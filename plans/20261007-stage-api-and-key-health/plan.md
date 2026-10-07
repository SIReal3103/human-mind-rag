# API selection by stage and credential health

2026-10-07 — Complete. [Validation report](reports/validation.md).

User requests independent API selection for each step, named failing keys, and importing the supplied keys.rtf. BTC remains the default. The upstream checkout must remain unchanged; the latest request requires an app-owned routing adapter around original gateway calls, without rewriting crawler, validation, embedding, or retrieval algorithms.

1. Import supplied OpenAI/Google credentials without displaying values; add explicit non-generation authentication probes and version-bound results.
2. Add separate planner, web-search, content-check, embedding and evidence providers (BTC/OpenAI supported by upstream). Query embedding stays locked to the index's embedding provider/model. Google/Veo key checks do not imply upstream pipeline support.
3. Route each original call in the isolated worker under the selected credential; record safe stage/provider/model/error metadata. Persist diagnostics only against the same credential version; never send keys in logs/jobs or probe arbitrary destinations.
4. Update selectors, key health/check buttons and per-stage trace. Preserve approvals, reset behavior, old jobs and provider compatibility.
5. Focused tests, live authentication checks, UI checks, independent review, docs/report. No automatic fallback, no invented successful credentials or vectors, no upstream edits.

Acceptance: independent stage settings reach the correct API; failures identify stage/provider/key label and distinguish invalid credentials from quota/permission/network/capability; updated keys clear obsolete health, in-flight old results cannot taint replacements; user can inspect current key health and change it. Native provider gates and human review remain enforced.

All five implementation and verification steps are complete. Live authentication confirmed OpenAI HTTP 401, Google HTTP 200 on the model-list endpoint, and no BTC key. Completing a live crawl still requires a usable BTC/OpenAI credential; Google/Veo is not integrated into upstream pipeline stages.
