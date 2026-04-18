"""Normalize SR types, aggregate weekly × ward × category, compute the Index.

Reads yearly 311 CSVs from data/raw/_unpacked/, produces:
- data/processed/weekly_ward_category.parquet — long-form weekly counts
- data/processed/weekly_ward_index.parquet    — per (iso_year, iso_week, ward) index
- data/processed/index_latest.json            — current-period snapshot for the site
- data/processed/ward_trend_sparklines.json   — 52-week trend per ward for panel views

The Index combines literal wildlife calls (`Cadaver`, `Injured/Distressed Wildlife`)
with raccoon-proxy signals (bin damage, missed garbage, dumping, litter overflow).
Weighted sum per ward-week, per-capita normalized, seasonal-baseline adjusted.
"""
from __future__ import annotations

import datetime
import json
import re
import zipfile
from decimal import Decimal
from pathlib import Path

import duckdb


def _json_default(o):
    if isinstance(o, Decimal):
        return float(o)
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
UNPACK = RAW / "_unpacked"
PROC = ROOT / "data" / "processed"
PROC.mkdir(parents=True, exist_ok=True)

YEARS = sorted(int(p.stem[2:]) for p in RAW.glob("sr20*.zip"))

# Canonical category → list of regex patterns matching raw SR Type (case-insensitive).
# Patterns are ORed; first match wins; unmatched rows are dropped from the index.
CATEGORIES: dict[str, list[str]] = {
    "wildlife_cadaver": [
        r"^cadaver\s*[-\s]*wildlife$",
        r"^pick up dead wildlife$",
        r"^dead animal on expressway$",
    ],
    "wildlife_injured": [
        r"^injur/dist wildlife$",
        r"^injured\s*-\s*wildlife$",
    ],
    "wildlife_nuisance": [
        r"^disturbing/injuring/feeding wildlife\b",
        r"^dangerous or trapped wildlife\b",
    ],
    "bin_damage": [
        r"^residential:\s*bin:\s*repair or replace\b",
        r"^residential bin (lid|body or handle|wheel) damaged$",
    ],
    "illegal_dumping": [
        r"\billegal dumping\b",
    ],
    # litter_overflow listed above garbage_missed because "overflow or not picked up"
    # would otherwise be captured by the broader garbage_missed pattern.
    "litter_overflow": [
        r"^litter\s*/\s*bin\s*/\s*overflow",
        r"^garbage\s*/\s*park\s*/\s*bin overflow$",
        r"^park garbage bin overflowing$",
        r"^clean up overflowing street litter bin$",
    ],
    "garbage_missed": [
        # Pickup didn't happen — several taxonomies over the years. Bin admin categories
        # ("Bin Missing" / "Bin Exchange") are separate and not matched here.
        r"\bnot picked up\b",
        r"/\s*missed\s*$",
        r"\s+missed on the whole street\b",
        r"\bwhole street\b.*\bnot picked up\b",
    ],
}

# Weights — wildlife signals weighted higher; proxy signals lower.
WEIGHTS = {
    "wildlife_cadaver": 2.0,
    "wildlife_injured": 1.5,
    "wildlife_nuisance": 1.5,
    "bin_damage": 1.0,
    "garbage_missed": 0.5,
    "illegal_dumping": 0.75,
    "litter_overflow": 0.75,
}

# Tier thresholds keyed off seasonal ratio. Shared between city-wide, projection,
# and per-ward assignments so the scale means the same thing everywhere.
TIERS = [
    (0.60, 1, "DEN DORMANCY"),
    (0.90, 2, "BIN ADVISORY"),
    (1.10, 3, "MASK ON"),
    (1.40, 4, "BIN BREACH"),
    (float("inf"), 5, "PANDAMONIUM"),
]


def assign_tier(ratio):
    """Map a seasonal ratio to (tier_level, tier_name). None → (None, None)."""
    if ratio is None:
        return None, None
    r = float(ratio)
    for upper, lvl, name in TIERS:
        if r < upper:
            return lvl, name
    last = TIERS[-1]
    return last[1], last[2]


def unpack_all() -> None:
    UNPACK.mkdir(exist_ok=True)
    for y in YEARS:
        dest = UNPACK / f"SR{y}.csv"
        if dest.exists():
            continue
        with zipfile.ZipFile(RAW / f"sr{y}.zip") as z:
            name = z.namelist()[0]
            z.extract(name, path=UNPACK)


def ward_code_from_str(s: str | None) -> str | None:
    """SR data format is 'Ward Name (NN)' with zero-padded NN."""
    if not s:
        return None
    m = re.search(r"\((\d{1,2})\)\s*$", s)
    if not m:
        return None
    return m.group(1).zfill(2)


