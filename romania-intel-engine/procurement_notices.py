"""Normalized, cross-notice-type procurement record — the richer sibling
of the lean `opportunities` table (scrapers/models.py:RawInstitutionalSignal).

Why a second schema instead of widening `opportunities`: the existing
table is deliberately lean because most of the 15+ scrapers in
scrapers/matrix/ can only ever populate a handful of its columns (a
municipal HTML listing has no award/attachment data to give). Adding
award_details/raw_attachments/CAEN/financial-breakdown columns there would
leave them NULL for every other source. This module instead gives SEAP
notices (which genuinely carry that richer structure) their own table,
written alongside — not instead of — the existing feed, via the same
db.with_connection() pool.

notice_type spans all five SEAP notice categories (CN/SC/DA/CAN/MC) so the
schema is ready for the ones not yet ingested. As of this module's initial
version, only DA (Direct Acquisitions) and CAN (Direct-Acquisition Award
Notices) are actually populated — see scrapers/matrix/direct_acquisition_scraper.py
for exactly which live e-licitatie.ro endpoints were verified and which
weren't (CN/SC's real public list endpoint could not be located; see that
file's module docstring before assuming a name for it).
"""

import hashlib
import json
import re
from typing import Any, Dict, List, Literal, Optional

import asyncpg
from pydantic import BaseModel, Field

import db

NoticeType = Literal["CN", "SC", "DA", "CAN", "MC"]


class ContractingAuthority(BaseModel):
    name: str
    cui: Optional[str] = None
    county: Optional[str] = None
    locality: Optional[str] = None
    contact_email: Optional[str] = None


class FinancialInfo(BaseModel):
    estimated_value_ron: float = 0.0
    currency: str = "RON"
    funding_source: Optional[str] = None
    eu_project_flag: bool = False


class AwardDetails(BaseModel):
    winning_bidder_name: Optional[str] = None
    winning_bidder_cui: Optional[str] = None
    awarded_value_ron: Optional[float] = None
    discount_pct: Optional[float] = None
    number_of_offers_received: Optional[int] = None


class Timeline(BaseModel):
    publication_date: Optional[str] = None
    bid_deadline_date: Optional[str] = None
    clarification_deadline_date: Optional[str] = None


class AttachmentRef(BaseModel):
    filename: str
    file_url: str
    file_type: Optional[str] = None
    size_bytes: Optional[int] = None


class ProcurementNotice(BaseModel):
    notice_id: str
    notice_type: NoticeType
    caen_codes: List[str] = Field(default_factory=list)
    cpv_code: Optional[str] = None
    contracting_authority: ContractingAuthority
    financial: FinancialInfo
    award_details: Optional[AwardDetails] = None
    timeline: Timeline = Field(default_factory=Timeline)
    raw_attachments: List[AttachmentRef] = Field(default_factory=list)
    source_url: Optional[str] = None

    def fingerprint(self) -> str:
        """SHA-256 over (notice_id, notice_type, estimated_value_ron), as
        specified. Note this is a content-change marker, not the dedup key
        — the value legitimately changes as a notice progresses (e.g. a
        direct-acquisition record updates once an offer is accepted), and
        keying the UPSERT on a hash that changes with the data would insert
        a duplicate row per update instead of revising the existing one.
        The real identity is (notice_id, notice_type); the fingerprint is
        stored alongside so a caller can cheaply tell "this notice's core
        financials changed since we last saw it" without diffing the row."""
        basis = f"{self.notice_id}_{self.notice_type}_{self.financial.estimated_value_ron}"
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()


_CUI_PREFIX_RE = re.compile(r"^(?:RO\s*)?(\d{2,10})\s+(.+)$")


def split_cui_and_name(raw: Optional[str]) -> "tuple[Optional[str], str]":
    """e-licitatie renders both suppliers and contracting authorities as one
    string, e.g. 'RO 6865630 DELTA PLUS TRADING S.R.L.' or
    '4317975 Unitatea Militara 01714' — CUI first, optionally RO-prefixed,
    then the legal name. Falls back to treating the whole string as the
    name when it doesn't match (safer than dropping the record)."""
    if not raw:
        return None, ""
    raw = raw.strip()
    m = _CUI_PREFIX_RE.match(raw)
    if m:
        return m.group(1), m.group(2).strip()
    return None, raw


