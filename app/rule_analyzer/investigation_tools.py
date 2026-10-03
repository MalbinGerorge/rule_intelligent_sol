"""
Genuine ReAct tools for the Rule Analyzer's investigation loop -- the
LLM decides whether/when to call these, unlike chain_analysis.py's
static context (scope, response data, enabled status), which is
ALWAYS shown regardless of judgment. These tools cover things NOT
already visible in that static chain text.

Most are pure Postgres queries. check_log_source_status,
check_reference_set_contents, and run_aql_event_search are LIVE
QRadar API tools -- everything else is structural-only, per the
agreed sequencing.
"""
from __future__ import annotations

import json as _json
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.qradar_client import QRadarAPIError, QRadarClient
from app.rule_analyzer.aql_safety import UnsafeAQLError, validate_aql
from app.rule_analyzer.rule_chain_context import resolve_identifier_to_rule_id
from app.rule_analyzer.aql_safety import UnsafeAQLError, validate_aql, _resolve_max_days


def _format_time_ago(dt: datetime | None) -> str:
    """Human-readable delta, not a raw timestamp -- deliberate:
    forcing the LLM to do its own date arithmetic against an ISO
    timestamp is error-prone. Computing the delta ourselves means the
    model reasons from a stated fact ("3 hours ago"), not a
    calculation it might get wrong."""
    if dt is None:
        return "unknown"
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    seconds = delta.total_seconds()
    if seconds < 3600:
        return f"{int(seconds // 60)} minute(s) ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} hour(s) ago"
    return f"{int(seconds // 86400)} day(s) ago"


def check_rule_timing(db: Session, customer_id: int, identifier: str) -> str:
    """Reports how long ago a rule/BB was created and last modified.
    Takes the IDENTIFIER string shown in the rule chain (e.g.
    "SYSTEM-1300" or the root rule's own identifier), NOT an internal
    numeric ID -- CONFIRMED NECESSARY from a real failure: earlier
    versions took an internal rule_id the LLM had no way to see
    anywhere in its context, causing every call to fail with a
    guessed/wrong value. The identifier is what's actually visible in
    the chain text, so that's what the tool now accepts, resolving it
    to the internal ID itself.

    A recent modification (hours ago) well after original creation is
    a strong, concrete signal worth investigating -- recent edits are
    a common, easily-overlooked cause of a rule that "used to work"."""
    rule_id = resolve_identifier_to_rule_id(db, customer_id, identifier)
    if rule_id is None:
        return f"No rule/building block found with identifier '{identifier}' for this customer."

    row = db.execute(
        text("SELECT name, created_at, updated_at FROM rules WHERE id = :rule_id"),
        {"rule_id": rule_id},
    ).mappings().first()
    if row is None:
        return f"No rule found with internal id {rule_id}."

    created_ago = _format_time_ago(row["created_at"])
    updated_ago = _format_time_ago(row["updated_at"])
    return f'"{row["name"]}" (identifier: {identifier}): created {created_ago}, last modified {updated_ago}.'


def get_shared_dependents(db: Session, customer_id: int, bb_identifier: str) -> str:
    """Which OTHER rules also depend on this same building block --
    informs risk: a BB relied on by 40 rules is a very different thing
    to touch than one relied on by just this single rule. Not visible
    in the static chain text, since that only shows THIS rule's own
    dependency tree, not who else shares it."""
    rows = db.execute(
        text(
            """
            SELECT DISTINCT r.name, r.identifier
            FROM rule_building_blocks rbb
            JOIN rules r ON r.id = rbb.rule_id
            WHERE rbb.bb_id = :bb_id AND r.customer_id = :customer_id
            ORDER BY r.name
            """
        ),
        {"bb_id": bb_identifier, "customer_id": customer_id},
    ).fetchall()

    if not rows:
        return f"No rules found referencing building block '{bb_identifier}' (it may not exist, or nothing currently depends on it)."

    names = [f"  - {r[0]} ({r[1]})" for r in rows]
    return f"{len(rows)} rule(s) depend on building block '{bb_identifier}':\n" + "\n".join(names)


