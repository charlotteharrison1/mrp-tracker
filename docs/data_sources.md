# Data source index

One row per data pull. This is the audit trail for "where did this number
come from" — update it every time a script fetches something new, even a
re-run with different parameters. See `docs/data_notes.md` for the
narrative/troubleshooting log (bugs found, format quirks); this file is
just the index.

| Date | Phase | Dataset | Source | Script | Params | Rows loaded | Tables |
|---|---|---|---|---|---|---|---|
| 2026-09-22 | 1 | Ward→Westminster constituency→LAD lookup, July 2024 vintage | ONS Open Geography Portal (ArcGIS FeatureServer): `WD24_PCON24_LAD24_UTLA24_UK_LU` — [dataset page](https://geoportal.statistics.gov.uk/datasets/ons::ward-to-westminster-parliamentary-constituency-to-lad-to-utla-july-2024-lookup-in-uk/about) | `01_fetch_ons_lookup.py` | `--suffix 24 --boundary-year 2024` | 650 constituencies, 8,396 wards | `constituencies`, `wards` |
| 2026-09-22 | 1 | LEAP council/year index (which councils have LEAP-hosted results for which years) | Local Elections Archive Project (Andrew Teale) — [elections index](https://www.andrewteale.me.uk/leap/elections-index/) | `02_fetch_leap_council_index.py` | — | 3,894 rows (3,714 LEAP-hosted / 180 external), 465 councils, years 2002–2026 | `data/leap_council_index.csv` (not yet in DB — it's an index file used by script 03) |
| 2026-09-22 | 2 | Ward-level local election results, per council/year, 2021–2025 | Local Elections Archive Project (Andrew Teale) — per-council CSVs, e.g. [Westminster 2022](https://www.andrewteale.me.uk/leap/results/2022/20/) | `03_fetch_leap_results.py` | `--from-index --years 2021 2022 2023 2024 2025` | 539 council/year events, 64,719 candidate/ward rows (94.0% with a non-null ONS ward code — but see below, that's not the same as being *placeable* into a constituency), 4,261 council-summary rows, across 269 councils | `local_election_events`, `local_election_ward_results`, `local_election_council_summary` |
| 2026-09-22 | — | `navigator_data.json` (derived, not fetched — exported from the DB above) | This repo's own DB, after fixing the wards join bug (see `docs/data_notes.md`) | `07_export_navigator_data.py` | — | 650 constituencies; 45,721/64,719 (70.7%) ward-level rows successfully placed into a constituency; 6,742 council-level aggregate rows; 0 GE2024 rows; 0 MRP rows (both await later phases) | `navigator_data.json` (repo root, feeds `index.html`) |
| 2026-09-22 | 4 | MRP release: Electoral Calculus / PLMR, published 2026-07-08, fieldwork 23–30 Jun 2026, n=5,500 | [Electoral Calculus blog post](https://www.electoralcalculus.co.uk/blogs/ec_vipoll_20260708.html) + [data tables xlsx](https://www.electoralcalculus.co.uk/blogs/DataTables_VIJul2026.xlsx) | `scripts/prep_electoral_calculus_xlsx.py` then `04_ingest_mrp_release.py` | "No TV" scenario (see docs/mrp_sources.md) | 632 constituencies (GB only, no NI), 4,655 party rows | `mrp_releases` (release_id=1), `mrp_constituency_results` |
| 2026-09-22 | 4 | MRP releases: More in Common, 6 releases spanning 2025-04-20 to 2026-07-19 | [research-type/mrp/ index](https://www.moreincommon.org.uk/research-type/mrp/), individual `wp-content/uploads` files — xlsx and one csv (see docs/mrp_sources.md for exact links) | `scripts/prep_more_in_common_xlsx.py` then `04_ingest_mrp_release.py` | One scenario per release (no TV split like Electoral Calculus); "Other" is a catch-all bucket; formats varied a lot across releases (see docs/data_notes.md) | 630–631 constituencies (GB only, no NI) per release, ~3,570–3,875 rows each | `mrp_releases` (release_id=6,7,8,9,10,11), `mrp_constituency_results` |
| 2026-09-22 | 4 | MRP release: Electoral Calculus / PLMR, published 2026-01-13, fieldwork 1–8 Dec 2025, n=5,596, fielded via Find Out Now | [blog post](https://www.electoralcalculus.co.uk/blogs/ec_vipoll_20260113.html) + [data tables xlsx](https://www.electoralcalculus.co.uk/blogs/DataTables_VIDec2025.xlsx) | `scripts/prep_electoral_calculus_xlsx.py` then `04_ingest_mrp_release.py` | "No TV" scenario; has a "YP" party column; source file has a non-party "cost of living issues" section that had to be explicitly excluded (see docs/data_notes.md) | 632 constituencies (GB only, no NI), 4,628 party rows | `mrp_releases` (release_id=5), `mrp_constituency_results` |
| 2026-09-22 | 4 | MRP release: Electoral Calculus / PLMR, published 2026-04-23, fieldwork 27 Mar–7 Apr 2026, n=5,599, fielded via Find Out Now | [blog post](https://www.electoralcalculus.co.uk/blogs/ec_vipoll_20260423.html) + [data tables xlsx](https://www.electoralcalculus.co.uk/blogs/DataTables_VIApr2026.xlsx) | `scripts/prep_electoral_calculus_xlsx.py` then `04_ingest_mrp_release.py` | "No TV" scenario; no "Restore" column existed yet in this file (`prep_electoral_calculus_xlsx.py` now reads columns by name, not position, specifically because of this) | 632 constituencies (GB only, no NI), 4,011 party rows | `mrp_releases` (release_id=4), `mrp_constituency_results` |
| 2026-09-22 | 3 | GE2024 actual result — every candidate, every constituency | UK Parliament / House of Commons Library official results database — [electionresults.parliament.uk](https://electionresults.parliament.uk/general-elections/6), `candidacies.csv` (the Commons Library's own briefing page, commonslibrary.parliament.uk, 403s on a plain fetch; this underlying data site doesn't) | `08_ingest_ge2024_results.py` | — | 4,515 candidate rows across all 650 constituencies; backfilled `constituencies.mp_2024/party_2024/majority_2024/electorate_2024/turnout_2024_pct/is_speaker_seat` for all 650 | `ge2024_results`, `constituencies` |
| 2026-09-22 | 2 | 2026 local election results (the initial `--years 2021 2022 2023 2024 2025` fetch omitted 2026, even though the README's own suggested command included it — caught when the user asked why a seat's most recent local result was 2022) | Local Elections Archive Project (Andrew Teale) | `03_fetch_leap_results.py` | `--from-index --years 2026` | 20 council/year events (Birmingham, Bolton, Bury, Camden, Essex, Hampshire, Manchester, Norfolk, North Tyneside, Norwich, Oldham, Rochdale, Salford, Stockport, Tameside, Trafford, Wakefield, Wandsworth, West Lancashire, Wigan) | `local_election_events`, `local_election_ward_results`, `local_election_council_summary` |

| 2026-09-22 | 4 | MRP releases reaching back to GE2024 and before: Ipsos (2024-06-18), YouGov (2024-07-03), Survation (2024-07-04), Focaldata/Best for Britain (2023-06-07) | See docs/mrp_sources.md for exact links | `04_ingest_mrp_release.py`, with `prep_ipsos_xlsx.py` / `prep_yougov_xlsx.py` / `prep_survation_xlsx.py` / `prep_bestforbritain_pdf.py` | Best for Britain's is PDF-only, extracted with pdfplumber and heavily validated (see docs/data_notes.md) — 584/632 seats passed; the other three are clean xlsx with 627-632/632 seats each | 627-632 constituencies per release (GB only, no NI) | `mrp_releases` (release_id=13,14,15,16), `mrp_constituency_results` |

| 2026-09-22 | — | 2026 local election results for 111 councils LEAP hadn't transcribed yet (128 of 136 councils now covered in total, vs. 20 at the start of this session) | Wikipedia's per-council "2026 X Council election" articles — [master index](https://en.wikipedia.org/wiki/2026_United_Kingdom_local_elections) | `09_fetch_wikipedia_council_index.py` then `10_fetch_wikipedia_local_results.py` (MediaWiki API, not raw page scraping — see docs/data_notes.md) | Ward tables detected structurally (Party+Candidate header columns), not by heading text, which varies a lot across councils | 111 councils, ~21,900 ward-level candidate rows, 93.5% matched to a real ward_code | `local_election_events`, `local_election_ward_results`, `local_election_council_summary` |
| 2026-09-22 | — | Backfilled real ONS `la_code`s onto all pre-existing LEAP-sourced events (was the placeholder `LEAP-<id>`) — a Phase 2 leftover from the original README, resolved while reconciling the Wikipedia and LEAP sources against each other | This repo's own DB (`wards.la_name` from Phase 1) | one-off fix, not a script — see docs/data_notes.md for the exact matching + collision-safety logic | 248 of 269 distinct LEAP council names matched and updated, across all years 2021-2026; 21 genuinely unmatchable county-level names left as placeholder | `local_election_events` |

## Remaining known gaps (updated 2026-09-22 during a full accuracy audit —
## this section had gone stale after Phases 3/4 were actually completed;
## the entries below are current, not aspirational)

**Done, despite what an older version of this section said**:
`ge2024_results` and `constituencies.mp_2024`/`party_2024`/`majority_2024`/
`electorate_2024`/`turnout_2024_pct`/`is_speaker_seat` (Phase 3, all 650
constituencies); `mrp_releases`/`mrp_constituency_results` (Phase 4, 15
releases); `local_election_events.la_code` (backfilled from LEAP's
placeholder `LEAP-<id>` to real ONS codes for 248 of 269 councils — 21
remain on the placeholder, all genuinely unmatchable two-tier English
county councils not present in `wards.la_name`, which only has districts).

**Still genuinely open:**
- `local_election_events.election_type` — 656 of 670 events (97.9%) are
  still `'unknown'`. LEAP's CSV doesn't say all-out/thirds/halves, only
  the results *page* text does; Wikipedia-sourced events do detect this
  (`detect_election_type()` in `10_fetch_wikipedia_local_results.py`), so
  the gap is entirely on the LEAP side. Cosmetic — nothing currently
  reads this field for a calculation — but worth knowing before relying
  on it for anything.
- 6.3% of `local_election_ward_results` rows (5,444 of 86,593) have no
  `ward_code` (source didn't supply one, or it didn't match a known
  ward) — untraceable to a constituency until name-matched or
  transcribed by hand.
- `senedd_2021_constituencies`, `senedd_2021_results`,
  `senedd2021_to_pcon24_crosswalk` — empty. Phase 5 was scoped and
  documented (`docs/senedd_crosswalk.md`) but never actually built; only
  discussed with the user, not executed. Nothing in `index.html`
  currently references these tables, so their absence isn't visibly
  broken anywhere — it's a missing feature, not a bug.
- `ward_constituency_overlap` — **populated 2026-09-22** (790 rows, 388
  wards) from a live query against the source ArcGIS layer's `SPLIT_WARD`
  flag: 390 of 8,396 wards (4.6%) are genuinely split across 2
  (occasionally 3 or 4) constituencies; 2 of those 390 turned out
  degenerate (flagged split but only 1 distinct `PCON24CD` in practice)
  and were skipped. `01_fetch_ons_lookup.py`'s `wards` table still only
  assigns each ward to ONE constituency (its primary key is `(ward_code,
  boundary_year)` — one row per ward, not one row per (ward,
  constituency) pair; changing that is a bigger schema change than this
  fix needed), but `07_export_navigator_data.py`'s `build_ward_pcon_map()`
  now reads `ward_constituency_overlap` first and falls back to
  `wards.pcon_code` only for the ~8,000 non-split wards — so every
  constituency a split ward touches gets that ward's local election
  results in the navigator now, not just whichever one
  `01_fetch_ons_lookup.py` happened to load last. Each split ward is
  weighted an equal 1/n toward each constituency's own average (no
  population data available to weight it precisely by how many electors
  actually live on each side of the boundary) — a deliberate
  approximation, not the full population-weighted geometric overlay
  described in `docs/senedd_crosswalk.md`, which is still not attempted.
  The two older CLI tools (`05_compare_mrp_vs_actuals.py`,
  `06_constituency_dashboard.py`) were NOT updated with this fix — they
  still silently use `wards.pcon_code`'s single assignment, per their
  existing "superseded by the navigator" caveat.
