#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts/verify_inventory_field.py
