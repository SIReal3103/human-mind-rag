# Native API configuration validation — 2026-10-07

## Result

New pipeline jobs use original upstream run_bot/build/retrieve and gateway requests at commit cb37446a00c6283cbb596df524885cfcb08a9fe7. No StageRouter, per-stage provider/model override, planner prompt/schema modifications or custom assessment repair in the new path. HITL and approved snapshot/revocation logic remain.

API settings come from upstream gateway.setting with original environment/file/default precedence. UI shows provider, text/embedding models and dimensions, endpoints, key variable/source/presence and BTC gates. No credential values are returned. Worker freezes resolved API values in its isolated environment without replacing upstream functions; config edits cannot mix providers or keys mid-run.

Old adapter indexes retain valid saved evidence download but cannot generate new context without native rebuild. Config changes after index build are rejected before query. Old selection payloads are explicitly rejected, not silently ignored.

## Checks

- Full suite: 117 passed, 30 subtests passed. One existing Starlette/httpx deprecation warning.
- Ruff lint and format: passed; node syntax for all three JavaScript modules: passed; git diff whitespace: passed.
- Native tests cover effective configuration, original env/file/default semantics, alias precedence, no secret reflection, BTC gate failures before network, original function identities, changed configuration rejection and stable execution after editing a synthetic config file.
- Existing HITL/index/withdrawal/download regression checks pass.
- CUA UI: refreshed real localhost application, created a new blank form, clicked read upstream configuration; no combobox/model selectors present. Read-only panel showed openai/gpt-4.1-mini/text-embedding-3-small/1536 and original OpenAI endpoints. [Screenshot](native-api-ui.png).
- Independent review found two issues: config could change mid-worker and recovery linked to unused app credential store. Both fixed and re-reviewed: DONE.

## Observed authentication and test isolation

The first regression run after enabling original configuration inherited a real host legacy THUCCHIEN_API_KEY instead of its former app-store fixture. Native OpenAI requests returned HTTP 401. This is not a successful live smoke test. The suite now explicitly isolates host credentials via autouse environment fixtures, closes all BTC capability gates, and never relies on live keys; rerun passed. No key values or raw provider error bodies are included here.

The live UI still truthfully displays the unchanged host key source. UI saved keys do not override upstream configuration. Configure a valid OPENAI_API_KEY in environment or upstream .env.local to run native OpenAI, or configure the BTC profile and verify its capabilities. No claim of successful native end-to-end crawl/index/query, BTC live support, factual accuracy or OCR acceptance is made.

## Scope

Only local Human Mind files changed. No tracked upstream files or user keys were edited. Publication authorized separately on 2026-10-07; this report accompanies the native API configuration commit. Historical reports describe the earlier adapter behavior; current README and AGENT-GUIDE supersede their operating instructions.
