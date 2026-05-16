"""Smoke testy dla agent/contact_finder - email/phone extraction.

Kluczowe scenariusze (regression dla user feedback "Malowanie z winem" - lead
ze stopka 'info@malowaniezwinem.pl' ktora enrichment przegapil):

1. Plain email z mailto: + tekst (najprostszy case)
2. HTML entity obfuscation (&#64; zamiast @)
3. CloudFlare email protection (data-cfemail)
4. Tekstowe "info [at] domena.pl" / variants
5. Junk filter (analytics, schema.org, noreply itp.)
"""
from __future__ import annotations

from agent.contact_finder import (
    EMAIL_RE,
    _decode_cloudflare_emails,
    _extract_emails,
    _extract_phones,
    _is_junk_email,
)


class TestPlainEmail:
    def test_mailto_link(self):
        html = '<a href="mailto:info@example.pl">napisz</a>'
        emails = _extract_emails(html, domain_hint="example.pl")
        assert "info@example.pl" in emails

    def test_plain_text(self):
        html = '<p>Skontaktuj się: kontakt@firma.pl lub +48 22 123 45 67</p>'
        emails = _extract_emails(html, domain_hint="firma.pl")
        assert "kontakt@firma.pl" in emails

    def test_footer_format(self):
        """Replikacja stopki 'Malowanie z winem' user'a."""
        html = '<footer>© 2024 · info@malowaniezwinem.pl · tel: 22 123 45 67</footer>'
        emails = _extract_emails(html, domain_hint="malowaniezwinem.pl")
        assert "info@malowaniezwinem.pl" in emails


class TestHtmlEntityObfuscation:
    def test_at_sign_entity(self):
        """info&#64;domena.pl - typowa obfuscation."""
        html = '<p>Email: info&#64;example.pl</p>'
        emails = _extract_emails(html, domain_hint="example.pl")
        assert "info@example.pl" in emails

    def test_full_email_entity_encoded(self):
        """&#105;&#110;&#102;&#111;@example.pl = info@example.pl"""
        html = '<p>&#105;&#110;&#102;&#111;@example.pl</p>'
        emails = _extract_emails(html, domain_hint="example.pl")
        assert "info@example.pl" in emails


class TestCloudFlareEmailProtection:
    def test_cfemail_decode(self):
        """data-cfemail="HEX" gdzie HEX to XOR base16."""
        # Generujemy real CloudFlare hex dla "info@example.pl"
        # key = 0x42, plaintext "info@example.pl"
        # decoded[i] = key XOR plaintext[i]
        key = 0x42
        plaintext = "info@example.pl"
        encoded_bytes = bytes([key] + [key ^ ord(c) for c in plaintext])
        hex_str = encoded_bytes.hex()

        html = f'<a href="/cdn-cgi/l/email-protection#{hex_str}" data-cfemail="{hex_str}">[email&#160;protected]</a>'
        emails = _extract_emails(html, domain_hint="example.pl")
        assert "info@example.pl" in emails

    def test_decode_function_alone(self):
        """Testuje sam helper bez wywolywania extract_emails."""
        key = 0xAA
        plaintext = "test@firma.pl"
        encoded = bytes([key] + [key ^ ord(c) for c in plaintext]).hex()
        html = f'<span data-cfemail="{encoded}">x</span>'
        out = _decode_cloudflare_emails(html)
        assert "test@firma.pl" in out


class TestTextObfuscation:
    def test_at_bracket(self):
        """info [at] domena.pl"""
        html = '<p>Napisz: info [at] firma.pl</p>'
        emails = _extract_emails(html, domain_hint="firma.pl")
        assert "info@firma.pl" in emails

    def test_at_paren(self):
        """info(at)domena.pl"""
        html = '<p>kontakt(at)firma.pl</p>'
        emails = _extract_emails(html, domain_hint="firma.pl")
        assert "kontakt@firma.pl" in emails

    def test_at_dot_paren(self):
        """info(at)firma(dot)pl"""
        html = '<p>napisz info(at)firma(dot)pl</p>'
        emails = _extract_emails(html)
        assert "info@firma.pl" in emails

    def test_malpa_polish(self):
        """info małpa domena.pl - polska wariacja"""
        html = '<p>Email: info małpa firma.pl</p>'
        emails = _extract_emails(html, domain_hint="firma.pl")
        assert "info@firma.pl" in emails


