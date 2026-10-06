"""Custom event property expressions: QRadar's "any" markers become NULL at
ingestion (Pydantic), the database rejects them (CHECK), and both readers
treat NULL as "applies to any"."""

import json
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.ai.agents.rule_analyzer.tools import check_field_extraction_configured
from app.ai.agents.simulator.dsm_property_extractor import DSMPropertyExtractor
from app.db.session import engine
from app.integrations.qradar.models import QRadarPropertyExpression

WINDOWS = 12  # QRadar log source type id for the test


def payload(**scope) -> dict:
    return {"identifier": "e1", "regex_property_identifier": "p1", **scope}


# --- Pydantic: validation at the QRadar boundary --------------------------------


def test_any_markers_become_none():
    expr = QRadarPropertyExpression.model_validate(
        payload(log_source_type_id=-1, log_source_id=-1, qid=0, low_level_category_id=-1)
    )
    assert (expr.log_source_type_id, expr.log_source_id, expr.qid, expr.low_level_category_id) == (
        None,
        None,
        None,
        None,
    )


def test_real_ids_are_kept():
    expr = QRadarPropertyExpression.model_validate(
        payload(log_source_type_id=12, log_source_id=62, qid=5000, low_level_category_id=3001)
    )
    assert (expr.log_source_type_id, expr.log_source_id, expr.qid, expr.low_level_category_id) == (
        12,
        62,
        5000,
        3001,
    )


def test_large_negative_type_id_is_kept_as_sent():
    assert (
        QRadarPropertyExpression.model_validate(
            payload(log_source_type_id=-2147483639)
        ).log_source_type_id
        == -2147483639
    )


def test_other_negative_ids_and_capture_groups_are_rejected():
    with pytest.raises(ValidationError, match="qid"):
        QRadarPropertyExpression.model_validate(payload(qid=-5))
    with pytest.raises(ValidationError, match="capture_group"):
        QRadarPropertyExpression.model_validate(payload(capture_group=-1))
    assert QRadarPropertyExpression.model_validate(payload(capture_group=0)).capture_group == 0


def test_missing_identifier_is_rejected():
    with pytest.raises(ValidationError, match="identifier"):
        QRadarPropertyExpression.model_validate({"regex_property_identifier": "p1"})


# --- Database fixtures --------------------------------------------------------------

EXPRESSIONS = [
    # (property_name, log_source_type_id, log_source_id)
    ("Logon Type", WINDOWS, None),  # this type, any log source
    ("Logon Type", None, None),  # any type, any log source
    ("Logon Type", 99, None),  # another type
    ('"Target Username"', None, None),  # AQL built-in field, stored quoted
    ("Workstation", WINDOWS, 500),  # this type, one specific log source
]


@pytest.fixture
def customer():
    with engine.begin() as db:
        customer_id = db.execute(
            text(
                "INSERT INTO customers (name, qradar_host, verify_ssl, active)"
                " VALUES (:n, 'qradar.test', true, true) RETURNING id"
            ),
            {"n": f"test-{uuid.uuid4().hex[:8]}"},
        ).scalar_one()
        rule_id = db.execute(
            text(
                "INSERT INTO rules (customer_id, qradar_rule_id, identifier)"
                " VALUES (:c, 100001, 'RULE-1') RETURNING id"
            ),
            {"c": customer_id},
        ).scalar_one()
        db.execute(
            text(
                "INSERT INTO rule_conditions (rule_id, sequence_order, test_class, negated, structured_data)"
                " VALUES (:r, 0, 'DeviceTypeID_Test', false, :sd)"
            ),
            {
                "r": rule_id,
                "sd": json.dumps({"device_type": {"log_source_names": ["Windows Security"]}}),
            },
        )
        for i, (name, type_id, source_id) in enumerate(EXPRESSIONS):
            db.execute(
                text(
                    "INSERT INTO custom_event_property_expressions (customer_id, property_qradar_identifier,"
                    " property_name, qradar_identifier, expression_type, enabled, log_source_type_id, log_source_id)"
                    " VALUES (:c, :p, :name, :q, 'regex', true, :t, :s)"
                ),
                {
                    "c": customer_id,
                    "p": f"p{i}",
                    "name": name,
                    "q": f"q{i}",
                    "t": type_id,
                    "s": source_id,
                },
            )
    yield customer_id
    with engine.begin() as db:
        db.execute(
            text("DELETE FROM custom_event_property_expressions WHERE customer_id = :c"),
            {"c": customer_id},
        )
        db.execute(
            text(
                "DELETE FROM rule_conditions WHERE rule_id IN (SELECT id FROM rules WHERE customer_id = :c)"
            ),
            {"c": customer_id},
        )
        db.execute(text("DELETE FROM rules WHERE customer_id = :c"), {"c": customer_id})
        db.execute(text("DELETE FROM customers WHERE id = :c"), {"c": customer_id})


# --- Database: the CHECK constraints -----------------------------------------------


@pytest.mark.parametrize(
    "column", ["log_source_id", "qid", "low_level_category_id", "log_source_type_id"]
)
def test_database_rejects_the_any_marker(customer, column):
    with pytest.raises(IntegrityError, match="ck_cepe_"), engine.begin() as db:
        db.execute(
            text(
                f"INSERT INTO custom_event_property_expressions (customer_id, property_qradar_identifier,"
                f" property_name, qradar_identifier, expression_type, {column})"
                f" VALUES (:c, 'p', 'x', 'q', 'regex', -1)"
            ),
            {"c": customer},
        )


# --- Readers: NULL means "applies to any" -------------------------------------------


def _names(rows: list[dict]) -> list[str]:
    return sorted(r["property_name"] for r in rows)


def test_simulator_selects_expressions_for_the_type_and_for_any(customer):
    with engine.connect() as db:
        extractor = DSMPropertyExtractor(db, customer)
        unknown_source = extractor._load_applicable_expressions(WINDOWS, None)
        specific_source = extractor._load_applicable_expressions(WINDOWS, 500)
        unknown_type = extractor._load_applicable_expressions(None, None)

    assert _names(unknown_source) == ['"Target Username"', "Logon Type", "Logon Type"]
    assert _names(specific_source) == [
        '"Target Username"',
        "Logon Type",
        "Logon Type",
        "Workstation",
    ]
    assert _names(unknown_type) == ['"Target Username"', "Logon Type"]


class FakeQRadar:
    def fetch_log_source_types(self):
        return [json.dumps([{"name": "Windows Security", "id": WINDOWS}])]


def test_rule_analyzer_tool_finds_configured_expressions(customer):
    with engine.connect() as db:
        logon = check_field_extraction_configured(
            db, FakeQRadar(), customer, "RULE-1", "Logon Type"
        )
        builtin = check_field_extraction_configured(
            db, FakeQRadar(), customer, "RULE-1", "Target Username"
        )
        missing = check_field_extraction_configured(db, FakeQRadar(), customer, "RULE-1", "Nope")

    assert logon.startswith('2 extraction expression(s) ARE configured for "Logon Type"')
    assert "scope=this specific type" in logon and "scope=all log source types" in logon
    assert builtin.startswith('1 extraction expression(s) ARE configured for "Target Username"')
    assert missing.startswith('No custom property named "Nope"')
