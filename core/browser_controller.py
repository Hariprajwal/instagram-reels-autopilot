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

    # ──────────────────────────────────────────────────────────────
    # Chrome auto-launch helpers
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _is_port_open(port: int = 9222, host: str = "127.0.0.1") -> bool:
        """Returns True if something is already listening on the given port."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                return s.connect_ex((host, port)) == 0
        except Exception:
            return False

    @staticmethod
    def _find_chrome() -> Optional[str]:
        """Locates the Google Chrome binary on common Windows paths."""
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
        ]
        for p in candidates:
            if os.path.isfile(p):
                return p
        return shutil.which("chrome") or shutil.which("google-chrome")

    @staticmethod
    def _kill_existing_chrome() -> None:
        """
        Kills any running Chrome processes that do NOT have the debug port open.
        This is needed because Chrome won't start a second instance with --remote-debugging-port
        if one is already running (it just opens a new window in the existing process).
        """
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5
            )
            if "chrome.exe" in result.stdout.lower():
                print("[BrowserController] Existing Chrome process detected without debugging port.")
                print("[BrowserController] Killing existing Chrome so debug instance can start cleanly...")
                subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True, timeout=5)
                import time
                time.sleep(1.5)   # Wait for Chrome to fully exit
                print("[BrowserController] ✓ Existing Chrome terminated.")
        except Exception as e:
            print(f"[BrowserController] Warning: could not kill Chrome: {e}")

    async def _launch_chrome_with_debugging(self) -> bool:
        """
        Launches Chrome with --remote-debugging-port=9222 and a dedicated
        user-data-dir so the profile (with Instagram already logged in) is reused.
        Kills any existing Chrome that would block the debug port from opening.
        Waits up to 15 seconds for the port to open.
        """
        chrome_bin = self._find_chrome()
        if not chrome_bin:
            raise FileNotFoundError(
                "[BrowserController] Google Chrome not found. "
                "Please install Chrome and try again."
            )

        profile_dir = str(settings.chrome_user_data_dir)
        os.makedirs(profile_dir, exist_ok=True)

        # If Chrome is running but NOT on port 9222, kill it first
        if not self._is_port_open(9222):
            self._kill_existing_chrome()

        print(f"\n[BrowserController] Launching Chrome debug instance on port 9222...")
        print(f"[BrowserController] Profile dir : {profile_dir}")
        print(f"[BrowserController] Chrome binary: {chrome_bin}")

        cmd = [
            chrome_bin,
            "--remote-debugging-port=9222",
            f"--user-data-dir={profile_dir}",
            "--remote-allow-origins=*",
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
            "--restore-last-session",
            "https://www.instagram.com/reels/",
        ]
        try:
            subprocess.Popen(
                cmd,
                shell=False,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )
        except Exception as e:
            raise RuntimeError(f"[BrowserController] Failed to launch Chrome: {e}")

        print("[BrowserController] Waiting for Chrome debugging port 9222 to open...")
        for i in range(30):         # 30 × 0.5s = 15 s max
            await asyncio.sleep(0.5)
            if self._is_port_open(9222):
                print("[BrowserController] ✓ Chrome debug port 9222 is ready!")
                await asyncio.sleep(2.0)   # Let the tab finish loading
                return True

        raise TimeoutError(
            "[BrowserController] Chrome launched but port 9222 never opened.\n"
            "Try running 'launch_chrome.ps1' manually, or close all Chrome windows and retry."
        )

    # ──────────────────────────────────────────────────────────────
    # Main connect entry-point
    # ──────────────────────────────────────────────────────────────

    async def connect(self) -> Page:
        """
        Connects to Chrome via CDP on port 9222.
        If Chrome is not already running on that port, automatically launches
        a dedicated debugging instance — no manual pre-launch required.
        """
        self.playwright = await async_playwright().start()

        # Auto-launch if port is closed
        if not self._is_port_open(9222):
            await self._launch_chrome_with_debugging()

        print(f"[BrowserController] Connecting to Chrome CDP at {settings.chrome_cdp_url}...")
        try:
            self.browser = await self.playwright.chromium.connect_over_cdp(settings.chrome_cdp_url)
        except Exception as e:
            # Port opened but CDP handshake failed — give Chrome one more second
            await asyncio.sleep(2.0)
            try:
                self.browser = await self.playwright.chromium.connect_over_cdp(settings.chrome_cdp_url)
            except Exception:
                raise ConnectionError(
                    f"\n[ERROR] Could not connect to Chrome on {settings.chrome_cdp_url}.\n"
                    f"Please close all Chrome windows, then run 'launch_chrome.ps1' manually.\n"
                    f"Original error: {e}"
                )

        contexts = self.browser.contexts
        if not contexts:
            raise RuntimeError("No browser context found in the Chrome instance.")

        self.context = contexts[0]
        self.page = await self._find_or_wait_for_instagram_tab()
        await self._handle_auto_login_if_needed(self.page)
        print(f"[BrowserController] ✓ Connected. Active tab: {self.page.url}")
        return self.page

    # ──────────────────────────────────────────────────────────────
    # Instagram auto-login
    # ──────────────────────────────────────────────────────────────

    async def _handle_auto_login_if_needed(self, page: Page) -> bool:
        """
        If Instagram is showing a login form, fills credentials from .env
        and logs in automatically.  Dismisses post-login dialogs, then
        navigates to /reels/.
        """
        await asyncio.sleep(1.0)

        # Detect login page
        is_login = "/accounts/login" in page.url.lower()
        if not is_login:
            try:
                u = await page.wait_for_selector(
                    "input[name='username'], input[aria-label*='username'], input[aria-label*='Mobile number']",
                    timeout=1500, state="visible"
                )
                p = await page.wait_for_selector(
                    "input[name='password'], input[type='password']",
                    timeout=1500, state="visible"
                )
                if u and p:
                    is_login = True
            except Exception:
                pass

        if not is_login:
            return True

        username = settings.instagram_username
        password = settings.instagram_password

        if not username or not password:
            print("\n[BrowserController] Instagram login page detected but no credentials in .env.")
            print(" >>> Please log in manually in the Chrome window <<<")
            return True

        print(f"\n[BrowserController] Instagram login detected — auto-logging in as @{username}...")

        try:
            # Fill username
            u_el = await page.wait_for_selector(
                "input[name='username'], input[aria-label*='username'], input[aria-label*='Mobile number']",
                timeout=3000, state="visible"
            )
            if u_el:
                cur = await u_el.input_value()
                if not cur:
                    await u_el.click()
                    await u_el.type(username, delay=35)
                    await asyncio.sleep(0.3)

            # Fill password
            p_el = await page.wait_for_selector(
                "input[name='password'], input[type='password']",
                timeout=3000, state="visible"
            )
            if p_el:
                cur = await p_el.input_value()
                if not cur:
                    await p_el.click()
                    await p_el.type(password, delay=35)
                    await asyncio.sleep(0.5)

            # Click Log In
            login_btn = await page.wait_for_selector(
                "button[type='submit'], button:has-text('Log in'), button:has-text('Log In')",
                timeout=2500, state="visible"
            )
            if login_btn:
                await login_btn.click()
            else:
                await page.keyboard.press("Enter")

            print("[BrowserController] Submitted login — waiting for redirect...")

            # Wait for redirect away from login page
            for _ in range(20):
                await asyncio.sleep(0.6)
                if await self.check_security_checkpoint():
                    await self.wait_for_user_to_resolve_checkpoint()
                    break
                if "/accounts/login" not in page.url.lower():
                    try:
                        if not await page.is_visible("input[name='password']", timeout=400):
                            break
                    except Exception:
                        break

            # Dismiss "Save login info?" dialog
            await asyncio.sleep(1.2)
            for sel in ["button:has-text('Not now')", "button:has-text('Not Now')", "div[role='button']:has-text('Not now')"]:
                try:
                    btn = await page.wait_for_selector(sel, timeout=1000, state="visible")
                    if btn:
                        await btn.click()
                        await asyncio.sleep(0.6)
                        break
                except Exception:
                    continue

            # Dismiss "Turn on notifications?" dialog
            for sel in ["button:has-text('Not Now')", "button:has-text('Not now')"]:
                try:
                    btn = await page.wait_for_selector(sel, timeout=800, state="visible")
                    if btn:
                        await btn.click()
                        await asyncio.sleep(0.5)
                        break
                except Exception:
                    continue

            # Ensure we land on Reels
            if "/reels" not in page.url.lower():
                await page.goto("https://www.instagram.com/reels/", wait_until="domcontentloaded")
                await asyncio.sleep(1.5)

            print(f"[BrowserController] ✓ Logged in! Now on: {page.url}")
            return True

        except Exception as e:
            print(f"[BrowserController] Auto-login notice: {e} — you can log in manually.")
            return False

    async def _find_or_wait_for_instagram_tab(self) -> Page:
        """Finds an open tab with instagram.com or attaches to the first active tab, ensuring it opens directly on Reels."""
        target_url = "https://www.instagram.com/reels/"
        pages = self.context.pages
        for p in pages:
            if "instagram.com" in p.url:
                await p.bring_to_front()
                if "/reels" not in p.url.lower():
                    print("[BrowserController] Navigating active Instagram tab directly to Reels...")
                    await p.goto(target_url, wait_until="domcontentloaded")
                return p

        # If not found, use first page and wait or navigate
        if pages:
            page = pages[0]
            if "/reels" not in page.url.lower():
                print("[BrowserController] Navigating existing tab directly to Instagram Reels...")
                await page.goto(target_url, wait_until="domcontentloaded")
            await page.bring_to_front()
            return page

        # If no pages at all (unlikely), create one in existing context
        page = await self.context.new_page()
        await page.goto(target_url, wait_until="domcontentloaded")
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

