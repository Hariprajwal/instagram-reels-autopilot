import asyncio
from typing import Optional
from models.schemas import (
    CommentData,
    ProfileData,
    ReelContext,
    ProspectAnalysis,
    DecisionClassification,
    MessageAvailability,
    DMPermission,
    CommentIntent
)
from models.classifier import AIClassifier, is_self_promo_or_spam
from storage.session_logger import SessionLogger
from storage.state_manager import StateManager
from config.settings import settings

class DecisionEngine:
    def __init__(self, session_logger: SessionLogger, state_manager: StateManager):
        self.session_logger = session_logger
        self.state_manager = state_manager
        self.classifier = AIClassifier()

    async def evaluate_commenter(
        self,
        comment: CommentData,
        profile: ProfileData,
        reel_context: ReelContext
    ) -> ProspectAnalysis:
        """
        Runs comprehensive evaluation on the commenter's comment and profile.

        ELIGIBILITY_MODE = "engaged" (default):
            ANY commenter with a visible Message button is ELIGIBLE — period.
            The LLM is only used to generate the personalized message sequence.
            It CANNOT veto the ELIGIBLE decision in engaged mode.

        ELIGIBILITY_MODE = "strict":
            Only commenters who explicitly invite a DM (e.g. "DM me", "send info") are ELIGIBLE.
            The LLM's decision is respected as-is.
        """
        print(f"\n[DecisionEngine] Evaluating commenter @{comment.username}...")

        # If profile was inaccessible
        if not profile.is_accessible:
            analysis = ProspectAnalysis(
                username=comment.username,
                reel_id=reel_context.reel_id,
                comment_text=comment.text,
                comment_intent=CommentIntent.UNCERTAIN,
                message_availability=MessageAvailability.PROFILE_INACCESSIBLE,
                dm_permission=DMPermission.NO_EXPLICIT_PERMISSION,
                decision=DecisionClassification.UNAVAILABLE,
                reasoning="Profile could not be accessed or loaded.",
                suggested_question=None
            )
            self._record_and_save(analysis, comment.username, reel_context.reel_id)
            return analysis

        mode = getattr(settings, "eligibility_mode", "engaged").lower()
        msg_visible = (profile.message_availability == MessageAvailability.MESSAGE_BUTTON_VISIBLE)

        # === HARD GATE 1: Message button not visible → always UNAVAILABLE ===
        if not msg_visible:
            analysis = ProspectAnalysis(
                username=comment.username,
                reel_id=reel_context.reel_id,
                comment_text=comment.text,
                comment_intent=CommentIntent.UNCERTAIN,
                message_availability=profile.message_availability,
                dm_permission=DMPermission.NO_EXPLICIT_PERMISSION,
                decision=DecisionClassification.UNAVAILABLE,
                reasoning="Message button not visible on this profile.",
                suggested_question=None
            )
            self._record_and_save(analysis, comment.username, reel_context.reel_id)
            return analysis

        # === HARD GATE 2: Self-promo / spam → always skip ===
        is_spam, spam_reason = is_self_promo_or_spam(comment.text)
        if is_spam:
            analysis = ProspectAnalysis(
                username=comment.username,
                reel_id=reel_context.reel_id,
                comment_text=comment.text,
                comment_intent=CommentIntent.UNRELATED,
                message_availability=profile.message_availability,
                dm_permission=DMPermission.NO_EXPLICIT_PERMISSION,
                decision=DecisionClassification.NOT_INTERESTED,
                reasoning=f"Self-promotional spam / engagement bait ({spam_reason}).",
                suggested_question=None
            )
            self._record_and_save(analysis, comment.username, reel_context.reel_id)
            return analysis

        # === ENGAGED MODE: Message button visible + not spam = ELIGIBLE, use LLM only for messages ===
        if mode == "engaged":
            # Still call LLM to generate the message sequence, but FORCE decision = ELIGIBLE
            analysis = await self.classifier.analyze(
                username=comment.username,
                reel_id=reel_context.reel_id,
                reel_caption=reel_context.caption,
                comment_text=comment.text,
                is_private=profile.is_private,
                message_availability=profile.message_availability,
                bio_text=profile.bio_text
            )

            # === OVERRIDE: Engaged mode forces ELIGIBLE when msg button is visible ===
            if analysis.decision != DecisionClassification.DO_NOT_CONTACT:
                if analysis.decision != DecisionClassification.ELIGIBLE:
                    print(f"[DecisionEngine] ✓ Engaged-mode override: {analysis.decision.value} → ELIGIBLE (msg button visible, not spam).")
                    analysis.decision = DecisionClassification.ELIGIBLE
                    analysis.dm_permission = DMPermission.EXISTING_PERMISSION
                    analysis.reasoning += " [Engaged mode: message button visible → auto-ELIGIBLE]"

                    # Generate message sequence if LLM didn't produce one
                    if not analysis.message_sequence or len(analysis.message_sequence) < 2:
                        rule_res = self.classifier._rule_based_fallback(
                            comment_text=comment.text,
                            reel_caption=reel_context.caption,
                            message_availability=profile.message_availability,
                            is_private=profile.is_private
                        )
                        from models.classifier import MessageSequenceAutomata
                        analysis.message_sequence = MessageSequenceAutomata.process_sequence(
                            comment_text=comment.text,
                            data=rule_res,
                            fallback_q=rule_res.get("suggested_question")
                        )
                        analysis.suggested_question = analysis.message_sequence[1] if len(analysis.message_sequence) > 1 else rule_res.get("suggested_question")

            self._record_and_save(analysis, comment.username, reel_context.reel_id)
            return analysis

        # === STRICT MODE: Trust the LLM decision fully ===
        analysis = await self.classifier.analyze(
            username=comment.username,
            reel_id=reel_context.reel_id,
            reel_caption=reel_context.caption,
            comment_text=comment.text,
            is_private=profile.is_private,
            message_availability=profile.message_availability,
            bio_text=profile.bio_text
        )

        # Safety override: If message button is NOT visible, cannot be ELIGIBLE (double-check)
        if not msg_visible and analysis.decision == DecisionClassification.ELIGIBLE:
            print(f"[DecisionEngine] Safety Gate: Overriding ELIGIBLE → UNAVAILABLE (no message button).")
            analysis.decision = DecisionClassification.UNAVAILABLE
            analysis.reasoning += " (Overridden: Message option unavailable)."
            analysis.suggested_question = None

        self._record_and_save(analysis, comment.username, reel_context.reel_id)
        return analysis

    def _record_and_save(self, analysis: ProspectAnalysis, username: str, reel_id: str):
        self.session_logger.record_analysis(analysis)
        self.state_manager.mark_user_processed(
            username=username,
            reel_id=reel_id,
            decision=analysis.decision.value,
            notes=analysis.reasoning
        )

