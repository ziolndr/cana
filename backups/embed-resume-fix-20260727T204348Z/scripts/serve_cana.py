#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.request
from collections import OrderedDict
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from threading import Lock

import numpy as np

from inventory_data import SCHEMA_VERSION, normalize_text, read_inventory

ROOT = Path(__file__).resolve().parents[1]

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


def post_json(url: str, payload: dict, timeout: int = 35) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json", "user-agent": "CANA-Cookies-field/1.0"},
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
    def __init__(self, configured_url: str):
        candidates = [
            configured_url,
            os.getenv("CANA_ARBITER_EMBED_URL"),
            os.getenv("ARBITER_EMBED_URL"),
            "https://api.arbiter.traut.ai/public/embed",
            "http://127.0.0.1:8000/v1/embed",
        ]
        self.candidates = []
        for candidate in candidates:
            if candidate and candidate not in self.candidates:
                self.candidates.append(candidate)
        self.active_url = None
        self.last_error = None
        self.lock = Lock()

    def embed(self, texts: list[str], timeout: int = 35) -> np.ndarray:
        with self.lock:
            ordered = ([self.active_url] if self.active_url else []) + [url for url in self.candidates if url != self.active_url]
            errors = []
            for url in ordered:
                try:
                    vectors = np.asarray(vectors_from(post_json(url, {"texts": texts, "use_freq": False}, timeout=timeout)), dtype=np.float32)
                    if vectors.ndim == 1:
                        vectors = vectors[None, :]
                    if vectors.shape != (len(texts), 72):
                        raise ValueError(f"ARBITER returned {vectors.shape}; expected {(len(texts), 72)}")
                    self.active_url = url
                    self.last_error = None
                    return vectors
                except Exception as error:
                    errors.append(f"{url}: {error}")
            self.active_url = None
            self.last_error = " | ".join(errors)[-1600:]
            raise ConnectionError(self.last_error)

    def probe(self) -> bool:
        try:
            self.embed(["CANA Cookies inventory query probe"], timeout=8)
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
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def manifest_payload(self):
        categories = sorted({row.get("category") or "Cannabis" for row in self.server.rows})
        return {
            "count": len(self.server.rows),
            "dim": 72,
            "field_ready": self.server.vectors is not None,
            "schema_version": self.server.schema_version,
            "embed_ready": self.server.embed_router.active_url is not None,
            "embed_url": self.server.embed_router.active_url,
            "last_embed_error": self.server.embed_router.last_error,
            "source": "Cookies Mission Valley inventory snapshot",
            "scraped_at": self.server.manifest.get("source_snapshot", {}).get("scraped_at"),
            "categories": categories,
            "mode": "ARBITER inventory field" if self.server.vectors is not None else "field rebuild required",
        }

    def do_GET(self):
        if self.path.split("?", 1)[0] in ("/api/manifest", "/health"):
            return self.send_json(self.manifest_payload())
        return super().do_GET()

    def query_vector(self, query: str) -> np.ndarray:
        key = normalize_text(query)
        cached = self.server.vector_cache.get(key)
        if cached is not None:
            return cached
        value = self.server.embed_router.embed([query])[0]
        value /= max(float(np.linalg.norm(value)), 1e-12)
        self.server.vector_cache.put(key, value)
        return value

    def strict_lookup(self, indexes: np.ndarray, phrase: str, offset: int, limit: int):
        matches = []
        for index in indexes:
            row = self.server.rows[int(index)]
            names = [normalize_text(row.get("name")), normalize_text(row.get("brand")), normalize_text(row.get("strain"))]
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
            limit = min(100, max(1, int(payload.get("limit") or 50)))

            indexes = np.arange(len(self.server.rows), dtype=np.int64)
            if category != "all":
                target = normalize_text(category)
                indexes = np.asarray([index for index in indexes if normalize_text(self.server.rows[int(index)].get("category")) == target], dtype=np.int64)

            if not query:
                ordered = sorted(indexes, key=lambda index: (
                    self.server.rows[int(index)].get("category") or "",
                    self.server.rows[int(index)].get("brand") or "",
                    self.server.rows[int(index)].get("name") or "",
                ))
                page = [{**self.server.rows[int(index)], "score": None, "query_mode": "browse"} for index in ordered[offset:offset + limit]]
                return self.send_json({
                    "results": page,
                    "total": len(ordered),
                    "mode": "Cookies inventory snapshot",
                    "query_mode": "browse",
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                })

            phrase = normalize_text(query)
            words = phrase.split()
            exact_identity = any(
                phrase in {normalize_text(self.server.rows[int(index)].get("name")), normalize_text(self.server.rows[int(index)].get("brand")), normalize_text(self.server.rows[int(index)].get("strain"))}
                for index in indexes
            )
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
                })

            if self.server.vectors is None:
                return self.send_json({
                    "error": "CANA Cookies inventory field is not built.",
                    "code": "FIELD_REBUILD_REQUIRED",
                    "message": "Run BUILD_COOKIES_AND_PUSH.command or BUILD_AND_START_CANA.command.",
                }, 503)

            query_text = canonicalize_query(query)
            query_vector = self.query_vector(query_text)
            scores = self.server.vectors[indexes] @ query_vector
            descriptor_terms = set(meaningful_terms(query_text))
            for position, index in enumerate(indexes):
                row = self.server.rows[int(index)]
                descriptors = normalize_text(" ".join(
                    [row.get("category") or "", row.get("subcategory") or "", row.get("form") or "", row.get("strain_type") or "", row.get("phenotype") or "", row.get("lineage") or "", row.get("description") or ""]
                    + (row.get("effects") or []) + (row.get("flavors") or [])
                ))
                overlap = sum(1 for term in descriptor_terms if term in descriptors)
                scores[position] += min(0.12, overlap * 0.012)

            order = np.argsort(-scores, kind="stable")
            ranked_indexes = indexes[order]
            ranked_scores = scores[order]
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

    os.chdir(ROOT)
    server = ThreadingHTTPServer((args.host, args.port), App)
    server.rows = rows
    server.vectors = vectors
    server.schema_version = SCHEMA_VERSION
    server.manifest = manifest
    server.vector_cache = LRUCache()
    server.embed_router = EmbedRouter(args.embed_url)
    embed_ready = server.embed_router.probe()
    print(
        f"CANA COOKIES · {args.host}:{args.port} · {len(rows):,} image-backed products · 72D · "
        + (f"QUERY EMBED {server.embed_router.active_url}" if embed_ready else "QUERY EMBED OFFLINE"),
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
