#!/usr/bin/env bash
# Artmaker Agent - one-shot installer for fresh Hetzner Cloud Ubuntu 24.04.
#
# Idempotent: można odpalić wielokrotnie, naprawi co trzeba.
#
# Wymagania:
#   - świeży serwer Hetzner Cloud (CX22 lub większy), Ubuntu 24.04 LTS
#   - uruchomione jako root (Hetzner daje login root domyślnie)
#   - publiczne SSH na port 22 (Hetzner daje out-of-the-box)
#
# Co robi:
#   1. apt update + niezbędne paczki (python3.12, git, nginx, ufw, htpasswd...)
#   2. tworzy systemowego usera 'artmaker' (apka pod nim chodzi, nie root)
#   3. generuje SSH deploy key dla Github i czeka aż wkleisz go do repo
#   4. klonuje repo + zakłada venv + pip install
#   5. interaktywnie pyta o klucze API i hasło panelu - zapisuje do /opt/artmaker/secrets.env
#   6. konfiguruje nginx reverse proxy (port 80 -> 8501) + basic auth
#   7. tworzy systemd unit dla Streamlit i go uruchamia
#   8. konfiguruje ufw (allow 22, 80)
#   9. dodaje crontaby: auto-update co 2 min + nightly discovery 03:00
#  10. wypisuje URL z którego korzystasz

set -euo pipefail

# ============================================================
# Konfiguracja
# ============================================================
REPO_HTTPS="https://github.com/sowinski-k/artmaker-agent-handlowiec.git"
REPO_SSH="git@github.com:sowinski-k/artmaker-agent-handlowiec.git"
BRANCH="claude/ai-sales-agent-artmaker-n48yh"
APP_USER="artmaker"
APP_DIR="/opt/artmaker"
REPO_DIR="$APP_DIR/repo"
VENV_DIR="$APP_DIR/venv"
SECRETS_FILE="$APP_DIR/secrets.env"
HTPASSWD_FILE="/etc/nginx/.htpasswd_artmaker"

# Kolory żeby było czytelnie
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${BLUE}[$(date +%H:%M:%S)]${NC} $*"; }
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
die()  { echo -e "${RED}✗ $*${NC}" >&2; exit 1; }

# ============================================================
# Pre-flight
# ============================================================
[[ $EUID -eq 0 ]] || die "Uruchom jako root (sudo -i, potem ./install.sh)."
[[ -f /etc/os-release ]] && grep -q "Ubuntu" /etc/os-release || die "Skrypt jest na Ubuntu 24.04. Wykryto co innego."

log "Artmaker Agent installer startuje. Plan na ~10 minut."
echo

# ============================================================
# 1. System packages
# ============================================================
log "Instaluję systemowe paczki..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    python3.12 python3.12-venv python3-pip \
    git nginx ufw apache2-utils \
    cron curl
ok "Paczki zainstalowane."

# ============================================================
# 2. Application user
# ============================================================
if ! id "$APP_USER" &>/dev/null; then
    useradd --system --create-home --home-dir "$APP_DIR" --shell /bin/bash "$APP_USER"
    ok "User '$APP_USER' utworzony."
else
    ok "User '$APP_USER' już istnieje."
fi
mkdir -p "$APP_DIR"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# ============================================================
# 3. SSH deploy key for Github (do prywatnych repo i pull)
# ============================================================
SSH_DIR="$APP_DIR/.ssh"
KEY_FILE="$SSH_DIR/github_deploy"
sudo -u "$APP_USER" mkdir -p "$SSH_DIR"
sudo -u "$APP_USER" chmod 700 "$SSH_DIR"

if [[ ! -f "$KEY_FILE" ]]; then
    log "Generuję deploy key SSH..."
    sudo -u "$APP_USER" ssh-keygen -t ed25519 -f "$KEY_FILE" -N "" -C "artmaker-deploy@$(hostname)" -q
    ok "Deploy key wygenerowany."
fi

# SSH config dla github.com - używaj tego konkretnego klucza
sudo -u "$APP_USER" tee "$SSH_DIR/config" > /dev/null <<EOF
Host github.com
  HostName github.com
  User git
  IdentityFile $KEY_FILE
  StrictHostKeyChecking no
  UserKnownHostsFile /dev/null
EOF
sudo -u "$APP_USER" chmod 600 "$SSH_DIR/config"

