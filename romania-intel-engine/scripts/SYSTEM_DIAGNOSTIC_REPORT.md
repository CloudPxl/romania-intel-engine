# Romania Intel Engine — System Diagnostic Report

**Generated:** 2026-08-21T14:55:08.817363Z
**Project Root:** `/Users/rosudavid/Romania intel agent/romania-intel-engine`

## Module Status

| Module | Status | Detail |
|--------|--------|--------|
| File Structure / Path Cleanliness | **PASS** | Orphan root .py files: none |
| Package __init__.py completeness | **PASS** | Missing: none |
| Bytecode / temp cleanliness | **PASS** | __pycache__ dirs found: 0 |
| Database / Table Integrity | **PASS** | Missing tables: none |
| Database / Index Parity | **PASS** | Missing indexes: none |
| Database / SQLite PRAGMA settings | **PASS** | WAL, foreign_keys, busy_timeout verified |
| Database / Pydantic model parity | **PASS** | RawRecord, StructuredIntelItem, TenantTier present |
| Scraper Adapters & Error Isolation | **PASS** | 5 adapters inherit BaseSourceAdapter |
| AI Refinement Engine | **PASS** | noise_skipped=True, valid_score=8, entity=Primăria Municipiului Iași |
| Multi-Tenant Matchmaking | **PASS** | tenant=eba2575a..., dispatches=1, duplicate_rerun=0 |
| Adapter Registry Load | **PASS** | registered=5 |
| Module Import / Syntax Soundness | **PASS** | all core modules import cleanly |
| E2E Pipeline Smoke (insert → AI → match) | **PASS** | inserted=True, still_pending=0, match_tenants=3 |

## Final Verdict

**PRODUCTION READY** — 13/13 checks passed.
