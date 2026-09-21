# Merge method

- Divergence audit: `main` (5f55538) is a strict ancestor of the frozen release; 0 main-only commits; merge-tree clean -> a fast-forward is history-possible.
- **Direct push to `main` is refused by the repository ruleset `MergePull` (active, no bypass actors): "Changes must be made through a pull request."** (`git push origin main` -> GH013.)
  The rule was NOT bypassed.
- **MERGE METHOD: MERGE_COMMIT via pull request** (`gh pr merge --merge`). A merge commit keeps every SHA - including the frozen release SHA `a56ec8c` and tag `v2-paper-rc1` -
  reachable from `main`. Squash and rebase were NOT used (they would rewrite/erase the frozen SHA and the milestone history). No force push, no reset of `main`, no history rewrite.
- Because `main` had no independent commits, the merge commit's tree is identical to the feature branch tree (verified after merge: `git diff <feature tip> main` is empty).
- Local verification was done on a fast-forwarded local `main` (same tree) BEFORE the PR merge; results in `17_post_merge_verification.txt` / `18_smoke_test_evidence.txt`.
- The feature branch is NOT deleted.