def main() -> None:
    unpack_all()
    con = duckdb.connect()

    # Union all years into a single view.
    union_sql = " UNION ALL ".join(
        f"""SELECT
              {y} AS src_year,
              TRY_CAST("Creation Date" AS TIMESTAMP) AS created_at,
              "First 3 Chars of Postal Code" AS fsa,
              Ward AS ward_raw,
              "Service Request Type" AS sr_type
            FROM read_csv(
              '{UNPACK / f"SR{y}.csv"}',
              header=true, delim=',', quote='"', escape='"',
              ignore_errors=true, null_padding=true, strict_mode=false,
              sample_size=-1
            )"""
        for y in YEARS
    )
    con.execute(f"CREATE OR REPLACE VIEW sr_all AS {union_sql}")

    # Build category CASE expression from the CATEGORIES dict.
    case_lines = []
    for cat, patterns in CATEGORIES.items():
        joined = "|".join(f"({p})" for p in patterns)
        case_lines.append(f"WHEN regexp_matches(LOWER(sr_type), '{joined}') THEN '{cat}'")
    case_sql = "CASE\n" + "\n".join(case_lines) + "\nEND"

    con.execute(
        f"""
        CREATE OR REPLACE VIEW sr_normalized AS
        SELECT
            created_at,
            CAST(YEAR(created_at) AS INT) AS year,
            CAST(DAYOFYEAR(created_at) AS INT) AS doy,
            -- ISO week (1..53) and its ISO year, so week aggregation is stable at year boundaries
            CAST(ISOYEAR(created_at) AS INT) AS iso_year,
            CAST(WEEK(created_at) AS INT) AS iso_week,
            fsa,
            ward_raw,
            sr_type,
            {case_sql} AS category
        FROM sr_all
        WHERE created_at IS NOT NULL
        """
    )

    # Register ward_code_from_str as a UDF.
    con.create_function(
        "ward_code",
        ward_code_from_str,
        ["VARCHAR"],
        "VARCHAR",
        null_handling="special",
    )

    # Weekly aggregation per ward × category. Use ward code '01'..'25' derived from ward_raw.
    con.execute(
        f"""
        CREATE OR REPLACE TABLE weekly_ward_category AS
        SELECT
            iso_year, iso_week,
            ward_code(ward_raw) AS ward,
            category,
            COUNT(*) AS n
        FROM sr_normalized
        WHERE category IS NOT NULL
          AND ward_code(ward_raw) IS NOT NULL
        GROUP BY iso_year, iso_week, ward, category
        """
    )

    total_rows = con.execute("SELECT SUM(n) FROM weekly_ward_category").fetchone()[0]
    print(f"Categorized rows: {total_rows:,}")

    # Print per-category totals.
    print("\n=== Per-category totals ===")
    for r in con.execute(
        "SELECT category, SUM(n) AS n FROM weekly_ward_category GROUP BY category ORDER BY n DESC"
    ).fetchall():
        print(f"  {r[1]:>10,} | {r[0]}")

    # Pivot to wide form: one row per (iso_year, iso_week, ward), one column per category.
    cats = list(CATEGORIES.keys())
    pivot_select = ",\n  ".join(
        f"SUM(CASE WHEN category = '{c}' THEN n ELSE 0 END) AS {c}" for c in cats
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE weekly_ward_wide AS
        SELECT iso_year, iso_week, ward,
          {pivot_select}
        FROM weekly_ward_category
        GROUP BY iso_year, iso_week, ward
        """
    )

    # Raw weighted score.
    weighted_expr = " + ".join(f"{WEIGHTS[c]} * {c}" for c in cats)
    con.execute(
        f"""
        CREATE OR REPLACE TABLE weekly_ward_index AS
        WITH scored AS (
            SELECT *, ({weighted_expr}) AS raw_score
            FROM weekly_ward_wide
        ),
        baseline AS (
            -- Seasonal baseline uses only 2019–2024, since Toronto switched from the
            -- 44-ward to the 25-ward model in late 2018. Pre-2019 ward codes refer
            -- to different geography and must not contaminate the baseline.
            SELECT ward, iso_week, AVG(raw_score) AS season_mean
            FROM scored
            WHERE iso_year BETWEEN 2019 AND 2024
            GROUP BY ward, iso_week
        )
        SELECT s.*,
               b.season_mean,
               CASE WHEN b.season_mean > 0 THEN s.raw_score / b.season_mean END AS seasonal_ratio
        FROM scored s
        LEFT JOIN baseline b USING (ward, iso_week)
        WHERE s.ward BETWEEN '01' AND '25'  -- current 25-ward model only
        ORDER BY iso_year, iso_week, ward
        """
    )

    # Persist the processed tables.
    con.execute(
        f"COPY weekly_ward_category TO '{PROC / 'weekly_ward_category.parquet'}' (FORMAT PARQUET)"
    )
    con.execute(
        f"COPY weekly_ward_index TO '{PROC / 'weekly_ward_index.parquet'}' (FORMAT PARQUET)"
    )

    # Latest *complete* period — drop the most recent week since city data backfills
    # for ~1-2 weeks. Use the second-most-recent week as "latest" for the site.
    recent_weeks = con.execute(
        "SELECT DISTINCT iso_year, iso_week FROM weekly_ward_index "
        "ORDER BY iso_year DESC, iso_week DESC LIMIT 3"
    ).fetchall()
    latest_y, latest_w = recent_weeks[1]  # skip the most recent (partial) week
    print(f"\nLatest period: ISO {latest_y}-W{latest_w:02d}")

    cat_select = ", ".join(cats)
    # Sort by seasonal ratio DESC so consumers (leaderboard) show self-normalized
    # rank. Raw score alone biases toward dense/populous wards. Wards without a
    # baseline (no historical data) sort last.
    latest = con.execute(
        f"""
        SELECT ward, raw_score, season_mean, seasonal_ratio, {cat_select}
        FROM weekly_ward_index
        WHERE iso_year = ? AND iso_week = ?
        ORDER BY seasonal_ratio DESC NULLS LAST, raw_score DESC
        """,
        [latest_y, latest_w],
    ).fetchall()

    def _ward_entry(row):
        tier_level, tier_name = assign_tier(row[3])
        return {
            "ward": row[0],
            "raw_score": row[1],
            "season_mean": row[2],
            "seasonal_ratio": row[3],
            "tier_level": tier_level,
            "tier_name": tier_name,
            "components": dict(zip(cats, row[4:])),
        }

    index_latest = {
        "iso_year": latest_y,
        "iso_week": latest_w,
        "weights": WEIGHTS,
        "wards": [_ward_entry(row) for row in latest],
    }
    (PROC / "index_latest.json").write_text(json.dumps(index_latest, indent=2, default=_json_default))
    print(f"Wrote {PROC / 'index_latest.json'} — {len(latest)} wards")

    # Last 52 weeks of raw_score per ward for sparklines.
    sparklines = con.execute(
        """
        WITH ranked AS (
            SELECT ward, iso_year, iso_week, raw_score,
                   ROW_NUMBER() OVER (PARTITION BY ward ORDER BY iso_year DESC, iso_week DESC) AS rn
            FROM weekly_ward_index
        )
        SELECT ward, iso_year, iso_week, raw_score
        FROM ranked
        WHERE rn <= 52
        ORDER BY ward, iso_year, iso_week
        """
    ).fetchall()
    spark: dict[str, list[dict]] = {}
    for ward, y, w, s in sparklines:
        spark.setdefault(ward, []).append({"iso_year": y, "iso_week": w, "raw_score": s})
    (PROC / "ward_trend_sparklines.json").write_text(
        json.dumps(spark, indent=2, default=_json_default)
    )
    print(f"Wrote {PROC / 'ward_trend_sparklines.json'} — {len(spark)} wards, up to 52 weeks")

    # City-wide summary for the front page.
    # Sum ward scores per week → city total. Ratio vs. same-week 2019–2024 city baseline.
    con.execute(
        """
        CREATE OR REPLACE TABLE weekly_city AS
        WITH city AS (
            SELECT iso_year, iso_week,
                   SUM(raw_score) AS city_raw,
                   SUM(season_mean) AS city_baseline
            FROM weekly_ward_index
            GROUP BY iso_year, iso_week
        )
        SELECT *,
               CASE WHEN city_baseline > 0 THEN city_raw / city_baseline END AS city_ratio
        FROM city
        ORDER BY iso_year, iso_week
        """
    )

    city_52 = con.execute(
        """
        SELECT iso_year, iso_week, city_raw, city_ratio
        FROM weekly_city
        ORDER BY iso_year DESC, iso_week DESC
        LIMIT 52
        """
    ).fetchall()
    city_series = [
        {"iso_year": y, "iso_week": w, "raw_score": r, "ratio": ratio}
        for y, w, r, ratio in reversed(city_52)
    ]
    city_now = con.execute(
        "SELECT city_raw, city_ratio FROM weekly_city WHERE iso_year = ? AND iso_week = ?",
        [latest_y, latest_w],
    ).fetchone()
    city_raw_now = float(city_now[0]) if city_now[0] is not None else 0.0
    city_ratio_now = float(city_now[1]) if city_now[1] is not None else None

    tier_level, tier_name = assign_tier(city_ratio_now)
    if tier_level is None:
        tier_level, tier_name = 3, "MASK ON"

    # Prior week for biggest-mover computation.
    prior_y, prior_w = recent_weeks[2] if len(recent_weeks) >= 3 else (None, None)
    biggest_mover = None
    if prior_y is not None:
        movers = con.execute(
            """
            SELECT this.ward, this.raw_score - prev.raw_score AS delta,
                   this.raw_score, prev.raw_score
            FROM weekly_ward_index this
            JOIN weekly_ward_index prev
              ON prev.ward = this.ward AND prev.iso_year = ? AND prev.iso_week = ?
            WHERE this.iso_year = ? AND this.iso_week = ?
            ORDER BY delta DESC
            LIMIT 1
            """,
            [prior_y, prior_w, latest_y, latest_w],
        ).fetchone()
        if movers:
            biggest_mover = {
                "ward": movers[0],
                "delta": float(movers[1]),
                "raw_score": float(movers[2]),
                "prev_raw_score": float(movers[3]),
            }

    # Trash Panda of the Week = ward with highest seasonal ratio.
    panda = con.execute(
        """
        SELECT ward, seasonal_ratio, raw_score
        FROM weekly_ward_index
        WHERE iso_year = ? AND iso_week = ? AND seasonal_ratio IS NOT NULL
        ORDER BY seasonal_ratio DESC
        LIMIT 1
        """,
        [latest_y, latest_w],
    ).fetchone()
    trash_panda = {
        "ward": panda[0],
        "seasonal_ratio": float(panda[1]),
        "raw_score": float(panda[2]),
    } if panda else None

    wards_elevated = sum(
        1 for w in index_latest["wards"]
        if w["seasonal_ratio"] is not None and float(w["seasonal_ratio"]) >= 1.0
    )

    # Projection for the current real-world ISO week.
    # Toronto 311 data lags ~3 weeks, so the latest confirmed week is usually well
    # behind today. Project the current week as (baseline for this ISO week) *
    # (mean seasonal ratio from trailing N weeks). Plain smoothing, not a forecast.
    today = datetime.date.today()
    proj_year, proj_week, _ = today.isocalendar()
    TRAIL_N = 4
    trailing = con.execute(
        """
        SELECT city_ratio FROM weekly_city
        WHERE city_ratio IS NOT NULL
          AND (iso_year < ? OR (iso_year = ? AND iso_week <= ?))
        ORDER BY iso_year DESC, iso_week DESC
        LIMIT ?
        """,
        [latest_y, latest_y, latest_w, TRAIL_N],
    ).fetchall()
    trailing_mean = (sum(float(r[0]) for r in trailing) / len(trailing)) if trailing else None

    proj_baseline_row = con.execute(
        """
        SELECT AVG(city_raw) FROM weekly_city
        WHERE iso_year BETWEEN 2019 AND 2024 AND iso_week = ?
        """,
        [proj_week],
    ).fetchone()
    proj_baseline = float(proj_baseline_row[0]) if proj_baseline_row[0] is not None else None

    projection = None
    if trailing_mean is not None and proj_baseline is not None:
        proj_raw = proj_baseline * trailing_mean
        proj_ratio = trailing_mean  # by construction
        proj_tier_level, proj_tier_name = assign_tier(proj_ratio)
        if proj_tier_level is None:
            proj_tier_level, proj_tier_name = 3, "MASK ON"
        projection = {
            "iso_year": proj_year,
            "iso_week": proj_week,
            "baseline": proj_baseline,
            "trailing_weeks": len(trailing),
            "trailing_ratio_mean": trailing_mean,
            "projected_raw_score": proj_raw,
            "projected_seasonal_ratio": proj_ratio,
            "projected_tier_level": proj_tier_level,
            "projected_tier_name": proj_tier_name,
        }

    summary = {
        "iso_year": latest_y,
        "iso_week": latest_w,
        "city_raw_score": city_raw_now,
        "city_seasonal_ratio": city_ratio_now,
        "tier_level": tier_level,
        "tier_name": tier_name,
        "wards_elevated": wards_elevated,
        "wards_total": len(index_latest["wards"]),
        "trash_panda": trash_panda,
        "biggest_mover": biggest_mover,
        "city_series_52w": city_series,
        "projection": projection,
    }
    (PROC / "index_summary.json").write_text(
        json.dumps(summary, indent=2, default=_json_default)
    )
    print(
        f"Wrote {PROC / 'index_summary.json'} — "
        f"tier {tier_level} {tier_name}, city ratio {city_ratio_now:.2f}×"
    )


if __name__ == "__main__":
    main()
