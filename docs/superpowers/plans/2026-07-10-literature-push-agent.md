# Literature Push Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deploy a Python 3.12 GitHub Actions agent that retrieves, ranks, summarizes, exports, and emails research literature three times daily while maintaining durable recommendation history.

**Architecture:** A single slot-aware CLI orchestrates independent academic-source adapters, deterministic deduplication/ranking/history rules, optional OpenAI JSON enrichment with local fallback, standards-compliant exporters, OA PDF handling, and Gmail SMTP delivery. Components communicate through typed dataclasses and tolerate failure at source and per-document boundaries.

**Tech Stack:** Python 3.12, requests, OpenAI Python SDK, pytest, ruff, PyYAML, GitHub Actions, Gmail SMTP SSL.

## Global Constraints

- Python version is exactly 3.12 in GitHub Actions.
- Crossref and OpenAlex are always integrated; Semantic Scholar is best-effort.
- Every external HTTP call has explicit timeout, retry, and exception handling.
- Secrets are read only from environment variables.
- Each delivery selects 2–3 papers normally; `MAX_PAPERS` is a configurable hard cap.
- The seven-day limit is at most three deliveries per paper; detailed deliveries older than 30 days are pruned.
- Only explicitly open-access PDFs may be downloaded, without bypassing paywalls.
- The workflow runs at UTC 01:00, 06:30, and 11:30 and supports manual slot selection.

---

### Task 1: Project configuration and typed domain models

**Files:**
- Create: `src/__init__.py`
- Create: `src/config.py`
- Create: `src/models.py`
- Create: `requirements.txt`
- Create: `pyproject.toml`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Slot`, `Paper`, `EnrichedPaper`, `History`, `Delivery`, `Settings.from_env()`.
- Consumes: environment variables documented in the design.

- [ ] **Step 1: Write failing configuration/model tests**

```python
def test_settings_defaults(monkeypatch):
    monkeypatch.delenv("RECIPIENT_EMAIL", raising=False)
    settings = Settings.from_env()
    assert settings.recipient_email == "qxh.igsnrr@gmail.com"
    assert settings.max_papers == 5

def test_enriched_paper_rejects_invalid_priority():
    with pytest.raises(ValueError):
        EnrichedPaper.from_paper(sample_paper(), priority=6)
```

- [ ] **Step 2: Run tests and confirm missing-module failure**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL because `src.config` and `src.models` do not exist.

- [ ] **Step 3: Implement minimal typed settings and dataclasses**

```python
class Slot(str, Enum):
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"

@dataclass(slots=True)
class Settings:
    recipient_email: str = "qxh.igsnrr@gmail.com"
    max_papers: int = 5

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            recipient_email=os.getenv("RECIPIENT_EMAIL", "qxh.igsnrr@gmail.com"),
            max_papers=max(2, int(os.getenv("MAX_PAPERS", "5"))),
        )
```

- [ ] **Step 4: Run tests until green**

Run: `python -m pytest tests/test_config.py -v`
Expected: all configuration/model tests PASS.

### Task 2: Deterministic deduplication and history controls

**Files:**
- Create: `src/dedup.py`
- Create: `src/history.py`
- Test: `tests/test_dedup.py`
- Test: `tests/test_history.py`
- Create: `data/history.json`

**Interfaces:**
- Consumes: `Paper`, `History`, `Delivery`.
- Produces: `normalize_doi(value: str) -> str`, `normalize_title(value: str) -> str`, `paper_key(paper: Paper) -> str`, `deduplicate(papers: list[Paper]) -> list[Paper]`, `load_history(path: Path) -> History`, `save_history(path: Path, history: History) -> None`, `eligible(paper: Paper, history: History, today: date) -> bool`, `record_delivery(history: History, papers: Sequence[Paper], slot: Slot, delivered_at: datetime) -> None`.

- [ ] **Step 1: Write failing deduplication/history tests**

```python
def test_deduplicates_doi_variants_and_merges_metadata():
    papers = [paper(doi="https://doi.org/10.1/ABC", abstract=""), paper(doi="10.1/abc", abstract="rich")]
    result = deduplicate(papers)
    assert len(result) == 1
    assert result[0].abstract == "rich"

def test_rejects_fourth_delivery_within_seven_days():
    history = history_with_deliveries("doi:10.1/a", ["2026-07-04", "2026-07-06", "2026-07-09"])
    assert not eligible(paper(doi="10.1/a"), history, date(2026, 7, 10))
```

- [ ] **Step 2: Verify failures**

Run: `python -m pytest tests/test_dedup.py tests/test_history.py -v`
Expected: FAIL because functions are missing.

- [ ] **Step 3: Implement DOI/title keys, merge, atomic state, and pruning**

```python
def paper_key(paper: Paper) -> str:
    doi = normalize_doi(paper.doi)
    return f"doi:{doi}" if doi else f"title:{normalize_title(paper.title)}"

