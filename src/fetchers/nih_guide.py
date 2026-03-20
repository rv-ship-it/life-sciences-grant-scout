import re
import xml.etree.ElementTree as ET
from datetime import date
from email.utils import parsedate_to_datetime
from typing import Generator

from ..models import Opportunity, Source, ActivityType
from .base import BaseFetcher

# Map NIH 2-letter institute codes to names
INSTITUTE_MAP = {
    "AA": "NIAAA", "AG": "NIA", "AI": "NIAID", "AR": "NIAMS",
    "AT": "NCCIH", "CA": "NCI", "DA": "NIDA", "DC": "NIDCD",
    "DE": "NIDCR", "DK": "NIDDK", "EB": "NIBIB", "ES": "NIEHS",
    "EY": "NEI", "GM": "NIGMS", "HD": "NICHD", "HG": "NHGRI",
    "HL": "NHLBI", "LM": "NLM", "MD": "NIMHD", "MH": "NIMH",
    "NR": "NINR", "NS": "NINDS", "OD": "OD", "RR": "NCRR",
    "TR": "NCATS", "TW": "FIC",
}

ACTIVITY_MAP = {
    "RFA": ActivityType.RFA,
    "PA": ActivityType.PA,
    "PAR": ActivityType.PAR,
    "NOT": ActivityType.NOT,
    "OTA": ActivityType.OTA,
}


class NIHGuideFetcher(BaseFetcher):
    source_name = "NIH Guide"

    def fetch(self) -> Generator[Opportunity, None, None]:
        resp = self._request_with_retry("GET", self.config["url"])
        root = ET.fromstring(resp.content)

        for item in root.findall(".//item"):
            opp = self._parse_item(item)
            if opp:
                yield opp

    def _parse_item(self, item: ET.Element) -> Opportunity | None:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        description = (item.findtext("description") or "").strip()
        pub_date_str = item.findtext("pubDate") or ""
        category = (item.findtext("category") or "").strip()
        guid = (item.findtext("guid") or "").strip()

        if not title:
            return None

        posted_date = self._parse_date(pub_date_str)
        activity_type = ACTIVITY_MAP.get(category.upper(), ActivityType.OTHER)
        agency = self._extract_agency(title)

        return Opportunity(
            id=guid or link,
            source=Source.NIH,
            url=link,
            title=title,
            description=description,
            agency=agency,
            activity_type=activity_type,
            posted_date=posted_date,
            raw_data={"category": category, "guid": guid},
        )

    def _extract_agency(self, title: str) -> str:
        m = re.search(r"(?:RFA|PA|PAR|NOT|OTA)-([A-Z]{2})", title)
        if m:
            code = m.group(1)
            return INSTITUTE_MAP.get(code, f"NIH-{code}")
        return "NIH"

    def _parse_date(self, date_str: str) -> date | None:
        if not date_str:
            return None
        try:
            return parsedate_to_datetime(date_str).date()
        except Exception:
            return None
