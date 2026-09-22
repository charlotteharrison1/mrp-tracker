"""
Prep helper (not part of the numbered pipeline): extracts the constituency
vote-share table from Best for Britain's Spring 2023 MRP PDF ("...Data -
All_Scenarios.pdf"). Unlike every other MRP source in this project, this
one only publishes as a PDF — no CSV/xlsx. Uses pdfplumber's table
extraction rather than transcribing by hand.

STRUCTURE: the PDF has 4 back-to-back constituency tables, one per
scenario (Baseline MRP / Reform UK Stands Down / DK's reallocated by
Education / Baseline with DK seats reallocated), each ~12 pages, with no
explicit page-range markers — found by scanning for where the seat
sequence restarts from "Aberafan Porthcawl". Defaults to the Baseline MRP
scenario (the one directly comparable to every other release's "raw
model" numbers); use --start-page/--end-page for a different scenario.

PDF TEXT-WRAP CORRUPTION — this is the hard part, and why this script
does NOT trust raw cell content the way the xlsx-based prep scripts do:
  1. A long winner/runner_up value ("scottish_national_party") wraps
     across 2-3 cells, and its tail ("rty ") bleeds into the START of the
     next cell, contaminating the Labour vote-share cell (e.g. "rty
     23.1%" instead of "23.1%"). Column COUNT and the value's own digits
     are still intact — fixed by regex-extracting the trailing percentage
     rather than parsing the whole cell.
  2. A long seat name ("Dumfriesshire, Clydesdale and Tweeddale") wraps
     onto a second line WITHIN its own cell, and pdfplumber splits that
     into what looks like two separate cells — "umfriesshire, Clydesdale
     and Tweedda" in cell 0, "le Scotland" in cell 1. Fixed by checking
     whether cell 1 looks like a real region name; if not, the seat name
     continues into it.
  3. Given how easy it is for a wrapping bug to silently misalign a row
     WITHOUT triggering a parse error (the cell still contains something
     that parses as a valid percentage, just from the wrong place), every
     extracted seat is validated at the end: fuzzy-matched against the
     real constituency list, and its shares summed and checked against a
     plausible range. Anything that fails either check is dropped with a
     loud warning rather than silently ingested — see docs/data_notes.md.

Usage:
    python scripts/prep_bestforbritain_pdf.py --pdf /path/to/All_Scenarios.pdf --out data/mrp_prepped/bfb_2023-06-07.csv
"""
import argparse
import csv
import re
import sqlite3
import sys
from pathlib import Path

import pdfplumber
from rapidfuzz import process, fuzz

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "uk_elections.db"

PARTY_COLS = {4: "Lab", 5: "LD", 6: "Con", 7: "SNP", 8: "RUK", 9: "PC", 10: "Green"}
# The exact labels this PDF uses (confirmed by scanning every region cell
# across the Baseline MRP table) — notably "Eastern", not "East of
# England". Getting this list wrong was a real bug: rows in a region not
# on the list looked "contaminated" and triggered the wrap-repair path
# even when they were already clean, actively corrupting them.
KNOWN_REGIONS = {
    "wales", "scotland", "south east", "west midlands", "east midlands", "north west",
    "yorkshire and the humber", "eastern", "london", "south west", "north east",
    "northern ireland",
}
PCT_RE = re.compile(r"(-?\d+\.?\d*)\s*%\s*$")
SEAT_NAME_SUFFIX_RE = re.compile(r"\s+(BC|CC|CBC)$")


def extract_pct(cell):
    if not cell:
        return None
    m = PCT_RE.search(cell.strip())
    return float(m.group(1)) if m else None


