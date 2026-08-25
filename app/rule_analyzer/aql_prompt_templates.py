"""
AQL generation guidance for the investigating LLM -- the rules and
confirmed-correct few-shot examples it needs to write safe, valid AQL
against a live QRadar console. Kept SEPARATE from investigation_nodes.py
(which wires this into the actual run_aql_search tool) so the prompt
content itself can be reviewed, tuned, and versioned independently of
the tool machinery around it.

TYPE-level log source scoping only (LOGSOURCETYPENAME), not
instance-level (LOGSOURCENAME) -- deliberately simplified: the LLM
only ever has a log source TYPE name available (from the rule chain),
never an individual log source instance name, so instance-level
scoping was never something it could reliably fill in correctly.

No OR operator -- QRadar AQL may not reliably support it, and even
where it does, an OR'd query gives an ambiguous result (can't tell
which condition actually matched). Separate sequential queries instead.
"""
from __future__ import annotations

AQL_RULES = """Follow these rules when writing the AQL query:
  - Must start with SELECT.
  - Must include an explicit relative time range: 'LAST N DAYS' / 'LAST N HOURS' / 'LAST N MINUTES', placed at the END of the query. There is a hard cap on how large this can be, DIFFERENT per log source type category (firewalls: 1 day max, Windows: 2 days max, Linux/Unix: 5 days max, anything else: 1 day max, or 12 hours if you don't know the type) -- to protect the live production console from resource-intensive searches. Keep your requested range comfortably within the relevant cap.
  - Absolute START/STOP date ranges are NOT supported -- always use the relative LAST N <unit> form.
  - MUST filter by log source TYPE, using LOGSOURCETYPENAME(devicetype) = 'exact type name'. An unscoped search across the entire console's event volume will be rejected before it ever reaches QRadar -- this is a hard requirement, not a suggestion, to protect the live console from load.
  - Column aliases MUST use SINGLE quotes ('Count'), never double quotes ("Count") -- CONFIRMED from a real 422 syntax error: a generated query using "Count" (double-quoted) was rejected by QRadar's own AQL parser as invalid syntax.
  - Custom field NAMES containing a space (e.g. "Event ID") MUST be wrapped in DOUBLE quotes; the VALUE you compare them against is still SINGLE-quoted (e.g. "Event ID"='4624'). Built-in fields with no space (QID, logSourceId) need no quoting on the name.
  - NEVER use OR to combine multiple conditions in one query. If you need to check more than one hypothesis (e.g. two different Event IDs, or an Event ID AND a QID as separate possibilities), run TWO SEPARATE, SEQUENTIAL searches -- one focused question per query -- not one query trying to check several things at once. This keeps each result unambiguous."""

AQL_FEW_SHOT_EXAMPLES = """Confirmed-correct example query, matching QRadar's real AQL syntax exactly (clause order matters -- WHERE, then GROUP BY, then ORDER BY, then LIMIT, then LAST):
  SELECT qid AS 'QID', QIDNAME(qid) AS 'Event Name', SUM("eventCount") AS 'Count'
  FROM events
  WHERE LOGSOURCETYPENAME(devicetype) = 'Fortinet FortiGate Security Gateway'
  GROUP BY qid
  ORDER BY 'Count' DESC
  LIMIT 50
  LAST 5 MINUTES

A simpler example for a direct QID occurrence check:
  SELECT QID, username FROM events WHERE LOGSOURCETYPENAME(devicetype) = 'Microsoft Windows Security Event Log' AND QID=5000910 LAST 2 DAYS

Confirmed-correct example checking a CUSTOM field with a space in its name (note the double-quoted field name, single-quoted value, and single-quoted alias):
  SELECT "Event ID" AS 'Event ID (custom)', COUNT(*) AS 'Count'
  FROM events
  WHERE ( "Event ID"='4624' AND LOGSOURCETYPENAME(devicetype)='Microsoft Windows Security Event Log' )
  GROUP BY "Event ID"
  ORDER BY 'Count' DESC
  LIMIT 1000
  LAST 5 MINUTES"""

AQL_TOOL_DESCRIPTION = (
    "Execute a LIVE AQL search against QRadar's Ariel event database to check whether an event "
    "has actually occurred (e.g. confirming a specific QID showed up in the log traffic within a "
    "recent window). WRITE the full AQL query yourself.\n\n"
    f"{AQL_RULES}\n\n"
    f"{AQL_FEW_SHOT_EXAMPLES}\n\n"
    "Pass log_source_type as the EXACT log source type name shown in the rule chain "
    "(e.g. \"Microsoft Windows Security Event Log\"), so the correct time-range cap applies -- "
    "this determines resource safety, so get it right rather than guessing. This tool has a "
    "budget of only 2 live searches per investigation -- use it deliberately, on the single most "
    "decisive question, not to explore broadly."
)