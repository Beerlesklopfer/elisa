#!/bin/sh
# Wird vom preinst des Pakets elisa-stack als Benutzer www-data ausgeführt
# (nie als root): holt ELISA und Eliezer von GitHub und baut die Images im
# rootless-Podman von www-data. Die Prüfsumme dieses Skripts ist im Paket fest
# eingebaut (preinst).
#
# Umgebung (optional): ELISA_REPO, ELISA_REF, ELIEZER_REPO, ELIEZER_REF,
#                      ELISA_SKIP_ELIEZER=1 (Eliezer läuft extern)
set -eu

BASE=/var/lib/elisa
ELISA_REPO="${ELISA_REPO:-https://github.com/Beerlesklopfer/elisa.git}"
ELISA_REF="${ELISA_REF:-main}"
ELIEZER_REPO="${ELIEZER_REPO:-https://github.com/Beerlesklopfer/eliezer.git}"
ELIEZER_REF="${ELIEZER_REF:-main}"

fetch() {  # fetch <repo> <ref> <dir>: Klon bzw. Update, danach exakt auf <ref>
    if [ -d "$3/.git" ]; then
        git -C "$3" fetch --depth 1 origin "$2"
    else
        git init -q "$3"
        git -C "$3" remote add origin "$1"
        git -C "$3" fetch --depth 1 origin "$2"
    fi
    git -C "$3" checkout -q --force FETCH_HEAD
}

echo "── ELISA holen ($ELISA_REF) ──"
fetch "$ELISA_REPO" "$ELISA_REF" "$BASE/src/elisa"
podman build -t localhost/elisa:stack -f "$BASE/src/elisa/Containerfile" "$BASE/src/elisa"

podman pull docker.io/pgvector/pgvector:pg16

if [ "${ELISA_SKIP_ELIEZER:-0}" != 1 ]; then
    echo "── Eliezer holen ($ELIEZER_REF) ──"
    fetch "$ELIEZER_REPO" "$ELIEZER_REF" "$BASE/src/eliezer"
    podman build -t localhost/eliezer:stack "$BASE/src/eliezer"
    mkdir -p "$BASE/eliezer" "$BASE/models"
    [ -f "$BASE/eliezer/config.toml" ] || \
        cp "$BASE/src/eliezer/packaging/config.container.toml" "$BASE/eliezer/config.toml"
fi
echo "Images gebaut."
