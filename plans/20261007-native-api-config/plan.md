# Native upstream API configuration

Status: complete. Publication authorized on 2026-10-07. User requests the original scope-data-bot API configuration and read-only UI display.

- Resolve provider/model/endpoints/capability gates with upstream gateway.setting (environment > upstream .env.local > upstream defaults).
- New jobs call upstream functions directly, without StageRouter, model/prompt overrides or custom assessment repair. Preserve approval snapshot and withdrawal gate.
- UI displays effective configuration; reject old model/provider override payloads. Native query requires matching index configuration. Historical adapter indexes require rebuild for new queries.
- Credentials for native calls come from upstream configuration only; existing app key store remains separate and explicitly labelled.
- Verify real upstream identity, offline capability gates, no credential output, configuration mismatch, UI read-only controls and regression suite. No claim of live API success without a live call.

## Verification

- [Report](reports/validation.md); [read-only UI screenshot](reports/native-api-ui.png).
- 117 tests + 30 subtests passed; Ruff lint/format, JavaScript syntax and diff checks passed.
- Independent reviewer: DONE after fixing worker configuration stability and ineffective key-store recovery links.
- Native provider live success remains unverified: inherited OpenAI legacy alias returned HTTP 401; no successful new native crawl/index/evidence claimed.
