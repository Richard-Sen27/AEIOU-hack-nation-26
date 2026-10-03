# Rare Disease Atlas ingestion pipeline. Each target calls the matching Typer command.
RUN := uv run atlas-pipeline
SOURCE ?=
SRC := $(if $(SOURCE),--source $(SOURCE),)

.PHONY: scope fetch normalize extract build analytics validate load snapshot explain all login test lint

scope:
	$(RUN) scope

fetch:
	$(RUN) fetch $(SRC)

normalize:
	$(RUN) normalize $(SRC)

extract:
	$(RUN) extract

build:
	$(RUN) build

analytics:
	$(RUN) analytics

validate:
	$(RUN) validate

load:
	$(RUN) load

snapshot:
	$(RUN) snapshot

explain:
	$(RUN) explain

all:
	$(RUN) all

login:
	$(RUN) login

test:
	uv run pytest -q

lint:
	uv run ruff check src tests && uv run ruff format --check src tests
