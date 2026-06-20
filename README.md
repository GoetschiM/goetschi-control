# Goetschi Control (RRM)

Central monitoring & control plane for the Goetschi Labs infrastructure
(Proxmox, LXC, Docker, gl-agent, Prometheus, Loki, UniFi, LiteLLM).

> **This repo is the single source of truth.** The dashboard must only be
> deployed by building from this repo. Do not edit code inside running
> containers — change it here, commit, then build & deploy.

## Stack
- Backend: Python / Flask (`app.py`)
- Frontend: SPA in `templates/index.html` + `static/` (app.js, style.css, PWA service worker)
- Runtime: Docker container, served on port `8080` (published `8181` on the host)

## Run locally
```bash
pip install -r requirements.txt
cp dashboard.env.example dashboard.env   # fill in secrets
python app.py
```

## Build & deploy
```bash
docker build -t goetschi-dashboard:N .
docker stop goetschi-control && docker rm goetschi-control
docker run -d --name goetschi-control --restart unless-stopped \
  --env-file /opt/goetschi-dashboard-data/dashboard.env \
  -v /opt/goetschi-dashboard-data:/data \
  -p 8181:8080 goetschi-dashboard:N
```

Currently live on **CT120 `goetschi-control`** → `http://10.0.60.155:8181`.

## Data sources (source-of-truth per value)
| Domain | Source |
|---|---|
| Infrastructure / per-container CPU & RAM | Proxmox API (`/cluster/resources`) |
| Metric history | Prometheus |
| Logs | Loki |
| Per-host telemetry & actions | gl-agent (port 9998) |
| Network | UniFi |

## Roadmap
See [ROADMAP.md](ROADMAP.md) — phased plan toward the full "Goetschi Control"
platform (per-service pages, remote management, asset/security inventory,
RBAC/audit, backup monitoring, AI analysis).
