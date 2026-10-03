"""
Pydantic response schemas for the graph API (UI2).

Condition/threshold shapes are genuinely variable across the ~60 test
classes (see rule_condition_parser.py) — using dict[str, Any] here
instead of forcing every possible field onto one rigid schema, same
flexible-JSON philosophy already used for rule_conditions.structured_data
on the Postgres side.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class RuleGraphDetail(BaseModel):
    rule: dict[str, Any]
    references: list[dict[str, Any]]
    conditions: list[dict[str, Any]]
    log_sources: list[str]
    mitre: list[dict[str, Any]]
    followed_by: list[dict[str, Any]]


class BuildingBlockDependent(BaseModel):
    rule_id: int
    identifier: str | None
    name: str | None
    threshold: dict[str, Any]


class FieldSearchResult(BaseModel):
    rule_id: int
    identifier: str | None
    name: str | None
    operator: str | None
    values: list[str] | None


class TechniqueSearchResult(BaseModel):
    rule_id: int
    identifier: str | None
    name: str | None