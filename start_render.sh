#!/usr/bin/env bash
set -euo pipefail

: "${PORT:?Render did not provide PORT}"

ARBITER_EMBED_URL="${ARBITER_EMBED_URL:-https://creation-api.actualgeneralintelligence.com/v1/embed}"
export ARBITER_EMBED_URL

echo
echo "CANA — RENDER STARTUP"
echo "────────────────────────────────────────────────────────"
echo "port:    $PORT"
echo "arbiter: $ARBITER_EMBED_URL"
echo
echo "Proving live ARBITER before CANA starts..."

python3 - "$ARBITER_EMBED_URL" <<'PY'
from __future__ import annotations

import json
import sys
import time
import urllib.request

url = sys.argv[1]

payload = json.dumps(
    {"texts": ["CANA Render startup verification"]}
).encode("utf-8")


def extract_vector(data):
    if isinstance(data, list):
        values = data
    elif isinstance(data, dict):
        values = (
            data.get("embeddings")
            or data.get("vectors")
            or data.get("data")
        )
    else:
        values = None

    if not values:
        raise RuntimeError(
            f"ARBITER returned no vectors: {data}"
        )

    first = values[0]

    if isinstance(first, dict):
        first = (
            first.get("embedding")
            or first.get("vector")
        )

    if not isinstance(first, list):
        raise RuntimeError(
            f"Unexpected ARBITER response: {data}"
        )

    return first


last_error = None

for attempt in range(1, 31):
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "CANA-Render-Startup/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=20,
        ) as response:
            data = json.loads(
                response.read().decode("utf-8")
            )

        vector = extract_vector(data)

        if len(vector) != 72:
            raise RuntimeError(
                f"Expected 72D, received {len(vector)}D"
            )

        print("ARBITER PREFLIGHT: PASS · 72D")
        sys.exit(0)

    except Exception as error:
        last_error = error
        print(
            f"waiting for ARBITER · "
            f"{attempt}/30 · {error}",
            flush=True,
        )
        time.sleep(2)

raise SystemExit(
    f"ARBITER PREFLIGHT FAILED: {last_error}"
)
PY

echo
echo "Starting CANA with live ARBITER only..."

exec python3 serve_cana.py \
  --host 0.0.0.0 \
  --port "$PORT" \
  --embed-url "$ARBITER_EMBED_URL"
