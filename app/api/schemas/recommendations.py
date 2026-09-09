"""Response/request schemas for the Sigma generation batch API."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SigmaGenerationRequest(BaseModel):
    rule_names: list[str] | None = Field(
        default=None,
        description="Specific rule names to generate for. Omit or leave null to generate for ALL canonical rules.",
        examples=[None],
    )


class SigmaGenerationJobCreateResponse(BaseModel):
    id: int
    status: str
    total_rules: int


class SigmaGenerationJobDetail(BaseModel):
    id: int
    customer_id: int
    status: str
    requested_rule_names: list[str] | None = None
    total_rules: int
    processed_rules: int
    failed_rules: int
    failed_rule_details: list[dict] | None = None
    error: str | None = None
    created_at: str
    finished_at: str | None = None