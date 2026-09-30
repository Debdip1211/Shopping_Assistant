"""The LLM (large language model) connection.

This is the ONLY file that knows which LLM provider we use. Everything else
calls `get_llm()` / `invoke_llm()` and never imports Hugging Face directly, so
switching providers later only means changing this file.

How it works: the model (set by LLM_MODEL, e.g. Qwen3-235B-A22B-Instruct-2507)
does NOT run on this computer.
Hugging Face "Inference Providers" are partner companies that host models on
their GPUs. We send our messages over the internet with our Hugging Face token,
a partner runs the model, and we get the reply back.

- `HuggingFaceEndpoint` describes WHICH model to call and HOW (provider, token,
  max answer length, temperature).
- `ChatHuggingFace` wraps it as a LangChain *chat model*, so we can send a
  list of messages (system / user / assistant) instead of one plain string.
"""

import logging
from functools import lru_cache

import httpx
from huggingface_hub.errors import HfHubHTTPError, InferenceTimeoutError
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint

from app.config import settings

logger = logging.getLogger(__name__)

# Low temperature = less random, more factual answers (0 = most deterministic).
TEMPERATURE = 0.2

# Friendly messages shown to the user (Section 4.1 of CLAUDE.md).
MSG_NO_ACCESS = (
    "You don't have access to this model yet. "
    "Accept the license on the model's Hugging Face page."
)
MSG_BAD_TOKEN = (
    "Your Hugging Face token is missing or invalid. "
    "Check LLM_API_KEY in backend/.env."
)
MSG_NO_CREDITS = (
    "Your Hugging Face inference credits are used up or you're being "
    "rate-limited. Check your billing page."
)
MSG_NO_PROVIDER = (
    "No inference provider currently serves this model. Try another model name."
)
MSG_BAD_ROUTING = (
    "LLM_ROUTING in backend/.env is not valid. Use cheapest, fastest, preferred, "
    "or a provider name."
)
MSG_TIMEOUT = "The AI service took too long to answer. Please try again."
MSG_NETWORK = "Couldn't reach Hugging Face. Check your internet connection."
MSG_UNKNOWN = "The AI service had a problem. Please try again."

# Words in Hugging Face error details meaning "no provider serves this model".
NO_PROVIDER_HINTS = (
    "model_not_found",
    "does not exist",
    "not supported",
    "model_not_supported",
    "no provider",
)


class LLMError(Exception):
    """An LLM failure with a message that is safe to show to the user.

    The message never contains the API token or a stack trace.
    """


def routed_model_id() -> str:
    """The model name plus the server-choice policy, e.g. "Qwen/...-2507:cheapest".

    Several companies (providers) host the same model at different prices.
    Hugging Face's router reads the ":<policy>" suffix to choose one:
    "cheapest" (lowest price), "fastest", "preferred" (your order in the HF
    settings), or a provider's name. The model itself never changes.
    """
    model, routing = settings.llm_model, settings.llm_routing
    if not routing or ":" in model:  # no policy, or one already given in LLM_MODEL
        return model
    return f"{model}:{routing}"


@lru_cache(maxsize=1)
def get_llm() -> BaseChatModel:
    """Create the chat model once and reuse it (lru_cache remembers the result).

    The API key is checked here, lazily, so the rest of the app (ingest, tests)
    works without a .env file.
    """
    if settings.llm_provider != "huggingface":
        raise LLMError(
            f"Unsupported LLM_PROVIDER {settings.llm_provider!r}. "
            "Only 'huggingface' is supported."
        )
    if not settings.llm_api_key:
        raise LLMError(MSG_BAD_TOKEN)

    endpoint = HuggingFaceEndpoint(
        repo_id=routed_model_id(),
        task="text-generation",
        # "auto" = Hugging Face picks an available partner that serves this model.
        provider="auto",
        max_new_tokens=settings.llm_max_tokens,
        temperature=TEMPERATURE,
        # Passed directly (not via environment variables) so it stays contained.
        huggingfacehub_api_token=settings.llm_api_key,
    )
    return ChatHuggingFace(llm=endpoint)


def _friendly_message(exc: Exception) -> str:
    """Translate a provider/network exception into one of the friendly messages."""
    if isinstance(exc, HfHubHTTPError):
        status = exc.response.status_code if exc.response is not None else None
        details = f"{exc} {exc.server_message or ''}".lower()
        # We always send a token, so 401 means the token itself is wrong.
        if status == 401:
            return MSG_BAD_TOKEN
        # 403 = valid token, but no permission (e.g. gated model not accepted).
        if status == 403:
            return MSG_NO_ACCESS
        # 402 = payment required (credits used up); 429 = too many requests.
        if status in (402, 429):
            return MSG_NO_CREDITS
        if "provider or policy" in details:
            return MSG_BAD_ROUTING
        # The router answers 400/404 with hints like "model_not_found" when no
        # provider serves the model (or the model name is wrong).
        if status == 404 or any(hint in details for hint in NO_PROVIDER_HINTS):
            return MSG_NO_PROVIDER
        return MSG_UNKNOWN
    if isinstance(exc, (InferenceTimeoutError, httpx.TimeoutException)):
        return MSG_TIMEOUT
    if isinstance(exc, httpx.TransportError):
        return MSG_NETWORK
    # huggingface_hub raises ValueError when it can't find a provider mapping.
    if isinstance(exc, ValueError) and "provider" in str(exc).lower():
        return MSG_NO_PROVIDER
    return MSG_UNKNOWN


def _status_of(exc: Exception) -> int | None:
    """Return the HTTP status code of an exception, if it has one (for logging)."""
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None)


def invoke_llm(messages: list[BaseMessage]) -> str:
    """Send chat messages to the LLM and return its reply text.

    Raises LLMError with a friendly message if anything goes wrong.
    """
    llm = get_llm()
    try:
        response = llm.invoke(messages)
    except Exception as exc:  # noqa: BLE001 — we translate every failure
        # Log only the error type and HTTP status: never the token or full details.
        logger.warning(
            "LLM call failed: %s (HTTP status: %s)",
            type(exc).__name__,
            _status_of(exc),
        )
        raise LLMError(_friendly_message(exc)) from None
    return str(response.content).strip()
