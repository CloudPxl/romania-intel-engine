import logging
from datetime import date, datetime
from typing import Any, Dict, Optional

from scrapers.models import RawInstitutionalSignal
from text_utils import matching_terms

logger = logging.getLogger("AIRefinery")

# Single source of truth for what counts as a high-priority lead on the
# refinery's 0-10 scale. Import this instead of writing a literal: the
# scale is evidence-built and can be recalibrated, and hardcoded copies
# elsewhere would silently stop matching it (an earlier revision scored
# every signal 7.5-10.0, so callers still testing `>= 9.2` would have
# quietly stopped alerting altogether once the scale was corrected).
HIGH_PRIORITY_SCORE = 7.0

# Value bands in RON. Unknown (0.0) is treated as unknown, not as "small":
# most genuinely early signals (CNI register rows, ministry notices, EU
# funding calls) publish no figure at all, and scoring them as worthless
# buried exactly the leads that matter most.
VALUE_BANDS = [
    (100_000_000.0, 2.0, "Capital major (>100M RON)"),
    (30_000_000.0, 1.5, "Valoare ridicată (>30M RON)"),
    (10_000_000.0, 1.0, "Valoare medie (>10M RON)"),
    (1_000_000.0, 0.5, "Valoare mică (>1M RON)"),
]

# Where the opportunity sits in the procurement funnel. Earlier stages are
# worth more to a consultancy: the specification is still open to
# influence, and competitors have not yet mobilised.
STAGE_PROFILES = {
    "pre_tender_approved_indicators": {
        "label": "Indicatori tehnico-economici aprobați (pre-licitație)",
        "weight": 1.6,
        "action": "Fereastră optimă: contactați autoritatea înainte de redactarea caietului de sarcini.",
    },
    "pre_tender_documentation_review": {
        "label": "Analiză documentație (pre-licitație)",
        "weight": 1.4,
        "action": "Propuneți specificații tehnice în faza de documentare.",
    },
    "market_consultation": {
        "label": "Consultare de piață / dialog tehnic",
        "weight": 1.5,
        "action": "Depuneți punct de vedere tehnic conform Art. 139 Legea 98/2016.",
    },
    "funding_call": {
        "label": "Apel de finanțare deschis",
        "weight": 1.2,
        "action": "Verificați eligibilitatea și pregătiți dosarul înainte de termenul limită.",
    },
    "in_procurement": {
        "label": "Procedură de achiziție în derulare",
        "weight": 0.9,
        "action": "Analizați caietul de sarcini și pregătiți oferta.",
    },
    # The four below are stated explicitly by municipal_scrapers.py's
    # source-specific classification (PMB's own announcement titles
    # distinguish these cleanly) rather than inferred from keywords. They
    # were previously absent from this dict, so a declared stage of e.g.
    # "awarded" failed the `declared in STAGE_PROFILES` check in
    # _infer_stage below and silently fell through to weak text-based
    # guessing — the richer classification was being computed and then
    # thrown away.
    "annual_plan": {
        "label": "Plan anual de achiziții publicat",
        "weight": 1.3,
        "action": "Poziționare timpurie: contactați autoritatea înainte de publicarea caietului de sarcini individual.",
    },
    "tender_open": {
        "label": "Anunț de participare / licitație deschisă",
        "weight": 0.9,
        "action": "Analizați anunțul și caietul de sarcini; pregătiți oferta înainte de termenul limită.",
    },
    "awarded": {
        "label": "Contract atribuit (rezultat procedură)",
        # Deliberately below every actionable stage, including "unknown":
        # this is a closed procedure, not a lead to bid on. It is kept in
        # the feed (not dropped) because who won what, for how much, is
        # genuine competitive intelligence for addons/competitor_tracker.py
        # — but it must never outrank a real open opportunity on score.
        "weight": -1.0,
        "action": "Informație competitivă: analizați câștigătorul și valoarea contractului pentru poziționarea pe proceduri similare viitoare.",
    },
    "unknown": {
        "label": "Stadiu neconfirmat",
        "weight": 0.6,
        "action": "Confirmați stadiul procedurii la sursa oficială.",
    },
    "notice": {
        "label": "Anunț instituțional (stadiu nespecificat)",
        "weight": 0.6,
        "action": "Confirmați stadiul procedurii la sursa oficială.",
    },
}

