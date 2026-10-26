#!/bin/sh
# Baut das Metapaket elisa-stack_<version>_all.deb aus dem committeten Stand.
# Das Installationsskript wird per Commit-SHA festgelegt (unveränderlich) und
# seine SHA256 in den preinst eingebaut. Der Commit muss auf GitHub liegen
# (Repo/Release öffentlich), sonst scheitert das preinst beim Herunterladen.
set -eu
cd "$(dirname "$0")/.."
VERSION="${1:-$(sed -n '1s/^elisa (\(.*\)) .*/\1/p' CHANGELOG.md)}"
SHA=$(git rev-parse HEAD)
SRC=packaging/install-as-www-data.sh
git diff --quiet HEAD -- "$SRC" || { echo "$SRC hat uncommittete Änderungen." >&2; exit 1; }
SUM=$(git show "$SHA:$SRC" | sha256sum | cut -d' ' -f1)
URL="https://raw.githubusercontent.com/Beerlesklopfer/elisa/$SHA/$SRC"

ROOT=$(mktemp -d); chmod 755 "$ROOT"; trap 'rm -rf "$ROOT"' EXIT
install -d "$ROOT/DEBIAN" "$ROOT/usr/share/elisa-stack/initdb" "$ROOT/etc/containers/systemd/users/33"
cp packaging/deb/DEBIAN/* "$ROOT/DEBIAN/"
sed -i "s|@VERSION@|$VERSION|; s|@SCRIPT_URL@|$URL|; s|@SCRIPT_SHA256@|$SUM|" "$ROOT/DEBIAN/control" "$ROOT/DEBIAN/preinst"
cp packaging/nginx/elisa-proxy.conf .env.example "$ROOT/usr/share/elisa-stack/"
mv "$ROOT/usr/share/elisa-stack/.env.example" "$ROOT/usr/share/elisa-stack/elisa.env.example"
cp packaging/initdb/*.sql "$ROOT/usr/share/elisa-stack/initdb/"
cp packaging/quadlet/* "$ROOT/etc/containers/systemd/users/33/"
# Quadlet-Units sind Konfiguration (conffiles), die Domain-Konfiguration nicht.
(cd "$ROOT" && find etc -type f | sed 's|^|/|') > "$ROOT/DEBIAN/conffiles"
mkdir -p dist
dpkg-deb --root-owner-group -b "$ROOT" "dist/elisa-stack_${VERSION}_all.deb"
echo "dist/elisa-stack_${VERSION}_all.deb  (Skript $SHA, sha256 $SUM)"
