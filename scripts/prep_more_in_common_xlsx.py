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
    "plaid cymru": "PC", "other": "Other", "restore britain": "Restore",
}
NON_PARTY_COLS = {"constituency", "winner", "change", "ge winner", "ge_winner", "margin"}
CODE_COL_KEYS = {"constituency code"}


def normalise_key(name):
    """Strip all punctuation (dots, parens) so 'Scottish.National.Party..SNP.'
    and 'Scottish National Party (SNP)' both resolve to the same key."""
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def fix_mojibake(name):
    """Repairs the specific, mechanical 'UTF-8 bytes decoded as Latin-1'
    corruption (found 2026-10-01: the Sep 2026 release had 'Ynys MÃ´n'
    baked into the xlsx itself for 'Ynys Môn', upstream of us — not
    something we caused by reading it wrong). Round-tripping a STRING
    through latin-1 encode -> utf-8 decode only succeeds if it really was
    mojibake in the first place (ordinary text raises UnicodeDecodeError
    and is returned unchanged), so this is safe to run unconditionally
    on every seat name rather than only the one known-bad case."""
    try:
        return name.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return name


def parse_share(val, already_pct):
    """Handles a decimal fraction (0.07, most xlsx releases), a percentage
    string ('7%', at least one release's csv), AND a bare already-a-
    percentage number (8.2 meaning 8.2%, the Sep 2026 release — no
    fraction, no '%' suffix, nothing to distinguish it from the other
    xlsx releases except that its values are the wrong order of
    magnitude if treated as a fraction). `already_pct` is decided once
    per file by scan_is_already_percent(), not per cell, since a bare
    number is genuinely ambiguous without that file-wide context."""
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
    return round(val, 3) if already_pct else round(val * 100, 3)


def scan_is_already_percent(rows, party_cols):
    """A vote-share FRACTION can never exceed 1.0 - if any party column
    anywhere in the file has a bare numeric value over 1.5 (a buffer
    against float noise right at 1.0), every bare number in this file
    must already be on a 0-100 scale, not a 0-1 fraction. Decided once
    for the whole file, not per cell/row - found 2026-10-01 when a new
    More in Common release switched to already-percent values with
    nothing else to flag it."""
    for row in rows[1:]:
        for i in party_cols.values():
            v = row[i] if i < len(row) else None
            if isinstance(v, (int, float)) and v > 1.5:
                return True
    return False


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

    already_pct = scan_is_already_percent(rows, party_cols)
    if already_pct:
        print("  Values are already on a 0-100 scale (not 0-1 fractions) - detected from a value > 1.5.")

    out_rows = []
    n_seats = 0
    for row in rows[1:]:
        if not row or not row[seat_col]:
            continue
        seat_name = fix_mojibake(row[seat_col])
        pcon_code = row[code_col].strip() if code_col is not None and row[code_col] else ""
        if pcon_code and pcon_code not in known_codes:
            n_code_mismatch += 1
            pcon_code = ""
        n_seats += 1
        for our_party, i in party_cols.items():
            share = parse_share(row[i], already_pct) if i < len(row) else None
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
