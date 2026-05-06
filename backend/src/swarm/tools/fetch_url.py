"""URL content fetching tool with HTML extraction.

Agents call fetch_url(url) to read full documentation pages, blog posts,
GitHub readmes, and other web resources discovered via web_search().
"""

import logging
import httpx
from typing import Dict, Any
from langchain_core.tools import tool

logger = logging.getLogger("tools")


def _extract_main_content(html: str) -> str:
    """Extract main readable content from HTML, removing nav/ads/scripts."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        # Fallback: crude text extraction
        import re
        text = re.sub(r'<[^>]+>', ' ', html)
        return re.sub(r'\s+', ' ', text).strip()[:8000]

    soup = BeautifulSoup(html, "html.parser")

    # Remove non-content elements
    for tag in soup(["script", "style", "nav", "footer", "header", "aside",
                     "form", "iframe", "noscript", "svg", "canvas"]):
        tag.decompose()

    # Try to find main content area
    main = (soup.find("main") or
            soup.find("article") or
            soup.find("div", class_=lambda x: x and "content" in x.lower()) or
            soup.find("div", role="main") or
            soup.find("body"))

    if main:
        text = main.get_text(separator="\n", strip=True)
    else:
        text = soup.get_text(separator="\n", strip=True)

    # Clean up excessive whitespace
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text = "\n".join(lines)

    # Truncate if too large for LLM context
    max_chars = 12000
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[Content truncated at {max_chars} chars — use fetch_url again with a more specific URL if needed]"

    return text


# Sites that aggressively block scrapers — skip to avoid wasting time/tokens
_BLOCKED_DOMAINS = {"medium.com", "towardsdatascience.com", "betterprogramming.pub"}


def _is_blocked(url: str) -> bool:
    from urllib.parse import urlparse
    netloc = urlparse(url).netloc.lower()
    return any(blocked in netloc for blocked in _BLOCKED_DOMAINS)


@tool("fetch_url")
async def fetch_url(url: str) -> Dict[str, Any]:
    """Fetch and extract the main text content from a web page URL.

    Use this AFTER web_search() to read full documentation, blog posts,
    GitHub readmes, or any web resource in depth.

    Args:
        url: Full URL to fetch (must include http:// or https://)

    Returns:
        Extracted text content, title, and metadata.
    """
    if _is_blocked(url):
        logger.warning(f"[fetch_url] Skipping blocked domain: {url}")
        return {"status": "error", "url": url, "error": "This site blocks automated access. Try a different URL from search results."}

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()

            # Extract title
            title = ""
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "html.parser")
                title_tag = soup.find("title")
                if title_tag:
                    title = title_tag.get_text(strip=True)
            except Exception:
                pass

            content = _extract_main_content(resp.text)
            logger.info(f"[fetch_url] Fetched {url[:80]} ({len(content)} chars)")

            return {
                "status": "success",
                "url": url,
                "title": title,
                "content": content,
                "content_length": len(content),
            }

    except httpx.TimeoutException:
        logger.warning(f"[fetch_url] Timeout: {url}")
        return {"status": "error", "url": url, "error": "Timeout fetching URL"}
    except httpx.HTTPStatusError as e:
        logger.warning(f"[fetch_url] HTTP error: {url} — {e}")
        return {"status": "error", "url": url, "error": f"HTTP {e.response.status_code}"}
    except Exception as e:
        logger.error(f"[fetch_url] Unexpected error: {url} — {e}")
        return {"status": "error", "url": url, "error": str(e)}
