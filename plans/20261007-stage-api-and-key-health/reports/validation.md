# Stage API routing and credential health validation

Date: 2026-10-07, Asia/Ho_Chi_Minh.

## Delivered behavior

- Independent BTC/OpenAI provider selection for planning, source search, content checking/ranking, embedding, and evidence scope/reranking. BTC remains the default, with no automatic fallback.
- Original upstream gateway functions run under the selected provider in an isolated worker. Embeddings use upstream's supported request function injection. The upstream checkout remains unchanged at `cb37446a00c6283cbb596df524885cfcb08a9fe7`.
- Query embedding stays tied to the index's provider/model. Human approval remains required before indexing.
- API call diagnostics identify the stage, provider and key label, without storing key values or raw provider response bodies. Results are bound to the credential version; replacing/removing/resetting a key prevents older requests from changing its health.
- Settings provides explicit credential checks and a status summary. The pipeline displays health next to each provider selector and records API calls in its trace.

## Supplied keys and live checks

The supplied `keys.rtf` contained OpenAI and Google credentials. Both were imported into the local credential store; no credential values were printed or added to project files. It contained no BTC key.

| Credential | Checked through the UI | Result |
| --- | --- | --- |
| `OPENAI_API_KEY` | 16:07:57 | Model-list request returned HTTP 401; credential rejected. |
| `GOOGLE_API_KEY` | 16:08:35 | Model-list request returned HTTP 200; authentication accepted for that endpoint. |
| `BTC_API_KEY` | Local store inspection | Missing. |

These checks make fixed GET requests to provider model-list endpoints. They do not generate content or prove access to all models, embeddings, search, or Veo. No paid generation/search request was made for this task. Google/Gemini/Veo credentials can be stored and checked, but the unchanged upstream pipeline supports BTC/OpenAI only. A usable BTC/OpenAI key is still needed for a successful live crawl.

Error classification follows the [OpenAI error guide](https://developers.openai.com/api/docs/guides/error-codes); Google's check uses the [models endpoint](https://ai.google.dev/api/models). Responses are reduced to allowlisted diagnostic codes rather than reflected as arbitrary provider messages.

## Verification

- Full Python suite: **81 passed, 30 subtests passed**. One pre-existing Starlette/httpx deprecation warning remains.
- Focused credential-health tests after the final HTTP error-read guard: **12 passed**.
- Ruff lint and formatting checks passed for the affected Python modules and tests. JavaScript syntax checks passed for both changed UI modules.
- Independent reviewer found no actionable issues in routing, index/query compatibility, version-bound health, probe destinations or approval boundaries; its focused run passed 38 tests.
- Browser checks confirmed five independent selectors: changing planning and content checking to OpenAI left search, embedding and evidence on BTC. The OpenAI rows displayed `OPENAI_API_KEY`, HTTP 401 and the latest check time. Restored all selectors to BTC afterwards and retained the user's Hà Nam scope, one-page limit and depth zero without starting another job.
- Both live check buttons persisted and displayed the outcomes above. Screenshot: `/tmp/human-mind-key-health.png`.
- `git diff --quiet HEAD --` succeeded in the upstream checkout. No commits or pushes were made.

Tests exercise the real upstream functions and provider gates without inventing successful network responses or vectors. Live end-to-end generation is not claimed because the supplied OpenAI key is rejected and BTC is absent.
