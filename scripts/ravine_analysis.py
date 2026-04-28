"""One-shot exploratory analysis: does ravine adjacency predict baseline activity?

Hypothesis going in: ravine-adjacent wards should have structurally higher
raccoon-proxy activity because the ravine system is a literal raccoon highway.

Finding (2026-04-28): no. Spearman rho ≈ +0.10 against the full Index raw
score, and *negative* (-0.26) against wildlife calls per km². Dense downtown
wards with little ravine area (Toronto-Danforth, Beaches-East York, Davenport)
produce 5–8× the wildlife calls per km² of Scarborough wards that are >50%
ravine. The signal we have is dominated by human reporter density, not
raccoon habitat — a concrete instance of the "311 measures reporting, not
incidence" caveat.

For each ward this script computes:
  - share of ward area inside Ravine & Natural Feature Protection polygons
  - share within a 200 m buffer of the same polygons
  - mean weekly raw Index score across baseline years (2019, 2022–2024)
  - wildlife-only call totals over the same window, per km²
  - Spearman rank correlations between ravine adjacency and each measure
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"

# UTM zone 17N — accurate metric units for Toronto.
TORONTO_CRS = "EPSG:32617"
BUFFER_METERS = 200
BASELINE_YEARS = (2019, 2022, 2023, 2024)


def main() -> None:
    wards = gpd.read_file(RAW / "city-wards-4326.geojson").to_crs(TORONTO_CRS)
    wards["ward"] = wards["AREA_SHORT_CODE"].astype(str).str.zfill(2)
    wards["name"] = wards["AREA_NAME"]
    wards["area_m2"] = wards.geometry.area

    ravine = gpd.read_file(f"zip://{RAW / 'ravine-protection-area.zip'}").to_crs(TORONTO_CRS)
    # Dissolve all ravine polygons into one geometry so per-ward intersections
    # aren't double-counted on overlapping/adjacent polys.
    ravine_union = ravine.geometry.union_all()
    ravine_buffered = ravine_union.buffer(BUFFER_METERS)

    rows = []
    for _, w in wards.iterrows():
        inter = w.geometry.intersection(ravine_union)
        inter_buf = w.geometry.intersection(ravine_buffered)
        rows.append({
            "ward": w["ward"],
            "name": w["name"],
            "ward_area_km2": w["area_m2"] / 1e6,
            "ravine_pct": (inter.area / w["area_m2"]) * 100 if w["area_m2"] > 0 else 0,
            "ravine_within_200m_pct": (inter_buf.area / w["area_m2"]) * 100 if w["area_m2"] > 0 else 0,
        })
    adj = pd.DataFrame(rows).sort_values("ravine_pct", ascending=False)

    # Index raw score per ward, baseline-year mean.
    idx = pd.read_parquet(PROC / "weekly_ward_index.parquet")
    baseline = (
        idx[idx["iso_year"].isin(BASELINE_YEARS)]
        .groupby("ward", as_index=False)["raw_score"]
        .mean()
        .rename(columns={"raw_score": "baseline_weekly_raw"})
    )

    # Wildlife-only totals (cadaver + injured + nuisance) across baseline years.
    cats = pd.read_parquet(PROC / "weekly_ward_category.parquet")
    wl = cats[
        cats["category"].isin(["wildlife_cadaver", "wildlife_injured", "wildlife_nuisance"])
        & cats["iso_year"].isin(BASELINE_YEARS)
    ]
    wildlife = (
        wl.groupby("ward", as_index=False)["n"].sum()
        .rename(columns={"n": "wildlife_calls_baseline"})
    )

    merged = adj.merge(baseline, on="ward", how="left").merge(wildlife, on="ward", how="left")
    merged["wildlife_per_km2"] = merged["wildlife_calls_baseline"] / merged["ward_area_km2"]

    print("\n=== Per-ward ravine adjacency vs. activity ===")
    print(
        merged.sort_values("ravine_within_200m_pct", ascending=False)[
            ["ward", "name", "ward_area_km2", "ravine_pct",
             "ravine_within_200m_pct", "baseline_weekly_raw", "wildlife_per_km2"]
        ].to_string(
            index=False,
            float_format=lambda v: f"{v:7.2f}",
        )
    )

    print(f"\n=== Spearman rank correlation (n = {len(merged)}) ===")
    targets = [
        ("baseline_weekly_raw", "Index raw score (baseline-year mean)"),
        ("wildlife_calls_baseline", "wildlife calls (baseline totals)"),
        ("wildlife_per_km2", "wildlife calls per km²"),
    ]
    for col, label in targets:
        for radj in ["ravine_pct", "ravine_within_200m_pct"]:
            r = merged[[radj, col]].corr(method="spearman").iloc[0, 1]
            print(f"  {radj:24s}  vs  {label:38s}  rho = {r:+.3f}")

    # Tertile comparison on the per-km² measure — the cleanest read on whether
    # ravines drive raccoon habitat density (rather than just total reports).
    merged["bucket"] = pd.qcut(
        merged["ravine_within_200m_pct"], 3, labels=["low", "mid", "high"]
    )
    print("\n=== Wildlife calls per km² by ravine-adjacency tertile ===")
    bucket_stats = merged.groupby("bucket", observed=True).agg(
        n=("ward", "count"),
        mean_per_km2=("wildlife_per_km2", "mean"),
        median_per_km2=("wildlife_per_km2", "median"),
    )
    print(bucket_stats.to_string(float_format=lambda v: f"{v:8.1f}"))
    if "low" in bucket_stats.index and "high" in bucket_stats.index:
        ratio = bucket_stats.loc["high", "mean_per_km2"] / bucket_stats.loc["low", "mean_per_km2"]
        print(f"\n  High-adjacency wards run {ratio:.2f}× the low-adjacency per-km² mean.")
        print("  Hypothesis was that ravines drive activity (expect >>1.0). Result is the")
        print("  other direction: ravine-rich wards (mostly Scarborough) report *fewer*")
        print("  wildlife calls per km² than dense downtown wards with little ravine area.")
        print("  311 measures who reports, not what's there.")

    # Save the per-ward table for downstream use if we end up surfacing it.
    out = PROC / "ward_ravine.json"
    merged_out = merged.drop(columns=["bucket"]).copy()
    out.write_text(merged_out.to_json(orient="records", indent=2))
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
