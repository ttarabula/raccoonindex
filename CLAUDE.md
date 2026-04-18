# raccoonindex — Toronto Raccoon Activity Index

## Who you're working with

Tyler is a Toronto civic hacker who ships public-good projects on top of City of Toronto open data. Previous work: **swimcal.ca** (swim-schedule ICS feeds). Other parallel threads (separate dirs, separate Claude sessions): `mycouncillor/`, `bikeshare-od-flows/`, `torontotrees/`, `permittheater/`. Do not bleed scope across them.

## Origin

The City of Toronto Open Data team published a dataset called **"Toronto Raccoon Activity Index"** as an April Fools joke. The page was later retired (URL still exists, content stripped). Raccoons are Toronto's unofficial mascot — cute + menacing, a shared civic joke. This project makes the joke real: a straight-faced civic dashboard for a ridiculous subject. Parks-Canada tone, raccoon content.

Retired joke URL: https://open.toronto.ca/dataset/toronto-raccoon-activity-index/

## What this project is

A geographic + temporal index of raccoon-proxy activity across Toronto, built from real open data. Two outputs:

1. **The Index** — daily (or weekly) FSA-level score, rolled up to wards, published as a static site with a map + leaderboard. "Which FSA has the highest trash panda density this week?"
2. **The Almanac** — lower-frequency retrospective pieces: annual wildlife-call trends, coyote responses, `FEED WILD` patterns from the Animal Services dataset.

## Datasets

All on open.toronto.ca. Verified 2026-04-18.

### Primary signal: 311 Service Requests — Customer Initiated
- Dataset: `311-service-requests-customer-initiated`
- Yearly ZIPs from 2010 onwards, per-year resource IDs.
- Fields: `Service Request Creation Date and Time`, `Service Request Location` (FSA only — M5V, M6J etc), `Original Service Request Type`, `Status`, `Division`, `Section-Unit`, `Ward`.
- **Geography: FSA (3-char postal prefix) + ward.** No lat/lon.
- **Temporal: datetime** — daily granularity.
- Refresh cadence: confirm in package metadata.

Raccoon-proxy SR types to extract:
- `Residential: Bin: Repair or Replace Lid` / `Body/Handle` / `Wheel` — direct raccoon damage signal.
- `Res / Nite Garbage / Missed` and related "Nite" variants — exposed overnight garbage.
- `Litter / Bin / Overflow or Missed`.
- `Illegal Dumping / Discharge`.
- `Dead Animal On Expressway`.
- Full list of 311 SR codes: resource `23b4e01c-37a6-46be-999b-e5f317dcdd8c` (XLS, despite `.xlsx` extension — actual format is old Excel, use `xlrd`).

### Secondary signal: Toronto Animal Services — Service Requests & Complaints
- Dataset: `toronto-animal-services-service-requests-complaints`
- Resource ID (CSV, datastore-active): `6fd2bca4-9f36-4d2d-b713-376e2386d199`.
- **Caveat: no geography, no date — only `Activity Year` and `SR Type`.** Updates annually.
- 171k rows 2014–2026. Top SR types: `INJURED WILDLIFE` (57k), `CADAVER - WILDLIFE` (50k), `COYOT RESPONSE` (12k), `FEED WILD` (2.4k), `MENACE` (2.3k), `PIGEONS` (80). Good for Almanac, not for the Index.

### Geographic joins
- FSA → ward crosswalk: Toronto publishes FSA boundaries. Verify slug.
- Ward boundaries for the site map.

## Hazards / things to verify early

- **None of the proxy signals are literally "raccoon" records.** The Index is a composite of bin/garbage/dumping complaints. Be honest about this in public framing — "raccoon-proxy" or "trash panda activity index", not "raccoons".
- FSA geography is coarse (~10–30k residents per FSA). Don't oversell resolution.
- 311 datasets reflect **reporter behavior**, not true incidence. FSAs with more civically-engaged residents will appear more "active". Worth calling out; possibly normalize by per-capita 311 call volume as a control.
- Seasonality is huge (raccoons are more active spring/summer). Index needs to be seasonal-adjusted or published alongside a baseline.
- The Animal Services `SR Type` column is not species-specific — `INJURED WILDLIFE` covers raccoon, squirrel, skunk, etc.
- 311 Customer Initiated data may have changed schema over years. Check ~2010–2015 files before assuming consistent columns.

## Index composition (draft — refine after EDA)

For each (FSA, week):
```
raw_score = w1 * bin_repair_complaints
          + w2 * nite_garbage_missed
          + w3 * litter_overflow
          + w4 * illegal_dumping
          + w5 * dead_animal_on_expressway
normalized_score = raw_score / fsa_population  # per-capita
seasonal_index = normalized_score / fsa_seasonal_baseline  # vs. same week historical avg
```

Weights start at 1.0 equal; tune after looking at signal strength and correlation. Need to decide whether to include controls for total 311 call volume.

## Preferred shape for output

- Static site: map (MapLibre or similar) with FSA choropleth of current-week index + ward-level leaderboard. Explanatory text in Parks-Canada deadpan voice.
- Blog posts for the Almanac analytics.
- Index data regenerated daily/weekly via a script; no live backend.
- Domain possibility: `trashpanda.to` or similar.

## Tooling

Python + uv. Use DuckDB for aggregations over the 311 ZIP CSVs (large, multi-year). GeoPandas/Shapely for FSA/ward joins. Site frontend: decide after EDA — probably static HTML + MapLibre GL.

## Working-style notes

- Genuinely useful > tech demo. But this one is allowed to be mostly whimsical.
- Deadpan civic-dashboard voice for public-facing copy.
- Honest about data gaps — the "raccoon" framing is commentary, not literal.
- Ad-hoc notebooks are fine intermediate artefacts.

## Memory

Session memory at `~/.claude/projects/-Users-tyler-src-open-data-toronto-raccoonindex/memory/`. Parent: `~/.claude/projects/-Users-tyler-src-open-data-toronto/memory/`.