def eligible(paper: Paper, history: History, today: date) -> bool:
    cutoff = today - timedelta(days=6)
    recent = [d for d in history.deliveries if d.key == paper_key(paper) and cutoff <= d.date <= today]
    return len(recent) < 3 and not any(d.date == today for d in recent)
```

- [ ] **Step 4: Run tests until green**

Run: `python -m pytest tests/test_dedup.py tests/test_history.py -v`
Expected: all tests PASS.

### Task 3: Slot-specific local ranking

**Files:**
- Create: `src/ranking.py`
- Test: `tests/test_ranking.py`

**Interfaces:**
- Consumes: papers, slot, history, current date.
- Produces: `relevance_score(paper: Paper) -> float`, `rank_papers(papers: Sequence[Paper], slot: Slot, history: History, today: date) -> list[Paper]`.

- [ ] **Step 1: Write tests demonstrating all three strategies**

```python
def test_morning_prefers_recent_relevant_paper():
    recent = paper(title="Root soil preferential flow", published=date.today(), cited_by=1)
    old = paper(title="Root soil preferential flow", published=date(1990, 1, 1), cited_by=500)
    assert rank_papers([old, recent], Slot.MORNING, History(), date.today())[0] == recent

def test_afternoon_prefers_highly_cited_mechanism_paper():
    classic = paper(title="Root induced macropore flow mechanism", cited_by=900)
    new = paper(title="Root induced macropore flow mechanism", cited_by=1)
    assert rank_papers([new, classic], Slot.AFTERNOON, History(), date.today())[0] == classic

def test_evening_prefers_review_and_excludes_afternoon_delivery():
    review = paper(doi="10.1/review", title="Review of hillslope hydrology", work_type="review")
    article = paper(doi="10.1/article", title="Hillslope hydrology", work_type="article")
    history = history_with_delivery(review, Slot.AFTERNOON, date.today())
    assert rank_papers([review, article], Slot.EVENING, history, date.today()) == [article]

def test_unseen_paper_beats_repeated_peer_when_other_scores_match():
    unseen = paper(doi="10.1/new", title="Preferential flow")
    seen = paper(doi="10.1/seen", title="Preferential flow")
    history = history_with_delivery(seen, Slot.MORNING, date.today() - timedelta(days=2))
    assert rank_papers([seen, unseen], Slot.AFTERNOON, history, date.today())[0] == unseen
```

- [ ] **Step 2: Verify tests fail for missing ranking**

Run: `python -m pytest tests/test_ranking.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement explicit weighted scoring**

```python
def rank_papers(papers: Sequence[Paper], slot: Slot, history: History, today: date) -> list[Paper]:
    eligible_papers = [p for p in papers if eligible(p, history, today)]
    return sorted(eligible_papers, key=lambda p: score_paper(p, slot, history, today), reverse=True)
```

- [ ] **Step 4: Run tests until green**

Run: `python -m pytest tests/test_ranking.py -v`
Expected: all tests PASS.

### Task 4: Resilient academic source adapters

**Files:**
- Create: `src/fetchers/__init__.py`
- Create: `src/fetchers/base.py`
- Create: `src/fetchers/crossref.py`
- Create: `src/fetchers/openalex.py`
- Create: `src/fetchers/semantic_scholar.py`
- Test: `tests/test_fetchers.py`

**Interfaces:**
- Produces: `build_session() -> requests.Session`; each fetcher exposes `fetch(slot: Slot, settings: Settings, now: date) -> list[Paper]`.
- OpenAlex maps `best_oa_location.pdf_url` to `Paper.oa_pdf_url` only when OA is true.

- [ ] **Step 1: Write mapping and failure-isolation tests with fake responses**

```python
def test_crossref_maps_doi_authors_and_date(fake_session):
    fake_session.json_data = {"message": {"items": [{"DOI": "10.1/a", "title": ["A"], "author": [{"given": "Ada", "family": "Lovelace"}], "published": {"date-parts": [[2026, 7, 1]]}}]}}
    result = CrossrefFetcher(fake_session).fetch(Slot.MORNING, settings(), date(2026, 7, 10))
    assert (result[0].doi, result[0].authors, result[0].published) == ("10.1/a", ["Ada Lovelace"], date(2026, 7, 1))

def test_openalex_maps_citations_type_and_oa_pdf(fake_session):
    fake_session.json_data = {"results": [{"title": "A", "cited_by_count": 10, "type": "review", "open_access": {"is_oa": True}, "best_oa_location": {"pdf_url": "https://example.org/a.pdf"}}]}
    result = OpenAlexFetcher(fake_session).fetch(Slot.EVENING, settings(), date(2026, 7, 10))
    assert (result[0].cited_by, result[0].work_type, result[0].oa_pdf_url) == (10, "review", "https://example.org/a.pdf")

def test_semantic_scholar_timeout_returns_no_results(caplog):
    session = FailingSession(requests.Timeout("slow"))
    assert SemanticScholarFetcher(session).fetch(Slot.AFTERNOON, settings(), date.today()) == []
    assert "Semantic Scholar" in caplog.text
```

