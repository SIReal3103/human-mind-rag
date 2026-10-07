# Native upstream integration validation

2026-10-07

## Source and execution

- `git ls-remote origin HEAD` and local HEAD both equal `cb37446a00c6283cbb596df524885cfcb08a9fe7` for https://github.com/Qyroven/scope-data-bot.
- `git diff --quiet HEAD --` succeeds; no upstream tracked files changed. macOS AppleDouble metadata in the external checkout is unrelated to its tracked source.
- Removed the app's custom crawler transport, seeded discovery monkeypatch, AI-opener replacement and embedding implementation. Worker now calls `run_bot` with the same `planner="model", search_provider="openai"` as `data_bot.py`; gateway provider selection remains explicit BTC/OpenAI. Native `build` and `retrieve` retain default request functions, scope gate and rerank.
- CA is supplied via `SSL_CERT_FILE`, not by replacing upstream objects. BTC capability flags default to zero; only explicit launch environment values are forwarded. No flag was enabled during verification.
- Human approval still precedes build. The app creates a separate approved-only snapshot with raw/hash/audit provenance; original crawl artifacts and existing decisions remain unchanged.

## Automated verification

- Focused pipeline tests: 22 passed before adding the two native job lifecycle tests.
- Full suite at that point: 65 passed and 30 subtests passed.
- Added real native crawl/build failure tests, then reran `tests/test_pipeline.py`: 11 passed, including both additions. These use isolated local test credentials and closed BTC capability flags: no provider request is sent. Planner fails at `BTC_STRUCTURED_VERIFIED`; build fails at `BTC_EMBEDDING_VERIFIED`. Both persist failed jobs, actionable sanitized trace, and no vector index.
- Tests also verify upstream discovery/PublicHTTP/opener/embedding function identity is unchanged after execution, original allowlist/redirect protection, default SSL certificate validation, selected-key requirement without fallback, old seed-URL API rejection, and masking of model response bodies in crawl trace.
- Existing approval, withdrawal, expiry, saved-evidence, raw/hash and actual chunk/provenance checks remain passing.
- Ruff check/format and Node syntax checks for pipeline/app JavaScript pass. One existing Starlette/httpx deprecation warning remains; no errors were suppressed.
- Independent review found no actionable regression in the integration, UI, provider errors or human approval boundaries.

## Browser and server

- Restarted the loopback server after confirming no job was running. New process serves http://localhost:8765/#pipeline.
- Reload preserved the selected historical Hà Nam session. Historical cards explicitly identify the old integration.
- `Tạo phiên mới` cleared the selected card/form, collapsed eight historical jobs, and restored BTC/12 pages/depth 1.
- Entered the user's Hà Nam scope and collection, with a small 1-page/depth-0 setting. Clicking `Bắt đầu crawl` required no URL; the backend responded `Chưa lưu key cho btc. Mở Cấu hình API key.` No job, source, approval or paid request was created.
- The page remains open with the Hà Nam scope and BTC selected. Screenshot: `/tmp/human-mind-native-pipeline.png`.

## Remaining live dependency

BTC is not configured. The previously supplied OpenAI key returned HTTP 401 in the earlier embedding trial; no paid search trial was attempted here. Native discovery through evidence has not been validated live with a valid provider key. BTC additionally requires the original repository's capability smoke tests before enabling its flags. The old one-article Hà Nam crawl is historical and is not presented as native auto-discovery success.

No project commit/push, key reset, upstream source edit, automatic provider fallback, fabricated vectors or new approval decision occurred.
