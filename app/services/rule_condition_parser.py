"""
General-purpose condition extractor — deterministic, no LLM. Covers the
majority of QRadar's 60 test classes with ONE algorithm, confirmed
against real Cotecna data (see project notes for the reconnaissance
trail: analyze_test_types.py -> sample_text_by_class.py -> targeted
multiselect checks).

CONFIRMED rules this algorithm relies on:
  - Negation is a plain attribute on <test>: negate="true" — not a
    different structure, not a different test class.
  - A parameter's userOptions has an <option id="code">Label</option>
    table when source="xml" — decode by looking THAT table up, never a
    hardcoded master list. Self-contained per parameter, every time.
  - Multiselect values in userSelection are comma-delimited, with
    inconsistent spacing ("l2l, l2r" vs "192.168.2.7,192.168.2.154") —
    split on "," and strip() each piece to handle both.
  - Parameters without an <option> table (source="user" etc.) are
    literal values (ports, IPs, free text) — same comma-split applies.

Special-cased below (not the generic algorithm) because each has its
own confirmed parameter layout or text-extraction quirk:
  - ArielFilterTest, ThresholdFunction_Test, TriggerTimeout,
    SequenceFunction_Test, DoubleSequenceFunction_Test,
    CauseAndEffect_Test, TriggerMatchCount, AQL_Test, DeviceTypeID_Test,
    DeviceID_Test, EventCategory_Test, QID_Test, ReferenceSetTest,
    ReferenceDataTest, RuleMatch_Test -- see each extractor's own
    docstring for details.

NOT handled here (separate pipeline):
  - Full BB/rule reference structural extraction (creating the actual
    REFERENCES graph edge) -> owned by
    rule_xml_parser.extract_bb_references into rule_building_blocks.
    RuleMatch_Test IS still parsed here too, but only lightly (which
    BB(s) it names, for display/sequence purposes) -- see
    extract_rule_match_condition. The two code paths are independent
    and don't duplicate each other's actual job.

ALL 60 confirmed real-data test classes are now covered, either via
this general algorithm or one of the 15 special-cased extractors above.
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET

# Historically held test classes whose BB/rule references are handled
# by rule_xml_parser.extract_bb_references — kept as an empty set now
# (not deleted) for backward compat / clarity. RuleMatch_Test moved
# OUT (see extract_rule_match_condition) so its sequence_order is
# preserved for chain-reconstruction purposes -- rule_building_blocks
# population is a SEPARATE code path (rule_xml_parser.extract_bb_references),
# entirely unaffected by this change.
_BB_REFERENCE_TEST_CLASSES: set[str] = set()

# Ariel filter operator codes, decoded from comparing real <text> against
# real <userSelection> (e.g. "CONALL" = "contains all of"). Extend this
# table as more codes are confirmed from real data.
# Confirmed from real data: QRadar only wraps values in [...] when
# there are MULTIPLE values joined by "or" — a single value has no
# brackets at all ("Command (custom) contains any of excel.exe" vs.
# "...contains any of [http:// or https://]"). The alternation below
# matches both: bracketed values in group 3, unbracketed single value
# in group 4 — whichever the input actually has.
_ARIEL_OPERATOR_TEXT = re.compile(
    r"^\s*(?:when the event matches\s+)?(.+?)\s*\(custom\)\s+(contains all of|contains any of|is any of|is none of)\s+(?:\[(.+)\]|(.+))\s*$"
)

_TIME_UNIT_NAMES = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}

# AQL_Test-specific: confirmed from 5 real samples. Unlike other classes,
# userSelection here is URL-encoded (and even double-serialized, with a
# trailing "|[...]" artifact) — but <text> is already clean and fully
# decoded, confirmed byte-for-byte identical to the manually URL-decoded
# userSelection. So we extract from raw_text, not userSelection, avoiding
# needing to touch the messy encoded field at all. Deliberately NOT
# building a full AQL expression parser (regex MATCHES, ilike wildcards,
# REFERENCEMAPSETCONTAINS, boolean AND/OR/parens) — only 8 occurrences
# total across the real dataset; the query is stored as one string.
_AQL_TEXT_PATTERN = re.compile(r"^when the (event|flow) matches\s+(.+?)\s+AQL filter query$", re.DOTALL)

# DeviceTypeID_Test-specific: confirmed from 5 real samples. userOptions
# uses method="getDeviceTypeDescs" (dynamic, no local <option> table) —
# BUT <text> already contains the resolved log source name(s), same
# trick as ArielFilterTest/AQL_Test. No external reference-table lookup
# needed for THIS purpose (log source names on rules that already use
# them) — log_source_types_reference (built separately) still useful
# for the full catalog + custom/internal metadata, but not required just
# to fix numeric-code display.
_DEVICE_TYPE_TEXT_PATTERN = re.compile(r"^when the event\(s\) were detected by one or more of\s+(.+)$")

# DeviceID_Test-specific: confirmed from 5 real samples (same pattern as
# DeviceTypeID_Test — userOptions uses method="getDevices" source="class",
# dynamic/no local <option> table, but <text> already has resolved device
# names, including multi-value cases with 17 comma-separated names in one
# real sample). Same regex as DeviceTypeID_Test — same sentence template,
# different underlying test class.
_DEVICE_ID_TEXT_PATTERN = _DEVICE_TYPE_TEXT_PATTERN

# EventCategory_Test-specific: confirmed from real samples seen earlier
# in this project (e.g. "when the event category for the event is one
# of the following Authentication.Admin Login Successful, ..."). Same
# "text already resolved" pattern as DeviceTypeID_Test/DeviceID_Test —
# param values are bare numeric codes, but <text> has real names,
# rendered as "HighLevel.LowLevel" pairs joined by ", ".
_EVENT_CATEGORY_TEXT_PATTERN = re.compile(
    r"^when the event category for the event is one of the following\s+(.+)$"
)

# QID_Test-specific: confirmed from 5 real samples. Same "text already
# resolved" pattern as every other numeric-code test class — <text>
# renders "(QID_NUMBER) Event Name" pairs, comma-separated for
# multiselect. No external QRadar API call or reference table needed.
_QID_TEXT_PATTERN = re.compile(r"^when the event QID is one of the following\s+(.+)$")
_QID_ENTRY_PATTERN = re.compile(r"^\((\d+)\)\s*(.+)$")

# TriggerMatchCount correlation field: appears in the sentence in TWO
# different positions depending on which real sample — "...with the
# same {field} in N minutes after..." OR "...match with the same
# {field}" at the very end. Confirmed from real data (Office 365 sample
# uses the first position, Fortigate/Authentication samples use the
# second). Matches whichever comes first: stop at " in <digit" or end
# of string.
_TRIGGER_MATCH_CORRELATION_PATTERN = re.compile(
    r"with the same\s+(.+?)(?:\s+in\s+\d|\s*$)"
)

# ReferenceSetTest-specific: confirmed from 5 real samples. Same "text
# already resolved" pattern — <text> shows real reference set names,
# raw userSelection is just numeric IDs. Structural identity only
# (which rule depends on which set, via which field) — deliberately
# NOT the set's live contents (see project notes: contents are
# genuinely dynamic operational data, resolved live via QRadar API
# on-demand for UI3/UI4, never cached here).
_REFSET_TEXT_PATTERN = re.compile(
    r"^when (any|all) of (.+?) are contained in (any|all) of\s+(.+)$"
)

# ReferenceDataTest-specific: confirmed from 2 real samples, both the
# MAP shape (key + value). Map-of-Sets and Table shapes NOT yet
# confirmed from real data — this pattern will correctly return None
# for those rather than guess, same defensive convention as everywhere
# else in this file.
_REFMAP_TEXT_PATTERN = re.compile(
    r"^when (any|all) of (.+?) is the key and (any|all) of (.+?) is the value in (any|all) of\s+(.+)$"
)

_BB_ID_LIKE_PATTERN = re.compile(
    r"^(SYSTEM-\d+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
    re.IGNORECASE,
)

def _test_short_name(test_el: ET.Element) -> str:
    return test_el.get("name", "UNKNOWN").rsplit(".", 1)[-1]


def _decode_parameter(param_el: ET.Element) -> list[str] | None:
    """Returns the decoded list of values for one <parameter>, or None
    if there's nothing to decode (no userSelection)."""
    user_selection = param_el.find("userSelection")
    if user_selection is None or not user_selection.text:
        return None

    raw_values = [v.strip() for v in user_selection.text.split(",") if v.strip()]

    user_options = param_el.find("userOptions")
    option_table: dict[str, str] = {}
    if user_options is not None:
        for opt in user_options.findall("option"):
            opt_id = opt.get("id")
            if opt_id is not None and opt.text:
                option_table[opt_id] = opt.text

    if option_table:
        return [option_table.get(v, v) for v in raw_values]
    return raw_values


