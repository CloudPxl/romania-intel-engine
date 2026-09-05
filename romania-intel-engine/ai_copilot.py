import os
import re
import json
import logging
from typing import Dict, Any, List, Optional
import httpx

logger = logging.getLogger("AICopilot")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
# render.yaml has always declared this env var as GROK_API_KEY (not
# XAI_API_KEY, xAI's own naming) — so a key set on Render was never once
# read by this module. Accepting both names fixes it without needing a
# Render dashboard change on top of a code deploy.
XAI_API_KEY = os.getenv("XAI_API_KEY", "") or os.getenv("GROK_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Forces one provider regardless of which other keys happen to be set —
# e.g. LLM_PROVIDER=groq to guarantee a newly-added free key is actually
# used, without having to remove an old/exhausted key for another
# provider first. Values: openai | xai | groq | gemini.
LLM_PROVIDER_OVERRIDE = os.getenv("LLM_PROVIDER", "").strip().lower()

# name -> (base_url, model, api_key). Groq and Gemini both have genuinely
# free tiers obtainable in minutes (console.groq.com, aistudio.google.com)
# with no billing setup; OpenAI and xAI do not, in practice, so the free
# ones are tried first when multiple keys are present. Gemini uses its
# OpenAI-compatible endpoint so one call shape covers all four providers.
#
# Every model id below was verified live against this deployment's actual
# keys (probed directly against each provider's /chat/completions), not
# assumed — model catalogs on all of these providers rotate every few
# months and a plausible-looking id silently 404s or, worse, burns tokens
# without producing output:
#   - groq/llama-3.3-70b-versatile: retired: 404 model_not_found. Replaced
#     with openai/gpt-oss-120b, one of the two general chat models still
#     live in this key's catalog, verified to answer correctly in Romanian.
#   - gemini-2.0-flash: retired. gemini-3.6-flash (Google's own suggested
#     replacement) is a reasoning model that spent ~800 tokens on hidden
#     "thinking" before producing 32 tokens of visible answer and still
#     got cut off (finish_reason=length) — impractical for short document
#     sections. gemini-flash-lite-latest answers directly (finish_reason
#     stop, no hidden token burn) and, being Google's auto-updating alias
#     rather than a pinned version, should not go stale the same way.
#   - grok-beta: retired. grok-3/grok-4 are confirmed real ids (they pass
#     model validation and reach the credits check), but this deployment's
#     xAI team has zero credits and xAI has no free tier at all — a 403
#     permission-denied every time regardless of model id, so this key
#     will not work until credits are purchased at console.x.ai.
_PROVIDERS = {
    "groq": ("https://api.groq.com/openai/v1", "openai/gpt-oss-120b", GROQ_API_KEY),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-flash-lite-latest", GEMINI_API_KEY),
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini", OPENAI_API_KEY),
    "xai": ("https://api.x.ai/v1", "grok-4", XAI_API_KEY),
}
_INVALID_KEYS = {"", "dummy_key", "re_dummy"}

# Hard character budget for the variable half of a prompt (the user prompt —
# the only half that carries caller-supplied text: caiet excerpts, a chat
# message, a clarification list, a feed sample).
#
# Measured in characters, deliberately not in tokens: the four providers
# above use three different tokenizers, none of them tiktoken's, so a token
# count computed here would be an accurate count of the wrong number while
# reading as authoritative. At a pessimistic ~3 chars/token for Romanian
# (diacritics cost extra), 32k chars is roughly 10k tokens — far inside
# every configured model's context window, and inside the free-tier
# tokens-per-minute ceilings on Groq and Gemini, which bind long before the
# context window does. Those ceilings are the real failure mode: an
# oversized prompt comes back 413/429 from every provider in turn and
# complete_text returns None, which each caller silently treats as "the AI
# expansion just didn't happen" — so an over-long input degrades invisibly
# rather than loudly. Truncating is the honest trade: the model sees a
# marked-as-incomplete document instead of the caller seeing nothing.
#
# The system prompt is deliberately exempt: every one is a module-level
# constant carrying the legal grounding and anti-hallucination rules, and
# cutting those would damage the output far more than dropping the tail of
# an oversized input does.
MAX_USER_PROMPT_CHARS = 32_000
_TRUNCATION_NOTICE = (
    "\n\n[NOTĂ: textul de mai sus a fost trunchiat automat deoarece a depășit limita "
    "de caractere pe cerere. Formulează răspunsul doar pe baza porțiunii primite și "
    "menționează explicit că analiza acoperă un extras parțial al documentului.]"
)


def _bound_user_prompt(user_prompt: str) -> str:
    """Caps the caller-supplied half of a prompt and tells the model, in the
    prompt itself, that what it received is an extract — so a truncated input
    cannot come back as a confident answer about a whole document."""
    if len(user_prompt) <= MAX_USER_PROMPT_CHARS:
        return user_prompt
    logger.warning(
        f"[LLM] User prompt of {len(user_prompt)} chars exceeds the {MAX_USER_PROMPT_CHARS}-char "
        "budget — truncating and flagging it as partial to the model."
    )
    return user_prompt[:MAX_USER_PROMPT_CHARS] + _TRUNCATION_NOTICE

ROMANIAN_STOPWORDS = {
    "ce", "faci", "cum", "este", "sunt", "care", "asta", "pentru", "despre", "in", "la", "de",
    "cu", "din", "pe", "am", "ai", "au", "vreau", "caut", "vrei", "poti", "mai", "un", "o",
    "si", "sau", "dar", "iar", "nu", "da", "tot", "toate", "acest", "aceasta", "proiect", "proiecte"
}

# Words that carry no request on their own. The small-talk shortcuts below
# fire only when a message consists of *nothing but* these (plus
# stopwords) — the previous `any(word in tokens)` test meant "salut, ce
# licitații sunt în Brașov?" was answered with a canned greeting and the
# actual question was silently dropped, and "ok, și în Cluj?" was answered
# with "cu plăcere!". A greeting attached to a real question is a real
# question.
GREETING_TOKENS = {
    "sal", "salut", "salutare", "buna", "bună", "ziua", "seara", "dimineata", "dimineața",
    "hello", "hi", "hey", "servus", "noroc", "neata", "neaţa",
}
THANKS_TOKENS = {"multumesc", "mulțumesc", "mersi", "multam", "super", "perfect", "ok", "okay", "bravo"}
_SMALL_TALK_FILLER = {"tu", "voi", "acolo", "azi", "astazi", "astăzi", "totul", "bine", "merge", "esti", "ești"}

# Question shape -> a curated topic in legal_kb. Used to attach the real,
# fetched statutory text to a legal question instead of leaving the model
# to recall an article number from memory — which is exactly how the
# hardcoded fallback below came to assert a the-law-does-not-contain-it
# 80% threshold under a wrong article number for months.
_LEGAL_TRIAGE = [
    (r"\b(pret|preț|neobisnuit|neobișnuit|scazut|scăzut|subevaluat|dumping|marja|marjă|discount)\b",
     "abnormally_low_price"),
    (r"\b(contesta|contestatie|contestație|cnsc|cale de atac|remedi|standstill|termen de contestare)\b",
     "remedies"),
    (r"\b(clarificar|lamurir|lămurir|intrebare catre autoritate|întrebare către autoritate)\b",
     "clarification_requests"),
    (r"\b(specificati|specificaţi|specificați|restrictiv|echivalent|marca|marcă|producator|producător)\b",
     "technical_specifications"),
    (r"\b(exclud|cazier|insolvent|insolvenț|datorii|restante|restanțe|fiscal)\b", "exclusion_grounds"),
    (r"\b(calificare|selectie|selecție|experienta similara|experiență similară|cifra de afaceri|capacitate tehnica)\b",
     "qualification_criteria"),
    (r"\b(criteriu de atribuire|factori de evaluare|punctaj|cel mai bun raport)\b", "award_criteria"),
    (r"\b(act aditional|act adițional|modificare(a)? contractului|suplimentare)\b", "contract_modification"),
]


# Long enough that no article in the curated TOPICS index gets cut through
# the middle of an operative limb. The first version used 900, which
# truncated art. 8 of Legea 101/2016 exactly one character before the "7
# zile" sub-threshold deadline — leaving the model a quotation that stops
# immediately before the number the user asked for, which is the single
# worst place to cut. Two of the indexed articles (art. 187 and art. 221 of
# Legea 98/2016) are genuinely longer than this and are still trimmed; the
# header below tells the model what a trailing […] means so it flags the
# gap instead of closing it from memory.
LEGAL_GROUNDING_MAX_CHARS = 2_400


def _legal_grounding(query: str, max_topics: int = 2) -> str:
    """The actual text of the articles a question touches, if any.

    Attached to the prompt only when the question is legal — a triage
    regex rather than a blanket injection, so an ordinary "ce e nou în
    Brașov?" does not carry two pages of statute into every provider call
    and burn the free-tier tokens-per-minute ceiling that binds here long
    before the context window does.
    """
    try:
        import legal_kb
    except Exception:
        return ""
    folded = query.lower()
    blocks: List[str] = []
    for pattern, topic_name in _LEGAL_TRIAGE:
        if len(blocks) >= max_topics:
            break
        if re.search(pattern, folded):
            block = legal_kb.topic_citation_block(topic_name, max_chars=LEGAL_GROUNDING_MAX_CHARS)
            if block:
                blocks.append(block)
    if not blocks:
        return ""
    return (
        "\n\nTEXT LEGAL VERIFICAT (extras din forma consolidată publicată pe legislatie.just.ro — "
        "citează din acesta, nu din memorie). Un citat care se termină cu […] este trunchiat: "
        "spune că nu ai textul complet al acelui alineat, nu îl completa din memorie:\n"
        + "\n\n".join(blocks)
    )

def list_llm_providers() -> List[tuple]:
    """Every provider with a usable key configured, in try-order, as
    (name, base_url, model, api_key).

    This used to return only the single first-configured provider — so an
    exhausted or invalid key for one provider (say xAI) silently blocked
    every other configured key (Groq, Gemini) from ever being tried, with
    no error surfaced anywhere. complete_text() below now walks this whole
    list and only gives up after every configured provider has failed.
    """
    if LLM_PROVIDER_OVERRIDE:
        entry = _PROVIDERS.get(LLM_PROVIDER_OVERRIDE)
        if entry and entry[2] not in _INVALID_KEYS:
            return [(LLM_PROVIDER_OVERRIDE, *entry)]
        logger.warning(
            f"[LLM] LLM_PROVIDER={LLM_PROVIDER_OVERRIDE!r} has no usable key configured; "
            "falling back to auto-detection."
        )
    return [
        (name, base_url, model, key)
        for name, (base_url, model, key) in _PROVIDERS.items()
        if key not in _INVALID_KEYS
    ]


def resolve_llm_provider() -> Optional[tuple]:
    """Back-compat single-provider accessor (base_url, model, api_key).
    Prefer list_llm_providers() / complete_text() for new code — this
    only reports whether *any* provider is configured."""
    providers = list_llm_providers()
    if not providers:
        return None
    _, base_url, model, key = providers[0]
    return base_url, model, key


def _bound_conversation(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Applies the same character budget to a multi-turn exchange.

    The newest turn is what the user is actually waiting on an answer to,
    so it is bounded individually and always kept; older turns are dropped
    from the front until the whole conversation fits. Trimming the oldest
    is the right direction for a chat — losing the start of a conversation
    degrades gracefully, losing the question does not.
    """
    if not messages:
        return []
    bounded = list(messages)
    bounded[-1] = {**bounded[-1], "content": _bound_user_prompt(bounded[-1]["content"])}
    while len(bounded) > 1 and sum(len(m["content"]) for m in bounded) > MAX_USER_PROMPT_CHARS:
        bounded.pop(0)
    return bounded


async def complete_chat(
    system_prompt: str,
    messages: List[Dict[str, str]],
    temperature: float = 0.4,
    max_tokens: int = 3000,
    timeout: float = 45.0,
) -> Optional[str]:
    """Multi-turn variant of complete_text, and the real implementation
    behind it.

    Exists because the copilot chat was sending each question as an
    isolated single-turn prompt: the frontend kept the visible transcript
    but the model never received it, so every follow-up ("și în Cluj?",
    "detaliază-l pe primul") arrived with no idea what "primul" referred
    to. That is a conversation in appearance only. Providers are tried in
    the same order and with the same never-raise contract as
    complete_text.

    `messages` is a list of {"role": "user"|"assistant", "content": str}.
    """
    providers = list_llm_providers()
    if not providers:
        return None

    messages = _bound_conversation(messages)

    for name, base_url, model_name, api_key in providers:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model_name,
                        "messages": [{"role": "system", "content": system_prompt}, *messages],
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                )
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"].strip()
                logger.warning(f"[LLM] {name} ({base_url}) returned {resp.status_code}: {resp.text[:200]} — trying next provider.")
        except Exception as e:
            logger.error(f"[LLM] {name} completion call failed: {e} — trying next provider.")
    return None


async def complete_text(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.4,
    max_tokens: int = 3000,
    timeout: float = 45.0,
) -> Optional[str]:
    """Shared single-turn completion call, reused by the document
    generators (dossier/FOIA) for optional deep-section expansion and by
    the market-report narrative. Returns the first successful completion,
    or None (never raises) when every provider is unconfigured or failed —
    every caller must have a template fallback, since this is a "nice to
    have" enhancement, not a load-bearing dependency.

    `user_prompt` is capped at MAX_USER_PROMPT_CHARS here rather than in
    each caller, so no route can send an unbounded document, chat message
    or clarification list into a provider — see _bound_user_prompt. A
    caller that wants a *structure-preserving* cut (keeping several
    sections of context rather than losing the tail) should still slice its
    own inputs first, the way the drafting generators slice caiet_text.
    """
    return await complete_chat(
        system_prompt,
        [{"role": "user", "content": user_prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )


def _format_budget(lead: Dict[str, Any]) -> str:
    """An undisclosed budget arrives as 0/None. Rendering that as
    '0.00 Mil. RON' tells the user the contract is worth nothing, which is
    a materially different claim from 'the authority did not publish it'."""
    value = lead.get("financial_value_ron") or 0
    if value <= 0:
        return "buget nepublicat"
    return f"{value / 1_000_000:.2f} Mil. RON"


def _build_market_telemetry(leads: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Shared deterministic aggregation behind both the fixed 72h radar and
    the customizable market report — factored out so the two never drift
    into computing "signals processed" or "pre-tender count" differently.

    The takeaways here are derived from the leads passed in, never fixed
    text: this used to assert specific market movements ("creștere a
    procedurilor pre-SEAP în Iași, Cluj, Timiș...") verbatim no matter what
    the data showed, including when the feed was empty.
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
    pre_tender_stages = ("pre_tender_approved_indicators", "pre_tender_documentation_review", "market_consultation")
    pre_tender = sum(n for stage, n in stage_counts.items() if stage in pre_tender_stages)

    takeaways: List[str] = []
    if not leads:
        takeaways.append("Nu există semnale în fereastra/filtrul analizat.")
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
            if pre_tender
            else "Analizați caietele de sarcini publicate și pregătiți documentația de calificare (DUAE)."
        ),
    }


class ProcurementAICopilot:
    @staticmethod
    def generate_72h_macro_report(leads: List[Dict[str, Any]]) -> Dict[str, Any]:
        telemetry = _build_market_telemetry(leads)
        # Short on purpose: the frontend renders this in a fixed, non-
        # shrinking uppercase eyebrow beside the "Sinteză macro" heading, so
        # a sentence-length value here squashed the heading out of the
        # column instead of labelling it.
        return {"period": "72h", **telemetry}

    @staticmethod
    async def generate_custom_market_report(
        leads: List[Dict[str, Any]],
        filters_applied: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Same deterministic telemetry as the 72h radar, computed over
        whatever custom slice routers/analysis.py just queried, plus an
        optional LLM-synthesized executive narrative (bespoke takeaways,
        strategic recommendations, competitor hypotheses) grounded strictly
        in that slice. Additive: if no provider is configured or the call
        fails, the deterministic telemetry above is still a complete,
        accurate report on its own — the narrative is a bonus, never a
        dependency.
        """
        base = _build_market_telemetry(leads)
        base["filters_applied"] = filters_applied or {}
        base["ai_narrative"] = None

        if not list_llm_providers():
            return base

        sample = json.dumps([{
            "titlu": l.get("project_title"),
            "beneficiar": l.get("entity_name"),
            "judet": l.get("county"),
            "domeniu": l.get("category"),
            "buget_ron": l.get("financial_value_ron") if (l.get("financial_value_ron") or 0) > 0 else "nepublicat",
            "stadiu": l.get("procurement_stage"),
            "sursa": l.get("source_url"),
        } for l in leads[:25]], ensure_ascii=False)

        system_prompt = (
            "Ești director de strategie într-o firmă de consultanță pentru achiziții publice din România. "
            "Primești un rezumat statistic și un eșantion de dosare reale, deja filtrate exact după criteriile "
            "clientului. Redactezi un raport de piață bespoke, bazat STRICT pe datele furnizate — nu pe "
            "cunoștințe generale despre piața românească și nu pe presupuneri despre dosare care nu sunt în "
            "eșantion. Dacă eșantionul este prea mic pentru o concluzie robustă, spune asta explicit în loc "
            "să generalizezi. Nu inventa nume de concurenți reali — formulează 'ipoteze de concurență' generice "
            "și condiționale (tipul de operator care ar fi probabil interesat), nu afirmații despre companii "
            "anume. Structurează răspunsul în trei secțiuni cu titluri: 'Sinteză executivă', 'Recomandări "
            "strategice', 'Ipoteze de concurență'. Scrii exclusiv în limba română, ton formal-consultativ."
        )
        user_prompt = (
            f"Filtre aplicate de client: {json.dumps(filters_applied or {}, ensure_ascii=False, default=str)}\n"
            f"Statistici agregate: {json.dumps(base['telemetry'], ensure_ascii=False)}\n"
            f"Eșantion de dosare (max 25 din {len(leads)} total): {sample}\n\n"
            "Redactează raportul bespoke conform instrucțiunilor."
        )
        narrative = await complete_text(system_prompt, user_prompt, temperature=0.5, max_tokens=1800, timeout=40.0)
        base["ai_narrative"] = narrative
        return base

    async def answer_copilot_query(
        self,
        query: str,
        context_leads: List[Dict[str, Any]],
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """`history` is the prior turns of this conversation, oldest first,
        as {"role": "user"|"assistant", "content": str}. It is what makes a
        follow-up like "și în Cluj?" resolvable; without it every message
        was answered as if it were the first one."""
        q_raw = query.strip()
        q_clean = re.sub(r"[^a-zA-Z0-9ăâîșțĂÂÎȘȚ ]", " ", q_raw).lower()
        tokens = [w for w in q_clean.split() if w]
        history = [m for m in (history or []) if m.get("content")]

        # Everything in the message that is not a greeting, a pleasantry or
        # a stopword. If this is empty the message really is only small
        # talk; if it is not, there is a question in here to answer.
        substantive = [
            w for w in tokens
            if w not in GREETING_TOKENS
            and w not in THANKS_TOKENS
            and w not in _SMALL_TALK_FILLER
            and w not in ROMANIAN_STOPWORDS
        ]
        asks_how_are_you = any(p in q_clean for p in ["ce faci", "cum merge", "ce mai faci"]) or "cf" in tokens

        # 1. Pure small talk — answered here rather than spending a
        #    provider call on "salut". Skipped once a conversation is
        #    under way, so the copilot does not re-introduce itself in the
        #    middle of an exchange.
        if not substantive and not history:
            if any(w in tokens for w in GREETING_TOKENS):
                if asks_how_are_you:
                    return (
                        "Salut! Sunt bine, monitorizez continuu noile consultări de piață și dosarele pre-SEAP din România. "
                        "Cu ce vă pot ajuta astăzi? Căutați proceduri într-un anumit județ sau aveți o întrebare despre o licitație anume?"
                    )
                return (
                    "Bună ziua! Sunt Copilotul AI RO-INTEL. Monitorizez 24/7 registrele pre-SEAP, consultările de piață și licitațiile din România. "
                    "Cu ce proiect, județ sau strategie de ofertare vă pot fi de folos?"
                )
            if asks_how_are_you:
                return "Monitorizez noile semnale pre-SEAP și calculez șansele de câștig pentru procedurile active. Cu ce începem?"
            if any(w in tokens for w in THANKS_TOKENS):
                return "Cu multă plăcere! Dacă mai aveți nevoie de analize pe caiete de sarcini sau simulări de marjă, sunt aici."

        # 2. Conversational repair. Deliberately *not* short-circuited when
        #    a provider is configured — "nu asta am întrebat" is precisely
        #    the case where the model, holding the transcript, can correct
        #    itself instead of emitting a canned apology.
        is_correction = any(
            phrase in q_clean for phrase in ["nu asta", "nu am intrebat", "nu la asta", "gresit", "te inseli", "altceva"]
        )

        if not substantive and not history and any(
            phrase in q_clean for phrase in ["cine esti", "ce poti sa faci", "ce stii", "ajutor", "help"]
        ):
            return (
                "Sunt Copilotul AI dedicat strategiilor de licitații publice din România. Vă pot ajuta cu:\n"
                "- Identificarea proiectelor din faza pre-SEAP (Hotărâri Locale, CNI, CNAIR, PNRR).\n"
                "- Scanarea caietelor de sarcini pentru clauze restrictive și contestații CNSC.\n"
                "- Calculul probabilității de câștig și al discountului financiar optim.\n"
                "- Redactarea adreselor oficiale de clarificări (Legea 98/2016, Art. 160) și acces la informații (Legea 544/2001)."
            )

        # 3. Live LLM Call (if configured on Render)
        if resolve_llm_provider() is not None:
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
                "specialist înainte de depunere.\n"
                "7. Dacă primești o secțiune 'TEXT LEGAL VERIFICAT', citează exclusiv din ea pentru "
                "articolele acoperite acolo; are prioritate față de orice reții din memorie.\n\n"
                "CUM PORȚI CONVERSAȚIA:\n"
                "- Ai istoricul discuției. Rezolvă referirile la ce s-a spus deja ('primul', 'acela', "
                "'și în Cluj?') din context, nu cere utilizatorului să repete.\n"
                "- Nu te prezenta și nu saluta din nou dacă discuția este deja în curs.\n"
                "- Dacă întrebarea este ambiguă, pune O singură întrebare de clarificare, apoi oprește-te; "
                "nu enumera toate interpretările posibile.\n"
                "- Dacă utilizatorul spune că răspunsul anterior a fost greșit, corectează-te concret pe "
                "baza istoricului — nu răspunde cu scuze generice.\n"
                "- Răspunsuri scurte: 2-5 propoziții pentru o întrebare simplă. Folosește liste doar când "
                "enumeri efectiv dosare sau pași. Fără introduceri de curtoazie și fără a repeta întrebarea.\n"
                "- Referă-te la dosare prin titlu și autoritate, nu prin poziția în listă.\n\n"
                "STIL: profesionist, direct, în limba română, fără formule inutile. La întrebări "
                "conversaționale răspunde firesc și scurt."
            )

            # Was 6 — enough to answer "what's in Brașov?" only if Brașov
            # happened to be in the top 6 of a feed sorted by relevance,
            # and to answer "nothing found" otherwise, which reads as a
            # broken index rather than a short context window.
            dossiers_summary = json.dumps([{
                "titlu": l.get("project_title"),
                "beneficiar": l.get("entity_name"),
                "judet": l.get("county"),
                "domeniu": l.get("category"),
                # Distinguish "not published" from zero so the model
                # cannot report an undisclosed budget as a 0 RON contract.
                "buget_ron": l.get("financial_value_ron") if (l.get("financial_value_ron") or 0) > 0 else "nepublicat",
                "data": l.get("published_date"),
                "termen": l.get("action_deadline") or "nepublicat",
                "stadiu": l.get("procurement_stage"),
                "sursa": l.get("source_url"),
            } for l in context_leads[:18]], ensure_ascii=False)

            # The dossiers ride on the newest turn rather than in the system
            # prompt so the model always scores them against the question it
            # is answering right now, and the transcript above stays a clean
            # record of what was actually said.
            user_prompt = (
                f"Dosare pre-SEAP active din registrul clientului "
                f"(primele {min(len(context_leads), 18)} din {len(context_leads)}, ordonate după relevanță):\n"
                f"{dossiers_summary}"
                f"{_legal_grounding(q_raw)}\n\n"
                f"Mesaj utilizator: {q_raw}"
            )
            conversation = [
                *[{"role": m["role"], "content": m["content"]} for m in history[-8:]],
                {"role": "user", "content": user_prompt},
            ]
            answer = await complete_chat(system_prompt, conversation, temperature=0.4, max_tokens=1200, timeout=12.0)
            if answer:
                return answer

        # Every provider is unconfigured or failed. The deterministic
        # branches below cannot resolve a reference to an earlier turn, so
        # say so rather than answering a follow-up as if it stood alone.
        if is_correction:
            return (
                "Am înțeles, îmi cer scuze pentru confuzie. Vă rog să-mi reformulați întrebarea sau să-mi spuneți exact "
                "ce detaliu vă interesează: de exemplu, căutați proiecte dintr-un anumit județ, o clarificare pe Legea 98/2016, "
                "sau o estimare de preț pentru o anumită categorie?"
            )

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

        # 5. Domain Knowledge Queries — answered from the ingested statutory
        #    texts, never from prose written here. The two hardcoded answers
        #    this replaced were both factually wrong: one gave the CNSC
        #    sub-threshold deadline as 5 days (art. 8 alin. (1) lit. b) of
        #    Legea 101/2016 says 7), and the other told users to keep their
        #    bid above "80% of the estimated value" under "Art. 215" — a
        #    threshold that appears nowhere in Legea 98/2016 and an article
        #    number that is not the one on abnormally low prices. Advice
        #    like that loses procedures.
        if any(w in tokens for w in ["lege", "legea", "contestatie", "contestație", "cnsc", "clarificari", "clarificări", "termen", "articol"]):
            grounded = _legal_grounding(q_raw, max_topics=1)
            if grounded:
                return (
                    "Textul în vigoare, din forma consolidată publicată în Monitorul Oficial:\n"
                    + grounded.split(":\n", 1)[-1]
                    + "\n\nVerificați termenele exacte în documentația procedurii — se pot modifica prin ordine ANAP."
                )
            return (
                "Repere legislative cheie:\n"
                "- Art. 139 Legea 98/2016: consultarea pieței, prealabilă publicării anunțului de participare.\n"
                "- Art. 160-161 Legea 98/2016: dreptul de a solicita clarificări și termenul în care autoritatea răspunde.\n"
                "- Art. 8 Legea 101/2016: contestația la CNSC se depune în 10 zile de la luarea la cunoștință "
                "pentru procedurile peste pragurile de publicare în JOUE, respectiv 7 zile sub aceste praguri."
            )

        if any(w in tokens for w in ["pret", "prețul", "pretul", "preț", "buget", "marja", "marjă", "discount", "calcul"]):
            return (
                "Poziționare financiară — ce spune efectiv legea:\n"
                "1. Legea nu prevede un prag procentual sub care o ofertă devine automat 'neobișnuit de scăzută'. "
                "Art. 210 din Legea 98/2016 obligă autoritatea să vă ceară clarificări și să respingă oferta doar "
                "dacă justificarea nu este corespunzătoare.\n"
                "2. Pregătiți justificarea pe cele șase capitole din art. 210 alin. (2): fundamentarea economică a "
                "prețului, soluțiile tehnice și condițiile favorabile, originalitatea soluției, respectarea "
                "obligațiilor din domeniul muncii (art. 51), obligațiile privind subcontractarea (art. 218) și "
                "eventualul ajutor de stat.\n"
                "3. Folosiți simulatorul de poziționare din această pagină pentru calculul pe baza ponderii "
                "prețului în criteriul de atribuire al procedurii concrete."
            )

        return (
            "Am înțeles solicitarea dumneavoastră legată de achiziții publice. "
            "Vă pot asista cu detalii despre dosarele pre-SEAP active, verificarea clauzelor din caiete de sarcini sau generarea de adrese oficiale. "
            "Puteți specifica județul, domeniul sau denumirea autorității contractante pentru detalii exacte."
        )
