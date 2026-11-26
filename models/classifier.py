import os
import re
import json
import random
import asyncio
from typing import Optional, Tuple, Any

from config.settings import settings
from models.schemas import (
    CommentIntent,
    MessageAvailability,
    DMPermission,
    DecisionClassification,
    ProspectAnalysis
)

ANALYSIS_SYSTEM_PROMPT = """You are writing DMs as a real Indian Instagram creator who just saw someone's comment on your Reel. You're not a bot, not a brand, not a marketer. You're a person sitting on your phone, genuinely curious about this commenter, sliding into their DMs the way a real human would.

Your job:
1. Decide if this person is worth messaging (see eligibility rules below).
2. If ELIGIBLE → write a DM sequence (1 to 3 messages) that feels 100% like a real human texted it.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ELIGIBILITY — STEP 1
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Comment Intent: EXPLICITLY_INTERESTED | ASKING_FOR_INFO | PURCHASE_INTENT | COLLABORATION | CASUAL_ENGAGEMENT | UNRELATED | UNCERTAIN
DM Permission: EXPLICIT_INVITATION | EXISTING_PERMISSION | NO_EXPLICIT_PERMISSION | EXPLICIT_REFUSAL

Decision:
- ELIGIBLE: Message button visible + they left a real, engaged comment.
- INTERESTED_BUT_NO_PERMISSION: Interest is there but no explicit DM invite.
- NOT_INTERESTED: Generic praise, emojis-only, or unrelated filler.
- UNAVAILABLE: Messaging not possible.
- DO_NOT_CONTACT: They refused or opted out.
- UNCERTAIN: Not enough info.

SPAM → auto NOT_INTERESTED: "check my story", "story dekho", "mera profile dekho", "check my profile", "link in bio", "follow back", "f4f", any engagement bait.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WRITING THE DM — STEP 2 (ELIGIBLE ONLY)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Write 1 to 3 DM messages. Each is a separate chat bubble.

⚠️ CRITICAL — msg_1 IS ALWAYS null IN YOUR OUTPUT:
  The system AUTOMATICALLY sends their original comment text as the very first bubble — you never write msg_1.
  Your job starts at msg_2. Always output msg_1 as null.

HOW REAL HUMANS DM ON INSTAGRAM — study this:
- After seeing a comment they react to in their DMs, real humans first "echo" that comment (the app does this automatically — it appears as the first bubble).
- Then they react in msg_2: what the comment made them FEEL — surprise, curiosity, relatability, humour.
- They're direct. They don't build up to the point for 3 lines.
- They use lowercase mostly. Capital letters feel formal/angry.
- They use "lol", "ngl", "tbh", "lowkey", "bro", "yaar", "na", "hai kya", "bata", "sach mein" naturally.
- Short messages feel casual and real. Long ones feel like an email.
- They might send ONE short reaction, then ONE actual question. That's it.

HINGLISH SPEAKERS — if the comment is in Hindi/Hinglish, respond the same way.
Real Hinglish DM examples of how people actually write (these are your msg_2 / msg_3):
  "bhai yeh dekh ke mujhe bhi same feel hua tha 😂"
  "yaar teri comment se mujhe genuine curiosity aayi"
  "ngl teri wali baat se sab relate karte hain"
  "bata isko dekh ke kya feel hua actually?"
  "yeh wala scene mujhe bhi bohot hit kiya tha ngl"

ENGLISH SPEAKERS — casual, lowercase, no corporate tone:
  "ngl your comment genuinely caught me off guard"
  "that's exactly the reaction I was hoping for honestly"
  "wait what made you stop at that part specifically?"
  "lowkey didn't expect someone to actually get that"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THE RULES — NON-NEGOTIABLE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔥 RULE 1 — msg_1 IS ALWAYS null — DO NOT WRITE IT
  The system sends their original comment as the first bubble automatically.
  Your msg_2 is the actual first thing YOU say. Make it a genuine human reaction.
  BAD msg_2: "\"bhai yeh kya scene tha 😂\" — that really made me laugh"  ← quoting again = robotic
  GOOD msg_2: "bhai scene wala comment notice ho gaya 😂 genuinely caught me"  ← natural reaction

🔥 RULE 2 — ONE QUESTION ONLY, IN msg_2 OR msg_3
  Ask exactly one real, specific question directly about their comment or the Reel. Max 15 words.
  BAD: "What did you think of the video? Did you enjoy it?"
  GOOD: "wait what actually made you stop at that part?"

🔥 RULE 3 — MATCH THEIR LANGUAGE EXACTLY
  Hinglish comment → Hinglish reply. English → English. Emoji-heavy → match emoji energy. Formal → tone down slang.

🔥 RULE 4 — SHORT IS BETTER
  msg_2: 1 sentence reaction max. msg_3 (question): short and direct. msg_4: only if it adds something real (a funny observation, soft CTA, genuine warmth) — skip it otherwise.

🔥 RULE 5 — ZERO CLICHÉS. EVER.
  Banned: "Let me know your thoughts", "Thanks for reaching out", "Hope this helps", "Have a great day", "Happy to help", "I'd love to connect", "Feel free to reach out", "Excited to chat", "Looking forward to it", "What was your favorite part", "I'd be happy to".

🔥 RULE 6 — TIE SOMETHING TO THE REEL
  At least msg_1 or msg_2 must reference the Reel's actual theme, topic or mood — not just the comment in isolation.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT — Valid JSON only:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
  "comment_intent": "EXPLICITLY_INTERESTED" | "ASKING_FOR_INFO" | "PURCHASE_INTENT" | "COLLABORATION" | "CASUAL_ENGAGEMENT" | "UNRELATED" | "UNCERTAIN",
  "dm_permission": "EXPLICIT_INVITATION" | "EXISTING_PERMISSION" | "NO_EXPLICIT_PERMISSION" | "EXPLICIT_REFUSAL",
  "decision": "ELIGIBLE" | "INTERESTED_BUT_NO_PERMISSION" | "NOT_INTERESTED" | "UNAVAILABLE" | "DO_NOT_CONTACT" | "UNCERTAIN",
  "reasoning": "1-sentence explanation",
  "msg_1": null,
  "msg_2": "YOUR first message — genuine human reaction to their comment + reel. Required if ELIGIBLE.",
  "msg_3": "The ONE specific question tied to their comment/reel. Required if ELIGIBLE.",
  "msg_4": "Optional only if it genuinely adds something — a funny line, soft CTA, warmth. null in most cases."
}
"""

