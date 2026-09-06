# SUE-580 — ProjectProfile before/after survey

Work Item: SUE-580 — Required Evidence: "Before/after inspection/profile comparison on
multiple real repositories with only aggregate/public-safe metrics retained."

**What this report actually is:** a before/after comparison of `ProjectProfile`
aggregates over **one real repository (Agent Foundry itself) plus the 11 committed
fixture projects** — 12 repositories in total, measured with two versions of the
library over an identical set of targets. It is not a broad survey of
independently-owned real repositories. That broader survey is SUE-581's scope, and it
reuses the mechanism this report exercises without any change.

## Method

* `tests/e2e/profile_delta_survey.py` builds one `ProfileSurvey` per repository from
  `synthesize_project_profile(inspect_project(path))`, and `aggregate_profile()`
  reduces a list of them to counts. Every recorded field is an `int`, a `bool`, or a
  tuple of dimension *names* — names are string literals fixed in
  `agent_foundry.profile.synth`'s own source, never text read out of a repository.
  `tests/e2e/test_e2e_profile_delta_survey.py` proves the field-shape property
  directly and checks that no fixture's own name or path ever appears in any recorded
  value or in the final comparison payload.
* **Before** = `origin/main` at `0765a4d`. **After** = `sue-580-inspection-expansion`
  at its merge head.
* **The targets are held constant across both runs, and only the library varies.**
  This branch adds three fixture projects, so running each side against "its own"
  fixture directory would blend "we added targets" into "the code changed" and make
  every count uninterpretable. Both snapshots therefore profile the same 12 physical
  directories; the `before` run imports `agent_foundry` from an `origin/main` worktree
  and the `after` run from this branch. The measuring instrument — the survey module
  itself, which is new on this branch — is likewise held constant across both runs.
* Two versions of the library were never imported into one process; each snapshot ran
  in its own interpreter with `sys.path` pointed at a single checkout.
  **Verified, not assumed:** each run printed `agent_foundry.__file__` first. The
  before run resolved into the `origin/main` worktree, the after run into this branch.
  Neither touched the container's stray editable install, which points at an unrelated
  checkout and would have silently produced a null result.

## Targets

12 repositories: the 11 fixture projects under `tests/fixtures/projects/`, plus Agent
Foundry's own repository. No repository name, path, or content appears below — only
counts.

## Results

| Measurement | Before (`0765a4d`) | After (merge head) | Delta |
|---|---|---|---|
| Repositories surveyed | 12 | 12 | 0 |
| Failures | 0 | 0 | 0 |
| Dimensions per profile — min / median / max | 31 / 31 / 31 | 31 / 31 / 31 | 0 |
| Dimensions resolved — min / median / max | 17 / 29 / 31 | 17 / 29 / 31 | 0 |
| Dimensions UNKNOWN — total | 68 | 65 | **−3** |
| Dimensions CONFLICTED — total | 0 | 0 | 0 |
| Attributions — total | 304 | 307 | +3 |
| Attributions — DECLARED | 113 | 114 | +1 |
| Attributions — OBSERVED | 169 | 171 | +2 |
| Attributions — INFERRED | 22 | 22 | 0 |
| Attributions — NORMATIVE | 0 | 0 | 0 |
| Attributions with an evidence ref | 221 | 222 | +1 |
| Attributions with no evidence ref | 83 | 85 | +2 |
| Attributions carrying a confidence | 172 | 175 | +3 |
| Attribution confidence — high (≥ 0.75) | 158 | 170 | **+12** |
| Attribution confidence — mid (0.25–0.75) | 14 | 5 | **−9** |
| Attribution confidence — low (< 0.25) | 0 | **0** | 0 |
| Readiness findings — total | 103 | 115 | +12 |
| Readiness findings — blockers | 0 | 0 | 0 |
| Repositories with an exhaustive walk | 11 of 12 | 11 of 12 | 0 |
| Repositories with a resolved project name | 8 of 12 | 8 of 12 | 0 |

Per-dimension movement, the only three that moved, each in exactly one repository:

