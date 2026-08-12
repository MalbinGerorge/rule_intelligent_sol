"""
Ingests rules_with_data, rules (reference), and building_blocks into
Postgres. All three use the same upsert pattern: ON CONFLICT on the
(customer_id, qradar_rule_id) unique constraint, so re-running ingestion
updates existing rows instead of creating duplicates.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

# "BB:HostDefinition: Servers" -> "HostDefinition"
_BB_SUBTYPE_RE = re.compile(r"^BB:([^:]+):")


def _epoch_ms_to_dt(value) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


def _bb_subtype(name: str | None) -> str | None:
    if not name:
        return None
    m = _BB_SUBTYPE_RE.match(name)
    return m.group(1) if m else None


def upsert_rules(session: Session, customer_id: int, pages: list[str]) -> int:
    """Ingest rules_with_data pages into `rules`. Returns rows upserted."""
    count = 0
    for page in pages:
        records = json.loads(page)
        for r in records:
            is_bb = bool(r.get("is_building_block"))
            name = r.get("name")
            session.execute(
                text(
                    """
                    INSERT INTO rules (
                        customer_id, qradar_rule_id, identifier, name, type, owner, origin,
                        object_type, building_block_subtype, enabled, linked_rule_identifier,
                        created_at, updated_at, raw_json, needs_reparse
                    ) VALUES (
                        :customer_id, :qradar_rule_id, :identifier, :name, :type, :owner, :origin,
                        :object_type, :building_block_subtype, :enabled, :linked_rule_identifier,
                        :created_at, :updated_at, :raw_json, true
                    )
                    ON CONFLICT (customer_id, qradar_rule_id) DO UPDATE SET
                        identifier = EXCLUDED.identifier,
                        name = EXCLUDED.name,
                        type = EXCLUDED.type,
                        owner = EXCLUDED.owner,
                        origin = EXCLUDED.origin,
                        object_type = EXCLUDED.object_type,
                        building_block_subtype = EXCLUDED.building_block_subtype,
                        enabled = EXCLUDED.enabled,
                        linked_rule_identifier = EXCLUDED.linked_rule_identifier,
                        created_at = EXCLUDED.created_at,
                        updated_at = EXCLUDED.updated_at,
                        raw_json = EXCLUDED.raw_json,
                        synced_at = now(),
                        -- Decision made ONCE, here, at ingest time: did the incoming
                        -- modification_date move forward past what we had stored?
                        -- Both sides are QRadar's own updated_at — never our wall clock.
                        -- If unchanged, preserve whatever needs_reparse currently is
                        -- (don't clobber a still-pending flag back to false).
                        needs_reparse = CASE
                            WHEN rules.updated_at < EXCLUDED.updated_at THEN true
                            ELSE rules.needs_reparse
                        END
                    """
                ),
                {
                    "customer_id": customer_id,
                    "qradar_rule_id": r["id"],
                    "identifier": r.get("identifier"),
                    "name": name,
                    "type": r.get("type"),
                    "owner": r.get("owner"),
                    "origin": r.get("origin"),
                    "object_type": "BUILDING_BLOCK" if is_bb else "RULE",
                    "building_block_subtype": _bb_subtype(name) if is_bb else None,
                    "enabled": r.get("enabled"),
                    "linked_rule_identifier": r.get("linked_rule_identifier"),
                    "created_at": _epoch_ms_to_dt(r.get("creation_date")),
                    "updated_at": _epoch_ms_to_dt(r.get("modification_date")),
                    "raw_json": json.dumps(r),
                },
            )
            count += 1
    return count


def upsert_rules_reference(session: Session, customer_id: int, pages: list[str]) -> int:
    """Ingest /analytics/rules (ground truth) into `rules_reference`."""
    count = 0
    for page in pages:
        records = json.loads(page)
        for r in records:
            session.execute(
                text(
                    """
                    INSERT INTO rules_reference (customer_id, qradar_rule_id, identifier, name, raw_json)
                    VALUES (:customer_id, :qradar_rule_id, :identifier, :name, :raw_json)
                    ON CONFLICT (customer_id, qradar_rule_id) DO UPDATE SET
                        identifier = EXCLUDED.identifier,
                        name = EXCLUDED.name,
                        raw_json = EXCLUDED.raw_json,
                        synced_at = now()
                    """
                ),
                {
                    "customer_id": customer_id,
                    "qradar_rule_id": r["id"],
                    "identifier": r.get("identifier"),
                    "name": r.get("name"),
                    "raw_json": json.dumps(r),
                },
            )
            count += 1
    return count


def upsert_building_blocks_reference(session: Session, customer_id: int, pages: list[str]) -> int:
    """Ingest /analytics/building_blocks (ground truth) into building_blocks_reference."""
    count = 0
    for page in pages:
        records = json.loads(page)
        for r in records:
            session.execute(
                text(
                    """
                    INSERT INTO building_blocks_reference (customer_id, qradar_rule_id, identifier, name, raw_json)
                    VALUES (:customer_id, :qradar_rule_id, :identifier, :name, :raw_json)
                    ON CONFLICT (customer_id, qradar_rule_id) DO UPDATE SET
                        identifier = EXCLUDED.identifier,
                        name = EXCLUDED.name,
                        raw_json = EXCLUDED.raw_json,
                        synced_at = now()
                    """
                ),
                {
                    "customer_id": customer_id,
                    "qradar_rule_id": r["id"],
                    "identifier": r.get("identifier"),
                    "name": r.get("name"),
                    "raw_json": json.dumps(r),
                },
            )
            count += 1
    return count