# JaT Ingestion Workers

The ingestion contracts (job schema, upload policy, status transitions, and the
dispatcher boundary) are implemented and consumed by the API in
`apps/api/jat_api/ingestion/`. The current worker entry point is:

```bash
python -m jat_api.ingestion.worker
```

Workers consume quarantined object-storage references, never browser paths or
host paths. Parsed content is untrusted data and must not be treated as
instructions.

This directory marks the ownership boundary for the future standalone worker
deployment unit. When background ingestion is split out of the API process
(container isolation for parsers is still a pending infrastructure decision),
contracts should move here as a shared package and the API should depend on them
again.
