-- ============================================================================
-- UK MRP & Local Elections Tracker — SQLite schema
-- ============================================================================
-- Design notes:
--   * Every table that can be joined to a constituency uses the ONS PCON code
--     (not the constituency name) as the join key, because names/ordering are
--     inconsistent across sources (this is the "Chorley problem" from the brief).
--   * Wards are versioned by boundary_year because ward geographies change
--     over time (a ward that existed in 2018 may not exist, or may have
--     different boundaries, in 2023).
--   * MRP data is stored long-format (one row per constituency per party per
--     release) rather than wide, because different pollsters report different
--     sets of parties.
-- ============================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Reference: Westminster constituencies (2024 boundaries, the current ones)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS constituencies (
    pcon_code       TEXT PRIMARY KEY,      -- ONS PCON code, e.g. E14001063
    pcon_name       TEXT NOT NULL,
    nation          TEXT NOT NULL,         -- England / Scotland / Wales / Northern Ireland
    region          TEXT,                  -- e.g. South East, West Midlands
    is_speaker_seat INTEGER DEFAULT 0,     -- Chorley = 1; often excluded from MRP/UNS models
    mp_2024         TEXT,
    party_2024      TEXT,
    majority_2024   INTEGER,
    electorate_2024 INTEGER,
    turnout_2024_pct REAL
);

-- ---------------------------------------------------------------------------
-- Reference: electoral wards, versioned by the boundary set they belong to
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS wards (
    ward_code       TEXT NOT NULL,         -- ONS WD code, e.g. E05014092
    ward_name       TEXT NOT NULL,
    boundary_year   INTEGER NOT NULL,      -- e.g. 2019, 2023 — the ONS lookup vintage this came from
    la_code         TEXT NOT NULL,
    la_name         TEXT NOT NULL,
    leap_council_id TEXT,                  -- Local Elections Archive Project's numeric council id
    leap_ward_id    TEXT,                  -- LEAP's numeric ward id (stable across years for a given ward)
    pcon_code       TEXT REFERENCES constituencies(pcon_code),
    pcon_name       TEXT,
    PRIMARY KEY (ward_code, boundary_year)
);

-- Some wards straddle a constituency boundary. Use this table when a ward's
-- electorate is genuinely split between >1 constituency; weight sums to 1.0
-- for a given (ward_code, boundary_year). If a ward sits wholly in one
-- constituency, a single row with weight = 1.0 is enough (or just rely on
-- wards.pcon_code directly).
CREATE TABLE IF NOT EXISTS ward_constituency_overlap (
    ward_code       TEXT NOT NULL,
    boundary_year   INTEGER NOT NULL,
    pcon_code       TEXT NOT NULL REFERENCES constituencies(pcon_code),
    weight          REAL NOT NULL,         -- 0-1, share of ward's electorate in this constituency
    PRIMARY KEY (ward_code, boundary_year, pcon_code)
);

-- ---------------------------------------------------------------------------
-- MRP releases
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mrp_releases (
    release_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    pollster        TEXT NOT NULL,         -- 'Electoral Calculus', 'More in Common', 'YouGov', ...
    client          TEXT,                  -- commissioning body, e.g. 'PLMR', if any
    fieldwork_start DATE,
    fieldwork_end   DATE,
    publish_date    DATE NOT NULL,
    sample_size     INTEGER,
    source_url      TEXT NOT NULL,         -- the pollster's article/blog page (human-readable)
    data_url        TEXT,                  -- direct link to the downloadable data file (csv/xlsx), if separate from source_url
    archive_url     TEXT,                  -- Wayback Machine snapshot, filled in if the live page dies
    methodology_notes TEXT,
    covers_scotland INTEGER DEFAULT 1,
    covers_wales    INTEGER DEFAULT 1,
    covers_ni       INTEGER DEFAULT 0,
    UNIQUE(pollster, publish_date, client)
);

CREATE TABLE IF NOT EXISTS mrp_constituency_results (
    release_id      INTEGER NOT NULL REFERENCES mrp_releases(release_id),
    pcon_code       TEXT NOT NULL REFERENCES constituencies(pcon_code),
    party           TEXT NOT NULL,         -- standardised party codes; see docs/party_codes.md
    vote_share_pct  REAL NOT NULL,
    rank            INTEGER,               -- 1 = projected winner, 2 = runner-up, etc. (compute on ingest)
    win_probability_pct REAL,              -- if the pollster publishes one (not all do)
    PRIMARY KEY (release_id, pcon_code, party)
);

-- Convenience view: simplified "who's projected to win" per release/seat
CREATE VIEW IF NOT EXISTS mrp_headline AS
SELECT
    r.release_id, r.pollster, r.publish_date, c.pcon_code, c.pcon_name,
    w.party  AS projected_winner,
    w.vote_share_pct AS winner_share,
    ch.party AS projected_runner_up,
    ch.vote_share_pct AS runner_up_share,
    ROUND(w.vote_share_pct - ch.vote_share_pct, 1) AS projected_margin
FROM mrp_releases r
JOIN mrp_constituency_results w  ON w.release_id = r.release_id AND w.rank = 1
JOIN constituencies c ON c.pcon_code = w.pcon_code
LEFT JOIN mrp_constituency_results ch ON ch.release_id = r.release_id
    AND ch.pcon_code = w.pcon_code AND ch.rank = 2;

