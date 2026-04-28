# raccoonindex — ideas to pick up later

A living backlog of improvements. Not a commitment list; not sorted by
priority. Start with whichever one feels most interesting.

## Data sources that could improve fidelity

### 1. Weather data (Environment Canada — ECCC Climate API)
**Rationale.** Raccoon activity correlates strongly with temperature (they
den up below freezing, peak around 10–20°C). Folding weather into the
projection would make it a real forecast instead of a 4-week trailing mean.

**Source.**
- ECCC Climate Historical Weather API — free, no auth.
- Station: Toronto Pearson Int'l (climateID 6158733) or Toronto City (6158355).
- URL pattern: `https://climate.weather.gc.ca/climate_data/bulk_data_e.html?format=csv&stationID=<id>&Year=YYYY&Month=M&Day=1&timeframe=2`
- Grab daily mean temp for the last N days; average over a week.

**Integration sketch.**
- Add `scripts/fetch_weather.py` to download weekly temp averages.
- In `build.py`, compute a temperature-adjusted baseline: instead of
  `season_mean = avg over 2019–2024 same ISO week`, use
  `temp_adjusted_baseline = f(historical_weeks_at_similar_temp)`.
- Or simpler: projection formula becomes
  `projected = baseline * trailing_mean * (current_temp_z / historical_temp_z)`.
- Start by just adding weather as an analytical layer (correlation chart on a
  new page) before folding into the index.

### 2. Ward populations (2021 Census via ward-profiles-25-ward-model) — *shipped 2026-04-28*
**Rationale.** Solved the per-capita bias acknowledged in earlier methodology
copy. Raw weighted Index score still rewards big/dense wards, but the
leaderboard now also shows per-100k residents alongside it.

**Source.** `ward-profiles-25-ward-model` on open.toronto.ca, sheet
"2021 One Variable", "Total - Age" row. Wired through `scripts/fetch.py`
and `build.load_ward_populations()`.

**What landed.** `raw_score_per_100k` and `population` fields on every ward
in `index_latest.json`; new "per 100k" column in the leaderboard; per-100k
sub-line in the ward detail panel; methodology paragraph updated. Ravine
analysis (idea 4) now also uses per-1000-residents normalization.

### 3. Day-of-week / time-of-day drill-down
**Rationale.** No new data source — the 311 `Creation Date` field has full
datetime. Directly answers "when is raccoon o'clock?" Almost certainly a
Monday/Tuesday overnight peak (garbage-night correlation).

**Integration sketch.**
- In `build.py`, add a `weekly_hour_dayofweek_counts` aggregation for the
  wildlife + bin-damage categories.
- Write `scripts/export_heatmap.py` to produce a `site/data/dayofweek.json`
  — 7×24 matrix of average counts per hour-of-day × day-of-week.
- New page or section with a SVG/canvas heatmap. Hottest cells + copy
  like "Raccoons call in sick Monday 3 AM" or similar.

### 4. Ravine proximity per ward — *explored 2026-04-28, negative result*
**Rationale (going in).** Toronto's ravine system is a literal raccoon highway.
Wards that touch ravines should have structurally higher baselines.

**Source.** `ravine-natural-feature-protection-area` on open.toronto.ca
(zipped shapefile, WGS84). Now wired through `scripts/fetch.py`.

**Result.** Hypothesis didn't hold. `scripts/ravine_analysis.py` does the
spatial join (ward × ravine polygons + 200 m buffer) and reports correlations
against both Index raw score and wildlife calls per km². Spearman rho is
about +0.10 against total raw score and **−0.26** against wildlife calls per
km² — i.e. ravine-rich Scarborough wards generate *fewer* wildlife calls per
km² than dense, low-ravine downtown wards (Toronto-Danforth, Beaches-East
York, Davenport, Toronto Centre top the per-km² list). The signal is
dominated by human reporter density, not raccoon habitat. Methodology copy
on the wards page now references this explicitly.

**Update (2026-04-28, after per-capita normalization landed).** Re-ran with
per-1000-residents instead of per-km². The negative correlation was an
artifact of ravine wards being large and low-density; on a per-resident
basis the correlation is weakly positive (rho = +0.20) but tertile means
are essentially flat (40 / 44 / 42 calls per 1000 residents). Refined
finding: ravine geography does not meaningfully predict 311 wildlife
reporting either way. Methodology copy updated to reflect the per-resident
result. The only path forward would be a denser raccoon-specific signal
(Toronto Wildlife Centre intake — not currently published).

### 5. Tree canopy density per ward
**Rationale.** Canopy → raccoon habitat. The `torontotrees/` project already
has the Street Tree dataset (689k rows, 2026) cached locally. Cross-walk.

**Source.**
- `torontotrees/data/raw/street-tree-data-4326.csv` (already fetched).
- open.toronto.ca: `street-tree-data`

**Integration sketch.**
- In `torontotrees/scripts/`, compute trees/km² per ward.
- Export a small `ward_canopy.json` joinable by ward code.
- Include as a secondary factor in the projection, or just as a ward-panel
  "context" stat ("Ward 10 has 18 street trees per 100 residents").

### Not worth pursuing

- **Toronto Animal Services dataset.** No geography, only annual.
  `toronto-animal-services-service-requests-complaints`. Already evaluated.
- **Social media / news scraping.** Not open data, TOS risk, maintenance burden.
- **Toronto Wildlife Centre intake.** Not published.
- **Toronto Zoo data.** Not relevant / not open.

## Non-data refinements also worth considering

- **Share / launch**: post to r/toronto, Bluesky, email blogTO/Toronto Life.
- **Blog section** for analytical write-ups (canopy equity style).
- **Subscribe to weekly email** — would require an email infrastructure decision.
- **Tidbyt app**: paused because Tidbyt auth backend is broken (cert expired
  2025-09). Tronbyt is the community replacement (see memory
  `project_raccoonindex.md`); revisit if hardware direction firms up.

## Hardware / distribution ideas (longer-term)

- Home + office Tidbyt-style displays, but requires:
  - Deciding on Tronbyt vs. Pixoo 64 vs. DIY Pi+HUB75.
  - Publishing the Pixlet app to a community repo if going the Tronbyt
    route (see `tidbyt/README.md`).
