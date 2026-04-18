"""EDA pass 1 — what raccoon-adjacent SR types exist in the 311 Customer Initiated
dataset, and how much geographic coverage do they have?

Key question: the Animal Services dataset has no geography. But earlier samples
of the 311 Customer Initiated CSVs show categories like 'Injured - Domestic' —
which suggests the wildlife records may also exist here with FSA. If so, we have
a real Index signal, not just a proxy one.

Outputs summary tables to stdout and writes processed/sr_type_counts.csv.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
PROC.mkdir(parents=True, exist_ok=True)

YEARS = sorted(int(p.stem[2:]) for p in RAW.glob("sr20*.zip"))


def load_year(con: duckdb.DuckDBPyConnection, year: int) -> None:
    """Extract the year's CSV from its ZIP into a temp view."""
    zpath = RAW / f"sr{year}.zip"
    with zipfile.ZipFile(zpath) as z:
        name = z.namelist()[0]
        z.extract(name, path=RAW / f"_unpacked")
    csv_path = RAW / "_unpacked" / name
    con.execute(
        f"""
        CREATE OR REPLACE TABLE sr_{year} AS
        SELECT * FROM read_csv(
            '{csv_path}',
            header=true,
            delim=',',
            quote='"',
            escape='"',
            ignore_errors=true,
            null_padding=true,
            strict_mode=false,
            sample_size=-1
        );
        """
    )


def main() -> None:
    con = duckdb.connect()

    print(f"Loading years: {YEARS}")
    for y in YEARS:
        load_year(con, y)

    # Union all into one view; normalize column names across years.
    # We expect: Creation Date, Status, First 3 Chars of Postal Code, Ward,
    # Service Request Type, Division, Section. Older years may differ slightly.
    print("\n=== Columns per year ===")
    for y in YEARS:
        cols = con.execute(f"DESCRIBE sr_{y}").fetchall()
        print(f"  {y}: {[c[0] for c in cols]}")

    # Build a unified view using only the columns that matter.
    union_sql = " UNION ALL ".join(
        f"""SELECT
              {y} AS year,
              TRY_CAST("Creation Date" AS TIMESTAMP) AS created_at,
              "First 3 Chars of Postal Code" AS fsa,
              Ward AS ward,
              "Service Request Type" AS sr_type,
              Division AS division,
              Section AS section
            FROM sr_{y}"""
        for y in YEARS
    )
    con.execute(f"CREATE OR REPLACE VIEW sr_all AS {union_sql}")

    total = con.execute("SELECT COUNT(*) FROM sr_all").fetchone()[0]
    print(f"\nTotal rows across all years: {total:,}")

    # All SR types by volume
    print("\n=== Top 30 SR types (all years) ===")
    rows = con.execute(
        """
        SELECT sr_type, COUNT(*) AS n,
               SUM(CASE WHEN fsa IS NOT NULL AND fsa <> '' THEN 1 ELSE 0 END) AS with_fsa
        FROM sr_all
        GROUP BY sr_type
        ORDER BY n DESC
        LIMIT 30
        """
    ).fetchall()
    for sr, n, f in rows:
        print(f"  {n:>10,} | fsa={f:>10,} ({f/n:.0%}) | {sr}")

    # Raccoon-adjacent keyword sweep
    print("\n=== Raccoon-adjacent SR types (keyword match) ===")
    rows = con.execute(
        """
        SELECT sr_type, COUNT(*) AS n,
               SUM(CASE WHEN fsa IS NOT NULL AND fsa <> '' THEN 1 ELSE 0 END) AS with_fsa
        FROM sr_all
        WHERE LOWER(sr_type) SIMILAR TO
              '%(raccoon|wildlife|coyote|skunk|squirrel|rodent|rat\\s|animal|cadaver|injured|pest|dead\\s|nuisance|feed|wild)%'
           OR LOWER(sr_type) LIKE '%bin%'
           OR LOWER(sr_type) LIKE '%garbage%'
           OR LOWER(sr_type) LIKE '%litter%'
           OR LOWER(sr_type) LIKE '%dumping%'
           OR LOWER(sr_type) LIKE '%overflow%'
        GROUP BY sr_type
        ORDER BY n DESC
        """
    ).fetchall()
    for sr, n, f in rows:
        print(f"  {n:>10,} | fsa={f:>10,} ({f/n:.0%}) | {sr}")

    # Write processed counts for downstream scripts
    con.execute(
        f"""
        COPY (
            SELECT sr_type, year, COUNT(*) AS n
            FROM sr_all
            GROUP BY sr_type, year
            ORDER BY sr_type, year
        ) TO '{PROC / "sr_type_year_counts.csv"}' (HEADER, DELIMITER ',');
        """
    )
    print(f"\nWrote {PROC / 'sr_type_year_counts.csv'}")


if __name__ == "__main__":
    main()
