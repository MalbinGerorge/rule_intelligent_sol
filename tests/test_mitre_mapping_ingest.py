"""MITRE coverage ingestion: both QRadar payload shapes, and re-ingestion of
tactic-only rows (technique NULL) without duplicates."""

import uuid

import pytest
from sqlalchemy import text

from app.db.session import engine
from app.ingestion.jobs.mitre_mapping_ingest import parse_mitre_coverage, upsert_mitre_mappings


def coverage(mapping: dict) -> dict:
    return {"Some rule": {"mapping": mapping}}


def test_tactic_keyed_by_id():
    rows = parse_mitre_coverage(
        coverage(
            {
                "TA0002": {
                    "name": "Execution",
                    "techniques": {"PowerShell": {"id": "T1059.001"}},
                }
            }
        )
    )
    assert rows == [
        {
            "tactic_id": "TA0002",
            "tactic": "Execution",
            "technique_id": "T1059.001",
            "technique_name": "PowerShell",
        }
    ]


def test_tactic_keyed_by_name_uses_the_id_from_the_payload():
    rows = parse_mitre_coverage(
        coverage(
            {
                "Execution": {
                    "id": "TA0002",
                    "techniques": {"PowerShell": {"id": "T1059.001"}},
                }
            }
        )
    )
    assert rows == [
        {
            "tactic_id": "TA0002",
            "tactic": "Execution",
            "technique_id": "T1059.001",
            "technique_name": "PowerShell",
        }
    ]


def test_tactic_without_techniques_has_null_technique():
    rows = parse_mitre_coverage(
        coverage({"TA0006": {"name": "Credential Access", "techniques": {}}})
    )
    assert rows == [
        {
            "tactic_id": "TA0006",
            "tactic": "Credential Access",
            "technique_id": None,
            "technique_name": None,
        }
    ]


def test_tactic_without_a_valid_id_is_skipped():
    assert parse_mitre_coverage(coverage({"Execution": {"techniques": {}}})) == []


@pytest.fixture
def rule():
    with engine.begin() as db:
        customer_id = db.execute(
            text(
                "INSERT INTO customers (name, qradar_host, verify_ssl, active)"
                " VALUES (:n, 'qradar.test', true, true) RETURNING id"
            ),
            {"n": f"test-{uuid.uuid4().hex[:8]}"},
        ).scalar_one()
        db.execute(
            text(
                "INSERT INTO rules (customer_id, qradar_rule_id, identifier)"
                " VALUES (:c, 100001, 'SYSTEM-1')"
            ),
            {"c": customer_id},
        )
    yield customer_id
    with engine.begin() as db:
        db.execute(text("DELETE FROM mitre_mappings WHERE customer_id = :c"), {"c": customer_id})
        db.execute(text("DELETE FROM rules WHERE customer_id = :c"), {"c": customer_id})
        db.execute(text("DELETE FROM customers WHERE id = :c"), {"c": customer_id})


def test_reingesting_tactic_only_rows_creates_no_duplicates(rule):
    """technique_id is NULL for tactic-only rows; the unique constraint is
    NULLS NOT DISTINCT, so the ON CONFLICT upsert must update, not insert."""
    customer_id = rule
    payload = [
        {
            "identifier": "SYSTEM-1",
            "mitre_coverage": coverage(
                {
                    "TA0006": {"name": "Credential Access", "techniques": {}},
                    "Execution": {
                        "id": "TA0002",
                        "techniques": {"PowerShell": {"id": "T1059.001"}},
                    },
                }
            ),
        }
    ]

    for _ in range(2):
        with engine.begin() as db:
            upsert_mitre_mappings(db, customer_id, payload)

    with engine.connect() as db:
        rows = db.execute(
            text(
                "SELECT tactic_id, tactic, technique_id FROM mitre_mappings"
                " WHERE customer_id = :c ORDER BY tactic_id"
            ),
            {"c": customer_id},
        ).fetchall()
    assert [tuple(r) for r in rows] == [
        ("TA0002", "Execution", "T1059.001"),
        ("TA0006", "Credential Access", None),
    ]
