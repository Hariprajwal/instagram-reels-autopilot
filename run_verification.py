import sys
import time
import asyncio

print("======================================================================", flush=True)
print("   INSTAGRAM REEL INVESTIGATION AGENT - VERIFICATION SUITE", flush=True)
print("======================================================================\n", flush=True)

from config.settings import settings
print(f"[1/5] Settings loaded: Cooldown={settings.reel_cooldown_seconds}s, GroqKey={'Set' if settings.groq_api_key else 'Not Set'}, OllamaEnabled={settings.ollama_enabled}", flush=True)

from storage.state_manager import StateManager
sm = StateManager()
print(f"[2/5] StateManager initialized: Cached Users={len(sm.processed_users)}, Cached Reels={len(sm.processed_reels)}", flush=True)

from storage.session_logger import SessionLogger
sl = SessionLogger()
print(f"[3/5] SessionLogger initialized: CSV at {sl.csv_file.name}", flush=True)

from core.decision_engine import DecisionEngine
engine = DecisionEngine(sl, sm)
print(f"[4/5] DecisionEngine initialized.", flush=True)

from models.schemas import (
    CommentData,
    ProfileData,
    ReelContext,
    MessageAvailability,
    DecisionClassification,
    DMPermission,
    CommentIntent
)

async def test_scenarios():
    print("\n[5/5] Running Scenario Tests:\n", flush=True)

    # Scenario A: Explicit DM Request + Message Button -> ELIGIBLE
    c1 = CommentData(
        username="growth_seeker",
        text="This workflow is insane! DM me the pricing and setup details please.",
        position_index=0,
        reel_id="reel_launch_01"
    )
    p1 = ProfileData(
        username="growth_seeker",
        is_private=False,
        message_button_found=True,
        message_availability=MessageAvailability.MESSAGE_BUTTON_VISIBLE,
        bio_text="Founder | Scaling ecom brands"
    )
    r1 = ReelContext(
        reel_id="reel_launch_01",
        url="https://www.instagram.com/reel/reel_launch_01/",
        caption="Launching our AI computer use automation engine"
    )

    t0 = time.time()
    res1 = await engine.evaluate_commenter(c1, p1, r1)
    dur1 = time.time() - t0
    print(f"  [Scenario A: Explicit DM Invitation]")
    print(f"    Comment: '{c1.text}'")
    print(f"    Decision: {res1.decision.value} (Expected: ELIGIBLE)")
    print(f"    DM Permission: {res1.dm_permission.value} (Expected: EXPLICIT_INVITATION)")
    print(f"    Suggested Question: '{res1.suggested_question}'")
    print(f"    Evaluated in: {dur1:.3f}s")
    assert res1.decision == DecisionClassification.ELIGIBLE, f"Expected ELIGIBLE, got {res1.decision}"
    assert res1.dm_permission == DMPermission.EXPLICIT_INVITATION
    assert res1.suggested_question is not None
    assert res1.suggested_question.count("?") <= 1, "One-Question Rule violated!"
    print("    >>> PASS ✓\n", flush=True)

    # Scenario B: Interested comment, but NO DM permission
    c2 = CommentData(
        username="tech_student",
        text="How much does this cost per month?",
        position_index=1,
        reel_id="reel_launch_01"
    )
    p2 = ProfileData(
        username="tech_student",
        is_private=False,
        message_button_found=True,
        message_availability=MessageAvailability.MESSAGE_BUTTON_VISIBLE
    )
    res2 = await engine.evaluate_commenter(c2, p2, r1)
    print(f"  [Scenario B: Interested but No Permission]")
    print(f"    Comment: '{c2.text}'")
    print(f"    Decision: {res2.decision.value} (Expected: INTERESTED_BUT_NO_PERMISSION)")
    print(f"    DM Permission: {res2.dm_permission.value} (Expected: NO_EXPLICIT_PERMISSION)")
    assert res2.decision == DecisionClassification.INTERESTED_BUT_NO_PERMISSION
    assert res2.suggested_question is None
    print("    >>> PASS ✓\n", flush=True)

    # Scenario C: Explicit Refusal
    c3 = CommentData(
        username="anti_spam",
        text="Please stop messaging and don't dm me",
        position_index=2,
        reel_id="reel_launch_01"
    )
    p3 = ProfileData(
        username="anti_spam",
        is_private=False,
        message_button_found=True,
        message_availability=MessageAvailability.MESSAGE_BUTTON_VISIBLE
    )
    res3 = await engine.evaluate_commenter(c3, p3, r1)
    print(f"  [Scenario C: Explicit Refusal]")
    print(f"    Comment: '{c3.text}'")
    print(f"    Decision: {res3.decision.value} (Expected: DO_NOT_CONTACT)")
    assert res3.decision == DecisionClassification.DO_NOT_CONTACT
    assert res3.suggested_question is None
    print("    >>> PASS ✓\n", flush=True)

    # Scenario D: Missing message button
    c4 = CommentData(
        username="locked_profile",
        text="DM me details",
        position_index=3,
        reel_id="reel_launch_01"
    )
    p4 = ProfileData(
        username="locked_profile",
        is_private=True,
        message_button_found=False,
        message_availability=MessageAvailability.MESSAGE_BUTTON_UNAVAILABLE
    )
    res4 = await engine.evaluate_commenter(c4, p4, r1)
    print(f"  [Scenario D: Message Button Unavailable]")
    print(f"    Decision: {res4.decision.value} (Expected: UNAVAILABLE)")
    assert res4.decision == DecisionClassification.UNAVAILABLE
    assert res4.suggested_question is None
    print("    >>> PASS ✓\n", flush=True)

    # Check stats
    print("  [Session Statistics Check]")
    print(f"    Eligible Conversations: {sl.stats.eligible_conversations}")
    print(f"    Interested w/o Permission: {sl.stats.interested_without_dm_permission}")
    print(f"    Do Not Contact: {sl.stats.do_not_contact_profiles}")
    print(f"    Unavailable: {sl.stats.unavailable_profiles}")
    print(f"    Questions Prepared: {sl.stats.questions_prepared}")
    assert sl.stats.eligible_conversations == 1
    assert sl.stats.questions_prepared == 1
    print("    >>> ALL ASSERTIONS PASSED! ✓\n", flush=True)

asyncio.run(test_scenarios())
print("======================================================================", flush=True)
print("   ALL TESTS PASSED SUCCESSFULLY! SYSTEM READY FOR DEPLOYMENT.", flush=True)
print("======================================================================", flush=True)

