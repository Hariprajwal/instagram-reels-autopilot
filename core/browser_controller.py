import os
import shutil
import socket
import asyncio
import subprocess
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

    @staticmethod
    def _is_port_in_use(port: int = 9222, host: str = "127.0.0.1") -> bool:
        """Checks if a local TCP port is already accepting connections."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                return s.connect_ex((host, port)) == 0
        except Exception:
            return False

    @staticmethod
    def _find_chrome_executable() -> Optional[str]:
        """Locates the Google Chrome binary on standard Windows installation paths."""
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe")
        ]
        for p in candidates:
            if os.path.isfile(p):
                return p
        return shutil.which("chrome") or shutil.which("google-chrome")

    @staticmethod
    def _is_chrome_process_running() -> bool:
        """Checks if any chrome.exe process is currently running on the system."""
        try:
            output = subprocess.check_output(
                ["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            )
            return "chrome.exe" in output.lower()
        except Exception:
            return False

    async def _auto_launch_chrome(self) -> bool:
        """
        Automatically launches Google Chrome with --remote-debugging-port=9222.
        If Chrome is already running without remote debugging, restarts it with
        --restore-last-session so existing tabs and Instagram logins are preserved.
        """
        chrome_bin = self._find_chrome_executable()
        if not chrome_bin:
            raise FileNotFoundError(
                "[BrowserController] Google Chrome was not found in standard directories.\n"
                "Please ensure Google Chrome is installed on your computer."
            )

        print("\n[BrowserController] Chrome is not active on port 9222.")
        if self._is_chrome_process_running():
            print("[BrowserController] Existing Chrome process detected without debugging port.")
            print("[BrowserController] Restarting Chrome with --remote-debugging-port=9222 (restoring last session)...")
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", "chrome.exe"],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
                )
                await asyncio.sleep(1.8)
            except Exception as e:
                print(f"[BrowserController] Process termination warning: {e}")

        print(f"[BrowserController] Launching Chrome from: {chrome_bin}...")
        cmd = [
            chrome_bin,
            "--remote-debugging-port=9222",
            "--remote-allow-origins=*",
            "--disable-blink-features=AutomationControlled",
            "--restore-last-session",
            "https://www.instagram.com/reels/"
        ]

        try:
            subprocess.Popen(
                cmd,
                shell=False,
                creationflags=subprocess.DETACHED_PROCESS if hasattr(subprocess, "DETACHED_PROCESS") else 0
            )
        except Exception as e:
            raise RuntimeError(f"[BrowserController] Failed to launch Chrome process: {e}")

        print("[BrowserController] Waiting for Chrome remote debugging port to become ready...")
        for attempt in range(24):
            await asyncio.sleep(0.5)
            if self._is_port_in_use(9222):
                print("[BrowserController] ✓ Chrome remote debugging is active on http://127.0.0.1:9222!")
                await asyncio.sleep(1.2)
                return True

        raise TimeoutError("[BrowserController] Timed out waiting for Chrome to open remote debugging port 9222.")

    async def connect(self) -> Page:
        """
        Connects to Chrome via CDP.
        If port 9222 is not yet open, automatically launches Google Chrome with
        remote debugging enabled so manual pre-launching is never required.
        """
        self.playwright = await async_playwright().start()

        # Step 1: Automatically ensure Chrome is running on port 9222
        if not self._is_port_in_use(9222):
            await self._auto_launch_chrome()

        # Step 2: Connect over CDP
        print(f"[BrowserController] Connecting to Chrome CDP at {settings.chrome_cdp_url}...")
        try:
            self.browser = await self.playwright.chromium.connect_over_cdp(settings.chrome_cdp_url)
        except Exception as e:
            print(f"[BrowserController] Initial connection attempt failed ({e}). Retrying auto-launch...")
            await self._auto_launch_chrome()
            self.browser = await self.playwright.chromium.connect_over_cdp(settings.chrome_cdp_url)

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

    async def check_security_checkpoint(self) -> bool:
        """
        Detects if Meta/Instagram has presented a reCAPTCHA, challenge, or security checkpoint.
        Inspects URL, active frames, and page DOM for Meta reCAPTCHA Enterprise indicators.
        Returns True if a challenge/checkpoint is detected.
        """
        page = await self.get_page()
        current_url = page.url.lower()

        # 1. Check URL indicators
        url_triggers = ["/challenge/", "/checkpoint/", "recaptcha", "security_check", "help/checkpoint"]
        if any(term in current_url for term in url_triggers):
            return True

        # 2. Check all active frames (reCAPTCHA Enterprise renders in cross-origin frames)
        try:
            for frame in page.frames:
                frame_url = frame.url.lower()
                if any(k in frame_url for k in ["recaptcha", "hcaptcha", "/challenge/", "/checkpoint/"]):
                    return True
        except Exception:
            pass

        # 3. Check page body text for Meta reCAPTCHA Enterprise phrases
        js_check_checkpoint = """
        () => {
            const text = (document.body ? document.body.innerText : '').toLowerCase();
            const triggers = [
                'combat harmful conduct',
                'recaptcha enterprise',
                "i'm not a robot",
                'confirm it\\'s you',
                'help us confirm you own this account',
                'suspicious activity',
                'checkpoint_required',
                'unusual activity',
                'confirm your info',
                'security check'
            ];
            for (const t of triggers) {
                if (text.includes(t)) return true;
            }

            // Check if reCAPTCHA iframe or container is present
            const recaptchaEl = document.querySelector('iframe[src*="recaptcha"], iframe[title*="reCAPTCHA"], div.g-recaptcha, .recaptcha-checkbox');
            if (recaptchaEl) return true;

            return false;
        }
        """
        try:
            if await page.evaluate(js_check_checkpoint):
                return True
        except Exception:
            pass

        return False

    async def wait_for_user_to_resolve_checkpoint(self, poll_interval: float = 2.0) -> bool:
        """
        Pauses automation when a security challenge/CAPTCHA is detected, yields control
        to the user, and waits until the user manually resolves it in their Chrome window.
        """
        if not await self.check_security_checkpoint():
            return True

        print("\a", end="", flush=True)  # System bell for audible notification
        print("\n" + "═" * 74)
        print(" [SECURITY CHECKPOINT / CAPTCHA DETECTED]")
        print(" Meta/Instagram has presented an 'I'm not a robot' / reCAPTCHA challenge.")
        print(" Automation is safely paused to safeguard your Instagram account.")
        print(" >>> PLEASE SOLVE THE VERIFICATION MANUALLY IN YOUR CHROME WINDOW <<<")
        print(" The agent is on standby and will automatically resume once cleared...")
        print("═" * 74 + "\n")

        while True:
            await asyncio.sleep(poll_interval)
            still_blocked = await self.check_security_checkpoint()
            if not still_blocked:
                print("\n[SUCCESS] Security check resolved! Resuming investigation...\n")
                await asyncio.sleep(2.0)
                return True

    async def close(self):
        """Disconnects without closing the user's Chrome window."""
        print("[BrowserController] Detaching from Chrome (browser will stay open)...")
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