def _to_jsonb(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


async def upsert_procurement_notice(notice: ProcurementNotice) -> bool:
    """Insert or refresh by (notice_id, notice_type). Returns True only for
    a brand-new row — same convention as db.upsert_opportunity."""
    fp = notice.fingerprint()
    async with db.with_connection() as conn:
        if conn is None:
            return True
        row = await conn.fetchrow(
            """
            INSERT INTO procurement_notices (
                notice_id, notice_type, fingerprint, caen_codes, cpv_code,
                contracting_authority, financial, award_details, timeline,
                raw_attachments, source_url, last_seen_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, now())
            ON CONFLICT (notice_id, notice_type) DO UPDATE SET
                fingerprint = EXCLUDED.fingerprint,
                financial = EXCLUDED.financial,
                award_details = EXCLUDED.award_details,
                timeline = EXCLUDED.timeline,
                cpv_code = EXCLUDED.cpv_code,
                last_seen_at = now()
            RETURNING (xmax = 0) AS inserted
            """,
            notice.notice_id,
            notice.notice_type,
            fp,
            notice.caen_codes,
            notice.cpv_code,
            _to_jsonb(notice.contracting_authority.model_dump()),
            _to_jsonb(notice.financial.model_dump()),
            _to_jsonb(notice.award_details.model_dump()) if notice.award_details else None,
            _to_jsonb(notice.timeline.model_dump()),
            _to_jsonb([a.model_dump() for a in notice.raw_attachments]),
            notice.source_url,
        )
    return bool(row["inserted"]) if row else True


async def get_ingest_state(notice_type: NoticeType) -> Optional[Dict[str, Any]]:
    """Read counterpart to update_ingest_state. Intentionally has no callers.

    Do not wire this into the scrapers as a "resume from last_item_id"
    checkpoint: SEAP's list endpoints were verified live to return items in
    no order (see the comment above the update_ingest_state call in
    scrapers/matrix/direct_acquisition_scraper.py), so stopping at the first
    already-seen id would silently skip notices published after it. The row
    is a record of when a sync last ran, not a resumption cursor.
    """
    async with db.with_connection() as conn:
        if conn is None:
            return None
        row = await conn.fetchrow(
            "SELECT last_synced_date, last_item_id FROM seap_ingest_state WHERE notice_type = $1",
            notice_type,
        )
    return dict(row) if row else None


async def update_ingest_state(notice_type: NoticeType, last_synced_date, last_item_id: Optional[str]) -> None:
    async with db.with_connection() as conn:
        if conn is None:
            return
        await conn.execute(
            """
            INSERT INTO seap_ingest_state (notice_type, last_synced_date, last_item_id, updated_at)
            VALUES ($1, $2, $3, now())
            ON CONFLICT (notice_type) DO UPDATE SET
                last_synced_date = EXCLUDED.last_synced_date,
                last_item_id = EXCLUDED.last_item_id,
                updated_at = now()
            """,
            notice_type, last_synced_date, last_item_id,
        )


# ---------------------------------------------------------------------------
# Award intelligence.
#
# What separates this from the rest of the analytics in this codebase is
# that award notices are the ONE place where a real outcome is recorded:
# who won, at what price, against how many bidders. Everything else the
# product computes is about procedures that have not been decided yet, so
# it can describe the market but never the result.
#
# That makes the honesty rule here stricter, not looser. Only CAN rows
# carry an award, and today only direct acquisitions produce them (see this
# module's docstring), so the coverage is genuinely narrow. Every function
# below reports the sample it computed from, and returns "no data" rather
# than a national average dressed up as a local one — a discount figure
# derived from four notices would otherwise drive a real pricing decision.
# ---------------------------------------------------------------------------

# Under this many awards, a median discount is an anecdote. Stated as a
# constant so the response can name the threshold it failed to meet.
MIN_AWARD_SAMPLE = 5


async def get_award_statistics(
    cpv_prefix: Optional[str] = None,
    county: Optional[str] = None,
    limit: int = 500,
) -> Dict[str, Any]:
    """Real winning-price behaviour, computed from ingested award notices.

    `cpv_prefix` matches on the leading digits of the CPV code — CPV is
    hierarchical (45000000 works, 45200000 building works), so a prefix is
    how you widen from "this exact thing" to "this family of things"
    without leaving the sector.

    Returns a dict that ALWAYS carries `sample_size` and `available`, so a
    caller cannot accidentally render a statistic computed from nothing.
    """
    empty = {
        "available": False,
        "sample_size": 0,
        "reason": "Nu există anunțuri de atribuire ingerate pentru acest filtru.",
        "cpv_prefix": cpv_prefix,
        "county": county,
    }

    async with db.with_connection() as conn:
        if conn is None:
            return {**empty, "reason": "Baza de date nu este disponibilă."}
        clauses = ["notice_type = 'CAN'", "award_details IS NOT NULL"]
        params: List[Any] = []
        if cpv_prefix:
            params.append(f"{cpv_prefix}%")
            clauses.append(f"cpv_code LIKE ${len(params)}")
        if county:
            # Reuses db._PG_COUNTY_KEY rather than restating the translate()
            # map: that map's two strings must stay the same length or
            # Postgres rejects the call at runtime, and a second copy is
            # exactly how they drift apart.
            params.append(db._county_key(county))
            county_expr = db._PG_COUNTY_KEY.format(
                col="COALESCE(contracting_authority->>'county', '')"
            )
            clauses.append(f"{county_expr} = ${len(params)}")
        params.append(limit)
        try:
            rows = await conn.fetch(
                f"""
                SELECT notice_id, cpv_code, contracting_authority, financial,
                       award_details, timeline
                FROM procurement_notices
                WHERE {' AND '.join(clauses)}
                ORDER BY last_seen_at DESC
                LIMIT ${len(params)}
                """,
                *params,
            )
        except asyncpg.exceptions.UndefinedTableError:
            return {**empty, "reason": "Tabela procurement_notices nu există — rulați schema.sql."}
        except Exception as e:  # pragma: no cover - defensive
            return {**empty, "reason": f"Interogarea a eșuat: {type(e).__name__}"}

    return summarize_awards([dict(r) for r in rows], cpv_prefix=cpv_prefix, county=county)


def _award_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flattens the JSONB columns into plain dicts, dropping any row whose
    award is not actually usable.

    A CAN row can exist with `award_details` present but the winning value
    missing — the notice was published, the figure was not. Those count
    toward "awards seen" and must not count toward any average, so they are
    separated here rather than silently coerced to zero.
    """
    out: List[Dict[str, Any]] = []
    for r in rows:
        award = r.get("award_details") or {}
        financial = r.get("financial") or {}
        authority = r.get("contracting_authority") or {}
        if isinstance(award, str):
            award = json.loads(award)
        if isinstance(financial, str):
            financial = json.loads(financial)
        if isinstance(authority, str):
            authority = json.loads(authority)
        out.append({
            "notice_id": r.get("notice_id"),
            "cpv_code": r.get("cpv_code"),
            "authority_name": authority.get("name"),
            "county": authority.get("county"),
            "estimated_value_ron": financial.get("estimated_value_ron") or 0.0,
            "winner": award.get("winning_bidder_name"),
            "winner_cui": award.get("winning_bidder_cui"),
            "awarded_value_ron": award.get("awarded_value_ron"),
            "offers": award.get("number_of_offers_received"),
        })
    return out


def _count_winners(awards: List[Dict[str, Any]]):
    from collections import Counter

    return Counter(a["winner"] for a in awards if a["winner"])


def _authority_profiles(awards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Who keeps winning at each authority.

    Named plainly as a count of observed awards, not an accusation: a firm
    can legitimately win repeatedly by being the only one qualified in a
    small county, and the concentration figure is evidence for a question,
    not an answer to it.
    """
    from collections import Counter

    by_authority: Dict[str, Counter] = {}
    for a in awards:
        if a["authority_name"] and a["winner"]:
            by_authority.setdefault(a["authority_name"], Counter())[a["winner"]] += 1
    profiles = []
    for authority, winners in by_authority.items():
        total = sum(winners.values())
        top_winner, top_count = winners.most_common(1)[0]
        profiles.append({
            "authority": authority,
            "awards_observed": total,
            "distinct_winners": len(winners),
            "top_winner": top_winner,
            "top_winner_share_pct": round(top_count / total * 100, 1),
        })
    profiles.sort(key=lambda x: x["awards_observed"], reverse=True)
    return profiles[:10]


def summarize_awards(
    rows: List[Dict[str, Any]],
    cpv_prefix: Optional[str] = None,
    county: Optional[str] = None,
) -> Dict[str, Any]:
    """Turns raw award rows into the three findings that actually change a
    bidding decision, or says why it cannot.

    Kept separate from the query so it is directly testable without a
    database, and so the same summary can be computed over rows obtained
    any other way.
    """
    import statistics as _stats
    from collections import Counter

    awards = _award_rows(rows)

    # A discount needs two DIFFERENT numbers. SEAP's direct-acquisition
    # award feed publishes only `awardedValue` — it carries no separate
    # pre-award estimate — so direct_acquisition_scraper._build_notice
    # stores that one figure in both `financial.estimated_value_ron` and
    # `award_details.awarded_value_ron`. Verified live against the feed:
    # 300 notices, every one of them with the two equal.
    #
    # Treating those as a 0% discount would be the single most damaging
    # number this product could publish: it would report "median winning
    # discount: 0.0%" over hundreds of real awards, and _classify_pressure
    # would then label every sector "Monopolizat" on the strength of it.
    # They are excluded from the priced set and counted separately, so the
    # response says "we have awards but no estimates to compare them to"
    # rather than inventing a comparison.
    no_estimate = [
        a for a in awards
        if (a["awarded_value_ron"] or 0) > 0
        and (a["estimated_value_ron"] or 0) > 0
        and abs(a["estimated_value_ron"] - a["awarded_value_ron"]) < 0.01
    ]
    priced = [
        a for a in awards
        if (a["awarded_value_ron"] or 0) > 0
        and (a["estimated_value_ron"] or 0) > 0
        and abs(a["estimated_value_ron"] - a["awarded_value_ron"]) >= 0.01
    ]

    result: Dict[str, Any] = {
        "available": len(priced) >= MIN_AWARD_SAMPLE,
        "sample_size": len(priced),
        "awards_seen": len(awards),
        "awards_without_estimate": len(no_estimate),
        "min_sample_required": MIN_AWARD_SAMPLE,
        "cpv_prefix": cpv_prefix,
        "county": county,
    }

    # Even without a discount, the winners themselves are real and worth
    # reporting — who keeps winning at a given authority is an observation
    # that needs no estimate at all.
    winners_all = _count_winners(awards)
    if winners_all:
        result["recurring_winners"] = [
            {"name": name, "awards": n, "share_pct": round(n / sum(winners_all.values()) * 100, 1)}
            for name, n in winners_all.most_common(8)
        ]
        result["authority_profiles"] = _authority_profiles(awards)

    if not priced:
        result["reason"] = (
            (
                f"Avem {len(no_estimate)} anunțuri de atribuire pentru acest filtru, dar feedul SEAP "
                "de achiziții directe publică doar valoarea atribuită, fără o valoare estimată "
                "separată — deci nu se poate calcula niciun discount câștigător. Câștigătorii "
                "observați sunt reali și sunt afișați mai jos."
            )
            if no_estimate
            else (
                "Niciun anunț de atribuire cu valoare atribuită pentru acest filtru. Ingerăm "
                "anunțuri de atribuire doar pentru achizițiile directe (SEAP CAN); pentru "
                "licitațiile deschise nu avem încă rezultate."
            )
        )
        return result

    # The winning discount: how far below the authority's own estimate the
    # winner actually bid. This is the number every other "average discount"
    # in this product refused to state, because until award ingestion there
    # was nothing to derive it from.
    discounts = [
        (1 - (a["awarded_value_ron"] / a["estimated_value_ron"])) * 100
        for a in priced
        if a["estimated_value_ron"] > 0
    ]
    result["winning_discount_pct"] = {
        "average": round(_stats.mean(discounts), 2),
        "median": round(_stats.median(discounts), 2),
        "min": round(min(discounts), 2),
        "max": round(max(discounts), 2),
    }

    # Recurring winners are computed over EVERY award, not just the priced
    # ones — winning repeatedly is an observation that does not need an
    # estimate behind it, and restricting it to the priced subset would
    # discard most of the real data.
    result["authority_profiles"] = _authority_profiles(awards)
    winners = _count_winners(awards)
    total_wins = sum(winners.values()) or 1
    result["recurring_winners"] = [
        {"name": name, "awards": n, "share_pct": round(n / total_wins * 100, 1)}
        for name, n in winners.most_common(8)
    ]

    offers = [a["offers"] for a in priced if a["offers"]]
    result["offers_per_procedure"] = (
        {"average": round(_stats.mean(offers), 1), "sample": len(offers)} if offers else None
    )

    result["competitive_pressure"] = _classify_pressure(
        winners=winners,
        total_awards=len(priced),
        median_discount=result["winning_discount_pct"]["median"],
        avg_offers=(_stats.mean(offers) if offers else None),
    )
    return result


def _classify_pressure(
    winners,
    total_awards: int,
    median_discount: float,
    avg_offers: Optional[float],
) -> Dict[str, Any]:
    """Names the shape of the competition, from the two signals that
    actually distinguish them: how concentrated the winners are, and how
    much of the estimate the winner had to give up.

    The label is a summary of the observed sample and says so — the bands
    are a stated convention, not a fitted model, and the evidence that
    produced the label travels with it so the reader can disagree.
    """
    top_share = (winners.most_common(1)[0][1] / total_awards * 100) if winners else 0.0

    if top_share >= 60 and median_discount < 5:
        label, code = "Monopolizat", "monopolized"
        detail = (
            f"Un singur ofertant câștigă {top_share:.0f}% din atribuirile observate, "
            f"cu un discount median de doar {median_discount:.1f}%. Intrarea este dificilă, "
            "dar marja aparentă este mare — verificați dacă există cerințe de calificare care vă exclud."
        )
    elif median_discount >= 20 or (avg_offers is not None and avg_offers >= 6):
        label, code = "Concurență agresivă", "cutthroat"
        detail = (
            f"Discount median de {median_discount:.1f}%"
            + (f", în medie {avg_offers:.1f} oferte pe procedură" if avg_offers else "")
            + ". Marja este strânsă; câștigă cine are costurile cele mai mici, nu cine ofertează cel mai des."
        )
    elif total_awards < 12 and median_discount < 10:
        label, code = "Slab acoperit", "under_served"
        detail = (
            f"Puține atribuiri observate ({total_awards}) și discount median mic "
            f"({median_discount:.1f}%) — semn de concurență redusă și marjă disponibilă."
        )
    else:
        label, code = "Concurență normală", "competitive"
        detail = (
            f"Discount median de {median_discount:.1f}% pe {total_awards} atribuiri observate, "
            "fără un câștigător dominant."
        )

    return {
        "label": label,
        "code": code,
        "detail": detail,
        "evidence": {
            "top_winner_share_pct": round(top_share, 1),
            "median_discount_pct": median_discount,
            "average_offers": round(avg_offers, 1) if avg_offers else None,
            "awards_analysed": total_awards,
        },
        "method_note": (
            "Clasificare pe praguri fixe, declarate, aplicate eșantionului observat — "
            "nu un model statistic. Dovezile sunt afișate ca să puteți verifica încadrarea."
        ),
    }
