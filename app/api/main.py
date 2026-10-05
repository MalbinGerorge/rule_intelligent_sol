from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.exception_handlers import register_exception_handlers
from app.api.v1.router import api_router
from app.core.logging import configure_logging, configure_simulator_logging

configure_logging(log_level="INFO")  # json_logs=True for real deployment
configure_simulator_logging(log_level="INFO")

app = FastAPI(title="Rule Intelligent Sol")
register_exception_handlers(app)

# Dev-friendly CORS: SvelteKit's dev server runs on a different port
# (localhost:5173) than this API (localhost:8000). Tighten this to a
# real allowlist before deploying anywhere non-local.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
