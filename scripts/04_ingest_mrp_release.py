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
TIE_MARGIN = 3         # WRatio candidates within this many points of the top score are tie-broken


def load_constituency_lookup(con):
    rows = con.execute("SELECT pcon_code, pcon_name FROM constituencies").fetchall()
    return {name: code for code, name in rows}, [name for _, name in rows]


def best_match(query, names):
    """WRatio alone confuses genuine near-duplicates: 'Devon South West' scores
    95 against BOTH 'South Devon' and 'South West Devon' (subset containment
    scores it can't tell apart), and would silently pick whichever sorts
    first. Within a small margin of the top score, re-rank by
    token_sort_ratio instead, which requires the same token SET (so it
    correctly prefers the exact-token match) — but isn't used as the primary
    scorer because it wrongly penalises genuine subset matches like
    'Hull East' -> 'Kingston upon Hull East' (drops to 56 vs WRatio's 90).
    See docs/data_notes.md 2026-09-22."""
    results = process.extract(query, names, scorer=fuzz.WRatio, limit=5)
    if not results:
        return None, 0
    top_score = results[0][1]
    contenders = [r for r in results if r[1] >= top_score - TIE_MARGIN]
    if len(contenders) > 1:
        contenders.sort(key=lambda r: fuzz.token_sort_ratio(query, r[0]), reverse=True)
    return contenders[0][0], top_score


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
    # SQLite treats every NULL as distinct from every other NULL for
    # UNIQUE(pollster, publish_date, client) purposes, so a NULL client
    # (the common case - most releases have no commissioning client) never
    # actually conflicts with itself: ON CONFLICT silently never fires, and
    # re-running this script for the same release inserts a second, empty
    # mrp_releases row instead of updating the first (found 2026-09-22
    # auditing the DB - release_id 12 was exactly this: an orphaned
    # zero-row duplicate of release_id 11 from a re-run after fixing the
    # Mac Roman encoding bug). Coercing to "" makes the UNIQUE constraint
    # actually unique.
    args.client = args.client or ""

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute(
        """INSERT INTO mrp_releases (pollster, client, fieldwork_start, fieldwork_end,
                                       publish_date, sample_size, source_url, data_url, methodology_notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(pollster, publish_date, client) DO UPDATE SET
               fieldwork_start=excluded.fieldwork_start, fieldwork_end=excluded.fieldwork_end,
               sample_size=excluded.sample_size, source_url=excluded.source_url,
               data_url=excluded.data_url, methodology_notes=excluded.methodology_notes""",
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
            match, score = best_match(pcon_name, all_names)
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
