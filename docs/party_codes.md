# Party code aliases across sources

`schema.sql` says party columns use "standardised party codes; see
docs/party_codes.md" — this is that doc. It didn't exist until now; the
inconsistency below was found while building the navigator's colour/legend
logic (`index.html`'s `PARTY_COLOURS`), not from a deliberate design.

**The problem**: LEAP (local election results) and the official
electionresults.parliament.uk GE2024 data (Phase 3) use different
abbreviations for the same party. Nothing in the pipeline normalises them —
`local_election_ward_results.party` stores whatever LEAP's CSV says
verbatim, and Phase 3's loader (when built) will store whatever the
official "Main party abbreviation" field says. Querying across both without
knowing this will silently split one party into two rows/lines.

| Party | LEAP code | Official GE2024 code |
|---|---|---|
| Conservative | `C` | `Con` |
| Green | `Grn` | `Green` |
| Workers Party of Britain | `Workers` | `WPB` |
| Heritage Party | `Heritage` | `HPUK` |
| Yorkshire Party | `Yorks` | `Yrks` |

Confirmed consistent (no alias needed): `Lab`, `LD`, `RUK`, `SNP`, `PC`,
`Ind`, `TUSC`, `Alba`.

**Current mitigation**: `index.html`'s `PARTY_COLOURS` map lists both
spellings for the ones found so far, so at least the colour/swatch is
consistent even though they're technically different string values. This
is a band-aid, not a fix — a party with an alias still shows as two
separate legend entries / table rows if both sources are loaded for the
same constituency.

**Real fix, not done yet**: normalise `party` to one canonical code at
ingest time (pick LEAP's shorter forms as canonical, since local election
data is already loaded and bigger to re-migrate) — add a lookup table or
dict in `03_fetch_leap_results.py` and whatever Phase 3 script loads
GE2024 results, and re-export `navigator_data.json` after. Only worth
doing once Phase 3 is actually loaded and party rows from both sources
start appearing together in the same constituency view — no observable
bug yet since `ge2024_results` is still empty.