| Dimension | Resolved before → after | UNKNOWN before → after |
|---|---|---|
| `operating.deploy-surface` | 11 → 12 | 1 → 0 |
| `integration.config-surface` | 11 → 12 | 1 → 0 |
| `testability.config-schema` | 11 → 12 | 1 → 0 |

## Reading of what moved

Each figure was traced to the dimension that produced it, by re-profiling every
target under both libraries and diffing per dimension. None of it is inferred from
the shape of the numbers.

* **Readiness +12 is exactly one finding per repository** — the new always-present
  `inspection-completeness` finding. Blockers stay at 0 on both sides: the branch
  reports how completely it looked and does not turn that report into a gate.
* **Three dimensions stopped being UNKNOWN, all in the one repository whose walk
  was not exhaustive** (Agent Foundry itself, which has three source files over the
  64 KB read limit). `operating.deploy-surface`, `integration.config-surface` and
  `testability.config-schema` are decided by filenames on the entry list; a file
  skipped for *size* is still an entry with a known name, so its content cannot
  change those answers. Before the branch's final round they were gated as though
  it could. Path holes — a depth limit, an entry limit, a containment refusal, an
  unobservable path — still gate everything, and a fourth and fifth dimension in
  the same repository (`testability.ci-entrypoint`, `testability.lint-type-entrypoint`)
  stay UNKNOWN because their subject sets are fed by Makefile *content*, which an
  unread file genuinely could hide. The gate narrowed to what it can justify; it
  did not open.
* **Confidence rose: +12 high, −9 mid, and nothing in the low bucket.** This is
  where an earlier draft of this report was wrong, and the correction is the point.
  That draft measured 8 attributions dropping into the low bucket and read it as a
  design question about aggregation. It was a defect: `_conventions_dimension`
  reported a global `min()` and a hardcoded `INFERRED`, so a `DECLARED`
  `test-invocation` parsed out of `pyproject.toml` at 0.8 was republished as
  inferred-at-0.15 whenever any prose mention sat beside it. It now groups by
  subject, takes each subject's strongest evidence, and preserves a single
  contributing provenance kind — so the low bucket is empty and one attribution
  moved from INFERRED to DECLARED.
* **The remaining +3 attributions and +2 OBSERVED are the three newly-resolved
  dimensions**, each contributing one `none-observed` attribution where it
  previously contributed none.
* **No dimension became CONFLICTED, and the resolved median did not move.**

## Honesty about the sample

This is one real repository plus 11 small, largely synthetic fixtures. It is **not** a
broad survey of independently-owned real repositories, and none of the figures above
should be read as more general than that. `docs/foundry/v0.1-readiness-report.md` §4
makes the same disclosure about its own local sample, for the same reason: the targets
that would make it broader are not committed to this branch and cannot be. The broader
real-repository survey is SUE-581's scope; it reuses
`tests/e2e/profile_delta_survey.py` unchanged as its method.

## Reproducing this

The targets must be the same physical directories for both runs, or the delta measures
the target set instead of the code:

```bash
# From a checkout of the "after" ref. BEFORE_SRC is the src/ of a worktree or clone
# of the "before" ref; the survey module and the targets both come from here.
PYTHONPATH="$BEFORE_SRC:$PWD" python -m tests.e2e.profile_delta_survey snapshot \
    tests/fixtures/projects/*/ . > before.json

PYTHONPATH="$PWD/src:$PWD" python -m tests.e2e.profile_delta_survey snapshot \
    tests/fixtures/projects/*/ . > after.json

python -m tests.e2e.profile_delta_survey compare before.json after.json
```

Print `agent_foundry.__file__` in each snapshot process and check it before trusting
the result. An import that silently resolves to the wrong checkout produces a clean,
plausible, entirely meaningless comparison.

`tests/e2e/test_e2e_profile_delta_survey.py` runs the survey and the comparison over
the committed fixtures on every test run and asserts the structural privacy property of
both, so this report's numbers are a one-off snapshot of a continuously exercised
mechanism rather than a claim resting only on this document.
