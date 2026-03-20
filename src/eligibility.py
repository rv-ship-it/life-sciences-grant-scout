import re

STARTUP_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r'\bSMEs?\b',
        r'\bsmall\s+business(?:es)?\b',
        r'\bstart-?ups?\b',
        r'\bsmall\s+and\s+medium\b',
        r'\bSBIR\b',
        r'\bSTTR\b',
        r'\bseed\s+funding\b',
        r'\bearly[- ]stage\s+compan(?:y|ies)\b',
        r'\bsmall\s+compan(?:y|ies)\b',
        r'\bnew\s+investigator\b',
        r'\bemerging\s+innovator\b',
    ]
]

CONSORTIUM_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r'\bconsortium\b',
        r'\bcollaborative\b',
        r'\bpartnership\b',
        r'\bmulti[- ]institutional\b',
        r'\bjoint\s+proposal\b',
        r'\bcollaborative\s+agreement\b',
        r'\bteaming\b',
        r'\bmulti[- ]site\b',
    ]
]


def parse_eligibility(opp):
    searchable = f"{opp.title} {opp.description} {opp.eligibility_text}"

    if not opp.startup_eligible:
        opp.startup_eligible = any(p.search(searchable) for p in STARTUP_PATTERNS)

    if not opp.consortium_eligible:
        opp.consortium_eligible = any(p.search(searchable) for p in CONSORTIUM_PATTERNS)

    return opp
