# Lead Generation Pipeline

## Overview

This pipeline automates the process of collecting, cleaning, enriching, and organizing business leads from Google Maps and company websites.

The primary focus is on:

* Construction Companies
* Property Management Companies

The pipeline scrapes business information, extracts contact details from company websites, cleans the data, and pushes qualified leads into Google Sheets for outreach preparation.

---

# Pipeline Architecture

```text
Google Maps
    ↓
scraper_maps.py
    ↓
businesses.csv
    ↓
scraper_emails.py
    ↓
raw_scrape.csv
    ↓
clean.py
    ↓
push_raw.py
    ↓
Google Sheet (Raw_Leads)
    ↓
process_leads.py
    ↓
Google Sheet (Leads_Ready)
```

---

# Project Structure

```text
leads_pipeline/
│
├── config.py
├── graph_pipeline.py
├── requirements.txt
│
├── credentials/
│   └── creds.json
│
├── pipeline_stages/
│   ├── scraper_maps.py
│   ├── scraper_emails.py
│   ├── clean.py
│   ├── push_raw.py
│   └── process_leads.py
│
└── data/
    ├── businesses.csv
    ├── raw_scrape.csv
    └── cleaned.csv
```

---

# Step 1 – Google Maps Scraping

### File

```text
pipeline_stages/scraper_maps.py
```

### Purpose

Collects businesses from Google Maps based on target keywords.

### Example Keywords

Construction:

```text
construction
contractor
builder
roofing
hvac
plumbing
concrete
excavation
remodeling
```

Property Management:

```text
property management
facility management
hoa management
apartment management
leasing company
```

### Output

```text
data/businesses.csv
```

Contains:

```text
Business Name
Website
Phone
Address
City
State
Google Rating
Review Count
```

---

# Step 2 – Website Contact Extraction

### File

```text
pipeline_stages/scraper_emails.py
```

### Purpose

Visits each company website and attempts to extract:

```text
Company Email
Contact Name
Contact Position
Contact Email
```

### Pages Searched

```text
Homepage
/team
/our-team
/leadership
/management
/staff
/about
/about-us
/contact
```

### Decision Maker Priority

The scraper prioritizes:

```text
Owner
Founder
President
CEO
COO
Vice President
Director
Project Manager
Property Manager
Operations Manager
```

### Output

```text
data/raw_scrape.csv
```

---

# Step 3 – Data Cleaning

### File

```text
pipeline_stages/clean.py
```

### Purpose

Standardizes and validates lead data.

### Operations

* Remove duplicates
* Normalize emails
* Remove invalid emails
* Normalize websites
* Clean phone numbers
* Remove empty records
* Validate required fields

### Output

```text
data/cleaned.csv
```

---

# Step 4 – Push to Raw Leads Sheet

### File

```text
pipeline_stages/push_raw.py
```

### Purpose

Uploads cleaned data into Google Sheets.

### Google Sheet

```text
Raw_Leads
```

### Purpose of Raw_Leads

Acts as the master database containing all scraped leads before processing.

### Typical Columns

```text
Company Name
Website
Email
Phone
Address
City
Industry
Contact Name
Contact Position
Contact Email
```

---

# Step 5 – Lead Processing

### File

```text
pipeline_stages/process_leads.py
```

### Purpose

Transforms raw leads into outreach-ready leads.

### Operations

#### Deduplication

Removes duplicates based on:

```text
Website
Email
Company Name
```

#### Classification

Assigns industry:

```text
Construction
Property Management
Unknown
```

#### Campaign Assignment

Maps leads into outreach campaigns.

Example:

```text
Construction
    ↓
Construction Outreach

Property Management
    ↓
Property Management Outreach
```

### Output Sheet

```text
Leads_Ready
```

---

# Leads_Ready Structure

```text
Company Name
Website
Email
Contact Name
Contact Position
Contact Email
Phone
Address
City
Industry
Website Status
Primary Campaign
Secondary Campaign
Notes
```

---

# Running The Full Pipeline

Run everything:

```bash
python graph_pipeline.py
```

Execution order:

```text
1. scraper_maps.py
2. scraper_emails.py
3. clean.py
4. push_raw.py
5. process_leads.py
```

---

# Running Individual Stages

Google Maps Scraper

```bash
python pipeline_stages/scraper_maps.py
```

Email & Contact Scraper

```bash
python pipeline_stages/scraper_emails.py
```

Cleaning

```bash
python pipeline_stages/clean.py
```

Push Raw Leads

```bash
python pipeline_stages/push_raw.py
```

Lead Processing

```bash
python pipeline_stages/process_leads.py
```

---

# Configuration

### File

```text
config.py
```

Contains:

* Google Sheet IDs
* Worksheet Names
* Campaign Mapping
* Industry Classification Rules
* File Paths
* Pipeline Settings

---

# Google Credentials

Place Google Service Account credentials inside:

```text
credentials/creds.json
```

Required permissions:

```text
Google Sheets API
Google Drive API
```

Share the spreadsheet with the service account email.

---

# Data Flow Summary

```text
Google Maps
    ↓
Business Information
    ↓
Company Website
    ↓
Email & Contact Extraction
    ↓
Data Cleaning
    ↓
Raw_Leads
    ↓
Classification
    ↓
Campaign Assignment
    ↓
Leads_Ready
    ↓
Outbound Outreach
```

---

# Future Improvements

### Contact Intelligence

Improve extraction of:

```text
Contact Name
Contact Position
Contact Email
```

from:

```text
Leadership Pages
Management Pages
Team Pages
```

### Email Enrichment

Integrate:

```text
Apollo
Hunter
Snov
Clearbit
```

for contact verification.

### AI Classification

Use LLM-based classification for:

```text
Industry Detection
Lead Qualification
Campaign Selection
```

### Confidence Scoring

Assign confidence scores to contacts:

```text
95 = Verified Executive
80 = Strong Match
60 = Probable Match
30 = Weak Match
```

to improve outreach quality.
