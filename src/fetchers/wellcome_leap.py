"""Wellcome Leap fetcher.

Scrapes https://wellcomeleap.org for open program calls.
Most Wellcome Leap programs have already selected performers,
so this fetcher only yields genuinely open calls.
"""

import re
import time
from datetime import date, datetime
from typing import Generator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import ActivityType, Opportunity, Source
from .base import BaseFetcher

# Known program URL paths as fallback (since /programs/ may 404)
KNOWN_PROGRAM_PATHS = [
    "/the-missed-vital-sign/",
    "/care/",
    "/visible/",
    "/delta-tissue/",
    "/r3/",
    "/1000-days/",
    "/in-utero/",
    "/untangling-addiction/",
    "/dynamic-resilience/",
    "/q4bio/",
    "/save/",
    "/r3-global/",
    "/mcpsych/",
    "/hope/",
    "/form/",
]


class WellcomeLeapFetcher(BaseFetcher):
    source_name = "Wellcome Leap"

    def fetch(self) -> Generator[Opportunity, None, None]:
        delay = self.config.get("request_delay", 2.0)
        base_url = self.config["url"].rstrip("/")

        # Phase 1: Discover programs from site navigation
        program_links = self._discover_programs(base_url)

        # Phase 2: Merge with known paths for completeness
        seen = {link for _, link in program_links}
        for path in KNOWN_PROGRAM_PATHS:
            full_url = base_url + path
            if full_url not in seen:
                name = path.strip("/").replace("-", " ").title()
                program_links.append((name, full_url))
                seen.add(full_url)

        self.logger.info(f"Checking {len(program_links)} Wellcome Leap programs")

        # Phase 3: Check each program page for open calls
        for name, link in program_links:
            time.sleep(delay)
            try:
                opp = self._check_program(name, link)
                if opp:
                    yield opp
            except Exception as e:
                self.logger.warning(f"Failed to check program {name}: {e}")

    def _discover_programs(self, base_url: str) -> list[tuple[str, str]]:
        """Discover program pages from site navigation and /programs/ page."""
        programs = []
        seen = set()

        skip_paths = {
            "/about", "/team", "/news", "/contact", "/careers",
            "/privacy", "/terms", "/stories", "/faq",
        }

        # Try main page navigation
        try:
            resp = self._request_with_retry("GET", base_url + "/")
            soup = BeautifulSoup(resp.text, "lxml")
            nav = soup.find("nav") or soup
            for a_tag in nav.find_all("a", href=True):
                href = a_tag["href"]
                full = urljoin(base_url + "/", href)
                if (
                    full.startswith(base_url)
                    and full != base_url + "/"
                    and full not in seen
                    and not any(skip in full for skip in skip_paths)
                ):
                    name = a_tag.get_text(strip=True)
                    if name and len(name) > 2:
                        programs.append((name, full))
                        seen.add(full)
        except Exception as e:
            self.logger.debug(f"Main page navigation scan failed: {e}")

        # Try /programs/ page
        programs_url = base_url + self.config.get("programs_path", "/programs/")
        try:
            resp = self._request_with_retry("GET", programs_url)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")
                for a_tag in soup.find_all("a", href=True):
                    href = a_tag["href"]
                    full = urljoin(base_url + "/", href)
                    if (
                        full.startswith(base_url)
                        and full not in seen
                        and full != base_url + "/"
                        and not any(skip in full for skip in skip_paths)
                    ):
                        name = a_tag.get_text(strip=True)
                        if name and len(name) > 2:
                            programs.append((name, full))
                            seen.add(full)
        except Exception as e:
            self.logger.debug(f"/programs/ page unavailable: {e}")

        return programs

    def _check_program(self, program_name: str, url: str) -> Opportunity | None:
        """Check if a program page has an open call."""
        resp = self._request_with_retry("GET", url)
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "lxml")
        text = soup.get_text()
        lower_text = text.lower()

        # Strong closed signals — skip immediately
        closed_patterns = [
            r"performers?\s+(?:have\s+been\s+)?selected",
            r"selection\s+(?:is\s+)?complete",
            r"program\s+(?:is\s+)?closed",
            r"no\s+longer\s+accepting",
            r"call\s+(?:is\s+)?closed",
            r"applications?\s+(?:are?\s+)?closed",
        ]
        if any(re.search(p, lower_text) for p in closed_patterns):
            self.logger.debug(f"Program '{program_name}' appears closed")
            return None

        # Open signals required to yield
        open_patterns = [
            r"call\s+for\s+proposals?",
            r"request\s+for\s+proposals?",
            r"apply\s+now",
            r"submit\s+(?:your\s+)?(?:proposal|application)",
            r"open\s+call",
            r"accepting\s+(?:applications?|proposals?)",
            r"letter\s+of\s+intent",
            r"LOI\s+deadline",
        ]
        if not any(re.search(p, lower_text) for p in open_patterns):
            self.logger.debug(f"No open call signals for '{program_name}'")
            return None

        slug = url.rstrip("/").split("/")[-1]
        title = self._extract_title(soup) or program_name
        description = self._extract_description(soup)
        deadline = self._extract_deadline(text)
        funding = self._extract_funding(text)

        return Opportunity(
            id=f"WL-{slug}",
            source=Source.WELLCOME_LEAP,
            url=url,
            title=f"Wellcome Leap: {title}",
            description=description[:5000],
            agency="Wellcome Leap",
            activity_type=ActivityType.GRANT,
            deadline=deadline,
            award_ceiling=funding,
            eligibility_text=self._extract_eligibility(text),
            raw_data={"program": program_name, "url": url},
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
        for selector in ["article", "main", ".content", "#content"]:
            content = soup.select_one(selector)
            if content:
                text = content.get_text(separator=" ", strip=True)
                if len(text) > 100:
                    return re.sub(r"\s+", " ", text)
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            return meta["content"].strip()
        return ""

    def _extract_deadline(self, text: str) -> date | None:
        patterns = [
            r"(?:deadline|due|closes?|submit\s+by)[:\s]*(\w+\s+\d{1,2},?\s+\d{4})",
            r"(?:LOI|letter\s+of\s+intent)[:\s]*.*?(\w+\s+\d{1,2},?\s+\d{4})",
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                parsed = self._parse_date_str(match)
                if parsed and parsed > date.today():
                    return parsed
        return None

    def _extract_funding(self, text: str) -> int | None:
        amounts = []
        for match in re.finditer(
            r"\$\s*([\d,]+(?:\.\d+)?)\s*([KMBkmb](?:illion)?)?", text
        ):
            num_str = match.group(1).replace(",", "")
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
            r"(?:eligib\w+|who\s+(?:can|may|should)\s+apply)[:\s]*([^.]{20,200}\.)",
            text, re.IGNORECASE,
        )
        return " ".join(matches[:2]).strip()

    def _parse_date_str(self, date_str: str) -> date | None:
        clean = date_str.strip().replace(",", "")
        for fmt in ("%B %d %Y", "%b %d %Y"):
            try:
                return datetime.strptime(clean, fmt).date()
            except ValueError:
                continue
        return None
