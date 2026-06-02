# ── Stage 1: dev ─────────────────────────────────────────────────────────────
# Used by docker-compose for local development (hot-reload, editable install).
FROM python:3.12-slim AS dev

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -e ".[dev]"
# Source is bind-mounted at runtime; no COPY needed.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]


# ── Stage 2: deps ─────────────────────────────────────────────────────────────
# Install only production + AWS dependencies into a clean prefix.
FROM python:3.12-slim AS deps

WORKDIR /build
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir ".[aws]"


# ── Stage 3: runtime (production default) ────────────────────────────────────
FROM python:3.12-slim AS runtime

# Minimal runtime system packages.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --gid 1001 app \
 && useradd --uid 1001 --gid app --no-create-home --shell /sbin/nologin app

WORKDIR /app

# Copy installed site-packages and console scripts from the deps stage.
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Copy only what the runtime needs — no tests, no docs, no scripts.
COPY --chown=app:app app/      ./app/
COPY --chown=app:app alembic/  ./alembic/
COPY --chown=app:app alembic.ini .

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
