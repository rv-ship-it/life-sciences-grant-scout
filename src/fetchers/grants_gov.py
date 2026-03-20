import time
from datetime import date, datetime
from typing import Generator

from ..models import Opportunity, Source, ActivityType
from .base import BaseFetcher

INSTRUMENT_MAP = {
    "G": ActivityType.GRANT,
    "CA": ActivityType.COOPERATIVE,
    "PC": ActivityType.CONTRACT,
    "O": ActivityType.OTHER,
}


class GrantsGovFetcher(BaseFetcher):
    source_name = "Grants.gov"

    def fetch(self) -> Generator[Opportunity, None, None]:
        start = 0
        rows = self.config.get("rows_per_page", 250)
        seen_ids = set()

        while True:
            payload = {
                "fundingCategories": "HL",
                "sortBy": "openDate|desc",
                "rows": rows,
                "oppStatuses": "forecasted|posted",
                "startRecordNum": start,
            }
            resp = self._request_with_retry(
                "POST", self.config["url"],
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            raw = resp.json()
            # Response is nested: {data: {oppHits: [...], hitCount: N}}
            data = raw.get("data", raw)

            hits = data.get("oppHits", [])
            if not hits:
                break

            for hit in hits:
                opp_id = str(hit.get("id", ""))
                if opp_id not in seen_ids:
                    seen_ids.add(opp_id)
                    yield self._parse_hit(hit)

            start += rows
            total = data.get("hitCount", data.get("totalCount", 0))
            if start >= total:
                break

            time.sleep(1)

    def _parse_hit(self, hit: dict) -> Opportunity:
        opp_id = str(hit.get("id", ""))
        number = hit.get("number", "") or ""
        title = hit.get("title", "")
        agency_code = hit.get("agencyCode", "") or hit.get("agency", "")
        doc_type = hit.get("docType", "")

        # Search results have limited fields; synopsis may not be present
        synopsis = hit.get("synopsis", "") or hit.get("description", "") or ""

        posted = self._parse_date(hit.get("openDate"))
        deadline = self._parse_date(hit.get("closeDate"))

        ceiling = self._parse_int(hit.get("awardCeiling"))
        floor = self._parse_int(hit.get("awardFloor"))

        eligibility_text = ""
        applicant_types = hit.get("applicantTypes", [])
        if isinstance(applicant_types, list):
            eligibility_text = "; ".join(str(t) for t in applicant_types)
        elif applicant_types:
            eligibility_text = str(applicant_types)

        cfda_list = hit.get("cfdaList", [])
        if cfda_list:
            eligibility_text += f" CFDA: {', '.join(str(c) for c in cfda_list)}"

        return Opportunity(
            id=f"GRANTS-GOV-{opp_id}",
            source=Source.GRANTS_GOV,
            url=f"https://www.grants.gov/search-results-detail/{opp_id}",
            title=title,
            description=synopsis[:5000] if synopsis else f"{title} ({number})",
            agency=agency_code,
            activity_type=ActivityType.GRANT,
            posted_date=posted,
            deadline=deadline,
            award_ceiling=ceiling,
            award_floor=floor,
            eligibility_text=eligibility_text.strip(),
            raw_data=hit,
        )

    def _parse_date(self, date_str) -> date | None:
        if not date_str:
            return None
        if isinstance(date_str, str):
            for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
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
