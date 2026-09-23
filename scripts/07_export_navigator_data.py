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


def build_ward_pcon_map(con):
    """ward_code -> [(pcon_code, weight), ...]. For the 388 wards genuinely
    split across >1 constituency (per ward_constituency_overlap — see
    docs/data_notes.md), this returns EVERY constituency the ward
    overlaps, each with an equal 1/n weight (no population data to weight
    by properly, so this is a deliberately simple approximation, not a
    precise split) — the ward's results now appear on every constituency
    it touches, rather than the previous single last-write-wins
    assignment that silently omitted it from all but one. Every other
    ward falls back to its single `wards.pcon_code` at weight 1.0."""
    m = defaultdict(list)
    overlap_wards = set()
    for ward_code, pcon_code, weight in con.execute(
        "SELECT ward_code, pcon_code, weight FROM ward_constituency_overlap"
    ):
        m[ward_code].append((pcon_code, weight))
        overlap_wards.add(ward_code)
    for ward_code, pcon_code in con.execute("SELECT ward_code, pcon_code FROM wards"):
        if ward_code not in overlap_wards:
            m[ward_code].append((pcon_code, 1.0))
    return m


def fetch_local_council(con, ward_pcon_map):
    """Council-level party share per constituency, for one (pcon, council,
    election date): a weighted average, across EVERY ward this constituency
    has in that council for that date, of local_election_ward_party_avg's
    now-correct (SUM'd, see schema.sql) per-ward party share.

    The averaging denominator must be every ward in scope, not just the
    wards a party happened to contest — a party that skipped its weakest
    ward is NOT "unmeasured" there, it got 0%, and excluding that ward from
    its average (the previous behaviour) inflated it. Doing this in Python
    rather than SQL because SQL would need an explicit party x ward cross
    join to materialise the implied zeros; zero-filling directly in a dict
    is simpler to get right. With this fix, plus the SUM fix in the view,
    one council/date's party shares now sum to (very close to) 100%, as an
    actual result should — see docs/data_notes.md, the "why don't these
    add up to 100%" investigation."""
    la_name_by_ward = dict(con.execute("SELECT ward_code, la_name FROM wards"))
    ward_rows = con.execute(
        """
        SELECT le.election_date, v.ward_code, v.party, v.ward_vote_share_pct AS share,
               v.seats_won_in_ward, le.page_url, le.source_url
        FROM local_election_ward_party_avg v
        JOIN local_election_events le ON le.election_id = v.election_id
        """
    ).fetchall()

    ward_universe = defaultdict(dict)              # (pcon, la, date) -> {ward_code: weight}
    party_ward_share = defaultdict(lambda: defaultdict(dict))  # (pcon, la, date) -> party -> {ward_code: share}
    party_ward_seats = defaultdict(lambda: defaultdict(dict))  # (pcon, la, date) -> party -> {ward_code: seats_won}
    meta = {}                                       # (pcon, la, date) -> (page_url, source_url)
    for date, ward_code, party, share, seats_won, page_url, source_url in ward_rows:
        la_name = la_name_by_ward.get(ward_code)
        for pcon, weight in ward_pcon_map.get(ward_code, []):
            key = (pcon, la_name, date)
            ward_universe[key][ward_code] = weight
            party_ward_share[key][party][ward_code] = share
            party_ward_seats[key][party][ward_code] = seats_won
            meta[key] = (page_url, source_url)

    by_pcon = defaultdict(list)
    for key in sorted(ward_universe, key=lambda k: (k[0], k[1], k[2]), reverse=True):
        pcon, la_name, date = key
        weights = ward_universe[key]
        total_weight = sum(weights.values()) or 1.0
        page_url, source_url = meta[key]
        rows_for_key = []
        for party, ward_map in party_ward_share[key].items():
            weighted_sum = sum((ward_map.get(wc) or 0.0) * wt for wc, wt in weights.items())
            share = weighted_sum / total_weight
            # Seats won: a straight sum, not weighted/averaged like the
            # vote share — a split ward's council seat is a real seat
            # regardless of what fraction of the ward's electorate sits
            # in this constituency, and a multi-member ward can hand a
            # party more than one seat there (each contested/won
            # candidacy is its own row in the source data).
            seats_won = sum(v or 0 for v in party_ward_seats[key][party].values())
            rows_for_key.append([la_name, date, party, round(share, 2), len(ward_map), seats_won, page_url, source_url])
        rows_for_key.sort(key=lambda r: r[3], reverse=True)
        by_pcon[pcon].extend(rows_for_key)
    return by_pcon


