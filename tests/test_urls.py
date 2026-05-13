"""Smoke testy dla core/urls.py - dedup leadow po URL.

Te funkcje sa krytyczne: kazdy fix do nich dotknie dedupu w discovery
(in-memory) ORAZ w save_lead (DB-level). Bez testow zmiana lacznie psuje
oba miejsca.
"""
from __future__ import annotations

import pytest

from core.urls import host_only, normalize_url


class TestNormalizeUrl:
    def test_strips_www(self):
        assert normalize_url("https://www.foo.pl/") == "foo.pl"

    def test_strips_protocol(self):
        assert normalize_url("http://foo.pl") == "foo.pl"

    def test_lowercase(self):
        assert normalize_url("FOO.PL/contact") == "foo.pl/contact"

    def test_strips_trailing_slash(self):
        assert normalize_url("https://bar.com/x/y/") == "bar.com/x/y"

    def test_preserves_path(self):
        assert normalize_url("https://www.example.com/kontakt") == "example.com/kontakt"

    def test_empty_returns_empty(self):
        assert normalize_url("") == ""
        assert normalize_url(None) == ""
        assert normalize_url("   ") == ""

    def test_same_business_same_key(self):
        """Dwa URL'e tej samej firmy musza miec ten sam klucz - inaczej dedup nie zadziala."""
        a = normalize_url("https://www.synchronik.pl/")
        b = normalize_url("http://synchronik.pl")
        c = normalize_url("SYNCHRONIK.PL/")
        assert a == b == c == "synchronik.pl"


class TestHostOnly:
    def test_bare_host(self):
        assert host_only("https://www.foo.pl/kontakt") == "foo.pl"

    def test_no_path(self):
        assert host_only("https://bar.com") == "bar.com"

    def test_empty(self):
        assert host_only("") == ""
        assert host_only(None) == ""

    def test_consistent_with_normalize(self):
        """host_only musi byc prefixem normalize_url - to zaleznosc na ktorej polega SQL ILIKE."""
        urls = ["https://www.foo.pl/x/y", "FOO.PL/abc", "http://foo.pl"]
        for u in urls:
            assert normalize_url(u).startswith(host_only(u))
