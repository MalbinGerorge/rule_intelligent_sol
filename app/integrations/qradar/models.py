"""Validated models for QRadar API payloads.

QRadar responses are validated and normalized here, at the boundary, before
any ingestion job writes them: a malformed payload fails with a message
naming the field, instead of reaching the database.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

# QRadar uses these as "not restricted / applies to any" in scope fields.
# We store NULL for "any", so the database can enforce real IDs (> 0).
_ANY_SENTINELS = {-1, 0}


class QRadarPropertyExpression(BaseModel):
    """One custom event property expression, from any of QRadar's
    /config/event_sources/custom_properties/*_property_*_expressions
    endpoints (regex, json, xml, cef, leef, nvp, aql)."""

    model_config = ConfigDict(extra="ignore")

    identifier: str
    regex_property_identifier: str
    enabled: bool | None = None

    # Scope: which log source type / log source / QID / category the
    # expression applies to. None = any (QRadar sends -1, or 0 for qid and
    # low_level_category_id on AQL expressions).
    log_source_type_id: int | None = None
    log_source_id: int | None = None
    qid: int | None = None
    low_level_category_id: int | None = None

    # Type-specific fields (which ones are set depends on the endpoint).
    expression: str | None = None
    regex: str | None = None
    capture_group: int | None = Field(default=None, ge=0)  # 0 = the whole match
    format_string: str | None = None
    delimiter_pair: str | None = None
    delimiter_name_value: str | None = None

    @field_validator("log_source_id", "qid", "low_level_category_id", mode="after")
    @classmethod
    def _any_is_none(cls, value: int | None) -> int | None:
        if value in _ANY_SENTINELS:
            return None
        if value is not None and value < 0:
            raise ValueError(f"expected a positive ID or -1 (any), got {value}")
        return value

    @field_validator("log_source_type_id", mode="after")
    @classmethod
    def _any_type_is_none(cls, value: int | None) -> int | None:
        # Large negative type IDs (around -2147483639) occur on a few AQL
        # expressions; their meaning is unknown, so they are kept as sent.
        return None if value in _ANY_SENTINELS else value
