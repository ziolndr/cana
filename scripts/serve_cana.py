#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import time
import urllib.request
from collections import OrderedDict
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from threading import Lock

import numpy as np

from inventory_data import SCHEMA_VERSION, normalize_text, read_inventory

ROOT = Path(__file__).resolve().parents[1]
FAST_EMBED_DEFAULT = ""

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "give", "i", "in", "is", "it", "me", "my", "of", "on", "or", "please",
    "show", "smoke", "some", "something", "that", "the", "this", "to", "want",
    "weed", "with", "product", "products", "cannabis",
}
INTENT_WORDS = {
    "high", "clean", "clear", "headed", "focused", "focus", "creative", "social",
    "calm", "relaxed", "relax", "sleep", "sleepy", "energy", "energetic",
    "uplifted", "happy", "euphoric", "functional", "anxiety", "flavor", "taste",
    "citrus", "berry", "earthy", "diesel", "body", "cerebral", "fog", "foggy",
    "talkative", "hungry", "tingly", "motivated", "tropical", "pine", "vape",
    "flower", "edible", "gummy", "disposable", "pre roll", "concentrate",
}
PHRASE_EXPANSIONS = {
    "clean high": "clear headed focused mentally crisp functional balanced uplifted minimal fog",
    "clear high": "clear headed focused functional mentally crisp minimal fog",
    "without anxiety": "calm steady gentle low anxiety",
    "no anxiety": "calm steady gentle low anxiety",
    "not sleepy": "alert awake functional minimal sedation",
    "without sleepiness": "alert awake functional minimal sedation",
    "for sleep": "sleepy deeply relaxed body relaxation nighttime",
    "social": "talkative friendly uplifted euphoric comfortable social",
}


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


_KEY_CACHE = {"value": "", "checked": 0.0}
ARBITER_KEY_FILE = os.path.expanduser(os.getenv("ARBITER_KEY_FILE", "~/.arbiter_api_key"))


def arbiter_key() -> str:
    """Local ARBITER keys are in-memory and die on every server restart.

    Read the key fresh (cached 5s) so REFRESH_CANA_KEY.command can rotate it
    without restarting this process.
    """
    env = os.getenv("ARBITER_API_KEY", "").strip()
    if env:
        return env
    now = time.monotonic()
    if now - _KEY_CACHE["checked"] < 5.0:
        return _KEY_CACHE["value"]
    try:
        with open(ARBITER_KEY_FILE, encoding="utf-8") as handle:
            _KEY_CACHE["value"] = handle.read().strip()
    except OSError:
        _KEY_CACHE["value"] = ""
    _KEY_CACHE["checked"] = now
    return _KEY_CACHE["value"]


def post_json(url: str, payload: dict, timeout: float = 35) -> dict:
    headers = {
        "content-type": "application/json",
        "connection": "keep-alive",
        "user-agent": "CANA-Cookies-field/2.0",
    }
    key = arbiter_key()
    if key:
        headers["authorization"] = f"Bearer {key}"
        headers["x-api-key"] = key
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers=headers,
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


def meaningful_terms(value: str) -> list[str]:
    return [term for term in normalize_text(value).split() if len(term) >= 3 and term not in STOPWORDS]


def expanded_intent(query: str) -> str:
    cleaned = normalize_text(query)
    prefixes = (
        "smoke me for ", "give me ", "find me ", "show me ", "i want ",
        "i need ", "looking for ", "something for ", "something that ",
    )
    for prefix in prefixes:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            break
    cleaned = " ".join(term for term in cleaned.split() if term not in {"a", "an", "the"})
    expanded = cleaned
    for phrase, descriptors in PHRASE_EXPANSIONS.items():
        if phrase in cleaned:
            expanded += " " + descriptors
    return expanded.strip()


def canonicalize_query(query: str) -> str:
    expanded = expanded_intent(query)
    return (
        f"Desired legal cannabis retail product, experience, sensory profile, and format: {expanded}. "
        "Rank by product category, format, reported effects, flavor, aroma, phenotype, lineage, "
        "potency description, and experiential context. Ignore accidental word overlap in brand or product names."
    )


def descriptor_text(row: dict) -> str:
    return normalize_text(" ".join(
        [
            row.get("category") or "",
            row.get("subcategory") or "",
            row.get("form") or "",
            row.get("strain_type") or "",
            row.get("phenotype") or "",
            row.get("lineage") or "",
            row.get("description") or "",
        ]
        + (row.get("effects") or [])
        + (row.get("flavors") or [])
    ))


class LRUCache:
    def __init__(self, maxsize: int = 512):
        self.maxsize = maxsize
        self.data = OrderedDict()
        self.lock = Lock()

    def get(self, key):
        with self.lock:
            value = self.data.get(key)
            if value is not None:
                self.data.move_to_end(key)
            return value

    def put(self, key, value):
        with self.lock:
            self.data[key] = value
            self.data.move_to_end(key)
            while len(self.data) > self.maxsize:
                self.data.popitem(last=False)


