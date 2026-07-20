"""
Central config for the leads pipeline.
Edit this file, not the pipeline scripts, when you need to change
sheet names, classification rules, template mapping, or file locations.
"""
import os

# ---- Folder structure ----
# Where intermediate CSV files (businesses.csv, raw_scrape.csv,
# cleaned.csv) get written and read from. Change DATA_DIR if you want
# them stored somewhere else -- e.g. a different drive, a shared
# network folder, etc. It's created automatically if it doesn't exist.
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

BUSINESSES_CSV = os.path.join(DATA_DIR, "businesses.csv")
RAW_SCRAPE_CSV = os.path.join(DATA_DIR, "raw_scrape.csv")
CLEANED_CSV = os.path.join(DATA_DIR, "cleaned.csv")

CREDENTIALS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials")
os.makedirs(CREDENTIALS_DIR, exist_ok=True)

# ---- Google Sheets ----
GOOGLE_CREDS_FILE = os.path.join(CREDENTIALS_DIR, "creds.json")  # your service account json goes in credentials/, see README
SPREADSHEET_NAME = "leads_pipeline"      # the Google Sheet file name
RAW_WORKSHEET = "Raw_Leads"
READY_WORKSHEET = "Leads_Ready"

# ---- Schema ----
# Columns your CSVs get normalized into. Add/remove as your scraper's
# output changes -- this is the one place that needs updating.
RAW_COLUMNS = ["contact_name", "contact_position", "email", "contact_email", "company", "domain", "phone", "address", "source_url", "scraped_at"]

# Must match the ACTUAL headers in your Leads_Ready Google Sheet tab exactly.
READY_COLUMNS = [
    "Company Name", "Website", "Email", "Contact Name", "Contact Position","Contact Email",
    "Phone", "Address", "City", "State", "Industry", "Template Type", "Website Status",
    "Primary Campaign", "Secondary Campaign", "Notes",
]

# ---- Classification rules (rule-based, keyword -> category) ----
# Checked against company name + domain, first match wins, top to bottom.
# V1 scope: construction and property management ONLY. Leads that match
# neither are classified as DEFAULT_CLASSIFICATION and dropped in
# process_leads.py (see DROP_UNMATCHED below) rather than kept.
CLASSIFICATION_RULES = [
    ("construction", [
        "construction", "contractor", "builder", "roofing", "hvac",
        "plumbing", "remodeling", "excavation", "civil", "concrete",
    ]),
    ("property_management", [
        "property management", "facility management", "leasing",
        "hoa", "condominium", "condo", "apartment",
    ]),
]

DEFAULT_CLASSIFICATION = "unclassified"

# ---- Template assignment (classification -> template id) ----
TEMPLATE_MAP = {
    "construction": "tmpl_construction_v1",
    "property_management": "tmpl_propertymgmt_v1",
}

# ---- Rule-based campaign assignment ----
# These are the only supported template types for now.  The pipeline assigns
# one based on the industry classifier plus explicit terms in the company
# name, domain, or website URL.  Edit these lists as you learn which terms
# identify software/automation prospects in your market.
CAMPAIGN_TYPES = [
    "CONSTRUCTION_WEBSITE",
    "CONSTRUCTION_SAAS",
    "CONSTRUCTION_AUTOMATION",
    "PROPERTY_WEBSITE",
    "PROPERTY_AUTOMATION",
]

AUTOMATION_KEYWORDS = [
    "automation", "automated", "workflow", "integrations", "integration",
    "digital transformation", "process optimization", "robotic process",
]

CONSTRUCTION_SAAS_KEYWORDS = [
    "software", "saas", "platform", "app", "cloud", "tech", "technology",
    "project management system", "estimating software", "construction management software",
]

# ---- Scope control ----
# If True, leads that don't match either category above are dropped
# entirely rather than written to Leads_Ready with a fallback template.
DROP_UNMATCHED = True

# ---- Maps scraper ----
# One representative search term per category (Maps search works better
# with a single clean phrase than a long keyword dump). Combined with
# each location below to build the search query list.
SEARCH_TERMS = [
    # "construction contractor",
    "roofing company",
    # "HVAC company",
    # "plumbing company",
    # "remodeling contractor",
    # "property management company",
    # "HOA management",
    # "apartment leasing office",
]

# Cities/regions you're targeting. Edit this to your actual target list.
# Full candidate list (Canada + US Sun Belt + major US metros) -- start
# with this subset given runtime (~8 search terms per city), add more
# once you've confirmed lead quality/volume is worth the extra time:
SEARCH_LOCATIONS = [
    # "Toronto, ON",
    "Vancouver, BC",
    # "Calgary, AB",
    # "Austin, TX",
    # "Dallas, TX",
    # "Houston, TX",
    # "Phoenix, AZ",
    # "Atlanta, GA",
    # "Charlotte, NC",
    # "Tampa, FL",
]

# Additional candidates to add later, once the above is validated:
# "Ottawa, ON", "Mississauga, ON", "Montreal, QC", "San Antonio, TX",
# "Nashville, TN", "Orlando, FL", "Miami, FL", "New York, NY",
# "Chicago, IL", "Los Angeles, CA", "Denver, CO", "Seattle, WA"

MAPS_RESULTS_PER_QUERY = 20   # roughly how many listings to pull per search
MAPS_HEADLESS = True          # set False to watch the browser while debugging

# ---- Validation ----
CHECK_MX_RECORDS = True   # set False to skip DNS lookups (faster, less accurate)
