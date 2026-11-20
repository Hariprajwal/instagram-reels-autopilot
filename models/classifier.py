import os
import re
import json
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

ANALYSIS_SYSTEM_PROMPT = """You are an expert Instagram analyst and lead investigator.
Your job is to inspect an Instagram Reel comment and the commenter's profile to evaluate:
1. Comment Intent: (EXPLICITLY_INTERESTED, ASKING_FOR_INFO, PURCHASE_INTENT, COLLABORATION, CASUAL_ENGAGEMENT, UNRELATED, UNCERTAIN)
2. Explicit DM Permission: (EXPLICIT_INVITATION, EXISTING_PERMISSION, NO_EXPLICIT_PERMISSION, EXPLICIT_REFUSAL)
   CRITICAL: You must NEVER assume a positive or interested comment welcomes a DM. Only comments explicitly asking to be messaged (e.g. "DM me", "send info to my DM", "check inbox") qualify as EXPLICIT_INVITATION.
3. Decision:
   - ELIGIBLE: The commenter explicitly welcomes a private message, messaging is technically available, and the platform permits the interaction.
   - INTERESTED_BUT_NO_PERMISSION: The commenter appears interested but has NOT explicitly invited a DM.
   - NOT_INTERESTED: Casual engagement, generic praise, emojis, or unrelated chat.
   - UNAVAILABLE: Profile or messaging option cannot be accessed.
   - DO_NOT_CONTACT: The person refuses messages or has opted out.
   - UNCERTAIN: Insufficient evidence.
4. One-Question Rule (ONLY if ELIGIBLE):
   - Re-read the original comment and consider the Reel context.
   - Formulate ONE natural, personalized question matching what they mentioned.
   - Keep it concise (< 25 words).
   - Avoid generic marketing messages.
   - Never send multiple questions (exactly 1 question mark).

Respond strictly in valid JSON matching this schema:
{
  "comment_intent": "EXPLICITLY_INTERESTED" | "ASKING_FOR_INFO" | "PURCHASE_INTENT" | "COLLABORATION" | "CASUAL_ENGAGEMENT" | "UNRELATED" | "UNCERTAIN",
  "dm_permission": "EXPLICIT_INVITATION" | "EXISTING_PERMISSION" | "NO_EXPLICIT_PERMISSION" | "EXPLICIT_REFUSAL",
  "decision": "ELIGIBLE" | "INTERESTED_BUT_NO_PERMISSION" | "NOT_INTERESTED" | "UNAVAILABLE" | "DO_NOT_CONTACT" | "UNCERTAIN",
  "reasoning": "Brief explanation of the decision",
  "suggested_question": "One concise question if ELIGIBLE, otherwise null"
}
"""

