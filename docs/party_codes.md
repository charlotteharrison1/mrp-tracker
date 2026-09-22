# Party code aliases across sources

`schema.sql` says party columns use "standardised party codes; see
docs/party_codes.md" — this is that doc. It didn't exist until now; the
inconsistency below was found while building the navigator's colour/legend
logic (`index.html`'s `PARTY_COLOURS`), not from a deliberate design.

**The problem (found while building the navigator's colour/legend logic,
confirmed for real 2026-09-22 once the combined MRP-vs-actual-vs-local
chart made it visible: Gorton and Denton's legend showed both `Grn` and
`Green` as separate swatches)**: LEAP/Wikipedia (local election results)
and the official electionresults.parliament.uk GE2024 data used different
abbreviations for the same party, and nothing in the pipeline normalised
them — each loader stored whatever its own source spelled the code as.
Querying across both without knowing this silently splits one party into
two rows/lines/legend entries.

| Party | LEAP/local code | Official GE2024/MRP code | Canonical (fixed) |
|---|---|---|---|
| Conservative | `C` | `Con` | `Con` |
| Green | `Grn` | `Green` | `Green` |
| Workers Party of Britain | `Workers` | `WPB` | `Workers` |
| Heritage Party | `Heritage` | `HPUK` | `Heritage` |
| Yorkshire Party | `Yorks` (also a stray `Yorkshire`) | `Yrks` | `Yorks` |

Confirmed consistent (no alias needed): `Lab`, `LD`, `RUK`, `SNP`, `PC`,
`Ind`, `TUSC`, `Alba`.

**Fixed 2026-09-22.** Canonical form is picked per-party for whichever
existing spelling reads more clearly out of context — NOT a blanket
"always LEAP" or "always official" rule — since `index.html` displays
these codes as literal text (`partyChip()` does `escapeHtml(p)`, no
full-name expansion), so a bare `C` on its own in a legend is genuinely
less readable than `Con`, while `Workers`/`Heritage` are clearer than
`WPB`/`HPUK`. This reverses the original draft plan on this page (which
proposed keeping LEAP's forms everywhere) — that plan optimised for
smaller migration effort, but once every table was actually loaded, the
"how many distinct-value rows need remapping" cost turned out similar
either way (MRP only uses ~12 broad categories, so remapping its `Con`
back to `C` would've been just as cheap as remapping local's `C` forward
to `Con`), so readability is what decided the direction instead.

Applied as: a one-off migration on the already-loaded DB (UPDATE the
`party` column directly in `local_election_ward_results`,
`local_election_council_summary`, `ge2024_results`, plus
`constituencies.party_2024`), and a `PARTY_MAP` dict added to each
ingest script so future re-runs land on the canonical form without
needing another migration — `03_fetch_leap_results.py` (LEAP took the
raw CSV party column completely unprocessed before this),
`08_ingest_ge2024_results.py`'s `normalise_party()`, and
`10_fetch_wikipedia_local_results.py`'s existing `PARTY_MAP` (which
already mapped Wikipedia's full party names to short codes, just to the
wrong short codes for these five).

`index.html`'s `PARTY_COLOURS` map still lists both spellings for each —
harmless now that no ingested row actually uses the old form, and cheap
insurance against a future source reintroducing one before its ingest
script gets the same `PARTY_MAP` treatment.
