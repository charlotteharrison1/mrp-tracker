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

Column positions are NOT hardcoded — they're read from the header row each
time, because they move between releases (the Jul 2026 file has a "Restore"
column the Apr 2026 file doesn't have at all, since Restore Britain hadn't
registered as a separate line in the model yet). Only column NAMES are
assumed stable. If a release adds a party name this script doesn't
recognise, it's carried through verbatim (see OTHER_PARTY_COLS handling)
rather than silently dropped — check the printed column list either way.

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

PARTY_MAP = {"CON": "Con", "LAB": "Lab", "LIB": "LD", "Reform": "RUK", "Green": "Green"}
# Columns with a known, fixed meaning that aren't a simple party vote share —
# skipped when scanning "everything else" in the sheet.
NON_PARTY_COLS = {"seat name", "electorate", "turnout", "predicted winner (with tv)",
                   "predicted winner (no tv)", "winner 2024"}
SPECIAL_PARTY_COLS = {"snp/\nplaid": "SNP/Plaid", "minor party": "Minor", "indep/ other": "Ind/Other"}


def find_header_row(ws):
    """The header row number is stable at 19 in both releases seen so far,
    but scan for it (a row containing both 'Seat Name' and 'CON') rather
    than trust that forever."""
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=30, values_only=True), start=1):
        cells = [str(c).strip() if c else "" for c in row]
        if "Seat Name" in cells and "CON" in cells:
            return i, cells
    raise ValueError("Could not find a header row containing 'Seat Name' and 'CON' in the first 30 rows")


def build_column_map(cells):
    """Two side-by-side tables (With TV / No TV) share column NAMES but not
    positions — find the second 'Seat Name' to split them, then map each
    table's columns by name rather than fixed index."""
    first_seat_col = cells.index("Seat Name")
    second_seat_col = cells.index("Seat Name", first_seat_col + 1)

    def slice_cols(start, end):
        out = {}
        for i in range(start, end):
            name = cells[i].strip().lower()
            if name:
                out[name] = i
        return out

    with_tv = slice_cols(first_seat_col, second_seat_col)
    no_tv = slice_cols(second_seat_col, len(cells))
    return with_tv, no_tv


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

    con = sqlite3.connect(DB_PATH)
    nation_lookup = load_nation_lookup(con)
    con.close()

    wb = openpyxl.load_workbook(args.xlsx, data_only=True)
    ws = wb[args.sheet]

    header_row_num, cells = find_header_row(ws)
    with_tv, no_tv = build_column_map(cells)
    cols = with_tv if args.with_tv else no_tv

    # Classify every column once: known party, SNP/Plaid, catch-all bucket,
    # a genuinely new party name we haven't seen before, or a non-party
    # field (seat name, electorate, ...) to ignore.
    known_lower = {k.lower(): v for k, v in PARTY_MAP.items()}
    other_party_cols = {}
    for name, i in cols.items():
        if name == "seat name" or name in NON_PARTY_COLS or name in known_lower or name in SPECIAL_PARTY_COLS:
            continue
        other_party_cols[name.strip().title()] = i
    if other_party_cols:
        print(f"  Party columns not in the fixed map, carried through verbatim: {list(other_party_cols.keys())}")

    out_rows = []
    n_seats = 0
    for row in ws.iter_rows(min_row=header_row_num + 1, max_row=ws.max_row, values_only=True):
        seat_name = row[cols["seat name"]]
        if not seat_name:
            continue
        n_seats += 1
        nation = nation_lookup(seat_name)

        for src_party, our_party in PARTY_MAP.items():
            share = row[cols[src_party.lower()]]
            if share:
                out_rows.append({"pcon_code": "", "pcon_name": seat_name, "party": our_party,
                                  "vote_share_pct": round(share * 100, 3), "win_probability_pct": ""})

        snp_plaid = row[cols["snp/\nplaid"]]
        if snp_plaid:
            party = "SNP" if nation == "Scotland" else ("PC" if nation == "Wales" else None)
            if party is None:
                print(f"  WARNING: {seat_name} has SNP/Plaid={snp_plaid} but nation={nation!r} — skipping, check manually")
            else:
                out_rows.append({"pcon_code": "", "pcon_name": seat_name, "party": party,
                                  "vote_share_pct": round(snp_plaid * 100, 3), "win_probability_pct": ""})

        for src_name, our_party in [("minor party", "Minor"), ("indep/ other", "Ind/Other")]:
            share = row[cols[src_name]]
            if share:
                out_rows.append({"pcon_code": "", "pcon_name": seat_name, "party": our_party,
                                  "vote_share_pct": round(share * 100, 3), "win_probability_pct": ""})

        for our_party, i in other_party_cols.items():
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
    print("(scenario: " + ("WITH tactical voting" if args.with_tv else "NO tactical voting (raw model)") + ")")


if __name__ == "__main__":
    sys.exit(main())