def extract_ariel_condition(test_el: ET.Element) -> dict | None:
    """ArielFilterTest-specific: parses the friendlier <text> field
    instead of userSelection's compound encoding. Reuses extract_raw_text
    (not its own duplicate tag-stripping logic) specifically so it also
    gets the html.unescape() double-encoding fix — confirmed necessary
    from real data (see extract_raw_text's docstring)."""
    raw = extract_raw_text(test_el)
    if not raw:
        return None

    m = _ARIEL_OPERATOR_TEXT.match(raw)
    if not m:
        return None

    field, operator, bracketed_values, single_value = m.groups()
    values_str = bracketed_values if bracketed_values is not None else single_value
    values = [v.strip() for v in values_str.split(" or ")]
    return {"field": field.strip(), "operator": operator, "values": values}


def extract_threshold_condition(test_el: ET.Element) -> dict | None:
    """
    ThresholdFunction_Test-specific: confirmed parameter layout from TWO
    independent real samples (see module docstring / project notes):
        param 1: BB reference(s) — now captured as bb_ids, so this data
            can be attached to the specific [:REFERENCES] edge(s) it
            describes, rather than living on a disconnected Condition node
        param 2: grouping field (e.g. SourceIP, DeviceId)
        param 3: count threshold
        param 4: comparison operator (gt/eq)
        param 5: cardinality count
        param 6: cardinality field (e.g. DestinationIP)
        param 7: time value
        param 8: time unit (s/m/h/d)
    Returns None if the parameter shape doesn't match (defensive — real
    data may have variants we haven't seen yet).
    """
    params = {p.get("id"): p for p in test_el.findall("parameter")}
    if not all(pid in params for pid in ("1", "2", "3", "4", "5", "6", "7", "8")):
        return None

    def _selection(pid: str) -> str | None:
        el = params[pid].find("userSelection")
        return el.text.strip() if el is not None and el.text else None

    def _decoded(pid: str) -> list[str] | None:
        return _decode_parameter(params[pid])

    bb_selection = _selection("1")
    bb_ids = [v.strip() for v in bb_selection.split(",") if v.strip()] if bb_selection else []
    grouping = _decoded("2")
    count = _selection("3")
    operator = _selection("4")
    cardinality_count = _selection("5")
    cardinality_field = _decoded("6")
    time_value = _selection("7")
    time_unit_raw = _selection("8")

    if count is None or time_value is None:
        return None

    return {
        "bb_ids": bb_ids,
        "grouping_field": grouping[0] if grouping else None,
        "count": int(count) if count.isdigit() else count,
        "operator": operator,
        "cardinality_count": int(cardinality_count) if cardinality_count and cardinality_count.isdigit() else cardinality_count,
        "cardinality_field": cardinality_field[0] if cardinality_field else None,
        "time_value": int(time_value) if time_value.isdigit() else time_value,
        "time_unit": _TIME_UNIT_NAMES.get(time_unit_raw, time_unit_raw),
    }


