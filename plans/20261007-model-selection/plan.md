# Model selection and crawl failure correction

2026-10-07 — Complete. [Validation and remaining external limits](reports/validation.md).

The new OpenAI key already matches the supplied file and authenticates successfully. The latest crawl failed after a successful planner call: the original rules parser treats “từ 2016 đến nay” as 2016–2016, while the model resolves a later end year. Preserve the upstream checkout and its validators; explicitly resolve relative time before both planners and constrain the model to those years.

1. Add one BTC/external key group and a stage-compatible model catalog based on the BTC pricing/API guides. Model selection determines the external provider; BTC uses the single BTC key.
2. Add app-owned model transports for the documented OpenAI, Gemini and DeepSeek interfaces, retaining original discovery, parsers, semantic validators, approvals and retrieval algorithms. Fixed destinations, no redirects or fallback, truthful receipts.
3. Persist normalized scope and model configuration; distinguish schema/scope failures from key, quota and model failures. Query vectors remain tied to the index.
4. Replace provider selectors with model selectors, show key freshness and historical failures clearly. Preserve legacy jobs.
5. Focused regression tests, real small crawl and API checks, independent review, docs and report. BTC live verification is limited by the absence of its key.

Acceptance: user selects BTC/external once; only eligible models appear per step; the supplied key is used; the reported relative-date failure is corrected without changing user intent or weakening upstream validation; successful calls and concrete remaining external failures are demonstrated.

Delivered and verified: UI-started mixed GPT/Gemini crawl imported one Hà Nam document for human review. An existing approved Bù Gia Mập document produced four indexed chunks and four retrieved evidence items using Google models. Source TLS/robots errors and a semantic evidence warning remain explicit; no claim that arbitrary sources or every catalog model will always succeed. No BTC/DeepSeek key was available for live calls.
