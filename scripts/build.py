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
import math
import re
import statistics
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
WEATHER_DAILY = RAW / "weather_daily.csv"
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

# Years used for the seasonal baseline. Excludes 2020–2021 because pandemic-era
# 311 call patterns are unrepresentative (WFH + lockdown distortions).
BASELINE_YEARS = (2019, 2022, 2023, 2024)
BASELINE_YEARS_SQL = "(" + ",".join(str(y) for y in BASELINE_YEARS) + ")"


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


# Z-score for a 90% two-sided credible interval under the normal approximation.
CI_Z = 1.645


def ratio_ci(components, baseline):
    """Approximate 90% CI on (weighted sum of counts) / baseline.

    Treats each category's count as independent Poisson (variance = count),
    so the weighted sum has variance = sum(w² · n). Baseline is treated as
    known (its uncertainty across 4 baseline years is small relative to the
    single-week Poisson noise).
    """
    if baseline is None or float(baseline) <= 0:
        return None, None
    raw = 0.0
    var = 0.0
    for cat, n in components.items():
        w = WEIGHTS.get(cat, 1.0)
        raw += w * float(n)
        var += w * w * float(n)
    if raw <= 0 or var <= 0:
        return None, None
    se = math.sqrt(var) / float(baseline)
    ratio = raw / float(baseline)
    return max(0.0, ratio - CI_Z * se), ratio + CI_Z * se


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
            -- Seasonal baseline excludes 2020–2021 (pandemic distortions) and any
            -- pre-2019 data (44-ward model uses different geography).
            SELECT ward, iso_week, AVG(raw_score) AS season_mean
            FROM scored
            WHERE iso_year IN """ + BASELINE_YEARS_SQL + """
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
        components = dict(zip(cats, row[4:]))
        ci_lo, ci_hi = ratio_ci(components, row[2])
        tier_lo = assign_tier(ci_lo)[0] if ci_lo is not None else tier_level
        tier_hi = assign_tier(ci_hi)[0] if ci_hi is not None else tier_level
        return {
            "ward": row[0],
            "raw_score": row[1],
            "season_mean": row[2],
            "seasonal_ratio": row[3],
            "seasonal_ratio_ci_low": ci_lo,
            "seasonal_ratio_ci_high": ci_hi,
            "tier_level": tier_level,
            "tier_name": tier_name,
            "tier_level_ci_low": tier_lo,
            "tier_level_ci_high": tier_hi,
            "components": components,
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

    # Trim the most-recent partial week so the trendline tail doesn't dip
    # misleadingly. Anchor to the latest *complete* week.
    city_52 = con.execute(
        """
        SELECT iso_year, iso_week, city_raw, city_ratio
        FROM weekly_city
        WHERE (iso_year < ? OR (iso_year = ? AND iso_week <= ?))
        ORDER BY iso_year DESC, iso_week DESC
        LIMIT 52
        """,
        [latest_y, latest_y, latest_w],
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

    # City-wide CI: sum Poisson variance across wards, then divide by the
    # (summed) baseline that drives the city_ratio.
    city_ci_low = city_ci_high = None
    if city_ratio_now is not None:
        total_var = 0.0
        total_baseline = 0.0
        for w_row in index_latest["wards"]:
            total_baseline += float(w_row["season_mean"] or 0.0)
            for cat, n in w_row["components"].items():
                w_c = WEIGHTS.get(cat, 1.0)
                total_var += w_c * w_c * float(n)
        if total_baseline > 0 and total_var > 0:
            se = math.sqrt(total_var) / total_baseline
            city_ci_low = max(0.0, city_ratio_now - CI_Z * se)
            city_ci_high = city_ratio_now + CI_Z * se

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
    trailing_values = [float(r[0]) for r in trailing]
    trailing_mean = (sum(trailing_values) / len(trailing_values)) if trailing_values else None

    # Weather integration: regress log(city_ratio) vs current-week temperature
    # deviation from the historical (baseline years) average for that ISO week.
    # Apply the resulting β to the current week's temp deviation to shift the
    # projection up or down. A hot week for March will nudge the projection
    # higher; a cold snap will nudge it lower.
    weather_beta_temp = 0.0
    weather_beta_precip = 0.0
    weather_n = 0
    weather_r2 = None
    weather_current_temp = None
    weather_current_precip = None
    weather_historical_temp = None
    weather_historical_precip = None
    weather_factor = 1.0
    hist_temp_by_iso_week: dict[int, float] = {}
    hist_precip_by_iso_week: dict[int, float] = {}

    if WEATHER_DAILY.exists():
        import numpy as np

        con.execute(
            f"""
            CREATE OR REPLACE VIEW weather_daily AS
            SELECT CAST(date AS DATE) AS d,
                   TRY_CAST(mean_temp_c AS DOUBLE) AS temp,
                   TRY_CAST(precip_mm AS DOUBLE) AS precip
            FROM read_csv('{WEATHER_DAILY}', header=true, auto_detect=true,
                          nullstr='')
            """
        )
        con.execute(
            """
            CREATE OR REPLACE VIEW weekly_weather AS
            SELECT CAST(ISOYEAR(d) AS INT) AS iso_year,
                   CAST(WEEK(d) AS INT) AS iso_week,
                   AVG(temp) AS weekly_temp,
                   AVG(precip) AS weekly_precip
            FROM weather_daily
            GROUP BY iso_year, iso_week
            """
        )
        hist_rows = con.execute(
            f"""
            SELECT iso_week, AVG(weekly_temp), AVG(weekly_precip)
            FROM weekly_weather
            WHERE iso_year IN {BASELINE_YEARS_SQL}
            GROUP BY iso_week
            """
        ).fetchall()
        for iso_w, t, p in hist_rows:
            if t is not None:
                hist_temp_by_iso_week[int(iso_w)] = float(t)
            if p is not None:
                hist_precip_by_iso_week[int(iso_w)] = float(p)

        reg_rows = con.execute(
            f"""
            SELECT c.city_ratio, w.weekly_temp, w.weekly_precip, c.iso_week
            FROM weekly_city c
            JOIN weekly_weather w USING (iso_year, iso_week)
            WHERE c.iso_year IN {BASELINE_YEARS_SQL}
              AND c.city_ratio IS NOT NULL AND c.city_ratio > 0
              AND w.weekly_temp IS NOT NULL
              AND w.weekly_precip IS NOT NULL
            """
        ).fetchall()
        X_rows, ys = [], []
        for ratio_v, temp_v, precip_v, iso_w in reg_rows:
            ht = hist_temp_by_iso_week.get(int(iso_w))
            hp = hist_precip_by_iso_week.get(int(iso_w))
            if ht is None or hp is None:
                continue
            X_rows.append([1.0, float(temp_v) - ht, float(precip_v) - hp])
            ys.append(math.log(float(ratio_v)))
        if len(X_rows) >= 10:
            X = np.array(X_rows)
            y = np.array(ys)
            coefs, *_ = np.linalg.lstsq(X, y, rcond=None)
            alpha_hat, weather_beta_temp, weather_beta_precip = (float(c) for c in coefs)
            weather_n = len(X_rows)
            y_hat = X @ coefs
            total_ss = float(((y - y.mean()) ** 2).sum())
            resid_ss = float(((y - y_hat) ** 2).sum())
            weather_r2 = 1.0 - resid_ss / total_ss if total_ss > 0 else None

        cur_row = con.execute(
            """
            SELECT AVG(temp), AVG(precip) FROM weather_daily
            WHERE CAST(ISOYEAR(d) AS INT) = ? AND CAST(WEEK(d) AS INT) = ?
            """,
            [proj_year, proj_week],
        ).fetchone()
        weather_current_temp = float(cur_row[0]) if cur_row[0] is not None else None
        weather_current_precip = float(cur_row[1]) if cur_row[1] is not None else None
        weather_historical_temp = hist_temp_by_iso_week.get(proj_week)
        weather_historical_precip = hist_precip_by_iso_week.get(proj_week)

        exponent = 0.0
        if weather_current_temp is not None and weather_historical_temp is not None:
            exponent += weather_beta_temp * (weather_current_temp - weather_historical_temp)
        if weather_current_precip is not None and weather_historical_precip is not None:
            exponent += weather_beta_precip * (weather_current_precip - weather_historical_precip)
        weather_factor = math.exp(exponent) if exponent != 0.0 else 1.0
    # Projection CI from the variability of trailing weekly ratios. Uses sample
    # std / sqrt(n); falls back to None when we have fewer than 2 observations.
    if trailing_mean is not None and len(trailing_values) >= 2:
        trailing_sd = statistics.stdev(trailing_values)
        trailing_se = trailing_sd / math.sqrt(len(trailing_values))
    else:
        trailing_se = None

    proj_baseline_row = con.execute(
        f"""
        SELECT AVG(city_raw) FROM weekly_city
        WHERE iso_year IN {BASELINE_YEARS_SQL} AND iso_week = ?
        """,
        [proj_week],
    ).fetchone()
    proj_baseline = float(proj_baseline_row[0]) if proj_baseline_row[0] is not None else None

    projection = None
    if trailing_mean is not None and proj_baseline is not None:
        # Apply weather adjustment: if this week is warmer than the historical
        # avg for this ISO week, nudge the projection up (and vice versa).
        proj_ratio_pre_weather = trailing_mean
        proj_ratio = trailing_mean * weather_factor
        proj_raw = proj_baseline * proj_ratio
        proj_tier_level, proj_tier_name = assign_tier(proj_ratio)
        if proj_tier_level is None:
            proj_tier_level, proj_tier_name = 3, "MASK ON"
        proj_ci_low = max(0.0, proj_ratio - CI_Z * trailing_se) if trailing_se is not None else None
        proj_ci_high = proj_ratio + CI_Z * trailing_se if trailing_se is not None else None
        projection = {
            "iso_year": proj_year,
            "iso_week": proj_week,
            "baseline": proj_baseline,
            "trailing_weeks": len(trailing),
            "trailing_ratio_mean": trailing_mean,
            "projected_raw_score": proj_raw,
            "projected_seasonal_ratio": proj_ratio,
            "projected_seasonal_ratio_ci_low": proj_ci_low,
            "projected_seasonal_ratio_ci_high": proj_ci_high,
            "projected_tier_level": proj_tier_level,
            "projected_tier_name": proj_tier_name,
            "weather": {
                "current_week_temp_c": weather_current_temp,
                "historical_week_temp_c": weather_historical_temp,
                "current_week_precip_mm": weather_current_precip,
                "historical_week_precip_mm": weather_historical_precip,
                "beta_temp": weather_beta_temp,
                "beta_precip": weather_beta_precip,
                "n_fit": weather_n,
                "r_squared": weather_r2,
                "adjustment_factor": weather_factor,
                "ratio_before_weather": proj_ratio_pre_weather,
            },
        }

    summary = {
        "iso_year": latest_y,
        "iso_week": latest_w,
        "city_raw_score": city_raw_now,
        "city_seasonal_ratio": city_ratio_now,
        "city_seasonal_ratio_ci_low": city_ci_low,
        "city_seasonal_ratio_ci_high": city_ci_high,
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
