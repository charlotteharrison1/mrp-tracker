"""
Pull a "Ward to Westminster Parliamentary Constituency to LAD to UTLA" lookup
from the ONS Open Geography Portal (ArcGIS Hub) and load it into the
`wards` and `constituencies` tables.

WHY THIS APPROACH:
ONS publishes a new vintage of this lookup periodically (found so far: Dec
2019, Dec 2023 — there will likely be a newer one reflecting the actual 2024
general election boundaries; check https://geoportal.statistics.gov.uk/ or
search "[year] Ward to Westminster Parliamentary Constituency lookup ONS"
for the current one). Each vintage has its own ArcGIS FeatureServer with its
own field names (WD19CD/PCON19CD vs WD23CD/PCON23CD etc.), so this script
takes the base FeatureServer URL and the field-name suffix as arguments
rather than hardcoding one vintage.

CONFIRMED WORKING (as of the research for this project, Sept 2026):
  Dec 2019 vintage, suffix "19":
  https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/WD19_PCON19_LAD19_UTLA19_UK_LU_e5a0b74eff43407b86dcc7a4300ceb25/FeatureServer

For the Dec 2023 vintage (suffix "23") or any newer one, go to the dataset's
page on https://geoportal.statistics.gov.uk/, open the "API" tab, and copy
the FeatureServer URL from there — the exact service ID isn't guessable and
drifts between ONS publications.

Usage:
    python scripts/01_fetch_ons_lookup.py \\
        --base-url "https://services1.arcgis.com/.../FeatureServer" \\
        --suffix 19 \\
        --boundary-year 2019
"""
import argparse
import sqlite3
import sys
from pathlib import Path

import requests
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "uk_elections.db"

NATION_PREFIX = {"E": "England", "S": "Scotland", "W": "Wales", "N": "Northern Ireland"}


def fetch_all_features(base_url: str, page_size: int = 2000):
    """Page through an ArcGIS FeatureServer layer 0 and yield all attribute rows."""
    offset = 0
    while True:
        params = {
            "where": "1=1",
            "outFields": "*",
            "f": "json",
            "resultOffset": offset,
            "resultRecordCount": page_size,
        }
        resp = requests.get(f"{base_url}/0/query", params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        features = data.get("features", [])
        if not features:
            break
        for f in features:
            yield f["attributes"]
        offset += len(features)
        if not data.get("exceededTransferLimit") and len(features) < page_size:
            break


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True, help="ArcGIS FeatureServer base URL (no trailing /0/query)")
    parser.add_argument("--suffix", required=True, help="field-name year suffix, e.g. 19 or 23")
    parser.add_argument("--boundary-year", type=int, required=True, help="boundary_year to tag these wards with")
    args = parser.parse_args()

    s = args.suffix
    wd_cd, wd_nm = f"WD{s}CD", f"WD{s}NM"
    pcon_cd, pcon_nm = f"PCON{s}CD", f"PCON{s}NM"
    lad_cd, lad_nm = f"LAD{s}CD", f"LAD{s}NM"

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    seen_constituencies = {}
    ward_rows = []

    print("Fetching from ArcGIS FeatureServer (paginated)...")
    for attrs in tqdm(fetch_all_features(args.base_url)):
        pc, pn = attrs.get(pcon_cd), attrs.get(pcon_nm)
        if pc and pc not in seen_constituencies:
            seen_constituencies[pc] = pn

        ward_rows.append((
            attrs.get(wd_cd), attrs.get(wd_nm), args.boundary_year,
            attrs.get(lad_cd), attrs.get(lad_nm),
            pc, pn,
        ))

    print(f"Found {len(seen_constituencies)} constituencies, {len(ward_rows)} ward rows.")

    for pc, pn in seen_constituencies.items():
        nation = NATION_PREFIX.get(pc[0], "Unknown")
        cur.execute(
            """INSERT INTO constituencies (pcon_code, pcon_name, nation)
               VALUES (?, ?, ?)
               ON CONFLICT(pcon_code) DO UPDATE SET pcon_name=excluded.pcon_name""",
            (pc, pn, nation),
        )

    cur.executemany(
        """INSERT INTO wards (ward_code, ward_name, boundary_year, la_code, la_name, pcon_code, pcon_name)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(ward_code, boundary_year) DO UPDATE SET
               ward_name=excluded.ward_name, la_code=excluded.la_code,
               la_name=excluded.la_name, pcon_code=excluded.pcon_code, pcon_name=excluded.pcon_name""",
        ward_rows,
    )

    con.commit()
    con.close()
    print("Done.")


if __name__ == "__main__":
    sys.exit(main())
