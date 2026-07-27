#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FIELD = ROOT / "field"
SCHEMA_VERSION = "cana-profile-v2"


def catalog_count() -> int:
    with (ROOT / "data" / "strains.csv").open(encoding="utf-8-sig", newline="") as handle:
        return sum(1 for row in csv.DictReader(handle) if (row.get("Strain") or "").strip())


def main() -> None:
    required = {
        "vectors": FIELD / "vectors.npy",
        "mask": FIELD / "profile_mask.npy",
        "manifest": FIELD / "manifest.json",
        "metadata": FIELD / "metadata.jsonl",
        "profiles": ROOT / "data" / "semantic_profiles.jsonl",
    }
    missing = [name for name, path in required.items() if not path.exists()]
    if missing:
        raise SystemExit("CANA profile field is incomplete: " + ", ".join(missing))

    expected_count = catalog_count()
    vectors = np.load(required["vectors"], mmap_mode="r")
    mask = np.load(required["mask"], mmap_mode="r")
    if vectors.shape != (expected_count, 72):
        raise SystemExit(f"CANA field shape {vectors.shape} does not match {(expected_count, 72)}")
    if mask.shape != (expected_count,) or mask.dtype != np.bool_:
        raise SystemExit(f"CANA profile mask {mask.shape}/{mask.dtype} is invalid")

    manifest = json.loads(required["manifest"].read_text())
    semantic_count = int(mask.sum())
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise SystemExit("Old CANA name-only field detected; rebuild required")
    if manifest.get("name_embedded") is not False:
        raise SystemExit("CANA manifest does not certify that names were excluded")
    if int(manifest.get("catalog_count") or manifest.get("count") or 0) != expected_count:
        raise SystemExit("CANA manifest catalog count does not match")
    if int(manifest.get("semantic_count") or 0) != semantic_count or int(manifest.get("dim") or 0) != 72:
        raise SystemExit("CANA manifest semantic count or dimension does not match")

    metadata_count = sum(1 for line in required["metadata"].open(encoding="utf-8") if line.strip())
    profile_count = 0
    ready_count = 0
    forbidden_markers = ("Registered name:", "Name tokens:", "Cannabis variety record. Registered")
    with required["profiles"].open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            profile_count += 1
            profile = json.loads(line)
            if profile.get("semantic_ready"):
                ready_count += 1
                text = str(profile.get("embedding_text") or "")
                if not text:
                    raise SystemExit(f"Ready profile has no embedding text: {profile.get('name')}")
                if any(marker in text for marker in forbidden_markers):
                    raise SystemExit(f"Identity-only marker leaked into profile: {profile.get('name')}")
            elif profile.get("embedding_text"):
                raise SystemExit(f"Unprofiled record has embedding text: {profile.get('name')}")

    if metadata_count != expected_count or profile_count != expected_count or ready_count != semantic_count:
        raise SystemExit(
            f"CANA counts disagree: catalog={expected_count}, metadata={metadata_count}, "
            f"profiles={profile_count}, ready={ready_count}, mask={semantic_count}"
        )

    ready_norms = np.linalg.norm(vectors[mask], axis=1)
    if not np.all(np.isfinite(ready_norms)) or not np.allclose(ready_norms, 1.0, atol=2e-4):
        raise SystemExit("Profiled CANA vectors are not finite unit vectors")
    if np.any(vectors[~mask] != 0):
        raise SystemExit("Unprofiled catalog records contain vectors; name-only leakage is possible")

    fields = set(manifest.get("embedded_fields") or [])
    if not {"reported effects", "laboratory terpenes", "laboratory cannabinoids"}.issubset(fields):
        raise SystemExit("CANA manifest is missing required profile fields")

    print(
        f"CANA FIELD VERIFIED · {expected_count:,} catalog records · {semantic_count:,} real profiles · "
        "72D · names excluded"
    )


if __name__ == "__main__":
    main()
