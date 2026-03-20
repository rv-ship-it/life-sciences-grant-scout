from datetime import date


class CombinedScorer:
    """Blend keyword and semantic scores, set high-priority flag."""

    def __init__(self, keyword_weight: float = 0.60, semantic_weight: float = 0.40,
                 priority_threshold: float = 40.0, priority_deadline_days: int = 60):
        self.kw_weight = keyword_weight
        self.sem_weight = semantic_weight
        self.priority_threshold = priority_threshold
        self.priority_deadline_days = priority_deadline_days

    def compute(self, opp) -> object:
        if opp.semantic_score is not None:
            opp.combined_score = round(
                opp.keyword_score * self.kw_weight
                + opp.semantic_score * self.sem_weight,
                1,
            )
        else:
            opp.combined_score = opp.keyword_score

        opp.matched_topics = [
            ts.topic_name for ts in opp.topic_scores if ts.score > 0
        ]

        opp.high_priority = False
        if opp.combined_score >= self.priority_threshold:
            if opp.deadline:
                days_until = (opp.deadline - date.today()).days
                if 0 <= days_until <= self.priority_deadline_days:
                    opp.high_priority = True
            elif opp.combined_score >= self.priority_threshold * 1.5:
                opp.high_priority = True

        return opp
