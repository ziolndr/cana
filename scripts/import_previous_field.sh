#!/bin/zsh
set -euo pipefail
ROOT="${0:A:h:h}"
TARGET="$ROOT/field"
mkdir -p "$TARGET"
if [[ -f "$TARGET/vectors.npy" ]]; then
  exit 0
fi
for PREVIOUS in   "$ROOT/../CANA_FIELD_V8/field"   "$ROOT/../CANA_FIELD_V7/field"   "$ROOT/../CANA_FIELD_V6/field"   "$ROOT/../CANA_FIELD_V5/field"   "$ROOT/../CANA_FIELD_V4/field"; do
  if [[ -f "$PREVIOUS/vectors.npy" ]]; then
    echo "Importing completed ARBITER field from ${PREVIOUS:h:t}..."
    for name in vectors.npy metadata.jsonl manifest.json build_state.json; do
      [[ -f "$PREVIOUS/$name" ]] && cp -p "$PREVIOUS/$name" "$TARGET/$name"
    done
    exit 0
  fi
done
