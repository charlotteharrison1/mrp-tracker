"""
Fetches ward-level 2026 local election results from Wikipedia for every
council resolved in data/wikipedia_2026_council_index.csv, filling the
gap left by LEAP (which only has 20 of 136 councils transcribed for 2026
so far — see docs/data_notes.md 2026-09-22).

Uses the MediaWiki API's action=parse endpoint (not raw page scraping,
which trips Wikipedia's bot detection within 2-3 rapid requests — see
09_fetch_wikipedia_council_index.py) to get each page's rendered HTML,
then extracts ward-by-ward result tables from it.

TABLE STRUCTURE (confirmed consistent across a single-member council
(Oxford) and a multi-member one (Camden, 3-seat wards)): under an
<h2>Ward results</h2> heading, each ward is an <h3> (occasionally <h4>)
heading immediately followed by a wikitable. Real candidate rows have
exactly 6 cells (a blank party-colour swatch + party/candidate/votes/
%/±%) — the header, "Turnout", "Majority", and the trailing hold/gain
summary rows all have a different cell count, which is what separates
real data rows from the rest. The winning candidate(s) are marked by a
<b> (bold) tag around their name — confirmed correct for multi-member
wards too (exactly N candidates are bold in an N-seat ward), so
seats_available is inferred as the count of bold rows, not assumed to be 1.

Usage:
    python scripts/10_fetch_wikipedia_local_results.py [--limit N] [--only "Council Name"]
"""
import argparse
import sqlite3
import sys
import time
import csv
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from rapidfuzz import process, fuzz

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "uk_elections.db"
INDEX_CSV = ROOT / "data" / "wikipedia_2026_council_index.csv"
API_URL = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "uk-elections-tracker/1.0 (research project)"}
ELECTION_DATE = "2026-05-07"
BOUNDARY_YEAR = 2024
WARD_MATCH_THRESHOLD = 85

PARTY_MAP = {
    "conservative": "C", "labour": "Lab", "labour co-op": "Lab", "labour and co-operative": "Lab",
    "liberal democrats": "LD", "green": "Grn", "green party": "Grn",
    "reform": "RUK", "reform uk": "RUK", "independent": "Ind", "independents": "Ind",
    "workers party": "Workers", "workers party of britain": "Workers",
    "scottish national party": "SNP", "snp": "SNP", "plaid cymru": "PC",
    "trade unionist and socialist coalition": "TUSC", "tusc": "TUSC", "ukip": "UKIP",
}


def party_code(name):
    return PARTY_MAP.get(name.strip().lower(), name.strip())


def best_match(query, names):
    """Same tie-break as everywhere else in this project — see
    docs/data_notes.md 2026-09-22 (the 'Devon South West' entry)."""
    results = process.extract(query, names, scorer=fuzz.WRatio, limit=5)
    if not results:
        return None, 0
    top_score = results[0][1]
    contenders = [r for r in results if r[1] >= top_score - 3]
    if len(contenders) > 1:
        contenders.sort(key=lambda r: fuzz.token_sort_ratio(query, r[0]), reverse=True)
    return contenders[0][0], top_score


def fetch_page_html(session, title):
    for attempt in range(5):
        resp = session.get(API_URL, params={
            "action": "parse", "page": title, "prop": "text", "format": "json", "redirects": 1,
        }, timeout=30)
        if resp.status_code == 429:
            time.sleep(2 ** attempt)
            continue
        data = resp.json()
        if "error" in data:
            return None
        return data["parse"]["text"]["*"]
    return None


def detect_election_type(soup):
    text = soup.get_text().lower()
    if "one third" in text or "by thirds" in text or "thirds of the council" in text:
        return "thirds"
    if "half of the council" in text or "by halves" in text:
        return "halves"
    if "whole council" in text or "all seats" in text or "all-out" in text:
        return "all-out"
    return "unknown"


