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
- **Phase 3 (GE2024) loaded, with two bugs caught before it shipped.**
  Source: `electionresults.parliament.uk/general-elections/6/candidacies.csv`
  (official House of Commons Library results DB — the Commons Library's own
  briefing page, commonslibrary.parliament.uk, 403s on a plain fetch, but
  this underlying data site doesn't, no UA spoofing needed). 4,515 candidate
  rows, all 650 constituencies backfilled.
  1. `ge2024_results`' original schema had `PRIMARY KEY (pcon_code, party)`
     — broke immediately since 100 constituencies have >1 independent
     candidate, all coded `party='Ind'`. Fixed by adding `candidate_name`
     to the key (and a `source_url` column) — safe schema change since the
     table was still empty.
  2. The Speaker's seat (Chorley, Lindsay Hoyle) has both `Main party
     abbreviation` and `Main party name` blank in the source — he's not
     coded as "independent" either, since he stands as "Speaker seeking
     re-election," a distinct category. `08_ingest_ge2024_results.py` first
     mapped this to `party='Unknown'`, then was fixed to check the source's
     own `Candidate is standing as Commons Speaker` flag and use `'Speaker'`
     — but since `party` is part of the primary key, re-running after that
     fix inserted a *new* row instead of replacing the old `Unknown` one,
     leaving a stale duplicate (4,516 rows instead of 4,515) until caught by
     comparing the loader's own printed count against the exported JSON's
     count. The script now does a full `DELETE FROM ge2024_results` before
     each load instead of upserting, since it always loads the whole
     dataset in one pass anyway — upserting only makes sense when a
     normalisation rule can change a row's key, which happened here.
- **Fuzzy constituency-name matching (`04_ingest_mrp_release.py`,
  `scripts/prep_electoral_calculus_xlsx.py`) had a real collision bug**:
  `rapidfuzz.fuzz.WRatio` scores "Devon South West" equally (95) against
  both "South Devon" and "South West Devon" — two genuinely different real
  seats — because WRatio leans on subset-containment logic that can't tell
  "same tokens, different order" from "some tokens missing." Left alone,
  this would have silently written one pollster's numbers for "South West
  Devon" onto "South Devon" instead (or vice versa, depending on dict/list
  ordering). Fixed by taking WRatio's top candidates within 3 points of
  each other and re-ranking those specifically by `token_sort_ratio` (which
  requires the same token *set*, so it correctly prefers the exact match) —
  token_sort_ratio isn't used as the primary scorer because it wrongly
  penalises genuine subset matches like "Hull East" -> "Kingston upon Hull
  East" (drops to 56 vs WRatio's 90). **If any other release's constituency
  names produce a suspiciously identical score for two candidates, that's
  this bug pattern recurring — check with token_sort_ratio, don't just
  trust the top WRatio hit.**
- **`prep_electoral_calculus_xlsx.py` had a real bug that would have
  silently loaded survey-issue data as fake political parties.** The Jan
  2026 release (`DataTables_VIDec2025.xlsx`) has a third section — "Q3.
  Top Three Cost-of-living Issues" (Energy/Food/Tax/Housing/Wages/Fuel/
  Childcare/Student Loan) — sharing the same header row as the No-TV
  seat table, positioned right after it. The original column-mapping
  logic took "everything from the second 'Seat Name' to the end of the
  row" as the No-TV table's columns, which swept this section up too —
  each issue would have been ingested as a minor party with a 50%+ "vote
  share." Fixed by bounding each table to end right after its own
  "Predicted Winner" sentinel column instead of at the row's end or the
  next table's start. **Always check the prep script's printed "Party
  columns not in the fixed map" list before trusting an ingest** — if
  something on it isn't obviously a party name, stop and inspect the
  sheet directly (`openpyxl`, print the header row) before proceeding.
- **More in Common's release files are wildly inconsistent in structure**
  across just 6 releases: sheet names vary (`Results`, `Full results`,
  `Seat summaries`), one release (Apr 2025) includes an explicit
  `Constituency code` column (bonus — skips fuzzy matching entirely) while
  the rest don't, value format varies (decimal fraction 0.07 in xlsx files
  vs percentage string "7%" in at least one csv), and the July 2025 CSV is
  **Mac Roman encoded**, not UTF-8 (byte `0x99` meant 'ô'; cp1252 would
  have silently decoded it as '™' instead of raising an error — neither
  single-byte codec reliably fails on a wrong guess, so this can't be
  fully automatic; if a future release still looks garbled, check the raw
  bytes directly rather than guessing another codec). `04_ingest_mrp_release.py`
  computes rank from vote share itself, so a text `Winner`/`Change`/`GE_winner`
  column is never used — just make sure it's excluded from the party-columns
  scan (`NON_PARTY_COLS`), not treated as a fake party.
- **Best for Britain's June 2023 MRP (PDF-only source) had a real data-corruption
  bug, caught before shipping.** `scripts/prep_bestforbritain_pdf.py` extracts
  a constituency table from a PDF (no CSV/xlsx available at all) via
  `pdfplumber`. PDF text-wrapping corrupts rows in ways that don't always
  throw a parse error:
  1. A long winner/runner-up value ("scottish_national_party") wraps
     across cells and its tail bleeds into the next cell, contaminating
     the Labour vote-share ("rty 23.1%" instead of "23.1%") — the digits
     are still extractable via regex, column count stays correct.
  2. A long seat name ("Dumfriesshire, Clydesdale and Tweeddale") wraps
     onto a second line inside its own cell, and pdfplumber splits that
     into two separate cells.
  3. **The real bug**: my region-detection allowlist was missing "Eastern"
     (this PDF's actual label; I'd assumed "East of England"), so every
     Eastern-region row falsely looked "contaminated" and got needlessly
     run through the wrap-repair path — actively corrupting otherwise-
     clean rows. Fallout: 5 real seats (Bedford, Cambridge, Glasgow
     South, Leeds Central and Headingley, Birmingham Hodge Hill and
     Solihull North) each ended up with TWO different source rows both
     claiming to be them, and the ingest script's upsert silently kept
     whichever came last — meaning the DB held arbitrary, likely-wrong
     numbers for 5 real seats with no error or warning anywhere.
  4. Also reused the plain-WRatio fuzzy match here before remembering the
     tie-break fix from `04_ingest_mrp_release.py`'s `best_match()` (see
     the "Devon South West" entry above) — same failure pattern
     ("Glasgow South" vs "Glasgow South East"), same fix, just written
     twice. **If a third fuzzy-matching call site ever gets added, pull
     `best_match()` out into somewhere shared instead of copying it
     again.**
  Fixed by correcting the region allowlist AND adding a permanent safety
  net: after matching, any real constituency claimed by more than one
  source row is rejected entirely (can't tell which is right) rather than
  silently keeping one. Final yield: 584 of 632 possible seats (92%)
  passed both the name-match and vote-share-sum validation; the rest are
  logged with the specific reason, not silently dropped.
- **Filled the 2026 local elections gap with a new Wikipedia-based source**
  (`scripts/09_fetch_wikipedia_council_index.py` + `10_fetch_wikipedia_local_results.py`).
  136 English councils held elections on 7 May 2026; LEAP only had 20
  transcribed as of this session. Wikipedia's per-council election
  articles (filled in within days by the WikiProject UK elections
  community) cover the rest, in a consistent wikitable format per ward.
  Real findings along the way:
  1. **Scraping raw Wikipedia page URLs directly (even just HEAD requests)
     trips bot detection within 2-3 rapid requests** (403s start
     immediately). The MediaWiki API (`action=query` for batched
     existence checks up to 50 titles/call, `action=parse` for page
     content) is the actual sanctioned bulk-access path and doesn't have
     this problem, though it still needs pacing (429s hit at even a few
     requests/second on `action=query` with `list=search`) — retry with
     exponential backoff, ~1 req/sec.
  2. **The council summary page's links don't point at the election
     article** — they go to the council's own general page (e.g.
     "Barnet_London_Borough_Council"), and the election article is
     reliably at "2026_<that title>_election" for MOST councils, but not
     all (e.g. "St_Helens_Council" -> the real article is
     "2026_St_Helens_**Borough**_Council_election", with "Borough"
     inserted) — handled with a search-API fallback for the ones that
     fail direct construction.
  3. **Ward-level table structure, confirmed consistent across single-
     member (Oxford) and multi-member (Camden, 3-seat) wards**: under an
     `<h2>Ward results</h2>` heading, each ward is an `<h3>` heading
     immediately followed by a wikitable; real candidate rows have
     exactly 6 cells (blank colour-swatch + party/candidate/votes/%/±%),
     which is what distinguishes them from the header/Turnout/Majority/
     hold-summary rows (all different cell counts). The winning
     candidate(s) are wrapped in `<b>` — confirmed this correctly
     identifies all N winners in an N-seat ward, not just one.
  4. **Real, serious bug caught before it corrupted the DB**: 20 councils
     already had 2026 data from LEAP. The Wikipedia scraper's constructed
     `la_code` (a REAL ONS code) didn't match LEAP's placeholder
     `LEAP-<id>` code for the same council/date, so it created a *second*,
     duplicate election event instead of recognising the overlap — found
     immediately (Camden) by comparing row counts against the existing
     LEAP data, which also revealed the actual vote data matches exactly
     between both independent sources (a good cross-validation, incidentally).
     Fixed by backfilling LEAP's placeholder la_codes with real ONS codes
     first (resolving the "LEAP-<id> placeholder" debt the README flagged
     back in Phase 2 for the whole project, not just 2026 — 248 of 269
     distinct LEAP council names matched with high confidence, applied
     retroactively to all years 2021-2026), then having the Wikipedia
     script skip any council already covered for 2026 once la_codes are
     comparable. Also fixed LEAP's 2026 placeholder date ('2026-05-01')
     to the real national polling day ('2026-05-07') for the 20 affected events.
  5. **21 LEAP council names are genuinely unmatchable to a real la_code
     and were deliberately left as placeholders**: county councils
     (Essex, Kent, Hampshire, Surrey, Norfolk, etc.) — counties aren't in
     `wards.la_name` at all (only their constituent districts are), so
     there's no correct target to match to. The naive fuzzy matcher
     initially matched several of these to a same-named DISTRICT within
     the county (e.g. "Norfolk" -> "North Norfolk", "Gloucestershire" ->
     "South Gloucestershire") — caught via a collision check (two
     different county/district LEAP names both trying to claim the same
     target la_code for the same date) before it was applied, not after.
  6. **The heading text above each ward-results section isn't consistent
     across councils** — 'Ward results' (Oxford, Camden), 'Results by
     ward' (Islington, Bradford, Leeds), plain 'Results' (Hull — which
     ALSO has an unrelated 'Results summary' heading, so a naive substring
     match on "result" would grab the wrong section), or 'Candidates'
     with no ward-related word at all (Cambridge). Chasing each variant by
     name is a losing game. Fixed by detecting ward tables STRUCTURALLY
     instead: scan every `<h3>`/`<h4>` in the whole document regardless of
     its parent heading, and accept the table right after it if that
     table's own header row contains both "Party" and "Candidate" — a
     combination that doesn't occur on the Incumbents/Council-composition/
     infobox tables elsewhere on the same pages, so it's self-validating
     rather than a guess.
  7. **The column SET isn't consistent either** — most councils' tables
     have Party/Candidate/Votes/%/±% (a swing column), but Bradford's
     omit ±% entirely (Party/Candidate/Votes/% only). A hardcoded "must
     have exactly 6 cells" check silently discarded every row on any
     table missing that column (zero rows extracted, indistinguishable
     from "no ward table found" without checking further) even though the
     table itself was completely fine. Fixed by mapping columns from the
     header row's own text (index of "Party", "Candidate", "Votes", "%")
     instead of assuming fixed positions, with a fixed +1 offset for the
     leading blank colour-swatch cell that data rows have but the header
     row doesn't.
  8. **The most serious bug of the batch, and the one hardest to catch**:
     script 09's la_code matching didn't exclude English county councils
     the way the LEAP backfill (point 5, this file) already learned to.
     "Hampshire" and "Norfolk" (counties) each matched a same-named
     DISTRICT uniquely — "East Hampshire", "North Norfolk" — with no
     COLLISION to trip the existing safety net, since collision-detection
     only catches two different names competing for one target, not one
     name confidently landing on the wrong unique target. Both got
     scraped and loaded successfully under the wrong la_code/la_name
     before this was noticed by manually cross-checking loaded councils
     against known target names, at which point it was already sitting
     in the database as if it were real district-level data. Deleted both
     corrupted events and fixed by reusing the same county exclusion list
     in `09_fetch_wikipedia_council_index.py` directly (not just the
     LEAP backfill), so county names never get a la_code candidate in the
     first place, structural match or not. **Lesson for next time: a
     collision check only catches AMBIGUOUS wrong matches, never
     CONFIDENT wrong ones — when a whole category of names (counties)
     structurally can't have a correct target, exclude the category
     explicitly rather than trusting the matcher's own confidence score.**

  Final result after all of the above: **128 of 136 councils have 2026
  local election data** (111 via Wikipedia, the rest already via LEAP,
  now on real la_codes throughout — 131 total distinct la_codes with 2026
  data once you count the 3 counties still correctly sitting on a
  placeholder, see point 5); 93.5% of the ~21,900 new ward-level rows
  matched a real ward_code. The remaining 8 councils are genuinely out of
  scope for this schema, not a bug: 6 English county councils (Essex,
  Hampshire, Norfolk, Suffolk, East Sussex, West Sussex — counties aren't
  in `wards.la_name`) plus East Surrey and West Surrey, two brand-new
  unitary authorities formed by Surrey's 2025 local government
  reorganisation that don't exist yet in the July-2024-vintage ONS ward
  lookup this project has loaded (Phase 1 would need a newer vintage to
  cover them).
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
- **2026-09-22 — "why don't a council's local-election vote shares add up
  to 100%?" — three separate, compounding bugs, all in how per-ward
  candidate rows get rolled up to a council-level party share:**
  1. **Multi-candidate-per-party wards were AVERAGED, not SUMMED.**
     `local_election_ward_party_avg` (the view that collapses a block-vote
     ward's several same-party candidates into one row per party) used
     `AVG(vote_share_pct)`. Every candidate's `vote_share_pct` is already a
     share of the SAME ward-wide total-votes pot, so the correct way to
     recover a party's combined share of that pot is to SUM its
     candidates, not average them (verified: summing every candidate of
     every party in a real 3-seat Southwark ward totals exactly 100.0%).
     AVG instead divided a party's total by however many candidates IT
     fielded — a full 3-candidate slate that swept a ward got cut to a
     third of its true share, while a lone minor-party candidate in the
     same ward kept its full, undivided share. This is what made
     council-level totals land far BELOW 100% specifically in councils
     with multi-member wards (e.g. Southwark, ~37% for a ward with a
     3-candidate LD slate + a 1-candidate Green). Fixed: view now uses
     `SUM(vote_share_pct) AS ward_vote_share_pct` (renamed from
     `avg_vote_share_pct` since it's no longer an average). The original
     comment justified AVG by analogy to "the same approach Opinium used
     for their 2026 London aggregation" — untraceable and, empirically,
     wrong for this data; trust the arithmetic check, not an uncited
     analogy.
  2. **A party's cross-ward average only counted wards it contested.**
     `07_export_navigator_data.py`'s `fetch_local_council()` averaged a
     party's ward shares over `COUNT(DISTINCT ward_code)` **for that
     party**, i.e. only the wards where it fielded a candidate. A party
     that skipped its weakest ward isn't "unmeasured" there — it got 0% —
     so excluding that ward from its own denominator inflates its average
     (this is what made Gorton and Denton / Manchester read as 111% total:
     Workers and independents skipped their weaker wards and their
     averages rode up on the wards they *did* contest). Fixed by rewriting
     `fetch_local_council()` in Python: build the full ward universe per
     (pcon, la_name, election_date) first, then average every party over
     that SAME universe, treating a ward the party didn't contest as 0%
     there rather than dropping it from the average.
  3. **Wikipedia's own "%" column isn't the same metric as LEAP's.** For
     the 111 councils loaded via `10_fetch_wikipedia_local_results.py`
     (2026-09-22 entry above), the per-candidate `vote_share_pct` was
     read directly from Wikipedia's own "%" table column. In multi-member
     wards, that column is each candidate's share of valid BALLOT PAPERS
     (turnout) — not of the combined votes pot LEAP's numbers are shares
     of. Since voters in a 3-seat ward can each cast up to 3 votes,
     summing Wikipedia's own percentages across a full ward totals
     roughly 3x100% (confirmed: a real Southwark 2026 ward summed to
     283%), not 100%. `local_election_council_summary` (the separate
     council-wide summary table) already self-derived its own
     `vote_share_pct` from `votes` instead of trusting Wikipedia's column
     — the ward-level table just hadn't been given the same treatment.
     Fixed the same way: `10_fetch_wikipedia_local_results.py` now
     computes each candidate's `vote_share_pct` as
     `100 * votes / sum(votes in that ward)`, discarding Wikipedia's own
     percentage entirely; a one-off migration (not re-scraping — the raw
     `votes` values were already correct) recomputed all 17,719 already-
     loaded Wikipedia ward-result rows the same way.

  **After all three fixes**: 1437 of 1471 (pcon, council, election-date)
  combinations across the whole dataset sum to within 1 percentage point
  of 100%. The remaining ~34 are genuine, explicable exceptions, not
  bugs: uncontested wards (very common in Welsh/Scottish local elections
  — a seat "elected unopposed" has no recorded vote to attribute to any
  party, so it correctly drags that ward's contribution below 100%
  instead of being silently excluded) and a handful of places with
  non-partisan/unusual electoral systems (City of London, Isles of
  Scilly). Not chased further — same standard applied elsewhere in this
  project (e.g. Survation's genuinely-blank seats): a printed/documented
  exception beats a forced fit.
  **Lesson for next time**: when a metric is supposed to sum to a known
  total (100% of a vote), and it doesn't, verify against raw per-ward
  candidate data by hand before trusting either the SQL or a comment's
  justification for it — three unrelated bugs were hiding behind one
  plausible-sounding comment ("avoids double-counting... same approach
  [X] used").
