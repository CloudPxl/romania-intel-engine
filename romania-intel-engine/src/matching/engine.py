import json
from typing import List, Dict, Any
from src.database.models import get_db_connection, is_postgres, TenantFilter, TenantTier

class MultiTenantMatchmaker:
    def __init__(self):
        pass

    def get_active_tenants_and_filters(self) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        cursor = conn.cursor()
        active_clause = "t.is_active = TRUE" if is_postgres() else "t.is_active = 1"
        cursor.execute(f"""
            SELECT t.id, t.company_name, t.tier, f.allowed_counties, f.subscribed_trade_tags,
                   f.min_financial_value_ron, f.min_opportunity_score
            FROM tenants t
            JOIN tenant_filters f ON t.id = f.tenant_id
            WHERE {active_clause}
        """)
        rows = cursor.fetchall()
        conn.close()

        tenants = []
        for r in rows:
            counties = json.loads(r[3]) if isinstance(r[3], str) else r[3]
            tags = json.loads(r[4]) if isinstance(r[4], str) else r[4]
            tenants.append({
                "tenant_id": r[0],
                "company_name": r[1],
                "tier": r[2],
                "allowed_counties": [str(c).lower() for c in (counties or [])],
                "subscribed_trade_tags": [str(t).lower() for t in (tags or [])],
                "min_value": float(r[5] or 0.0),
                "min_score": int(r[6] or 6)
            })
        return tenants

    def run_matchmaking(self) -> Dict[str, List[Dict[str, Any]]]:
        tenants = self.get_active_tenants_and_filters()
        if not tenants:
            return {}

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT source_id, category, county, locality, project_title, entity_name,
                   financial_value_ron, executive_summary, sales_pitch_angle, trade_tags,
                   opportunity_score, action_deadline, source_url
            FROM structured_intel
            ORDER BY structured_at DESC LIMIT 300
        """)
        records = cursor.fetchall()

        matched_summary = {t["tenant_id"]: [] for t in tenants}
        ph = "%s" if is_postgres() else "?"

        for r in records:
            source_id = r[0]
            county = (r[2] or "").lower()
            val_ron = float(r[6]) if r[6] is not None else None
            tags = json.loads(r[9]) if isinstance(r[9], str) else (r[9] or [])
            tags_lower = [str(t).lower() for t in tags]
            score = int(r[10] or 1)

            lead_obj = {
                "source_id": source_id,
                "category": r[1],
                "county": r[2],
                "locality": r[3],
                "project_title": r[4],
                "entity_name": r[5],
                "financial_value_ron": val_ron,
                "executive_summary": r[7],
                "sales_pitch_angle": r[8],
                "trade_tags": tags,
                "opportunity_score": score,
                "action_deadline": r[11],
                "source_url": r[12]
            }

            for t in tenants:
                if score < t["min_score"]:
                    continue
                if val_ron is not None and val_ron < t["min_value"]:
                    continue
                county_match = ("national" in t["allowed_counties"] or
                                "all" in t["allowed_counties"] or
                                county in t["allowed_counties"] or
                                "national" in county)
                if not county_match:
                    continue
                tag_match = any(tag in t["subscribed_trade_tags"] for tag in tags_lower) or ("*" in t["subscribed_trade_tags"])
                if not tag_match:
                    continue

                try:
                    if is_postgres():
                        cursor.execute(f"""
                            INSERT INTO tenant_dispatches (tenant_id, source_id, is_sent)
                            VALUES ({ph}, {ph}, FALSE)
                            ON CONFLICT (tenant_id, source_id) DO NOTHING
                        """, (t["tenant_id"], source_id))
                    else:
                        cursor.execute(f"""
                            INSERT OR IGNORE INTO tenant_dispatches (tenant_id, source_id, is_sent)
                            VALUES ({ph}, {ph}, 0)
                        """, (t["tenant_id"], source_id))
                    matched_summary[t["tenant_id"]].append(lead_obj)
                except Exception:
                    pass

        conn.commit()
        conn.close()
        return matched_summary
