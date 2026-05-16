"""Lead enrichment - znajdz email/telefon dla leadow ktore wyszly puste.

Strategia (3 stopnie, najtanszy pierwszy):

  1. SCRAPE_HOMEPAGE  - GET / + /kontakt + /contact + /o-nas (5x httpx GET)
                        regex po mailto: i tel: + tekstowe Polish patterns
                        koszt: ~0 (bez LLM/API), ~5-10s

  2. APIFY_EMAIL_EXTR - Apify "Email Extractor" actor (chodzi po podstronach)
                        koszt: ~$0.005/lead (1 kredyt), ~30-60s
                        TODO: tu na razie placeholder

  3. (przyszlosc)     - Hunter.io domain-search albo Gemini grounded

Po wszystkich krokach bez sukcesu -> Lead.status = DEAD_END,
last_enriched_at = now. Recheck po 90 dniach (firmy aktualizuja wizytowki).
"""
from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

import httpx

log = logging.getLogger("ecombinat.contact_finder")

# Lead bez kontaktu po enrichmencie -> dead_end. Recheckujemy po RECHECK_DAYS
# (firmy aktualizuja wizytowki, nowe podstrony, etc).
RECHECK_DAYS = 90

# Common contact paths to check. Kolejnosc: najpierw najprawdopodobniejsze
# (homepage, /kontakt PL, /contact EN), potem subkategorie.
CONTACT_PATHS = [
    "/",
    "/kontakt", "/kontakt.html", "/kontakt/",
    "/contact", "/contact-us", "/contact.html",
    "/o-nas", "/o-nas.html",
    "/about", "/about-us",
    "/wspolpraca",      # B2B specific
    "/dla-firm",
    "/footer",          # niektore strony maja osobny endpoint dla stopki
]
# Cap na rozmiar pobieranego HTML (anti-bomb)
MAX_HTML_SIZE = 500_000  # 500KB

# Email regex - strict, wymaga ze:
#  - lokal nie zaczyna sie kropka
#  - po @ pierwszy znak to alfanumeric (NIE kropka)
#  - TLD min 2 znaki
# Wczesniejsza wersja lapala "edge-ch@.facebook.com" (FB SDK markup w HTML),
# "document.loc@ion.protocol" (JS code), "fonts.gst@ic.com" (Google CDN),
# "d@alayer.push" (dataLayer.push). To regression guard po user'owym
# zgloszeniu false-positive mailów wpadajacych do leadow.
EMAIL_RE = re.compile(
    r"(?<![a-zA-Z0-9.])"                # nic alfanumeric+kropka przed (nie matchuj 'foo.bar@')
    r"[a-zA-Z0-9_%+-]"                  # pierwszy znak local NIE moze byc kropka
    r"[a-zA-Z0-9._%+-]*"                # reszta local (kropki OK w srodku)
    r"@"
    r"[a-zA-Z0-9]"                      # pierwszy znak hosta MUSI byc alfanumeric (NIE kropka!)
    r"[a-zA-Z0-9.-]*"                   # reszta hosta (kropki OK w srodku)
    r"\.[a-zA-Z]{2,}"                   # TLD min 2 alfa
)
# Polski telefon: +48 XXX XXX XXX, 9 cyfr, ze spacjami / mysl-nikami / bez
PHONE_RE = re.compile(
    r"(?:(?:\+|00)?\s?48\s?)?"   # opcjonalny prefix +48
    r"(?:\(?\d{2,3}\)?[\s\-.]?)" # area code
    r"\d{3}[\s\-.]?\d{2,3}[\s\-.]?\d{2,3}"
)

