"""
Prep helper (not part of the numbered pipeline): converts a More in Common
MRP release into the CSV shape 04_ingest_mrp_release.py expects. One row
per constituency, one column per party (full party names, not
abbreviations), a single scenario (no tactical-voting variant), an
"Other" catch-all, and text columns ("Winner", "Change", "GE_winner") not
used here — 04_ingest_mrp_release.py computes rank from vote share itself.

Handles BOTH formats seen across releases: .xlsx (a "Results" sheet,
values as decimal fractions like 0.07) and .csv (values as percentage
strings like "7%", R-style dotted column names like
"Scottish.National.Party..SNP." instead of "Scottish National Party
(SNP)"). Column names are matched after stripping all punctuation, so
both spellings resolve to the same party.

Usage:
    python scripts/prep_more_in_common_xlsx.py --file /path/to/release.xlsx --out data/mrp_prepped/mic_2026-07-19.csv
    python scripts/prep_more_in_common_xlsx.py --file /path/to/release.csv --out data/mrp_prepped/mic_2025-07-05.csv
"""
import argparse
import csv
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "uk_elections.db"

PARTY_MAP = {
    "conservative": "Con", "labour": "Lab", "liberal democrat": "LD",
    "reform uk": "RUK", "the green party": "Green", "green party": "Green", "green": "Green",
    "scottish national party snp": "SNP", "snp": "SNP",
    "plaid cymru": "PC", "other": "Other",
}
NON_PARTY_COLS = {"constituency", "winner", "change", "ge winner", "ge_winner", "margin"}
CODE_COL_KEYS = {"constituency code"}


def normalise_key(name):
    """Strip all punctuation (dots, parens) so 'Scottish.National.Party..SNP.'
    and 'Scottish National Party (SNP)' both resolve to the same key."""
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def parse_share(val):
    """Handles both a decimal fraction (0.07, from xlsx) and a percentage
    string ('7%', from at least one release's csv) — returns a vote_share_pct
    (0-100 scale) or None if empty/not a number."""
    if val is None or val == "":
        return None
    if isinstance(val, str):
        val = val.strip()
        if val.endswith("%"):
            try:
                return float(val[:-1])
            except ValueError:
                return None
        try:
            val = float(val)
        except ValueError:
            return None
    return round(val * 100, 3)


def read_rows(path, sheet):
    if path.suffix.lower() == ".csv":
        # Both cp1252 and mac_roman are single-byte codecs that accept
        # almost every byte value, so neither reliably raises on the WRONG
        # guess — this can't be fully automatic. mac_roman is what one real
        # release actually needed (0x99 meant 'ô', which cp1252 would
        # silently decode as '™' instead without erroring). If a future
        # release still looks garbled after this, open it in a hex/text
        # editor and check the actual byte values rather than guessing.
        try:
            with open(path, encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))
        except UnicodeDecodeError:
            with open(path, encoding="mac_roman") as f:
                rows = list(csv.reader(f))
    else:
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb[sheet]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help=".xlsx or .csv release file")
    parser.add_argument("--sheet", default="Results", help="sheet name, xlsx only")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    path = Path(args.file)
    rows = read_rows(path, args.sheet)

    header = [str(c).strip() if c else "" for c in rows[0]]
    norm_header = [normalise_key(h) for h in header]
    seat_col = norm_header.index("constituency")
    code_col = next((i for i, k in enumerate(norm_header) if k in CODE_COL_KEYS), None)
    if code_col is not None:
        print("  Found an explicit constituency-code column.")
    # Even when the source has its own code column, don't trust it blindly:
    # the April 2025 release's codes for 5 Scottish seats (Ayr Carrick and
    # Cumnock, Berwickshire Roxburgh and Selkirk, Central Ayrshire,
    # Kilmarnock and Loudoun, West Aberdeenshire and Kincardine) turned out
    # to be pre-final ONS numbering, not the ones in our `constituencies`
    # table — same known issue as prep_ipsos_xlsx.py/prep_yougov_xlsx.py,
    # just missed here originally (found 2026-09-22 auditing the DB for
    # orphan pcon_codes). Validate against the DB and fall back to blank
    # pcon_code (name-only) for 04_ingest_mrp_release.py's own fuzzy
    # matcher, which will be an exact string match for cases like this.
    con = sqlite3.connect(DB_PATH)
    known_codes = set(r[0] for r in con.execute("SELECT pcon_code FROM constituencies"))
    con.close()
    n_code_mismatch = 0

    party_cols = {}  # our_code -> column index
    unrecognised = []
    for i, key in enumerate(norm_header):
        if not key or key in NON_PARTY_COLS or key in CODE_COL_KEYS:
            continue
        if key in PARTY_MAP:
            party_cols[PARTY_MAP[key]] = i
        else:
            unrecognised.append(header[i])
            party_cols[header[i].strip()] = i
    if unrecognised:
        print(f"  Party columns not in the fixed map, carried through verbatim: {unrecognised}")

    out_rows = []
    n_seats = 0
    for row in rows[1:]:
        if not row or not row[seat_col]:
            continue
        seat_name = row[seat_col]
        pcon_code = row[code_col].strip() if code_col is not None and row[code_col] else ""
        if pcon_code and pcon_code not in known_codes:
            n_code_mismatch += 1
            pcon_code = ""
        n_seats += 1
        for our_party, i in party_cols.items():
            share = parse_share(row[i]) if i < len(row) else None
            if share:
                out_rows.append({"pcon_code": pcon_code, "pcon_name": seat_name, "party": our_party,
                                  "vote_share_pct": share, "win_probability_pct": ""})

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["pcon_code", "pcon_name", "party", "vote_share_pct", "win_probability_pct"])
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"Wrote {len(out_rows)} party rows across {n_seats} seats to {out_path}")
    if n_code_mismatch:
        print(f"  ({n_code_mismatch} seats had a pcon_code not in our DB, falling back to name matching)")


if __name__ == "__main__":
    sys.exit(main())