class TestJunkFilter:
    def test_noreply_rejected(self):
        assert _is_junk_email("noreply@firma.pl") is True
        assert _is_junk_email("no-reply@firma.pl") is True

    def test_example_com_rejected(self):
        assert _is_junk_email("ktos@example.com") is True

    def test_schema_org_rejected(self):
        assert _is_junk_email("foo@schema.org") is True

    def test_real_email_accepted(self):
        assert _is_junk_email("info@malowaniezwinem.pl") is False
        assert _is_junk_email("biuro@synchronik.pl") is False


class TestEmailRanking:
    def test_same_domain_first(self):
        html = '''
            <p>kontakt: backup@gmail.com</p>
            <p>oficjalny: info@firma.pl</p>
        '''
        emails = _extract_emails(html, domain_hint="firma.pl")
        # info@firma.pl powinno byc na poczatku
        assert emails[0] == "info@firma.pl"

    def test_pl_before_others(self):
        html = '<p>info@firma.com</p><p>biuro@firma.pl</p>'
        emails = _extract_emails(html)
        # .pl wczesniej niz .com (gdy brak domain_hint)
        assert emails.index("biuro@firma.pl") < emails.index("info@firma.com")


class TestPhone:
    def test_tel_link(self):
        html = '<a href="tel:+48221234567">zadzwon</a>'
        phones = _extract_phones(html)
        assert any("+48" in p for p in phones)

    def test_polish_format(self):
        html = '<p>tel: 22 123 45 67</p>'
        phones = _extract_phones(html)
        assert len(phones) > 0


class TestJunkEmailFalsePositives:
    """Regression - user zglosil false-positive maile wpadajace do leadow
    z Google Maps scrapingu stron Allegro/Facebook. Te to fragmenty JS/HTML
    sparsowane jako email (np. "edge-ch@.facebook.com" z Facebook SDK)."""

    def test_facebook_sdk_fragment_rejected(self):
        # edge-ch@.facebook.com - kropka po @ w regex starszej wersji
        assert EMAIL_RE.fullmatch("edge-ch@.facebook.com") is None

    def test_javascript_document_location_rejected(self):
        # document.loc@ion.protocol - JS code parsed jak email
        assert _is_junk_email("document.loc@ion.protocol") is True

    def test_gstatic_cdn_fragment_rejected(self):
        # fonts.gst@ic.com - fragment "fonts.gstatic.com" Google Fonts CDN
        assert _is_junk_email("fonts.gst@ic.com") is True

    def test_dataLayer_push_rejected(self):
        # d@alayer.push - dataLayer.push() z Google Tag Manager
        assert _is_junk_email("d@alayer.push") is True

    def test_facebook_subdomain_rejected(self):
        # 100% false-positive z FB SDK markup
        assert _is_junk_email("foo@cdn.facebook.com") is True

    def test_fake_tld_protocol_rejected(self):
        assert _is_junk_email("x@host.protocol") is True

    def test_fake_tld_push_rejected(self):
        assert _is_junk_email("x@host.push") is True

    def test_fake_tld_local_rejected(self):
        assert _is_junk_email("x@server.local") is True

    def test_window_prefix_rejected(self):
        assert _is_junk_email("window.location@example.org") is True

    def test_real_polish_emails_pass(self):
        # Sanity: realne emaile NIE moga zostac zablokowane
        for email in [
            "kontakt@artbox.pl",
            "biuro@papiernia.com.pl",
            "jan.kowalski@gmail.com",
            "sklep@wp.pl",
            "ania@drukarnia.com.pl",
            "j.kowalski@firma.pl",  # 8-char nazwisko OK
        ]:
            assert EMAIL_RE.fullmatch(email) is not None, f"{email} regex blocked"
            assert _is_junk_email(email) is False, f"{email} marked junk"

