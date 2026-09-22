# MRP release tracker

One row per release. Status: `not started` / `csv built` / `ingested`.
Add rows as you find more — this list (seeded from initial research, Sept
2026) is a starting point, not exhaustive.

| Pollster | Client | Approx. date | Where to look | Status |
|---|---|---|---|---|
| Focaldata/Prolific | — | Jun 2024 | focaldata.com/blog/focaldata-prolific-uk-general-election-mrp | not started |
| Ipsos | — | Jun 2024 | ipsos.com/en-uk/uk-opinion-polls/ipsos-election-mrp | not started |
| YouGov | Sky/Times | Jun 2024 | yougov.co.uk elections hub | not started |
| More in Common | — | 2026-01-04 | [January MRP](https://www.moreincommon.org.uk/research/more-in-commons-january-mrp/) | **ingested** (release_id=7) |
| More in Common | — | 2026-04-12 | [April MRP](https://www.moreincommon.org.uk/research/more-in-commons-april-mrp-2/) | **ingested** (release_id=8) |
| More in Common | — | 2026-07-19 | ["The Final MRP of Keir Starmer's Premiership"](https://www.moreincommon.org.uk/research/the-final-mrp-of-keir-starmers-premiership/) | **ingested** (release_id=6) |
| More in Common | — | 2025-04-20 | [April 2025 MRP](https://www.moreincommon.org.uk/research/more-in-commons-april-mrp/) | **ingested** (release_id=10) — source file has an explicit constituency-code column, no fuzzy matching needed |
| More in Common | — | 2025-07-05 | [July 2025 MRP](https://www.moreincommon.org.uk/research/more-in-commons-july-mrp/) | **ingested** (release_id=11) — source CSV is Mac Roman encoded, not UTF-8 (see docs/data_notes.md) |
| More in Common | — | 2025-09-28 | [September 2025 MRP](https://www.moreincommon.org.uk/research/more-in-commons-september-mrp/) | **ingested** (release_id=9) |
| More in Common | — | 2026-05-05 | [2026 London MRP](https://www.moreincommon.org.uk/research/more-in-commons-2026-london-mrp/) | not started — London-specific, check if it's Westminster-boundary (fits our schema) or a different geography first |
| More in Common | — | 2026-06-18 | ["An Immigration Salience Map of Britain"](https://www.moreincommon.org.uk/research/an-immigration-salience-map-of-britain/) | not started — check if this is a seat-level vote-share MRP or a thematic-only piece before treating it as one |
| More in Common | — | 2026-07-27 | ["What would Britain look like with proportional representation?"](https://www.moreincommon.org.uk/research/what-would-britain-look-like-with-proportional-representation/) | not started — likely a PR-scenario piece, not a standard FPTP seat MRP; check before ingesting |
| More in Common (Senedd) | — | 2026-04-20 draft / 2026-05-04 final | [2026 Senedd MRP](https://www.moreincommon.org.uk/research/more-in-commons-2026-senedd-mrp/) / [Final Senedd MRP](https://www.moreincommon.org.uk/research/more-in-common-final-senedd-mrp/) | **blocked** — uses the Senedd's *new post-2026-reform* multi-member constituencies, a third boundary set distinct from both 2024 Westminster and the 2021 Senedd seats Phase 5 already plans a crosswalk for. Needs its own new crosswalk (new Senedd boundaries -> pcon_code), not yet scoped anywhere. |
| More in Common (Holyrood) | — | 2026-04-20 draft / 2026-05-04 final | [2026 Holyrood MRP](https://www.moreincommon.org.uk/research/more-in-commons-2026-holyrood-mrp/) / [Final Holyrood MRP](https://www.moreincommon.org.uk/research/more-in-common-final-holyrood-mrp/) | **blocked** — Holyrood constituencies aren't Westminster seats either, and there's no Holyrood crosswalk table or plan in the schema at all yet (unlike Senedd, which at least has Phase 5 as a partial precedent) |
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
