#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if [[ -f field/vectors.npy && -f field/manifest.json && -f field/metadata.jsonl ]]; then
  python scripts/verify_field.py
else
  : "${ARBITER_EMBED_URL:?ARBITER_EMBED_URL must point to the public 72D ARBITER /v1/embed endpoint}"
  python scripts/build_cana_field.py --embed-url "$ARBITER_EMBED_URL"
  python scripts/verify_field.py
fi
