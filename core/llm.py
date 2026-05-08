from __future__ import annotations

import anthropic

from core.config import settings

_client: anthropic.Anthropic | None = None


def _resolve_api_key() -> str:
    """Resolve the Anthropic API key from .env first, then Streamlit secrets.

    Streamlit Community Cloud doesn't propagate `secrets.toml` into env vars,
    so we have to consult `st.secrets` explicitly when running under Streamlit.
    """
    if settings.anthropic_api_key:
        return settings.anthropic_api_key
    try:
        import streamlit as st  # type: ignore[import-not-found]

        if hasattr(st, "secrets") and "ANTHROPIC_API_KEY" in st.secrets:
            return str(st.secrets["ANTHROPIC_API_KEY"])
    except Exception:
        pass
    raise RuntimeError(
        "ANTHROPIC_API_KEY not set. Put it in `.env` locally, or in Streamlit Cloud "
        "Settings → Secrets (TOML format)."
    )


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=_resolve_api_key())
    return _client
