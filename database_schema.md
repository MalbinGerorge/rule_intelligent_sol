# Rule Intelligent Sol — Database Schema Reference

Postgres schema for pulling QRadar rule/offense/MITRE data and validating
it against QRadar's own reference data. Multi-tenant: one row per
customer in `customers`, everything else scoped by `customer_id`.

**Status: confirmed against real Cotecna data** — every table below
reflects actual field shapes pulled from a live QRadar console, not
guesses. Generated directly from the live schema (`\d <table>` in psql),
not from memory.

---

## The four "id"-like values, and how not to confuse them

This trips people up, so it's worth stating explicitly:

| Column | What it is | Example | Scope |
|---|---|---|---|
| `rules.id` | Postgres's own auto-increment PK. Internal only, never sent to/from QRadar. | `1`, `2`, `47`... | this DB only |
| `rules.qradar_rule_id` | QRadar's numeric rule ID. Same value space as `rules_reference.qradar_rule_id` and `rule_offense_contributions.qradar_rule_id`. | `100001`, `108042` | per QRadar console |
| `rules.identifier` | QRadar's string identifier. Used **only** to call the MITRE coverage endpoint. | `"SYSTEM-1443"`, `"CUSTOM-1"` | per QRadar console |
| `rule_offense_contributions.qradar_contribution_id` | The contribution record's own ID (QRadar's `id` field on that endpoint). Distinct from any rule ID. | `100421` | per QRadar console |

Foreign keys everywhere in this schema point at `rules.id` (Postgres's
own PK) — never at `qradar_rule_id` or `identifier` directly. Ingestion
code resolves QRadar's numeric/string IDs to our internal `rules.id` via
a lookup before inserting child rows.

---

## Entity overview

```
customers ──< customer_credentials      (1:1, encrypted token)
customers ──< rules                     (rules_with_data — BOTH rules AND building blocks)
customers ──< rules_reference           (ground truth from /analytics/rules)
customers ──< building_blocks_reference (ground truth from /analytics/building_blocks)
customers ──< mitre_mappings
customers ──< rule_offense_contributions
customers ──< validation_results
customers ──< sync_runs

rules ──< rule_offense_contributions    (FK: rule_id -> rules.id)
rules ──< rule_building_blocks          (BBs referenced inside a rule's rule_xml)
rules ──< mitre_mappings                (FK: rule_id -> rules.id)

rule_summary  (VIEW — consolidates rules + rule_offense_contributions + mitre_mappings)
```

Two validation pipelines, both writing into the same `validation_results` table:
- **Rules**: does every `rules.qradar_rule_id` exist in `rules_reference`?
- **Building blocks**: does every `rules` row with `object_type='BUILDING_BLOCK'` exist in `building_blocks_reference`?

---

## Tables

### `customers`
| Column | Type | Notes |
|---|---|---|
| id | SERIAL PK | |
| name | TEXT UNIQUE NOT NULL | e.g. `cotecna` |
| qradar_host | TEXT NOT NULL | e.g. `23.97.253.242` |
| verify_ssl | BOOLEAN NOT NULL | off by default — most consoles use self-signed certs |
| active | BOOLEAN NOT NULL | |
| created_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |

### `customer_credentials`
API token, encrypted at rest via Postgres `pgcrypto` (`pgp_sym_encrypt`/`pgp_sym_decrypt`), keyed by `TOKEN_ENCRYPTION_KEY` from `.env` — never stored or logged in plaintext.

| Column | Type | Notes |
|---|---|---|
| customer_id | INTEGER PK, FK → customers.id | |
| token_encrypted | BYTEA NOT NULL | |
| rotated_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |

### `rules`
Ingested from `GET /analytics/rules_with_data` (**JSON**, not XML — corrected from an early assumption).

**Confirmed:** this endpoint returns BOTH actual rules and Building
Blocks in the same list, distinguished by the real `is_building_block`
boolean field (not by parsing the `"BB:"` name prefix, which was our
original guess before seeing real data).

