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
