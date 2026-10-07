# End-to-end operator walkthrough

2026-10-07 — Implementation and local end-to-end verification complete. Live semantic validation blocked by OpenAI HTTP 401; awaiting a valid key. BTC remains default.

Run a real public Bình Phước source in collection binh-phuoc-demo, inspect original/extraction, record Codex as demo reviewer, then embed/index/retrieve with the user's explicitly approved stored OpenAI key. BTC remains default. Fix empirically observed failures and improve the guided path through the application. Preserve prior jobs and audit. Do not use fabricated vectors or claim human approval by another person.

Acceptance: real source → pending → reviewed demo approval → real provider index → cited evidence; errors are actionable; user can follow the same sequence. Tests target fixes and gates. Report exact live results and unresolved external blockers.

Completed: observed TLS failure repaired, actionable provider errors, review-to-index continuation, saved evidence gate/cards/export, keyword-search fallback. Real public source was crawled and reviewed; local retrieval/export verified. No fake vectors, no provider fallback, no unrelated documents approved. Tests and independent review completed.

Remaining: after the operator replaces the invalid OpenAI key or supplies BTC credentials, create the semantic index and retrieve question evidence through the UI. See [validation and runbook](reports/validation.md).

Follow-up (2026-10-07): new-session reset and single selected job with collapsed history; explicit direct-URL versus DuckDuckGo discovery; source gzip support. Hà Nam live crawl now imports one pending document for the user to review. See [follow-up verification](reports/session-and-source-fix.md). No paid calls or approval decisions in this follow-up.

Follow-up superseded (2026-10-07): user requires canonical upstream automatic discovery. Forced rules/DuckDuckGo, URL seeding and runtime overrides are removed by [the upstream-native plan](../20261007-upstream-native-pipeline/plan.md). Prior validation remains historical; native AI search still needs valid credentials.