# Email patterns ktore sa SMIECIEM (analytics, libs, copyright placeholders)
EMAIL_BLACKLIST_HOSTS = {
    # Generic placeholders
    "example.com", "example.org", "example.net", "domain.com",
    # Hosting platforms
    "sentry.io", "wixpress.com", "shopify.com", "squarespace.com",
    "wordpress.com", "wp.com", "schema.org",
    "w3.org", "namesilo.com", "godaddy.com", "wpengine.com",
    "sentry-next.wixpress.com",
    # CDNs i platformy social - tu w 100% false-positive z JS/HTML markup
    "facebook.com", "fbcdn.net", "instagram.com", "twitter.com", "t.co",
    "linkedin.com", "twimg.com", "ytimg.com", "youtube.com",
    # Google libs (CDN, fonty, analytics, recaptcha)
    "gstatic.com", "googleapis.com", "googleusercontent.com",
    "googletagmanager.com", "google-analytics.com", "googlesyndication.com",
    "doubleclick.net", "recaptcha.net",
    # CSS/JS CDNs - typowe imports w HTML
    "jsdelivr.net", "unpkg.com", "bootstrapcdn.com", "cdnjs.com",
    "fontawesome.com", "jquery.com",
    # Cloudflare / analytics
    "cloudflareinsights.com", "cloudflare.com", "static-cf.com",
    "gravatar.com",
}
# Sfalszowane TLD ktore matchuja regex ale to nie real domain.
# 'protocol' = JS document.location.protocol, 'push' = dataLayer.push,
# 'local' / 'test' / 'invalid' / 'example' = reserved test TLDs (RFC 2606).
EMAIL_BLACKLIST_TLDS = {
    "protocol", "push", "local", "test", "invalid", "example",
    "localhost", "internal", "lan",
}
# Local part prefixes ktore w 100% to fragmenty kodu JS.
EMAIL_BLACKLIST_LOCAL_PREFIXES = {
    "document.", "window.", "console.", "navigator.",
    "this.", "globalThis.", "location.",
}
EMAIL_BLACKLIST_LOCALS = {
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "test", "test1", "test2", "demo", "user",
    "you", "your", "name", "imie", "nazwisko",
}


@dataclass
class EnrichResult:
    email: str | None = None
    phone: str | None = None
    source: str = ""           # "homepage_scrape", "apify_email_extractor", ...
    pages_checked: int = 0
    duration_s: float = 0.0


def _is_junk_email(email: str) -> bool:
    """Czy email to placeholder / library / analytics, czy realny kontakt.

    Filtruje:
      - Hosty z EMAIL_BLACKLIST_HOSTS (FB SDK, Google CDN, Cloudflare, etc.)
      - Fake TLDs z EMAIL_BLACKLIST_TLDS (.protocol, .push, .local, .test)
      - Local part prefixes z EMAIL_BLACKLIST_LOCAL_PREFIXES (document., window.)
      - Local part exact matches (noreply, test, demo)
      - Lockal > 40 chars (analytics IDs)
      - Host ze ext obrazka (analytics trackers w URL)
    """
    e = email.lower().strip()
    if "@" not in e: return True
    local, _, host = e.partition("@")
    if host in EMAIL_BLACKLIST_HOSTS: return True
    # Sprawdz subdomeny: x.facebook.com -> facebook.com
    host_parts = host.split(".")
    for i in range(len(host_parts) - 1):
        if ".".join(host_parts[i:]) in EMAIL_BLACKLIST_HOSTS:
            return True
    # TLD blacklist (fake/reserved TLDs)
    if host_parts and host_parts[-1] in EMAIL_BLACKLIST_TLDS: return True
    # Local part: prefix patterns (document., window., ...)
    if any(local.startswith(p) for p in EMAIL_BLACKLIST_LOCAL_PREFIXES): return True
    # Local part: exact matches (noreply, demo, test)
    if any(local.startswith(b) for b in EMAIL_BLACKLIST_LOCALS): return True
    # Long random-looking locals (analytics IDs)
    if len(local) > 40: return True
    # Image extension (analytics tracker pixels in URLs)
    if any(host.endswith(s) for s in [".png", ".jpg", ".gif", ".svg", ".webp"]): return True
    # Truncated library/CDN fragments: "fonts.gst@ic.com" - last local segment
    # po kropce jest super krotki (<=3 chars) co znaczy ze ktos sparsowal
    # "fonts.gstatic.com" jako 'local@host' przy @ w innym miejscu HTMLa.
    # Real emaile rzadko maja "jan.x@..." gdzie x to 1-3 chars.
    if "." in local:
        last_local_segment = local.rsplit(".", 1)[-1]
        if 1 <= len(last_local_segment) <= 3 and last_local_segment.isalpha():
            return True
    return False


