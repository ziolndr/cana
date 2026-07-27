#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ ! -x .venv/bin/python ]]; then
  echo "Creating CANA Python environment..."
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import numpy; from PIL import Image' >/dev/null 2>&1; then
  echo "Installing CANA dependencies..."
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt
fi
printf "%s\n" "$ROOT/.venv/bin/python"
