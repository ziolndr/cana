#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
from collections import OrderedDict
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from threading import Lock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / '.cache'
COMMONS_CACHE_PATH = CACHE_DIR / 'commons-images.json'


def post_json(url: str, payload: dict, timeout: int = 60) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={'content-type': 'application/json', 'user-agent': 'CANA-field/9.0'},
        method='POST',
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def get_json(url: str, timeout: int = 10) -> dict:
    request = urllib.request.Request(url, headers={'user-agent': 'CANA-field/9.0 (open media resolver)'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def vector_from_response(data: dict):
    for key in ('vectors', 'embeddings', 'data'):
        value = data.get(key) if isinstance(data, dict) else None
        if isinstance(value, list) and value:
            if isinstance(value[0], dict):
                return value[0].get('embedding') or value[0].get('vector')
            return value[0] if isinstance(value[0], list) else value
    return data.get('embedding') or data.get('vector')


def tokens(value: object) -> list[str]:
    return ''.join(char.lower() if char.isalnum() else ' ' for char in str(value)).split()


def normalize_text(value: object) -> str:
    return ' '.join(tokens(value))


def metadata_value(metadata: dict, key: str) -> str:
    value = metadata.get(key, {}).get('value', '') if isinstance(metadata, dict) else ''
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', str(value)))).strip()


class LRUCache:
    def __init__(self, maxsize: int = 384):
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


class CommonsCache:
    def __init__(self):
        self.lock = Lock()
        self.data = {}
        try:
            if COMMONS_CACHE_PATH.exists():
                self.data = json.loads(COMMONS_CACHE_PATH.read_text())
        except Exception:
            self.data = {}

    def get(self, key):
        with self.lock:
            return self.data.get(key, '__missing__')

    def put(self, key, value):
        with self.lock:
            self.data[key] = value
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            temp = COMMONS_CACHE_PATH.with_suffix('.tmp')
            temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2))
            temp.replace(COMMONS_CACHE_PATH)


def commons_candidate_score(page: dict, name: str) -> int:
    query = normalize_text(name)
    terms = [term for term in query.split() if len(term) > 1]
    title = normalize_text(re.sub(r'^File:', '', str(page.get('title', '')), flags=re.I).rsplit('.', 1)[0])
    info = (page.get('imageinfo') or [{}])[0]
    metadata = info.get('extmetadata') or {}
    description = normalize_text(' '.join([
        metadata_value(metadata, 'ImageDescription'),
        metadata_value(metadata, 'ObjectName'),
        metadata_value(metadata, 'Categories'),
    ]))
    haystack = f'{title} {description}'
    if terms and not all(term in haystack for term in terms):
        return -1
    score = 0
    if title == query:
        score += 120
    if query and query in title:
        score += 55
    for term in terms:
        if term in title:
            score += 10
        if term in description:
            score += 2
    if any(word in haystack for word in ('cannabis', 'marijuana', 'strain', 'cultivar')):
        score += 28
    if any(word in haystack for word in ('logo', 'map', 'chart', 'package', 'packaging', 'seed packet')):
        score -= 40
    return score


def resolve_commons_image(name: str, cache: CommonsCache):
    key = normalize_text(name)
    if not key:
        return None
    cached = cache.get(key)
    if cached != '__missing__':
        return cached

    safe_name = re.sub(r'["\n\r]+', ' ', name).strip()
    params = {
        'action': 'query',
        'format': 'json',
        'generator': 'search',
        'gsrsearch': f'intitle:"{safe_name}" cannabis',
        'gsrnamespace': '6',
        'gsrlimit': '10',
        'prop': 'imageinfo',
        'iiprop': 'url|extmetadata',
        'iiurlwidth': '900',
    }
    url = 'https://commons.wikimedia.org/w/api.php?' + urllib.parse.urlencode(params)
    try:
        data = get_json(url, timeout=9)
        pages = list((data.get('query', {}).get('pages') or {}).values())
        pages.sort(key=lambda page: commons_candidate_score(page, name), reverse=True)
        selected = next(
            (
                page for page in pages
                if commons_candidate_score(page, name) >= 30
                and (page.get('imageinfo') or [{}])[0].get('thumburl')
            ),
            None,
        )
        if selected is None:
            cache.put(key, None)
            return None
        info = selected['imageinfo'][0]
        metadata = info.get('extmetadata') or {}
        result = {
            'name': name,
            'image': info.get('thumburl') or info.get('url'),
            'source': metadata_value(metadata, 'Artist') or metadata_value(metadata, 'Credit') or 'Wikimedia Commons contributor',
            'license': metadata_value(metadata, 'LicenseShortName') or metadata_value(metadata, 'UsageTerms') or 'See file page',
            'source_url': info.get('descriptionurl') or 'https://commons.wikimedia.org/wiki/' + urllib.parse.quote(selected.get('title', '').replace(' ', '_')),
        }
        cache.put(key, result)
        return result
    except Exception:
        # Network failures are not cached permanently; the next launch can retry.
        return None


