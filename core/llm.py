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
) -> tuple[T, dict]:
    import anthropic

    client = anthropic.Anthropic(api_key=_require_anthropic_key())
    response = client.messages.parse(
        model=model,
        max_tokens=max_tokens,
        system=[
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ],
        messages=[{"role": "user", "content": user}],
        output_format=output_schema,
    )
    parsed: T = response.parsed_output  # type: ignore[assignment]
    usage = {
        "input_tokens": getattr(response.usage, "input_tokens", 0),
        "output_tokens": getattr(response.usage, "output_tokens", 0),
        "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0),
        "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0),
    }
    return parsed, usage


# ---- Gemini backend ---------------------------------------------------------

def _parse_gemini(
    *,
    model: str,
    system: str,
    user: str,
    output_schema: type[T],
    max_tokens: int,
) -> tuple[T, dict]:
    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=_require_gemini_key())
    response = client.models.generate_content(
        model=model,
        contents=user,
        config=genai_types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=output_schema,
            max_output_tokens=max_tokens,
            temperature=0.3,
        ),
    )
    text = response.text or ""
    parsed = output_schema.model_validate_json(text)
    meta = getattr(response, "usage_metadata", None)
    usage = {
        "input_tokens": getattr(meta, "prompt_token_count", 0) if meta else 0,
        "output_tokens": getattr(meta, "candidates_token_count", 0) if meta else 0,
        "cache_read_input_tokens": getattr(meta, "cached_content_token_count", 0) if meta else 0,
        "cache_creation_input_tokens": 0,
    }
    return parsed, usage


# ---- Public dispatch --------------------------------------------------------

def parse_structured(
    *,
    provider: str,
    model: str,
    system: str,
    user: str,
    output_schema: type[T],
    max_tokens: int = 4096,
) -> tuple[T, dict]:
    """Call the chosen provider, return (parsed_pydantic_model, usage_info)."""
    provider = provider.lower()
    if provider == "anthropic":
        return _parse_anthropic(
            model=model, system=system, user=user,
            output_schema=output_schema, max_tokens=max_tokens,
        )
    if provider == "gemini":
        return _parse_gemini(
            model=model, system=system, user=user,
            output_schema=output_schema, max_tokens=max_tokens,
        )
    raise ValueError(f"Unknown LLM provider: {provider!r}. Use 'anthropic' or 'gemini'.")


def estimate_cost_usd(provider: str, model: str, usage: dict) -> float | None:
    """Best-effort USD estimate from the usage dict returned by parse_structured."""
    pricing = MODEL_PRICING.get((provider, model))
    if not pricing:
        return None
    in_tokens = usage.get("input_tokens", 0)
    out_tokens = usage.get("output_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    cache_write = usage.get("cache_creation_input_tokens", 0)
    fresh_in = max(in_tokens - cache_read - cache_write, 0)
    cost = (
        fresh_in * pricing["input"] / 1_000_000
        + out_tokens * pricing["output"] / 1_000_000
        + cache_read * pricing.get("cache_read", pricing["input"]) / 1_000_000
        + cache_write * pricing.get("cache_write", pricing["input"]) / 1_000_000
    )
    return round(cost, 6)
