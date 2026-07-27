#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PYTHON="$(./scripts/ensure_env.sh | tail -n 1)"
EMBED_URL="${ARBITER_EMBED_URL:-https://api.arbiter.traut.ai/public/embed}"

"$PYTHON" scripts/scrape_cookies_inventory.py \
  --site missionvalley.cookies.co \
  --workers "${CANA_IMAGE_WORKERS:-10}" \
  --minimum "${CANA_MINIMUM_PRODUCTS:-20}"

"$PYTHON" scripts/test_embedding_policy.py

rm -rf field
mkdir -p field
"$PYTHON" scripts/build_inventory_field.py \
  --embed-url "$EMBED_URL" \
  --batch "${CANA_EMBED_BATCH:-128}" \
  --conc "${CANA_EMBED_CONCURRENCY:-2}"
"$PYTHON" scripts/verify_inventory_field.py
