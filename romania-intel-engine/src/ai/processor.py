import json
import re
from typing import Dict, Any, Optional, List
from src.database.models import (
    StructuredIntelItem,
    save_structured_intel,
    get_unprocessed_raw_records,
    get_db_connection,
    is_postgres
)

ROMANIAN_COUNTIES = [
    "Alba", "Arad", "Arges", "Bacau", "Bihor", "Bistrita-Nasaud", "Botosani", "Brasov",
    "Braila", "Bucuresti", "Buzau", "Caras-Severin", "Calarasi", "Cluj", "Constanta",
    "Covasna", "Dambovita", "Dolj", "Galati", "Giurgiu", "Gorj", "Harghita", "Hunedoara",
    "Ialomita", "Iasi", "Ilfov", "Maramures", "Mehedinti", "Mures", "Neamt", "Olt",
    "Prahova", "Satu Mare", "Salaj", "Sibiu", "Suceava", "Teleorman", "Timis", "Tulcea",
    "Vaslui", "Valcea", "Vrancea"
]

NAVIGATIONAL_JUNK = [
    "prezentari program", "ghiduri de finantare active", "ghiduri de finantare in consultare",
    "comunicate de presa", "noutati", "arhiva", "contact", "galerie", "legislatie",
    "despre noi", "calendar orientativ"
]

