"""
Syncs rule_mitre_unified -- a REAL table, refreshed explicitly (not
automatically) after anything changes rule_summary's MITRE data or
rule_yaml_representations.mitre_techniques_inferred.

CONFIRMED: reads confirmed mappings from mitre_mappings directly (the
real tactic/technique/technique_name triplets), NOT from
rule_summary's three separately-aggregated arrays -- those can have
mismatched lengths (real data: rule 393 had tactics enabled with zero
techniques under them), which would silently fabricate wrong pairings
if combined positionally.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine


def sync_rule_mitre_unified(engine: Engine) -> int:
    with engine.begin() as db:
        db.execute(text("TRUNCATE TABLE rule_mitre_unified"))
        result = db.execute(
            text(
                """
                INSERT INTO rule_mitre_unified (rule_id, customer_id, tactic, technique_id, technique_name, mitre_source, confidence)
                SELECT rule_id, customer_id, tactic, NULLIF(technique_id, ''), NULLIF(technique_name, ''), 'confirmed', NULL
                FROM mitre_mappings

                UNION ALL

                SELECT ryr.rule_id, ryr.customer_id, elem->>'tactic', elem->>'technique_id', elem->>'technique_name', 'derived', elem->>'confidence'
                FROM rule_yaml_representations ryr, jsonb_array_elements(ryr.mitre_techniques_inferred) AS elem
                WHERE ryr.mitre_techniques_inferred IS NOT NULL AND jsonb_array_length(ryr.mitre_techniques_inferred) > 0
                """
            )
        )
        return result.rowcount