"""UK Research & Innovation (UKRI) fetcher.

Parses the UKRI opportunities RSS feed at
https://www.ukri.org/opportunity/feed/ for new funding calls.
Optionally scrapes each opportunity's detail page for closing dates
(not present in the RSS feed).
"""

import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Generator

from bs4 import BeautifulSoup

from ..models import ActivityType, Opportunity, Source
from .base import BaseFetcher


class UKRIFetcher(BaseFetcher):
    source_name = "UKRI"

    def fetch(self) -> Generator[Opportunity, None, None]:
        delay = self.config.get("request_delay", 1.0)
        fetch_detail = self.config.get("fetch_detail_pages", True)

        try:
            resp = self._request_with_retry("GET", self.config["url"])
            root = ET.fromstring(resp.content)
        except Exception as e:
            self.logger.error(f"Failed to fetch UKRI RSS: {e}")
            return

        items = root.findall(".//item")
        self.logger.info(f"Found {len(items)} UKRI opportunities in RSS feed")

        for item in items:
            try:
                opp = self._parse_item(item, fetch_detail)
                if opp:
                    yield opp
            except Exception as e:
                self.logger.warning(f"Failed to parse UKRI item: {e}")
            if fetch_detail:
                time.sleep(delay)

    def _parse_item(self, item: ET.Element, fetch_detail: bool) -> Opportunity | None:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        description = (item.findtext("description") or "").strip()
        pub_date_str = item.findtext("pubDate") or ""
        category = (item.findtext("category") or "").strip()

        if not title or not link:
            return None

        slug = link.rstrip("/").split("/")[-1]
        posted = self._parse_rfc_date(pub_date_str)

        # Strip HTML from description
        clean_desc = re.sub(r"<[^>]+>", " ", description)
        clean_desc = re.sub(r"\s+", " ", clean_desc).strip()[:5000]

        deadline = None
        if fetch_detail:
            try:
                deadline = self._scrape_deadline(link)
            except Exception as e:
                self.logger.debug(f"Could not fetch deadline for {link}: {e}")

        agency = category or "UKRI"

        return Opportunity(
            id=f"UKRI-{slug}",
            source=Source.UKRI,
            url=link,
            title=title,
            description=clean_desc,
            agency=agency,
            activity_type=ActivityType.GRANT,
            posted_date=posted,
            deadline=deadline,
            currency="GBP",
            consortium_eligible=False,
            raw_data={"category": category, "slug": slug},
        )

    def _scrape_deadline(self, url: str) -> date | None:
        """Scrape the opportunity page for a closing date.
        UKRI pages typically have 'Closing date: DD Month YYYY'."""
        resp = self._request_with_retry("GET", url)
        soup = BeautifulSoup(resp.text, "lxml")
        text = soup.get_text()
        # Try "Closing date: 15 January 2027" style
        patterns = [
            r"[Cc]losing\s+date[:\s]+(\d{1,2}\s+\w+\s+\d{4})",
            r"[Cc]loses[:\s]+(\d{1,2}\s+\w+\s+\d{4})",
            r"[Dd]eadline[:\s]+(\d{1,2}\s+\w+\s+\d{4})",
        ]
        for pattern in patterns:
            m = re.search(pattern, text)
            if m:
                d = self._parse_date_str(m.group(1))
                if d:
                    return d
        return None

    def _parse_rfc_date(self, date_str: str) -> date | None:
        if not date_str:
            return None
        try:
            return parsedate_to_datetime(date_str).date()
        except Exception:
            return None

    def _parse_date_str(self, date_str: str) -> date | None:
        clean = date_str.strip()
        for fmt in ("%d %B %Y", "%d %b %Y"):
            try:
                return datetime.strptime(clean, fmt).date()
            except ValueError:
                continue
        return None
