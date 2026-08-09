# Contributing to JaT

1. Read `ARCHITECTURE_ASSESSMENT.md` and the relevant package boundary before changing code.
2. Never commit `.env`, credentials, private keys, datasets, or generated model artifacts.
3. Add or update tests with every security-sensitive behavior change.
4. Run `make verify` before submitting changes.
5. Schema changes require an Alembic migration; do not manually alter deployed databases.
6. Keep model, vector-store, tool, and multimodal integrations behind provider interfaces when introduced.
