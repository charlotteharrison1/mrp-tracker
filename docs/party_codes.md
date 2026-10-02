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

## `Indept.` → `Ind` (found 2026-10-02, during a data-quality/sourcing audit)

Electoral Calculus's 2024-06-26 release (`release_id=25`, their final
pre-GE2024 poll) had its own column literally headed "Indept." — distinct
from "Indep/ Other", which the SAME release ALSO has as a separate column.
`prep_electoral_calculus_xlsx.py`'s generic "carry through any unrecognised
column verbatim" fallback (`other_party_cols`) picked it up uncanonicalised,
so 14 rows landed in the DB as `party='Indept.'` with no source-code
mapping at all — not wrong data, just never normalised.

Checked what it actually measures before picking a target code: every seat
carrying it (Islington North, Rochdale, Birmingham Ladywood, Leicester
East, Chingford and Woodford Green, Ilford North, ...) is a seat with a
specific, named independent candidate — Corbyn, Galloway, the pro-Gaza
independents — standing separately from whatever "Other" already covers
in the same release. That's the same thing `08_ingest_ge2024_results.py`
and `10_fetch_wikipedia_local_results.py` already code as `Ind` for these
same people's actual results, so `Ind` is the correct target, not
`Ind/Other` — later Electoral Calculus releases reuse "Indep/ Other" as a
genuinely combined independents+minor-parties bucket, which `Indept.` is
not (it only ever appeared alongside a separate "Other" column, never
alongside "Indep/ Other").

Fixed as: a one-off `UPDATE mrp_constituency_results SET party='Ind' WHERE
party='Indept.'` on the already-loaded DB, plus `indept.` added to
`SPECIAL_PARTY_COLS` and the per-row column loop in
`prep_electoral_calculus_xlsx.py` so a future re-run lands on `Ind`
directly.

## Generic catch-all codes can still mean one real, large contender

Found the same day, while auditing the navigator's "top contenders"
banner: `Other`, `Ind/Other`, and `Minor` are generic pollster bucket
names, but what they contain isn't always a genuine mix of small
also-ran candidates — for a seat with one dominant non-major-party
figure (Chorley's Speaker convention; Islington North/Rochdale's named
independents once a pollster stops tracking them individually), the
*entire* bucket can be that one real, choosable thing, polling 30-60%.
Confirmed by cross-checking Islington North across every tracked
Electoral Calculus release: the same real independent/Your Party
standing is coded `Indept.` → `Ind/Other` → `Minor` → `Yp` as the
pollster's own labelling evolved over 2024–2026, while `Other` covers it
on every release from every OTHER pollster for that same seat. A code-
based exclusion list can't tell "one real big thing" apart from "a
genuine assortment of small things" sharing the same label — so
`index.html`'s `computeTopContenders` no longer excludes any of these by
code; the gap-based elbow method is left to do that job on magnitude
alone, same as it already does for every named party.

`Yp` (Your Party, Jeremy Corbyn's registered party as of its 2025-10-15
Electoral Calculus appearance) has no dedicated hex in `PARTY_COLOURS`
yet and isn't itself a catch-all — it falls through to the deterministic
hashed fallback palette, same as any other minor party code, which is
fine but worth knowing if it starts showing up more widely.

## `Your` → `Your Party` (found the same day, same audit)

The exact Grn/Green problem recurring for a new party: some Wikipedia
council-results infoboxes abbreviate Your Party's own column to "Your"
instead of spelling it out, and `10_fetch_wikipedia_local_results.py`'s
`party_code()` falls back to the raw (lowercased-then-restripped) source
text for anything not in `PARTY_MAP` — so 6 council-summary rows and 11
ward-level rows landed as `party='Your'` rather than `Your Party`, split
across different councils (Birmingham, Hampshire, Salford, Stockport,
Tameside, West Lancashire) with no overlap against the 6/10 rows already
correctly coded `Your Party` elsewhere, so no duplicate-key collision when
merging them. All values involved are under 1.3% vote share, so this
never changed which party led anywhere — found by auditing the full
distinct-party-code list, not because it affected a result.

Fixed as: `UPDATE local_election_council_summary` and `UPDATE
local_election_ward_results SET party='Your Party' WHERE party='Your'` on
the already-loaded DB, plus `"your"`/`"your party"` added to
`10_fetch_wikipedia_local_results.py`'s `PARTY_MAP`. Not to be confused
with `Your Bradford Independent group`, a genuinely different local
group whose name happens to start with the same word.
