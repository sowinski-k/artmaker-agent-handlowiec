"""Provider-agnostic LLM client.

Wraps Anthropic Claude and Google Gemini behind a single `parse_structured()`
function. The structured output schema is a Pydantic model; both providers
return a validated instance.

Provider/model can be overridden per call (used by the GUI selector) or read
from env defaults (used by the CLI).
"""
from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from core.config import settings

T = TypeVar("T", bound=BaseModel)

# ---- Tunables ---------------------------------------------------------------
# Default request timeout in seconds. Gemini thinking models can be slow on
# preview tier — 180s gives them room without hanging the GUI forever.
REQUEST_TIMEOUT_S = 180.0

# Cap thinking budget on Gemini thinking-capable models. Setting a low cap
# (instead of unlimited) gives 3-5x speedup on preview models with negligible
# quality loss on our scoring task. Set to 0 to disable thinking entirely on
# models that allow it (flash); pro/preview models often require >0.
GEMINI_THINKING_BUDGET = 1024


# ---- Pricing reference (USD per 1M tokens). ----------------------------------
# Used only for "estimated cost" hints in the GUI. Do not rely on this for
# billing — actual prices come from your provider invoice.
MODEL_PRICING: dict[tuple[str, str], dict[str, float]] = {
    # Anthropic Claude
    ("anthropic", "claude-opus-4-7"):   {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    ("anthropic", "claude-opus-4-6"):   {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    ("anthropic", "claude-sonnet-4-6"): {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    ("anthropic", "claude-haiku-4-5"):  {"input": 1.00, "output":  5.00, "cache_read": 0.10, "cache_write": 1.25},
    # Google Gemini
    ("gemini", "gemini-3.1-pro-preview"): {"input": 2.00, "output": 12.00},
    ("gemini", "gemini-2.5-pro"):         {"input": 1.25, "output": 10.00},
    ("gemini", "gemini-2.5-flash"):       {"input": 0.30, "output":  2.50},
    ("gemini", "gemini-2.5-flash-lite"):  {"input": 0.10, "output":  0.40},
}

ANTHROPIC_MODELS = [
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
]

GEMINI_MODELS = [
    "gemini-3.1-pro-preview",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]


# ---- Secrets resolution (env first, then Streamlit secrets) ------------------

def _resolve_secret(env_value: str, secret_key: str) -> str:
    if env_value:
        return env_value
    try:
        import streamlit as st  # type: ignore[import-not-found]

        if hasattr(st, "secrets") and secret_key in st.secrets:
            return str(st.secrets[secret_key])
    except Exception:
        pass
    return ""


def has_anthropic_key() -> bool:
    return bool(_resolve_secret(settings.anthropic_api_key, "ANTHROPIC_API_KEY"))


def has_gemini_key() -> bool:
    return bool(_resolve_secret(settings.gemini_api_key, "GEMINI_API_KEY"))


def _require_anthropic_key() -> str:
    key = _resolve_secret(settings.anthropic_api_key, "ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Put it in `.env` locally or in Streamlit Cloud "
            "Settings → Secrets (TOML format)."
        )
    return key


def _require_gemini_key() -> str:
    key = _resolve_secret(settings.gemini_api_key, "GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY not set. Put it in `.env` locally or in Streamlit Cloud "
            "Settings → Secrets (TOML format)."
        )
    return key


# ---- Anthropic backend ------------------------------------------------------

def _parse_anthropic(
    *,
    model: str,
    system: str,
    user: str,
    output_schema: type[T],
    max_tokens: int,
    temperature: float = 0.3,
) -> tuple[T, dict]:
    import anthropic

    client = anthropic.Anthropic(
        api_key=_require_anthropic_key(),
        timeout=REQUEST_TIMEOUT_S,
    )
    response = client.messages.parse(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=[
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ],
        messages=[{"role": "user", "content": user}],
        output_format=output_schema,
    )
    parsed: T = response.parsed_output  # type: ignore[assignment]
    usage = {
        "input_tokens": int(getattr(response.usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(response.usage, "output_tokens", 0) or 0),
        "cache_read_input_tokens": int(getattr(response.usage, "cache_read_input_tokens", 0) or 0),
        "cache_creation_input_tokens": int(getattr(response.usage, "cache_creation_input_tokens", 0) or 0),
    }
    return parsed, usage


# ---- Gemini backend ---------------------------------------------------------

def _gemini_thinking_config(model: str):
    """Low-cap ThinkingConfig for thinking-capable Gemini models.

    Returns None for non-thinking models (e.g. older flash) so we don't pass
    an unsupported field. The cap drastically cuts latency on preview models.
    """
    try:
        from google.genai.types import ThinkingConfig
    except ImportError:
        return None

    name = model.lower()
    is_thinking_capable = (
        "preview" in name
        or "2.5-pro" in name
        or "2.5-flash" in name
        or name.startswith("gemini-3")
    )
    if not is_thinking_capable:
        return None
    return ThinkingConfig(thinking_budget=GEMINI_THINKING_BUDGET)


def _parse_gemini(
    *,
    model: str,
    system: str,
    user: str,
    output_schema: type[T],
    max_tokens: int,
    temperature: float = 0.3,
) -> tuple[T, dict]:
    from google import genai
    from google.genai import types as genai_types

    http_options = genai_types.HttpOptions(timeout=int(REQUEST_TIMEOUT_S * 1000))
    client = genai.Client(api_key=_require_gemini_key(), http_options=http_options)

    config_kwargs = dict(
        system_instruction=system,
        response_mime_type="application/json",
        response_schema=output_schema,
        max_output_tokens=max_tokens,
        temperature=temperature,
    )
    thinking = _gemini_thinking_config(model)
    if thinking is not None:
        config_kwargs["thinking_config"] = thinking

    response = client.models.generate_content(
        model=model,
        contents=user,
        config=genai_types.GenerateContentConfig(**config_kwargs),
    )
    text = response.text or ""
    parsed = output_schema.model_validate_json(text)
    meta = getattr(response, "usage_metadata", None)
    usage = {
        "input_tokens": int(getattr(meta, "prompt_token_count", 0) or 0),
        "output_tokens": int(getattr(meta, "candidates_token_count", 0) or 0),
        "cache_read_input_tokens": int(getattr(meta, "cached_content_token_count", 0) or 0),
        "cache_creation_input_tokens": 0,
    }
    return parsed, usage


# ---- Public dispatch --------------------------------------------------------

def _is_transient_error(exc: Exception) -> bool:
    """Czy blad jest tymczasowy (warto retry'owac z backoffem) czy permanent
    (autoryzacja, model name itd - retry nie pomoze)."""
    msg = str(exc).lower()
    # HTTP 5xx, 429 throttle, 408 timeout - retry
    transient_codes = ["503", "502", "504", "500", "429", "408",
                       "unavailable", "overloaded", "rate limit",
                       "timeout", "deadline", "internal error",
                       "connection reset", "connection error"]
    return any(code in msg for code in transient_codes)


def parse_structured(
    *,
    provider: str,
    model: str,
    system: str,
    user: str,
    output_schema: type[T],
    max_tokens: int = 4096,
    temperature: float = 0.3,
    max_retries: int = 4,
) -> tuple[T, dict]:
    """Call the chosen provider, return (parsed_pydantic_model, usage_info).

    Default temperature 0.3 is right for grounded, deterministic structured
    output (research scoring, relevance classification). Bump for creative
    work — drafts use ~0.85 to escape AI-cliché defaults.

    Retry logic: exponential backoff (2s, 4s, 8s, 16s) dla 503/429/timeout.
    4xx (auth, bad request) NIE retry'owany - propagacja bledu od razu.
    """
    import time
    import logging
    log = logging.getLogger("ecombinat.llm")

    provider = provider.lower()
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            if provider == "anthropic":
                return _parse_anthropic(
                    model=model, system=system, user=user,
                    output_schema=output_schema, max_tokens=max_tokens,
                    temperature=temperature,
                )
            if provider == "gemini":
                return _parse_gemini(
                    model=model, system=system, user=user,
                    output_schema=output_schema, max_tokens=max_tokens,
                    temperature=temperature,
                )
            raise ValueError(f"Unknown LLM provider: {provider!r}. Use 'anthropic' or 'gemini'.")
        except Exception as exc:
            last_exc = exc
            if not _is_transient_error(exc):
                raise
            if attempt >= max_retries - 1:
                break
            wait_s = 2 ** (attempt + 1)  # 2, 4, 8, 16
            log.warning(
                f"LLM transient error (attempt {attempt+1}/{max_retries}, "
                f"provider={provider}, model={model}): {str(exc)[:200]}. "
                f"Retry za {wait_s}s..."
            )
            time.sleep(wait_s)
    # Wszystkie retry'a zuzyte
    raise last_exc if last_exc else RuntimeError("LLM call failed without exception")


def estimate_cost_usd(provider: str, model: str, usage: dict) -> float | None:
    """Best-effort USD estimate from the usage dict returned by parse_structured."""
    pricing = MODEL_PRICING.get((provider, model))
    if not pricing:
        return None
    in_tokens = usage.get("input_tokens") or 0
    out_tokens = usage.get("output_tokens") or 0
    cache_read = usage.get("cache_read_input_tokens") or 0
    cache_write = usage.get("cache_creation_input_tokens") or 0
    fresh_in = max(in_tokens - cache_read - cache_write, 0)
    cost = (
        fresh_in * pricing["input"] / 1_000_000
        + out_tokens * pricing["output"] / 1_000_000
        + cache_read * pricing.get("cache_read", pricing["input"]) / 1_000_000
        + cache_write * pricing.get("cache_write", pricing["input"]) / 1_000_000
    )
    return round(cost, 6)
