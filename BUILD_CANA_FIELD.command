#!/bin/zsh
set -euo pipefail
cd "${0:A:h}"
./scripts/import_previous_field.sh
if [[ -f field/vectors.npy && -f field/manifest.json ]]; then
  COUNT="$(python3 - <<'PY'
import json
try:
    print(int(json.load(open('field/manifest.json')).get('count') or 0))
except Exception:
    print(0)
PY
)"
  if [[ "$COUNT" == "12804" ]]; then
    echo "CANA FIELD READY · 12,804 records · reusing completed ARBITER geometry"
    exit 0
  fi
fi
PYTHON="$(./scripts/ensure_env.sh | tail -n 1)"
EMBED_URL="${ARBITER_EMBED_URL:-http://127.0.0.1:8000/v1/embed}"
"$PYTHON" scripts/build_cana_field.py --embed-url "$EMBED_URL"
