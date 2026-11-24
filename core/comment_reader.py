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

    async def get_total_comment_count(self) -> int:
        """
        Reads the displayed comment count from the reel sidebar (e.g. '90').
        Returns 0 if not found. This is the UI counter — includes hidden/nested comments.
        """
        js_count = """
        () => {
            // The comment count sits as a sibling/child of the comment SVG button in the sidebar
            // Instagram renders it as a plain text span near svg[aria-label='Comment'] or svg[aria-label='Comments']
            const svgs = Array.from(document.querySelectorAll(
                'svg[aria-label="Comment"], svg[aria-label="Comments"]'
            ));
            for (const svg of svgs) {
                // Walk up to the button wrapper, then look for a sibling/child span with a number
                const wrapper = svg.closest('[role="button"]') || svg.parentElement;
                if (!wrapper) continue;
                // The count is usually a span directly after the SVG wrapper
                const parent = wrapper.parentElement || wrapper;
                const spans = Array.from(parent.querySelectorAll('span'));
                for (const span of spans) {
                    const text = (span.innerText || span.textContent || '').trim().replace(/,/g, '');
                    const num = parseInt(text, 10);
                    if (!isNaN(num) && num > 0) return num;
                }
            }
            // Fallback: search for any element whose text looks like a comment count near a comment icon
            const allSpans = Array.from(document.querySelectorAll('span, div'));
            for (const el of allSpans) {
                const text = (el.innerText || '').trim();
                // Skip huge numbers (like/view counts can be very large)
                if (/^\d{1,5}$/.test(text.replace(/,/g, ''))) {
                    const num = parseInt(text.replace(/,/g, ''), 10);
                    if (num > 0 && num < 50000) {
                        // Check if it's near a comment button
                        const nearby = el.closest('div') || el;
                        if (nearby.innerHTML && nearby.innerHTML.includes('Comment')) return num;
                    }
                }
            }
            return 0;
        }
        """
        try:
            count = await self.page.evaluate(js_count)
            return int(count) if count else 0
        except Exception as e:
            print(f"[CommentReader] Could not read total comment count: {e}")
            return 0

    async def _is_spinner_visible(self) -> bool:
        """Checks if Instagram's comment loading spinner is visible at the bottom of the drawer."""
        spinner_selectors = [
            "div[role='dialog'] svg[aria-label='Loading']",
            "div[role='dialog'] [role='progressbar']",
            "div[aria-label='Comments'] svg[aria-label='Loading']",
            "div[role='dialog'] circle[class*='spin']",
            "div[role='dialog'] div[class*='Loading']",
            # Generic: any visible SVG with spinning animation inside the dialog
            "div[role='dialog'] svg[class*='anim']",
        ]
        for sel in spinner_selectors:
            try:
                if await self.page.is_visible(sel, timeout=300):
                    return True
            except Exception:
                continue
        # JS fallback: look for any SVG inside the dialog that has aria-label containing 'load' or 'Loading'
        try:
            found = await self.page.evaluate("""
            () => {
                const dialog = document.querySelector('div[role="dialog"]') || document.querySelector('div[aria-label="Comments"]');
                if (!dialog) return false;
                const svgs = Array.from(dialog.querySelectorAll('svg'));
                return svgs.some(svg => {
                    const label = (svg.getAttribute('aria-label') || '').toLowerCase();
                    return label.includes('load') || label.includes('loading');
                });
            }
            """)
            if found:
                return True
        except Exception:
            pass
        return False

    async def _wait_for_spinner_to_clear(self, max_wait: float = 8.0) -> None:
        """Waits until the loading spinner disappears (up to max_wait seconds)."""
        waited = 0.0
        interval = 0.4
        while waited < max_wait:
            if not await self._is_spinner_visible():
                return
            await asyncio.sleep(interval)
            waited += interval
        print(f"[CommentReader] Spinner still visible after {max_wait}s — continuing anyway.")

    async def _scroll_comment_drawer(self, pixels: int = 600) -> None:
        """Scrolls the comment drawer panel downward by `pixels` to trigger lazy-loading."""
        try:
            scrolled = await self.page.evaluate(f"""
            () => {{
                const dialog = document.querySelector('div[role="dialog"]') || document.querySelector('div[aria-label="Comments"]');
                if (!dialog) return false;
                // Find the scrollable child: the one with overflow-y scroll/auto
                const containers = Array.from(dialog.querySelectorAll('*'));
                for (const el of containers) {{
                    const style = window.getComputedStyle(el);
                    if ((style.overflowY === 'scroll' || style.overflowY === 'auto') && el.scrollHeight > el.clientHeight) {{
                        el.scrollTop += {pixels};
                        return true;
                    }}
                }}
                // Fallback: scroll the dialog itself
                dialog.scrollTop += {pixels};
                return true;
            }}
            """)
            return scrolled
        except Exception as e:
            print(f"[CommentReader] Scroll error: {e}")

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
                    // Skip elements inside like/reply action buttons
                    const parentBtn = node.closest('button, [role="button"]');
                    if (parentBtn && parentBtn !== row) {
                        const btnText = (parentBtn.innerText || '').toLowerCase();
                        if (btnText.includes('like') || btnText.includes('reply') || btnText.includes('translation')) {
                            continue;
                        }
                    }

                    let text = node.innerText.trim();
                    if (!text) continue;

                    // Skip usernames
                    if (text.toLowerCase() === username || text.toLowerCase() === '@' + username) continue;

                    // Clean any concatenated action metadata if an outer container was picked up
                    text = text.replace(/[\d,.]+[kmb]?\s*likes?\s*(reply)?.*$/i, '').trim();
                    text = text.replace(/\s*reply\s*$/i, '').trim();
                    text = text.replace(/\s*see translation\s*$/i, '').trim();
                    text = text.replace(/\s*see original\s*$/i, '').trim();

                    // Strictly filter out like counters (e.g. "4 likes", "24,845 likes", "1 like", "likes")
                    if (/^[\d,.]+[kmb]?\s*likes?$/i.test(text) || /^likes?$/i.test(text)) continue;

                    // Strictly filter out reply counts and system buttons
                    if (/^(view\s+)?(\d+\s+)?(more\s+)?repl(?:y|ies)/i.test(text)) continue;
                    if (/^hide\s+replies/i.test(text)) continue;
                    if (['like', 'likes', 'reply', 'replies', 'see translation', 'see original', 'view replies', 'hide replies', 'pinned', 'edited', 'author', 'creator'].includes(text.toLowerCase())) continue;

                    // Strictly filter out timestamps (e.g. "1d", "4h", "2w", "30s", "10m")
                    if (/^\d+\s*(s|m|h|d|w|y|sec|min|hr|day|wk|yr)s?$/i.test(text) || /^\d+[smhdwy]$/i.test(text)) continue;

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
                raw_text = (c.get("text") or "").strip()
                # Secondary Python-level sanitization: discard pure like counters
                if re.match(r"^[\d,.]+[kmb]?\s*likes?$", raw_text, re.IGNORECASE) or raw_text.lower() in ["like", "likes", "reply"]:
                    print(f"[CommentReader] Ignored like counter string erroneously captured as comment: '{raw_text}' for @{c.get('username')}")
                    continue

                # Strip any trailing like counter artifacts
                clean_text = re.sub(r"[\d,.]+[kmb]?\s*likes?\s*(reply)?.*$", "", raw_text, flags=re.IGNORECASE).strip()
                if not clean_text:
                    clean_text = raw_text

                results.append(CommentData(
                    username=c["username"],
                    text=clean_text,
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