class EmbedRouter:
    """Hedged fast-tunnel router with no global network lock.

    The previous server held one lock around the entire outbound embed request. Live
    typing therefore queued every abandoned keystroke behind the previous request.
    This router only locks tiny state updates and lets requests resolve independently.
    """

    def __init__(self, configured_url: str, use_freq: bool):
        candidates = [
            os.getenv("CANA_FAST_EMBED_URL") or FAST_EMBED_DEFAULT,
            configured_url,
            os.getenv("CANA_ARBITER_EMBED_URL"),
            os.getenv("ARBITER_EMBED_URL"),
            "https://api.arbiter.traut.ai/public/embed",
            "http://127.0.0.1:8000/v1/embed",
        ]
        self.candidates: list[str] = []
        for candidate in candidates:
            if candidate and candidate not in self.candidates:
                self.candidates.append(candidate)
        self.active_url: str | None = None
        self.last_error: str | None = None
        self.last_embed_ms: float | None = None
        self.use_freq = bool(use_freq)
        self.state_lock = Lock()
        self.fail_until: dict[str, float] = {}
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="cana-embed")
        self.hedge_seconds = max(0.05, env_float("CANA_EMBED_HEDGE_MS", 280.0) / 1000.0)
        self.failure_cooldown = max(2.0, env_float("CANA_EMBED_FAILURE_COOLDOWN", 20.0))

    def _ordered_candidates(self) -> list[str]:
        now = time.monotonic()
        with self.state_lock:
            active = self.active_url
            available = [url for url in self.candidates if self.fail_until.get(url, 0.0) <= now]
        if not available:
            available = list(self.candidates)
        fast = self.candidates[0] if self.candidates else None
        ordered: list[str] = []
        # Retry the dedicated fast path whenever it is not in cooldown.
        for url in (fast, active, *available):
            if url and url in available and url not in ordered:
                ordered.append(url)
        return ordered

    def _request(self, url: str, texts: list[str], timeout: float) -> tuple[np.ndarray, str, float]:
        started = time.perf_counter()
        vectors = np.asarray(
            vectors_from(post_json(url, {"texts": texts, "use_freq": self.use_freq}, timeout=timeout)),
            dtype=np.float32,
        )
        if vectors.ndim == 1:
            vectors = vectors[None, :]
        if vectors.shape != (len(texts), 72):
            raise ValueError(f"ARBITER returned {vectors.shape}; expected {(len(texts), 72)}")
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return vectors, url, elapsed_ms

    def _mark_success(self, url: str, elapsed_ms: float) -> None:
        with self.state_lock:
            self.active_url = url
            self.last_error = None
            self.last_embed_ms = elapsed_ms
            self.fail_until.pop(url, None)

    def _mark_failure(self, url: str, error: Exception) -> str:
        detail = f"{url}: {type(error).__name__}: {error}"
        with self.state_lock:
            self.fail_until[url] = time.monotonic() + self.failure_cooldown
        return detail

    def embed(self, texts: list[str], timeout: float = 35) -> np.ndarray:
        ordered = self._ordered_candidates()
        if not ordered:
            raise ConnectionError("No ARBITER embed endpoints configured")

        futures: dict[concurrent.futures.Future, str] = {}
        errors: list[str] = []
        next_index = 0

        def launch() -> bool:
            nonlocal next_index
            if next_index >= len(ordered):
                return False
            url = ordered[next_index]
            next_index += 1
            futures[self.pool.submit(self._request, url, texts, timeout)] = url
            return True

        launch()
        # Give the local named tunnel a tiny head start. If it stalls, race the
        # public endpoint instead of making the user wait for a full timeout.
        done, _ = concurrent.futures.wait(
            list(futures), timeout=self.hedge_seconds, return_when=concurrent.futures.FIRST_COMPLETED
        )
        if not done and len(ordered) > 1:
            launch()

        deadline = time.monotonic() + timeout
        while futures:
            remaining = max(0.01, deadline - time.monotonic())
            done, _ = concurrent.futures.wait(
                list(futures), timeout=remaining, return_when=concurrent.futures.FIRST_COMPLETED
            )
            if not done:
                break
            for future in done:
                url = futures.pop(future)
                try:
                    vectors, winner, elapsed_ms = future.result()
                    self._mark_success(winner, elapsed_ms)
                    for pending in futures:
                        pending.cancel()
                    return vectors
                except Exception as error:
                    errors.append(self._mark_failure(url, error))
                    if not futures:
                        launch()

        for future, url in list(futures.items()):
            future.cancel()
            errors.append(f"{url}: timed out")
        with self.state_lock:
            self.active_url = None
            self.last_error = " | ".join(errors)[-2000:]
        raise ConnectionError(self.last_error or "ARBITER embed request failed")

    def probe(self) -> bool:
        try:
            self.embed(["CANA Cookies inventory query probe"], timeout=12)
            return True
        except Exception:
            return False


