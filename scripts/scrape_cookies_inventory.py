#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from inventory_data import clean_text, normalize_text, split_terms

ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "CANA-Cookies-inventory-freezer/1.0 (+https://github.com/ziolndr/cana)"


def request(url: str, timeout: int = 45, attempts: int = 5):
    last = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,image/*,*/*"})
            return urllib.request.urlopen(req, timeout=timeout)
        except Exception as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(min(12, 1.5 ** attempt))
    raise last


def get_json(url: str) -> tuple[Any, dict[str, str]]:
    with request(url) as response:
        payload = json.loads(response.read().decode("utf-8", "replace"))
        headers = {key.lower(): value for key, value in response.headers.items()}
        return payload, headers


def fetch_post_type(base: str, post_type: str, include_embed: bool = False) -> list[dict]:
    query = {"per_page": 100, "page": 1, "orderby": "id", "order": "asc", "status": "publish"}
    if include_embed:
        query["_embed"] = "wp:featuredmedia"
    first_url = f"{base}/wp-json/wp/v2/{post_type}?{urllib.parse.urlencode(query)}"
    first, headers = get_json(first_url)
    if not isinstance(first, list):
        raise RuntimeError(f"{post_type} returned {type(first).__name__}, expected list")
    total_pages = max(1, int(headers.get("x-wp-totalpages") or 1))
    total = int(headers.get("x-wp-total") or len(first))
    rows = list(first)
    print(f"{post_type}: {total:,} records · {total_pages:,} pages")
    for page in range(2, total_pages + 1):
        query["page"] = page
        url = f"{base}/wp-json/wp/v2/{post_type}?{urllib.parse.urlencode(query)}"
        batch, _ = get_json(url)
        if not isinstance(batch, list):
            raise RuntimeError(f"{post_type} page {page} returned invalid payload")
        rows.extend(batch)
        if page == total_pages or page % 10 == 0:
            print(f"  fetched {len(rows):,}/{total:,}", flush=True)
    return rows


