"""
Builds an index of every council that held 2026 local elections, sourced
from Wikipedia's "2026 United Kingdom local elections" summary page,
matched against real ONS la_codes (from wards.la_name, loaded in Phase 1)
rather than LEAP's placeholder LEAP-<id> codes.

WHY WIKIPEDIA FOR 2026 SPECIFICALLY: 136 English councils held elections
on 7 May 2026, but LEAP (the source for everything else in this project)
only has 20 of them transcribed so far — it's a volunteer effort and
lags behind. Wikipedia's per-council election articles are filled in
within days of results night by the WikiProject UK elections community
and use a consistent, scrapable wikitable format per ward. This is a
supplementary source for 2026 specifically, not a replacement for LEAP.

URL CONSTRUCTION: the summary page links to each council's general
Wikipedia article (e.g. "Barking_and_Dagenham_London_Borough_Council"),
not directly to the election results article. Confirmed by manual spot
checks that the election article is reliably at
"2026_<that same title>_election" (e.g.
"2026_Barking_and_Dagenham_London_Borough_Council_election") — this
script verifies that construction against every council with a live HTTP
request rather than assuming it holds for all 136 (county/unitary
naming is less consistent than London boroughs/metropolitan boroughs).

Usage:
    python scripts/09_fetch_wikipedia_council_index.py
Output:
    data/wikipedia_2026_council_index.csv
"""
import csv
import sqlite3
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from rapidfuzz import process, fuzz

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "uk_elections.db"
OUT_CSV = ROOT / "data" / "wikipedia_2026_council_index.csv"
INDEX_URL = "https://en.wikipedia.org/wiki/2026_United_Kingdom_local_elections"
API_URL = "https://en.wikipedia.org/w/api.php"
# Scraping raw page URLs directly (even just HEAD requests) trips Wikipedia's
# bot detection after ~2 rapid requests (403s start immediately) — the
# MediaWiki API is the actual sanctioned way to do bulk lookups like this,
# and batches up to 50 titles per call instead of one request per page.
HEADERS = {"User-Agent": "uk-elections-tracker/1.0 (research project; contact via github repo)"}


