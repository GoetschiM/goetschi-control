#!/bin/bash
# Aktualisiert RRM auf den neuesten Stand des Branches (Standard: main).
# Baut Abhängigkeiten/Frontend nur bei Änderungen, prüft den Start und rollt bei Fehlern zurück.
set -u
APP=${RRM_APP:-/opt/rrm}
BRANCH=${RRM_BRANCH:-main}
SERVICE=${RRM_SERVICE:-rrm}
PORT=${PORT:-8181}
cd "$APP" || exit 1

git fetch -q origin "$BRANCH" || { echo "fetch fehlgeschlagen"; exit 1; }
OLD=$(git rev-parse HEAD); NEW=$(git rev-parse "origin/$BRANCH")
[ "$OLD" = "$NEW" ] && exit 0
echo "Update $OLD -> $NEW"
CHANGED=$(git diff --name-only "$OLD" "$NEW")

rollback() {
  echo "FEHLER: $1 - zurück auf $OLD"
  git reset -q --hard "$OLD"
  if [ -d static/spa.prev ]; then rm -rf static/spa; mv static/spa.prev static/spa; fi
  venv/bin/pip install -q -r requirements.txt
  systemctl restart "$SERVICE"
  exit 1
}

rm -rf static/spa.prev
[ -d static/spa ] && cp -a static/spa static/spa.prev
git reset -q --hard "$NEW"
if echo "$CHANGED" | grep -q '^requirements.txt$'; then
  venv/bin/pip install -q -r requirements.txt || rollback "pip install"
fi
if echo "$CHANGED" | grep -q '^frontend/'; then
  (cd frontend && npm install --silent && npm run build --silent) || rollback "Frontend-Build"
fi
systemctl restart "$SERVICE"
for _ in $(seq 1 20); do
  sleep 2
  if curl -fs -o /dev/null "http://127.0.0.1:$PORT/login"; then
    rm -rf static/spa.prev
    echo "OK: $NEW"
    exit 0
  fi
done
rollback "Dienst startet nicht"
