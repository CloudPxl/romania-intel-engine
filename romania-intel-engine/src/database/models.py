import os
import json
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

class TenantTier(str, Enum):
    STANDARD = "standard"
    ENTERPRISE = "enterprise"
    VIP = "vip"

class SourceCategory(str, Enum):
    PRE_SICAP = "pre_sicap"
    URBANISM = "urbanism"
    ENVIRONMENT = "environment"
    GRANTS = "grants"
    OPEN_DATA = "open_data"

@dataclass
class RawRecord:
    source_id: str
    category: SourceCategory
    county: str
    locality: Optional[str]
    institution: str
    document_title: str
    document_url: Optional[str]
    raw_metadata: Dict[str, Any]

@dataclass
class StructuredIntelItem:
    source_id: str
    category: str
    county: str
    locality: Optional[str]
    project_title: str
    entity_name: str
    financial_value_ron: Optional[float]
    executive_summary: str
    sales_pitch_angle: str
    trade_tags: List[str]
    opportunity_score: int
    action_deadline: Optional[str] = None
    source_url: Optional[str] = None

def is_postgres() -> bool:
    return bool(DATABASE_URL and DATABASE_URL.startswith("postgres"))

def get_db_connection():
    if is_postgres():
        import psycopg2
        return psycopg2.connect(DATABASE_URL)
    else:
        import sqlite3
        db_path = Path(__file__).resolve().parent.parent.parent / "database.sqlite3"
        conn = sqlite3.connect(str(db_path), timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    if not is_postgres():
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS raw_intel (
                source_id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                county TEXT NOT NULL,
                locality TEXT,
                institution TEXT NOT NULL,
                document_title TEXT NOT NULL,
                document_url TEXT,
                raw_metadata TEXT,
                scraped_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                processed_by_ai INTEGER DEFAULT 0
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS structured_intel (
                source_id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                county TEXT NOT NULL,
                locality TEXT,
                project_title TEXT NOT NULL,
                entity_name TEXT NOT NULL,
                financial_value_ron REAL,
                executive_summary TEXT NOT NULL,
                sales_pitch_angle TEXT NOT NULL,
                trade_tags TEXT NOT NULL,
                opportunity_score INTEGER NOT NULL,
                action_deadline TEXT,
                source_url TEXT,
                structured_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tenants (
                id TEXT PRIMARY KEY,
                company_name TEXT NOT NULL,
                fiscal_code_cui TEXT,
                contact_email TEXT NOT NULL,
                contact_phone TEXT,
                tier TEXT NOT NULL DEFAULT 'standard',
                is_active INTEGER DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tenant_filters (
                tenant_id TEXT PRIMARY KEY,
                allowed_counties TEXT NOT NULL,
                subscribed_trade_tags TEXT NOT NULL,
                min_financial_value_ron REAL DEFAULT 0,
                min_opportunity_score INTEGER DEFAULT 6,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                phone TEXT,
                full_name TEXT NOT NULL,
                avatar_url TEXT,
                auth_provider TEXT DEFAULT 'email',
                tenant_id TEXT,
                role TEXT DEFAULT 'owner',
                custom_ui_settings TEXT DEFAULT '{"advanced_mode": false, "theme": "dark", "instant_notifications": true}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_login DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE SET NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tenant_dispatches (
                tenant_id TEXT,
                source_id TEXT,
                matched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_sent INTEGER DEFAULT 0,
                PRIMARY KEY (tenant_id, source_id),
                FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
                FOREIGN KEY (source_id) REFERENCES structured_intel(source_id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scraper_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                adapter_name TEXT NOT NULL,
                status TEXT NOT NULL,
                records_ingested INTEGER DEFAULT 0,
                error_message TEXT,
                execution_time_ms REAL,
                logged_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    conn.close()

def is_record_scraped(source_id: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    ph = "%s" if is_postgres() else "?"
    cursor.execute(f"SELECT 1 FROM raw_intel WHERE source_id = {ph}", (source_id,))
    res = cursor.fetchone()
    conn.close()
    return res is not None

def save_raw_record(record: RawRecord) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    meta_json = json.dumps(record.raw_metadata, ensure_ascii=False)
    ph = "%s" if is_postgres() else "?"
    try:
        if is_postgres():
            query = f"""
                INSERT INTO raw_intel (source_id, category, county, locality, institution, document_title, document_url, raw_metadata)
                VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                ON CONFLICT (source_id) DO NOTHING
            """
        else:
            query = f"""
                INSERT OR IGNORE INTO raw_intel (source_id, category, county, locality, institution, document_title, document_url, raw_metadata)
                VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
            """
        cursor.execute(query, (
            record.source_id,
            record.category.value if isinstance(record.category, SourceCategory) else record.category,
            record.county,
            record.locality,
            record.institution,
            record.document_title,
            record.document_url,
            meta_json
        ))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def get_unprocessed_raw_records(limit: int = 200) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    if is_postgres():
        cursor.execute("""
            SELECT source_id, category, county, locality, institution, document_title, document_url, raw_metadata 
            FROM raw_intel 
            WHERE processed_by_ai = FALSE 
            ORDER BY scraped_at DESC LIMIT %s
        """, (limit,))
    else:
        cursor.execute("""
            SELECT source_id, category, county, locality, institution, document_title, document_url, raw_metadata 
            FROM raw_intel 
            WHERE processed_by_ai = 0 
            ORDER BY scraped_at DESC LIMIT ?
        """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    result = []
    for r in rows:
        result.append({
            "source_id": r[0],
            "category": r[1],
            "county": r[2],
            "locality": r[3],
            "institution": r[4],
            "document_title": r[5],
            "document_url": r[6],
            "raw_metadata": r[7] if isinstance(r[7], str) else json.dumps(r[7] or {})
        })
    return result

def save_structured_intel(item: StructuredIntelItem) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    tags_json = json.dumps(item.trade_tags, ensure_ascii=False)
    ph = "%s" if is_postgres() else "?"
    try:
        if is_postgres():
            query = f"""
                INSERT INTO structured_intel (
                    source_id, category, county, locality, project_title, entity_name,
                    financial_value_ron, executive_summary, sales_pitch_angle, trade_tags,
                    opportunity_score, action_deadline, source_url
                ) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                ON CONFLICT (source_id) DO UPDATE SET
                    opportunity_score = EXCLUDED.opportunity_score,
                    financial_value_ron = EXCLUDED.financial_value_ron,
                    sales_pitch_angle = EXCLUDED.sales_pitch_angle
            """
            cursor.execute(query, (
                item.source_id, item.category, item.county, item.locality, item.project_title,
                item.entity_name, item.financial_value_ron, item.executive_summary, item.sales_pitch_angle,
                tags_json, item.opportunity_score, item.action_deadline, item.source_url
            ))
            cursor.execute("UPDATE raw_intel SET processed_by_ai = TRUE WHERE source_id = %s", (item.source_id,))
        else:
            query = f"""
                INSERT OR REPLACE INTO structured_intel (
                    source_id, category, county, locality, project_title, entity_name,
                    financial_value_ron, executive_summary, sales_pitch_angle, trade_tags,
                    opportunity_score, action_deadline, source_url
                ) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
            """
            cursor.execute(query, (
                item.source_id, item.category, item.county, item.locality, item.project_title,
                item.entity_name, item.financial_value_ron, item.executive_summary, item.sales_pitch_angle,
                tags_json, item.opportunity_score, item.action_deadline, item.source_url
            ))
            cursor.execute("UPDATE raw_intel SET processed_by_ai = 1 WHERE source_id = ?", (item.source_id,))
        conn.commit()
        return True
    finally:
        conn.close()

def log_adapter_run(name: str, status: str, count: int, err: Optional[str], exec_time: float):
    conn = get_db_connection()
    cursor = conn.cursor()
    ph = "%s" if is_postgres() else "?"
    try:
        cursor.execute(f"""
            INSERT INTO scraper_logs (adapter_name, status, records_ingested, error_message, execution_time_ms)
            VALUES ({ph}, {ph}, {ph}, {ph}, {ph})
        """, (name, status, count, err, exec_time))
        conn.commit()
    finally:
        conn.close()
