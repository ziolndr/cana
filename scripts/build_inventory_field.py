#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import random
import socket
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from inventory_data import SCHEMA_VERSION, read_inventory, record_text, source_fingerprint


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def atomic_json(path: Path, payload: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp.replace(path)


def post_json(url: str, payload: dict, timeout: int) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "content-type": "application/json",
            "user-agent": "CANA-Cookies-field-builder/3.0",
            "connection": "close",
        },
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


def embed_batch(
    url: str,
    texts: list[str],
    use_freq: bool,
    timeout: int,
    attempts: int,
) -> np.ndarray:
    error: Exception | None = None
    for attempt in range(attempts):
        try:
            data = post_json(url, {"texts": texts, "use_freq": use_freq}, timeout=timeout)
            array = np.asarray(vectors_from(data), dtype=np.float32)
            if array.shape != (len(texts), 72):
                raise ValueError(f"ARBITER returned {array.shape}; expected {(len(texts), 72)}")
            array /= np.maximum(np.linalg.norm(array, axis=1, keepdims=True), 1e-12)
            return array
        except Exception as exc:  # network, HTTP, JSON, or shape failure
            error = exc
            if attempt + 1 < attempts:
                delay = min(30.0, (2 ** attempt) + random.random())
                print(
                    f"retry {attempt + 1}/{attempts - 1} · {len(texts)} texts · "
                    f"{type(exc).__name__}: {exc} · sleeping {delay:.1f}s",
                    flush=True,
                )
                time.sleep(delay)
    assert error is not None
    raise error


def embed_range(
    url: str,
    start: int,
    texts: list[str],
    use_freq: bool,
    timeout: int,
    attempts: int,
    min_batch: int,
) -> list[tuple[int, np.ndarray]]:
    # Large requests get a few retries. If they still fail, split them instead of
    # throwing away the completed field. Small requests receive the full retry budget.
    local_attempts = min(attempts, 3) if len(texts) > min_batch else attempts
    try:
        return [(start, embed_batch(url, texts, use_freq, timeout, local_attempts))]
    except Exception as exc:
        if len(texts) <= min_batch:
            raise RuntimeError(
                f"ARBITER failed permanently for rows {start}:{start + len(texts)} "
                f"after {local_attempts} attempts: {exc}"
            ) from exc
        midpoint = len(texts) // 2
        print(
            f"batch {start}:{start + len(texts)} failed at size {len(texts)}; "
            f"splitting into {midpoint} + {len(texts) - midpoint}",
            flush=True,
        )
        return (
            embed_range(url, start, texts[:midpoint], use_freq, timeout, attempts, min_batch)
            + embed_range(url, start + midpoint, texts[midpoint:], use_freq, timeout, attempts, min_batch)
        )


def completed_mask(array: np.ndarray) -> np.ndarray:
    finite = np.isfinite(array).all(axis=1)
    if not finite.any():
        return finite
    norms = np.zeros(array.shape[0], dtype=np.float32)
    norms[finite] = np.linalg.norm(array[finite], axis=1)
    return finite & (norms > 0.5)


def missing_batches(mask: np.ndarray, batch_size: int) -> list[tuple[int, int]]:
    batches: list[tuple[int, int]] = []
    index = 0
    count = len(mask)
    while index < count:
        if mask[index]:
            index += 1
            continue
        run_start = index
        while index < count and not mask[index]:
            index += 1
        run_end = index
        for start in range(run_start, run_end, batch_size):
            batches.append((start, min(run_end, start + batch_size)))
    return batches


def state_config(
    *,
    fingerprint: str,
    count: int,
    embed_url: str,
    use_freq: bool,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "source_fingerprint": fingerprint,
        "count": count,
        "dim": 72,
        "embed_url": embed_url,
        "use_freq": use_freq,
    }


