# Deploy na Hetzner Cloud

Krok po kroku setup serwera Hetzner Cloud + zainstalowanie Artmaker Agent.
Total time: ~20 minut, ~17 zł/mies za hosting.

## Co dostajesz na końcu

- Publiczny URL `http://<IP>` z apką Streamlit
- Login/hasło żeby przypadkowy bot się nie dostał
- **Auto-update z Githuba co 2 minuty** - committujesz tutaj, w 2 min jest na produkcji
- Nightly discovery cron uruchamiający `scripts.nightly_discovery` codziennie o 03:00 UTC
- SQLite baza która **przeżywa restart serwera** (czego Streamlit Cloud nie umiał)

## Krok 1: Załóż konto Hetzner Cloud

1. Wejdź: https://accounts.hetzner.com/signUp
2. Zarejestruj się (email + hasło, weryfikacja jest tradycyjna - skan dowodu albo karta).
   Hetzner robi KYC bo niektórzy nadużywali do crypto-mining. Trwa ~15 min do 24h.
3. Po zatwierdzeniu zaloguj się na https://console.hetzner.cloud
4. **New project** → nazwa "artmaker" → Create

> Tip: jeśli czekanie na KYC Cię irytuje, alternatywa: **DigitalOcean** (instant signup, $200 kredytu na pierwsze 2 miesiące, ale 50% droższe niż Hetzner długoterminowo). Ten installer powinien też tam działać; testowany na Hetzner.

## Krok 2: Dodaj SSH key (z lokalnego komputera)

Hetzner musi wiedzieć jak Cię puścić na serwer.

### Jeśli masz już SSH key (Mac/Linux/WSL):

```bash
cat ~/.ssh/id_ed25519.pub
# albo
cat ~/.ssh/id_rsa.pub
```

Skopiuj output.

### Jeśli NIE masz SSH key:

```bash
ssh-keygen -t ed25519 -C "twoj-email@example.com"
# enter, enter, enter (zostaw domyślne)
cat ~/.ssh/id_ed25519.pub
```

### Wklej do Hetzner:

W panelu Hetzner: **Security → SSH Keys → Add SSH Key** → wklej → nazwa "moj-laptop" → Save.

## Krok 3: Utwórz serwer

W panelu Hetzner: **Servers → New Server**

| Pole | Wartość |
|---|---|
| Location | **Helsinki (Finlandia)** lub Falkenstein (Niemcy) - obie OK, latencja z PL ~25-35ms |
| Image | **Ubuntu 24.04** |
| Type | **CX22** (2 vCPU, 4 GB RAM, 40 GB SSD) - 4€/mies |
| Networking | IPv4 + IPv6 (domyślnie zaznaczone) |
| SSH Keys | Zaznacz ten który dodałeś w kroku 2 |
| Name | `artmaker` |

→ **Create & Buy now**

Po ~10 sekundach dostaniesz **IP serwera** (np. `135.181.234.56`). **Zapisz to IP.**

## Krok 4: Zaloguj się na serwer

Z lokalnego terminala:

```bash
ssh root@<IP_SERWERA>
```

Pierwsze logowanie zapyta "Are you sure you want to continue connecting?" → wpisz `yes` → Enter.

Powinieneś zobaczyć prompt:
```
root@artmaker:~#
```

## Krok 5: Uruchom installer

Skopiuj-wklej tę komendę na serwerze (zauważ — używamy publicznego URL repo, więc nie wymaga deploy key na tym etapie):

```bash
curl -fsSL https://raw.githubusercontent.com/sowinski-k/artmaker-agent-handlowiec/claude/ai-sales-agent-artmaker-n48yh/deploy/install.sh -o /tmp/install.sh && bash /tmp/install.sh
```

> Jeśli repo jest prywatne i `curl` zwraca 404 — pobierz `install.sh` na lokalny komputer (z Github → raw → save) i skopiuj na serwer: `scp install.sh root@<IP>:/tmp/install.sh && ssh root@<IP> "bash /tmp/install.sh"`.

Installer:
1. Zainstaluje paczki (Python, nginx, ufw...) — ~2 min
2. Wygeneruje **deploy key SSH** dla Github i wypisze go w terminalu
3. **Zatrzyma się** i powie: "wklej ten klucz tutaj: https://github.com/sowinski-k/artmaker-agent-handlowiec/settings/keys/new"
   - Otwórz link w przeglądarce
   - Title: `Hetzner deploy`
   - Allow write access: **NIE** (read-only wystarczy do pulla)
   - Wklej klucz w pole "Key"
   - **Add key**
4. Wróć do terminala SSH, naciśnij Enter
5. Installer poprosi o klucze API: ANTHROPIC, GEMINI, APIFY (opcjonalne), Google Places (opcjonalne)
6. Installer poprosi o login/hasło do panelu webowego (basic auth)
7. ~5 minut konfiguruje resztę

