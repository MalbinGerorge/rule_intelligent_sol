# Backend high-level design

Rule Intelligent Sol analyzes IBM QRadar detection rules for multiple customers. It pulls each customer's rules, building blocks, MITRE mappings and log sources from QRadar, parses them into Postgres, builds a dependency graph in Neo4j, and adds AI features on top: natural-language questions about the rules, automated rule investigations, coverage-gap analysis, Sigma rule generation and cross-customer similarity search.

This document describes the backend **as it is in the code today**. The import edges and external connections below were measured from the source (import graph via `grimp`), not drawn from intent. The target design and its reasoning are in [ADR 0001](../adr/0001-modular-monolith-structure.md); the API contract is in [`docs/api/`](../api/README.md).

## 1. Runtime: processes and connections

Three kinds of process run from the same codebase. They never call each other directly: the API hands work to the worker through Redis, and the worker reports back by writing to Postgres.

```mermaid
flowchart LR
    fe["Frontend<br/>(SvelteKit today, React planned)"]
    subgraph ours["Our processes (one codebase)"]
        api["API<br/>uvicorn app.api.main:app"]
        worker["Celery worker<br/>celery -A app.workers.celery_app"]
        cli["CLI scripts<br/>scripts/*.py (run by hand)"]
    end
    redis[("Redis<br/>task queue")]
    pg[("Postgres<br/>source of truth")]
    neo[("Neo4j<br/>rule graph")]
    chroma[("Chroma + local<br/>embedding models")]
    azure(["Azure OpenAI"])
    qradar(["QRadar consoles<br/>(one per customer)"])

    fe -- "HTTP/JSON, SSE" --> api
    api -- "enqueue .delay()" --> redis
    redis -- "deliver task" --> worker
    api -- "read/write" --> pg
    api -- "Cypher (read)" --> neo
    api -- "similarity search" --> chroma
    api -- "assistant Q&A" --> azure
    worker -- "job status + results" --> pg
    worker -- "embeddings" --> chroma
    worker -- "investigations, Sigma" --> azure
    worker -- "AQL searches" --> qradar
    cli -- "pull rules, offenses, log sources" --> qradar
    cli -- "upsert" --> pg
    cli -- "rebuild graph" --> neo
```

### Who connects to what

| | Redis | Postgres | Neo4j | Chroma + models | Azure OpenAI | QRadar |
|---|---|---|---|---|---|---|
| **Frontend** | – | – | – | – | – | – |
| **API** | enqueue | ✔ | ✔ | ✔ similarity search | ✔ assistant only | **–** |
| **Worker** | consume | ✔ | – (rule-chain context reads Postgres) | ✔ embedding batches | ✔ | ✔ AQL in investigations |
| **CLI scripts** | – | ✔ | ✔ graph build | – | ✔ simulator only | ✔ ingestion, simulator |

The frontend only ever talks to the API. The API never calls QRadar; every QRadar call happens in the worker or a CLI script.

## 2. Code: layers and import direction

An arrow means "imports". Every arrow points down; `import-linter` enforces this in CI (contracts in `pyproject.toml`). Edges to `app.core` are omitted because every layer may use it.

```mermaid
flowchart TB
    subgraph L1["api"]
        api["api<br/>routes · schemas · deps"]
    end
    subgraph L2["workers"]
        tasks["workers.tasks"]
    end
    subgraph L3["services"]
        gap["services.gap_analysis"]
    end
    subgraph L4["ai | ingestion  (same level, independent)"]
        subgraph AI["ai"]
            assistant["agents.assistant"]
            analyzer["agents.rule_analyzer"]
            simulator["agents.simulator"]
            sigma["sigma"]
            retrieval["retrieval"]
            context["context"]
            llm["llm"]
        end
        subgraph ING["ingestion"]
            jobs["jobs"]
            parsers["parsers"]
        end
    end
    subgraph L5["repositories"]
        repos["repositories<br/>rules · graph"]
    end
    subgraph L6["integrations"]
        qradar["qradar"]
        neo4j["neo4j"]
    end
    subgraph L7["db · core"]
        db["db<br/>session · models"]
        core["core<br/>config · logging · exceptions"]
    end

    api --> tasks & gap & assistant & retrieval & repos & neo4j & db
    tasks --> analyzer & sigma & retrieval & llm & repos & qradar & db
    gap --> retrieval
    analyzer --> context & llm & qradar
    simulator --> qradar
    sigma --> context & llm
    context --> repos
    jobs --> parsers & qradar
```

