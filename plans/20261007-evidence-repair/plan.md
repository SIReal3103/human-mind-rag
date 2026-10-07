# Bounded evidence repair

Status: complete.

- Cause: a successful model API response can claim years absent from selected source segments; the original semantic validator correctly rejects it.
- Change: same-model correction once, preserving both responses and original validation. No upstream source edits or robots/TLS bypass.
- Acceptance: unsupported years/IDs remain rejected; a valid correction reaches original validator; trace distinguishes response delivery from evidence validation.
- Validation: focused tests, full suite, independent review and live public-document trial. See reports/validation.md.

- Additional root cause fixed: parsed documents marked out_of_scope were discarded before human review. They now enter pending review with scope warnings and original assessment. Reimport is idempotent within a job.
