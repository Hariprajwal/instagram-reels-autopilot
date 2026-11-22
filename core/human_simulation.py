"""
human_simulation.py — Human-Like Interaction Physics Engine

Implements all behavioral heuristics to defeat Meta/Instagram bot detection:
  1. Gaussian jitter delays (not fixed timers)
  2. Bézier curve mouse movement (not linear teleportation)
  3. Variable keystroke cadence with Gaussian distribution
  4. Passive content consumption simulation (inbound ratio balance)
  5. Session fatigue model (gradual slowdown over time)
  6. Natural micro-pause injection between actions
"""

import math
import random
import asyncio
from typing import Optional
from playwright.async_api import Page


# ══════════════════════════════════════════════════════════════════════════════
# 1. GAUSSIAN DELAY ENGINE
#    Fixed timers → instant flagged. All delays must have natural variance.
# ══════════════════════════════════════════════════════════════════════════════

def gauss_delay(mean: float, sigma_ratio: float = 0.25, minimum: float = 0.3) -> float:
    """
    Returns a Gaussian-distributed delay (seconds) centered on `mean`.
    sigma_ratio controls spread: 0.25 = ±25% variance (human-like).
    minimum enforces a floor to prevent near-zero delays.
    """
    sigma = mean * sigma_ratio
    delay = random.gauss(mean, sigma)
    return max(minimum, delay)


async def human_sleep(mean: float, sigma_ratio: float = 0.25, minimum: float = 0.3):
    """Sleeps for a Gaussian-distributed duration instead of a fixed delay."""
    await asyncio.sleep(gauss_delay(mean, sigma_ratio, minimum))


async def micro_pause():
    """
    Simulates the micro-hesitations humans naturally have between actions
    (200ms–800ms). Inserted between clicks, scrolls, and other interactions.
    """
    await asyncio.sleep(gauss_delay(0.4, 0.5, 0.15))


# ══════════════════════════════════════════════════════════════════════════════
# 2. BÉZIER CURVE MOUSE MOVEMENT
#    Linear mouse teleportation → flagged instantly. Curves with acceleration
#    and deceleration match real human motor control.
# ══════════════════════════════════════════════════════════════════════════════

def _bezier_point(t: float, points: list) -> tuple:
    """Evaluates a cubic Bézier curve at parameter t ∈ [0, 1]."""
    p0, p1, p2, p3 = points
    mt = 1 - t
    x = (mt**3)*p0[0] + 3*(mt**2)*t*p1[0] + 3*mt*(t**2)*p2[0] + (t**3)*p3[0]
    y = (mt**3)*p0[1] + 3*(mt**2)*t*p1[1] + 3*mt*(t**2)*p2[1] + (t**3)*p3[1]
    return x, y


async def move_mouse_human(
    page: Page,
    target_x: float,
    target_y: float,
    start_x: Optional[float] = None,
    start_y: Optional[float] = None,
    steps: int = 18,
    overshoot: bool = True
):
    """
    Moves the mouse from (start_x, start_y) to (target_x, target_y) along a
    natural Bézier curve with:
      - Random control points creating organic curved path
      - Gaussian step timing (acceleration at start, deceleration at end)
      - Optional target overshoot + correction (humans miss targets slightly)

    Falls back to direct mouse.move() if anything fails.
    """
    try:
        # Use current position as start if not provided
        if start_x is None:
            start_x = target_x + random.uniform(-200, 200)
        if start_y is None:
            start_y = target_y + random.uniform(-150, 150)

        # Generate two random Bézier control points creating natural curve
        cp1_x = start_x + (target_x - start_x) * random.uniform(0.2, 0.5) + random.uniform(-80, 80)
        cp1_y = start_y + (target_y - start_y) * random.uniform(0.1, 0.4) + random.uniform(-60, 60)
        cp2_x = start_x + (target_x - start_x) * random.uniform(0.5, 0.8) + random.uniform(-80, 80)
        cp2_y = start_y + (target_y - start_y) * random.uniform(0.6, 0.9) + random.uniform(-60, 60)

        control_points = [(start_x, start_y), (cp1_x, cp1_y), (cp2_x, cp2_y), (target_x, target_y)]

        for i in range(steps):
            t = (i + 1) / steps
            # Apply ease-in-out: slower at start and end (human motor control)
            t_eased = t * t * (3 - 2 * t)
            px, py = _bezier_point(t_eased, control_points)

            # Add micro-jitter (human hand tremor simulation)
            px += random.gauss(0, 0.8)
            py += random.gauss(0, 0.8)

            # Variable step timing: slow at start, fast in middle, slow at end
            if i < steps * 0.2 or i > steps * 0.8:
                step_delay = gauss_delay(0.025, 0.3, 0.008)  # slow
            else:
                step_delay = gauss_delay(0.010, 0.4, 0.003)  # fast

            await page.mouse.move(px, py)
            await asyncio.sleep(step_delay)

        # Optional overshoot: humans often move slightly past the target and correct
        if overshoot and random.random() < 0.35:
            overshoot_x = target_x + random.uniform(-6, 6)
            overshoot_y = target_y + random.uniform(-6, 6)
            await page.mouse.move(overshoot_x, overshoot_y)
            await asyncio.sleep(gauss_delay(0.08, 0.4, 0.03))
            await page.mouse.move(target_x, target_y)
            await asyncio.sleep(gauss_delay(0.05, 0.3, 0.02))

    except Exception:
        # Fallback: simple move if Bézier fails
        try:
            await page.mouse.move(target_x, target_y)
        except Exception:
            pass


