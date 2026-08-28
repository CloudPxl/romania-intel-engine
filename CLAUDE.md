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
playwright install chromium                              # required for scraper deps

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
2. **Production pipeline** (`api.py`, `daemon.py`, `scripts/run_full_cycle.py` is unrelated to this one): `scrapers/orchestrator.py:OpportunityOrchestrator` fans out to 25 scrapers under `scrapers/matrix/*_scrapers.py` (5 domains × 5 sources — infra/health/energy/defense/digital), each extending `scrapers/base_scraper.py:BaseScraper`. Results are scored by `ai_refinery.py:IntelligenceRefineryEngine` and matched against tenant product lines in `matching_engine.py`.

**Important:** the 25 scrapers in `scrapers/matrix/` still return hardcoded static `RawInstitutionalSignal` objects rather than performing live scraping — treat their data as fixtures, not live feeds. `BaseScraper.fetch_url()` (httpx, capped at 15 concurrent requests via a class-level semaphore) is real, though: each scraper calls it against its own `source_url` and stores the boolean result in `signal.metadata["live_fetch_verified"]`, so link liveness is genuinely checked even though the signal content is not.

### The production API's only persistent state is a file-backed newsletter cache

`api.py` (served via `server.py`, entrypoint `api:app`) still does not touch SQLite, Postgres, or Supabase at request time — grep confirms no `psycopg2`/`supabase`/`sqlite3` usage in `api.py`, `matching_engine.py`, or `workflow_engine.py`. Tenant config (`matching_engine.py:TENANT_ORGANIZATIONS`) and the deal pipeline (`workflow_engine.py:CONCURRENT_DEAL_PIPELINE`) are plain module-level Python dicts — all state resets on process restart. `DATABASE_URL`, `multi_tenancy_schema.sql`, and `supabase_security_hardening.sql` exist for a Postgres/Supabase-backed design but are not currently wired into the live request path.

The one exception is `cache_engine.py:newsletter_store` (`NewsletterStore`), which writes refined leads to `data/newsletter_cache.json` on disk and backs `/api/v1/newsletter/feed` and `routers/analysis.py`'s `/api/v1/analysis/market-trends`. This is separate from `cache_engine.py:global_cache` (`MemoryCacheEngine`, a pure in-memory TTL cache, default 90s, used for per-tenant feed responses). A background APScheduler job (`api.py:background_scraping_job`, wired via FastAPI `lifespan`) runs once immediately on process startup and every 6 hours after: it re-runs the orchestrator, saves the results into `newsletter_store`, dispatches high-score alerts, and invalidates `global_cache`. `render.yaml` defines only one Render service (the web API) — `daemon.py`'s standalone scheduler is not deployed separately, so `api.py`'s own in-process job is what actually keeps `newsletter_store` populated in production. Because Render's disk is ephemeral, that store is rebuilt from scratch on every restart/redeploy rather than truly persisting.

### Routers vs. inline routes

Most `addons/*.py` engines (independent, single-purpose, no shared base class: `caiet_analyzer`, `competitor_tracker`, `win_probability`) are invoked directly from routes inline in `api.py`. `business_eligibility`, `dossier_generator`, and `foia_generator` instead live behind `routers/eligibility.py` and `routers/drafting.py` — pulled out specifically so they map 1:1 to the frontend's standalone `/eligibility` and `/drafting` pages. `routers/analysis.py` is not an addon wrapper at all; it reads `newsletter_store` directly and aggregates totals/breakdowns for the `/analysis` page. All three are mounted in `api.py` via `app.include_router(...)`. If you add a new addon-backed feature that has (or will have) its own frontend route, extract it into `routers/` rather than adding it inline to `api.py`.

`ai_copilot.py:ProcurementAICopilot` is the conversational chat engine backing `/api/v1/copilot/chat` (inline in `api.py`, not a router), and is multi-provider (falls back across LLM providers — check `ai_copilot.py` for the current provider chain before assuming a single API key is required).

Cross-cutting concerns are separate small modules, not middleware classes: `security.py:SecurityGuard` (in-memory per-IP rate limiting), `freemium_shield.py:FreemiumGatekeeper` (redacts/locks leads past the free-tier limit), `billing.py` (Stripe + manual proforma invoice generation, RON/EUR plans), `notifier.py:LeadAlertDispatcher` (email/Telegram/Slack alert fan-out for high-score leads).

### Frontend

The app is split into standalone routed pages rather than one workspace component — each page owns its own data fetching and calls `lib/api.ts` directly: `/newsletter` (main feed), `/eligibility` (business eligibility scanner), `/drafting` (technical proposal + Legea 544 clarification generator, tabbed), `/analytics` (Copilot/Radar 72h, Competitor Radar, Caiet Scanner, Win Simulator, tabbed), `/analysis` (market-trends dashboard backed by `routers/analysis.py`), and `/pipeline` (deal pipeline). `/` is a landing dashboard (summary stats + links into the other pages), not a redirect. `components/intelligence-workspace.tsx` is leftover from before this split and is no longer imported anywhere — treat it as dead code, not a reference for current structure.

`components/NavBar.tsx` is mounted once in `app/layout.tsx` and is the only navigation: a slim fixed header with a hamburger button that opens a slide-out drawer listing all routes plus desk-switching and account actions (there is no horizontal tab bar). `components/EnterpriseModals.tsx` now holds only the three modals used globally from the nav (`PricingModal`, `AccountSettingsModal`, `WorkspaceDeskModal`) — tool-specific dialogs that used to live there (caiet scanner, competitor radar, win odds, clarification, copilot chat, etc.) were inlined into their corresponding page under `app/` during the route split; add new tool UI to its page, not back into this file.

`lib/api.ts` is the sole HTTP boundary to the backend — it auto-selects `http://localhost:8000` vs `https://api.ro-intel.xyz` based on `window.location.hostname`, and every function corresponds 1:1 to a FastAPI route in `api.py`/`routers/*.py`; when adding a backend endpoint, add the matching typed function here rather than calling `fetch` inline from components. Auth/session/desk-switching state lives in `context/AuthContext.tsx`, backed by Supabase auth (`lib/supabase.ts`) with tenant sync posted to the backend via `syncBackendAuth`.

The visual design follows BiziDay's real theme (colors/typography pulled from their live site, `wp-theme-biziday`): an indigo brand scale (`brand-50`…`brand-900`, base `#242a88`) defined via Tailwind v4 `@theme` tokens in `app/globals.css`, and Roboto loaded through `next/font/google` in `app/layout.tsx`. Use `brand-*` utility classes for accents rather than reintroducing `sky-*` or other ad hoc colors.

UI text is in Romanian (error messages, labels) — match that convention when touching user-facing frontend strings.
