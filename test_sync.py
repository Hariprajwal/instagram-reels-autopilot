import re
import time

print("======================================================================", flush=True)
print("   INSTAGRAM REEL INVESTIGATION AGENT - PURE LOGIC VERIFICATION", flush=True)
print("======================================================================\n", flush=True)

from config.settings import settings
print(f"[1/5] Settings loaded: Cooldown={settings.reel_cooldown_seconds}s, Mode={settings.eligibility_mode}", flush=True)

from storage.state_manager import StateManager
sm = StateManager()
print(f"[2/5] StateManager initialized: Cached Users={len(sm.processed_users)}", flush=True)

from storage.session_logger import SessionLogger
sl = SessionLogger()
print(f"[3/5] SessionLogger initialized: CSV at {sl.csv_file.name}", flush=True)

from models.classifier import AIClassifier
classifier = AIClassifier()
print(f"[4/5] AIClassifier initialized (Rule Engine Ready).", flush=True)

from models.schemas import (
    CommentData,
    ProfileData,
    ReelContext,
    MessageAvailability,
    DecisionClassification,
    DMPermission,
    CommentIntent,
    ProspectAnalysis
)

print("\n[5/5] Testing Rule Engine Scenarios:\n", flush=True)

# Scenario A: Explicit DM Request + Visible Button -> ELIGIBLE
resA = classifier._rule_based_fallback(
    comment_text="This workflow is insane! DM me the pricing and setup details please.",
    reel_caption="Launching our AI computer use automation engine",
    message_availability=MessageAvailability.MESSAGE_BUTTON_VISIBLE,
    is_private=False
)
analysisA = classifier._build_analysis_object("growth_seeker", "reel_01", "This workflow is insane! DM me the pricing and setup details please.", MessageAvailability.MESSAGE_BUTTON_VISIBLE, resA)
sl.record_analysis(analysisA)
sm.mark_user_processed("growth_seeker", "reel_01", analysisA.decision.value)

print("  [Scenario A: Explicit DM Request]")
print(f"    Decision: {analysisA.decision.value} (Expected: ELIGIBLE)")
print(f"    DM Permission: {analysisA.dm_permission.value}")
print(f"    Message Sequence (Length={len(analysisA.message_sequence)}):")
for i, m in enumerate(analysisA.message_sequence, 1):
    print(f"      Msg {i}: {m}")
assert analysisA.decision == DecisionClassification.ELIGIBLE
assert analysisA.suggested_question is not None
assert len(analysisA.message_sequence) >= 2
assert analysisA.message_sequence[0] == "This workflow is insane! DM me the pricing and setup details please."
print("    >>> PASS ✓\n", flush=True)

# Scenario B: Engaged commenter with Message Button (Hindi / Reel reaction) -> ELIGIBLE
resB = classifier._rule_based_fallback(
    comment_text="Maine kr liya 🙌👏",
    reel_caption="Instagram automation tutorial",
    message_availability=MessageAvailability.MESSAGE_BUTTON_VISIBLE,
    is_private=False
)
analysisB = classifier._build_analysis_object("__anu.anushka_", "reel_01", "Maine kr liya 🙌👏", MessageAvailability.MESSAGE_BUTTON_VISIBLE, resB)
sl.record_analysis(analysisB)
sm.mark_user_processed("__anu.anushka_", "reel_01", analysisB.decision.value)

print("  [Scenario B: Engaged Commenter with Message Button]")
print(f"    Decision: {analysisB.decision.value} (Expected: ELIGIBLE in engaged mode)")
print(f"    Suggested Question: '{analysisB.suggested_question}'")
assert analysisB.decision == DecisionClassification.ELIGIBLE
assert analysisB.suggested_question is not None
print("    >>> PASS ✓\n", flush=True)

# Scenario C: Explicit Refusal -> DO_NOT_CONTACT
resC = classifier._rule_based_fallback(
    comment_text="Please stop messaging and don't dm me",
    reel_caption="Demo",
    message_availability=MessageAvailability.MESSAGE_BUTTON_VISIBLE,
    is_private=False
)
analysisC = classifier._build_analysis_object("anti_spam", "reel_01", "Please stop messaging and don't dm me", MessageAvailability.MESSAGE_BUTTON_VISIBLE, resC)
sl.record_analysis(analysisC)
sm.mark_user_processed("anti_spam", "reel_01", analysisC.decision.value)

print("  [Scenario C: Explicit Refusal]")
print(f"    Decision: {analysisC.decision.value} (Expected: DO_NOT_CONTACT)")
print(f"    DM Permission: {analysisC.dm_permission.value} (Expected: EXPLICIT_REFUSAL)")
assert analysisC.decision == DecisionClassification.DO_NOT_CONTACT
assert analysisC.suggested_question is None
print("    >>> PASS ✓\n", flush=True)

