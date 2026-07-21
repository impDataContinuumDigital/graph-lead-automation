"""
Stage 0b: Given the businesses.csv from scraper_maps.py, visit each website,
traverse team/about/contact routes using Scrapling's StealthyFetcher, extract text,
and use Groq API to parse decision-makers. ONLY real scraped emails are saved.
"""
import sys
import re
import csv
import time
import json
import random
from pathlib import Path
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import pandas as pd
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from scrapling.fetchers import StealthyFetcher
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

BLOCKED_DOMAINS = {
    "sentry.io", "wixpress.com", "godaddy.com", "example.com",
    "yourdomain.com", "domain.com", "schema.org",
}
BLOCKED_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")

CONTACT_PATHS = ["", "contact", "contact-us"]
TEAM_ROUTES = [
    "team",
    "our-team",
    "leadership",
    "management",
    "staff",
    "about",
    "about-us",
]

LLM_PROMPT = """
You are an expert lead generator. Analyze the text extracted from a company's team/about page.
Identify the HIGHEST-RANKING decision-maker based on this priority order:
1. Owner / Founder / Co-Founder
2. President / CEO / COO
3. Vice President / Director
4. General Manager / Operations Manager / Project Manager / Property Manager

Extract:
1. Full Name
2. Position/Title

Return ONLY a valid JSON object in this format:
{
  "contact_name": "First Last",
  "contact_position": "Title"
}
If no explicit person or decision-maker is found, return null values:
{
  "contact_name": null,
  "contact_position": null
}
"""

OUTPUT_FIELDS = [
    "contact_name",
    "contact_position",
    "email",
    "contact_email",
    "company",
    "source_url",
    "phone",
    "address",
]


def extract_domain(url: str) -> str:
    """Extract clean domain (e.g., companyname.com) from standard URL."""
    if not url:
        return ""
    parsed = urlparse(url if url.startswith("http") else f"https://{url}")
    domain = parsed.netloc if parsed.netloc else parsed.path
    domain = re.sub(r"^www\.", "", domain).lower().strip()
    return domain


def clean_emails(raw_emails, page_domain):
    good = []
    for e in raw_emails:
        e = e.strip().lower().rstrip(".")
        domain = e.split("@")[-1]
        if domain in BLOCKED_DOMAINS or e.endswith(BLOCKED_EXTENSIONS):
            continue
        good.append(e)
    return good


def pick_best_email(emails, page_domain):
    if not emails:
        return ""
    priority_prefixes = ["info@", "contact@", "office@", "sales@", "hello@"]
    for prefix in priority_prefixes:
        for e in emails:
            if e.startswith(prefix):
                return e
    same_domain = [e for e in emails if e.endswith(f"@{page_domain}")]
    if same_domain:
        return same_domain[0]
    return emails[0] if emails else ""


def _fetch_route(url: str):
    """Fetch one URL through Scrapling and return HTML immediately on HTTP 200."""
    try:
        page = StealthyFetcher.fetch(
            url,
            headless=True,
            network_idle=True,
            timeout=8000,
            retries=0,
        )
        if page and getattr(page, "status", None) == 200:
            return page.text
    except Exception:
        pass
    return ""


def _emails_from_html(html: str):
    soup = BeautifulSoup(html, "html.parser")
    emails = []
    for link in soup.select('a[href^="mailto:"]'):
        emails.append(link["href"].replace("mailto:", "").split("?")[0])
    emails.extend(EMAIL_RE.findall(soup.get_text(" ")))
    return emails


def _visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.extract()
    return soup.get_text(separator=" ", strip=True)