-- ---------------------------------------------------------------------------
-- Local elections
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS local_election_events (
    election_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    la_code         TEXT NOT NULL,         -- ONS LAD code where available
    la_name         TEXT NOT NULL,
    leap_council_id TEXT,                  -- LEAP's numeric council id, e.g. Westminster = 20
    election_date   DATE NOT NULL,
    election_year   INTEGER NOT NULL,
    election_type   TEXT NOT NULL,         -- 'all-out' | 'thirds' | 'halves' | 'by-election'
    boundary_year   INTEGER,               -- links to wards.boundary_year in effect at this election
    source_url      TEXT,                  -- the raw data file actually fetched (e.g. LEAP's .csv)
    page_url        TEXT,                  -- the human-readable results page (e.g. LEAP's results/YYYY/ID/ page)
    UNIQUE(la_code, election_date)
);

CREATE TABLE IF NOT EXISTS local_election_ward_results (
    result_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    election_id     INTEGER NOT NULL REFERENCES local_election_events(election_id),
    ward_code       TEXT,                  -- may be NULL if not yet matched to an ONS ward code
    ward_name_raw   TEXT NOT NULL,         -- name as it appeared in the source, always populated
    boundary_year   INTEGER NOT NULL,
    seats_available INTEGER NOT NULL DEFAULT 1,
    candidate_name  TEXT,
    party           TEXT NOT NULL,
    votes           INTEGER,
    vote_share_pct  REAL,
    elected         INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS local_election_council_summary (
    election_id     INTEGER NOT NULL REFERENCES local_election_events(election_id),
    party           TEXT NOT NULL,
    seats_won       INTEGER NOT NULL,
    votes           INTEGER,
    vote_share_pct  REAL,
    PRIMARY KEY (election_id, party)
);

-- Party's share of ONE ward's vote, collapsing multiple same-party
-- candidates in a block-vote (multi-member) ward into a single row.
-- MUST be SUM, not AVG: every candidate's vote_share_pct is already a
-- share of the SAME ward-wide total-votes pot, so summing a party's
-- candidates recovers its true combined share of that pot (verified:
-- summing every candidate of every party in a 3-seat ward totals
-- exactly 100%). An earlier version used AVG here on the theory that it
-- corrected for "some parties stand fewer candidates than others" - it
-- did the opposite: it divided a party's total by however many
-- candidates THAT party fielded, so a full 3-candidate slate that swept
-- a ward got cut to a third of its true share while a lone minor-party
-- candidate in the same ward kept its full, undivided share. That's
-- what made council-level totals land far below 100% in wards with
-- multi-member councils (e.g. Southwark) - see docs/data_notes.md.
CREATE VIEW IF NOT EXISTS local_election_ward_party_avg AS
SELECT
    result_id_min.election_id, r.ward_code, r.ward_name_raw, r.boundary_year, r.party,
    SUM(r.vote_share_pct) AS ward_vote_share_pct,
    SUM(r.elected) AS seats_won_in_ward
FROM local_election_ward_results r
JOIN (SELECT MIN(result_id) AS result_id_min, election_id, ward_name_raw
      FROM local_election_ward_results GROUP BY election_id, ward_name_raw) result_id_min
      ON result_id_min.election_id = r.election_id AND result_id_min.ward_name_raw = r.ward_name_raw
GROUP BY r.election_id, r.ward_code, r.ward_name_raw, r.boundary_year, r.party;

-- ---------------------------------------------------------------------------
-- Senedd 2021 (old, pre-2024 Westminster-based boundaries) + crosswalk
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS senedd_2021_constituencies (
    senedd_code     TEXT PRIMARY KEY,      -- old Assembly constituency code
    senedd_name     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS senedd_2021_results (
    senedd_code     TEXT NOT NULL REFERENCES senedd_2021_constituencies(senedd_code),
    party           TEXT NOT NULL,
    votes           INTEGER,
    vote_share_pct  REAL,
    elected         INTEGER DEFAULT 0,
    PRIMARY KEY (senedd_code, party)
);

-- Electorate-weighted crosswalk: old Senedd (2021, pre-2024-boundary) seat ->
-- new 2024 Westminster constituency. weight = share of the OLD seat's
-- electorate that now falls inside the NEW pcon. Rows for one senedd_code
-- should sum to (approximately) 1.0 across all pcon_codes it overlaps.
-- This has to be built from boundary geometry (or the Boundary Commission's
-- own change documentation) — see docs/senedd_crosswalk.md for the method.
CREATE TABLE IF NOT EXISTS senedd2021_to_pcon24_crosswalk (
    senedd_code     TEXT NOT NULL REFERENCES senedd_2021_constituencies(senedd_code),
    pcon_code       TEXT NOT NULL REFERENCES constituencies(pcon_code),
    weight          REAL NOT NULL,
    PRIMARY KEY (senedd_code, pcon_code)
);

-- ---------------------------------------------------------------------------
-- GE2024 actual result — the baseline every MRP and local result gets
-- compared back to
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ge2024_results (
    pcon_code       TEXT NOT NULL REFERENCES constituencies(pcon_code),
    party           TEXT NOT NULL,
    candidate_name  TEXT NOT NULL,  -- part of the key: >1 candidate per seat can share party='Ind'
    votes           INTEGER,
    vote_share_pct  REAL,
    rank            INTEGER,
    source_url      TEXT,           -- per-constituency electionresults.parliament.uk page
    PRIMARY KEY (pcon_code, party, candidate_name)
);

-- ---------------------------------------------------------------------------
-- Helpful indexes
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_wards_pcon ON wards(pcon_code);
CREATE INDEX IF NOT EXISTS idx_mrp_results_pcon ON mrp_constituency_results(pcon_code);
CREATE INDEX IF NOT EXISTS idx_local_ward_results_election ON local_election_ward_results(election_id);
CREATE INDEX IF NOT EXISTS idx_local_events_la ON local_election_events(la_code);
