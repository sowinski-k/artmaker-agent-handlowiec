"""Strict business-email validation.

Wspoldzielone przez:
  - agent/contact_finder.py  - filtruje emaile wyciagniete regexem z HTML
  - agent/research.py        - waliduje email zwrocony przez LLM (ResearchResult)

Problem ktory rozwiazuje: do leadow wpadaly "syfiaste" maile typu:
  d@e.gettime, +m@h.random, cre@ivecommons.org, secure.grav@ar.com,
  29818881.two_step_verific@ion.pre, https%3a%2f%2fsztuk@worzenia.pl

Zrodla syfu:
  1. Obfuscation decoder matchowal literalne "at" w srodku slow (gravatar ->
     grav@ar) - naprawione osobno w contact_finder _OBFUSCATION_PATTERNS.
  2. Regex EMAIL_RE lapal fragmenty zminifikowanego JS / URL-i.

Strategia walidacji (defense-in-depth):
  - TLD musi byc na whiteliscie realnych TLD (.apply/.react/.gettime/.pdf
    odpadaja - to metody JS / rozszerzenia plikow, nie domeny).
  - struktura local/domain - bez %, *, nawiasow, bez prefiksu http/www.
  - SLD min 2 znaki (a.pl, g.hf odpadaja).
  - blacklist SLD znanych serwisow/CDN (divi, gravatar, googleapis...).
"""
from __future__ import annotations

import re

# Whitelist realnych TLD - hojny, pokrywa PL B2B + branze art/kreatywne.
# Cokolwiek poza lista traktujemy jako NIE-domene (artefakt JS / pliku).
_VALID_TLDS: frozenset[str] = frozenset({
    # generic
    "com", "net", "org", "info", "biz", "name", "pro",
    # country codes (PL + sasiedzi + UE gdzie moga byc dostawcy)
    "pl", "eu", "de", "cz", "sk", "uk", "fr", "es", "it", "nl", "at", "be",
    "se", "no", "dk", "fi", "ie", "pt", "ch", "lt", "lv", "ee", "hu", "ro",
    "ua", "lu", "gr", "hr", "si", "bg",
    # new gTLD realne dla biznesu / art / edukacji / kreatywnych
    "shop", "store", "online", "site", "tech", "studio", "design", "art",
    "gallery", "media", "agency", "group", "email", "app", "dev", "io",
    "co", "me", "one", "live", "work", "company", "solutions", "expert",
    "academy", "school", "events", "education", "center", "club", "team",
})

# SLD (czesc przed TLD) znanych serwisow/CDN/library - jak email ma taki SLD
# to artefakt scrapingu HTML, nie kontakt firmy.
_SERVICE_SLDS: frozenset[str] = frozenset({
    "divi", "elementor", "gravatar", "googleapis", "gstatic",
    "googlesyndication", "google-analytics", "googletagmanager",
    "cloudflare", "jsdelivr", "unpkg", "cdnjs", "jquery", "bootstrapcdn",
    "doubleclick", "fbcdn", "facebook", "creativecommons", "schema",
    "sentry", "hotjar", "wordpress", "woocommerce", "wp", "w3",
})

# Fragmenty nazw serwisow/CDN. Email rozbity przez obfuscation-decoder na "at"
# (gravatar -> grav@ar) po sklejeniu z powrotem (local + "at" + domain) zawiera
# pelna nazwe serwisu. Real biznesowy email po sklejeniu jej nie zawiera.
_SERVICE_NAME_FRAGMENTS: tuple[str, ...] = (
    "gravatar", "googlesyndication", "creativecommons", "ppstatic",
    "gstatic", "googleapis", "googletagmanager", "googleanalytics",
    "cloudflare", "jsdelivr", "jquery", "bootstrap", "fontawesome",
    "doubleclick", "wordpress", "woocommerce", "elementor", "recaptcha",
    "cloudfront", "akamai", "polyfill", "wp-content", "wpcontent",
)

# Niedozwolone znaki gdziekolwiek w emailu - sygnal ze to JS / URL / maska.
_BAD_CHARS: frozenset[str] = frozenset("*[]()<>{}\"'%\\ \t\n\r|^`~")

# local part: zaczyna+konczy alfanumerycznie, w srodku . _ + -
_LOCAL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._+-]*[a-z0-9])?$")
# domain label: alfanumeryczny, myslnik tylko w srodku
_DOMAIN_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")

_LOCAL_BAD_PREFIXES = ("https", "http", "www", "mailto", "ftp")


def is_valid_business_email(email: str | None) -> bool:
    """True jezeli `email` wyglada na realny biznesowy adres kontaktowy.

    Konserwatywne - lepiej odrzucic watpliwy (lead zostaje, pole email puste)
    niz zapisac syf ktory potem trafi do Woodpeckera jako odbiorca.
    """
    if not email or not isinstance(email, str):
        return False
    e = email.strip().lower()

    if len(e) < 6 or len(e) > 254:
        return False
    if any(c in _BAD_CHARS for c in e):
        return False
    if e.count("@") != 1:
        return False

    local, _, domain = e.partition("@")

    # --- local part ---
    if len(local) < 2 or len(local) > 64:
        return False
    if ".." in local:
        return False
    if local.isdigit():  # czysto numeryczny local = analytics ID
        return False
    if not _LOCAL_RE.match(local):
        return False
    if any(local.startswith(p) for p in _LOCAL_BAD_PREFIXES):
        return False

    # --- domain ---
    if "." not in domain or ".." in domain:
        return False
    labels = domain.split(".")
    if len(labels) < 2:
        return False
    for lbl in labels:
        if not lbl or not _DOMAIN_LABEL_RE.match(lbl):
            return False

    tld = labels[-1]
    if tld not in _VALID_TLDS:
        return False

    sld = labels[-2]
    if len(sld) < 2:  # 'a.pl', 'g.hf', 't.qc' - nie domena firmy
        return False
    if sld in _SERVICE_SLDS:
        return False

    # Artefakt obfuscation-decodera: email powstal z rozbicia slowa na "at"
    # (gravatar -> grav@ar.com). Po sklejeniu local+at+domain wraca nazwa
    # serwisu. cre@ivecommons.org -> "creativecommons", secure.grav@ar.com ->
    # "gravatar", d-art.ppst@ic.pl -> "ppstatic".
    rejoined = (local + "at" + domain).replace(".", "").replace("-", "").replace("_", "")
    for frag in _SERVICE_NAME_FRAGMENTS:
        if frag in rejoined:
            return False

    return True
