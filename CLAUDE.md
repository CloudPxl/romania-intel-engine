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

`db.py` maintains a small `asyncpg` pool against Supabase Postgres (transaction-pooler-aware — `statement_cache_size=0` is set automatically when the connection string points at port 6543 / `*.pooler.supabase.com`, since the pooler can't hold per-session prepared statements). `api.py:_load_feed()` is the single read path used by the tenant feed, the copilot, and `routers/analysis.py`'s market-trends endpoint: it calls `db.get_recent_opportunities()` (which accepts optional `start_date`/`end_date`/`counties`/`categories`/`min_value_ron`/`max_value_ron` filters, pushed down into a dynamically-built SQL `WHERE` clause) fresh on every call — there is no caching at this layer, so a filtered market-analysis request always re-queries live. Only when Postgres returns nothing does it fall back to `cache_engine.py:newsletter_store` (`NewsletterStore`, a JSON file on Render's ephemeral disk, rebuilt from scratch on every restart) — and the same filters are re-applied in Python to that fallback so a degraded response still honors the request. `TENANT_ORGANIZATIONS` (`matching_engine.py`) remains a plain in-process dict, not database-backed — tenant/product config still resets on restart. The deal pipeline (`workflow_engine.py:ConcurrentWorkflowEngine`) is now Postgres-backed (`pipeline_schema.sql`: `product_bidding_deals`, `deal_stage_history`, via `db.py`'s `get_deals_for_tenant`/`add_deal`/`update_deal`/`record_stage_transition`) with `CONCURRENT_DEAL_PIPELINE` kept only as an in-memory fallback — every read/write tries Postgres first and only touches the dict when `DATABASE_URL` isn't set or the migration hasn't been applied yet (detected via `asyncpg.exceptions.UndefinedTableError`), so don't assume the dict is authoritative.

`/api/v1/system/tick` dispatches the ingestion run as a background task and acks immediately rather than blocking on it — it used to await the full run (observed live: 1s to 373s+), which routinely exceeded the GitHub Actions heartbeat's client-side timeout and caused curl's retries to fire a second overlapping tick on top of the still-running first one. A module-level `asyncio.Lock` (`api.py:_tick_lock`) makes an overlapping call a no-op ("already_running") instead of a pile-up.

`db.py:connectivity()` answers whether persistence is configured *and* reachable, and is surfaced as the `database` block on `/api/v1/system/status`; `db.is_available()` backs the same distinction on the read path, so `_load_feed` now sets `degraded` when the database is unreachable rather than only when a query raises. This matters because every read in `db.py` degrades by returning `None`/empty for both "no database" and "database has nothing" — without the explicit check, a completely unconfigured `DATABASE_URL` reached the UI as a calm "0 opportunities" and the heartbeat as a bare `is_stale`, with nothing anywhere pointing at the actual cause. Connection errors are redacted before being returned over HTTP (`db._redact`), since asyncpg echoes the DSN — which carries the password — in some parse errors.

`cache_engine.py:global_cache` (`MemoryCacheEngine`, in-memory TTL, default 90s) is a separate, purely-response-level cache layered on top of `_load_feed()` for per-tenant feed requests — invalidated by the background scraping job, not related to `newsletter_store`.

`workflow_engine.py:ConcurrentWorkflowEngine.get_pipeline_metrics()` (exposed at `GET /api/v1/tenants/{id}/pipeline/metrics`) computes weighted pipeline value using a stated stage-probability heuristic (not a trained model — the system has never ingested a real award result), plus real time-in-stage and funnel conversion rates derived from each deal's actual `stage_history` transition timestamps.

### Routers vs. inline routes

Most `addons/*.py` engines (independent, single-purpose, no shared base class: `caiet_analyzer`, `competitor_tracker`, `win_probability`) are invoked directly from routes inline in `api.py`. `business_eligibility`, `dossier_generator`, and `foia_generator` instead live behind `routers/eligibility.py` and `routers/drafting.py` — pulled out specifically so they map 1:1 to the frontend's standalone `/eligibility` and `/drafting` pages. `routers/drafting.py` also exposes `export-dossier-docx`/`export-clarification-docx` (streaming `.docx` downloads via `addons/docx_export.py`, python-docx) and an opt-in `use_ai_expansion` flag on the JSON generation endpoints that deepens the methodology/risk sections (`dossier_generator.py`/`foia_generator.py`'s `expand_with_ai()`) through the LLM chain described below — always additive, template output is a complete document on its own if no provider is configured. `routers/analysis.py` is not an addon wrapper at all; it reads `_load_feed()` directly (see above) and aggregates totals/breakdowns, with an opt-in `include_ai_report` flag for an LLM-synthesized strategic narrative. All three are mounted in `api.py` via `app.include_router(...)`. If you add a new addon-backed feature that has (or will have) its own frontend route, extract it into `routers/` rather than adding it inline to `api.py`.

