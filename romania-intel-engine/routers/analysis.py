from collections import defaultdict
from fastapi import APIRouter

from cache_engine import newsletter_store

router = APIRouter(prefix="/api/v1/analysis", tags=["Market Analysis"])


@router.get("/market-trends")
async def get_market_trends():
    # Reads through the same Postgres-first loader as the feed, so the
    # dashboard does not go blank after a redeploy wipes Render's
    # ephemeral disk while the data is still safe in the database.
    from api import _load_feed

    store = await _load_feed()
    leads = store.get("leads", [])

    total_value_ron = 0.0
    by_county: dict = defaultdict(lambda: {"count": 0, "value_ron": 0.0})
    by_category: dict = defaultdict(lambda: {"count": 0, "value_ron": 0.0})
    by_funding_source: dict = defaultdict(lambda: {"count": 0, "value_ron": 0.0})
    score_sum = 0.0
    score_count = 0
    top_opportunities = []

    for lead in leads:
        value = lead.get("financial_value_ron") or 0
        county = lead.get("county") or "Necunoscut"
        category = lead.get("category") or "Necunoscut"
        funding_source = lead.get("funding_source") or "Necunoscut"
        score = lead.get("opportunity_score")

        total_value_ron += value

        by_county[county]["count"] += 1
        by_county[county]["value_ron"] += value

        by_category[category]["count"] += 1
        by_category[category]["value_ron"] += value

        by_funding_source[funding_source]["count"] += 1
        by_funding_source[funding_source]["value_ron"] += value

        if isinstance(score, (int, float)):
            score_sum += score
            score_count += 1

        top_opportunities.append({
            "project_title": lead.get("project_title"),
            "entity_name": lead.get("entity_name"),
            "county": county,
            "category": category,
            "financial_value_ron": value,
            "opportunity_score": score,
        })

    top_opportunities.sort(key=lambda o: o["financial_value_ron"] or 0, reverse=True)

    return {
        "updated_at": store.get("updated_at"),
        "total_leads": len(leads),
        "total_market_value_ron": total_value_ron,
        "average_opportunity_score": round(score_sum / score_count, 1) if score_count else None,
        "by_county": [
            {"county": county, "count": v["count"], "value_ron": v["value_ron"]}
            for county, v in sorted(by_county.items(), key=lambda kv: kv[1]["value_ron"], reverse=True)
        ],
        "by_category": [
            {"category": category, "count": v["count"], "value_ron": v["value_ron"]}
            for category, v in sorted(by_category.items(), key=lambda kv: kv[1]["value_ron"], reverse=True)
        ],
        "by_funding_source": [
            {"funding_source": fs, "count": v["count"], "value_ron": v["value_ron"]}
            for fs, v in sorted(by_funding_source.items(), key=lambda kv: kv[1]["value_ron"], reverse=True)
        ],
        "top_opportunities": top_opportunities[:10],
    }
