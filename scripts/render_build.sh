#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if [[ ! -f data/semantic_profiles.jsonl || ! -f data/profile_stats.json ]]; then
  python scripts/prepare_cana_profiles.py
fi

if python scripts/verify_field.py; then
  exit 0
fi

: "${ARBITER_EMBED_URL:?ARBITER_EMBED_URL must point to the public 72D ARBITER /v1/embed endpoint}"
rm -f field/manifest.json
python scripts/build_cana_field.py --embed-url "$ARBITER_EMBED_URL" --batch "${CANA_EMBED_BATCH:-24}"
python scripts/verify_field.py
