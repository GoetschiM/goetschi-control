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
- [ ] Configurable service dashboard: add/remove services manually + auto-discovered
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
- [x] Container restart from the UI (via gl-agent); host/agent restart actions
- [ ] Container start / stop / update from the UI
- [x] SSH / shell access — xterm terminal page, routed via Proxmox `pct enter` for LXC
- [x] Fix the CT "Diag" auth error — now uses gl-agent /nanoclaw/diagnose, not SSH:22
- [ ] Bulk actions across hosts
- [ ] Add / remove monitored CT / device / service from the UI

## Phase 3 — Asset & security transparency
- [ ] Per-CT inventory: OS + version, Python version, installed packages
- [ ] Searchable across all hosts ("which CT runs package X vY?") for zero-day triage
- [ ] Host tags (owner, environment, criticality), change history

## Phase 4 — Pro features
- [ ] RBAC, user management, MFA, audit log, API tokens
- [ ] Dokploy actions from RRM (delete/redeploy service) — needs Dokploy API token
- [ ] Backup success monitoring
- [ ] SSL cert + domain expiry monitoring
- [ ] Grafana / DB integrations
- [ ] AI analysis: log summary, root-cause, "chat with infrastructure"

## Smarter agents (cross-cutting)
- [ ] gl-agent: versioning, auto-update, command channel, richer security/asset data
- [ ] Nanoclaw: smarter self-healing + correlation
