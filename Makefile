BACKEND := apps/backend
FRONTEND := apps/frontend
PIPELINE := apps/pipeline
COMPOSE := docker compose -f deploy/compose/docker-compose.yml
ENV_FILE := $(BACKEND)/.env
# The pipeline's optional settings file (see apps/pipeline/.env.example).
PIPELINE_ENV := $(if $(wildcard $(PIPELINE)/.env),--env-file .env,)
# Host directory with the ChatGPT login used by the pipeline's LLM steps.
AMBER_CONFIG_DIR ?= $(HOME)/.config/amber
export AMBER_CONFIG_DIR

.DEFAULT_GOAL := help
.PHONY: help setup up down db-bootstrap migrate seed-fixture backend frontend mock-openai openapi \
	test frontend-check pipeline pipeline-login explain up-all down-all pipeline-docker

help: ## list targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# --- dev mode: database in Docker, API and frontend on the host -----------------------------

setup: ## create .env with generated secrets, install deps
	@if [ ! -f $(ENV_FILE) ]; then \
		cp $(BACKEND)/.env.example $(ENV_FILE); \
		cd $(BACKEND) && uv run python -c "import re, secrets, uuid; \
from pathlib import Path; from cryptography.fernet import Fernet; \
p = Path('.env'); s = p.read_text(); \
vals = {'SESSION_SECRET': secrets.token_urlsafe(48), \
'TOKEN_ENCRYPTION_KEY': Fernet.generate_key().decode(), \
'OPENAI_AGENT_HOST_ID': f'urn:uuid:{uuid.uuid4()}'}; \
s = re.sub(r'^(SESSION_SECRET|TOKEN_ENCRYPTION_KEY|OPENAI_AGENT_HOST_ID)=$$', \
lambda m: f'{m[1]}={vals[m[1]]}', s, flags=re.M); p.write_text(s)"; \
		echo "created $(ENV_FILE)"; \
	fi
	cd $(BACKEND) && uv sync
	cd $(FRONTEND) && pnpm install

up: ## start Postgres and wait until healthy
	$(COMPOSE) up -d --wait db

down: ## stop the compose services (data volume kept)
	$(COMPOSE) down

db-bootstrap: ## roles, extensions, schemas (idempotent; initdb only runs on a fresh volume)
	$(COMPOSE) exec -T -e PGOPTIONS="-c client_min_messages=warning" db \
		psql -U atlas -d atlas -v ON_ERROR_STOP=1 -q \
		-f /docker-entrypoint-initdb.d/01-bootstrap.sql

migrate: ## apply Alembic migrations (as atlas_owner)
	cd $(BACKEND) && uv run alembic upgrade head

seed-fixture: ## load the small fixture graph instead of running the pipeline
	cd $(BACKEND) && uv run python -m backend.fixtures.load

backend: ## API on http://127.0.0.1:8000 with reload, no access log
	cd $(BACKEND) && uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload \
		--no-access-log

frontend: ## Next.js dev server on http://127.0.0.1:3100
	cd $(FRONTEND) && pnpm dev

mock-openai: ## local mock of the OpenAI issuer and API on http://127.0.0.1:8090
	cd $(BACKEND) && uv run python -m backend.devtools.mock_openai --port 8090

openapi: ## export apps/backend/openapi.json
	cd $(BACKEND) && uv run python scripts/export_openapi.py

# --- data -----------------------------------------------------------------------------------

pipeline: ## run every pipeline stage (fetch ... load, snapshot, explanations)
	cd $(PIPELINE) && uv run $(PIPELINE_ENV) atlas-pipeline all

pipeline-login: ## one-time Sign in with ChatGPT for the pipeline's LLM steps
	cd $(PIPELINE) && uv run atlas-pipeline login

explain: ## precompute explanations for the demo paths
	cd $(BACKEND) && uv run python -m backend.cli precompute-explanations

# --- checks ---------------------------------------------------------------------------------

test: ## backend tests (needs the database from `make up`)
	cd $(BACKEND) && uv run pytest

frontend-check: ## frontend typecheck, lint and mocked e2e tests
	cd $(FRONTEND) && pnpm typecheck && pnpm lint && pnpm test:e2e

# --- everything in Docker -------------------------------------------------------------------

up-all: ## build and start database, migrations, API and frontend in Docker
	$(COMPOSE) --profile app up -d --build --wait

down-all: ## stop everything started by up-all (data volume kept)
	$(COMPOSE) --profile app --profile pipeline down

pipeline-docker: ## run the pipeline and precompute explanations in Docker
	mkdir -p -m 700 "$(AMBER_CONFIG_DIR)"
	$(COMPOSE) run --build --rm pipeline all --skip-explain
	$(COMPOSE) run --rm explain
