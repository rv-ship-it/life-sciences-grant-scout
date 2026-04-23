import re
from typing import Tuple

from ..models import TopicScore


class KeywordScorer:
    """Score opportunities by weighted keyword matching against topic categories.

    Algorithm:
    1. For each topic, count distinct keyword matches in title + description.
    2. Per-topic score = (matched / total) * 100 * weight.
    3. Title matches get a 2.0x bonus.
    4. Final score = sum of top-3 topic scores, capped at 100.
    5. Subtract exclusion penalty (e.g. bio-based, circular economy matches)
       to filter out industrial biotech / sustainability false positives.
    """

    def __init__(
        self,
        topics_config: dict,
        exclusion_keywords: list[str] | None = None,
        exclusion_penalty_per_hit: float = 8.0,
    ):
        self._compiled: dict[str, tuple[float, list[tuple[str, re.Pattern]]]] = {}
        for topic_name, topic_data in topics_config.items():
            weight = topic_data.get("weight", 1.0)
            patterns = []
            for kw in topic_data.get("keywords", []):
                pat = re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
                patterns.append((kw, pat))
            self._compiled[topic_name] = (weight, patterns)

        self._exclusions = [
            (kw, re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE))
            for kw in (exclusion_keywords or [])
        ]
        self._exclusion_penalty = exclusion_penalty_per_hit

    def score(self, title: str, description: str) -> Tuple[float, list[TopicScore]]:
        topic_scores = []

        for topic_name, (weight, patterns) in self._compiled.items():
            hits = []
            has_title_hit = False
            for keyword, pattern in patterns:
                title_match = pattern.search(title)
                desc_match = pattern.search(description)
                if title_match or desc_match:
                    hits.append(keyword)
                    if title_match:
                        has_title_hit = True

            if hits:
                base_score = (len(hits) / len(patterns)) * 100.0
                if has_title_hit:
                    base_score = min(100.0, base_score * 2.0)
                weighted_score = base_score * weight

                topic_scores.append(TopicScore(
                    topic_name=topic_name,
                    keyword_hits=hits,
                    score=round(weighted_score, 1),
                ))

        topic_scores.sort(key=lambda ts: ts.score, reverse=True)

        if not topic_scores:
            return 0.0, []

        top_n = topic_scores[:3]
        combined = sum(ts.score for ts in top_n)

        # Apply exclusion penalty (industrial bio-based / sustainability terms)
        exclusion_hits = 0
        haystack = f"{title} {description}"
        for _, pat in self._exclusions:
            if pat.search(haystack):
                exclusion_hits += 1
        penalty = exclusion_hits * self._exclusion_penalty
        combined = max(0.0, combined - penalty)

        combined = min(100.0, round(combined, 1))
        return combined, topic_scores
