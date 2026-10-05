#!/usr/bin/env bash
# Start the AURORA server (API + dashboard) in the background on every attach; Codespaces
# forwards port 8765 and opens the dashboard in the browser.
cd "$(dirname "$0")/.."
if ! curl -s -o /dev/null http://127.0.0.1:8765/api/health; then
  nohup python -m uv run aurora serve --host 0.0.0.0 --port 8765 > /tmp/aurora.log 2>&1 &
  echo "AURORA is starting on port 8765 (log: /tmp/aurora.log). Open the Ports tab if the browser does not open."
fi
