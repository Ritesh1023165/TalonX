# ERM nominee: owner GO for the single locked historical validation (window B)

**Received:** 2026-10-06. The session's first action under this GO ran at 07:12:38Z (08:12 Europe/London).

**Bound to:**

| Binding | Value |
|---|---|
| Protocol | `ERM_NOMINEE_PROTOCOL_FINAL.md` `7e71fabc9ed68e6de99981839a97d75d235792e1ca57decd98bd735194613043` |
| Protocol lock | `55a31d24a7d1e9d2eecc03073af0e29e89bc2f8bc1530798c6b14cc6e0440829` |
| Implementation aggregate | `ce924d902d620a873d6bf693e0e590b6ac066d4ce8117deddf04ff96a942c75e` (built from `d23d9fe`) |
| Implementation lock | `1584e460676f3d3703588b05860f45a44f4b90905d692d9307bc1ad02734a0b3` |
| Config | `d8ad21af7d7f646373947041b8cd86e76057889d0386e099cd0307710c8bdf90` |
| Decision fields | `b430eead25ae05cbf0ec6172fb4667de15274b75a6733abe78fc50a0824c09b3` |
| Decision record | `33095e0e0329907ae070de0c2e893f71cf3b7bfec1fdda3c98357f035d250355` |

**Hypothesis identifier.** The GO names `GAP_UP_10|SHORT|H10|L1_V1`. This is the locked final protocol's own identifier,
verbatim in its title and in every draft title since r8. The protocol lock binds that protocol to the locked config,
whose hypothesis cell key is `GAP_UP_10|SHORT|H10|L1`. No other version of this nominee exists. The machine record
(`ERM_NOMINEE_VALIDATION_GO_B.json`) carries the config key, because the release validates that field.

**Window and scope.**

- Window B: 2024-01-02..2026-09-30.
- R = 2026-10-06.
- Scope: the locked template instantiated with R (broad endpoints to R+1 = 2026-10-07; identity renames
  2026-10-01..2026-10-06).

## GO text (verbatim)

GO: execute the single locked historical validation for GAP_UP_10|SHORT|H10|L1_V1, window B, subject to the prerequisites and boundaries below.

This prompt is the separate owner GO. It authorises the scoped release, protected acquisition, recorded reserve consumption and one statistical validation run. It does not authorise changing the hypothesis, rules, costs, universe definition, estimator or acceptance criteria.

AUTHORISATION
- Hypothesis: GAP_UP_10|SHORT|H10|L1_V1. Verify the canonical identifier matches the locked configuration exactly; do not guess aliases.
- Window B: 2024-01-02..2026-09-30.
- Acquisition reference date R: 2026-10-06.
- Scope: exactly the locked template instantiated with R, including approved warmup and metadata categories.
- Acknowledge consumption of the overlapping Task75 reserved windows and the reserved 2025–September 2026 data through the documented release/acquisition process.
- Use only the locked implementation and protocol.
- Observe the existing R5 off-hours restrictions.
- No automatic switch to window A or another data source.

EXPECTED LOCKED BASELINE
Branch: research/erm-nominee-validation-plumbing @ 90c4755, pushed.
Implementation built from d23d9fe.

SHA-256:
- Protocol:
  7e71fabc9ed68e6de99981839a97d75d235792e1ca57decd98bd735194613043
- Protocol lock:
  55a31d24a7d1e9d2eecc03073af0e29e89bc2f8bc1530798c6b14cc6e0440829
- Implementation aggregate:
  ce924d902d620a873d6bf693e0e590b6ac066d4ce8117deddf04ff96a942c75e
- Implementation lock:
  1584e460676f3d3703588b05860f45a44f4b90905d692d9307bc1ad02734a0b3
- Config:
  d8ad21af7d7f646373947041b8cd86e76057889d0386e099cd0307710c8bdf90

Live checkout last reported at 0b2967d. Leave the live application and all trackers untouched.

1. PREFLIGHT BEFORE RELEASE
Read repository instructions and the final protocol, decisions, locks and release procedure.

Verify:
- Actual branch/HEAD and remote state.
- Every locked hash and the complete scope template.
- No uncommitted scoring-relevant changes.
- Existing attempt ledger, release journal, run directories and completion markers.
- No prior scoring attempt or competing validation process.
- Required credentials are available without printing them.
- Adequate disk space and operational isolation.

Determine the next permitted acquisition window and the exact locked interpretation of the R+1 envelope.
Use request-volume estimates from existing evidence only; do not probe protected inputs before release.

If acquisition cannot reasonably fit inside the authorised envelope, stop before release and report the timing blocker. Do not repin R or widen scope yourself.

