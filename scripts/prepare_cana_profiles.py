#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import statistics
import time
import unicodedata
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
LEAFLY_URL = "https://raw.githubusercontent.com/manrajrrs/cannabis-strain-recommender/main/data/cannabis.csv"
KUSHY_URL = "https://raw.githubusercontent.com/kushyapp/cannabis-dataset/master/Dataset/Strains/strains-kushy_api.2017-11-14.csv"
LAB_URL = "https://github.com/MaxValue/Terpene-Profile-Parser-for-Cannabis-Strains/raw/refs/heads/master/results.csv"

IDENTITY_COLUMNS = {
    "Database Identifier", "Database Name", "Test Result UID", "Sample Name", "Sample Type",
    "Receipt Time", "Test Time", "Post Time", "Provider",
}
CANNABINOID_COLUMNS = {
    "delta-9 THC-A", "delta-9 THC", "delta-8 THC", "THC-A", "THCV", "CBN",
    "CBD-A", "CBD", "CBDV", "CBDV-A", "delta-9 CBG-A", "delta-9 CBG", "CBC",
}
IGNORE_CHEMISTRY_COLUMNS = {"Moisture Content"}


def download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    error: Exception | None = None
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers={"user-agent": "CANA-profile-builder/2.0"})
            with urllib.request.urlopen(request, timeout=180) as response:
                temp.write_bytes(response.read())
            temp.replace(path)
            return
        except Exception as caught:
            error = caught
            if temp.exists():
                temp.unlink()
            time.sleep(2 ** attempt)
    assert error is not None
    raise error


