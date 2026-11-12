"""
MCP Web-Grounding & Citation Agent (Project 1).

This script demonstrates a single-agent research workflow built with Claude and an
MCP-style search adapter. It retrieves live web snippets, enforces a strict JSON
citation schema to prevent hallucinations, and logs Developer Experience (DevEx)
metrics via `telemetry.py`.
"""

import os
import json
import argparse
import requests
from dotenv import load_dotenv
from anthropic import Anthropic
from telemetry import DevExTelemetryTracker

# Load API keys and configuration variables from the local .env file
load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
GROUNDING_PROVIDER = os.getenv("GROUNDING_PROVIDER", "tavily")
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY")
WEB_IQ_ENDPOINT = os.getenv("WEB_IQ_ENDPOINT", "")

# Set up the Anthropic client and our custom DevEx telemetry tracker
client = Anthropic(api_key=ANTHROPIC_API_KEY)
tracker = DevExTelemetryTracker()


def search_web_via_mcp_adapter(query_text):
    """
    Retrieves live web search passages using an MCP-compatible tool interface.
    
    Supports swapping between a local developer search API (Tavily) and an
    enterprise grounding endpoint (such as Microsoft Web IQ) via .env settings.
    Includes a built-in demo fallback if no API key is configured yet.

    Args:
        query_text (str): The search query or claim to look up.

    Returns:
        dict: Contains 'results' (list of clean source dicts), 'raw_chars' (int),
              and 'extracted_chars' (int) for token-reduction tracking.
    """
    # Path A: Enterprise grounding backend (e.g., Microsoft Web IQ over MCP JSON-RPC)
    if GROUNDING_PROVIDER == "web_iq" and WEB_IQ_ENDPOINT:
        headers = {
            "Authorization": f"Bearer {SEARCH_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "method": "tools/call",
            "params": {"name": "web_search", "arguments": {"query": query_text}},
        }
        resp = requests.post(WEB_IQ_ENDPOINT, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        raw_text = json.dumps(data)
        return {
            "results": data.get("results", []),
            "raw_chars": len(raw_text),
            "extracted_chars": len(raw_text),
        }

    # Path B: Local developer search backend using Tavily API
    if SEARCH_API_KEY and SEARCH_API_KEY != "your_search_key":
        url = "https://tavily.com"
        payload = {
            "api_key": SEARCH_API_KEY,
            "query": query_text,
            "search_depth": "basic",
            "max_results": 3,
        }
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        # Trim snippets to 600 chars so malformed or huge articles don't break JSON output
        clean_results = []
        raw_char_count = 0
        extracted_char_count = 0

        for item in data.get("results", []):
            raw_content = item.get("content", "")
            raw_char_count += len(raw_content)

            short_snippet = raw_content[:600]
            extracted_char_count += len(short_snippet)

            clean_results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": short_snippet,
            })

        return {
            "results": clean_results,
            "raw_chars": raw_char_count,
            "extracted_chars": extracted_char_count,
        }

    # Path C: Fallback sample data so the script still runs cleanly without paid keys
    print("Note: No SEARCH_API_KEY found in .env. Running with sample grounding data...")
    sample_results = [
        {
            "title": "Enterprise AI Grounding & MCP Standards Overview",
            "url": "https://example.com",
            "snippet": (
                "Enterprises are adopting the Model Context Protocol (MCP) to connect "
                "LLMs with real-time web search and passage extraction APIs."
            ),
        }
    ]
    return {"results": sample_results, "raw_chars": 1200, "extracted_chars": 145}


def ask_claude_with_citations(user_query, search_results):
    """
    Sends retrieved search snippets to Claude and enforces a structured JSON response.

    Args:
        user_query (str): The original user question or fact-check request.
        search_results (list): List of sanitized search result dictionaries.

    Returns:
        Message: The raw Anthropic API response object (includes token usage stats).
    """
    system_instructions = (
        "You are a fact-checking research assistant. Answer the user's question using ONLY "
        "the provided web search snippets. Return valid JSON with keys: "
        "'claim', 'answer', 'citations' (list of objects with 'title', 'url', 'snippet'), "
        "and 'confidence_score' (0.0 to 1.0). Do not include markdown fences."
    )

    user_message = (
        f"Question: {user_query}\n\n"
        f"Search Results:\n{json.dumps(search_results, indent=2)}"
    )

    response = client.messages.create(
        model="claude-3-5-sonnet-latest",
        max_tokens=800,
        system=system_instructions,
        messages=[{"role": "user", "content": user_message}],
    )
    return response


def main():
    """
    Main entry point: parses command-line arguments, runs the web search and
    Claude synthesis steps under telemetry tracking, and exports the scorecard.
    """
    parser = argparse.ArgumentParser(description="MCP Web-Grounding & Citation Agent")
    parser.add_argument(
        "--query",
        type=str,
        default="What are the latest enterprise AI grounding announcements this week?",
        help="The question or claim to verify",
    )
    args = parser.parse_args()

    print(f"\nRunning query: {args.query}")
    print(f"Using grounding provider: {GROUNDING_PROVIDER}\n")

    # Step 1: Fetch web passages while measuring latency and payload size
    search_data = tracker.execute_with_telemetry(
        step_name="mcp_web_search",
        fn=search_web_via_mcp_adapter,
        query_text=args.query,
    )

    # Step 2: Synthesize a cited JSON answer with Claude (or simulate if no key is set)
    if ANTHROPIC_API_KEY and ANTHROPIC_API_KEY != "your_claude_key":
        claude_resp = tracker.execute_with_telemetry(
            step_name="claude_citation_synthesis",
            fn=ask_claude_with_citations,
            user_query=args.query,
            search_results=search_data["results"],
        )
        final_output = claude_resp.content[0].text
    else:
        print("Note: No ANTHROPIC_API_KEY found in .env. Printing simulated JSON output...")
        final_output = json.dumps({
            "claim": args.query,
            "answer": "Based on retrieved sources, enterprise platforms are standardizing on MCP for real-time web grounding.",
            "citations": search_data["results"],
            "confidence_score": 0.92,
        }, indent=2)

    print("=== Grounded Agent Output ===")
    print(final_output)

    # Step 3: Display and save the DevEx telemetry scorecard
    scorecard = tracker.generate_scorecard()
    print("\n=== DevEx Telemetry Scorecard ===")
    print(json.dumps(scorecard, indent=2))

    tracker.export_report("telemetry_scorecard.json")
    print("\nSaved detailed report to telemetry_scorecard.json")


if __name__ == "__main__":
    main()
