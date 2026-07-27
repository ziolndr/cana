#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from inventory_data import SCHEMA_VERSION, read_inventory, record_text, source_fingerprint


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    rows = read_inventory(root)
    manifest = json.loads((root / "field/manifest.json").read_text())
    vectors = np.load(root / "field/vectors.npy", mmap_mode="r")

    checks = {
        "schema": manifest.get("schema_version") == SCHEMA_VERSION,
        "count": int(manifest.get("count") or 0) == len(rows),
        "shape": vectors.shape == (len(rows), 72),
        "fingerprint": manifest.get("source_fingerprint") == source_fingerprint(root),
        "images": all(row.get("image") and (root / row["image"]).exists() for row in rows),
        "stock": all(row.get("in_stock") is not False for row in rows),
    }
    norms = np.linalg.norm(np.asarray(vectors[: min(len(rows), 1000)]), axis=1)
    checks["normalized"] = bool(np.all(np.isfinite(norms)) and np.max(np.abs(norms - 1.0)) < 1e-3)

    # Names/brands must not leak into the embedding text through metadata assembly.
    leaked = []
    for row in rows[: min(len(rows), 500)]:
        text = record_text(row).lower()
        for field in ("name", "brand"):
            value = str(row.get(field) or "").strip().lower()
            if len(value) >= 8 and value in text:
                leaked.append((row.get("id"), field, value))
    checks["metadata_exclusion"] = not leaked

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise SystemExit(f"CANA Cookies field verification failed: {', '.join(failed)}; leaks={leaked[:3]}")
    print(f"VERIFY PASS · {len(rows):,} products · {vectors.shape[1]}D · every result image-backed")


if __name__ == "__main__":
    main()
