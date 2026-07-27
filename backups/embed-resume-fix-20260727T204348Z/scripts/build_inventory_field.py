#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from inventory_data import SCHEMA_VERSION, read_inventory, record_text, source_fingerprint


def post_json(url: str, payload: dict, timeout: int = 120) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json", "user-agent": "CANA-Cookies-field-builder/2.0"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def vectors_from(data: dict) -> list:
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


def embed_batch(url: str, texts: list[str], use_freq: bool, attempts: int = 6) -> np.ndarray:
    error = None
    for attempt in range(attempts):
        try:
            data = post_json(url, {"texts": texts, "use_freq": use_freq})
            array = np.asarray(vectors_from(data), dtype=np.float32)
            if array.shape != (len(texts), 72):
                raise ValueError(f"ARBITER returned {array.shape}; expected {(len(texts), 72)}")
            array /= np.maximum(np.linalg.norm(array, axis=1, keepdims=True), 1e-12)
            return array
        except Exception as exc:
            error = exc
            if attempt + 1 < attempts:
                time.sleep(min(30, 2 ** attempt))
    raise error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--field", default="field")
    parser.add_argument(
        "--embed-url",
        default=os.getenv("ARBITER_EMBED_URL") or "https://api.arbiter.traut.ai/public/embed",
    )
    parser.add_argument("--batch", type=int, default=128)
    parser.add_argument("--conc", type=int, default=2)
    parser.add_argument("--use-freq", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    rows = read_inventory(root)
    if not rows:
        raise SystemExit("No Cookies inventory exists. Run scrape_cookies_inventory.py first.")
    if any(not row.get("image") for row in rows):
        raise SystemExit("Inventory contains records without frozen local images.")

    out = root / args.field
    out.mkdir(parents=True, exist_ok=True)
    fingerprint = source_fingerprint(root)
    vector_path = out / "vectors.npy"
    meta_path = out / "metadata.jsonl"
    manifest_path = out / "manifest.json"
    state_path = out / "build_state.json"

    old = {}
    if manifest_path.exists():
        try:
            old = json.loads(manifest_path.read_text())
        except Exception:
            old = {}
    if (
        old.get("schema_version") == SCHEMA_VERSION
        and old.get("source_fingerprint") == fingerprint
        and int(old.get("count") or 0) == len(rows)
        and vector_path.exists()
        and meta_path.exists()
    ):
        vectors = np.load(vector_path, mmap_mode="r")
        if vectors.shape == (len(rows), 72):
            print(f"COOKIES FIELD READY · reusing {len(rows):,} × 72D")
            return

    for path in (vector_path, meta_path, manifest_path, state_path):
        path.unlink(missing_ok=True)

    texts = [record_text(row) for row in rows]
    if any(not text.strip() for text in texts):
        raise SystemExit("One or more products produced empty embedding text.")

    probe = embed_batch(args.embed_url, ["CANA Cookies inventory embedding health check"], args.use_freq)
    if probe.shape != (1, 72):
        raise SystemExit(f"Expected 72D ARBITER vectors; received {probe.shape}")

    array = np.lib.format.open_memmap(vector_path, mode="w+", dtype="float32", shape=(len(rows), 72))
    batches = [(start, texts[start:start + args.batch]) for start in range(0, len(texts), args.batch)]
    completed = 0
    print(
        f"CANA COOKIES INVENTORY FIELD · {len(rows):,} products · 72D · "
        f"batch {args.batch} · concurrency {args.conc} · use_freq={args.use_freq}"
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.conc)) as pool:
        pending: dict[concurrent.futures.Future, tuple[int, int]] = {}
        iterator = iter(batches)

        def submit_next() -> bool:
            try:
                start, batch_texts = next(iterator)
            except StopIteration:
                return False
            future = pool.submit(embed_batch, args.embed_url, batch_texts, args.use_freq)
            pending[future] = (start, len(batch_texts))
            return True

        for _ in range(max(1, args.conc)):
            submit_next()

        while pending:
            done, _ = concurrent.futures.wait(pending, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                start, size = pending.pop(future)
                vectors = future.result()
                array[start:start + size] = vectors
                completed += size
                array.flush()
                state_path.write_text(json.dumps({
                    "completed": completed,
                    "count": len(rows),
                    "dim": 72,
                    "schema_version": SCHEMA_VERSION,
                    "source_fingerprint": fingerprint,
                    "embed_url": args.embed_url,
                    "use_freq": args.use_freq,
                }, indent=2))
                print(f"embedded {completed:,}/{len(rows):,}", flush=True)
                submit_next()

    with meta_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    source_manifest = {}
    source_path = root / "data/inventory_source_manifest.json"
    if source_path.exists():
        source_manifest = json.loads(source_path.read_text())
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "count": len(rows),
        "dim": 72,
        "source_fingerprint": fingerprint,
        "source": "Cookies Mission Valley / Jane-synced WordPress REST inventory snapshot",
        "source_url": "https://missionvalley.cookies.co",
        "source_snapshot": source_manifest,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "embed_url": args.embed_url,
        "use_freq": args.use_freq,
        "embedding_policy": "Names and brands stripped from free text while controlled category, subcategory, form, and strain-type vocabulary is preserved; price, stock, images, and IDs excluded",
        "image_policy": "Every searchable result has a frozen local product image",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"FIELD READY · {len(rows):,} Cookies products · 72D")


if __name__ == "__main__":
    main()
