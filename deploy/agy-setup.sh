#!/bin/bash
# Verbindet die Antigravity CLI (agy) mit RRM.
#  - MCP "rrm" (lesend) ist ohne Rueckfrage freigegeben
#  - MCP "rrm-admin" (aendernd) ist eingetragen, aber NICHT freigegeben -> nur nach "Plan ausfuehren"
#  - Arbeitskopie des Repos fuer Aenderungen per Pull Request, plus git und gh
#   sudo bash deploy/agy-setup.sh            (vorher einmal: agy  -> mit Google-Konto anmelden)
set -euo pipefail
ENVF=${RRM_ENV:-/etc/rrm.env}
AGY=${AGY_BIN:-/usr/local/bin/agy}
APP=${RRM_APP:-/opt/rrm}
WORK=${AGY_WORKDIR:-/root/admin}
PORT=$(grep -oP '^PORT=\K.*' "$ENVF" 2>/dev/null || echo 8181)
DATA=$(dirname "$(grep -oP '^AUDIT_DB=\K.*' "$ENVF" 2>/dev/null || echo /data/audit.db)")
TOKEN=$(grep -oP '^MCP_TOKEN=\K.*' "$ENVF" 2>/dev/null || cat "$DATA/mcp_token")
[ -x "$AGY" ] || { echo "agy nicht gefunden: $AGY"; exit 1; }
[ -n "$TOKEN" ] || { echo "MCP-Token nicht gefunden"; exit 1; }
export HOME=${AGY_HOME:-/root}

"$AGY" mcp add --header "Authorization: Bearer $TOKEN" rrm "http://127.0.0.1:$PORT/mcp" >/dev/null
"$AGY" mcp add --header "Authorization: Bearer $TOKEN" rrm-admin "http://127.0.0.1:$PORT/mcp/admin" >/dev/null

SETTINGS="$HOME/.gemini/antigravity-cli/settings.json"
mkdir -p "$(dirname "$SETTINGS")" "$WORK"
python3 - "$SETTINGS" "$WORK" <<'PY'
import json, os, sys
p, wd = sys.argv[1], sys.argv[2]
d = json.load(open(p)) if os.path.exists(p) else {}
perm = d.setdefault('permissions', {})
perm['allow'] = sorted(set(a for a in perm.get('allow', []) if not a.startswith('mcp(rrm-admin')) | {'mcp(rrm/*)'})
d['trustedWorkspaces'] = sorted(set(d.get('trustedWorkspaces', []) + [wd]))
json.dump(d, open(p, 'w'), indent=2)
PY

# Werkzeuge und Arbeitskopie fuer Aenderungen am RRM per Pull Request
if command -v apt-get >/dev/null; then
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git gh >/dev/null 2>&1 || true
fi
REPO_URL=$(git -C "$APP" remote get-url origin 2>/dev/null || echo https://github.com/GoetschiM/goetschi-control.git)
if [ ! -d "$WORK/rrm-src/.git" ]; then git clone -q "$REPO_URL" "$WORK/rrm-src"; fi
git -C "$WORK/rrm-src" config user.name  "RRM KI-Assistent"
git -C "$WORK/rrm-src" config user.email "rrm-ki@localhost"
git -C "$WORK/rrm-src" config credential.helper '!f() { echo username=x-access-token; echo "password=$GH_TOKEN"; }; f'
cp "$APP/deploy/agy-instructions.md" "$WORK/RRM.md"

echo "agy ist mit RRM verbunden: MCP rrm (frei), rrm-admin (nur nach Freigabe), Arbeitskopie $WORK/rrm-src."
command -v gh >/dev/null || echo "Hinweis: gh nicht installiert – Pull Requests dann per GitHub-API."
