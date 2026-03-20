import logging
from datetime import date, datetime
from pathlib import Path

import yaml

from .deduplicator import Deduplicator
from .eligibility import parse_eligibility
from .fetchers.eu_portal import EUPortalFetcher
from .fetchers.grants_gov import GrantsGovFetcher
from .fetchers.nih_guide import NIHGuideFetcher
from .fetchers.sbir import SBIRFetcher
from .scoring.combined import CombinedScorer
from .scoring.keyword_scorer import KeywordScorer
from .scoring.semantic_scorer import SemanticScorer

logger = logging.getLogger(__name__)

# Order matters: SBIR before Grants.gov so startup flags are preserved during dedup
FETCHER_MAP = {
    "nih_guide": (NIHGuideFetcher, "nih_guide"),
    "sbir": (SBIRFetcher, "sbir"),
    "grants_gov": (GrantsGovFetcher, "grants_gov"),
    "eu_portal": (EUPortalFetcher, "eu_portal"),
}


class Pipeline:
    """Orchestrates: FETCH -> ELIGIBILITY -> SCORE -> DEDUPE -> FILTER EXPIRED -> EXPORT."""

    def __init__(self, config_dir: str = "config"):
        self.config_dir = Path(config_dir)
        self.settings = self._load_yaml("settings.yml")
        self.topics = self._load_yaml("topics.yml")
        self.run_log = {
            "started_at": datetime.utcnow().isoformat(),
            "sources": {},
            "errors": [],
        }

    def _load_yaml(self, filename: str) -> dict:
        with open(self.config_dir / filename) as f:
            return yaml.safe_load(f)

    def run(self, sources: list[str] | None = None,
            skip_semantic: bool = False) -> list:
        # Stage 1: FETCH
        all_opps = []
        fetchers = self._build_fetchers(sources)

        for fetcher in fetchers:
            try:
                logger.info(f"Fetching from {fetcher.source_name}...")
                opps = list(fetcher.fetch())
                self.run_log["sources"][fetcher.source_name] = {
                    "fetched": len(opps), "status": "ok"
                }
                all_opps.extend(opps)
                logger.info(f"  -> {len(opps)} opportunities")
            except Exception as e:
                logger.error(f"Error fetching {fetcher.source_name}: {e}")
                self.run_log["sources"][fetcher.source_name] = {
                    "fetched": 0, "status": "error", "error": str(e)
                }
                self.run_log["errors"].append(str(e))

        logger.info(f"Total fetched: {len(all_opps)}")

        # Stage 2: ELIGIBILITY
        logger.info("Parsing eligibility flags...")
        all_opps = [parse_eligibility(opp) for opp in all_opps]

        # Stage 3: KEYWORD SCORING
        logger.info("Running keyword scoring...")
        keyword_scorer = KeywordScorer(self.topics["topics"])
        for opp in all_opps:
            score, topic_scores = keyword_scorer.score(opp.title, opp.description)
            opp.keyword_score = score
            opp.topic_scores = topic_scores

        # Stage 4: SEMANTIC SCORING (optional)
        sem_config = self.settings.get("semantic_scoring", {})
        if sem_config.get("enabled", False) and not skip_semantic:
            logger.info("Running semantic scoring with Claude API...")
            semantic_scorer = SemanticScorer(sem_config)
            candidates = [o for o in all_opps if o.keyword_score > 10]
            logger.info(f"  -> Scoring {len(candidates)} candidates")
            semantic_scorer.score_batch(candidates)

        # Stage 5: COMBINED SCORING
        logger.info("Computing combined scores...")
        scoring_config = self.topics.get("scoring", {})
        combined_scorer = CombinedScorer(
            keyword_weight=scoring_config.get("keyword_weight", 0.60),
            semantic_weight=scoring_config.get("semantic_weight", 0.40),
            priority_threshold=scoring_config.get("high_priority_score_threshold", 40),
            priority_deadline_days=scoring_config.get("high_priority_deadline_days", 60),
        )
        all_opps = [combined_scorer.compute(opp) for opp in all_opps]

        # Stage 6: DEDUPE
        logger.info("Deduplicating...")
        threshold = self.settings["pipeline"].get("dedup_similarity_threshold", 0.85)
        deduper = Deduplicator(similarity_threshold=threshold)
        before = len(all_opps)
        all_opps = deduper.deduplicate(all_opps)
        logger.info(f"  -> Removed {before - len(all_opps)} duplicates")

        # Stage 7: FILTER EXPIRED
        logger.info("Filtering expired opportunities...")
        before_expire = len(all_opps)
        today = date.today()
        all_opps = [
            opp for opp in all_opps
            if opp.deadline is None or opp.deadline >= today
        ]
        removed_expired = before_expire - len(all_opps)
        if removed_expired:
            logger.info(f"  -> Removed {removed_expired} expired opportunities")
        self.run_log["expired_removed"] = removed_expired

        # Stage 8: SORT
        all_opps.sort(key=lambda o: o.combined_score, reverse=True)

        # Finalize run log
        self.run_log["completed_at"] = datetime.utcnow().isoformat()
        self.run_log["total_opportunities"] = len(all_opps)
        self.run_log["high_priority_count"] = sum(1 for o in all_opps if o.high_priority)
        self.run_log["startup_eligible_count"] = sum(1 for o in all_opps if o.startup_eligible)

        return all_opps

    def _build_fetchers(self, sources: list[str] | None) -> list:
        result = []
        for key, (cls, config_key) in FETCHER_MAP.items():
            src_config = self.settings["sources"].get(config_key, {})
            if not src_config.get("enabled", False):
                continue
            if sources and key not in sources:
                continue
            result.append(cls(src_config))
        return result