def extract_raw_text(test_el: ET.Element) -> str | None:
    """Strips the <a href='javascript:editParameter...'> wrapper tags,
    keeping QRadar's own plain-English sentence intact. Applied to
    EVERY condition (not just ArielFilterTest) — this is the human-
    readable explanation UI3's rule analyzer needs, generated by
    QRadar itself, at zero extraction cost beyond a regex strip.

    CONFIRMED from real data: some rules have DOUBLE-encoded HTML
    entities in their stored XML (e.g. "&amp;quot;" — an &amp; wrapping
    a quot;). A single XML parse only resolves the outer &amp;, leaving
    literal "&quot;" text behind instead of a real ". html.unescape()
    as a second pass resolves this; it's a safe no-op on text that was
    only single-encoded to begin with."""
    text_el = test_el.find("text")
    if text_el is None or not text_el.text:
        return None
    stripped = re.sub(r"<a [^>]*>(.*?)</a>", r"\1", text_el.text, flags=re.DOTALL).strip()
    return html.unescape(stripped)


def extract_trigger_timeout_condition(test_el: ET.Element) -> dict | None:
    """
    TriggerTimeout-specific: confirmed parameter layout from 3 real
    samples, all consistent. Negative/absence pattern: "none of X match
    within T after Y match" — flags an EXPECTED follow-up event that did
    NOT happen (e.g. a device going silent).
        param 1: BB/rule reference(s) that must be ABSENT
        param 2: time value
        param 3: time unit
        param 4: BB/rule reference(s) that triggers the timeout window
        param 5: correlation field(s)
    """
    params = {p.get("id"): p for p in test_el.findall("parameter")}
    if not all(pid in params for pid in ("2", "3", "5")):
        return None

    def _selection(pid: str) -> str | None:
        el = params[pid].find("userSelection")
        return el.text.strip() if el is not None and el.text else None

    time_value = _selection("2")
    time_unit_raw = _selection("3")
    correlation_fields = _decode_parameter(params["5"])

    if time_value is None:
        return None

    return {
        "time_value": int(time_value) if time_value.isdigit() else time_value,
        "time_unit": _TIME_UNIT_NAMES.get(time_unit_raw, time_unit_raw),
        "correlation_fields": correlation_fields or [],
    }


