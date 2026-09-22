"""
Prep helper (not part of the numbered pipeline): converts YouGov's final
2024 MRP "call results" sheet into the CSV shape 04_ingest_mrp_release.py
expects. One row per seat, decimal-fraction vote shares, its own pcon_code
column ("const"). Same 5 Scottish seats as Ipsos's file have a pcon_code
our DB doesn't recognise (a shared pre-final ONS numbering both pollsters
apparently had at the time) — same fallback: pass the name instead and
let 04_ingest_mrp_release.py's fuzzy matcher resolve it (exact match).

The file also carries WinnerGE2024/SecondGE2024 columns — these are the
ACTUAL result, added after the fact for YouGov's own "how did we do"
retrospective piece, not part of the original prediction. Ignored here;
we already have the real GE2024 result from the official source
(08_ingest_ge2024_results.py) and don't want an unofficial copy of it
tagged as if it were MRP data.

Usage:
    python scripts/prep_yougov_xlsx.py --xlsx /path/to/Final_YouGov_2024_MRP_call_results_2.xlsx --out data/mrp_prepped/yougov_2024-07-03.csv
"""
import argparse
import csv
import sqlite3
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "uk_elections.db"

PARTY_MAP = {
    "conshare": "Con", "labshare": "Lab", "libdemshare": "LD", "snpshare": "SNP",
    "plaidshare": "PC", "greenshare": "Green", "reformshare": "RUK", "othersshare": "Other",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--xlsx", required=True)
    parser.add_argument("--sheet", default="Sheet1")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    con = sqlite3.connect(DB_PATH)
    known_codes = set(r[0] for r in con.execute("SELECT pcon_code FROM constituencies"))
    con.close()

    wb = openpyxl.load_workbook(args.xlsx, data_only=True)
    ws = wb[args.sheet]
    header = [str(c).strip() if c else "" for c in next(ws.iter_rows(min_row=1, max_row=1, values_only=True))]
    norm = [h.strip().lower().replace(" ", "") for h in header]

    code_col = norm.index("const")
    name_col = norm.index("area")
    party_cols = {PARTY_MAP[k]: i for i, k in enumerate(norm) if k in PARTY_MAP}

    out_rows = []
    n_seats = 0
    n_code_mismatch = 0
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, values_only=True):
        if not row[code_col]:
            continue
        n_seats += 1
        code, name = row[code_col], row[name_col]
        if code not in known_codes:
            n_code_mismatch += 1
            code = ""
        for our_party, i in party_cols.items():
            share = row[i]
            if isinstance(share, (int, float)) and share:
                out_rows.append({"pcon_code": code, "pcon_name": name, "party": our_party,
                                  "vote_share_pct": round(share * 100, 3), "win_probability_pct": ""})

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["pcon_code", "pcon_name", "party", "vote_share_pct", "win_probability_pct"])
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"Wrote {len(out_rows)} party rows across {n_seats} seats to {out_path} "
          f"({n_code_mismatch} seats fell back to name matching)")


if __name__ == "__main__":
    sys.exit(main())
