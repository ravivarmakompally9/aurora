# One image: built dashboard + API. Runs fully offline once built (NFR-01, NFR-10).
# Also the image Render deploys (render.yaml).
FROM node:22-slim AS dashboard
WORKDIR /app/dashboard
COPY dashboard/package*.json ./
RUN npm ci
COPY dashboard/ ./
RUN npm run build

FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY aurora/ aurora/
COPY configs/ configs/
COPY data/raw/ data/raw/
# the trained forecaster and the full-year daily summary (the only files .dockerignore lets
# through): training at start-up takes minutes, the year run far longer
COPY data/processed/ data/processed/
COPY docs/ docs/
RUN uv sync --frozen --no-dev
# train here if the forecaster is missing, so the server never trains at start-up
RUN test -f data/processed/forecaster_bharati.pkl || uv run --no-dev aurora train --station bharati
COPY --from=dashboard /app/dashboard/dist dashboard/dist
ENV AURORA_STATION=bharati
EXPOSE 8765 5020
# hosts such as Render pass the port in $PORT
CMD ["sh", "-c", "exec uv run --no-dev aurora serve --host 0.0.0.0 --port ${PORT:-8765}"]
