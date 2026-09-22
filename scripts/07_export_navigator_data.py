"""
Export the SQLite database into navigator_data.json — the single data file
that index.html (the constituency navigator, hosted as a static GitHub Pages
site) fetches and renders client-side.

Re-run this after every ingest so the navigator reflects the current DB.
Both navigator_data.json and index.html live at the repo root (NOT under
data/, which is gitignored) because GitHub Pages needs to serve them.

Row data is exported as compact tuples (documented per-section under
"columns") rather than repeated-key objects — the ward-level table alone is
~65k rows, so repeating key names per row would roughly double the file size
for no benefit.

Usage:
    python scripts/07_export_navigator_data.py
Output:
    navigator_data.json
"""
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "uk_elections.db"
OUT_PATH = ROOT / "navigator_data.json"


def fetch_constituencies(con):
    rows = con.execute(
        """SELECT pcon_code, pcon_name, nation, region, mp_2024, party_2024,
                  majority_2024, electorate_2024, turnout_2024_pct, is_speaker_seat
           FROM constituencies ORDER BY pcon_name"""
    ).fetchall()
    return [
        {
            "code": r[0], "name": r[1], "nation": r[2], "region": r[3],
            "mp": r[4], "party": r[5], "majority": r[6],
            "electorate": r[7], "turnout": r[8], "speaker": bool(r[9]),
        }
        for r in rows
    ]


def fetch_ge2024(con):
    by_pcon = defaultdict(list)
    for pcon, party, candidate, votes, share, rank, source_url in con.execute(
        """SELECT pcon_code, party, candidate_name, votes, vote_share_pct, rank, source_url
           FROM ge2024_results ORDER BY pcon_code, rank"""
    ):
        by_pcon[pcon].append([party, candidate, votes, share, rank, source_url])
    return by_pcon


def fetch_mrp(con):
    by_pcon = defaultdict(list)
    for pcon, pollster, pub_date, party, share, rank, win_prob, source_url, data_url in con.execute(
        """SELECT r.pcon_code, rel.pollster, rel.publish_date, r.party,
                  r.vote_share_pct, r.rank, r.win_probability_pct, rel.source_url, rel.data_url
           FROM mrp_constituency_results r
           JOIN mrp_releases rel ON rel.release_id = r.release_id
           ORDER BY r.pcon_code, rel.publish_date, r.rank"""
    ):
        by_pcon[pcon].append([pollster, pub_date, party, share, rank, win_prob, source_url, data_url])
    return by_pcon


def fetch_local_council(con):
    """Council-level party average per constituency: uses
    local_election_ward_party_avg (collapses multi-candidate-per-ward
    distortion) and AVGs across wards within a council-block — NOT SUM,
    which would overcount (see docs/data_notes.md, the 2026-09-22 fix)."""
    by_pcon = defaultdict(list)
    for pcon, la_name, date, party, share, n_wards, page_url, source_url in con.execute(
        """
        SELECT w.pcon_code, w.la_name, le.election_date, v.party,
               AVG(v.avg_vote_share_pct * COALESCE(o.weight, 1.0)) AS share,
               COUNT(DISTINCT v.ward_code) AS n_wards,
               MAX(le.page_url) AS page_url,
               MAX(le.source_url) AS source_url
        FROM local_election_ward_party_avg v
        JOIN local_election_events le ON le.election_id = v.election_id
        -- ward_code only, not boundary_year — see docs/data_notes.md 2026-09-22
        JOIN wards w ON w.ward_code = v.ward_code
        LEFT JOIN ward_constituency_overlap o
               ON o.ward_code = v.ward_code AND o.boundary_year = w.boundary_year AND o.pcon_code = w.pcon_code
        GROUP BY w.pcon_code, w.la_name, le.election_date, v.party
        ORDER BY w.pcon_code, w.la_name, le.election_date DESC
        """
    ):
        by_pcon[pcon].append([la_name, date, party, round(share, 2) if share is not None else None, n_wards, page_url, source_url])
    return by_pcon


def fetch_local_wards(con):
    """Raw candidate-level rows, for the navigator's optional ward-level
    drill-down. Only rows with a matched ward_code can be placed in a
    constituency — see docs/data_sources.md for the ~6% that can't yet."""
    by_pcon = defaultdict(list)
    for pcon, la_name, ward_name, ward_code, date, party, candidate, votes, share, elected in con.execute(
        """
        SELECT w.pcon_code, w.la_name, r.ward_name_raw, r.ward_code, le.election_date,
               r.party, r.candidate_name, r.votes, r.vote_share_pct, r.elected
        FROM local_election_ward_results r
        JOIN local_election_events le ON le.election_id = r.election_id
        -- ward_code only, not boundary_year — see docs/data_notes.md 2026-09-22
        JOIN wards w ON w.ward_code = r.ward_code
        ORDER BY w.pcon_code, w.la_name, r.ward_name_raw, le.election_date DESC, r.votes DESC
        """
    ):
        by_pcon[pcon].append([la_name, ward_name, ward_code, date, party, candidate, votes, share, bool(elected)])
    return by_pcon


