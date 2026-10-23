"""Deterministic, abstaining decisions about the next arithmetic practice target."""
from config import adaptive as settings

from .models import AdaptiveDecision, AdaptiveState, EvidenceSummary


def decide(
        evidence: EvidenceSummary, 
        state: AdaptiveState, 
        *, 
        difficulty: int, 
        default_practice: bool, 
        variant: str,
        operators=None,
        ) -> AdaptiveDecision:
    if evidence.attempted_count < settings.MIN_ADAPTIVE_PROBLEMS or difficulty > 5:
        return AdaptiveDecision()
    if state.last_offer_count is not None and evidence.assessable_count - state.last_offer_count < settings.RECOMMENDATION_COOLDOWN_PROBLEMS:
        return AdaptiveDecision()
    if evidence.recent_pattern == "needs_support" and difficulty == 1 and default_practice and variant != "foundation_support":
        return AdaptiveDecision("foundation_support", "foundation_support", "default_support")
    if evidence.recent_pattern == "strong":
        if variant == "foundation_support":
            return AdaptiveDecision("offer", "standard_level_one", "foundation_progress")
        return AdaptiveDecision("offer", "increase_level" if difficulty < 5 else "continuation", "independent_progress")
    
    for signal in evidence.operator_signals:
        if (
            signal.operation in {"*", "/"} 
            and (operators is None or signal.operation in operators)
            and len(signal.problem_ids) >= settings.MIN_OPERATOR_PROBLEMS
            and signal.difficult_count / len(signal.problem_ids) >= settings.OPERATOR_SUPPORT_RATE 
            and signal.recent_difficult):
            return AdaptiveDecision(
                "offer", 
                "focus_operator", 
                "operator_support", 
                signal.operation, 
                signal.upper_bound,
                )
    if evidence.recent_pattern == "needs_support":
        return AdaptiveDecision("offer", "reduce_range", "recent_support")
    return AdaptiveDecision()