2. RECORD GO AND ACTIVATE THE SCOPED RELEASE
Record this authorisation verbatim with its receipt timestamp and the bound hypothesis, window, R, protocol, implementation, configuration and decision hashes.

Use the reviewed activation mechanism and journal:
PREPARED → ERM audit → Task75 ledger → ACTIVE.

Verify the completed release matches the locked scope exactly.
Do not manually edit guards, bypass the journal or broadly unlock other studies.

Record separately:
- Permission/reservation changes at activation.
- Data actually retrieved and exposed during acquisition.

An interrupted activation must remain fail-closed.

3. RUN THE S&P PREREQUISITE FIRST
During permitted acquisition hours, make the locked S&P request first.

Validate:
- Snapshot format and increasing dates.
- Coverage through 2026-09-30 under the locked rule.
- Response scope and archive hashes.

If insufficient:
- Stop as ACQUISITION_BLOCKED before other acquisition or scoring.
- Preserve the response, exposure record and attempt ledger.
- Do not label the strategy FAIL.
- Do not switch window/source or repeatedly poll for a newer file.
- Report the blocker.

4. ACQUIRE THROUGH THE LOCKED PRODUCTION PATH
If the prerequisite passes, continue the locked workflow:
base metadata → R1 scope → bars → candidate-event dates/identities → filing headers/issuer evidence → descriptive metadata → completeness → archive manifest.

Enforce:
- Guards before every request and load.
- Exact category/date envelopes, including broader metadata.
- Fixed R and provider identity/as-of semantics.
- Required-input failures stop before scoring.
- Acquisition failures never become absent evidence or silent exclusions.
- Optional metadata handling exactly as locked.
- No interim outcome inspection or manual analysis of promising events.

Preserve archives and per-request provenance. Do not alter implementation to work around an unexpected provider response.

5. APPLY THE LOCKED ATTEMPT POLICY
Use the existing ledger per hypothesis/window. Do not reset it through a new directory, run ID or process.

- Request-level retries: only the locked bounded policy.
- At most two acquisition executions total.
- One acquisition retry may be used only for a documented recoverable pre-outcome failure, under unchanged rules, hashes and authorised scope.
- Do not spend the retry on a known structural coverage failure without evidence that it is recoverable.
- No automatic retry after the outcome stage starts, even if no final output file was written.
- A second pre-outcome failure stops for owner review.
- No reference-date repinning or envelope expansion.
- Preserve every partial attempt and exposure record.

6. SCORE EXACTLY ONCE
After successful acquisition, completeness, hash and manifest checks:
- Enter the outcome stage once.
- Compute the locked primary metric, G1–G4, classification and declared diagnostics.
- Report every result, favourable or unfavourable.
- Do not tune, rerank, evaluate another cell or substitute a window.
- Write final reports and the completion marker according to the locked workflow.

If execution fails after outcome-stage entry, preserve everything and report INCOMPLETE_AFTER_OUTCOME_EXPOSURE. Do not fix-and-rerun automatically.

7. DURABLE EXECUTION IF WAITING IS REQUIRED
Do not rely on a foreground sleep or this Claude session staying alive.

If execution must wait for permitted hours:
- Use one durable, one-off task invoking the locked command and exact configuration.
- Record its trigger in UTC and Europe/London, maximum runtime, logs and output paths.
- Ensure its deadline respects the authorised envelope.
- Verify no duplicate trigger or competing launcher.
- Verify the laptop’s required power/session conditions.
- Do not weaken security settings.
- Return an interim report immediately after arming it.

A scheduled task is not a completed validation. Do not claim success until final evidence exists.

8. FINAL RESULT AND PRESERVATION
On completion, preserve and commit/push the protocol-permitted evidence and reports to the research branch or a dedicated result branch. Do not modify locked artifacts or commit secrets/large raw archives contrary to repository conventions.

Return:
- Statistical verdict, or precise acquisition/execution blocker.
- Run ID, start/end times, release identity and reference date.
- Branch/SHAs and lock verification.
- S&P prerequisite evidence.
- Acquisition/scoring attempt counts and exposure ledger.
- Event/date/symbol counts, exclusions and missing exits.
- Gross and primary net mean, CI, top-five robustness and each gate’s result.
- Declared descriptive diagnostics, clearly non-gating.
- Coverage and execution limitations.
- Paths to reports, archives/manifests, logs and completion marker.
- Confirmation no other hypothesis was tested and live runtime was untouched.

A PASS is PASS_STATISTICAL_PROXY_PRE_BORROW, not executable profitability.
A FAIL or INCONCLUSIVE receives no automatic rescue run or prospective tracker.

Complete the authorised locked run where possible, then stop and report.
