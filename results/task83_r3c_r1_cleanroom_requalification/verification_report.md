# Task 83-R3C-R1 — Clean Offline Requalification — Verification Report

**Verdict: `CLEAN_OFFLINE_REQUALIFICATION_PASS`**

## Qualification SHA

| | |
|---|---|
| Qualification SHA (Phase F) | `5955e82938f965a16ed2c779851c75dc593421cc` |
| Prior SHA (Phases A–E, attempt 2) | `320da7b8e606ed5aad642c2d5fa4c4e489c4fd29` |
| Branch | `research/talonx-strategy-validation` |
| SHA delta | one commit, `5955e82` — *"test: make offline suite hermetic against clean-room env and CRLF checkout"* |
| Files changed by delta | `tests/conftest.py`, `tests/test_task65b_protected_fingerprints.py`, `tests/test_task66b_prep_preflight.py`, `tests/test_task79e_r2_activation_safety.py` (+51 / −3) |
| Production / non-test code touched | **none** |

Phase F re-executed the **entire** repository suite (2927 tests) at `5955e82` and is self-sufficient. Phases A–E from attempt 2 at `320da7b8` remain valid corroboration: the only difference between the two SHAs is four test files, three of which are outside the A–E focused scope, and the fourth change (`conftest.py`) only adds two offline env defaults with no bearing on those phases.

## Phase results

| Phase | SHA | Attempt | Exit | Result | Counts |
|---|---|---|---|---|---|
| Pre-test integrity | 320da7b8 | 2 | 0 | PASS | 2 passed |
| A — focused run 1 | 320da7b8 | 2 | 0 | PASS | 300 passed |
| B — focused run 2 | 320da7b8 | 2 | 0 | PASS | 300 passed |
| C — adjacent suites | 320da7b8 | 2 | 0 | PASS | 530 passed |
| D — retained + expanded scenarios | 320da7b8 | 2 | 0 | PASS | 34 passed |
| E — guarded full collection | 320da7b8 | 2 | 0 | PASS | 2927 tests collected |
| **F — complete suite** | **5955e82** | **3** | **0** | **PASS** | **2927 passed, 0 failed, 0 errors, 0 skipped, 0 xfailed, 0 xpassed** (321 warnings, 2362.72s) |

### Rehearsal totals (Phase D, attempt 2)

- Retained scenarios 1–20: **20/20 PASS**
- Expanded scenarios 21–33: **13/13 PASS**
- Scenario 33: **PASS**
- Phase D total: **34 passed**

## Collection / full-suite reconciliation

| | |
|---|---|
| Phase E collected | 2927 |
| Phase F executed | 2927 |
| Phase F passed | 2927 |
| Reconciled | **yes** |

## Network-guard reconciliation (Phase F, `attempt3_phase_f_20260830_200809_062.network_guard.json`)

| Metric | Value |
|---|---|
| guard initialized | **true** |
| guard initialization failures | **0** |
| unexpected external attempts | **0** |
| permitted loopback connections | 881 |
| expected negative-control blocks | 4 |
| negative controls reconciled | **true** |
| malformed reports | 0 |
| leftover writer temp files | 0 |

Expected negative controls (declared == observed): `unfaked_telegram_getme` ×1 (`api.telegram.org` getaddrinfo), `block_ipv4` ×1 (`198.51.100.10`), `block_ipv6` ×1 (`2001:db8::10`), `block_hostname` ×1 (`telegram.invalid.example`). No `huggingface.co` events. `stderr.log` is 0 bytes.

## Completed repair history

Attempt 2 Phase F at `320da7b8` failed (exit 1; 6 failed / 2921 passed; guard recorded 10 unexpected `huggingface.co:443` attempts). All six failures were test-side environment fragility, not production defects. Fixed in `5955e82`:

| Failure(s) | Root cause | Fix |
|---|---|---|
| `test_task83_r3b_network_isolation::test_unfaked_telegram_is_blocked_before_external_access`, `::test_zz_guard_report_reconciles_expected_and_unexpected_attempts` | `test_task66b_prep_preflight` ran `FullAppPreflight().run()` unmocked → `brain_operational_hard_requirement` built a real `ResearchAgent` whose `ContextRetriever` eagerly constructs `SentenceTransformerEmbeddingFunction`, reaching `huggingface.co` for the embedding model. `run()`'s try/except hid it, but the session network guard recorded the attempts, breaking reconciliation + `conftest.pytest_unconfigure`. | Autouse `_offline_brain` fixture in `test_task66b_prep_preflight.py` faking `talonx_brain.consumer.ResearchAgent` (same pattern `test_task80_p1_process_guard.py` already uses); `conftest.py` sets `HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1` at import time as defense in depth. |
| `test_task65b_protected_fingerprints::test_orpb_v1_fingerprint_unchanged`, `::test_fprc_v1_fingerprint_unchanged` | `_fingerprint()` hashed raw `read_bytes()`; the detached clean-room worktree materialised the frozen files as CRLF (`core.autocrlf`) while committed blobs are LF, so the frozen fingerprints did not match. | `_fingerprint()` normalises `\r\n` → `\n` before hashing. Committed blobs are LF, so the frozen constants are unchanged (verified against both the LF main tree and the CRLF clean-room tree). |
| `test_task79e_r2_activation_safety::test_session_identity_reuse_requires_current_config_and_runtime_bindings` | Built `PivConfig` without explicit paper bindings, relying on ambient `TALONX_PIV_*` env vars that the clean-room sanitiser strips → `paper_trading=False` → `PaperGuardError` at `verify_paper_identity()`. | `PivConfig` now passes `key_id="key"`, `secret_key="secret"`, `paper_trading=True`, `real_capital=False`, `broker_endpoint=PAPER_ENDPOINT` explicitly — identical to every sibling `verify_paper_identity()` test in the file. |
| `test_task66b_prep_preflight::test_no_secrets_printed_check_never_echoes_a_token` | Asserted the env-var **name** `TELEGRAM_BOT_TOKEN` never appears in any check detail; the check's own diagnostic `"TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID missing"` (a name, not a value) tripped it once tokens were sanitised. The test's own comment says names are fine, values are not. | Assertion rewritten to confirm no configured secret **value** is echoed, permitting env-var names. |

Pre-run verification (main tree): affected 4 files (61 tests) pass with `TALONX_TEST_NETWORK_GUARD=1` and `TALONX_PIV_*` / `TELEGRAM_*` scrubbed; 111 adjacent brain/ingestion/pipeline/process-guard tests pass with the `conftest` change. Confirmed end-to-end by attempt 3 Phase F.

## Raw ignored-evidence references

Directory `results/task83_r3c_r1_cleanroom_requalification/raw_test_output/` is under the `/results/` gitignore and is **not** committed. SHA-256 of the attempt 3 Phase F artefacts:

| File | SHA-256 |
|---|---|
| `attempt3_phase_f.spec.json` | `d53cbb92f757f712f24dd951d99652c3aef69abd0fcb15e241d49eccd246e738` |
| `…_20260830_200809_062.stdout.log` | `6a9b957543da5da6c23773f5e48e08a3015baf545e0b65b44f368ca9a87c6757` |
| `…_20260830_200809_062.stderr.log` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` (empty) |
| `…_20260830_200809_062.exitcode.txt` | `13bf7b3039c63bf5a50491fa3cfd8eb4e699d1ba1436315aef9cbe5711530354` |
| `…_20260830_200809_062.status.json` | `7d63f7e5894e584f0dbc2743f5f000400b4a4d454ebc947e11d1bd57c22196ff` |
| `…_20260830_200809_062.network_guard.json` | `0dcca5b27bc8005302a429a6c6b77e9f36bfd9772f533f118b4cad713f331010` |
| `…_20260830_200809_062.environment.json` | `5c94effc42552310f149a37f9d29a0493abf81003b9be66309f9f9c4a1a6ae81` |

Attempt 1 (aborted at Phase C diagnostic) and attempt 2 (Phases A–E PASS, Phase F FAIL at `320da7b8`) artefacts remain in the same directory, preserved and unmodified.

## Protected-file and stash status

- `talonx_quant/` diff: **empty** — HEAD vs `320da7b8`, HEAD vs working tree, and clean-room worktree vs HEAD.
- QuantStateStore / IEX timestamp items remain open; untouched by this task.
- Stashes intact:
  - `stash@{0}` — `task83-r2-preexisting-partial-rehearsal-evidence`
  - `stash@{1}` — `task56-resume-ledger-intact`
  - `stash@{2}` — `task56-resume-preserve-intact-blocker`

## Worktree cleanup

Detached clean-room worktree `C:\workspace\TalonX_task83r3c_cleanroom` (task-owned) removed after the pass. Main working tree clean apart from the pre-existing untracked `.task83r2_*` temp directories (not created by this task).

## Restrictions observed

No production/non-test code modified · no external service contacted (guard confirms 0 unexpected external attempts) · no Original/PIV/Redis/dashboard launched · PAPER / experimental authorization never enabled · no holdouts accessed · no strategy tuned or approved · **R3D not started**.