def parse_ward_tables(html):
    """Finds ward result tables STRUCTURALLY rather than by heading text —
    the parent heading varies a lot across councils ('Ward results',
    'Results by ward', plain 'Results' that coexists with an unrelated
    'Results summary' heading, or 'Candidates' with no ward-ish word at
    all) and hardcoding each variant is a losing game. Every ward table
    seen so far is a <h3>/<h4> immediately followed by a table whose
    header row contains both 'Party' and 'Candidate' — that combination
    doesn't occur on the 'Incumbents'/'Council composition'/infobox
    tables elsewhere on the same pages, so it's a reliable, self-
    validating signal instead of a heading-text guess."""
    soup = BeautifulSoup(html, "lxml")
    election_type = detect_election_type(soup)

    wards = []
    seen_tables = set()
    for heading in soup.find_all(["h3", "h4"]):
        table = heading.find_next("table")
        if not table or id(table) in seen_tables:
            continue
        header_row = table.find("tr")
        if not header_row:
            continue
        header_text = [c.get_text(strip=True) for c in header_row.find_all(["th", "td"])]
        if "Party" not in header_text or "Candidate" not in header_text:
            continue
        # Column SET varies (some councils' tables drop the "±%" swing
        # column entirely, e.g. Bradford has only Party/Candidate/Votes/%)
        # — map columns by the header's own text instead of assuming a
        # fixed width. Data rows have one extra leading cell (a colour
        # swatch, blank text) that the header row doesn't have, hence +1.
        party_i = header_text.index("Party") + 1
        cand_i = header_text.index("Candidate") + 1
        votes_i = header_text.index("Votes") + 1 if "Votes" in header_text else None
        pct_i = header_text.index("%") + 1 if "%" in header_text else None
        expected_len = len(header_text) + 1
        if votes_i is None or pct_i is None:
            continue  # can't get a usable row without these — skip this table
        seen_tables.add(id(table))
        ward_name = heading.get_text(strip=True)
        rows = []
        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if len(cells) != expected_len:
                continue
            party_text = cells[party_i].get_text(strip=True)
            if party_text == "Party":
                continue
            cand_text = cells[cand_i].get_text(strip=True).rstrip("*").strip()
            votes_text = cells[votes_i].get_text(strip=True).replace(",", "")
            pct_text = cells[pct_i].get_text(strip=True)
            if not cand_text or not party_text:
                continue
            elected = bool(cells[cand_i].find("b"))
            votes = int(votes_text) if votes_text.isdigit() else None
            try:
                share = float(pct_text)
            except ValueError:
                share = None
            rows.append({"party": party_code(party_text), "candidate": cand_text,
                          "votes": votes, "share": share, "elected": elected})
        if rows:
            wards.append((ward_name, rows))
    return wards, election_type


