"""
Browser Agent - Automated web browsing and information extraction
Uses browser-use library with Claude vision
"""
import logging
import asyncio
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
            try:
                from browser_use import Agent as BrowserUseAgent
                return await self._execute_with_browser_use(task)
            except ImportError:
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
                instruction = f"Search for '{task.search_query}' and then: {instruction}"

            if task.extract_fields:
                instruction += f"\n\nExtract these fields: {', '.join(task.extract_fields)}"
                instruction += "\n\nReturn results as JSON"

            # Create agent
            agent = BrowserUseAgent(
                task=instruction,
                llm=self.llm,
            )

            # Run agent
            logger.info(f"🤖 Browser-use agent starting: {instruction[:100]}...")
            result = await agent.run()

            logger.info(f"✅ Browser-use completed")

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
            from bs4 import BeautifulSoup

            # If URL provided, fetch it
            if task.url:
                async with httpx.AsyncClient(
                    follow_redirects=True,
                    timeout=30
                ) as client:
                    response = await client.get(task.url)
                    response.raise_for_status()
                    html = response.text

                # Parse HTML
                soup = BeautifulSoup(html, 'html.parser')
                data = await self._extract_from_html(soup, task.extract_fields)

                logger.info(f"✅ Fallback extraction completed, found {len(data)} items")

                return BrowserResult(
                    success=True,
                    data=data,
                )

            elif task.search_query:
                # Use search API if configured
                logger.warning("Search fallback not fully implemented")
                return BrowserResult(
                    success=False,
                    error="Search fallback requires browser-use or external search API",
                )

            else:
                return BrowserResult(
                    success=False,
                    error="Must provide either URL or search query",
                )

        except Exception as e:
            logger.error(f"Fallback extraction error: {e}")
            raise

    def _parse_result(self, raw_result: Any, expected_fields: Optional[list] = None) -> dict:
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

    async def _extract_from_html(self, soup, fields: Optional[list] = None) -> list:
        """Extract structured data from HTML"""
        # Simple extraction - can be enhanced
        data = []

        # Look for common product containers
        for item in soup.select(".product, .item, .listing, article"):
            entry = {}

            # Try to extract common fields
            if not fields or "name" in fields:
                name_elem = item.select_one(".name, .title, h2, h3")
                if name_elem:
                    entry["name"] = name_elem.get_text(strip=True)

            if not fields or "price" in fields:
                price_elem = item.select_one(".price, .cost, .amount")
                if price_elem:
                    entry["price"] = price_elem.get_text(strip=True)

            if not fields or "url" in fields:
                url_elem = item.select_one("a")
                if url_elem and url_elem.get("href"):
                    entry["url"] = url_elem["href"]

            if not fields or "rating" in fields:
                rating_elem = item.select_one(".rating, .stars, .score")
                if rating_elem:
                    entry["rating"] = rating_elem.get_text(strip=True)

            if entry:
                data.append(entry)

        return data[:10]  # Return top 10 items


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
    search_query: str,
    extract_fields: list[str],
    instructions: str = ""
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
    url: str,
    instruction: str,
    extract_fields: Optional[list[str]] = None
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
