import os
import re
import json
import logging
from typing import Dict, Any, List, Optional
import httpx

logger = logging.getLogger("AICopilot")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
XAI_API_KEY = os.getenv("XAI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

ROMANIAN_STOPWORDS = {
    "ce", "faci", "cum", "este", "sunt", "care", "asta", "pentru", "despre", "in", "la", "de",
    "cu", "din", "pe", "am", "ai", "au", "vreau", "caut", "vrei", "poti", "mai", "un", "o",
    "si", "sau", "dar", "iar", "nu", "da", "tot", "toate", "acest", "aceasta", "proiect", "proiecte"
}

def _format_budget(lead: Dict[str, Any]) -> str:
    """An undisclosed budget arrives as 0/None. Rendering that as
    '0.00 Mil. RON' tells the user the contract is worth nothing, which is
    a materially different claim from 'the authority did not publish it'."""
    value = lead.get("financial_value_ron") or 0
    if value <= 0:
        return "buget nepublicat"
    return f"{value / 1_000_000:.2f} Mil. RON"


class ProcurementAICopilot:
    def __init__(self):
        self.api_key = OPENAI_API_KEY or XAI_API_KEY or GROQ_API_KEY or GEMINI_API_KEY or ""

    @staticmethod
    def generate_72h_macro_report(leads: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregates the actual feed.

        The takeaways here are derived from the leads passed in. They used
        to be three fixed sentences asserting specific market movements
        ("creștere a procedurilor pre-SEAP în Iași, Cluj, Timiș...") that
        were printed verbatim no matter what the data showed — including
        when the feed was empty.
        """
        from collections import Counter

        published_values = [
            l.get("financial_value_ron", 0) or 0
            for l in leads
            if (l.get("financial_value_ron") or 0) > 0
        ]
        county_counts = Counter(l.get("county") for l in leads if l.get("county"))
        category_counts = Counter(l.get("category", "General") for l in leads)
        stage_counts = Counter(l.get("procurement_stage", "unknown") for l in leads)

        takeaways: List[str] = []
        if not leads:
            takeaways.append("Nu există semnale noi în fereastra analizată.")
        else:
            top_counties = county_counts.most_common(3)
            if top_counties:
                takeaways.append(
                    "Concentrare geografică: "
                    + ", ".join(f"{c} ({n} semnale)" for c, n in top_counties)
                    + "."
                )
            top_cat, top_cat_n = category_counts.most_common(1)[0]
            takeaways.append(
                f"Domeniul dominant este '{top_cat}', cu {top_cat_n} din {len(leads)} semnale "
                f"({top_cat_n / len(leads) * 100:.0f}%)."
            )
            pre_tender = sum(
                n for stage, n in stage_counts.items()
                if stage in ("pre_tender_approved_indicators", "pre_tender_documentation_review", "market_consultation")
            )
            if pre_tender:
                takeaways.append(
                    f"{pre_tender} semnale sunt în fază pre-licitație, unde specificațiile tehnice "
                    "pot fi încă influențate."
                )
            undisclosed = len(leads) - len(published_values)
            if undisclosed:
                takeaways.append(
                    f"{undisclosed} din {len(leads)} semnale nu au valoare estimată publicată — "
                    "bugetul trebuie confirmat la autoritate."
                )

        return {
            "period": "Ultimele 72 de ore (Radar Achiziții Publice)",
            "telemetry": {
                # Only sums figures the sources actually published, and says
                # how many they cover, so the total is not mistaken for the
                # full pipeline value.
                "published_pipeline_ron": sum(published_values),
                "signals_with_published_value": len(published_values),
                "signals_processed": len(leads),
                "top_active_counties": [c for c, _ in county_counts.most_common(5)],
                "sector_breakdown": dict(category_counts),
                "stage_breakdown": dict(stage_counts),
            },
            "executive_takeaways": takeaways,
            "strategic_recommendation": (
                "Prioritizați semnalele în fază pre-licitație: în această etapă puteți influența "
                "specificațiile tehnice, conform art. 139 din Legea nr. 98/2016 (consultarea pieței)."
                if any(
                    s in stage_counts
                    for s in ("pre_tender_approved_indicators", "pre_tender_documentation_review", "market_consultation")
                )
                else "Analizați caietele de sarcini publicate și pregătiți documentația de calificare (DUAE)."
            ),
        }

    async def answer_copilot_query(self, query: str, context_leads: List[Dict[str, Any]]) -> str:
        q_raw = query.strip()
        q_clean = re.sub(r"[^a-zA-Z0-9ăâîșțĂÂÎȘȚ ]", " ", q_raw).lower()
        tokens = [w for w in q_clean.split() if w]

        # 1. Greetings & Small Talk
        if any(w in tokens for w in ["sal", "salut", "buna", "hello", "hi", "servus", "noroc", "salutare", "hey"]):
            if "ce faci" in q_clean or "cf" in tokens or "cum merge" in q_clean:
                return (
                    "Salut! Sunt bine, monitorizez continuu noile consultări de piață și dosarele pre-SEAP din România. "
                    "Cu ce vă pot ajuta astăzi? Căutați proceduri într-un anumit județ sau aveți o întrebare despre o licitație anume?"
                )
            return (
                "Bună ziua! Sunt Copilotul AI RO-INTEL. Monitorizez 24/7 registrele pre-SEAP, consultările de piață și licitațiile din România. "
                "Cu ce proiect, județ sau strategie de ofertare vă pot fi de folos?"
            )

        # 2. Conversational feedback & Negation
        if any(phrase in q_clean for phrase in ["nu asta", "nu am intrebat", "nu la asta", "gresit", "te inseli", "altceva"]):
            return (
                "Am înțeles, îmi cer scuze pentru confuzie. Vă rog să-mi reformulați întrebarea sau să-mi spuneți exact "
                "ce detaliu vă interesează: de exemplu, căutați proiecte dintr-un anumit județ, o clarificare pe Legea 98/2016, "
                "sau o estimare de preț pentru o anumită categorie?"
            )

        if q_clean in ["ce faci", "cf", "cum merge", "ce mai faci"]:
            return "Monitorizez noile semnale pre-SEAP și calculez șansele de câștig pentru procedurile active. Cu ce începem?"

        if any(phrase in q_clean for phrase in ["multumesc", "mersi", "super", "ok", "perfect", "multam"]):
            return "Cu multă plăcere! Dacă mai aveți nevoie de analize pe caiete de sarcini sau simulări de marjă, sunt aici."

        if any(phrase in q_clean for phrase in ["cine esti", "ce poti sa faci", "ce stii", "ajutor", "help"]):
            return (
                "Sunt Copilotul AI dedicat strategiilor de licitații publice din România. Vă pot ajuta cu:\n"
                "- Identificarea proiectelor din faza pre-SEAP (Hotărâri Locale, CNI, CNAIR, PNRR).\n"
                "- Scanarea caietelor de sarcini pentru clauze restrictive și contestații CNSC.\n"
                "- Calculul probabilității de câștig și al discountului financiar optim.\n"
                "- Redactarea adreselor oficiale de clarificări (Legea 98/2016, Art. 160) și acces la informații (Legea 544/2001)."
            )

        # 3. Live LLM Call (if configured on Render)
        if self.api_key and self.api_key not in ["dummy_key", "re_dummy"]:
            try:
                base_url = "https://api.openai.com/v1"
                model_name = "gpt-4o-mini"
                if XAI_API_KEY:
                    base_url, model_name = "https://api.x.ai/v1", "grok-beta"
                elif GROQ_API_KEY:
                    base_url, model_name = "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"

                system_prompt = (
                    "Ești consultant senior în achiziții publice din România, în cadrul platformei RO-INTEL. "
                    "Vorbești cu profesioniști care depun oferte pe bani publici; răspunsurile tale au consecințe "
                    "juridice și financiare reale.\n\n"
                    "CADRU LEGAL pe care îl stăpânești:\n"
                    "- Legea nr. 98/2016 (achiziții publice clasice): art. 2 alin. (2) principii; art. 7 praguri "
                    "și tipuri de proceduri; art. 139 consultarea pieței; art. 160-161 solicitări de clarificări; "
                    "art. 164/165/167 motive de excludere; art. 193 DUAE; art. 210 preț neobișnuit de scăzut.\n"
                    "- Legea nr. 99/2016 (achiziții sectoriale: utilități, energie, transport, apă).\n"
                    "- Legea nr. 101/2016 (remedii și căi de atac): termene de contestare la CNSC, "
                    "termenul de așteptare (standstill).\n"
                    "- HG nr. 395/2016 (norme de aplicare), Legea nr. 544/2001 (informații publice), "
                    "Legea nr. 10/1995 (calitatea în construcții), Legea nr. 346/2004 (IMM).\n\n"
                    "REGULI DE RĂSPUNS — obligatorii:\n"
                    "1. Când citezi legislația, indică articolul exact. Dacă nu ești sigur de numărul articolului "
                    "sau de forma în vigoare, spune explicit acest lucru și recomandă verificarea în Monitorul Oficial. "
                    "Nu inventa niciodată numere de articole, termene sau praguri.\n"
                    "2. Termenele și pragurile valorice se modifică prin ordine ANAP. Prezintă-le ca orientative și "
                    "recomandă confirmarea pentru procedura concretă.\n"
                    "3. Folosește exclusiv datele din dosarele furnizate în context. Dacă informația cerută nu se "
                    "află acolo, spune că nu o ai — nu completa din memorie și nu estima valori.\n"
                    "4. Când o valoare estimată lipsește din dosar, tratează asta ca 'nepublicată', nu ca zero.\n"
                    "5. Nu oferi consultanță care ar încălca principiile concurenței sau care ar sugera "
                    "influențarea nelegală a unei proceduri. Poți explica participarea legitimă la consultarea "
                    "pieței (art. 139), care este permisă și publică.\n"
                    "6. Ești asistent, nu avocat: pentru contestații și litigii, recomandă consultarea unui "
                    "specialist înainte de depunere.\n\n"
                    "STIL: profesionist, direct, în limba română, fără formule inutile. La întrebări "
                    "conversaționale răspunde firesc și scurt."
                )

                dossiers_summary = json.dumps([{
                    "titlu": l.get("project_title"),
                    "beneficiar": l.get("entity_name"),
                    "judet": l.get("county"),
                    # Distinguish "not published" from zero so the model
                    # cannot report an undisclosed budget as a 0 RON contract.
                    "buget_ron": l.get("financial_value_ron") if (l.get("financial_value_ron") or 0) > 0 else "nepublicat",
                    "data": l.get("published_date"),
                    "termen": l.get("action_deadline") or "nepublicat",
                    "stadiu": l.get("procurement_stage"),
                    "sursa": l.get("source_url"),
                } for l in context_leads[:6]], ensure_ascii=False)

                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Dosare pre-SEAP active:\n{dossiers_summary}\n\nMesaj utilizator: {q_raw}"}
                ]

                async with httpx.AsyncClient(timeout=12.0) as client:
                    resp = await client.post(
                        f"{base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                        json={"model": model_name, "messages": messages, "temperature": 0.4}
                    )
                    if resp.status_code == 200:
                        return resp.json()["choices"][0]["message"]["content"].strip()
            except Exception as e:
                logger.error(f"[AICopilot] LLM Error: {e}")

        # 4. Filtered Contextual Matching (No false substring collisions)
        meaningful_words = [w for w in tokens if len(w) > 3 and w not in ROMANIAN_STOPWORDS]

        # Match County — folded so "Iași" in the feed matches "iasi" typed
        # by the user (and vice versa); a plain .lower() missed both ways.
        from text_utils import fold, normalize_county

        folded_tokens = {fold(t) for t in tokens}
        matched_county = [
            l for l in context_leads
            if normalize_county(l.get("county", "")) in folded_tokens
        ]
        if matched_county:
            top_c = matched_county[:3]
            c_name = top_c[0].get("county")
            summary = "\n".join([
                f"• {l.get('project_title')} ({l.get('entity_name')} — {_format_budget(l)})"
                for l in top_c
            ])
            return f"În județul {c_name} avem următoarele dosare calificate în radar:\n\n{summary}\n\nPuteți deschide oricare dosar pentru analiza completă a cerințelor tehnice."

        # Match Project or Entity using whole-word matches
        if meaningful_words:
            matched_leads = []
            folded_words = [fold(w) for w in meaningful_words]
            for l in context_leads:
                text_corpus = f"{l.get('project_title', '')} {l.get('entity_name', '')} {l.get('sub_category', '')}"
                corpus_words = set(re.findall(r"[a-z0-9]+", fold(text_corpus)))
                score = sum(1 for w in folded_words if w in corpus_words)
                if score > 0:
                    matched_leads.append((score, l))
            
            matched_leads.sort(key=lambda x: x[0], reverse=True)
            if matched_leads:
                top_lead = matched_leads[0][1]
                return (
                    f"Dosarul identificat pentru căutarea dumneavoastră este '{top_lead.get('project_title')}':\n\n"
                    f"- Autoritate: {top_lead.get('entity_name')} ({top_lead.get('county')})\n"
                    f"- Buget estimat: {_format_budget(top_lead)}\n"
                    f"- Publicat la: {top_lead.get('published_date') or 'N/A'} | Termen reacție: {top_lead.get('action_deadline') or 'nepublicat'}\n\n"
                    f"Recomandare: {top_lead.get('sales_pitch_angle', 'Formulați o solicitare de clarificări pe specificațiile tehnice.')}"
                )

        # 5. Domain Knowledge Queries
        if any(w in tokens for w in ["lege", "legea", "contestatie", "cnsc", "clarificari", "termen"]):
            return (
                "Repere legislative cheie:\n"
                "- Art. 139 Legea 98/2016: Permite consultarea de piață prealabilă publicării anunțului de participare.\n"
                "- Art. 160 Legea 98/2016: Solicitările de clarificări se depun cu respectarea termenului stabilit în fișa de date.\n"
                "- Termen CNSC (Legea 101/2016): 10 zile de la luarea la cunoștință a actului pentru contracte peste pragurile europene, respectiv 5 zile sub praguri."
            )

        if any(w in tokens for w in ["pret", "pretul", "buget", "marja", "discount", "calcul"]):
            return (
                "Recomandări pentru oferta financiară:\n"
                "1. Mențineți oferta peste 80% din valoarea estimată pentru a nu intra la verificare de preț neobișnuit de scăzut (Art. 215 Legea 98/2016).\n"
                "2. Un discount optim recomandat este între 6% și 10% față de valoarea estimată a autorității.\n"
                "3. Folosiți simulatorul de șanse din pagina dosarului pentru calculul exact pe baza ponderii prețului."
            )

        return (
            f"Am înțeles solicitarea dumneavoastră legată de achiziții publice. "
            f"Vă pot asista cu detalii despre dosarele pre-SEAP active, verificarea clauzelor din caiete de sarcini sau generarea de adrese oficiale. "
            f"Puteți specifica județul, domeniul sau denumirea autorității contractante pentru detalii exacte."
        )
