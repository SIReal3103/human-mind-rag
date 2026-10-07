# Restore the upstream pipeline

2026-10-07 — Implementation and local verification complete; live AI validation still needs valid credentials. User requires automatic source discovery and unchanged scope-data-bot source/behavior.

Evidence: pinned upstream `cb37446a00c6283cbb596df524885cfcb08a9fe7` matches GitHub HEAD. Its `data_bot.py` invokes `run_bot` with `planner="model", search_provider="openai"`; the gateway honors the selected BTC/OpenAI provider. The app instead forced rules/DuckDuckGo and patched discovery/network/embedding behavior.

1. Remove overrides; call upstream crawl/build/retrieve functions with the canonical profile. Configure CA through the environment, preserve upstream capability gates and the app's human approval boundary.
2. Remove URL requirement and source-mode selector. Explain provider use before crawl, restore actionable errors, retain current-session/history behavior.
3. Test real upstream failure/gate paths without paid requests, review affected contracts, verify UI and untouched upstream checkout, update README and validation report.

Acceptance: scope-only form; no monkeypatches or replacement transport/embedding; approved-only index; no provider fallback; errors preserve trace and distinguish missing/invalid key from empty discovery. BTC remains default. Existing documents/jobs/keys preserved. Do not claim live success with the previously rejected OpenAI key.

Rollback: restore only app integration/UI changes from this task; upstream checkout and stored records are never rewritten.

Validation: unchanged GitHub commit, real upstream gate tests, approval tests, UI scope-only submit and independent review complete. See [validation report](reports/validation.md). No live end-to-end success claimed, no paid requests made in this task.

2026-10-07 follow-up: user explicitly requested independent stage APIs. [Stage routing and key health](../20261007-stage-api-and-key-health/plan.md) adds app-owned gateway wrappers for provider selection only; the earlier no-runtime-wrapper statement is superseded by that requirement. Upstream tracked source stays unchanged.
