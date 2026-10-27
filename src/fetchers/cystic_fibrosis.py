"""Cystic Fibrosis Foundation (CFF) fetcher.

Scrapes the CFF Clinical Research Awards page for open grants.
Mucin biology is central to CF (mucus clearance defect), so CFF
grants are high-relevance for a mucin-focused company.
"""

import re
import time
from datetime import date, datetime
from typing import Generator

from bs4 import BeautifulSoup

from ..models import ActivityType, Opportunity, Source
from .base import BaseFetcher


class CFFFetcher(BaseFetcher):
    source_name = "Cystic Fibrosis Foundation"

    def fetch(self) -> Generator[Opportunity, None, None]:
        delay = self.config.get("request_delay", 2.0)
        base_url = "https://www.cff.org"

        # Add browser-like headers; CFF uses Cloudflare and will 403 the
        # default User-Agent on some paths.
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        })

        try:
            resp = self._request_with_retry("GET", self.config["url"])
        except Exception as e:
            self.logger.warning(f"CFF main page failed ({e}); yielding no grants")
            return

        soup = BeautifulSoup(resp.text, "lxml")

        # Find grant/award links on the page. The CFF research awards page
        # typically has a list of named awards.
        award_links = self._extract_award_links(soup, base_url)
        self.logger.info(f"Found {len(award_links)} CFF award links")

        for title, link in award_links:
            time.sleep(delay)
            try:
                opp = self._scrape_award(title, link)
                if opp:
                    yield opp
            except Exception as e:
                self.logger.warning(f"Failed to scrape CFF {link}: {e}")

    def _extract_award_links(
        self, soup: BeautifulSoup, base_url: str
    ) -> list[tuple[str, str]]:
        links = []
        seen = set()
        # Look for links in the main content area that appear to be awards
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = a.get_text(strip=True)
            if not text or len(text) < 10:
                continue
            # Filter to award-related URLs
            lower = href.lower()
            if any(
                kw in lower
                for kw in ["award", "grant", "fellowship", "scholar", "pilot"]
            ):
                if href.startswith("/"):
                    href = base_url + href
                if href not in seen and href.startswith(base_url):
                    seen.add(href)
                    links.append((text, href))
        return links[:30]  # Cap to avoid runaway

    def _scrape_award(self, title: str, url: str) -> Opportunity | None:
        try:
            resp = self._request_with_retry("GET", url)
        except Exception:
            return None
        soup = BeautifulSoup(resp.text, "lxml")

        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True) or title

        description = self._extract_description(soup)
        if not description or len(description) < 50:
            return None

        text = soup.get_text()
        deadline = self._extract_deadline(text)
        funding = self._extract_funding(text)

        slug = url.rstrip("/").split("/")[-1]
        return Opportunity(
            id=f"CFF-{slug}",
            source=Source.CFF,
            url=url,
            title=title,
            description=description[:5000],
            agency="Cystic Fibrosis Foundation",
            activity_type=ActivityType.GRANT,
            deadline=deadline,
            award_ceiling=funding,
            raw_data={"url": url},
        )

    def _extract_description(self, soup: BeautifulSoup) -> str:
        for selector in ["article", "main", ".content", "#content"]:
            el = soup.select_one(selector)
            if el:
                text = el.get_text(separator=" ", strip=True)
                if len(text) > 100:
                    return re.sub(r"\s+", " ", text)
        meta = soup.find("meta", attrs={"name": "description"})
        return meta.get("content", "").strip() if meta else ""

    def _extract_deadline(self, text: str) -> date | None:
        for pattern in [
            r"(?:deadline|due|closes?|submit\s+by)[:\s]+(\w+\s+\d{1,2},?\s+\d{4})",
            r"(?:deadline|due|closes?)[:\s]+(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})",
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
                elif sfx == "B":
                    amount *= 1_000_000_000
                amounts.append(amount)
            except ValueError:
                continue
        return max(amounts) if amounts else None

    def _parse_date_str(self, s: str) -> date | None:
        s = s.strip().replace(",", "")
        for fmt in ("%B %d %Y", "%b %d %Y", "%m/%d/%Y", "%m-%d-%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None
