"""Pydantic response schemas for the rules API — mirrors rule_summary."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RuleSummary(BaseModel):
    """One row from the rule_summary view. from_attributes lets this be
    built directly from a SQLAlchemy Row/mapping without manual field-by-field
    construction."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    qradar_rule_id: int
    identifier: str | None
    name: str | None
    object_type: str
    building_block_subtype: str | None
    type: str | None
    enabled: bool | None
    owner: str | None
    origin: str | None
    created_at: datetime | None
    updated_at: datetime | None
    last_event_at: datetime | None
    last_event_count: int | None
    last_offense_id: str | None
    tactics: list[str]
    techniques: list[str]
    sub_techniques: list[str]


class RuleListResponse(BaseModel):
    count: int
    results: list[RuleSummary]


class RuleHealthMetrics(BaseModel):
    total_rules: int
    total_building_blocks: int
    enabled_rules: int
    disabled_rules: int
    enabled_triggered: int
    enabled_not_triggered: int