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
  dzięki czemu produkujemy farby, sztalugi, płótna, pędzle, akcesoria DIY,
  papier kreatywny, dziurkacze, washi tape, w zasadzie wszystko z naszej
  branży, pod specyfikację klienta w cenach producenta - typowo 30-50%
  taniej niż polska hurtownia (czasem więcej, czasem mniej - zależy od
  produktu i wolumenu).
- Robimy personalizowane opakowania, etykiety, branding i kolekcje pod
  marką własną klienta (white-label / private label). Różne poziomy
  jakości - klient wybiera.
- **Skala / MOQ: BARDZO różne w zależności od produktu i stopnia
  personalizacji.** Dla wysoko spersonalizowanych / handmade rzeczy może
  to być nawet kilka-kilkanaście sztuk. Dla standardowych produktów z
  brandingiem - kilkaset. Dla pełnej produkcji od zera ze swoim packagingiem
  - kilka tysięcy. **NIGDY nie podajemy konkretnej liczby MOQ z głowy w
  cold mailu - to wycenia się indywidualnie po znajomości produktu i
  oczekiwań klienta.**
- Lead time też zależny - od kilku tygodni dla standardowych zamówień do
  kilku miesięcy dla rozbudowanych kolekcji. Nie sztywne ramy w mailu.

Idealni klienci dla TRACK A:
- Sieci sklepów detalicznych chcące własnej marki w niższym pułapie cenowym
- Marki produkujące zestawy kreatywne / boxy subskrypcyjne
- Dystrybutorzy szukający kontraktu produkcyjnego pod ich brand
- Hurtownie z regularnym wolumenem
- Małe marki / startup'y chcące zacząć od małej partii brandowanej

## ŚCIEŻKA B: Panel B2B SOWINS (magazyn PL, dostawa 24h)

Dla klientów którzy potrzebują towaru OD RĘKI bez czekania na produkcję.

- Stała oferta produktów plastycznych, kreatywnych i papierniczych, i nie tylko dostępna
  na magazynie w Polsce - towar wysyłamy w 24h od złożenia zamówienia.
- Ceny hurtowe od producenta (omijamy pośredników, więc taniej niż polska
  hurtownia).
- Dedykowany panel B2B online: **https://b2b.sowins.pl** - aktualny stan
  magazynowy, ceny po zalogowaniu, historia zamówień, e-faktury.
- **Minimum logistyczne: 1000 zł netto** na zamówienie.
- **Dostawa GRATIS** przy zamówieniach od minimum (1000 zł netto) - my
  pokrywamy koszt transportu kurierskim na terenie PL.
- Bez czekania na produkcję (vs Track A gdzie jest 4-8 tygodni lead time).

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
