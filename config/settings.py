import os
import re
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
CHROME_PROFILE_DIR = SESSION_DATA_DIR / "chrome_profile"

# Ensure directories exist
for d in [SESSION_DATA_DIR, SCREENSHOTS_DIR, REEL_SCREENSHOTS_DIR, PROFILE_SCREENSHOTS_DIR, CHROME_PROFILE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Load .env file
load_dotenv(BASE_DIR / ".env")

def _load_credentials():
    ig_user = os.getenv("INSTAGRAM_USERNAME", "").strip()
    ig_pass = os.getenv("INSTAGRAM_PASSWORD", "").strip()
    g_email = os.getenv("GOOGLE_EMAIL", "").strip() or os.getenv("GMAIL", "").strip()
    g_pass = os.getenv("GOOGLE_PASSWORD", "").strip()

    env_file = BASE_DIR / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                lower = line.lower()
                parts = re.split(r"[:=]", line, maxsplit=1)
                if len(parts) == 2:
                    k = parts[0].strip().lower()
                    v = parts[1].strip()
                    if ("instagram_username" in k or k == "username") and not ig_user:
                        ig_user = v
                    elif ("instagram_password" in k or k == "instagram_pass") and not ig_pass:
                        ig_pass = v
                    elif ("google_email" in k or "gmail" in k or k == "email") and not g_email:
                        g_email = v
                    elif ("google_password" in k or "google_pass" in k) and not g_pass:
                        g_pass = v
                    elif k == "password" and not ig_pass:
                        ig_pass = v

    return ig_user, ig_pass, g_email, g_pass

_ig_user, _ig_pass, _g_email, _g_pass = _load_credentials()

class AgentSettings(BaseModel):
    # Instagram Credentials for auto-login
    instagram_username: str = Field(default=_ig_user)
    instagram_password: str = Field(default=_ig_pass)

    # Google / Chrome Profile Credentials
    google_email: str = Field(default=_g_email)
    google_password: str = Field(default=_g_pass)
    chrome_profile_directory: str = Field(default=os.getenv("CHROME_PROFILE_DIRECTORY", "Default"))

    # Chrome CDP settings
    chrome_cdp_url: str = Field(default=os.getenv("CHROME_CDP_URL", "http://127.0.0.1:9222"))
    chrome_user_data_dir: Path = Field(default=CHROME_PROFILE_DIR)
    reel_cooldown_seconds: float = Field(default=float(os.getenv("REEL_COOLDOWN_SECONDS", "3.5")))
    navigation_mode: str = Field(default=os.getenv("NAVIGATION_MODE", "in_tab"))  # in_tab or new_tab
    eligibility_mode: str = Field(default=os.getenv("ELIGIBILITY_MODE", "engaged"))  # engaged or strict

    # Primary LLM: Groq API
    groq_api_key: str = Field(default=os.getenv("GROQ_API_KEY", ""))
    groq_model: str = Field(default=os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b"))
    groq_fallback_models: list = Field(default=[
        "qwen/qwen3.8-27b",
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "allam-2-7b",
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant"
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
