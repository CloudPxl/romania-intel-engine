# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

This is a monorepo with two independently-versioned projects:

- `romania-intel-engine/` — Python/FastAPI backend (the deployed product API).
- `romania-intel-frontend/` — Next.js 16 / React 19 frontend, checked in as a **git submodule** with its own `.git`. Commit and push inside that directory separately from the root repo.

The root also contains several large one-off `deploy_*.py`, `fix_*.py`, and `setup_*.py` scripts (e.g. `deploy_master.py`, `fix_build.py`, `setup_phase4.py`). These are throwaway code-generation/patch scripts used to bulk-write files into `romania-intel-engine/` and `romania-intel-frontend/` during earlier sessions — they are not part of the running application and generally should not be run or extended. Prefer editing files in the two project directories directly.

## Commands

### Backend (`romania-intel-engine/`)

```bash
python -m venv ../venv && source ../venv/bin/activate   # first-time setup (venv lives at repo root)
pip install -r requirements.txt

python server.py                    # run the production API (uvicorn, reads PORT env, defaults to 8000)
python daemon.py                    # run the standalone 6-hourly ingestion scheduler (no HTTP server)
python main.py                      # run the legacy src/ scraper pipeline once and print results
python test_ai.py                   # run the legacy src/ AI refinement pass once and print results

python scripts/verify_backend_health.py   # hit the deployed Render API + Postgres and report health
python scripts/system_health_check.py
python scripts/seed_tenants.py
```

There is no configured lint/test runner (no pytest config, no CI) — verify changes by running the relevant script above or by hitting the FastAPI routes directly (`python server.py` then `curl localhost:8000/...`).

### Frontend (`romania-intel-frontend/`)

```bash
npm run dev          # next dev, expects backend on http://localhost:8000
npm run build
npm run start
npx tsc --noEmit     # typecheck — no lint/test script is configured, no CI; build + this are the only verification
```

## Architecture

### Two parallel, unconnected backend pipelines

The engine directory contains two separate scraper/ingestion systems that do **not** share code. When working on ingestion or scoring, check which pipeline the entry point you're editing belongs to before assuming shared behavior:

