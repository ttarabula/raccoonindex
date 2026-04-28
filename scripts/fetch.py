"""Fetch Toronto Open Data sources for raccoonindex.

Downloads the 311 Customer-Initiated yearly ZIPs, the Animal Services CSV, and
the 311 SR code reference. Idempotent: skips files already on disk.
"""
from pathlib import Path
import requests

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"

# 311 Service Requests — Customer Initiated (yearly ZIPs, FSA + ward geography)
SR_DS = "2e54bc0e-4399-4076-b717-351df5918ae7"  # parent dataset UUID
CKAN_BASE = f"https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/{SR_DS}/resource"
SR_YEARS = {
    2026: "99b7f283-7345-4f5a-a126-d078ed4f3419",
    2025: "f3db05ab-2588-4159-89f7-56c74d1d8201",
    2024: "f46b640d-d465-4f8b-9db5-5000a08295cd",
    2023: "079766f3-815d-4257-8731-5ff6b0c84c13",
    2022: "f00a3313-f074-463e-89a7-26563084fbef",
    2021: "95145825-04b4-40d8-b883-9d114b5853c4",
    2020: "04169bcc-860f-465d-b562-caab023b6f3c",
    2019: "120c0545-0a03-4ab0-ab08-f149d4ca61fc",
    2018: "5cce361d-35af-4251-802e-1b1ea1306a07",
    2017: "0b45485e-690d-425b-a69b-8b8c4f039f2b",
    2016: "4c6f5bed-5e7f-41c9-95c0-7181e048cdcf",
    2015: "e33b6300-8899-4f73-8ed0-febe10cbce92",
}

# 311 SR type classification codes (XLS, despite the .xlsx URL)
SR_CODES_URL = f"{CKAN_BASE}/23b4e01c-37a6-46be-999b-e5f317dcdd8c/download/sr_type_classification_codes.xlsx"

# Toronto Animal Services — Service Requests & Complaints (since 2023, CSV)
ANIMAL_DS = "694b6a00-7850-4d2b-a2f4-0d6ab93f8883"
ANIMAL_URL = (
    f"https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/{ANIMAL_DS}/resource/"
    "432cc813-6339-4b37-bb6c-a6b199e05289/download/"
    "service-requests-and-complaints-since-2023.csv"
)

# City Wards (25-ward model, 2018, WGS84)
WARDS_URL = (
    "https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/"
    "5e7a8234-f805-43ac-820f-03d7c360b588/resource/"
    "737b29e0-8329-4260-b6af-21555ab24f28/download/city-wards-data-4326.geojson"
)

# Ravine & Natural Feature Protection area (zipped shapefile, WGS84).
# Used by ravine_analysis.py to compute per-ward ravine adjacency.
RAVINE_URL = (
    "https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/"
    "204a7e54-8963-4e35-992e-5f21544ef595/resource/"
    "bb81bb0f-f88a-4f3e-bca7-a328154ba31b/download/"
    "ravine-natural-feature-protection-area-wgs84.zip"
)

# Ward Profiles (25-ward model) — XLSX of 2011/2016/2021 census data per ward.
# Used by build.py for per-capita normalization.
WARD_PROFILES_URL = (
    "https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/"
    "6678e1a6-d25f-4dff-b2b7-aa8f042bc2eb/resource/"
    "16a31e1d-b4d9-4cf0-b5b3-2e3937cb4121/download/"
    "2023-wardprofiles-2011-2021-censusdata_rev0719.xlsx"
)


def download(name: str, url: str) -> None:
    out = RAW / name
    if out.exists():
        print(f"skip {name} ({out.stat().st_size / 1e6:.1f} MB)")
        return
    print(f"download -> {name}")
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with out.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    print(f"  done: {out.stat().st_size / 1e6:.1f} MB")


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)

    download("sr_type_codes.xls", SR_CODES_URL)
    download("animal_services_since_2023.csv", ANIMAL_URL)
    download("city-wards-4326.geojson", WARDS_URL)
    download("ravine-protection-area.zip", RAVINE_URL)
    download("ward-profiles-2021.xlsx", WARD_PROFILES_URL)

    for year, rid in SR_YEARS.items():
        url = f"{CKAN_BASE}/{rid}/download/sr{year}.zip"
        download(f"sr{year}.zip", url)


if __name__ == "__main__":
    main()
