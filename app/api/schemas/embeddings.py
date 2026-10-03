"""Schemas for the embedding-generation job API -- mirrors the Sigma
generation job schemas exactly."""
from __future__ import annotations

from pydantic import BaseModel


class EmbeddingJobCreateResponse(BaseModel):
    id: int
    status: str
    total_representations: int


class EmbeddingJobDetail(BaseModel):
    id: int
    status: str
    total_representations: int
    processed_representations: int
    failed_representations: int
    failed_details: list[dict] | None = None
    error: str | None = None
    created_at: str
    finished_at: str | None = None


class SimilaritySearchRequest(BaseModel):
    query: str