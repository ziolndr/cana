# CANA — Cookies Mission Valley Inventory Field

One-shot extraction, embedding, freezing, and deployment of the current Cookies Mission Valley shelf into CANA.

## What the build does

1. Reads the Jane-synced WordPress REST post types from `missionvalley.cookies.co`.
2. Downloads all `joint_products` plus brands, categories, strains, effects, terpenes, and cannabinoids.
3. Keeps the current shelf by excluding only products explicitly marked out of stock.
4. Deduplicates by Jane product ID, then SKU, then WordPress ID.
5. Downloads and compresses each real product image to a local WebP file.
6. Excludes products whose real image cannot be frozen, guaranteeing that every search result has an image.
7. Constructs semantic text from category, subcategory, format, strain type, description, phenotype, lineage, flavors, effects, and potency.
8. Strips product-name and brand identity tokens from free text while preserving controlled category, subcategory, format, and strain-type vocabulary such as `flower`, `live resin`, `preroll`, and `hybrid`.
9. Keeps price, stock state, IDs, and image paths out of the embedded text.
10. Runs semantic regression tests before embedding.
11. Builds a normalized `N × 72` ARBITER field.
12. Verifies the field, clones `ziolndr/cana`, replaces the repository contents, commits, and pushes to `main`.

The Render build never scrapes the store and never rebuilds vectors. It only installs dependencies and verifies the frozen committed field.

## One command

After unzipping:

```bash
./BUILD_COOKIES_AND_PUSH.command
```

Default ARBITER endpoint:

```text
https://api.arbiter.traut.ai/public/embed
```

Override it when needed:

```bash
ARBITER_EMBED_URL=http://127.0.0.1:8000/v1/embed ./BUILD_COOKIES_AND_PUSH.command
```

## Controls

```text
CANA_EMBED_BATCH=128
CANA_EMBED_CONCURRENCY=2
CANA_IMAGE_WORKERS=10
CANA_MINIMUM_PRODUCTS=20
```

## Outputs committed to GitHub

```text
data/inventory.jsonl
field/vectors.npy
field/metadata.jsonl
field/manifest.json
assets/inventory/*.webp
data/catalog.js
```

Raw WordPress snapshots remain under `snapshots/` locally and are excluded from Git.
