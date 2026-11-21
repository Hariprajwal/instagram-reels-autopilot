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
    # Chrome profile dir used when auto-launching with --remote-debugging-port=9222
    chrome_user_data_dir: Path = Field(default=SESSION_DATA_DIR / "chrome_profile")
    chrome_profile_directory: str = Field(default=os.getenv("CHROME_PROFILE_DIRECTORY", "Default"))

    reel_cooldown_seconds: float = Field(default=float(os.getenv("REEL_COOLDOWN_SECONDS", "3.5")))
    navigation_mode: str = Field(default=os.getenv("NAVIGATION_MODE", "in_tab"))  # in_tab or new_tab
    eligibility_mode: str = Field(default=os.getenv("ELIGIBILITY_MODE", "engaged"))  # engaged or strict

    # Instagram credentials (for auto-login if login screen appears)
    instagram_username: str = Field(default=os.getenv("INSTAGRAM_USERNAME", ""))
    instagram_password: str = Field(default=os.getenv("INSTAGRAM_PASSWORD", ""))

    # Google account (for Chrome sign-in if needed)
    google_email: str = Field(default=os.getenv("GOOGLE_EMAIL", ""))
    google_password: str = Field(default=os.getenv("GOOGLE_PASSWORD", ""))

    # Primary LLM: Groq API
    groq_api_key: str = Field(default=os.getenv("GROQ_API_KEY", ""))
    groq_model: str = Field(default=os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b"))
    groq_fallback_models: list = Field(default=[
        "qwen/qwen3.8-27b",
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
        "allam-2-7b",
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "meta-llama/llama-4-maverick-17b-128e-instruct",
        "llama-3.1-8b-instant",
        "gemma2-9b-it",
    ])

    # Alternative LLM: OpenRouter API
    openrouter_api_key: str = Field(default=os.getenv("OPENROUTER_API_KEY", ""))
    openrouter_model: str = Field(default=os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct"))
    openrouter_base_url: str = Field(default=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"))

    # Fallback LLM: Local Ollama
    ollama_enabled: bool = Field(default=os.getenv("OLLAMA_ENABLED", "false").lower() == "true")
    ollama_base_url: str = Field(default=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    ollama_model: str = Field(default=os.getenv("OLLAMA_MODEL", "llama3:latest"))

    # Navigation Controls
    auto_next_reel: bool = Field(default=os.getenv("AUTO_NEXT_REEL", "true").lower() == "true")
    cleanup_screenshots_on_exit: bool = Field(default=os.getenv("CLEANUP_SCREENSHOTS_ON_EXIT", "true").lower() == "true")
    save_profile_screenshots: bool = Field(default=os.getenv("SAVE_PROFILE_SCREENSHOTS", "false").lower() == "true")

    # Safety limits
    human_in_the_loop: bool = Field(default=os.getenv("HUMAN_IN_THE_LOOP", "true").lower() == "true")
    auto_send_dm: bool = Field(default=os.getenv("AUTO_SEND_DM", "true").lower() == "true")
    max_comments_per_reel: int = Field(default=int(os.getenv("MAX_COMMENTS_PER_REEL", "25")))
    max_profiles_per_session: int = Field(default=int(os.getenv("MAX_PROFILES_PER_SESSION", "100")))

    # Timing and jitter (human-like pacing)
    min_action_delay: float = Field(default=float(os.getenv("MIN_ACTION_DELAY", "2.8")))
    max_action_delay: float = Field(default=float(os.getenv("MAX_ACTION_DELAY", "5.5")))
    page_load_timeout: float = 20000  # ms

    # Selector storage
    selectors_file: Path = CONFIG_DIR / "selectors.json"

    def load_selectors(self) -> dict:
        if self.selectors_file.exists():
            with open(self.selectors_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

settings = AgentSettings()
