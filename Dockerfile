# Saarthi: one container, one port. Stage 1 builds the web app; stage 2 runs the API, which also
# serves the built UI. Both vendored repos are copied in unmodified (git submodules).
FROM node:22-slim AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8.4 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend/ backend/
COPY vendor/ vendor/
COPY --from=web /app/web/dist web/dist
ENV SAARTHI_DB=/app/data/saarthi.db PYTHONDONTWRITEBYTECODE=1
VOLUME ["/app/data"]
EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "backend.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
