"""Bid pricing modelled from the award criterion, plus the Art. 210 defence.

Replaces the fixed 3/14/20% opinion bands in `win_probability.py`, which
told every bidder the same thing regardless of how the procedure actually
scores offers. Two contracts at the same discount can have opposite
outcomes: under *prețul cel mai scăzut* only the lowest price wins, while
under *cel mai bun raport calitate-preț* a 40%-weighted price component
means a 10% discount buys far less than it appears to.

Three things this does that the band table could not:

**It computes the real trade-off.** Romanian best-value procedures score
price by the standard proportional formula — your price points are
(lowest offer / your offer) x the price weight. That is arithmetic, so it
can answer the question a bidder actually has: *if a competitor undercuts
me by X%, how many technical points do I need to still win?* The formula
is stated in the output, so the reader can check it.

**Its abnormally-low trigger is honest about what it is.** The "under 80%
of the estimated value" rule is NOT in force. Verified against both
consolidated texts: art. 210 of Legea 98/2016 states a qualitative test
("aparent neobișnuit de scăzute, prin raportare la prețurile pieței") and
lists six justification headings, with no percentage; art. 136 of the HG
395/2016 norms — the article invariably cited for the 80% — has three
paragraphs and no figure either. The threshold is a survival from the
repealed OUG 34/2006. It is kept here as an internal early-warning
heuristic, named as one, because preparing a justification you turn out
not to need costs nothing and being asked for one you have not prepared
loses the contract. Where real award data exists, the observed median
winning discount is a far better trigger and takes precedence.

**Its justification dossier follows the law's own structure.** Art. 210
alin. (2) lit. a)-f) names the six matters the explanation may address,
and art. 136 alin. (2) of the norms names the evidence that must
accompany it — supplier prices, raw-material stock, work organisation and
methods, personnel salary levels, equipment performance and costs. Those
are the chapters, quoted from the ingested text rather than invented, so
the generated dossier is answering the questions the commission is
actually required to ask.
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("PriceStrategy")

# Internal early-warning threshold ONLY. See the module docstring: this is
# not a legal threshold, and every response that uses it says so.
HEURISTIC_LOW_PRICE_TRIGGER_PCT = 20.0  # i.e. a bid at 80% of the estimate

AWARD_CRITERIA = {
    "lowest_price": "Prețul cel mai scăzut",
    "best_value": "Cel mai bun raport calitate-preț",
}

# The six matters art. 210 alin. (2) allows the clarification to cover,
# paired with the evidence art. 136 alin. (2) of the norms requires. Keys
# are the letters as the law numbers them, so a reader can check the
# mapping against the quoted article travelling in the same response.
JUSTIFICATION_CHAPTERS = [
    {
        "letter": "a",
        "title": "Fundamentarea economică a modului de formare a prețului",
        "prompt": (
            "Devizul pe categorii de lucrări/produse: costuri unitare de materiale, manoperă, "
            "utilaje și transport, cu cantitățile aferente și marja aplicată."
        ),
        "evidence": "Deviz general și devize pe obiect, liste de cantități, fișe de calcul al prețului unitar.",
    },
    {
        "letter": "b",
        "title": "Soluțiile tehnice adoptate și condițiile deosebit de favorabile",
        "prompt": (
            "Ce anume vă permite să executați mai ieftin: tehnologia folosită, utilaje proprii, "
            "contracte-cadru cu furnizorii, proximitatea față de amplasament."
        ),
        "evidence": "Oferte/confirmări de preț de la furnizori, contracte-cadru, fișe tehnice de utilaje.",
    },
    {
        "letter": "c",
        "title": "Originalitatea lucrărilor, produselor sau serviciilor propuse",
        "prompt": "Elementele proprii de soluție care nu sunt disponibile în mod obișnuit pe piață.",
        "evidence": "Documentație tehnică, brevete, certificări de produs.",
    },
    {
        "letter": "d",
        "title": "Respectarea obligațiilor din domeniul muncii (art. 51 alin. (1))",
        "prompt": (
            "Demonstrația că manopera din deviz respectă salariul minim brut și contribuțiile "
            "legale, pentru fiecare categorie de personal prevăzută."
        ),
        "evidence": "Stat de funcții, structura tarifului orar, declarație privind respectarea legislației muncii.",
    },
    {
        "letter": "e",
        "title": "Respectarea obligațiilor privind subcontractarea (art. 218)",
        "prompt": "Cine execută ce parte, la ce preț, și cum se reflectă în prețul total ofertat.",
        "evidence": "Acorduri de subcontractare cu prețurile pe părțile subcontractate.",
    },
    {
        "letter": "f",
        "title": "Posibilitatea de a beneficia de un ajutor de stat",
        "prompt": "Dacă un ajutor de stat contribuie la nivelul prețului, temeiul și legalitatea acestuia.",
        "evidence": "Decizia de acordare a ajutorului, dacă este cazul; altfel, declarație că nu este cazul.",
    },
]


def _legal_articles(keys: List[str], max_chars: int = 900) -> List[Dict[str, Any]]:
    try:
        import legal_kb
    except Exception:  # pragma: no cover
        return []
    out = []
    for key in keys:
        entry = legal_kb.cite_with_text(key, max_chars)
        if entry and not entry["repealed"]:
            out.append(entry)
    return out


def _price_points(your_price: float, lowest_price: float, price_weight: float) -> float:
    """The standard Romanian proportional price score.

    Points = (lowest offer / your offer) x weight. Stated explicitly in the
    output rather than applied silently, because it is the whole reason a
    given discount is worth more on one procedure than another.
    """
    if your_price <= 0:
        return 0.0
    return round(min(lowest_price, your_price) / your_price * price_weight, 2)


def analyze_pricing(
    estimated_value_ron: float,
    proposed_price_ron: float,
    award_criterion: str = "lowest_price",
    price_weight_pct: float = 100.0,
    your_technical_score_pct: Optional[float] = None,
    award_stats: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Models one bid against the procedure's own scoring rules.

    `award_stats` is a procurement_notices.summarize_awards() result. When
    it carries a usable sample, the observed median winning discount
    replaces the heuristic trigger — a real distribution beats a rule of
    thumb, and it is the only version of this figure the product is willing
    to call a benchmark.
    """
    if not estimated_value_ron or estimated_value_ron <= 0:
        return {
            "status": "error",
            "message": (
                "Valoarea estimată nu este publicată. Fără ea nu se poate calcula niciun "
                "discount de referință și nicio expunere la regimul prețului neobișnuit de scăzut."
            ),
        }
    if proposed_price_ron is None or proposed_price_ron < 0:
        return {"status": "error", "message": "Prețul propus este invalid."}

    criterion = award_criterion if award_criterion in AWARD_CRITERIA else "lowest_price"
    weight = max(0.0, min(100.0, price_weight_pct if criterion == "best_value" else 100.0))
    discount_pct = round((estimated_value_ron - proposed_price_ron) / estimated_value_ron * 100, 2)

    result: Dict[str, Any] = {
        "status": "success",
        "award_criterion": criterion,
        "award_criterion_label": AWARD_CRITERIA[criterion],
        "estimated_value_ron": estimated_value_ron,
        "proposed_price_ron": proposed_price_ron,
        "discount_pct": discount_pct,
        "price_weight_pct": weight,
        "technical_weight_pct": round(100.0 - weight, 2) if criterion == "best_value" else 0.0,
    }

    # ---------------------------------------------------------- scoring
    if criterion == "best_value":
        technical_weight = 100.0 - weight
        scenarios = []
        # What happens if a competitor undercuts you. Concrete numbers for
        # a concrete decision, rather than an adjective.
        for undercut in (5, 10, 15):
            rival_price = proposed_price_ron * (1 - undercut / 100)
            your_points = _price_points(proposed_price_ron, rival_price, weight)
            lost = round(weight - your_points, 2)
            scenarios.append({
                "competitor_undercuts_you_by_pct": undercut,
                "competitor_price_ron": round(rival_price, 2),
                "your_price_points": your_points,
                "price_points_lost": lost,
                "technical_advantage_needed_pts": lost,
                "technical_advantage_needed_pct_of_technical_weight": (
                    round(lost / technical_weight * 100, 1) if technical_weight > 0 else None
                ),
            })
        result["scoring_model"] = {
            "formula": "Punctaj preț = (prețul cel mai scăzut / prețul dvs.) × ponderea prețului",
            "note": (
                f"Cu preț ponderat {weight:.0f}% și tehnic {technical_weight:.0f}%, un competitor "
                "care vă subcotează nu vă scoate din joc automat — trebuie doar să recuperați "
                "diferența de punctaj pe partea tehnică."
            ),
            "undercut_scenarios": scenarios,
        }
        if your_technical_score_pct is not None:
            result["scoring_model"]["your_estimated_total_at_lowest_price"] = round(
                weight + (your_technical_score_pct / 100) * technical_weight, 2
            )
    else:
        result["scoring_model"] = {
            "formula": "Câștigă oferta admisibilă cu prețul cel mai scăzut.",
            "note": (
                "Punctajul tehnic nu compensează nimic: calitatea contează doar pentru "
                "admisibilitate. Singurele pârghii sunt costul propriu și conformitatea tehnică."
            ),
        }

    # ------------------------------------------------- abnormally low risk
    observed_median = None
    if award_stats and award_stats.get("available"):
        observed_median = award_stats["winning_discount_pct"]["median"]

    if discount_pct < 0:
        risk_level, risk_code = "Inacceptabil", "over_budget"
        risk_detail = (
            f"Prețul depășește valoarea estimată cu {abs(discount_pct):.2f}%. Autoritatea poate "
            "respinge oferta ca inacceptabilă dacă depășește bugetul pe care îl poate angaja."
        )
    elif observed_median is not None and discount_pct >= observed_median + 10:
        risk_level, risk_code = "Ridicat", "below_observed_market"
        risk_detail = (
            f"Discountul dvs. ({discount_pct:.1f}%) depășește cu peste 10 puncte discountul median "
            f"al câștigătorilor observați ({observed_median:.1f}%, {award_stats['sample_size']} atribuiri). "
            "Este cel mai solid indiciu că vi se vor cere justificări de preț."
        )
    elif discount_pct >= HEURISTIC_LOW_PRICE_TRIGGER_PCT:
        risk_level, risk_code = "Ridicat", "heuristic_trigger"
        risk_detail = (
            f"Discountul dvs. ({discount_pct:.1f}%) depășește pragul intern de avertizare de "
            f"{HEURISTIC_LOW_PRICE_TRIGGER_PCT:.0f}%. Acesta este un semnal al nostru, nu un prag "
            "legal — legea nu prevede un procent — dar la acest nivel solicitarea de justificare "
            "este frecventă în practică."
        )
    elif discount_pct >= 10:
        risk_level, risk_code = "Moderat", "moderate"
        risk_detail = (
            f"Discount de {discount_pct:.1f}%. Sub nivelul la care justificarea este uzuală, dar "
            "pregătiți devizul: comisia poate cere clarificări la orice nivel dacă prețul pare "
            "neobișnuit raportat la prețurile pieței."
        )
    else:
        risk_level, risk_code = "Redus", "low"
        risk_detail = (
            f"Discount de {discount_pct:.1f}%. Expunere redusă la regimul prețului neobișnuit de scăzut."
        )

    result["abnormally_low_risk"] = {
        "level": risk_level,
        "code": risk_code,
        "detail": risk_detail,
        "trigger_used": (
            "discountul median observat al câștigătorilor" if risk_code == "below_observed_market"
            else "prag intern de avertizare" if risk_code == "heuristic_trigger"
            else "nu s-a declanșat"
        ),
        "observed_median_discount_pct": observed_median,
        "legal_position": (
            "Nici art. 210 din Legea 98/2016, nici art. 136 din normele HG 395/2016 nu prevăd un "
            "prag procentual. Regula „sub 80% din valoarea estimată” provine din OUG 34/2006, "
            "abrogată. Testul în vigoare este calitativ: raportarea la prețurile pieței."
        ),
        "requires_justification_dossier": risk_code in ("below_observed_market", "heuristic_trigger"),
        "legal_basis": _legal_articles(["L98/2016:210", "HG395/2016:136"]),
    }
    return result


