"""
ALL prompt content for Sigma generation, both simple and correlation
rules, in one file. Shared instructions (de-identification, field
values, logsource) are defined ONCE at the top and reused by both
prompt builders below -- a fix to shared guidance only needs to
happen in one place.
"""
from __future__ import annotations

# -- Shared instructions, used by BOTH prompts below ------------------

_DE_IDENTIFICATION = """CRITICAL - DE-IDENTIFICATION: The rule chain below may include real sample values from reference sets (usernames, IPs, domains, hostnames) or other customer-specific sensitive data. You MUST replace ONLY these with a general description -- NEVER copy specific values verbatim. Every abstracted value MUST include ALL THREE of the following, not just a vague label:
  1. WHAT TYPE of value it is (e.g. "a domain subdomain", "a privileged account identifier", "an internal hostname").
  2. The STRUCTURAL PATTERN actually visible in the real value(s) -- prefix, suffix, length, delimiter, casing, or any other shape you can observe. Never omit this even if the real value looks arbitrary -- describe whatever pattern IS there.
  3. ONE illustrative placeholder example showing that shape, using <angle-bracket> tokens for the variable part.

GOOD EXAMPLE (preserves enough structure to be genuinely useful):
  Real values: "aaa.stage.xyz123", "post.1.abc456"
  Abstracted: "a subdomain pattern used for C2 staging, typically starting with a short fixed prefix (e.g. 'stage' or 'post') followed by a numeric or alphanumeric token, e.g. '<prefix>.<token>'"

BAD EXAMPLE (too vague to be useful -- DO NOT do this):
  Real values: "aaa.stage.xyz123", "post.1.abc456"
  Abstracted: "<substring indicator associated with the detected activity>"

The BAD example only restates what the rule detects without saying anything about what the actual VALUE looks like -- always aim for the GOOD example's level of detail. Applies to every field, including selections, description, and title.

CRITICAL - DO NOT OVER-ABSTRACT: only abstract values that are GENUINELY customer-specific and sensitive. The following are PUBLIC, STANDARD, NON-SENSITIVE values and must ALWAYS be kept literal, exactly as written -- NEVER replaced with a placeholder:
  - Known software, vendor, or application names (e.g. "Chrome", "Edge", "Brave", "Mozilla", "Chromium", "PowerShell", "Mimikatz")
  - Standard file extensions (e.g. ".sqlite", ".db", ".json", ".exe", ".dll")
  - Well-known system/application folder or file names (e.g. "Login Data", "Cookies", "User Data", "Profiles", "AppData", "System32")
  - Standard protocol, port, or built-in Windows/Linux system terms
  - Publicly documented attack tool or technique names

CONFIRMED REAL BUG this rule fixes: an earlier version of this system incorrectly abstracted a list of browser names (Chrome, Edge, Brave, etc.) into meaningless placeholders like "<browser_app_dir_fragment_3>" -- this made the resulting Sigma rule COMPLETELY NON-FUNCTIONAL, since nobody could tell what it actually checks for anymore. Browser names, file extensions, and folder names like "Login Data" or "Cookies" are PUBLIC, standard terms -- not customer secrets -- and must be written out literally:
  CORRECT: values: ["\\Chrome\\", "\\Edge\\", "\\Brave-Browser\\"]
  WRONG:   values: ["<browser_app_dir_fragment_1>", "<browser_app_dir_fragment_2>", "<browser_app_dir_fragment_3>"]

The ONLY things to abstract are values UNIQUE TO THIS SPECIFIC CUSTOMER'S ENVIRONMENT that would reveal real, private information if shared -- e.g. an actual employee's username, an actual internal server hostname, an actual internal domain name, or actual IP addresses from a customer's reference set. A list of well-known software names is never one of these."""

_FIELD_VALUES = """CRITICAL - FIELD VALUES: values must be the actual literal value the field is compared against (e.g. a numeric QID like "101250969"), never a human-readable NAME or label for that value. If you want to record a human-readable name alongside a code, use a separate field for it."""

_LOGSOURCE = """CRITICAL - LOGSOURCE MUST BE POPULATED: whenever the rule chain shows a real log source/device type, you MUST reflect it in the logsource's product (and service if applicable) -- never leave both null when a log source is clearly present, even though the same info may also appear as a DeviceVendor/DeviceProduct field inside detection selections. CONFIRMED real Sigma product naming (from actual SigmaHQ rules) is lowercase, e.g.:
  - "Fortinet FortiGate Security Gateway" -> product: "fortigate"
  - "Microsoft Windows Security Event Log" -> product: "windows", service: "security"
If genuinely uncertain of the exact real product name, use your best lowercase guess rather than leaving it null."""

