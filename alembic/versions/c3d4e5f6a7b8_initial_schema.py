"""add linked_rule_identifier to rule_summary

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-06 16:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_VIEW_SQL = """
CREATE VIEW rule_summary AS
SELECT
    r.id,
    r.customer_id,
    r.qradar_rule_id,
    r.identifier,
    r.linked_rule_identifier,
    r.name,
    r.object_type,
    r.building_block_subtype,
    r.type,
    r.enabled,
    r.owner,
    r.origin,
    r.created_at,
    r.updated_at,
    loc.last_event_at,
    loc.event_count       AS last_event_count,
    loc.offense_id         AS last_offense_id,
    COALESCE(mitre_agg.tactics, ARRAY[]::text[])        AS tactics,
    COALESCE(mitre_agg.techniques, ARRAY[]::text[])     AS techniques,
    COALESCE(mitre_agg.sub_techniques, ARRAY[]::text[]) AS sub_techniques
FROM rules r
LEFT JOIN LATERAL (
    SELECT last_event_at, event_count, offense_id
    FROM rule_offense_contributions
    WHERE rule_id = r.id
    ORDER BY last_event_at DESC NULLS LAST
    LIMIT 1
) loc ON true
LEFT JOIN LATERAL (
    SELECT
        array_agg(DISTINCT tactic) FILTER (WHERE tactic IS NOT NULL AND tactic != '') AS tactics,
        array_agg(DISTINCT split_part(technique_id, '.', 1))
            FILTER (WHERE technique_id IS NOT NULL AND technique_id != '') AS techniques,
        array_agg(DISTINCT technique_id)
            FILTER (WHERE technique_id LIKE '%.%') AS sub_techniques
    FROM mitre_mappings
    WHERE rule_id = r.id
) mitre_agg ON true
WHERE NOT EXISTS (
    SELECT 1 FROM validation_results val
    WHERE val.customer_id = r.customer_id
      AND val.entity_ref = r.qradar_rule_id::text
      AND val.entity_type = CASE WHEN r.object_type = 'BUILDING_BLOCK' THEN 'building_block' ELSE 'rule' END
      AND val.check_type = 'in_reference'
);
"""

PREVIOUS_VIEW_SQL = """
CREATE VIEW rule_summary AS
SELECT
    r.id,
    r.customer_id,
    r.qradar_rule_id,
    r.identifier,
    r.name,
    r.object_type,
    r.building_block_subtype,
    r.type,
    r.enabled,
    r.owner,
    r.origin,
    r.created_at,
    r.updated_at,
    loc.last_event_at,
    loc.event_count       AS last_event_count,
    loc.offense_id         AS last_offense_id,
    COALESCE(mitre_agg.tactics, ARRAY[]::text[])        AS tactics,
    COALESCE(mitre_agg.techniques, ARRAY[]::text[])     AS techniques,
    COALESCE(mitre_agg.sub_techniques, ARRAY[]::text[]) AS sub_techniques
FROM rules r
LEFT JOIN LATERAL (
    SELECT last_event_at, event_count, offense_id
    FROM rule_offense_contributions
    WHERE rule_id = r.id
    ORDER BY last_event_at DESC NULLS LAST
    LIMIT 1
) loc ON true
LEFT JOIN LATERAL (
    SELECT
        array_agg(DISTINCT tactic) FILTER (WHERE tactic IS NOT NULL AND tactic != '') AS tactics,
        array_agg(DISTINCT split_part(technique_id, '.', 1))
            FILTER (WHERE technique_id IS NOT NULL AND technique_id != '') AS techniques,
        array_agg(DISTINCT technique_id)
            FILTER (WHERE technique_id LIKE '%.%') AS sub_techniques
    FROM mitre_mappings
    WHERE rule_id = r.id
) mitre_agg ON true
WHERE NOT EXISTS (
    SELECT 1 FROM validation_results val
    WHERE val.customer_id = r.customer_id
      AND val.entity_ref = r.qradar_rule_id::text
      AND val.entity_type = CASE WHEN r.object_type = 'BUILDING_BLOCK' THEN 'building_block' ELSE 'rule' END
      AND val.check_type = 'in_reference'
);
"""


def upgrade() -> None:
    op.execute("DROP VIEW rule_summary")
    op.execute(NEW_VIEW_SQL)


def downgrade() -> None:
    op.execute("DROP VIEW rule_summary")
    op.execute(PREVIOUS_VIEW_SQL)