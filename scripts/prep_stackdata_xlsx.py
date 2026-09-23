"""
Prep helper (not part of the numbered pipeline): converts a Stack Data
Strategy MRP release's "MRP Estimates" sheet into the CSV shape
04_ingest_mrp_release.py expects. Confirmed against the 2025-08-03
release (a public Google Sheet, exported to xlsx).

Clean single-header-row format: Constituency Code, Constituency Name,
Region, Turnout_Pred, then one _Pred column per party (decimal
fractions), plus DontKnow_Pred (excluded — not a party) and Winner_Pred
(excluded — redundant with the vote shares).

Usage:
    python scripts/prep_stackdata_xlsx.py --file /path/to/stackdata_mrp.xlsx --out data/mrp_prepped/stackdata_2025-08-03.csv
"""
import argparse
import csv
import sys
from pathlib import Path

import openpyxl

PARTY_MAP = {"LAB_Pred": "Lab", "CON_Pred": "Con", "RUK_Pred": "RUK", "LD_Pred": "LD",
             "GREEN_Pred": "Green", "SNP_Pred": "SNP", "PC_Pred": "PC", "OTH_Pred": "Other"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--sheet", default="MRP Estimates")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    wb = openpyxl.load_workbook(args.file, data_only=True)
    ws = wb[args.sheet]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]

    header = rows[0]
    code_col = header.index("Constituency Code")
    name_col = header.index("Constituency Name")
    party_cols = {PARTY_MAP[h]: i for i, h in enumerate(header) if h in PARTY_MAP}

    out_rows = []
    n_seats = 0
    for row in rows[1:]:
        if not row[code_col]:
            continue
        n_seats += 1
        for our_party, i in party_cols.items():
            share = row[i]
            if isinstance(share, (int, float)) and share:
                out_rows.append({"pcon_code": row[code_col], "pcon_name": row[name_col], "party": our_party,
                                  "vote_share_pct": round(share * 100, 3), "win_probability_pct": ""})

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["pcon_code", "pcon_name", "party", "vote_share_pct", "win_probability_pct"])
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"Wrote {len(out_rows)} party rows across {n_seats} seats to {out_path}")


if __name__ == "__main__":
    sys.exit(main())
