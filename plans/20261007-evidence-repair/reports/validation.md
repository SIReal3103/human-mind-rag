# Validation — 2026-10-07

- 93 tests passed, 30 subtests passed. Existing Starlette/httpx deprecation warning remains.
- Ruff and JavaScript syntax checks passed.
- Independent reviewer found no concrete blockers. Follow-up review of pending import/idempotency found no blockers. Full correction branch lacks an automated integration test; pure evidence contract and routing are covered.
- Rechecking the previously rejected Hà Nam article with the saved OpenAI model passed the original semantic validator with supported years 2024 and 2025. One API call, no correction needed for that particular response.
- Fresh six-page crawl b8367577a53a4bb5b60440459be10ce9 completed: 8 API calls, 3 document checks accepted by the original validator, no correction needed on these responses. It produced 3 parsed documents classified out_of_scope and 1 unextractable page. All 4 now enter pending review, with the empty page still blocked from approval. Two source issues remain (TLS/extraction), not key failures.
- Concurrent user crawl 35ad0696a7064fcb945152c2ed832ee8 was marked interrupted during server replacement. Its orphan worker finished and its original result/credential events were recovered without new API calls. Final no_documents: all five attempted sources failed TLS/robots/403.
- Upstream commit cb37446 has no tracked source changes. Existing AppleDouble artifacts trigger an unrelated git pack-index warning.

UI verification: opened recovered Vietstock article, nonempty text, pending status, extraction score 95 (not factual confidence), original out_of_scope assessment/reasons, no autoapproval. Screenshot /tmp/human-mind-review-recovered.png. Current server PID35781 loaded final files.
