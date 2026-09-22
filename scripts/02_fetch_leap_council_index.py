"""
Parse https://www.andrewteale.me.uk/leap/elections-index/ into a CSV of
(council_name, leap_council_id, year, result_url).

The index page lists every council alphabetically, each with links like:
    Westminster: [2002](.../results/2002/20/) [2006](.../results/2006/20/) ...

Some years for some councils link to an EXTERNAL site (the council's own
results page) rather than to a LEAP-hosted results page — LEAP does this
when it hasn't transcribed that particular year yet. Those rows are kept
in the output (flagged is_leap_hosted=False) so you know what needs manual
attention, but 03_fetch_leap_results.py only auto-processes the LEAP-hosted
ones (i.e. those with a downloadable .csv).

Usage:
    python scripts/02_fetch_leap_council_index.py
Output:
    data/leap_council_index.csv
"""
import csv
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
OUT_CSV = ROOT / "data" / "leap_council_index.csv"
INDEX_URL = "https://www.andrewteale.me.uk/leap/elections-index/"
# The site's proxy 502s requests carrying the default python-requests UA.
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; uk-elections-tracker/1.0)"}

# Matches https://www.andrewteale.me.uk/leap/results/2022/20/  -> year=2022, id=20
LEAP_RESULTS_RE = re.compile(r"/leap/results/(\d{4})/(\d+)/?$")


def main():
    print(f"Fetching {INDEX_URL} ...")
    resp = requests.get(INDEX_URL, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    rows = []
    # Each council is a top-level <li> (or <p>) starting "CouncilName: [year](url) ..."
    # We scan all <li> elements in the main content and use the leading text
    # before the first link as the council name.
    for li in soup.find_all("li"):
        # Skip nested by-election <li>s — those live inside a further <ul>/<em>
        # under the council's own <li>; find_all recursion would double count,
        # so only treat this li as a council entry if its OWN text (not from
        # nested lists) starts with a capital letter followed by a colon.
        direct_text = li.find(text=True, recursive=False)
        if not direct_text or ":" not in direct_text:
            continue
        council_name = direct_text.split(":")[0].strip()
        if not council_name or not council_name[0].isalpha():
            continue

        links = li.find_all("a", href=True, recursive=True)
        for a in links:
            href = urljoin(INDEX_URL, a["href"])
            m = LEAP_RESULTS_RE.search(href)
            if m:
                year, cid = m.groups()
                rows.append({
                    "council_name": council_name,
                    "leap_council_id": cid,
                    "year": int(year),
                    "result_url": href,
                    "csv_url": href.rstrip("/") + ".csv",
                    "is_leap_hosted": True,
                })
            elif "andrewteale.me.uk" not in href and a.text.strip().isdigit():
                # A year link pointing off-site (council's own results page)
                rows.append({
                    "council_name": council_name,
                    "leap_council_id": None,
                    "year": int(a.text.strip()),
                    "result_url": href,
                    "csv_url": None,
                    "is_leap_hosted": False,
                })

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "council_name", "leap_council_id", "year", "result_url", "csv_url", "is_leap_hosted"
        ])
        writer.writeheader()
        writer.writerows(rows)

    n_hosted = sum(1 for r in rows if r["is_leap_hosted"])
    print(f"Wrote {len(rows)} rows ({n_hosted} LEAP-hosted, {len(rows) - n_hosted} external) to {OUT_CSV}")
    print("Review the external rows manually — those councils' results for that "
          "year live on the council's own site and need a bespoke parser.")


if __name__ == "__main__":
    sys.exit(main())
