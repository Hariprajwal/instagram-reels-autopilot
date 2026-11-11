import asyncio
from typing import Optional
from models.schemas import (
    CommentData,
    ProfileData,
    ReelContext,
    ProspectAnalysis,
    DecisionClassification,
    MessageAvailability,
    DMPermission
)
from models.classifier import AIClassifier
from storage.session_logger import SessionLogger
from storage.state_manager import StateManager

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
        Strictly distinguishes technical message availability from explicit DM permission.
        """
        print(f"\n[DecisionEngine] Evaluating commenter @{comment.username}...")

        # If profile was inaccessible
        if not profile.is_accessible:
            analysis = ProspectAnalysis(
                username=comment.username,
                reel_id=reel_context.reel_id,
                comment_text=comment.text,
                comment_intent=self.classifier._rule_based_fallback(comment.text, reel_context.caption, profile.message_availability, profile.is_private)["comment_intent"],
                message_availability=MessageAvailability.PROFILE_INACCESSIBLE,
                dm_permission=DMPermission.NO_EXPLICIT_PERMISSION,
                decision=DecisionClassification.UNAVAILABLE,
                reasoning="Profile could not be accessed or loaded.",
                suggested_question=None
            )
            self._record_and_save(analysis, comment.username, reel_context.reel_id)
            return analysis

        # Run AI Classifier (Groq -> Ollama -> Rule Engine)
        analysis = await self.classifier.analyze(
            username=comment.username,
            reel_id=reel_context.reel_id,
            reel_caption=reel_context.caption,
            comment_text=comment.text,
            is_private=profile.is_private,
            message_availability=profile.message_availability,
            bio_text=profile.bio_text
        )

        # Safety override: If message button is NOT visible, it CANNOT be ELIGIBLE
        if profile.message_availability != MessageAvailability.MESSAGE_BUTTON_VISIBLE:
            if analysis.decision == DecisionClassification.ELIGIBLE:
                print(f"[DecisionEngine] Safety Gate: Overriding ELIGIBLE -> UNAVAILABLE because Message button is not visible.")
                analysis.decision = DecisionClassification.UNAVAILABLE
                analysis.reasoning += " (Overridden: Message option unavailable on profile)."
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

