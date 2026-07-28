#!/usr/bin/env bash
set -euo pipefail

EMBED_URL="${ARBITER_EMBED_URL:-https://api.arbiter.traut.ai/public/embed}"

exec python scripts/serve_cana.py \
  --host 0.0.0.0 \
  --port "${PORT:-10000}" \
  --embed-url "$EMBED_URL"
