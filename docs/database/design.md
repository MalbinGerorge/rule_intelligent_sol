# Database design

- **Status:** Proposed (phase 0) — for review before any migration is written
- **Date:** 2026-10-06
- **Diagrams:** current schema [keys](current_schema_keys.mmd) · [full](current_schema_full.mmd) · [target](target_schema.mmd) (paste into https://mermaid.live)

## 1. Why redesign

The current schema (22 tables, 1 view) grew one feature at a time. Measured on the development database:

| Problem | Evidence |
|---|---|
| Duplicate tables | All 2,627 `rules_reference` rows and all 1,154 `building_blocks_reference` rows already exist in `rules`; they only feed a validation job whose `validation_results` table is empty |
| Hand-refreshed derived table | `rule_mitre_unified` is rebuilt by `TRUNCATE` + insert from a script; stale between runs |
| Four job tables | `sigma_generation_jobs`, `embedding_jobs`, `investigation_reports` (status part), `sync_runs` each track status/progress/error differently; 2 embedding jobs are stuck at `running` |
| No tenant isolation in the database | Row level security off on all tables; `rule_conditions`, `rule_building_blocks`, `rule_responses` have no `customer_id` |
| No value checks | 0 CHECK constraints; status columns accept any text; `investigation_reports.status` defaults to `'completed'` |
| Mass deletion by accident | All 21 foreign keys are `ON DELETE CASCADE`: deleting one customer row deletes all of its data |
| Missing keys | `rule_mitre_unified` has no primary key and no foreign keys (migration 0031's `add_column(primary_key=True)` never created the constraint); building block, log source and log source type references are unenforced |
| Inconsistent data | `mitre_mappings.tactic_id` holds IDs (`TA0002`, 2,395 rows) **and** names (`Execution`, 1,127 rows); 704 rows use `''` instead of NULL for "no technique" |
| Half-built vector search | `rule_yaml_representations.embedding` is `vector(384)` but the model (Qwen3-Embedding-0.6B) produces 1024 dimensions; 0 of 1,813 rows populated — vectors live in Chroma |
| Code ≠ database | `alembic check` reports ~60 differences between ORM models and the real schema |

## 2. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | Deleting a customer is `RESTRICT`ed; customers are **deactivated** (`deactivated_at`), purging is an explicit, separate operation | No accidental mass deletion |
| D2 | Rules removed in QRadar are **kept** and marked `deleted_in_qradar_at`; every sync sets `last_seen_at` | Investigations, Sigma output and offense history stay meaningful |
| D3 | Row level security is **deferred** to a later phase (after authentication). Until then isolation comes from `customer_id` on every tenant table and composite foreign keys (phase 4) | Enforced cross-customer integrity now; RLS added later without schema changes, because every tenant table already carries `customer_id` |
| D4 | pgvector in Postgres replaces Chroma | One less service; vectors live with their rows; tenant filtering in SQL; removes 4 accepted Chroma CVEs |
| D5 | Postgres schemas group tables by role: `tenancy`, `catalog`, `qradar`, `analysis`, `ops` | A table's purpose is visible in its name; permissions can be granted per schema |
| D6 | Scale target: up to ~20 customers in 1–2 years | Composite keys + indexes are sufficient; no partitioning now |
| D7 | Keep all history; no automatic deletion | `created_at` everywhere so a retention policy can be added without schema changes |
| D8 | QRadar `-1` ("not restricted") is stored as `NULL` meaning "any" | 4,471 of 4,473 apparent orphans in event properties are `-1` |
| D9 | References QRadar makes to objects we may not have are kept as **QRadar ID + nullable resolved FK** | Integrity where the target exists, no data loss where it doesn't, gaps become queryable (e.g. All Cargo's 8 unresolved building blocks `38750177`–`38750184`) |

## 3. Conventions (apply to every table)

**Keys**
- `id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY`, except 1:1 and pure link tables, which use their natural composite key.
- QRadar's own identifiers are kept as natural keys: `UNIQUE (customer_id, qradar_<thing>_id)`.

**Tenancy**
- Every tenant table has `customer_id bigint NOT NULL` → `tenancy.customers(id) ON DELETE RESTRICT`.
- Child rows of a rule reference it with a **composite foreign key** `(customer_id, rule_id) → qradar.rules (customer_id, id)`, backed by `UNIQUE (customer_id, id)` on `qradar.rules`. A row can never point at another customer's rule — enforced by the database, not by code.

**`ON DELETE` policy**
| Relationship | Rule |
|---|---|
| customer → its data | `RESTRICT` (D1) |
| rule → its own parts (conditions, responses, dependencies, MITRE mappings) | `CASCADE` (one aggregate) |
| rule → history and derived output (offense contributions, Sigma rules, investigations) | `RESTRICT` (rules are soft-deleted per D2, so this never blocks normal operation) |
| resolved references into QRadar data (D9) | `SET NULL (<that column>)` — the QRadar ID column is kept |

**Values**
- Fixed value sets are `text` + `CHECK (col IN (…))`, not Postgres enums (adding a value is a one-line migration).
- Counters `CHECK (>= 0)`; time ranges `CHECK (end >= start)`; identifiers with a known format get a regex `CHECK` (MITRE IDs, UUIDs as `uuid` type).
- `NULL` means "unknown / not applicable"; empty strings are never used as a placeholder.
- JSON columns `CHECK (jsonb_typeof(col) = 'object' | 'array')` for their expected shape. Original QRadar payloads are kept in `raw_json` (it is the audit trail when parsing logic changes).

**Timestamps**
- `timestamptz` only. `created_at NOT NULL DEFAULT now()` everywhere; `updated_at` maintained by one shared trigger function on mutable tables.

**Indexes**
- Every foreign key column (or composite FK) is indexed; additional indexes only for real queries; no index that duplicates a unique constraint (two exist today and are dropped).

## 4. Target schema

18 tables + 2 views (from 22 tables + 1 view), grouped by purpose. Diagram: [target_schema.mmd](target_schema.mmd).

### `tenancy` — who the customers are
| Table | Notes |
|---|---|
| `customers` | `name UNIQUE`, `CHECK` not blank; `verify_ssl NOT NULL DEFAULT false` (unchanged; agreed to keep as is for now); `deactivated_at` replaces `active` |
| `customer_credentials` | 1:1 with customer (`customer_id` PK), `token_encrypted bytea` (pgcrypto); the only `CASCADE` from customers — credentials are part of the customer |

Authentication will add `users` and `customer_memberships` here later.

### `catalog` — global reference data (no tenant)
| Table | Notes |
|---|---|
| `mitre_tactics` | `tactic_id` PK `CHECK ^TA\d{4}$`, `name UNIQUE` — also used to normalize the 1,127 rows that store tactic names |
| `mitre_techniques` | `technique_id` PK `CHECK ^T\d{4}(\.\d{3})?$`; `parent_technique_id` self-FK, `CHECK` set iff sub-technique; `status IN ('active','deprecated','revoked')` so historical mappings stay valid |
| `mitre_technique_tactics` | many-to-many technique ↔ tactic (replaces the `tactic_names text[]` array) |

The catalog sync currently misses current techniques such as T1562 (Impair Defenses) and T1070.001 — 9 techniques used in confirmed mappings are absent. This is fixed before the technique foreign keys are added.

### `qradar` — each customer's QRadar content, mirrored
| Table | From | Key constraints |
|---|---|---|
| `rules` | `rules` | `UNIQUE (customer_id, qradar_rule_id)`, `UNIQUE (customer_id, identifier)`, `UNIQUE (customer_id, id)`; `object_type IN ('RULE','BUILDING_BLOCK')`; `name`, `enabled`, `raw_json NOT NULL`; `first_seen_at`, `last_seen_at`, `deleted_in_qradar_at` (D2); trigram index on `name` for search |
| `rule_dependencies` | `rule_building_blocks` | PK `(rule_id, building_block_identifier)` — a set of edges (16 rules reference the same building block twice today); `building_block_id` resolved FK, `NULL` = unresolved (D9), `CHECK <> rule_id` |
| `rule_conditions` | `rule_conditions` | `UNIQUE (rule_id, sequence_order)`, `sequence_order >= 0`, `structured_data` is an object |
| `rule_responses` | `rule_responses` | PK `rule_id` (1:1, matches data); severity/credibility/relevance `CHECK BETWEEN 0 AND 10`; limiter counts `>= 0` |
| `rule_mitre_mappings` | `mitre_mappings` | `tactic_id NOT NULL` → catalog; `technique_id` → catalog, `NULL` = tactic-level mapping; `UNIQUE NULLS NOT DISTINCT (rule_id, tactic_id, technique_id)` (Postgres 16) |
| `offense_contributions` | `rule_offense_contributions` | `UNIQUE (customer_id, qradar_contribution_id)`; `event_count >= 0`; `first_event_at <= last_event_at`; drops `first/last_event_epoch_ms`, `rule_name`, `rule_type` (exact copies of other columns / of the rule; originals stay in `raw_json`); index `(customer_id, rule_id, last_event_at DESC)` |
| `log_source_types` | `log_source_types_reference` | `UNIQUE (customer_id, qradar_type_id)`, `name NOT NULL` |
| `log_sources` | `log_sources_reference` | `UNIQUE (customer_id, qradar_log_source_id)`; `qradar_type_id` + resolved `log_source_type_id` (D9); `average_eps >= 0` |
| `event_property_expressions` | `custom_event_property_expressions` | `expression_type IN ('regex','json','aql','leef','cef')`; QRadar IDs with `-1` → `NULL` (D8) + resolved FKs to log sources / types (D9); `capture_group >= 0` |

View `rule_summary`: same columns as today, rebuilt on the new tables, without the empty `validation_results`.

### `analysis` — what the application generates
| Table | From | Key constraints |
|---|---|---|
| `sigma_rules` | `rule_yaml_representations` | `sigma_id uuid UNIQUE`; `UNIQUE (customer_id, rule_id, role)`; `role`, `status`, `level` `CHECK` value sets (match all 1,813 rows today); `correlation` present iff `role = 'correlation'` (holds for all rows); `embedding vector(1024)` + `embedding_model` + `embedded_at` set together; HNSW index (cosine) |
| `inferred_rule_techniques` | `rule_yaml_representations.mitre_techniques_inferred` (JSON array) | PK `(sigma_rule_id, technique_id)`; `confidence IN ('low','medium','high')`; technique → catalog |
| `investigations` | `investigation_reports` (result columns) | `job_id UNIQUE` → `ops.jobs`; report columns; `tool_calls_made >= 0`. Status/error/timing move to the job |

View `rule_techniques`: confirmed mappings `UNION ALL` inferred techniques with `source IN ('confirmed','inferred')` and `confidence`. Replaces `rule_mitre_unified`; always current.

**Cross-customer reads by design.** Similarity search and gap analysis suggest *other* customers' de-identified Sigma rules. When row level security is added (D3), this will be expressed explicitly: a read-only view exposing only the de-identified Sigma columns, with its own policy — not by disabling RLS.

### `ops` — background work
`jobs` replaces `sigma_generation_jobs`, `embedding_jobs`, `sync_runs` and the status part of `investigation_reports`:

| Column | Constraint |
|---|---|
| `job_type` | `IN ('investigation','sigma_generation','embedding','qradar_sync')` |
| `customer_id` | `NULL` only for global job types (`CHECK`) |
| `status` | `IN ('queued','running','completed','failed','cancelled')`, default `queued` |
| `params` | `jsonb NOT NULL`, object — e.g. `rule_id`, requested rule names, QRadar endpoint |
| `total_items`, `processed_items`, `failed_items` | `>= 0`, `processed + failed <= total` |
| `failure_details` | `jsonb` array of per-item errors |
| `error` | required when `status = 'failed'` |
| `created_at`, `started_at`, `finished_at`, `heartbeat_at` | ordered (`CHECK`); `finished_at` set iff status is terminal |
| `celery_task_id` | for tracing a job to its worker |

- **Stuck jobs:** workers update `heartbeat_at`; a scheduled reaper marks `running` jobs with an old heartbeat `failed`. This covers the case the code's try/except can't: a worker that crashes or is killed.
- **No duplicate runs:** partial unique indexes allow only one active job per customer for `sigma_generation` and `qradar_sync`, and one active investigation per rule.

### Removed
`rules_reference`, `building_blocks_reference`, `validation_results` (and the validation job that writes them), `rule_mitre_unified` (→ view), `sigma_generation_jobs`, `embedding_jobs`, `sync_runs` (→ `ops.jobs`), and the Chroma service.

## 5. Old → new mapping

| Current | Target | Data |
|---|---|---|
| `customers` | `tenancy.customers` | `active = false` → `deactivated_at = now()` |
| `customer_credentials` | `tenancy.customer_credentials` | as is |
| `mitre_technique_catalog` | `catalog.mitre_techniques` + `mitre_tactics` + `mitre_technique_tactics` | re-synced from MITRE (fixes missing techniques) |
| `rules` | `qradar.rules` | `first_seen_at`/`last_seen_at` from `synced_at`; `building_block_subtype` trimmed |
| `rule_building_blocks` | `qradar.rule_dependencies` | deduplicated; `customer_id` from the rule; resolve `building_block_id` |
| `rule_conditions`, `rule_responses` | `qradar.*` | add `customer_id` from the rule |
| `mitre_mappings` | `qradar.rule_mitre_mappings` | tactic names → `TA####`; `''` → `NULL` |
| `rule_offense_contributions` | `qradar.offense_contributions` | drop redundant columns |
| `log_source_types_reference`, `log_sources_reference` | `qradar.log_source_types`, `qradar.log_sources` | resolve type FK |
| `custom_event_property_expressions` | `qradar.event_property_expressions` | `-1` → `NULL`; resolve FKs |
| `rule_yaml_representations` | `analysis.sigma_rules` + `analysis.inferred_rule_techniques` | `sigma_id` → `uuid`; JSON techniques → rows; embeddings re-generated into pgvector |
| `investigation_reports` | `ops.jobs` + `analysis.investigations` | one job + one result per report |
| `sigma_generation_jobs`, `embedding_jobs`, `sync_runs` | `ops.jobs` | mapped by type; stuck `running` → `failed` |
| `rules_reference`, `building_blocks_reference`, `validation_results`, `rule_mitre_unified` | removed | duplicates / empty / derived |

## 6. Database roles (phase 4) and row level security (deferred)

| Role | Can | Used by |
|---|---|---|
| `rule_intel_owner` | owns all objects; DDL | Alembic migrations only |
| `rule_intel_app` | `SELECT/INSERT/UPDATE/DELETE` on tables, no DDL | API and workers |
| `rule_intel_readonly` | `SELECT` | support / reporting |

**Row level security, when it is added later:**

- Policies on every tenant table: `customer_id = current_setting('app.customer_id')::bigint`, with `FORCE ROW LEVEL SECURITY`.
- The application sets `app.customer_id` per transaction (`SET LOCAL`); a missing setting returns no rows instead of all rows.
- Global work (MITRE catalog sync, global jobs) runs without a customer and only touches `catalog` / `ops`.

## 7. Implementation phases

Each phase is one or a few small PRs; each leaves a working system. Every PR that changes the schema must pass, before merge:

1. **Backup first** — a fresh dump of the development database exists and has been restored once.
2. **Upgrade and downgrade** — `alembic upgrade head` and `alembic downgrade -1` both succeed on a copy of the real data, and upgrading again returns to the same schema.
3. **Data preserved** — row counts (and, where data is transformed, checksums) match before and after, with any intended changes listed in the PR.
4. **Behavior unchanged** — `pytest`, the API contract check (`export_openapi.py --check`), import contracts and CI all pass; endpoints that read the changed tables return the same results before and after.
5. **No drift** — `alembic check` reports no new differences between models and database.

| Phase | Content | Verification |
|---|---|---|
| **1. Safety net** | Backup/restore drill on dev data; `alembic check` in CI (drift can't come back); repository module for each table just before it changes | restore produces identical row counts |
| **2. Integrity on today's tables** | Bring migrations in line with the real database (3 objects exist only there, see §8); fix migration 0032's downgrade; fix data (tactic names → IDs, `''` → NULL, `-1` → NULL, catalog sync); add missing PK/FKs, CHECKs, `RESTRICT` on customers; drop 2 redundant indexes; fix job status default | every constraint validated on real data |
| **3. Consolidate** | `ops.jobs`; remove duplicate reference tables + validation job; MITRE view; `rule_dependencies` as a set | row counts / checksums old vs new |
| **4. Tenant integrity** | `customer_id` everywhere, composite FKs, database roles | tests: a row can't reference another customer's rule; the app role can't run DDL |
| **5. Namespaces + vectors** | Move tables into schemas; `vector(1024)` + HNSW; embeddings regenerated into pgvector; retire Chroma | similarity-search eval results comparable before/after |
| **6. New baseline** | Squash 32 migrations into one baseline matching the final schema | fresh database from baseline == migrated database (schema diff empty) |

## 8. Open items

- **Building blocks `38750177`–`38750184` (All Cargo):** referenced by 8 rule dependencies but absent from ingested rules; kept as unresolved references (D9) until investigated.
- **TLS verification** stays off by default (`verify_ssl = false`), as agreed; revisit when customer consoles have CA bundles.
- **Row level security** is deferred (D3); the design keeps `customer_id` on every tenant table so it can be added without schema changes.
- ~~Objects created outside migrations~~ **Resolved in phase 2a** (migration 0033): `UNIQUE (rule_id, customer_id, role)` and `UNIQUE (sigma_id)` on `rule_yaml_representations` and the `pg_trgm` extension existed only in the development database; 0033 creates them if missing.
- ~~Migration 0032's downgrade~~ **Resolved in phase 2a**: it now recreates the 0031 tables (empty), so a downgraded database can be upgraded again.
- **Embedding dimension:** 1024 per the Qwen3-Embedding-0.6B model card; confirmed against the loaded model before phase 5.
