import json
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class SemanticScorer:
    """Optional Claude API scoring for grant relevance."""

    def __init__(self, config: dict):
        self.model = config.get("model", "claude-sonnet-4-6")
        self.company_context = config.get("company_context", "")
        self.batch_size = config.get("batch_size", 10)
        self.batch_delay = config.get("batch_delay", 5)

        try:
            import anthropic
            self.client = anthropic.Anthropic()
        except Exception as e:
            logger.warning(f"Could not initialize Anthropic client: {e}")
            self.client = None

    def score_single(self, title: str, description: str) -> Optional[float]:
        if not self.client:
            return None

        prompt = f"""Score this grant opportunity's relevance to our company on a 0-100 scale.

Company context: {self.company_context}

Grant title: {title}
Grant description: {description[:2000]}

Respond with ONLY a JSON object:
{{"score": <0-100>, "rationale": "<one sentence>"}}"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=100,
                messages=[{"role": "user", "content": prompt}],
            )
            result = json.loads(response.content[0].text)
            return float(result["score"])
        except Exception as e:
            logger.warning(f"Semantic scoring failed: {e}")
            return None

    def score_batch(self, opportunities: list) -> list:
        for i in range(0, len(opportunities), self.batch_size):
            batch = opportunities[i : i + self.batch_size]
            for opp in batch:
                opp.semantic_score = self.score_single(opp.title, opp.description)

            if i + self.batch_size < len(opportunities):
                time.sleep(self.batch_delay)

        return opportunities
