#!/usr/bin/env python3
"""Serve the CANA browser field and same-origin ARBITER fallback."""
from __future__ import annotations

import argparse
import array
import json
import math
import os
import posixpath
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


class CanaField:
    def __init__(self, root: Path, embed_url: str) -> None:
        self.root = root.resolve()
        self.embed_url = embed_url
        self.manifest_path = self.root / "field" / "browser_field.json"
        self.products_path = self.root / "data" / "browser_products.json"
        self.vectors_path = self.root / "field" / "browser_vectors.f32"
        self.manifest: dict[str, Any] = {}
        self.products: list[dict[str, Any]] = []
        self.vectors = array.array("f")
        self.dim = 72
        self.load()

    def load(self) -> None:
        missing = [
            str(path)
            for path in (self.manifest_path, self.products_path, self.vectors_path)
            if not path.is_file()
        ]
        if missing:
            raise RuntimeError("Missing CANA browser field files: " + ", ".join(missing))
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.products = json.loads(self.products_path.read_text(encoding="utf-8"))
        self.dim = int(self.manifest.get("dim") or self.manifest.get("dimension") or 72)
        if self.dim != 72:
            raise RuntimeError(f"Expected 72D field, received {self.dim}D")
        self.vectors = array.array("f")
        with self.vectors_path.open("rb") as handle:
            self.vectors.fromfile(handle, self.vectors_path.stat().st_size // self.vectors.itemsize)
        expected = len(self.products) * self.dim
        if len(self.vectors) != expected:
            raise RuntimeError(f"Vector length {len(self.vectors):,} != {len(self.products):,} × {self.dim}")

    @property
    def count(self) -> int:
        return len(self.products)

    def public_manifest(self) -> dict[str, Any]:
        return {
            **self.manifest,
            "ok": True,
            "count": self.count,
            "dim": self.dim,
            "dimension": self.dim,
            "embed_url": self.embed_url,
            "fast_embed_url": self.embed_url,
            "design_schema": "cana-effect-design-v1",
            "design_ready": True,
        }

    @staticmethod
    def _vectors_from_response(data: dict[str, Any]) -> list[list[float]]:
        rows: Any = data.get("vectors") or data.get("embeddings") or data.get("data")
        if isinstance(rows, dict):
            rows = rows.get("vectors") or rows.get("embeddings") or rows.get("data")
        if not isinstance(rows, list):
            single = data.get("embedding") or data.get("vector")
            rows = [single] if isinstance(single, list) else None
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("ARBITER returned no vectors")
        vectors: list[list[float]] = []
        for row in rows:
            values: Any = row.get("embedding") or row.get("vector") if isinstance(row, dict) else row
            if not isinstance(values, list) or len(values) != 72:
                raise RuntimeError("ARBITER returned a non-72D vector")
            vector = [float(value) for value in values]
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / norm for value in vector])
        return vectors

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        request = urllib.request.Request(
            self.embed_url,
            data=json.dumps({"texts": texts, "use_freq": self.manifest.get("use_freq", True)}).encode(),
            headers={"content-type": "application/json", "user-agent": "CANA-effect-design/1.0"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.load(response)
        vectors = self._vectors_from_response(data)
        if len(vectors) != len(texts):
            raise RuntimeError(f"ARBITER returned {len(vectors)} vectors for {len(texts)} texts")
        return vectors

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    @staticmethod
    def category(row: dict[str, Any]) -> str:
        return str(row.get("category") or row.get("type") or row.get("format") or "Uncategorized")

    def search(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("q") or payload.get("query") or payload.get("text") or "").strip()
        category = str(payload.get("category") or payload.get("type") or "all").strip().lower()
        offset = max(0, int(payload.get("offset") or 0))
        limit = min(250, max(1, int(payload.get("limit") or payload.get("k") or 50)))
        rows: list[tuple[float | None, int, dict[str, Any]]] = []

        if text:
            query = self.embed(text)
            for index, row in enumerate(self.products):
                if category != "all" and self.category(row).lower() != category:
                    continue
                base = index * self.dim
                score = 0.0
                for axis in range(self.dim):
                    score += self.vectors[base + axis] * query[axis]
                rows.append((score, index, row))
            rows.sort(key=lambda item: (-float(item[0] or 0.0), item[1]))
            mode = "ARBITER 72D · SAME-ORIGIN FALLBACK"
        else:
            for index, row in enumerate(self.products):
                if category != "all" and self.category(row).lower() != category:
                    continue
                rows.append((None, index, row))
            mode = "LOCAL 72D FIELD"

        total = len(rows)
        page = []
        for score, _, row in rows[offset : offset + limit]:
            item = dict(row)
            if score is not None:
                item["score"] = score
            page.append(item)
        return {"results": page, "total": total, "offset": offset, "limit": limit, "mode": mode}


class Handler(SimpleHTTPRequestHandler):
    server_version = "CANAEffectDesign/1.0"

    @property
    def field(self) -> CanaField:
        return self.server.field  # type: ignore[attr-defined]

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if self.path.startswith(("/field/", "/data/", "/assets/")):
            self.send_header("Cache-Control", "public, max-age=300")
        else:
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}", flush=True)

    def json_response(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = self.path.split("?", 1)[0]
        if parsed in {"/health", "/api/health", "/api/manifest", "/field/v1/manifest"}:
            self.json_response(self.field.public_manifest())
            return
        if parsed == "/design/manifest":
            self.json_response({"schema": "cana-effect-design-v1", "natural_candidate_classes": 16, "dosing_instructions": False})
            return
        super().do_GET()

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_POST(self) -> None:
        parsed = self.path.split("?", 1)[0]
        if parsed not in {"/api/search", "/field/v1/search", "/api/embed"}:
            self.json_response({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("content-length") or 0)
            if length > 1_000_000:
                raise ValueError("request too large")
            payload = json.loads(self.rfile.read(length) or b"{}")
            if parsed == "/api/embed":
                texts = payload.get("texts")
                if not isinstance(texts, list) or not 1 <= len(texts) <= 64:
                    raise ValueError("texts must contain 1 to 64 strings")
                cleaned = [str(text).strip() for text in texts]
                if any(not text for text in cleaned):
                    raise ValueError("texts cannot contain empty values")
                vectors = self.field.embed_many(cleaned)
                self.json_response({"vectors": vectors, "dim": 72})
                return
            self.json_response(self.field.search(payload))
        except urllib.error.HTTPError as error:
            self.json_response({"error": f"ARBITER upstream returned {error.code}"}, HTTPStatus.BAD_GATEWAY)
        except Exception as error:
            self.json_response({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def translate_path(self, path: str) -> str:
        # Pin static resolution to the configured repository root.
        path = path.split("?", 1)[0].split("#", 1)[0]
        path = posixpath.normpath(urllib.request.url2pathname(path))
        words = [word for word in path.split("/") if word and word not in {os.curdir, os.pardir}]
        resolved = self.field.root
        for word in words:
            resolved = resolved / word
        return str(resolved)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], field: CanaField) -> None:
        self.field = field
        super().__init__(address, Handler)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8904)
    parser.add_argument("--embed-url", default=os.environ.get("CANA_EMBED_URL", "https://cana-embed.actualgeneralintelligence.com/v1/embed"))
    args = parser.parse_args()

    field = CanaField(args.root, args.embed_url)
    server = Server((args.host, args.port), field)
    print(f"CANA EFFECT DESIGN · {field.count:,} records · 72D · http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