- [ ] **Step 2: Verify failures**

Run: `python -m pytest tests/test_fetchers.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement retry sessions, timeouts, query windows, and parsers**

```python
retry = Retry(total=3, backoff_factor=0.8, status_forcelist=(429, 500, 502, 503, 504))
session.mount("https://", HTTPAdapter(max_retries=retry))
response = session.get(url, params=params, timeout=settings.http_timeout)
response.raise_for_status()
```

- [ ] **Step 4: Run tests until green**

Run: `python -m pytest tests/test_fetchers.py -v`
Expected: all tests PASS.

### Task 5: OpenAI structured enrichment with local fallback

**Files:**
- Create: `src/ai_enrichment.py`
- Test: `tests/test_ai_enrichment.py`

**Interfaces:**
- Produces: `validate_payload(payload: object, candidates: Sequence[Paper]) -> list[EnrichedPaper]`, `fallback_enrich(paper: Paper) -> EnrichedPaper`, `enrich_and_select(candidates: Sequence[Paper], settings: Settings, client: object | None = None) -> list[EnrichedPaper]`.
- Consumes: an injected OpenAI-compatible client so tests require no network.

- [ ] **Step 1: Write tests for valid JSON, one retry, identity checking, and fallback**

```python
def test_invalid_json_is_retried_once():
    client = FakeClient(["not json", valid_payload()])
    assert enrich_and_select([paper()], settings(), client)[0].title == paper().title
    assert client.calls == 2

def test_second_invalid_response_uses_local_fallback():
    client = FakeClient(["bad", "still bad"])
    result = enrich_and_select([paper()], settings(), client)
    assert result[0].summary_zh and client.calls == 2

def test_model_cannot_introduce_unknown_paper():
    with pytest.raises(ValueError, match="candidate"):
        validate_payload(payload(title="Invented", doi="10.1/fake"), [paper()])

def test_chapter_and_priority_are_strictly_validated():
    with pytest.raises(ValueError):
        validate_payload(payload(priority=9, dissertation_section="invalid"), [paper()])
```

- [ ] **Step 2: Verify failures**

Run: `python -m pytest tests/test_ai_enrichment.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement schema prompt, parsing/validation loop, and deterministic fallback**

```python
for attempt in range(2):
    try:
        return parse_and_validate(call_model(client, prompt), candidates)
    except (ValueError, json.JSONDecodeError):
        logger.warning("OpenAI structured output attempt %s failed", attempt + 1)
return [fallback_enrich(paper) for paper in candidates[:target_count]]
```

- [ ] **Step 4: Run tests until green**

Run: `python -m pytest tests/test_ai_enrichment.py -v`
Expected: all tests PASS.

### Task 6: HTML, RIS, CSV, BibTeX, and OA PDF exporters

**Files:**
- Create: `src/exporters.py`
- Test: `tests/test_exporters.py`

**Interfaces:**
- Produces: `render_html`, `write_ris`, `write_csv`, `write_bibtex`, `download_oa_pdfs`.

- [ ] **Step 1: Write exporter contract tests**

```python
def test_ris_contains_required_fields_and_note(tmp_path):
    text = write_ris([enriched_paper()], tmp_path / "papers.ris").read_text(encoding="utf-8")
    for tag in ("TY  -", "TI  -", "AU  -", "PY  -", "JO  -", "DO  -", "UR  -", "AB  -", "KW  -", "N1  -", "ER  -"):
        assert tag in text

def test_csv_has_utf8_bom_and_exact_column_order(tmp_path):
    path = write_csv([enriched_paper()], tmp_path / "papers.csv")
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert raw.decode("utf-8-sig").splitlines()[0].split(",") == CSV_FIELDS

def test_bibtex_escapes_values_and_uses_stable_key(tmp_path):
    text = write_bibtex([enriched_paper(title="Root & soil")], tmp_path / "papers.bib").read_text(encoding="utf-8")
    assert "@article{" in text and "Root \\& soil" in text

def test_html_escapes_metadata_and_renders_five_star_priority():
    text = render_html([enriched_paper(title="Root < Soil", priority=4)], Slot.MORNING, date.today())
    assert "Root &lt; Soil" in text and "★★★★☆" in text
```

