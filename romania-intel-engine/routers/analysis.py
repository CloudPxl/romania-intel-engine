from collections import defaultdict
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/v1/analysis", tags=["Market Analysis"])


@router.get("/market-trends")
async def get_market_trends(
    start_date: Optional[date] = Query(None, description="Include only opportunities on/after this date"),
    end_date: Optional[date] = Query(None, description="Include only opportunities on/before this date"),
    counties: Optional[List[str]] = Query(None, description="Repeat to filter to several counties, e.g. ?counties=Cluj&counties=Iasi"),
    categories: Optional[List[str]] = Query(None, description="Repeat to filter to several categories, e.g. ?categories=sanatate"),
    min_value_ron: Optional[float] = Query(None, ge=0),
    max_value_ron: Optional[float] = Query(None, ge=0),
    limit: int = Query(500, ge=1, le=2000),
    include_ai_report: bool = Query(False, description="Also synthesize an LLM strategic report over this exact slice (adds LLM latency)"),
):
    """Live market-trends aggregation over a customizable slice of the feed.

    Every filter is optional and additive; the aggregations below (county/
    category/funding breakdowns, totals, top opportunities) are computed
    *only* over whatever slice the caller asked for, and the query re-reads
    Postgres through _load_feed on every call — there is no result caching
    at this layer, so "only Health projects in Cluj over 1M RON" always
    reflects the current database, not a snapshot from whenever the server
    last ran the pipeline.
    """
    from api import _load_feed
    from ai_copilot import ProcurementAICopilot

    filters = {
        "start_date": start_date,
        "end_date": end_date,
        "counties": counties,
        "categories": categories,
        "min_value_ron": min_value_ron,
        "max_value_ron": max_value_ron,
        "limit": limit,
    }
    active_filters = {k: v for k, v in filters.items() if v not in (None, [])}

    store = await _load_feed(filters)
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

    # Heatmap intensity: value_ron normalized against the highest-value
    # county in *this* slice, so a filtered county list still produces a
    # meaningful 0-1 spread instead of every entry reading 1.0 because the
    # top nationwide county was filtered out.
    max_county_value = max((v["value_ron"] for v in by_county.values()), default=0.0)

    response = {
        "updated_at": store.get("updated_at"),
        "filters_applied": active_filters,
        "total_leads": len(leads),
        "total_market_value_ron": total_value_ron,
        "average_opportunity_score": round(score_sum / score_count, 1) if score_count else None,
        "by_county": [
            {
                "county": county,
                "count": v["count"],
                "value_ron": v["value_ron"],
                "heat_index": round(v["value_ron"] / max_county_value, 3) if max_county_value else 0.0,
            }
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

    if store.get("degraded"):
        response["degraded"] = True
        response["detail"] = store.get("detail")

    if include_ai_report:
        response["ai_strategic_report"] = await ProcurementAICopilot.generate_custom_market_report(leads, active_filters)

    return response
