#!/usr/bin/env python3
"""
Isolated system health validation for romania-intel-engine.
Run from project root: python scripts/system_health_check.py
"""
from __future__ import annotations

import importlib
import inspect
import json
import sqlite3
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

REQUIRED_TABLES = {
    "raw_intel",
    "structured_intel",
    "tenants",
    "tenant_filters",
    "tenant_dispatches",
    "adapter_health_logs",
}

REQUIRED_INDEXES = {
    "raw_intel": {
        "idx_raw_intel_category",
        "idx_raw_intel_county",
        "idx_raw_intel_processed",
        "idx_raw_intel_scraped_at",
    },
    "structured_intel": {
        "idx_structured_score",
        "idx_structured_county",
        "idx_structured_trade_tags",
        "idx_structured_analyzed_at",
    },
    "tenants": {"idx_tenants_active", "idx_tenants_tier"},
    "tenant_filters": {"idx_tenant_filters_tenant"},
    "tenant_dispatches": {"idx_dispatches_tenant"},
}

REQUIRED_PACKAGES = [
    "src",
    "src.database",
    "src.scrapers",
    "src.scrapers.sources",
    "src.ai",
    "src.matching",
    "src.notifications",
    "src.utils",
]

REQUIRED_SCRAPERS = [
    "src.scrapers.sources.seap_consultations",
    "src.scrapers.sources.cluj_urbanism",
    "src.scrapers.sources.adr_national",
    "src.scrapers.sources.mipe_oportunitati",
    "src.scrapers.sources.datagov_ro",
]

REQUIRED_PRAGMAS = {
    "journal_mode": "wal",
    "foreign_keys": 1,
    "busy_timeout": 30000,
}


class HealthReport:
    def __init__(self) -> None:
        self.results: List[Tuple[str, bool, str]] = []

    def record(self, module: str, passed: bool, detail: str = "") -> None:
        self.results.append((module, passed, detail))

    @property
    def all_passed(self) -> bool:
        return all(passed for _, passed, _ in self.results)


def check_file_structure(report: HealthReport) -> None:
    engine_root = PROJECT_ROOT
    parent_root = engine_root.parent

    stray_py = [
        p for p in parent_root.glob("*.py")
        if p.parent == parent_root
    ]
    report.record(
        "File Structure / Path Cleanliness",
        len(stray_py) == 0,
        f"Orphan root .py files: {[p.name for p in stray_py] or 'none'}",
    )

    missing_init: List[str] = []
    for pkg in REQUIRED_PACKAGES:
        init_path = engine_root / pkg.replace(".", "/") / "__init__.py"
        if not init_path.exists():
            missing_init.append(str(init_path.relative_to(engine_root)))

    report.record(
        "Package __init__.py completeness",
        len(missing_init) == 0,
        f"Missing: {missing_init or 'none'}",
    )

    pycache_dirs = list(engine_root.rglob("__pycache__"))
    report.record(
        "Bytecode / temp cleanliness",
        len(pycache_dirs) == 0,
        f"__pycache__ dirs found: {len(pycache_dirs)}",
    )


