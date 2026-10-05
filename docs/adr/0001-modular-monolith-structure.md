# ADR 0001: Layered modular monolith with multiple deployables

- **Status:** Accepted
- **Date:** 2026-10-05

## Context

The backend grew feature by feature, and the layout no longer shows how the
system works:

- Shared infrastructure lives inside features: the LLM client is in
  `rule_analyzer/` but used by `recommendations/` and `services/`; the QRadar
  client is in `services/` and used by four packages.
- Dependencies point the wrong way: `recommendations/` (business logic)
  imports from `api/schemas/` (the HTTP layer).
- One feature is spread across up to four folders (Rule Analyzer: endpoint,
  schemas, `rule_analyzer/`, `services/investigation_runner.py`).
- `services/` holds 22 unrelated modules (HTTP client, XML parsers,
  ingestion jobs, read queries, a Celery task).
- Raw SQL appears in 35 modules, including HTTP endpoints.
- Every process loads every dependency: importing the API pulls in the LLM
  libraries, and the embedding/reranker models load inside the API process.

## Decision

### 1. Code layout: layers at the top, domains inside each layer

```
app/
├── api/            HTTP only: app factory, dependencies, v1/routes, v1/schemas
├── services/       business logic (use cases)
├── ai/             llm/ (provider), agents/ (assistant, rule_analyzer, simulator),
│                   sigma/, retrieval/ (embeddings, similarity search, reranker)
├── ingestion/      QRadar → Postgres jobs, and pure parsers
├── repositories/   all database access (introduced gradually, see 3)
├── integrations/   adapters to external systems: qradar/, neo4j/, vectorstore/
├── workers/        Celery app and thin task wrappers
├── db/             SQLAlchemy base, session, ORM models
└── core/           domain-free shared code: config, logging, exceptions
```

### 2. Dependency rule

Imports only point downward:

```
api, workers  →  services  →  ai, repositories, integrations  →  db, core
```

- Nothing imports `api/`; business logic never knows about HTTP.
- Routes are thin: validate input, call a service, return a schema.
- `core/` contains no domain logic and imports nothing from the layers above.

This will be enforced in CI with `import-linter`.

### 3. Repositories are introduced per table, just before its redesign

The restructure only moves files. SQL moves into `repositories/` table by
table, immediately before that table is redesigned, starting with
`investigation_reports`. This keeps the restructure verifiable as a pure move
and puts the repository work exactly where it pays off.

### 4. Interfaces only at real boundaries

Code depends on an interface rather than a concrete client where an
implementation is likely to change, needs a fake for tests, or must be
isolated:

- LLM provider (vendor/model changes; no live LLM calls in CI)
- Vector store (Chroma is planned to be replaced by pgvector)
- QRadar client (recorded responses for tests and evals)

Frameworks we won't replace (SQLAlchemy, FastAPI) are used directly.

### 5. Runtime: one codebase, several processes

One repository and one container image, started with different commands:

| Process | Runs | Why separate |
|---|---|---|
| `api` | HTTP requests, light queries, assistant Q&A | Many short requests; must start fast and not hold ML models |
| `worker-llm` | Rule Analyzer investigations, Sigma generation (Celery queue `llm`) | Minutes-long LLM jobs; concurrency limited by Azure quotas |
| `worker-ingestion` + scheduler | QRadar sync, parsing, graph rebuild (Celery queue `ingestion`, beat) | Scheduled batch work, today run by hand |
| `ml-inference` (later, if needed) | Embedding and reranker models | Large memory/GPU; load once instead of per API worker |

All processes share the same Postgres, Neo4j and Redis. This is not a
microservice architecture: no separate databases, no network APIs between
our own components.

## Consequences

- Each layer and domain has an obvious home; new code has one right place.
- The database redesign touches repositories instead of scattered SQL.
- Swapping the LLM vendor or the vector store is a new adapter, not a rewrite.
- Processes can be scaled and fail independently.
- Costs: more folders than a flat layout; the move touches almost every
  import, so it is done in reviewable steps (R1 infrastructure, R2 the rest,
  R3 follow-ups), each proven to change file locations and imports only.
- Start commands change (for example `celery -A app.workers.celery_app`).
