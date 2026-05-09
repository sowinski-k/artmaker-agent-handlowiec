"""Shared URL helpers. Single source of truth for "are these two URLs the
same lead?" — used by both discovery (in-memory dedup of search results) and
research/save_lead (DB-level dedup against existing leads).
"""
from __future__ import annotations

from urllib.parse import urlparse


def normalize_url(u: str | None) -> str:
    """Lowercase host without `www.`, plus path without trailing slash.

    Two URLs that point at "the same business" should produce the same key:
        https://www.foo.pl/   -> foo.pl
        http://foo.pl         -> foo.pl
        FOO.PL/contact        -> foo.pl/contact
        https://bar.com/x/y/  -> bar.com/x/y
    """
    if not u:
        return ""
    raw = u.strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw if "://" in raw else f"http://{raw}")
        host = (parsed.netloc or parsed.path or "").lower()
        if host.startswith("www."):
            host = host[4:]
        path = parsed.path.rstrip("/") if parsed.netloc else ""
        return f"{host}{path}"
    except Exception:
        return raw.lower().rstrip("/")


def host_only(u: str | None) -> str:
    """Bare hostname for fast SQL ILIKE prefiltering."""
    norm = normalize_url(u)
    return norm.split("/", 1)[0] if norm else ""
