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

## Columns not yet sourced (tracked here so gaps are visible)

- `constituencies.mp_2024`, `party_2024`, `majority_2024`, `electorate_2024`,
  `turnout_2024_pct`, `is_speaker_seat` — need Phase 3 (Electoral Commission
  GE2024 results).
- `ge2024_results` — empty, needs Phase 3.
- `local_election_events.la_code` — currently a placeholder (`LEAP-<id>`),
  not a real ONS LAD code. Per README Phase 2, needs backfilling by
  fuzzy-matching `la_name` against `wards.la_name` from Phase 1.
- `local_election_events.election_type` — all rows currently `'unknown'`;
  LEAP's CSV doesn't say all-out/thirds/halves, only the results *page*
  text does (per README Phase 2).
- ~6% of `local_election_ward_results` rows have no `ward_code` (LEAP
  didn't supply/match one) — untraceable to a constituency until
  name-matched or transcribed.
- `senedd_2021_constituencies`, `senedd_2021_results`,
  `senedd2021_to_pcon24_crosswalk` — empty, needs Phase 5.
- `ward_constituency_overlap` — empty; ~400 split wards from the Phase 1
  load need this (see `docs/data_notes.md`, 2026-09-22 entry).
- `mrp_releases`, `mrp_constituency_results` — empty, needs Phase 4
  (tracked release-by-release in `docs/mrp_sources.md`).