def _normalize_phone(raw: str) -> str:
    """Format do +48 XXX XXX XXX. Rzuca '' jesli za malo cyfr po normalizacji."""
    digits = re.sub(r"\D", "", raw)
    # Strip leading 0048 / 48
    if digits.startswith("0048"): digits = digits[4:]
    elif digits.startswith("48") and len(digits) > 9: digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 10: digits = digits[1:]
    if len(digits) != 9: return ""  # PL numer ma 9 cyfr
    return f"+48 {digits[0:3]} {digits[3:6]} {digits[6:9]}"


# Wzorce obfuskacji emaila ktore widzimy na polskich stronach kontaktowych.
# Lista NIE wyczerpujaca - to top-10 patternow.
# (?:...) = non-capturing group, ([a-z0-9._%+-]+) = email local part
# i ([a-z0-9.-]+\.[a-z]{2,}) = domena - po decode wracamy do EMAIL_RE.
_OBFUSCATION_PATTERNS = [
    # info [at] domena.pl / info[at]domena.pl / info @at@ domena.pl
    r"([a-z0-9._%+-]+)\s*[\[\(]?\s*(?:at|AT|małpa|małpka)\s*[\]\)]?\s*([a-z0-9.-]+\.[a-z]{2,})",
    # info ‒ at ‒ domena.pl (z roznymi myslnikami: -, –, —)
    r"([a-z0-9._%+-]+)\s*[\-‒–—]\s*at\s*[\-‒–—]\s*([a-z0-9.-]+\.[a-z]{2,})",
    # info(at)domena(dot)pl
    r"([a-z0-9._%+-]+)\s*\(at\)\s*([a-z0-9.-]+)\s*\(dot\)\s*([a-z]{2,})",
    # i n f o @ d o m e n a . p l (spaced for anti-scraper)
    # (skomplikowany - pomijam, rzadko spotykany)
]


def _decode_cloudflare_emails(html_text: str) -> str:
    """CloudFlare email-protection: <a data-cfemail="HEX">[email&#160;protected]</a>
    gdzie HEX to base16 XOR z kluczem w pierwszym bajcie.

    Decoduje wszystkie data-cfemail w HTML do plain email + wstawia je do
    HTML zeby EMAIL_RE/mailto regex je znalazl.
    """
    def _decode_one(match: re.Match) -> str:
        hex_str = match.group(1)
        try:
            data = bytes.fromhex(hex_str)
            key = data[0]
            decoded = ''.join(chr(b ^ key) for b in data[1:])
            return f' {decoded} '  # spacje wokol = standalone email
        except Exception:
            return match.group(0)  # zostawcie jak jest

    return re.sub(r'data-cfemail="([0-9a-fA-F]+)"', _decode_one, html_text)