def fetch_local_wards(con, ward_pcon_map):
    """Raw candidate-level rows, for the navigator's optional ward-level
    drill-down. Only rows with a matched ward_code can be placed in a
    constituency — see docs/data_sources.md for the ~6% that can't yet.
    A ward split across >1 constituency (ward_pcon_map) appears identically
    under each — the raw candidate/vote data doesn't change per
    constituency, only how much it should count toward each one's
    AVERAGE does (handled separately in fetch_local_council)."""
    la_name_by_ward = dict(con.execute("SELECT ward_code, la_name FROM wards"))
    by_pcon = defaultdict(list)
    rows = con.execute(
        """
        SELECT r.ward_name_raw, r.ward_code, le.election_date,
               r.party, r.candidate_name, r.votes, r.vote_share_pct, r.elected
        FROM local_election_ward_results r
        JOIN local_election_events le ON le.election_id = r.election_id
        WHERE r.ward_code IS NOT NULL
        ORDER BY r.ward_name_raw, le.election_date DESC, r.votes DESC
        """
    ).fetchall()
    for ward_name, ward_code, date, party, candidate, votes, share, elected in rows:
        la_name = la_name_by_ward.get(ward_code)
        for pcon, _weight in ward_pcon_map.get(ward_code, []):
            by_pcon[pcon].append([la_name, ward_name, ward_code, date, party, candidate, votes, share, bool(elected)])
    # Stable multi-pass sort (Python's sort is stable) to get the same
    # ordering as the original SQL: la_name, ward_name asc; date, votes desc.
    for pcon in by_pcon:
        rows = by_pcon[pcon]
        rows.sort(key=lambda r: r[6] or 0, reverse=True)   # votes desc
        rows.sort(key=lambda r: r[3], reverse=True)        # date desc
        rows.sort(key=lambda r: (r[0] or "", r[1]))         # la_name, ward_name asc
    return by_pcon


STATIC_SOURCES = [
    {
        "phase": 1, "dataset": "Ward → Westminster constituency → LAD lookup (July 2024 vintage)",
        "source_name": "ONS Open Geography Portal (ArcGIS FeatureServer)",
        "source_url": "https://geoportal.statistics.gov.uk/datasets/ons::ward-to-westminster-parliamentary-constituency-to-lad-to-utla-july-2024-lookup-in-uk/about",
        "script": "01_fetch_ons_lookup.py",
        "note": "650 constituencies, 8,396 wards. Known limitation: 388 wards nationally "
                "(4.6%) are flagged by ONS as split across 2+ constituencies. Every "
                "constituency a split ward touches now gets that ward's local election "
                "results in full (not silently omitted, as an earlier version of this "
                "project did) — but each is weighted only an equal 1/n share toward that "
                "constituency's own average, since we don't have the population data to "
                "split it properly by how many of the ward's electors actually live on "
                "each side. A precise fix needs population-weighted boundary geometry (see "
                "docs/senedd_crosswalk.md for the same technique applied to a different "
                "problem) — not attempted, this is a deliberate approximation.",
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
    ward_pcon_map = build_ward_pcon_map(con)
    local_council = fetch_local_council(con, ward_pcon_map)
    local_wards = fetch_local_wards(con, ward_pcon_map)
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
                "local_council": ["la_name", "election_date", "party", "avg_vote_share_pct", "n_wards", "seats_won", "source_url", "data_url"],
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
