"""
Stage 2: Push a cleaned CSV into the Raw_Leads Google Sheet.

Usage:
    python push_raw.py output_cleaned.csv

Requires a Google service account JSON (see README.md) shared as an
editor on the target spreadsheet.
"""
import sys
import os
import pandas as pd
import gspread

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # find config.py one level up
from config import GOOGLE_CREDS_FILE, SPREADSHEET_NAME, RAW_WORKSHEET, RAW_COLUMNS


def ensure_headers(ws, expected_headers):
    """Add missing columns in-place without creating a second header row."""
    current_headers = ws.row_values(1)
    if not current_headers:
        ws.insert_row(expected_headers, index=1, value_input_option="RAW")
        return

    for index, header in enumerate(expected_headers):
        if index < len(current_headers) and current_headers[index] == header:
            continue
        if header not in current_headers:
            ws.insert_cols([[header]], col=index + 1, value_input_option="RAW")
            current_headers.insert(index, header)
            continue
        raise RuntimeError(
            f"Cannot safely reconcile the '{RAW_WORKSHEET}' headers. "
            f"Expected '{header}' in column {index + 1}, found '{current_headers[index]}'."
        )


def push_raw(csv_path: str):
    df = pd.read_csv(csv_path)

    gc = gspread.service_account(filename=GOOGLE_CREDS_FILE)
    sh = gc.open(SPREADSHEET_NAME)
    ws = sh.worksheet(RAW_WORKSHEET)

    # Check row 1 specifically rather than "is the whole sheet empty" --
    # leftover formatting on a supposedly-empty sheet can make
    # get_all_values() look non-empty even with no real data, silently
    # skipping the header write. Checking row 1's actual content avoids that.
    if ws.row_values(1) != RAW_COLUMNS:
        ensure_headers(ws, RAW_COLUMNS)
        last_col = chr(ord("A") + len(RAW_COLUMNS) - 1)
        ws.format(
            f"A1:{last_col}1",
            {
                "textFormat": {"bold": True},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
            },
        )
        # row 2 may carry stale bold formatting left over from before this
        # sheet had a proper header -- reset it explicitly so it doesn't
        # look like a second header.
        ws.format(f"A2:{last_col}2", {"textFormat": {"bold": False}})

    # Skip emails already sitting in Raw_Leads -- important for repeated/
    # daily runs, since scraper_emails.py accumulates results across runs
    # (cleaned.csv can contain leads pushed on a previous day). Without
    # this, re-running push_raw.py would duplicate every prior lead.
    existing_emails = {
        str(e).strip().lower()
        for e in ws.col_values(RAW_COLUMNS.index("email") + 1)[1:]
        if str(e).strip()
    }  # skip header and never treat blank emails as duplicates
    before = len(df)
    normalized_emails = df["email"].fillna("").astype(str).str.strip().str.lower()
    # Preserve contact-only leads: blank values are not a deduplication key.
    df = df[(normalized_emails == "") | ~normalized_emails.isin(existing_emails)]
    skipped = before - len(df)

    rows = df[RAW_COLUMNS].fillna("").values.tolist()
    phone_idx = RAW_COLUMNS.index("phone")
    for row in rows:
        if row[phone_idx] and not str(row[phone_idx]).startswith("'"):
            row[phone_idx] = "'" + str(row[phone_idx])  # force text, avoids formula parsing of leading "+"

    if rows:
        existing_row_count = len(ws.get_all_values())
        # RAW (not USER_ENTERED) so values like "+1 737-510-4833" are
        # stored as literal text instead of Sheets trying to parse the
        # leading "+" as the start of a formula.
        # insert_data_option="OVERWRITE" so new rows fill existing empty
        # cells instead of being inserted -- inserted rows inherit
        # formatting (like bold) from the row directly above them.
        ws.append_rows(rows, value_input_option="RAW", insert_data_option="OVERWRITE")
        last_col = chr(ord("A") + len(RAW_COLUMNS) - 1)
        start_row = existing_row_count + 1
        end_row = existing_row_count + len(rows)
        ws.format(
            f"A{start_row}:{last_col}{end_row}",
            {
                "textFormat": {"bold": False},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
            },
        )
    print(f"Pushed {len(rows)} new rows to '{RAW_WORKSHEET}' (skipped {skipped} already there)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python push_raw.py output_cleaned.csv")
        sys.exit(1)
    push_raw(sys.argv[1])