echo
echo "============================================================"
echo -e "${YELLOW}WAŻNE - dodaj deploy key do Github:${NC}"
echo "============================================================"
echo "1. Otwórz: https://github.com/sowinski-k/artmaker-agent-handlowiec/settings/keys/new"
echo "2. Title:    'Hetzner deploy $(hostname)'"
echo "3. Allow write access: NIE (read-only wystarczy)"
echo "4. Wklej poniższy klucz w pole 'Key':"
echo
echo -e "${GREEN}$(cat $KEY_FILE.pub)${NC}"
echo
read -p "Po dodaniu - naciśnij ENTER żeby kontynuować..."
echo

# ============================================================
# 4. Clone repo
# ============================================================
if [[ ! -d "$REPO_DIR/.git" ]]; then
    log "Klonuję repo (branch: $BRANCH)..."
    sudo -u "$APP_USER" git clone --branch "$BRANCH" "$REPO_SSH" "$REPO_DIR" \
        || die "Klonowanie nie poszło. Sprawdź czy deploy key jest dodany do Github."
    ok "Repo sklonowane do $REPO_DIR."
else
    log "Repo już istnieje, fetch + reset do $BRANCH..."
    sudo -u "$APP_USER" -H bash -c "cd $REPO_DIR && git fetch origin && git checkout $BRANCH && git reset --hard origin/$BRANCH"
    ok "Repo zaktualizowane."
fi

# ============================================================
# 5. Python venv + dependencies
# ============================================================
if [[ ! -d "$VENV_DIR" ]]; then
    log "Tworzę venv..."
    sudo -u "$APP_USER" python3.12 -m venv "$VENV_DIR"
    ok "Venv utworzony."
fi
log "Instaluję zależności Python (może chwilę potrwać)..."
sudo -u "$APP_USER" "$VENV_DIR/bin/pip" install --quiet --upgrade pip
sudo -u "$APP_USER" "$VENV_DIR/bin/pip" install --quiet -r "$REPO_DIR/requirements.txt"
ok "Zależności zainstalowane."

# ============================================================
# 6. Secrets - interaktywny prompt
# ============================================================
if [[ ! -f "$SECRETS_FILE" ]]; then
    echo
    echo "============================================================"
    echo "Konfiguracja sekretów - wpisz klucze API."
    echo "Możesz zostawić puste i uzupełnić później w $SECRETS_FILE."
    echo "============================================================"

    read -p "ANTHROPIC_API_KEY: " ANTHROPIC_KEY
    read -p "GEMINI_API_KEY: " GEMINI_KEY
    read -p "APIFY_API_TOKEN (opcjonalne, ENTER żeby pominąć): " APIFY_KEY
    read -p "GOOGLE_PLACES_API_KEY (opcjonalne, ENTER żeby pominąć): " PLACES_KEY

    LLM_PROVIDER="gemini"
    read -p "LLM_PROVIDER [gemini/anthropic, domyślnie gemini]: " LLM_INPUT
    [[ -n "$LLM_INPUT" ]] && LLM_PROVIDER="$LLM_INPUT"

    cat > "$SECRETS_FILE" <<EOF
# Sekrety Artmaker Agent. Plik czytany przez systemd przy starcie.
# chmod 600 - tylko user artmaker może czytać.
ANTHROPIC_API_KEY=$ANTHROPIC_KEY
GEMINI_API_KEY=$GEMINI_KEY
APIFY_API_TOKEN=$APIFY_KEY
GOOGLE_PLACES_API_KEY=$PLACES_KEY
LLM_PROVIDER=$LLM_PROVIDER
DATABASE_URL=sqlite:///$APP_DIR/data/leads.db
EOF
    chown "$APP_USER:$APP_USER" "$SECRETS_FILE"
    chmod 600 "$SECRETS_FILE"
    ok "Sekrety zapisane (chmod 600)."
else
    ok "Sekrety już istnieją w $SECRETS_FILE - nie nadpisuję."
fi

# DB directory
sudo -u "$APP_USER" mkdir -p "$APP_DIR/data" "$APP_DIR/logs"

