#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FIELD = ROOT / "field"


def catalog_count() -> int:
    with (ROOT / "data" / "strains.csv").open(encoding="utf-8-sig", newline="") as handle:
        return sum(1 for row in csv.DictReader(handle) if (row.get("Strain") or "").strip())


def main() -> None:
    vectors_path = FIELD / "vectors.npy"
    manifest_path = FIELD / "manifest.json"
    metadata_path = FIELD / "metadata.jsonl"
    if not vectors_path.exists() or not manifest_path.exists() or not metadata_path.exists():
        raise SystemExit("CANA field is incomplete")

    expected_count = catalog_count()
    vectors = np.load(vectors_path, mmap_mode="r")
    if vectors.shape != (expected_count, 72):
        raise SystemExit(f"CANA field shape {vectors.shape} does not match {(expected_count, 72)}")

    manifest = json.loads(manifest_path.read_text())
    if int(manifest.get("count") or 0) != expected_count or int(manifest.get("dim") or 0) != 72:
        raise SystemExit("CANA manifest does not match the catalog")

    metadata_count = sum(1 for line in metadata_path.open(encoding="utf-8") if line.strip())
    if metadata_count != expected_count:
        raise SystemExit(f"CANA metadata count {metadata_count} does not match {expected_count}")

    print(f"CANA FIELD VERIFIED · {expected_count:,} records · 72D")


if __name__ == "__main__":
    main()