`ai_copilot.py` is genuinely multi-provider with real sequential failover, not just a single configurable key: `list_llm_providers()` tries every configured provider (auto-detect order: groq, gemini, openai, xai — free-tier providers first, or forced via `LLM_PROVIDER`) and `complete_text()` walks the whole list, only giving up after every one fails. This is shared by `ProcurementAICopilot` (`/api/v1/copilot/chat`, inline in `api.py`) and by the document generators' `expand_with_ai()`. Note `render.yaml` names the xAI env var `GROK_API_KEY`, not `XAI_API_KEY` — `ai_copilot.py` reads both.

Cross-cutting concerns are separate small modules, not middleware classes. `security.py:SecurityGuard` now does two real things: `enforce_rate_limit` (180 req/60s per IP, in-process memory, wired in globally as `api.py:rate_limit_middleware` with a periodic stale-entry purge so the store can't grow unbounded) and `verify_tenant_authorization`, which decodes a real Supabase JWT via PyJWT against `SUPABASE_JWT_SECRET` (the project's actual JWT secret from the Supabase dashboard — NOT `NEXT_PUBLIC_SUPABASE_ANON_KEY`, which is itself a JWT and can't double as another token's verification key) and raises 401/503 rather than returning a fixed fake user. It is now applied via `Depends(require_auth)` to every tenant-scoped, add-on, copilot, drafting and eligibility route (`security.py` exposes `require_auth` for the hard gate and `optional_auth` for routes that stay public but behave differently when signed in). Public by design: `/`, `/health`, `/api/v1/system/*`, `/api/v1/tenants`, `/api/v1/billing/plans`, and `/api/v1/analysis/market-trends` — the last via `optional_auth`, which serves aggregates to anyone but empties `top_opportunities` for anonymous callers. **This authenticates, it does not authorize per tenant**: no user→tenant mapping is stored anywhere (`TENANT_ORGANIZATIONS` is a hardcoded dict, desks are per-browser localStorage), so a signed-in user can still address another tenant's id — closing that needs a real membership table, and the function's name does not by itself make it one. Two related hardenings shipped with it: `/api/v1/auth/sync` now takes the identity from the verified token instead of the request body (anyone could previously POST an arbitrary email and be handed a profile for it), and the tenant feed's `is_subscribed` is no longer a client-settable query param (it defaulted to `true` and was trivially spoofable, so `FreemiumGatekeeper` never actually withheld anything). `billing.py`'s `StripeBillingEngine` still has no Stripe SDK/API integration despite the name — it generates real HTML proforma invoices for manual bank-transfer payment, and `create_checkout_session()` just returns a "proforma required" response. `freemium_shield.py:FreemiumGatekeeper` (redacts/locks leads past the free-tier limit) and `notifier.py:LeadAlertDispatcher` (Telegram + email fan-out for high-score leads, gated by per-tenant `min_alert_score` and deduped via `db.has_alert_been_dispatched` — there is no Slack channel despite older docs mentioning one; unconfigured SMTP silently "succeeds" without sending) are both real, working logic.

### Frontend

The app is split into standalone routed pages rather than one workspace component — each page owns its own data fetching and calls `lib/api.ts` directly: `/` (front page: masthead, live public stat tiles from `fetchMarketTrends()`, lead story, section index), `/login` (two-column editorial screen, no NavBar — Supabase Google OAuth or email magic link), `/auth/callback` (**client** component, not a route handler — see below), `/newsletter` (the core product: filterable/searchable pre-tender feed with a slide-over dossier per lead), `/eligibility`, `/drafting` (tabbed: technical proposal + clarification/FOIA, both with `.docx` export and an opt-in AI-expansion flag), `/analytics` (Copilot + 72h briefing, market profile, caiet scanner, price positioning — 4 tabs), `/analysis` (market-trends dashboard with pushdown filters; the only tool page that renders for anonymous visitors), and `/pipeline` (saved deals + `fetchPipelineMetrics`, with stage transitions).

