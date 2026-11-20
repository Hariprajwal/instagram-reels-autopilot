import re
import asyncio
from typing import List, Optional, Tuple
from playwright.async_api import Page, ElementHandle

from config.settings import settings
from models.schemas import CommentData

class CommentReader:
    def __init__(self, page: Page):
        self.page = page
        self.selectors = settings.load_selectors().get("comments", {})
        self.reel_selectors = settings.load_selectors().get("reel", {})

    async def is_comments_open(self) -> bool:
        """Checks if comments drawer/modal is currently open."""
        drawer_selectors = self.selectors.get("drawer", [
            "div[role='dialog']",
            "div[aria-label='Comments']",
            "section:has(h2:has-text('Comments'))"
        ])
        for s in drawer_selectors:
            try:
                if await self.page.is_visible(s, timeout=600):
                    return True
            except Exception:
                continue
        return False

    async def open_comments(self) -> bool:
        """Finds and clicks the comment button on the active Reel to open comments."""
        if await self.is_comments_open():
            print("[CommentReader] Comments section is already open.")
            return True

        print("[CommentReader] Opening comments section...")
        comment_buttons = self.reel_selectors.get("comment_button", [
            "svg[aria-label='Comment']",
            "svg[aria-label='Comments']",
            "div[role='button']:has(svg[aria-label='Comment'])"
        ])

        for selector in comment_buttons:
            try:
                btn = await self.page.wait_for_selector(selector, timeout=2500, state="visible")
                if btn:
                    await btn.scroll_into_view_if_needed()
                    await asyncio.sleep(0.3)
                    await btn.click()
                    await asyncio.sleep(1.5)
                    if await self.is_comments_open():
                        print("[CommentReader] Comments drawer opened successfully.")
                        return True
            except Exception:
                continue

        # Fallback click via JS
        js_click = """
        () => {
            const svgs = Array.from(document.querySelectorAll('svg[aria-label="Comment"], svg[aria-label="Comments"]'));
            for (const svg of svgs) {
                const btn = svg.closest('[role="button"]') || svg.parentElement;
                if (btn) {
                    btn.click();
                    return true;
                }
            }
            return false;
        }
        """
        try:
            clicked = await self.page.evaluate(js_click)
            if clicked:
                await asyncio.sleep(1.5)
                return await self.is_comments_open()
        except Exception:
            pass

        return False

    async def close_comments(self) -> bool:
        """Closes the comments section to restore the original Reel view."""
        print("[CommentReader] Closing comments section...")
        if not await self.is_comments_open():
            return True

        close_selectors = self.selectors.get("close_button", [
            "svg[aria-label='Close']",
            "div[role='button']:has(svg[aria-label='Close'])"
        ])

        for s in close_selectors:
            try:
                btn = await self.page.wait_for_selector(s, timeout=1500, state="visible")
                if btn:
                    await btn.click()
                    await asyncio.sleep(1.0)
                    return True
            except Exception:
                continue

        # Try Escape key
        try:
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(0.8)
            if not await self.is_comments_open():
                return True
        except Exception:
            pass

        return False

    async def read_accessible_comments(self, reel_id: str) -> List[CommentData]:
        """
        Parses all currently rendered individual comments from the comments container.
        Returns list of structured CommentData.
        """
        js_extract = """
        () => {
            const commentsList = [];
            // Locate comments drawer or modal
            const dialog = document.querySelector('div[role="dialog"]') || document.querySelector('div[aria-label="Comments"]') || document.body;

            // Find all anchor links that lead to user profiles inside the comments dialog
            const links = Array.from(dialog.querySelectorAll('a[role="link"], h3 a, span a'));
            const seenUsers = new Set();

            for (const link of links) {
                const href = link.getAttribute('href') || '';
                const match = href.match(/^\\/([A-Za-z0-9_.]+)\\/?$/);
                if (!match) continue;

                const username = match[1].toLowerCase();
                // Filter out non-user links
                if (['explore', 'reel', 'reels', 'stories', 'direct', 'p'].includes(username)) continue;
                if (seenUsers.has(username)) continue;

                // Find comment row container (go up 3 to 6 levels to find row)
                let row = link.closest('li') || link.closest('div[role="button"]') || link.parentElement?.parentElement?.parentElement;
                if (!row) continue;

                // Extract comment text from row
                const textNodes = Array.from(row.querySelectorAll('span[dir="auto"], div[dir="auto"]'));
                let commentText = '';

                for (const node of textNodes) {
                    const text = node.innerText.trim();
                    // Skip usernames, timestamps, and action labels
                    if (text === username || text === '@' + username) continue;
                    if (['Like', 'Reply', 'See translation', 'View replies', 'Hide replies'].includes(text)) continue;
                    if (/^\\d+\\s*(s|m|h|d|w)$/i.test(text)) continue;
                    if (text.length > commentText.length) {
                        commentText = text;
                    }
                }

                if (commentText.length > 0) {
                    seenUsers.add(username);
                    commentsList.push({
                        username: username,
                        text: commentText
                    });
                }
            }

            return commentsList;
        }
        """
        try:
            raw_comments = await self.page.evaluate(js_extract)
            results = []
            for idx, c in enumerate(raw_comments):
                results.append(CommentData(
                    username=c["username"],
                    text=c["text"],
                    position_index=idx,
                    reel_id=reel_id
                ))
            return results
        except Exception as e:
            print(f"[CommentReader] Error extracting comments: {e}")
            return []

    async def click_commenter_profile(self, username: str) -> bool:
        """
        Finds and clicks the specific commenter's username link inside comments.
        Tries native Playwright locator click first to trigger client-side SPA routing,
        then JavaScript event click, and finally direct URL navigation as fail-safe.
        """
        clean_user = username.strip().lstrip("@").lower()
        print(f"[CommentReader] Opening profile for @{clean_user}...")

        # 1. Native Playwright locator click (triggers natural React router navigation without full reload)
        link_selectors = [
            f"div[role='dialog'] a[href*='/{clean_user}']",
            f"a[role='link'][href*='/{clean_user}']",
            f"a[href='/{clean_user}/']",
            f"a[href='/{clean_user}']"
        ]
        for sel in link_selectors:
            try:
                link = self.page.locator(sel).first
                if await link.is_visible(timeout=400):
                    await link.scroll_into_view_if_needed()
                    await asyncio.sleep(0.15)
                    await link.click(timeout=1000)
                    for _ in range(6):
                        await asyncio.sleep(0.3)
                        if clean_user in self.page.url.lower():
                            return True
            except Exception:
                continue

        # 2. Search and click username element inside comments dialog via DOM
        js_click_user = f"""
        () => {{
            const targetUser = '{clean_user}'.toLowerCase();
            const dialog = document.querySelector('div[role="dialog"]') || document.querySelector('div[aria-label="Comments"]') || document.body;
            const elements = Array.from(dialog.querySelectorAll('a, h3, span'));
            for (const el of elements) {{
                const href = (el.getAttribute('href') || '').toLowerCase();
                const text = (el.innerText || '').trim().toLowerCase();
                if (href.includes('/' + targetUser + '/') || href.endsWith('/' + targetUser) || href === '/' + targetUser) {{
                    el.scrollIntoView({{ behavior: 'instant', block: 'center' }});
                    el.click();
                    return true;
                }}
                if (text === targetUser || text === '@' + targetUser) {{
                    const clickable = el.closest('a') || el;
                    clickable.scrollIntoView({{ behavior: 'instant', block: 'center' }});
                    clickable.click();
                    return true;
                }}
            }}
            return false;
        }}
        """
        try:
            clicked = await self.page.evaluate(js_click_user)
            if clicked:
                for _ in range(5):
                    await asyncio.sleep(0.3)
                    if clean_user in self.page.url.lower():
                        return True
        except Exception as e:
            print(f"[CommentReader] Error clicking user link: {e}")

        # 3. FAIL-SAFE: Direct profile navigation so investigation never stalls
        profile_url = f"https://www.instagram.com/{clean_user}/"
        print(f"[CommentReader] Navigating directly to profile: {profile_url}")
        try:
            await self.page.goto(profile_url, wait_until="domcontentloaded")
            await asyncio.sleep(1.2)
            return True
        except Exception as e:
            print(f"[CommentReader] Direct navigation error: {e}")
            return False

