#!/usr/bin/env bash
# =============================================================================
# ELISA – Deploy (CrystalKey-Stil): Der Code wird nach /usr/share/elisa
# KOPIERT (lokal, www-data-lesbar – NICHT aus dem NFS-/0700-Home gelinkt), die
# venv wird DORT gebaut, die Dienste laufen als www-data mit Sandboxing.
# Schreibbare Daten (DB, media, RAG-Index, incoming) liegen unter /var/lib.
#
# Aufruf:  sudo ./deploy.sh [--nginx] [--hostname NAME] [--with-ollama]
# =============================================================================
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR=/usr/share/elisa
CONF_DIR=/etc/elisa
DATA_DIR=/var/lib/elisa
LOG_DIR=/var/log/elisa

NGINX=0; HOSTNAME=""; WITH_OLLAMA=0; RESTART=1
while [[ $# -gt 0 ]]; do
    case "$1" in
        --nginx)       NGINX=1; shift ;;
        --hostname)    HOSTNAME="$2"; shift 2 ;;
        --with-ollama) WITH_OLLAMA=1; shift ;;
        --no-restart)  RESTART=0; shift ;;
        -h|--help) echo "Usage: sudo $0 [--nginx] [--hostname NAME] [--with-ollama] [--no-restart]"; exit 0 ;;
        *) echo "Unbekannte Option: $1" >&2; exit 1 ;;
    esac
done
[[ $EUID -eq 0 ]] || { echo "Bitte als root:  sudo $0 $*" >&2; exit 1; }

echo "── ELISA Deploy (Kopie nach $APP_DIR) ──"

# ── FHS-Verzeichnisse (www-data) ───────────────────────────────────────────
install -d "$CONF_DIR" "$CONF_DIR/nginx"
# Alte Symlinks aus einem früheren (Symlink-)Deploy entfernen – sonst zeigen
# media/incoming weiter ins NFS-Home (0700) und www-data kann nicht zugreifen.
for d in incoming media staticfiles indexed_pdfs ollama-models; do
    [ -L "$DATA_DIR/$d" ] && { echo "  Entferne alten Symlink $DATA_DIR/$d"; rm -f "$DATA_DIR/$d"; }
done
install -d -o www-data -g www-data \
    "$DATA_DIR" "$DATA_DIR/media" "$DATA_DIR/staticfiles" "$DATA_DIR/incoming" \
    "$DATA_DIR/indexed_pdfs" "$DATA_DIR/ollama-models" "$LOG_DIR"

# ── Code KOPIEREN (kein Symlink) ───────────────────────────────────────────
echo "── Kopiere Anwendungscode ──"
# Alten Symlink-Deploy entfernen, sonst kopiert rsync in den Quellbaum!
[ -L "$APP_DIR" ] && { echo "  Entferne alten Symlink $APP_DIR"; rm -f "$APP_DIR"; }
mkdir -p "$APP_DIR"
rsync -a --delete \
    --exclude '.venv' --exclude '.git' --exclude '.ollama' \
    --exclude 'incoming' --exclude 'media' --exclude 'logs' \
    --exclude 'tmp' --exclude '*.zip' --exclude '__pycache__' \
    --exclude '.claude' --exclude '*.sqlite3' \
    --exclude 'rag/indexed_pdfs' --exclude 'rag/index_progress.json' \
    "$SRC"/ "$APP_DIR"/

# ── Konfiguration ──────────────────────────────────────────────────────────
if [ ! -f "$CONF_DIR/env" ]; then
    cp "$SRC/.env.example" "$CONF_DIR/env"
    SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
    sed -i "s|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=$SECRET|" "$CONF_DIR/env"
    echo "  Erstellt: $CONF_DIR/env (Secret generiert) – bitte SMTP/DB prüfen."
else
    echo "  Existiert bereits: $CONF_DIR/env"
fi
chown root:www-data "$CONF_DIR/env"; chmod 640 "$CONF_DIR/env"

# ── venv VOR ORT bauen ─────────────────────────────────────────────────────
echo "── Virtuelle Umgebung in $APP_DIR/.venv ──"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip setuptools wheel -q
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q

