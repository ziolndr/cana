#!/usr/bin/env bash
set -euo pipefail

EMBED_URL="https://api.arbiter.traut.ai/public/embed"

export ARBITER_EMBED_URL="$EMBED_URL"
export FAST_ARBITER_EMBED_URL="$EMBED_URL"

exec python scripts/serve_cana.py \
  --host 0.0.0.0 \
  --port "${PORT:-10000}" \
  --embed-url "$EMBED_URL"
