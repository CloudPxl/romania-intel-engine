"""Does this opportunity matter to this person?

Scope note, because there are now two things that "match" in this codebase
and they deliberately disagree:

  * THIS module answers "is this worth interrupting someone for?" — a hard
    question, gated on real keyword evidence, used for email/Telegram
    alerts.
  * db.get_ranked_opportunities answers "what order should the feed be
    in?" — a soft question that ranks the entire market and hides nothing.

Feeding the soft ranking into alerting would mean everything matches a
little, and every user would be emailed about every signal until they
unsubscribed. Ranking a page and filling an inbox are not the same
decision, so they are not the same function.

There is no tenant, no organisation and no product line. A profile is a
person, and a person has exactly one set of criteria — which is why the
old per-product loop and the in-process TENANT_ORGANIZATIONS cache are
both gone. Profiles are loaded once per tick by the caller (see
db.get_onboarded_profiles) and passed in; nothing here holds state.
"""

import logging
from typing import Any, Dict, List

from text_utils import counties_match, matching_terms

logger = logging.getLogger("MatchingEngine")

# Default alerting bar on the 0-10 scale below. Clearing it needs domain
# alignment plus real keyword evidence plus either the right county or a
# qualifying budget — a lead worth interrupting someone for, not merely a
# plausible one. Each profile may override it via min_alert_score.
ALERT_THRESHOLD = 7.5

# Most Romanian pre-tender publications carry no figure at all: an intention
# notice names the object and the authority but not the money. Nearly every
# ms.ro notice and every MFE funding call land this way — so the value floor
# must not be applied to them as if they had failed it.
UNKNOWN_VALUE = 0.0

# What an opportunity must clear to count as a match at all. Scores are
# built from weighted evidence rather than nudged off a high baseline, so
# this sits mid-scale.
MATCH_THRESHOLD = 6.0


class RelevanceEngine:
    @staticmethod
    def evaluate(opportunity: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
        """Scores one opportunity against one person's criteria.

        Always returns a dict — `is_match` False rather than None — so the
        caller can log or display a near-miss instead of it vanishing.
        """
        title = opportunity.get("project_title", "") or ""
        summary = opportunity.get("executive_summary", "") or ""
        sub_category = opportunity.get("sub_category", "") or ""
        text = f"{title} {summary} {sub_category}"

        def _result(is_match: bool, score: float, reasons: List[str]) -> Dict[str, Any]:
            return {
                "is_match": is_match,
                "score": score,
                "reasons": reasons,
            }

        # Hard exclusions first — a disqualifying term ends it regardless of
        # how well everything else lines up. Note this is where alerting
        # diverges most from the feed ranking, which only *sinks* excluded
        # items so the user can still scroll to them.
        blocked = matching_terms(text, profile.get("exclude_keywords") or [])
        if blocked:
            return _result(False, 0.0, [f"Exclus prin: {', '.join(blocked[:3])}"])

        matched_kws = matching_terms(text, profile.get("keywords") or [])

        # Keyword evidence is mandatory. Domain and geography reinforce a
        # match below but must never create one on their own: without this
        # gate an energy specialist was alerted about defence contracts
        # purely because they shared a county.
        if not matched_kws:
            return _result(False, 0.0, ["Fără dovezi în text pentru cuvintele-cheie alese"])

        score = 0.0
        reasons: List[str] = []

        if profile.get("domain") and opportunity.get("category") == profile["domain"]:
            score += 3.4
            reasons.append(f"Domeniu: {str(profile['domain']).capitalize()}")

        # Diminishing returns, so one very generic term cannot outweigh
        # genuine domain alignment.
        score += min(3.0, 1.4 + 0.55 * (len(matched_kws) - 1))
        reasons.append(f"Relevanță tehnică: {', '.join(matched_kws[:4])}")

        county = opportunity.get("county", "")
        if any(counties_match(county, c) for c in profile.get("target_counties") or []):
            score += 1.6
            reasons.append(f"Zonă vizată: {county}")
        elif county:
            reasons.append(f"În afara zonei prioritare ({county})")

        # Unknown budgets neither reward nor penalise — they are flagged so
        # the user knows the figure still has to be confirmed at source.
        value = (
            opportunity.get("financial_value_ron")
            or opportunity.get("estimated_value_ron")
            or UNKNOWN_VALUE
        )
        min_value = float(profile.get("min_value_ron") or 0.0)
        if value == UNKNOWN_VALUE:
            score += 0.5
            reasons.append("Buget nepublicat — de confirmat la sursă")
        elif value >= min_value:
            score += 1.5
            reasons.append(f"Buget eligibil: {value:,.0f} RON")
        else:
            score -= 1.5
            reasons.append(f"Sub pragul stabilit ({value:,.0f} < {min_value:,.0f} RON)")

        # Pre-tender stages are worth more than a notice already out to bid,
        # because the specification can still be influenced. Set by the CNI
        # scrapers (see cni_common.py).
        stage = (opportunity.get("metadata") or {}).get("procurement_stage")
        if stage in ("pre_tender_approved_indicators", "pre_tender_documentation_review"):
            score += 0.8
            reasons.append("Fază pre-licitație — specificațiile pot fi încă influențate")

        final_score = max(0.0, min(10.0, round(score, 1)))
        return _result(final_score >= MATCH_THRESHOLD, final_score, reasons)
