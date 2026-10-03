"""Response schemas for the Rule Analyzer's async investigation API."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class InvestigationCreateResponse(BaseModel):
    id: int
    status: str


class InvestigationDetail(BaseModel):
    id: int
    rule_id: int
    customer_id: int
    status: str
    error: str | None = None
    chain_analysis: dict | None = None
    final_report: dict | None = None
    rendered_report: str | None = None
    trace: str | None = None
    tool_calls_made: int | None = None
    created_at: datetime


class InvestigationListItem(BaseModel):
    id: int
    status: str
    tool_calls_made: int | None = None
    created_at: datetime


class InvestigationListResponse(BaseModel):
    items: list[InvestigationListItem]
    total: int
    limit: int
    offset: int