| Column | Type | Notes |
|---|---|---|
| id | SERIAL PK | Postgres's own ID — see table above |
| customer_id | INTEGER FK → customers.id | |
| qradar_rule_id | BIGINT NOT NULL | QRadar's numeric `id` |
| identifier | TEXT, indexed | e.g. `SYSTEM-1443` — MITRE lookup key |
| name | TEXT | |
| type | TEXT | `EVENT` \| `FLOW` \| `COMMON` \| `USER` \| `ANOMALY` \| `BEHAVIORAL` \| `THRESHOLD` |
| owner | TEXT | |
| origin | TEXT | e.g. `SYSTEM` (IBM default) vs `USER` (custom) |
| object_type | TEXT NOT NULL DEFAULT `'RULE'` | `'RULE'` \| `'BUILDING_BLOCK'` — derived from `is_building_block` |
| building_block_subtype | TEXT | e.g. `HostDefinition`, `CategoryDefinition` — parsed from the `"BB:<Subtype>:"` name prefix, only set when object_type = BUILDING_BLOCK |
| enabled | BOOLEAN | |
| linked_rule_identifier | TEXT | |
| created_at | TIMESTAMPTZ | from `creation_date` (epoch ms) |
| updated_at | TIMESTAMPTZ | from `modification_date` (epoch ms) |
| raw_json | JSONB | full original payload, including `rule_xml` |
| synced_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |

UNIQUE (customer_id, qradar_rule_id) — upsert target for re-ingestion.

> **Not a column here on purpose:** "last triggered" info. It doesn't exist on this endpoint at all — it's derived by joining to `rule_offense_contributions` (see `rule_summary` below), not duplicated as a column.

> **BB references inside a rule's logic** show up embedded in `raw_json.rule_xml` as `<userSelection>{identifier}</userSelection>` — that's how `rule_building_blocks` gets populated (parsed separately, not stored as a column here).

### `rules_reference`
Ground truth from `GET /analytics/rules` (JSON). Used only to validate `rules`. **Confirmed same shape as `building_blocks_reference`** — both endpoints return rules/BBs mixed together, unflagged.

| Column | Type | Notes |
|---|---|---|
| id | SERIAL PK | |
| customer_id | INTEGER FK → customers.id | |
| qradar_rule_id | BIGINT NOT NULL | |
| identifier | TEXT, indexed | |
| name | TEXT | |
| raw_json | JSONB | |
| synced_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |

UNIQUE (customer_id, qradar_rule_id)

### `building_blocks_reference`
Ground truth from `GET /analytics/building_blocks` (JSON). **Confirmed these rows are literally the same underlying objects** as the `is_building_block=true` subset of `rules_with_data` (matching `id` + `identifier` in both, verified against real data). Kept as a separate table purely for cross-validation.

| Column | Type | Notes |
|---|---|---|
| id | SERIAL PK | |
| customer_id | INTEGER FK → customers.id | |
| qradar_rule_id | BIGINT NOT NULL | same numeric ID as the matching `rules` row |
| identifier | TEXT, indexed | |
| name | TEXT | |
| raw_json | JSONB | |
| synced_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |

UNIQUE (customer_id, qradar_rule_id)

### `rule_offense_contributions`
Ingested from `GET /analytics/rules_offense_contributions` (**JSON** — also corrected from an early XML assumption).

| Column | Type | Notes |
|---|---|---|
| id | SERIAL PK | |
| customer_id | INTEGER FK → customers.id | |
| rule_id | INTEGER NOT NULL, FK → rules.id, ON DELETE CASCADE | our internal FK — resolved from `qradar_rule_id` at ingestion time |
| qradar_contribution_id | BIGINT NOT NULL | the API's own `id` — dedup key |
| qradar_rule_id | BIGINT | the API's `rule_id` — CONFIRMED same numeric space as `rules.qradar_rule_id` |
| rule_name | TEXT | |
| rule_type | TEXT | |
| offense_id | TEXT | |
| event_count | INTEGER | |
| first_event_epoch_ms / last_event_epoch_ms | BIGINT | raw epoch-ms as QRadar sends it |
| first_event_at / last_event_at | TIMESTAMPTZ | converted from the above |
| raw_json | JSONB | |
| synced_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |

