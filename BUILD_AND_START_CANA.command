#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
./BUILD_CANA_FIELD.command
./START_CANA.command
