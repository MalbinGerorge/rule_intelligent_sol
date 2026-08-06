from fastapi import FastAPI

from app.api import rules as rules_router
from app.core.logging import configure_logging

configure_logging()

app = FastAPI(title="Rule Intelligent Sol")

app.include_router(rules_router.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}