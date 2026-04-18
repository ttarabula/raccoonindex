"""Toronto Raccoon Activity Index — Tidbyt app.

Fetches the current week's city-wide alert from https://raccoonindex.ca and
renders the tier level + tier name + seasonal ratio on a 64x32 pixel Tidbyt.

Layout:
    LVL 4            <- grey "LVL" + big tier-colored number
    BIN BREACH       <- tier name, tier-colored
    CITY 1.16x       <- dim "CITY" + ratio in tier color
"""

load("encoding/json.star", "json")
load("http.star", "http")
load("render.star", "render")

SUMMARY_URL = "https://raccoonindex.ca/data/index_summary.json"
TTL_SECONDS = 900  # Tidbyt polls roughly every 15 minutes

TIER_COLORS = {
    1: "#5b8fa8",  # DEN DORMANCY    — cool blue
    2: "#6fa0b0",  # BIN ADVISORY    — lighter blue
    3: "#c8d18a",  # MASK ON         — pale green-yellow
    4: "#d89b5f",  # BIN BREACH      — rust
    5: "#d85c3f",  # PANDAMONIUM     — red-orange
}

DIM = "#8a8680"

def main():
    resp = http.get(SUMMARY_URL, ttl_seconds = TTL_SECONDS)
    if resp.status_code != 200:
        return _error("feed down")

    data = json.decode(resp.body())
    tier_level = data.get("tier_level")
    tier_name = data.get("tier_name") or "—"
    ratio = data.get("city_seasonal_ratio")

    if tier_level == None:
        return _error("no tier")

    color = TIER_COLORS.get(tier_level, "#c8d18a")
    ratio_str = _fmt_ratio(ratio)

    return render.Root(
        child = render.Column(
            expanded = True,
            main_align = "space_evenly",
            cross_align = "center",
            children = [
                render.Row(
                    cross_align = "center",
                    children = [
                        render.Text("LVL ", font = "tom-thumb", color = DIM),
                        render.Text(str(tier_level), font = "6x13", color = color),
                    ],
                ),
                render.Marquee(
                    width = 64,
                    child = render.Text(tier_name, font = "tb-8", color = color),
                ),
                render.Row(
                    children = [
                        render.Text("CITY ", font = "tom-thumb", color = DIM),
                        render.Text(ratio_str, font = "tom-thumb", color = color),
                    ],
                ),
            ],
        ),
    )

def _fmt_ratio(r):
    # Starlark's % operator lacks precision/padding; do it manually.
    if r == None:
        return "—"
    hundredths = int(r * 100 + 0.5)
    whole = hundredths // 100
    frac = hundredths % 100
    frac_str = str(frac) if frac >= 10 else "0" + str(frac)
    return str(whole) + "." + frac_str + "x"

def _error(msg):
    return render.Root(
        child = render.Box(
            child = render.Text(msg, font = "tom-thumb", color = "#d85c3f"),
        ),
    )
