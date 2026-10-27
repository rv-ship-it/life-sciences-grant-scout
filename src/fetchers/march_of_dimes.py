"""March of Dimes fetcher.

Scrapes the March of Dimes research grants page. March of Dimes funds
maternal/infant health research including breast milk composition —
high relevance for the mucin/HMO angle.
"""

import re
import time
from datetime import date, datetime
from typing import Generator

from bs4 import BeautifulSoup

from ..models import ActivityType, Opportunity, Source
from .base import BaseFetcher


class MarchOfDimesFetcher(BaseFetcher):
    source_name = "March of Dimes"

    def fetch(self) -> Generator[Opportunity, None, None]:
        delay = self.config.get("request_delay", 2.0)
        base_url = "https://www.marchofdimes.org"

        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        })

        try:
            resp = self._request_with_retry("GET", self.config["url"])
        except Exception as e:
            self.logger.warning(f"March of Dimes page failed ({e}); yielding no grants")
            return

        soup = BeautifulSoup(resp.text, "lxml")

        grant_links = self._extract_grant_links(soup, base_url)
        self.logger.info(f"Found {len(grant_links)} March of Dimes grant links")

        for title, link in grant_links:
            time.sleep(delay)
            try:
                opp = self._scrape_grant(title, link)
                if opp:
                    yield opp
            except Exception as e:
                self.logger.warning(f"Failed to scrape {link}: {e}")

    # Titles that look grant-ish but are really navigation / landing pages
    GENERIC_TITLE_BLOCKLIST = {
        "areas of research",
        "grants and awards",
        "grants & awards",
        "research grants",
        "our research",
        "funding",
        "research",
        "awards",
        "grants",
        "research centers",
        "prematurity research centers",
        "research areas",
    }

    def _extract_grant_links(
        self, soup: BeautifulSoup, base_url: str
    ) -> list[tuple[str, str]]:
        links = []
        seen = set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = a.get_text(strip=True)
            if not text or len(text) < 10:
                continue
            if text.lower() in self.GENERIC_TITLE_BLOCKLIST:
                continue
            lower_href = href.lower()
            lower_text = text.lower()
            # Keep links that look like SPECIFIC grant programs (named awards,
            # starter grants, etc.) — not landing pages
            specific_markers = [
                "starter",
                "scholar",
                "fellowship",
                "grant program",
                "award program",
                "innovator",
                "pilot",
                "basil",
                "rfa",
                "rfp",
            ]
            is_specific = any(
                m in lower_text or m in lower_href for m in specific_markers
            )
            # OR: the URL path is deep (more than just /our-work/research/*)
            # indicating a specific program page
            path_depth = href.count("/") - (3 if href.startswith("http") else 0)
            is_deep = path_depth >= 4 and any(
                kw in lower_href
                for kw in ["grant", "award", "fellowship", "scholar"]
            )
            if is_specific or is_deep:
                if href.startswith("/"):
                    href = base_url + href
                if href not in seen and href.startswith(base_url):
                    seen.add(href)
                    links.append((text, href))
        return links[:30]

    def _scrape_grant(self, title: str, url: str) -> Opportunity | None:
        try:
            resp = self._request_with_retry("GET", url)
        except Exception:
            return None
        soup = BeautifulSoup(resp.text, "lxml")

        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True) or title

        description = ""
        for sel in ["article", "main", ".content"]:
            el = soup.select_one(sel)
            if el:
                description = re.sub(r"\s+", " ", el.get_text(separator=" ", strip=True))
                if len(description) > 100:
                    break
        if len(description) < 50:
            return None

        text = soup.get_text()
        deadline = self._extract_deadline(text)
        funding = self._extract_funding(text)

        # Quality gate: only yield pages that look like actual grant RFPs,
        # not navigation / "about our research" landing pages.
        lower = text.lower()
        has_rfp_content = any(
            kw in lower
            for kw in [
                "deadline",
                "applications are",
                "application deadline",
                "apply by",
                "letter of intent",
                "loi deadline",
                "submission deadline",
                "eligibility",
                "principal investigator",
                "award amount",
                "award period",
            ]
        )
        if not (deadline or funding or has_rfp_content):
            self.logger.debug(f"MOD page {url} looks like a landing page; skipping")
            return None

        slug = url.rstrip("/").split("/")[-1]
        return Opportunity(
            id=f"MOD-{slug}",
            source=Source.MARCH_OF_DIMES,
            url=url,
            title=title,
            description=description[:5000],
            agency="March of Dimes",
            activity_type=ActivityType.GRANT,
            deadline=deadline,
            award_ceiling=funding,
            raw_data={"url": url},
        )

    def _extract_deadline(self, text: str) -> date | None:
        for pattern in [
            r"(?:deadline|due|closes?|submit\s+by)[:\s]+(\w+\s+\d{1,2},?\s+\d{4})",
        ]:
            for match in re.findall(pattern, text, re.IGNORECASE):
                d = self._parse_date_str(match)
                if d and d > date.today():
                    return d
        return None

    def _extract_funding(self, text: str) -> int | None:
        amounts = []
        for m in re.finditer(r"\$\s*([\d,]+)\s*([KMB])?", text):
            try:
                amount = int(m.group(1).replace(",", ""))
                sfx = (m.group(2) or "").upper()
                if sfx == "M":
                    amount *= 1_000_000
                elif sfx == "K":
                    amount *= 1_000
                amounts.append(amount)
            except ValueError:
                continue
        return max(amounts) if amounts else None

    def _parse_date_str(self, s: str) -> date | None:
        s = s.strip().replace(",", "")
        for fmt in ("%B %d %Y", "%b %d %Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None
