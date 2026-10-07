# Scope Data Bot reuse review

Date: 2026-10-07. Source: external checkout `scope-data-bot`, remote
`https://github.com/Qyroven/scope-data-bot.git`, commit
`cb37446a00c6283cbb596df524885cfcb08a9fe7`.

## Decision

Reuse the external checkout through an isolated process, restricted to document
extraction and token spans. Do not invoke its discovery, assessment, embedding,
build or retrieval workflow for the human review application. No upstream files
were copied or changed. The adapter verifies the commit before use.

No LICENSE/COPYING file or license declaration was found in the tracked tree,
README or pyproject at this commit. The review therefore does not establish a
license grant for redistribution. The external-path arrangement avoids including
upstream source in this repository; it does not itself settle licensing.

## Actual upstream contracts

| Call | Contract and effects |
| --- | --- |
| `bot.extract_document(body, content_type, charset, url, scope=None, parser_cache=None)` | Main dispatch at `bot.py:638`. Returns parsed document dictionary. Recognizes PDF, HTML, CSV, JSON and Docling formats. Does not call a provider. Does not add ingestion status, assessment, raw source metadata or trace. Plain TXT is not supported by this upstream function. |
| `document_parser.parse_document(body, content_type, cache_dir=None)` | Docling-only worker adapter at `document_parser.py:145`; it does not select native parsing. Requires the isolated runtime even if caller configured native mode. Dispatch must happen through `bot.extract_document` or `should_use_docling`. |
| `data_pipeline.spans(text, limit)` | Generator of exact Python Unicode character `[start,end)` spans, paragraph preference and token ceiling. No overlap; raises if one character cannot fit. |
| `data_pipeline.tokens(text)` | `cl100k_base` count with special-token rejection disabled. The review app uses actual upstream spans/counts with a 400-token limit. |
| `data_pipeline.make_chunks(folder, trace, limit=500, max_chunks=10000)` | Full run-folder interface, not a text-in/text-out helper. Reads `parsed/*.json`, excludes `unassessed-*` and statuses other than `review` or `verified_against_source`, requires valid provenance parents, reads lineage for integrity checks, and writes trace artifacts. Adds title prefixes, rows and structured table evidence. |
| `data_pipeline.build(...)`, `retrieve(...)` | Default embedding requests and, for retrieval, model scope gate/rerank. These must not be used as an offline parser/chunker shortcut. |

`engine.py` contains World Bank processing and common save/validation helpers;
the general document parsing entrypoint is in `bot.py`.

## Quality and provenance

- Native PDF output includes `pages[{page,text}]`, `selected_pages`,
  `pdf_total_pages`, `parse_partial`, `coverage_note` and a warning that OCR/table
  structure are unavailable (`bot.py:650–699`). With `scope=None`, all pages are
  retained up to 200 pages; fewer than 150 extracted non-whitespace characters
  fail explicitly. Native parsing has no hard memory sandbox. Its internal
  45-second timer is checked between pages; the application adds a process timeout.
- Docling output retains native JSON, parser/config/version, page item character
  spans, item provenance/bounding boxes, table cell coordinates and merged-cell
  grids (`docling_worker.py:19–150`). Unlocated Office items are not assigned an
  invented page. The app retains page-level locators and warnings, rather than
  exposing every native Docling field in its smaller interface.
- Table warnings include `MULTIPLE_NUMERIC_VALUES` and `MISSING_GRID_CELLS`.
  Table status is `extracted_structure_not_verified`; extraction cannot certify
  numeric correctness. Generic parse warnings explicitly require source review.
- Docling defaults: first 40 pages, vi/en OCR, CPU two threads, 180-second worker
  timeout, 10 MB input, PDF at most 500 pages, 600k text characters/20 MB result,
  Office archive/member limits, image 20 MP/single frame. Partial conversion or
  page truncation is reported. No real Docling runtime/OCR quality run was
  performed here; CI includes an optional real DOCX conversion, not universal
  PDF/OCR accuracy proof.
- The application rejects stale segment locations when non-whitespace text no
  longer matches. Reviewed text uses `kind=reviewed_text` and character offsets,
  with no page number. Source chunks retain page and page-local offsets.

## Provider and import behavior

`document_parser` imports `gateway.setting`; importing those modules does not
invoke inference. `ai_http` constructs an HTTP opener but does not send a request
on import. `gateway.setting` reads environment first, then upstream `.env.local`
when the requested setting is absent. `gateway.provider()` defaults to OpenAI.
The application worker supplies parser settings explicitly, strips inherited
keys/proxies/Python paths, sets BTC with empty key values and closed capability
gates, and never calls provider functions.

Importing `data_pipeline` immediately loads `tiktoken.get_encoding('cl100k_base')`.
On a cold cache this downloads public tokenizer data; it is not an inference
request or a document upload. For disconnected operation prepopulate and preserve
`TIKTOKEN_CACHE_DIR`. Verified against the pinned package's official
[encoding definition](https://raw.githubusercontent.com/openai/tiktoken/0.12.0/tiktoken_ext/openai_public.py)
and [cache implementation](https://raw.githubusercontent.com/openai/tiktoken/0.12.0/tiktoken/load.py).

Docling setup explicitly downloads model weights. Conversion sets offline model
flags, disables remote services/downloads, and receives no parent AI keys.

## Application adapter validation

Implemented `chung-khao/rag-review/ingestion.py` and `tests/test_ingestion.py`.
The adapter accepts only native or explicit Docling mode, bounds local processes,
input and output, and uses no upstream inference workflow. UTF-8 text has a small
local extraction path because upstream does not support it; chunks still use
the actual upstream tokenizer/span functions.

URL fetching uses a separate process with a hard deadline, a 10 MB limit, default
HTTP(S) ports, no credentials/proxy inheritance, public-IP validation of every
DNS answer, repeat validation on redirects, and a socket connected to the
validated address. HTTPS verifies certificates with system plus certifi roots
and uses the original hostname for TLS. This prevents a second DNS resolution
between validation and connection.

Validation on 2026-10-07:

- 13 tests passed in the application venv: real Vietnamese TXT, HTML and two-page
  PDF extraction; exact chunk spans/token bounds/page references; stale locator
  rejection; pin/input checks; environment isolation; loopback/mixed/private/
  multicast rejection; redirect recheck; DNS pinning and TLS hostname; size limits.
- Ruff check and formatting check passed for both owned Python files.
- Live unauthenticated HTTPS GET `https://example.com/`: 577 bytes,
  `text/html; charset=utf-8`, expected title present. This exposed missing macOS
  Python CA roots; adding certifi roots resolved it without disabling validation.
- No `.env` or personal data inspected. No real inference request made. No
  Docling models installed or real OCR quality claimed.

The external drive exposes AppleDouble `._*` files, including a Git pack-index
warning. The commit remains readable; these unrelated files were not removed.
