#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from pathlib import Path

SCHEMA_VERSION = "cana-cookies-inventory-v2"
INVENTORY_PATH = Path("data/inventory.jsonl")

BOILERPLATE_PATTERNS = [
    r"(?i)\bthis product has intoxicating effects.*$",
    r"(?i)\bfor use only by adults.*$",
    r"(?i)\bkeep out of reach of children.*$",
    r"(?i)\blicense(?:d)? dispensary.*$",
    r"(?i)\bcannabis products may only be possessed.*$",
    r"(?i)\bwarning:\s*.*$",
]


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = text.lower().replace("&", " and ")
    return " ".join(re.findall(r"[a-z0-9]+", text))


def clean_text(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(?:p|div|li|h[1-6])>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    for pattern in BOILERPLATE_PATTERNS:
        text = re.sub(pattern, "", text).strip()
    return text


def split_terms(value: object) -> list[str]:
    if isinstance(value, list):
        candidates = value
    else:
        candidates = re.split(r"[,;|/\n]", str(value or ""))
    out: list[str] = []
    seen = set()
    for item in candidates:
        term = clean_text(item).strip(" .:-")
        key = normalize_text(term)
        if not key or key in {"none", "null", "unknown", "n a"} or key in seen:
            continue
        seen.add(key)
        out.append(term)
    return out


def read_inventory(root: Path) -> list[dict]:
    path = root / INVENTORY_PATH
    rows: list[dict] = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def record_text(row: dict) -> str:
    # Deliberately excludes product name, brand, price, stock, image URL, Jane ID,
    # and WordPress ID. Those stay metadata-only so names cannot dominate meaning.
    blocked_phrases = [clean_text(row.get("name")), clean_text(row.get("brand"))]
    # Controlled-vocabulary and format words legitimately appear in BOTH the
    # product name and the category/description. Stripping them because they
    # occur in the name deletes real signal -- "Cookies Gelatti Flower" would
    # erase "flower" from its own category.
    protected = set()
    for field in ("category", "subcategory", "form", "strain_type"):
        protected.update(normalize_text(row.get(field)).split())
    protected.update(
        """flower preroll prerolls roll rolls joint joints vape vapes cart carts
        cartridge cartridges disposable disposables edible edibles gummy gummies
        chocolate beverage drink tincture topical balm lotion capsule capsules
        extract extracts concentrate concentrates live resin rosin badder batter
        budder sugar sauce diamonds shatter wax hash infused indica sativa hybrid
        cbd cbn cbg thc thca gram grams eighth ounce pack indoor outdoor
        greenhouse premium smalls popcorn""".split()
    )
    blocked_terms = {
        term
        for phrase in blocked_phrases
        for term in normalize_text(phrase).split()
        if len(term) >= 3 and term not in protected
    }

    def semantic(value: object) -> str:
        text = clean_text(value)
        for phrase in blocked_phrases:
            if phrase:
                text = re.sub(re.escape(phrase), " ", text, flags=re.I)
        for term in sorted(blocked_terms, key=len, reverse=True):
            text = re.sub(rf"(?i)\b{re.escape(term)}\b", " ", text)
        return re.sub(r"\s+", " ", text).strip(" .,:;-\n")

    parts = ["Cannabis retail inventory product."]
    category = clean_text(row.get("category"))
    subcategory = clean_text(row.get("subcategory"))
    strain_type = clean_text(row.get("strain_type"))
    form = clean_text(row.get("form"))
    if category:
        parts.append(f"Product category: {category}.")
    if subcategory:
        parts.append(f"Product subcategory: {subcategory}.")
    if form and normalize_text(form) not in {normalize_text(category), normalize_text(subcategory)}:
        parts.append(f"Format: {form}.")
    if strain_type:
        parts.append(f"Strain type: {strain_type}.")
    if row.get("phenotype"):
        parts.append(f"Phenotype: {semantic(row['phenotype'])}.")
    if row.get("lineage"):
        parts.append(f"Lineage: {semantic(row['lineage'])}.")
    if row.get("flavors"):
        parts.append("Flavor and aroma profile: " + ", ".join(filter(None, (semantic(item) for item in row["flavors"]))) + ".")
    if row.get("effects"):
        parts.append("Reported effect profile: " + ", ".join(filter(None, (semantic(item) for item in row["effects"]))) + ".")
    description = semantic(row.get("description"))
    if description:
        parts.append("Product description: " + description)
    if row.get("thc_text"):
        parts.append("Listed THC potency: " + semantic(row["thc_text"]) + ".")
    if row.get("cbd_text"):
        parts.append("Listed CBD potency: " + semantic(row["cbd_text"]) + ".")
    return " ".join(parts)


def source_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    path = root / INVENTORY_PATH
    digest.update(INVENTORY_PATH.as_posix().encode())
    if path.exists():
        digest.update(path.read_bytes())
    digest.update(SCHEMA_VERSION.encode())
    return digest.hexdigest()
