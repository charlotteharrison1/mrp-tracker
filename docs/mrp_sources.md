# MRP release tracker

One row per release. Status: `not started` / `csv built` / `ingested`.
Add rows as you find more — this list (seeded from initial research, Sept
2026) is a starting point, not exhaustive.

| Pollster | Client | Approx. date | Where to look | Status |
|---|---|---|---|---|
| Focaldata/Prolific | — | Jun 2024 | focaldata.com/blog/focaldata-prolific-uk-general-election-mrp | not started |
| Ipsos | — | Jun 2024 | ipsos.com/en-uk/uk-opinion-polls/ipsos-election-mrp | not started |
| YouGov | Sky/Times | Jun 2024 | yougov.co.uk elections hub | not started |
| More in Common | — | Dec 2025 (first post-election MRP) | moreincommon.org.uk/research-type/mrp/ | not started |
| More in Common | — | Jan 2026 | moreincommon.org.uk/research-type/mrp/ | not started |
| More in Common | — | Apr 2026 | moreincommon.org.uk/research-type/mrp/ | not started |
| More in Common (Senedd) | — | Apr 2026 | moreincommon.org.uk/research-type/mrp/ | not started |
| More in Common (Holyrood) | — | Apr 2026 | moreincommon.org.uk/research-type/mrp/ | not started |
| Electoral Calculus | PLMR | Apr 2026 (23rd) | electoralcalculus.co.uk/blogs/ec_vipoll_20260423.html | **ingested** (release_id=4, 2026-09-22) — same process as the July release; no separate "Restore" column existed yet in this file |
| Electoral Calculus | PLMR | Jan 2026 (found while researching Apr) | electoralcalculus.co.uk/blogs/ec_vipoll_20260113.html | **ingested** (release_id=5, 2026-09-22) — fieldwork was actually Dec 2025 (data file is literally named DataTables_VIDec2025.xlsx); has a "YP" party column (likely "Your Party") not seen in later releases, and a non-party "cost of living issues" section on the same header row that had to be explicitly excluded (see docs/data_notes.md) |
| Electoral Calculus | PLMR | Jul 2026 | electoralcalculus.co.uk/blogs/ec_vipoll_20260708.html | **ingested** (release_id=1, 2026-09-22) — GB only (no NI), loaded the "No TV" scenario via `scripts/prep_electoral_calculus_xlsx.py` + `04_ingest_mrp_release.py`; the tactically-adjusted "With TV" variant in the same file wasn't loaded, re-run prep with `--with-tv` if wanted |
| Find Out Now / Electoral Calculus | — | 2026 (Scotland) | electionanalysis.uk cites this — check Electoral Calculus site | not started |
| JL Partners | Telegraph | 2026 (Scotland, Wales) | check Telegraph / JL Partners site — note known D'Hondt application error flagged by electionanalysis.uk, treat cautiously | not started |
| Survation | — | check survation.com | not started |

## Process per row

1. Open the source, find the constituency-level table/download.
2. Fill in `templates/mrp_release_template.csv` (or a copy of it) with that
   release's numbers.
3. Run `04_ingest_mrp_release.py` with the release's metadata.
4. Update this table's status.

## Where to keep checking for NEW releases going forward

- moreincommon.org.uk/research-type/mrp/ (running index)
- electoralcalculus.co.uk/blogs/ (individual posts, not indexed centrally —
  check periodically)
- Wikipedia: "Opinion polling for the next United Kingdom general election"
  — lists every poll chronologically, including MRPs, with source links.
