# JaT RAG — Current Implementation Boundary

Phase 3 retrieval is now enabled end to end for text documents: governed upload,
quarantined object storage, worker-driven ingestion, vector indexing, semantic
search, and citations in chat. This document records exactly what is and is not
in the trust boundary yet.

## What is implemented

- **Governed upload** — `POST /knowledge-bases/{id}/documents/upload` requires
  `source` and `license` metadata, enforces the allowlist of content types and
  the 25 MiB limit, computes SHA-256 server-side, deduplicates per knowledge base,
  and writes bytes to quarantined object storage under a server-generated key.
- **Ingestion pipeline** — `pending → validating → parsing → chunking → embedding
  → ready`, with every other outcome landing in `failed` plus a `failure_reason`.
  The worker re-verifies the stored object against the registered hash before
  parsing. Re-ingestion replaces the document's prior index atomically.
- **Dispatch** — `inline` (synchronous dev/test default, no infrastructure),
  `redis` (durable queue: `python -m jat_api.ingestion.worker` consumes
  `JAT_INGESTION_QUEUE`), and a records-only `local` fixture.
- **Parsing** — `text/plain` and `text/markdown` at this milestone. Accepted but
  not yet parsed types (`application/pdf`, `application/json`, `text/csv`) fail
  ingestion explicitly rather than silently emitting garbage.
- **Chunking** — deterministic paragraph-aware chunker with sliding overlap
  (defaults 1000 chars / 200 overlap), capped at 200 chunks per document.
- **Vector indexing and search** — `PostgresVectorStore` stores embeddings in
  `float8[]` columns and ranks with pure-SQL cosine similarity, so any PostgreSQL
  14+ works without extensions (including CI). Retrieval is always scoped by
  `organization_id`, requires a matching `embedding_model`, and only reads
  `ready` documents. Filters are an allowlist — never SQL built from request data.
- **Chat grounding and citations** — `knowledge_base_id` on chat requests injects
  passages as delimited **untrusted data** in the user channel (never the system
  channel) and emits `citation` SSE events before tokens; citations persist as
  `citation` message parts. Ownership of the knowledge base is enforced (404)
  before any retrieval runs.
- **Embedding providers** — provider-neutral `EmbeddingProvider` contract with the
  deterministic hash-based fixture. The fixture exercises the full pipeline but is
  **not a semantic model**; real quality requires a model-backed adapter.

## Explicitly not yet implemented

- PDF/JSON/CSV (and binary) parsers, and their sandboxed/container execution.
- At-least-once queue semantics: the Redis worker is best-effort — a crash between
  pop and terminal state leaves documents stuck in an intermediate state and they
  must be re-dispatched. Production needs ack/redrive (e.g., Redis Streams or a
  dedicated queue) plus a reaper for `pending`/`failed` documents.
- **pgvector.** When data outgrows sequential scans: `CREATE EXTENSION vector`,
  migrate `document_chunks.embedding` to `vector`, add an HNSW index, and point
  the search expression at `<=>`. The `VectorStore` contract does not change.
- Model-backed embedding providers (Ollama embeddings are the natural next adapter),
  hybrid/BM25 ranking, re-ranking, and retrieval evaluation harnesses.
- Per-document re-ingestion and deletion APIs over indexed chunks, and the
  knowledge-base management UI in the web app.

## Security invariants that must survive every change above

1. Workers only ever receive object-storage references — never browser or host paths.
2. Parsed content is untrusted data: it enters prompts only inside delimited,
   clearly-labelled reference blocks in the user channel, never as instructions.
3. Chunk metadata always carries `organization_id`, source, and license; every
   retrieval path enforces the organization filter server-side.
4. The quarantined object store never serves content back to clients.
5. The embedding model used at query time must match the indexed vectors;
   changing providers requires re-indexing (document statuses support re-dispatch).
