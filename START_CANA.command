#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PYTHON="$(./scripts/ensure_env.sh | tail -n 1)"
EMBED_URL="${ARBITER_EMBED_URL:-https://api.arbiter.traut.ai/public/embed}"
PORT="${CANA_PORT:-8868}"

"$PYTHON" scripts/verify_inventory_field.py
for pid in $(pgrep -f '/CANA_.*?/scripts/serve_cana.py' 2>/dev/null || true); do
  [[ "$pid" != "$$" ]] && kill "$pid" 2>/dev/null || true
done
for pid in $(lsof -ti tcp:"$PORT" 2>/dev/null || true); do kill "$pid" 2>/dev/null || true; done
sleep .3
"$PYTHON" scripts/serve_cana.py --host 127.0.0.1 --port "$PORT" --embed-url "$EMBED_URL" &
PID=$!
trap 'kill "$PID" 2>/dev/null || true' EXIT INT TERM
for attempt in {1..60}; do
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    open "http://127.0.0.1:$PORT/?build=cookies-inventory-v1"
    wait "$PID"
    exit 0
  fi
  sleep .2
done
echo "CANA failed to start on port $PORT" >&2
exit 1
