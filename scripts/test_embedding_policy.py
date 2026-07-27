#!/usr/bin/env python3
from __future__ import annotations

from inventory_data import record_text


def assert_contains(text: str, *phrases: str) -> None:
    lowered = text.lower()
    for phrase in phrases:
        assert phrase.lower() in lowered, f"missing protected semantic signal: {phrase!r}\n{text}"


def assert_excludes(text: str, *phrases: str) -> None:
    lowered = text.lower()
    for phrase in phrases:
        assert phrase.lower() not in lowered, f"leaked blocked identity token: {phrase!r}\n{text}"


def main() -> None:
    cases = [
        {
            "name": "Cookies Gelatti Flower 3.5g",
            "brand": "Cookies",
            "category": "flower",
            "subcategory": "Flower",
            "strain_type": "hybrid",
            "lineage": "Gelato x Biscotti",
            "description": (
                "Gelatti flower with a creamy dessert nose. "
                "Relaxing body effect. Dense indoor flower."
            ),
            "flavors": ["creamy", "dessert"],
            "effects": ["relaxed", "calm", "social"],
        },
        {
            "name": "Blue Dream Live Resin",
            "brand": "Raw Garden",
            "category": "extract",
            "subcategory": "Live Resin",
            "strain_type": "sativa",
            "lineage": "Blueberry x Haze",
            "description": (
                "Blue Dream delivers a dreamy, uplifting head high. "
                "Live resin preserves fresh terpenes."
            ),
            "flavors": ["blueberry", "sweet"],
            "effects": ["uplifted", "dreamy", "creative"],
        },
    ]

    flower = record_text(cases[0])
    extract = record_text(cases[1])

    assert_contains(
        flower,
        "Product category: flower.",
        "Product subcategory: Flower.",
        "Strain type: hybrid.",
        "Dense indoor flower",
    )
    assert_excludes(flower, "Cookies", "Gelatti")

    assert_contains(
        extract,
        "Product category: extract.",
        "Product subcategory: Live Resin.",
        "Strain type: sativa.",
        "Live resin preserves fresh terpenes",
    )
    assert_excludes(extract, "Blue Dream", "Raw Garden")

    print("EMBEDDING POLICY PASS · controlled vocabulary preserved · identity tokens removed")


if __name__ == "__main__":
    main()
