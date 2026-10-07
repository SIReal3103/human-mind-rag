# Validation — 2026-10-07

Implemented persistent crawl/build jobs and an approved-only snapshot bridge to pinned scope-data-bot. Every imported source requires human approval. Pending queue orders lower extraction scores first; no probability threshold or automatic factual verification is claimed.

## Executed

- Real live crawl using explicit https://example.com/ in isolated temporary data: 1 source fetched/parsed by upstream, imported pending into Human Mind, no import errors. No user corpus or keys modified.
- Real DuckDuckGo discovery for Bình Phước culture/tourism scope: 0 sources returned. This is a source-discovery limitation, not successful corpus collection. UI offers explicit source URLs and reports no-documents honestly.
- Real upstream snapshot/trace/chunker test, with raw source integrity and human-approved revision carried into evidence metadata. No synthetic embedding vectors.
- Approval/withdrawal/currentness gate, empty extraction blocker, connector datasets pending, PDF MIME, interrupted jobs, failed snapshot preparation, CSRF and public-network boundary tests.
- Browser: pipeline page displays scope/collection/optional URLs/page bounds/provider, start/index/queue controls and job list. BTC stays default; no provider fallback.

## Remaining live validation

No BTC key is configured in the reviewed local settings. Paid embedding/index/retrieval calls were not executed. Worker implements the BTC embedding contract documented at https://docs.thucchien.ai/docs/round-2/user-guide/embeddings (checked 2026-10-07), validates each actual response, and fails closed. OpenAI provider is explicit opt-in, using the existing upstream endpoint/adapter contract; its paid calls were also not executed.

## Review resolutions

Independent read-only review identified MIME loss, omitted connector series, fabricated empty `[]` text, and running jobs left after snapshot failure. All four were fixed. Originals are copied/hashed into approved snapshots; unchanged PDF page locators are retained, and crawl provenance is saved atomically with document creation. Crawl transport reuses public-IP DNS pinning and preserves upstream robots checks.

## Operational limits

Single local server/process; one crawl/build at a time, 30-minute worker deadline, manual refresh. No automatic restart/retry. Query endpoint rechecks approved revisions and current effective day before and after retrieval. Consumers bypassing this endpoint and reading historic exported artifacts must handle revocation themselves. Crawling remains bounded and does not bypass robots, login, CAPTCHA or JS requirements.
