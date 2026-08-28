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
npm run dev      # next dev, expects backend on http://localhost:8000
npm run build
npm run start
```

## Architecture

### Two parallel, unconnected backend pipelines

The engine directory contains two separate scraper/ingestion systems that do **not** share code. When working on ingestion or scoring, check which pipeline the entry point you're editing belongs to before assuming shared behavior:

1. **Legacy `src/` pipeline** (`main.py`, `test_ai.py`, `scripts/run_full_cycle.py`): `src/scrapers/sources/*` adapters extend `src/scrapers/base_adapter.py:BaseSourceAdapter`, persist into a local SQLite DB (`data/intel_local.db`, schema in `src/database/models.py`), and are scored by `src/ai/processor.py`. This path is not wired into the deployed API.
2. **Production pipeline** (`api.py`, `daemon.py`, `scripts/run_full_cycle.py` is unrelated to this one): `scrapers/orchestrator.py:OpportunityOrchestrator` fans out to 25 scrapers under `scrapers/matrix/*_scrapers.py` (5 domains × 5 sources — infra/health/energy/defense/digital), each extending `scrapers/base_scraper.py:BaseScraper`. Results are scored by `ai_refinery.py:IntelligenceRefineryEngine` and matched against tenant product lines in `matching_engine.py`.

**Important:** the 25 scrapers in `scrapers/matrix/` currently return hardcoded static `RawInstitutionalSignal` objects rather than performing live HTTP scraping — treat their data as fixtures, not live feeds, unless you've verified a given scraper actually fetches a URL.

### The production API is stateless / in-memory

`api.py` (served via `server.py`, entrypoint `api:app`) does not touch SQLite, Postgres, or Supabase at request time — grep confirms no `psycopg2`/`supabase`/`sqlite3` usage in `api.py`, `matching_engine.py`, or `workflow_engine.py`. Tenant config (`matching_engine.py:TENANT_ORGANIZATIONS`) and the deal pipeline (`workflow_engine.py:CONCURRENT_DEAL_PIPELINE`) are plain module-level Python dicts — all state resets on process restart. `DATABASE_URL`, `multi_tenancy_schema.sql`, and `supabase_security_hardening.sql` exist for a Postgres/Supabase-backed design but are not currently wired into the live request path — don't assume writes persist across a redeploy without checking the specific module first.

A background APScheduler job (`api.py:background_scraping_job`) re-runs the orchestrator every 6 hours and invalidates `cache_engine.py:global_cache` (a simple in-memory TTL cache, default 90s) — this is the only "refresh" mechanism; there's no webhook/push ingestion.

### Addon engines

`addons/*.py` are independent, single-purpose engines invoked directly from `api.py` routes (no shared base class): `caiet_analyzer` (spec-doc AI analysis), `competitor_tracker`, `dossier_generator`, `foia_generator` (legal clarification letters), `win_probability`, `business_eligibility`. `ai_copilot.py:ProcurementAICopilot` is the conversational chat engine backing `/api/v1/copilot/chat`, and is multi-provider (falls back across LLM providers — check `ai_copilot.py` for the current provider chain before assuming a single API key is required).

Cross-cutting concerns are separate small modules, not middleware classes: `security.py:SecurityGuard` (in-memory per-IP rate limiting), `freemium_shield.py:FreemiumGatekeeper` (redacts/locks leads past the free-tier limit), `billing.py` (Stripe + manual proforma invoice generation, RON/EUR plans), `notifier.py:LeadAlertDispatcher` (email/Telegram/Slack alert fan-out for high-score leads).

### Frontend

Single-page app under `app/page.tsx` rendering `components/intelligence-workspace.tsx` as the main authenticated workspace, with `components/EnterpriseModals.tsx` for paywall/billing/proposal dialogs. `lib/api.ts` is the sole HTTP boundary to the backend — it auto-selects `http://localhost:8000` vs `https://api.ro-intel.xyz` based on `window.location.hostname`, and every function corresponds 1:1 to a FastAPI route in `api.py`; when adding a backend endpoint, add the matching typed function here rather than calling `fetch` inline from components. Auth/session/desk-switching state lives in `context/AuthContext.tsx`, backed by Supabase auth (`lib/supabase.ts`) with tenant sync posted to the backend via `syncBackendAuth`.

UI text is in Romanian (error messages, labels) — match that convention when touching user-facing frontend strings.