def _extract_emails(html_text: str, domain_hint: str | None = None) -> list[str]:
    """Wyciagnij sensowne emaile z HTML. Ranking: same domain > inny PL > inny.

    Obsluguje 3 typowe obfuscation patterns:
    1. HTML entities (&#64; = @, &#105; = i) - html.unescape przed regex
    2. CloudFlare email-protection (data-cfemail) - XOR base16 decode
    3. "info [at] domena.pl" / "info (at) domena (dot) pl" / dash variants
    """
    candidates = set()

    # Step 1: HTML entity decode (`&#64;` -> `@`, `&#105;` -> `i` itp.)
    decoded = html.unescape(html_text)

    # Step 2: CloudFlare data-cfemail decode (top obfuscation w polsce 2024+)
    decoded = _decode_cloudflare_emails(decoded)

    # mailto: links - najwiekszy sygnal
    for m in re.finditer(r'mailto:\s*([^"\'\s<>?&]+)', decoded, re.IGNORECASE):
        candidates.add(m.group(1).strip().lower())

    # Plain emails w tekscie (po decode)
    for m in EMAIL_RE.finditer(decoded):
        candidates.add(m.group(0).strip().lower())

    # Step 3: obfuscation patterns - `info [at] domena.pl` etc.
    decoded_lower = decoded.lower()
    for pattern in _OBFUSCATION_PATTERNS:
        for m in re.finditer(pattern, decoded_lower, re.IGNORECASE):
            groups = m.groups()
            if len(groups) == 2:
                # local @ host
                reconstructed = f"{groups[0]}@{groups[1]}"
            elif len(groups) == 3:
                # local (at) host (dot) tld
                reconstructed = f"{groups[0]}@{groups[1]}.{groups[2]}"
            else:
                continue
            # Walidacja - cofnij do EMAIL_RE
            if EMAIL_RE.fullmatch(reconstructed):
                candidates.add(reconstructed)

    # Filter junk
    clean = [e for e in candidates if not _is_junk_email(e)]

    # Rank: domain match first, .pl second, rest last
    def _rank(e: str) -> tuple[int, int, str]:
        host = e.split("@")[-1]
        domain_match = 0 if domain_hint and host.endswith(domain_hint) else 1
        is_pl = 0 if host.endswith(".pl") else 1
        return (domain_match, is_pl, e)

    return sorted(clean, key=_rank)


def _extract_phones(html_text: str) -> list[str]:
    """Wyciagnij polskie numery telefonow z HTML."""
    candidates = set()
    # HTML entity decode dla numerow tez (rzadziej obfuscated ale dla pewnosci)
    decoded = html.unescape(html_text)

    # tel: links - najpewniejsze
    for m in re.finditer(r'tel:\s*([+\d\s\-.()]+)', decoded, re.IGNORECASE):
        norm = _normalize_phone(m.group(1))
        if norm: candidates.add(norm)

    # Tekstowe numery (znacznie więcej falsy positives, drugi priorytet)
    for m in PHONE_RE.finditer(decoded):
        norm = _normalize_phone(m.group(0))
        if norm: candidates.add(norm)

    # Order: deterministyczny - najczesciej jest jeden, max kilka
    return sorted(candidates)


def find_contacts_on_website(website: str, *, timeout_s: float = 10.0) -> EnrichResult:
    """Krok 1: scrape homepage + typowych podstron kontaktowych.

    Raises nothing - on any error returns empty EnrichResult.
    Bezpieczne dla nielegalnych URL, timeoutow, redirectow.
    """
    start = datetime.now(timezone.utc)
    result = EnrichResult(source="homepage_scrape")

    try:
        parsed = urlparse(website if "://" in website else f"https://{website}")
    except Exception:
        return result
    if not parsed.netloc:
        return result

    base = f"{parsed.scheme or 'https'}://{parsed.netloc}"
    domain_hint = parsed.netloc.lower().lstrip("www.")

    emails: list[str] = []
    phones: list[str] = []
    pages_ok = 0

    # User-Agent zeby nie dostac 403 od bot-walls
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; EcombinatBot/1.0)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "pl,en;q=0.8",
    }

    with httpx.Client(timeout=timeout_s, follow_redirects=True, headers=headers) as client:
        for path in CONTACT_PATHS:
            url = urljoin(base, path)
            try:
                resp = client.get(url)
                if resp.status_code != 200: continue
                # 'page_html' nie 'html' bo `import html` (stdlib) wyzej w pliku
                page_html = resp.text[:MAX_HTML_SIZE]
                pages_ok += 1
                emails.extend(_extract_emails(page_html, domain_hint))
                phones.extend(_extract_phones(page_html))
                # Wczesny exit jesli mamy dobre znalezisko
                if emails and phones: break
            except Exception as exc:
                log.debug(f"GET {url} failed: {exc}")
                continue

    # Dedup zachowujac kolejnosc (best first)
    seen_e: set[str] = set()
    emails_unique = [e for e in emails if not (e in seen_e or seen_e.add(e))]
    seen_p: set[str] = set()
    phones_unique = [p for p in phones if not (p in seen_p or seen_p.add(p))]

    result.email = emails_unique[0] if emails_unique else None
    result.phone = phones_unique[0] if phones_unique else None
    result.pages_checked = pages_ok
    result.duration_s = round((datetime.now(timezone.utc) - start).total_seconds(), 2)
    return result