SELF_PROMO_SPAM_PATTERNS = [
    # 1. Story engagement bait (English & Hinglish)
    (r"\b(check|chek|see|dekho|deko|dekh|dekhiye|kro|krdo)\b.*\b(story|stori)\b", "Story check bait"),
    (r"\b(story|stori)\b.*\b(check|chek|dekho|deko|dekh|dekhiye|kro|krdo|pe|par|me|mein)\b", "Story check bait"),
    (r"\bek\s*ba+r\s*(bhi\s*)?(story|stori)\b", "Story check bait"),
    (r"\b(meri|my)\s*(bhi\s*)?(story|stori)\b", "Story check bait"),
    (r"\bcheck\s*my\s*highlights?\b", "Highlight check bait"),
    
    # 2. Profile / Account / Page bait (English & Hinglish)
    (r"\b(mera|meri|my)\s*(profile|proflie|pfiodel|profil|ac+ount|id|page)\b", "Profile visit bait"),
    (r"\b(check|chek|visit|dekho|deko|dekh|dekhiye|kro|krdo)\s*(my|mera|meri)?\s*(profile|proflie|pfiodel|profil|ac+ount|id|page)\b", "Profile visit bait"),
    (r"\b(profile|proflie|pfiodel|profil|ac+ount|id|page)\s*(check|chek|dekho|deko|dekh|dekhiye|kro|krdo)\b", "Profile visit bait"),
    (r"\bvisit\s*(my\s*)?(page|profile)\b", "Profile visit bait"),
    (r"\bcheck\s*my\s*page\b", "Profile visit bait"),
    
    # 3. Bio link / bait
    (r"\b(check|chek|see|dekho|deko|dekh)\s*(my\s*)?bio\b", "Bio check bait"),
    (r"\blink\s*in\s*bio\b", "Link in bio bait"),
    (r"\bbio\s*(check|link|mein|pe|par)\b", "Bio check bait"),
    
    # 4. Follow-for-follow & spam promotion
    (r"\bfollow\s*(back|me|karo|krdo|krna)\b", "Follow-for-follow bait"),
    (r"\bf4f\b", "Follow-for-follow bait"),
    (r"\bpromote\s*(it\s*)?on\b", "Promo bot spam"),
    (r"\bsend\s*(pic|photo|video)\s*on\b", "Promo bot spam"),
    (r"\bdm\s*(it\s*)?on\b", "Promo bot spam")
]

