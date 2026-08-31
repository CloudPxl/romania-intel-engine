import logging
from typing import Any, Dict

logger = logging.getLogger("WinProbabilityEngine")

# This module used to return a "win_probability_score" as a specific
# percentage ("75.0%"), produced by adding fixed bonuses to a 55% baseline.
# There is no model and no training data behind those numbers — the system
# has never ingested a single award result — so a precise-looking
# percentage implied a calibration that does not exist, and a user could
# reasonably have staked a bid decision on it.
#
# It now returns a banded, explained competitiveness assessment. The bands
# are heuristics, and they say so. Two other defects are fixed at the same
# time: `lead_time_days` was accepted and never used, and the tactical
# guidance was a fixed string claiming the price sat "in the optimal 5-14%
# range" even when the caller had just been told their discount was 30%.

# Discount bands, in percent off the published estimate.
BAND_TOO_THIN = 3.0      # below this, price is rarely the differentiator
BAND_COMPETITIVE_HIGH = 14.0
BAND_AGGRESSIVE = 20.0   # above this, expect a price justification request


class WinProbabilityEngine:
    @staticmethod
    def calculate_win_odds(
        estimated_budget_ron: float,
        proposed_price_ron: float,
        has_local_partnership: bool = False,
        lead_time_days: int = 30,
    ) -> Dict[str, Any]:
        if not estimated_budget_ron or estimated_budget_ron <= 0:
            return {
                "status": "error",
                "message": (
                    "Valoarea estimată nu este publicată sau este invalidă. "
                    "Fără estimarea autorității nu se poate calcula un discount de referință."
                ),
            }
        if proposed_price_ron is None or proposed_price_ron < 0:
            return {"status": "error", "message": "Prețul propus este invalid."}

        discount_pct = round(
            ((estimated_budget_ron - proposed_price_ron) / estimated_budget_ron) * 100, 2
        )

        factors = []

        if discount_pct < 0:
            band = "peste_estimare"
            assessment = "Nefavorabil"
            factors.append(
                f"Prețul propus depășește valoarea estimată cu {abs(discount_pct):.2f}%; "
                "autoritatea poate respinge oferta ca inacceptabilă dacă depășește bugetul disponibil."
            )
        elif discount_pct < BAND_TOO_THIN:
            band = "marja_redusa"
            assessment = "Competitiv (diferențiere tehnică necesară)"
            factors.append(
                f"Discount de {discount_pct:.2f}% — prețul nu va fi un diferențiator; "
                "punctajul se decide pe componenta tehnică."
            )
        elif discount_pct <= BAND_COMPETITIVE_HIGH:
            band = "interval_uzual"
            assessment = "Favorabil"
            factors.append(
                f"Discount de {discount_pct:.2f}%, în intervalul uzual de "
                f"{BAND_TOO_THIN:.0f}-{BAND_COMPETITIVE_HIGH:.0f}% pentru proceduri competitive."
            )
        elif discount_pct <= BAND_AGGRESSIVE:
            band = "agresiv"
            assessment = "Competitiv (risc de justificare)"
            factors.append(
                f"Discount de {discount_pct:.2f}% — competitiv, dar verificați acoperirea costurilor."
            )
        else:
            band = "risc_pret_neobisnuit_de_scazut"
            assessment = "Risc ridicat"
            factors.append(
                f"Discount de {discount_pct:.2f}% — la acest nivel autoritatea poate solicita "
                "justificarea prețului (regimul ofertei cu preț neobișnuit de scăzut, Legea nr. 98/2016). "
                "Pregătiți fundamentarea detaliată a costurilor."
            )

        if has_local_partnership:
            factors.append(
                "Parteneriat local declarat — poate susține criteriile de capacitate tehnică "
                "și disponibilitate a resurselor, dacă este documentat în ofertă."
            )

        # lead_time_days is now actually used: the time left before the
        # deadline changes what a bidder can realistically assemble.
        if lead_time_days is not None:
            if lead_time_days < 7:
                factors.append(
                    f"Doar {lead_time_days} zile până la termen — riscul principal este completitudinea "
                    "dosarului (DUAE, certificate fiscale, garanție de participare), nu prețul."
                )
            elif lead_time_days < 21:
                factors.append(
                    f"{lead_time_days} zile până la termen — timp suficient pentru dosar, "
                    "dar solicitările de clarificări trebuie transmise imediat."
                )
            else:
                factors.append(
                    f"{lead_time_days} zile până la termen — există timp pentru clarificări "
                    "și eventuale ajustări ale specificațiilor."
                )

        return {
            "estimated_budget_ron": estimated_budget_ron,
            "proposed_price_ron": proposed_price_ron,
            "discount_percentage": discount_pct,
            "competitiveness_band": band,
            "assessment": assessment,
            "factors": factors,
            "methodology_note": (
                "Evaluare euristică bazată pe intervalele uzuale de discount din achizițiile publice "
                "din România. Sistemul nu colectează rezultate de atribuire, deci nu poate produce "
                "o probabilitate statistică de câștig — această evaluare este calitativă, nu predictivă."
            ),
        }
