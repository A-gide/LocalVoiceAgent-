# Hub contract fixtures (PR-012)

Sanitised request/response fixtures pinned to the reviewed upstream commit in
`src/lva/providers/hub_contracts_v0_9_8_3.py`.

Rules for anything added here:

- No host, no account identifier, no absolute path, no credential. The test
  `test_fixtures_are_redacted` enforces this.
- A fixture may carry unknown keys on purpose: the pinned DTO must preserve them
  rather than drop or rewrite them (plan L584).
