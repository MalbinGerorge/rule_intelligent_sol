"""
Safety layer for LLM-generated AQL, before it's ever sent to a live
QRadar console -- same two-layer defense-in-depth philosophy as
app/agent/cypher_safety.py, adapted for AQL's different risk profile.

Cypher's risk was DATA INTEGRITY (a write could corrupt/delete real
data). AQL's risk is different: Ariel search against event data has
no write capability at all (confirmed: QRadar's own search API only
accepts SELECT). The real risk here is RESOURCE CONSUMPTION on a
customer's LIVE PRODUCTION SIEM -- an unbounded or huge time-range
query can consume significant search resources while it runs,
potentially degrading the console's ability to do its actual job
(real-time threat detection) for the duration.

TWO layers, same principle as cypher_safety.py:
  1. Text-level pre-check (this module): fast, catches the common
     case immediately, before any QRadar round-trip.
  2. QRadar's own SELECT-only enforcement (confirmed via real API
     docs): the AUTHORITATIVE guarantee against write risk,
     independent of what this module catches.

TIME LIMIT IS PER LOG SOURCE TYPE, not one flat global cap -- a
firewall can generate orders of magnitude more events per second than
an internal Windows host, so the same time range represents wildly
different real resource cost depending on what's being searched.
The caller (the investigation tool, which already knows the log
source type it's investigating -- same DeviceTypeID_Test data used
throughout this project) passes that type in explicitly; this module
does NOT try to parse it out of the generated AQL text itself, since
reliably regex-matching a WHERE clause's log-source filter out of
free-form LLM-generated text would be fragile. Explicit, known input
from the caller is more robust than inferring intent from text.
"""
from __future__ import annotations

import re

# Ordered list: FIRST matching category wins. Keywords matched
# case-insensitively as substrings within the real log source type
# name (e.g. "Fortinet FortiGate Security Gateway" matches "fortigate").
_TIME_LIMIT_CATEGORIES: list[tuple[list[str], float]] = [
    (["firewall", "fortigate", "cisco asa", "palo alto"], 1.0),
    (["windows"], 2.0),
    (["linux", "unix"], 5.0),
]

_UNMATCHED_TYPE_MAX_DAYS = 1.0  # a real log source type was given, but matched no category above
_NO_TYPE_MAX_DAYS = 0.5  # 12 hours -- no log source type known/relevant at all (most conservative)


def _resolve_max_days(log_source_type: str | None) -> float:
    """Returns the max allowed days-back for this specific query,
    based on which log source type (if any) it targets."""
    if log_source_type is None:
        return _NO_TYPE_MAX_DAYS

    type_lower = log_source_type.lower()
    for keywords, max_days in _TIME_LIMIT_CATEGORIES:
        if any(kw in type_lower for kw in keywords):
            return max_days

    return _UNMATCHED_TYPE_MAX_DAYS


_SELECT_PATTERN = re.compile(r"^\s*SELECT\b", re.IGNORECASE)

# "LAST 7 DAYS", "LAST 24 HOURS", "LAST 30 MINUTES", "LAST 2 WEEKS",
# "LAST 6 MONTHS" -- singular/plural, case-insensitive. WEEK/MONTH
# included deliberately even though they'll almost always exceed any
# category's cap -- so a query using them gets a clear "exceeds the
# limit" message, not a misleading "no time range found" one.
_LAST_N_PATTERN = re.compile(
    r"\bLAST\s+(\d+)\s+(SECOND|SECONDS|MINUTE|MINUTES|HOUR|HOURS|DAY|DAYS|WEEK|WEEKS|MONTH|MONTHS)\b",
    re.IGNORECASE,
)

# Standalone "OR" keyword, not matched inside ORDER/ORDINAL/etc. -- \b
# word boundaries mean this correctly does NOT trigger on "ORDER BY"
# (confirmed via test: ORDER is one token, no boundary between OR and
# DER within it).
_OR_OPERATOR_PATTERN = re.compile(r"\bOR\b", re.IGNORECASE)

_UNIT_TO_DAYS = {
    "second": 1 / 86400, "seconds": 1 / 86400,
    "minute": 1 / 1440, "minutes": 1 / 1440,
    "hour": 1 / 24, "hours": 1 / 24,
    "day": 1, "days": 1,
    "week": 7, "weeks": 7,
    "month": 30, "months": 30,  # approximate -- fine, always exceeds every category's cap anyway
}

# Absolute START/STOP ranges are NOT currently supported -- deferred
# rather than built with fragile ad-hoc date parsing. Our own
# generation prompt should only ever produce the relative "LAST N
# <unit>" form; a query using START/STOP is rejected outright for now.
_START_STOP_PATTERN = re.compile(r"\bSTART\s+['\"]", re.IGNORECASE)


