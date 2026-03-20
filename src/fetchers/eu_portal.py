import json
import re
import time
from datetime import date, datetime
from typing import Generator

from ..models import Opportunity, Source, ActivityType
from .base import BaseFetcher


class EUPortalFetcher(BaseFetcher):
    source_name = "EU Funding Portal"

    def fetch(self) -> Generator[Opportunity, None, None]:
        seen_ids: set[str] = set()
        max_pages = self.config.get("max_pages", 10)

        # Run multiple focused searches for better relevance
        search_terms = [
            "microbiome AND health",
            "nutrition AND infant",
            "biomanufacturing",
            "mucosal AND barrier",
            "glycan OR glycoprotein",
            "probiotic OR prebiotic",
            "menopause OR vaginal",
            "skin AND microbiome",
            "gut AND health",
            "fermentation AND biotherapeutic",
            # Expanded topic coverage
            "inflammatory bowel disease OR Crohn OR ulcerative colitis",
            "autoimmune disease OR chronic inflammation",
            "bacterial vaginosis OR endometriosis OR PCOS",
            "nutraceutical OR functional food OR personalized nutrition",
            "Clostridioides difficile OR necrotizing enterocolitis",
        ]

        for search_text in search_terms:
            page = 1
            while page <= max_pages:
                form_data = {
                    "apiKey": "SEDIA",
                    "text": search_text,
                    "pageSize": "50",
                    "pageNumber": str(page),
                    "type": "1",
                }
                try:
                    resp = self._request_with_retry(
                        "POST", self.config["url"], data=form_data
                    )
                    data = resp.json()
                except Exception as e:
                    self.logger.warning(f"EU search '{search_text}' failed: {e}")
                    break

                results = data.get("results", [])
                if not results:
                    break

                for result in results:
                    meta = result.get("metadata", {})
                    identifier = self._get_first(meta, "identifier")
                    if identifier and identifier not in seen_ids:
                        seen_ids.add(identifier)
                        opp = self._parse_result(meta)
                        if opp:
                            yield opp

                total = data.get("totalResults", 0)
                if page * 50 >= total or page >= 5:
                    break
                page += 1
                time.sleep(0.5)

            time.sleep(0.5)

    def _parse_result(self, meta: dict) -> Opportunity | None:
        identifier = self._get_first(meta, "identifier") or ""
        title = self._get_first(meta, "title") or ""
        if not title:
            return None

        # Get description from descriptionByte (HTML) - strip tags
        description_html = self._get_first(meta, "descriptionByte") or ""
        description = re.sub(r"<[^>]+>", " ", description_html)
        description = re.sub(r"\s+", " ", description).strip()[:5000]

        # Add tags/keywords for better topic matching
        tags = meta.get("tags", [])
        keywords = meta.get("keywords", [])
        extra_text = " ".join(str(t) for t in tags + keywords)
        if extra_text:
            description = f"{description}\n\nTags: {extra_text}"

        deadline_str = self._get_first(meta, "deadlineDate")
        start_str = self._get_first(meta, "startDate")
        budget = self._parse_budget(meta)

        action_type = self._get_first(meta, "typesOfAction") or ""
        call_id = self._get_first(meta, "callIdentifier") or ""
        call_title = self._get_first(meta, "callTitle") or ""

        return Opportunity(
            id=f"EU-{identifier}",
            source=Source.EU_PORTAL,
            url=f"https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/{identifier}",
            title=title,
            description=description,
            agency=call_id.split("-")[0] if call_id else "EU",
            activity_type=ActivityType.GRANT,
            posted_date=self._parse_date(start_str),
            deadline=self._parse_date(deadline_str),
            award_ceiling=budget,
            currency="EUR",
            startup_eligible=False,  # Detected by eligibility parser
            consortium_eligible=True,  # Most EU grants require consortia
            eligibility_text=f"{action_type}. Call: {call_title}",
            raw_data=meta,
        )

    def _get_first(self, meta: dict, key: str) -> str | None:
        val = meta.get(key)
        if isinstance(val, list) and val:
            return str(val[0])
        if val:
            return str(val)
        return None

    def _parse_date(self, date_str) -> date | None:
        if not date_str:
            return None
        date_str = str(date_str)
        # Handle "2026-04-14T00:00:00.000+0000" format
        clean = date_str.split(".")[0].split("+")[0]
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(clean, fmt).date()
            except ValueError:
                continue
        return None

    def _parse_budget(self, meta: dict) -> int | None:
        budget_str = self._get_first(meta, "budgetOverview")
        if not budget_str:
            return None
        try:
            budget_data = json.loads(budget_str)
            topic_map = budget_data.get("budgetTopicActionMap", {})
            total = 0
            for actions in topic_map.values():
                for action in actions:
                    for item in action.get("budgetItems", []):
                        amt = item.get("amount", 0)
                        if amt:
                            total += int(amt)
            return total if total > 0 else None
        except Exception:
            return None
