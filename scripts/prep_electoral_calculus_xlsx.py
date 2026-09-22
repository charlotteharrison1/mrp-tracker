"""
Prep helper (not part of the numbered pipeline): converts an Electoral
Calculus "DataTables_*.xlsx" release into the CSV shape
04_ingest_mrp_release.py expects. Electoral Calculus publishes a "Seats"
sheet with two side-by-side scenarios (with/without tactical voting) and a
combined SNP/Plaid column — this resolves that column per-seat by nation
(needs the DB already populated with constituencies, i.e. after Phase 1).

Loads the "No TV" (raw model, no tactical-voting adjustment) columns by
default — the tactically-adjusted variant exists specifically to correct
for the small-party-vote-leaks-to-the-viable-challenger effect, so it's
the less useful one for comparing what the demographic model itself
predicted against what actually happened. Pass --with-tv to use the other
scenario instead.

GB-only releases (Electoral Calculus doesn't model Northern Ireland) will
produce fewer than 650 rows — that's expected, not a bug.

Usage:
    python scripts/prep_electoral_calculus_xlsx.py --xlsx /path/to/DataTables_VIJul2026.xlsx --out data/mrp_prepped/ec_2026-07-08.csv
"""
import argparse
import csv
import sqlite3
import sys
from pathlib import Path

import openpyxl
from rapidfuzz import process, fuzz

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "uk_elections.db"
NATION_MATCH_THRESHOLD = 80

# With-TV columns start at index 1 (Seat Name); No-TV mirror starts at index 16.
COLS_WITH_TV = {
    "seat_name": 1, "electorate": 2, "CON": 3, "LAB": 4, "LIB": 5, "Reform": 6,
    "Green": 7, "Restore": 8, "SNP/Plaid": 9, "Minor Party": 10, "Indep/Other": 11,
}
COLS_NO_TV = {
    "seat_name": 16, "CON": 17, "LAB": 18, "LIB": 19, "Reform": 20,
    "Green": 21, "Restore": 22, "SNP/Plaid": 23, "Minor Party": 24, "Indep/Other": 25,
}

PARTY_MAP = {"CON": "Con", "LAB": "Lab", "LIB": "LD", "Reform": "RUK", "Green": "Green"}
HEADER_ROW = 19
DATA_START_ROW = 20


def load_nation_lookup(con):
    rows = con.execute("SELECT pcon_name, nation FROM constituencies").fetchall()
    exact = {name: nation for name, nation in rows}
    names = [name for name, _ in rows]

    def lookup(seat_name):
        if seat_name in exact:
            return exact[seat_name]
        # WRatio alone confuses near-duplicates ('Devon South West' scores
        # equally against 'South Devon' and 'South West Devon') — tie-break
        # with token_sort_ratio. See 04_ingest_mrp_release.py's best_match
        # and docs/data_notes.md 2026-09-22.
        results = process.extract(seat_name, names, scorer=fuzz.WRatio, limit=5)
        if not results:
            return None
        top_score = results[0][1]
        contenders = [r for r in results if r[1] >= top_score - 3]
        if len(contenders) > 1:
            contenders.sort(key=lambda r: fuzz.token_sort_ratio(seat_name, r[0]), reverse=True)
        match, score = contenders[0][0], top_score
        if score >= NATION_MATCH_THRESHOLD:
            print(f"  (nation lookup) fuzzy-matched {seat_name!r} -> {match!r} (score {score})")
            return exact[match]
        return None

    return lookup


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--xlsx", required=True)
    parser.add_argument("--sheet", default="Seats")
    parser.add_argument("--out", required=True)
    parser.add_argument("--with-tv", action="store_true", help="use the tactically-adjusted scenario instead of the raw model")
    args = parser.parse_args()

    cols = COLS_WITH_TV if args.with_tv else COLS_NO_TV

    con = sqlite3.connect(DB_PATH)
    nation_lookup = load_nation_lookup(con)
    con.close()

    wb = openpyxl.load_workbook(args.xlsx, data_only=True)
    ws = wb[args.sheet]

    out_rows = []
    n_seats = 0
    for row in ws.iter_rows(min_row=DATA_START_ROW, max_row=ws.max_row, values_only=True):
        seat_name = row[cols["seat_name"]]
        if not seat_name:
            continue
        n_seats += 1
        nation = nation_lookup(seat_name)

        for src_party, our_party in PARTY_MAP.items():
            share = row[cols[src_party]]
            if share:
                out_rows.append({"pcon_code": "", "pcon_name": seat_name, "party": our_party,
                                  "vote_share_pct": round(share * 100, 3), "win_probability_pct": ""})

        snp_plaid = row[cols["SNP/Plaid"]]
        if snp_plaid:
            party = "SNP" if nation == "Scotland" else ("PC" if nation == "Wales" else None)
            if party is None:
                print(f"  WARNING: {seat_name} has SNP/Plaid={snp_plaid} but nation={nation!r} — skipping, check manually")
            else:
                out_rows.append({"pcon_code": "", "pcon_name": seat_name, "party": party,
                                  "vote_share_pct": round(snp_plaid * 100, 3), "win_probability_pct": ""})

        for src_party, our_party in [("Restore", "Restore"), ("Minor Party", "Minor"), ("Indep/Other", "Ind/Other")]:
            share = row[cols[src_party]]
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
    print("(scenario: " + ("WITH tactical voting" if args.with_tv else "NO tactical voting (raw model)") + ")")


if __name__ == "__main__":
    sys.exit(main())
