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

