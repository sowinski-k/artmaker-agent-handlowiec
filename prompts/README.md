# Prompts

Warstwa promptowa agenta. To najważniejsza część projektu pod kątem jakości
maili — kod jest tu w pomocniczej roli.

## Pliki (do uzupełnienia)

- `research_prompt.md` — system prompt do oceny i wzbogacania leadów.
- `generate_prompt.md` — system prompt do generowania snippetów maila.
- `few_shot_examples/` — prawdziwe cold maile napisane ręcznie przez
  właściciela. **Krytyczne dla jakości.** Bez nich Claude defaultuje do
  generycznego korpo-AI-stylu.

## Format few-shot przykładu

Jeden plik na przykład, nazwany `<segment>_<numer>.md`, np.
`paint_and_sip_01.md`.

Treść pliku:

    Subject: <linia tematu>
    Segment: <id segmentu, np. paint_and_sip>
    Lead context: <2-3 linie tłumaczące, co było wyjątkowego w tym leadzie —
    żeby agent wiedział, kiedy ten przykład pasuje>
    ---
    <sama treść maila po polsku, naturalny głos właściciela, z wszystkimi
    naturalnymi niedoskonałościami: krótszymi zdaniami, urwanymi myślami,
    naturalnym rytmem>

## Cel

Minimum 2-3 przykłady na segment zanim ruszymy z generowaniem na skalę.
Te przykłady są jedynym źródłem "głosu" dla Claude'a — ich jakość
bezpośrednio przekłada się na jakość wszystkich wygenerowanych maili.