class RomanianIntelAIProcessor:
    def _is_noise(self, title: str) -> bool:
        t = title.lower().strip()
        if len(t) < 18:
            return True
        return any(junk in t for junk in NAVIGATIONAL_JUNK)

    def _resolve_county(self, current_county: str, text: str) -> str:
        t_clean = text.lower()
        for county in ROMANIAN_COUNTIES:
            c = county.lower()
            if f"judetul {c}" in t_clean or f"jud. {c}" in t_clean or f" {c} " in f" {t_clean} ":
                return county
        return current_county

    def _clean_title(self, raw_title: str) -> str:
        cleaned = re.sub(r"^\[(?:LUCRARI|FURNIZARE|SERVICII|Vest|Nord-Est|Centru|Nord-Vest)\]\s*", "", raw_title, flags=re.IGNORECASE)
        return cleaned.strip()

    def _extract_entity(self, raw_record: Dict[str, Any], meta: Dict[str, Any], text: str) -> str:
        candidate = meta.get("authority_name") or meta.get("beneficiary") or raw_record.get("institution", "")
        is_generic = not candidate or any(g in candidate.lower() for g in [
            "autoritate contractanta", "autoritate publica", "necunoscuta", "persoana fizica", "seap", "sicap"
        ])

        if is_generic:
            match = re.search(
                r"((?:Prim[aă]ria\s+(?:Municipiului|Comunei|Orașului)?\s*[A-ZĂÎÂȘȚa-zăîâșț\-]+)|"
                r"(?:Consiliul\s+Județean\s+[A-ZĂÎÂȘȚa-zăîâșț\-]+)|"
                r"(?:Spitalul\s+(?:Clinic|Județean|Municipal|de Urgență)?\s*[A-ZĂÎÂȘȚa-zăîâșț\s\-]+)|"
                r"(?:Comuna\s+[A-ZĂÎÂȘȚa-zăîâșț\-]+)|"
                r"(?:Municipiul\s+[A-ZĂÎÂȘȚa-zăîâșț\-]+)|"
                r"(?:Compania\s+Națională\s+[A-ZĂÎÂȘȚa-zăîâșț\s\-]+))",
                text, re.IGNORECASE
            )
            if match:
                return match.group(1).strip().title()

            if any(k in text.lower() for k in ["oncologice", "medicamente", "medicale", "spital"]):
                return "Unitate Sanitară Publică / CAS"

            co = re.search(r"(S\.?C\.?\s+[A-Z0-9\s\.\-]{3,35}(?:S\.?R\.?L\.?|S\.?A\.?))", text, re.IGNORECASE)
            if co:
                return co.group(1).strip()

            c_name = raw_record.get("county", "National")
            return f"Autoritate Publică ({c_name})"
        return candidate.strip()

    def _categorize(self, text: str) -> List[str]:
        tags = []
        low = text.lower()
        taxonomy = {
            "infrastructura_drumuri_asfalt": ["covor", "asfalt", "drum", "strada", "pod", "pasaj", "carosabil", "trotuar", "sens giratoriu", "reabilitare drum"],
            "constructii_civile_industriale": ["construire", "hala", "depozit", "cladire", "imobil", "locuinte", "etaje", "structura", "arhitectura", "parc industrial"],
            "energie_regenerabila_fotovoltaic": ["fotovoltaic", "parc solar", "panouri solare", "eolian", "biomasa", "stocare energie", "invertor", "evacuare putere"],
            "instalatii_hvac_sanitare": ["hvac", "climatizare", "ventilatie", "sanitare", "termice", "conducte", "canalizare", "apa", "epurare"],
            "demolari_si_dezafectari": ["demolare", "turnuri", "dezafectare", "casare", "ecologizare", "desfiintare"],
            "echipamente_medicale_pharma": ["medicament", "spital", "medical", "sanatate", "rmn", "radiologie", "aparatura medicala", "oncologice", "dispozitive medicale"],
            "flota_auto_transport": ["autoturism", "anvelope", "vehicul", "camion", "microbuz", "transport"],
            "fonduri_ue_granturi_imm": ["ghid", "apel", "grant", "finantare", "imm", "digitalizare", "nerambursabil", "pnrr", "regio", "ajutor de stat"]
        }
        for tag, words in taxonomy.items():
            if any(w in low for w in words):
                tags.append(tag)
        return tags if tags else ["achizitii_publice_generale"]

    def _calculate_score(self, category: str, val_ron: Optional[float], text: str) -> int:
        low = text.lower()
        if val_ron and val_ron < 50000:
            if any(k in low for k in ["anvelope", "consumabile", "papetarie", "toner"]):
                return 3
            return 4

        if val_ron:
            if val_ron >= 5000000:
                return 10
            elif val_ron >= 1000000:
                return 9
            elif val_ron >= 250000:
                return 8
            elif val_ron >= 50000:
                return 7
            return 5

        if category == "environment" and any(k in low for k in ["fotovoltaic", "parc", "hala", "fabrica"]):
            return 9
        if category == "urbanism" and len(text) > 35:
            return 8
        if category == "grants":
            return 8
        return 6

    def _build_action_plan(self, category: str, entity: str, tags: List[str], val_ron: Optional[float], deadline: str) -> str:
        main_tag = tags[0].replace("_", " ").title()
        if category == "environment":
            return (
                f"1. Faza Pre-Construcție (Aviz APM). Contactați direct echipa tehnică a {entity}. "
                f"2. Ofertați pachete de subcontractare pentru {main_tag} înainte de emiterea autorizației de construire. "
                f"3. Obiectiv: Încheiere acord de parteneriat în faza de proiectare."
            )
        elif category == "urbanism":
            return (
                f"1. Autorizație de Construire emisă pentru {entity}. "
                f"2. Contactați direct antreprenorul general / dezvoltatorul pe domeniul {main_tag}. "
                f"3. Transmiteți oferta comercială înainte de organizarea licitației de execuție."
            )
        elif category == "pre_sicap":
            val_txt = f" (Valoare estimată: {val_ron:,.0f} RON)" if val_ron else ""
            return (
                f"1. Oportunitate activă la {entity}{val_txt}. "
                f"2. Accesați caietul de sarcini pe nișa {main_tag} și încărcați oferta în catalogul electronic. "
                f"3. Termen de acțiune: {deadline}."
            )
        elif category == "grants":
            return (
                f"1. Selectați companiile eligibile din portofoliul clienților pe axa {main_tag}. "
                f"2. Elaborați cererea de finanțare conform ghidului solicitantului lansat de {entity}. "
                f"3. Propuneți pachet complet: Scriere proiect + Consultanță cu comision de succes (3%-8%)."
            )
        return f"Contactați comisia tehnică a {entity} pentru pachetul de {main_tag}."

    def refine_record(self, raw: Dict[str, Any]) -> Optional[StructuredIntelItem]:
        raw_title = raw["document_title"].strip()
        category = raw["category"]
        meta = json.loads(raw.get("raw_metadata") or "{}")

        if self._is_noise(raw_title):
            return None

        inst_str = raw.get("institution", "")
        context = f"{raw_title} {inst_str} {json.dumps(meta, ensure_ascii=False)}"
        clean_title = self._clean_title(raw_title)
        county = self._resolve_county(raw["county"], context)
        entity = self._extract_entity(raw, meta, context)
        tags = self._categorize(context)

        val_ron = None
        if meta.get("estimated_value_ron"):
            try:
                val_ron = float(meta["estimated_value_ron"])
            except (ValueError, TypeError):
                pass
        if not val_ron:
            m = re.search(r"([\d\.,]+)\s*(?:milioane|lei|ron|eur|euro)", context, re.IGNORECASE)
            if m:
                try:
                    val_ron = float(m.group(1).replace(".", "").replace(",", "."))
                except ValueError:
                    pass

        score = self._calculate_score(category, val_ron, context)
        deadline = meta.get("submission_deadline") or meta.get("consultation_deadline") or "Imediat / În desfășurare"

        val_str = f"{val_ron:,.0f} RON" if val_ron else "Dosar aprobat / procedură deschisă"
        summary = f"Oportunitate comercială la {entity} ({county}). Obiectiv: {clean_title[:100]}... Buget/Stadiu: {val_str}."
        action_plan = self._build_action_plan(category, entity, tags, val_ron, deadline)

        return StructuredIntelItem(
            source_id=raw["source_id"],
            category=category,
            county=county,
            locality=raw.get("locality") or "All",
            project_title=clean_title,
            entity_name=entity,
            financial_value_ron=val_ron,
            executive_summary=summary,
            sales_pitch_angle=action_plan,
            trade_tags=tags,
            opportunity_score=score,
            action_deadline=deadline if deadline != "Imediat / În desfășurare" else None,
            source_url=raw.get("document_url")
        )

    def process_pending_records(self, limit: int = 300) -> int:
        unprocessed = get_unprocessed_raw_records(limit=limit)
        if not unprocessed:
            return 0
        saved = 0
        conn = get_db_connection()
        cursor = conn.cursor()
        ph = "%s" if is_postgres() else "?"

        for rec in unprocessed:
            item = self.refine_record(rec)
            if item:
                save_structured_intel(item)
                saved += 1
            else:
                if is_postgres():
                    cursor.execute("UPDATE raw_intel SET processed_by_ai = TRUE WHERE source_id = %s", (rec["source_id"],))
                else:
                    cursor.execute("UPDATE raw_intel SET processed_by_ai = 1 WHERE source_id = ?", (rec["source_id"],))
                conn.commit()
        conn.close()
        return saved
