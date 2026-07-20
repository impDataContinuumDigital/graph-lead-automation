"""
Stage 0a: Scrape business listings (name, website, phone, address) from
Google Maps for each (search term x location) combo in config.py.

Usage:
    python scraper_maps.py businesses.csv

IMPORTANT:
- This drives a real browser against Google Maps' web UI. It is NOT
  using an official API, which means: (a) it's against Google's Terms
  of Service, (b) the DOM/selectors WILL change over time and break
  this script, (c) Google will rate-limit or block your IP if you hit
  it too hard. Use delays, don't run this constantly, and consider
  rotating IPs / using a residential proxy if you scale this up.
- Output has no email yet -- that's scraper_emails.py's job, run after
  this one, using the "website" column this script produces.
"""
import csv
import sys
import os
import time
import random
from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # find config.py one level up
from config import SEARCH_TERMS, SEARCH_LOCATIONS, MAPS_RESULTS_PER_QUERY, MAPS_HEADLESS

OUTPUT_COLUMNS = ["business_name", "category", "website", "phone", "address", "search_query"]


def scroll_results_panel(page, target_count, max_scrolls=25):
    """Google Maps lazy-loads results as you scroll the left panel."""
    feed_selector = 'div[role="feed"]'
    try:
        page.wait_for_selector(feed_selector, timeout=10000)
    except Exception:
        return

    seen = 0
    stagnant_rounds = 0
    for _ in range(max_scrolls):
        cards = page.query_selector_all(f'{feed_selector} > div > div[role="article"]')
        if len(cards) >= target_count:
            break
        if len(cards) == seen:
            stagnant_rounds += 1
            if stagnant_rounds >= 3:
                break
        else:
            stagnant_rounds = 0
        seen = len(cards)
        page.eval_on_selector(feed_selector, "el => el.scrollBy(0, el.scrollHeight)")
        time.sleep(random.uniform(1.2, 2.0))


def extract_listing_data(page, card):
    """Click a result card and pull details from the side panel."""
    data = {"business_name": "", "category": "", "website": "", "phone": "", "address": ""}
    try:
        name_el = card.query_selector('div[class*="fontHeadlineSmall"]') or card.query_selector("a")
        data["business_name"] = (name_el.inner_text().strip() if name_el else "")

        card.click()
        page.wait_for_timeout(random.randint(1500, 2500))

        website_el = page.query_selector('a[data-item-id="authority"]')
        if website_el:
            data["website"] = website_el.get_attribute("href") or ""

        phone_el = page.query_selector('button[data-item-id^="phone"]')
        if phone_el:
            data["phone"] = (phone_el.get_attribute("aria-label") or "").replace("Phone:", "").strip()

        addr_el = page.query_selector('button[data-item-id="address"]')
        if addr_el:
            data["address"] = (addr_el.get_attribute("aria-label") or "").replace("Address:", "").strip()

        cat_el = page.query_selector('button[jsaction*="category"]')
        if cat_el:
            data["category"] = cat_el.inner_text().strip()
    except Exception as e:
        print(f"  ! failed to extract a listing: {e}")
    return data


CARD_SELECTOR = 'div[role="feed"] > div > div[role="article"]'


def scrape_query(page, query: str, target_count: int):
    print(f"Searching: {query}")
    url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}"
    page.goto(url, timeout=30000)
    page.wait_for_timeout(random.randint(2000, 3000))

    scroll_results_panel(page, target_count)

    # Google Maps virtualizes this list -- elements get swapped in/out of
    # the DOM as you scroll or click. Grabbing all card handles up front
    # and clicking through them later hits "not attached to the DOM"
    # errors once Maps re-renders. Instead, re-query the live list by
    # index right before each click so we always hold a fresh, valid
    # handle for the card we're about to interact with.
    available = len(page.query_selector_all(CARD_SELECTOR))
    count = min(available, target_count)

    results = []
    for i in range(count):
        cards = page.query_selector_all(CARD_SELECTOR)
        if i >= len(cards):
            break  # list shrank (Maps re-rendered) -- nothing more to get
        card = cards[i]
        try:
            card.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            pass  # element may already be visible or briefly detached; click below will retry via re-query on next loop
        data = extract_listing_data(page, card)
        data["search_query"] = query
        if data["business_name"]:
            results.append(data)
        time.sleep(random.uniform(0.8, 1.5))
    print(f"  -> got {len(results)} listings")
    return results


def run(output_csv: str):
    queries = [f"{term} in {loc}" for term in SEARCH_TERMS for loc in SEARCH_LOCATIONS]

    all_results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=MAPS_HEADLESS)
        page = browser.new_page(locale="en-US")

        for i, query in enumerate(queries):
            try:
                all_results.extend(scrape_query(page, query, MAPS_RESULTS_PER_QUERY))
            except Exception as e:
                print(f"  ! query failed: {query} ({e})")
            # be polite between queries -- tune this, or expect blocks
            time.sleep(random.uniform(4, 8))

        browser.close()

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for row in all_results:
            writer.writerow(row)

    print(f"\nWrote {len(all_results)} business listings -> {output_csv}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scraper_maps.py businesses.csv")
        sys.exit(1)
    run(sys.argv[1])