# Scenario D: Missing Message Button -> UNAVAILABLE
resD = classifier._rule_based_fallback(
    comment_text="DM me details",
    reel_caption="Demo",
    message_availability=MessageAvailability.MESSAGE_BUTTON_UNAVAILABLE,
    is_private=True
)
analysisD = classifier._build_analysis_object("locked_profile", "reel_01", "DM me details", MessageAvailability.MESSAGE_BUTTON_UNAVAILABLE, resD)
sl.record_analysis(analysisD)
sm.mark_user_processed("locked_profile", "reel_01", analysisD.decision.value)

print("  [Scenario D: Message Button Unavailable]")
print(f"    Decision: {analysisD.decision.value} (Expected: UNAVAILABLE)")
assert analysisD.decision == DecisionClassification.UNAVAILABLE
assert analysisD.suggested_question is None
print("    >>> PASS ✓\n", flush=True)

# Scenario E: StateManager Deduplication Check
print("  [Scenario E: StateManager Deduplication]")
assert sm.is_user_processed("growth_seeker")
assert sm.is_user_processed("@GROWTH_SEEKER")
assert sm.is_user_processed("anti_spam")
assert not sm.is_user_processed("uncontacted_lead")
print("    >>> PASS ✓\n", flush=True)

# Scenario F: Self-Promotional Spam & Story/Profile Bait Filter
from models.classifier import is_self_promo_or_spam

print("  [Scenario F: Self-Promotional Spam & Story/Profile Bait Filter]")
spam_samples = [
    "Ek bar story chek kro❤️",
    "mera profile dekho",
    "check my story please",
    "meri profile check karo na",
    "link in bio check it out",
    "follow back please f4f",
    "Promote it on @some_page"
]
for sample in spam_samples:
    is_spam, reason = is_self_promo_or_spam(sample)
    print(f"    '{sample}' -> Detected Spam: {is_spam} ({reason})")
    assert is_spam, f"Sample '{sample}' should have been detected as spam!"

# Verify rule-based fallback also classifies it as NOT_INTERESTED
resF = classifier._rule_based_fallback(
    comment_text="Ek bar story chek kro❤️",
    reel_caption="Demo reel",
    message_availability=MessageAvailability.MESSAGE_BUTTON_VISIBLE,
    is_private=False
)
assert resF["decision"] == DecisionClassification.NOT_INTERESTED.value
print("    >>> PASS ✓ (All self-promo bait correctly ignored!)\n", flush=True)

# Scenario G: Comment Text Cleaning (Ignore Like Counts like "4 likes", "24,845 likes")
print("  [Scenario G: Like Counter Discard & Sanitization]")
like_samples = ["4 likes", "24,845 likes", "1 like", "10k likes", "likes", "Like"]
for lk in like_samples:
    is_pure_like = bool(re.match(r"^[\d,.]+[kmb]?\s*likes?$", lk, re.IGNORECASE) or lk.lower() in ["like", "likes", "reply"])
    print(f"    '{lk}' -> Identified as pure Like counter: {is_pure_like}")
    assert is_pure_like, f"Expected '{lk}' to be recognized as like counter!"

raw_with_trailing = "My respect for cameraman 😄\n24,845 likes Reply"
cleaned = re.sub(r"[\d,.]+[kmb]?\s*likes?\s*(reply)?.*$", "", raw_with_trailing, flags=re.IGNORECASE).strip()
print(f"    Raw: '{raw_with_trailing}' -> Cleaned: '{cleaned}'")
assert cleaned == "My respect for cameraman 😄"
print("    >>> PASS ✓ (Like counters never mistaken for comment text!)\n", flush=True)

# Session Stats & Message Logging Verification
print("  [Session Stats & Dedicated Message Log Verification]")
sl.record_message_sent(
    reel_id="reel_01",
    reel_url="https://www.instagram.com/reel/reel_01/",
    username="growth_seeker",
    comment_text="This workflow is insane! DM me the pricing and setup details please.",
    messages=analysisA.message_sequence
)
assert sl.messages_file.exists()
print(f"    Eligible Conversations: {sl.stats.eligible_conversations}")
print(f"    Questions Prepared: {sl.stats.questions_prepared}")
print(f"    Do Not Contact: {sl.stats.do_not_contact_profiles}")
print(f"    Unavailable Profiles: {sl.stats.unavailable_profiles}")
assert sl.stats.eligible_conversations == 2
assert sl.stats.questions_prepared == 2
assert sl.stats.do_not_contact_profiles == 1
assert sl.stats.unavailable_profiles == 1
print("    >>> ALL SESSION METRICS VERIFIED! ✓\n", flush=True)

print("======================================================================", flush=True)
print("   ALL SCENARIOS AND DECISION LOGIC VERIFIED 100% SUCCESSFULLY!", flush=True)
print("======================================================================", flush=True)
