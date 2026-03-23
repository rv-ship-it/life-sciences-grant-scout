"""Innovation Fund Denmark fetcher.

Scrapes https://innovationsfonden.dk/en/programmes
for open calls across IFD's programme portfolio.
"""

import re
import time
from datetime import date, datetime
from typing import Generator

from bs4 import BeautifulSoup

from ..models import ActivityType, Opportunity, Source
from .base import BaseFetcher


class InnovationFundDKFetcher(BaseFetcher):
    source_name = "Innovation Fund Denmark"

    def fetch(self) -> Generator[Opportunity, None, None]:
        delay = self.config.get("request_delay", 2.0)
        base_url = self.config.get(
            "detail_url_base", "https://innovationsfonden.dk"
        )

        # Phase 1: Get programmes listing page
        listing_url = self.config["url"]
        try:
            resp = self._request_with_retry("GET", listing_url)
        except Exception as e:
            self.logger.error(f"Failed to fetch listing page: {e}")
            return

        soup = BeautifulSoup(resp.text, "lxml")
        programme_links = self._extract_programme_links(soup, base_url)
        self.logger.info(f"Found {len(programme_links)} programme links")

        # Phase 2: Scrape each programme page for open calls
        for name, link in programme_links:
            time.sleep(delay)
            try:
                for opp in self._fetch_programme(name, link):
                    yield opp
            except Exception as e:
                self.logger.warning(f"Failed to parse programme {name}: {e}")

        # Also check the apply-investment page for additional calls
        time.sleep(delay)
        try:
            apply_url = base_url + "/en/apply-investment"
            for opp in self._fetch_apply_page(apply_url, base_url):
                yield opp
        except Exception as e:
            self.logger.warning(f"Failed to parse apply page: {e}")

    def _extract_programme_links(
        self, soup: BeautifulSoup, base_url: str
    ) -> list[tuple[str, str]]:
        """Extract programme page URLs from the listing page."""
        links = []
        seen = set()
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if "/en/p/" in href:
                if href.startswith("/"):
                    href = base_url.rstrip("/") + href
                if href not in seen:
                    seen.add(href)
                    name = a_tag.get_text(strip=True) or href.split("/")[-1]
                    links.append((name, href))
        return links

    def _fetch_programme(
        self, programme_name: str, url: str
    ) -> Generator[Opportunity, None, None]:
        """Scrape a programme page for open calls."""
        resp = self._request_with_retry("GET", url)
        soup = BeautifulSoup(resp.text, "lxml")
        text = soup.get_text()

        if not self._has_open_call_signals(text):
            self.logger.debug(f"No open call signals for {programme_name}")
            return

        slug = url.rstrip("/").split("/")[-1]
        title = self._extract_title(soup) or programme_name
        description = self._extract_description(soup)
        deadline = self._extract_deadline(text)

        yield Opportunity(
            id=f"IFD-{slug}",
            source=Source.INNOVATION_FUND_DK,
            url=url,
            title=title,
            description=description[:5000],
            agency="Innovation Fund Denmark",
            activity_type=ActivityType.GRANT,
            deadline=deadline,
            award_ceiling=self._extract_funding(text),
            currency="EUR",
            eligibility_text=self._extract_eligibility(text),
            raw_data={"programme": programme_name, "url": url},
        )

    def _fetch_apply_page(
        self, url: str, base_url: str
    ) -> Generator[Opportunity, None, None]:
        """Scrape the apply-investment page for additional open calls."""
        try:
            resp = self._request_with_retry("GET", url)
        except Exception:
            return

        soup = BeautifulSoup(resp.text, "lxml")
        text = soup.get_text()

        # Look for deadline mentions that indicate open calls
        deadlines = re.findall(
            r"(?:deadline|closes?)[:\s]*(\d{1,2}[\s./\-]\w+[\s./\-]\d{4}|\w+\s+\d{1,2},?\s+\d{4})",
            text,
            re.IGNORECASE,
        )

        if not deadlines:
            return

        # The apply page may have distinct calls listed
        title = self._extract_title(soup) or "Innovation Fund Denmark - Open Calls"
        description = self._extract_description(soup)
        deadline = None
        for d_str in deadlines:
            parsed = self._try_parse_date(d_str)
            if parsed and parsed > date.today():
                deadline = parsed
                break

        if deadline:
            yield Opportunity(
                id="IFD-apply-investment",
                source=Source.INNOVATION_FUND_DK,
                url=url,
                title=title,
                description=description[:5000],
                agency="Innovation Fund Denmark",
                activity_type=ActivityType.GRANT,
                deadline=deadline,
                currency="EUR",
                raw_data={"url": url},
            )

    def _has_open_call_signals(self, text: str) -> bool:
        """Check if page text indicates an active/open call."""
        lower = text.lower()
        open_signals = [
            r"\bopen\s+call\b", r"\bapply\s+now\b", r"\bdeadline\b",
            r"\bsubmission\b", r"\bapplication\s+period\b",
            r"\bcall\s+for\s+proposals\b", r"\bapply\s+for\b",
        ]
        closed_signals = [
            r"\bno\s+open\s+calls?\b", r"\bcurrently\s+closed\b",
            r"\bnot\s+currently\s+open\b",
        ]
        has_open = any(re.search(s, lower) for s in open_signals)
        has_closed = any(re.search(s, lower) for s in closed_signals)
        return has_open and not has_closed

    def _extract_title(self, soup: BeautifulSoup) -> str:
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)
        return ""

    def _extract_description(self, soup: BeautifulSoup) -> str:
        for selector in ["article", ".field--name-body", "main", ".node__content"]:
            content = soup.select_one(selector)
            if content:
                text = content.get_text(separator=" ", strip=True)
                if len(text) > 50:
                    return re.sub(r"\s+", " ", text)
        return ""

    def _extract_deadline(self, text: str) -> date | None:
        patterns = [
            r"(?:deadline|due|closes?)[:\s]*(\d{1,2}[\./\-]\d{1,2}[\./\-]\d{4})",
            r"(?:deadline|due|closes?)[:\s]*(\d{1,2}\s+\w+\s+\d{4})",
            r"(?:deadline|due|closes?)[:\s]*(\w+\s+\d{1,2},?\s+\d{4})",
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                parsed = self._try_parse_date(match)
                if parsed and parsed > date.today():
                    return parsed
        return None

    def _extract_funding(self, text: str) -> int | None:
        amounts = []
        for match in re.finditer(
            r"(?:EUR|DKK|\$|€)\s*([\d,.]+)\s*([KMBkmb](?:illion|r)?)?",
            text, re.IGNORECASE,
        ):
            num_str = match.group(1).replace(",", "")
            # Handle European decimal format (dots as thousands separator)
            if "." in num_str and len(num_str.split(".")[-1]) == 3:
                num_str = num_str.replace(".", "")
            suffix = (match.group(2) or "").upper()
            try:
                amount = float(num_str)
                if suffix.startswith("M"):
                    amount *= 1_000_000
                elif suffix.startswith("K"):
                    amount *= 1_000
                elif suffix.startswith("B"):
                    amount *= 1_000_000_000
                amounts.append(int(amount))
            except ValueError:
                continue
        return max(amounts) if amounts else None

    def _extract_eligibility(self, text: str) -> str:
        matches = re.findall(
            r"(?:eligib\w+|who\s+can\s+apply)[:\s]*([^.]{20,200}\.)",
            text, re.IGNORECASE,
        )
        return " ".join(matches[:2]).strip()

    def _try_parse_date(self, date_str: str) -> date | None:
        clean = date_str.strip().replace(",", "")
        formats = [
            "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
            "%d %B %Y", "%d %b %Y",
            "%B %d %Y", "%b %d %Y",
            "%Y-%m-%d",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(clean, fmt).date()
            except ValueError:
                continue
        return None
