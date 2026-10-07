# UI validation and defect repair

Read README.md, review_ui/README.md, .github/workflows/tests.yml and nearby implementation before edits.

Files: modify only modules with verified defects and their focused tests; update existing setup/workflow docs if behavior changes. Preserve public contracts. Reports remain in local-evidence/ha-nam-ui-20261007/.

| Group | Applies | Cases / tool | Command or action | Data / budget | Evidence | State |
|---|---|---|---|---|---|---|
| Setup | Yes | clone, dependencies, local server | ./run-ui.sh | isolated checkout/store | baseline logs, jobs-final.json | passed |
| UI/API | Yes | browser main and error flows | actual UI interaction | bounded public-source crawl | screenshots, live-final.json, downloads | passed for exercised flows |
| Unit/regression | Yes | pytest, unittest | repository CI commands | offline authored fixtures | final-pytest.log, final-unittest.log | 129 pytest pass; 102 unittest run, 1 skip |
| Lint/syntax | Yes | Ruff, node | CI commands | changed files, then repo | final-ruff.log, verification notes | passed |
| AI/data quality | Yes | source/scope/locator comparison | original vs parsed vs evidence | inspected public documents | originals, reviews, live-final.json | provenance passes; annual completeness not met |
| Latency/reliability | Limited | elapsed jobs, error states | actual UI jobs | same E2E requests | timestamps/trace | single-run timings only; no percentiles |
| Security/privacy | Limited | local secret handling and affected input boundaries | targeted review/tests | no external active scan | tests/review notes | targeted checks only; broad audit not run |
| Load / independent AI holdout | Out of scope | no benchmark | none | none | explicit limitation | not run |
| Multi-tenant / voice | Absent | no product feature | none | none | explicit limitation | N/A |

Validation: narrow regression first; then pytest, unittest, pip check, Ruff and JavaScript syntax as appropriate. Browser retest must check backend artifacts. No fixture/mocked model response counts as live crawl evidence. No claims of exhaustive 2016–present coverage.

Risks: search blocking, missing key/model entitlement, changed administrative scope, partial parsing/index. Keep originals and job history; preserve failures. Rollback: revert only task changes; retain local crawl records.
