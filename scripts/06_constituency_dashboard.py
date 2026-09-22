"""
Generate a static HTML "constituency profile" page: MRP trend over time,
GE2024 baseline, and a ward-by-ward local election breakdown grouped by
council — so a constituency that crosses two councils with different
political histories shows that split explicitly.

This is a starting point, not a polished product — it's plain HTML/CSS with
no JS framework, so it's easy for Claude Code to extend (e.g. swap in
Chart.js, or turn it into a proper multi-page site with a constituency
picker) once more data is loaded.

Usage:
    python scripts/06_constituency_dashboard.py --pcon E14001063 --out data/dashboards/
    python scripts/06_constituency_dashboard.py --all --out data/dashboards/
"""
import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "uk_elections.db"

PARTY_COLOURS = {
    "LAB": "#E4003B", "CON": "#0087DC", "LD": "#FAA61A", "REF": "#12B6CF",
    "GRN": "#02A95B", "SNP": "#FFF95D", "PC": "#3F8428", "Ind": "#909090",
}


def party_colour(p):
    return PARTY_COLOURS.get(p, "#999999")


def render_mrp_trend(con, pcon_code):
    rows = con.execute(
        """SELECT pollster, publish_date, projected_winner, winner_share, projected_margin
           FROM mrp_headline WHERE pcon_code=? ORDER BY publish_date""", (pcon_code,)
    ).fetchall()
    if not rows:
        return "<p><em>No MRP releases loaded yet for this seat.</em></p>"

    items = "".join(
        f"<tr><td>{date}</td><td>{pollster}</td>"
        f"<td><span class='chip' style='background:{party_colour(winner)}'>{winner}</span> {share:.1f}%</td>"
        f"<td>+{margin:.1f}pts</td></tr>"
        for pollster, date, winner, share, margin in rows
    )
    return f"""
    <table class="mrp-table">
      <thead><tr><th>Date</th><th>Pollster</th><th>Projected winner</th><th>Margin</th></tr></thead>
      <tbody>{items}</tbody>
    </table>
    """


def render_local_by_council(con, pcon_code):
    # NOTE: AVGs only over wards a party contested, and joins through
    # wards.pcon_code's single assignment (so a split ward only ever
    # shows up on one side, with a real-but-unnormalised weight now that
    # ward_constituency_overlap is populated) — same caveats as
    # 05_compare_mrp_vs_actuals.py's get_local_leaning() — see
    # docs/data_notes.md 2026-09-22. Superseded by the navigator, which
    # does the full zero-fill + both-sides-of-a-split-ward version of this.
    rows = con.execute(
        """
        SELECT w.la_name, le.election_date, v.party,
               AVG(v.ward_vote_share_pct * COALESCE(o.weight, 1.0)) AS share,
               COUNT(DISTINCT v.ward_code) AS n_wards
        FROM local_election_ward_party_avg v
        JOIN local_election_events le ON le.election_id = v.election_id
        -- Join on ward_code alone, not boundary_year: v.boundary_year is the
        -- calendar year of the ELECTION (set in 03_fetch_leap_results.py),
        -- not an ONS ward-geometry vintage, and only one vintage (2024) is
        -- loaded into `wards` anyway. Requiring equality here silently
        -- dropped ~93% of matchable rows (see docs/data_notes.md, 2026-09-22).
        JOIN wards w ON w.ward_code = v.ward_code
        LEFT JOIN ward_constituency_overlap o
               ON o.ward_code = v.ward_code AND o.boundary_year = w.boundary_year AND o.pcon_code = w.pcon_code
        WHERE w.pcon_code = ?
        GROUP BY w.la_name, le.election_date, v.party
        ORDER BY w.la_name, le.election_date DESC
        """,
        (pcon_code,),
    ).fetchall()

    if not rows:
        return "<p><em>No local election data loaded yet for wards in this seat.</em></p>"

    by_council = defaultdict(list)
    for la_name, date, party, share, n_wards in rows:
        by_council[la_name].append((date, party, share, n_wards))

    blocks = []
    for la_name, entries in by_council.items():
        rows_html = "".join(
            f"<tr><td>{date}</td>"
            f"<td><span class='chip' style='background:{party_colour(party)}'>{party}</span></td>"
            f"<td>{share:.1f}%</td><td>{n_wards}</td></tr>"
            for date, party, share, n_wards in entries
        )
        blocks.append(f"""
        <div class="council-block">
          <h3>{la_name}</h3>
          <table class="local-table">
            <thead><tr><th>Date</th><th>Party</th><th>Avg. ward share</th><th># wards</th></tr></thead>
            <tbody>{rows_html}</tbody>
          </table>
        </div>
        """)

    note = ""
    if len(by_council) > 1:
        note = (f"<p class='note'>This constituency crosses <strong>{len(by_council)} councils</strong> "
                f"— compare the blocks below to see whether they lean differently.</p>")

    return note + "".join(blocks)


def render_page(con, pcon_code):
    row = con.execute("SELECT pcon_name, mp_2024, party_2024, majority_2024 FROM constituencies WHERE pcon_code=?",
                       (pcon_code,)).fetchone()
    if not row:
        return None
    pcon_name, mp_2024, party_2024, majority_2024 = row

    ge = con.execute("SELECT party, vote_share_pct FROM ge2024_results WHERE pcon_code=? ORDER BY rank",
                      (pcon_code,)).fetchall()
    ge_html = "".join(
        f"<span class='chip' style='background:{party_colour(p)}'>{p} {s:.1f}%</span> " for p, s in ge
    ) or "<em>GE2024 result not loaded yet</em>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{pcon_name} — constituency profile</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Arial, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }}
  h1 {{ margin-bottom: 0.2rem; }}
  .subtitle {{ color: #555; margin-top: 0; }}
  table {{ border-collapse: collapse; width: 100%; margin: 0.5rem 0 1.5rem; }}
  th, td {{ text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #eee; font-size: 0.92rem; }}
  th {{ color: #666; font-weight: 600; }}
  .chip {{ color: white; border-radius: 4px; padding: 0.1rem 0.5rem; font-size: 0.85rem; font-weight: 600; }}
  .council-block {{ margin-bottom: 1.5rem; }}
  .note {{ background: #fff8e1; border-left: 3px solid #f5c518; padding: 0.6rem 1rem; }}
  section {{ margin-bottom: 2rem; }}
</style>
</head>
<body>
  <h1>{pcon_name}</h1>
  <p class="subtitle">2024 MP: {mp_2024 or '—'} ({party_2024 or '—'}), majority {majority_2024 or '—'}</p>

  <section>
    <h2>GE2024 baseline</h2>
    <p>{ge_html}</p>
  </section>

  <section>
    <h2>MRP projections over time</h2>
    {render_mrp_trend(con, pcon_code)}
  </section>

  <section>
    <h2>Local election results by council</h2>
    {render_local_by_council(con, pcon_code)}
  </section>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pcon")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--out", default=str(ROOT / "data" / "dashboards"))
    args = parser.parse_args()

    con = sqlite3.connect(DB_PATH)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.all:
        pcons = [r[0] for r in con.execute("SELECT pcon_code FROM constituencies").fetchall()]
    elif args.pcon:
        pcons = [args.pcon]
    else:
        parser.error("pass --pcon CODE or --all")

    for pc in pcons:
        html = render_page(con, pc)
        if html:
            (out_dir / f"{pc}.html").write_text(html, encoding="utf-8")

    print(f"Wrote {len(pcons)} dashboard page(s) to {out_dir}/")
    con.close()


if __name__ == "__main__":
    sys.exit(main())