**Every page whose data comes from an authenticated route is wrapped in `components/AuthGate.tsx`**, which distinguishes "not signed in" from "signed in but the backend rejected the session" (`AuthContext`'s `authError`). `/analysis` and `/` are the exceptions — they render public aggregates for anonymous visitors and hide only lead-level detail.

`lib/api.ts` is the sole HTTP boundary (no component calls `fetch` directly). Everything goes through one `apiFetch()` wrapper that selects the base URL, attaches `Authorization: Bearer <token>` read fresh from `supabase.auth.getSession()` on every call (never cached — a cached token goes stale after an hour and starts 401-ing), and decodes FastAPI's `detail` field into a typed `ApiError` so the real backend message (including the Romanian ones from `SecurityGuard`) reaches the UI. Routes that must stay anonymous pass `anonymous: true`; file downloads pass `raw: true` and go through a blob + object-URL helper, because an authenticated endpoint cannot be reached by a plain `<a download href>` — that is why CSV export and both `.docx` exports are buttons, not links.

**Response shapes are the backend's, not the old UI's assumptions.** `predict-win-rate` returns a qualitative `assessment`/`competitiveness_band`/`factors[]`, *not* a `win_probability_score` — the engine refuses to emit a probability it cannot evidence. `competitor-analysis` returns `observed_market`/`pricing.reference_points_ron`/`data_limitations`, *not* `benchmark.historical_avg_discount` or a competitor list. `analyze-caiet` signals a clean document with a single sentinel flag of severity `"OK"` rather than an empty array. The pre-refactor frontend read the older field names on all three, so those panels rendered blank or `undefined` in production; when touching these, verify against a live response rather than the surrounding TypeScript.

"Companies" are modeled client-side as **Desks** (`BusinessDesk`) in `localStorage`, with no backend desk CRUD. Critically, **each desk carries a `tenant_id` naming a real key in `matching_engine.TENANT_ORGANIZATIONS`** (`GET /api/v1/tenants` lists them; `tenantIdForDomain()` maps a desk's domain onto one). The desk's own local id (`desk_main_infra`) is *not* a tenant id — passing it as one, which the app used to do everywhere, makes `evaluate_opportunity_for_tenant` fail closed and returns an empty feed with no error, which is what made the UI look permanently broken. `AuthContext.migrateDesks()` repairs desks saved before this binding existed. Always send `activeTenantId`, never `activeDesk.id`.

`/auth/callback` must stay a **client** component. It was a `route.ts` calling `exchangeCodeForSession()` server-side, which cannot work under PKCE: the code verifier lives in the browser's localStorage, so the exchange failed silently and bounced the user to `/` still signed out.

`components/NavBar.tsx` (mounted once in `app/layout.tsx`) is the only navigation: a sticky masthead with a dateline plus a slide-out drawer grouping routes into "Ediția"/"Instrumente", desk switching, and account actions. `components/EnterpriseModals.tsx` holds the three globally-invoked modals (`PricingModal`, `AccountSettingsModal`, `WorkspaceDeskModal`) over a shared `Modal` shell; tool-specific dialogs live inlined in their page under `app/`.

`components/newsprint.tsx` is the shared component vocabulary (`Button`, `Field`, `Input`, `Panel`, `StatCell`, `TabBar`, `Notice`, `EmptyState`, `Loading`, `DegradedBanner`, `PageHeader`, …). Compose from it rather than restating border/typography classes inline; `lib/format.ts` holds the RON/date/stage formatters.

### Design system: Newsprint

A deliberately **single-mode** design — ink (`#111111`) on newsprint (`#F9F9F7`), one accent (editorial red `#CC0000`) used sparingly. There is no dark variant and no theme toggle; every colour is stated explicitly in `app/globals.css` via Tailwind v4 `@theme` tokens (`paper`, `ink`, `rule`, `divider`, `editorial`, `stock-*`). **Border radius is zero everywhere** — the whole radius scale is zeroed in `@theme` so no component can reintroduce one. Four faces via `next/font/google`, exposed as `font-display` (Playfair Display, headlines), `font-body` (Lora, running text), `font-sans` (Inter, UI/labels) and `font-mono` (JetBrains Mono, data/metadata).

Collapsed newspaper grids use the **`.rule-grid`** utility, which draws its rules by letting the container's ink background show through a 1px `gap` — *not* by giving each child a `border-right` and stripping it from row-ending cells. That per-child approach only works at a fixed column count; a grid that is 2-up on tablet and 4-up on desktop has different row-ending cells per breakpoint and leaves a double rule on one of them. Other utilities: `.newsprint-texture` (graph-paper weave), `.hard-shadow-hover` (4px offset cut-out lift — needs a card on its own ground, not inside a `.rule-grid`), `.drop-cap`, `.label-eyebrow`, `.tabular`, `.scroll-x`.

Mobile is a first-class target, not a fallback: all interactive elements are `min-h-[44px]`, wide content scrolls inside `.scroll-x` containers so the body never scrolls sideways, filter panels collapse behind a toggle, and modals dock to the bottom edge on small screens.

`next.config.mjs` no longer sets `typescript.ignoreBuildErrors` — type errors fail the build, which is the point of having them. `npm run build` is therefore a real check; keep it that way.

UI text is in Romanian (error messages, labels) — match that convention when touching user-facing frontend strings.
