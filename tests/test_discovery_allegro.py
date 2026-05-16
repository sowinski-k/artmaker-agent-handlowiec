"""Testy dla ApifyAllegroSource._normalize - kluczowy mapper z roznych
schematow odpowiedzi Apify Allegro actorow na nasz DiscoveredPlace.

Regression guard - poprzednie iteracje mialy bug ze title produktu byl
wpisywany jako nazwa firmy (LaptopHP zamiast sklepu), oraz emaile
@allegromail.pl (proxy aliasy) byly propagowane mimo ze sa useless.
"""
from __future__ import annotations

from agent.discovery import ApifyAllegroSource


class TestNormalizeListingScraper:
    """automation-lab/parseforge - listing scraper, zwraca product-level
    z `seller` jako string (login)."""

    def test_seller_login_used_as_name_not_product_title(self):
        item = {
            "title": "Laptop HP 14 Intel Celeron",
            "seller": "ArtBoxSklep",
            "url": "https://allegro.pl/oferta/laptop-hp-12345",
            "sellerRating": 4.8,
        }
        place = ApifyAllegroSource._normalize(item)
        # Nazwa firmy = login sprzedawcy, NIE tytul produktu
        assert place.name == "ArtBoxSklep"
        assert "Laptop HP" not in place.name

    def test_seller_url_built_from_login(self):
        item = {"seller": "ArtBoxSklep", "title": "Farba akrylowa"}
        place = ApifyAllegroSource._normalize(item)
        # URL profilu zbudowany z konwencji Allegro
        assert place.website == "https://allegro.pl/uzytkownik/ArtBoxSklep"

    def test_seller_as_dict_login_extracted(self):
        item = {
            "seller": {"login": "FarbyPL", "rating": 4.9},
            "title": "Pedzle artystyczne",
        }
        place = ApifyAllegroSource._normalize(item)
        assert place.name == "FarbyPL"
        assert place.rating == 4.9

    def test_product_title_in_notes_for_llm_context(self):
        item = {
            "title": "Sztaluga drewniana 160cm",
            "seller": "MalarskiSklep",
        }
        place = ApifyAllegroSource._normalize(item)
        # Tytul produktu w notes - dla LLM relevance (zeby wiedzial co
        # sprzedawca w ogole sprzedaje)
        assert "Sztaluga" in (place.notes or "")
        assert "produkt:" in (place.notes or "")

    def test_no_seller_falls_back_to_placeholder(self):
        item = {"title": "Pedzel"}
        place = ApifyAllegroSource._normalize(item)
        assert place.name == "(sprzedawca Allegro)"
        assert place.website is None


class TestNormalizeProfileScraper:
    """contactminerlabs - profile scraper, zwraca {email, title, bio,
    sourceUrl}. Title to nazwa profilu sprzedawcy."""

    def test_profile_title_used_as_name(self):
        item = {
            "title": "Pracownia Artystyczna Anna",
            "email": "anna@pracownia-anna.pl",
            "sourceUrl": "https://allegro.pl/uzytkownik/AnnaPracownia",
            "bio": "Sprzedajemy farby i akcesoria malarskie",
        }
        place = ApifyAllegroSource._normalize(item)
        assert place.name == "Pracownia Artystyczna Anna"
        assert place.email == "anna@pracownia-anna.pl"
        assert place.website == "https://allegro.pl/uzytkownik/AnnaPracownia"


class TestAllegromailFiltering:
    """Maile @allegromail.pl to proxy Allegro - bezuzyteczne dla cold
    mail (lamia ToS + low deliverability). Filtrujemy do None."""

    def test_allegromail_pl_email_filtered(self):
        item = {
            "title": "Sklep XYZ",
            "email": "abc123@allegromail.pl",
            "sourceUrl": "https://allegro.pl/uzytkownik/SklepXYZ",
        }
        place = ApifyAllegroSource._normalize(item)
        assert place.email is None  # alias proxy - odrzucony

    def test_allegromail_com_email_filtered(self):
        item = {"title": "Shop", "email": "xyz@allegromail.com"}
        place = ApifyAllegroSource._normalize(item)
        assert place.email is None

    def test_real_email_preserved(self):
        item = {
            "title": "FarbyPL",
            "email": "kontakt@farbypl.pl",
        }
        place = ApifyAllegroSource._normalize(item)
        assert place.email == "kontakt@farbypl.pl"

    def test_case_insensitive_filter(self):
        item = {"title": "Shop", "email": "abc@AllegroMail.PL"}
        place = ApifyAllegroSource._normalize(item)
        assert place.email is None


class TestSellerLinkRegex:
    """Regex do wyciagniecia sellerLogin z HTML strony oferty Allegro.
    Allegro renderuje link do profilu sprzedawcy w roznych formach
    (relative / absolute, z/bez https) - test pokrywa wszystkie."""

    def test_relative_url_match(self):
        html = '<a href="/uzytkownik/ArtBoxSklep" data-role="seller-link">Sklep</a>'
        m = ApifyAllegroSource._SELLER_LINK_RE.search(html)
        assert m is not None
        assert m.group(1) == "ArtBoxSklep"

    def test_absolute_url_match(self):
        html = '<a href="https://allegro.pl/uzytkownik/FarbyPL_2024">Profil</a>'
        m = ApifyAllegroSource._SELLER_LINK_RE.search(html)
        assert m is not None
        assert m.group(1) == "FarbyPL_2024"

    def test_login_with_hyphen_and_dot(self):
        html = '<a href="/uzytkownik/abc.shop-123">Sklep</a>'
        m = ApifyAllegroSource._SELLER_LINK_RE.search(html)
        assert m.group(1) == "abc.shop-123"

    def test_no_match_returns_none(self):
        html = '<div>nothing here</div>'
        assert ApifyAllegroSource._SELLER_LINK_RE.search(html) is None

    def test_takes_first_match(self):
        # Allegro czasem ma kilka linkow do uzytkownika (np. footer)
        # - bierzemy pierwszy ktory zwykle jest w sekcji "O sprzedawcy"
        html = (
            '<a href="/uzytkownik/FirstSeller">A</a>'
            '<a href="/uzytkownik/SecondSeller">B</a>'
        )
        m = ApifyAllegroSource._SELLER_LINK_RE.search(html)
        assert m.group(1) == "FirstSeller"


class TestParseQuery:
    """parse_query - obsluga 3 modow query string (keyword/category/preset)."""

    def test_keyword_prefix(self):
        mode, value = ApifyAllegroSource._parse_query("keyword:farby akrylowe")
        assert mode == "keyword"
        assert value == "farby akrylowe"

    def test_category_prefix(self):
        url = "https://allegro.pl/kategoria/sztuki-piekne-3148"
        mode, value = ApifyAllegroSource._parse_query(f"category:{url}")
        assert mode == "category"
        assert value == url

    def test_preset_prefix(self):
        mode, value = ApifyAllegroSource._parse_query("preset:sklep_plastyczny")
        assert mode == "preset"
        assert value == "sklep_plastyczny"

    def test_no_prefix_treated_as_keyword(self):
        mode, value = ApifyAllegroSource._parse_query("podobrazie malarskie")
        assert mode == "keyword"
        assert value == "podobrazie malarskie"

    def test_unknown_prefix_treated_as_keyword(self):
        # Edge case: "unknown:foo" - traktuj caly string jako keyword
        mode, value = ApifyAllegroSource._parse_query("unknown:foo")
        assert mode == "keyword"
        assert value == "unknown:foo"
