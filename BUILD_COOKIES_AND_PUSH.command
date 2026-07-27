#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
REMOTE="https://github.com/ziolndr/cana.git"
WORK="$HOME/Downloads/cana-cookies-inventory-push"
cd "$ROOT"
PYTHON="$(./scripts/ensure_env.sh | tail -n 1)"

./BUILD_CANA_FIELD.command

rm -rf "$WORK"
git clone "$REMOTE" "$WORK"
rsync -a --delete \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '.cache/' \
  --exclude '__pycache__/' \
  --exclude 'snapshots/' \
  --exclude 'reports/missing-images.jsonl' \
  "$ROOT/" "$WORK/"

cd "$WORK"
"$PYTHON" - <<'PY'
import json, os, numpy as np
m=json.load(open('field/manifest.json'))
rows=sum(1 for line in open('data/inventory.jsonl') if line.strip())
v=np.load('field/vectors.npy',mmap_mode='r')
assert m.get('schema_version')=='cana-cookies-inventory-v2',m
assert v.shape==(rows,72),(v.shape,rows)
assert all(os.path.exists(json.loads(line)['image']) for line in open('data/inventory.jsonl') if line.strip())
print(f'PUBLISH VERIFIED · {rows:,} products · {v.shape[1]}D · every result image-backed')
PY

git add -A
if git diff --cached --quiet; then
  echo "No CANA Cookies inventory changes to push."
  exit 0
fi
COUNT="$(python3 -c 'print(sum(1 for line in open("data/inventory.jsonl") if line.strip()))')"
git commit -m "Freeze Cookies Mission Valley inventory field (${COUNT} products)"
git push origin main

echo
echo "CANA COOKIES INVENTORY PUSHED"
echo "repo: https://github.com/ziolndr/cana"
echo "products: $COUNT"
echo "Render will deploy the committed frozen field; it will not scrape or rebuild during deploy."