def check_reference_data_dependencies(db: Session, customer_id: int, identifier: str) -> str:
    """Lists any ReferenceSet/ReferenceMap this rule's/BB's OWN
    conditions depend on. Takes the IDENTIFIER string shown in the
    rule chain (e.g. "SYSTEM-1300" or the root rule's own identifier),
    NOT an internal numeric ID -- see check_rule_timing's docstring
    for why. Does not recurse into referenced BBs -- call again with a
    nested BB's own identifier if it also needs checking.

    STRUCTURAL ONLY -- reports WHICH sets/maps are depended on, not
    their live contents. For reference SET contents (existence, real
    entry count, a sample of real values), use
    check_reference_set_contents instead, which queries QRadar live --
    per the agreed design, reference set data is genuinely dynamic
    operational data, so it is deliberately NEVER cached in Postgres."""
    rule_id = resolve_identifier_to_rule_id(db, customer_id, identifier)
    if rule_id is None:
        return f"No rule/building block found with identifier '{identifier}' for this customer."

    rows = db.execute(
        text(
            """
            SELECT test_class, structured_data
            FROM rule_conditions
            WHERE rule_id = :rule_id AND test_class IN ('ReferenceSetTest', 'ReferenceDataTest')
            """
        ),
        {"rule_id": rule_id},
    ).mappings().all()

    if not rows:
        return f"'{identifier}' has no reference set/map dependencies in its own conditions."

    lines = []
    for r in rows:
        sd = r["structured_data"] if isinstance(r["structured_data"], dict) else {}
        if r["test_class"] == "ReferenceSetTest":
            names = sd.get("refset", {}).get("refset_names", [])
            lines.extend(f'  - Reference SET: "{n}"' for n in names)
        else:
            names = sd.get("refmap", {}).get("map_names", [])
            lines.extend(f'  - Reference MAP: "{n}"' for n in names)

    disclaimer = (
        "\nIMPORTANT: this system cannot verify the LIVE CONTENTS of these reference "
        "sets/maps from this tool alone -- only that the rule depends on them. For SET "
        "contents (existence, real entry count, sample values), call check_reference_set_live "
        "with this same identifier. Reference MAP contents are not yet covered by any tool "
        "and cannot be verified."
    )
    return "This rule depends on the following reference data:\n" + "\n".join(lines) + disclaimer