CONSULTATION_TERMS = ["consultare", "dialog tehnic", "punct de vedere"]
PRE_TENDER_TERMS = ["indicatori", "studiu de fezabilitate", "avizare", "documentatie de avizare", "hotarare"]
FUNDING_TERMS = ["ghidul solicitantului", "apel", "finantare", "pnrr", "fonduri"]


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


class IntelligenceRefineryEngine:
    @staticmethod
    def _infer_stage(signal: RawInstitutionalSignal) -> str:
        """Derives the procurement stage from what the source actually said.

        Scrapers that know their stage state it in metadata; everything
        else is inferred from the text. This replaces a hardcoded
        'Consultare de Piață & Dialog Tehnic' that was reported for every
        signal regardless of what it was.
        """
        declared = (signal.metadata or {}).get("procurement_stage")
        if declared in STAGE_PROFILES:
            return declared

        text = f"{signal.project_title} {signal.raw_description} {signal.sub_category}"
        if matching_terms(text, CONSULTATION_TERMS):
            return "market_consultation"
        if matching_terms(text, FUNDING_TERMS) or "Apel" in signal.sub_category:
            return "funding_call"
        if matching_terms(text, PRE_TENDER_TERMS):
            return "pre_tender_approved_indicators"
        return "unknown"

    @staticmethod
    def _infer_funding(signal: RawInstitutionalSignal) -> str:
        """Checked most-specific first. The previous order tested PNRR
        before CNI, so a CNI project in the register's own 'Proiecte prin
        PNRR' category was mislabelled as generic national budget."""
        haystack = f"{signal.project_title} {signal.source_type} {signal.sub_category} {signal.entity_name}"
        if matching_terms(haystack, ["pnrr", "mipe", "mfe", "redresare", "rezilienta"]):
            return "PNRR / Fonduri Europene Nerambursabile"
        if matching_terms(haystack, ["fondul de modernizare", "modernizare ue"]):
            return "Fondul de Modernizare UE"
        if matching_terms(haystack, ["poim", "por", "poids", "fse", "feder", "programul sanatate"]):
            return "Fonduri Structurale UE (Program Operațional)"
        if matching_terms(haystack, ["cni"]):
            return "Buget Național CNI"
        if matching_terms(haystack, ["ministerul"]):
            return "Buget de Stat / Minister"
        return "Buget Local Municipal / Județean"

    @staticmethod
    def _build_pitch(signal: RawInstitutionalSignal, stage: str) -> str:
        """Category guidance plus what this specific signal supports.

        The category sentence is a genuine domain default; the rest is
        derived from the individual record, so two opportunities in the
        same category no longer receive byte-identical advice.
        """
        base = {
            "infrastructura": "Subliniați capacitatea de mobilizare a utilajelor, termenele de execuție și certificările ISO 9001/14001/45001.",
            "sanatate": "Evidențiați garanția extinsă (min. 36 luni), suportul tehnic cu intervenție sub 4 ore și compatibilitatea DICOM/HL7.",
            "energie": "Prezentați randamentul echipamentelor, protecțiile BESS și mentenanța predictivă SCADA.",
            "aparare": "Accentuați conformitatea NATO STANAG, criptarea hardware și avizele ORNISS.",
        }.get(signal.category, "Focalizați-vă pe arhitectura deschisă, API-uri documentate și SLA de disponibilitate.")

        extras = [STAGE_PROFILES.get(stage, STAGE_PROFILES["unknown"])["action"]]

        if signal.cpv_code:
            extras.append(f"Verificați corespondența ofertei cu codul CPV {signal.cpv_code}.")
        if signal.caen_codes:
            extras.append(f"Coduri CAEN relevante identificate în documentație: {', '.join(signal.caen_codes[:4])}.")
        if signal.document_url:
            extras.append("Documentația sursă este disponibilă pentru analiză detaliată.")
        if not signal.estimated_value_ron:
            extras.append("Valoarea nu este publicată — solicitați estimarea bugetară prin Legea 544/2001.")

        return " ".join([base] + extras)

    @staticmethod
    def refine_signal(signal: RawInstitutionalSignal) -> Dict[str, Any]:
        value = signal.estimated_value_ron or 0.0
        if value < 0:
            # No live parser can currently produce this (they all read
            # digit-only regex captures or non-negative JSON fields), so a
            # negative here means a parser has started reading the wrong
            # field. It is loud on purpose — clamping without the warning
            # would let that bug ride silently — but it is still clamped,
            # because the alternative is persisting a negative
            # `financial_value_ron` that then subtracts from
            # routers/analysis.py's total_market_value_ron and renders as a
            # negative RON figure in the feed. Treating it as unpublished is
            # the honest reading: we do not have a usable value.
            logger.warning(
                f"[AIRefinery] Negative estimated_value_ron ({value}) from {signal.source_type}/"
                f"{signal.source_id} — treating as unpublished; check that scraper's value parser."
            )
            value = 0.0
        stage = IntelligenceRefineryEngine._infer_stage(signal)
        stage_profile = STAGE_PROFILES.get(stage, STAGE_PROFILES["unknown"])

        # Scores are assembled from evidence rather than nudged off a high
        # baseline. The old version started at 7.5 and could only reach
        # 10.0, so every signal landed in the top quarter of the scale and
        # the number carried almost no information.
        score = 4.0
        drivers = []

        for threshold, weight, label in VALUE_BANDS:
            if value >= threshold:
                score += weight
                drivers.append(label)
                break
        else:
            if value == 0.0:
                drivers.append("Valoare nepublicată")

        score += stage_profile["weight"]
        drivers.append(stage_profile["label"])

        # Deadline urgency, computed from the real deadline when the source
        # published one.
        deadline = _parse_date(signal.action_deadline)
        days_left: Optional[int] = None
        if deadline:
            days_left = (deadline - date.today()).days
            if days_left < 0:
                score -= 2.5
                drivers.append("Termen expirat")
            elif days_left <= 7:
                score += 1.5
                drivers.append(f"Urgent — {days_left} zile rămase")
            elif days_left <= 21:
                score += 1.0
                drivers.append(f"Termen apropiat — {days_left} zile rămase")
            elif days_left <= 60:
                score += 0.5
                drivers.append(f"{days_left} zile până la termen")

        # Data completeness: a record we can act on immediately is worth
        # more than one that still needs research.
        if signal.cpv_code:
            score += 0.3
        if signal.caen_codes:
            score += 0.3
        if signal.document_url:
            score += 0.4
            drivers.append("Documentație atașată")

        final_score = max(0.0, min(10.0, round(score, 1)))

        timeline: Dict[str, Any] = {
            "current_stage": stage_profile["label"],
            "recommended_action": stage_profile["action"],
        }
        # Only state a deadline when the source actually published one. The
        # previous version asserted a fixed "T4 2026" launch window and a
        # "next 14 days" action window for every record, which was invented.
        if deadline:
            timeline["action_deadline"] = deadline.isoformat()
            timeline["days_remaining"] = days_left
        else:
            timeline["action_deadline"] = None
            timeline["days_remaining"] = None
            timeline["note"] = "Sursa nu publică un termen limită — de confirmat la autoritate."

        return {
            "source_id": signal.source_id,
            "source_type": signal.source_type,
            "category": signal.category,
            "sub_category": signal.sub_category,
            "county": signal.county,
            "locality": signal.locality,
            "project_title": signal.project_title,
            "entity_name": signal.entity_name,
            "financial_value_ron": value,
            "value_is_published": value > 0.0,
            "published_date": signal.published_date,
            "action_deadline": signal.action_deadline,
            "executive_summary": signal.raw_description,
            "sales_pitch_angle": IntelligenceRefineryEngine._build_pitch(signal, stage),
            "funding_source": IntelligenceRefineryEngine._infer_funding(signal),
            "procurement_stage": stage,
            "estimated_timeline": timeline,
            "opportunity_score": final_score,
            "score_drivers": drivers,
            "source_url": signal.source_url,
            "caen_codes": signal.caen_codes,
            "cpv_code": signal.cpv_code,
            "document_url": signal.document_url,
            "metadata": signal.metadata,
        }
