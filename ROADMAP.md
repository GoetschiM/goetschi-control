# Goetschi Control — Roadmap

Decisions (2026-06-20):
- **Source of truth:** GitHub (private repo).
- **Frontend:** redesign from scratch — professional, minimalist, modern, configurable.
- **First feature focus:** per-service / per-container detail pages + better navigation/topology.

## Phase 0 — Foundation (in progress)
- [x] Pull live code (v18) from CT120 into a git repo as baseline
- [ ] Push to private GitHub repo (needs auth)
- [ ] Build & deploy only from repo; retire ad-hoc in-container edits
- [ ] Clean up stale images / instances

## Phase 1 — Frontend redesign (foundation + per-service pages)
- [x] Design system (layout grid, typography, color tokens, dark mode, mobile-first)
- [x] New navigation / information architecture; topology view
- [x] **Per-service / per-container detail page** (real-time metrics, logs, actions)
- [x] Animated live "flow" diagram (tiered topology with animated connectors)
- [x] Configurable service board (Homarr-style): open/add/remove/reorder tiles, auto-fill from discovered services
- [x] Logs from systemd journal (Proxmox pct exec) — Loki/promtail pipeline is broken/empty
- [x] Fixed central log pipeline: promtail redeployed on all docker hosts with docker.sock -> Loki ingests container logs (33 streams)
- [ ] Journal logs to Loki (promtail image lacks journald support; RRM reads journals directly instead)
- [x] Remove right-hand "LXC Status" panel (gone in redesign); fix PWA service-worker caching

## Phase 1.5 — Settings & configuration (UI)
- [x] Settings page (host metadata, tokens, config overview, audit log)
- [x] Edit host metadata: display name, category, notes
- [x] Manage API tokens (create / revoke)
- [x] Telegram test button (via /api/telegram/test)
- [ ] Edit host tags, criticality, owner
- [x] Alert thresholds config (Settings-UI, /api/alert-thresholds, gilt auch für Telegram) — v41
- [ ] Add / remove monitored hosts & services from the UI
- [ ] Theme / layout preferences

## Phase 2 — Remote management
- [x] Container start / stop / restart from the UI (via Proxmox pct exec, injection-guarded)
- [ ] Container update (needs Dokploy/Coolify orchestrator integration — Phase 4)
- [x] SSH / shell access — xterm terminal page, routed via Proxmox `pct enter` for LXC
- [x] Fix the CT "Diag" auth error — now uses gl-agent /nanoclaw/diagnose, not SSH:22
- [x] Bulk actions (select containers → start/stop/restart; API supports multi-host)
- [ ] Add / remove monitored CT / device / service from the UI

## Phase 3 — Asset & security transparency
- [x] Per-CT inventory: OS + version, Python version, kernel, installed packages (via Proxmox pct exec, cached in audit.db)
- [x] Searchable across all hosts ("which CT runs package X vY?") for zero-day triage
- [ ] Scheduled/auto inventory refresh + change history
- [x] pip package inventory (system pip; note: most python here is in venv/uv, so often empty)
- [x] Integrations self-test page (Proxmox/Prometheus/Loki/UniFi/LiteLLM/LLM/Dokploy/agents) — "MCP/API audit"
- [x] Per-user password change
- [ ] Host tags (owner, environment, criticality)

## Phase 4 — Pro features
- [x] RBAC: users + roles (admin/viewer), user management, role-gated actions, audit log, API tokens
- [x] MFA / TOTP (2FA) — opt-in per user, QR enrollment, two-step login
- [ ] Per-user password change UI; finer-grained roles
- [ ] Dokploy actions from RRM (delete/redeploy service) — needs Dokploy API token
- [x] Backup success monitoring (Proxmox vzdump jobs, last-OK + failure highlighting)
- [x] SSL cert expiry monitoring (per HTTPS service, colour-coded)
- [ ] Domain registration expiry (whois) — not yet
- [x] Native metrics page (CPU/RAM/Disk time-series charts from history) + Grafana deep-link
- [x] Full Grafana embedding (allow_embedding + anonymous Viewer enabled on Grafana; RRM Grafana page with kiosk iframe)
- [x] AI analysis: "chat with infrastructure" (grounded in metrics/logs/alerts via LiteLLM gemini-flash)
- [ ] AI: scheduled incident summaries, ticket suggestions, deeper Loki/Prometheus tool-calling

## Automations
- [x] Event rule engine: "when X then Y" (metric/status conditions) with cooldown, 60s evaluator
- [x] Actions: Telegram, AI-diagnose (LiteLLM), CT reboot, container restart
- [ ] More triggers (backup failed, SSL expiry, log pattern) + chained actions + UI for cron tasks

## Go-Live Hardening (v41, 2026-07-04)
- [x] SECRET_KEY: zufällig generiert + persistiert in /data/secret_key (vorher erratbarer Hardcode → Session-Forgery)
- [x] Login-Brute-Force-Schutz: 5 Fehlversuche/IP → 5 min Sperre (LOGIN_MAX_FAILS / LOGIN_BLOCK_S)
- [x] Session-Cookies: SameSite=Lax + HttpOnly; Secure via COOKIE_SECURE=1 (wenn HTTPS davor)
- [x] Security-Header (X-Frame-Options, nosniff, Referrer-Policy)
- [x] Socket.IO CORS: same-origin statt `*` (Ausnahmen via CORS_ORIGINS)
- [x] `/healthz` (öffentlich, für Uptime-Monitoring)
- [x] Öffentliche Status-Seite `/status` + `/api/public/status` (nur Name+Status, keine IPs; PUBLIC_STATUS=0 deaktiviert)
- [x] Host-Daten korrigiert: CT100 = Mattermost/Odysseus (Dokploy-Stack weg), Coolify-Dienste aktualisiert (MT5 Trading 3007), CT120 überwacht sich jetzt selbst ('control')
- [ ] HTTPS: Reverse-Proxy (Coolify/Traefik oder NPM) mit Zertifikat davorschalten, dann COOKIE_SECURE=1
- [ ] Fallback-Logins (USERS dict, Default 'line13') entfernen/ändern, sobald DB-Login etabliert

## Smarter agents (cross-cutting)
- [ ] gl-agent: versioning, auto-update, command channel, richer security/asset data
- [ ] Nanoclaw: smarter self-healing + correlation
