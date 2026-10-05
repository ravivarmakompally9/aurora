#!/usr/bin/env bash
# Start AURORA: backend + dashboard on http://127.0.0.1:8765 (one process serves both).
#   ./start.sh          build the dashboard if needed, then serve
#   ./start.sh --dev    backend on :8765 plus the Vite dev server with live reload on :5173
set -euo pipefail
cd "$(dirname "$0")"

command -v uv >/dev/null || { echo "uv not found: install it from https://docs.astral.sh/uv/"; exit 1; }
command -v npm >/dev/null || { echo "npm not found: install Node.js 20 or newer"; exit 1; }

echo "Checking Python dependencies…"
uv sync -q

if [ ! -d dashboard/node_modules ]; then
  echo "Installing dashboard dependencies…"
  npm --prefix dashboard install --silent
fi

if [ ! -f docs/year_bharati_2023.json ] || [ ! -f data/processed/year_bharati_2023_daily.csv ]; then
  echo "First run: simulating a full year for the fuel planner and Simulation lab (about 7 minutes)…"
  uv run aurora year --station bharati
fi

if [ "${1:-}" = "--dev" ]; then
  uv run aurora serve --port 8765 &
  API=$!
  trap 'kill $API 2>/dev/null' EXIT
  echo "Dev dashboard: http://localhost:5173  (API on :8765)"
  npm --prefix dashboard run dev
else
  if [ ! -d dashboard/dist ] || [ -n "$(find dashboard/src dashboard/index.html -newer dashboard/dist/index.html 2>/dev/null | head -1)" ]; then
    echo "Building dashboard…"
    npm --prefix dashboard run build --silent
  fi
  echo "AURORA running at http://127.0.0.1:8765  (Ctrl+C to stop)"
  (sleep 4 && command -v open >/dev/null && open "http://127.0.0.1:8765") >/dev/null 2>&1 &
  uv run aurora serve --port 8765
fi
