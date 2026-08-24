import logging
from typing import Dict, Any

logger = logging.getLogger("WinProbabilityEngine")

class WinProbabilityEngine:
    @staticmethod
    def calculate_win_odds(
        estimated_budget_ron: float,
        proposed_price_ron: float,
        has_local_partnership: bool = False,
        lead_time_days: int = 30
    ) -> Dict[str, Any]:
        if estimated_budget_ron <= 0:
            return {"status": "error", "message": "Buget estimat invalid"}

        discount_pct = round(((estimated_budget_ron - proposed_price_ron) / estimated_budget_ron) * 100, 2)
        base_prob = 55.0
        
        if 5.0 <= discount_pct <= 14.0:
            base_prob += 20.0
        elif discount_pct > 20.0:
            base_prob += 10.0
        elif discount_pct < 3.0:
            base_prob -= 15.0

        if has_local_partnership:
            base_prob += 12.0

        final_prob = max(10.0, min(95.0, round(base_prob, 1)))

        return {
            "estimated_budget_ron": estimated_budget_ron,
            "proposed_price_ron": proposed_price_ron,
            "discount_percentage": f"{discount_pct}%",
            "win_probability_score": f"{final_prob}%",
            "rating": "Favorabil" if final_prob >= 75 else "Competitiv (Risc Mediu)" if final_prob >= 50 else "Nefavorabil",
            "tactical_guidance": (
                "Marja de pret se situeaza in intervalul optim de competitivitate (5-14% discount). "
                "Focalizati-va pe maximizarea punctajului tehnic la garantie si timpi de interventie."
            )
        }
