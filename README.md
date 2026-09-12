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

## Deployment & Configuration

### Prerequisites
- Docker with multi-stage build support
- Python 3.11+ (for local development)
- Node.js 20+ (for frontend build)
- Network access to infrastructure services (Proxmox, Prometheus, Loki, etc.)

### Environment Setup
Create a `dashboard.env` file (based on `dashboard.env.example`) with your infrastructure credentials:

```bash
cp dashboard.env.example dashboard.env
# Edit dashboard.env and fill in your actual credentials for:
# - Proxmox API access
# - Prometheus & Loki endpoints
# - UniFi controller credentials
# - LiteLLM API key (for AI analysis features)
# - Optional: Telegram alerts configuration
```

### Docker Deployment
Build and run the container:
```bash
docker build -t goetschi-control:latest .
docker run -d --name goetschi-control --restart unless-stopped \
  --env-file dashboard.env \
  -v /var/lib/goetschi-control:/data \
  -p 8181:8080 goetschi-control:latest
```

The dashboard will be available at `http://localhost:8181`.

### Production Considerations
- **HTTPS**: Place a reverse proxy (Nginx, Traefik, or similar) in front for TLS termination
- **SECRET_KEY**: Generated automatically on first run and persisted in `/data/secret_key` — do not share between instances
- **Session Security**: Configure `COOKIE_SECURE=1` when using HTTPS
- **Access Control**: Enable RBAC/users in Settings to restrict dashboard access
- **Backups**: Regularly backup `/data/audit.db` for audit log persistence

### Service Integration
| Service | Environment Variable | Purpose |
|---------|----------------------|---------|
| Proxmox | `PROXMOX_HOST`, `PROXMOX_PASS` | Infrastructure monitoring & control |
| Prometheus | `PROMETHEUS_URL` | Metrics history |
| Loki | `LOKI_URL` | Centralized logging |
| UniFi | `UNIFI_URL`, `UNIFI_PASS` | Network monitoring |
| LiteLLM | `LITELLM_KEY` | AI-powered analysis (optional) |
| Telegram | `TELEGRAM_TOKEN` | Alert notifications (optional) |

All credentials are read-only from environment variables at startup. No secrets are stored in the repository.

## Roadmap
See [ROADMAP.md](ROADMAP.md) — phased plan toward the full "Goetschi Control"
platform (per-service pages, remote management, asset/security inventory,
RBAC/audit, backup monitoring, AI analysis).
