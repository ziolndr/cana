#!/usr/bin/env python3
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts" / "serve_cana.py"
MARKER = "CANA_PROFILE_SERVER_V3"


def method_source(text: str) -> str:
    return textwrap.indent(textwrap.dedent(text).strip("\n"), "    ") + "\n"


def function_source(text: str) -> str:
    return textwrap.dedent(text).strip("\n") + "\n"


def locate_targets(tree: ast.Module) -> dict[str, ast.AST]:
    app = next((node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "App"), None)
    main = next((node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main"), None)
    if app is None or main is None:
        raise SystemExit("serve_cana.py does not contain the expected App class and main function. Backup was preserved.")
    methods = {
        node.name: node
        for node in app.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing = [name for name in ("do_GET", "do_POST") if name not in methods]
    if missing:
        raise SystemExit("serve_cana.py is missing required method(s): " + ", ".join(missing))
    return {"do_GET": methods["do_GET"], "do_POST": methods["do_POST"], "main": main}


def main() -> None:
    source = PATH.read_text(encoding="utf-8")
    if MARKER in source and "profile_mask.npy" in source and "name_embedded" in source:
        print("serve_cana.py already uses structural profile-only retrieval")
        return

    tree = ast.parse(source, filename=str(PATH))
    targets = locate_targets(tree)

    replacements = {
        "do_GET": method_source(r'''
            def do_GET(self):
                # CANA_PROFILE_SERVER_V3
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == '/health':
                    return self.send_json({
                        'ok': True,
                        'service': 'cana',
                        'count': len(self.server.rows),
                        'semantic_count': self.server.semantic_count,
                        'field_ready': self.server.vectors is not None,
                        'dim': 72 if self.server.vectors is not None else None,
                        'name_embedded': False if self.server.vectors is not None else None,
                    })
                if parsed.path == '/api/manifest':
                    return self.send_json({
                        'count': len(self.server.rows),
                        'catalog_count': len(self.server.rows),
                        'semantic_count': self.server.semantic_count,
                        'dim': 72 if self.server.vectors is not None else None,
                        'field_ready': self.server.vectors is not None,
                        'name_embedded': False if self.server.vectors is not None else None,
                        'mode': 'ARBITER 72D profile field' if self.server.vectors is not None else 'local name index',
                    })
                if parsed.path == '/api/image':
                    name = urllib.parse.parse_qs(parsed.query).get('name', [''])[0].strip()
                    if not name:
                        return self.send_json({'image': None}, 400)
                    result = resolve_commons_image(name, self.server.commons_cache)
                    return self.send_json(result or {'image': None})
                return super().do_GET()
        '''),
        "do_POST": method_source(r'''
            def do_POST(self):
                if urllib.parse.urlparse(self.path).path != '/api/search':
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

                    normalized_query = normalize_text(query)
                    if normalized_query:
                        exact_indexes = np.asarray([
                            index for index in indexes
                            if normalize_text(self.server.rows[int(index)]['name']) == normalized_query
                        ], dtype=np.int64)
                        if len(exact_indexes):
                            page_indexes = exact_indexes[offset:offset + limit]
                            return self.send_json({
                                'results': [{**self.server.rows[int(index)], 'score': None} for index in page_indexes],
                                'total': len(exact_indexes),
                                'catalog_total': len(self.server.rows),
                                'mode': 'catalog exact match',
                                'elapsed_ms': round((time.perf_counter() - started) * 1000, 1),
                            })

                    if self.server.vectors is not None and query:
                        indexes = indexes[self.server.profile_mask[indexes]]
                        if not len(indexes):
                            return self.send_json({
                                'results': [],
                                'total': 0,
                                'catalog_total': len(self.server.rows),
                                'mode': 'ARBITER 72D profile field',
                                'name_embedded': False,
                                'elapsed_ms': round((time.perf_counter() - started) * 1000, 1),
                            })
                        query_vector = self.query_vector(query)
                        scores = self.server.vectors[indexes] @ query_vector
                        order = np.argsort(-scores, kind='stable')
                        ranked_indexes = indexes[order]
                        ranked_scores = scores[order]
                        page_indexes = ranked_indexes[offset:offset + limit]
                        page_scores = ranked_scores[offset:offset + limit]
                        page = [
                            {**self.server.rows[int(index)], 'score': float(score)}
                            for index, score in zip(page_indexes, page_scores)
                        ]
                        return self.send_json({
                            'results': page,
                            'total': len(ranked_indexes),
                            'catalog_total': len(self.server.rows),
                            'mode': 'ARBITER 72D profile field',
                            'name_embedded': False,
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
                        'catalog_total': len(self.server.rows),
                        'mode': 'local name index',
                        'elapsed_ms': round((time.perf_counter() - started) * 1000, 1),
                    })
                except Exception as error:
                    return self.send_json({
                        'error': str(error),
                        'elapsed_ms': round((time.perf_counter() - started) * 1000, 1),
                    }, 500)
        '''),
        "main": function_source(r'''
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
                profile_mask = np.zeros(len(rows), dtype=np.bool_)
                manifest_path = ROOT / 'field/manifest.json'
                vectors_path = ROOT / 'field/vectors.npy'
                mask_path = ROOT / 'field/profile_mask.npy'
                metadata_path = ROOT / 'field/metadata.jsonl'
                field_paths = (manifest_path, vectors_path, mask_path, metadata_path)

                if all(path.exists() for path in field_paths):
                    manifest = json.loads(manifest_path.read_text())
                    if manifest.get('schema_version') != 'cana-profile-v2' or manifest.get('name_embedded') is not False:
                        raise SystemExit('Old CANA name-only field detected. Run BUILD_CANA_FIELD.command to rebuild it.')
                    vectors = np.load(vectors_path, mmap_mode='r')
                    profile_mask = np.load(mask_path, mmap_mode='r')
                    metadata_rows = [json.loads(line) for line in metadata_path.read_text(encoding='utf-8').splitlines() if line.strip()]
                    if vectors.shape != (len(rows), 72) or profile_mask.shape != (len(rows),) or len(metadata_rows) != len(rows):
                        raise SystemExit(f'Profile field does not match the {len(rows):,}-record CANA catalog. Rebuild it.')
                    for index, metadata in enumerate(metadata_rows):
                        if str(metadata.get('id')) != str(rows[index]['id']):
                            raise SystemExit(f'CANA metadata order mismatch at record {index:,}. Rebuild the field.')
                        rows[index] = {**rows[index], **metadata, 'id': rows[index]['id'], 'name': rows[index]['name'], 'type': rows[index]['type']}
                elif any(path.exists() for path in field_paths):
                    raise SystemExit('Incomplete or old CANA field detected. Run BUILD_CANA_FIELD.command to rebuild it.')

                os.chdir(ROOT)
                server = ThreadingHTTPServer((args.host, args.port), App)
                server.rows = rows
                server.vectors = vectors
                server.profile_mask = profile_mask
                server.semantic_count = int(profile_mask.sum())
                server.embed_url = args.embed_url
                server.featured_priority = featured_priority
                server.vector_cache = LRUCache()
                server.commons_cache = CommonsCache()
                print(
                    f'CANA · {args.host}:{args.port} · {len(rows):,} catalog records · '
                    + (f'{int(profile_mask.sum()):,} real profiles · ARBITER 72D · names excluded' if vectors is not None else 'local name index'),
                    flush=True,
                )
                server.serve_forever()
        '''),
    }

    lines = source.splitlines(keepends=True)
    edits = []
    for name, node in targets.items():
        start = node.lineno - 1
        end = node.end_lineno
        edits.append((start, end, replacements[name], name))

    for start, end, replacement, _ in sorted(edits, reverse=True):
        lines[start:end] = [replacement]

    patched = ''.join(lines)
    ast.parse(patched, filename=str(PATH))
    PATH.write_text(patched, encoding="utf-8")
    print("serve_cana.py structurally patched for profile-only semantic retrieval")


if __name__ == "__main__":
    main()
