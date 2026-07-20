"""
Full pipeline as a LangGraph state machine -- pure rule-based, no LLM.

Nodes:
  scrape_maps -> scrape_emails -> clean -> push_raw -> process_leads

Each node calls its script's function directly, in-process (no
subprocess spawning) -- every script already separates its logic
from CLI argument parsing, so this is just a normal Python import +
function call. process_leads runs the keyword-based classifier,
website status check, and prints the processing summary (Total Raw
Leads / Duplicates Removed / Qualified Leads / Qualification Rate).

Every node reports success/failure into shared state; a conditional
edge after each one routes to an "error" node and stops the whole
graph the moment anything fails, instead of continuing with bad data.

Setup:
    pip install langgraph

Usage:
    python graph_pipeline.py
    python graph_pipeline.py --fresh     # deletes businesses.csv / raw_scrape.csv / cleaned.csv first
"""
import sys
import os
import traceback
from pathlib import Path
from typing import TypedDict, Optional

from langgraph.graph import StateGraph, END

# The 5 stage scripts live in pipeline_stages/ -- add that folder to
# the import path so they can be imported directly, same as any other
# module, without needing __init__.py or package-relative imports.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline_stages"))

# Import the actual functions from each script instead of shelling out --
# each one already separates its logic from its CLI argument parsing
# (the `if __name__ == "__main__":` block), so this is a direct call,
# no subprocess needed.
from scraper_maps import run as scrape_maps_fn
from scraper_emails import run as scrape_emails_fn
from clean import clean as clean_fn
from push_raw import push_raw as push_raw_fn
from process_leads import run as process_leads_fn
from config import BUSINESSES_CSV, RAW_SCRAPE_CSV, CLEANED_CSV

FILES = {"businesses": BUSINESSES_CSV, "raw_scrape": RAW_SCRAPE_CSV, "cleaned": CLEANED_CSV}


class PipelineState(TypedDict):
    error: Optional[str]
    step: str


# ---------- nodes: each calls its script's function directly, in-process ----------

def node_scrape_maps(state: PipelineState) -> dict:
    try:
        scrape_maps_fn(FILES["businesses"])
        return {"error": None, "step": "scrape_maps"}
    except Exception as e:
        traceback.print_exc()
        return {"error": f"scrape_maps failed: {e}", "step": "scrape_maps"}


def node_scrape_emails(state: PipelineState) -> dict:
    try:
        scrape_emails_fn(FILES["businesses"], FILES["raw_scrape"])
        return {"error": None, "step": "scrape_emails"}
    except Exception as e:
        traceback.print_exc()
        return {"error": f"scrape_emails failed: {e}", "step": "scrape_emails"}


def node_clean(state: PipelineState) -> dict:
    try:
        clean_fn(FILES["raw_scrape"], FILES["cleaned"])
        return {"error": None, "step": "clean"}
    except Exception as e:
        traceback.print_exc()
        return {"error": f"clean failed: {e}", "step": "clean"}


def node_push_raw(state: PipelineState) -> dict:
    try:
        push_raw_fn(FILES["cleaned"])
        return {"error": None, "step": "push_raw"}
    except Exception as e:
        traceback.print_exc()
        return {"error": f"push_raw failed: {e}", "step": "push_raw"}


def node_process_leads(state: PipelineState) -> dict:
    try:
        process_leads_fn()
        return {"error": None, "step": "process_leads"}
    except Exception as e:
        traceback.print_exc()
        return {"error": f"process_leads failed: {e}", "step": "process_leads"}


def node_error(state: PipelineState) -> dict:
    print(f"\n!! PIPELINE STOPPED at step '{state['step']}': {state['error']}")
    return state


def route_after(state: PipelineState) -> str:
    return "error" if state.get("error") else "continue"


# ---------- build the graph ----------

builder = StateGraph(PipelineState)
builder.add_node("scrape_maps", node_scrape_maps)
builder.add_node("scrape_emails", node_scrape_emails)
builder.add_node("clean", node_clean)
builder.add_node("push_raw", node_push_raw)
builder.add_node("process_leads", node_process_leads)
builder.add_node("error", node_error)

builder.set_entry_point("scrape_maps")
builder.add_conditional_edges("scrape_maps", route_after, {"continue": "scrape_emails", "error": "error"})
builder.add_conditional_edges("scrape_emails", route_after, {"continue": "clean", "error": "error"})
builder.add_conditional_edges("clean", route_after, {"continue": "push_raw", "error": "error"})
builder.add_conditional_edges("push_raw", route_after, {"continue": "process_leads", "error": "error"})
builder.add_edge("process_leads", END)
builder.add_edge("error", END)

app = builder.compile()


if __name__ == "__main__":
    if "--fresh" in sys.argv:
        for f in FILES.values():
            p = Path(f)
            if p.exists():
                p.unlink()
                print(f"Deleted {f} (starting fresh)")

    final_state = app.invoke({"error": None, "step": "start"})
    if final_state.get("error"):
        sys.exit(1)
    print("\nPipeline finished successfully.")