UNIQUE (customer_id, qradar_contribution_id) — upsert target.

### `mitre_mappings`
From the Use Case Manager app proxy:
`GET /console/plugins/app_proxy:UseCaseManager_Service/api/mitre/mitre_coverage/{identifier}`

**Confirmed: one HTTP call per rule** (keyed by `rules.identifier`), not
one bulk call. Response is nested (`{rule_name: {mapping: {tactic_id:
{techniques: {...}}}}}`) and gets flattened into one row per
(rule, tactic, technique) during ingestion.

| Column | Type | Notes |
|---|---|---|
| id | SERIAL PK | |
| customer_id | INTEGER FK → customers.id | |
| rule_id | INTEGER, FK → rules.id, ON DELETE CASCADE | nullable — null only if lookup by identifier fails |
| tactic_id | TEXT NOT NULL DEFAULT `''` | e.g. `TA0006` |
| tactic | TEXT | e.g. `Credential Access` |
| technique_id | TEXT NOT NULL DEFAULT `''` | e.g. `T1030`, or `T1078.004` for a sub-technique |
| technique_name | TEXT | e.g. `Steal or Forge Kerberos Tickets` |
| raw_json | JSONB | full `mitre_coverage` payload for this rule |
| synced_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |

UNIQUE (rule_id, tactic_id, technique_id).

> **Why `technique_id`/`tactic_id` default to `''` instead of `NULL`:** a tactic can apply with zero specific techniques (an empty `techniques: {}` in the real payload — e.g. `"Discovery"` with nothing under it). That still needs its own row (partial coverage), with `technique_id = ''`. Postgres treats `NULL != NULL` in unique constraints, which would silently break `ON CONFLICT` deduplication for these tactic-only rows on repeated ingestion. Empty string is a real, comparable value, so the constraint (and re-run dedup) actually works.

### `rule_building_blocks`
Building blocks referenced inside a rule's `rule_xml` (as `<userSelection>{identifier}</userSelection>`) — extraction not yet implemented, table exists but is currently unpopulated.

| Column | Type | Notes |
|---|---|---|
| id | SERIAL PK | |
| rule_id | INTEGER NOT NULL, FK → rules.id, ON DELETE CASCADE | |
| bb_id | TEXT NOT NULL, indexed | the referenced BB's `identifier`, as it appears in `rule_xml` |
| raw_xml_snippet | TEXT | the specific `<userSelection>` fragment |
| synced_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |

### `validation_results`
Generalized cross-check results, covering both the rules pipeline and the building-blocks pipeline. Not yet populated — the actual comparison logic (rules vs. rules_reference, BB rows vs. building_blocks_reference) hasn't been written yet.

| Column | Type | Notes |
|---|---|---|
| id | SERIAL PK | |
| customer_id | INTEGER FK → customers.id | |
| entity_type | TEXT NOT NULL, indexed | `'rule'` \| `'building_block'` |
| entity_ref | TEXT NOT NULL, indexed | qradar_rule_id or identifier |
| check_type | TEXT NOT NULL | e.g. `'exists_in_reference'` |
| status | TEXT NOT NULL | `'pass'` \| `'fail'` \| `'missing'` |
| details | TEXT | |
| checked_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |

### `sync_runs`
Audit trail — one row per ingestion run, per endpoint (see `scripts/ingest.py`).

| Column | Type | Notes |
|---|---|---|
| id | SERIAL PK | |
| customer_id | INTEGER FK → customers.id | |
| endpoint | TEXT NOT NULL | e.g. `rules_with_data`, `mitre_coverage` |
| started_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |
| finished_at | TIMESTAMPTZ | |
| status | TEXT | `'success'` \| `'partial'` \| `'error'` |
| records | INTEGER | rows upserted this run |
| error | TEXT | |

---

## `rule_summary` (VIEW — the consolidated table)

