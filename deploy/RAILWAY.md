# Deploy na Railway

Railway = managed PaaS. Zero Linuxa, każdy `git push` = auto-deploy w ~60s.
Dostajesz HTTPS, healthcheck, restarty na crash, logi w UI - wszystko z pudełka.

**Cena:**
- **Hobby Plan**: $5/mies kredytu (jeśli wykorzystasz, pay-as-you-go ~$5-15/mies za małą apkę)
- **Pro Plan**: $20/mies kredytu + priorytetowe szybsze buildy
- Nasze MVP zmieści się w Hobby ($5/m).

**Plus persistent volume** dla SQLite: +$0.25/GB/mies (czyli ~$0.50/m za zapas).

## Krok 1: Konto Railway

1. https://railway.com/login → **Login with GitHub**
2. Autoryzuj Railway dla swojego konta Github
3. Wybierz plan **Hobby** (wymaga karty, ale nie obciąża dopóki nie wykorzystasz $5 darmowego kredytu)

## Krok 2: Stwórz projekt z repo Github

1. **New Project → Deploy from GitHub repo**
2. Jeśli to pierwszy raz: Railway poprosi o pozwolenie na dostęp do repo
   - **Only select repositories** → wybierz `sowinski-k/artmaker-agent-handlowiec`
   - Install & Authorize
3. Wróć do Railway, wybierz repo `artmaker-agent-handlowiec`
4. Railway od razu zacznie build z `Dockerfile` na branchu `main`. **Zatrzymaj go** klikając Settings → zmień branch:

### Konfiguracja brancha
W panelu projektu → kliknij service → **Settings → Source → Branch**:
- Zmień na `claude/ai-sales-agent-artmaker-n48yh`
- Save

Railway zatrzyma stary deploy i zacznie nowy z właściwego brancha. Build trwa ~3-5 min (pierwszy raz; kolejne ~1-2 min dzięki layer cache).

## Krok 3: Environment variables (sekrety)

W panelu projektu → service `artmaker-agent-handlowiec` → **Variables**:

Wklej te zmienne (klik **Raw Editor**, wklej blok poniżej, edytuj wartości):

```bash
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AIza...
APIFY_API_TOKEN=apify_api_...
GOOGLE_PLACES_API_KEY=AIza...

# Opcjonalnie - actor IDs jeśli używasz Apify Allegro/LinkedIn
APIFY_GMAPS_ACTOR=compass~google-maps-scraper
APIFY_ALLEGRO_ACTOR=
APIFY_LINKEDIN_ACTOR=

# Domyślny provider LLM
LLM_PROVIDER=gemini

# Hasło dostępu do panelu - jedyne zabezpieczenie żeby nikt postronny się nie dostał
APP_PASSWORD=cos-co-zapamietasz-min-12-znakow

# SQLite na persistent volume (krok 4)
DATABASE_URL=sqlite:////data/leads.db
```

**Update Variables** → deploy się automatycznie odpali ponownie z nowymi env vars.

## Krok 4: Persystencja danych - PostgreSQL (zalecam) lub Volume

Bez tego baza ginie przy każdym deploy. Krytyczne. Dwie opcje:

### Opcja 4A: Managed PostgreSQL (zalecam) ⭐

Lepsze długoterminowo (multi-user gotowe, backupy, scale). Cena ~$5/mies.

