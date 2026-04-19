"""Fetch daily temperatures from Environment Canada for Toronto City station.

One request per (year, month). Saves raw CSVs to data/raw/weather/ and a
merged CSV at data/raw/weather_daily.csv.

Used by build.py to adjust the projection for current-week temperature.
"""
from __future__ import annotations

import csv
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "weather"
MERGED = ROOT / "data" / "raw" / "weather_daily.csv"

# Toronto City Climate ID 6158355 (station ID 31688). Central, good record
# going back decades. We could also use Pearson (51459) — but since most of
# Toronto's 311 calls come from central wards, City is a fine choice.
STATION_ID = 31688
START_YEAR = 2019
END_YEAR = 2026  # inclusive; overwrite latest month on each run

URL = "https://climate.weather.gc.ca/climate_data/bulk_data_e.html"


def fetch_month(year: int, month: int, out: Path, force: bool = False) -> None:
    if out.exists() and not force:
        return
    params = {
        "format": "csv",
        "stationID": STATION_ID,
        "Year": year,
        "Month": month,
        "Day": 1,
        "timeframe": 2,
    }
    # ECCC's server occasionally times out or rate-limits CI runners. Retry
    # a few times with backoff rather than failing the whole deploy on a
    # single flaky request.
    last_err: Exception | None = None
    for attempt in range(4):
        try:
            r = requests.get(URL, params=params, timeout=60)
            r.raise_for_status()
            out.write_bytes(r.content)
            return
        except (requests.exceptions.RequestException, requests.HTTPError) as e:
            last_err = e
            import time
            time.sleep(2 ** attempt)
    assert last_err is not None
    raise last_err


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    import datetime
    today = datetime.date.today()
    current_year_month = (today.year, today.month)

    # ECCC's bulk endpoint returns the full year of daily data regardless of
    # the Month param. Fetch one request per year. For the current year, force
    # a refresh so recent days land.
    for year in range(START_YEAR, END_YEAR + 1):
        if year > today.year:
            break
        out = RAW / f"{year}-01.csv"
        force = (year == today.year)
        fetch_month(year, 1, out, force=force)

    # Merge into one clean daily CSV with (date, mean_temp). ECCC bulk
    # endpoint returns the full year regardless of Month param, so dedupe
    # by date and prefer the most recent file (newer fetches for the current
    # month pick up intra-month updates).
    # (date -> (mean_temp_c, precip_mm)). precip can be missing independently
    # of temp; we keep whichever are available per day.
    seen: dict[str, tuple[float | None, float | None]] = {}
    for fp in sorted(RAW.glob("*.csv")):
        with fp.open(encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                date = row.get("Date/Time") or row.get("\ufeffDate/Time")
                mean = row.get("Mean Temp (\u00b0C)")
                precip = row.get("Total Precip (mm)")
                if not date:
                    continue
                t = None
                p = None
                try:
                    if mean:
                        t = float(mean)
                except ValueError:
                    pass
                try:
                    if precip:
                        p = float(precip)
                except ValueError:
                    pass
                seen[date] = (t, p)
    with MERGED.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "mean_temp_c", "precip_mm"])
        for date in sorted(seen):
            t, p = seen[date]
            w.writerow([date, "" if t is None else t, "" if p is None else p])
    print(f"wrote {MERGED} ({len(seen)} unique daily rows)")


if __name__ == "__main__":
    main()
