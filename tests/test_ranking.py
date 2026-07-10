from __future__ import annotations

from datetime import date, timedelta

from src.dedup import paper_key
from src.models import Delivery, History, Paper, RecommendationRecord, Slot
from src.ranking import rank_papers, relevance_score

TODAY = date(2026, 7, 10)


def paper(
    *,
    doi: str,
    title: str = "Root soil preferential flow in hillslopes",
    published: date | None = None,
    cited_by: int = 0,
    work_type: str = "article",
) -> Paper:
    return Paper(
        title=title,
        doi=doi,
        published=published,
        year=published.year if published else None,
        cited_by=cited_by,
        work_type=work_type,
        abstract="Hydrological connectivity and subsurface stormflow through root macropores.",
    )


def test_relevance_rewards_multiple_research_concepts() -> None:
    relevant = paper(doi="10.1/relevant")
    irrelevant = paper(
        doi="10.1/irrelevant",
        title="Quantum computing for financial portfolios",
    )
    irrelevant.abstract = "Algorithms and market optimization."
    assert relevance_score(relevant) > relevance_score(irrelevant) + 5


def test_morning_prefers_recent_relevant_paper() -> None:
    recent = paper(doi="10.1/recent", published=TODAY - timedelta(days=3), cited_by=1)
    old = paper(doi="10.1/old", published=date(1990, 1, 1), cited_by=900)
    assert rank_papers([old, recent], Slot.MORNING, History(), TODAY)[0] == recent


def test_afternoon_prefers_highly_cited_mechanism_paper() -> None:
    classic = paper(
        doi="10.1/classic",
        title="Root induced macropore flow mechanism",
        published=date(1998, 1, 1),
        cited_by=900,
    )
    new = paper(
        doi="10.1/new",
        title="Root induced macropore flow mechanism",
        published=TODAY - timedelta(days=2),
        cited_by=1,
    )
    assert rank_papers([new, classic], Slot.AFTERNOON, History(), TODAY)[0] == classic


def test_evening_prefers_review_and_excludes_afternoon_delivery() -> None:
    delivered_review = paper(doi="10.1/review-a", work_type="review", cited_by=100)
    unseen_review = paper(doi="10.1/review-b", work_type="review", cited_by=10)
    article = paper(doi="10.1/article", work_type="article", cited_by=100)
    history = History(
        deliveries=[
            Delivery(paper_key(delivered_review), TODAY, Slot.AFTERNOON),
        ]
    )
    ranked = rank_papers(
        [delivered_review, article, unseen_review], Slot.EVENING, history, TODAY
    )
    assert delivered_review not in ranked
    assert ranked[0] == unseen_review


def test_unseen_paper_beats_repeated_peer_when_other_scores_match() -> None:
    unseen = paper(doi="10.1/unseen")
    seen = paper(doi="10.1/seen")
    history = History(
        ever_recommended={
            paper_key(seen): RecommendationRecord(
                first_recommended=TODAY - timedelta(days=10),
                last_recommended=TODAY - timedelta(days=2),
                count=2,
            )
        },
        deliveries=[
            Delivery(paper_key(seen), TODAY - timedelta(days=2), Slot.MORNING),
        ],
    )
    assert rank_papers([seen, unseen], Slot.AFTERNOON, history, TODAY)[0] == unseen


def test_fourth_delivery_within_seven_days_is_removed_before_scoring() -> None:
    repeated = paper(doi="10.1/repeated", cited_by=9999)
    key = paper_key(repeated)
    history = History(
        deliveries=[
            Delivery(key, TODAY - timedelta(days=6), Slot.MORNING),
            Delivery(key, TODAY - timedelta(days=4), Slot.AFTERNOON),
            Delivery(key, TODAY - timedelta(days=1), Slot.EVENING),
        ]
    )
    assert rank_papers([repeated], Slot.AFTERNOON, history, TODAY) == []