def is_self_promo_or_spam(comment_text: str) -> Tuple[bool, Optional[str]]:
    """
    Detects whether a comment is self-promotional spam or engagement bait
    (e.g., 'Ek bar story chek kro', 'check my story', 'mera profile dekho', 'check bio').
    Returns (True, reason) if spam, otherwise (False, None).
    """
    if not comment_text:
        return False, None
    text = comment_text.lower().strip()
    for pattern, reason in SELF_PROMO_SPAM_PATTERNS:
        if re.search(pattern, text):
            return True, reason
    return False, None

class MessageSequenceAutomata:
    """
    Builds and validates the final 2-4 message DM sequence from AI output.

    Slots:
      msg_1  — Anchor: echoes the comment, genuine recognition opener.
      msg_2  — Personalized reaction + the ONE question (required).
      msg_3  — Optional followup: context, soft CTA, funny aside, warmth.
      msg_4  — Rare bonus line (≤30% chance). Only if genuinely adds value.

    Also supports legacy keys (message_1_quote / suggested_question / message_3_optional)
    so old rule-engine fallback results still work.
    """

    FORBIDDEN_CLICHES = [
        "let me know your thoughts",
        "let me know what you think",
        "what was your favorite part",
        "hope this helps",
        "thanks for reaching out",
        "happy to help",
        "hope you're having a great day",
        "i'd love to connect",
        "feel free to reach out",
        "excited to chat",
        "looking forward to it",
        "i'd be happy to",
        "don't hesitate to",
    ]

    @classmethod
    def _clean(cls, text: str) -> str:
        """Strip wrapping quotes, hashtags, and ensure clean text."""
        if not text:
            return ""
        text = text.strip()
        if len(text) >= 2 and text[0] in ('"', "'") and text[-1] == text[0]:
            text = text[1:-1].strip()
        # Strip hashtags — DMs with hashtags look like copy-paste marketing, not human
        text = re.sub(r'\s*#\w+', '', text).strip()
        return text

    @classmethod
    def _is_valid(cls, text: str, existing: list) -> bool:
        """Returns True if text is non-empty, non-cliché, and not a duplicate."""
        if not text or len(text) < 3:
            return False
        lower = text.lower()
        if any(cliche in lower for cliche in cls.FORBIDDEN_CLICHES):
            return False
        if text in existing:
            return False
        return True

    @classmethod
    def _enforce_one_question(cls, text: str) -> str:
        """Trims to max 1 question mark."""
        if text.count("?") > 1:
            parts = text.split("?")
            text = parts[0].strip() + "?"
        return text

    @classmethod
    def process_sequence(cls, comment_text: str, data: dict, fallback_q: str = None) -> list:
        """
        Builds the final ordered DM sequence (2–4 messages).

        Slot 1 — ALWAYS the commenter's exact original comment text (non-negotiable).
                  This is what creates natural context — the person sees their own words echoed back.
                  The AI is instructed to set msg_1=null; we override it here regardless.

        Slot 2 — AI's genuine human reaction to the comment (msg_2). Required.

        Slot 3 — AI's ONE specific question (msg_3). Required.
                  Falls back to legacy key suggested_question or fallback_q.

        Slot 4 — Optional bonus line (msg_4). Hard-capped at 30% chance.
        """
        sequence = []

        # ── Slot 1: Their comment verbatim — always first, always sent ────────
        raw1 = cls._clean(comment_text or "")
        if raw1:
            sequence.append(raw1)  # Non-negotiable: their own comment goes first

        # ── Slot 2: AI's human reaction (required) ────────────────────────────
        raw2 = cls._clean(data.get("msg_2") or data.get("msg_1") or data.get("message_1_quote") or "")
        if cls._is_valid(raw2, sequence):
            sequence.append(raw2)

        # ── Slot 3: The ONE question (required) ───────────────────────────────
        raw3 = cls._clean(data.get("msg_3") or data.get("suggested_question") or fallback_q or "")
        raw3 = cls._enforce_one_question(raw3)
        if cls._is_valid(raw3, sequence):
            sequence.append(raw3)

        # ── Slot 4: Rare bonus line (hard-capped at 30%) ──────────────────────
        raw4 = cls._clean(data.get("msg_4") or data.get("message_3_optional") or "")
        if raw4 and random.random() < 0.30 and cls._is_valid(raw4, sequence):
            sequence.append(raw4)

        return sequence