def extract_sequence_function_condition(test_el: ET.Element) -> dict | None:
    """
    SequenceFunction_Test-specific: confirmed from 1 real sample ("Recon
    Followed by Accept"). An ORDERED chain of BBs (arbitrary length, via
    an ordered multiselect), with two correlation-field dimensions.
        param 1: minimum match count
        param 2: ordered BB chain
        param 3: match mode (In/Any)
        param 4: correlation type A (same/any)
        param 5: correlation field A
        param 6: correlation type B (same/any)
        param 7: correlation field B
        param 8: time value
        param 9: time unit (s/m/h/d)
    """
    params = {p.get("id"): p for p in test_el.findall("parameter")}
    if not all(pid in params for pid in ("1", "2", "3", "4", "5", "6", "7", "8", "9")):
        return None

    def _selection(pid: str) -> str | None:
        el = params[pid].find("userSelection")
        return el.text.strip() if el is not None and el.text else None

    def _decoded(pid: str) -> list[str] | None:
        return _decode_parameter(params[pid])

    min_count = _selection("1")
    bb_selection = _selection("2")
    bb_ids = [v.strip() for v in bb_selection.split(",") if v.strip()] if bb_selection else []
    match_mode = _decoded("3")
    correlation_type_a = _decoded("4")
    correlation_field_a = _decoded("5")
    correlation_type_b = _decoded("6")
    correlation_field_b = _decoded("7")
    time_value = _selection("8")
    time_unit_raw = _selection("9")

    if time_value is None:
        return None

    return {
        "bb_ids": bb_ids,
        "min_count": int(min_count) if min_count and min_count.isdigit() else min_count,
        "match_mode": match_mode[0] if match_mode else None,
        "correlation_type_a": correlation_type_a[0] if correlation_type_a else None,
        "correlation_field_a": correlation_field_a[0] if correlation_field_a else None,
        "correlation_type_b": correlation_type_b[0] if correlation_type_b else None,
        "correlation_field_b": correlation_field_b[0] if correlation_field_b else None,
        "time_value": int(time_value) if time_value.isdigit() else time_value,
        "time_unit": _TIME_UNIT_NAMES.get(time_unit_raw, time_unit_raw),
    }


def extract_double_sequence_condition(test_el: ET.Element) -> dict | None:
    """
    DoubleSequenceFunction_Test-specific: confirmed from 3 real samples,
    all consistent. Fixed 2-stage chain — stage 1 must match, THEN
    stage 2 must match, correlated by field(s), with a direction
    (To/From) resolving which stage's field the correlation applies to.
        param 1: stage-1 minimum count
        param 2: stage-1 BB reference(s)
        param 3: stage-1 match mode (In/Any)
        param 4: stage-1 correlation field
        param 5: stage-2 minimum count
        param 6: stage-2 BB reference(s)
        param 7: stage-2 match mode (In/Any)
        param 8: stage-2 correlation field
        param 9: time value
        param 10: time unit (s/m/h/d)
        param 11: direction (To/From)
    """
    params = {p.get("id"): p for p in test_el.findall("parameter")}
    if not all(pid in params for pid in [str(i) for i in range(1, 12)]):
        return None

    def _selection(pid: str) -> str | None:
        el = params[pid].find("userSelection")
        return el.text.strip() if el is not None and el.text else None

    def _decoded(pid: str) -> list[str] | None:
        return _decode_parameter(params[pid])

    def _bb_ids(pid: str) -> list[str]:
        sel = _selection(pid)
        return [v.strip() for v in sel.split(",") if v.strip()] if sel else []

    time_value = _selection("9")
    if time_value is None:
        return None

    stage1_mode = _decoded("3")
    stage1_field = _decoded("4")
    stage2_mode = _decoded("7")
    stage2_field = _decoded("8")
    direction = _decoded("11")
    time_unit_raw = _selection("10")

    return {
        "stage1_bb_ids": _bb_ids("2"),
        "stage1_min_count": _selection("1"),
        "stage1_match_mode": stage1_mode[0] if stage1_mode else None,
        "stage1_correlation_field": stage1_field[0] if stage1_field else None,
        "stage2_bb_ids": _bb_ids("6"),
        "stage2_min_count": _selection("5"),
        "stage2_match_mode": stage2_mode[0] if stage2_mode else None,
        "stage2_correlation_field": stage2_field[0] if stage2_field else None,
        "time_value": int(time_value) if time_value.isdigit() else time_value,
        "time_unit": _TIME_UNIT_NAMES.get(time_unit_raw, time_unit_raw),
        "direction": direction[0] if direction else None,
    }


