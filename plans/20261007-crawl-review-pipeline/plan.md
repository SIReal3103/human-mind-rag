# Crawl → human approval → evidence

Status: implemented; live paid-provider validation pending a configured BTC key (2026-10-07).

Validation: [report](reports/validation.md).

- Add persistent bounded jobs for upstream discovery/crawl; import originals and parsed assessment into pending review, never auto-approve by model score.
- Build isolated upstream runs from eligible approved revisions only. Keep original crawl artifacts separate from approved snapshots. Reject stale indexes after withdrawal/revision or effective-date changes.
- Add crawl/build/evidence UI and API, explicit provider selection, no key fallback or secret logs.
- Validate real offline pipeline contracts, approval/withdrawal boundaries, job recovery, and browser UI. Live paid embeddings require a configured key; do not claim unexecuted network validation.

Acceptance: pending/rejected/withdrawn documents never reach served evidence; existing review remains functional; crawl failures and partial imports are visible. All outputs stay in local data storage.
