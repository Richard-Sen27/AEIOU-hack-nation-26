# Amber — Rare Disease Atlas

Amber is a sourced knowledge graph for one cluster of rare diseases, developmental and epileptic
encephalopathies and channelopathies (seed genes such as STXBP1, SCN1A, SCN2A, KCNQ2, CDKL5),
with a web app to explore it. It connects diseases, genes, variants, mechanisms, pathways,
symptoms, papers, researchers, clinicians, trials, grants, patient organizations and registries.
Every edge carries its sources, a confidence score and an observed or inferred label. Guests can
search and explore the whole graph. People who sign in with ChatGPT also get the chat agent,
document upload with findings review, and on-demand explanations. Those model calls run on their
own ChatGPT plan.

Built for Hack-Nation 7 (2026), challenge 05. Specs: [`docs/specs/system.md`](docs/specs/system.md)
(system), [`docs/specs/agent.md`](docs/specs/agent.md) (chat agent).

## Architecture

```
Offline pipeline · make pipeline  (atlas-pipeline all, apps/pipeline)
  Public sources                      Stages (Typer CLI)                     apps/pipeline/data/snapshot/
  MONDO, HGNC, HPO, ClinVar,     ──▶  fetch → scope → normalize + link  ──▶  <data_version>/
  ClinGen, Reactome, GO, Orphanet,    → extract (LLM) → build → analytics    Parquet + manifest.json
  PubMed, ClinicalTrials.gov,         → validate → load → snapshot
  NIH RePORTER, patient orgs          → explain                 │ psql \copy as atlas_pipeline
                                                                ▼
Live service · per request
  Next.js frontend            ◀──▶  FastAPI (apps/backend)   ◀──▶  Postgres 18 + pgvector
  127.0.0.1:3100                    127.0.0.1:8000                 staging schema, graph tables,
  graph views, chat, uploads        search, graph, path, explain,  user tables with forced RLS
  (session cookie, no tokens)       chat, documents, gap agent,    (API connects as atlas_app)
                                    auth
                                      ▲                 │
               /auth/callback         │                 │ LLM calls with the signed-in
  Sign in with ChatGPT ───────────────┘                 ▼ user's OpenAI token
  OIDC + PKCE (auth.openai.com)                       OpenAI API (billed to the user's plan)
```

**Offline pipeline** (`apps/pipeline`). Eight stages, each a Typer command and a target in
`apps/pipeline/Makefile`. They are idempotent and cached under `apps/pipeline/data`. `seeds.yaml`
defines the scope. The pipeline downloads public data, resolves identities to MONDO, HGNC, HPO,
PMID and NCT ids, and extracts relations from abstracts with a model, keeping an exact quote for
each relation and checking that quote against the source text. It merges evidence into edges with
a confidence score and computes symptom similarity, mechanism edges, Leiden clusters, layouts and
centrality. It then validates the result, loads it into Postgres and exports a snapshot.

**Live service** (`apps/backend`, `apps/frontend`). FastAPI loads `nodes` and `edges` into memory
at startup. Postgres handles search (pg_trgm, unaccent, pgvector with local fastembed embeddings),
evidence lookups and every write. The Next.js app calls the API from the browser with the session
cookie through a generated Hey API client, and it never handles OpenAI tokens.

**Database.** One Postgres 18 database with pgvector (`pgvector/pgvector:pg18`), bootstrapped by
[`deploy/compose/initdb/01-bootstrap.sql`](deploy/compose/initdb/01-bootstrap.sql). The schema
lives in Alembic migrations under `apps/backend/migrations`. There are three login roles:

- `atlas_owner` owns the schema and runs migrations.
- `atlas_app` is what the API connects as. It does not own the tables, has no `BYPASSRLS`, can only
  read the graph tables, and can read and write user tables subject to row-level security.
- `atlas_pipeline` owns the `staging` schema, writes the graph tables, and has no access to user
  tables.

Every user table has `FORCE ROW LEVEL SECURITY` with a policy on
`current_setting('app.user_id')`, which the API sets per request transaction. The only lookup
that runs before a user id is known goes through a narrow `SECURITY DEFINER` function owned by the
non-login role `atlas_definer`. Account deletion cascades from `users`.

**Sign-in and billing.** Continue with ChatGPT is the only sign-in method. The API runs OpenID
Connect with PKCE against `auth.openai.com`. It uses OpenAI's locally hosted flow with dynamic
client registration (`OPENAI_CLIENT_ID` empty) and requests the identity scopes plus the scopes
that allow API use on the user's ChatGPT plan. The OpenAI tokens are stored encrypted with
`TOKEN_ENCRYPTION_KEY` in `openai_tokens`. The browser only gets an `HttpOnly` session cookie,
which is a JWT signed with `SESSION_SECRET`. Every model call goes through `backend.llm.LLMClient`
with that user's token, so usage counts against their plan. Guests never trigger a model call.

