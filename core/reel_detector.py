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

            // If reelId wasn't in URL, use video src or active element signature
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
            return await self.page.evaluate(js_script)
        except Exception as e:
            return {
                "url": self.page.url,
                "reel_id": "unknown_reel",
                "author": "unknown",
                "caption": ""
            }

    async def wait_for_user_to_settle_on_reel(self) -> ReelContext:
        """
        Continuously monitors user manual scrolling.
        Only returns when the user has settled on a Reel for 15 uninterrupted seconds.
        """
        cooldown = settings.reel_cooldown_seconds
        print(f"\n[ReelDetector] Waiting for user to scroll and settle on a Reel for {cooldown:.0f} seconds...")

        last_seen_id = None
        settle_start_time = None

        while True:
            info = await self.get_active_reel_info()
            detected_id = info["reel_id"]

            if detected_id != last_seen_id:
                # Reel changed or user scrolled!
                last_seen_id = detected_id
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
                    # Settled for full 15 seconds!
                    print(f"[ReelDetector] Reel [{detected_id}] has settled ({cooldown:.0f}s reached)! Confirming fully loaded...")
                    await asyncio.sleep(1.0)  # Brief buffer for DOM stability

                    # Capture fresh screenshot
                    screenshot_name = f"reel_{detected_id}_{int(time.time())}.png"
                    screenshot_path = REEL_SCREENSHOTS_DIR / screenshot_name
                    try:
                        await self.page.screenshot(path=str(screenshot_path))
                        print(f"[ReelDetector] Captured fresh Reel screenshot: {screenshot_path.name}")
                    except Exception as e:
                        print(f"[ReelDetector] Screenshot warning: {e}")
                        screenshot_path = None

                    # Fresh info grab
                    final_info = await self.get_active_reel_info()
                    return ReelContext(
                        reel_id=final_info["reel_id"],
                        url=final_info["url"],
                        author=final_info["author"],
                        caption=final_info["caption"],
                        timestamp=datetime.now(),
                        screenshot_path=str(screenshot_path) if screenshot_path else None
                    )

            await asyncio.sleep(0.8)

    async def navigate_to_next_reel(self) -> bool:
        """
        Navigates to the next Reel when all comments on the current Reel are finished.
        Uses the proven Instagram shortcut:
        1. Focuses the active Reel video area / body.
        2. Emits 'ArrowDown' keypress.
        3. Emits 'Enter' keypress to advance directly to the next Reel.
        4. Fallback: Clicks the circular Down Arrow button and emits PageDown.
        """
        print("\n[ReelDetector] ⚡ All comments finished. Navigating to NEXT Reel via [Down Arrow -> Enter] shortcut...")

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
            await asyncio.sleep(0.6)
        except Exception as e:
            print(f"[ReelDetector] Shortcut execution error: {e}")

        # Step 3: Button click & PageDown fallback (if needed)
        down_selectors = [
            "div[role='button']:has(svg[aria-label*='Down'])",
            "div[role='button']:has(svg[aria-label*='down'])",
            "div[role='button']:has(svg[aria-label*='Next'])",
            "div[role='button']:has(svg[aria-label*='next'])",
            "button:has(svg[aria-label*='Down'])",
            "button:has(svg[aria-label*='Next'])",
            "svg[aria-label*='Down']",
            "svg[aria-label*='Next']"
        ]

        for sel in down_selectors:
            try:
                btn = await self.page.wait_for_selector(sel, timeout=300, state="visible")
                if btn:
                    box = await btn.bounding_box()
                    if box and box["x"] > 350:
                        await self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                        await self.page.mouse.down()
                        await asyncio.sleep(0.08)
                        await self.page.mouse.up()
                        await btn.click()
                        print(f"[ReelDetector] Dispatched Down Arrow button click fallback ({sel}).")
                        break
            except Exception:
                continue

        # Step 4: Keyboard PageDown fallback
        try:
            await self.page.keyboard.press("PageDown")
        except Exception:
            pass

        await asyncio.sleep(1.2)
        return True