def best_match(query, names):
    """Same tie-break as 04_ingest_mrp_release.py's best_match(): plain
    WRatio can't tell 'Glasgow South' from 'Glasgow South West' apart (one
    is a substring of the other), and silently prefers whichever comes
    first — within 3 points of the top score, re-rank by token_sort_ratio,
    which requires the same token set. See docs/data_notes.md 2026-09-22."""
    results = process.extract(query, names, scorer=fuzz.WRatio, limit=5)
    if not results:
        return None, 0
    top_score = results[0][1]
    contenders = [r for r in results if r[1] >= top_score - 3]
    if len(contenders) > 1:
        contenders.sort(key=lambda r: fuzz.token_sort_ratio(query, r[0]), reverse=True)
    return contenders[0][0], top_score


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--start-page", type=int, default=2, help="0-indexed page the scenario table starts on")
    parser.add_argument("--end-page", type=int, default=13, help="0-indexed page the scenario table ends on (inclusive)")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    con = sqlite3.connect(DB_PATH)
    real_names = [r[0] for r in con.execute("SELECT pcon_name FROM constituencies")]
    con.close()

    seats = {}  # seat_name -> {party: share}
    with pdfplumber.open(args.pdf) as pdf:
        for page_num in range(args.start_page, args.end_page + 1):
            tables = pdf.pages[page_num].extract_tables()
            if not tables:
                continue
            for row in tables[0]:
                if not row[0] or row[0] == "westminster_constituency" or len(row) <= max(PARTY_COLS):
                    continue
                seat_name = row[0].strip()
                region_cell = (row[1] or "").strip().lower()
                if region_cell not in KNOWN_REGIONS and len(row) > 1:
                    # seat name wrapped onto a second line and bled into cell 1 —
                    # region name is whatever trails after the seat-name fragment
                    seat_name = (seat_name + (row[1] or "")).strip()
                    for known in KNOWN_REGIONS:
                        idx = seat_name.lower().rfind(known)
                        if idx != -1:
                            seat_name = seat_name[:idx].strip()
                            break
                seat_name = SEAT_NAME_SUFFIX_RE.sub("", seat_name)

                shares = {}
                for i, our_party in PARTY_COLS.items():
                    val = extract_pct(row[i])
                    if val:
                        shares[our_party] = val
                if shares:
                    seats[seat_name] = shares

    # Validate: fuzzy-match every seat name, and sanity-check its share total.
    matched = {}  # real constituency name -> list of (source seat_name, shares)
    rejected = []
    for seat_name, shares in seats.items():
        match, score = best_match(seat_name, real_names)
        total = sum(shares.values())
        problems = []
        if score < 90:
            problems.append(f"best name match {match!r} only scores {score}")
        if not (70 <= total <= 100):
            problems.append(f"shares sum to {total:.1f}% (expected roughly 70-100, since 'Other' isn't in this table)")
        if problems:
            rejected.append((seat_name, problems))
            continue
        matched.setdefault(match, []).append((seat_name, shares))

    # Safety net: two different source rows landing on the same real seat
    # means at least one of them is wrong (can't tell which) — this is
    # exactly the failure that slipped through here once already before
    # best_match() got its tie-break fix. Reject both rather than guess.
    out_rows = []
    for real_name, candidates in matched.items():
        if len(candidates) > 1:
            rejected.append((real_name, [f"{len(candidates)} different source rows all matched here: "
                                          f"{[c[0] for c in candidates]} — can't tell which is right"]))
            continue
        seat_name, shares = candidates[0]
        for party, share in shares.items():
            out_rows.append({"pcon_code": "", "pcon_name": real_name, "party": party,
                              "vote_share_pct": share, "win_probability_pct": ""})

    if rejected:
        print(f"  REJECTED {len(rejected)} seats that failed validation (not written to the output CSV):")
        for name, problems in rejected:
            print(f"    {name!r}: {'; '.join(problems)}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["pcon_code", "pcon_name", "party", "vote_share_pct", "win_probability_pct"])
        writer.writeheader()
        writer.writerows(out_rows)

    n_validated = sum(1 for c in matched.values() if len(c) == 1)
    print(f"Wrote {len(out_rows)} party rows across {n_validated} validated seats "
          f"(of {len(seats)} extracted) to {out_path}")


if __name__ == "__main__":
    sys.exit(main())