def rendered(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("rendered") or value.get("raw") or ""
    return clean_text(value)


def flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            out.update(flatten(item, name))
    elif isinstance(value, list):
        out[prefix] = value
        for index, item in enumerate(value[:10]):
            if isinstance(item, (dict, list)):
                out.update(flatten(item, f"{prefix}.{index}"))
    else:
        out[prefix] = value
    return out


def scalar(value: Any) -> Any:
    if isinstance(value, list):
        if not value:
            return None
        if len(value) == 1:
            return scalar(value[0])
        return value
    if isinstance(value, dict):
        for key in ("name", "title", "label", "value", "url", "src", "guid", "id"):
            if key in value and value[key] not in (None, ""):
                return scalar(value[key])
        return value
    return value


def choose(meta: dict[str, Any], exact: tuple[str, ...] = (), contains: tuple[str, ...] = (), excludes: tuple[str, ...] = ()) -> Any:
    normalized = {normalize_text(key).replace(" ", "_"): value for key, value in meta.items()}
    for key in exact:
        value = normalized.get(normalize_text(key).replace(" ", "_"))
        if value not in (None, "", [], {}):
            return scalar(value)
    for key, value in normalized.items():
        if value in (None, "", [], {}):
            continue
        if contains and not all(token in key for token in contains):
            continue
        if excludes and any(token in key for token in excludes):
            continue
        return scalar(value)
    return None


def extract_url(value: Any) -> str | None:
    if isinstance(value, str):
        match = re.search(r"https?://[^\s\"'<>]+", html.unescape(value))
        return match.group(0).rstrip("),.;") if match else None
    if isinstance(value, dict):
        for key in ("url", "src", "source_url", "guid", "large", "full"):
            found = extract_url(value.get(key))
            if found:
                return found
        for item in value.values():
            found = extract_url(item)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = extract_url(item)
            if found:
                return found
    return None


def bool_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = normalize_text(value)
    if text in {"1", "true", "yes", "y", "in stock", "available", "active"}:
        return True
    if text in {"0", "false", "no", "n", "out of stock", "unavailable", "inactive", "sold out"}:
        return False
    return None


def number_text(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    text = clean_text(value)
    return text or None


def money_value(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 1000 and number.is_integer():
            number /= 100
        return round(number, 2)
    text = clean_text(value)
    match = re.search(r"(?:\$\s*)?([0-9]+(?:\.[0-9]{1,2})?)", text.replace(",", ""))
    if not match:
        return None
    number = float(match.group(1))
    if "$" not in text and number >= 1000 and number.is_integer():
        number /= 100
    return round(number, 2)


def resolve_lookup(value: Any, lookup: dict[int, str]) -> str:
    value = scalar(value)
    values = value if isinstance(value, list) else [value]
    output = []
    for item in values:
        try:
            key = int(item)
        except Exception:
            key = None
        text = lookup.get(key) if key is not None else clean_text(item)
        if text and text not in output:
            output.append(text)
    return ", ".join(output)


def parse_labeled(description: str, label: str, next_labels: tuple[str, ...]) -> str:
    if not description:
        return ""
    stops = "|".join(re.escape(item) for item in next_labels)
    pattern = rf"(?is)\b{re.escape(label)}\s*:\s*(.*?)(?=\b(?:{stops})\s*:|$)"
    match = re.search(pattern, description)
    return clean_text(match.group(1)).strip(" .;:-") if match else ""


def embedded_image(post: dict) -> str | None:
    embedded = post.get("_embedded") or {}
    media = embedded.get("wp:featuredmedia") or []
    if media:
        item = media[0] or {}
        for value in (
            item.get("source_url"),
            ((item.get("media_details") or {}).get("sizes") or {}).get("large"),
            ((item.get("media_details") or {}).get("sizes") or {}).get("medium_large"),
        ):
            found = extract_url(value)
            if found:
                return found
    return None


def lookup_map(rows: list[dict]) -> dict[int, str]:
    out = {}
    for row in rows:
        title = rendered(row.get("title"))
        if row.get("id") is not None and title:
            out[int(row["id"])] = title
    return out


def normalize_product(post: dict, lookups: dict[str, dict[int, str]]) -> dict:
    raw_meta = post.get("meta") or {}
    meta = flatten(raw_meta)
    title = rendered(post.get("title"))
    content = rendered(post.get("content"))
    excerpt = rendered(post.get("excerpt"))
    description = clean_text(choose(meta, exact=("joint_product_description", "product_description", "description"), contains=("description",)) or content or excerpt)

    labels = ("FLAVOR PROFILE", "EFFECT PROFILE", "PHENOTYPE", "LINEAGE", "AROMA", "FEELING", "DESCRIPTION")
    flavor_text = parse_labeled(description, "FLAVOR PROFILE", tuple(item for item in labels if item != "FLAVOR PROFILE"))
    effect_text = parse_labeled(description, "EFFECT PROFILE", tuple(item for item in labels if item != "EFFECT PROFILE"))
    phenotype = parse_labeled(description, "PHENOTYPE", tuple(item for item in labels if item != "PHENOTYPE"))
    lineage = parse_labeled(description, "LINEAGE", tuple(item for item in labels if item != "LINEAGE"))

    brand_raw = choose(meta, exact=("joint_product_brand", "product_brand", "brand"), contains=("brand",), excludes=("id", "url", "image"))
    category_raw = choose(meta, exact=("joint_product_category", "product_category", "category"), contains=("category",), excludes=("sub", "url", "image"))
    subcategory_raw = choose(meta, exact=("joint_product_subcategory", "product_subcategory", "subcategory"), contains=("subcategory",))
    strain_raw = choose(meta, exact=("joint_product_strain", "product_strain", "strain"), contains=("strain",), excludes=("type", "url", "image"))
    strain_type = clean_text(choose(meta, exact=("joint_product_strain_type", "strain_type", "type"), contains=("strain", "type")) or "")
    form = clean_text(choose(meta, exact=("joint_product_form", "product_form", "form"), contains=("form",), excludes=("transform",)) or "")

    brand = resolve_lookup(brand_raw, lookups.get("brands", {}))
    category = resolve_lookup(category_raw, lookups.get("categories", {}))
    subcategory = resolve_lookup(subcategory_raw, lookups.get("categories", {}))
    strain = resolve_lookup(strain_raw, lookups.get("strains", {}))

    image = extract_url(choose(meta, exact=("joint_product_image", "joint_product_image_url", "product_image", "image"), contains=("image",), excludes=("id",))) or embedded_image(post)
    if not image:
        image = extract_url(post.get("content")) or extract_url(post.get("excerpt"))

    stock_raw = choose(meta, exact=("joint_product_in_stock", "product_in_stock", "in_stock", "stock"), contains=("stock",), excludes=("quantity", "level"))
    in_stock = bool_value(stock_raw)
    price = money_value(choose(meta, exact=("joint_product_price", "product_price", "price"), contains=("price",), excludes=("sale", "range")))
    thc_text = number_text(choose(meta, exact=("joint_product_potency_thc", "potency_thc", "thc"), contains=("thc",), excludes=("id", "url")))
    cbd_text = number_text(choose(meta, exact=("joint_product_potency_cbd", "potency_cbd", "cbd"), contains=("cbd",), excludes=("id", "url")))
    jane_id = clean_text(choose(meta, exact=("joint_product_id", "jane_product_id", "product_id"), contains=("product", "id"), excludes=("wp",)) or "")
    sku = clean_text(choose(meta, exact=("joint_product_sku", "product_sku", "sku"), contains=("sku",)) or "")
    unit = clean_text(choose(meta, exact=("joint_product_unit", "product_unit", "unit", "weight"), contains=("weight",)) or "")

    effects = split_terms(effect_text)
    flavors = split_terms(flavor_text)
    if not effects:
        effects = split_terms(choose(meta, exact=("joint_product_effects", "effects"), contains=("effect",), excludes=("id", "url")))
    if not flavors:
        flavors = split_terms(choose(meta, exact=("joint_product_flavors", "flavors"), contains=("flavor",), excludes=("id", "url")))

    product_url = extract_url(choose(meta, exact=("joint_product_url", "product_url", "jane_url"), contains=("product", "url"))) or post.get("link")
    stable = jane_id or sku or str(post.get("id"))
    return {
        "id": f"cookies-mv-{stable}",
        "wp_id": post.get("id"),
        "jane_product_id": jane_id or None,
        "sku": sku or None,
        "name": title,
        "brand": brand,
        "category": category or "Cannabis",
        "subcategory": subcategory,
        "form": form,
        "strain": strain,
        "strain_type": strain_type,
        "description": description,
        "effects": effects,
        "flavors": flavors,
        "phenotype": phenotype,
        "lineage": lineage,
        "thc_text": thc_text,
        "cbd_text": cbd_text,
        "price": price,
        "unit": unit,
        "in_stock": in_stock,
        "image_url": image,
        "product_url": product_url,
        "modified_gmt": post.get("modified_gmt") or post.get("modified"),
        "source": "Cookies Mission Valley",
        "source_site": "missionvalley.cookies.co",
    }


def download_image(row: dict, image_dir: Path, timeout: int = 35) -> tuple[dict, str | None]:
    url = row.get("image_url")
    if not url:
        return row, "missing image URL"
    digest = hashlib.sha256(f"{row['id']}\n{url}".encode()).hexdigest()[:20]
    out = image_dir / f"{digest}.webp"
    try:
        if not out.exists() or out.stat().st_size < 512:
            temp = out.with_suffix(".download")
            with request(url, timeout=timeout, attempts=4) as response, temp.open("wb") as handle:
                shutil.copyfileobj(response, handle)
            with Image.open(temp) as image:
                image = image.convert("RGB")
                image.thumbnail((900, 900), Image.Resampling.LANCZOS)
                image.save(out, "WEBP", quality=78, method=6)
            temp.unlink(missing_ok=True)
        row = dict(row)
        row["image"] = f"assets/inventory/{out.name}"
        return row, None
    except Exception as exc:
        out.unlink(missing_ok=True)
        return row, str(exc)


def write_catalog(rows: list[dict], root: Path) -> None:
    public = []
    for row in rows:
        public.append({
            key: row.get(key)
            for key in (
                "id", "name", "brand", "category", "subcategory", "form", "strain",
                "strain_type", "effects", "flavors", "price", "unit", "in_stock",
                "image", "thc_text", "cbd_text", "product_url"
            )
        })
    (root / "data/catalog.json").write_text(json.dumps(public, ensure_ascii=False, separators=(",", ":")))
    (root / "data/catalog.js").write_text("const CATALOG=" + json.dumps(public, ensure_ascii=False, separators=(",", ":")) + ";\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", default="missionvalley.cookies.co")
    parser.add_argument("--include-out-of-stock", action="store_true")
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--minimum", type=int, default=20)
    args = parser.parse_args()

    base = "https://" + args.site.strip().strip("/")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot_dir = ROOT / "snapshots" / stamp
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    image_dir = ROOT / "assets/inventory"
    image_dir.mkdir(parents=True, exist_ok=True)

    auxiliary = {}
    for post_type, key in (
        ("joint_brands", "brands"),
        ("joint_categories", "categories"),
        ("joint_strains", "strains"),
        ("joint_effects", "effects"),
        ("joint_terpenes", "terpenes"),
        ("joint_cannabinoids", "cannabinoids"),
    ):
        try:
            rows = fetch_post_type(base, post_type)
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 404):
                rows = []
            else:
                raise
        auxiliary[key] = rows
        (snapshot_dir / f"{post_type}.json").write_text(json.dumps(rows, ensure_ascii=False))

    products = fetch_post_type(base, "joint_products", include_embed=True)
    (snapshot_dir / "joint_products.json").write_text(json.dumps(products, ensure_ascii=False))
    lookups = {
        "brands": lookup_map(auxiliary["brands"]),
        "categories": lookup_map(auxiliary["categories"]),
        "strains": lookup_map(auxiliary["strains"]),
    }
    normalized = [normalize_product(post, lookups) for post in products]
    for row in normalized:
        if row.get("image_url"):
            row["image_url"] = urllib.parse.urljoin(base + "/", row["image_url"])
        if row.get("product_url"):
            row["product_url"] = urllib.parse.urljoin(base + "/", row["product_url"])

    deduped = {}
    for row in normalized:
        key = row.get("jane_product_id") or row.get("sku") or row["id"]
        current = deduped.get(key)
        if current is None or str(row.get("modified_gmt") or "") > str(current.get("modified_gmt") or ""):
            deduped[key] = row
    normalized = list(deduped.values())

    if not args.include_out_of_stock:
        # Unknown stock is retained because some Jane sync versions omit the flag;
        # only explicit false is excluded.
        normalized = [row for row in normalized if row.get("in_stock") is not False]

    print(f"normalized inventory candidates: {len(normalized):,}")
    image_ready = []
    missing = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(download_image, row, image_dir) for row in normalized]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            row, error = future.result()
            if error:
                missing.append({**row, "image_error": error})
            else:
                image_ready.append(row)
            if index % 50 == 0 or index == len(futures):
                print(f"images: {index:,}/{len(futures):,} · ready {len(image_ready):,} · missing {len(missing):,}", flush=True)

    if len(image_ready) < args.minimum:
        raise SystemExit(
            f"Only {len(image_ready):,} image-backed products survived. "
            "The Cookies/Jane field mapping or image source changed; nothing was published."
        )

    image_ready.sort(key=lambda row: (row.get("category") or "", row.get("brand") or "", row.get("name") or ""))
    data_path = ROOT / "data/inventory.jsonl"
    with data_path.open("w", encoding="utf-8") as handle:
        for row in image_ready:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (ROOT / "reports/missing-images.jsonl").open("w", encoding="utf-8") as handle:
        for row in missing:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_catalog(image_ready, ROOT)

    manifest = {
        "source": base,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "raw_products": len(products),
        "deduped_products": len(deduped),
        "searchable_products": len(image_ready),
        "missing_image_products": len(missing),
        "in_stock_only": not args.include_out_of_stock,
        "image_policy": "Only locally frozen product images are searchable",
    }
    (ROOT / "data/inventory_source_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(
        f"COOKIES INVENTORY FROZEN · {len(image_ready):,} image-backed products · "
        f"{len(missing):,} excluded without images"
    )


if __name__ == "__main__":
    main()
