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

### 2. Ward populations (2021 Census via ward-profiles-25-ward-model)
**Rationale.** Solves the per-capita bias we acknowledged in the leaderboard
methodology. Currently the ward raw score rewards big/dense wards.

**Source.**
- open.toronto.ca dataset: `ward-profiles-25-ward-model`
- 2021 Census population per ward (25-ward model).
- Updates every 5 years; next Census 2026 results probably ~2027.

**Integration sketch.**
- `scripts/fetch.py` gains an ECCC-style lookup for ward populations.
- `build.py` divides raw scores by `population / 100_000` to get
  "calls per 100k residents."
- Leaderboard keeps seasonal ratio as primary; adds per-capita column.
- Front page "wards elevated" count stays as-is (it's a yes/no).

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

### 4. Ravine proximity per ward
**Rationale.** Toronto's ravine system is a literal raccoon highway. Wards
that touch ravines should have structurally higher baselines. This doesn't
change the index itself (seasonal ratio already self-normalizes) but it's a
great analytical finding — "ravine-adjacent wards have 2.3× the baseline
activity of non-adjacent wards."

**Source.**
- open.toronto.ca: `ravine-and-natural-feature-protection` or the
  `topographic-hill-shade` / ravine strategy dataset. Verify the current slug.

**Integration sketch.**
- One-off analysis in a notebook or `scripts/ravine_analysis.py`.
- GeoPandas spatial join: for each ward polygon, compute % area within N
  metres of a ravine centreline.
- Scatter plot: ravine-adjacency vs. mean 2019–2024 baseline.
- Publish as a blog-post-style page, not necessarily part of the live index.

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
