"""Centralny kontekst marki Artmaker — używany przez wszystkie LLM-owe komponenty
(filtr trafności discovery, research agent, generowanie maili) żeby wszędzie
trzymać tę samą narrację o tym kim jesteśmy i jakich klientów szukamy.
"""

BRAND_CONTEXT: str = """\
Artmaker — polski producent i importer artykułów plastycznych, kreatywnych i
DIY pod własną marką oraz pod private label.

CO ROBIMY:
- Mamy zakontraktowane sprawdzone fabryki w Chinach ("fabryka świata"),
  dzięki czemu oferujemy najkorzystniejsze ceny rynkowe na produkty plastyczne
  (farby, sztalugi, płótna, pędzle, materiały dla rękodzieła, akcesoria DIY).
- Produkujemy i importujemy pod specyfikację klienta — od 1 SKU do pełnych
  kolekcji.
- Robimy personalizowane opakowania, branding i marki własne (white-label /
  private label) dla sklepów i operatorów detalicznych.
- Skala B2B: hurt, kontrakt produkcyjny, OEM/ODM.

KOGO SZUKAMY (idealny lead):
- Sklepy plastyczne, papiernicze, artystyczne (stacjonarne i e-commerce) —
  potrzebują tańszego źródła towaru lub własnej marki.
- Studia paint & sip, pracownie malarstwa, kursy online — zużywają farby,
  płótna, sztalugi w hurtowych ilościach.
- Firmy organizujące warsztaty kreatywne dla dzieci, animatorzy, szkoły
  artystyczne — duża rotacja materiałów.
- Marki własne, dystrybutorzy, sieci handlowe — chcą private label.

KOGO NIE SZUKAMY:
- Firmy spoza branży artystyczno-kreatywnej (motoryzacja, AGD, supermarkety,
  apteki, sklepy medyczne, zoologiczne, ogólne sklepy przemysłowe).
- Detalista bez skali (jednoosobowy sklepik bez e-commerce, bez warsztatów,
  bez planów rozwoju).
"""
