import os
import json
from pathlib import Path
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
SESSION_DATA_DIR = BASE_DIR / "session_data"
SCREENSHOTS_DIR = SESSION_DATA_DIR / "screenshots"
REEL_SCREENSHOTS_DIR = SCREENSHOTS_DIR / "reels"
PROFILE_SCREENSHOTS_DIR = SCREENSHOTS_DIR / "profiles"

# Ensure directories exist
for d in [SESSION_DATA_DIR, SCREENSHOTS_DIR, REEL_SCREENSHOTS_DIR, PROFILE_SCREENSHOTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Load .env file
load_dotenv(BASE_DIR / ".env")

class AgentSettings(BaseModel):
    # Chrome CDP settings
    chrome_cdp_url: str = Field(default=os.getenv("CHROME_CDP_URL", "http://127.0.0.1:9222"))
    reel_cooldown_seconds: float = Field(default=float(os.getenv("REEL_COOLDOWN_SECONDS", "15.0")))
    navigation_mode: str = Field(default=os.getenv("NAVIGATION_MODE", "in_tab"))  # in_tab or new_tab

    # Primary LLM: Groq API
    groq_api_key: str = Field(default=os.getenv("GROQ_API_KEY", ""))
    groq_model: str = Field(default=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"))

    # Fallback LLM: Local Ollama
    ollama_enabled: bool = Field(default=os.getenv("OLLAMA_ENABLED", "false").lower() == "true")
    ollama_base_url: str = Field(default=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    ollama_model: str = Field(default=os.getenv("OLLAMA_MODEL", "llama3:latest"))

    # Safety limits
    human_in_the_loop: bool = Field(default=os.getenv("HUMAN_IN_THE_LOOP", "true").lower() == "true")
    auto_send_dm: bool = Field(default=os.getenv("AUTO_SEND_DM", "false").lower() == "true")
    max_comments_per_reel: int = Field(default=int(os.getenv("MAX_COMMENTS_PER_REEL", "25")))
    max_profiles_per_session: int = Field(default=int(os.getenv("MAX_PROFILES_PER_SESSION", "100")))

    # Timing and jitter
    min_action_delay: float = 1.5
    max_action_delay: float = 3.8
    page_load_timeout: float = 20000  # ms

    # Selector storage
    selectors_file: Path = CONFIG_DIR / "selectors.json"

    def load_selectors(self) -> dict:
        if self.selectors_file.exists():
            with open(self.selectors_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

settings = AgentSettings()
