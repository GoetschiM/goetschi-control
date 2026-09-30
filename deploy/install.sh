#!/bin/bash
# RRM ohne Docker auf Debian/Ubuntu installieren (z.B. in einem kleinen LXC).
#   curl -fsSL https://raw.githubusercontent.com/GoetschiM/goetschi-control/main/deploy/install.sh | bash
# Optional: AUTO_UPDATE=0 schaltet die automatische Aktualisierung ab.
set -euo pipefail
REPO=${RRM_REPO:-https://github.com/GoetschiM/goetschi-control.git}
BRANCH=${RRM_BRANCH:-main}
APP=/opt/rrm
DATA=/var/lib/rrm
ENVF=/etc/rrm.env

[ "$(id -u)" = 0 ] || { echo "Bitte als root ausführen"; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git python3-venv curl ca-certificates nodejs npm >/dev/null

if [ -d "$APP/.git" ]; then git -C "$APP" pull -q; else git clone -q -b "$BRANCH" "$REPO" "$APP"; fi
python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install -q -r "$APP/requirements.txt"
(cd "$APP/frontend" && npm install --silent && npm run build --silent)

mkdir -p "$DATA"
if [ ! -f "$ENVF" ]; then
  umask 077
  { echo "AUDIT_DB=$DATA/audit.db"; echo "PORT=8181"; grep -vE '^(AUDIT_DB|PORT)=' "$APP/.env.example"; } > "$ENVF"
fi

sed "s#/opt/rrm#$APP#g" "$APP/deploy/rrm.service" > /etc/systemd/system/rrm.service
cp "$APP/deploy/rrm-update.service" "$APP/deploy/rrm-update.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now rrm
if [ "${AUTO_UPDATE:-1}" = 1 ]; then systemctl enable --now rrm-update.timer; fi

IP=$(hostname -I | awk '{print $1}')
echo "RRM läuft: http://$IP:8181  (Konfiguration: $ENVF)"
