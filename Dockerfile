# syntax=docker/dockerfile:1
#
# TRACE image (MVP). Non-root, read-only root filesystem at run time (see docker-compose.yml).
#
# TODO(digest): pin both base images by digest (`FROM image@sha256:...`). Resolving a digest needs
# registry access and changing a base-image digest is an ask-first change (CLAUDE.md), so the tags
# below are placeholders until a maintainer pins them. `tests/unit/test_container.py` tracks it.

FROM node:20-bookworm-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim-bookworm AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONHASHSEED=0 \
    TRACE_DATA_DIR=/data TRACE_CONTAINER=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv \
 && groupadd --gid 10001 trace \
 && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin trace \
 && mkdir /data && chown 10001:10001 /data
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
COPY --from=web /web/dist /app/frontend/dist
ENV PATH="/app/backend/.venv/bin:${PATH}"
USER 10001:10001
EXPOSE 8000
VOLUME ["/data"]
CMD ["python", "-c", "from trace_api.main import run; run()"]
