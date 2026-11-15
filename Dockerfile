# Saarthi: one container, one port. Stage 1 builds the web app; stage 2 runs the API, which also
# serves the built UI. Both vendored repos are copied in unmodified (git submodules).
FROM node:22-slim AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8.4 /uv /usr/local/bin/uv
WORKDIR /app
# Tolerate slow or flaky connections while downloading packages. The cache mount keeps what was
# already downloaded, so a build that fails mid-download resumes instead of starting over.
ENV UV_HTTP_TIMEOUT=180 UV_HTTP_RETRIES=8 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project
COPY backend/ backend/
COPY vendor/ vendor/
# The two trading repos are git submodules; a clone without --recurse-submodules leaves them empty.
RUN test -f vendor/nse-trader-skill/nse-common/nsecal.py && test -f vendor/claude-trading-skills-india/LICENSE \
 || { echo "vendor/ is empty: run 'git submodule update --init --recursive' and build again" >&2; exit 1; }
COPY --from=web /app/web/dist web/dist
ENV SAARTHI_DB=/app/data/saarthi.db PYTHONDONTWRITEBYTECODE=1
VOLUME ["/app/data"]
EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "backend.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
