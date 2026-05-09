"""Centralny kontekst marki Artmaker - używany przez wszystkie LLM-owe komponenty
(filtr trafności discovery, research agent, generowanie maili) żeby wszędzie
trzymać tę samą narrację o tym kim jesteśmy, jakich klientów szukamy i którą
z dwóch ścieżek sprzedaży zaproponować.
"""

BRAND_CONTEXT: str = """\
Artmaker - polski producent i importer artykułów plastycznych, kreatywnych,
DIY i papierniczo-biurowych. Działamy w modelu B2B na DWÓCH ścieżkach
sprzedaży, dopasowanych do skali i potrzeb klienta.

## ŚCIEŻKA A: Private label / OEM z fabryk w Chinach

Dla klientów z planem na własną markę albo dużym wolumenem.

- Mamy zakontraktowane sprawdzone fabryki w Chinach ("fabryka świata"),
  dzięki czemu produkujemy farby, sztalugi, płótna, pędzle, akcesoria DIY
  pod specyfikację klienta w cenach producenta - 30-50% taniej niż polska
  hurtownia.
- Robimy personalizowane opakowania, etykiety, branding i kolekcje pod
  marka własną klienta (white-label / private label).
- Skala: typowo MOQ 300-1000 sztuk, lead time 4-8 tygodni produkcji + transport.

Idealni klienci dla TRACK A:
- Sieci sklepów detalicznych chcące własnej marki w niższym pułapie cenowym
- Marki produkujące zestawy kreatywne / boxy subskrypcyjne
- Dystrybutorzy szukający kontraktu produkcyjnego pod ich brand
- Hurtownie z wolumenem co najmniej kilkaset sztuk SKU/miesiąc

## ŚCIEŻKA B: Panel B2B Artmaker (magazyn PL, dostawa 24h)

Dla klientów którzy potrzebują towaru OD RĘKI bez czekania na produkcję.

- Stała oferta produktów plastycznych, kreatywnych i papierniczych dostępna
  na magazynie w Polsce - można zamówić od 1 sztuki / kartonu, ze stocku.
- Dostawa 24h, ceny hurtowe od producenta (i tak taniej niż polska
  hurtownia bo my omijamy pośredników).
- Dedykowany panel B2B z aktualnym stanem magazynowym i historią zamówień.
- Bez minimum zamówienia w wartości premium / bez czekania na produkcję.

Idealni klienci dla TRACK B:
- Sklepy plastyczne, papiernicze, biurowe z szybką rotacją asortymentu
- Studia paint & sip, pracownie malarstwa, szkoły artystyczne zużywające
  materiały konsumpcyjnie (kupują regularnie, niewielkie ilości naraz)
- Firmy organizujące warsztaty kreatywne / animatorzy / urodziny - kupują
  pod konkretne wydarzenie, potrzebują na już
- Sklepy hobbystyczne, biurowo-papiernicze rozszerzające ofertę o plastykę
- Mniejsi sprzedawcy e-commerce, dropshipperzy

## Jak wybrać między A i B dla danego leada

Domyślnie TRACK B (większy adresowalny rynek, niższy próg wejścia, łatwiej
zamknąć pierwszą transakcję). TRACK A tylko wtedy gdy lead jasno sygnalizuje:
sieć sklepów, własna marka w pipeline'ie, duży wolumen, gotowość czekać na
produkcję.

W cold mailu MOŻNA zasugerować obie opcje, ale jako PROPOZYCJĘ-KOLEJNOŚĆ:
najpierw to co mu pasuje TERAZ (zwykle B), Track A jako "przy okazji,
gdybyście kiedyś chcieli rozwinąć własną markę".

## Kogo NIE szukamy

- Firmy spoza branży artystyczno-kreatywnej-papierniczej: motoryzacja, AGD,
  supermarkety spożywcze, apteki, sklepy medyczne, zoologiczne, sklepy
  spożywcze, sklepy odzieżowe.
- Jednoosobowe stoiska bazarowe bez stałego adresu / e-commerce / planów.
- Ogólne sklepy przemysłowe ("wszystko od szpilki po lokomotywę") bez
  wyraźnej kategorii kreatywnej / papierniczej.
"""
