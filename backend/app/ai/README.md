# Developer 2 — Backend / AI

Owns `backend/app/ai/**`, `backend/tests/ai/**`, `data/benchmark/**`, `data/evidence/**`.
Pipeline: retrieval → provider → structured output → validation → product.
Provider = env only (`AI_PROVIDER`, `AI_API_KEY`, `AI_MODEL`). Benchmark: `python -m app.ai.benchmark`.