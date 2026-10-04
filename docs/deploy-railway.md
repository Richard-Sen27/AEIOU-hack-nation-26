# Deploying to Railway

How to host Amber on Railway: project `amber`, environment `production`, services `frontend`, `backend` and `Postgres`. The data is loaded from your machine; the two app services are built from their Dockerfiles. Local development is unchanged: none of this applies until the variables below are set.

## How it fits together

- **The browser talks only to the frontend.** The Next.js server proxies `/api/*` to the API (and `/auth/*` unprefixed, so the OAuth callbacks match the sign-in cookies' paths), so the API is same-origin. This is needed because two `*.up.railway.app` hosts are different sites: the API's `SameSite=Lax` session cookie would not be sent on the frontend's `fetch` calls, and Safari and Firefox also block or partition third-party cookies. The proxy is on only when `API_PROXY_TARGET` is set at build time (`apps/frontend/next.config.ts`).
- **The API needs no public domain.** The frontend reaches it at `http://backend.railway.internal:8000` over Railway's private network.
- **Postgres** is Railway's `postgres-ssl:18` image (PostgreSQL 18.6, pgvector 0.8.6, `pg_trgm` and `unaccent` included). A TCP proxy is opened only while data is loaded from your machine.
- **Sign-in:** Google, with the operator's `OPENAI_API_KEY` for Dr. Wu. Sign in with ChatGPT does not work on a hosted domain: the open-source flow pins its redirect to `http://127.0.0.1:<port>/auth/callback` (`validate_loopback_redirect` in `apps/backend/src/backend/openai_auth/oidc.py`). Partner mode (`OPENAI_CLIENT_ID`, `OPENAI_CLIENT_SECRET`, `OPENAI_REDIRECT_URI=https://<frontend>/auth/callback`) needs a client ID approved by OpenAI. Until then the API leaves `openai` out of `sign_in_methods` and the app shows no ChatGPT button (with neither method set up: "Sign-in is not available here.").

## Service settings

| Service | Source | Config | Port | Health check |
| --- | --- | --- | --- | --- |
| backend | `apps/backend` (Dockerfile) | `apps/backend/railway.toml` | `PORT=8000` | `/health`, 300 s (the graph is loaded into memory before the API answers) |
| frontend | `apps/frontend` (Dockerfile) | `apps/frontend/railway.toml` | `PORT=3100` | `/`, 120 s |
| Postgres | `ghcr.io/railwayapp-templates/postgres-ssl:18` | (template) | 5432 | (template) |

The backend runs `alembic upgrade head` as its pre-deploy command, then `uvicorn` on `::` port 8000 with uvicorn's access log off: the API writes its own request lines instead (route templates, never raw paths or query strings; see Logs below).

### Logs

Everything goes to stdout, which Railway collects (`railway logs -s backend`). One line per request, for example:

```
2026-10-04T12:41:03.351Z INFO backend.request request rid=3f9c0a1b2c4d5e6f method=GET route=/node/{node_id} status=200 ms=12 bytes=5123 client=guest
```

Signed-in requests add `uh=<10 hex>`, a pseudonym of the account that changes every UTC day. Every response carries the same id in `X-Request-ID`, and error responses in `error.request_id`, so a reported error can be found in the log. Start-up writes `starting …` (which features are configured, secrets as `set`/`unset`), `migrations state=…`, `graph loaded: <n> nodes, <m> edges data_version=… ms=…` and `ready ms=…`; shutdown writes run counts. Failed model calls show as `model call failed provider=openai credential=server_key model=… status=… upstream_code=… param=…` (for example `status=400 upstream_code=unsupported_value param=stream` when the OpenAI organisation is not verified for streaming). `LOG_LEVEL=debug` adds health checks and model-call timings. What is never logged: `docs/compliance.md` (Security logs).

### Rate limits

The request chain is browser → Railway edge → Next.js server (`frontend`) → API over the private network. The Railway edge puts the address it saw into `X-Forwarded-For` (whether it appends to a header the client sent or replaces it, that address is the last entry); the Next.js rewrite proxy (`httpxy` without `xfwd`) forwards the header unchanged and adds no entry of its own. So exactly one trusted proxy writes the header, and `TRUSTED_PROXY_HOPS=1` makes the API take the last entry; entries further left come from the client and are ignored, so a client cannot choose its own key. This chain is read from the code, not yet observed on Railway (check below). `X-Real-IP` is not used. With the default `0` every guest would be keyed on the frontend's private address (one shared bucket); the API logs a warning if the header has fewer entries than the setting. To check after a deploy: with `LOG_LEVEL=debug`, two guests on different networks (a laptop and a phone on mobile data) show different `net=` values in their request lines, and `via=forwarded`. Set `LOG_LEVEL` back afterwards.

Limits (in memory, per process): every request 600/minute per client (account; guests: address plus User-Agent, and 4× that per address); search 120/minute, neighbourhood 60/minute, path 30/minute, clusters 30/minute, Atlas tree 30/minute, Atlas summaries 120/minute; new explanations 20/minute and 200/day per account; chat 30/minute and 300/day; at most 3 model-calling runs at once per account and 16 per process ("busy"); and for Google accounts on the operator's key `MODEL_DAILY_BUDGET` model-calling requests per account and day and `MODEL_DAILY_CEILING` for all of them together (the usual "usage limit" message). Every 429 carries `Retry-After`. Also set a monthly spend limit on the OpenAI project itself.

**Deploying without a push:** `railway up <dir> --path-as-root` uploads one directory and finds `railway.toml` at its root. To upload exactly one commit (no `.env`, nothing uncommitted from other work), deploy from a `git archive` export (step 10). **With GitHub instead:** connect the branch (`railway service source connect --repo Richard-Sen27/AEIOU-hack-nation-26 --branch <branch> -s <service>`) and in the dashboard set the root directory to `/apps/backend` (or `/apps/frontend`) and the config file path to `/apps/backend/railway.toml` (or `/apps/frontend/railway.toml`); the config path does not follow the root directory. Pick one way per service: a GitHub config path does not exist in a `railway up` upload.

## Variables

`<F>` is the frontend's domain from step 6, for example `frontend-production-1234.up.railway.app`.

**backend**

| Name | Value | Who |
| --- | --- | --- |
| `PORT` | `8000` | fixed |
| `DATABASE_URL` | `postgresql+asyncpg://atlas_app:<app pw>@${{Postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/${{Postgres.PGDATABASE}}` | secret, step 2 |
| `MIGRATION_DATABASE_URL` | `postgresql+psycopg://atlas_owner:<owner pw>@${{Postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/${{Postgres.PGDATABASE}}` | secret, step 2 |
| `SESSION_SECRET` | `secrets.token_urlsafe(48)` | secret, generate |
| `TOKEN_ENCRYPTION_KEY` | a Fernet key (seals the sign-in cookies) | secret, generate |
| `MESSAGE_ENCRYPTION_KEY` | another Fernet key (without it messaging answers 501 off loopback) | secret, generate |
| `COOKIE_SECURE` | `true` (the API refuses to start off loopback without it) | fixed |
| `FRONTEND_URL` | `https://<F>` | domain |
| `API_URL` | `https://<F>/api` | domain |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | from the Google Cloud console | secret, you |
| `GOOGLE_REDIRECT_URI` | `https://<F>/auth/google/callback` (must not be under `/api`) | domain |
| `OPENAI_API_KEY` | the operator's key; without it set `GOOGLE_LOGIN_ENABLED=true` and Dr. Wu answers 503 | secret, you |
| `OPENAI_API_MODEL_MAIN`, `OPENAI_API_MODEL_SMALL` | optional, default `gpt-5`, `gpt-5-mini` | you |
| `CALLS_REVIEW_REQUIRED` | `false` (default) or `true` | you |
| `DEMO_AUTO_VERIFY` | `true` for the judged demo only: manual verification requests of doctors and researchers are approved at once and labelled "Demo, verification simulated" (start-up logs a warning). Default `false`; set it back to `false` before real patients use the product (`docs/compliance.md`, MUST NOT) | you |
| `TRUSTED_PROXY_HOPS` | `1` (see Rate limits below; without it every guest shares the frontend's address) | fixed |
| `MODEL_DAILY_BUDGET`, `MODEL_DAILY_CEILING` | optional, default `200` per account and `2000` per process and UTC day (model-calling requests on `OPENAI_API_KEY`) | you |
| `LOG_LEVEL`, `RATE_LIMIT_GENERAL`, `MODEL_MAX_CONCURRENT`, `MODEL_MAX_CONCURRENT_PER_ACCOUNT` | optional, defaults `info`, `600/minute`, `16`, `3` | you |
| `NCBI_API_KEY`, `BRIGHTDATA_API_KEY`, `BRIGHTDATA_SERP_ZONE` | optional (gap search) | you |

Leave unset: `ORCID_MOCK` (refused off loopback; experts verify through the manual request and `backend.cli`, or with `DEMO_AUTO_VERIFY=true` at once as a simulated verification, or set real `ORCID_CLIENT_ID`, `ORCID_CLIENT_SECRET`, `ORCID_BASE_URL` and register `https://<F>/api/me/professional/orcid/callback`), `DEMO_MODE`, `LANGFUSE_*`, `LANGSMITH_*`, `PIPELINE_DATABASE_URL`, `BOOTSTRAP_DATABASE_URL`.

**frontend** (the first three are build arguments: changing them needs a new build)

| Name | Value |
| --- | --- |
| `NEXT_PUBLIC_API_URL` | `https://<F>/api` |
| `API_PROXY_TARGET` | `http://${{backend.RAILWAY_PRIVATE_DOMAIN}}:8000` |
| `NEXT_PUBLIC_PRIVACY_EMAIL` | the privacy contact address |
| `PORT` | `3100` |
| `NEXT_PUBLIC_ANALYTICS` | optional build argument: `off` stops the page counter (it runs only on the host name in `ANALYTICS_HOSTNAMES`, `src/lib/analytics.ts`) |

## Steps

Run from the repository root with the project linked (`railway link -p amber -e production`). Never paste secrets into a command line that is logged; the commands below read them from a file or stdin.

1. **Postgres.** In the dashboard, turn off App Sleeping for Postgres (it shows "sleeping"), and check its region (prefer EU West while it is still empty). Open a TCP proxy and note its host and port:

   ```sh
   railway tcp-proxy create --port 5432 -s Postgres
   railway tcp-proxy list -s Postgres --json   # domain and proxyPort
   ```

2. **Role passwords.** Keep them in a local file outside the repository:

   ```sh
   mkdir -p -m 700 ~/.config/amber
   umask 077; cat > ~/.config/amber/railway-db.env <<EOF
   DB_HOST=<proxy domain>
   DB_PORT=<proxy port>
   ATLAS_OWNER_PASSWORD=$(openssl rand -hex 24)
   ATLAS_APP_PASSWORD=$(openssl rand -hex 24)
   ATLAS_PIPELINE_PASSWORD=$(openssl rand -hex 24)
   EOF
   set -a; . ~/.config/amber/railway-db.env; set +a
   ```

3. **Bootstrap** (superuser `postgres`, from Railway's variables): roles, extensions, schemas, then real passwords instead of the development ones.

   ```sh
   railway run -s Postgres -- env PGHOST=$DB_HOST PGPORT=$DB_PORT PGOPTIONS="-c client_min_messages=warning" \
     psql -X -q -v ON_ERROR_STOP=1 -f deploy/compose/initdb/01-bootstrap.sql
   railway run -s Postgres -- env PGHOST=$DB_HOST PGPORT=$DB_PORT psql -X -q -v ON_ERROR_STOP=1 <<'SQL'
   \getenv owner_pw ATLAS_OWNER_PASSWORD
   \getenv app_pw ATLAS_APP_PASSWORD
   \getenv pipeline_pw ATLAS_PIPELINE_PASSWORD
   ALTER ROLE atlas_owner PASSWORD :'owner_pw';
   ALTER ROLE atlas_app PASSWORD :'app_pw';
   ALTER ROLE atlas_pipeline PASSWORD :'pipeline_pw';
   SQL
   ```

4. **Migrations** (as `atlas_owner`, about 10 s):

   ```sh
   (cd apps/backend && MIGRATION_DATABASE_URL="postgresql+psycopg://atlas_owner:$ATLAS_OWNER_PASSWORD@$DB_HOST:$DB_PORT/railway" \
     uv run alembic upgrade head)
   ```

5. **Data** (as `atlas_pipeline`; reads `apps/pipeline/data/graph/final`, sends about 275 MB of CSV through `\copy`, then promotes in one transaction; expect 5 to 15 minutes depending on your upload speed). The snapshot stage writes local Parquet files only and is not needed for the hosted database. Then the precomputed explanations, as `atlas_app` (with your CLI ChatGPT login if present, otherwise template texts; the command loads the graph from the hosted database first):

   ```sh
   (cd apps/pipeline && PIPELINE_DATABASE_URL="postgresql://atlas_pipeline:$ATLAS_PIPELINE_PASSWORD@$DB_HOST:$DB_PORT/railway" \
     HF_HUB_OFFLINE=1 uv run atlas-pipeline load)
   (cd apps/backend && DATABASE_URL="postgresql+asyncpg://atlas_app:$ATLAS_APP_PASSWORD@$DB_HOST:$DB_PORT/railway" \
     uv run python -m backend.cli precompute-explanations --language en --language de)
   ```

   Check: `railway run -s Postgres -- env PGHOST=$DB_HOST PGPORT=$DB_PORT psql -Atc "select data_version, count(*) from nodes group by 1"` shows the expected version and node count.

6. **Frontend domain:** `railway domain -s frontend -p 3100` and note `<F>`. The backend gets no public domain.

7. **Backend variables.** Secrets through stdin, the rest on the command line; `--skip-deploys` until everything is set:

   ```sh
   S="-s backend --skip-deploys"
   python3 -c "import secrets; print(secrets.token_urlsafe(48))" | railway variable set SESSION_SECRET --stdin $S
   (cd apps/backend && uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") | railway variable set TOKEN_ENCRYPTION_KEY --stdin $S
   (cd apps/backend && uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") | railway variable set MESSAGE_ENCRYPTION_KEY --stdin $S
   echo "postgresql+asyncpg://atlas_app:$ATLAS_APP_PASSWORD@\${{Postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/\${{Postgres.PGDATABASE}}" | railway variable set DATABASE_URL --stdin $S
   echo "postgresql+psycopg://atlas_owner:$ATLAS_OWNER_PASSWORD@\${{Postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/\${{Postgres.PGDATABASE}}" | railway variable set MIGRATION_DATABASE_URL --stdin $S
   railway variable set PORT=8000 COOKIE_SECURE=true FRONTEND_URL=https://<F> API_URL=https://<F>/api \
     GOOGLE_REDIRECT_URI=https://<F>/auth/google/callback TRUSTED_PROXY_HOPS=1 $S
   railway variable set GOOGLE_CLIENT_ID --stdin $S        # paste, then Ctrl-D
   railway variable set GOOGLE_CLIENT_SECRET --stdin $S
   railway variable set OPENAI_API_KEY --stdin $S
   railway variable list -s backend --json | python3 -c "import json,sys; print(sorted(json.load(sys.stdin)))"   # names only
   ```

8. **Frontend variables:**

   ```sh
   railway variable set -s frontend --skip-deploys PORT=3100 NEXT_PUBLIC_API_URL=https://<F>/api \
     'API_PROXY_TARGET=http://${{backend.RAILWAY_PRIVATE_DOMAIN}}:8000' NEXT_PUBLIC_PRIVACY_EMAIL=<address>
   ```

9. **Google OAuth client** (Google Cloud console, Credentials, the web client): add the authorized redirect URI `https://<F>/auth/google/callback`. Scopes stay `openid email profile`.

10. **Deploy** one commit, backend first:

    ```sh
    rm -rf /tmp/amber-deploy && mkdir /tmp/amber-deploy && git archive HEAD apps/backend apps/frontend | tar -x -C /tmp/amber-deploy
    railway up /tmp/amber-deploy/apps/backend --path-as-root -s backend --ci -m "deploy $(git rev-parse --short HEAD)"
    railway up /tmp/amber-deploy/apps/frontend --path-as-root -s frontend --ci -m "deploy $(git rev-parse --short HEAD)"
    railway deployment list -s backend --json; railway logs -s backend --lines 100
    ```

    The backend log should show `graph loaded: <n> nodes, <m> edges`. If the frontend's proxy cannot reach `backend.railway.internal` (502 on `/api/health`), give the backend a domain (`railway domain -s backend -p 8000`), set `API_PROXY_TARGET=https://<backend domain>` on the frontend and deploy the frontend again.

11. **Close the TCP proxy** once the data is in: `railway tcp-proxy list -s Postgres --json`, then `railway tcp-proxy delete <id> --yes`. Open it again for the next data load.

## Verification checklist

- `curl -s https://<F>/api/health` answers `{"status":"ok"}`; `curl -s https://<F>/api/auth/session` shows the expected `data_version` and `"sign_in_methods":["openai","google"]`.
- The landing page, search and the Atlas load; a node panel opens; a path and its precomputed explanation show.
- Continue with Google returns to the page you started from, signed in (cookie `amber_session` on `<F>`, `Secure`, `HttpOnly`, `SameSite=Lax`); reload keeps you signed in; sign out works.
- A chat turn with Dr. Wu streams token by token (not all at once at the end) and finishes even when it takes over 30 s.
- Upload of a small document works (20 MB limit); messaging opens (not 501); `GET /api/me/export` downloads.
- `railway logs -s backend` shows `request rid=… route=/… status=…` lines with route templates only (no raw paths, no query strings, no health data), the `starting …`, `graph loaded: …` and `ready` lines, and no uvicorn access-log lines.

## Rollback

- **App:** in the dashboard, open the service's deployments and choose Rollback on the last good one, or deploy an older commit with step 10 using `git archive <commit>`. A failed build or a failed health check never replaces the running deployment.
- **Data:** run step 5 again with the earlier `data/graph/final` (the load replaces the graph tables in one transaction). Migrations only move forward; before a risky one, take a dump through the TCP proxy (`pg_dump -Fc`).
- **Everything off:** `railway down -s frontend` and `railway down -s backend` remove the latest deployments; the database and its volume stay.
