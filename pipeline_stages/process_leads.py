"""
Stage 3: Read Raw_Leads, run validation + dedup + classification +
template assignment, write results to Leads_Ready.

Usage:
    python process_leads.py

This reads directly from the Raw_Leads worksheet and writes directly
to Leads_Ready -- no CSV in between. Run it on a schedule (cron) or
by hand whenever new rows have landed in Raw_Leads.
"""
import sys
import os
import gspread
import pandas as pd
import dns.resolver
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # find config.py one level up
from config import (
    GOOGLE_CREDS_FILE, SPREADSHEET_NAME, RAW_WORKSHEET, READY_WORKSHEET,
    READY_COLUMNS, CLASSIFICATION_RULES, DEFAULT_CLASSIFICATION,
    CHECK_MX_RECORDS, DROP_UNMATCHED, AUTOMATION_KEYWORDS,
    CONSTRUCTION_SAAS_KEYWORDS,
)

_mx_cache = {}


def ensure_headers(ws, expected_headers):
    """Add new output columns without inserting a second header row."""
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
            f"Cannot safely reconcile the '{READY_WORKSHEET}' headers. "
            f"Expected '{header}' in column {index + 1}, found '{current_headers[index]}'."
        )


def has_mx_record(domain: str) -> bool:
    if not domain:
        return False
    if domain in _mx_cache:
        return _mx_cache[domain]
    try:
        dns.resolver.resolve(domain, "MX")
        _mx_cache[domain] = True
    except Exception:
        _mx_cache[domain] = False
    return _mx_cache[domain]


def check_website_status(url: str) -> str:
    """Real HTTP check, not just 'do we have a URL on file'. Sites can
    go down between when they were scraped and when you actually reach
    out, so this is worth checking fresh each run."""
    if not url or not isinstance(url, str) or not url.strip():
        return "No Website"
    try:
        resp = requests.get(
            url, timeout=8, allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; LeadResearchBot/1.0)"},
        )
        return "Active" if 200 <= resp.status_code < 400 else "Broken"
    except Exception:
        return "Broken"


def validate(row) -> str:
    if not CHECK_MX_RECORDS:
        return "valid_syntax_only"
    return "valid" if has_mx_record(row["domain"]) else "invalid_domain"


def classify(row) -> str:
    text = f"{row['company']} {row['domain']}".lower()
    for category, keywords in CLASSIFICATION_RULES:
        if any(kw in text for kw in keywords):
            return category
    return DEFAULT_CLASSIFICATION
    # --- To swap in LLM classification later ---
    # replace the loop above with a call to the Claude API, e.g.
    # classify_with_llm(row["company"], row["domain"]) -> category string
    # keep the TEMPLATE_MAP lookup in run() unchanged.


def assign_template_type(row) -> str:
    """Choose one outreach template without an LLM.

    Website is the default for each industry. Explicit automation terms take
    priority, then construction software/SaaS terms; this avoids assigning a
    specialised campaign merely because a company has a website.
    """
    industry = row.get("classification", "")
    text = " ".join(
        str(row.get(field, ""))
        for field in ("company", "domain", "source_url")
    ).lower()

    has_automation_signal = any(keyword in text for keyword in AUTOMATION_KEYWORDS)
    if industry == "construction":
        if has_automation_signal:
            return "CONSTRUCTION_AUTOMATION"
        if any(keyword in text for keyword in CONSTRUCTION_SAAS_KEYWORDS):
            return "CONSTRUCTION_SAAS"
        return "CONSTRUCTION_WEBSITE"
    if industry == "property_management":
        return "PROPERTY_AUTOMATION" if has_automation_signal else "PROPERTY_WEBSITE"
    return ""


def parse_city_state(address: str):
    """Best-effort split of a Maps-style address string into city/state.
    Google Maps addresses are typically "Street, City, Region, Country,
    Postal Code" but this varies -- treat this as a starting point you
    may need to spot-check, not a guaranteed-accurate parser."""
    if not address or not isinstance(address, str):
        return "", ""
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if len(parts) >= 4:
        return parts[-4], parts[-3]  # City, Region (skipping Country, Postal)
    if len(parts) == 3:
        return parts[-3], parts[-2]
    if len(parts) == 2:
        return parts[0], ""
    return "", ""


def print_summary(total_raw: int, duplicates_removed: int, qualified: int):
    rate = (qualified / total_raw * 100) if total_raw else 0.0
    print("\n" + "=" * 40)
    print("PROCESSING SUMMARY")
    print("=" * 40)
    print(f"Total Raw Leads:     {total_raw}")
    print(f"Duplicates Removed:  {duplicates_removed}")
    print(f"Qualified Leads:     {qualified}")
    print(f"Qualification Rate:  {rate:.1f}%")
    print("=" * 40)


