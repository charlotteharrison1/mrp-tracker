"""
Prep helper (not part of the numbered pipeline): converts a Focaldata MRP
release's "Seat results" sheet into the CSV shape 04_ingest_mrp_release.py
expects. Confirmed against the 2025-02-03 Focaldata/Hope Not Hate release
(a public Google Sheet, exported to xlsx).

SHEET SHAPE: a two-row header (row 1 says "MRP vote shares" / "Change
since 2024" as merged-cell section labels, row 2 has the actual party
codes) followed by data from row 4. Real data columns:
  A=Seat ID (pcon_code), B=Seat name, C=Winner, then E-L = MRP vote
  shares for LAB/CON/RFM/LDM/GRN/SNP/PCY/OTH (fractions, blank/None
  where a party isn't standing e.g. SNP outside Scotland) — column L
  ("Total", tiny values like 5e-6) and everything from column O onward
  ("Change since 2024") are ignored, not party data.

Usage:
    python scripts/prep_focaldata_xlsx.py --file /path/to/focaldata_mrp.xlsx --out data/mrp_prepped/focaldata_2025-02-03.csv
"""
import argparse
import csv
import sys
from pathlib import Path

import openpyxl

PARTY_MAP = {"LAB": "Lab", "CON": "Con", "RFM": "RUK", "LDM": "LD",
             "GRN": "Green", "SNP": "SNP", "PCY": "PC", "OTH": "Other"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--sheet", default="Seat results")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    wb = openpyxl.load_workbook(args.file, data_only=True)
    ws = wb[args.sheet]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]

    # The party codes (LAB/CON/RFM/...) appear TWICE in row 2 - once under
    # the "MRP vote shares" section, again under "Change since 2024" -
    # bound the search to before the second section starts (row 1 has the
    # section labels) or a naive column->party dict silently keeps the
    # LAST (wrong, "change since 2024") occurrence of each code instead
    # of the first (found 2026-09-23: every row came out as the swing
    # since 2024, not the actual vote share, e.g. Lab -7.41 instead of
    # ~33%).
    section_row = rows[0]
    change_section_start = next((i for i, v in enumerate(section_row) if v == "Change since 2024"), len(section_row))
    party_header_row = rows[1][:change_section_start]
    party_cols = {}
    for i, v in enumerate(party_header_row):
        if v in PARTY_MAP and PARTY_MAP[v] not in party_cols:
            party_cols[PARTY_MAP[v]] = i

    out_rows = []
    n_seats = 0
    for row in rows[3:]:
        code, name = row[0], row[1]
        if not code or not name:
            continue
        n_seats += 1
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

    print(f"Wrote {len(out_rows)} party rows across {n_seats} seats to {out_path}")


if __name__ == "__main__":
    sys.exit(main())
