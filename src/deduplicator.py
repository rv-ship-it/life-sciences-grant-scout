import re
from difflib import SequenceMatcher


class Deduplicator:
    """Remove duplicate opportunities across sources.

    Three-pass strategy:
    1. Exact match on normalized URL.
    2. Exact match on grant number (NIH format).
    3. Fuzzy title match (SequenceMatcher >= threshold).
    Keeps entry with longer description on conflict.
    """

    def __init__(self, similarity_threshold: float = 0.85):
        self.threshold = similarity_threshold

    def _is_better(self, new_opp, existing) -> bool:
        """Decide if new_opp should replace existing during dedup.

        Prefers: longer description, then startup_eligible, then consortium_eligible.
        """
        if len(new_opp.description) > len(existing.description):
            return True
        if len(new_opp.description) == len(existing.description):
            if new_opp.startup_eligible and not existing.startup_eligible:
                return True
            if new_opp.consortium_eligible and not existing.consortium_eligible:
                return True
        return False

    def _merge_flags(self, kept, dropped):
        """Merge eligibility flags from dropped into kept entry."""
        if dropped.startup_eligible:
            kept.startup_eligible = True
        if dropped.consortium_eligible:
            kept.consortium_eligible = True

    def deduplicate(self, opportunities: list) -> list:
        seen_urls: dict[str, object] = {}
        seen_numbers: dict[str, object] = {}
        result: list = []

        for opp in opportunities:
            norm_url = opp.url.rstrip("/").lower()

            # Pass 1: URL dedup
            if norm_url in seen_urls:
                existing = seen_urls[norm_url]
                if self._is_better(opp, existing):
                    self._merge_flags(opp, existing)
                    result.remove(existing)
                    result.append(opp)
                    seen_urls[norm_url] = opp
                    grant_num = self._extract_grant_number(opp)
                    if grant_num:
                        seen_numbers[grant_num] = opp
                else:
                    self._merge_flags(existing, opp)
                continue

            # Pass 2: Grant number dedup
            grant_num = self._extract_grant_number(opp)
            if grant_num and grant_num in seen_numbers:
                existing = seen_numbers[grant_num]
                if self._is_better(opp, existing):
                    self._merge_flags(opp, existing)
                    result.remove(existing)
                    result.append(opp)
                    seen_numbers[grant_num] = opp
                    seen_urls[norm_url] = opp
                else:
                    self._merge_flags(existing, opp)
                continue

            # Pass 3: Fuzzy title match (with length pre-filter for speed)
            is_dup = False
            opp_title_lower = opp.title.lower()
            opp_title_len = len(opp_title_lower)
            for existing in result:
                existing_title_lower = existing.title.lower()
                len_ratio = min(opp_title_len, len(existing_title_lower)) / max(opp_title_len, len(existing_title_lower), 1)
                if len_ratio < self.threshold:
                    continue
                ratio = SequenceMatcher(
                    None, opp_title_lower, existing_title_lower
                ).ratio()
                if ratio >= self.threshold:
                    if self._is_better(opp, existing):
                        self._merge_flags(opp, existing)
                        result.remove(existing)
                        result.append(opp)
                        seen_urls[norm_url] = opp
                        if grant_num:
                            seen_numbers[grant_num] = opp
                    else:
                        self._merge_flags(existing, opp)
                    is_dup = True
                    break

            if not is_dup:
                result.append(opp)
                seen_urls[norm_url] = opp
                if grant_num:
                    seen_numbers[grant_num] = opp

        return result

    def _extract_grant_number(self, opp) -> str | None:
        patterns = [
            r"((?:RFA|PA|PAR|NOT|OTA)-\w{2,4}-\d{2}-\d{3})",
            r"(HRSA-\d{2}-\d{3})",
        ]
        text = f"{opp.title} {opp.id}"
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                return m.group(1).upper()
        return None
