"""Central configuration for the backend.

Every setting is read from environment variables (loaded from backend/.env if
that file exists) and exposed through ONE typed `settings` object. Other
modules import `settings` from here instead of hardcoding values, so changing
behaviour (e.g. chunk size) only ever means editing .env.

Every setting has a default, so the app and the tests work even with no .env
file at all. The LLM API key is the one exception: it is checked lazily, only
when the LLM is actually created (see app/rag/llm.py).
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# backend/ folder (this file is backend/app/config.py). Used so that paths work
# no matter which directory you start Python from.
BACKEND_DIR = Path(__file__).resolve().parent.parent

# Load backend/.env into os.environ. Missing file is fine (defaults are used).
load_dotenv(BACKEND_DIR / ".env")


class ConfigError(Exception):
    """Raised when a setting in .env has an invalid value."""


def _get_str(name: str, default: str) -> str:
    """Read a string setting, falling back to `default` if unset or blank."""
    value = os.getenv(name, "").strip()
    return value or default


def _get_int(name: str, default: int) -> int:
    """Read a positive integer setting, with a clear error if it isn't one."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number, got {raw!r}.") from None
    if value < 0:
        raise ConfigError(f"{name} must not be negative, got {value}.")
    return value


def _get_path(name: str, default: str) -> Path:
    """Read a path setting; relative paths are resolved against backend/."""
    path = Path(_get_str(name, default))
    return path if path.is_absolute() else (BACKEND_DIR / path).resolve()


@dataclass(frozen=True)
class Settings:
    """All configuration values, with types. `frozen` makes them read-only."""

    # LLM
    llm_provider: str
    llm_model: str
    llm_api_key: str | None  # optional here; validated in get_llm()
    llm_max_tokens: int
    llm_routing: str  # which provider runs the model: "cheapest", "fastest", ...

    # Embeddings
    embedding_model: str

    # Modes and chunking
    full_context_char_limit: int
    chunk_size: int
    chunk_overlap: int

    # Retrieval
    current_top_k: int
    per_product_k: int
    max_compare_products: int

    # Limits
    max_history_messages: int
    max_product_chars: int

    # Storage
    data_dir: Path


def load_settings() -> Settings:
    """Build a Settings object from environment variables and defaults."""
    settings = Settings(
        llm_provider=_get_str("LLM_PROVIDER", "huggingface").lower(),
        llm_model=_get_str("LLM_MODEL", "Qwen/Qwen3-235B-A22B-Instruct-2507"),
        llm_api_key=os.getenv("LLM_API_KEY", "").strip() or None,
        llm_max_tokens=_get_int("LLM_MAX_TOKENS", 512),
        llm_routing=_get_str("LLM_ROUTING", "cheapest"),
        embedding_model=_get_str(
            "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        ),
        full_context_char_limit=_get_int("FULL_CONTEXT_CHAR_LIMIT", 12000),
        chunk_size=_get_int("CHUNK_SIZE", 800),
        chunk_overlap=_get_int("CHUNK_OVERLAP", 100),
        current_top_k=_get_int("CURRENT_TOP_K", 5),
        per_product_k=_get_int("PER_PRODUCT_K", 2),
        max_compare_products=_get_int("MAX_COMPARE_PRODUCTS", 8),
        max_history_messages=_get_int("MAX_HISTORY_MESSAGES", 6),
        max_product_chars=_get_int("MAX_PRODUCT_CHARS", 300000),
        data_dir=_get_path("DATA_DIR", "./data"),
    )
    if settings.chunk_overlap >= settings.chunk_size:
        raise ConfigError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE.")
    return settings


# The single shared settings object. Import it with:
#     from app.config import settings
settings = load_settings()
