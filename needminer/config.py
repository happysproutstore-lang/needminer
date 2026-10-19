"""All configuration comes from environment variables (see .env.example).

Nothing here is required for the default run: App Store, Hacker News and Stack Exchange
are queried without keys. Only the optional LLM grouping needs GEMINI_API_KEY.
"""

import os
from dataclasses import dataclass, field


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    user_agent: str = field(default_factory=lambda: os.environ.get(
        "NEEDMINER_USER_AGENT", "needminer/0.1 (open-source market research CLI)"))
    http_timeout: int = field(default_factory=lambda: _env_int("NEEDMINER_HTTP_TIMEOUT", 20))
    output_dir: str = field(default_factory=lambda: os.environ.get("NEEDMINER_OUTPUT_DIR", "reports"))
    # Optional LLM grouping (off by default).
    llm_enabled: bool = field(default_factory=lambda: _env_bool("NEEDMINER_LLM", False))
    gemini_api_key: str = field(default_factory=lambda: os.environ.get("GEMINI_API_KEY", ""))
    # flash-lite does not spend "thinking" tokens on short classification prompts (cheapest option).
    gemini_model: str = field(default_factory=lambda: os.environ.get(
        "NEEDMINER_GEMINI_MODEL", "gemini-flash-lite-latest"))
    # Optional Stack Exchange app key: raises the anonymous quota (300 requests/day/IP).
    stackexchange_key: str = field(default_factory=lambda: os.environ.get("STACKEXCHANGE_KEY", ""))
    # Google Trends cooldown state file (after an HTTP 429 no Trends request is sent for N hours).
    trends_state_file: str = field(default_factory=lambda: os.environ.get(
        "NEEDMINER_TRENDS_STATE", os.path.join(".cache", "trends_429.json")))
    trends_cooldown_hours: int = field(default_factory=lambda: _env_int("NEEDMINER_TRENDS_COOLDOWN_HOURS", 6))


def load_settings() -> Settings:
    return Settings()


def http_headers(settings: Settings = None) -> dict:
    return {"User-Agent": (settings or load_settings()).user_agent}
