"""Fetch a lead's website (homepage + a few supporting pages) and extract
clean text for the research agent to analyse.

Strategy:
    1. Fetch homepage with httpx (timeouts, redirects, custom UA).
    2. Parse HTML, strip nav/script/style/footer/iframe noise.
    3. Look for internal links matching about / contact / offer keywords.
    4. Fetch up to 2 of those supporting pages.
    5. Capture Instagram/Facebook URLs found anywhere in the homepage.

Output is a dict ready to splice into the research user prompt.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

USER_AGENT = (
    "ArtmakerResearchBot/1.0 (B2B prospecting for art-supplies wholesale; "
    "contact via website)"
)
TIMEOUT_S = 15.0
MAX_PAGE_CHARS = 10_000
MAX_SUPPORTING_PAGES = 2

ABOUT_KEYWORDS = ["o-nas", "o nas", "about", "o-firmie", "kim-jestesmy", "kim jestesmy"]
CONTACT_KEYWORDS = ["kontakt", "contact", "skontaktuj"]
OFFER_KEYWORDS = ["oferta", "offer", "uslugi", "usługi", "produkty", "warsztaty", "zajecia", "zajęcia"]


def _normalize_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url.lstrip("/")
    return url.strip()


def _extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "noscript", "iframe", "svg"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text[:MAX_PAGE_CHARS]


def _find_internal_links(
    html: str, base_url: str, *, keywords: list[str], limit: int = 1
) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    base_host = urlparse(base_url).netloc
    found: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True).lower()
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        if parsed.netloc != base_host:
            continue
        if parsed.scheme not in ("http", "https"):
            continue
        haystack = (href + " " + text).lower()
        if any(kw in haystack for kw in keywords):
            if full not in found:
                found.append(full)
        if len(found) >= limit:
            break
    return found


def _find_social_links(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "instagram.com/" in href and "instagram" not in out:
            out["instagram"] = href.split("?")[0]
        elif "facebook.com/" in href and "facebook" not in out:
            out["facebook"] = href.split("?")[0]
    return out


def _fetch(client: httpx.Client, url: str) -> tuple[str, str] | None:
    try:
        resp = client.get(url)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "")
        if "text/html" not in ctype and "application/xhtml" not in ctype:
            return None
        return str(resp.url), resp.text
    except Exception:
        return None


def gather_pages(url: str) -> dict:
    """Fetch homepage + supporting pages. Returns a dict with text content."""
    url = _normalize_url(url)
    pages: dict[str, str] = {}
    social: dict[str, str] = {}
    home_url: str | None = None
    errors: list[str] = []

    with httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "pl,en;q=0.7"},
        timeout=TIMEOUT_S,
        follow_redirects=True,
    ) as client:
        home = _fetch(client, url)
        if home is None:
            errors.append(f"Nie udało się pobrać strony głównej: {url}")
            return {"home_url": url, "pages": pages, "social": social, "errors": errors}

        home_url, home_html = home
        pages[home_url] = _extract_text(home_html)
        social = _find_social_links(home_html)

        supporting: list[str] = []
        for keywords in (ABOUT_KEYWORDS, CONTACT_KEYWORDS, OFFER_KEYWORDS):
            for link in _find_internal_links(home_html, home_url, keywords=keywords, limit=1):
                if link not in pages and link not in supporting:
                    supporting.append(link)
                if len(supporting) >= MAX_SUPPORTING_PAGES:
                    break
            if len(supporting) >= MAX_SUPPORTING_PAGES:
                break

        for link in supporting[:MAX_SUPPORTING_PAGES]:
            sub = _fetch(client, link)
            if sub is None:
                continue
            sub_url, sub_html = sub
            if sub_url not in pages:
                pages[sub_url] = _extract_text(sub_html)

    return {"home_url": home_url, "pages": pages, "social": social, "errors": errors}


def build_user_message(
    *,
    target_url: str,
    gathered: dict,
    segment_hint: str | None = None,
    city_hint: str | None = None,
) -> str:
    parts: list[str] = []
    parts.append(f"TARGET URL: {target_url}")
    if gathered.get("home_url") and gathered["home_url"] != target_url:
        parts.append(f"FINAL URL po redirectach: {gathered['home_url']}")

    hints: list[str] = []
    if segment_hint:
        hints.append(f"- Segment hint: {segment_hint}")
    if city_hint:
        hints.append(f"- City hint: {city_hint}")
    if hints:
        parts.append("HINTS (do weryfikacji, mogą być błędne):\n" + "\n".join(hints))

    if gathered.get("errors"):
        parts.append("BŁĘDY:\n" + "\n".join(f"- {e}" for e in gathered["errors"]))

    pages = gathered.get("pages") or {}
    if pages:
        parts.append("ZNALEZIONE STRONY:\n")
        for page_url, content in pages.items():
            parts.append(f"## {page_url}\n\n{content}\n")
    else:
        parts.append("Brak udanych pobrań stron — oceń lead jako martwy/niedostępny.")

    social = gathered.get("social") or {}
    if social:
        parts.append("ZNALEZIONE SOCIALE:")
        for k, v in social.items():
            parts.append(f"- {k}: {v}")

    parts.append(
        "\nOceń lead według rubryki i zwróć strukturalny wynik. "
        "Pamiętaj o regułach rygorystycznych ze system prompta."
    )
    return "\n\n".join(parts)
