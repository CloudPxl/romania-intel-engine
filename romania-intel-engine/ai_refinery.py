import logging
from typing import Dict, Any
from scrapers.models import RawInstitutionalSignal

logger = logging.getLogger("AIRefinery")

class IntelligenceRefineryEngine:
    @staticmethod
    def refine_signal(signal: RawInstitutionalSignal) -> Dict[str, Any]:
        val = signal.estimated_value_ron
        title = signal.project_title.lower()
        desc = signal.raw_description.lower()

        score = 7.5
        if val >= 100000000.0:
            score += 2.0
        elif val >= 30000000.0:
            score += 1.4
        elif val >= 10000000.0:
            score += 0.8

        if any(kw in title or kw in desc for kw in ["consultare", "indicatori", "studiu de fezabilitate", "avizare", "ghid"]):
            score += 0.5

        final_score = min(10.0, round(score, 1))

        if signal.category == "infrastructura":
            pitch = (
                "Subliniați timpii rapizi de execuție, capacitatea de mobilizare a utilajelor grele și certificările ISO 9001/14001 "
                "pentru a securiza punctajul maxim la factorul de evaluare tehnică."
            )
        elif signal.category == "sanatate":
            pitch = (
                "Evidențiați garanția extinsă (minimum 36 luni), suportul tehnic 24/7 cu intervenție sub 4 ore și compatibilitatea DICOM/HL7 "
                "pentru integrarea directă cu sistemele spitalicești existente."
            )
        elif signal.category == "energie":
            pitch = (
                "Prezentați randamentul ridicat al celulelor solare (>22.5%), sistemele de protecție avansată BESS și capabilitatea de mentenanță predictivă SCADA."
            )
        elif signal.category == "aparare":
            pitch = (
                "Accentați conformitatea strictă cu standardele militare NATO STANAG, criptarea hardware rezistentă la interferențe și avizele de securitate ORNISS/NATO."
            )
        else:
            pitch = (
                "Focalizați-vă pe arhitectura deschisă bazată pe microservicii, API-urile REST documentate pentru interoperabilitate și SLA-ul de 99.9% disponibilitate în cloud."
            )

        if "PNRR" in signal.project_title or "MIPE" in signal.source_type or "PNRR" in signal.source_type:
            funding = "PNRR / Fonduri Europene Nerambursabile (100% Garantat)"
        elif "Modernizare" in signal.source_type or "Modernizare" in signal.project_title:
            funding = "Fondul de Modernizare UE"
        elif "CNI" in signal.source_type or "CNI" in signal.project_title:
            funding = "Buget Național CNI (Ministerul Dezvoltării)"
        else:
            funding = "Buget Local Municipal / Județean"

        return {
            "source_id": signal.source_id,
            "source_type": signal.source_type,
            "category": signal.category,
            "sub_category": signal.sub_category,
            "county": signal.county,
            "locality": signal.locality,
            "project_title": signal.project_title,
            "entity_name": signal.entity_name,
            "financial_value_ron": signal.estimated_value_ron,
            "published_date": signal.published_date,
            "action_deadline": signal.action_deadline,
            "executive_summary": signal.raw_description,
            "sales_pitch_angle": pitch,
            "funding_source": funding,
            "estimated_timeline": {
                "current_stage": "Consultare de Piață & Dialog Tehnic",
                "estimated_tender_launch": "T4 2026 (Octombrie - Noiembrie)",
                "recommended_action_window": "Următoarele 14 zile (Depunere punct de vedere tehnic)"
            },
            "opportunity_score": final_score,
            "source_url": signal.source_url,
            "metadata": signal.metadata
        }