async def human_click(page: Page, x: float, y: float, double: bool = False):
    """
    Performs a human-like click: Bézier movement → settle pause → click.
    Optionally double-clicks with natural timing between presses.
    """
    await move_mouse_human(page, x, y)
    await asyncio.sleep(gauss_delay(0.08, 0.5, 0.03))  # Hover before click
    if double:
        await page.mouse.click(x, y)
        await asyncio.sleep(gauss_delay(0.12, 0.4, 0.06))
        await page.mouse.click(x, y)
    else:
        await page.mouse.click(x, y)


async def human_click_element(page: Page, element):
    """
    Clicks a Playwright ElementHandle using human-like cursor movement.
    Gets the element's bounding box center and uses human_click.
    """
    try:
        box = await element.bounding_box()
        if box:
            cx = box["x"] + box["width"] / 2 + random.uniform(-3, 3)
            cy = box["y"] + box["height"] / 2 + random.uniform(-3, 3)
            await human_click(page, cx, cy)
            return True
    except Exception:
        pass

    # Fallback to native click
    try:
        await element.scroll_into_view_if_needed()
        await asyncio.sleep(gauss_delay(0.2, 0.3, 0.1))
        await element.click()
        return True
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
# 3. GAUSSIAN KEYSTROKE DYNAMICS
#    Uniform typing speed → instantly flagged. Human typing follows a
#    Gaussian distribution with hesitation on special characters.
# ══════════════════════════════════════════════════════════════════════════════

async def human_type(page: Page, element, text: str):
    """
    Types text into an element with:
      - Gaussian per-keystroke delay (30ms–180ms, mean ~65ms)
      - Extra hesitation before capital letters, numbers, symbols, spaces
      - Random chance of micro-pauses between words (thinking pause)
      - Clears field first with realistic selection behavior
    """
    try:
        await element.click()
        await asyncio.sleep(gauss_delay(0.15, 0.4, 0.05))

        # Clear existing content naturally (triple-click selects all, then type overwrites)
        await element.fill("")
        await asyncio.sleep(gauss_delay(0.1, 0.3, 0.05))

        for i, char in enumerate(text):
            # Base typing speed: Gaussian around 65ms
            delay_ms = random.gauss(65, 25)
            delay_ms = max(25, min(delay_ms, 220))  # Clamp: 25ms–220ms

            # Special character hesitations (humans slow down for capitals, symbols)
            if char.isupper():
                delay_ms += random.gauss(30, 15)  # Shift key takes time
            elif char in ".,!?;:\"'()[]{}@#$%&*-_+=<>/\\":
                delay_ms += random.gauss(25, 12)  # Symbol key pause
            elif char == " ":
                delay_ms += random.gauss(10, 8)   # Spacebar is fast but varies

            # Random thinking pause between words (humans pause to think mid-sentence)
            if char == " " and random.random() < 0.12:
                delay_ms += random.gauss(300, 100)

            await page.keyboard.type(char)
            await asyncio.sleep(delay_ms / 1000)

    except Exception as e:
        # Fallback: use page.type with moderate delay
        try:
            await element.fill(text)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# 4. PASSIVE CONTENT CONSUMPTION (Inbound/Outbound Ratio Balance)
#    Real humans spend 85-90% of time consuming, only 10-15% on actions.
#    Simulating video watching time before comment actions balances the ratio.
# ══════════════════════════════════════════════════════════════════════════════

async def simulate_watching_reel(page: Page, duration: float = None):
    """
    Simulates a human watching a Reel before taking any action:
      - Keeps focus on the video element
      - Optionally moves mouse slightly (attention tracking)
      - Waits for a Gaussian duration resembling actual video watch time
    
    Call this BEFORE opening comments on each Reel.
    Default duration: 4–8 seconds (simulates partial Reel watch).
    """
    if duration is None:
        # Humans watch 4-15 seconds of a Reel before interacting
        duration = gauss_delay(7.0, 0.4, 3.5)

    print(f"[HumanSim] Watching Reel for {duration:.1f}s (simulating natural content consumption)...")

    try:
        # Find the video and move mouse nearby (attention gaze simulation)
        video = await page.query_selector("video")
        if video:
            box = await video.bounding_box()
            if box:
                # Move to a random position within the video frame (gaze wandering)
                gaze_x = box["x"] + random.uniform(box["width"] * 0.2, box["width"] * 0.8)
                gaze_y = box["y"] + random.uniform(box["height"] * 0.3, box["height"] * 0.7)
                await move_mouse_human(page, gaze_x, gaze_y)
    except Exception:
        pass

    # Wait and add occasional tiny mouse micro-movements (eye tracking fidget)
    elapsed = 0
    while elapsed < duration:
        chunk = min(gauss_delay(1.5, 0.4, 0.8), duration - elapsed)
        await asyncio.sleep(chunk)
        elapsed += chunk

        # Occasional micro-movement (humans shift attention slightly)
        if random.random() < 0.25 and elapsed < duration - 1:
            try:
                viewport = page.viewport_size or {"width": 1280, "height": 800}
                nudge_x = viewport["width"] / 2 + random.uniform(-50, 50)
                nudge_y = viewport["height"] / 2 + random.uniform(-30, 30)
                await page.mouse.move(nudge_x, nudge_y)
            except Exception:
                pass


