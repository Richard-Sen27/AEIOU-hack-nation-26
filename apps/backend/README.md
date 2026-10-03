# Amber backend

The FastAPI service: search, graph, paths, explanations, chat agent, documents, gap search,
account and Sign in with ChatGPT. It also holds the Alembic migrations (`migrations/`), the
backend CLI (`python -m backend.cli precompute-explanations | eval`) and the local OpenAI mock
(`python -m backend.devtools.mock_openai`).

Configuration lives in `.env` (copy `.env.example`; `make setup` in the repository root generates
the secrets). Run it with `make up migrate backend` from the root, or in Docker with
`make up-all` (image: `Dockerfile`). Tests: `make test`.

Architecture, setup and how to reproduce the dataset: see the [root README](../../README.md).
