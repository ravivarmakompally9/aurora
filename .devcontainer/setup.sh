#!/usr/bin/env bash
# One-time Codespaces setup: Python and Node dependencies, dashboard build, and the
# full-year simulation the fuel planner needs (skipped when its output is in the repo).
set -euo pipefail
cd "$(dirname "$0")/.."

python -m pip install --user --quiet uv
python -m uv sync
npm --prefix dashboard ci --no-audit --no-fund
npm --prefix dashboard run build

if [ ! -f data/processed/year_bharati_2023_daily.csv ] || [ ! -f docs/year_bharati_2023.json ]; then
  echo "Simulating the full year once for the fuel planner (about 15 minutes on 4 cores)…"
  python -m uv run aurora year --station bharati --workers "$(nproc)"
fi
echo "Setup done. The dashboard starts on port 8765."
