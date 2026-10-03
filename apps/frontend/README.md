# Amber frontend

The Next.js app: Atlas, disease and path views, chat, document upload and findings review,
account and privacy pages. It calls the API from the browser through the generated Hey API client
(`pnpm gen:api` regenerates it from `../backend/openapi.json`).

- Dev server: `make frontend` from the repository root (`pnpm dev`, http://127.0.0.1:3100).
- `NEXT_PUBLIC_API_URL` (default `http://127.0.0.1:8000`) and `NEXT_PUBLIC_PRIVACY_EMAIL`, see
  `.env.example`. Always use `127.0.0.1`, never `localhost`.
- Checks: `make frontend-check` (`pnpm typecheck`, `pnpm lint`, `pnpm test:e2e` with a mocked
  API).
- Docker: `Dockerfile` builds the standalone production server; `NEXT_PUBLIC_API_URL` is a build
  argument because it is inlined into the browser bundle.

Architecture and setup: see the [root README](../../README.md).
