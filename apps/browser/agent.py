"""
Browser Agent - Automated web browsing and information extraction
Uses browser-use library with Claude vision
"""

import logging
from typing import Optional, Any
import json

from shared.config import get_settings
from shared.models import BrowserTask, BrowserResult
from shared.llm import get_llm_router

logger = logging.getLogger(__name__)
settings = get_settings()


class BrowserAgent:
    """Web automation agent using browser-use"""

    def __init__(self):
        self.llm = get_llm_router()
        self.browser_session = None

    async def initialize(self):
        """Initialize browser session"""
        try:
            # Import browser-use when available
            # from browser_use import Agent as BrowserUseAgent
            # This will be initialized on-demand
            logger.info("✅ Browser agent initialized (lazy loading)")
        except ImportError:
            logger.warning("⚠️  browser-use not installed, using fallback mode")

    async def execute(self, task: BrowserTask) -> BrowserResult:
        """
        Execute browser automation task

        Args:
            task: BrowserTask with URL/search query and instruction

        Returns:
            BrowserResult with extracted data
        """
        logger.info(f"🌐 [BROWSER] Starting task: {task.instruction}")

        try:
            # Check if browser-use is available
            import importlib.util

            if importlib.util.find_spec("browser_use"):
                return await self._execute_with_browser_use(task)
            else:
                logger.info("Using lightweight fallback mode (no browser-use)")
                return await self._execute_fallback(task)
        except Exception as e:
            logger.error(f"❌ Browser task failed: {e}")
            return BrowserResult(
                success=False,
                error=str(e),
            )

    async def _execute_with_browser_use(self, task: BrowserTask) -> BrowserResult:
        """
        Use browser-use library for advanced web automation
        """
        try:
            from browser_use import Agent as BrowserUseAgent

            # Build full instruction
            instruction = task.instruction
            if task.url:
                instruction = f"Navigate to {task.url} and then: {instruction}"
            elif task.search_query:
                instruction = (
                    f"Search for '{task.search_query}' and then: {instruction}"
                )

            if task.extract_fields:
                instruction += (
                    f"\n\nExtract these fields: {', '.join(task.extract_fields)}"
                )
                instruction += "\n\nReturn results as JSON"

            # Create agent
            agent = BrowserUseAgent(
                task=instruction,
                llm=self.llm,
            )

            # Run agent
            logger.info(f"🤖 Browser-use agent starting: {instruction[:100]}...")
            result = await agent.run()

            logger.info("✅ Browser-use completed")

            # Parse result
            return BrowserResult(
                success=True,
                data=self._parse_result(result, task.extract_fields),
            )

        except Exception as e:
            logger.error(f"browser-use error: {e}")
            raise

    async def _execute_fallback(self, task: BrowserTask) -> BrowserResult:
        """
        Lightweight fallback using httpx + BeautifulSoup
        (when browser-use not available)
        """
        try:
            import httpx
            import urllib.parse
            from bs4 import BeautifulSoup

            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; AI-Agent/1.0; +https://example.com/bot)"
            }

            # Case A: Explicit URL provided
            if task.url:
                async with httpx.AsyncClient(
                    follow_redirects=True,
                    timeout=30,
                    headers=headers,
                ) as client:
                    response = await client.get(task.url)
                    response.raise_for_status()
                    html = response.text

                # Parse HTML
                soup = BeautifulSoup(html, "html.parser")
                data = await self._extract_from_html(
                    soup, task.extract_fields, task.instruction
                )

                logger.info(
                    f"✅ Fallback extraction completed, found {len(data)} items"
                )

                return BrowserResult(
                    success=True,
                    data={"items": data},
                )

            # Case B: Search query provided (Scrape DuckDuckGo HTML results)
            elif task.search_query:
                query_encoded = urllib.parse.quote(task.search_query)
                search_url = f"https://html.duckduckgo.com/html/?q={query_encoded}"

                logger.info(
                    f"🔎 [Fallback Search] Querying DuckDuckGo: {task.search_query}"
                )
                async with httpx.AsyncClient(
                    follow_redirects=True,
                    timeout=30,
                    headers=headers,
                ) as client:
                    response = await client.get(search_url)
                    response.raise_for_status()
                    html = response.text

                soup = BeautifulSoup(html, "html.parser")
                results = []

                # DuckDuckGo HTML structure search
                for element in soup.select(".result__body, .web-result"):
                    title_elem = element.select_one(".result__title, a.result__url")
                    snippet_elem = element.select_one(".result__snippet")
                    url_elem = element.select_one("a.result__url, a")

                    if title_elem and url_elem:
                        title = title_elem.get_text(strip=True)
                        snippet = (
                            snippet_elem.get_text(strip=True) if snippet_elem else ""
                        )
                        url = url_elem.get("href", "")

                        # Clean outbound click tracking links if necessary
                        if "uddg=" in url:
                            try:
                                parsed = urllib.parse.urlparse(url)
                                query_params = urllib.parse.parse_qs(parsed.query)
                                if "uddg" in query_params:
                                    url = query_params["uddg"][0]
                            except Exception:
                                pass

                        results.append({"title": title, "snippet": snippet, "url": url})

                logger.info(
                    f"✅ Fallback search completed, found {len(results)} search results"
                )
                return BrowserResult(
                    success=True,
                    data={"results": results[:10]},
                )

            else:
                return BrowserResult(
                    success=False,
                    error="Must provide either URL or search query",
                )

        except Exception as e:
            logger.error(f"Fallback extraction error: {e}")
            return BrowserResult(
                success=False,
                error=str(e),
            )

    def _parse_result(
        self, raw_result: Any, expected_fields: Optional[list] = None
    ) -> dict:
        """Parse browser-use result into structured format"""
        if isinstance(raw_result, dict):
            return raw_result
        elif isinstance(raw_result, str):
            try:
                return json.loads(raw_result)
            except json.JSONDecodeError:
                return {"output": raw_result}
        else:
            return {"output": str(raw_result)}

    async def _extract_from_html(
        self, soup, fields: Optional[list] = None, instruction: str = ""
    ) -> list:
        """Extract structured data from HTML with high-reliability selector & LLM fallbacks"""
        data = []
        fields = fields or ["name", "url", "description"]

        # 1. Selector Heuristics (Quick & Cheap)
        for item in soup.select(".product, .item, .listing, article, .post, .entry"):
            entry = {}
            if "name" in fields or "title" in fields:
                name_elem = item.select_one(".name, .title, h2, h3, a")
                if name_elem:
                    entry["name"] = name_elem.get_text(strip=True)

            if "price" in fields:
                price_elem = item.select_one(".price, .cost, .amount")
                if price_elem:
                    entry["price"] = price_elem.get_text(strip=True)

            if "url" in fields:
                url_elem = item.select_one("a")
                if url_elem and url_elem.get("href"):
                    entry["url"] = url_elem["href"]

            if "description" in fields or "snippet" in fields:
                desc_elem = item.select_one(".description, .desc, .snippet, p")
                if desc_elem:
                    entry["description"] = desc_elem.get_text(strip=True)

            # Keep if we found at least 2 requested fields
            if len(entry) >= min(2, len(fields)):
                data.append(entry)

        # 2. LLM-Assisted Parser Fallback (Highly Intelligent & Accurate to eliminate hallucinations)
        if len(data) == 0:
            logger.info(
                "⚠️ Selector heuristics returned no data. Falling back to LLM-Assisted text parsing..."
            )

            # Clean body HTML to retrieve only text content
            for tag in soup(["script", "style", "head", "nav", "footer", "iframe"]):
                tag.decompose()

            clean_text = soup.get_text(separator=" ", strip=True)
            # Truncate to stay comfortably inside cheap LLM context limits (e.g. gpt-4o-mini)
            truncated_text = clean_text[:6000]

            prompt = (
                f"You are an expert web scraper. Extract structured data from the following webpage text.\n"
                f"Target fields to extract: {fields}\n"
                f"Scraping instructions: {instruction}\n\n"
                f"Webpage content snippet:\n"
                f'"""\n{truncated_text}\n"""\n\n'
                f"Return the results strictly as a JSON array of objects. Each object must strictly use the keys: {fields}.\n"
                f"If no relevant items matching the instruction are present, return an empty array [].\n"
                f"Return only the raw JSON output. Do NOT wrap it in markdown codeblocks (e.g. ```json) or add extra comments."
            )

            try:
                raw_response = await self.llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    task="extract",
                    temperature=0.0,
                )

                # Sanitize response
                json_str = raw_response.strip()
                if json_str.startswith("```"):
                    # Strip any markdown fences
                    json_str = json_str.lstrip("```").rstrip("```").strip()
                    if json_str.startswith("json"):
                        json_str = json_str[4:].strip()

                parsed_data = json.loads(json_str)
                if isinstance(parsed_data, list):
                    return parsed_data[:10]
            except Exception as llm_err:
                logger.error(f"❌ LLM-assisted extraction failed: {llm_err}")

        return data[:10]


