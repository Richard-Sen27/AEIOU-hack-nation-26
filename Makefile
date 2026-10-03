BACKEND := apps/backend
FRONTEND := apps/frontend
COMPOSE := docker compose -f deploy/compose/docker-compose.yml
ENV_FILE := $(BACKEND)/.env

.PHONY: setup up down db-bootstrap migrate seed-fixture backend frontend mock-openai openapi test

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

down:
	$(COMPOSE) down

db-bootstrap: ## roles, extensions, schemas (idempotent; initdb only runs on a fresh volume)
	$(COMPOSE) exec -T -e PGOPTIONS="-c client_min_messages=warning" db \
		psql -U atlas -d atlas -v ON_ERROR_STOP=1 -q \
		-f /docker-entrypoint-initdb.d/01-bootstrap.sql

migrate:
	cd $(BACKEND) && uv run alembic upgrade head

seed-fixture:
	cd $(BACKEND) && uv run python -m backend.fixtures.load

backend:
	cd $(BACKEND) && uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload \
		--no-access-log

frontend:
	cd $(FRONTEND) && pnpm dev

mock-openai:
	cd $(BACKEND) && uv run python -m backend.devtools.mock_openai --port 8090

openapi:
	cd $(BACKEND) && uv run python scripts/export_openapi.py

test:
	cd $(BACKEND) && uv run pytest
