# RRM

Self-hosted infrastructure monitoring and control. It starts empty and grows as you
connect things: hosts, agents, Proxmox, UniFi, your own tooling via MCP.

- **Host overview** with status, CPU/RAM/disk, ports and services
- **Agents**: one-line install on any Linux host (Python 3 only, no packages)
- **Discovery**: Proxmox containers, network scan, UniFi, manual hosts
- **Inventory**: installed packages per host, searchable across everything
- **Alerts** by Telegram, audit log, users with roles and 2FA
- **MCP server** (read-only) so AI agents can ask what runs where

## Quick start

```bash
git clone https://github.com/GoetschiM/goetschi-control rrm && cd rrm
cp .env.example .env        # optional, everything can stay empty
docker compose up -d
```

Open `http://<host>:8181`. The first visit asks you to create the administrator.
Nothing is preconfigured: no users, hosts, addresses or tokens ship with the code.

Without Docker: `pip install -r requirements.txt`, build the UI once
(`cd frontend && npm install && npm run build`), then `python app.py`.

## Growing your setup

Everything is under **Verbinden** in the sidebar:

1. **Install an agent** on a host. Copy the one-liner, run it as root on the target.
   The host appears within a minute.
2. **Add hosts without an agent** by hand, or scan a private network and pick the hosts you want.
3. **Connect integrations** by setting variables from `.env.example` (Proxmox, UniFi,
   Prometheus, Loki, Dokploy, Coolify, LiteLLM, Telegram) and restarting. Each is optional.
4. **Connect AI agents** through the MCP endpoint `/mcp` (Bearer token shown in the same page).

### Proxmox

Create a read-only token and set `PROXMOX_HOST` and `PROXMOX_TOKEN`:

```bash
pveum user add rrm@pve
pveum acl modify / --users rrm@pve --roles PVEAuditor
pveum user token add rrm@pve dash --privsep 0
```

Containers are then discovered automatically with name, IP, CPU and RAM.

### MCP tools

`list_containers`, `infra_status`, `list_agents`, `active_alerts`, `find_package`

```bash
claude mcp add --transport http rrm http://<host>:8181/mcp --header "Authorization: Bearer <token>"
```

## Security notes

- Put a reverse proxy with HTTPS in front and set `COOKIE_SECURE=1`.
- Agent and MCP tokens are generated on first start and stored in `/data` (mode 600).
- Network scans are limited to private ranges up to /22.
- The agent contains no secrets; the token is set at install time.

## Data

Everything lives in the `/data` volume (`audit.db`, generated secrets). Back it up.

## Development

Flask backend in `app.py`, React (Vite) frontend in `frontend/`, agent in `agent/gl-agent.py`.
See [CONTRIBUTING.md](CONTRIBUTING.md) and [ROADMAP.md](ROADMAP.md).

Licensed under the terms in [LICENSE](LICENSE).