STATIC_SOURCES = [
    {
        "phase": 1, "dataset": "Ward → Westminster constituency → LAD lookup (July 2024 vintage)",
        "source_name": "ONS Open Geography Portal (ArcGIS FeatureServer)",
        "source_url": "https://geoportal.statistics.gov.uk/datasets/ons::ward-to-westminster-parliamentary-constituency-to-lad-to-utla-july-2024-lookup-in-uk/about",
        "script": "01_fetch_ons_lookup.py",
        "note": "650 constituencies, 8,396 wards.",
    },
    {
        "phase": 1, "dataset": "LEAP council/year index",
        "source_name": "Local Elections Archive Project (Andrew Teale)",
        "source_url": "https://www.andrewteale.me.uk/leap/elections-index/",
        "script": "02_fetch_leap_council_index.py",
        "note": "3,894 rows, 465 councils, years 2002–2026.",
    },
    {
        "phase": 2, "dataset": "Ward-level local election results, 2021–2026",
        "source_name": "Local Elections Archive Project (Andrew Teale)",
        "source_url": "https://www.andrewteale.me.uk/leap/elections-index/",
        "script": "03_fetch_leap_results.py",
        "note": "One CSV per council per year — see the per-row \"source\"/\"csv\" links on each constituency page for the exact file behind any given number.",
    },
    {
        "phase": 3, "dataset": "GE2024 actual result — every candidate, every constituency",
        "source_name": "UK Parliament / House of Commons Library official results database",
        "source_url": "https://electionresults.parliament.uk/general-elections/6",
        "script": "08_ingest_ge2024_results.py",
        "note": "4,515 candidate rows, all 650 constituencies. Per-constituency source links are on each seat's GE2024 section.",
    },
]


def fetch_mrp_releases_meta(con):
    releases = []
    for row in con.execute(
        """SELECT r.release_id, r.pollster, r.client, r.publish_date, r.fieldwork_start, r.fieldwork_end,
                  r.sample_size, r.source_url, r.data_url, r.methodology_notes,
                  r.covers_scotland, r.covers_wales, r.covers_ni,
                  (SELECT COUNT(DISTINCT pcon_code) FROM mrp_constituency_results WHERE release_id = r.release_id) AS n_seats,
                  (SELECT COUNT(*) FROM mrp_constituency_results WHERE release_id = r.release_id) AS n_rows
           FROM mrp_releases r ORDER BY r.publish_date"""
    ):
        releases.append({
            "release_id": row[0], "pollster": row[1], "client": row[2], "publish_date": row[3],
            "fieldwork_start": row[4], "fieldwork_end": row[5], "sample_size": row[6],
            "source_url": row[7], "data_url": row[8], "methodology_notes": row[9],
            "covers_scotland": bool(row[10]), "covers_wales": bool(row[11]), "covers_ni": bool(row[12]),
            "n_seats": row[13], "n_rows": row[14],
        })
    return releases


def main():
    con = sqlite3.connect(DB_PATH)

    constituencies = fetch_constituencies(con)
    ge2024 = fetch_ge2024(con)
    mrp = fetch_mrp(con)
    local_council = fetch_local_council(con)
    local_wards = fetch_local_wards(con)
    mrp_releases_meta = fetch_mrp_releases_meta(con)

    pcons = [c["code"] for c in constituencies]
    by_pcon = {
        pcon: {
            "ge2024": ge2024.get(pcon, []),
            "mrp": mrp.get(pcon, []),
            "local_council": local_council.get(pcon, []),
            "local_wards": local_wards.get(pcon, []),
        }
        for pcon in pcons
    }

    n_unmatched_ward_rows = con.execute(
        "SELECT COUNT(*) FROM local_election_ward_results WHERE ward_code IS NULL OR ward_code = ''"
    ).fetchone()[0]

    data = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "columns": {
                "ge2024": ["party", "candidate_name", "votes", "vote_share_pct", "rank", "source_url"],
                "mrp": ["pollster", "publish_date", "party", "vote_share_pct", "rank", "win_probability_pct", "source_url", "data_url"],
                "local_council": ["la_name", "election_date", "party", "avg_vote_share_pct", "n_wards", "source_url", "data_url"],
                "local_wards": ["la_name", "ward_name", "ward_code", "election_date", "party",
                                 "candidate_name", "votes", "vote_share_pct", "elected"],
            },
            "counts": {
                "constituencies": len(constituencies),
                "ge2024_rows": sum(len(v) for v in ge2024.values()),
                "mrp_rows": sum(len(v) for v in mrp.values()),
                "local_council_rows": sum(len(v) for v in local_council.values()),
                "local_ward_rows": sum(len(v) for v in local_wards.values()),
                "local_ward_rows_unmatched_to_a_constituency": n_unmatched_ward_rows,
            },
        },
        "sources": {
            "static": STATIC_SOURCES,
            "mrp_releases": mrp_releases_meta,
        },
        "constituencies": constituencies,
        "by_pcon": by_pcon,
    }

    OUT_PATH.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    size_mb = OUT_PATH.stat().st_size / 1_000_000
    print(f"Wrote {OUT_PATH} ({size_mb:.2f} MB)")
    print(f"  {len(constituencies)} constituencies, "
          f"{data['meta']['counts']['local_council_rows']} local-council rows, "
          f"{data['meta']['counts']['local_ward_rows']} ward-level rows, "
          f"{data['meta']['counts']['ge2024_rows']} GE2024 rows, "
          f"{data['meta']['counts']['mrp_rows']} MRP rows")

    con.close()


if __name__ == "__main__":
    sys.exit(main())
