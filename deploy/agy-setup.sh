#!/bin/bash
# Verbindet die Antigravity CLI (agy) mit RRM: MCP-Server eintragen und nur die
# lesenden RRM-Werkzeuge ohne Rueckfrage erlauben. Alles andere bleibt im Fragemodus
# gesperrt und laeuft erst nach Freigabe im RRM ("Plan ausfuehren").
#   sudo bash deploy/agy-setup.sh            (vorher einmal: agy  -> mit Google-Konto anmelden)
set -euo pipefail
ENVF=${RRM_ENV:-/etc/rrm.env}
AGY=${AGY_BIN:-/usr/local/bin/agy}
PORT=$(grep -oP '^PORT=\K.*' "$ENVF" 2>/dev/null || echo 8181)
DATA=$(dirname "$(grep -oP '^AUDIT_DB=\K.*' "$ENVF" 2>/dev/null || echo /data/audit.db)")
TOKEN=$(grep -oP '^MCP_TOKEN=\K.*' "$ENVF" 2>/dev/null || cat "$DATA/mcp_token")
[ -x "$AGY" ] || { echo "agy nicht gefunden: $AGY"; exit 1; }
[ -n "$TOKEN" ] || { echo "MCP-Token nicht gefunden"; exit 1; }

export HOME=${AGY_HOME:-/root}
"$AGY" mcp add --header "Authorization: Bearer $TOKEN" rrm "http://127.0.0.1:$PORT/mcp" >/dev/null

SETTINGS="$HOME/.gemini/antigravity-cli/settings.json"
mkdir -p "$(dirname "$SETTINGS")" "${AGY_WORKDIR:-/root/admin}"
python3 - "$SETTINGS" "${AGY_WORKDIR:-/root/admin}" <<'PY'
import json, os, sys
p, wd = sys.argv[1], sys.argv[2]
d = json.load(open(p)) if os.path.exists(p) else {}
perm = d.setdefault('permissions', {})
perm['allow'] = sorted(set(perm.get('allow', []) + ['mcp(rrm/*)']))
d['trustedWorkspaces'] = sorted(set(d.get('trustedWorkspaces', []) + [wd]))
json.dump(d, open(p, 'w'), indent=2)
PY
echo "agy ist mit RRM verbunden (MCP 'rrm', Freigabe: nur lesende RRM-Werkzeuge)."
