from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from enum import Enum
from typing import Any


ALLOWED_SECTIONS: tuple[str, ...] = (
    "3.1 根土复合体结构异质性及连通性表征",
    "3.2 根系调控下坡面多路径水分传输过程",
    "3.3 坡面壤中流事件响应与演化过程",
    "3.4 结构–路径耦合的壤中流产流模型优化",
)


class Slot(str, Enum):
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"


@dataclass(slots=True)
class Paper:
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    journal: str = ""
    doi: str = ""
    url: str = ""
    abstract: str = ""
    keywords: list[str] = field(default_factory=list)
    published: date | None = None
    cited_by: int = 0
    influential_citations: int = 0
    work_type: str = "article"
    sources: list[str] = field(default_factory=list)
    oa_pdf_url: str = ""
    score: float = 0.0


@dataclass(slots=True)
class EnrichedPaper(Paper):
    summary_zh: str = ""
    why_read: str = ""
    dissertation_section: str = ALLOWED_SECTIONS[0]
    priority: int = 3
    endnote_group: str = "根土复合体"

    def __post_init__(self) -> None:
        if self.dissertation_section not in ALLOWED_SECTIONS:
            raise ValueError("dissertation_section must be one of the allowed sections")
        if not 1 <= self.priority <= 5:
            raise ValueError("priority must be an integer from 1 to 5")
        if not self.keywords or not all(isinstance(value, str) and value.strip() for value in self.keywords):
            raise ValueError("keywords must contain non-empty strings")

    @classmethod
    def from_paper(
        cls,
        paper: Paper,
        *,
        summary_zh: str,
        why_read: str,
        dissertation_section: str,
        priority: int,
        keywords: list[str],
        endnote_group: str,
    ) -> EnrichedPaper:
        values = asdict(paper)
        values.update(
            summary_zh=summary_zh.strip(),
            why_read=why_read.strip(),
            dissertation_section=dissertation_section,
            priority=priority,
            keywords=[value.strip() for value in keywords if value.strip()],
            endnote_group=endnote_group.strip(),
        )
        return cls(**values)


@dataclass(slots=True)
class Delivery:
    key: str
    delivered_on: date
    slot: Slot

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Delivery:
        return cls(
            key=str(value["key"]),
            delivered_on=date.fromisoformat(str(value["date"])),
            slot=Slot(str(value["slot"])),
        )

    def to_dict(self) -> dict[str, str]:
        return {"key": self.key, "date": self.delivered_on.isoformat(), "slot": self.slot.value}


@dataclass(slots=True)
class RecommendationRecord:
    first_recommended: date
    last_recommended: date
    count: int = 1

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RecommendationRecord:
        return cls(
            first_recommended=date.fromisoformat(str(value["first_recommended"])),
            last_recommended=date.fromisoformat(str(value["last_recommended"])),
            count=int(value.get("count", 1)),
        )

    def to_dict(self) -> dict[str, str | int]:
        return {
            "first_recommended": self.first_recommended.isoformat(),
            "last_recommended": self.last_recommended.isoformat(),
            "count": self.count,
        }


@dataclass(slots=True)
class History:
    ever_recommended: dict[str, RecommendationRecord] = field(default_factory=dict)
    deliveries: list[Delivery] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> History:
        return cls(
            ever_recommended={
                str(key): RecommendationRecord.from_dict(record)
                for key, record in value.get("ever_recommended", {}).items()
            },
            deliveries=[Delivery.from_dict(item) for item in value.get("deliveries", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "ever_recommended": {
                key: record.to_dict() for key, record in sorted(self.ever_recommended.items())
            },
            "deliveries": [item.to_dict() for item in self.deliveries],
        }