def extract_cause_and_effect_condition(test_el: ET.Element) -> dict | None:
    """
    CauseAndEffect_Test-specific: confirmed from 3 real samples, all
    consistent. Fixed 2-stage chain, similar to DoubleSequenceFunction_Test
    but the correlation field is split into two separate parameters
    (side: Source/Destination, and type: IP/PortInt) instead of one
    combined field name.
        param 1: stage-1 minimum count
        param 2: stage-1 BB reference(s)
        param 3: stage-1 match mode (In/Any)
        param 4: stage-1 field side (Source/Destination)
        param 5: stage-1 field type (IP/PortInt)
        param 6: stage-2 minimum count
        param 7: stage-2 BB reference(s)
        param 8: stage-2 match mode (In/Any)
        param 9: stage-2 field type (IP/PortInt)
        param 10: stage-2 field side (Source/Destination)
        param 11: time value
        param 12: time unit (s/m/h/d)
    """
    params = {p.get("id"): p for p in test_el.findall("parameter")}
    if not all(pid in params for pid in [str(i) for i in range(1, 13)]):
        return None

    def _selection(pid: str) -> str | None:
        el = params[pid].find("userSelection")
        return el.text.strip() if el is not None and el.text else None

    def _decoded(pid: str) -> list[str] | None:
        return _decode_parameter(params[pid])

    def _bb_ids(pid: str) -> list[str]:
        sel = _selection(pid)
        return [v.strip() for v in sel.split(",") if v.strip()] if sel else []

    time_value = _selection("11")
    if time_value is None:
        return None

    stage1_mode = _decoded("3")
    stage1_side = _decoded("4")
    stage1_type = _decoded("5")
    stage2_mode = _decoded("8")
    stage2_type = _decoded("9")
    stage2_side = _decoded("10")
    time_unit_raw = _selection("12")

    return {
        "stage1_bb_ids": _bb_ids("2"),
        "stage1_min_count": _selection("1"),
        "stage1_match_mode": stage1_mode[0] if stage1_mode else None,
        "stage1_field_side": stage1_side[0] if stage1_side else None,
        "stage1_field_type": stage1_type[0] if stage1_type else None,
        "stage2_bb_ids": _bb_ids("7"),
        "stage2_min_count": _selection("6"),
        "stage2_match_mode": stage2_mode[0] if stage2_mode else None,
        "stage2_field_type": stage2_type[0] if stage2_type else None,
        "stage2_field_side": stage2_side[0] if stage2_side else None,
        "time_value": int(time_value) if time_value.isdigit() else time_value,
        "time_unit": _TIME_UNIT_NAMES.get(time_unit_raw, time_unit_raw),
    }


def extract_trigger_match_count_condition(test_el: ET.Element) -> dict | None:
    """
    TriggerMatchCount-specific: confirmed from 3 real samples, all
    consistent. IMPORTANT: param 1 and param 7 are REVERSED from reading
    order — the sentence is "when [param 7] match... after [param 1]
    match", meaning param 7 is the EARLIER (trigger) stage and param 1
    is the LATER stage that must match N times afterward. Verified by
    tracing the real <text> against parameter values, not assumed from
    position.
        param 1: LATER-stage BB reference(s) (fires N times, after trigger)
        param 2: minimum count for the later stage
        param 3, 4: correlation fields (often blank)
        param 5: time value
        param 6: time unit (s/m/h/d)
        param 7: EARLIER-stage BB reference(s) (the trigger)
        param 8: correlation field (e.g. Username, Policy Name)

    correlation_field is read from <text>, NOT param 8's raw
    userSelection. Confirmed from 5 real samples this is NOT a simple
    camelCase transform — raw values are QRadar's internal storage
    representation and are inconsistently shaped (sometimes camelCase
    like "userName", sometimes already readable like "Policy Name").
    <text> is always the correct human-facing label, and can carry
    extra meaning the raw value omits entirely (e.g. a "(custom)" 
    suffix marking a custom event property). Some real samples also
    have NO correlation field at all (no "with the same X" in the
    sentence) — correctly returns None for those, not a crash or a
    wrong match.
    """
    params = {p.get("id"): p for p in test_el.findall("parameter")}
    if not all(pid in params for pid in ("1", "2", "5", "6", "7", "8")):
        return None

    def _selection(pid: str) -> str | None:
        el = params[pid].find("userSelection")
        return el.text.strip() if el is not None and el.text else None

    def _bb_ids(pid: str) -> list[str]:
        sel = _selection(pid)
        return [v.strip() for v in sel.split(",") if v.strip()] if sel else []

    time_value = _selection("5")
    if time_value is None:
        return None

    time_unit_raw = _selection("6")

    # Correlation field from raw_text (human-readable label, e.g.
    # "Username"), NOT param 8's raw userSelection (QRadar's internal
    # camelCase identifier, e.g. "userName") — confirmed bug fix, see
    # module-level comment on _TRIGGER_MATCH_CORRELATION_PATTERN.
    raw_text = extract_raw_text(test_el)
    correlation_match = _TRIGGER_MATCH_CORRELATION_PATTERN.search(raw_text) if raw_text else None
    correlation_field = correlation_match.group(1).strip() if correlation_match else None

    return {
        "trigger_bb_ids": _bb_ids("7"),
        "later_bb_ids": _bb_ids("1"),
        "later_min_count": _selection("2"),
        "time_value": int(time_value) if time_value.isdigit() else time_value,
        "time_unit": _TIME_UNIT_NAMES.get(time_unit_raw, time_unit_raw),
        "correlation_field": correlation_field.strip() if correlation_field and correlation_field.strip() else None,
    }


