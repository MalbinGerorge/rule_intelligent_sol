# API reference

> Generated from the FastAPI app by `scripts/export_openapi.py` — do not edit.
> The machine-readable contract is [`openapi.json`](openapi.json).

**Rule Intelligent Sol** · version 0.1.0 · OpenAPI 3.1.0

## rules

| Method | Path | Parameters | Request body | Response (200) |
|---|---|---|---|---|
| `GET` | `/rules` | `customer_id` (query), `object_type`? (query), `limit`? (query), `offset`? (query) | – | `RuleListResponse` |
| `GET` | `/rules/metrics` | `customer_id` (query) | – | `RuleHealthMetrics` |
| `GET` | `/rules/{rule_id}` | `rule_id` (path) | – | `RuleSummary` |

## graph

| Method | Path | Parameters | Request body | Response (200) |
|---|---|---|---|---|
| `GET` | `/graph/rules/search/by-field` | `field` (query), `customer_id` (query) | – | list of `FieldSearchResult` |
| `GET` | `/graph/rules/search/by-technique` | `technique_id` (query), `customer_id` (query) | – | list of `TechniqueSearchResult` |
| `GET` | `/graph/building-blocks/{identifier}/dependents` | `identifier` (path), `customer_id` (query) | – | list of `BuildingBlockDependent` |
| `GET` | `/graph/rules/{rule_id}` | `rule_id` (path) | – | `RuleGraphDetail` |

## agent

| Method | Path | Parameters | Request body | Response (200) |
|---|---|---|---|---|
| `POST` | `/agent/ask` | – | `AgentAskRequest` | `AgentAskResponse` |

## rule-analyzer

| Method | Path | Parameters | Request body | Response (200) |
|---|---|---|---|---|
| `POST` | `/rule-analyzer/rules/{rule_id}/investigate` | `rule_id` (path) | – | `InvestigationCreateResponse` |
| `GET` | `/rule-analyzer/investigations/{investigation_id}` | `investigation_id` (path) | – | `InvestigationDetail` |
| `GET` | `/rule-analyzer/rules/{rule_id}/investigations` | `rule_id` (path), `limit`? (query), `offset`? (query) | – | `InvestigationListResponse` |

## recommendations

| Method | Path | Parameters | Request body | Response (200) |
|---|---|---|---|---|
| `POST` | `/recommendations/customers/{customer_name}/sigma/generate` | `customer_name` (path) | `SigmaGenerationRequest` | `SigmaGenerationJobCreateResponse` |
| `GET` | `/recommendations/sigma-jobs/{job_id}` | `job_id` (path) | – | `SigmaGenerationJobDetail` |
| `GET` | `/recommendations/sigma-jobs/{job_id}/stream` | `job_id` (path) | – | stream (`text/event-stream`) |
| `GET` | `/recommendations/customers/{customer_name}/mitre-gaps` | `customer_name` (path) | – | list of `MitreGap` |
| `GET` | `/recommendations/customers/{customer_name}/log-source-gaps` | `customer_name` (path) | – | list of `LogSourceGap` |
| `POST` | `/recommendations/embeddings/generate` | – | – | `EmbeddingJobCreateResponse` |
| `GET` | `/recommendations/embeddings-jobs/{job_id}` | `job_id` (path) | – | `EmbeddingJobDetail` |
| `GET` | `/recommendations/embeddings-jobs/{job_id}/stream` | `job_id` (path) | – | stream (`text/event-stream`) |
| `POST` | `/recommendations/customers/{customer_name}/similarity-search` | `customer_name` (path) | `SimilaritySearchRequest` | `SimilaritySearchResult` |

## customers

| Method | Path | Parameters | Request body | Response (200) |
|---|---|---|---|---|
| `GET` | `/customers` | – | – | `CustomerListResponse` |

## other

| Method | Path | Parameters | Request body | Response (200) |
|---|---|---|---|---|
| `GET` | `/health` | – | – | `object` |

## Schemas

- **`AgentAskRequest`**: `question`, `customer_id`
- **`AgentAskResponse`**: `status`, `query`?, `rows`?, `retried`?, `question`?, `reason`?, `error`?
- **`BuildingBlockDependent`**: `rule_id`, `identifier`, `name`, `threshold`
- **`CustomerListResponse`**: `customers`
- **`CustomerSummary`**: `id`, `name`
- **`EmbeddingJobCreateResponse`**: `id`, `status`, `total_representations`
- **`EmbeddingJobDetail`**: `id`, `status`, `total_representations`, `processed_representations`, `failed_representations`, `failed_details`?, `error`?, `created_at`, `finished_at`?
- **`FieldSearchResult`**: `rule_id`, `identifier`, `name`, `operator`, `values`
- **`HTTPValidationError`**: `detail`?
- **`InvestigationCreateResponse`**: `id`, `status`
- **`InvestigationDetail`**: `id`, `rule_id`, `customer_id`, `status`, `error`?, `chain_analysis`?, `final_report`?, `rendered_report`?, `trace`?, `tool_calls_made`?, `created_at`
- **`InvestigationListItem`**: `id`, `status`, `tool_calls_made`?, `created_at`
- **`InvestigationListResponse`**: `items`, `total`, `limit`, `offset`
- **`LogSourceGap`**: `log_source_type_name`, `qradar_type_id`, `peer_customer_names`, `suggested_rules`
- **`MitreGap`**: `technique_id`, `technique_name`, `tactic_names`, `is_subtechnique`, `peer_customer_names`, `suggested_rules`
- **`PeerRuleSuggestion`**: `source_customer_name`, `rule_id`, `title`, `description`, `level`, `detection`, `tags`, `mitre_source`?, `mitre_confidence`?, `required_log_source_types`?, `customer_has_required_log_source`?, `similarity_score`?, `embedding_score`?
- **`RuleGraphDetail`**: `rule`, `references`, `conditions`, `log_sources`, `mitre`, `followed_by`
- **`RuleHealthMetrics`**: `total_rules`, `total_building_blocks`, `enabled_rules`, `disabled_rules`, `enabled_triggered`, `enabled_not_triggered`
- **`RuleListResponse`**: `count`, `results`
- **`RuleSummary`**: `id`, `customer_id`, `qradar_rule_id`, `identifier`, `name`, `object_type`, `building_block_subtype`, `type`, `enabled`, `owner`, `origin`, `created_at`, `updated_at`, `last_event_at`, `last_event_count`, `last_offense_id`, `tactics`, `techniques`, `sub_techniques`
- **`SigmaGenerationJobCreateResponse`**: `id`, `status`, `total_rules`
- **`SigmaGenerationJobDetail`**: `id`, `customer_id`, `status`, `requested_rule_names`?, `total_rules`, `processed_rules`, `failed_rules`, `failed_rule_details`?, `error`?, `created_at`, `finished_at`?
- **`SigmaGenerationRequest`**: `rule_names`?
- **`SimilaritySearchRequest`**: `query`
- **`SimilaritySearchResult`**: `results`, `excluded_low_relevance`
- **`TechniqueSearchResult`**: `rule_id`, `identifier`, `name`
- **`ValidationError`**: `loc`, `msg`, `type`, `input`?, `ctx`?
