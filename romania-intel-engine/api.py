from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import sqlite3
import json
import uvicorn
from src.database.models import get_db_connection, init_db
from src.notifications.exporter import LeadExporter

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(
    title="Romania B2B Intelligence Engine API",
    description="High-Yield Commercial Intelligence Platform for Romanian B2B Contractors & Consultancies",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for Next.js / v0 frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {
        "status": "online",
        "system": "Romania B2B Intelligence Engine",
        "docs_url": "http://127.0.0.1:8080/docs",
        "tenants_url": "http://127.0.0.1:8080/api/v1/tenants",
        "leads_url": "http://127.0.0.1:8080/api/v1/leads"
    }

@app.get("/api/v1/tenants")
def list_tenants():
    """Lists all registered corporate client tenants with their IDs."""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.id, t.company_name, t.fiscal_code_cui, t.contact_email, t.contact_phone, t.tier, t.is_active,
               f.allowed_counties, f.subscribed_trade_tags, f.min_financial_value_ron, f.min_opportunity_score
        FROM tenants t
        LEFT JOIN tenant_filters f ON t.id = f.tenant_id
        ORDER BY t.created_at DESC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    for r in rows:
        if r.get("allowed_counties"):
            r["allowed_counties"] = json.loads(r["allowed_counties"])
        if r.get("subscribed_trade_tags"):
            r["subscribed_trade_tags"] = json.loads(r["subscribed_trade_tags"])
        r["feed_url"] = f"/api/v1/tenants/{r['id']}/feed"
        r["export_csv_url"] = f"/api/v1/tenants/{r['id']}/export/csv"

    return {"count": len(rows), "tenants": rows}

@app.get("/api/v1/leads")
def get_leads(
    county: Optional[str] = None,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    min_score: int = Query(1, ge=1, le=10),
    min_value: Optional[float] = None,
    limit: int = 100
):
    """Search Feed with multi-attribute filtering."""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = "SELECT * FROM structured_intel WHERE opportunity_score >= ?"
    params = [min_score]

    if county and county.lower() != "all":
        query += " AND LOWER(county) LIKE ?"
        params.append(f"%{county.lower()}%")
    if category and category.lower() != "all":
        query += " AND category = ?"
        params.append(category)
    if tag:
        query += " AND LOWER(trade_tags) LIKE ?"
        params.append(f"%{tag.lower()}%")
    if min_value:
        query += " AND financial_value_ron >= ?"
        params.append(min_value)

    query += " ORDER BY opportunity_score DESC, financial_value_ron DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    for r in rows:
        r["trade_tags"] = json.loads(r["trade_tags"]) if isinstance(r["trade_tags"], str) else r["trade_tags"]

    return {"count": len(rows), "data": rows}

@app.get("/api/v1/tenants/{tenant_id}/feed")
def get_tenant_feed(tenant_id: str):
    """Retrieves all qualified, deduplicated leads matched to a tenant."""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM tenants WHERE id = ? AND is_active = 1", (tenant_id,))
    tenant = cursor.fetchone()
    if not tenant:
        conn.close()
        raise HTTPException(status_code=404, detail="Tenant not found or inactive")

    cursor.execute("""
        SELECT s.*, d.matched_at, d.is_sent
        FROM tenant_dispatches d
        JOIN structured_intel s ON d.source_id = s.source_id
        WHERE d.tenant_id = ?
        ORDER BY s.opportunity_score DESC, d.matched_at DESC
    """, (tenant_id,))

    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    for r in rows:
        r["trade_tags"] = json.loads(r["trade_tags"]) if isinstance(r["trade_tags"], str) else r["trade_tags"]

    return {
        "tenant_id": tenant_id,
        "company_name": tenant["company_name"],
        "tier": tenant["tier"],
        "lead_count": len(rows),
        "leads": rows
    }

@app.get("/api/v1/tenants/{tenant_id}/export/csv")
def export_tenant_leads_csv(tenant_id: str):
    """Direct 1-click CRM CSV download for paying tenants."""
    feed = get_tenant_feed(tenant_id)
    leads = feed["leads"]
    company_name = feed["company_name"]

    csv_content = LeadExporter.export_to_csv_string(leads)
    filename = f"Leads_{company_name.replace(' ', '_')}.csv"

    return Response(
        content=csv_content.encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8080)