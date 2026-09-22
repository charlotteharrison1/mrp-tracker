"""
Download a LEAP results CSV for one council/year and load it into
local_election_events + local_election_ward_results. Also computes the
council-level summary (seats won, votes, vote share per party) directly
from the ward data and stores it in local_election_council_summary.

CONFIRMED CSV FORMAT (no header row):
  council_name, ward_name, "", ward_ons_code, candidate_name, party, votes, status
  e.g.
  "Westminster","Abbey Road","","E05013792","Amanda Langford","C",1241,"Elected"

Usage (single council/year):
    python scripts/03_fetch_leap_results.py --council-id 20 --year 2022 \
        --la-code E09000033 --la-name Westminster --boundary-year 2022

Usage (bulk, from the index produced by 02_fetch_leap_council_index.py):
    python scripts/03_fetch_leap_results.py --from-index --years 2021 2022 2023 2024 2025

Notes:
  * election_type is NOT reliably inferable from the CSV alone (LEAP doesn't
    encode "all-out" vs "thirds" directly). This script leaves it as
    'unknown'; fill it in later from the results-page text (which does say
    "Whole council up for election..." vs partial) if you need that field —
    see docs/data_notes.md.
  * vote_share_pct is computed per ward as votes / total votes cast in that
    ward (i.e. across all candidates), which is standard for FPTP multi-member
    wards — NOT divided by seats.
"""
import argparse
import csv as csv_module
import io
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import requests
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "uk_elections.db"
INDEX_CSV = ROOT / "data" / "leap_council_index.csv"
# The site's proxy 502s requests carrying the default python-requests UA.
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; uk-elections-tracker/1.0)"}


def fetch_and_load_one(con, council_id, year, la_code, la_name, boundary_year, csv_url=None, page_url=None):
    csv_url = csv_url or f"https://www.andrewteale.me.uk/leap/results/{year}/{council_id}.csv"
    page_url = page_url or (csv_url[:-4] + "/" if csv_url.endswith(".csv") else csv_url)
    resp = requests.get(csv_url, headers=HEADERS, timeout=60)
    if resp.status_code != 200 or not resp.text.strip():
        print(f"  [skip] no data at {csv_url} ({resp.status_code})")
        return

    reader = csv_module.reader(io.StringIO(resp.text))
    rows = list(reader)
    if not rows:
        print(f"  [skip] empty CSV at {csv_url}")
        return

    cur = con.cursor()
    election_date = f"{year}-05-01"  # LEAP doesn't give exact date in the CSV; refine manually if needed
    cur.execute(
        """INSERT INTO local_election_events (la_code, la_name, leap_council_id, election_date,
                                                election_year, election_type, boundary_year, source_url, page_url)
           VALUES (?, ?, ?, ?, ?, 'unknown', ?, ?, ?)
           ON CONFLICT(la_code, election_date) DO UPDATE SET source_url=excluded.source_url, page_url=excluded.page_url
           """,
        (la_code, la_name, str(council_id), election_date, year, boundary_year, csv_url, page_url),
    )
    con.commit()
    election_id = cur.execute(
        "SELECT election_id FROM local_election_events WHERE la_code=? AND election_date=?",
        (la_code, election_date),
    ).fetchone()[0]

    # Clear any previous load for this election (idempotent re-runs)
    cur.execute("DELETE FROM local_election_ward_results WHERE election_id=?", (election_id,))

    ward_totals = defaultdict(int)          # (ward_code) -> total votes cast
    parsed_rows = []
    for row in rows:
        if len(row) < 8:
            continue
        _council, ward_name, _blank, ward_code, candidate, party, votes, status = row[:8]
        votes = int(votes) if votes.strip().isdigit() else None
        elected = 1 if status.strip().lower() == "elected" else 0
        ward_code = ward_code.strip() or None
        parsed_rows.append((ward_name.strip(), ward_code, candidate.strip(), party.strip(), votes, elected))
        if votes:
            ward_totals[ward_name.strip()] += votes

    insert_rows = []
    for ward_name, ward_code, candidate, party, votes, elected in parsed_rows:
        total = ward_totals.get(ward_name, 0)
        share = round(100 * votes / total, 2) if votes and total else None
        seats_avail = sum(1 for w, _, _, _, _, e in parsed_rows if w == ward_name and e)
        insert_rows.append((election_id, ward_code, ward_name, boundary_year,
                             max(seats_avail, 1), candidate, party, votes, share, elected))

    cur.executemany(
        """INSERT INTO local_election_ward_results
           (election_id, ward_code, ward_name_raw, boundary_year, seats_available,
            candidate_name, party, votes, vote_share_pct, elected)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        insert_rows,
    )

    # Council-level summary, computed from the ward data itself
    party_votes = defaultdict(int)
    party_seats = defaultdict(int)
    total_votes = 0
    for _, _, _, party, votes, elected in parsed_rows:
        if votes:
            party_votes[party] += votes
            total_votes += votes
        if elected:
            party_seats[party] += 1

    cur.execute("DELETE FROM local_election_council_summary WHERE election_id=?", (election_id,))
    summary_rows = [
        (election_id, party, party_seats.get(party, 0), party_votes.get(party, 0),
         round(100 * party_votes.get(party, 0) / total_votes, 2) if total_votes else None)
        for party in set(list(party_votes) + list(party_seats))
    ]
    cur.executemany(
        """INSERT INTO local_election_council_summary
           (election_id, party, seats_won, votes, vote_share_pct) VALUES (?, ?, ?, ?, ?)""",
        summary_rows,
    )
    con.commit()
    print(f"  loaded {la_name} {year}: {len(insert_rows)} candidate rows, "
          f"{len(ward_totals)} wards, {sum(party_seats.values())} seats declared")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--council-id")
    parser.add_argument("--year", type=int)
    parser.add_argument("--la-code")
    parser.add_argument("--la-name")
    parser.add_argument("--boundary-year", type=int)
    parser.add_argument("--from-index", action="store_true",
                         help="bulk load every LEAP-hosted row in data/leap_council_index.csv")
    parser.add_argument("--years", nargs="*", type=int, help="restrict --from-index to these years")
    args = parser.parse_args()

    con = sqlite3.connect(DB_PATH)

    if args.from_index:
        if not INDEX_CSV.exists():
            print("Run 02_fetch_leap_council_index.py first.")
            return 1
        with INDEX_CSV.open(encoding="utf-8") as f:
            index_rows = [r for r in csv_module.DictReader(f) if r["is_leap_hosted"] == "True"]
        if args.years:
            index_rows = [r for r in index_rows if int(r["year"]) in args.years]

        print(f"Loading {len(index_rows)} council/year combinations...")
        for r in tqdm(index_rows):
            # la_code is unknown from the index alone; leave blank and join to
            # `wards`/ONS LAD names later, or pass a lookup CSV — see README.
            fetch_and_load_one(
                con, council_id=r["leap_council_id"], year=int(r["year"]),
                la_code=f"LEAP-{r['leap_council_id']}", la_name=r["council_name"],
                boundary_year=int(r["year"]), csv_url=r["csv_url"], page_url=r["result_url"],
            )
    else:
        if not all([args.council_id, args.year, args.la_code, args.la_name, args.boundary_year]):
            parser.error("either --from-index, or all of --council-id --year --la-code --la-name --boundary-year")
        fetch_and_load_one(con, args.council_id, args.year, args.la_code, args.la_name, args.boundary_year)

    con.close()


if __name__ == "__main__":
    sys.exit(main())