def clean(value: object) -> str:
    text = str(value or "").strip()
    if text.upper() in {"NULL", "NONE", "N/A", "NA", "ND", "NOT DETECTED"}:
        return ""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def normalize_name(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    text = text.replace("&", " and ").replace("$", "")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\bstrain\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def safe_match_key(value: object) -> str:
    key = normalize_name(value)
    # Prevent accidental attachment of lab data to catalog entries named only "1", "4", etc.
    return key if len(key) >= 3 and len(re.findall(r"[a-z]", key)) >= 2 else ""


def split_values(value: object) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in re.split(r"[,;|]", clean(value)):
        item = clean(item)
        key = item.casefold()
        if item and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def merge_values(*groups: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for group in groups:
        for item in group:
            item = clean(item)
            key = item.casefold()
            if item and key not in seen:
                seen.add(key)
                result.append(item)
    return result


def strip_own_name(text: str, name: str) -> str:
    text = clean(text)
    if not text:
        return text
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    aliases = [ascii_name, re.sub(r"\([^)]*\)", " ", ascii_name)]
    aliases.extend(re.findall(r"\(([^)]*)\)", ascii_name))
    for alias in aliases:
        for candidate in re.split(r"[/|]", alias):
            tokens = re.findall(r"[A-Za-z0-9]+", candidate)
            if len("".join(tokens)) < 3 or len(re.findall(r"[A-Za-z]", "".join(tokens))) < 2:
                continue
            pattern = r"(?i)(?<![A-Za-z0-9])" + r"[^A-Za-z0-9]+".join(re.escape(token) for token in tokens) + r"(?![A-Za-z0-9])"
            text = re.sub(pattern, "the cultivar", text)
    return re.sub(r"\s+", " ", text).strip()


def best_record(records: list[dict], fields: tuple[str, ...]) -> dict:
    return max(records, key=lambda row: sum(bool(clean(row.get(field))) for field in fields), default={})


def number(value: object) -> float | None:
    text = clean(value).replace(",", "")
    if not text:
        return None
    match = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", text)
    if not match:
        return None
    try:
        result = float(match.group())
    except ValueError:
        return None
    return result if math.isfinite(result) and result > 0 else None


def preferred_lab_rows(rows: list[dict]) -> list[dict]:
    flower = [row for row in rows if "flower" in clean(row.get("Sample Type")).lower()]
    if flower:
        return flower
    archived = [row for row in rows if clean(row.get("Sample Type")).lower() in {"archived", ""}]
    return archived


def aggregate_lab_profile(rows: list[dict], terpene_columns: list[str]) -> tuple[list[dict], list[dict], int, list[str]]:
    rows = preferred_lab_rows(rows)
    if not rows:
        return [], [], 0, []
    values: defaultdict[str, list[float]] = defaultdict(list)
    labs: set[str] = set()
    for row in rows:
        lab = clean(row.get("Database Name"))
        if lab:
            labs.add(lab)
        for component in [*terpene_columns, *sorted(CANNABINOID_COLUMNS)]:
            parsed = number(row.get(component))
            if parsed is not None:
                values[component].append(parsed)

    def summarize(columns: list[str], limit: int) -> list[dict]:
        summaries = []
        for component in columns:
            measured = values.get(component, [])
            if not measured:
                continue
            summaries.append({
                "name": component,
                "median": round(float(statistics.median(measured)), 4),
                "observations": len(measured),
            })
        summaries.sort(key=lambda item: (item["median"], item["observations"]), reverse=True)
        return summaries[:limit]

    return summarize(terpene_columns, 10), summarize(sorted(CANNABINOID_COLUMNS), 10), len(rows), sorted(labs)


def chemistry_text(items: list[dict]) -> str:
    return ", ".join(
        f"{item['name']} (median published assay value {item['median']:g}; {item['observations']} observations)"
        for item in items
    )


def build_embedding_text(profile: dict) -> str:
    # Deliberately excludes name, ID, and name tokens. Identity remains metadata only.
    parts = ["Cannabis experiential, sensory, lineage, terpene, and cannabinoid profile."]
    if profile["effects"]:
        parts.append("Reported consumer effects: " + ", ".join(profile["effects"]) + ".")
    if profile["flavors"]:
        parts.append("Reported aroma and flavor: " + ", ".join(profile["flavors"]) + ".")
    if profile["lab_terpenes"]:
        parts.append("Laboratory terpene measurements: " + chemistry_text(profile["lab_terpenes"]) + ".")
    elif profile["reported_terpenes"]:
        parts.append("Reported terpenes: " + ", ".join(profile["reported_terpenes"]) + ".")
    if profile["lab_cannabinoids"]:
        parts.append("Laboratory cannabinoid measurements: " + chemistry_text(profile["lab_cannabinoids"]) + ".")
    if profile["ailments"]:
        parts.append("Reported consumer use contexts: " + ", ".join(profile["ailments"]) + ".")
    if profile["description"]:
        parts.append("Experience and cultivar description: " + profile["description"])
    if profile["type"] and profile["type"] != "Unclassified":
        parts.append("Variety classification: " + profile["type"] + ".")
    if profile["crosses"]:
        parts.append("Reported lineage: " + profile["crosses"] + ".")
    if profile["breeder"]:
        parts.append("Breeder or source: " + profile["breeder"] + ".")
    return " ".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default="data/strains.csv")
    parser.add_argument("--output", default="data/semantic_profiles.jsonl")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    catalog_path = (ROOT / args.catalog).resolve()
    output_path = (ROOT / args.output).resolve()
    leafly_path = ROOT / "data/leafly_cannabis.csv"
    kushy_path = ROOT / "data/kushy_strains.csv"
    lab_path = ROOT / "data/lab_chemistry.csv"

    for label, url, path in (
        ("experiential strain profiles", LEAFLY_URL, leafly_path),
        ("supplemental strain profiles", KUSHY_URL, kushy_path),
        ("laboratory terpene and cannabinoid profiles", LAB_URL, lab_path),
    ):
        if args.refresh or not path.exists():
            print(f"downloading {label}...")
            download(url, path)

    with catalog_path.open(encoding="utf-8-sig", newline="") as handle:
        catalog = [row for row in csv.DictReader(handle) if clean(row.get("Strain"))]

    leafly_by_name: defaultdict[str, list[dict]] = defaultdict(list)
    with leafly_path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            key = safe_match_key(row.get("Strain"))
            if key:
                leafly_by_name[key].append(row)

    kushy_by_name: defaultdict[str, list[dict]] = defaultdict(list)
    with kushy_path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            key = safe_match_key(row.get("name"))
            if key:
                kushy_by_name[key].append(row)

    lab_by_name: defaultdict[str, list[dict]] = defaultdict(list)
    with lab_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        chemistry_columns = [field for field in (reader.fieldnames or []) if field not in IDENTITY_COLUMNS and field not in IGNORE_CHEMISTRY_COLUMNS]
        terpene_columns = [field for field in chemistry_columns if field not in CANNABINOID_COLUMNS]
        for row in reader:
            key = safe_match_key(row.get("Sample Name"))
            if key:
                lab_by_name[key].append(row)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    semantic_count = 0
    coverage = {
        "effects": 0, "flavors": 0, "reported_terpenes": 0, "lab_terpenes": 0,
        "lab_cannabinoids": 0, "descriptions": 0, "ailments": 0, "lineage": 0,
    }

    with output_path.open("w", encoding="utf-8") as output:
        for item in catalog:
            name = clean(item.get("Strain"))
            key = safe_match_key(name)
            leaf = best_record(leafly_by_name.get(key, []), ("Effects", "Flavor", "Description", "Rating")) if key else {}
            kushy = best_record(kushy_by_name.get(key, []), ("effects", "flavor", "description", "terpenes", "ailment", "breeder", "crosses")) if key else {}
            lab_terpenes, lab_cannabinoids, lab_sample_count, labs = aggregate_lab_profile(lab_by_name.get(key, []), terpene_columns) if key else ([], [], 0, [])

            effects = merge_values(split_values(leaf.get("Effects")), split_values(kushy.get("effects")))
            flavors = merge_values(split_values(leaf.get("Flavor")), split_values(kushy.get("flavor")))
            reported_terpenes = split_values(kushy.get("terpenes"))
            ailments = split_values(kushy.get("ailment"))
            description = strip_own_name(clean(leaf.get("Description")) or clean(kushy.get("description")), name)
            variety_type = clean(leaf.get("Type")) or clean(kushy.get("type")) or clean(item.get("Type")) or "Unclassified"
            breeder = clean(kushy.get("breeder"))
            crosses = clean(kushy.get("crosses"))
            rating = clean(leaf.get("Rating"))

            semantic_ready = bool(effects or flavors or reported_terpenes or lab_terpenes or lab_cannabinoids or description or crosses)
            sources = []
            if leaf:
                sources.append("Leafly-derived public dataset")
            if kushy:
                sources.append("Kushy open dataset")
            if lab_sample_count:
                sources.append("Published laboratory assay aggregation")

            profile = {
                "id": clean(item.get("ID")), "name": name, "type": variety_type,
                "catalog_type": clean(item.get("Type")) or "Unclassified",
                "effects": effects, "flavors": flavors, "reported_terpenes": reported_terpenes,
                "lab_terpenes": lab_terpenes, "lab_cannabinoids": lab_cannabinoids,
                "lab_sample_count": lab_sample_count, "labs": labs,
                "ailments": ailments, "description": description, "breeder": breeder,
                "crosses": crosses, "rating": rating, "semantic_ready": semantic_ready,
                "sources": sources,
            }
            profile["embedding_text"] = build_embedding_text(profile) if semantic_ready else ""
            output.write(json.dumps(profile, ensure_ascii=False) + "\n")

            if semantic_ready:
                semantic_count += 1
                coverage["effects"] += bool(effects)
                coverage["flavors"] += bool(flavors)
                coverage["reported_terpenes"] += bool(reported_terpenes)
                coverage["lab_terpenes"] += bool(lab_terpenes)
                coverage["lab_cannabinoids"] += bool(lab_cannabinoids)
                coverage["descriptions"] += bool(description)
                coverage["ailments"] += bool(ailments)
                coverage["lineage"] += bool(crosses)

    stats = {
        "schema_version": "cana-profile-v2",
        "catalog_count": len(catalog), "semantic_count": semantic_count,
        "name_embedded": False, "coverage": coverage,
        "source_urls": [LEAFLY_URL, KUSHY_URL, LAB_URL],
        "matching": "conservative normalized exact-name joins; ambiguous numeric-only names rejected",
        "chemistry": "flower assays preferred; archived assays used only when no flower assays exist",
    }
    (ROOT / "data/profile_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(f"CANA PROFILES READY · {semantic_count:,}/{len(catalog):,} records carry real experiential, lineage, or chemical data")
    print("name embedded: NO")
    print("coverage: " + " · ".join(f"{key} {value:,}" for key, value in coverage.items()))


if __name__ == "__main__":
    main()