def extract_aql_condition(test_el: ET.Element) -> dict | None:
    """AQL_Test-specific: pulls the target (event/flow) and the raw AQL
    query string out of the already-decoded raw_text, rather than the
    URL-encoded userSelection field. See module-level comment for why."""
    raw = extract_raw_text(test_el)
    if not raw:
        return None
    m = _AQL_TEXT_PATTERN.match(raw)
    if not m:
        return None
    target, query = m.groups()
    return {"target": target, "aql_query": query.strip()}


def extract_device_type_condition(test_el: ET.Element) -> dict | None:
    """DeviceTypeID_Test-specific: extracts log source name(s) from the
    already-resolved raw_text, since userOptions has no local <option>
    table (dynamic method="getDeviceTypeDescs") but QRadar's own <text>
    rendering already shows the real name(s)."""
    raw = extract_raw_text(test_el)
    if not raw:
        return None
    m = _DEVICE_TYPE_TEXT_PATTERN.match(raw)
    if not m:
        return None
    names = [v.strip() for v in m.group(1).split(",") if v.strip()]
    return {"log_source_names": names}


def extract_device_id_condition(test_el: ET.Element) -> dict | None:
    """DeviceID_Test-specific: same trick as DeviceTypeID_Test — extracts
    resolved device name(s) from raw_text. Confirmed from 5 real samples,
    including a 17-device multiselect case."""
    raw = extract_raw_text(test_el)
    if not raw:
        return None
    m = _DEVICE_ID_TEXT_PATTERN.match(raw)
    if not m:
        return None
    names = [v.strip() for v in m.group(1).split(",") if v.strip()]
    return {"device_names": names}


def extract_event_category_condition(test_el: ET.Element) -> dict | None:
    """EventCategory_Test-specific: extracts resolved category name(s)
    from raw_text, splitting each "HighLevel.LowLevel" pair on the
    FIRST "." only — confirmed safe since real high-level category
    names (Authentication, Recon, etc.) never contain a period
    themselves; only the low-level name occasionally might."""
    raw = extract_raw_text(test_el)
    if not raw:
        return None
    m = _EVENT_CATEGORY_TEXT_PATTERN.match(raw)
    if not m:
        return None
    categories = []
    for entry in m.group(1).split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "." in entry:
            high, low = entry.split(".", 1)
            categories.append({"high_level": high.strip(), "low_level": low.strip()})
        else:
            categories.append({"high_level": entry, "low_level": None})
    return {"categories": categories}


def extract_qid_condition(test_el: ET.Element) -> dict | None:
    """QID_Test-specific: extracts (qid, event_name) pairs from raw_text,
    format "(QID_NUMBER) Event Name". Uses a lookahead split (each entry
    ends where the next "(digits)" begins, or at string end) rather than
    a blind comma-split, since a real event name could itself contain a
    comma — confirmed-safe boundary marker is the QID number pattern,
    not the comma."""
    raw = extract_raw_text(test_el)
    if not raw:
        return None
    m = _QID_TEXT_PATTERN.match(raw)
    if not m:
        return None
    entries = re.findall(r"\((\d+)\)\s*(.+?)(?=,\s*\(\d+\)|$)", m.group(1))
    if not entries:
        return None
    return {"qids": [{"qid": int(qid), "event_name": name.strip()} for qid, name in entries]}