def check_database_schema(report: HealthReport) -> sqlite3.Connection:
    from src.config import settings
    from src.database.models import (
        RawRecord,
        SourceCategory,
        StructuredIntelItem,
        TenantTier,
        get_db_connection,
        init_db,
        save_raw_record,
    )

    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    missing_tables = REQUIRED_TABLES - tables
    report.record(
        "Database / Table Integrity",
        len(missing_tables) == 0,
        f"Missing tables: {sorted(missing_tables) or 'none'}",
    )

    missing_indexes: List[str] = []
    cursor.execute("SELECT name, tbl_name FROM sqlite_master WHERE type='index'")
    index_map: Dict[str, set] = {}
    for idx_name, tbl in cursor.fetchall():
        index_map.setdefault(tbl, set()).add(idx_name)

    for table, expected in REQUIRED_INDEXES.items():
        present = index_map.get(table, set())
        for idx in expected:
            if idx not in present:
                missing_indexes.append(f"{table}.{idx}")

    report.record(
        "Database / Index Parity",
        len(missing_indexes) == 0,
        f"Missing indexes: {missing_indexes or 'none'}",
    )

    pragma_ok = True
    pragma_details: List[str] = []
    for key, expected in REQUIRED_PRAGMAS.items():
        row = conn.execute(f"PRAGMA {key};").fetchone()
        actual = row[0] if row else None
        if key == "journal_mode":
            ok = str(actual).lower() == expected
        else:
            ok = actual == expected
        if not ok:
            pragma_ok = False
            pragma_details.append(f"{key}={actual} (expected {expected})")

    report.record(
        "Database / SQLite PRAGMA settings",
        pragma_ok,
        "; ".join(pragma_details) or "WAL, foreign_keys, busy_timeout verified",
    )

    pydantic_ok = all(
        cls is not None
        for cls in (RawRecord, StructuredIntelItem, TenantTier, SourceCategory)
    )
    report.record("Database / Pydantic model parity", pydantic_ok, "RawRecord, StructuredIntelItem, TenantTier present")

    return conn


def check_scraper_adapters(report: HealthReport) -> None:
    from src.scrapers.base_adapter import BaseSourceAdapter
    from src.utils.http_client import fetch_with_retry, get_random_headers

    adapter_issues: List[str] = []
    for module_path in REQUIRED_SCRAPERS:
        mod = importlib.import_module(module_path)
        adapter_classes = [
            obj for _, obj in inspect.getmembers(mod, inspect.isclass)
            if issubclass(obj, BaseSourceAdapter) and obj is not BaseSourceAdapter
        ]
        if not adapter_classes:
            adapter_issues.append(f"{module_path}: no adapter class")
            continue
        for cls in adapter_classes:
            if not hasattr(cls, "fetch_latest"):
                adapter_issues.append(f"{cls.__name__}: missing fetch_latest")
            if "generate_source_id" not in BaseSourceAdapter.__dict__:
                adapter_issues.append("BaseSourceAdapter: missing generate_source_id")

    src = inspect.getsource(BaseSourceAdapter.execute_safe)
    execute_safe_ok = "try:" in src and "except Exception" in src and "log_adapter_run" in src
    if not execute_safe_ok:
        adapter_issues.append("BaseSourceAdapter.execute_safe incomplete")

    http_ok = callable(fetch_with_retry) and callable(get_random_headers)
    if not http_ok:
        adapter_issues.append("http_client utilities missing")

    report.record(
        "Scraper Adapters & Error Isolation",
        len(adapter_issues) == 0 and execute_safe_ok and http_ok,
        "; ".join(adapter_issues) or f"{len(REQUIRED_SCRAPERS)} adapters inherit BaseSourceAdapter",
    )


def check_ai_processor(report: HealthReport) -> None:
    from src.ai.processor import RomanianIntelAIProcessor

    processor = RomanianIntelAIProcessor()
    noise = processor.refine_record({"document_title": "Contact", "category": "grants", "source_id": "x"})
    empty = processor.refine_record({"category": "grants"})
    valid = processor.refine_record({
        "source_id": "health-check-ai",
        "document_title": "Proiect construire hala industriala depozit logistica Cluj",
        "category": "urbanism",
        "county": "National",
        "institution": "Primaria Municipiului Cluj-Napoca",
        "locality": "Cluj-Napoca",
        "document_url": "https://example.ro/permit",
        "raw_metadata": json.dumps({"beneficiary": "SC Test Construct SRL", "estimated_value_ron": 2500000}),
    })

    diacritics_entity = processor._extract_real_entity(
        {"county": "Iasi", "institution": "SEAP"},
        {},
        "Autorizatie construire ansamblu locuinte Primăria Municipiului Iași",
    )

    ok = (
        noise is None
        and empty is None
        and valid is not None
        and valid.opportunity_score >= 6
        and "Prim" in diacritics_entity
    )
    report.record(
        "AI Refinement Engine",
        ok,
        f"noise_skipped={noise is None}, valid_score={getattr(valid, 'opportunity_score', None)}, entity={diacritics_entity[:40]}",
    )