def load_wards_for_la(con, la_code):
    rows = con.execute(
        "SELECT ward_code, ward_name FROM wards WHERE la_code=? AND boundary_year=?",
        (la_code, BOUNDARY_YEAR),
    ).fetchall()
    return {name: code for code, name in rows}, [name for _, name in rows]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="only process the first N councils (for testing)")
    parser.add_argument("--only", help="only process the council with this exact display_name")
    args = parser.parse_args()

    con_precheck = sqlite3.connect(DB_PATH)
    already_covered = set(r[0] for r in con_precheck.execute(
        "SELECT la_code FROM local_election_events WHERE election_year=2026 AND la_code NOT LIKE 'LEAP-%'"
    ))
    con_precheck.close()

    with INDEX_CSV.open(encoding="utf-8") as f:
        index_rows = [r for r in csv.DictReader(f) if r["election_page_found"] == "True" and r["la_code"]]
    # dedupe by la_code — a couple of display_names appear twice with the
    # same real council (e.g. a duplicate row from a separate mayoral table)
    seen_la = set()
    councils = []
    skipped_covered = 0
    for r in index_rows:
        if r["la_code"] in seen_la:
            continue
        seen_la.add(r["la_code"])
        if r["la_code"] in already_covered:
            skipped_covered += 1
            continue
        councils.append(r)
    if skipped_covered:
        print(f"Skipping {skipped_covered} councils already covered by LEAP for 2026 "
              f"(now backfilled with real la_codes — see docs/data_notes.md 2026-09-22).")

    if args.only:
        councils = [c for c in councils if c["display_name"] == args.only]
    if args.limit:
        councils = councils[:args.limit]

    print(f"Processing {len(councils)} councils...")

    con = sqlite3.connect(DB_PATH)
    session = requests.Session()
    session.headers.update(HEADERS)

    totals = {"councils_loaded": 0, "wards_loaded": 0, "candidate_rows": 0, "ward_match_failures": 0}

    for c in councils:
        title = c["election_url"].rsplit("/", 1)[-1].replace("_", " ")
        html = fetch_page_html(session, title)
        time.sleep(0.5)
        if not html:
            print(f"  [skip] could not fetch {title!r}")
            continue

        ward_tables, election_type = parse_ward_tables(html)
        if not ward_tables:
            print(f"  [skip] no ward results table found for {c['display_name']!r}")
            continue

        ward_name_to_code, all_ward_names = load_wards_for_la(con, c["la_code"])

        cur = con.cursor()
        cur.execute(
            """INSERT INTO local_election_events (la_code, la_name, election_date, election_year,
                                                     election_type, boundary_year, source_url, page_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(la_code, election_date) DO UPDATE SET
                   election_type=excluded.election_type, source_url=excluded.source_url, page_url=excluded.page_url""",
            (c["la_code"], c["la_name_matched"], ELECTION_DATE, 2026, election_type,
             BOUNDARY_YEAR, c["election_url"], c["election_url"]),
        )
        con.commit()
        election_id = cur.execute(
            "SELECT election_id FROM local_election_events WHERE la_code=? AND election_date=?",
            (c["la_code"], ELECTION_DATE),
        ).fetchone()[0]
        cur.execute("DELETE FROM local_election_ward_results WHERE election_id=?", (election_id,))

        insert_rows = []
        for ward_name, candidate_rows in ward_tables:
            clean_name = ward_name.replace("&", "and")
            ward_code = None
            if all_ward_names:
                match, score = best_match(clean_name, all_ward_names)
                if score >= WARD_MATCH_THRESHOLD:
                    ward_code = ward_name_to_code[match]
                else:
                    totals["ward_match_failures"] += 1
            seats_available = max(sum(1 for r in candidate_rows if r["elected"]), 1)
            for r in candidate_rows:
                insert_rows.append((
                    election_id, ward_code, ward_name, BOUNDARY_YEAR, seats_available,
                    r["candidate"], r["party"], r["votes"], r["share"], int(r["elected"]),
                ))
            totals["wards_loaded"] += 1

        cur.executemany(
            """INSERT INTO local_election_ward_results
               (election_id, ward_code, ward_name_raw, boundary_year, seats_available,
                candidate_name, party, votes, vote_share_pct, elected)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            insert_rows,
        )
        # council-level summary, same approach as 03_fetch_leap_results.py
        cur.execute("DELETE FROM local_election_council_summary WHERE election_id=?", (election_id,))
        party_votes, party_seats, total_votes = {}, {}, 0
        for _, candidate_rows in ward_tables:
            for r in candidate_rows:
                if r["votes"]:
                    party_votes[r["party"]] = party_votes.get(r["party"], 0) + r["votes"]
                    total_votes += r["votes"]
                if r["elected"]:
                    party_seats[r["party"]] = party_seats.get(r["party"], 0) + 1
        summary_rows = [
            (election_id, p, party_seats.get(p, 0), party_votes.get(p, 0),
             round(100 * party_votes.get(p, 0) / total_votes, 2) if total_votes else None)
            for p in set(list(party_votes) + list(party_seats))
        ]
        cur.executemany(
            "INSERT INTO local_election_council_summary (election_id, party, seats_won, votes, vote_share_pct) VALUES (?,?,?,?,?)",
            summary_rows,
        )
        con.commit()

        totals["councils_loaded"] += 1
        totals["candidate_rows"] += len(insert_rows)
        print(f"  loaded {c['display_name']}: {len(ward_tables)} wards, {len(insert_rows)} candidate rows, "
              f"type={election_type}")

    print(f"\nDone. {totals['councils_loaded']} councils, {totals['wards_loaded']} wards, "
          f"{totals['candidate_rows']} candidate rows loaded. "
          f"{totals['ward_match_failures']} wards couldn't be matched to a ward_code.")
    con.close()


if __name__ == "__main__":
    sys.exit(main())
