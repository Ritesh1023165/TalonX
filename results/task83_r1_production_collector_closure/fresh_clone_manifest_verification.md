# Task 83-R1 §6.9/§6.10 — Fresh-clone evidence-manifest verification

## The Task 83 defect (reproduced)

`results/task83_dashboard_comparison_qualification/evidence_manifest.json`
recorded `bytes` / `sha256` computed from the **CRLF working-tree bytes**
on Windows, while Git stores **LF-normalized blobs**. On a fresh clone
(LF working tree) 6 of 12 artifacts fail verification:

```
acceptance_matrix.md            manifest 11623 / 5cef7a5d   vs blob 11494 / a7b0ed70
offline_rehearsal_matrix.csv    manifest  3439 / 7f719b75   vs blob  3418 / 785ed380
raw_test_output/baseline_full_suite.txt   manifest 10837 / fc3dccd9   vs blob 10708 / e37ef661
raw_test_output/final_full_suite.txt      manifest  8426 / 340510b7   vs blob  8304 / bc4c6301
raw_test_output/focused_run1.txt          manifest   447 / 56ddec47   vs blob   439 / dba8296a
verification_report.md          manifest  5717 / e081349f   vs blob  5626 / b711a5af
```

(The byte deltas equal the count of `\n`→`\r\n` conversions.)

## The R1 fix

1. **LF-normalized hashing.** `_make_manifest.py::_sha256_lf` /
   `_byte_len_lf` hash `path.read_bytes().replace(b"\r\n", b"\n")`. The
   recorded value is therefore identical on a CRLF checkout and an LF
   checkout, and it equals `hashlib.sha256(<git blob bytes>)`.
2. **`.gitattributes`** pins `results/task83_r1_production_collector_closure/**`
   to `text eol=lf`, so the committed blob and a fresh checkout's working
   tree are byte-identical — verification passes even without the
   normalization step.
3. **No self-referential SHA.** The manifest records
   `content_commit` (the code/evidence commit the hashes describe), passed
   explicitly to the generator. It **excludes** `_make_manifest.py` and
   `evidence_manifest.json` themselves (`"excluded"` field).

## How it is verified

- `tests/test_task83_r1_production_loop.py::test_s33_fresh_clone_manifest_verification`
  — (a) round-trips the generator against a file with injected CRLF and
  asserts the hash/length equal the LF form; (b) when the R1 evidence is
  committed, re-hashes every artifact straight out of `git cat-file -p
  HEAD:<path>` (i.e. the exact blob a fresh clone would receive) and
  asserts zero mismatches.
- `tests/test_task83_r1_archive_integrity.py::test_verifier_detects_hash_mismatch`
  and the other `verify_archive` cases prove the runtime verifier
  (`EvidenceWriter.verify_archive`, which also uses `sha256_normalized`)
  is fail-closed against every corruption class.

## Regeneration order (§6)

The evidence manifest is regenerated **only after every hashed file is
final**, then `git add -f`'d, then the verifier is run **against the
committed blobs** (not merely the pre-commit working tree):

```
# after the last evidence edit, with the content commit already made:
.venv/Scripts/python.exe results/task83_r1_production_collector_closure/_make_manifest.py <content_commit>
git add -f results/task83_r1_production_collector_closure/evidence_manifest.json
git commit -m "docs(task83-r1): evidence manifest for <content_commit>"
# verify against committed blobs:
.venv/Scripts/python.exe -m pytest -q tests/test_task83_r1_production_loop.py::test_s33_fresh_clone_manifest_verification
```

The result of that committed-blob run is recorded in
`verification_report.md`.
