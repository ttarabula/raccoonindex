"""Copy processed data into the site/ directory in the shape the frontend expects.

Produces:
- site/data/wards.geojson — ward polygons with only the fields we need
- site/data/index_latest.json — current-week snapshot (keyed by ward code)
- site/data/ward_trend.json — 52-week raw_score series per ward
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"
RAW = ROOT / "data" / "raw"
SITE = ROOT / "site" / "data"
SITE.mkdir(parents=True, exist_ok=True)


def trim_wards_geojson() -> None:
    src = json.loads((RAW / "city-wards-4326.geojson").read_text())
    for feat in src["features"]:
        p = feat["properties"]
        feat["properties"] = {
            "ward": str(p.get("AREA_SHORT_CODE", "")).zfill(2),
            "name": p.get("AREA_NAME", ""),
        }
    (SITE / "wards.geojson").write_text(json.dumps(src, separators=(",", ":")))
    print(f"wrote wards.geojson ({(SITE / 'wards.geojson').stat().st_size / 1024:.0f} KB)")


def copy_index() -> None:
    data = json.loads((PROC / "index_latest.json").read_text())
    # Key by ward code for easy lookup from the map.
    data["by_ward"] = {w["ward"]: w for w in data["wards"]}
    (SITE / "index_latest.json").write_text(json.dumps(data, separators=(",", ":")))
    print(f"wrote index_latest.json ({(SITE / 'index_latest.json').stat().st_size / 1024:.0f} KB)")


def copy_trend() -> None:
    data = json.loads((PROC / "ward_trend_sparklines.json").read_text())
    (SITE / "ward_trend.json").write_text(json.dumps(data, separators=(",", ":")))
    print(f"wrote ward_trend.json ({(SITE / 'ward_trend.json').stat().st_size / 1024:.0f} KB)")


def copy_summary() -> None:
    src = PROC / "index_summary.json"
    dst = SITE / "index_summary.json"
    dst.write_text(src.read_text())
    print(f"wrote index_summary.json ({dst.stat().st_size / 1024:.0f} KB)")


def main() -> None:
    trim_wards_geojson()
    copy_index()
    copy_trend()
    copy_summary()


if __name__ == "__main__":
    main()
