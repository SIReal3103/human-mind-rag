# Model selection and corrected crawl — validation

2026-10-07, Asia/Ho_Chi_Minh.

## Cause and changes

The supplied file's OpenAI key matches the credential saved by the user at 16:18:44. It is a different credential from the previously rejected key and currently authenticates. The file and local store agree; no unnecessary replacement or disclosure was performed. Model-list checks at 16:31:46 returned HTTP 200 for OpenAI and Google. BTC remains absent.

The failed job `3e80f42f8c8a4c3aa8250350e226e8d9` had a successful `gpt-4.1-mini` response. Its actual failure was `Planner tự thay đổi năm đã trích từ input`: rules parsed “từ 2016 đến nay” as 2016–2016, while the model inferred a later end year. The app previously concealed this behind a generic failure message. New jobs resolve the phrase to 2016–2026 before both planners, constrain the JSON schema to those years, and carry the resolved scope into approved snapshots. Original input remains visible.

The UI now has one key group (BTC/external) and five model selectors. Model catalog and endpoints follow the [BTC pricing guide](https://docs.thucchien.ai/docs/round-2/user-guide/pricing), [grounding guide](https://docs.thucchien.ai/docs/round-2/user-guide/google-search-grounding), [embedding guide](https://docs.thucchien.ai/docs/round-2/user-guide/embeddings), and provider documentation. Search excludes DeepSeek; embedding excludes generation models. External model families select their own stored keys; all BTC models use the BTC key. No automatic fallback.

An additional live test uncovered Google's intermediary citation URLs being rejected at the intermediary's robots check. The app now resolves only HEAD redirects at `vertexaisearch.cloud.google.com/grounding-api-redirect/`, with public DNS/address pinning, normal TLS, no credentials and a bounded redirect count. It stops before fetching source content. Receipt metadata records original citation and final source; the original crawler enforces the source's robots and TLS.

## Live evidence

| Check | Actual outcome |
| --- | --- |
| OpenAI `gpt-6-luna` planner with original relative-date request | Completed with 2016–2026. |
| OpenAI search and ranking | Successful API calls; first one-source run then hit a source TLS error. |
| Google `gemini-3.1-flash-lite` JSON | Valid structured result. |
| Google grounding | Real search metadata/citations returned; three saved redirects independently resolved to VnEconomy source pages. |
| Google `gemini-embedding-2` two-input smoke test | Two requests, two real vectors of 3072 dimensions. |
| UI-started mixed GPT/Gemini crawl `1c044d705695408f8290bd7ba26f1816` | Six successful API operations, one Hà Nam document imported pending; “Tiếp tục duyệt 1 tài liệu” visible. |
| Build `3f20716629d74453af4f9d636e3e9d15` from existing approved `binh-phuoc-demo` document | Four chunks indexed with `gemini-embedding-2`; manifest provider correctly `google`. |
| Retrieval from that build with `gemini-3.1-flash-lite` scope gate/rerank | Four evidence items, three matched anchors; no_relevant_evidence=false. |

The new Hà Nam document (`e73c0efa0ce7470aad83fbcc38c81400`) has a semantic warning: the model listed a year absent from its selected quotes. The original validator rejected that assessment, and the app retained the raw document for human review. Two other attempted sources had robots/403 errors. These are displayed separately from key authentication. No new document was automatically approved, and no TLS/robots checks were disabled.

Small live generation/search/embedding calls used the authorized external keys and may incur provider fees. No claim of live BTC or DeepSeek verification is made because those keys were not available. Listing a model does not establish account access or guarantee source availability.

## Automated and manual verification

- Full suite: **90 passed, 30 subtests passed**. One existing Starlette/httpx deprecation warning remains.
- Latest trace/model-focused run: 15 passed; after the final diagnostic hint edit, 6 trace tests passed.
- Ruff lint and formatting passed; both changed JavaScript files passed Node syntax checks.
- Independent reviewer identified and verified fixes for Google provider provenance, consistent effective scope in build, and honest legacy model display. Follow-up review of citation resolution found no additional blocker; 14 focused tests passed.
- Browser verified one BTC/external selector, eligible models by stage, successful current key status, and the pending-document continuation. The final crawl was started through the actual UI.
- Original `scope-data-bot` checkout remains unchanged at `cb37446a00c6283cbb596df524885cfcb08a9fe7`; `git diff --quiet HEAD --` returned 0. Git prints an existing exFAT AppleDouble pack-index warning.
- Credentials stay outside project source and API responses. No commits or pushes.