Na końcu zobaczysz:
```
✓ Instalacja zakończona.
Panel webowy: http://135.181.234.56/
```

## Krok 6: Sprawdź apkę

Otwórz `http://<IP_SERWERA>` w przeglądarce. Zobaczysz okienko basic auth — wpisz login/hasło które ustawiłeś. Apka powinna się otworzyć w ciągu ~5 sekund.

## Workflow Claude Code → produkcja

Od teraz:
1. Rozmawiamy tutaj na Claude Code
2. Ja commituję na branch `claude/ai-sales-agent-artmaker-n48yh`
3. Cron na serwerze co 2 min sprawdza Github, pulluje, restartuje
4. W max 2 min jest na produkcji

Jak chcesz wymusić deploy NATYCHMIAST (zamiast czekać 2 min):

```bash
ssh root@<IP> "/opt/artmaker/repo/deploy/update.sh"
```

## Częste operacje (jako root na serwerze)

```bash
# Status apki
systemctl status artmaker

# Restart apki (po edycji secrets)
systemctl restart artmaker

# Live logi apki
journalctl -u artmaker -f

# Logi auto-update
tail -f /opt/artmaker/logs/update.log

# Logi nightly discovery
tail -f /opt/artmaker/logs/nightly.log

# Ręczny update z Githuba
/opt/artmaker/repo/deploy/update.sh

# Ręczny nightly discovery
sudo -u artmaker /opt/artmaker/venv/bin/python -m scripts.nightly_discovery --max 20

# Edycja sekretów (potem `systemctl restart artmaker`)
nano /opt/artmaker/secrets.env

# Zmiana hasła do panelu
htpasswd /etc/nginx/.htpasswd_artmaker admin
systemctl reload nginx
```

## Skalowanie - jak baza/użycie rośnie

Wszystko klikiem w panelu Hetzner: **Servers → artmaker → Rescale**.

| Stan | Plan | Cena |
|---|---|---|
| MVP (teraz) | CX22 - 2vCPU/4GB | 4€/m |
| 1k-10k leadów, kilkoro userów | CX32 - 4vCPU/8GB | 8€/m |
| 10k+ leadów, dziesiątki userów | CX42 - 8vCPU/16GB | 17€/m |
| SaaS dla wielu klientów | CCX33 + managed Postgres | 50€/m |

Rescale wymaga restartu serwera (~1 min downtime), ale **dane są bezpieczne** — dysk SSD się nie zmienia.

## Backup bazy

SQLite w `/opt/artmaker/data/leads.db`. Backup raz dziennie:

```bash
sudo -u artmaker sqlite3 /opt/artmaker/data/leads.db ".backup /opt/artmaker/data/leads-$(date +%F).db"
```

Możesz dodać do crontab. Dla MVP wystarczy Hetzner Cloud Backups (4 EUR/mies dodatkowo, **automatyczne snapshoty całego dysku codziennie, trzymane 7 dni**) — włącz w panelu: serwer → **Backups → Enable**.

## Dorzucenie domeny (gdy będziesz miał)

1. Kup domenę (Cloudflare Registrar, nazwa.pl, OVH — co wolisz)
2. W panelu domeny ustaw rekord A: `artmaker.twojadomena.pl → <IP_SERWERA>`
3. Poczekaj ~5 min na propagację DNS
4. Na serwerze:
   ```bash
   apt install certbot python3-certbot-nginx
   certbot --nginx -d artmaker.twojadomena.pl
   ```
   Certbot poprosi o email, zaakceptujesz TOS, on sam podmieni nginx config żeby gadał HTTPS.
5. Edytuj `/etc/nginx/sites-available/artmaker` — w `server { ... }` zmień `server_name _;` na `server_name artmaker.twojadomena.pl;`
6. `nginx -t && systemctl reload nginx`

Gotowe — `https://artmaker.twojadomena.pl` z prawdziwym SSL.

## Troubleshooting

**Apka nie wstaje:**
```bash
journalctl -u artmaker -n 100
# Często: brakuje klucza API, albo Streamlit nie znalazł requirements
```

**"502 Bad Gateway" w przeglądarce:**
Streamlit nie chodzi. `systemctl restart artmaker` i poczekaj 5 sek.

**Auto-update nie działa:**
```bash
sudo -u artmaker /opt/artmaker/repo/deploy/update.sh
# Jak rzuca błąd - debug. Najczęściej: deploy key bez dostępu do repo.
```

**Hetzner Cloud panel mówi "out of stock" dla CX22:**
Wybierz inny location (Falkenstein zamiast Helsinki, lub odwrotnie).

**Chcesz wszystko wyczyścić i zacząć od nowa:**
W Hetzner: **Servers → artmaker → ... → Delete**. Tracisz wszystkie dane, ale instaluje się od zera za 5 min.
