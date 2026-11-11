import json
from pathlib import Path
from typing import Set, Dict
from config.settings import SESSION_DATA_DIR

class StateManager:
    def __init__(self, cache_file: Path = SESSION_DATA_DIR / "processed_cache.json"):
        self.cache_file = cache_file
        self.processed_users: Set[str] = set()
        self.processed_reels: Set[str] = set()
        self.user_history: Dict[str, dict] = {}
        self.load()

    def load(self):
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.processed_users = set(data.get("processed_users", []))
                    self.processed_reels = set(data.get("processed_reels", []))
                    self.user_history = data.get("user_history", {})
            except Exception as e:
                print(f"[StateManager] Warning: Could not load cache: {e}")

    def save(self):
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump({
                    "processed_users": list(self.processed_users),
                    "processed_reels": list(self.processed_reels),
                    "user_history": self.user_history
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[StateManager] Warning: Could not save cache: {e}")

    def is_user_processed(self, username: str) -> bool:
        clean_user = username.strip().lstrip("@").lower()
        return clean_user in self.processed_users

    def mark_user_processed(self, username: str, reel_id: str, decision: str, notes: str = ""):
        clean_user = username.strip().lstrip("@").lower()
        self.processed_users.add(clean_user)
        self.user_history[clean_user] = {
            "reel_id": reel_id,
            "decision": decision,
            "notes": notes
        }
        self.save()

    def is_reel_processed(self, reel_id: str) -> bool:
        return reel_id in self.processed_reels

    def mark_reel_processed(self, reel_id: str):
        self.processed_reels.add(reel_id)
        self.save()