def build_justification_outline(
    company_name: str,
    project_title: str,
    estimated_value_ron: float,
    proposed_price_ron: float,
    authority_name: Optional[str] = None,
) -> Dict[str, Any]:
    """The deterministic skeleton of a *Fundamentare economică a prețului*.

    A complete, usable document on its own — the LLM expansion below is
    additive, same convention as every other generator here. The chapters
    are art. 210 alin. (2) lit. a)-f); the evidence lines are art. 136
    alin. (2) of the norms.
    """
    discount = (
        round((estimated_value_ron - proposed_price_ron) / estimated_value_ron * 100, 2)
        if estimated_value_ron else 0.0
    )
    return {
        "title": "Fundamentarea economică a prețului ofertat",
        "subtitle": f"Răspuns la solicitarea de clarificări privind prețul aparent neobișnuit de scăzut",
        "company_name": company_name,
        "authority_name": authority_name,
        "project_title": project_title,
        "estimated_value_ron": estimated_value_ron,
        "proposed_price_ron": proposed_price_ron,
        "discount_pct": discount,
        "chapters": [
            {
                "letter": c["letter"],
                "title": c["title"],
                "what_to_provide": c["prompt"],
                "supporting_evidence": c["evidence"],
            }
            for c in JUSTIFICATION_CHAPTERS
        ],
        "legal_basis": _legal_articles(["L98/2016:210", "HG395/2016:136"]),
        "closing_note": (
            "Conform art. 210 alin. (3) din Legea nr. 98/2016, oferta se respinge numai dacă "
            "dovezile furnizate nu justifică în mod corespunzător nivelul prețului. Documentul de "
            "față trebuie însoțit de dovezile concludente enumerate la fiecare capitol."
        ),
    }


