import asyncio
from typing import Optional, List
from playwright.async_api import async_playwright, Playwright, Browser, BrowserContext, Page
from config.settings import settings

class BrowserController:
    def __init__(self):
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.selectors = settings.load_selectors()

    async def connect(self) -> Page:
        """Connects to the already-running Chrome window via CDP."""
        print(f"[BrowserController] Connecting to Chrome CDP at {settings.chrome_cdp_url}...")
        self.playwright = await async_playwright().start()

        try:
            self.browser = await self.playwright.chromium.connect_over_cdp(settings.chrome_cdp_url)
        except Exception as e:
            raise ConnectionError(
                f"\n[ERROR] Could not connect to Chrome on {settings.chrome_cdp_url}.\n"
                f"Please ensure Google Chrome was launched with '--remote-debugging-port=9222'.\n"
                f"You can launch it easily by running 'launch_chrome.bat' or 'launch_chrome.ps1'.\n"
                f"Original error: {e}"
            )

        contexts = self.browser.contexts
        if not contexts:
            raise RuntimeError("No browser context found in running Chrome instance.")

        self.context = contexts[0]
        self.page = await self._find_or_wait_for_instagram_tab()
        print(f"[BrowserController] Successfully attached to Instagram tab: {self.page.url}")
        return self.page

    async def _find_or_wait_for_instagram_tab(self) -> Page:
        """Finds an open tab with instagram.com or attaches to the first active tab."""
        pages = self.context.pages
        for p in pages:
            if "instagram.com" in p.url:
                await p.bring_to_front()
                return p

        # If not found, use first page and wait or navigate
        if pages:
            page = pages[0]
            if "instagram.com" not in page.url:
                print("[BrowserController] No active Instagram tab found. Navigating existing tab to Instagram Reels...")
                await page.goto("https://www.instagram.com/reels/", wait_until="domcontentloaded")
            await page.bring_to_front()
            return page

        # If no pages at all (unlikely), create one in existing context
        page = await self.context.new_page()
        await page.goto("https://www.instagram.com/reels/", wait_until="domcontentloaded")
        return page

    async def get_page(self) -> Page:
        if not self.page or self.page.is_closed():
            self.page = await self._find_or_wait_for_instagram_tab()
        return self.page

    async def find_element_by_selectors(self, selector_list: List[str], timeout: int = 3000):
        """Tries multiple selectors in order and returns the first matching ElementHandle."""
        page = await self.get_page()
        for selector in selector_list:
            try:
                el = await page.wait_for_selector(selector, timeout=timeout, state="visible")
                if el:
                    return el
            except Exception:
                continue
        return None

    async def is_visible_any(self, selector_list: List[str]) -> bool:
        """Returns True if any selector in the list is currently visible."""
        page = await self.get_page()
        for selector in selector_list:
            try:
                visible = await page.is_visible(selector, timeout=800)
                if visible:
                    return True
            except Exception:
                continue
        return False

    async def safe_click(self, selector: str, timeout: int = 4000) -> bool:
        page = await self.get_page()
        try:
            el = await page.wait_for_selector(selector, timeout=timeout, state="visible")
            if el:
                await el.scroll_into_view_if_needed()
                await asyncio.sleep(0.3)
                await el.click()
                return True
        except Exception:
            pass
        return False

    async def safe_click_any(self, selector_list: List[str], timeout: int = 3000) -> bool:
        for selector in selector_list:
            if await self.safe_click(selector, timeout=timeout):
                return True
        return False

    async def close(self):
        """Disconnects without closing the user's Chrome window."""
        print("[BrowserController] Detaching from Chrome (browser will stay open)...")
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