1. **W widoku projektu** kliknij **"+ Create"** na pustym canvasie (nie wewnątrz service'u, tylko na poziomie projektu)
2. Wybierz **Database → PostgreSQL** (Add PostgreSQL)
3. Railway tworzy service "Postgres" w ~20s
4. W service `artmaker-agent-handlowiec` → **Variables**:
   - Znajdź istniejący `DATABASE_URL` (ten z `sqlite:///...`) i **usuń go** (-)
   - Kliknij **+ New Variable** → **Add Reference** → wybierz service Postgres → wybierz `DATABASE_URL`
   - Save
5. Railway automatycznie:
   - łączy oba service'y w sieci wewnętrznej
   - przekazuje connection string do apki przez env var
   - przy każdym restarcie Postgres'a auto-aktualizuje URL w apce (zero-downtime przy roli rebootów)
6. Po redeploy apka łączy się z Postgres, tabele tworzą się automatycznie przez `init_db()`

> **Gotowe!** Baza persistent, masz UI w Railway do podglądu tabel + backupy.

### Opcja 4B: Volume + SQLite (taniej, ale wolniej dorastasz)

Tylko jeśli z jakiegoś powodu volumes Ci się nie chce zostawiać Postgresa. ~$0.50/mies.

W widoku projektu → "+ Create" → **Volume** (jeśli widoczne)
- Mount path: `/data`
- Size: **1 GB**
- Attach do `artmaker-agent-handlowiec`

W Variables: ustaw `DATABASE_URL=sqlite:////data/leads.db` (cztery slashe = absolutna ścieżka).

> Jeśli **Volume nie widać w UI** Railway (czasami zachowują tylko dla Pro plan), użyj Opcji 4A.

## Krok 5: Wygeneruj domenę

Railway domyślnie nie wystawia publicznego URL. Musisz włączyć:

Service → **Settings → Networking → Generate Domain**

Dostaniesz coś typu `artmaker-agent-handlowiec-production.up.railway.app`. **HTTPS out-of-the-box**.

## Krok 6: Otwórz panel

Idź pod URL który dostałeś. Zobaczysz prompt "🔒 Podaj hasło" — wpisz to co ustawiłeś w `APP_PASSWORD`. Powinno wpuścić.

Apka działa.

## Workflow Claude Code → produkcja

Z **Railway jest ŁATWIEJ niż VPS**:

1. Rozmawiamy tutaj
2. Ja commituję na branch `claude/ai-sales-agent-artmaker-n48yh`
3. Railway wykrywa push i **automatycznie buduje i deployuje w ~60-120s**
4. Stary container chodzi do momentu aż nowy przejdzie healthcheck, potem swap (zero-downtime)

Nie ma cron'a, nie ma SSH, wszystko sterowane Github + Railway UI.

## Co widzisz w panelu Railway

- **Deployments**: historia builds + deploy events
- **Logs**: live logi z apki (kliknij build → Deploy Logs / Build Logs)
- **Metrics**: CPU, RAM, network usage (przydatne gdy myślisz o skalowaniu)
- **Variables**: env vars (edycja = redeploy)
- **Settings → Resources**: limit RAM/CPU per service (skalowanie pionowe)

## Nightly discovery cron

Railway nie ma natywnego cron'a w Hobby plan. Trzy opcje:

### Opcja A: GitHub Actions cron (zalecam, zero kosztu Railway)
Już mamy `.github/workflows/nightly-discovery.yml` (z poprzedniego setupu). Działa równolegle:
- GitHub Actions co noc o 03:00 UTC odpala swój runner
- Runner ma `DATABASE_URL` z secrets → pisze do TEGO SAMEGO Postgres co Railway (musisz przerzucić z SQLite na Postgres)
- Lub: prościej, raz w tygodniu ręcznie odpalasz lokalnie / przez "workflow_dispatch"

### Opcja B: Drugi service na Railway "Cron"
Railway ma feature "Cron Jobs" w Settings:
- Settings → Service → **Cron Schedule** → wpisz `0 3 * * *` (codziennie 03:00 UTC)
- Override start command: `python -m scripts.nightly_discovery --max 50`
- Railway tworzy short-lived container który odpala skrypt i kończy
- **Koszt: ~$0.10 / run** (5-10 min runtime)

### Opcja C: Cron-job.org (free external)
https://cron-job.org → free cron który hituje URL co X. Zrobić endpoint `/api/run-nightly` w Streamlit z auth → external cron go odpala. Najmniej eleganckie ale działa.

**Polecam A** - już mamy workflow w repo, wystarczy dodać Railway DATABASE_URL do GitHub Secrets i włączyć cron w `.github/workflows/`.

## Skalowanie

W panelu service → **Settings → Resources**:

| Stan | Plan Railway | Cena |
|---|---|---|
| **MVP teraz** | Hobby ($5/m kredyt) + Volume | ~$5-7/mies |
| Wzrost | Hobby + większy RAM (8GB cap) | ~$10-15/mies |
| Pro / SaaS | Pro Plan ($20/m kredyt) + horizontal scale | ~$25-40/mies |

**Postgres zamiast SQLite** gdy SaaS dla wielu klientów:
- Service → **+ New → Database → PostgreSQL**
- Railway daje `DATABASE_URL` jako env var automatycznie
- Wystarczy zmienić env var w app service, kod (SQLAlchemy) działa bez zmian

## Co jeśli build pada?

W panelu service → **Deployments** → kliknij failed deploy → **View Logs**.

Najczęstsze:
- **"requirements not found"**: sprawdź czy `requirements.txt` jest w korzeniu repo (powinien być)
- **"port not bound"**: Railway czeka aż coś nasłucha na `$PORT`. Sprawdź czy Dockerfile używa `${PORT}` (powinien)
- **"healthcheck timeout"**: Streamlit za długo wstaje. Zwiększ `healthcheckTimeout` w `railway.toml`

Wklej mi logi - znajdziemy.

## Migracja Hetzner ↔ Railway

Jeśli kiedyś zmienisz zdanie - oba setupy są **niezależne**:
- Pliki Hetzner (`deploy/install.sh`, `update.sh`, `artmaker.service`, `nginx.conf`) nie są używane przez Railway
- Pliki Railway (`Dockerfile`, `railway.toml`, `.dockerignore`) nie są używane przez Hetzner (install.sh ich nawet nie tknie)

Kod aplikacji jest 100% portowalny. Możesz mieć obie wersje równolegle.

## Co dalej

Daj znać URL który dostałeś od Railway, lub jak build pada wklej mi link do logów (lub błąd) — naprawimy.
