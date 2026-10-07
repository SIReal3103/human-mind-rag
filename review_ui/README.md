# Scope Data Bot: human review UI

Bundled in this repository. Start `./run-ui.sh` from the repository root and open http://127.0.0.1:8765 . Python 3.12 or 3.14 and SQLite FTS5 are required. The launcher installs pinned UI dependencies once. It prefers Docling when its local runtime is installed; `DOCUMENT_PARSER=native ./run-ui.sh` selects lightweight parsing. Run `./setup-parser.sh` once for OCR/layout models; images and Office require Docling. No second clone, SCOPE_BOT_PATH or fixed external commit is needed. Engine source fingerprints are recorded in documents/jobs.

## Daily workflow

1. Configure provider keys in Settings. BTC uses its own key; External uses a key for each selected provider. No automatic provider fallback. OpenAI External defaults to gpt-4.1-mini and text-embedding-3-small. A model appearing in the catalog does not establish account access; actual calls may fail.
2. Create a new Crawl & RAG session, enter the scope and collection. Conceptual topics do not require invented geography, dates or a denominator. State these constraints when relevant. Source/page/depth limits bound discovery; no run guarantees complete coverage.
3. Crawl. OpenAI web search keeps query text separate from scope instructions and collects URLs from completed search-tool sources and citations. Downloaded originals and parser output are preserved even when assessment fails. Inspect per-stage errors and trace. Retry creates a new run using the current form settings, including any changed scope, key group, models or limits.
4. Review pending documents against originals. Approve, reject or correct text. Approval requires a reviewer label and acknowledgement of warnings. The document tab shows local review chunks; semantic index chunks are built separately from the approved parser structure. Text edits clear old coordinates/native parser evidence; originals and review history remain. To resolve partial extraction, save complete replacement text, compare it with the entire original and manually acknowledge the retained warnings before approval. Metadata-only edits or unchanged text keep the partial blocker; the replacement audit records the prior parser and partial state. Labels are not authenticated identities. Optional automatic approval is off by default and is a rule-based policy, not human review or factual verification.
5. Build an index from approved, currently effective documents in the collection. Pending/rejected/withdrawn documents are excluded. Tables, page/item coordinates, parser config and native Docling JSON survive unchanged documents. Parsed structure is retained in parser_evidence; large documents can consume disk space. A build is ready only with a `ready_partial` manifest and at least one semantic chunk. A `no_evidence` or empty build fails with a diagnostic and cannot serve evidence.
6. Get evidence for a question from the downstream chatbot. Query embedding stays compatible with the index; hybrid search and reranking return source-bound context, not a generated answer. No question is needed for ingestion.

An index is reusable across days if the currently eligible approved versions are unchanged. Expiry, newly effective versions, edits or withdrawal block stale indexes until rebuilt. Embedding cache is shared within the data store and keyed by provider/model/dimensions/exact input; it never reuses review decisions. Exported JSON cannot be remotely withdrawn: consumers must use lifecycle-gated API calls or sync updates.

Local keyword search results are cleared when the collection, date, query, view or document list changes; after successful source intake, form reset restores collection `general` and version `1`.

## Local API

`GET /api/config` returns a session CSRF token. Send `X-CSRF-Token` on mutations; browser callers must use same origin.

- `POST /api/pipeline`: action crawl/build, scope, collection, key_group btc/external, optional stage_models; crawl limits max_sources/max_pages/max_depth, auto_approve defaults false.
- `GET /api/pipeline`, `GET /api/pipeline/{id}/trace`: job history and stage diagnostics.
- `GET /api/documents` (lightweight summaries), `GET /api/documents/{id}`: staging and reviewed documents.
- `POST /api/documents/text`, `/upload`, `/web`: manual sources. Upload supports PDF, UTF-8 TXT/MD/HTML, DOCX/PPTX/XLSX and PNG/JPEG/TIFF/WebP.
- `PATCH /api/documents/{id}`: edit pending text/metadata with current revision.
- `POST /api/documents/{id}/decision`: approve/reject/reopen/withdraw with revision, actor and note; warnings require acknowledge_findings.
- `POST /api/pipeline/{id}/evidence`: question and optional evidence model. `GET` returns saved context while rechecking lifecycle; `/evidence/download` exports it.
- `/api/search` is local FTS5 keyword search on approved documents, distinct from the semantic pipeline.

## Storage and limits

Data and credentials stay outside Git at `~/.local/share/scope-data-bot/<workspace-hash>/`, or set RAG_REVIEW_DATA. Keep that setting when moving source to reuse a store. Keys are local plaintext in a 0600 file under a 0700 directory, not a Keychain. Protect backups. The UI does not silently import CLI .env.local credentials; configure keys explicitly in Settings. Workers receive selected API keys through stdin, not command arguments; parser workers do not receive keys.

Loopback only, one server per store. No multi-tenant authentication/ACL, durable queue or hard RAM sandbox. Parser warnings, OCR errors and partial coverage remain review concerns. A ready index does not prove source truth or completeness. Native PDF scans remain blocked until OCR or reviewed replacement text resolves missing evidence. Manual web intake reports timeout, HTTPS certificate/connection and other network errors separately. Sources blocked by robots/TLS/CAPTCHA are reported; no bypass.

Run maintenance checks from the repository root: install requirements-ui-dev.txt, then `python -m pytest` and `ruff check .`. CI uses authored fixtures, no paid model calls or real keys. Historical/live benchmark evidence stays local. See root NOTICE.md for UI origin.
