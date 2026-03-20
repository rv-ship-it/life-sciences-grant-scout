import time
from datetime import date, datetime
from typing import Generator

from ..models import Opportunity, Source, ActivityType
from .base import BaseFetcher

# Keywords to search for SBIR/STTR health grants via Grants.gov
SBIR_SEARCH_KEYWORDS = [
    "SBIR", "STTR", "small business innovation",
    "small business technology transfer",
]


class SBIRFetcher(BaseFetcher):
    """Fetch SBIR/STTR grants from Grants.gov (health category).

    The SBIR.gov API is currently unavailable, so we use Grants.gov
    filtered to SBIR/STTR opportunities in the health funding category.
    All SBIR/STTR grants are startup-eligible by definition.
    """

    source_name = "SBIR/STTR"

    def fetch(self) -> Generator[Opportunity, None, None]:
        seen_ids: set[str] = set()
        api_url = "https://api.grants.gov/v1/api/search2"

        for keyword in SBIR_SEARCH_KEYWORDS:
            start = 0
            while True:
                payload = {
                    "keyword": keyword,
                    "fundingCategories": "HL",
                    "sortBy": "openDate|desc",
                    "rows": 100,
                    "oppStatuses": "forecasted|posted",
                    "startRecordNum": start,
                }
                try:
                    resp = self._request_with_retry(
                        "POST", api_url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    raw = resp.json()
                    data = raw.get("data", raw)
                except Exception as e:
                    self.logger.warning(f"SBIR search '{keyword}' failed: {e}")
                    break

                hits = data.get("oppHits", [])
                if not hits:
                    break

                for hit in hits:
                    opp_id = str(hit.get("id", ""))
                    if opp_id and opp_id not in seen_ids:
                        seen_ids.add(opp_id)
                        yield self._parse_hit(hit)

                start += 100
                total = data.get("hitCount", 0)
                if start >= total:
                    break
                time.sleep(1)

            time.sleep(1)

    def _parse_hit(self, hit: dict) -> Opportunity:
        opp_id = str(hit.get("id", ""))
        title = hit.get("title", "")
        number = hit.get("number", "") or ""
        agency_code = hit.get("agencyCode", "") or hit.get("agency", "")

        synopsis = hit.get("synopsis", "") or hit.get("description", "") or ""

        # Determine if STTR (requires research partner = consortium)
        is_sttr = "STTR" in title.upper() or "STTR" in number.upper()
        program = "STTR" if is_sttr else "SBIR"

        posted = self._parse_date(hit.get("openDate"))
        deadline = self._parse_date(hit.get("closeDate"))

        return Opportunity(
            id=f"SBIR-{opp_id}",
            source=Source.SBIR,
            url=f"https://www.grants.gov/search-results-detail/{opp_id}",
            title=title,
            description=synopsis[:5000] if synopsis else f"{title} ({number})",
            agency=agency_code,
            activity_type=ActivityType.GRANT,
            posted_date=posted,
            deadline=deadline,
            award_ceiling=self._parse_int(hit.get("awardCeiling")),
            award_floor=self._parse_int(hit.get("awardFloor")),
            startup_eligible=True,
            consortium_eligible=is_sttr,
            eligibility_text=f"{program} - Small business eligibility required",
            raw_data=hit,
        )

    def _parse_date(self, date_str) -> date | None:
        if not date_str:
            return None
        if isinstance(date_str, str):
            for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
                try:
                    return datetime.strptime(date_str, fmt).date()
                except ValueError:
                    continue
        return None

    def _parse_int(self, val) -> int | None:
        if val is None:
            return None
        try:
            return int(float(str(val).replace(",", "").replace("$", "")))
        except (ValueError, TypeError):
            return None
