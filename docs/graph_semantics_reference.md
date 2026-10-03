# Graph Semantics Reference (hand-written — Layer 2)

Read this alongside `graph_schema_reference.md` (Layer 1 — auto-generated
structure) before writing Cypher. Layer 1 tells you what exists. This
file tells you how to use it correctly — every rule below comes from a
real bug or design decision confirmed against live data, not guessed.

## General rules — apply to every query

1. **Always scope by `customer_id`.** Every `Rule` node and most other
   nodes carry it. Never write a query without it — this is a
   multi-tenant graph.

2. **`Rule.rule_id` is the internal database ID, NOT `qradar_rule_id`.**
   `rule_id` is what every relationship uses to connect to a Rule.
   `qradar_rule_id` is a separate property, only useful if the user
   explicitly asks for QRadar's own numeric ID.

3. **`(r:Rule)` alone returns BOTH actual rules AND building blocks.**
   A BuildingBlock is stored as `(:Rule:BuildingBlock)` — same node,
   extra label. If the question implies "real detection rules" (not
   BBs), filter with `r.object_type = 'RULE'` or `NOT r:BuildingBlock`.

4. **`Condition.raw_text` is QRadar's own plain-English sentence for
   that condition.** Prefer returning this alongside structured fields
   when the user's question is "why"/"what does this rule do" — it's
   more useful to a human than raw property values alone.

## REFERENCES (Rule -> BuildingBlock)

5. **Threshold data lives on the edge, not a separate node.**
   `threshold_count`, `threshold_operator`, `threshold_grouping_field`,
   `threshold_cardinality_count`, `threshold_cardinality_field`,
   `threshold_time_value`, `threshold_time_unit` are all edge
   properties on `REFERENCES` — present ONLY when a `ThresholdFunction_Test`
   named that specific BB. Absent entirely = a plain reference with no
   threshold (e.g. from `RuleMatch_Test`). Don't assume every
   `REFERENCES` edge has threshold data.

## FOLLOWED_BY (BuildingBlock -> BuildingBlock)

6. **This edge connects the two referenced BBs to EACH OTHER — it does
   NOT connect to the Rule that defined the relationship.** The
   defining rule is recorded as `rel.rule_id` / `rel.rule_name`,
   properties on the edge, not graph adjacency. To find "which sequence
   relationships does rule X define," filter on the edge property:
   `MATCH (a)-[rel:FOLLOWED_BY]->(b) WHERE rel.rule_id = X`
   — do NOT look for a direct edge from the Rule node.

7. **The same BB pair can have multiple `FOLLOWED_BY` edges, one per
   defining rule.** If two different rules both describe BB-A followed
   by BB-B with different timing, that's two separate edges (each keyed
   by its own `rel.rule_id`), not one shared edge. Don't assume
   uniqueness on `(source)-[:FOLLOWED_BY]->(target)` alone.

8. **`rel.sequence_test_class` tells you which of the 4 original
   QRadar test classes produced this edge** (`SequenceFunction_Test`,
   `DoubleSequenceFunction_Test`, `CauseAndEffect_Test`,
   `TriggerMatchCount`) — useful context if the user asks about a
   specific pattern type, not required for basic traversal.

## REQUIRES_LOGSOURCE_TYPE vs REQUIRES_DEVICE — do not conflate

9. **`LogSourceType` is a CATEGORY** (e.g. "Microsoft Windows Security
   Event Log") — matches many possible configured log sources.
   **`Device` is one SPECIFIC CONFIGURED INSTANCE** (e.g. "Custom Rule
   Engine-8 :: c-ctcna-qr") — one exact log source in this QRadar
   console. "Rules needing any Windows log source" (LogSourceType) and
   "rules needing this one specific device" (Device) are different
   questions with different answers — pick the right node type based
   on what the user actually asked.

## MATCHES_EVENT_CATEGORY

10. **`EventCategory.low_level` can be an empty string `""`, not just a
    real sub-category name — and `""` is NOT missing data.** It means
    the rule matches the ENTIRE high-level category with no
    sub-category filter (e.g. matching all of "Exploit", not one
    specific exploit sub-type). Do not filter this out as null/invalid;
    treat `low_level = ""` as a legitimate, common value.

## MATCHES_QID

11. **`QID.qid` is globally unique** across the whole QRadar console —
    safe to match on directly without scoping by anything else.

## DEPENDS_ON_REFSET / DEPENDS_ON_REFMAP — contents are NEVER in this graph

12. **`ReferenceSet` and `ReferenceMap` nodes represent structural
    identity ONLY** — which rule depends on which named set/map, via
    which field(s). **The actual live contents (which IPs, which
    usernames are currently in the set) are deliberately never stored
    here.** If a question asks "is IP X in reference set Y" or "what's
    currently in this set," that CANNOT be answered from this graph —
    say so plainly rather than generating a query that will silently
    return nothing. That kind of question needs a live QRadar API call,
    outside this system's scope.

13. **`ReferenceDataTest` (→ `ReferenceMap`) currently only covers the
    MAP shape (key + value).** Map-of-Sets and Table variants are not
    yet confirmed/modeled — if a query against `ReferenceMap` returns
    nothing for a rule you know uses reference data, that rule may use
    an unmodeled shape, not a bug.

## DETECTS_TECHNIQUE / BELONGS_TO_TACTIC

14. **Tactic info is two hops from Rule, not one.**
    `(Rule)-[:DETECTS_TECHNIQUE]->(MitreTechnique)-[:BELONGS_TO_TACTIC]->(MitreTactic)`.
    A question about "which tactic does this rule cover" needs both
    hops, not just the first.

## Condition.negated

15. **`negated: true` means the rule fires when that condition does
    NOT match** — an exclusion/whitelist pattern (e.g. "detected by
    this log source AND NOT one of these excluded hosts"). Do not
    read `negated: true` as "this condition is disabled" — the
    condition is fully active, just inverted.

## AQL_Test conditions

16. **AQL_Test conditions stay as generic `Condition` nodes** with
    `aql_query` (the raw AQL string) and `target` (`"event"` or
    `"flow"`) properties — no dedicated node type. The query itself is
    a free-form embedded query language (regex `MATCHES`, `ilike`
    wildcards, `REFERENCEMAPSETCONTAINS(...)`, boolean AND/OR) — do not
    attempt to parse its internal structure via Cypher property
    matching beyond a simple `CONTAINS` on the raw string.