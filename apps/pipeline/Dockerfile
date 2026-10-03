# Amber ingestion pipeline image. Build context: apps/pipeline, plus the backend image as the
# named build context `backend` (the pipeline imports the backend package and shares its
# dependencies, so it is layered on top of the API image instead of installing them twice).
#   docker build -t amber-backend:local apps/backend
#   docker build -t amber-pipeline:local \
#     --build-context backend=docker-image://amber-backend:local apps/pipeline
# Compose does this through `additional_contexts: backend: service:api`.
# apps/pipeline/data must be mounted at /app/pipeline/data so downloads and caches survive.

FROM ghcr.io/astral-sh/uv:0.12.19 AS uv

FROM backend
USER root
# psql runs the \copy of the load stage.
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app/pipeline
COPY pyproject.toml uv.lock seeds.yaml ./
COPY curated ./curated
COPY src ./src
# Same locked versions as the backend, so this only adds the pipeline's own packages to the
# backend's virtualenv (the backend package resolves to /app/backend through ../backend).
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    UV_PROJECT_ENVIRONMENT=/app/backend/.venv UV_NO_CACHE=1 UV_PYTHON_DOWNLOADS=never \
       uv sync --frozen --no-dev \
    && mkdir -p data \
    && chown app:app data
ENV PSQL_BIN=/usr/bin/psql
USER app
ENTRYPOINT ["atlas-pipeline"]
CMD ["--help"]
