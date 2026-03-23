from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from enum import Enum
from typing import Optional


class Source(str, Enum):
    NIH = "NIH Guide"
    GRANTS_GOV = "Grants.gov"
    EU_PORTAL = "EU Funding Portal"
    SBIR = "SBIR/STTR"
    GRAND_CHALLENGES = "Grand Challenges"
    INNOVATION_FUND_DK = "Innovation Fund Denmark"
    WELLCOME_LEAP = "Wellcome Leap"


class ActivityType(str, Enum):
    RFA = "RFA"
    PA = "PA"
    PAR = "PAR"
    NOT = "NOT"
    OTA = "OTA"
    GRANT = "Grant"
    CONTRACT = "Contract"
    COOPERATIVE = "Cooperative Agreement"
    OTHER = "Other"


@dataclass
class TopicScore:
    topic_name: str
    keyword_hits: list[str]
    score: float


@dataclass
class Opportunity:
    # Identity
    id: str
    source: Source
    url: str

    # Core fields
    title: str
    description: str
    agency: str
    activity_type: ActivityType

    # Dates
    posted_date: Optional[date] = None
    deadline: Optional[date] = None
    close_date_explanation: str = ""

    # Funding
    award_ceiling: Optional[int] = None
    award_floor: Optional[int] = None
    expected_awards: Optional[int] = None
    currency: str = "USD"

    # Eligibility
    startup_eligible: bool = False
    consortium_eligible: bool = False
    eligibility_text: str = ""

    # Scoring
    keyword_score: float = 0.0
    semantic_score: Optional[float] = None
    combined_score: float = 0.0
    topic_scores: list[TopicScore] = field(default_factory=list)
    matched_topics: list[str] = field(default_factory=list)
    high_priority: bool = False

    # Metadata
    fetched_at: datetime = field(default_factory=datetime.utcnow)
    raw_data: dict = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["source"] = self.source.value
        d["activity_type"] = self.activity_type.value
        for k in ("posted_date", "deadline"):
            if d[k]:
                d[k] = d[k].isoformat()
        d["fetched_at"] = self.fetched_at.isoformat()
        d.pop("raw_data", None)
        return d
