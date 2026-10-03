# Amber API image. Build context: apps/backend.
#   docker build -t amber-backend:local apps/backend
# Default command serves the API; the same image runs migrations and the backend CLI:
#   alembic upgrade head
#   python -m backend.cli precompute-explanations
# No secrets in the image: configuration comes from the environment at run time.

ARG PYTHON_IMAGE=python:3.13-slim-trixie

FROM ghcr.io/astral-sh/uv:0.12.19 AS uv

FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3
WORKDIR /app/backend
# Dependencies first (cached unless the lock changes), then the project itself (editable, so
# alembic.ini, migrations and the package all live under /app/backend).
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src
RUN UV_COMPILE_BYTECODE=1 uv sync --frozen --no-dev

FROM ${PYTHON_IMAGE} AS runtime
# tesseract-ocr + English data: OCR for photographed documents (Tesseract CLI).
# libmagic1: content sniffing of uploads (python-magic). pillow-heif ships its own libheif.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       tesseract-ocr tesseract-ocr-eng libmagic1 \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data/fastembed \
    && chown app:app /data/fastembed
COPY --from=build /app/backend /app/backend
WORKDIR /app/backend
ENV PATH=/app/backend/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FASTEMBED_CACHE_DIR=/data/fastembed \
    HF_HUB_DISABLE_TELEMETRY=1
USER app
EXPOSE 8000
# No access log: query strings can carry health-related search terms and one-time auth codes.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
