"""Web search tool using Serper API (primary) and Google CSE (fallback).

Agents call web_search(query) to find relevant documentation, best practices,
and reference implementations before generating code. This enables the swarm to
produce enterprise-grade, production-ready architecture instead of toy examples.
"""

import os
import json
import logging
from typing import Dict, Any, List
from langchain_core.tools import tool

logger = logging.getLogger("tools")

SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID", "")

SERPER_URL = "https://google.serper.dev/search"


def _search_serper(query: str, num_results: int = 5) -> List[Dict[str, Any]]:
    """Search via Serper API. Returns list of {title, link, snippet} dicts."""
    if not SERPER_API_KEY:
        raise RuntimeError("SERPER_API_KEY not configured")

    import requests
    payload = json.dumps({"q": query, "num": num_results})
    headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json",
    }
    resp = requests.post(SERPER_URL, headers=headers, data=payload, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    results = []
    for item in data.get("organic", []):
        results.append({
            "title": item.get("title", ""),
            "link": item.get("link", ""),
            "snippet": item.get("snippet", ""),
        })
    return results


def _search_google_cse(query: str, num_results: int = 5) -> List[Dict[str, Any]]:
    """Search via Google Custom Search JSON API."""
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        raise RuntimeError("GOOGLE_API_KEY or GOOGLE_CSE_ID not configured")

    import requests
    url = (
        "https://www.googleapis.com/customsearch/v1"
        f"?q={requests.utils.quote(query)}"
        f"&key={GOOGLE_API_KEY}"
        f"&cx={GOOGLE_CSE_ID}"
        f"&num={num_results}"
    )
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    results = []
    for item in data.get("items", []):
        results.append({
            "title": item.get("title", ""),
            "link": item.get("link", ""),
            "snippet": item.get("snippet", ""),
        })
    return results


@tool("web_search")
def web_search(query: str, num_results: int = 5) -> Dict[str, Any]:
    """Search the web for current information, documentation, and best practices.

    Use this BEFORE generating code to research:
    - Latest framework versions and patterns
    - Security best practices
    - Enterprise architecture patterns
    - Official documentation
    - Production deployment guides

    Args:
        query: Search query string (be specific, e.g.
               "Spring Boot 3.2 security best practices 2025")
        num_results: Number of results to return (default 5, max 10)

    Returns:
        Search results with title, URL, and snippet for each result.
    """
    try:
        num_results = min(max(num_results, 1), 10)

        # Try Serper first (better results, more quota)
        try:
            results = _search_serper(query, num_results)
            logger.info(f"[web_search] Serper: {len(results)} results for '{query[:60]}'")
        except Exception as e:
            logger.warning(f"[web_search] Serper failed ({e}), trying Google CSE")
            results = _search_google_cse(query, num_results)
            logger.info(f"[web_search] Google CSE: {len(results)} results for '{query[:60]}'")

        if not results:
            return {"status": "success", "query": query, "results": [], "message": "No results found"}

        # Format as readable text for the LLM
        formatted = []
        for i, r in enumerate(results, 1):
            formatted.append(f"{i}. {r['title']}\n   URL: {r['link']}\n   {r['snippet']}")

        return {
            "status": "success",
            "query": query,
            "results": results,
            "formatted": "\n\n".join(formatted),
            "count": len(results),
        }

    except Exception as e:
        logger.error(f"[web_search] Failed: {e}")
        return {"status": "error", "query": query, "error": str(e)}