# ──---- Standalone Functions ----


async def run_browser_task(task: BrowserTask) -> BrowserResult:
    """
    Standalone function to run a browser task
    """
    agent = BrowserAgent()
    await agent.initialize()
    return await agent.execute(task)


# Common task templates


async def search_and_extract(
    search_query: str, extract_fields: list[str], instructions: str = ""
) -> BrowserResult:
    """
    Search for something and extract data

    Example:
        result = await search_and_extract(
            search_query="iPhone 15 Pro",
            extract_fields=["name", "price", "rating"],
            instructions="Compare top 5 products"
        )
    """
    task = BrowserTask(
        search_query=search_query,
        instruction=instructions or f"Extract {', '.join(extract_fields)}",
        extract_fields=extract_fields,
    )
    return await run_browser_task(task)


async def scrape_url(
    url: str, instruction: str, extract_fields: Optional[list[str]] = None
) -> BrowserResult:
    """
    Fetch and extract data from a specific URL

    Example:
        result = await scrape_url(
            url="https://shopee.vn/search?q=iphone15",
            instruction="Extract product info",
            extract_fields=["name", "price"]
        )
    """
    task = BrowserTask(
        url=url,
        instruction=instruction,
        extract_fields=extract_fields,
    )
    return await run_browser_task(task)
