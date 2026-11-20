import json
import csv
from pathlib import Path
from datetime import datetime
from typing import List, Optional
from config.settings import SESSION_DATA_DIR
from models.schemas import SessionStats, ProspectAnalysis, DecisionClassification

class SessionLogger:
    def __init__(self, session_dir: Path = SESSION_DATA_DIR):
        self.session_dir = session_dir
        self.stats = SessionStats()
        self.prospects: List[ProspectAnalysis] = []
        self.report_file = self.session_dir / "session_report.json"
        self.csv_file = self.session_dir / "session_leads.csv"
        self.messages_file = self.session_dir / "messages_sent.csv"
        self.queue_file = self.session_dir / "queue.json"
        self._init_csv()
        self.load_queue()

    def _init_csv(self):
        if not self.csv_file.exists():
            with open(self.csv_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Timestamp", "Reel ID", "Reel URL", "Username", "Profile URL",
                    "Comment", "Intent", "Message Available", "DM Permission",
                    "Decision", "Reasoning", "Suggested Question", "Approved"
                ])

        if not self.messages_file.exists():
            with open(self.messages_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Timestamp", "Reel ID", "Reel URL", "Username", "Profile URL",
                    "Original Comment", "Message 1 (Quote)", "Message 2 (Reaction/Question)",
                    "Message 3 (Followup)", "Status"
                ])

    def record_reel_inspected(self):
        self.stats.reels_inspected += 1
        self.stats.last_updated = datetime.now()
        self.save_report()

    def record_comment_read(self):
        self.stats.comments_read += 1
        self.stats.last_updated = datetime.now()

    def record_profile_opened(self, has_message_btn: bool = False, is_unavailable: bool = False):
        self.stats.profiles_opened += 1
        if has_message_btn:
            self.stats.profiles_with_message_buttons += 1
        if is_unavailable:
            self.stats.unavailable_profiles += 1
        self.stats.last_updated = datetime.now()

    def record_analysis(self, analysis: ProspectAnalysis, reel_url: Optional[str] = None):
        self.prospects.append(analysis)

        # Update stats
        if analysis.decision == DecisionClassification.ELIGIBLE:
            self.stats.eligible_conversations += 1
            if analysis.suggested_question:
                self.stats.questions_prepared += 1
            self.add_to_queue(analysis)
        elif analysis.decision == DecisionClassification.INTERESTED_BUT_NO_PERMISSION:
            self.stats.interested_without_dm_permission += 1
        elif analysis.decision == DecisionClassification.DO_NOT_CONTACT:
            self.stats.do_not_contact_profiles += 1
        elif analysis.decision == DecisionClassification.UNAVAILABLE:
            self.stats.unavailable_profiles += 1

        if analysis.dm_permission.value == "EXPLICIT_INVITATION":
            self.stats.explicit_dm_invitations += 1

        self.stats.last_updated = datetime.now()

        # Construct full Instagram profile and Reel URLs
        profile_url = f"https://www.instagram.com/{analysis.username}/"
        final_reel_url = reel_url or f"https://www.instagram.com/reel/{analysis.reel_id}/"

        # Append to CSV
        with open(self.csv_file, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                analysis.analyzed_at.strftime("%Y-%m-%d %H:%M:%S"),
                analysis.reel_id,
                final_reel_url,
                analysis.username,
                profile_url,
                analysis.comment_text,
                analysis.comment_intent.value,
                analysis.message_availability.value,
                analysis.dm_permission.value,
                analysis.decision.value,
                analysis.reasoning,
                analysis.suggested_question or "",
                "YES" if analysis.approved_by_user else "NO"
            ])

        self.save_report()

    def record_message_sent(
        self,
        reel_id: str,
        reel_url: str,
        username: str,
        comment_text: str,
        messages: List[str],
        status: str = "DELIVERED"
    ):
        """Dedicated log for all multi-message sequences dispatched to Instagram users."""
        profile_url = f"https://www.instagram.com/{username}/"
        final_reel_url = reel_url if "http" in reel_url else f"https://www.instagram.com/reel/{reel_id}/"

        msg1 = messages[0] if len(messages) > 0 else ""
        msg2 = messages[1] if len(messages) > 1 else ""
        msg3 = messages[2] if len(messages) > 2 else ""

        with open(self.messages_file, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                reel_id,
                final_reel_url,
                username,
                profile_url,
                comment_text,
                msg1,
                msg2,
                msg3,
                status
            ])
        print(f"[SessionLogger] Logged message sequence to: {self.messages_file.name}")

    def cleanup_screenshots(self):
        """Cleans up temporary screenshot image files on session completion to save disk space."""
        cleaned_count = 0
        for sub in ["reels", "profiles"]:
            sub_dir = self.session_dir / "screenshots" / sub
            if sub_dir.exists():
                for p in sub_dir.glob("*.png"):
                    try:
                        p.unlink()
                        cleaned_count += 1
                    except Exception:
                        pass
        if cleaned_count > 0:
            print(f"[SessionLogger] Cleaned up {cleaned_count} temporary screenshots to free disk space.")

    def save_report(self):
        try:
            report_data = {
                "stats": self.stats.model_dump(mode="json"),
                "total_prospects_logged": len(self.prospects)
            }
            with open(self.report_file, "w", encoding="utf-8") as f:
                json.dump(report_data, f, indent=2)
        except Exception as e:
            print(f"[SessionLogger] Warning: Could not save report: {e}")

    def add_to_queue(self, analysis: ProspectAnalysis):
        queue = self.load_queue()
        queue.append(analysis.model_dump(mode="json"))
        try:
            with open(self.queue_file, "w", encoding="utf-8") as f:
                json.dump(queue, f, indent=2)
        except Exception as e:
            print(f"[SessionLogger] Warning: Could not save queue: {e}")

    def load_queue(self) -> list:
        if self.queue_file.exists():
            try:
                with open(self.queue_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