| Layer | Contains | Talks to |
|---|---|---|
| `api` | FastAPI app, `v1/routes`, `v1/schemas`, dependencies | everything below |
| `workers` | Celery app; tasks for investigations, Sigma, embeddings | ai, repositories, integrations, db |
| `services` | gap analysis (MITRE, log sources) | ai.retrieval |
| `ai` | LLM provider, three agents, Sigma generation, retrieval, rule-chain context | repositories, integrations |
| `ingestion` | QRadar → Postgres jobs, Postgres → Neo4j graph build, XML/condition/response parsers | integrations |
| `repositories` | read queries for rules (Postgres) and the graph (Neo4j) | db |
| `integrations` | QRadar HTTP client + per-customer factory, Neo4j driver | core |
| `db`, `core` | SQLAlchemy base/session/models; config, logging, exceptions | – |

## 3. What is deliberately not connected

These pairs have no imports between them. The first two groups are enforced in CI; the rest are true today and should stay true.

| Not connected | Why it matters | Enforced |
|---|---|---|
| Any lower layer → a higher layer (e.g. `ai` → `api`, `db` → `services`) | Business logic never depends on HTTP; models never depend on features | ✔ layers contract |
| `agents.assistant` ↔ `agents.rule_analyzer` ↔ `agents.simulator` | Three separate products; shared code goes in `ai.llm` / `ai.context` | ✔ independence contract |
| `ai` ↔ `ingestion` | Ingestion is deterministic and must keep working without any LLM | ✔ same layer, `\|` |
| `api` → `ingestion` | No HTTP endpoint triggers a QRadar sync; ingestion runs from CLI scripts | observed |
| `workers` → `api` | Workers report results through Postgres, never by calling the API | ✔ layers contract |
| `api` → `integrations.qradar` | Request handlers never wait on a QRadar console | observed |

## 4. Key flows

### Asynchronous investigation (Rule Analyzer)

```mermaid
sequenceDiagram
    autonumber
    participant FE as Frontend
    participant API as API
    participant PG as Postgres
    participant R as Redis
    participant W as Worker
    participant X as QRadar + Azure OpenAI
    FE->>API: POST /rule-analyzer/rules/{id}/investigate
    API->>PG: insert investigation (status = running)
    API->>R: run_investigation_task.delay(...)
    API-->>FE: { id, status: running }  (milliseconds)
    R->>W: deliver task
    W->>X: AQL searches, LLM reasoning (30 s – 2+ min)
    W->>PG: update investigation (completed / failed + report)
    loop every ~2 s until not running
        FE->>API: GET /rule-analyzer/investigations/{id}
        API->>PG: read investigation
        API-->>FE: status, report
    end
```

Sigma generation and embedding batches follow the same pattern; their progress is also available as a server-sent event stream (`GET …/stream`).

### Synchronous reads

`GET /rules`, `/graph/*`, `/customers`, the gap analyses and similarity search answer within the request: route → repository / service → Postgres, Neo4j or Chroma → response schema.

### Ingestion (by hand today)

`scripts/ingest.py` → `scripts/sync_bb_relationships.py` → `scripts/build_graph.py`, per customer: pull from QRadar, upsert into Postgres, parse rule XML into conditions/building-block links/responses, rebuild that customer's slice of the Neo4j graph.

## 5. API contract

22 endpoints under six tags (`rules`, `graph`, `agent`, `rule-analyzer`, `recommendations`, `customers`) plus `/health`. The contract is generated from the code into [`docs/api/openapi.json`](../api/openapi.json) with a readable [reference](../api/README.md); CI fails if a route or schema changes without regenerating it.

## 6. Known gaps (next steps)

| Gap | Where | Planned fix |
|---|---|---|
| No authentication or tenant authorization; tenant is a URL/query parameter | `api` | OIDC/JWT + user↔customer membership |
| `agents.assistant` builds its own Azure client instead of using `ai.llm` | `ai.agents.assistant.nodes` | Route through the LLM provider interface |
| `core` imports FastAPI (`exceptions.py`) | `core` | Keep HTTP mapping in `api/exception_handlers.py` only |
| Raw SQL in routes, tasks and agents (35 modules) | several | Repositories, table by table, before the DB redesign |
| ORM models and the database differ (`alembic check`: ~60 differences; some tables have no model) | `db.models` | Database redesign |
| One worker consumes every task; ingestion is manual | `workers` | `llm` and `ingestion` queues, Celery beat schedule |
| Auto-generated operation IDs (e.g. `get_health_metrics_rules_metrics_get`); SSE endpoints untyped | API contract | Explicit operation IDs and stream event schemas |
| URLs are not versioned although code lives in `api/v1` | API contract | `/api/v1` prefix together with the new frontend |
