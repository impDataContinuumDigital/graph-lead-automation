"""
Stage 0b: Given the businesses.csv from scraper_maps.py (which has a
"website" column but no email), visit each website and try to find a
contact email. Output is already in the raw scraped format clean.py
expects, so you can feed it straight into clean.py next.

Usage:
    python scraper_emails.py businesses.csv raw_scrape.csv
"""
import sys
import re
import csv
import time
import random
import requests
from pathlib import Path
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import pandas as pd
from scrapling.fetchers import StealthyFetcher

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# junk/noise emails that show up in tracking pixels, theme boilerplate, etc.
BLOCKED_DOMAINS = {
    "sentry.io", "wixpress.com", "godaddy.com", "example.com",
    "yourdomain.com", "domain.com", "schema.org",
}
BLOCKED_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")

CONTACT_PATHS = ["", "contact", "contact-us", "about", "about-us"]
TEAM_PATHS = ["team", "our-team", "meet-the-team", "leadership", "management", "staff"]
# Pages to check FIRST for a link that actually points to the team page
# -- more reliable than guessing URL paths, since site structures vary a lot.
NAV_CHECK_PATHS = ["", "about", "about-us", "company", "our-company"]
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LeadResearchBot/1.0)"}

# Link text worth following to find the real team page.
TEAM_LINK_RE = re.compile(
    r"\b(our\s+team|meet\s+the\s+team|meet\s+our\s+team|team|our\s+company|"
    r"leadership|management|staff|who\s+we\s+are|our\s+people)\b", re.I
)

# Titles worth finding a named person for -- decision-makers most
# relevant for B2B outreach in construction / property management.
TITLE_KEYWORDS = [
    "owner", "president", "vice president", "vp", "ceo", "cfo", "coo",
    "founder", "co-founder", "project manager", "managing director",
    "general manager", "principal", "director",
]
TITLE_RE = re.compile("|".join(re.escape(k) for k in TITLE_KEYWORDS), re.I)

# Matches "John Smith" or "John A. Smith" style names -- a heuristic,
# not a guarantee. Will occasionally false-positive on things like
# "Contact Us" (capitalized phrase) or miss single-name mentions.
NAME_RE = re.compile(r"\b[A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+){1,2}\b")

# Used to find the ACTUAL team page link from About page nav/links,
# instead of guessing fixed URL paths (which misses non-standard URLs).
TEAM_LINK_RE = re.compile(r"our\s*team|meet\s*the\s*team|our\s*company|leadership|management\s*team|^team$|who\s*we\s*are|staff", re.I)


def clean_emails(raw_emails, page_domain):
    good = []
    for e in raw_emails:
        e = e.strip().lower().rstrip(".")
        domain = e.split("@")[-1]
        if domain in BLOCKED_DOMAINS:
            continue
        if e.endswith(BLOCKED_EXTENSIONS):
            continue
        good.append(e)
    return good


def pick_best_email(emails, page_domain):
    if not emails:
        return ""
    # prefer generic business inboxes, then anything on the site's own domain
    priority_prefixes = ["info@", "contact@", "office@", "sales@", "hello@"]
    for prefix in priority_prefixes:
        for e in emails:
            if e.startswith(prefix):
                return e
    same_domain = [e for e in emails if e.endswith(f"@{page_domain}")]
    if same_domain:
        return same_domain[0]
    return emails[0]


def find_email_on_site(website: str) -> str:
    if not website:
        return ""
    parsed = urlparse(website if website.startswith("http") else f"https://{website}")
    base = f"{parsed.scheme}://{parsed.netloc}"
    page_domain = parsed.netloc.replace("www.", "")

    found = []
    for path in CONTACT_PATHS:
        url = urljoin(base + "/", path)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=8)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")

            # mailto links first -- most reliable signal
            for a in soup.select('a[href^="mailto:"]'):
                found.append(a["href"].replace("mailto:", "").split("?")[0])

            # fallback: regex over visible text
            found.extend(EMAIL_RE.findall(soup.get_text(" ")))
        except Exception:
            continue

        if found:
            break  # stop once a page yields something
        time.sleep(random.uniform(0.5, 1.2))

    found = clean_emails(found, page_domain)
    return pick_best_email(found, page_domain)


def discover_team_url(base: str) -> str:
    """Look at the About page's actual links for a real Team/Our Company
    page URL, instead of guessing fixed paths -- catches non-standard
    URLs that TEAM_PATHS would miss."""
    for path in ["about", "about-us", ""]:
        try:
            page = StealthyFetcher.fetch(urljoin(base + "/", path), headless=True, network_idle=True)
            if not page or page.status != 200:
                continue
        except Exception:
            continue
        for link in page.css("a"):
            href = link.attrib.get("href", "")
            text = (link.text or "").strip()
            if TEAM_LINK_RE.search(text) or TEAM_LINK_RE.search(href):
                return page.urljoin(href)
    return ""


