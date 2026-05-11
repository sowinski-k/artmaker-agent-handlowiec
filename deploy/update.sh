#!/usr/bin/env bash
# Auto-update Artmaker Agent z Github.
#
# Uruchamiany przez cron co 2 minuty. Idempotent:
#  - jeśli nic nie zmienione na branchu - exit cicho
#  - jeśli są zmiany - pull, opcjonalnie pip install, restart usługi
#
# Logi: $APP_DIR/logs/update.log (tail -f żeby śledzić)

set -euo pipefail

REPO_DIR="/opt/artmaker/repo"
VENV_DIR="/opt/artmaker/venv"
BRANCH="claude/ai-sales-agent-artmaker-n48yh"
APP_USER="artmaker"

timestamp() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(timestamp)] $*"; }

cd "$REPO_DIR"

# Fetch tylko nasz branch
git fetch origin "$BRANCH" --quiet 2>/dev/null || {
    log "git fetch failed - skipping update"
    exit 0
}

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")

if [[ "$LOCAL" == "$REMOTE" ]]; then
    # Nic do roboty - cisza
    exit 0
fi

log "Update available: $LOCAL -> $REMOTE"

# Sprawdź czy requirements.txt się zmienił (przed pullem)
REQS_CHANGED=0
if git diff --name-only "$LOCAL" "$REMOTE" 2>/dev/null | grep -q "^requirements.txt$"; then
    REQS_CHANGED=1
    log "requirements.txt zmieniony - zrobię pip install po pullu"
fi

# Pull (jako artmaker, żeby zachować ownership)
sudo -u "$APP_USER" git reset --hard "origin/$BRANCH" --quiet
log "git reset --hard origin/$BRANCH OK"

# pip install jeśli trzeba
if [[ $REQS_CHANGED -eq 1 ]]; then
    sudo -u "$APP_USER" "$VENV_DIR/bin/pip" install --quiet -r "$REPO_DIR/requirements.txt"
    log "pip install OK"
fi

# Restart service - to uderza w main repo + nowe deps
systemctl restart artmaker.service
log "systemctl restart artmaker OK"

# Krótki sanity check
sleep 3
if systemctl is-active --quiet artmaker.service; then
    log "Service is active after restart - update successful"
else
    log "WARN: service nie wstał po restart - sprawdź 'journalctl -u artmaker -n 50'"
    exit 1
fi