# ── Django-Setup (FHS: /etc/elisa/env -> DATA_DIR=/var/lib/elisa) ──
MANAGE="$APP_DIR/.venv/bin/python $APP_DIR/manage.py"
set -a; . "$CONF_DIR/env"; set +a
$MANAGE migrate --noinput
$MANAGE collectstatic --noinput
$MANAGE compilemessages 2>/dev/null || true   # i18n-Kataloge (.po -> .mo)

# ── Ollama optional: Binary-Bundle kopieren, Modelle nach /var/lib syncen ──
if [ "$WITH_OLLAMA" = 1 ]; then
    if [ -d "$SRC/.ollama/dist" ]; then
        echo "── Kopiere Ollama-Binary ──"
        mkdir -p "$APP_DIR/.ollama"; rsync -a "$SRC/.ollama/dist" "$APP_DIR/.ollama/"
    fi
    if [ -d "$SRC/.ollama/models" ]; then
        echo "── Synchronisiere Ollama-Modelle (kann groß sein) ──"
        rsync -a "$SRC/.ollama/models/" "$DATA_DIR/ollama-models/"
    fi
fi

# ── Rechte ─────────────────────────────────────────────────────────────────
chown -R www-data:www-data "$APP_DIR" "$DATA_DIR" "$LOG_DIR"

# ── systemd-Units ──────────────────────────────────────────────────────────
echo "── Installiere systemd-Units ──"
install -m 644 "$SRC/elisa.service"        /usr/lib/systemd/system/
install -m 644 "$SRC/elisa-mcp.service"    /usr/lib/systemd/system/
install -m 644 "$SRC/elisa-worker.service" /usr/lib/systemd/system/
install -m 644 "$SRC/elisa-ollama.service" /usr/lib/systemd/system/
systemctl daemon-reload
systemctl enable elisa.service elisa-mcp.service elisa-worker.service
[ "$WITH_OLLAMA" = 1 ] && systemctl enable elisa-ollama.service && systemctl restart elisa-ollama.service || true

if [ "$RESTART" = 1 ]; then
    # Robust: erst stoppen, verwaiste Port-Belegung (8088/8765) freigeben, dann starten.
    systemctl stop elisa-worker.service elisa.service elisa-mcp.service 2>/dev/null || true
    command -v fuser >/dev/null && fuser -k 8088/tcp 8765/tcp 2>/dev/null || true
    sleep 1
    systemctl start elisa.service elisa-mcp.service
    # Worker NACH der MCP starten (er verbindet sich per Loopback an :8765).
    # Ohne aktive WorkerBackends beendet er sich sofort (kein Fehler) – sobald
    # im Admin Backends angelegt sind: systemctl restart elisa-worker.
    systemctl start elisa-worker.service || true
    echo "  Dienste neu gestartet (App :8088, MCP :8765, Worker)."
else
    echo "  --no-restart: Dienste NICHT neu gestartet (manuell: systemctl restart elisa elisa-mcp elisa-worker)."
fi

# ── Nginx ──────────────────────────────────────────────────────────────────
if [ "$NGINX" = 1 ]; then
    [ -n "$HOSTNAME" ] || { read -rp "  Hostname [localhost]: " HOSTNAME; HOSTNAME="${HOSTNAME:-localhost}"; }
    install -m 644 "$SRC/elisa.nginx.conf" "$CONF_DIR/nginx/elisa.conf"
    NGINX_CONF="/etc/nginx/sites-available/elisa.conf"
    sed "s|__SERVER_NAME__|${HOSTNAME}|g" "$CONF_DIR/nginx/elisa.conf" > "$NGINX_CONF"
    ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/elisa.conf
    nginx -t && systemctl reload nginx
    echo "  Nginx: $HOSTNAME (App unter /, MCP unter /mcp/). MCP_PATH_PREFIX=/mcp in env setzen!"
fi

echo ""
echo "  ════════════════════════════════════════════"
echo "  Deploy abgeschlossen (Code KOPIERT, läuft als www-data)."
echo "    Code:   $APP_DIR   (read-only)"
echo "    Daten:  $DATA_DIR  (media, indexed_pdfs, incoming; Vektoren in Postgres/pgvector)"
echo "    Status: systemctl status elisa elisa-mcp elisa-worker"
echo "    Logs:   journalctl -u elisa -f   (Worker: -u elisa-worker)"
echo "    Worker: Backends im Admin (/admin/app/workerbackend/) anlegen,"
echo "            dann: systemctl restart elisa-worker"
echo "  ════════════════════════════════════════════"
