# raccoonindex

A straight-faced civic dashboard for a ridiculous subject: the Toronto Raccoon Activity Index.

Born from the City of Toronto Open Data team's 2024 April Fools dataset "Toronto Raccoon Activity Index" (since retired). Raccoons are Toronto's unofficial mascot. This makes the joke real with actual open data.

## What's in here

- `scripts/fetch.py` — downloads 311 Customer Initiated (yearly ZIPs) + Animal Services + SR code reference.
- `scripts/eda.py` — exploratory counts of raccoon-proxy categories by FSA and year.
- `data/raw/` — fetched source files (gitignored).
- `data/processed/` — derived outputs (gitignored).
- `site/` — static site output.

## Quickstart

```
uv sync
uv run python scripts/fetch.py
uv run python scripts/eda.py
```

## Data

Primary: **311 Service Requests - Customer Initiated** (FSA + datetime + SR type). Proxy signals: bin-lid repairs, night-garbage missed, overflow bins, illegal dumping.

Secondary: **Toronto Animal Services** (wildlife calls by year — no geography). Feeds the Almanac, not the Index.

## Honest caveats

- None of these records are literally raccoon records. The Index is a composite of garbage/bin/dumping proxies.
- 311 data reflects reporter behaviour, not true incidence.
- FSA geography is coarse (~10–30k residents).