def fetch_council_links():
    resp = requests.get(INDEX_URL, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    seen = set()
    councils = []
    for table in soup.find_all("table", class_="wikitable"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
        if header[:1] not in (["Council"], ["District"]):
            continue
        for r in rows[1:]:
            cells = r.find_all(["th", "td"])
            if not cells:
                continue
            a = cells[0].find("a")
            href = a.get("href", "") if a else ""
            if not a or "/wiki/" not in href or "Party" in href:
                continue
            page_title = href.split("/wiki/")[-1].split("#")[0]
            if page_title in seen:
                continue
            seen.add(page_title)
            councils.append({"display_name": a.get_text(strip=True), "council_page_title": page_title})
    return councils


def check_pages_exist(session, titles):
    """Batched existence check via the MediaWiki API (50 titles/call) —
    returns {title: bool}."""
    result = {}
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        resp = session.get(API_URL, params={
            "action": "query", "titles": "|".join(batch), "format": "json",
        }, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # "normalized" maps our underscored title -> the page's real title;
        # entries with a "missing" key don't exist.
        norm = {n["from"]: n["to"] for n in data["query"].get("normalized", [])}
        missing_titles = {p["title"] for p in data["query"]["pages"].values() if "missing" in p}
        for t in batch:
            result[t] = norm.get(t, t.replace("_", " ")) not in missing_titles
    return result


def search_for_election_page(session, display_name):
    """Fallback for when '2026_<council page title>_election' doesn't
    exist — Wikipedia's naming isn't fully consistent (e.g. the generic
    council page is 'St_Helens_Council' but the election article is
    '2026_St_Helens_Borough_Council_election', with "Borough" inserted).
    Uses the search API (not batchable, but only needed for the handful
    that fail direct lookup) and only accepts a hit that's clearly a 2026
    council election page for this council, not just a loose text match."""
    for attempt in range(4):
        resp = session.get(API_URL, params={
            "action": "query", "list": "search", "srsearch": f"2026 {display_name} council election",
            "format": "json", "srlimit": 5,
        }, timeout=30)
        if resp.status_code == 429:
            time.sleep(2 ** attempt)  # 1s, 2s, 4s, 8s
            continue
        resp.raise_for_status()
        break
    else:
        print(f"  WARNING: gave up on {display_name!r} after repeated 429s")
        return None
    time.sleep(1)  # stay well under Wikipedia's rate limit between searches
    hits = [h["title"] for h in resp.json()["query"]["search"]]
    for title in hits:
        if (title.startswith("2026 ") and title.endswith(" election")
                and "council" in title.lower() and display_name.lower() in title.lower()):
            return title
    return None


def best_match(query, names):
    """Same tie-break fix as 04_ingest_mrp_release.py's best_match(): plain
    WRatio can't distinguish real near-duplicate names (e.g. it scored
    'Newcastle' equally against 'Newcastle upon Tyne' and
    'Newcastle-under-Lyme' in testing) — re-rank ties within 3 points by
    token_sort_ratio. See docs/data_notes.md 2026-09-22."""
    results = process.extract(query, names, scorer=fuzz.WRatio, limit=5)
    if not results:
        return None, 0
    top_score = results[0][1]
    contenders = [r for r in results if r[1] >= top_score - 3]
    if len(contenders) > 1:
        contenders.sort(key=lambda r: fuzz.token_sort_ratio(query, r[0]), reverse=True)
    return contenders[0][0], top_score


# English two-tier county councils — genuinely absent from wards.la_name
# (only their constituent DISTRICTS are there from Phase 1), so any match
# is necessarily wrong. Found the hard way: "Hampshire" and "Norfolk" both
# matched a same-named district at exactly the 90 threshold ("East
# Hampshire", "North Norfolk") with no collision to catch it (each was a
# UNIQUE match, not two names competing for one target, which is the only
# case the existing safety net in main() catches) — that silently loaded
# the county's whole election under the district's la_code and la_name
# until caught by manual inspection. See docs/data_notes.md 2026-09-22.
# Same list used for the LEAP la_code backfill (a one-off DB fix, not in
# this repo as a script) — keep both in sync if either changes.
COUNTY_EXCLUDE = {
    "Buckinghamshire", "Cambridgeshire", "Derbyshire", "Devon", "East Sussex", "Essex", "Gloucestershire",
    "Hampshire", "Hertfordshire", "Kent", "Lancashire", "Leicestershire", "Lincolnshire", "Norfolk",
    "North Yorkshire", "Nottinghamshire", "Oxfordshire", "Somerset", "Staffordshire", "Suffolk", "Surrey",
    "Warwickshire", "West Sussex", "Worcestershire",
}


def match_la_code(display_name, all_la_names, la_name_to_code):
    if display_name in COUNTY_EXCLUDE:
        return "", "", 0
    if display_name in la_name_to_code:
        return la_name_to_code[display_name], display_name, 100
    match, score = best_match(display_name, all_la_names)
    if score >= 90:
        return la_name_to_code[match], match, score
    return "", "", score


def main():
    con = sqlite3.connect(DB_PATH)
    la_rows = con.execute("SELECT DISTINCT la_code, la_name FROM wards").fetchall()
    la_name_to_code = {name: code for code, name in la_rows}
    all_la_names = list(la_name_to_code.keys())

    print(f"Fetching {INDEX_URL} ...")
    councils = fetch_council_links()
    print(f"Found {len(councils)} candidate councils in the summary tables.")

    session = requests.Session()
    session.headers.update(HEADERS)

    titles = [f"2026_{c['council_page_title']}_election" for c in councils]
    print(f"Checking existence of {len(titles)} candidate pages via the MediaWiki API...")
    exists_by_title = check_pages_exist(session, titles)

    out_rows = []
    for c in councils:
        election_title = f"2026_{c['council_page_title']}_election"
        exists = exists_by_title.get(election_title, False)
        election_url = f"https://en.wikipedia.org/wiki/{election_title}"

        la_code, la_match, la_score = match_la_code(c["display_name"], all_la_names, la_name_to_code)
        out_rows.append({
            "display_name": c["display_name"],
            "council_page_title": c["council_page_title"],
            "election_url": election_url if exists else "",
            "election_page_found": exists,
            "la_code": la_code,
            "la_name_matched": la_match,
            "la_match_score": la_score,
        })

    # Search-fallback, once per council (not per row) — only for councils
    # with NO confirmed page at all yet, since the direct-construction
    # naming convention isn't fully consistent across council types.
    found_names = {r["display_name"] for r in out_rows if r["election_page_found"]}
    unresolved = sorted({r["display_name"] for r in out_rows if not r["election_page_found"]} - found_names)
    if unresolved:
        print(f"Searching for {len(unresolved)} councils with no directly-constructed match...")
        resolved_titles = {}
        for name in unresolved:
            title = search_for_election_page(session, name)
            if title:
                resolved_titles[name] = title
        print(f"  resolved {len(resolved_titles)} via search")
        for r in out_rows:
            if not r["election_page_found"] and r["display_name"] in resolved_titles:
                title = resolved_titles[r["display_name"]]
                r["election_url"] = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
                r["election_page_found"] = True

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["display_name", "council_page_title", "election_url",
                                                 "election_page_found", "la_code", "la_name_matched", "la_match_score"])
        writer.writeheader()
        writer.writerows(out_rows)

    n_found = sum(1 for r in out_rows if r["election_page_found"])
    n_la_matched = sum(1 for r in out_rows if r["la_code"])
    print(f"Wrote {len(out_rows)} rows to {OUT_CSV}")
    print(f"  {n_found} election pages confirmed to exist")
    print(f"  {n_la_matched} matched to a real ONS la_code")
    not_found = [r["display_name"] for r in out_rows if not r["election_page_found"]]
    if not_found:
        print(f"  NOT FOUND (needs manual check): {not_found}")

    con.close()


if __name__ == "__main__":
    sys.exit(main())
