# tests/red_v121 — v1.2.1 RED suite (PR-022 harness)

**Status: mixed.** The R03b contract slice is closed, while later v1.2.1 fix
slices still have expected RED tests. Do not interpret a passing subset as the
whole suite or formal G0 passing.

## Why a separate directory

The v1.2 layer directories (`tests/unit`, `tests/contract`, `tests/invariants`,
`tests/integration`, `tests/fault`, `tests/migration`, `tests/ux`) are green and
are what `scripts/verify_release_gates.py` runs. Keeping the RED suite separate
means:

* `G0–G8` keep running against the v1.2 layer dirs and are unaffected;
* the RED state is explicit and never silently mixed into a green gate;
* the fix slices (R03, R05, R06, R09, R10, R13, R14) can turn these green one
  group at a time.

## Commands

```powershell
# v1.2.1 suite (remaining gaps are expected RED)
.venv\Scripts\python.exe -B -m pytest tests\red_v121 -q

# v1.2 layer groups and harness
.venv\Scripts\python.exe -B tests\run_groups.py --layer v12
.venv\Scripts\python.exe -B tests\run_groups.py harness

# legacy v1.2 release gates, not formal v1.2.1 G0
.venv\Scripts\python.exe -B scripts\verify_release_gates.py
```

## Map: RED file -> frozen rule -> fix slice

| RED file | v1.2.1 rule | Fix slice |
|---|---|---|
| `test_red_contract_cas.py` | §4.2 / §4.4 / §4.5 (patch #2: aggregate CAS, typed `precondition`, `STALE_REVISION`, `settings.*`) | R03 |
| `test_red_auth.py` | §Phase 1 / PR-006 (fail-closed auth, token never in argv/URL) | R05 |
| `test_red_bootstrap.py` | §2.3 / PR-006+PR-007 (pipe handshake, `LVA_READY`, spawn wiring) | R06 |
| `test_red_snapshot.py` | §8.1 (one snapshot DTO across Core/Rust/store/mock). **Not PR-008** — PR-008 is *Service identity and readiness*, see the row below | R08 |
| `test_red_service_identity.py` | PR-008 (L1208-1216: service identity/readiness, Windows listener table, typed bind attestation, crash reason, redacted diagnostic snapshot) | R08 |
| `test_red_authority.py` | I21 / I22 (patch #7: Hub control only from Core; no conversation bypass). **Mixed ownership** — see the per-test split below; only 2 of its 6 tests belong to R09/R10 | R09 / R10 (partial) |
| `test_red_capture.py` | §3.3 (patch #4: Standby turns LVA-managed capture off; `record_reality_during_live`) | R13 |
| `test_red_output_mute.py` | §3.3 / §8.4 (patch #6: Output Mute must not change capture) | R14 |
| `test_red_temporal_mention.py` | §7.1 (patch #5: `mention_index` + spans) | R12 |
| `test_red_config_boundary.py` | PR-003 (runtime config boundary) + PR-004 (secret DTO and `settings_revision`) | R11 |

### Errata — per-test ownership of `test_red_authority.py` (2026-09-24)

This file was previously mapped as a whole to `R09 / R10`, which promised that
those two slices would turn it green.  They cannot: the file's own docstrings and
assertions bind three different PRs across three different waves.

| Test | Bound rule | Fix slice | Wave |
|---|---|---|---|
| `test_no_hub_management_client_outside_core` | I21 (no Hub management client outside Core) | R09 | — (already green) |
| `test_ask_route_adapts_into_a_command` | I22 / PR-010 (`/api/ask` adapts into a command) | **R10** | Wave 3 |
| `test_no_route_bypasses_the_command_dispatcher` | I22 / PR-010 (no route performs provider/journal side effects directly) | **R10 remaining** | Wave 3 |
| `test_core_actually_wires_a_hub_saga` | PR-014 (Hub binding and lifecycle saga) | **not R09/R10** | Wave 4 |
| `test_rust_exposes_no_direct_model_lifecycle_commands` | PR-015 (remove direct llama lifecycle and scanner) | **not R09/R10** | Wave 5 |
| `test_legacy_1234_default_is_gone` | PR-015 (remove the 1234 / LM Studio default) | **not R09/R10** | Wave 5 |

Consequence: `red_v121` cannot be driven to zero by R09/R10 alone.  Three of the
six tests are RED-first coverage for Wave 4/5 work, which is the normal state for
a RED suite that runs ahead of its owning slices — not a backlog item.

## Harness

`harness.py` provides, with no network/audio/Hub/disk dependencies:

* `DeterministicClock` — reproducible timestamps;
* `FakeProvider` / `FakeProviderSet` — ASR/LLM/TTS doubles with call counters and
  crash injection (I07/I08/I12);
* `EventRecorder` — ordered event capture;
* `ArtifactWriter` — writes failure artifacts with secrets, absolute paths and
  transcripts scrubbed (I20), and asserts the scrub before writing;
* `iter_source_files` / `read_text` — repo scanning helpers.
* `forbidden_endpoint_hits` / `route_call_map` / `conversation_bypasses` —
  authority probes shared by the RED tests and synthetic self-tests.

`test_harness_selftest.py` proves the rig itself works and stays green, so a RED
result elsewhere is attributable to the product rather than the harness.

## Rules honoured

* No assertion is weakened to make a test pass.
* No gate is shortened or skipped.
* No dual authority is introduced.
* Failure artifacts are written to `tests/red_v121/_artifacts/` and are scrubbed
  before they reach disk. `LVA_TEST_ARTIFACT_DIR` may redirect them to a local
  scratch directory; CI retains the default upload path.
