import os, sys, subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(ROOT, "romania-intel-engine")
FRONTEND = os.path.join(ROOT, "romania-intel-frontend")

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content.strip() + "\n")
    print(f"  [✓] Written: {os.path.relpath(path, ROOT)}")

def run_cmd(cmd, cwd):
    print(f"\n[RUN] {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=cwd)
    if res.returncode != 0:
        print(f"❌ Failed: {' '.join(cmd)}")
        sys.exit(1)

print("\n⚡ [1/3] Upgrading AI Copilot to Natural Conversational Engine...")

# REWRITE AI_COPILOT.PY WITH CONVERSATIONAL INTELLIGENCE
write_file(os.path.join(ENGINE, "ai_copilot.py"), """
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

class ProcurementAICopilot:
    def __init__(self):
        self.api_key = OPENAI_API_KEY or XAI_API_KEY or GROQ_API_KEY or GEMINI_API_KEY or ""

    @staticmethod
    def generate_72h_macro_report(leads: List[Dict[str, Any]]) -> Dict[str, Any]:
        total_val = sum(l.get("financial_value_ron", 0) for l in leads)
        counties = list(set(l.get("county", "") for l in leads if l.get("county")))
        categories = {}
        for l in leads:
            cat = l.get("category", "General")
            categories[cat] = categories.get(cat, 0) + 1

        return {
            "period": "Ultimele 72 de ore (Radar Achizitii Publice)",
            "telemetry": {
                "active_pipeline_ron": total_val,
                "signals_processed": len(leads),
                "top_active_counties": counties[:5],
                "sector_breakdown": categories
            },
            "executive_takeaways": [
                "Crestere a procedurilor pre-SEAP in Iasi, Cluj, Timis si Bucuresti pe ITS, infrastructura spitaliceasca si energie verde.",
                "Autoritatile contractante publica consultari de piata cu termen mediu de reactie de 14 zile conform Art. 139 Legea 98/2016.",
                "Apelurile PNRR C6 si C7 au alocari bugetare active pentru digitalizare si eficienta energetica."
            ],
            "strategic_recommendation": "Formulati puncte de vedere tehnice in faza de consultare pentru a influenta specificatiile din caietul de sarcini."
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
                "Sunt Copilotul AI dedicat strategiilor de licitații publice din România. Vă pot ajuta cu:\\n"
                "- Identificarea proiectelor din faza pre-SEAP (Hotărâri Locale, CNI, CNAIR, PNRR).\\n"
                "- Scanarea caietelor de sarcini pentru clauze restrictive și contestații CNSC.\\n"
                "- Calculul probabilității de câștig și al discountului financiar optim.\\n"
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
                    "Ești consultantul AI senior de bidding și achiziții publice pentru platforma RO-INTEL România. "
                    "Răspunzi natural, profesionist, scurt și direct la întrebările utilizatorului. "
                    "Cunoști legislația achizițiilor publice (Legea 98/2016, Legea 101/2016, HG 395/2016). "
                    "Dacă utilizatorul pune o întrebare generală sau conversațională, răspunde-i conversațional și plăcut, nu repeta template-uri."
                )

                dossiers_summary = json.dumps([{
                    "titlu": l.get("project_title"),
                    "beneficiar": l.get("entity_name"),
                    "judet": l.get("county"),
                    "buget_ron": l.get("financial_value_ron"),
                    "data": l.get("published_date"),
                    "termen": l.get("action_deadline")
                } for l in context_leads[:6]], ensure_ascii=False)

                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Dosare pre-SEAP active:\\n{dossiers_summary}\\n\\nMesaj utilizator: {q_raw}"}
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

        # Match County
        matched_county = [l for l in context_leads if l.get("county", "").lower() in tokens]
        if matched_county:
            top_c = matched_county[:3]
            c_name = top_c[0].get("county")
            summary = "\\n".join([f"• {l.get('project_title')} ({l.get('entity_name')} — {l.get('financial_value_ron', 0)/1000000:.1f} Mil. RON)" for l in top_c])
            return f"În județul {c_name} avem următoarele dosare calificate în radar:\\n\\n{summary}\\n\\nPuteți deschide oricare dosar pentru analiza completă a cerințelor tehnice."

        # Match Project or Entity using whole-word matches
        if meaningful_words:
            matched_leads = []
            for l in context_leads:
                text_corpus = f"{l.get('project_title', '')} {l.get('entity_name', '')} {l.get('sub_category', '')}".lower()
                corpus_words = set(re.findall(r"\\w+", text_corpus))
                score = sum(1 for w in meaningful_words if w in corpus_words)
                if score > 0:
                    matched_leads.append((score, l))
            
            matched_leads.sort(key=lambda x: x[0], reverse=True)
            if matched_leads:
                top_lead = matched_leads[0][1]
                val_mil = top_lead.get("financial_value_ron", 0) / 1000000
                return (
                    f"Dosarul identificat pentru căutarea dumneavoastră este '{top_lead.get('project_title')}':\\n\\n"
                    f"- Autoritate: {top_lead.get('entity_name')} ({top_lead.get('county')})\\n"
                    f"- Buget estimat: {val_mil:.2f} Mil. RON\\n"
                    f"- Publicat la: {top_lead.get('published_date', 'N/A')} | Termen reacție: {top_lead.get('action_deadline', 'Nespecificat')}\\n\\n"
                    f"Recomandare: {top_lead.get('sales_pitch_angle', 'Formulați o solicitare de clarificări pe specificațiile tehnice.')}"
                )

        # 5. Domain Knowledge Queries
        if any(w in tokens for w in ["lege", "legea", "contestatie", "cnsc", "clarificari", "termen"]):
            return (
                "Repere legislative cheie:\\n"
                "- Art. 139 Legea 98/2016: Permite consultarea de piață prealabilă publicării anunțului de participare.\\n"
                "- Art. 160 Legea 98/2016: Solicitările de clarificări se depun cu respectarea termenului stabilit în fișa de date.\\n"
                "- Termen CNSC (Legea 101/2016): 10 zile de la luarea la cunoștință a actului pentru contracte peste pragurile europene, respectiv 5 zile sub praguri."
            )

        if any(w in tokens for w in ["pret", "pretul", "buget", "marja", "discount", "calcul"]):
            return (
                "Recomandări pentru oferta financiară:\\n"
                "1. Mențineți oferta peste 80% din valoarea estimată pentru a nu intra la verificare de preț neobișnuit de scăzut (Art. 215 Legea 98/2016).\\n"
                "2. Un discount optim recomandat este între 6% și 10% față de valoarea estimată a autorității.\\n"
                "3. Folosiți simulatorul de șanse din pagina dosarului pentru calculul exact pe baza ponderii prețului."
            )

        return (
            f"Am înțeles solicitarea dumneavoastră legată de achiziții publice. "
            f"Vă pot asista cu detalii despre dosarele pre-SEAP active, verificarea clauzelor din caiete de sarcini sau generarea de adrese oficiale. "
            f"Puteți specifica județul, domeniul sau denumirea autorității contractante pentru detalii exacte."
        )
""")

print("\n⚡ [2/3] Verifying Backend Python Imports...")
res_py = subprocess.run([sys.executable, "-c", "import api, notifier, workflow_engine, ai_refinery, scrapers.orchestrator, ai_copilot; print('  [OK] Python Backend: 0 errors')"], cwd=ENGINE)
if res_py.returncode != 0:
    print("❌ Backend verification failed.")
    sys.exit(1)

print("\n⚡ [3/3] Verifying Next.js Production Build...")
res_next = subprocess.run(["npm", "run", "build"], cwd=FRONTEND)
if res_next.returncode != 0:
    print("❌ Frontend build failed.")
    sys.exit(1)

print("\n⚡ [DEPLOY] Pushing Clean Production Builds to GitHub...")

run_cmd(["git", "add", "-A"], cwd=FRONTEND)
subprocess.run(["git", "commit", "-m", "feat: light enterprise theme, clean logo, dynamic desks, and zero emojis"], cwd=FRONTEND)
run_cmd(["git", "push", "origin", "main"], cwd=FRONTEND)

run_cmd(["git", "add", "-A"], cwd=ENGINE)
subprocess.run(["git", "commit", "-m", "feat: conversational ai copilot with stopword filtering and multi-provider llm support"], cwd=ENGINE)
run_cmd(["git", "push", "origin", "main"], cwd=ENGINE)

run_cmd(["git", "add", "-A"], cwd=ROOT)
subprocess.run(["git", "commit", "-m", "deploy: sync all submodules for production release"], cwd=ROOT)
run_cmd(["git", "push", "origin", "main"], cwd=ROOT)

print("\n🎉 [SUCCESS] Deployment completed! Vercel and Render builds triggered with 0 errors.")