def extract_refset_condition(test_el: ET.Element) -> dict | None:
    """ReferenceSetTest-specific: extracts field(s), match modes, and
    reference SET name(s) — structural identity only, never contents."""
    raw = extract_raw_text(test_el)
    if not raw:
        return None
    m = _REFSET_TEXT_PATTERN.match(raw)
    if not m:
        return None
    field_mode, fields, refset_mode, refsets = m.groups()
    return {
        "field_match_mode": field_mode,
        "fields": [f.strip() for f in fields.split(",") if f.strip()],
        "refset_match_mode": refset_mode,
        "refset_names": [r.strip() for r in refsets.split(",") if r.strip()],
    }


def extract_refmap_condition(test_el: ET.Element) -> dict | None:
    """ReferenceDataTest-specific: MAP shape only (key + value), the
    only shape confirmed from real data so far. Returns None for any
    other shape (Map-of-Sets, Table) rather than guessing — same
    defensive convention as every other extractor here."""
    raw = extract_raw_text(test_el)
    if not raw:
        return None
    m = _REFMAP_TEXT_PATTERN.match(raw)
    if not m:
        return None
    key_mode, key_field, value_mode, value_field, map_mode, maps = m.groups()
    return {
        "key_match_mode": key_mode,
        "key_field": key_field.strip(),
        "value_match_mode": value_mode,
        "value_field": value_field.strip(),
        "map_match_mode": map_mode,
        "map_names": [n.strip() for n in maps.split(",") if n.strip()],
    }


def extract_rule_match_condition(test_el: ET.Element) -> dict | None:
    """RuleMatch_Test-specific: a plain "AND when matches BB:X" check,
    no threshold. Full structural extraction (creating the actual
    REFERENCES edge) is owned by rule_xml_parser.extract_bb_references
    -- a separate, unrelated code path, untouched by this. This
    extractor's ONLY job is capturing which BB(s) are referenced, for
    display purposes, so this condition's position in the rule's real
    execution sequence isn't silently lost.

    CONFIRMED BUG FIX: an earlier version assumed the BB identifier(s)
    always live in parameter id="1". True for the simple "AND when
    matches BB:X" sentence shape, but FALSE for the "matches any/all
    of the following BB(s):" shape -- there, parameter id="1" is the
    match-mode QUANTIFIER ("any"/"all"), not a BB id at all, and the
    real BB identifier lives in parameter id="2" instead. The old code
    silently stored "any" as if it were a real bb_id, breaking
    downstream BB lookup for every rule using this sentence shape
    (confirmed on real data: "Bypass UAC via Fodhelper.exe", BB:
    Process Creation, identifier 44f094bf-d53e-4102-b89e-39a0fc3692eb).

    Fixed by NEVER trusting a fixed parameter position: inspect EVERY
    parameter's values, keep only ones that actually LOOK LIKE a real
    identifier (SYSTEM-nnnn or a UUID) -- explicitly excludes known
    quantifier words ("any", "all"). Robust to both sentence shapes at
    once, without needing to special-case each one separately.
    """
    candidate_ids: list[str] = []
    for param_el in test_el.findall("parameter"):
        sel = param_el.find("userSelection")
        if sel is None or not sel.text:
            continue
        for value in (v.strip() for v in sel.text.split(",")):
            if value and _BB_ID_LIKE_PATTERN.match(value):
                candidate_ids.append(value)

    if not candidate_ids:
        return None
    return {"bb_ids": candidate_ids}

def extract_dst_port_condition(test_el: ET.Element) -> dict | None:
    """DstPort_Test-specific: confirmed from real data -- param 1's
    values are already the literal port number(s) (e.g. ["445"]), no
    decoding table needed."""
    params = {p.get("id"): p for p in test_el.findall("parameter")}
    if "1" not in params:
        return None
    ports = _decode_parameter(params["1"])
    if not ports:
        return None
    return {"field": "Destination Port", "operator": "is any of", "values": ports}


