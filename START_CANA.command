#!/bin/zsh
set -euo pipefail
cd "${0:A:h}"
./scripts/import_previous_field.sh
PYTHON="$(./scripts/ensure_env.sh | tail -n 1)"
EMBED_URL="${ARBITER_EMBED_URL:-http://127.0.0.1:8000/v1/embed}"
PORT="${CANA_PORT:-8868}"

# Kill stale CANA servers so an older interface can never remain on the port.
for pid in $(pgrep -f '/CANA_FIELD_V[0-9]+/scripts/serve_cana.py' 2>/dev/null || true); do
  [[ "$pid" != "$$" ]] && kill "$pid" 2>/dev/null || true
done
for pid in $(lsof -ti tcp:"$PORT" 2>/dev/null || true); do
  kill "$pid" 2>/dev/null || true
done
sleep 0.4

"$PYTHON" scripts/serve_cana.py --embed-url "$EMBED_URL" --port "$PORT" &
PID=$!
trap 'kill "$PID" 2>/dev/null || true' EXIT INT TERM
for attempt in {1..40}; do
  if curl -fsS "http://127.0.0.1:$PORT/api/manifest" >/dev/null 2>&1; then
    open "http://127.0.0.1:$PORT/?build=v9"
    wait "$PID"
    exit 0
  fi
  sleep 0.25
done
echo "CANA server failed to start on port $PORT"
kill "$PID" 2>/dev/null || true
exit 1