def check_matchmaking(report: HealthReport, conn: sqlite3.Connection) -> None:
    from src.database.models import (
        RawRecord,
        SourceCategory,
        save_raw_record,
        save_structured_intel,
        StructuredIntelItem,
    )
    from src.matching.engine import MultiTenantMatchmaker, _safe_json_list

    malformed = _safe_json_list("{not-json", default=["all"])
    empty = _safe_json_list("[]", default=["all"])

    matchmaker = MultiTenantMatchmaker()
    tenant_id = matchmaker.register_tenant(
        company_name="HealthCheck SRL",
        contact_email="qa@healthcheck.test",
        contact_phone="+40000000000",
        tier="trial",
        allowed_counties=["all"],
        subscribed_trade_tags=["constructii_civile_industriale"],
        min_value_ron=100000,
        min_score=6,
    )

    source_id = f"health-{uuid.uuid4().hex[:12]}"
    save_raw_record(RawRecord(
        source_id=source_id,
        category=SourceCategory.URBANISM,
        county="Cluj",
        locality="Cluj-Napoca",
        institution="Health Check Institution",
        document_title="Health Check Construction Project",
        processed_by_ai=True,
    ))
    save_structured_intel(StructuredIntelItem(
        source_id=source_id,
        category="urbanism",
        county="Cluj",
        locality="Cluj-Napoca",
        project_title="Health Check Construction Project",
        entity_name="SC Health Construct SRL",
        financial_value_ron=500000.0,
        executive_summary="Synthetic health-check lead.",
        sales_pitch_angle="Contact developer for civil works package.",
        trade_tags=["constructii_civile_industriale"],
        opportunity_score=8,
        source_url="https://example.ro/health",
    ))

    matches = matchmaker.run_matchmaking()
    second_pass = matchmaker.run_matchmaking()

    dispatch_count = conn.execute(
        "SELECT COUNT(*) FROM tenant_dispatches WHERE tenant_id = ? AND source_id = ?",
        (tenant_id, source_id),
    ).fetchone()[0]

    ok = (
        malformed == ["all"]
        and empty == []
        and tenant_id
        and source_id in {lead["source_id"] for lead in matches.get(tenant_id, [])}
        and dispatch_count == 1
        and len(second_pass.get(tenant_id, [])) == 0
    )
    report.record(
        "Multi-Tenant Matchmaking",
        ok,
        f"tenant={tenant_id[:8]}..., dispatches={dispatch_count}, duplicate_rerun={len(second_pass.get(tenant_id, []))}",
    )


def check_registry_and_imports(report: HealthReport) -> None:
    from src.scrapers.registry import registry, ScraperRegistry
    from src.scrapers.sources.seap_consultations import SeapMarketConsultationAdapter
    from src.scrapers.sources.cluj_urbanism import ClujUrbanismAdapter
    from src.scrapers.sources.adr_national import NationalAdrHubAdapter
    from src.scrapers.sources.mipe_oportunitati import MipeOportunitatiAdapter
    from src.scrapers.sources.datagov_ro import DataGovRoAdapter

    test_registry = ScraperRegistry()
    adapters = [
        SeapMarketConsultationAdapter(),
        ClujUrbanismAdapter(),
        NationalAdrHubAdapter(),
        MipeOportunitatiAdapter(),
        DataGovRoAdapter(),
    ]
    for adapter in adapters:
        test_registry.register(adapter)

    loaded = test_registry.get_all()
    report.record(
        "Adapter Registry Load",
        len(loaded) == 5,
        f"registered={len(loaded)}",
    )

    import_errors: List[str] = []
    modules = [
        "main",
        "daemon",
        "src.config",
        "src.database.models",
        "src.ai.processor",
        "src.matching.engine",
        "src.notifications.dossier",
    ]
    for mod in modules:
        try:
            importlib.import_module(mod)
        except Exception as exc:
            import_errors.append(f"{mod}: {exc}")

    report.record(
        "Module Import / Syntax Soundness",
        len(import_errors) == 0,
        "; ".join(import_errors) or "all core modules import cleanly",
    )


