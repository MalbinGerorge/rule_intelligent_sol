"""Aggregates every endpoint module's router into one. main.py imports
only from here — it never reaches into app/api/endpoint/* directly, so
adding a new resource (offenses, mitre, etc.) means touching this file
and the new endpoint module, not main.py."""
from fastapi import APIRouter

from app.api.endpoint import rules, graph

api_router = APIRouter()
api_router.include_router(rules.router)
api_router.include_router(graph.router)