def extract_match_count_condition(test_el: ET.Element) -> dict | None:
    """
    MatchCount-specific: confirmed from real data. Unlike
    TriggerMatchCount (references SEPARATE BBs via trigger_bb_ids/
    later_bb_ids), MatchCount has NO bb_ids -- it's a SELF-REFERENTIAL
    threshold on the rule's OWN preceding conditions. Confirmed layout:
        param 2: minimum count, param 3: "same" grouping field,
        param 4: "different" field, param 5: time value, param 6: time unit
    """
    params = {p.get("id"): p for p in test_el.findall("parameter")}
    if not all(pid in params for pid in ("2", "5", "6")):
        return None

    def _selection(pid: str) -> str | None:
        el = params[pid].find("userSelection")
        return el.text.strip() if el is not None and el.text else None

    def _decoded(pid: str) -> list[str] | None:
        return _decode_parameter(params[pid])

    count = _selection("2")
    time_value = _selection("5")
    if count is None or time_value is None:
        return None

    same_field = _decoded("3")
    different_field = _decoded("4")
    time_unit_raw = _selection("6")

    return {
        "count": int(count) if count.isdigit() else count,
        "same_field": same_field[0] if same_field else None,
        "different_field": different_field[0] if different_field else None,
        "time_value": int(time_value) if time_value.isdigit() else time_value,
        "time_unit": _TIME_UNIT_NAMES.get(time_unit_raw, time_unit_raw),
    }


def parse_rule_conditions(rule_xml: str | None) -> list[dict]:
    """
    Returns one dict per <test> element (excluding BB-reference tests,
    see module docstring):
        {
            "test_class": "AttackContext_Test",
            "negated": False,
            "parameters": [{"param_id": "1", "values": ["Local to Local", "Local to Remote"]}],
        }
    ArielFilterTest entries additionally include "field"/"operator" keys
    from extract_ariel_condition(), when parseable.
    """
    if not rule_xml:
        return []

    try:
        root = ET.fromstring(rule_xml)
    except ET.ParseError:
        return []

    results: list[dict] = []

    for test_el in root.iter("test"):
        short_name = _test_short_name(test_el)
        if short_name in _BB_REFERENCE_TEST_CLASSES:
            continue

        negated = test_el.get("negate", "false").lower() == "true"

        entry: dict = {
            "test_class": short_name,
            "negated": negated,
            "raw_text": extract_raw_text(test_el),
            "parameters": [],
        }

        if short_name == "ArielFilterTest":
            ariel = extract_ariel_condition(test_el)
            if ariel:
                entry.update(ariel)
        elif short_name == "ThresholdFunction_Test":
            threshold = extract_threshold_condition(test_el)
            if threshold:
                entry["threshold"] = threshold
        elif short_name == "TriggerTimeout":
            timeout = extract_trigger_timeout_condition(test_el)
            if timeout:
                entry["timeout"] = timeout
        elif short_name == "SequenceFunction_Test":
            seq = extract_sequence_function_condition(test_el)
            if seq:
                entry["sequence"] = seq
        elif short_name == "DoubleSequenceFunction_Test":
            dseq = extract_double_sequence_condition(test_el)
            if dseq:
                entry["double_sequence"] = dseq
        elif short_name == "CauseAndEffect_Test":
            cae = extract_cause_and_effect_condition(test_el)
            if cae:
                entry["cause_and_effect"] = cae
        elif short_name == "TriggerMatchCount":
            tmc = extract_trigger_match_count_condition(test_el)
            if tmc:
                entry["trigger_match_count"] = tmc
        elif short_name == "AQL_Test":
            aql = extract_aql_condition(test_el)
            if aql:
                entry["aql"] = aql
        elif short_name == "DeviceTypeID_Test":
            device_type = extract_device_type_condition(test_el)
            if device_type:
                entry["device_type"] = device_type
        elif short_name == "DeviceID_Test":
            device_id = extract_device_id_condition(test_el)
            if device_id:
                entry["device_id"] = device_id
        elif short_name == "EventCategory_Test":
            event_category = extract_event_category_condition(test_el)
            if event_category:
                entry["event_category"] = event_category
        elif short_name == "QID_Test":
            qid = extract_qid_condition(test_el)
            if qid:
                entry["qid"] = qid
        elif short_name == "ReferenceSetTest":
            refset = extract_refset_condition(test_el)
            if refset:
                entry["refset"] = refset
        elif short_name == "ReferenceDataTest":
            refmap = extract_refmap_condition(test_el)
            if refmap:
                entry["refmap"] = refmap
        elif short_name == "RuleMatch_Test":
            rule_match = extract_rule_match_condition(test_el)
            if rule_match:
                entry["rule_match"] = rule_match
        elif short_name == "DstPort_Test":
            dst_port = extract_dst_port_condition(test_el)
            if dst_port:
                entry.update(dst_port)
        elif short_name == "MatchCount":
            match_count = extract_match_count_condition(test_el)
            if match_count:
                entry["match_count"] = match_count

        for param_el in test_el.findall("parameter"):
            values = _decode_parameter(param_el)
            if values is not None:
                entry["parameters"].append({"param_id": param_el.get("id"), "values": values})

        results.append(entry)

    return results