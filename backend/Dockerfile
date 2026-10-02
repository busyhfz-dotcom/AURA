FROM python:3.11-slim
WORKDIR /app

# COPY paths below are relative to the repo root, not this file's directory:
# docker-compose builds with context "./backend" (see ../docker-compose.yml),
# but Railway (see ../railway.toml) builds with the repo root as context and
# just points dockerfilePath at this file — so both COPY forms must resolve.
# Using repo-root-relative paths here means this Dockerfile only works when
# built with repo-root context. docker-compose.yml's build.context is set to
# "." (repo root) with dockerfile: backend/Dockerfile to match.
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
EXPOSE 8000

# Railway (and most PaaS container platforms) inject a $PORT env var and route
# traffic to whatever port the process actually binds — 8000 is only a local
# default for docker-compose. Shell form (not exec-array form) is required so
# $PORT gets expanded; ${PORT:-8000} falls back to 8000 when PORT is unset
# (plain `docker run` / docker-compose).
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
