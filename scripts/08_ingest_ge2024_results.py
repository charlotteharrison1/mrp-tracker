"""
Phase 3: load the actual 2024 general election result — the baseline every
MRP release and local election trend gets compared back to.

SOURCE: the official House of Commons Library results database,
electionresults.parliament.uk (the same body that publishes the
Commons Library's "General election 2024 results" briefing, CBP-10009 —
that page itself 403s on a plain fetch, but its underlying data site
doesn't). One CSV, candidate-level, for the whole UK:
    https://electionresults.parliament.uk/general-elections/6/candidacies.csv

Loads:
  - ge2024_results: one row per candidate (not just the winner) — party,
    votes, vote_share_pct, rank, and a per-constituency source_url. Multiple
    independents in one seat are expected (100 constituencies have >1),
    which is why the table's key includes candidate_name, not just party.
  - constituencies: backfills mp_2024, party_2024, majority_2024,
    electorate_2024, turnout_2024_pct, is_speaker_seat (Chorley) from the
    winning candidate's row.

Party codes come from the CSV's "Main party abbreviation" field as-is
(e.g. Con, Lab, RUK) — see docs/party_codes.md for known mismatches against
LEAP's local-election codes (Grn vs Green, C vs Con, Workers vs WPB).
Independents have a blank abbreviation in the source data; normalised to
"Ind" here to match the convention already used throughout local election
data.

Usage:
    python scripts/08_ingest_ge2024_results.py
"""
import csv
import sqlite3
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "uk_elections.db"
CSV_URL = "https://electionresults.parliament.uk/general-elections/6/candidacies.csv"


def fetch_csv():
    with urllib.request.urlopen(CSV_URL, timeout=60) as resp:
        text = resp.read().decode("utf-8-sig")
    return list(csv.DictReader(text.splitlines()))


def normalise_party(row):
    abbrev = row["Main party abbreviation"].strip()
    if abbrev:
        return abbrev
    if row["Candidate is standing as Commons Speaker"] == "true":
        return "Speaker"  # Hoyle (Chorley) stands with no party label, not as an independent
    if row["Candidate is standing as independent"] == "true":
        return "Ind"
    return row["Main party name"].strip() or "Unknown"


def main():
    print(f"Fetching {CSV_URL} ...")
    rows = fetch_csv()
    print(f"{len(rows)} candidate rows across {len(set(r['Constituency geographic code'] for r in rows))} constituencies")

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    result_rows = []
    constituency_updates = []
    skipped_notional = 0

    for r in rows:
        if r["Candidate is notional political party aggregate"] == "true":
            skipped_notional += 1
            continue  # not a real candidate row — shouldn't occur for a non-notional GE, guarded anyway

        pcon_code = r["Constituency geographic code"]
        party = normalise_party(r)
        candidate_name = (r["Candidate given name"] + " " + r["Candidate family name"]).strip()
        votes = int(r["Candidate vote count"]) if r["Candidate vote count"] else None
        vote_share_pct = round(float(r["Candidate vote share"]) * 100, 2) if r["Candidate vote share"] else None
        rank = int(r["Candidate result position"]) if r["Candidate result position"] else None
        source_url = r["Election URL"]

        result_rows.append((pcon_code, party, candidate_name, votes, vote_share_pct, rank, source_url))

        if rank == 1:
            electorate = int(r["Electorate"]) if r["Electorate"] else None
            valid = int(r["Election valid vote count"]) if r["Election valid vote count"] else None
            invalid = int(r["Election invalid vote count"]) if r["Election invalid vote count"] else 0
            turnout_pct = round(100 * (valid + invalid) / electorate, 2) if electorate and valid is not None else None
            majority = int(r["Majority"]) if r["Majority"] else None
            is_speaker = 1 if r["Candidate is standing as Commons Speaker"] == "true" else 0
            constituency_updates.append((candidate_name, party, majority, electorate, turnout_pct, is_speaker, pcon_code))

    # Full delete+insert, not upsert: this script always loads the entire
    # dataset in one pass, and party is part of the primary key — if a
    # normalisation rule changes (as happened once: Hoyle's party code
    # Unknown -> Speaker), an upsert leaves the old row behind as a stale
    # duplicate instead of replacing it. See docs/data_notes.md 2026-09-22.
    cur.execute("DELETE FROM ge2024_results")
    cur.executemany(
        """INSERT INTO ge2024_results (pcon_code, party, candidate_name, votes, vote_share_pct, rank, source_url)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        result_rows,
    )
    cur.executemany(
        """UPDATE constituencies SET mp_2024=?, party_2024=?, majority_2024=?,
               electorate_2024=?, turnout_2024_pct=?, is_speaker_seat=?
           WHERE pcon_code=?""",
        constituency_updates,
    )
    con.commit()

    print(f"Loaded {len(result_rows)} ge2024_results rows, "
          f"backfilled {len(constituency_updates)} constituencies "
          f"(skipped {skipped_notional} notional-aggregate rows).")

    speaker = cur.execute("SELECT pcon_name FROM constituencies WHERE is_speaker_seat=1").fetchall()
    print(f"Speaker's seat flagged: {speaker}")

    con.close()


if __name__ == "__main__":
    sys.exit(main())
