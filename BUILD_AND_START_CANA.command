#!/bin/zsh
set -euo pipefail
cd "${0:A:h}"
./BUILD_CANA_FIELD.command
./START_CANA.command