async def simulate_reading_comments_pause():
    """
    Simulates a human briefly reading a few comments before the agent begins.
    Wait 1.5–4 seconds (Gaussian) after the drawer opens.
    """
    duration = gauss_delay(2.5, 0.4, 1.2)
    print(f"[HumanSim] Reading comments for {duration:.1f}s before processing...")
    await asyncio.sleep(duration)


async def simulate_profile_glance():
    """
    Simulates glancing at a profile before deciding to message.
    Moves mouse across the profile area and waits 2–5 seconds.
    """
    wait_time = gauss_delay(3.0, 0.4, 1.5)
    print(f"[HumanSim] Glancing at profile for {wait_time:.1f}s...")
    await asyncio.sleep(wait_time)


# ══════════════════════════════════════════════════════════════════════════════
# 5. SESSION FATIGUE MODEL
#    Humans slow down over time. Maintaining robot-speed for hours = instant flag.
# ══════════════════════════════════════════════════════════════════════════════

class SessionFatigueModel:
    """
    Models natural human session fatigue:
    - Early session (0–15 min): Fast, energetic pace
    - Mid session (15–45 min): Normal pace with occasional pauses
    - Late session (45+ min): Slower pace, longer think-pauses, random micro-breaks
    """

    def __init__(self):
        self._start_time = None
        self._actions_taken = 0

    def session_start(self):
        import time
        self._start_time = time.time()
        self._actions_taken = 0

    def _session_age_minutes(self) -> float:
        import time
        if self._start_time is None:
            return 0
        return (time.time() - self._start_time) / 60

    def record_action(self):
        self._actions_taken += 1

    def get_fatigue_multiplier(self) -> float:
        """
        Returns a delay multiplier based on session age and action count.
        1.0 = no fatigue (fresh), 1.8 = tired (long session).
        """
        age = self._session_age_minutes()
        if age < 10:
            multiplier = gauss_delay(1.0, 0.1, 0.8)
        elif age < 30:
            multiplier = gauss_delay(1.2, 0.15, 1.0)
        elif age < 60:
            multiplier = gauss_delay(1.5, 0.2, 1.1)
        else:
            multiplier = gauss_delay(1.8, 0.2, 1.3)
        return multiplier

    async def apply_fatigue_delay(self, base_delay: float = 1.0):
        """Applies a fatigue-scaled Gaussian delay."""
        delay = base_delay * self.get_fatigue_multiplier()
        await asyncio.sleep(gauss_delay(delay, 0.3, 0.3))
        self.record_action()

    async def maybe_take_micro_break(self):
        """
        With 8% probability per action, simulates a human micro-break:
        3–12 seconds of inactivity (looking away, checking phone, etc.)
        """
        if random.random() < 0.08:
            break_duration = gauss_delay(6.0, 0.5, 2.5)
            print(f"[HumanSim] Taking {break_duration:.1f}s micro-break (natural fatigue simulation)...")
            await asyncio.sleep(break_duration)


# ══════════════════════════════════════════════════════════════════════════════
# 6. NATURAL SCROLL SIMULATION
#    Single exact scroll amount → flagged. Humans scroll in irregular chunks.
# ══════════════════════════════════════════════════════════════════════════════

async def human_scroll_down(page: Page, viewport_fraction: float = 0.9):
    """
    Scrolls down by approximately one screen height using natural Gaussian
    variation — not exact pixel amounts every time.
    """
    try:
        viewport = page.viewport_size or {"width": 1280, "height": 800}
        base_scroll = viewport["height"] * viewport_fraction

        # Gaussian variation on scroll amount (±15%)
        scroll_amount = int(gauss_delay(base_scroll, 0.15, base_scroll * 0.6))

        # Slight nudge at the end (humans often over-scroll slightly)
        nudge = int(random.uniform(0, viewport["height"] * 0.08))

        await page.mouse.wheel(0, scroll_amount)
        await asyncio.sleep(gauss_delay(0.4, 0.4, 0.2))
        if nudge > 10 and random.random() < 0.5:
            await page.mouse.wheel(0, nudge)
            await asyncio.sleep(gauss_delay(0.2, 0.3, 0.1))

    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# Global singleton fatigue model
# ══════════════════════════════════════════════════════════════════════════════
fatigue_model = SessionFatigueModel()