Not a physical table — a live SQL view that joins `rules` with the most
recent `rule_offense_contributions` row and aggregated `mitre_mappings`
per rule. Always reflects current data with no separate refresh step.
Your Svelte frontend (and the `/rules` API) reads from this directly.

```sql
CREATE OR REPLACE VIEW rule_summary AS
SELECT
    r.id, r.customer_id, r.qradar_rule_id, r.identifier, r.name,
    r.object_type, r.building_block_subtype, r.type, r.enabled,
    r.owner, r.origin, r.created_at, r.updated_at,
    loc.last_event_at,
    loc.event_count       AS last_event_count,
    loc.offense_id         AS last_offense_id,
    COALESCE(mitre_agg.tactics, ARRAY[]::text[])        AS tactics,
    COALESCE(mitre_agg.techniques, ARRAY[]::text[])     AS techniques,
    COALESCE(mitre_agg.sub_techniques, ARRAY[]::text[]) AS sub_techniques
FROM rules r
LEFT JOIN LATERAL (
    SELECT last_event_at, event_count, offense_id
    FROM rule_offense_contributions
    WHERE rule_id = r.id
    ORDER BY last_event_at DESC NULLS LAST
    LIMIT 1
) loc ON true
LEFT JOIN LATERAL (
    SELECT
        array_agg(DISTINCT tactic) FILTER (WHERE tactic IS NOT NULL AND tactic != '') AS tactics,
        array_agg(DISTINCT split_part(technique_id, '.', 1))
            FILTER (WHERE technique_id IS NOT NULL AND technique_id != '') AS techniques,
        array_agg(DISTINCT technique_id)
            FILTER (WHERE technique_id LIKE '%.%') AS sub_techniques
    FROM mitre_mappings
    WHERE rule_id = r.id
) mitre_agg ON true;
```

| Column | Type | Notes |
|---|---|---|
| tactics | TEXT[] | distinct tactic names for this rule, `[]` if none |
| techniques | TEXT[] | distinct **base** technique IDs (e.g. `T1078`, sub-technique suffix stripped) |
| sub_techniques | TEXT[] | distinct **full** sub-technique IDs (e.g. `T1078.004`) — only entries containing a `.` |
| last_event_at | TIMESTAMPTZ, nullable | most recent `rule_offense_contributions.last_event_at` for this rule — `NULL` if the rule has never contributed to an offense, not `''` |

Splitting `T1078.004` into `techniques: ['T1078']` and `sub_techniques: ['T1078.004']` (rather than one flat list) was a deliberate ask — confirmed working against real MITRE data during testing.

---

## Ingestion flow (implemented)

```
QRadarClient (app/services/qradar_client.py)
  fetch_rules_with_data() / fetch_rules() / fetch_building_blocks()
  fetch_rules_offense_contributions() / fetch_mitre_mapping(identifier)
        │
        ▼
scripts/ingest.py         — fetch live, push straight to Postgres, log sync_runs
scripts/test_pull_data.py — fetch live, save to logs/raw_pulls/ for inspection (debug only)
scripts/run_ingestion.py  — read from a saved logs/raw_pulls/ dir, push to Postgres
        │
        ▼
app/services/rule_ingest.py                 → upsert_rules, upsert_rules_reference, upsert_building_blocks_reference
app/services/offense_contribution_ingest.py → upsert_offense_contributions
app/services/mitre_mapping_ingest.py        → upsert_mitre_mappings
        │
        ▼
Postgres tables (all upsert on their unique constraint — re-running
ingestion updates existing rows, never creates duplicates; verified by
running twice and diffing row counts)
        │
        ▼
rule_summary (view) → app/api/rules.py (GET /rules, GET /rules/{id}) → Svelte frontend
```

## Not yet built
- `rule_building_blocks` extraction (parsing `<userSelection>` tags out of `rule_xml`)
- `validation_results` population (the actual rules-vs-reference, BB-vs-reference comparison logic)
- Scheduling/automation for `scripts/ingest.py` (currently manual, on-demand)
