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
        Automatically launches Google Chrome with --remote-debugging-port=9222 and a
        dedicated user-data-dir in session_data/chrome_profile.
        Using a dedicated profile guarantees that Chrome opens a standalone debugging
        window with port 9222 active, without attaching to existing personal Chrome
        windows or requiring personal Chrome to be closed.
        """
        chrome_bin = self._find_chrome_executable()
        if not chrome_bin:
            raise FileNotFoundError(
                "[BrowserController] Google Chrome was not found in standard directories.\n"
                "Please ensure Google Chrome is installed on your computer."
            )

        profile_dir = str(getattr(settings, "chrome_user_data_dir", os.path.join("session_data", "chrome_profile")))
        profile_name = str(getattr(settings, "chrome_profile_directory", "Default"))
        os.makedirs(profile_dir, exist_ok=True)

        print("\n[BrowserController] Chrome is not active on port 9222.")
        print(f"[BrowserController] Launching dedicated Chrome on port 9222 (profile: {profile_dir}, directory: {profile_name})...")
        cmd = [
            chrome_bin,
            "--remote-debugging-port=9222",
            f"--user-data-dir={profile_dir}",
            f"--profile-directory={profile_name}",
            "--remote-allow-origins=*",
            "--disable-blink-features=AutomationControlled",
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
        try:
            self.playwright = await async_playwright().start()

            # Step 1: Automatically ensure Chrome is running on port 9222
            if not self._is_port_in_use(9222):
                await self._auto_launch_chrome()

            # Step 2: Connect over CDP
            print(f"[BrowserController] Connecting to Chrome CDP at {settings.chrome_cdp_url}...")
            self.browser = await self.playwright.chromium.connect_over_cdp(settings.chrome_cdp_url)

            contexts = self.browser.contexts
            if not contexts:
                raise RuntimeError("No browser context found in running Chrome instance.")

            self.context = contexts[0]

            # Step 3: Handle Google account sign-in & dismiss Chrome sync prompt if presented
            await self._handle_google_signin_if_needed()
            await self._handle_chrome_sync_prompt()

            # Step 4: Locate or navigate to Instagram tab
            self.page = await self._find_or_wait_for_instagram_tab()

            # Step 5: Check sync prompt again and perform Instagram auto-login if needed
            await self._handle_chrome_sync_prompt()
            await self._handle_auto_login_if_needed(self.page)
            print(f"[BrowserController] Successfully attached to Instagram tab: {self.page.url}")
            return self.page
        except Exception as e:
            if self.playwright:
                try:
                    await self.playwright.stop()
                except Exception:
                    pass
            raise e

    async def _handle_chrome_sync_prompt(self) -> bool:
        """
        Detects the Chrome sync modal dialog:
        'To quickly get back to sites you've visited, sync your history and tabs'
        and automatically clicks 'No thanks' as requested.
        """
        if not self.context:
            return False

        handled = False
        for p in self.context.pages:
            try:
                # 1. Direct Playwright selector search across all visible buttons
                no_thanks_selectors = [
                    "button:has-text('No thanks')",
                    "button:has-text('No Thanks')",
                    "div[role='button']:has-text('No thanks')",
                    "div[role='button']:has-text('No Thanks')",
                    "cr-button#notNowButton",
                    "cr-button:has-text('No thanks')",
                    "cr-button:has-text('No Thanks')",
                    "button#cancelButton",
                    "[aria-label*='No thanks']",
                    "[aria-label*='No Thanks']"
                ]
                for sel in no_thanks_selectors:
                    try:
                        btn = await p.wait_for_selector(sel, timeout=300, state="visible")
                        if btn:
                            await btn.click()
                            print("[BrowserController] ✓ Detected Chrome Sync prompt. Clicked 'No thanks' as requested.")
                            handled = True
                            await asyncio.sleep(0.5)
                            break
                    except Exception:
                        continue

                # 2. Deep DOM and Shadow DOM traversal for Chrome WebUI sync dialogs
                try:
                    clicked = await p.evaluate('''() => {
                        const findAndClickNoThanks = (root) => {
                            if (!root) return false;
                            const elements = root.querySelectorAll('button, div[role="button"], cr-button, [role="button"]');
                            for (const el of elements) {
                                const text = (el.textContent || el.innerText || '').trim().toLowerCase();
                                if (text === 'no thanks' || text === 'not now') {
                                    el.click();
                                    return true;
                                }
                            }
                            const allNodes = root.querySelectorAll('*');
                            for (const node of allNodes) {
                                if (node.shadowRoot) {
                                    const found = findAndClickNoThanks(node.shadowRoot);
                                    if (found) return true;
                                }
                            }
                            return false;
                        };
                        return findAndClickNoThanks(document);
                    }''')
                    if clicked:
                        print("[BrowserController] ✓ Dismissed Chrome Sync prompt ('No thanks' clicked via Shadow DOM).")
                        handled = True
                        await asyncio.sleep(0.5)
                except Exception:
                    pass

            except Exception:
                continue

        return handled

    async def _handle_google_signin_if_needed(self) -> bool:
        """
        Detects if a tab is open to Google Sign-in / 'Sign in to Chrome'.
        If google_email and google_password are provided, automatically fills them in,
        advances through the sign-in flow, and dismisses any sync prompts with 'No thanks'.
        """
        if not self.context:
            return False

        email = settings.google_email
        password = settings.google_password
        if not email:
            return False

        for p in self.context.pages:
            try:
                url = p.url.lower()
                is_google_signin = ("accounts.google.com" in url) or ("signin-dice-web" in url) or ("chrome://signin" in url)
                if not is_google_signin:
                    continue

                print(f"\n[BrowserController] Google / Chrome sign-in page detected ({p.url}).")
                print(f"[BrowserController] Automatically authenticating with Google account: {email}...")

                # 1. Fill email if input is visible
                email_input = await p.wait_for_selector(
                    "input[type='email'], input[name='identifier'], input#identifierId, input[aria-label*='Email']",
                    timeout=2000,
                    state="visible"
                )
                if email_input:
                    current_val = await email_input.input_value()
                    if current_val != email:
                        await email_input.click()
                        await email_input.fill("")
                        await email_input.type(email, delay=30)
                        await asyncio.sleep(0.3)

                    # Click Next
                    next_btn = await p.wait_for_selector(
                        "#identifierNext, button:has-text('Next'), div[role='button']:has-text('Next')",
                        timeout=2000,
                        state="visible"
                    )
                    if next_btn:
                        await next_btn.click()
                    else:
                        await p.keyboard.press("Enter")

                    print("[BrowserController] Submitted Google email. Waiting for password prompt...")
                    await asyncio.sleep(2.0)

                # 2. Fill password if visible
                if password:
                    try:
                        pass_input = await p.wait_for_selector(
                            "input[type='password'], input[name='Passwd'], input[name='password']",
                            timeout=4000,
                            state="visible"
                        )
                        if pass_input:
                            await pass_input.click()
                            await pass_input.fill("")
                            await pass_input.type(password, delay=30)
                            await asyncio.sleep(0.3)

                            next_pass = await p.wait_for_selector(
                                "#passwordNext, button:has-text('Next'), div[role='button']:has-text('Next')",
                                timeout=2000,
                                state="visible"
                            )
                            if next_pass:
                                await next_pass.click()
                            else:
                                await p.keyboard.press("Enter")

                            print("[BrowserController] Submitted Google password. Waiting for completion...")
                            await asyncio.sleep(2.5)
                    except Exception:
                        pass

                # 3. Check for sync prompt right after sign-in
                await self._handle_chrome_sync_prompt()
                return True

            except Exception as e:
                print(f"[BrowserController] Google sign-in notice: {e}")
                continue

        return False

    async def _handle_auto_login_if_needed(self, page: Page) -> bool:
        """
        Detects if Instagram is showing a login page or login prompt.
        If credentials are provided in settings, automatically fills username and password,
        submits login, dismisses post-login prompts, and navigates to Reels.
        """
        await asyncio.sleep(1.0)

        # Check if login form is present
        is_login = False
        current_url = page.url.lower()
        if "/accounts/login" in current_url:
            is_login = True
        else:
            try:
                user_input = await page.wait_for_selector(
                    "input[name='username'], input[aria-label*='username'], input[aria-label*='Mobile number']",
                    timeout=1800,
                    state="visible"
                )
                pass_input = await page.wait_for_selector(
                    "input[name='password'], input[type='password']",
                    timeout=1800,
                    state="visible"
                )
                if user_input and pass_input:
                    is_login = True
            except Exception:
                is_login = False

        if not is_login:
            return True

        username = settings.instagram_username
        password = settings.instagram_password

        if not username or not password:
            print("\n" + "=" * 70)
            print(" [INSTAGRAM LOGIN REQUIRED]")
            print(" Instagram is displaying the login page, but credentials were not found in .env.")
            print(" >>> PLEASE LOG IN TO INSTAGRAM IN YOUR CHROME WINDOW <<<")
            print(" (Your login will be saved permanently in session_data/chrome_profile)")
            print("=" * 70 + "\n")
            return True

        print(f"\n[BrowserController] Instagram login screen detected. Automatically logging in as @{username}...")

        try:
            # 1. Fill username (skip retyping if already autofilled by Chrome)
            user_el = await page.wait_for_selector(
                "input[name='username'], input[aria-label*='username'], input[aria-label*='Mobile number']",
                timeout=3000,
                state="visible"
            )
            if user_el:
                cur_user = await user_el.input_value()
                if not cur_user:
                    await user_el.click()
                    await user_el.fill("")
                    await user_el.type(username, delay=35)
                    await asyncio.sleep(0.3)

            # 2. Fill password (skip retyping if already autofilled by Chrome)
            pass_el = await page.wait_for_selector(
                "input[name='password'], input[type='password']",
                timeout=3000,
                state="visible"
            )
            if pass_el:
                cur_pass = await pass_el.input_value()
                if not cur_pass:
                    await pass_el.click()
                    await pass_el.fill("")
                    await pass_el.type(password, delay=35)
                    await asyncio.sleep(0.5)

            # 3. Click Log In button
            login_btn = await page.wait_for_selector(
                "button[type='submit'], button:has-text('Log in'), button:has-text('Log In'), div[role='button']:has-text('Log in')",
                timeout=2500,
                state="visible"
            )
            if login_btn:
                await login_btn.click()
                print("[BrowserController] Clicked 'Log in' button. Authenticating...")
            else:
                await page.keyboard.press("Enter")

            # 4. Wait for authentication navigation
            for _ in range(20):
                await asyncio.sleep(0.6)
                if await self.check_security_checkpoint():
                    await self.wait_for_user_to_resolve_checkpoint()
                    break

                current_url = page.url.lower()
                if "/accounts/login" not in current_url:
                    try:
                        if not await page.is_visible("input[name='password']", timeout=400):
                            break
                    except Exception:
                        break

            # 5. Dismiss "Save your login info?" dialog if present
            await asyncio.sleep(1.2)
            save_selectors = [
                "button:has-text('Save info')",
                "button:has-text('Save Info')",
                "button:has-text('Not now')",
                "button:has-text('Not Now')",
                "div[role='button']:has-text('Not now')"
            ]
            for sel in save_selectors:
                try:
                    btn = await page.wait_for_selector(sel, timeout=1200, state="visible")
                    if btn:
                        await btn.click()
                        print("[BrowserController] Handled login info dialog.")
                        await asyncio.sleep(0.8)
                        break
                except Exception:
                    continue

            # 6. Dismiss "Turn on notifications" dialog if present
            notif_selectors = [
                "button:has-text('Not Now')",
                "button:has-text('Not now')",
                "div[role='button']:has-text('Not now')"
            ]
            for sel in notif_selectors:
                try:
                    btn = await page.wait_for_selector(sel, timeout=1000, state="visible")
                    if btn:
                        await btn.click()
                        print("[BrowserController] Handled notifications dialog.")
                        await asyncio.sleep(0.5)
                        break
                except Exception:
                    continue

            # 7. Ensure active page is on Reels
            if "/reels" not in page.url.lower():
                print("[BrowserController] Navigating to Instagram Reels...")
                await page.goto("https://www.instagram.com/reels/", wait_until="domcontentloaded")
                await asyncio.sleep(1.5)

            print(f"[BrowserController] ✓ Successfully logged in and ready on Instagram Reels!")
            return True

        except Exception as e:
            print(f"[BrowserController] Auto-login notice: {e}. You can log in manually in Chrome.")
            return False

    async def _find_or_wait_for_instagram_tab(self) -> Page:
        """Finds an open tab with instagram.com or attaches to the first active tab."""
        pages = self.context.pages
        for p in pages:
            if "instagram.com" in p.url:
                await p.bring_to_front()
                return p

        # If not found, use first page (preferring non-Google signin pages) and navigate
        if pages:
            non_google_pages = [p for p in pages if "accounts.google.com" not in p.url and "signin" not in p.url.lower()]
            page = non_google_pages[0] if non_google_pages else pages[0]
            if "instagram.com" not in page.url:
                print("[BrowserController] No active Instagram tab found. Navigating tab to Instagram Reels...")
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