def check_log_source_status(db: Session, qradar_client: QRadarClient, customer_id: int, identifier: str) -> str:
    """
    Checks whether the log source TYPE this rule's/BB's OWN conditions
    require (from a DeviceTypeID_Test condition) has any actual
    configured log sources, and their real live status. Takes the
    IDENTIFIER string shown in the rule chain (e.g. "SYSTEM-1300" or
    the root rule's own identifier), NOT an internal numeric ID -- see
    check_rule_timing's docstring for why.

    STATISTICAL, bucket-based design -- confirmed better than an
    earlier "top N stalest" version for the same scale problem (a
    large environment can have hundreds of log sources of one type).
    A histogram of "time since last event" stays compact regardless of
    whether there are 5 or 5,000 log sources, unlike any fixed-size
    "top N" list. Buckets:
      - Enabled vs disabled -- always an exact count.
      - Disabled ones are still individually NAMED (capped only if
        the disabled count itself is huge) -- small, always directly
        actionable ("go re-enable this specific device").
      - Enabled ones are bucketed by time since last event: under 1
        week, 1-2 weeks, 2-3 weeks, over 3 weeks, never received an
        event. Each bucket always reports an exact COUNT; individual
        names are only listed within a bucket if that bucket is small
        enough (<= NAME_THRESHOLD) to be genuinely actionable -- the
        healthy "under 1 week" bucket is never named individually,
        since it could legitimately contain hundreds/thousands.

    Does not recurse into referenced building blocks -- call again
    with a nested BB's own identifier if its own DeviceTypeID_Test
    condition also needs checking.
    """
    MAX_DETAILED_DISABLED = 20
    NAME_THRESHOLD = 10  # a bucket only gets individual names if it has this many or fewer entries

    rule_id = resolve_identifier_to_rule_id(db, customer_id, identifier)
    if rule_id is None:
        return f"No rule/building block found with identifier '{identifier}' for this customer."

    rows = db.execute(
        text(
            """
            SELECT structured_data FROM rule_conditions
            WHERE rule_id = :rule_id AND test_class = 'DeviceTypeID_Test'
            """
        ),
        {"rule_id": rule_id},
    ).mappings().all()

    required_type_names: list[str] = []
    for r in rows:
        sd = r["structured_data"] if isinstance(r["structured_data"], dict) else {}
        required_type_names += sd.get("device_type", {}).get("log_source_names", [])

    if not required_type_names:
        return (
            f"'{identifier}' doesn't specify a required log source type in its own "
            "conditions -- nothing to check here (it may rely entirely on a referenced "
            "building block's log source requirement instead, or on a specific device "
            "via DeviceID_Test rather than a type)."
        )

    try:
        type_pages = qradar_client.fetch_log_source_types()
    except QRadarAPIError as e:
        return f"Could not reach QRadar to resolve the log source type: {e}"

    all_types = []
    for page in type_pages:
        all_types.extend(_json.loads(page))

    name_to_id = {t["name"]: t["id"] for t in all_types}
    matched_ids = {name_to_id[n] for n in required_type_names if n in name_to_id}

    if not matched_ids:
        return (
            f"Required log source type name(s) {required_type_names} were not found in "
            "QRadar's LIVE log source type list -- the type may have been renamed or removed."
        )

    try:
        ls_pages = qradar_client.fetch_log_sources()
    except QRadarAPIError as e:
        return f"Could not reach QRadar to check log source status: {e}"

    all_log_sources = []
    for page in ls_pages:
        all_log_sources.extend(_json.loads(page))

    matching = [ls for ls in all_log_sources if ls.get("type_id") in matched_ids]

    if not matching:
        return (
            f"No configured log sources exist AT ALL for type(s) {required_type_names} -- "
            "this data source may never have been onboarded in QRadar."
        )

    disabled_ones = [ls for ls in matching if not ls.get("enabled")]
    enabled_ones = [ls for ls in matching if ls.get("enabled")]

    lines = [
        f"{len(matching)} log source(s) total for type(s) {required_type_names}: "
        f"{len(enabled_ones)} enabled, {len(disabled_ones)} disabled."
    ]

    if disabled_ones:
        lines.append("\nDISABLED log source(s):")
        shown = disabled_ones[:MAX_DETAILED_DISABLED]
        for ls in shown:
            lines.append(f'  - "{ls.get("name")}" (status: {(ls.get("status") or {}).get("status")})')
        if len(disabled_ones) > MAX_DETAILED_DISABLED:
            lines.append(f"  ... and {len(disabled_ones) - MAX_DETAILED_DISABLED} more disabled, not shown.")

    if not enabled_ones:
        return "\n".join(lines)

    now = datetime.now(timezone.utc)
    buckets: dict[str, list[dict]] = {
        "under_1w": [], "1_to_2w": [], "2_to_3w": [], "over_3w": [], "never": [],
    }
    for ls in enabled_ones:
        last_event_ms = ls.get("last_event_time")
        if not last_event_ms:
            buckets["never"].append(ls)
            continue
        last_event_dt = datetime.fromtimestamp(last_event_ms / 1000, tz=timezone.utc)
        age_days = (now - last_event_dt).days
        if age_days < 7:
            buckets["under_1w"].append(ls)
        elif age_days < 14:
            buckets["1_to_2w"].append(ls)
        elif age_days < 21:
            buckets["2_to_3w"].append(ls)
        else:
            buckets["over_3w"].append(ls)

    bucket_labels = {
        "under_1w": "received an event within the last week",
        "1_to_2w": "last event was 1-2 weeks ago",
        "2_to_3w": "last event was 2-3 weeks ago",
        "over_3w": "last event was more than 3 weeks ago",
        "never": "NEVER received any event",
    }

    lines.append("\nENABLED log source(s), grouped by time since last event:")
    for key, label in bucket_labels.items():
        group = buckets[key]
        lines.append(f"  - {label}: {len(group)}")
        if group and len(group) <= NAME_THRESHOLD and key != "under_1w":
            for ls in group:
                lines.append(f'      "{ls.get("name")}"')

    lines.append(
        "\nNOTE: an analyst-entered 'description' field may exist on individual log sources "
        "but is NOT reliably kept up to date -- treat it as a possible hint if you fetch it "
        "separately, never as confirmed fact. Base conclusions on 'enabled' and 'last event' instead."
    )
    return "\n".join(lines)