def run():
    gc = gspread.service_account(filename=GOOGLE_CREDS_FILE)
    sh = gc.open(SPREADSHEET_NAME)
    raw_ws = sh.worksheet(RAW_WORKSHEET)
    ready_ws = sh.worksheet(READY_WORKSHEET)

    raw = pd.DataFrame(raw_ws.get_all_records())
    if raw.empty:
        print("Raw_Leads is empty, nothing to process.")
        return
    raw.columns = [str(c).strip().lower() for c in raw.columns]

    if "email" not in raw.columns:
        print(f"ERROR: no 'email' column found in Raw_Leads. Actual headers: {list(raw.columns)}")
        print("Check row 1 of the Raw_Leads tab -- it must have a column named exactly 'email' (lowercase).")
        return

    total_raw = len(raw)

    # Deduplicate only real emails. Pandas treats all blanks as equal, which
    # previously discarded almost every contact-only lead.
    normalized_emails = raw["email"].fillna("").astype(str).str.strip().str.lower()
    raw = raw[(normalized_emails == "") | ~normalized_emails.duplicated(keep="first")].copy()
    dupes_in_batch = total_raw - len(raw)

    # skip emails already present in Leads_Ready
    existing = pd.DataFrame(ready_ws.get_all_records())
    already_processed = 0
    if not existing.empty and "Email" in existing.columns:
        already = set(existing["Email"].astype(str).str.lower())
        before_already = len(raw)
        raw = raw[~raw["email"].str.lower().isin(already)]
        already_processed = before_already - len(raw)

    duplicates_removed = dupes_in_batch + already_processed

    if raw.empty:
        print_summary(total_raw, duplicates_removed, 0)
        return

    raw["validation_status"] = raw.apply(validate, axis=1)
    raw = raw[raw["validation_status"] == "valid"] if CHECK_MX_RECORDS else raw

    raw["classification"] = raw.apply(classify, axis=1)
    raw["template_type"] = raw.apply(assign_template_type, axis=1)

    if DROP_UNMATCHED:
        raw = raw[raw["classification"] != DEFAULT_CLASSIFICATION]

    if raw.empty:
        print_summary(total_raw, duplicates_removed, 0)
        return

    # build rows in the exact Leads_Ready column order
    out_rows = []
    for i, r in raw.reset_index(drop=True).iterrows():
        city, state = parse_city_state(r.get("address", ""))
        website = r.get("source_url", "")
        print(f"[{i+1}/{len(raw)}] Checking website: {website or '(none)'}")
        status = check_website_status(website)
        out_rows.append([
            r.get("company", ""),          # Company Name
            website,                       # Website
            r.get("email", ""),            # Email
            r.get("contact_name", ""),     # Contact Name
            r.get("contact_position", ""), # Contact Position
            r.get("contact_email", ""),    # Contact Email 
            r.get("phone", ""),            # Phone
            r.get("address", ""),          # Address
            city,                           # City
            state,                          # State
            r.get("linkedin_url", ""),     # LinkedIn URL
            r.get("classification", ""),   # Industry
            r.get("template_type", ""),    # Template Type
            status,                        # Website Status
            "",                            # Primary Campaign (manual/future)
            "",                            # Secondary Campaign (manual/future)
            "",                            # Notes
        ])
        

    phone_idx = READY_COLUMNS.index("Phone")
    for row in out_rows:
        if row[phone_idx] and not str(row[phone_idx]).startswith("'"):
            row[phone_idx] = "'" + str(row[phone_idx])  # force text, avoids formula parsing

    last_col_idx = len(READY_COLUMNS) - 1
    last_col = chr(ord("A") + last_col_idx) if last_col_idx < 26 else "Z"

    if ready_ws.row_values(1) != READY_COLUMNS:
        ensure_headers(ready_ws, READY_COLUMNS)
        ready_ws.format(
            f"A1:{last_col}1",
            {
                "textFormat": {"bold": True},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
            },
        )
        ready_ws.format(f"A2:{last_col}2", {"textFormat": {"bold": False}})

    if out_rows:
        existing_row_count = len(ready_ws.get_all_values())
        # RAW so phone numbers like "+1 737-510-4833" don't get parsed
        # as formulas by Sheets. insert_data_option="OVERWRITE" so new
        # rows fill existing empty cells instead of being inserted --
        # inserted rows inherit formatting (like bold) from the row
        # directly above them.
        ready_ws.append_rows(out_rows, value_input_option="RAW", insert_data_option="OVERWRITE")
        start_row = existing_row_count + 1
        end_row = existing_row_count + len(out_rows)
        ready_ws.format(
            f"A{start_row}:{last_col}{end_row}",
            {
                "textFormat": {"bold": False},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
            },
        )

    print_summary(total_raw, duplicates_removed, len(out_rows))


if __name__ == "__main__":
    run()
