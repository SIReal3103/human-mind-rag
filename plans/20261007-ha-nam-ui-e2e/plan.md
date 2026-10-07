# Hà Nam UI end-to-end validation

Status: completed for bounded UI end-to-end validation. Baseline: ae8b28c, branch fix/ha-nam-ui-e2e. Date: 2026-10-07 (Asia/Ho_Chi_Minh).

## Scope and acceptance

Use the actual local UI to collect public culture and economy sources for Hà Nam from 2016 through 2026-10-07, review originals, approve usable documents, build an index, retrieve and export evidence. Inspect partial coverage and errors honestly. Preserve the original repository and local data. No automatic commit or push.

## Phases

1. [Environment and baseline](phase-01-ui-validation.md): clone latest main, start UI, inspect configuration, run existing tests.
2. Exercise crawl, originals/review, index and evidence through UI; save local evidence.
3. Reproduce and fix concrete defects, add focused regressions, rerun affected UI flows.
4. Review diff, run required checks, document outcomes and limitations.

Dependencies: selected provider key configured in UI for paid model/search/embedding calls; source accessibility. Start with at most 5 sources / 12 pages / depth 1 per crawl. No load or broad security audit is requested.

Evidence: local-evidence/ha-nam-ui-20261007/ (ignored). QA result must distinguish working UI/pipeline from factual accuracy and year coverage.

## Outcome

- Used the actual UI for crawl, source review, decisions, index, two evidence queries and JSON downloads. The final crawl imported five sources: three approved and two rejected. Four earlier footer-only extractions remain rejected; separate intake/lifecycle tests remain rejected or withdrawn.
- The approved collection `ha-nam-van-hoa-kinh-te-2016-2026` built 21 embedding chunks. Each evidence query returned four excerpts. All eight returned citation entries matched reviewed text, character locators, source URLs and original SHA-256; the downloaded corpus contains exactly the three approved documents.
- Fixed grounded search parsing/prompt separation, HTML article recovery, retry configuration loss, source-error diagnostics, manual replacement of partial text, empty-index status, stale search results and intake form defaults.
- Verification: 129 pytest tests passed; unittest ran 102 tests, OK with one optional Docling smoke skipped. Ruff lint/format, JavaScript syntax and Git diff checks passed. Independent backend and parser/UI reviews found no actionable regression.
- This is a bounded trial, not a complete annual dataset. Sources cover historical 2016–2020 economics and 2023–2024 culture/tourism references; missing years and metrics remain missing. Evidence excerpts are not synthesized or independently verified statistical answers. OCR, load testing, comprehensive security review and an independent AI holdout were not run.

Local handoff: `local-evidence/ha-nam-ui-20261007/qa-report.html`, `qa-report-data.json`, `live-final.json`, `approved-rag-ui-download.json` and `evidence-ui-download.json`. These artifacts and credentials are not committed.