class UnsafeAQLError(Exception):
    """Raised when a generated AQL query fails the safety pre-check."""


def check_select_only(query: str) -> None:
    if not _SELECT_PATTERN.match(query):
        raise UnsafeAQLError(
            "Query must start with SELECT. Only read-only searches are permitted."
        )


def check_time_bound(query: str, log_source_type: str | None = None) -> None:
    """Requires an explicit, bounded relative time range, capped
    according to the log source type this query targets (see
    _resolve_max_days). A query with NO time bound at all would
    actually be SAFE by QRadar's own default (60 seconds) -- but also
    nearly useless for real investigation, so we require one
    explicitly rather than silently accepting a near-empty search."""
    if _START_STOP_PATTERN.search(query):
        raise UnsafeAQLError(
            "Absolute START/STOP time ranges are not supported yet -- use a relative "
            "'LAST N DAYS/HOURS/MINUTES' clause instead."
        )

    match = _LAST_N_PATTERN.search(query)
    if not match:
        raise UnsafeAQLError(
            "Query must include an explicit time range, e.g. 'LAST 7 DAYS' -- "
            "queries without one are rejected rather than silently defaulting to "
            "QRadar's own 60-second window, which would make the search misleadingly empty."
        )

    count = int(match.group(1))
    unit = match.group(2).lower()
    days_requested = count * _UNIT_TO_DAYS[unit]
    max_days = _resolve_max_days(log_source_type)

    if days_requested > max_days:
        type_label = f"'{log_source_type}'" if log_source_type else "unspecified log source type"
        raise UnsafeAQLError(
            f"Time range too large for {type_label}: 'LAST {count} {unit}' is approximately "
            f"{days_requested:.2f} days, exceeding the {max_days}-day maximum for this category. "
            "This limit exists to protect the live QRadar console from resource-intensive searches."
        )


def check_log_source_scoping(query: str) -> None:
    """Requires the query to filter by log source TYPE --
    LOGSOURCETYPENAME(devicetype) = '...' or a raw devicetype
    comparison. Confirmed necessary per real operator guidance: an
    unscoped search across the WHOLE console's event volume is exactly
    the "resource intensive query" risk this safety layer exists to
    prevent, independent of the time-range cap.

    TYPE-level only, NOT instance-level (LOGSOURCENAME) -- deliberately
    simplified: the LLM only ever has a log source TYPE name available
    (from the rule chain), never an individual log source instance
    name, so instance-level scoping was never something it could
    reliably fill in correctly."""
    scoping_patterns = (
        r"LOGSOURCETYPENAME\s*\(",
        r"\bdevicetype\b",
    )
    if not any(re.search(p, query, re.IGNORECASE) for p in scoping_patterns):
        raise UnsafeAQLError(
            "Query must filter by log source type, e.g. "
            "LOGSOURCETYPENAME(devicetype) = 'exact log source type name'. "
            "An unscoped search across the entire console's event volume is exactly "
            "the resource-intensive query pattern this system exists to prevent."
        )


def check_no_or_operator(query: str) -> None:
    """Rejects queries using OR to combine multiple conditions.
    CONFIRMED preference, explicitly requested: run separate,
    sequential queries -- one per specific hypothesis/condition --
    rather than one OR'd query trying to check several things at once.
    Keeps each search focused and its result unambiguous (a count from
    "A OR B" doesn't tell you whether A occurred, B occurred, or both),
    consistent with the existing "one decisive question per search"
    guidance in the AQL rules. Real QRadar consoles may also simply
    not support OR reliably in AQL -- an earlier real 422 syntax
    rejection may have been caused by this, not (only) the quoting
    issue also fixed separately."""
    if _OR_OPERATOR_PATTERN.search(query):
        raise UnsafeAQLError(
            "Query must not use OR to combine multiple conditions. Run separate, "
            "sequential searches instead -- one focused query per specific hypothesis "
            "(e.g. check Event ID 4740 in one search, QID 5000910 in a separate search), "
            "not one query trying to check multiple things at once."
        )


def validate_aql(query: str, log_source_type: str | None = None) -> str:
    """Runs all text-level checks. Raises UnsafeAQLError on any
    failure. Returns the query unchanged if it passes -- unlike
    Cypher's validate_and_prepare(), there's no LIMIT to inject here;
    AQL result size is naturally bounded by the time range check above,
    and callers should also cap rows fetched from the results endpoint
    directly (a separate, execution-layer concern)."""
    check_select_only(query)
    check_time_bound(query, log_source_type)
    check_log_source_scoping(query)
    check_no_or_operator(query)
    return query