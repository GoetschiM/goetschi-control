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
- [ ] Fix the central log pipeline (promtail can't reach docker socket -> Loki empty)
- [x] Remove right-hand "LXC Status" panel (gone in redesign); fix PWA service-worker caching

## Phase 1.5 — Settings & configuration (UI)
- [x] Settings page (host metadata, tokens, config overview, audit log)
- [x] Edit host metadata: display name, category, notes
- [x] Manage API tokens (create / revoke)
- [x] Telegram test button (via /api/telegram/test)
- [ ] Edit host tags, criticality, owner
- [ ] Alert thresholds config
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
- [ ] pip / npm package inventory (not just dpkg)
- [ ] Host tags (owner, environment, criticality)

## Phase 4 — Pro features
- [ ] RBAC, user management, MFA, audit log, API tokens
- [ ] Dokploy actions from RRM (delete/redeploy service) — needs Dokploy API token
- [x] Backup success monitoring (Proxmox vzdump jobs, last-OK + failure highlighting)
- [x] SSL cert expiry monitoring (per HTTPS service, colour-coded)
- [ ] Domain registration expiry (whois) — not yet
- [ ] Grafana / DB integrations
- [x] AI analysis: "chat with infrastructure" (grounded in metrics/logs/alerts via LiteLLM gemini-flash)
- [ ] AI: scheduled incident summaries, ticket suggestions, deeper Loki/Prometheus tool-calling

## Automations
- [x] Event rule engine: "when X then Y" (metric/status conditions) with cooldown, 60s evaluator
- [x] Actions: Telegram, AI-diagnose (LiteLLM), CT reboot, container restart
- [ ] More triggers (backup failed, SSL expiry, log pattern) + chained actions + UI for cron tasks

## Smarter agents (cross-cutting)
- [ ] gl-agent: versioning, auto-update, command channel, richer security/asset data
- [ ] Nanoclaw: smarter self-healing + correlation