def should_enrich(lead) -> bool:
    """Czy warto enrichowac tego leada teraz.

    True jesli:
      - lead nie ma email AND nie ma phone
      - AND nie probowalismy ostatnio (< RECHECK_DAYS)
      - AND lead ma website (bez tego nie ma co scrapowac)
    """
    if lead.email or lead.phone:
        return False
    if not lead.website:
        return False
    if lead.last_enriched_at:
        cutoff = datetime.now(timezone.utc) - timedelta(days=RECHECK_DAYS)
        last = lead.last_enriched_at
        if last.tzinfo is None: last = last.replace(tzinfo=timezone.utc)
        if last > cutoff: return False
    return True


def enrich_lead_in_db(lead_id: int, *, workspace_id: int | None = None) -> EnrichResult:
    """Enrich + zapis do DB. Zwraca EnrichResult.

    Jeśli znajdzie kontakt - aktualizuje Lead.email/phone, status=RESEARCHED.
    Jeśli nie znajdzie - status=DEAD_END, last_enriched_at=now.
    """
    from sqlalchemy import select
    from core.db import Lead, LeadStatus, SessionLocal

    with SessionLocal() as session:
        q = select(Lead).where(Lead.id == lead_id)
        if workspace_id is not None:
            q = q.where(Lead.workspace_id == workspace_id)
        lead = session.execute(q).scalar_one_or_none()
        if lead is None:
            log.warning(f"enrich_lead_in_db: lead #{lead_id} nie istnieje")
            return EnrichResult()
        if not lead.website:
            return EnrichResult()

        result = find_contacts_on_website(lead.website)
        lead.last_enriched_at = datetime.now(timezone.utc)

        changed = False
        if result.email and not lead.email:
            lead.email = result.email
            changed = True
        if result.phone and not lead.phone:
            lead.phone = result.phone
            changed = True

        if changed:
            # Mial dead_end -> przywrocony do RESEARCHED
            if lead.status == LeadStatus.DEAD_END.value:
                lead.status = LeadStatus.RESEARCHED.value
            log.info(f"Lead #{lead_id} enriched: email={result.email} phone={result.phone}")
        elif not lead.email and not lead.phone:
            lead.status = LeadStatus.DEAD_END.value
            log.info(f"Lead #{lead_id} marked DEAD_END (no contacts after enrichment)")

        session.commit()
        return result


def find_leads_to_enrich(
    workspace_id: int, *, limit: int = 100, include_dead_end: bool = False,
) -> list[int]:
    """Zwroc lead_ids ktore warto enrichowac (workspace-scoped).

    Filtr:
      - workspace_id match
      - email IS NULL AND phone IS NULL
      - website IS NOT NULL
      - last_enriched_at is null OR < RECHECK_DAYS days ago
      - opcjonalnie: pomijaj DEAD_END
    """
    from sqlalchemy import or_, select
    from core.db import Lead, LeadStatus, SessionLocal

    cutoff = datetime.now(timezone.utc) - timedelta(days=RECHECK_DAYS)

    with SessionLocal() as session:
        q = select(Lead.id).where(
            Lead.workspace_id == workspace_id,
            Lead.email.is_(None),
            Lead.phone.is_(None),
            Lead.website.isnot(None),
            Lead.deleted_at.is_(None),  # nie enrichuj leadow w koszu
            or_(Lead.last_enriched_at.is_(None), Lead.last_enriched_at < cutoff),
        )
        if not include_dead_end:
            q = q.where(Lead.status != LeadStatus.DEAD_END.value)
        q = q.order_by(Lead.created_at.desc()).limit(max(1, min(limit, 1000)))
        return [row[0] for row in session.execute(q).all()]
