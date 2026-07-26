#!/bin/zsh
set -euo pipefail
ROOT="${0:A:h:h}"
cd "$ROOT"
if [[ ! -x .venv/bin/python ]]; then
  echo "Creating CANA Python environment..."
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import numpy' >/dev/null 2>&1; then
  echo "Installing NumPy into CANA environment..."
  .venv/bin/python -m pip install --quiet --upgrade pip numpy
fi
print -r -- "$ROOT/.venv/bin/python"