_MITRE_CONFIRMED = (
    "This rule ALREADY has CONFIRMED MITRE mapping -- tactics: {tactics}, techniques: {techniques}, "
    "sub-techniques: {sub_techniques}. Use these directly in the tags (format: attack.txxxx for techniques, "
    "attack.txxxx.xxx for sub-techniques, attack.tactic-name-with-dashes for tactics -- all lowercase). "
    "Leave mitre_techniques_inferred EMPTY -- do not re-infer or guess additional MITRE data."
)

_MITRE_INFERRED = (
    "This rule has NO confirmed MITRE mapping at all. Based on the detection logic below, infer the most "
    "likely MITRE ATT&CK tactic/technique(s). mitre_techniques_inferred MUST NOT be left empty -- every "
    "rule maps to SOME MITRE tactic/technique, even if only loosely. If not fully confident, still provide "
    "your best assessment with confidence 'low' rather than leaving the list empty.\n\n"
    "Example of a correctly filled entry, for a rule detecting repeated failed logins:\n"
    '{"tactic": "Credential Access", "technique_id": "T1110", "technique_name": "Brute Force", "confidence": "high"}'
)


def _mitre_instruction(tactics: list[str], techniques: list[str], sub_techniques: list[str]) -> str:
    if tactics or techniques or sub_techniques:
        return _MITRE_CONFIRMED.format(tactics=tactics, techniques=techniques, sub_techniques=sub_techniques)
    return _MITRE_INFERRED


# -- Prompt 1: SIMPLE rule generation ---------------------------------

def build_sigma_generation_prompt(tactics: list[str], techniques: list[str], sub_techniques: list[str]) -> str:
    mitre = _mitre_instruction(tactics, techniques, sub_techniques)
    return f"""You are converting a QRadar detection rule (including any referenced building blocks, already inlined below) into a Sigma-format representation, following the REAL Sigma rule specification.

{_DE_IDENTIFICATION}

CRITICAL - MITRE MAPPING: {mitre}

{_FIELD_VALUES}

Follow the real Sigma spec fields: title, description, level (informational/low/medium/high/critical), logsource (category/product/service), detection (named selection blocks + a condition string), tags (attack.txxxx), falsepositives.

{_LOGSOURCE}

REAL SIGMA CONVENTIONS (from actual SigmaHQ community rules):
- Titles are terse and technique-descriptive -- describe WHAT is suspicious and WHERE, not a vague summary.
- Use field modifiers whenever the real match logic isn't exact equality -- 'contains'/'startswith'/'endswith'/'re'.
- Selection block names should be descriptive when there's more than one part to the logic.
- logsource.category should use Sigma's standard vocabulary where it fits: 'process_creation', 'dns_query', 'network_connection', 'file_event', 'registry_event', 'authentication'.
"""


# -- Prompt 2: CORRELATION rule generation (base + correlation) ------

def build_correlation_generation_prompt(tactics: list[str], techniques: list[str], sub_techniques: list[str]) -> str:
    mitre = _mitre_instruction(tactics, techniques, sub_techniques)
    return f"""You are converting a QRadar detection rule that involves COUNTING or THRESHOLDING occurrences of an event pattern over time (e.g. "at least N events matching X within Y minutes") into Sigma's CORRELATION format.

CRITICAL - THIS REQUIRES TWO LINKED DOCUMENTS, NOT ONE: Real Sigma syntax does NOT support embedding a count/threshold inside a single detection block's condition string. Instead:
  1. A BASE rule describes the underlying event pattern being counted (the "what"), given a short reference_name. NO count/threshold logic in it at all.
  2. A CORRELATION section describes the threshold logic (the "how many, how often") -- type, which base rule it references by reference_name, group-by field(s), the time window, and the count condition.

CORRELATION TYPES: event_count (counts matches -- the common case, e.g. brute force), value_count (counts DISTINCT values of one field, requires condition.field), temporal/temporal_ordered (multiple DIFFERENT base rules occurring together -- use only for genuine multi-stage/sequence logic, not a repeated single pattern).

GROUP-BY: field(s) identifying "the same X", e.g. group_by: ["Username"].
TIMESPAN: integer + single-char unit -- s/m/h/d/w/M(months)/y, e.g. "5m".
CONDITION: one operator (gt/gte/lt/lte/eq/neq) + a count.

WORKED EXAMPLE (shape only -- your real values must come from the rule chain below):
  "6+ failed VPN logins for the same username within 5 minutes" becomes:
  base_title: "Fortinet VPN Failed Login", reference_name: "fortigate_vpn_failed_login", base_detection with NO threshold logic;
  correlation: type="event_count", rules=["fortigate_vpn_failed_login"], group_by=["Username"], timespan="5m", condition operator="gte" count=6.

{_DE_IDENTIFICATION}

{_LOGSOURCE}

CRITICAL - MITRE MAPPING: {mitre}

{_FIELD_VALUES}
"""