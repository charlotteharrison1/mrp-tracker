# Mapping 2021 Senedd results onto 2024 Westminster constituencies

## The problem

The 2021 Senedd election used constituencies based on the **pre-2024**
Westminster boundaries (each Senedd constituency = one old Westminster seat,
a rule that held until the Senedd's own 2026 reform introduced new,
larger multi-member constituencies — but the 2021 results you want predate
that, so they're still on the old single-member, old-boundary basis).

The 2024 general election introduced new Westminster boundaries. So a 2021
Senedd result can't be joined to a `pcon_code` in `constituencies` (which is
on 2024 boundaries) by name or code — the geography itself changed.
`senedd2021_to_pcon24_crosswalk` exists in the schema for exactly this: an
electorate-weighted mapping from old seat -> new seat(s).

## Recommended method: geometric overlay

This needs actual boundary polygons, not just a lookup table, because the
boundaries don't nest cleanly.

1. **Get both boundary sets as shapefiles/GeoJSON** from the ONS Open
   Geography Portal:
   - Pre-2024 (2019-vintage or similar) Westminster constituency boundaries
     — search "Westminster Parliamentary Constituencies boundaries" on
     geoportal.statistics.gov.uk, pick the vintage that matches the old
     Senedd-constituency basis (i.e. the boundaries in force in 2021).
   - 2024 Westminster constituency boundaries (final recommendations from
     the 2023 Boundary Commission for Wales review).
2. **Overlay with `geopandas`**: `geopandas.overlay(old_gdf, new_gdf,
   how="intersection")` gives you every old-seat/new-seat polygon
   intersection.
3. **Weight by population, not area.** A crude area-based split will be
   wrong wherever population density varies within the old seat (which is
   most of the time). Intersect the overlay polygons against LSOA- or
   OA-level population/electorate figures (ONS mid-year population
   estimates or the electorate figures from the 2023 boundary review
   itself) and weight by population within each intersection, not raw km².
4. **Load into `senedd2021_to_pcon24_crosswalk`**: for each old
   `senedd_code`, the weights across all `pcon_code`s it overlaps should sum
   to ~1.0.
5. **Sanity-check a handful by hand** against the Boundary Commission for
   Wales's own "which wards moved where" documentation from the 2023
   review — they publish exactly this kind of ward-movement commentary,
   which is a good cross-check even though it's not itself a machine-
   readable crosswalk.

## Faster (rougher) fallback

If the full geometric approach is more than you need right now: since
Senedd constituencies nest inside Welsh **local authorities**, and wards
nest inside both, you can approximate the crosswalk by going via wards —
`wards.pcon_code` (already loaded from the ONS ward lookup, Phase 1) tells
you which 2024 Westminster seat each ward is in. If you can establish which
wards made up each 2021 Senedd constituency (the Senedd used the same wards
as the old Westminster seats), you can weight by ward electorate instead of
doing a full polygon overlay. Less precise at the margins but much less
setup, and reuses data you already have.

## Applying the results

Once the crosswalk is loaded, a 2021 Senedd party vote share for a 2024
constituency is:

```sql
SELECT c.pcon_code, sr.party,
       SUM(sr.vote_share_pct * cw.weight) AS weighted_share_pct
FROM senedd2021_to_pcon24_crosswalk cw
JOIN senedd_2021_results sr ON sr.senedd_code = cw.senedd_code
JOIN constituencies c ON c.pcon_code = cw.pcon_code
WHERE c.pcon_code = ?
GROUP BY c.pcon_code, sr.party
ORDER BY weighted_share_pct DESC;
```

Flag any constituency where a single old seat contributes >90% of the
weight — for those the mapping is close to 1:1 and the result is fairly
trustworthy; where several old seats each contribute a meaningful share,
treat the weighted figure as indicative only and say so in any dashboard
that shows it.
