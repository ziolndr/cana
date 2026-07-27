#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PYTHON="$(./scripts/ensure_env.sh | tail -n 1)"
EMBED_URL="${ARBITER_EMBED_URL:-https://creation-api.actualgeneralintelligence.com/v1/embed}"

if [[ "${CANA_REFRESH_PROFILES:-0}" == "1" ]]; then
  "$PYTHON" scripts/prepare_cana_profiles.py --refresh
elif [[ ! -f data/semantic_profiles.jsonl || ! -f data/profile_stats.json ]]; then
  "$PYTHON" scripts/prepare_cana_profiles.py
fi

rm -f field/manifest.json
"$PYTHON" scripts/build_cana_field.py --embed-url "$EMBED_URL" --batch "${CANA_EMBED_BATCH:-24}"
"$PYTHON" scripts/verify_field.py

echo
echo "CANA PROFILE FIELD READY"
