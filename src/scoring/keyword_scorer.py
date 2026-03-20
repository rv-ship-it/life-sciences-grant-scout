import re
from typing import Tuple

from ..models import TopicScore


class KeywordScorer:
    """Score opportunities by weighted keyword matching against topic categories.

    Algorithm:
    1. For each topic, count distinct keyword matches in title + description.
    2. Per-topic score = (matched / total) * 100 * weight.
    3. Title matches get a 1.3x bonus.
    4. Final score = average of top-3 topic scores, capped at 100.
    """

    def __init__(self, topics_config: dict):
        self._compiled: dict[str, tuple[float, list[tuple[str, re.Pattern]]]] = {}
        for topic_name, topic_data in topics_config.items():
            weight = topic_data.get("weight", 1.0)
            patterns = []
            for kw in topic_data.get("keywords", []):
                pat = re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
                patterns.append((kw, pat))
            self._compiled[topic_name] = (weight, patterns)

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
                    base_score = min(100.0, base_score * 1.3)
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
        combined = sum(ts.score for ts in top_n) / len(top_n)
        combined = min(100.0, round(combined, 1))

        return combined, topic_scores