The offline steps that use a model have no team API key either. They are: abstract and
patient-organization extraction, LLM-assisted linking of leftover names, cluster labels and
precomputed explanations. They run on the plan of whoever ran `make pipeline-login` on that
machine (see below).

## Prerequisites

- Docker with Compose v2 (tested with Docker Desktop, Compose 5.5, 8 GB memory for Docker).
- For dev mode, and for `make setup`, which creates the env file: [uv](https://docs.astral.sh/uv/)
  (Python 3.13 is fetched by uv if missing), Node.js 22 and pnpm 11 (`corepack enable`).
- For the pipeline outside Docker: the PostgreSQL client (`psql`). The default path is
  `/opt/homebrew/bin/psql`. Set `PSQL_BIN` in `apps/pipeline/.env` if yours is elsewhere.
- Disk: the backend image is about 1.5 GB, the pipeline image adds about 0.7 GB on top of it, the
  frontend image is about 0.3 GB, and the pipeline data directory is about 720 MB.

## Quick start

Run `make` (or `make help`) to list all targets.

### Mode 1: database in Docker, API and frontend in dev mode

```sh
make setup        # apps/backend/.env with generated secrets, uv sync, pnpm install
make up           # Postgres on 5432 (roles and extensions are created on a fresh volume)
make migrate      # Alembic as atlas_owner
make pipeline     # build and load the graph (see "Reproduce the dataset"), or: make seed-fixture
make backend      # API on http://127.0.0.1:8000 (separate terminal)
make frontend     # app on http://127.0.0.1:3100 (separate terminal)
```

If the database volume existed before the bootstrap script changed, re-apply it with
`make db-bootstrap` (idempotent).

### Mode 2: everything in Docker

```sh
make setup        # once, only to create apps/backend/.env (or copy .env.example and fill the
                  # three generated values: SESSION_SECRET, TOKEN_ENCRYPTION_KEY,
                  # OPENAI_AGENT_HOST_ID)
make up-all       # builds the images, starts db → migrate → api → frontend, waits for health
make pipeline-docker   # pipeline + explanations in containers, then restarts the api container
make down-all     # stop everything (the database volume is kept)
```

What this runs (`deploy/compose/docker-compose.yml`):

- `db` has no profile, so `docker compose up -d db` (= `make up`) still starts only Postgres.
- `migrate`, `api` and `frontend` are in the `app` profile. `api` waits for `migrate` to finish
  successfully, and `frontend` waits for a healthy `api`. The API is published on
  `127.0.0.1:8000` and the frontend on `127.0.0.1:3100`, both bound to loopback.
- `pipeline` and `explain` are in the `pipeline` profile and run on demand:
  `docker compose -f deploy/compose/docker-compose.yml run --rm pipeline <stage>` and
  `... run --rm explain`.
- Host ports can be changed with `ATLAS_DB_PORT`, `ATLAS_API_PORT` and `ATLAS_FRONTEND_PORT`
  (defaults 5432, 8000, 3100). The frontend bakes `NEXT_PUBLIC_API_URL` in at build time, so
  `up-all` rebuilds it. Real sign-in only works with the API on 8000 (next section).
- Secrets are read from `apps/backend/.env` at run time and are never part of an image or of the
  compose file. The database URLs from that file are replaced so they point at the `db` service.
- The API runs as a non-root user with `--no-access-log`.
- `apps/pipeline/data` is bind-mounted into the pipeline container, so downloads and caches are
  shared with dev mode.
- The fastembed model (`BAAI/bge-small-en-v1.5`, about 130 MB) is downloaded on first use into
  the named volume `fastembed-cache`, which `api`, `pipeline` and `explain` share. A volume keeps
  the image smaller, the model is downloaded once per machine rather than once per build, and it
  survives rebuilds. The trade-off: the first API start needs network access to Hugging Face.
- The pipeline container uses the host's ChatGPT login from `~/.config/amber`, which is mounted
  read-write so tokens can be refreshed. Override the directory with `AMBER_CONFIG_DIR`.

Stop the dev-mode API and frontend before `make up-all`, because they use the same host ports.

### Why 127.0.0.1 and never localhost

Open the app at `http://127.0.0.1:3100`, not `http://localhost:3100`:

- OpenAI's locally hosted sign-in flow redirects to exactly
  `http://127.0.0.1:8000/auth/callback` (`OPENAI_REDIRECT_URI`).
- Cookies are bound to the host name. The session cookie is set by `127.0.0.1:8000`, and
  `localhost` and `127.0.0.1` are different sites for cookies and for `SameSite=Lax`, so a page
  served from `localhost` would never be signed in.
- The API's CORS policy allows only `FRONTEND_URL` (`http://127.0.0.1:3100`) with credentials.

## Reproduce the dataset

The dataset is defined by `apps/pipeline/seeds.yaml` (seed genes and diseases plus expansion
rules) and the curated inputs in `apps/pipeline/curated/`. One command runs everything:

```sh
make pipeline          # dev mode: cd apps/pipeline && uv run atlas-pipeline all
make pipeline-docker   # same in Docker, then the explanations via the explain service
```

`atlas-pipeline all` runs these steps in order. Each one is also a command
(`uv run atlas-pipeline <stage>`, `make -C apps/pipeline <stage>`, `SOURCE=pubmed` for one
source):

| Step | Command | What it does |
| --- | --- | --- |
| 1 (bulk) | `fetch --phase bulk` | Public bulk downloads into `data/raw/<source>/`, each with URL, time, SHA-256 and version: MONDO, HGNC, HPO (`hp.json`, `phenotype.hpoa`, `genes_to_phenotype.txt`), ClinVar `variant_summary.txt.gz`, ClinGen, Reactome, GO, Orphanet, OMIM (only with `OMIM_API_KEY`) |
| 0 | `scope` | Resolves `seeds.yaml` into `data/scope/scope.json` (genes, diseases, phenotypes in scope) |
| 1 (scoped) | `fetch --phase scoped` | Per-scope API queries: PubMed abstracts and authors, ClinicalTrials.gov studies, NIH RePORTER grants, patient organization pages (curated list, plus Bright Data search when configured) |
| 2 | `normalize` | Contract tables under `data/normalized/<source>/` with standard ids, a synonyms table, and linking of leftover names (trigram + embedding candidates, model decision when signed in, every decision logged in `data/logs/linking.jsonl`) |
| 3 | `extract` | Model extraction of relations from abstracts and patient-organization pages, with quote verification |
| 4 | `build` | Merges evidence into edges with tier-weighted confidence, prunes weakly linked researchers and orphan nodes |
| 5 | `analytics` | Symptom similarity, mechanism edges, shared researchers, Leiden clusters and their labels, layouts, centrality |
| 6 | `validate` | Fails the run unless every check passes (evidence per edge, no orphans, golden facts, the SCN2A counterexample) |
| 7a | `load` | `psql \copy` into `staging` as `atlas_pipeline`, then promotes into the graph tables and records the run in `ingestion_runs` |
| 7b | `snapshot` | Writes `data/snapshot/<data_version>/` (Parquet files for nodes, synonyms, edges, evidence, clusters and mechanisms, plus `manifest.json` with source versions, hashes, counts, thresholds and quote-verification results). `data/snapshot/latest` points to it |
| — | `explain` | Precomputes explanations for the demo paths in every role (`python -m backend.cli precompute-explanations`, also `make explain`) |

**Duration and size.** A full `atlas-pipeline all` on already-cached data took about 12 minutes,
about 10 of them for the literature fetches. The first run takes longer: the ClinVar download
alone takes about 90 seconds, and the first embedding pass about 5 minutes. API responses are
cached for 30 days (`CACHE_TTL_DAYS`) and bulk files are kept as files, so re-runs are cheaper.
`apps/pipeline/data` is about 720 MB. The data version loaded at the time of writing was
`2026-10-04.9`, with 6,343 nodes, 16,883 edges and 9 clusters.

**Restart the API after a load.** The API loads the graph into memory at startup and looks up
cached explanations by `data_version`. Until it restarts, a running API keeps serving the old
graph and misses every newly cached explanation. In dev mode, stop `make backend` and start it
again. In Docker, run `docker compose -f deploy/compose/docker-compose.yml restart api`.
`make pipeline-docker` does this for you when the API container is running.

**Optional keys** go in `apps/pipeline/.env`. Copy
[`apps/pipeline/.env.example`](apps/pipeline/.env.example), which documents every setting,
including the caps and the LLM budget. All keys are optional:

- `NCBI_API_KEY`: PubMed at 10 instead of 3 requests per second.
- `OMIM_API_KEY`: enables the OMIM source.
- `BRIGHTDATA_API_KEY` + `BRIGHTDATA_SERP_ZONE`: web search for further patient organizations.
  The gap-search agent in the API reads the same two keys from `apps/backend/.env`.

**ChatGPT login for the model steps.** Run this once per machine, on the host. The login
listens for its callback on `127.0.0.1`, so it cannot run inside a container:

```sh
make pipeline-login    # opens the browser; stores the login in ~/.config/amber/openai.json
cd apps/pipeline && uv run atlas-pipeline whoami   # check it (logout: atlas-pipeline logout)
```

Without a login the pipeline still finishes:

- Extraction uses only results already cached in `data/cache/llm/`. The manifest records
  `skipped_not_logged_in` for the extractors.
- Leftover names that need a model decision stay unlinked.
- Cluster labels are built from the members' genes and pathways.
- Explanations are generated from templates over the edge data instead of by a model.

`PIPELINE_LLM_MAX_CALLS` (default 300) caps the uncached model calls per run, and
`PIPELINE_LLM_DISABLED=true` turns them off entirely.

## Tests

```sh
make test                      # backend (pytest; needs `make up`, creates throwaway databases)
make -C apps/pipeline test     # pipeline unit tests
make -C apps/pipeline lint     # pipeline ruff check + format check
make frontend-check            # frontend typecheck, ESLint, Playwright e2e with mocked API
cd apps/backend && uv run python -m backend.cli eval --mock   # agent evals against the mock
```

The frontend e2e suite starts its own `next dev` on port 3109 with a separate build directory,
so it does not interfere with a dev server on 3100. It needs the Playwright browsers
(`pnpm exec playwright install chromium`).

## What is verified and what is not

Verified locally:

- Both modes start. In Docker, migrations apply on a fresh volume, the bootstrap creates the roles
  and extensions, and `/health`, `/auth/session`, search and the frontend answer.
- The pipeline's `load` and `snapshot` stages run in the container against a throwaway database,
  and the explanations precompute runs (template mode without a login).
- The backend test suite covers RLS isolation, document extraction with local Tesseract,
  Presidio redaction and the sign-in flow against the mock.

Not verified: **the real Sign in with ChatGPT flow and model calls billed to a ChatGPT plan.**
They have only been tested against a local mock of OpenAI's issuer and API, because that needs a
person to sign in with a real account. This applies both to the web flow and to the pipeline's
CLI login. Until someone has done that, treat everything behind sign-in as tested only against
the mock.

The mock lives in `apps/backend/src/backend/devtools/mock_openai/` and is for development only.
To use it in dev mode:

```sh
make mock-openai     # issuer and API on http://127.0.0.1:8090
# in apps/backend/.env, then restart the API (and re-run pipeline-login for the CLI):
OPENAI_AUTH_ISSUER=http://127.0.0.1:8090
OPENAI_API_BASE_URL=http://127.0.0.1:8090/v1
```

The mock is meant for dev mode. In the Docker setup the issuer URL has to be reachable from both
the browser and the API container, and `127.0.0.1:8090` is not reachable from the container.

## Privacy

The app handles health and genetic data. The rules are in [`docs/compliance.md`](docs/compliance.md)
(GDPR and California; where they differ, the stricter rule applies), and what is stored for how
long is in [`docs/retention.md`](docs/retention.md). In short:

- Guests are stateless.
- Signed-in users give two separate consents, each revocable on its own: `health_data`, for
  processing their own health and genetic data (chat, profile and uploads), and `contribute`,
  for sharing data with the atlas.
- Raw uploads are deleted after extraction.
- Personal data is redacted with Presidio before any model call.
- Nothing extracted is used until the user confirms it.
- Every user table is under row-level security.
- The API writes no access log, because query strings can carry health-related search terms and
  one-time auth codes.
- Searches sent to public sources (PubMed, Bright Data) are built from graph ids and public terms
  only, never from user text.

## Troubleshooting

- **`uv sync` or an image build fails with HTTP 503 for `en_core_web_lg`.** The spaCy model is
  pinned to a GitHub release URL, and GitHub sometimes returns 503. Retry.
- **Port already in use on `make up-all`.** Stop the dev-mode API and frontend, or set
  `ATLAS_API_PORT` / `ATLAS_FRONTEND_PORT` / `ATLAS_DB_PORT`. Sign-in needs the API on 8000.
- **The API shows an old or empty graph after a pipeline run.** It loads the graph at startup.
  Restart it (`make backend` again, or `docker compose -f deploy/compose/docker-compose.yml
  restart api`).
- **Linux: permission denied writing `apps/pipeline/data` from the container.** The pipeline
  container runs as uid 10001. Make the directory writable for that uid, for example
  `sudo chown -R 10001 apps/pipeline/data` (Docker Desktop on macOS needs nothing).
- **`load` fails with "psql failed" outside Docker.** Set `PSQL_BIN` in `apps/pipeline/.env`.
