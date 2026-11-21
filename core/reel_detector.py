import re
import time
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
from playwright.async_api import Page

from config.settings import settings, REEL_SCREENSHOTS_DIR
from models.schemas import ReelContext

class ReelDetector:
    def __init__(self, page: Page):
        self.page = page
        self.selectors = settings.load_selectors().get("reel", {})
        self.current_reel_id: Optional[str] = None
        self.last_change_time: float = 0.0

    async def get_active_reel_info(self) -> dict:
        """Extracts current URL, Reel ID/shortcode, author, and visible caption via DOM evaluation."""
        js_script = """
        () => {
            const url = window.location.href;
            let reelId = null;

            // Extract from URL if present
            const match = url.match(/\\/(?:reel|reels)\\/([A-Za-z0-9_-]+)/);
            if (match && match[1]) {
                reelId = match[1];
            }

            // Find visible video near center of viewport
            const videos = Array.from(document.querySelectorAll('video'));
            const midY = window.innerHeight / 2;
            let activeVideo = null;
            let minDistance = Infinity;

            for (const v of videos) {
                const rect = v.getBoundingClientRect();
                if (rect.height > 0 && rect.width > 0) {
                    const center = rect.top + rect.height / 2;
                    const dist = Math.abs(center - midY);
                    if (dist < minDistance) {
                        minDistance = dist;
                        activeVideo = v;
                    }
                }
            }

            // If reelId wasn't in URL, find permalink inside the active reel container
            if (!reelId && activeVideo) {
                const container = activeVideo.closest('article') || activeVideo.closest('div[role="presentation"]') || activeVideo.parentElement?.parentElement;
                if (container) {
                    const reelLink = container.querySelector('a[href*="/reel/"], a[href*="/reels/"]');
                    if (reelLink) {
                        const m = (reelLink.getAttribute('href') || '').match(/\/(?:reel|reels)\/([A-Za-z0-9_-]+)/);
                        if (m && m[1]) {
                            reelId = m[1];
                        }
                    }
                }
            }

            // Fallback to video src hash if no permalink in DOM
            if (!reelId && activeVideo) {
                const src = activeVideo.getAttribute('src') || '';
                reelId = 'vid_' + Math.abs(src.split('').reduce((a,b)=>{a=((a<<5)-a)+b.charCodeAt(0);return a&a},0)).toString(16);
            }

            // Find author and caption
            let author = '';
            let caption = '';

            const authorEls = document.querySelectorAll('article a[role="link"], header a[role="link"], div[role="presentation"] a[role="link"]');
            for (const el of authorEls) {
                const href = el.getAttribute('href') || '';
                if (href.startsWith('/') && !href.includes('/reel/') && !href.includes('/explore/') && !href.includes('/direct/')) {
                    const text = el.innerText.trim();
                    if (text && text.length > 1) {
                        author = text.replace(/^@/, '');
                        break;
                    }
                }
            }

            const captionEls = document.querySelectorAll('article h1, article span[dir="auto"], article div[dir="auto"]');
            for (const el of captionEls) {
                const text = el.innerText.trim();
                if (text && text.length > 5 && !text.includes('Follow') && !text.includes('Liked by')) {
                    caption = text.substring(0, 300);
                    break;
                }
            }

            return {
                url: url,
                reel_id: reelId || 'unknown_reel',
                author: author || 'unknown_creator',
                caption: caption || ''
            };
        }
        """
        try:
            info = await self.page.evaluate(js_script)
            reel_id = info.get("reel_id")
            if reel_id and not reel_id.startswith("unknown") and not reel_id.startswith("vid_"):
                info["url"] = f"https://www.instagram.com/reel/{reel_id}/"
            return info
        except Exception as e:
            return {
                "url": self.page.url,
                "reel_id": "unknown_reel",
                "author": "unknown",
                "caption": ""
            }

    async def wait_for_user_to_settle_on_reel(self, state_manager=None) -> ReelContext:
        """
        Continuously monitors user manual scrolling or automatic navigation.
        Only returns when settled on an uninspected Reel for cooldown seconds.
        If the current Reel was already processed, automatically advances past it.

        FIXED: We track how many consecutive skip-advances we've done so we don't
        loop back to reel-1 when ALL known reels have been processed. After 5 skips
        without finding a fresh reel we just wait for the user to manually scroll
        to a new one (instead of wrapping around forever).
        """
        cooldown = settings.reel_cooldown_seconds
        print(f"\n[ReelDetector] Waiting for user to scroll and settle on a Reel for {cooldown:.0f} seconds...")

        last_seen_id = None
        settle_start_time = None
        consecutive_skips = 0
        MAX_CONSECUTIVE_SKIPS = 5  # Safety: stop auto-advancing after this many misses

        while True:
            info = await self.get_active_reel_info()
            detected_id = info["reel_id"]

            # If this reel was already processed in this session, skip it once — but
            # don't loop endlessly if all visible reels were already done.
            if (state_manager and detected_id
                    and not detected_id.startswith("unknown")
                    and state_manager.is_reel_processed(detected_id)):
                consecutive_skips += 1
                if consecutive_skips <= MAX_CONSECUTIVE_SKIPS:
                    print(f"[ReelDetector] Reel [{detected_id}] already investigated (skip {consecutive_skips}/{MAX_CONSECUTIVE_SKIPS}). Advancing...")
                    await self.navigate_to_next_reel()
                    await asyncio.sleep(1.5)
                    last_seen_id = None
                    settle_start_time = None
                else:
                    # Too many consecutive skips — stop auto-advancing and just wait for user to scroll
                    if consecutive_skips == MAX_CONSECUTIVE_SKIPS + 1:
                        print(f"[ReelDetector] ⚠ Reached {MAX_CONSECUTIVE_SKIPS} consecutive skips of already-processed reels.")
                        print(f"[ReelDetector] Pausing auto-advance. Waiting for you to scroll to a fresh Reel...")
                    await asyncio.sleep(1.5)
                continue

            # Fresh / unprocessed reel — reset skip counter
            consecutive_skips = 0

            if detected_id != last_seen_id:
                # Reel changed or user scrolled!
                last_seen_id = detected_id
                self.current_reel_id = detected_id
                settle_start_time = time.time()
                print(f"[ReelDetector] Detected Reel change: [{detected_id}]. Starting {cooldown:.0f}s cooldown timer...")
            else:
                # Same reel is still in view
                elapsed = time.time() - settle_start_time
                remaining = max(0.0, cooldown - elapsed)

                if remaining > 0:
                    if int(remaining) % 3 == 0 and remaining > 1:
                        print(f"[ReelDetector] Settle progress: {elapsed:.1f}s / {cooldown:.0f}s (Reel: {detected_id})")
                else:
                    # Settled for full cooldown period!
                    print(f"[ReelDetector] Reel [{detected_id}] has settled ({cooldown:.0f}s reached)! Confirming fully loaded...")
                    await asyncio.sleep(1.0)  # Brief buffer for DOM stability

                    # Fresh info grab — no screenshot here (screenshots happen on reel settle only)
                    final_info = await self.get_active_reel_info()
                    self.current_reel_id = final_info["reel_id"]
                    return ReelContext(
                        reel_id=final_info["reel_id"],
                        url=final_info["url"],
                        author=final_info["author"],
                        caption=final_info["caption"],
                        timestamp=datetime.now(),
                        screenshot_path=None  # No per-reel screenshots to save disk
                    )

            await asyncio.sleep(0.8)

    async def navigate_to_next_reel(self) -> bool:
        """
        Navigates to the next Reel when all comments on the current Reel are finished.
        Uses the proven Instagram shortcut:
        1. Focuses the active Reel video area.
        2. Emits 'ArrowDown' -> 'Enter' shortcut.
        3. Clicks the circular Down Arrow button (shown in UI) if needed.
        4. Verifies active Reel changes to a new ID before completing.
        """
        previous_id = self.current_reel_id
        if not previous_id or previous_id.startswith("unknown"):
            info = await self.get_active_reel_info()
            previous_id = info["reel_id"]

        print(f"\n[ReelDetector] ⚡ All comments finished. Navigating to NEXT Reel from [{previous_id}] via [Down Arrow -> Enter] shortcut...")

        # Step 1: Ensure active focus is on the Reel container
        try:
            viewport = self.page.viewport_size or {"width": 1280, "height": 800}
            center_x = viewport["width"] / 2
            center_y = viewport["height"] / 2

            video_el = await self.page.query_selector("video")
            if video_el:
                box = await video_el.bounding_box()
                if box and box["width"] > 50 and box["height"] > 50:
                    center_x = box["x"] + box["width"] / 2
                    center_y = box["y"] + box["height"] / 2

            await self.page.mouse.click(center_x, center_y)
            await asyncio.sleep(0.15)
        except Exception:
            try:
                await self.page.focus("body")
            except Exception:
                pass

        # Step 2: Primary proven shortcut: ArrowDown followed by Enter
        try:
            await self.page.keyboard.press("ArrowDown")
            await asyncio.sleep(0.2)
            await self.page.keyboard.press("Enter")
            print("[ReelDetector] Triggered shortcut: [ArrowDown -> Enter] to advance Reel.")
        except Exception as e:
            print(f"[ReelDetector] Shortcut execution notice: {e}")

        # Step 3: Check if the Reel changed to a new ID
        for _ in range(6):
            await asyncio.sleep(0.5)
            check = await self.get_active_reel_info()
            new_id = check["reel_id"]
            if new_id and new_id != previous_id and not new_id.startswith("unknown"):
                print(f"[ReelDetector] ✓ Successfully advanced to next Reel: [{new_id}]")
                self.current_reel_id = new_id
                return True

        # Step 4: Circular Down Arrow button click fallback (targets the round white down-arrow button)
        print("[ReelDetector] Shortcut verification pending. Dispatching circular Down Arrow button click fallback...")
        js_click_down_arrow = """
        () => {
            const buttons = Array.from(document.querySelectorAll('div[role="button"], button'));
            for (const b of buttons) {
                const rect = b.getBoundingClientRect();
                // Check if button is on the right side of the video player
                if (rect.width > 24 && rect.width < 75 && rect.height > 24 && rect.height < 75 && rect.right > window.innerWidth / 3) {
                    const svg = b.querySelector('svg');
                    if (svg) {
                        const aria = (svg.getAttribute('aria-label') || b.getAttribute('aria-label') || '').toLowerCase();
                        if (aria.includes('down') || aria.includes('next') || aria.includes('below')) {
                            b.click();
                            return true;
                        }
                    }
                }
            }
            return false;
        }
        """
        try:
            clicked = await self.page.evaluate(js_click_down_arrow)
            if not clicked:
                down_selectors = [
                    "div[role='button']:has(svg[aria-label*='Down'])",
                    "div[role='button']:has(svg[aria-label*='down'])",
                    "div[role='button']:has(svg[aria-label*='Next'])",
                    "button:has(svg[aria-label*='Down'])",
                    "button:has(svg[aria-label*='Next'])"
                ]
                for sel in down_selectors:
                    try:
                        btn = await self.page.wait_for_selector(sel, timeout=400, state="visible")
                        if btn:
                            await btn.click()
                            break
                    except Exception:
                        continue
        except Exception:
            pass

        # Step 5: PageDown as final fallback
        try:
            await self.page.keyboard.press("PageDown")
        except Exception:
            pass

        # Final verification wait
        for _ in range(5):
            await asyncio.sleep(0.4)
            check = await self.get_active_reel_info()
            new_id = check["reel_id"]
            if new_id and new_id != previous_id and not new_id.startswith("unknown"):
                print(f"[ReelDetector] ✓ Successfully locked to next Reel: [{new_id}]")
                self.current_reel_id = new_id
                return True

        print(f"[ReelDetector] Advance signal completed (current: [{self.current_reel_id}]).")
        return True