def scrape_company_routes(website: str):
    """Fetch contact and team routes. Extract real emails and raw team page text."""
    if not website:
        return [], "", []

    parsed = urlparse(website if website.startswith("http") else f"https://{website}")
    base = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    page_domain = parsed.netloc.replace("www.", "")
    successful_urls = set()
    raw_emails = []
    team_text = ""

    # 1. Fetch Contact routes for real company emails (e.g. info@)
    for route in CONTACT_PATHS:
        target_url = urljoin(base + "/", route)
        if target_url in successful_urls:
            continue
        html = _fetch_route(target_url)
        if html:
            successful_urls.add(target_url)
            raw_emails.extend(_emails_from_html(html))

    # 2. Fetch Team routes for decision maker text
    for route in TEAM_ROUTES:
        target_url = urljoin(base + "/", route)
        if target_url in successful_urls:
            continue
        html = _fetch_route(target_url)
        if html:
            successful_urls.add(target_url)
            raw_emails.extend(_emails_from_html(html))
            text = _visible_text(html)
            if len(text) >= 100:
                team_text = text[:4000]
                break  # Exit team search loop on first valid route found

    emails = clean_emails(raw_emails, page_domain)
    return emails, team_text, sorted(successful_urls)


def analyze_with_llm(page_text: str, groq_client: ChatGroq):
    """Sends extracted page text to Groq Chat model to parse decision-maker info."""
    if not page_text or not groq_client:
        return None, None

    try:
        messages = [
            SystemMessage(content=LLM_PROMPT),
            HumanMessage(content=f"Website Text:\n{page_text}")
        ]
        
        response = groq_client.invoke(messages)
        cleaned_content = response.content.strip()
        
        if "```json" in cleaned_content:
            cleaned_content = cleaned_content.split("```json")[1].split("```")[0].strip()
        elif "```" in cleaned_content:
            cleaned_content = cleaned_content.split("```")[1].split("```")[0].strip()

        result = json.loads(cleaned_content)
        return result.get("contact_name"), result.get("contact_position")
    except Exception as e:
        print(f"  ! Groq LLM extraction error: {e}")
        return None, None


def run(input_csv: str, output_csv: str):
    df = pd.read_csv(input_csv)

    try:
        groq_client = ChatGroq(model_name="llama-3.3-70b-versatile", temperature=0)
    except Exception as e:
        print(f"WARNING: Groq client failed to initialize: {e}")
        groq_client = None

    done_urls = set()
    out_path = Path(output_csv)
    file_exists = out_path.exists()
    if file_exists:
        try:
            prev = pd.read_csv(output_csv)
            if "source_url" in prev.columns:
                done_urls = set(prev["source_url"].dropna().astype(str))
                print(f"Resuming: {len(done_urls)} sites already processed.")
        except Exception:
            file_exists = False

    f = open(output_csv, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
    if not file_exists:
        writer.writeheader()

    found_count = 0

    for i, r in df.iterrows():
        website = str(r.get("website", "")).strip()
        if website in done_urls:
            continue

        domain = extract_domain(website)
        print(f"[{i+1}/{len(df)}] {r.get('business_name','')} -> {website or 'no website'}")

        # 1. Scrape real emails directly from DOM/mailto tags across routes
        route_emails, team_text, successful_routes = scrape_company_routes(website)
        company_email = pick_best_email(route_emails, domain)

        # 2. Extract decision maker via Groq LLM
        contact_name, contact_position = None, None
        if team_text and groq_client:
            contact_name, contact_position = analyze_with_llm(team_text, groq_client)

        if contact_name:
            print(f"  -> Decision Maker: {contact_name} ({contact_position or 'Title unknown'})")
        if company_email:
            print(f"  -> Real Scraped Email: {company_email}")

        row = {
            "contact_name": contact_name or "",
            "contact_position": contact_position or "",
            "email": company_email or "",      # Real scraped email from page (info@, contact@, etc.)
            "contact_email": "",               # Left empty since we are not predicting personal emails
            "company": r.get("business_name", ""),
            "source_url": website,
            "phone": r.get("phone", ""),
            "address": r.get("address", ""),
        }

        # ALWAYS write the row to raw_scrape.csv so business leads are saved
        writer.writerow(row)
        f.flush()
        found_count += 1

        time.sleep(random.uniform(0.5, 1.0))

    f.close()
    print(f"\nDone. Processed {found_count} leads -> {output_csv}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scraper_emails.py businesses.csv raw_scrape.csv")
        sys.exit(1)
    run(sys.argv[1], sys.argv[2])