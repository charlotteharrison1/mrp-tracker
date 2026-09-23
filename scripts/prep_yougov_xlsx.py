"""
Prep helper (not part of the numbered pipeline): converts a YouGov MRP
seat-level file into the CSV shape 04_ingest_mrp_release.py expects. One
row per seat, decimal-fraction vote shares, its own pcon_code column.

YouGov has used at least THREE different header naming schemes across
releases seen so far (found 2026-09-23 while backfilling missed
releases) — code/name column names are auto-detected from a list of
known aliases rather than hardcoded, since a 4th naming scheme wouldn't
be surprising:
  - 2024-07-03 (.xlsx): "const" / "area"
  - 2025-06-26 (.xlsx): "ONS_ID" / "Constituency"
  - 2025-09-26 (.csv):  "ons_id24" / "const_name24"
Party share column names (ConShare, LabShare, etc.) have stayed
consistent across all three.

Same 5 Scottish seats as Ipsos's file have a pcon_code our DB doesn't
recognise in the 2024 release (a shared pre-final ONS numbering both
pollsters apparently had at the time) — same fallback: pass the name
instead and let 04_ingest_mrp_release.py's fuzzy matcher resolve it
(exact match). Later releases haven't shown this issue but the fallback
applies uniformly regardless.

The 2024 file also carries WinnerGE2024/SecondGE2024 columns — the
ACTUAL result, added after the fact for YouGov's own "how did we do"
retrospective piece, not part of the original prediction. Ignored here;
we already have the real GE2024 result from the official source
(08_ingest_ge2024_results.py) and don't want an unofficial copy of it
tagged as if it were MRP data.

Usage:
    python scripts/prep_yougov_xlsx.py --file /path/to/Final_YouGov_2024_MRP_call_results_2.xlsx --out data/mrp_prepped/yougov_2024-07-03.csv
    python scripts/prep_yougov_xlsx.py --file /path/to/YouGov-MRP-Results-2025-09-25.csv --out data/mrp_prepped/yougov_2025-09-26.csv
"""
import argparse
import csv
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "uk_elections.db"

PARTY_MAP = {
    "conshare": "Con", "labshare": "Lab", "libdemshare": "LD", "snpshare": "SNP",
    "plaidshare": "PC", "greenshare": "Green", "reformshare": "RUK", "othersshare": "Other",
}
CODE_COL_ALIASES = ["const", "ons_id", "ons_id24"]
NAME_COL_ALIASES = ["area", "constituency", "const_name24"]


def read_rows(path, sheet):
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
    else:
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb[sheet]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help=".xlsx or .csv release file")
    parser.add_argument("--sheet", default="Sheet1", help="sheet name, xlsx only")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    con = sqlite3.connect(DB_PATH)
    known_codes = set(r[0] for r in con.execute("SELECT pcon_code FROM constituencies"))
    con.close()

    rows = read_rows(Path(args.file), args.sheet)
    header = [str(c).strip() if c else "" for c in rows[0]]
    norm = [h.strip().lower().replace(" ", "") for h in header]

    code_col = next((norm.index(a) for a in CODE_COL_ALIASES if a in norm), None)
    name_col = next((norm.index(a) for a in NAME_COL_ALIASES if a in norm), None)
    if code_col is None or name_col is None:
        sys.exit(f"Couldn't find a code/name column in header: {header}")
    party_cols = {PARTY_MAP[k]: i for i, k in enumerate(norm) if k in PARTY_MAP}

    out_rows = []
    n_seats = 0
    n_code_mismatch = 0
    for row in rows[1:]:
        if not row or not row[code_col]:
            continue
        n_seats += 1
        code, name = row[code_col], row[name_col]
        if code not in known_codes:
            n_code_mismatch += 1
            code = ""
        for our_party, i in party_cols.items():
            share = row[i]
            if isinstance(share, str):
                share = float(share) if share.strip() else None
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