def run_pipeline_smoke(report: HealthReport) -> None:
    from src.database.models import (
        RawRecord,
        SourceCategory,
        get_unprocessed_raw_records,
        init_db,
        mark_raw_record_processed,
        save_raw_record,
    )
    from src.ai.processor import RomanianIntelAIProcessor
    from src.matching.engine import MultiTenantMatchmaker

    init_db()
    source_id = f"smoke-{uuid.uuid4().hex[:12]}"
    inserted = save_raw_record(RawRecord(
        source_id=source_id,
        category=SourceCategory.PRE_SICAP,
        county="National",
        locality="National",
        institution="Health Check Authority",
        document_title="Consultare piata lucrari constructii drumuri asfaltare national",
        document_url="https://example.ro/smoke",
        raw_metadata={"estimated_value_ron": 1500000, "authority_name": "Primaria Municipiului Timisoara"},
    ))

    pending_before = get_unprocessed_raw_records(limit=500)
    processor = RomanianIntelAIProcessor()
    processed = processor.process_pending_records(limit=500)
    pending_after = [r for r in get_unprocessed_raw_records(limit=500) if r["source_id"] == source_id]

    matchmaker = MultiTenantMatchmaker()
    matchmaker.register_tenant(
        company_name="Smoke Test Tenant",
        contact_email="smoke@test.local",
        contact_phone="",
        tier="standard",
        allowed_counties=["timis", "national"],
        subscribed_trade_tags=["infrastructura_drumuri_asfalt"],
        min_value_ron=500000,
        min_score=6,
    )
    matches = matchmaker.run_matchmaking()

    ok = inserted and source_id not in [r["source_id"] for r in pending_after] and processed >= 0
    report.record(
        "E2E Pipeline Smoke (insert → AI → match)",
        ok,
        f"inserted={inserted}, still_pending={len(pending_after)}, match_tenants={len(matches)}",
    )


def render_markdown(report: HealthReport) -> str:
    lines = [
        "# Romania Intel Engine — System Diagnostic Report",
        "",
        f"**Generated:** {datetime.utcnow().isoformat()}Z",
        f"**Project Root:** `{PROJECT_ROOT}`",
        "",
        "## Module Status",
        "",
        "| Module | Status | Detail |",
        "|--------|--------|--------|",
    ]
    for module, passed, detail in report.results:
        status = "PASS" if passed else "FAIL"
        detail_safe = detail.replace("|", "\\|")[:120]
        lines.append(f"| {module} | **{status}** | {detail_safe} |")

    verdict = "PRODUCTION READY" if report.all_passed else "NEEDS REMEDIATION"
    lines.extend([
        "",
        "## Final Verdict",
        "",
        f"**{verdict}** — {sum(1 for _, p, _ in report.results if p)}/{len(report.results)} checks passed.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    report = HealthReport()
    check_file_structure(report)
    conn = check_database_schema(report)
    check_scraper_adapters(report)
    check_ai_processor(report)
    check_matchmaking(report, conn)
    check_registry_and_imports(report)
    run_pipeline_smoke(report)
    conn.close()

    markdown = render_markdown(report)
    report_path = PROJECT_ROOT / "scripts" / "SYSTEM_DIAGNOSTIC_REPORT.md"
    report_path.write_text(markdown, encoding="utf-8")

    print(markdown)
    print(f"\nReport written to: {report_path}")
    return 0 if report.all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
