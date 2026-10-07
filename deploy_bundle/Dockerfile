# syntax=docker/dockerfile:1.7
ARG PYTHON_IMAGE=python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56
FROM ${PYTHON_IMAGE} AS wheels
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY requirements-production.txt requirements-phase04.lock.txt ./
RUN python -m pip wheel --only-binary=:all: --wheel-dir=/wheels -r requirements-production.txt -c requirements-phase04.lock.txt

FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 \
    TEMP=/tmp TMP=/tmp TMPDIR=/tmp \
    SENTINEL_AUTH_FILE=/run/secrets/accounts.json \
    SENTINEL_SESSION_KEY_FILE=/run/secrets/session.key \
    SENTINEL_PG_AUTH_FILE=/run/secrets/postgres-identities.json \
    SENTINEL_API_STATE=/var/lib/sentinelsql/jobs.sqlite
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libodbc2 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 sentinel && useradd --uid 10001 --gid sentinel --no-create-home sentinel \
    && mkdir -p /app/.runtime /var/lib/sentinelsql && chown -R sentinel:sentinel /app /var/lib/sentinelsql
COPY --from=wheels /wheels /wheels
COPY requirements-production.txt /app/requirements-production.txt
COPY requirements-phase04.lock.txt /app/requirements-phase04.lock.txt
RUN python -m pip install --no-index --find-links=/wheels -r /app/requirements-production.txt -c /app/requirements-phase04.lock.txt \
    && python -m pip check && rm -rf /wheels
WORKDIR /app
COPY --chown=sentinel:sentinel api ./api
COPY --chown=sentinel:sentinel agents ./agents
COPY --chown=sentinel:sentinel core ./core
COPY --chown=sentinel:sentinel utils ./utils
COPY --chown=sentinel:sentinel data/fincore_schema.sql data/financial_metrics.v1.json ./data/
COPY --chown=sentinel:sentinel BUSINESS_RULES.md ./
COPY --chown=sentinel:sentinel tools/migrate_fincore.py ./tools/migrate_fincore.py
COPY --chown=sentinel:sentinel tools/container_health.py ./tools/container_health.py
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 CMD ["python", "tools/container_health.py"]
# One process owns the durable audit lease. Capacity comes from bounded engine threads.
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log", "--timeout-graceful-shutdown", "25", "--ws-max-size", "16384", "--ws-max-queue", "16"]