def find_team_contact(website: str):
    """Best-effort: look for a named decision-maker (owner/VP/PM/etc.)
    on the site's actual Team/About page, and try to find their title
    and an email tied to them. Returns (name, position, email) -- any
    may be "". Uses Scrapling's adaptive element-finding (find_similar/
    find_ancestor) instead of hand-guessed DOM depth, since every site
    nests its team cards differently."""
    if not website:
        return "", "", ""
    parsed = urlparse(website if website.startswith("http") else f"https://{website}")
    base = f"{parsed.scheme}://{parsed.netloc}"
    page_domain = parsed.netloc.replace("www.", "")

    discovered = discover_team_url(base)
    urls_to_try = ([discovered] if discovered else []) + [urljoin(base + "/", p) for p in TEAM_PATHS]

    for url in urls_to_try:
        try:
            page = StealthyFetcher.fetch(url, headless=True, network_idle=True)
            if not page or page.status != 200:
                continue
        except Exception:
            continue

        title_elements = page.find_by_regex(TITLE_RE, first_match=False, partial=True)
        if not title_elements:
            time.sleep(random.uniform(0.5, 1.0))
            continue

        # once we've found ONE title (e.g. "Project Manager"), every other
        # team card's title sits at the same DOM depth/tag/parent chain --
        # find_similar grabs them all in one shot instead of guessing paths
        all_titles = list(title_elements)
        try:
            all_titles.extend(title_elements[0].find_similar())
        except Exception:
            pass

        candidates = []
        seen = set()
        for title_el in all_titles:
            container = title_el.find_ancestor(lambda e: 0 < len(e.text or "") < 300) or title_el.parent
            key = container.generate_css_selector
            if key in seen:
                continue
            seen.add(key)

            name = _find_name_in(container)
            if not name:
                continue

            mailto = container.css('a[href^="mailto:"]::attr(href)').get()
            person_email = ""
            if mailto:
                candidate = mailto.replace("mailto:", "").split("?")[0].strip()
                if clean_emails([candidate], page_domain):
                    person_email = candidate

            position_text = (title_el.text or "").strip()[:60]
            candidates.append((name, position_text, person_email))

        if candidates:
            with_email = [c for c in candidates if c[2]]
            return with_email[0] if with_email else candidates[0]

        time.sleep(random.uniform(0.5, 1.0))

    return "", "", ""


def _find_name_in(container) -> str:
    """Prefer names in heading/anchor tags or image alt text over blind
    flattened-text search, since that's where site builders put names."""
    for sel in ["h1", "h2", "h3", "h4", "a"]:
        for el in container.css(sel):
            m = NAME_RE.search(el.text or "")
            if m and m.group(0).lower() not in (k.lower() for k in TITLE_KEYWORDS):
                return m.group(0).strip()

    for alt in container.css("img::attr(alt)").getall():
        m = NAME_RE.search(alt or "")
        if m and m.group(0).lower() not in (k.lower() for k in TITLE_KEYWORDS):
            return m.group(0).strip()

    m = NAME_RE.search(container.text or "")
    if m and m.group(0).lower() not in (k.lower() for k in TITLE_KEYWORDS):
        return m.group(0).strip()

    return ""


OUTPUT_FIELDS = ["contact_name", "contact_position", "email", "contact_email", "company", "source_url", "phone", "address"]


def run(input_csv: str, output_csv: str):
    df = pd.read_csv(input_csv)

    # Resume support: if output_csv already exists (e.g. from an
    # interrupted previous run), skip websites already processed.
    done_urls = set()
    out_path = Path(output_csv)
    file_exists = out_path.exists()
    if file_exists:
        try:
            prev = pd.read_csv(output_csv)
            done_urls = set(prev["source_url"].dropna().astype(str))
            print(f"Resuming: {len(done_urls)} sites already done, skipping those.")
        except Exception:
            file_exists = False  # empty/corrupt file, start fresh with header

    f = open(output_csv, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
    if not file_exists:
        writer.writeheader()

    found_count = 0
    skipped = 0
    for i, r in df.iterrows():
        website = str(r.get("website", "")).strip()
        if website in done_urls:
            continue
        print(f"[{i+1}/{len(df)}] {r.get('business_name','')} -> {website or 'no website'}")

        company_email = find_email_on_site(website)
        contact_name, contact_position, contact_email = find_team_contact(website)
        if contact_name:
            print(f"  -> found contact: {contact_name} ({contact_position or 'title unknown'})" + (f", {contact_email}" if contact_email else ""))

        # prefer the company inbox as the main Email column; fall back
        # to the person's email if that's all we found
        final_email = company_email or contact_email

        row = {
            "contact_name": contact_name,
            "contact_position": contact_position,
            "email": final_email,
            "contact_email": contact_email,
            "company": r.get("business_name", ""),
            "source_url": website,
            "phone": r.get("phone", ""),
            "address": r.get("address", ""),
        }
        # write if we found EITHER an email OR at least a contact
        # name -- a named decision-maker without an email is
        # still useful for outreach research, not a dead end
        if final_email or contact_name:
            writer.writerow(row)
            f.flush()
            found_count += 1
        else:
            skipped += 1
        time.sleep(random.uniform(1.0, 2.0))

    f.close()
    print(f"\nDone. Found emails for {found_count} businesses this run (skipped {skipped} with no email) -> {output_csv}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scraper_emails.py businesses.csv raw_scrape.csv")
        sys.exit(1)
    run(sys.argv[1], sys.argv[2])