# One image: built dashboard + API. Runs fully offline once built (NFR-01, NFR-10).
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
COPY docs/ docs/
RUN uv sync --frozen --no-dev
COPY --from=dashboard /app/dashboard/dist dashboard/dist
ENV AURORA_STATION=bharati
EXPOSE 8765 5020
CMD ["uv", "run", "--no-dev", "aurora", "serve", "--host", "0.0.0.0", "--port", "8765"]