def state_matches(state: dict, config: dict) -> bool:
    return all(state.get(key) == value for key, value in config.items())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--field", default="field")
    parser.add_argument(
        "--embed-url",
        default=os.getenv("ARBITER_EMBED_URL") or "https://api.arbiter.traut.ai/public/embed",
    )
    parser.add_argument("--batch", type=int, default=int(os.getenv("CANA_EMBED_BATCH", "64")))
    parser.add_argument("--conc", type=int, default=int(os.getenv("CANA_EMBED_CONCURRENCY", "2")))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("CANA_EMBED_TIMEOUT", "180")))
    parser.add_argument("--attempts", type=int, default=int(os.getenv("CANA_EMBED_ATTEMPTS", "6")))
    parser.add_argument("--min-batch", type=int, default=int(os.getenv("CANA_EMBED_MIN_BATCH", "8")))
    frequency = parser.add_mutually_exclusive_group()
    frequency.add_argument("--use-freq", dest="use_freq", action="store_true")
    frequency.add_argument("--no-use-freq", dest="use_freq", action="store_false")
    parser.set_defaults(use_freq=env_bool("CANA_USE_FREQ", True))
    args = parser.parse_args()

    if args.batch < 1 or args.conc < 1 or args.timeout < 1 or args.attempts < 1 or args.min_batch < 1:
        raise SystemExit("batch, concurrency, timeout, attempts, and min-batch must be positive")

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

    config = state_config(
        fingerprint=fingerprint,
        count=len(rows),
        embed_url=args.embed_url,
        use_freq=args.use_freq,
    )

    old_manifest: dict = {}
    if manifest_path.exists():
        try:
            old_manifest = json.loads(manifest_path.read_text())
        except Exception:
            old_manifest = {}
    if (
        state_matches(old_manifest, config)
        and vector_path.exists()
        and meta_path.exists()
    ):
        vectors = np.load(vector_path, mmap_mode="r")
        if vectors.shape == (len(rows), 72) and completed_mask(vectors).all():
            print(
                f"COOKIES FIELD READY · reusing {len(rows):,} × 72D · "
                f"use_freq={args.use_freq}"
            )
            return

    texts = [record_text(row) for row in rows]
    if any(not text.strip() for text in texts):
        raise SystemExit("One or more products produced empty embedding text.")

    prior_state: dict = {}
    if state_path.exists():
        try:
            prior_state = json.loads(state_path.read_text())
        except Exception:
            prior_state = {}

    can_resume = state_matches(prior_state, config) and vector_path.exists()
    if can_resume:
        try:
            array = np.load(vector_path, mmap_mode="r+")
            can_resume = array.shape == (len(rows), 72)
        except Exception:
            can_resume = False

    if not can_resume:
        if vector_path.exists() or state_path.exists():
            previous_freq = prior_state.get("use_freq")
            reason = "configuration changed"
            if previous_freq is not None and previous_freq != args.use_freq:
                reason = f"use_freq changed from {previous_freq} to {args.use_freq}"
            print(f"RESETTING PARTIAL FIELD · {reason}", flush=True)
        for path in (vector_path, meta_path, manifest_path, state_path):
            path.unlink(missing_ok=True)
        array = np.lib.format.open_memmap(
            vector_path,
            mode="w+",
            dtype="float32",
            shape=(len(rows), 72),
        )
        array[:] = np.nan
        array.flush()
    else:
        print("RESUMING EXISTING PARTIAL FIELD", flush=True)

    mask = completed_mask(array)
    completed = int(mask.sum())

    probe = embed_batch(
        args.embed_url,
        ["CANA Cookies inventory embedding health check"],
        args.use_freq,
        min(args.timeout, 30),
        max(2, min(args.attempts, 4)),
    )
    if probe.shape != (1, 72):
        raise SystemExit(f"Expected 72D ARBITER vectors; received {probe.shape}")

    batches = missing_batches(mask, args.batch)
    print(
        f"CANA COOKIES INVENTORY FIELD · {len(rows):,} products · 72D · "
        f"batch {args.batch} · concurrency {args.conc} · use_freq={args.use_freq} · "
        f"timeout {args.timeout}s · resumed {completed:,}",
        flush=True,
    )

    def save_state(last_error: str | None = None) -> None:
        payload = {
            **config,
            "completed": int(mask.sum()),
            "remaining": int((~mask).sum()),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "batch": args.batch,
            "concurrency": args.conc,
            "timeout": args.timeout,
            "attempts": args.attempts,
            "min_batch": args.min_batch,
        }
        if last_error:
            payload["last_error"] = last_error
        atomic_json(state_path, payload)

    save_state()

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.conc) as pool:
            pending: dict[concurrent.futures.Future, tuple[int, int]] = {}
            iterator = iter(batches)

            def submit_next() -> bool:
                try:
                    start, end = next(iterator)
                except StopIteration:
                    return False
                future = pool.submit(
                    embed_range,
                    args.embed_url,
                    start,
                    texts[start:end],
                    args.use_freq,
                    args.timeout,
                    args.attempts,
                    args.min_batch,
                )
                pending[future] = (start, end)
                return True

            for _ in range(args.conc):
                submit_next()

            while pending:
                done, _ = concurrent.futures.wait(
                    pending,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                for future in done:
                    start, end = pending.pop(future)
                    pieces = future.result()
                    for piece_start, vectors in pieces:
                        piece_end = piece_start + len(vectors)
                        array[piece_start:piece_end] = vectors
                        mask[piece_start:piece_end] = True
                    array.flush()
                    save_state()
                    print(
                        f"embedded {int(mask.sum()):,}/{len(rows):,} · "
                        f"last request {start}:{end}",
                        flush=True,
                    )
                    submit_next()
    except BaseException as exc:
        array.flush()
        save_state(f"{type(exc).__name__}: {exc}")
        print(
            f"BUILD PAUSED · {int(mask.sum()):,}/{len(rows):,} safely checkpointed · "
            "rerun the same command to resume",
            flush=True,
        )
        raise

    mask = completed_mask(array)
    if not mask.all():
        missing = np.flatnonzero(~mask)
        raise SystemExit(f"Build ended with {len(missing)} missing vectors; first rows: {missing[:20].tolist()}")

    with meta_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    source_manifest = {}
    source_path = root / "data/inventory_source_manifest.json"
    if source_path.exists():
        source_manifest = json.loads(source_path.read_text())
    manifest = {
        **config,
        "source": "Cookies Mission Valley / Jane-synced WordPress REST inventory snapshot",
        "source_url": "https://missionvalley.cookies.co",
        "source_snapshot": source_manifest,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "embedding_policy": (
            "Names and brands stripped from free text while controlled category, "
            "subcategory, form, and strain-type vocabulary is preserved; price, "
            "stock, images, and IDs excluded"
        ),
        "image_policy": "Every searchable result has a frozen local product image",
        "resume_policy": "Per-row durable checkpointing; failed large requests split automatically",
    }
    atomic_json(manifest_path, manifest)
    save_state()
    print(
        f"FIELD READY · {len(rows):,} Cookies products · 72D · use_freq={args.use_freq}",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("BUILD PAUSED · interrupted · rerun the same command to resume", flush=True)
        raise SystemExit(130)
    except Exception as exc:
        if os.getenv("CANA_DEBUG"):
            raise
        print(f"BUILD STOPPED · {type(exc).__name__}: {exc}", flush=True)
        raise SystemExit(1)
