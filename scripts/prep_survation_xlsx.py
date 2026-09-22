"""
Prep helper (not part of the numbered pipeline): converts Survation's MRP
"Seat results" + "Win probabilities" sheets into the CSV shape
04_ingest_mrp_release.py expects. Best-structured file seen so far: exact
PCON24CD codes (our scheme exactly, no fuzzy matching needed at all), and
a separate win-probability figure per party per seat that the template
CSV has a column for but most other releases don't supply.

Note the scale: Survation's vote shares are already 0-100 (e.g. 30.9),
NOT a 0-1 fraction like Ipsos/YouGov/More in Common — don't multiply by
100 again.

Usage:
    python scripts/prep_survation_xlsx.py --xlsx /path/to/Survation_Final_MRP_04_07_2024.xlsx --out data/mrp_prepped/survation_2024-07-04.csv
"""
import argparse
import csv
import sys
from pathlib import Path

import openpyxl

PARTY_MAP = {"con": "Con", "lab": "Lab", "ldem": "LD", "green": "Green", "reform": "RUK", "plaid": "PC", "snp": "SNP", "other": "Other"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--xlsx", required=True)
    parser.add_argument("--shares-sheet", default="Seat results")
    parser.add_argument("--winprob-sheet", default="Win probabilities")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    wb = openpyxl.load_workbook(args.xlsx, data_only=True)

    ws = wb[args.shares_sheet]
    header = [str(c).strip() if c else "" for c in next(ws.iter_rows(min_row=1, max_row=1, values_only=True))]
    code_col = header.index("PCON24CD")
    name_col = header.index("Seat")
    share_cols = {}
    for i, name in enumerate(header):
        if name.lower().startswith("mean_"):
            party_key = name[5:].lower()
            if party_key in PARTY_MAP:
                share_cols[PARTY_MAP[party_key]] = i

    shares = {}  # (pcon_code, party) -> share
    seat_names = {}
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, values_only=True):
        code = row[code_col]
        if not code:
            continue
        seat_names[code] = row[name_col]
        for party, i in share_cols.items():
            val = row[i]
            if isinstance(val, (int, float)) and val:
                shares[(code, party)] = val

    win_probs = {}
    wpws = wb[args.winprob_sheet]
    wp_header = [str(c).strip() if c else "" for c in next(wpws.iter_rows(min_row=1, max_row=1, values_only=True))]
    wp_code_col = wp_header.index("PCON24CD")
    wp_party_cols = {}
    for i, name in enumerate(wp_header):
        key = name.lower()
        if key in PARTY_MAP:
            wp_party_cols[PARTY_MAP[key]] = i
    for row in wpws.iter_rows(min_row=2, max_row=wpws.max_row, values_only=True):
        code = row[wp_code_col]
        if not code:
            continue
        for party, i in wp_party_cols.items():
            val = row[i]
            if isinstance(val, (int, float)) and val:
                win_probs[(code, party)] = round(val * 100, 2)

    out_rows = []
    for (code, party), share in shares.items():
        out_rows.append({
            "pcon_code": code, "pcon_name": seat_names[code], "party": party,
            "vote_share_pct": round(share, 3), "win_probability_pct": win_probs.get((code, party), ""),
        })

    seats_with_data = set(code for code, _ in shares)
    empty_seats = [(code, name) for code, name in seat_names.items() if code not in seats_with_data]
    if empty_seats:
        print(f"  WARNING: {len(empty_seats)} seats have a row in the source but no non-zero party "
              f"shares at all (a genuine gap in Survation's own file, not a parsing issue): {empty_seats}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["pcon_code", "pcon_name", "party", "vote_share_pct", "win_probability_pct"])
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"Wrote {len(out_rows)} party rows across {len(seats_with_data)} seats (of {len(seat_names)} listed) to {out_path}")


if __name__ == "__main__":
    sys.exit(main())
