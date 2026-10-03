"""
Centralized exception handling for the FastAPI app -- adapted from a
reference pattern, trimmed to what THIS project actually needs.
Converts every error path into a consistent RFC 9457 problem+json
response, and logs unhandled/integrity failures with structured
context (trace_id, path, method) so real failures are debuggable from
logs, not just a generic message the caller sees.

Deliberately OMITTED vs. the reference this was adapted from:
  - StaleDataError / optimistic locking -- no version-column
    concurrency control exists anywhere in this project yet.
  - RBAC/auth-specific error shaping -- no auth layer exists yet,
    deliberately deferred (see project notes) -- 401/403 mappings are
    kept in the table below for when that's eventually added, but
    nothing currently raises them.
"""
from __future__ import annotations

import uuid

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import APIError

logger = structlog.get_logger(__name__)

PROBLEM_JSON = "application/problem+json"

_LOCATION_SEGMENTS = {"body", "query", "path", "header", "cookie"}
_VALUE_ERROR_PREFIX = "Value error, "


def _problem(status_code: int, code: str, title: str, detail: str, errors=None) -> JSONResponse:
    """Build a standard RFC 9457 problem+json response."""
    body = {
        "type": "about:blank",
        "title": title,
        "status": status_code,
        "detail": detail,
        "code": code,
    }
    if errors:
        body["errors"] = errors
    return JSONResponse(status_code=status_code, content=body, media_type=PROBLEM_JSON)


def format_validation_errors(raw_errors: list[dict]) -> list[dict[str, str]]:
    """Normalise Pydantic errors into the API's {field?, detail} shape."""
    items: list[dict[str, str]] = []
    for err in raw_errors:
        loc = [str(p) for p in err["loc"] if p not in _LOCATION_SEGMENTS]
        msg = err["msg"]
        if msg.startswith(_VALUE_ERROR_PREFIX):
            msg = msg[len(_VALUE_ERROR_PREFIX):]
        item: dict[str, str] = {}
        if loc:
            item["field"] = ".".join(loc)
        item["detail"] = msg
        items.append(item)
    return items


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_response(),
        media_type=PROBLEM_JSON,
        headers=exc.headers,
    )


async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _problem(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "validation_error",
        "Validation error",
        "Field validation failed",
        format_validation_errors(exc.errors()),
    )


async def integrity_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    """Catches real DB-level UNIQUE/FK violations -- e.g. the
    rule_yaml_representations (rule_id, customer_id, role) constraint
    -- and returns a clean 409 instead of leaking a raw psycopg2
    traceback to the caller."""
    logger.warning("unhandled_integrity_error", path=request.url.path, error=str(exc.orig))
    return _problem(
        status.HTTP_409_CONFLICT,
        "conflict",
        "Conflict",
        "The request conflicts with the current state of the resource.",
    )


_HTTP_ERROR_CODES: dict[int, tuple[str, str]] = {
    400: ("bad_request", "Bad request"),
    401: ("unauthorized", "Unauthorized"),  # dormant -- no auth layer raises this yet
    403: ("forbidden", "Forbidden"),  # dormant -- no auth layer raises this yet
    404: ("not_found", "Not found"),
    405: ("method_not_allowed", "Method not allowed"),
}


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Converts framework-native HTTPExceptions (e.g. the raw
    HTTPException(404, ...) calls already in recommendations.py/
    customers.py) into the same problem+json envelope, so callers see
    one consistent error shape regardless of which path raised it."""
    mapping = _HTTP_ERROR_CODES.get(exc.status_code)
    if mapping is None:
        return await unhandled_handler(request, exc)
    code, title = mapping
    return _problem(exc.status_code, code, title, str(exc.detail))


async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all -- guarantees NOTHING ever leaks a raw Python
    traceback to a caller. A trace_id is logged AND returned in the
    response, so a user reporting 'I got error <trace_id>' can be
    matched directly to the real, full server-side log entry."""
    trace_id = str(uuid.uuid4())
    logger.exception(
        "unhandled_exception",
        trace_id=trace_id,
        path=request.url.path,
        method=request.method,
    )
    body = {
        "type": "about:blank",
        "title": "Internal server error",
        "status": 500,
        "detail": "An unexpected error occurred.",
        "code": "internal_error",
        "traceId": trace_id,
    }
    return JSONResponse(status_code=500, content=body, media_type=PROBLEM_JSON)


def register_exception_handlers(app: FastAPI) -> None:
    """Call ONCE, right after creating the FastAPI() app instance in
    app/main.py."""
    app.add_exception_handler(APIError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_handler)
    app.add_exception_handler(IntegrityError, integrity_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_handler)