class App(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if self.path.startswith('/api/'):
            return
        super().log_message(fmt, *args)

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-store, max-age=0')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Headers', 'content-type')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.end_headers()

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('content-type', 'application/json; charset=utf-8')
        self.send_header('content-length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/health':
            return self.send_json({
                'ok': True,
                'service': 'cana',
                'count': len(self.server.rows),
                'field_ready': self.server.vectors is not None,
                'dim': 72 if self.server.vectors is not None else None,
            })
        if parsed.path == '/api/manifest':
            return self.send_json({
                'count': len(self.server.rows),
                'dim': 72 if self.server.vectors is not None else None,
                'field_ready': self.server.vectors is not None,
                'mode': 'ARBITER 72D' if self.server.vectors is not None else 'local name index',
            })
        if parsed.path == '/api/image':
            name = urllib.parse.parse_qs(parsed.query).get('name', [''])[0].strip()
            if not name:
                return self.send_json({'image': None}, 400)
            result = resolve_commons_image(name, self.server.commons_cache)
            return self.send_json(result or {'image': None})
        return super().do_GET()

    def query_vector(self, query: str):
        key = normalize_text(query)
        cached = self.server.vector_cache.get(key)
        if cached is not None:
            return cached
        value = np.asarray(
            vector_from_response(post_json(self.server.embed_url, {'texts': [query], 'use_freq': True})),
            dtype=np.float32,
        )
        if value.ndim != 1 or value.shape[0] != 72:
            raise ValueError(f'ARBITER returned vector shape {value.shape}; expected (72,)')
        value /= max(float(np.linalg.norm(value)), 1e-12)
        self.server.vector_cache.put(key, value)
        return value

    def do_POST(self):
        if self.path != '/api/search':
            return self.send_json({'error': 'not found'}, 404)
        started = time.perf_counter()
        try:
            length = int(self.headers.get('content-length', '0'))
            payload = json.loads(self.rfile.read(length) or b'{}')
            query = str(payload.get('q') or '').strip()
            variety_type = str(payload.get('type') or 'all')
            offset = max(0, int(payload.get('offset') or 0))
            limit = min(100, max(1, int(payload.get('limit') or 50)))

            indexes = np.arange(len(self.server.rows), dtype=np.int64)
            if variety_type != 'all':
                indexes = np.asarray([
                    index for index in indexes
                    if self.server.rows[int(index)]['type'] == variety_type
                ], dtype=np.int64)

            if self.server.vectors is not None and query:
                query_vector = self.query_vector(query)
                scores = self.server.vectors[indexes] @ query_vector
                normalized_query = normalize_text(query)
                lexical = np.zeros(len(indexes), dtype=np.float32)
                for position, index in enumerate(indexes):
                    name = normalize_text(self.server.rows[int(index)]['name'])
                    if name == normalized_query:
                        lexical[position] = .18
                    elif name.startswith(normalized_query):
                        lexical[position] = .11
                    elif normalized_query and normalized_query in name:
                        lexical[position] = .065
                scores = scores + lexical
                order = np.argsort(-scores, kind='stable')
                indexes = indexes[order]
                scores = scores[order]
                page = [
                    {**self.server.rows[int(index)], 'score': float(scores[offset + position])}
                    for position, index in enumerate(indexes[offset:offset + limit])
                ]
                return self.send_json({
                    'results': page,
                    'total': len(indexes),
                    'mode': 'ARBITER 72D',
                    'elapsed_ms': round((time.perf_counter() - started) * 1000, 1),
                })

            phrase = normalize_text(query)
            query_terms = tokens(query)
            scored = []
            for index in indexes:
                row = self.server.rows[int(index)]
                name = normalize_text(row['name'])
                score = 80 if phrase and name == phrase else 42 if phrase and name.startswith(phrase) else 25 if phrase and phrase in name else 0
                if query_terms:
                    for term in query_terms:
                        score += 20 if name == term else 10 if name.startswith(term) else 6 if term in name else 0
                    if not score:
                        continue
                priority = self.server.featured_priority.get(name, 99999)
                scored.append((score, priority, row))
            scored.sort(key=lambda item: (-item[0], item[1], item[2]['name'].lower()) if query_terms else (item[1], item[2]['name'].lower()))
            page = [
                {**row, 'score': min(.999, .45 + score / 100) if query_terms else None}
                for score, _, row in scored[offset:offset + limit]
            ]
            return self.send_json({
                'results': page,
                'total': len(scored),
                'mode': 'local name index',
                'elapsed_ms': round((time.perf_counter() - started) * 1000, 1),
            })
        except Exception as error:
            return self.send_json({
                'error': str(error),
                'elapsed_ms': round((time.perf_counter() - started) * 1000, 1),
            }, 500)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default=os.getenv('HOST', '127.0.0.1'))
    parser.add_argument('--port', type=int, default=int(os.getenv('PORT', '8868')))
    parser.add_argument('--embed-url', default=os.getenv('ARBITER_EMBED_URL', 'http://127.0.0.1:8000/v1/embed'))
    args = parser.parse_args()

    rows = []
    with (ROOT / 'data/strains.csv').open(encoding='utf-8-sig', newline='') as handle:
        for item in csv.DictReader(handle):
            name = (item.get('Strain') or '').strip()
            variety_type = (item.get('Type') or '').strip()
            if name:
                rows.append({
                    'id': item['ID'],
                    'name': name,
                    'type': variety_type if variety_type not in ('', '-unknown-') else 'Unclassified',
                })

    featured = json.loads((ROOT / 'data/featured.json').read_text())
    featured_priority = {normalize_text(item['name']): index for index, item in enumerate(featured)}

    vectors = None
    if (ROOT / 'field/manifest.json').exists() and (ROOT / 'field/vectors.npy').exists():
        vectors = np.load(ROOT / 'field/vectors.npy', mmap_mode='r')
        if vectors.shape != (len(rows), 72):
            raise SystemExit(f'Field shape {vectors.shape} does not match {(len(rows), 72)}. Rebuild the CANA field.')

    os.chdir(ROOT)
    server = ThreadingHTTPServer((args.host, args.port), App)
    server.rows = rows
    server.vectors = vectors
    server.embed_url = args.embed_url
    server.featured_priority = featured_priority
    server.vector_cache = LRUCache()
    server.commons_cache = CommonsCache()
    print(f'CANA · {args.host}:{args.port} · {len(rows):,} records · ' + ('ARBITER 72D' if vectors is not None else 'local name index'), flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