1. **Legacy `src/` pipeline** (`main.py`, `test_ai.py`, `scripts/run_full_cycle.py`): `src/scrapers/sources/*` adapters extend `src/scrapers/base_adapter.py:BaseSourceAdapter`, persist into a local SQLite DB (`data/intel_local.db`, schema in `src/database/models.py`), and are scored by `src/ai/processor.py`. This path is not wired into the deployed API.
2. **Production pipeline** (`api.py`, `daemon.py`): `scrapers/orchestrator.py:OpportunityOrchestrator` fans out to 15 scrapers (16 when `ENABLE_LIVE_ELICITATIE=true`, which `render.yaml` sets by default) under `scrapers/matrix/*_scrapers.py`, each extending `scrapers/base_scraper.py:BaseScraper`. **These are real live scrapers, not fixtures** — every one does genuine `httpx`/BeautifulSoup/PDF-table extraction against a specific verified source (a JSON API, a WordPress REST endpoint, a server-rendered listing page, a PDF register) and honestly reports zero signals rather than fabricating data when a source is unreachable or has no real feed (e.g. `CnairCfrScraper`, `ApmPermitScraper`). The matrix is not an even grid across domains — it's whatever real sources exist per domain, plus `elicitatie_scraper.py:ElicitatieLiveScraper` (live SICAP/e-licitatie market consultations) and `municipal_scrapers.py` (direct feeds for București, Timișoara, Constanța; Cluj-Napoca and Iași are covered by `infra_scrapers.py`'s `UrbanismAcScraper`/`CountyHclScraper`). Results are scored by `ai_refinery.py:IntelligenceRefineryEngine` (evidence-based 0-10 scoring — see `STAGE_PROFILES` for the procurement-funnel weighting, including a deliberately negative weight for already-`awarded` results so closed procedures don't outrank live opportunities) and matched against tenant product lines in `matching_engine.py` (keyword evidence is a mandatory gate; domain/geography/budget only reinforce a match, never create one alone).

Ingestion runs on a soft per-tick deadline (`orchestrator.py:run_tick`, `TICK_DEADLINE_SECONDS`), skips sources whose own `poll_interval_minutes` hasn't elapsed (`db.is_source_due`) or whose circuit breaker is open (`db.get_circuit_state`, opens after 3 consecutive failures), and persists via `db.upsert_opportunity` — an overrun tick degrades to a partial run rather than being hard-cancelled, so `db.finish_tick` always records an outcome. Two things keep `is_stale` from going permanently true on Render's free tier: `.github/workflows/heartbeat.yml` (a GitHub Actions cron every 5 minutes, POSTing `X-Tick-Secret` to `/api/v1/system/tick` with a browser `User-Agent` — Render's backend edge, which runs on Cloudflare's CDN internally, can otherwise challenge headless-looking requests) and `api.py`'s own in-process APScheduler job that ticks once on startup and every 6 hours after.

### Postgres is the real backing store; the file cache is only a fallback

`db.py` maintains a small `asyncpg` pool against Supabase Postgres (transaction-pooler-aware — `statement_cache_size=0` is set automatically when the connection string points at port 6543 / `*.pooler.supabase.com`, since the pooler can't hold per-session prepared statements). `api.py:_load_feed()` is the single read path used by the tenant feed, the copilot, and `routers/analysis.py`'s market-trends endpoint: it calls `db.get_recent_opportunities()` (which accepts optional `start_date`/`end_date`/`counties`/`categories`/`min_value_ron`/`max_value_ron` filters, pushed down into a dynamically-built SQL `WHERE` clause) fresh on every call — there is no caching at this layer, so a filtered market-analysis request always re-queries live. Only when Postgres returns nothing does it fall back to `cache_engine.py:newsletter_store` (`NewsletterStore`, a JSON file on Render's ephemeral disk, rebuilt from scratch on every restart) — and the same filters are re-applied in Python to that fallback so a degraded response still honors the request. `TENANT_ORGANIZATIONS` (`matching_engine.py`) and `CONCURRENT_DEAL_PIPELINE` (`workflow_engine.py`) remain plain in-process dicts, not database-backed — tenant/product config and the deal pipeline still reset on restart.

`cache_engine.py:global_cache` (`MemoryCacheEngine`, in-memory TTL, default 90s) is a separate, purely-response-level cache layered on top of `_load_feed()` for per-tenant feed requests — invalidated by the background scraping job, not related to `newsletter_store`.

`workflow_engine.py:ConcurrentWorkflowEngine.get_pipeline_metrics()` (exposed at `GET /api/v1/tenants/{id}/pipeline/metrics`) computes weighted pipeline value using a stated stage-probability heuristic (not a trained model — the system has never ingested a real award result), plus real time-in-stage and funnel conversion rates derived from each deal's actual `stage_history` transition timestamps.

### Routers vs. inline routes

Most `addons/*.py` engines (independent, single-purpose, no shared base class: `caiet_analyzer`, `competitor_tracker`, `win_probability`) are invoked directly from routes inline in `api.py`. `business_eligibility`, `dossier_generator`, and `foia_generator` instead live behind `routers/eligibility.py` and `routers/drafting.py` — pulled out specifically so they map 1:1 to the frontend's standalone `/eligibility` and `/drafting` pages. `routers/drafting.py` also exposes `export-dossier-docx`/`export-clarification-docx` (streaming `.docx` downloads via `addons/docx_export.py`, python-docx) and an opt-in `use_ai_expansion` flag on the JSON generation endpoints that deepens the methodology/risk sections (`dossier_generator.py`/`foia_generator.py`'s `expand_with_ai()`) through the LLM chain described below — always additive, template output is a complete document on its own if no provider is configured. `routers/analysis.py` is not an addon wrapper at all; it reads `_load_feed()` directly (see above) and aggregates totals/breakdowns, with an opt-in `include_ai_report` flag for an LLM-synthesized strategic narrative. All three are mounted in `api.py` via `app.include_router(...)`. If you add a new addon-backed feature that has (or will have) its own frontend route, extract it into `routers/` rather than adding it inline to `api.py`.

`ai_copilot.py` is genuinely multi-provider with real sequential failover, not just a single configurable key: `list_llm_providers()` tries every configured provider (auto-detect order: groq, gemini, openai, xai — free-tier providers first, or forced via `LLM_PROVIDER`) and `complete_text()` walks the whole list, only giving up after every one fails. This is shared by `ProcurementAICopilot` (`/api/v1/copilot/chat`, inline in `api.py`) and by the document generators' `expand_with_ai()`. Note `render.yaml` names the xAI env var `GROK_API_KEY`, not `XAI_API_KEY` — `ai_copilot.py` reads both.

Cross-cutting concerns are separate small modules, not middleware classes. Two are more stubbed than their names suggest — check before relying on either: `security.py:SecurityGuard.verify_tenant_authorization` is a hardcoded stub that returns a fixed fake user/role regardless of the request (the actual rate limiting, 180 req/60s per IP in-process memory, is real); `billing.py`'s `StripeBillingEngine` has no Stripe SDK/API integration anywhere despite the name — it generates real HTML proforma invoices for manual bank-transfer payment, and `create_checkout_session()` just returns a "proforma required" response. `freemium_shield.py:FreemiumGatekeeper` (redacts/locks leads past the free-tier limit) and `notifier.py:LeadAlertDispatcher` (Telegram + email fan-out for high-score leads, gated by per-tenant `min_alert_score` and deduped via `db.has_alert_been_dispatched` — there is no Slack channel despite older docs mentioning one; unconfigured SMTP silently "succeeds" without sending) are both real, working logic.

### Frontend

The app is split into standalone routed pages rather than one workspace component — each page owns its own data fetching and calls `lib/api.ts` directly: `/` (landing dashboard: live stat tiles from `fetchMarketTrends()` plus links into every tool), `/login` (standalone dark-themed screen, no NavBar — Supabase Google OAuth or email magic link), `/newsletter` (the core product: filterable/searchable pre-tender feed with a slide-over dossier per lead, save-to-pipeline, and freemium blur past the 2nd result), `/eligibility` (grant/funding eligibility scanner), `/drafting` (technical-proposal + Legea 544 clarification generator, tabbed), `/analytics` (Copilot chat + 72h briefing, Competitor Radar, Caiet Scanner, Win Simulator — 4 tabs), `/analysis` (read-only market-trends dashboard backed by `routers/analysis.py`), and `/pipeline` (the tenant's saved deals). `components/intelligence-workspace.tsx` is leftover from before this route split and is never imported — along with everything it alone depends on (`lib/mock-data.ts`, and `components/ui/{tabs,sheet,switch,avatar,dialog,badge,separator,select,input,tooltip}.tsx`), it's dead code, not a reference for current structure.

"Companies" are modeled client-side as **Desks** (`BusinessDesk`) — created, switched, and deleted entirely in `localStorage` via `WorkspaceDeskModal`, with no backend desk CRUD; `switchTenantWorkspace` only writes local state. Treat this as the current tenant-switching mechanism, not a stopgap to route around.

`components/NavBar.tsx` is mounted once in `app/layout.tsx` and is the only navigation: a slim fixed header with a hamburger button that opens a slide-out drawer listing all routes plus desk-switching and account actions (there is no horizontal tab bar). `components/EnterpriseModals.tsx` holds the three modals used globally from the nav (`PricingModal` — plan picker that generates a printable proforma invoice; `AccountSettingsModal`; `WorkspaceDeskModal`) — tool-specific dialogs live inlined in their corresponding page under `app/` instead; add new tool UI there, not back into this file.

`lib/api.ts` is the sole HTTP boundary to the backend (18 functions) — it auto-selects `http://localhost:8000` vs `https://api.ro-intel.xyz` based on `window.location.hostname`, and every function corresponds 1:1 to a FastAPI route in `api.py`/`routers/*.py`; when adding a backend endpoint, add the matching typed function here rather than calling `fetch` inline from components. Auth/session/desk-switching state lives in `context/AuthContext.tsx`, backed by Supabase auth (`lib/supabase.ts`) with tenant sync posted to the backend via `syncBackendAuth` (`syncUserWithAuth` is an unused alias of it — don't add new callers of that name).

The visual design follows BiziDay's real theme (colors/typography pulled from their live site, `wp-theme-biziday`): an indigo brand scale (`brand-50`…`brand-900`, base `#242a88`) defined via Tailwind v4 `@theme` tokens in `app/globals.css`, layered on shadcn/oklch theme tokens, and Roboto loaded through `next/font/google` in `app/layout.tsx`. Use `brand-*` utility classes for accents rather than reintroducing `sky-*` or other ad hoc colors. Light/dark CSS variables both exist but the app is currently hardcoded to light mode — there is no theme toggle wired anywhere.

UI text is in Romanian (error messages, labels) — match that convention when touching user-facing frontend strings.
