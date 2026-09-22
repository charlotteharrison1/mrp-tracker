# Data notes (running log)

Use this as a lab notebook — append short dated notes about anything
surprising, any manual fixes made, any source that changed shape, etc. This
is for whichever session (or agent) picks this project up next.

## Example entry format

```
### 2026-09-22
- ONS ward lookup Dec 2023 FeatureServer URL: <paste once found>
- LEAP: council X's 2023 results are external (council's own site) not LEAP-hosted, see leap_council_index.csv
```

### 2026-09-22 — Phase 1 (reference data) completed

- **ONS ward→constituency lookup, July 2024 vintage (matches actual GE2024
  boundaries), suffix `24`:**
  `https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/WD24_PCON24_LAD24_UTLA24_UK_LU/FeatureServer`
  Found via the ArcGIS Hub API (`hub.arcgis.com/api/v3/datasets/<item-id>`)
  since the geoportal dataset page is JS-rendered and doesn't expose the
  FeatureServer URL to a plain fetch. Loaded: 650 constituencies (543 Eng /
  57 Scot / 32 Wales / 18 NI — correct UK total), 8,396 unique ward rows.
- **Bug fixed in `01_fetch_ons_lookup.py`:** pagination broke after the
  first page because this service caps `resultRecordCount` at 1,000
  regardless of what's requested (2,000), and the old code compared the
  returned count to the *requested* page size to detect the last page —
  so it silently stopped after 1,000 of 8,798 rows. Now checks the
  response's `exceededTransferLimit` flag instead. **If this script is
  ever pointed at a different ArcGIS service, verify pagination actually
  reaches the full row count — don't trust a clean exit silently.**
- **~400 wards are split across >1 constituency** (ONS's `SPLIT_WARD`
  flag on this dataset). `01_fetch_ons_lookup.py` doesn't populate
  `ward_constituency_overlap` for these — it just last-write-wins into
  `wards.pcon_code`, so 8,798 raw rows collapsed to 8,396. Not fixed yet;
  matters for precision on any constituency containing a split ward.
  Revisit alongside Phase 5 (crosswalk/geometry work).
- **`www.andrewteale.me.uk` (LEAP) 502s any request without a browser-like
  `User-Agent`** (its proxy blocks the default `python-requests` UA).
  Fixed in both `02_fetch_leap_council_index.py` and
  `03_fetch_leap_results.py` by sending a static UA header.
- **Bug fixed in `02_fetch_leap_council_index.py`:** `csv_url`/`result_url`
  were built from the raw (site-relative) `href`, e.g.
  `/leap/results/2003/427.csv`, which `requests.get()` can't fetch as-is.
  Now resolved to absolute URLs with `urljoin`. Re-ran after the fix —
  `data/leap_council_index.csv` now has 3,894 rows (3,714 LEAP-hosted, 180
  external) across 465 councils, years 2002–2026.
- **Bug found and fixed in `05_compare_mrp_vs_actuals.py`, `06_constituency_dashboard.py`
  (and the new `07_export_navigator_data.py`):** two separate issues, both in
  how local election results get attached to a constituency —
  1. The council-block aggregation used `SUM(vote_share_pct)` across every
     ward in a council but labelled it "average" — e.g. a party standing in 4
     wards showed 200%+. Fixed to `AVG(...)` over
     `local_election_ward_party_avg` (the view that already collapses
     multi-candidate-per-ward distortion).
  2. Far more serious: every join to `wards` required
     `w.boundary_year = r.boundary_year`, but `r.boundary_year` (set in
     `03_fetch_leap_results.py`) is the *calendar year of the election*
     (2021, 2022, ...), not an ONS ward-geometry vintage — and only the 2024
     vintage is loaded into `wards`. So only rows from elections literally
     held in 2024 ever matched; everything else (2021–2023, 2025) was
     silently dropped. Match rate before the fix: 4,357/64,719 raw ward rows
     (6.7%). After dropping the boundary_year equality and joining on
     `ward_code` alone: 45,721/64,719 (70.7%) — Gorton and Denton went from
     showing only 2024 local results to all four years (2021–2024). The
     remaining gap is real (mostly 2025 elections on ward boundaries drawn
     after the July-2024 ONS vintage this project has loaded, plus wards
     genuinely recoded between reviews) — loading an additional, newer ONS
     ward vintage would close more of it. **If a second ward vintage is ever
     loaded, revisit this join** — it should probably prefer the vintage
     whose year is closest to (at or before) the election year, not just
     "any vintage, any ward_code."
- **If a constituency's local election data looks stuck at an old year, check
  before assuming it's a bug.** 101 councils had 2022 as their most recent
  loaded election; only 3 (Birmingham, Camden, Wandsworth) were a real gap
  (fixed above — 2026 just hadn't been fetched). The other 98 are correct:
  Scottish and Welsh councils elect on a 5-year cycle (2022→2027, so 2022
  genuinely is current), and most English councils that held all-out
  elections in 2026 haven't had their results transcribed onto LEAP yet —
  as of this session only 20 councils have a 2026 LEAP CSV at all. Re-check
  `data/leap_council_index.csv` for a `year=2026` row before concluding a
  given council is missing data we could otherwise fetch.
- **LEAP CSV column order isn't stable across eras.** Modern exports
  (confirmed on Westminster 2022) are
  `council, ward, "", ward_code(GSS), candidate, party, votes, status` —
  matching what `03_fetch_leap_results.py` assumes. But pre-2011 exports
  (confirmed on Aberdeen 2003) have the blank and code columns **swapped**:
  `council, ward, old_ward_code, "", candidate, party, votes, status` —
  and the "code" is an old pre-GSS format (e.g. `00QA34`), not an ONS ward
  code anyway. Doesn't affect Phase 2 as scoped (2021+), but **don't run
  `03_fetch_leap_results.py` on pre-2011 years without handling this** —
  it'll silently write garbage/empty `ward_code`s.
