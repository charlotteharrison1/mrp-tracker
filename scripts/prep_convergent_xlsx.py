"""
Prep helper (not part of the numbered pipeline): converts a Convergent
Opinion MRP release's "Vote Shares by Seat" sheet into the CSV shape
04_ingest_mrp_release.py expects. Confirmed against the 2026-07-30
release (convergent-opinion.com polling archive).

SHEET SHAPE: a two-row header (row 1 has section labels "Constituency" /
"Modelled vote share" / "GE2024 result", row 2 has the real column
names), data from row 3. Columns: Code, Name, Winner, then the MRP vote
shares (Labour, Reform, Conservative, Green, Lib Dem, SNP, Plaid Cymru,
Other), then "GE24 Winner" plus a couple of GE2024 result columns -
those last ones are the ACTUAL result, not this release's prediction,
and are excluded (we already have the real GE2024 result from the
official source; see the same exclusion in prep_yougov_xlsx.py).

Usage:
    python scripts/prep_convergent_xlsx.py --file /path/to/convergent_mrp.xlsx --out data/mrp_prepped/convergent_2026-07-30.csv
"""
import argparse
import csv
import sys
from pathlib import Path

import openpyxl

PARTY_MAP = {
    "Labour": "Lab", "Reform": "RUK", "Conservative": "Con", "Green": "Green",
    "Lib Dem": "LD", "SNP": "SNP", "Plaid Cymru": "PC", "Other": "Other",
}
# Only the first occurrence of each name is real MRP data - "Labour" and
# "Reform" repeat verbatim in the GE2024-result columns at the end of the
# row, same trap as Focaldata's repeated party codes (see
# prep_focaldata_xlsx.py) - stop scanning once the GE2024 section starts.
STOP_AT = "GE24 Winner"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--sheet", default="Vote Shares by Seat")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    wb = openpyxl.load_workbook(args.file, data_only=True)
    ws = wb[args.sheet]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]

    header = rows[1]
    code_col, name_col = 0, 1
    stop_i = header.index(STOP_AT) if STOP_AT in header else len(header)
    party_cols = {PARTY_MAP[h]: i for i, h in enumerate(header[:stop_i]) if h in PARTY_MAP}

    out_rows = []
    n_seats = 0
    for row in rows[2:]:
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
