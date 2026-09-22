"""
Build a comparison table: for each constituency, show the GE2024 actual
result, every MRP release's projected winner/margin in chronological order,
and (where available) the most recent local-election-derived leaning for
wards inside that constituency.

This directly answers "how do MRP projections compare with actual results
over time" — export to CSV/Excel and pivot/chart from there, or feed it
into scripts/06_constituency_dashboard.py.

Usage:
    python scripts/05_compare_mrp_vs_actuals.py --pcon E14001063
    python scripts/05_compare_mrp_vs_actuals.py --all --out data/comparison_export.csv
"""
import argparse
import csv
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "uk_elections.db"


def get_ge2024(con, pcon_code):
    return con.execute(
        """SELECT party, vote_share_pct FROM ge2024_results
           WHERE pcon_code=? AND rank=1""", (pcon_code,)
    ).fetchone()


def get_mrp_timeline(con, pcon_code):
    return con.execute(
        """SELECT pollster, publish_date, projected_winner, winner_share,
                  projected_runner_up, runner_up_share, projected_margin
           FROM mrp_headline WHERE pcon_code=? ORDER BY publish_date""",
        (pcon_code,),
    ).fetchall()


def get_local_leaning(con, pcon_code):
    """Most recent local election ward results rolled up for wards mapped to
    this constituency, weighted by ward_constituency_overlap where present."""
    return con.execute(
        """
        SELECT le.election_date, v.party, AVG(v.avg_vote_share_pct * COALESCE(o.weight, 1.0)) AS weighted_share
        FROM local_election_ward_party_avg v
        JOIN local_election_events le ON le.election_id = v.election_id
        -- ward_code only, not boundary_year — see docs/data_notes.md 2026-09-22
        JOIN wards w ON w.ward_code = v.ward_code
        LEFT JOIN ward_constituency_overlap o
               ON o.ward_code = v.ward_code AND o.boundary_year = w.boundary_year AND o.pcon_code = w.pcon_code
        WHERE w.pcon_code = ?
        GROUP BY le.election_date, v.party
        ORDER BY le.election_date DESC, weighted_share DESC
        """,
        (pcon_code,),
    ).fetchall()


def build_rows(con, pcon_code):
    ge = get_ge2024(con, pcon_code)
    rows = []
    for pollster, pub_date, winner, w_share, runner_up, ru_share, margin in get_mrp_timeline(con, pcon_code):
        rows.append({
            "pcon_code": pcon_code,
            "source": pollster,
            "date": pub_date,
            "type": "MRP",
            "leading_party": winner,
            "leading_share": w_share,
            "second_party": runner_up,
            "second_share": ru_share,
            "margin": margin,
            "ge2024_winner": ge[0] if ge else None,
            "ge2024_winner_share": ge[1] if ge else None,
        })
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pcon", help="single ONS PCON code")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--out", default=str(ROOT / "data" / "comparison_export.csv"))
    args = parser.parse_args()

    con = sqlite3.connect(DB_PATH)
    if args.all:
        pcons = [r[0] for r in con.execute("SELECT pcon_code FROM constituencies").fetchall()]
    elif args.pcon:
        pcons = [args.pcon]
    else:
        parser.error("pass --pcon CODE or --all")

    all_rows = []
    for pc in pcons:
        all_rows.extend(build_rows(con, pc))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "pcon_code", "source", "date", "type", "leading_party", "leading_share",
            "second_party", "second_share", "margin", "ge2024_winner", "ge2024_winner_share",
        ])
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"Wrote {len(all_rows)} rows to {out_path}")
    con.close()


if __name__ == "__main__":
    sys.exit(main())
