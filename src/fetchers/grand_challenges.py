"""Grand Challenges (Gates Foundation) fetcher.

Scrapes https://gcgh.grandchallenges.org/grant-opportunities
for open grant challenges, then fetches each detail page for
deadline, funding, and eligibility information.
"""

import re
import time
from datetime import date, datetime
from typing import Generator

from bs4 import BeautifulSoup

from ..models import ActivityType, Opportunity, Source
from .base import BaseFetcher


class GrandChallengesFetcher(BaseFetcher):
    source_name = "Grand Challenges"

    def fetch(self) -> Generator[Opportunity, None, None]:
        delay = self.config.get("request_delay", 2.0)
        base_url = self.config.get(
            "detail_url_base", "https://gcgh.grandchallenges.org"
        )

        # Phase 1: Get listing page, extract challenge links
        listing_url = self.config["url"]
        try:
            resp = self._request_with_retry("GET", listing_url)
        except Exception as e:
            self.logger.error(f"Failed to fetch listing page: {e}")
            return

        soup = BeautifulSoup(resp.text, "lxml")
        challenge_links = self._extract_challenge_links(soup, base_url)
        self.logger.info(f"Found {len(challenge_links)} challenge links")

        # Phase 2: Scrape each detail page
        for link in challenge_links:
            time.sleep(delay)
            try:
                opp = self._fetch_detail(link)
                if opp:
                    yield opp
            except Exception as e:
                self.logger.warning(f"Failed to parse {link}: {e}")

    def _extract_challenge_links(
        self, soup: BeautifulSoup, base_url: str
    ) -> list[str]:
        """Extract challenge detail page URLs from the listing page."""
        links = set()
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if "/challenge/" in href:
                if href.startswith("/"):
                    href = base_url.rstrip("/") + href
                links.add(href)
        return sorted(links)

    def _fetch_detail(self, url: str) -> Opportunity | None:
        """Scrape a single challenge detail page."""
        resp = self._request_with_retry("GET", url)
        soup = BeautifulSoup(resp.text, "lxml")

        title = self._extract_title(soup)
        if not title:
            return None

        slug = url.rstrip("/").split("/")[-1]
        description = self._extract_description(soup)
        deadline = self._extract_deadline(soup)
        award_ceiling = self._extract_max_funding(soup)

        return Opportunity(
            id=f"GC-{slug}",
            source=Source.GRAND_CHALLENGES,
            url=url,
            title=title,
            description=description[:5000],
            agency="Gates Foundation",
            activity_type=ActivityType.GRANT,
            deadline=deadline,
            award_ceiling=award_ceiling,
            eligibility_text=self._extract_eligibility(soup),
            raw_data={"slug": slug, "url": url},
        )

    def _extract_title(self, soup: BeautifulSoup) -> str:
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)
        meta = soup.find("meta", property="og:title")
        if meta and meta.get("content"):
            return meta["content"].strip()
        return ""

    def _extract_description(self, soup: BeautifulSoup) -> str:
        for selector in ["article", ".field--name-body", ".node__content", "main"]:
            content = soup.select_one(selector)
            if content:
                text = content.get_text(separator=" ", strip=True)
                if len(text) > 100:
                    return re.sub(r"\s+", " ", text)
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            return meta["content"].strip()
        return ""

    def _extract_deadline(self, soup: BeautifulSoup) -> date | None:
        text = soup.get_text()
        # Look for dates near deadline keywords first
        deadline_patterns = [
            r"(?:deadline|due|closes?|submit\s+by)[:\s]*(\w+\s+\d{1,2},?\s+\d{4})",
        ]
        for pattern in deadline_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                parsed = self._parse_date_str(match)
                if parsed and parsed > date.today():
                    return parsed
        # Fallback: any future date in "Month DD, YYYY" format
        for match in re.findall(r"(\w+\s+\d{1,2},?\s+\d{4})", text):
            parsed = self._parse_date_str(match)
            if parsed and parsed > date.today():
                return parsed
        return None

    def _extract_max_funding(self, soup: BeautifulSoup) -> int | None:
        text = soup.get_text()
        amounts = []
        for match in re.finditer(r"\$\s*([\d,]+(?:\.\d+)?)\s*([KMBkmb])?", text):
            num_str = match.group(1).replace(",", "")
            multiplier_char = (match.group(2) or "").upper()
            try:
                amount = float(num_str)
                multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
                amount *= multiplier.get(multiplier_char, 1)
                amounts.append(int(amount))
            except ValueError:
                continue
        return max(amounts) if amounts else None

    def _extract_eligibility(self, soup: BeautifulSoup) -> str:
        text = soup.get_text()
        matches = []
        for pattern in [
            r"(?:eligib\w+)[:\s]*([^.]{20,200}\.)",
            r"(?:who\s+(?:can|may|should)\s+apply)[:\s]*([^.]{20,200}\.)",
        ]:
            matches.extend(re.findall(pattern, text, re.IGNORECASE))
        return " ".join(matches[:3]).strip()

    def _parse_date_str(self, date_str: str) -> date | None:
        clean = date_str.strip().replace(",", "")
        for fmt in ("%B %d %Y", "%b %d %Y"):
            try:
                return datetime.strptime(clean, fmt).date()
            except ValueError:
                continue
        return None