class AIClassifier:
    def __init__(self):
        self.groq_client: Optional[Any] = None
        self.ollama_client: Optional[Any] = None
        self._init_clients()

    def _init_clients(self):
        # 1. Initialize Groq client only if API key is provided
        if settings.groq_api_key and settings.groq_api_key.strip():
            try:
                import httpx
                from openai import AsyncOpenAI
                http_client = httpx.AsyncClient(trust_env=False, timeout=5.0)
                self.groq_client = AsyncOpenAI(
                    base_url="https://api.groq.com/openai/v1",
                    api_key=settings.groq_api_key.strip(),
                    http_client=http_client,
                    max_retries=1
                )
                print("[AIClassifier] Groq client initialized successfully.")
            except Exception as e:
                print(f"[AIClassifier] Error initializing Groq client: {e}")

        # 2. Initialize Ollama client only if explicitly enabled
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
                print(f"[AIClassifier] Groq request failed: {e}. Falling back...")

        # 2. Try Ollama local model if active
        if self.ollama_client:
            try:
                res = await self._call_ollama(user_prompt)
                if res:
                    return self._build_analysis_object(username, reel_id, comment_text, message_availability, res)
            except Exception as e:
                print(f"[AIClassifier] Ollama request failed: {e}. Falling back to Rule Engine...")

        # 3. Deterministic Heuristic Rule Engine (Fallback)
        res = self._rule_based_fallback(
            comment_text=comment_text,
            reel_caption=reel_caption,
            message_availability=message_availability,
            is_private=is_private
        )
        return self._build_analysis_object(username, reel_id, comment_text, message_availability, res)

    async def _call_groq(self, prompt: str) -> Optional[dict]:
        response = await self.groq_client.chat.completions.create(
            model=settings.groq_model,
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

        # Check explicit refusals first
        refusal_patterns = [r"don't dm", r"dont dm", r"no dms", r"stop messaging", r"spam", r"leave me alone"]
        if any(re.search(p, text) for p in refusal_patterns):
            return {
                "comment_intent": CommentIntent.UNRELATED.value,
                "dm_permission": DMPermission.EXPLICIT_REFUSAL.value,
                "decision": DecisionClassification.DO_NOT_CONTACT.value,
                "reasoning": "Commenter explicitly refused direct messages or asked not to be contacted.",
                "suggested_question": None
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
        elif has_explicit_dm_invite and is_msg_possible:
            decision = DecisionClassification.ELIGIBLE.value
            permission = DMPermission.EXPLICIT_INVITATION.value
            reasoning = "User explicitly requested a DM and messaging is technically available."
            question = self._generate_fallback_question(comment_text, reel_caption)
        elif is_msg_possible and mode == "engaged":
            # Growth / Engaged Lead Mode: Profile has open DM and commenter actively engaged with the Reel
            decision = DecisionClassification.ELIGIBLE.value
            permission = DMPermission.EXISTING_PERMISSION.value
            reasoning = f"Profile allows direct messaging and user actively engaged with comment: '{comment_text[:40]}'."
            question = self._generate_fallback_question(comment_text, reel_caption)
        elif has_info_intent:
            decision = DecisionClassification.INTERESTED_BUT_NO_PERMISSION.value
            reasoning = "User expressed interest or asked a question, but did not explicitly invite a DM."
            question = None
        else:
            decision = DecisionClassification.NOT_INTERESTED.value
            reasoning = "Casual comment or no explicit DM permission found."
            question = None

        return {
            "comment_intent": intent,
            "dm_permission": permission,
            "decision": decision,
            "reasoning": reasoning,
            "suggested_question": question
        }

    def _generate_fallback_question(self, comment_text: str, reel_caption: Optional[str]) -> str:
        text = comment_text.lower()
        if "price" in text or "cost" in text or "how much" in text or "kitna" in text:
            return "Hey! Happy to share the pricing—are you looking for individual or team options?"
        if "link" in text or "bhejo" in text:
            return "Hey! Glad you reached out—would you like me to send over the direct resource link?"
        if "how" in text or "details" in text or "info" in text or "kaise" in text:
            return "Hey! Happy to share more details—what specific part can I help clarify for you?"
        if any(w in text for w in ["kr liya", "kar liya", "done", "tried", "maine"]):
            return "Hey! Saw you tried this out—how was your experience with it?"
        if any(w in text for w in ["god", "😂", "lol", "kya", "can you", "tum kar", "sakte"]):
            return "Haha love your comment on the Reel! Have you tried doing this yourself?"
        return "Hey! Thanks for engaging with the Reel—what was your favorite part about it?"

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
        if decision != DecisionClassification.ELIGIBLE:
            question = None
        elif question:
            # Enforce One-Question Rule
            if question.count("?") > 1:
                parts = question.split("?")
                question = parts[0].strip() + "?"

        return ProspectAnalysis(
            username=username,
            reel_id=reel_id,
            comment_text=comment_text,
            comment_intent=intent,
            message_availability=message_availability,
            dm_permission=permission,
            decision=decision,
            reasoning=data.get("reasoning", ""),
            suggested_question=question
        )
