"""MITRE catalog sync: every technique is kept with its status, revoked
techniques point at their replacement, tactic names come from MITRE's data,
and readers of the catalog only see active techniques."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.ai.agents.simulator.mitre_validator import MitreTechniqueValidator
from app.db.session import engine
from app.ingestion.jobs.mitre_catalog_sync import parse_attack_bundle, sync_mitre_catalog
from app.services.gap_analysis.mitre import MitreGapAnalyzer


def _ref(attack_id):
    return [{"source_name": "mitre-attack", "external_id": attack_id}]


def _tactic(stix_id, attack_id, name, shortname, **extra):
    return {
        "type": "x-mitre-tactic",
        "id": stix_id,
        "name": name,
        "x_mitre_shortname": shortname,
        "external_references": _ref(attack_id),
        **extra,
    }


def _technique(stix_id, attack_id, name, phases, **extra):
    return {
        "type": "attack-pattern",
        "id": stix_id,
        "name": name,
        "external_references": _ref(attack_id),
        "kill_chain_phases": [{"kill_chain_name": "mitre-attack", "phase_name": p} for p in phases],
        **extra,
    }


BUNDLE = {
    "objects": [
        _tactic("x-tac-1", "TA0005", "Stealth", "stealth"),
        _tactic("x-tac-2", "TA0112", "Defense Impairment", "defense-impairment"),
        _tactic("x-tac-old", "TA9999", "Old Tactic", "old-tactic", x_mitre_deprecated=True),
        _technique("ap-new", "T1685", "Disable or Modify Tools", ["defense-impairment"]),
        _technique(
            "ap-new-sub",
            "T1685.005",
            "Clear Windows Event Logs",
            ["defense-impairment"],
            x_mitre_is_subtechnique=True,
        ),
        _technique("ap-old", "T1562", "Impair Defenses", ["stealth"], revoked=True),
        _technique(
            "ap-old-sub",
            "T1070.001",
            "Clear Windows Event Logs",
            ["stealth"],
            revoked=True,
            x_mitre_is_subtechnique=True,
        ),
        _technique(
            "ap-retired", "T1099", "Retired Technique", ["stealth"], x_mitre_deprecated=True
        ),
        _technique("ap-orphan", "T1098", "Revoked Without Target", ["stealth"], revoked=True),
        {
            "type": "attack-pattern",
            "id": "ap-capec",
            "name": "Not ATT&CK",
            "external_references": [{"source_name": "capec"}],
        },
        {
            "type": "relationship",
            "relationship_type": "revoked-by",
            "source_ref": "ap-old",
            "target_ref": "ap-new",
        },
        {
            "type": "relationship",
            "relationship_type": "revoked-by",
            "source_ref": "ap-old-sub",
            "target_ref": "ap-new-sub",
        },
        {
            "type": "relationship",
            "relationship_type": "revoked-by",
            "source_ref": "ap-orphan",
            "target_ref": "not-a-technique",
        },
    ]
}


def test_parser_keeps_every_technique_with_status_and_replacement():
    tactics, techniques = parse_attack_bundle(BUNDLE)
    by_id = {t["technique_id"]: t for t in techniques}

    assert {t["tactic_id"] for t in tactics} == {"TA0005", "TA0112"}  # deprecated tactic skipped
    assert set(by_id) == {
        "T1685",
        "T1685.005",
        "T1562",
        "T1070.001",
        "T1099",
        "T1098",
    }  # non-ATT&CK skipped
    assert (by_id["T1562"]["status"], by_id["T1562"]["replaced_by_technique_id"]) == (
        "revoked",
        "T1685",
    )
    assert by_id["T1070.001"]["replaced_by_technique_id"] == "T1685.005"
    assert (by_id["T1099"]["status"], by_id["T1099"]["replaced_by_technique_id"]) == (
        "deprecated",
        None,
    )
    assert (
        by_id["T1098"]["replaced_by_technique_id"] is None
    )  # replacement isn't a published technique
    assert by_id["T1685"]["status"] == "active"


def test_parser_takes_tactic_names_from_mitre_and_sets_parents():
    _, techniques = parse_attack_bundle(BUNDLE)
    by_id = {t["technique_id"]: t for t in techniques}

    assert by_id["T1562"]["tactic_names"] == ["Stealth"]
    assert by_id["T1685"]["tactic_names"] == ["Defense Impairment"]
    assert (by_id["T1685.005"]["is_subtechnique"], by_id["T1685.005"]["parent_technique_id"]) == (
        True,
        "T1685",
    )
    assert by_id["T1685"]["parent_technique_id"] is None


@pytest.fixture
def synced_catalog():
    counts = sync_mitre_catalog(engine, BUNDLE)
    yield counts
    with engine.begin() as db:
        db.execute(text("TRUNCATE TABLE mitre_technique_catalog"))
        db.execute(text("DELETE FROM mitre_tactics"))


def test_sync_writes_tactics_statuses_and_replacements(synced_catalog):
    assert synced_catalog == {
        "tactics": 2,
        "active": 2,
        "deprecated": 1,
        "revoked": 3,
        "revoked_with_replacement": 2,
    }
    with engine.connect() as db:
        rows = dict(
            db.execute(
                text(
                    "SELECT technique_id, replaced_by_technique_id FROM mitre_technique_catalog WHERE status = 'revoked'"
                )
            ).fetchall()
        )
        tactics = dict(db.execute(text("SELECT tactic_id, name FROM mitre_tactics")).fetchall())
    assert rows == {"T1562": "T1685", "T1070.001": "T1685.005", "T1098": None}
    assert tactics == {"TA0005": "Stealth", "TA0112": "Defense Impairment"}


def test_catalog_readers_only_see_active_techniques(synced_catalog):
    with engine.connect() as db:
        validator = MitreTechniqueValidator(db)
        assert validator._lookup_by_id("T1685") is not None
        assert validator._lookup_by_id("T1562") is None  # revoked
        assert validator._lookup_by_id("T1099") is None  # deprecated
        catalog_ids = {
            t["technique_id"] for t in MitreGapAnalyzer(db, driver=None)._get_full_catalog()
        }
    assert catalog_ids == {"T1685", "T1685.005"}


def test_database_rejects_inconsistent_catalog_rows(synced_catalog):
    bad_rows = [
        "('T1700', 'x', false, NULL, 'retired', NULL)",  # unknown status
        "('T1701', 'x', false, NULL, 'active', 'T1685')",  # replacement on an active technique
        "('T17', 'x', false, NULL, 'active', NULL)",  # bad ID format
        "('T1702.001', 'x', true, NULL, 'active', NULL)",  # sub-technique without parent
        "('T1703', 'x', false, NULL, 'revoked', 'T9999')",  # replacement that doesn't exist
    ]
    for values in bad_rows:
        with pytest.raises(IntegrityError), engine.begin() as db:
            db.execute(
                text(
                    "INSERT INTO mitre_technique_catalog (technique_id, technique_name, is_subtechnique,"
                    f" parent_technique_id, status, replaced_by_technique_id) VALUES {values}"
                )
            )


def test_sync_refuses_an_empty_bundle():
    with pytest.raises(ValueError, match="refusing to empty the catalog"):
        sync_mitre_catalog(engine, {"objects": []})
