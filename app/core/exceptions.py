"""
Typed, structured API exceptions -- adapted from a reference pattern,
scoped to what THIS project actually needs.

Base APIError carries everything needed for a consistent RFC 9457
problem+json response. Concrete subclasses below replace the raw
HTTPException(status_code=404, detail=...) calls currently scattered
across recommendations.py / customers.py with a real, typed vocabulary
-- so a caller catching NotFoundError doesn't need to know or guess
which status code that implies.

Deliberately NOT included (unlike the reference this was adapted
from): a StaleVersionError / optimistic-locking exception -- this
project has no version-column concurrency control anywhere yet. Add
it only if that's genuinely introduced later, not speculatively now.
"""
from __future__ import annotations

from fastapi import status


class APIError(Exception):
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"
    title: str = "Internal server error"
    headers: dict[str, str] | None = None

    def __init__(self, detail: str, *, headers: dict[str, str] | None = None):
        self.detail = detail
        if headers is not None:
            self.headers = headers
        super().__init__(detail)

    def to_response(self) -> dict:
        return {
            "type": "about:blank",
            "title": self.title,
            "status": self.status_code,
            "detail": self.detail,
            "code": self.code,
        }


class NotFoundError(APIError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    title = "Not found"


class BadRequestError(APIError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "bad_request"
    title = "Bad request"


class ConflictError(APIError):
    """Reserved for explicit application-level conflicts you detect
    and raise yourself. A genuine DB-level UNIQUE violation (e.g. the
    rule_yaml_representations (rule_id, customer_id, role) constraint)
    is caught separately by integrity_handler in
    exception_handlers.py, so most callers won't need to raise this
    directly -- it's here for cases where YOUR code notices a
    conflict before the database would."""
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    title = "Conflict"