# CANA semantic profile field

CANA keeps the 12,804-record OpenTHC identity catalog, but identity fields are not embedded into the semantic vectors.

## Embedded evidence

A record enters semantic ranking only when at least one matched source supplies real profile evidence:

- reported consumer effects
- aroma and flavor
- published laboratory terpene measurements
- published laboratory cannabinoid measurements
- experience/cultivar description
- lineage, classification, and breeder/source context

The embedding text deliberately excludes the record name, ID, and generated name tokens. Records without profile evidence remain available in the catalog but receive no semantic vector and are excluded from meaning-based ranking.

## Profile sources

- Leafly-derived public strain dataset: `https://raw.githubusercontent.com/manrajrrs/cannabis-strain-recommender/main/data/cannabis.csv`
- Kushy open cannabis dataset: `https://github.com/kushyapp/cannabis-dataset`
- Published laboratory assay aggregation: `https://github.com/MaxValue/Terpene-Profile-Parser-for-Cannabis-Strains`
- Identity catalog: `https://vdb.openthc.org/download/strains.csv`

## Matching and chemistry handling

Sources are joined through conservative normalized exact-name matching. Numeric-only and otherwise ambiguous short names are rejected. Flower assays are preferred. Archived assay records are used only when no flower assay exists for that matched identity. Concentrates, edibles, and topical products are not used as strain-flower chemistry.

The manifest records live coverage counts and certifies `name_embedded: false`.
