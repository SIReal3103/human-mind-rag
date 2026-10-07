# UI workflow and opt-in automatic review

Status: complete. UI workflow verified on 2026-10-07.

- Reproduced: new-session UI silently resets selected external models/key group to missing BTC. Keep user selection; BTC remains first-use default.
- Add preflight missing-key message without creating a paid job; refresh stale local CSRF exactly once only for server-rejected requests.
- Opt-in auto-review policy: new revision, extraction score >=90, no warning/error, source web, valid original semantic assessment matching scope, not truncated. Does not assert factual correctness.
- Preserve approval provenance into search and index, retain ineligible pending documents, allow index while pending items remain.
- Live UI-only workflow budget: one public conceptual Cúc Phương scope, four pages/depth zero, external gpt-6-luna planner/check, Gemini 3.1 Flash Lite search/evidence, Gemini embedding 2. No independent semantic judge; test workflow contracts only. All live workflow mutations via CUA UI.
- Acceptance: crawl → auto-review → UI build → UI retrieval with actual evidence and trace; no API/direct DB bypass for live test.
- QA kit remote bf0640b2c73ec7abdb3a9aec0754c4fcbdf5bb8e lacks qa-report renderer referenced by skill. Use its documented report.py fallback; explicitly label contract/UI checks, not RAG semantic evaluation.

## Results

- Real UI run: 3 automatically approved documents → 10 indexed chunks → 4 evidence items → downloaded valid JSON.
- Fixed new-session key selection, stale CSRF, live-job ownership, approval provenance, direct evidence download with revocation checks.
- Validation: 103 tests + 30 subtests; after download change, 12 focused pipeline tests passed. Review completed without remaining blockers.
- [QA report](reports/ui-workflow-report.html), [machine-readable results](reports/ui-workflow-results.json), [UI screenshot](reports/ui-complete.png).
- BTC live and independent factual quality are not evaluated.
