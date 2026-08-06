"""TODO: FastAPI router exposing rules data to the Svelte frontend.

Left as a placeholder until the ingestion services (subtask 2) exist —
no point wiring routes to empty tables.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/rules", tags=["rules"])