# ============================================================
# 7. Basic auth dla nginx
# ============================================================
if [[ ! -f "$HTPASSWD_FILE" ]]; then
    echo
    read -p "Login do panelu webowego (domyślnie 'admin'): " WEB_USER
    [[ -z "$WEB_USER" ]] && WEB_USER="admin"
    read -s -p "Hasło do panelu (zapamiętaj!): " WEB_PASS
    echo
    htpasswd -bc "$HTPASSWD_FILE" "$WEB_USER" "$WEB_PASS" > /dev/null
    chmod 640 "$HTPASSWD_FILE"
    chown root:www-data "$HTPASSWD_FILE"
    ok "Basic auth skonfigurowane (user: $WEB_USER)."
else
    ok "Plik htpasswd już istnieje - nie nadpisuję."
fi

# ============================================================
# 8. Nginx config
# ============================================================
log "Konfiguruję nginx..."
install -m 644 "$REPO_DIR/deploy/nginx.conf" /etc/nginx/sites-available/artmaker
ln -sf /etc/nginx/sites-available/artmaker /etc/nginx/sites-enabled/artmaker
rm -f /etc/nginx/sites-enabled/default
nginx -t > /dev/null 2>&1 || die "Nginx config invalid - sprawdź /etc/nginx/sites-available/artmaker."
systemctl restart nginx
systemctl enable nginx --now > /dev/null
ok "Nginx skonfigurowany i uruchomiony."

# ============================================================
# 9. Systemd unit dla Streamlit
# ============================================================
log "Instaluję systemd unit..."
install -m 644 "$REPO_DIR/deploy/artmaker.service" /etc/systemd/system/artmaker.service
systemctl daemon-reload
systemctl enable artmaker.service > /dev/null 2>&1
systemctl restart artmaker.service
sleep 3
if systemctl is-active --quiet artmaker.service; then
    ok "Artmaker service działa."
else
    warn "Service nie wstał - sprawdź: journalctl -u artmaker.service -n 50"
fi

# ============================================================
# 10. Firewall (ufw)
# ============================================================
log "Konfiguruję firewall..."
ufw --force reset > /dev/null
ufw default deny incoming > /dev/null
ufw default allow outgoing > /dev/null
ufw allow 22/tcp comment 'SSH' > /dev/null
ufw allow 80/tcp comment 'HTTP' > /dev/null
ufw --force enable > /dev/null
ok "Firewall: 22 + 80 otwarte, reszta zamknięta."

# ============================================================
# 11. Cron - auto-update co 2 min + nightly discovery 03:00 UTC
# ============================================================
log "Konfiguruję crontab..."
CRON_TMP=$(mktemp)
crontab -u "$APP_USER" -l 2>/dev/null > "$CRON_TMP" || true
# Idempotent - usuń stare wpisy artmaker przed dodaniem
grep -v "artmaker-cron" "$CRON_TMP" > "${CRON_TMP}.clean" || true
mv "${CRON_TMP}.clean" "$CRON_TMP"
cat >> "$CRON_TMP" <<EOF
*/2 * * * * $REPO_DIR/deploy/update.sh >> $APP_DIR/logs/update.log 2>&1 # artmaker-cron
0 3 * * *   cd $REPO_DIR && $VENV_DIR/bin/python -m scripts.nightly_discovery --max 50 >> $APP_DIR/logs/nightly.log 2>&1 # artmaker-cron
EOF
crontab -u "$APP_USER" "$CRON_TMP"
rm -f "$CRON_TMP"
ok "Cron: auto-update co 2 min, nightly discovery codziennie 03:00 UTC."

# ============================================================
# 12. Done
# ============================================================
SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
echo
echo "============================================================"
echo -e "${GREEN}✓ Instalacja zakończona.${NC}"
echo "============================================================"
echo
echo "Panel webowy: http://$SERVER_IP/"
echo "Logowanie:    user/hasło które wpisałeś przy basic auth"
echo
echo "Przydatne komendy (jako root):"
echo "  systemctl status artmaker         # status apki"
echo "  systemctl restart artmaker        # restart apki"
echo "  journalctl -u artmaker -f         # live logi"
echo "  tail -f $APP_DIR/logs/update.log  # logi auto-update"
echo "  $REPO_DIR/deploy/update.sh        # ręczny update"
echo "  nano $SECRETS_FILE                # edycja sekretów (potem systemctl restart artmaker)"
echo
echo "Pierwsze logowanie - poczekaj 5-10 sekund aż Streamlit wstanie po raz pierwszy."
echo
