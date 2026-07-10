from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from typing import Any

from openai import OpenAI

from src.config import RESEARCH_TOPIC, Settings
from src.dedup import normalize_doi, normalize_title, paper_key
from src.models import ALLOWED_SECTIONS, EnrichedPaper, Paper


LOGGER = logging.getLogger(__name__)
CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["papers"],
    "properties": {
        "papers": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "title",
                    "authors",
                    "year",
                    "journal",
                    "doi",
                    "url",
                    "summary_zh",
                    "why_read",
                    "dissertation_section",
                    "priority",
                    "keywords",
                    "endnote_group",
                ],
                "properties": {
                    "title": {"type": "string"},
                    "authors": {"type": "array", "items": {"type": "string"}},
                    "year": {"type": ["integer", "null"]},
                    "journal": {"type": "string"},
                    "doi": {"type": "string"},
                    "url": {"type": "string"},
                    "summary_zh": {"type": "string"},
                    "why_read": {"type": "string"},
                    "dissertation_section": {"type": "string", "enum": list(ALLOWED_SECTIONS)},
                    "priority": {"type": "integer", "minimum": 1, "maximum": 5},
                    "keywords": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string"},
                    },
                    "endnote_group": {"type": "string"},
                },
            },
        }
    },
}


def _required_string(item: dict[str, Any], field: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _candidate_for(item: dict[str, Any], candidates: Sequence[Paper]) -> Paper:
    item_doi = normalize_doi(_required_string(item, "doi"))
    item_title = normalize_title(_required_string(item, "title"))
    for paper in candidates:
        candidate_doi = normalize_doi(paper.doi)
        if item_doi and candidate_doi and item_doi == candidate_doi:
            return paper
        if not item_doi and item_title == normalize_title(paper.title):
            return paper
    raise ValueError("Model returned a paper that is not in the candidate set")


def validate_payload(payload: object, candidates: Sequence[Paper]) -> list[EnrichedPaper]:
    if not isinstance(payload, dict) or not isinstance(payload.get("papers"), list):
        raise ValueError("OpenAI payload must contain a papers array")
    items = payload["papers"]
    if not 1 <= len(items) <= len(candidates):
        raise ValueError("OpenAI selected an invalid number of papers")

    result: list[EnrichedPaper] = []
    used: set[str] = set()
    for raw_item in items:
        if not isinstance(raw_item, dict):
            raise ValueError("Each selected paper must be an object")
        item: dict[str, Any] = raw_item
        paper = _candidate_for(item, candidates)
        key = paper_key(paper)
        if key in used:
            raise ValueError("OpenAI selected the same candidate more than once")
        used.add(key)

        authors = item.get("authors")
        if not isinstance(authors, list) or not all(isinstance(value, str) for value in authors):
            raise ValueError("authors must be a string array")
        year = item.get("year")
        if year is not None and type(year) is not int:
            raise ValueError("year must be an integer or null")
        for field in ("journal", "url"):
            if not isinstance(item.get(field), str):
                raise ValueError(f"{field} must be a string")
        priority = item.get("priority")
        if type(priority) is not int or not 1 <= priority <= 5:
            raise ValueError("priority must be an integer from 1 to 5")
        section = item.get("dissertation_section")
        if section not in ALLOWED_SECTIONS:
            raise ValueError("dissertation_section is invalid")
        keywords = item.get("keywords")
        if (
            not isinstance(keywords, list)
            or not keywords
            or not all(
                isinstance(value, str) and value.strip() and CJK_PATTERN.search(value)
                for value in keywords
            )
        ):
            raise ValueError("keywords must be a non-empty Chinese string array")
        result.append(
            EnrichedPaper.from_paper(
                paper,
                summary_zh=_required_string(item, "summary_zh"),
                why_read=_required_string(item, "why_read"),
                dissertation_section=str(section),
                priority=priority,
                keywords=[str(value) for value in keywords],
                endnote_group=_required_string(item, "endnote_group"),
            )
        )
    return result


def _section_for(paper: Paper) -> str:
    text = f"{paper.title} {paper.abstract}".casefold()
    if any(term in text for term in ("model", "modelling", "framework", "模型")):
        return ALLOWED_SECTIONS[3]
    if any(term in text for term in ("stormflow", "interflow", "runoff generation", "壤中流", "产流")):
        return ALLOWED_SECTIONS[2]
    if any(term in text for term in ("preferential", "macropore", "pathway", "优先流", "大孔隙")):
        return ALLOWED_SECTIONS[1]
    return ALLOWED_SECTIONS[0]


def _keywords_for(paper: Paper) -> list[str]:
    text = f"{paper.title} {paper.abstract}".casefold()
    mapping = (
        (("root", "根系"), "根土复合体"),
        (("preferential", "优先流"), "优先流"),
        (("macropore", "大孔隙"), "大孔隙流"),
        (("stormflow", "interflow", "壤中流"), "壤中流"),
        (("connectivity", "连通"), "水文连通性"),
        (("hydraulic", "水力"), "土壤水力性质"),
        (("model", "模型"), "水文模型"),
    )
    keywords = [label for needles, label in mapping if any(needle in text for needle in needles)]
    return keywords[:5] or ["坡面水文", "根土复合体"]


def fallback_enrich(paper: Paper) -> EnrichedPaper:
    section = _section_for(paper)
    priority = max(1, min(5, 3 + int(paper.score >= 35) + int(paper.score >= 60)))
    focus = "、".join(_keywords_for(paper)[:3])
    summary = (
        f"该研究围绕{focus}展开。当前为本地规则降级摘要，内容依据题名与公开元数据生成，"
        "阅读全文时请重点核对研究区、实验设计和因果机制。"
    )
    why_read = f"与“{RESEARCH_TOPIC}”中的结构—路径—产流关系相关，可作为{section[:3]}部分的参考。"
    group = {
        ALLOWED_SECTIONS[0]: "根土结构与连通性",
        ALLOWED_SECTIONS[1]: "坡面水分传输路径",
        ALLOWED_SECTIONS[2]: "壤中流事件响应",
        ALLOWED_SECTIONS[3]: "壤中流模型",
    }[section]
    return EnrichedPaper.from_paper(
        paper,
        summary_zh=summary,
        why_read=why_read,
        dissertation_section=section,
        priority=priority,
        keywords=_keywords_for(paper),
        endnote_group=group,
    )


def _prompt(candidates: Sequence[Paper], target_count: int) -> str:
    compact = [
        {
            "candidate_key": paper_key(paper),
            "title": paper.title,
            "authors": paper.authors,
            "year": paper.year,
            "journal": paper.journal,
            "doi": normalize_doi(paper.doi),
            "url": paper.url,
            "abstract": paper.abstract[:1800],
            "cited_by": paper.cited_by,
            "work_type": paper.work_type,
            "local_score": paper.score,
        }
        for paper in candidates
    ]
    return (
        f"你是自然地理与坡面水文学文献助手。博士课题：{RESEARCH_TOPIC}。"
        f"只能从候选中选择最值得阅读的 {target_count} 篇，不得虚构或修改身份信息。"
        "summary_zh 和 why_read 使用准确、审慎的中文；keywords 必须是中文数组；"
        "dissertation_section 必须使用给定枚举。候选如下：\n"
        + json.dumps(compact, ensure_ascii=False)
    )


def _call_model(client: Any, settings: Settings, prompt: str) -> str:
    response = client.responses.create(
        model=settings.openai_model,
        input=prompt,
        text={
            "format": {
                "type": "json_schema",
                "name": "literature_selection",
                "strict": True,
                "schema": OUTPUT_SCHEMA,
            }
        },
        timeout=settings.http_timeout[1],
    )
    output = getattr(response, "output_text", "")
    if not isinstance(output, str) or not output.strip():
        raise ValueError("OpenAI response did not contain output_text")
    return output


def enrich_and_select(
    candidates: Sequence[Paper],
    settings: Settings,
    client: Any | None = None,
) -> list[EnrichedPaper]:
    target_count = min(settings.delivery_count, len(candidates))
    selected_candidates = list(candidates[: max(target_count * 4, target_count)])
    if not selected_candidates:
        return []
    if client is None and not settings.openai_api_key:
        LOGGER.warning("OPENAI_API_KEY is not configured; using local enrichment fallback")
        return [fallback_enrich(paper) for paper in selected_candidates[:target_count]]
    model_client = client or OpenAI(api_key=settings.openai_api_key, timeout=settings.http_timeout[1])
    prompt = _prompt(selected_candidates, target_count)
    for attempt in range(2):
        try:
            payload = json.loads(_call_model(model_client, settings, prompt))
            enriched = validate_payload(payload, selected_candidates)
            return enriched[:target_count]
        except Exception as exc:  # OpenAI errors and validation failures share fallback behavior.
            LOGGER.warning("OpenAI enrichment attempt %d failed: %s", attempt + 1, exc)
    return [fallback_enrich(paper) for paper in selected_candidates[:target_count]]