class AIClassifier:
    def __init__(self):
        self.groq_client: Optional[Any] = None
        self.openrouter_client: Optional[Any] = None
        self.ollama_client: Optional[Any] = None
        self._init_clients()

    def _init_clients(self):
        # 1. Initialize Groq client only if API key is provided
        if settings.groq_api_key and settings.groq_api_key.strip():
            try:
                import httpx
                from openai import AsyncOpenAI
                http_client = httpx.AsyncClient(trust_env=False, timeout=6.0)
                self.groq_client = AsyncOpenAI(
                    base_url="https://api.groq.com/openai/v1",
                    api_key=settings.groq_api_key.strip(),
                    http_client=http_client,
                    max_retries=1
                )
                print(f"[AIClassifier] Groq client initialized successfully ({settings.groq_model}).")
            except Exception as e:
                print(f"[AIClassifier] Error initializing Groq client: {e}")

        # 2. Initialize OpenRouter client if API key is provided
        if settings.openrouter_api_key and settings.openrouter_api_key.strip():
            try:
                import httpx
                from openai import AsyncOpenAI
                http_client = httpx.AsyncClient(trust_env=False, timeout=8.0)
                self.openrouter_client = AsyncOpenAI(
                    base_url=settings.openrouter_base_url.rstrip("/"),
                    api_key=settings.openrouter_api_key.strip(),
                    http_client=http_client,
                    max_retries=1
                )
                print(f"[AIClassifier] OpenRouter client initialized ({settings.openrouter_model}).")
            except Exception as e:
                print(f"[AIClassifier] Error initializing OpenRouter client: {e}")

        # 3. Initialize Ollama client only if explicitly enabled
        if settings.ollama_enabled:
            try:
                import httpx
                from openai import AsyncOpenAI
                http_client = httpx.AsyncClient(trust_env=False, timeout=3.0)
                self.ollama_client = AsyncOpenAI(
                    base_url=f"{settings.ollama_base_url.rstrip('/')}/v1",
                    api_key="ollama",
                    http_client=http_client,
                    max_retries=0
                )
                print(f"[AIClassifier] Ollama client initialized on {settings.ollama_base_url}.")
            except Exception as e:
                print(f"[AIClassifier] Error initializing Ollama client: {e}")

    async def analyze(
        self,
        username: str,
        reel_id: str,
        reel_caption: Optional[str],
        comment_text: str,
        is_private: bool,
        message_availability: MessageAvailability,
        bio_text: Optional[str]
    ) -> ProspectAnalysis:
        user_prompt = f"""
REEL CONTEXT:
Reel ID: {reel_id}
Caption: {reel_caption or "N/A"}

COMMENTER:
Username: @{username}
Comment: "{comment_text}"

PROFILE CONTEXT:
Account Private: {"Yes" if is_private else "No"}
Message Button Available: {message_availability.value}
Bio: {bio_text or "N/A"}
"""
        # Priority order: Ollama (local/free) → Groq (cloud fast) → OpenRouter (last resort)

        # 1. Try Ollama local model FIRST if active
        if self.ollama_client:
            try:
                res = await self._call_ollama(user_prompt)
                if res:
                    print(f"[AIClassifier] ✓ Used Ollama local model ({settings.ollama_model})")
                    return self._build_analysis_object(username, reel_id, comment_text, message_availability, res)
            except Exception as e:
                print(f"[AIClassifier] Ollama failed ({e}). Trying Groq...")

        # 2. Try Groq API (cloud, fast, free tier)
        if self.groq_client:
            try:
                res = await self._call_groq(user_prompt)
                if res:
                    return self._build_analysis_object(username, reel_id, comment_text, message_availability, res)
            except Exception as e:
                print(f"[AIClassifier] Groq exhausted ({e}). Trying OpenRouter...")

        # 3. Try OpenRouter (last cloud resort)
        if self.openrouter_client:
            try:
                res = await self._call_openrouter(user_prompt)
                if res:
                    return self._build_analysis_object(username, reel_id, comment_text, message_availability, res)
            except Exception as e:
                print(f"[AIClassifier] OpenRouter failed ({e}). Falling back to rule engine...")

        # 4. Deterministic Heuristic Rule Engine (absolute last resort)
        res = self._rule_based_fallback(
            comment_text=comment_text,
            reel_caption=reel_caption,
            message_availability=message_availability,
            is_private=is_private
        )
        return self._build_analysis_object(username, reel_id, comment_text, message_availability, res)

    async def _call_groq(self, prompt: str) -> Optional[dict]:
        """
        Executes Groq chat completion with automatic multi-model fallback rotation.
        If the primary model is decommissioned, rate-limited, or unavailable,
        it automatically tries the next active model in sequence.
        """
        models_to_try = [settings.groq_model]
        # Up-to-date fallback rotation — decommissioned models removed
        # Order: fastest/cheapest → larger → safest fallback
        fallback_models = getattr(settings, "groq_fallback_models", [
            "qwen/qwen3.8-27b",          # 131K ctx, JSON mode, fast
            "openai/gpt-oss-20b",         # OpenAI open-weight on Groq
            "openai/gpt-oss-120b",        # Larger OSS model
            "allam-2-7b",                 # Arabic/multilingual capable
            "meta-llama/llama-4-scout-17b-16e-instruct",   # Llama 4 Scout
            "meta-llama/llama-4-maverick-17b-128e-instruct", # Llama 4 Maverick
            "llama-3.1-8b-instant",       # Fast 8B — broad availability
            "gemma2-9b-it",               # Google Gemma 2 — widely available
        ])
        for m in fallback_models:
            if m not in models_to_try:
                models_to_try.append(m)

        last_error = None
        for model_name in models_to_try:
            try:
                try:
                    response = await self.groq_client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                            {"role": "user", "content": prompt}
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.92,
                        top_p=0.95,
                        max_tokens=900
                    )
                except Exception as json_err:
                    err_str = str(json_err).lower()
                    if "response_format" in err_str or "json_validate_failed" in err_str:
                        response = await self.groq_client.chat.completions.create(
                            model=model_name,
                            messages=[
                                {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                                {"role": "user", "content": prompt}
                            ],
                            temperature=0.92,
                            top_p=0.95,
                            max_tokens=900
                        )
                    else:
                        raise json_err

                content = (response.choices[0].message.content or "").strip()
                if content.startswith("```"):
                    content = re.sub(r"^```(?:json)?\s*", "", content)
                    content = re.sub(r"\s*```$", "", content)
                data = json.loads(content)
                if model_name != settings.groq_model:
                    print(f"[AIClassifier] ✓ Groq rotated to fallback model: [{model_name}] (Success)")
                return data
            except Exception as e:
                last_error = e
                print(f"[AIClassifier] Groq model '{model_name}' unavailable ({e}). Rotating to next fallback model...")
                continue

        raise last_error or RuntimeError("All Groq models exhausted.")

    async def _call_openrouter(self, prompt: str) -> Optional[dict]:
        """
        Executes OpenRouter chat completion with multi-model fallback rotation.
        """
        models_to_try = [
            settings.openrouter_model,
            "meta-llama/llama-3.3-70b-instruct",
            "google/gemini-2.0-flash-exp:free",
            "mistralai/mistral-7b-instruct:free"
        ]
        unique_models = []
        for m in models_to_try:
            if m and m not in unique_models:
                unique_models.append(m)

        last_error = None
        for model_name in unique_models:
            try:
                response = await self.openrouter_client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.92,
                    top_p=0.95,
                    max_tokens=900
                )
                content = (response.choices[0].message.content or "").strip()
                if content.startswith("```"):
                    content = re.sub(r"^```(?:json)?\s*", "", content)
                    content = re.sub(r"\s*```$", "", content)
                return json.loads(content)
            except Exception as e:
                last_error = e
                print(f"[AIClassifier] OpenRouter model '{model_name}' failed ({e}). Rotating to next model...")
                continue

        raise last_error or RuntimeError("All OpenRouter models exhausted.")

    async def _call_ollama(self, prompt: str) -> Optional[dict]:
        """
        Calls local Ollama with model rotation fallback.
        Tries settings.ollama_model first, then common capable local models.
        """
        models_to_try = [settings.ollama_model]
        # Prefer big-context capable local models — small ones give generic responses
        for m in ["qwen2.5:14b", "llama3.1:8b", "llama3.3:70b", "qwen2.5:7b", "mistral:7b", "llama3.2:3b", "phi3:mini", "gemma2:2b"]:
            if m not in models_to_try:
                models_to_try.append(m)

        for model_name in models_to_try:
            try:
                response = await self.ollama_client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.85,   # Higher temp for more natural, varied messages
                    top_p=0.95,
                    max_tokens=700
                )
                content = response.choices[0].message.content or ""
                if content.startswith("```"):
                    content = re.sub(r"^```(?:json)?\s*", "", content)
                    content = re.sub(r"\s*```$", "", content)
                data = json.loads(content)
                if model_name != settings.ollama_model:
                    print(f"[AIClassifier] Ollama rotated to: [{model_name}]")
                return data
            except Exception as e:
                err = str(e).lower()
                if "not found" in err or "pull" in err or "model" in err:
                    # Model not installed locally — try next
                    continue
                raise  # Other errors (connection etc.) → let caller handle

    def _rule_based_fallback(
        self,
        comment_text: str,
        reel_caption: Optional[str],
        message_availability: MessageAvailability,
        is_private: bool
    ) -> dict:
        text = comment_text.lower().strip()

        # Check self-promotional spam and engagement-bait first (e.g. "Ek bar story chek kro", "mera profile dekho")
        is_spam, spam_reason = is_self_promo_or_spam(comment_text)
        if is_spam:
            return {
                "comment_intent": CommentIntent.UNRELATED.value,
                "dm_permission": DMPermission.NO_EXPLICIT_PERMISSION.value,
                "decision": DecisionClassification.NOT_INTERESTED.value,
                "reasoning": f"Ignored: Self-promotional engagement bait ({spam_reason}).",
                "suggested_question": None,
                "message_1_quote": None,
                "message_3_optional": None
            }

        # Check explicit refusals first
        refusal_patterns = [r"don't dm", r"dont dm", r"no dms", r"stop messaging", r"spam", r"leave me alone"]
        if any(re.search(p, text) for p in refusal_patterns):
            return {
                "comment_intent": CommentIntent.UNRELATED.value,
                "dm_permission": DMPermission.EXPLICIT_REFUSAL.value,
                "decision": DecisionClassification.DO_NOT_CONTACT.value,
                "reasoning": "Commenter explicitly refused direct messages or asked not to be contacted.",
                "suggested_question": None,
                "message_1_quote": None,
                "message_3_optional": None
            }

        # Check explicit DM invitations
        dm_invitation_patterns = [
            r"\bdm\s*me\b", r"\bsend\s*me\s*(a\s*)?dm\b", r"\bmessage\s*me\b",
            r"\binbox\s*me\b", r"\bcheck\s*(your\s*)?(dm|inbox)\b", r"\bsend\s*(me\s*)?(the\s*)?(link|info|details|pricing)\b",
            r"\bshoot\s*me\s*a\s*dm\b", r"\bpm\s*me\b"
        ]
        has_explicit_dm_invite = any(re.search(p, text) for p in dm_invitation_patterns)

        # Check purchase/info intent
        info_patterns = [r"how much", r"price", r"cost", r"where can i", r"link", r"how to", r"interested", r"want this"]
        has_info_intent = any(re.search(p, text) for p in info_patterns)

        # Classify Intent
        if has_explicit_dm_invite:
            intent = CommentIntent.EXPLICITLY_INTERESTED.value
            permission = DMPermission.EXPLICIT_INVITATION.value
        elif has_info_intent:
            intent = CommentIntent.ASKING_FOR_INFO.value
            permission = DMPermission.NO_EXPLICIT_PERMISSION.value
        elif len(text.split()) < 3 and any(w in text for w in ["nice", "cool", "fire", "wow", "🔥", "❤️", "clap"]):
            intent = CommentIntent.CASUAL_ENGAGEMENT.value
            permission = DMPermission.NO_EXPLICIT_PERMISSION.value
        else:
            intent = CommentIntent.UNCERTAIN.value
            permission = DMPermission.NO_EXPLICIT_PERMISSION.value

        # Technical Message Availability Check
        is_msg_possible = (message_availability == MessageAvailability.MESSAGE_BUTTON_VISIBLE)
        mode = getattr(settings, "eligibility_mode", "engaged")

        # Decision synthesis
        if not is_msg_possible:
            decision = DecisionClassification.UNAVAILABLE.value
            reasoning = "Message button is unavailable or restricted on this profile."
            question = None
            opt_msg3 = None
        elif has_explicit_dm_invite and is_msg_possible:
            decision = DecisionClassification.ELIGIBLE.value
            permission = DMPermission.EXPLICIT_INVITATION.value
            reasoning = "User explicitly requested a DM and messaging is technically available."
            question = self._generate_fallback_question(comment_text, reel_caption)
            opt_msg3 = "I can drop the direct resource link right here if you'd like!"
        elif is_msg_possible and mode == "engaged":
            # Growth / Engaged Lead Mode: Profile has open DM and commenter actively engaged with the Reel
            decision = DecisionClassification.ELIGIBLE.value
            permission = DMPermission.EXISTING_PERMISSION.value
            reasoning = f"Profile allows direct messaging and user actively engaged with comment: '{comment_text[:40]}'."
            question = self._generate_fallback_question(comment_text, reel_caption)
            opt_msg3 = None
        elif has_info_intent:
            decision = DecisionClassification.INTERESTED_BUT_NO_PERMISSION.value
            reasoning = "User expressed interest or asked a question, but did not explicitly invite a DM."
            question = None
            opt_msg3 = None
        else:
            decision = DecisionClassification.NOT_INTERESTED.value
            reasoning = "Casual comment or no explicit DM permission found."
            question = None
            opt_msg3 = None

        return {
            "comment_intent": intent,
            "dm_permission": permission,
            "decision": decision,
            "reasoning": reasoning,
            "msg_1": comment_text.strip() if decision == DecisionClassification.ELIGIBLE.value else None,
            "msg_2": question,
            "msg_3": opt_msg3,
            "msg_4": None,
            # Legacy keys kept for backward compat
            "message_1_quote": comment_text.strip() if decision == DecisionClassification.ELIGIBLE.value else None,
            "suggested_question": question,
            "message_3_optional": opt_msg3
        }

    def _generate_fallback_question(self, comment_text: str, reel_caption: Optional[str]) -> str:
        text = comment_text.lower().strip()
        variant_idx = sum(ord(c) for c in text[:8]) % 3

        if "price" in text or "cost" in text or "how much" in text or "kitna" in text:
            options = [
                "Hey! Are you looking at this for yourself or for your business?",
                "Saw your question on pricing—curious what you're planning to use it for?",
                "Hey! Quick question, are you looking to test this out soon?"
            ]
            return options[variant_idx]
        if "link" in text or "bhejo" in text:
            options = [
                "Hey! Want me to shoot over the link right here?",
                "Saw you asked for the link—shall I drop it in this chat for you?",
                "Happy to share it—are you looking to set it up right away?"
            ]
            return options[variant_idx]
        if "how" in text or "details" in text or "info" in text or "kaise" in text:
            options = [
                "Saw your comment—which specific step seemed most tricky to you?",
                "Hey! Which part of the process were you most curious about?",
                "Curious—have you tried a setup like this before?"
            ]
            return options[variant_idx]
        if any(w in text for w in ["kr liya", "kar liya", "done", "tried", "maine"]):
            options = [
                "Awesome that you gave it a shot! Did it work smoothly for you?",
                "Love that you tried it! How long did it take you to set up?",
                "Respect for trying it out—what was the coolest part for you?"
            ]
            return options[variant_idx]
        if any(w in text for w in ["gorgeous", "fire", "nice", "wow", "love", "sahi", "🔥", "❤️", "aww", "super"]):
            options = [
                "Haha appreciate the love! Are you into this kind of content usually?",
                "That clip was crazy fun to watch right? What was your take on it?",
                "Loved your reaction! Have you seen anything like that before?"
            ]
            return options[variant_idx]
        if any(w in text for w in ["god", "😂", "lol", "kya", "can you", "tum kar", "sakte"]):
            options = [
                "Haha that part made me crack up too! Did you see that coming?",
                "Right?! What would you have done in that situation?",
                "That ending was unbelievable haha—did that catch you off guard?"
            ]
            return options[variant_idx]

        options = [
            "Hey! Saw your comment on the clip—are you into this topic as well?",
            "Appreciate you stopping by the reel! What caught your eye first?",
            "Hey! Curious, have you come across something like this before?"
        ]
        return options[variant_idx]

    def _build_analysis_object(
        self,
        username: str,
        reel_id: str,
        comment_text: str,
        message_availability: MessageAvailability,
        data: dict
    ) -> ProspectAnalysis:
        try:
            intent = CommentIntent(data.get("comment_intent", CommentIntent.UNCERTAIN.value))
        except ValueError:
            intent = CommentIntent.UNCERTAIN

        try:
            permission = DMPermission(data.get("dm_permission", DMPermission.NO_EXPLICIT_PERMISSION.value))
        except ValueError:
            permission = DMPermission.NO_EXPLICIT_PERMISSION

        try:
            decision = DecisionClassification(data.get("decision", DecisionClassification.UNCERTAIN.value))
        except ValueError:
            decision = DecisionClassification.UNCERTAIN

        question = data.get("suggested_question")
        message_sequence = []

        if decision != DecisionClassification.ELIGIBLE:
            question = None
        else:
            # Use Theory Automata to orchestrate and sort message sequence
            message_sequence = MessageSequenceAutomata.process_sequence(
                comment_text=comment_text,
                data=data,
                fallback_q=question
            )
            # Ensure suggested_question is set from sequence
            if len(message_sequence) > 1:
                question = message_sequence[1]

        return ProspectAnalysis(
            username=username,
            reel_id=reel_id,
            comment_text=comment_text,
            comment_intent=intent,
            message_availability=message_availability,
            dm_permission=permission,
            decision=decision,
            reasoning=data.get("reasoning", ""),
            suggested_question=question,
            message_sequence=message_sequence
        )
