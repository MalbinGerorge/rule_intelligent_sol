"""
MITRE Technique Validator -- DETERMINISTIC, not an LLM call. Confirms
the Attack Interpreter's guessed technique against the REAL,
authoritative catalog already synced from MITRE's own data
(mitre_technique_catalog -- see scripts/sync_mitre_catalog.py).

Two-tier match, exact first:
  1. Exact technique_id lookup, if the LLM provided one.
  2. Fuzzy name match, if no id or the id didn't exist in the catalog.
No match at all is an HONEST outcome -- mitre_confirmed=False -- not
an error, and not silently filled with a guess.
"""
from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agent.simulator.schemas import AttackStep

logger = structlog.get_logger(__name__)


class MitreTechniqueValidator:
    def __init__(self, db: Session):
        self.db = db

    def validate(self, step: AttackStep) -> AttackStep:
        if step.technique_id:
            exact = self._lookup_by_id(step.technique_id)
            if exact is not None:
                return self._apply_match(step, exact, confirmed=True)

        fuzzy = self._lookup_by_name(step.technique_name)
        if fuzzy is not None:
            return self._apply_match(step, fuzzy, confirmed=True)

        logger.warning(
            "mitre_technique_not_confirmed",
            step_number=step.step_number,
            guessed_technique_id=step.technique_id,
            guessed_technique_name=step.technique_name,
        )
        step.mitre_confirmed = False
        return step

    def _lookup_by_id(self, technique_id: str) -> dict | None:
        row = self.db.execute(
            text("SELECT technique_id, technique_name FROM mitre_technique_catalog WHERE technique_id = :id"),
            {"id": technique_id},
        ).mappings().first()
        return dict(row) if row else None

    def _lookup_by_name(self, technique_name: str) -> dict | None:
        """Fuzzy fallback -- Postgres trigram similarity via pg_trgm.
        Requires: CREATE EXTENSION IF NOT EXISTS pg_trgm;"""
        row = self.db.execute(
            text(
                """
                SELECT technique_id, technique_name,
                       similarity(technique_name, :name) AS sim
                FROM mitre_technique_catalog
                WHERE similarity(technique_name, :name) > 0.3
                ORDER BY sim DESC
                LIMIT 1
                """
            ),
            {"name": technique_name},
        ).mappings().first()
        return dict(row) if row else None

    def _apply_match(self, step: AttackStep, match: dict, confirmed: bool) -> AttackStep:
        step.mitre_confirmed = confirmed
        step.confirmed_technique_id = match["technique_id"]
        step.confirmed_technique_name = match["technique_name"]
        logger.info(
            "mitre_technique_confirmed",
            step_number=step.step_number,
            guessed_technique_name=step.technique_name,
            confirmed_technique_id=match["technique_id"],
            confirmed_technique_name=match["technique_name"],
        )
        return step