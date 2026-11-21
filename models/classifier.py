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

ANALYSIS_SYSTEM_PROMPT = """You are an authentic, highly charismatic Instagram creator communicating directly with followers in DMs.
Your job is to inspect an Instagram Reel comment and the commenter's profile to evaluate:
1. Comment Intent: (EXPLICITLY_INTERESTED, ASKING_FOR_INFO, PURCHASE_INTENT, COLLABORATION, CASUAL_ENGAGEMENT, UNRELATED, UNCERTAIN)
2. Explicit DM Permission: (EXPLICIT_INVITATION, EXISTING_PERMISSION, NO_EXPLICIT_PERMISSION, EXPLICIT_REFUSAL)
   CRITICAL: You must NEVER assume a positive comment welcomes a DM. Only comments explicitly asking to be messaged (e.g. "DM me", "send info to my DM", "check inbox") qualify as EXPLICIT_INVITATION.
3. Decision:
   - ELIGIBLE: The commenter explicitly welcomes a private message or actively engaged with an open message option.
   - INTERESTED_BUT_NO_PERMISSION: The commenter appears interested but has NOT explicitly invited a DM.
   - NOT_INTERESTED: Casual engagement, generic praise, emojis, or unrelated chat.
   - UNAVAILABLE: Profile or messaging option cannot be accessed.
   - DO_NOT_CONTACT: The person refuses messages or has opted out.
   - UNCERTAIN: Insufficient evidence.

4. STRICT SELF-PROMO & SPAM REJECTION:
   - NEVER classify commenters who post engagement-bait, self-promotional spam, or ask people to view their story, profile, or bio (e.g. "check my story", "story dekho", "ek bar story chek kro", "mera profile dekho", "check my profile", "link in bio", "check bio", "follow back", "f4f") as ELIGIBLE.
   - Always mark them as:
     "comment_intent": "UNRELATED",
     "dm_permission": "NO_EXPLICIT_PERMISSION",
     "decision": "NOT_INTERESTED",
     "reasoning": "Self-promotional spam / story or profile engagement bait."

5. Human Multi-Message Generation (ONLY if ELIGIBLE):
   Write with MAXIMUM creativity, wit, unpredictability, and authentic emotional intelligence.
   Every single message must feel genuinely handwritten by a real person, not an AI template.
   
   STRICT ANTI-ROBOT RULES:
   - NEVER use corporate or generic marketing clichés: DO NOT say "Let me know your thoughts", "Let me know what you think", "Hope you're having a great day", "What was your favorite part", "Thanks for reaching out", "Happy to help", or "Hope this helps".
   - Talk like a real, cool, authentic person on Instagram DMs. Match their language, vibe, and energy (English, casual slang, Hinglish, emojis).
   - Never use the same repetitive question structure. Vary your phrasing, tone, and perspective every time.

   - message_1_quote: The commenter's exact comment text WITHOUT artificial quotation marks or brackets (e.g. {comment_text}).
   - suggested_question: A thoughtful, high-vibe, hyper-personalized reaction and single question reacting directly to their exact words and the Reel's specific theme (< 25 words, exactly 1 question mark).
   - message_3_optional: An optional natural short human closing (e.g. "I can drop the link if you want", "That scene was wild haha"), or null.

Respond strictly in valid JSON matching this schema:
{
  "comment_intent": "EXPLICITLY_INTERESTED" | "ASKING_FOR_INFO" | "PURCHASE_INTENT" | "COLLABORATION" | "CASUAL_ENGAGEMENT" | "UNRELATED" | "UNCERTAIN",
  "dm_permission": "EXPLICIT_INVITATION" | "EXISTING_PERMISSION" | "NO_EXPLICIT_PERMISSION" | "EXPLICIT_REFUSAL",
  "decision": "ELIGIBLE" | "INTERESTED_BUT_NO_PERMISSION" | "NOT_INTERESTED" | "UNAVAILABLE" | "DO_NOT_CONTACT" | "UNCERTAIN",
  "reasoning": "Brief explanation of the decision",
  "message_1_quote": "Clean raw comment text without quotes if ELIGIBLE, otherwise null",
  "suggested_question": "Creative, highly personalized human reaction/question if ELIGIBLE, otherwise null",
  "message_3_optional": "Contextual casual human closing or null"
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
    Finite State Automata for sequencing and validating Instagram DM conversations:
    State 0 (QUOTE): Extracts and cleans the user's raw comment (no artificial quotes).
    State 1 (REACTION): Generates/validates the personalized creative reaction + single question.
    State 2 (FOLLOWUP): Evaluates optional followup with ~50% randomized frequency and zero clichés.
    State 3 (OUTPUT): Yields ordered, validated message sequence ready for fast dispatch.
    """
    FORBIDDEN_CLICHES = [
        "let me know your thoughts",
        "let me know what you think",
        "what was your favorite part",
        "hope this helps",
        "thanks for reaching out",
        "happy to help",
        "hope you're having a great day"
    ]

    @classmethod
    def process_sequence(cls, comment_text: str, data: dict, fallback_q: str = None) -> list:
        sequence = []

        # State 0: Raw Comment Quote (Natural, clean, no artificial double quotes)
        raw_msg1 = (data.get("message_1_quote") or comment_text or "").strip()
        if (raw_msg1.startswith('"') and raw_msg1.endswith('"')) or (raw_msg1.startswith("'") and raw_msg1.endswith("'")):
            raw_msg1 = raw_msg1[1:-1].strip()
        if raw_msg1:
            sequence.append(raw_msg1)

        # State 1: Creative Personalized Reaction / Question
        raw_msg2 = (data.get("suggested_question") or fallback_q or "").strip()
        if raw_msg2:
            # Enforce One-Question Rule (max 1 question mark)
            if raw_msg2.count("?") > 1:
                parts = raw_msg2.split("?")
                raw_msg2 = parts[0].strip() + "?"
            sequence.append(raw_msg2)

        # State 2: Optional Contextual Followup (Randomized ~50% frequency, filtered for zero generic clichés)
        # Allows Message 3 to be truly optional and dynamic
        if random.random() < 0.50:
            raw_msg3 = (data.get("message_3_optional") or "").strip()
            if raw_msg3 and not any(cliche in raw_msg3.lower() for cliche in cls.FORBIDDEN_CLICHES):
                if len(raw_msg3) > 3 and raw_msg3 != raw_msg2:
                    sequence.append(raw_msg3)

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
        # 1. Try Groq API if active
        if self.groq_client:
            try:
                res = await self._call_groq(user_prompt)
                if res:
                    return self._build_analysis_object(username, reel_id, comment_text, message_availability, res)
            except Exception as e:
                print(f"[AIClassifier] Groq request failed: {e}. Trying alternative LLM...")

        # 2. Try OpenRouter API if active
        if self.openrouter_client:
            try:
                res = await self._call_openrouter(user_prompt)
                if res:
                    return self._build_analysis_object(username, reel_id, comment_text, message_availability, res)
            except Exception as e:
                print(f"[AIClassifier] OpenRouter request failed: {e}. Trying Ollama...")

        # 3. Try Ollama local model if active
        if self.ollama_client:
            try:
                res = await self._call_ollama(user_prompt)
                if res:
                    return self._build_analysis_object(username, reel_id, comment_text, message_availability, res)
            except Exception as e:
                print(f"[AIClassifier] Ollama request failed: {e}. Falling back to Rule Engine...")

        # 4. Deterministic Heuristic Rule Engine (Fallback)
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
                        temperature=0.88,
                        top_p=0.95,
                        max_tokens=650
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
                            temperature=0.88,
                            top_p=0.95,
                            max_tokens=650
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
                    temperature=0.88,
                    top_p=0.95,
                    max_tokens=650
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
        response = await self.ollama_client.chat.completions.create(
            model=settings.ollama_model,
            messages=[
                {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=600
        )
        content = response.choices[0].message.content
        return json.loads(content)

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
