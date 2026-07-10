from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date

from src.dedup import paper_key
from src.history import eligible
from src.models import History, Paper, Slot

CONCEPTS: tuple[tuple[str, ...], ...] = (
    ("root soil", "root-soil", "root–soil", "根土"),
    ("preferential flow", "优先流"),
    ("macropore", "大孔隙"),
    ("subsurface stormflow", "stormflow", "壤中流"),
    ("interflow",),
    ("hillslope hydrology", "坡面水文"),
    ("ecohydrology", "生态水文"),
    ("hydrological connectivity", "水文连通"),
    ("runoff generation", "产流"),
    ("soil water pathway", "water pathways", "水分路径"),
    ("root architecture", "根系构型"),
    ("soil hydraulic", "土壤水力"),
    ("root induced soil structure", "root-induced soil structure"),
    ("hengduan", "横断山"),
    ("mountain hazard", "山地灾害"),
)

MECHANISM_TERMS = ("mechanism", "process", "pathway", "connectivity", "hydraulic", "机制")
METHOD_TERMS = ("review", "meta-analysis", "method", "model", "framework", "综述", "方法", "模型")


def relevance_score(paper: Paper) -> float:
    title = paper.title.casefold()
    body = f"{paper.abstract} {' '.join(paper.keywords)}".casefold()
    score = 0.0
    for variants in CONCEPTS:
        if any(value in title for value in variants):
            score += 3.0
        elif any(value in body for value in variants):
            score += 1.5
    return score


def _freshness(paper: Paper, today: date) -> float:
    if paper.published is None:
        return 0.0
    age = (today - paper.published).days
    if age < 0:
        return 1.0
    if age <= 7:
        return 30.0
    if age <= 30:
        return 25.0
    if age <= 45:
        return 20.0
    if age <= 90:
        return 8.0
    return 0.0


def _history_adjustment(paper: Paper, history: History) -> float:
    record = history.ever_recommended.get(paper_key(paper))
    return 12.0 if record is None else -min(18.0, record.count * 5.0)


def score_paper(paper: Paper, slot: Slot, history: History, today: date) -> float:
    relevance = relevance_score(paper)
    citations = math.log1p(max(0, paper.cited_by))
    history_score = _history_adjustment(paper, history)
    text = f"{paper.title} {paper.abstract} {paper.work_type}".casefold()

    if slot is Slot.MORNING:
        return relevance * 3.0 + _freshness(paper, today) + citations * 0.6 + history_score
    if slot is Slot.AFTERNOON:
        mechanism = 10.0 if any(term in text for term in MECHANISM_TERMS) else 0.0
        return relevance * 3.5 + citations * 5.0 + mechanism + history_score

    special_type = 0.0
    if paper.work_type.casefold() in {"review", "systematic-review", "meta-analysis"}:
        special_type += 35.0
    if any(term in text for term in METHOD_TERMS):
        special_type += 14.0
    overlooked = max(0.0, 12.0 - citations)
    return relevance * 3.0 + citations * 1.5 + special_type + overlooked + history_score


def rank_papers(
    papers: Sequence[Paper],
    slot: Slot,
    history: History,
    today: date,
) -> list[Paper]:
    ranked: list[tuple[float, Paper]] = []
    for paper in papers:
        if not paper.title.strip() or not eligible(paper, history, today):
            continue
        score = score_paper(paper, slot, history, today)
        paper.score = round(score, 4)
        ranked.append((score, paper))
    ranked.sort(key=lambda item: (item[0], item[1].cited_by, item[1].title), reverse=True)
    return [paper for _, paper in ranked]