def _normalize_refset_display_name(display_name: str) -> str:
    """QRadar's rule display TEXT wraps the real stored reference set
    name in UI decoration that isn't part of the actual name: a
    "(Shared|Private|Tenant) " prefix (from the set's namespace field)
    and a " - AlphaNumeric[ (Ignore Case)]" suffix (from the set's
    entry_type field). CONFIRMED bug fix from real data: an exact-match
    lookup against the live console's real names ALWAYS failed because
    of this decoration, even for sets that genuinely exist and are
    populated (confirmed: 7 real sets, 9-20 entries each, all matched
    "NOT FOUND" before this fix). Only ALN/ALNIC suffix wording is
    confirmed from real data so far -- NUM/IP/PORT/CIDR/DATE entry
    types may use different suffix text, not yet confirmed."""
    name = display_name.strip()

    for prefix in ("(Shared) ", "(Private) ", "(Tenant) "):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break

    # Longer/more specific suffix checked FIRST -- "AlphaNumeric" is a
    # literal prefix of "AlphaNumeric (Ignore Case)", so checking the
    # short one first would incorrectly strip only part of the longer one.
    for suffix in (" - AlphaNumeric (Ignore Case)", " - AlphaNumeric"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break

    return name.strip()


def check_reference_set_contents(db: Session, qradar_client: QRadarClient, customer_id: int, identifier: str) -> str:
    """
    Checks the LIVE, real contents of the reference set(s) that a
    specific rule/building block's own conditions depend on. Takes the
    IDENTIFIER string shown in the rule chain, NOT an internal ID --
    same reasoning as every other tool here.

    This CLOSES a real, previously-honest limitation: check_reference_data_dependencies
    could only say "this rule depends on set X, but contents cannot be
    verified." This tool actually verifies them, live, via the real
    reference_data_collections API (confirmed against a live customer
    console).

    For each dependent set, reports:
      - Whether it exists at all (a renamed/deleted set is a direct cause).
      - Its real entry count (0 entries directly explains a rule that
        never matches -- confirms or rules out the "empty set" hypothesis).
      - A CAPPED sample of real values (not the full set -- a set can
        have thousands of entries; the sample exists specifically so
        the LLM can visually compare VALUE FORMAT against what the
        rule's condition actually checks, e.g. "DOMAIN\\username" vs
        plain "username" -- exactly the kind of format-mismatch
        hypothesis worth confirming or ruling out with real examples,
        not a full dump).

    Does not check reference MAPS (a separate QRadar API surface not
    yet confirmed) or nested building blocks -- call again with a
    nested BB's own identifier if it also needs checking.
    """
    MAX_SAMPLE_VALUES = 10

    rule_id = resolve_identifier_to_rule_id(db, customer_id, identifier)
    if rule_id is None:
        return f"No rule/building block found with identifier '{identifier}' for this customer."

    rows = db.execute(
        text(
            """
            SELECT structured_data FROM rule_conditions
            WHERE rule_id = :rule_id AND test_class = 'ReferenceSetTest'
            """
        ),
        {"rule_id": rule_id},
    ).mappings().all()

    required_set_names: list[str] = []
    for r in rows:
        sd = r["structured_data"] if isinstance(r["structured_data"], dict) else {}
        required_set_names += sd.get("refset", {}).get("refset_names", [])

    if not required_set_names:
        return (
            f"'{identifier}' has no ReferenceSetTest dependency in its own conditions "
            "-- nothing to check here (it may depend on a reference MAP instead, which "
            "this tool doesn't cover, or on nothing at all)."
        )

    try:
        set_pages = qradar_client.fetch_reference_sets()
    except QRadarAPIError as e:
        return f"Could not reach QRadar to look up reference sets: {e}"

    all_sets = []
    for page in set_pages:
        all_sets.extend(_json.loads(page))

    name_to_set = {s["name"]: s for s in all_sets}
    normalized_to_original = {_normalize_refset_display_name(n): n for n in required_set_names}
    missing = [orig for norm, orig in normalized_to_original.items() if norm not in name_to_set]
    found = {orig: name_to_set[norm] for norm, orig in normalized_to_original.items() if norm in name_to_set}

    lines = []
    if missing:
        lines.append(f"NOT FOUND on the live console (renamed or deleted?): {missing}")

    if not found:
        return "\n".join(lines) if lines else "None of the required reference sets could be resolved."

    try:
        entry_pages = qradar_client.fetch_reference_set_entries()
    except QRadarAPIError as e:
        lines.append(f"Could not fetch entries to sample values: {e}")
        for name, meta in found.items():
            lines.append(f'  - "{name}": exists, {meta.get("number_of_entries")} entries (sample unavailable)')
        return "\n".join(lines)

    all_entries = []
    for page in entry_pages:
        all_entries.extend(_json.loads(page))

    for name, meta in found.items():
        collection_id = meta.get("id")
        count = meta.get("number_of_entries", 0)
        lines.append(f'\n"{name}" (live): {count} entries')

        if count == 0:
            lines.append("  *** EMPTY *** -- this set currently has NO entries, which would mean")
            lines.append("  any condition checking membership in it can NEVER match.")
            continue

        matching_entries = [e for e in all_entries if e.get("collection_id") == collection_id]
        sample = matching_entries[:MAX_SAMPLE_VALUES]
        if sample:
            lines.append(f"  Sample of real value(s) (showing {len(sample)} of {count}):")
            for e in sample:
                lines.append(f'    - "{e.get("value")}"')

    return "\n".join(lines)


def run_aql_event_search(
    qradar_client: QRadarClient, aql_query: str, log_source_type: str | None
) -> str:
    """
    Executes a LIVE AQL search against QRadar's Ariel event database.

    aql_query is written by the INVESTIGATING LLM ITSELF, not
    constructed by this function -- per the agreed design, AQL
    generation uses GPT-5.2's own knowledge (grounded by the
    system prompt's syntax rules and few-shot examples), not rigid
    Python-built templates. This function's job is purely to VALIDATE
    (via aql_safety.py) and EXECUTE (via the async Ariel search
    lifecycle) whatever query the LLM wrote -- never to write one.

    log_source_type should be the exact log source type name the
    query targets (visible in the rule chain), so aql_safety.py can
    apply the correct resource-safety time-range cap for that
    category. Pass None if the query isn't scoped to one specific type.

    Errors (safety rejection OR a live QRadar failure) are returned as
    a clear, actionable STRING, not raised as an exception -- this
    lets the investigating LLM see exactly what went wrong on its next
    turn and self-correct (e.g. shorten the time range), using the
    ReAct loop's existing natural retry behavior rather than needing a
    separate validator node.

    NOTE: results shape (results.get("events") vs "results") is not
    confirmed against a real QRadar response yet -- tried defensively.
    """
    try:
        safe_query = validate_aql(aql_query, log_source_type)
    except UnsafeAQLError as e:
        return f"Query rejected before execution: {e}"

    try:
        results = qradar_client.run_ariel_search(safe_query)
    except QRadarAPIError as e:
        return f"Search failed: {e}"

    events = results.get("events") or results.get("results") or []
    MAX_EVENTS_SHOWN = 20

    if not events:
        return f"Query executed successfully but returned NO matching events.\nQuery used: {safe_query}"

    lines = [f"{len(events)} matching event(s) found.", f"Query used: {safe_query}", ""]
    for event in events[:MAX_EVENTS_SHOWN]:
        lines.append(f"  {event}")
    if len(events) > MAX_EVENTS_SHOWN:
        lines.append(f"  ... and {len(events) - MAX_EVENTS_SHOWN} more, not shown.")
    return "\n".join(lines)


def check_field_extraction_configured(
    db: Session, qradar_client: QRadarClient, customer_id: int, identifier: str, field_name: str
) -> str:
    """
    STRUCTURAL FIRST CHECK -- is ANY extraction expression even
    configured for this custom property, on the log source type this
    rule requires? Involves one small LIVE call (resolving the log
    source TYPE NAME to QRadar's internal numeric ID, reusing the same
    lookup check_log_source_status already makes) -- NOT a full AQL
    search, so this stays cheap and should be checked BEFORE spending
    AQL search budget on check_field_population_rate.

    If NO extraction expression exists at all, that alone is a
    confirmed structural explanation -- no live event data is needed
    to prove the field is always empty; parsing was simply never set
    up for it here.
    """
    rule_id = resolve_identifier_to_rule_id(db, customer_id, identifier)
    if rule_id is None:
        return f"No rule/building block found with identifier '{identifier}' for this customer."

    rows = db.execute(
        text(
            """
            SELECT structured_data FROM rule_conditions
            WHERE rule_id = :rule_id AND test_class = 'DeviceTypeID_Test'
            """
        ),
        {"rule_id": rule_id},
    ).mappings().all()
    required_type_names: list[str] = []
    for r in rows:
        sd = r["structured_data"] if isinstance(r["structured_data"], dict) else {}
        required_type_names += sd.get("device_type", {}).get("log_source_names", [])

    if not required_type_names:
        return (
            f"'{identifier}' doesn't specify a required log source type -- cannot resolve "
            "which type's extraction config to check."
        )

    try:
        type_pages = qradar_client.fetch_log_source_types()
    except QRadarAPIError as e:
        return f"Could not reach QRadar to resolve the log source type: {e}"

    all_types = []
    for page in type_pages:
        all_types.extend(_json.loads(page))
    name_to_id = {t["name"]: t["id"] for t in all_types}
    matched_ids = {name_to_id[n] for n in required_type_names if n in name_to_id}

    if not matched_ids:
        return f"Required log source type name(s) {required_type_names} not found in QRadar's live type list."

    prop_row = db.execute(
        text("SELECT id FROM custom_event_properties WHERE customer_id = :customer_id AND name = :name"),
        {"customer_id": customer_id, "name": field_name},
    ).mappings().first()

    if prop_row is None:
        return (
            f'No custom property named "{field_name}" found in the synced property list for this '
            "customer -- either it doesn't exist, or the property sync hasn't run/hasn't captured it. "
            "This alone would explain the field always being empty."
        )

    expr_rows = db.execute(
        text(
            "SELECT expression_type, enabled, log_source_type_id "
            "FROM custom_event_property_expressions WHERE property_id = :property_id"
        ),
        {"property_id": prop_row["id"]},
    ).mappings().all()

    applicable = [e for e in expr_rows if e["log_source_type_id"] is None or e["log_source_type_id"] in matched_ids]

    if not applicable:
        other_count = len(expr_rows)
        extra = (
            f" ({other_count} expression(s) exist for OTHER log source types, but none for {required_type_names})"
            if other_count else ""
        )
        return (
            f'NO extraction expression is configured for "{field_name}" on log source type(s) '
            f"{required_type_names}{extra}. This is a direct, structural explanation for why this "
            "field is always empty on these events -- parsing was simply never set up for it here."
        )

    lines = [
        f'{len(applicable)} extraction expression(s) ARE configured for "{field_name}" '
        f"on log source type(s) {required_type_names}:"
    ]
    for e in applicable:
        status = "enabled" if e["enabled"] else "DISABLED"
        scope = "all log source types" if e["log_source_type_id"] is None else "this specific type"
        lines.append(f"  - type={e['expression_type']}, status={status}, scope={scope}")
    lines.append(
        "\nExtraction IS configured, so an empty field is more likely a LIVE parsing/matching issue "
        "(e.g. the raw event payload doesn't match the configured regex/path) rather than missing "
        "configuration. Consider check_field_population_rate to confirm with real event data."
    )
    return "\n".join(lines)


def check_field_population_rate(qradar_client: QRadarClient, field_name: str, qid: int, log_source_type: str) -> str:
    """
    DETERMINISTIC (NOT LLM-authored) live check: for the SPECIFIC QID
    this rule requires, is `field_name` actually populated on real
    recent events, or mostly/always NULL? Unlike run_aql_search
    (flexible, LLM-written queries for open-ended investigation), this
    is ONE well-defined, repeatable metric with an EXACT query WE
    construct ourselves -- more reliable than trusting the LLM to
    freshly write an equivalent ad-hoc query every time. Reuses ONLY
    confirmed-working AQL syntax (a plain GROUP BY on the field), the
    same pattern already proven live against real Verdict/Delivery
    Action/Policy Action data -- deliberately avoids unconfirmed
    syntax like CASE WHEN, never tested against a real console.
    """
    max_days = _resolve_max_days(log_source_type)
    hours = int(min(12, max_days * 24))

    query = (
        f'SELECT "{field_name}" AS \'Value\', COUNT(*) AS \'Count\' '
        f"FROM events "
        f"WHERE LOGSOURCETYPENAME(devicetype) = '{log_source_type}' AND QID={qid} "
        f'GROUP BY "{field_name}" '
        f"ORDER BY 'Count' DESC "
        f"LIMIT 50 "
        f"LAST {hours} HOURS"
    )

    try:
        safe_query = validate_aql(query, log_source_type)
    except UnsafeAQLError as e:
        return f"Internal query construction error (should not happen -- please report): {e}"

    try:
        results = qradar_client.run_ariel_search(safe_query)
    except QRadarAPIError as e:
        return f"Search failed: {e}"

    events = results.get("events") or results.get("results") or []
    if not events:
        return f"No events found for QID={qid} in the last {hours} hours -- cannot assess field population."

    total = sum(row.get("Count", 0) for row in events)
    null_count = sum(row.get("Count", 0) for row in events if row.get("Value") is None)
    populated_count = total - null_count

    lines = [f'Field "{field_name}" population, for QID={qid}, last {hours} hours ({int(total)} total events):']
    lines.append(f"  - Populated: {int(populated_count)} ({populated_count/total*100:.0f}%)")
    lines.append(f"  - Empty/NULL: {int(null_count)} ({null_count/total*100:.0f}%)")

    if null_count == total:
        lines.append("\n  *** ALWAYS EMPTY *** -- this field is NEVER populated on real events for this QID.")
        lines.append("  This directly explains any rule condition checking this field: it can never match.")
    elif null_count > 0:
        lines.append(f"\n  Partially populated -- {int(null_count)} of {int(total)} events lack this field, which")
        lines.append("  could still cause a rule to miss some matching events.")

    lines.append("\nDistinct real values observed:")
    for row in events[:10]:
        val = row.get("Value")
        val_display = "(NULL/empty)" if val is None else f'"{val}"'
        lines.append(f'  - {val_display}: {int(row.get("Count", 0))} event(s)')

    return "\n".join(lines)