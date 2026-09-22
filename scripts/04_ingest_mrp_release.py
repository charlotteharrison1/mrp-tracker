"""
Load one MRP release into the database from a standardised CSV
(see templates/mrp_release_template.csv).

WHY THIS IS SEMI-MANUAL:
Every pollster publishes MRP results in a different shape (some as an
interactive dashboard, some as a downloadable spreadsheet, some only as
numbers embedded in a PDF/blog post). There's no reliable way to
auto-scrape all of them the same way. The practical workflow is:

  1. Find the release (see docs/mrp_sources.md for where to look).
  2. Get its constituency-level numbers into templates/mrp_release_template.csv
     format — copy-paste from their table/download, or (for a PDF/dashboard)
     transcribe it. If Claude Code is doing this step, it can often read the
     page/PDF directly and produce this CSV itself.
  3. Run this script to load that CSV into the database, with the release's
     metadata as arguments.

MATCHING CONSTITUENCIES:
If your CSV has pcon_code filled in for every row, matching is exact. If a
pollster only gives constituency NAMES (no ONS codes — which is common),
leave pcon_code blank and this script will fuzzy-match pcon_name against
the `constituencies` table (rapidfuzz, threshold configurable). Anything
below the threshold is written to data/mrp_unmatched_<release>.csv for you
to fix by hand and re-run.

Usage:
    python scripts/04_ingest_mrp_release.py \\
        --csv templates/mrp_release_template.csv \\
        --pollster "Electoral Calculus" --client PLMR \\
        --publish-date 2026-07-08 \\
        --source-url "https://www.electoralcalculus.co.uk/blogs/ec_vipoll_20260708.html" \\
        --sample-size 5500
"""
import argparse
import csv as csv_module
import sqlite3
import sys
from pathlib import Path

from rapidfuzz import process, fuzz

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "uk_elections.db"

MATCH_THRESHOLD = 90  # rapidfuzz score 0-100; below this, flagged for manual review


def load_constituency_lookup(con):
    rows = con.execute("SELECT pcon_code, pcon_name FROM constituencies").fetchall()
    return {name: code for code, name in rows}, [name for _, name in rows]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--pollster", required=True)
    parser.add_argument("--client")
    parser.add_argument("--publish-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--fieldwork-start")
    parser.add_argument("--fieldwork-end")
    parser.add_argument("--source-url", required=True, help="the pollster's article/blog page (human-readable)")
    parser.add_argument("--data-url", help="direct link to the downloadable data file, if separate from --source-url")
    parser.add_argument("--sample-size", type=int)
    parser.add_argument("--methodology-notes")
    args = parser.parse_args()

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute(
        """INSERT INTO mrp_releases (pollster, client, fieldwork_start, fieldwork_end,
                                       publish_date, sample_size, source_url, data_url, methodology_notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(pollster, publish_date, client) DO UPDATE SET
               source_url=excluded.source_url, data_url=excluded.data_url""",
        (args.pollster, args.client, args.fieldwork_start, args.fieldwork_end,
         args.publish_date, args.sample_size, args.source_url, args.data_url, args.methodology_notes),
    )
    con.commit()
    release_id = cur.execute(
        "SELECT release_id FROM mrp_releases WHERE pollster=? AND publish_date=? AND client IS ?",
        (args.pollster, args.publish_date, args.client),
    ).fetchone()[0]

    name_to_code, all_names = load_constituency_lookup(con)

    with open(args.csv, encoding="utf-8") as f:
        rows = list(csv_module.DictReader(f))

    unmatched = []
    by_constituency = {}
    for row in rows:
        pcon_code = row.get("pcon_code", "").strip()
        pcon_name = row.get("pcon_name", "").strip()

        if not pcon_code and pcon_name:
            match, score, _ = process.extractOne(pcon_name, all_names, scorer=fuzz.WRatio)
            if score >= MATCH_THRESHOLD:
                pcon_code = name_to_code[match]
            else:
                unmatched.append({**row, "best_guess": match, "score": score})
                continue

        by_constituency.setdefault(pcon_code, []).append(row)

    insert_rows = []
    for pcon_code, party_rows in by_constituency.items():
        ranked = sorted(party_rows, key=lambda r: float(r["vote_share_pct"]), reverse=True)
        for rank, row in enumerate(ranked, start=1):
            wp = row.get("win_probability_pct", "").strip()
            insert_rows.append((
                release_id, pcon_code, row["party"].strip(),
                float(row["vote_share_pct"]), rank,
                float(wp) if wp else None,
            ))

    cur.executemany(
        """INSERT INTO mrp_constituency_results
           (release_id, pcon_code, party, vote_share_pct, rank, win_probability_pct)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(release_id, pcon_code, party) DO UPDATE SET
               vote_share_pct=excluded.vote_share_pct, rank=excluded.rank,
               win_probability_pct=excluded.win_probability_pct""",
        insert_rows,
    )
    con.commit()

    print(f"Loaded release_id={release_id}: {len(by_constituency)} constituencies, {len(insert_rows)} rows.")

    if unmatched:
        out = ROOT / "data" / f"mrp_unmatched_{args.pollster.replace(' ', '_')}_{args.publish_date}.csv"
        with out.open("w", newline="", encoding="utf-8") as f:
            writer = csv_module.DictWriter(f, fieldnames=list(unmatched[0].keys()))
            writer.writeheader()
            writer.writerows(unmatched)
        print(f"WARNING: {len(unmatched)} rows could not be confidently matched to a constituency. "
              f"Review {out}, fix pcon_code by hand, and re-run.")

    con.close()


if __name__ == "__main__":
    sys.exit(main())
