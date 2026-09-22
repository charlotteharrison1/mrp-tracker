"""
Prep helper (not part of the numbered pipeline): converts a More in Common
MRP release's "Results" sheet into the CSV shape 04_ingest_mrp_release.py
expects. Much simpler layout than Electoral Calculus's: one row per
constituency, one column per party (full party names, not abbreviations),
a single scenario (no tactical-voting variant), no combined SNP/Plaid
column, plus an "Other" catch-all and a "Winner" text column (not used —
04_ingest_mrp_release.py computes rank from vote share itself).

Column names are read from the header row rather than hardcoded, since
column SET could plausibly vary release to release (e.g. Plaid Cymru only
matters where Wales is covered) even though it hasn't yet across the
releases checked so far.

Usage:
    python scripts/prep_more_in_common_xlsx.py --xlsx /path/to/jul26-mrp-datatables-final-3.xlsx --out data/mrp_prepped/mic_2026-07-19.csv
"""
import argparse
import csv
import sys
from pathlib import Path

import openpyxl

PARTY_MAP = {
    "conservative": "Con", "labour": "Lab", "liberal democrat": "LD",
    "reform uk": "RUK", "the green party": "Green", "green party": "Green", "green": "Green",
    "scottish national party (snp)": "SNP", "snp": "SNP",
    "plaid cymru": "PC", "other": "Other",
}
NON_PARTY_COLS = {"constituency", "winner", "change"}  # "change" is a text field like "RUK GAIN from Lab", not a vote share


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--xlsx", required=True)
    parser.add_argument("--sheet", default="Results")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    wb = openpyxl.load_workbook(args.xlsx, data_only=True)
    ws = wb[args.sheet]

    header = [str(c).strip() if c else "" for c in next(ws.iter_rows(min_row=1, max_row=1, values_only=True))]
    seat_col = header.index("Constituency")

    party_cols = {}  # our_code -> column index
    unrecognised = []
    for i, name in enumerate(header):
        key = name.strip().lower()
        if not key or key in NON_PARTY_COLS:
            continue
        if key in PARTY_MAP:
            party_cols[PARTY_MAP[key]] = i
        else:
            unrecognised.append(name)
            party_cols[name.strip()] = i
    if unrecognised:
        print(f"  Party columns not in the fixed map, carried through verbatim: {unrecognised}")

    out_rows = []
    n_seats = 0
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, values_only=True):
        seat_name = row[seat_col]
        if not seat_name:
            continue
        n_seats += 1
        for our_party, i in party_cols.items():
            share = row[i]
            if share:
                out_rows.append({"pcon_code": "", "pcon_name": seat_name, "party": our_party,
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