async def expand_justification_with_ai(
    outline: Dict[str, Any],
    cost_notes: Optional[str] = None,
) -> Optional[str]:
    """Drafts the narrative for each chapter. Returns None if no provider is
    configured or every one fails — the outline above stands alone."""
    from ai_copilot import complete_text, list_llm_providers

    if not list_llm_providers():
        return None

    chapters = "\n".join(
        f"{c['letter']}) {c['title']} — {c['what_to_provide']} Dovezi: {c['supporting_evidence']}"
        for c in outline["chapters"]
    )
    legal = "\n\n".join(f"{a['citation']}:\n„{a['text']}”" for a in outline.get("legal_basis", []))

    system_prompt = (
        "Ești consultant senior în achiziții publice din România și redactezi documente oficiale "
        "care se depun la o comisie de evaluare. Redactezi o 'Fundamentare economică a prețului "
        "ofertat', ca răspuns la o solicitare de clarificări privind prețul aparent neobișnuit de "
        "scăzut.\n\n"
        "REGULI OBLIGATORII:\n"
        "1. Structurează documentul EXACT pe capitolele primite, în ordinea literelor a)-f). "
        "Sunt literele din art. 210 alin. (2) din Legea nr. 98/2016 și comisia le verifică în "
        "această ordine.\n"
        "2. NU inventa cifre, furnizori, utilaje sau contracte. Unde este nevoie de o valoare "
        "concretă pe care nu o ai, scrie un marcaj clar de completat, de forma [de completat: "
        "cost unitar material X], și enumeră documentul justificativ necesar.\n"
        "3. Nu afirma că un prag procentual legal ar exista. Legea nu prevede unul; argumentul "
        "este că prețul este fundamentat, nu că se încadrează într-un procent.\n"
        "4. Ton formal, la persoana I plural ('subscrisa'), fără superlative comerciale.\n"
        "5. Fiecare capitol se încheie cu lista dovezilor anexate pentru capitolul respectiv.\n"
        "6. Scrii exclusiv în limba română."
    )
    user_prompt = (
        f"Ofertant: {outline['company_name']}\n"
        f"Autoritate contractantă: {outline.get('authority_name') or '[de completat]'}\n"
        f"Procedura: {outline['project_title']}\n"
        f"Valoare estimată: {outline['estimated_value_ron']:,.2f} RON\n"
        f"Preț ofertat: {outline['proposed_price_ron']:,.2f} RON "
        f"(cu {outline['discount_pct']:.2f}% sub valoarea estimată)\n\n"
        f"Capitole obligatorii:\n{chapters}\n\n"
        + (f"Note interne despre structura costurilor:\n{cost_notes}\n\n" if cost_notes else "")
        + f"TEXT LEGAL VERIFICAT (citează din acesta, nu din memorie):\n{legal}\n\n"
        "Redactează documentul complet."
    )
    return await complete_text(system_prompt, user_prompt, temperature=0.35, max_tokens=2600, timeout=45.0)