- [ ] **Step 2: Verify failures**

Run: `python -m pytest tests/test_exporters.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement deterministic serializers and bounded streaming PDF downloads**

```python
with path.open("w", encoding="utf-8-sig", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
    writer.writeheader()
    writer.writerows(rows)
```

- [ ] **Step 4: Run tests until green**

Run: `python -m pytest tests/test_exporters.py -v`
Expected: all tests PASS.

### Task 7: SMTP delivery and CLI orchestration

**Files:**
- Create: `src/mailer.py`
- Create: `src/main.py`
- Test: `tests/test_mailer.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Produces: `build_message`, `send_email`, `run(slot, settings) -> int`, and CLI `main() -> int`.
- History is updated only after `send_email` returns successfully.

- [ ] **Step 1: Write tests for subjects, credentials, failure isolation, and transaction order**

```python
def test_missing_gmail_credentials_has_actionable_error():
    with pytest.raises(ConfigurationError, match="GMAIL_ADDRESS.*GMAIL_APP_PASSWORD"):
        send_email(settings(gmail_address="", gmail_app_password=""), message())

def test_history_is_not_updated_when_smtp_fails(tmp_path):
    result = run(Slot.MORNING, settings(tmp_path), dependencies(smtp_error=RuntimeError("smtp")))
    assert result != 0 and load_history(tmp_path / "history.json").deliveries == []

def test_history_is_updated_after_smtp_success(tmp_path):
    assert run(Slot.MORNING, settings(tmp_path), dependencies()) == 0
    assert len(load_history(tmp_path / "history.json").deliveries) == 3

def test_one_fetcher_failure_does_not_stop_other_sources(tmp_path):
    deps = dependencies(fetchers=[FailingFetcher(), StaticFetcher([paper()])])
    assert run(Slot.MORNING, settings(tmp_path), deps) == 0
```

- [ ] **Step 2: Verify failures**

Run: `python -m pytest tests/test_mailer.py tests/test_main.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement MIME attachments, SMTP SSL, orchestration, logs, and exit codes**

```python
with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=settings.smtp_timeout) as smtp:
    smtp.login(settings.gmail_address, settings.gmail_app_password)
    smtp.send_message(message)
```

- [ ] **Step 4: Run tests until green**

Run: `python -m pytest tests/test_mailer.py tests/test_main.py -v`
Expected: all tests PASS.

### Task 8: GitHub Actions, documentation, and full verification

**Files:**
- Create: `.github/workflows/literature.yml`
- Replace: `README.md`
- Create: `.gitignore`
- Test: `tests/test_workflow.py`

**Interfaces:**
- Workflow produces artifacts under `output/` and updates only `data/history.json`.

- [ ] **Step 1: Write workflow structure tests**

```python
def test_workflow_has_all_crons_and_manual_slots():
    workflow = load_workflow()
    assert {item["cron"] for item in workflow["on"]["schedule"]} == {"0 1 * * *", "30 6 * * *", "30 11 * * *"}
    assert workflow["on"]["workflow_dispatch"]["inputs"]["slot"]["options"] == ["morning", "afternoon", "evening"]

def test_workflow_has_contents_write_timeout_tests_artifacts_and_history_commit():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "contents: write" in text and "timeout-minutes:" in text
    assert "pytest" in text and "upload-artifact" in text and "data/history.json" in text
```

- [ ] **Step 2: Verify tests fail**

Run: `python -m pytest tests/test_workflow.py -v`
Expected: FAIL because workflow is absent.

- [ ] **Step 3: Implement workflow, deployment guide, and troubleshooting guide**

```yaml
on:
  schedule:
    - cron: "0 1 * * *"
    - cron: "30 6 * * *"
    - cron: "30 11 * * *"
  workflow_dispatch:
    inputs:
      slot:
        type: choice
        options: [morning, afternoon, evening]
```

- [ ] **Step 4: Run complete verification**

Run: `python -m pytest -v`
Expected: all tests PASS.

Run: `python -m ruff check .`
Expected: exit 0 with no diagnostics.

Run: `python -m compileall -q src tests`
Expected: exit 0.

Run: `python -c "import pathlib,yaml; yaml.safe_load(pathlib.Path('.github/workflows/literature.yml').read_text(encoding='utf-8'))"`
Expected: exit 0.

- [ ] **Step 5: Commit and push main**

```bash
git add .
git commit -m "feat: build automated literature push agent"
git push origin main
```

- [ ] **Step 6: Trigger and inspect morning workflow**

```bash
gh workflow run literature.yml --ref main -f slot=morning
gh run list --workflow literature.yml --limit 1
```

Expected: the run starts; with missing Secrets it fails at the explicit credential preflight and retains logs/artifacts.