class App(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if self.path.startswith("/api/") or self.path == "/health":
            return
        super().log_message(fmt, *args)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store" if self.path.startswith("/api/") else "public, max-age=300")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def manifest_payload(self):
        categories = sorted({row.get("category") or "Cannabis" for row in self.server.rows})
        router = self.server.embed_router
        return {
            "count": len(self.server.rows),
            "dim": 72,
            "field_ready": self.server.vectors is not None,
            "schema_version": self.server.schema_version,
            "embed_ready": router.active_url is not None,
            "embed_url": router.active_url,
            "fast_embed_url": router.candidates[0] if router.candidates else None,
            "last_embed_ms": router.last_embed_ms,
            "last_embed_error": router.last_error,
            "use_freq": router.use_freq,
            "source": "Cookies Mission Valley inventory snapshot",
            "scraped_at": self.server.manifest.get("source_snapshot", {}).get("scraped_at"),
            "categories": categories,
            "mode": "ARBITER inventory field" if self.server.vectors is not None else "field rebuild required",
        }

    def do_GET(self):
        if self.path.split("?", 1)[0] in ("/api/manifest", "/health"):
            return self.send_json(self.manifest_payload())
        return super().do_GET()

    def query_vector(self, query: str) -> tuple[np.ndarray, float, bool]:
        key = normalize_text(query)
        cached = self.server.vector_cache.get(key)
        if cached is not None:
            return cached, 0.0, True
        started = time.perf_counter()
        value = self.server.embed_router.embed([query])[0]
        value /= max(float(np.linalg.norm(value)), 1e-12)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        self.server.vector_cache.put(key, value)
        return value, elapsed_ms, False

    def strict_lookup(self, indexes: np.ndarray, phrase: str, offset: int, limit: int):
        matches = []
        for index in indexes:
            row = self.server.rows[int(index)]
            names = self.server.identity_values[int(index)]
            weight = 0
            for value in names:
                if not value:
                    continue
                if value == phrase:
                    weight = max(weight, 4)
                elif value.startswith(phrase):
                    weight = max(weight, 3)
                elif phrase in value:
                    weight = max(weight, 2)
            if weight:
                matches.append((weight, row))
        matches.sort(key=lambda item: (-item[0], item[1].get("brand") or "", item[1].get("name") or ""))
        return [{**row, "score": None, "query_mode": "identity"} for _, row in matches[offset:offset + limit]], len(matches)

    def do_POST(self):
        if self.path != "/api/search":
            return self.send_json({"error": "not found"}, 404)
        started = time.perf_counter()
        try:
            length = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            query = str(payload.get("q") or "").strip()
            category = str(payload.get("category") or payload.get("type") or "all")
            offset = max(0, int(payload.get("offset") or 0))
            limit = min(100, max(1, int(payload.get("limit") or 24)))

            indexes = self.server.category_indexes.get(normalize_text(category)) if category != "all" else self.server.all_indexes
            if indexes is None:
                indexes = np.empty(0, dtype=np.int64)

            if not query:
                ordered = self.server.browse_orders.get(normalize_text(category), self.server.browse_orders["all"])
                page = [{**self.server.rows[int(index)], "score": None, "query_mode": "browse"} for index in ordered[offset:offset + limit]]
                return self.send_json({
                    "results": page,
                    "total": len(ordered),
                    "mode": "Cookies inventory snapshot",
                    "query_mode": "browse",
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                    "embed_ms": 0.0,
                    "rank_ms": 0.0,
                })

            phrase = normalize_text(query)
            words = phrase.split()
            exact_identity = phrase in self.server.identity_exact
            has_intent = bool(set(meaningful_terms(query)) & INTENT_WORDS)
            query_mode = "identity" if exact_identity or (len(words) <= 3 and not has_intent and len(phrase) >= 3) else "outcome"

            if query_mode == "identity":
                page, total = self.strict_lookup(indexes, phrase, offset, limit)
                return self.send_json({
                    "results": page,
                    "total": total,
                    "mode": "strict product lookup",
                    "query_mode": query_mode,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                    "embed_ms": 0.0,
                    "rank_ms": 0.0,
                })

            if self.server.vectors is None:
                return self.send_json({
                    "error": "CANA Cookies inventory field is not built.",
                    "code": "FIELD_REBUILD_REQUIRED",
                    "message": "Run BUILD_COOKIES_AND_PUSH.command or BUILD_AND_START_CANA.command.",
                }, 503)

            cache_key = (phrase, normalize_text(category))
            cached_ranking = self.server.ranking_cache.get(cache_key)
            embed_ms = 0.0
            rank_ms = 0.0
            query_text = canonicalize_query(query)
            if cached_ranking is None:
                query_vector, embed_ms, _ = self.query_vector(query_text)
                rank_started = time.perf_counter()
                scores = np.asarray(self.server.vectors[indexes] @ query_vector, dtype=np.float32)
                descriptor_terms = set(meaningful_terms(query_text))
                if descriptor_terms:
                    for position, index in enumerate(indexes):
                        overlap = sum(1 for term in descriptor_terms if term in self.server.descriptor_strings[int(index)])
                        scores[position] += min(0.12, overlap * 0.012)
                order = np.argsort(-scores, kind="stable")
                ranked_indexes = indexes[order]
                ranked_scores = scores[order]
                rank_ms = (time.perf_counter() - rank_started) * 1000.0
                self.server.ranking_cache.put(cache_key, (ranked_indexes, ranked_scores, query_text))
            else:
                ranked_indexes, ranked_scores, query_text = cached_ranking

            page = [
                {**self.server.rows[int(index)], "score": float(ranked_scores[offset + position]), "query_mode": query_mode}
                for position, index in enumerate(ranked_indexes[offset:offset + limit])
            ]
            return self.send_json({
                "results": page,
                "total": len(ranked_indexes),
                "mode": "ARBITER 72D Cookies inventory",
                "query_mode": query_mode,
                "query_text": query_text,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                "embed_ms": round(embed_ms, 1),
                "rank_ms": round(rank_ms, 1),
                "embed_url": self.server.embed_router.active_url,
            })
        except ConnectionError as error:
            return self.send_json({
                "error": "ARBITER query embedding endpoint is offline.",
                "code": "ARBITER_OFFLINE",
                "message": "CANA refused to replace meaning search with product-name substring matches.",
                "detail": str(error),
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            }, 503)
        except Exception as error:
            return self.send_json({"error": str(error), "code": "SEARCH_FAILED"}, 500)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8868")))
    parser.add_argument("--embed-url", default=os.getenv("ARBITER_EMBED_URL") or "https://api.arbiter.traut.ai/public/embed")
    args = parser.parse_args()

    rows = read_inventory(ROOT)
    if not rows:
        raise SystemExit("CANA inventory is missing. Run the build command.")
    manifest = json.loads((ROOT / "field/manifest.json").read_text())
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise SystemExit("CANA inventory field schema mismatch. Rebuild.")
    vectors = np.load(ROOT / "field/vectors.npy", mmap_mode="r")
    if vectors.shape != (len(rows), 72):
        raise SystemExit(f"Field shape {vectors.shape} does not match {(len(rows), 72)}")

    all_indexes = np.arange(len(rows), dtype=np.int64)
    category_indexes: dict[str, np.ndarray] = {}
    for category in sorted({normalize_text(row.get("category") or "Cannabis") for row in rows}):
        category_indexes[category] = np.asarray(
            [index for index, row in enumerate(rows) if normalize_text(row.get("category") or "Cannabis") == category],
            dtype=np.int64,
        )
    browse_orders = {
        "all": np.asarray(sorted(all_indexes, key=lambda index: (
            rows[int(index)].get("category") or "",
            rows[int(index)].get("brand") or "",
            rows[int(index)].get("name") or "",
        )), dtype=np.int64)
    }
    for category, indexes in category_indexes.items():
        browse_orders[category] = np.asarray(sorted(indexes, key=lambda index: (
            rows[int(index)].get("brand") or "",
            rows[int(index)].get("name") or "",
        )), dtype=np.int64)

    identity_values = [
        (
            normalize_text(row.get("name")),
            normalize_text(row.get("brand")),
            normalize_text(row.get("strain")),
        )
        for row in rows
    ]
    identity_exact = {value for values in identity_values for value in values if value}
    descriptor_strings = [descriptor_text(row) for row in rows]

    os.chdir(ROOT)
    server = ThreadingHTTPServer((args.host, args.port), App)
    server.daemon_threads = True
    server.rows = rows
    server.vectors = vectors
    server.schema_version = SCHEMA_VERSION
    server.manifest = manifest
    server.all_indexes = all_indexes
    server.category_indexes = category_indexes
    server.browse_orders = browse_orders
    server.identity_values = identity_values
    server.identity_exact = identity_exact
    server.descriptor_strings = descriptor_strings
    server.vector_cache = LRUCache(maxsize=1024)
    server.ranking_cache = LRUCache(maxsize=256)
    field_use_freq = bool(manifest.get("use_freq", True))
    server.embed_router = EmbedRouter(args.embed_url, field_use_freq)
    print(
        f"CANA COOKIES · {args.host}:{args.port} · {len(rows):,} image-backed products · 72D · "
        f"QUERY EMBED LAZY · use_freq={field_use_freq} · server ready",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
