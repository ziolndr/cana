#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "cana-profile-v2"


def post_json(url: str, payload: dict, timeout: int = 120) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json", "user-agent": "CANA-profile-field-builder/2.0"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def vectors_from(data: dict) -> list[list[float]]:
    for key in ("vectors", "embeddings", "data"):
        value = data.get(key) if isinstance(data, dict) else None
        if isinstance(value, list) and value:
            if isinstance(value[0], dict):
                return [item.get("embedding") or item.get("vector") for item in value]
            return value
    for key in ("embedding", "vector"):
        value = data.get(key) if isinstance(data, dict) else None
        if isinstance(value, list):
            return [value] if (not value or not isinstance(value[0], list)) else value
    raise ValueError("ARBITER response contained no vectors")


def load_profiles(path: Path) -> list[dict]:
    profiles: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            profile = json.loads(line)
            if not profile.get("name") or not profile.get("id"):
                raise SystemExit(f"Invalid profile at line {line_number}")
            ready = bool(profile.get("semantic_ready"))
            text = str(profile.get("embedding_text") or "").strip()
            if ready != bool(text):
                raise SystemExit(f"Profile readiness/text mismatch at line {line_number}: {profile.get('name')}")
            profiles.append(profile)
    if not profiles:
        raise SystemExit("No CANA profiles found")
    return profiles


def clean_field(out: Path) -> None:
    for name in ("vectors.npy", "profile_mask.npy", "metadata.jsonl", "manifest.json", "build_state.json"):
        path = out / name
        if path.exists():
            path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", default="data/semantic_profiles.jsonl")
    parser.add_argument("--stats", default="data/profile_stats.json")
    parser.add_argument("--field", default="field")
    parser.add_argument("--embed-url", default=os.getenv("ARBITER_EMBED_URL", "http://127.0.0.1:8000/v1/embed"))
    parser.add_argument("--batch", type=int, default=96)
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()

    profiles_path = (ROOT / args.profiles).resolve()
    stats_path = (ROOT / args.stats).resolve()
    out = (ROOT / args.field).resolve()
    out.mkdir(parents=True, exist_ok=True)
    profiles = load_profiles(profiles_path)
    stats = json.loads(stats_path.read_text()) if stats_path.exists() else {}

    if stats.get("schema_version") != SCHEMA_VERSION or stats.get("name_embedded") is not False:
        raise SystemExit("Profile stats do not certify CANA profile-v2 with names excluded")

    ready_indexes = np.asarray([index for index, profile in enumerate(profiles) if profile["semantic_ready"]], dtype=np.int64)
    if not len(ready_indexes):
        raise SystemExit("No records contain real semantic profile data")

    probe = vectors_from(post_json(args.embed_url, {"texts": ["CANA profile field verification"], "use_freq": True}))[0]
    dim = len(probe)
    if dim != 72:
        raise SystemExit(f"Expected 72D ARBITER vectors, received {dim}D")

    vectors_path = out / "vectors.npy"
    mask_path = out / "profile_mask.npy"
    metadata_path = out / "metadata.jsonl"
    state_path = out / "build_state.json"

    if args.fresh:
        clean_field(out)

    start = 0
    can_resume = vectors_path.exists() and mask_path.exists() and metadata_path.exists() and state_path.exists()
    if can_resume:
        state = json.loads(state_path.read_text())
        if (
            state.get("schema_version") == SCHEMA_VERSION
            and int(state.get("catalog_count") or 0) == len(profiles)
            and int(state.get("semantic_count") or 0) == len(ready_indexes)
        ):
            start = int(state.get("completed_profiles") or 0)
            vectors = np.lib.format.open_memmap(vectors_path, mode="r+", dtype="float32", shape=(len(profiles), dim))
        else:
            clean_field(out)
            can_resume = False

    if not can_resume:
        vectors = np.lib.format.open_memmap(vectors_path, mode="w+", dtype="float32", shape=(len(profiles), dim))
        vectors[:] = 0
        vectors.flush()
        mask = np.zeros(len(profiles), dtype=np.bool_)
        mask[ready_indexes] = True
        np.save(mask_path, mask)
        with metadata_path.open("w", encoding="utf-8") as handle:
            for profile in profiles:
                metadata = {key: value for key, value in profile.items() if key != "embedding_text"}
                handle.write(json.dumps(metadata, ensure_ascii=False) + "\n")
        start = 0

    print(
        f"CANA PROFILE FIELD · {len(profiles):,} catalog records · {len(ready_indexes):,} profiled · "
        f"{dim}D · starting at {start:,}"
    )

    for position in range(start, len(ready_indexes), args.batch):
        batch_indexes = ready_indexes[position:position + args.batch]
        texts = [profiles[int(index)]["embedding_text"] for index in batch_indexes]
        error: Exception | None = None
        for attempt in range(5):
            try:
                batch_vectors = np.asarray(
                    vectors_from(post_json(args.embed_url, {"texts": texts, "use_freq": True})),
                    dtype=np.float32,
                )
                if batch_vectors.shape != (len(batch_indexes), dim):
                    raise ValueError(f"Bad vector shape {batch_vectors.shape}")
                norms = np.linalg.norm(batch_vectors, axis=1, keepdims=True)
                batch_vectors = batch_vectors / np.maximum(norms, 1e-12)
                vectors[batch_indexes] = batch_vectors
                vectors.flush()
                error = None
                break
            except Exception as caught:
                error = caught
                time.sleep(min(20, 2 ** attempt))
        if error is not None:
            raise error
        completed = position + len(batch_indexes)
        state_path.write_text(json.dumps({
            "schema_version": SCHEMA_VERSION,
            "completed_profiles": completed,
            "catalog_count": len(profiles),
            "semantic_count": len(ready_indexes),
            "dim": dim,
            "embed_url": args.embed_url,
        }, indent=2))
        print(f"embedded {completed:,}/{len(ready_indexes):,} profiles", flush=True)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "count": len(profiles),
        "catalog_count": len(profiles),
        "semantic_count": len(ready_indexes),
        "dim": dim,
        "name_embedded": False,
        "embedded_fields": [
            "reported effects", "aroma and flavor", "laboratory terpenes", "laboratory cannabinoids",
            "reported terpenes", "experience description", "lineage", "classification", "breeder/source",
        ],
        "coverage": stats.get("coverage", {}),
        "sources": stats.get("source_urls", []),
        "matching": stats.get("matching"),
        "chemistry": stats.get("chemistry"),
        "built_at": datetime.now(timezone.utc).isoformat(),
        "embed_url": args.embed_url,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"FIELD READY · {len(profiles):,} catalog · {len(ready_indexes):,} profiled · {dim}D · names excluded")


if __name__ == "__main__":
    main()
