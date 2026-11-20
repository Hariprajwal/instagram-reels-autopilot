import re
import time
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional
from playwright.async_api import Page

from config.settings import settings, PROFILE_SCREENSHOTS_DIR
from models.schemas import ProfileData, MessageAvailability
from core.comment_reader import CommentReader

class ProfileInspector:
    def __init__(self, page: Page):
        self.page = page
        self.selectors = settings.load_selectors().get("profile", {})

    async def wait_for_profile_load(self, username: str, timeout_ms: int = 10000) -> bool:
        """Waits for the profile page header or username element to render."""
        clean_user = username.strip().lstrip("@").lower()
        start = time.time()

        while (time.time() - start) * 1000 < timeout_ms:
            # Check if URL matches profile
            current_url = self.page.url.lower()
            if clean_user in current_url:
                # Wait for header elements
                header_selectors = self.selectors.get("header", ["header", "main header"])
                for s in header_selectors:
                    if await self.page.is_visible(s, timeout=600):
                        await asyncio.sleep(1.0)
                        return True
            await asyncio.sleep(0.5)

        return False

    async def inspect(self, username: str) -> ProfileData:
        """
        Extracts all visible profile information, public/private status,
        Message button availability, restrictions, bio, and captures screenshot.
        """
        clean_user = username.strip().lstrip("@").lower()
        print(f"[ProfileInspector] Inspecting profile for @{clean_user}...")

        is_loaded = await self.wait_for_profile_load(clean_user)
        if not is_loaded:
            print(f"[ProfileInspector] Warning: Profile for @{clean_user} did not load in time.")
            return ProfileData(
                username=clean_user,
                is_accessible=False,
                message_availability=MessageAvailability.PROFILE_INACCESSIBLE
            )

        # Capture screenshot
        screenshot_path = PROFILE_SCREENSHOTS_DIR / f"{clean_user}_{int(time.time())}.png"
        try:
            await self.page.screenshot(path=str(screenshot_path))
            print(f"[ProfileInspector] Captured profile screenshot: {screenshot_path.name}")
        except Exception as e:
            print(f"[ProfileInspector] Screenshot error: {e}")
            screenshot_path = None

        # Execute comprehensive DOM evaluation
        js_profile_inspect = """
        () => {
            const bodyText = document.body.innerText;

            // Check Private status
            const privatePhrases = [
                'This account is private',
                'This Account is Private',
                'Follow this account to see their photos and videos',
                'Follow to see their photos and videos'
            ];
            const isPrivate = privatePhrases.some(p => bodyText.includes(p));

            // Check Message Button (comprehensive multi-language & icon search)
            let hasMessageBtn = false;
            const messageKeywords = ['message', 'send message', 'direct', 'mensaje', 'mensagem', 'nachricht', 'invia un messaggio', 'संदेश', 'dm', 'contact'];
            const candidateElements = Array.from(document.querySelectorAll('header button, header div[role="button"], header a, main header button, main header div[role="button"], main header a'));
            
            for (const el of candidateElements) {
                const text = (el.innerText || '').trim().toLowerCase();
                const ariaLabel = (el.getAttribute('aria-label') || '').toLowerCase();
                const href = (el.getAttribute('href') || '').toLowerCase();
                
                // Direct link check
                if (href.includes('/direct/t/') || href.includes('/direct/new/') || href.includes('/direct/')) {
                    hasMessageBtn = true;
                    break;
                }
                
                // Text or aria-label check
                if (messageKeywords.some(kw => text === kw || text.includes(kw) || ariaLabel.includes(kw))) {
                    hasMessageBtn = true;
                    break;
                }
                
                // SVG inside candidate check
                const svgs = el.querySelectorAll('svg');
                for (const svg of svgs) {
                    const svgAria = (svg.getAttribute('aria-label') || '').toLowerCase();
                    if (messageKeywords.some(kw => svgAria.includes(kw))) {
                        hasMessageBtn = true;
                        break;
                    }
                }
                if (hasMessageBtn) break;
            }

            // Check Messaging Restrictions
            const restrictionPhrases = [
                'You can send 1 message to invite them to chat',
                'Only accounts that follow this user can send messages',
                'You can\\'t message this account unless they follow you',
                'This account can\\'t receive your message'
            ];
            let restriction = null;
            for (const r of restrictionPhrases) {
                if (bodyText.includes(r)) {
                    restriction = r;
                    break;
                }
            }

            // Extract Bio Text
            let bioText = '';
            const header = document.querySelector('header');
            if (header) {
                const bioSection = header.querySelector('section > div:last-child') || header;
                const bioSpans = Array.from(bioSection.querySelectorAll('span[dir="auto"], div[dir="auto"]'));
                const texts = bioSpans.map(s => s.innerText.trim()).filter(t => t.length > 0 && !t.includes('followers') && !t.includes('following') && !t.includes('posts'));
                bioText = texts.join(' | ').substring(0, 300);
            }

            return {
                is_private: isPrivate,
                has_message_btn: hasMessageBtn,
                restriction: restriction,
                bio: bioText
            };
        }
        """
        try:
            dom_data = await self.page.evaluate(js_profile_inspect)
            is_private = dom_data["is_private"]
            has_message_btn = dom_data["has_message_btn"]
            restriction = dom_data["restriction"]
            bio = dom_data["bio"]

            # Determine Message Availability
            if restriction:
                availability = MessageAvailability.MESSAGING_RESTRICTED
            elif has_message_btn:
                availability = MessageAvailability.MESSAGE_BUTTON_VISIBLE
            else:
                availability = MessageAvailability.MESSAGE_BUTTON_UNAVAILABLE

            print(f"[ProfileInspector] @{clean_user} -> Private: {is_private} | Message Btn: {has_message_btn} | Status: {availability.value}")

            return ProfileData(
                username=clean_user,
                is_private=is_private,
                message_button_found=has_message_btn,
                message_availability=availability,
                messaging_restrictions=restriction,
                bio_text=bio,
                is_accessible=True,
                screenshot_path=str(screenshot_path) if screenshot_path else None
            )
        except Exception as e:
            print(f"[ProfileInspector] Error inspecting DOM: {e}")
            return ProfileData(
                username=clean_user,
                is_accessible=False,
                message_availability=MessageAvailability.UNCERTAIN
            )

    async def open_message_dialog(self) -> bool:
        """
        Clicks the 'Message' button on the profile header to open the floating
        Direct Message chat drawer shown in the bottom-right corner.
        """
        print("[ProfileInspector] Clicking 'Message' button to open chat drawer...")
        message_selectors = self.selectors.get("message_button", [
            "div[role='button']:has-text('Message')",
            "button:has-text('Message')",
            "a:has-text('Message')",
            "div[role='button']:has-text('Send message')",
            "button:has-text('Send message')"
        ])

        for sel in message_selectors:
            try:
                btn = await self.page.wait_for_selector(sel, timeout=1800, state="visible")
                if btn:
                    await btn.scroll_into_view_if_needed()
                    await asyncio.sleep(0.3)
                    await btn.click()
                    await asyncio.sleep(2.0)
                    if await self._find_chat_input():
                        print("[ProfileInspector] Chat drawer opened successfully.")
                        return True
            except Exception:
                continue

        # JavaScript fallback click
        js_click_msg = """
        () => {
            const buttons = Array.from(document.querySelectorAll('header button, header div[role="button"], header a, main header button, main header div[role="button"]'));
            const keywords = ['message', 'send message', 'direct', 'mensaje', 'mensagem'];
            for (const b of buttons) {
                const text = (b.innerText || '').trim().toLowerCase();
                const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                if (keywords.some(k => text === k || text.includes(k) || aria.includes(k))) {
                    b.click();
                    return true;
                }
            }
            return false;
        }
        """
        try:
            clicked = await self.page.evaluate(js_click_msg)
            if clicked:
                await asyncio.sleep(2.0)
                return (await self._find_chat_input()) is not None
        except Exception:
            pass

        return False

    async def _find_chat_input(self):
        """Finds the contenteditable text input inside the floating DM drawer."""
        input_selectors = [
            "div[contenteditable='true'][role='textbox']",
            "div[aria-label*='Message'][contenteditable='true']",
            "div[contenteditable='true']",
            "textarea[placeholder*='Message']"
        ]
        for sel in input_selectors:
            try:
                el = await self.page.wait_for_selector(sel, timeout=1200, state="visible")
                if el:
                    return el
            except Exception:
                continue
        return None

    async def draft_or_send_message(self, question: str, auto_send: bool = True) -> bool:
        """
        Types the prepared question into the open chat drawer and sends it
        by pressing Enter and/or clicking the 'Send' button.
        """
        input_el = await self._find_chat_input()
        if not input_el:
            print("[ProfileInspector] Could not find chat message input box.")
            return False

        try:
            await input_el.click()
            await asyncio.sleep(0.3)
            # Type naturally with keystroke delay
            await input_el.type(question, delay=25)
            await asyncio.sleep(0.8)

            if auto_send:
                print(f"[ProfileInspector] Sending message to prospect: \"{question}\"")
                sent = await self._dispatch_send_action(input_el=input_el)
                return sent
            else:
                print(f"[ProfileInspector] Message drafted in Chrome chat box: \"{question}\"")
                return True
        except Exception as e:
            print(f"[ProfileInspector] Error typing/sending message: {e}")
            return False

    async def _dispatch_send_action(self, input_el=None) -> bool:
        """
        Dispatches the typed message to the recipient.
        Performs dual dispatch:
        1. Emits Enter keypress directly on the input element and keyboard.
        2. Clicks the visible 'Send' button or executes JS dispatch.
        Ensures the message is immediately transmitted without getting stuck.
        """
        print("[ProfileInspector] Dispatching message (Enter keypress + Send button click)...")

        # 1. Press Enter key on input element and keyboard
        try:
            if input_el:
                await input_el.focus()
                await input_el.press("Enter")
            await self.page.keyboard.press("Enter")
            print("[ProfileInspector] Pressed Enter key on message input.")
        except Exception as e:
            print(f"[ProfileInspector] Enter keypress notice: {e}")

        await asyncio.sleep(0.6)

        # 2. Try clicking the explicit 'Send' button beside the input box
        send_selectors = [
            "div[role='button']:has-text('Send')",
            "button:has-text('Send')",
            "div[tabindex='0']:has-text('Send')",
            "span:has-text('Send')",
            "div[aria-label='Send']",
            "svg[aria-label='Send']"
        ]
        clicked_send = False
        for sel in send_selectors:
            try:
                send_btn = await self.page.wait_for_selector(sel, timeout=800, state="visible")
                if send_btn:
                    await send_btn.click()
                    print(f"[ProfileInspector] Clicked 'Send' button in chat drawer ({sel}).")
                    clicked_send = True
                    await asyncio.sleep(0.8)
                    break
            except Exception:
                continue

        # 3. JavaScript evaluation fallback if Send button is still in DOM
        if not clicked_send:
            js_click_send = """
            () => {
                const candidates = Array.from(document.querySelectorAll('div[role="dialog"] button, div[role="dialog"] div[role="button"], div[role="dialog"] span, button, div[role="button"]'));
                for (const el of candidates) {
                    const text = (el.innerText || '').trim().toLowerCase();
                    const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                    if (text === 'send' || aria === 'send') {
                        el.click();
                        return true;
                    }
                }
                return false;
            }
            """
            try:
                if await self.page.evaluate(js_click_send):
                    print("[ProfileInspector] Dispatched JS Send button click.")
                    clicked_send = True
            except Exception:
                pass

        # Give network/WebSocket time to deliver message
        await asyncio.sleep(1.5)
        return True

    async def close_chat_dialog(self):
        """Closes the floating chat drawer so the screen is restored before navigating back."""
        close_selectors = [
            "div[role='dialog'] svg[aria-label='Close']",
            "svg[aria-label='Close']",
            "div[role='button']:has(svg[aria-label='Close'])"
        ]
        for sel in close_selectors:
            try:
                btn = await self.page.wait_for_selector(sel, timeout=1000, state="visible")
                if btn:
                    await btn.click()
                    await asyncio.sleep(0.5)
                    return
            except Exception:
                continue

        # Fallback: press Escape
        try:
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
        except Exception:
            pass

    async def return_to_reel_and_reopen_comments(self, reel_url: str, comment_reader: CommentReader):
        """Safely navigates back to the exact Reel and reopens comments."""
        print(f"[ProfileInspector] Returning to original Reel: {reel_url}...")
        try:
            await self.page.go_back(wait_until="domcontentloaded")
            await asyncio.sleep(1.5)
        except Exception:
            pass

        # If back navigation didn't land on Reel URL, navigate directly
        if reel_url not in self.page.url:
            print(f"[ProfileInspector] Fallback direct navigation to Reel: {reel_url}")
            await self.page.goto(reel_url, wait_until="domcontentloaded")
            await asyncio.sleep(2.0)

        # Confirm comments are reopened
        if not await comment_reader.is_comments_open():
            print("[ProfileInspector] Reopening comments panel...")
            await comment_reader.open_comments()
            await asyncio.sleep(1.0)

