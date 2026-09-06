# SUE-580 — ProjectProfile before/after survey

> **Superseded in part — re-run owed before merge.** Every figure below measures
> `ba9afa7`. An independent review over `1e04359` found the confidence collapse
> reported in "One finding this survey turns from a worry into a measurement" to
> be a provenance-laundering defect rather than a design question, and it has
> since been fixed: `_conventions_dimension` no longer reports a global `min()`,
> and no subject inherits another's provenance or confidence. The "mid → low, 8
> of 12" rows and that section therefore describe behaviour the branch no longer
> has. The method, the target set and the privacy argument are unchanged and
> still hold. The table is left as measured rather than edited in place, because
> a survey rewritten to match a later commit is not a measurement; the numbers
> are being regenerated against the merge head.

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
  at `ba9afa7`.
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

| Measurement | Before (`0765a4d`) | After (`ba9afa7`) | Delta |
|---|---|---|---|
| Repositories surveyed | 12 | 12 | 0 |
| Failures | 0 | 0 | 0 |
| Dimensions per profile — min / median / max | 31 / 31 / 31 | 31 / 31 / 31 | 0 |
| Dimensions resolved — min / median / max | 17 / 29 / 31 | 17 / 29 / 31 | 0 |
| Dimensions UNKNOWN — total | 68 | 68 | 0 |
| Dimensions CONFLICTED — total | 0 | 0 | 0 |
| Per-dimension resolved / unknown / conflicted breakdown | — | — | **no dimension moved** |
| Attributions — total | 304 | 304 | 0 |
| Attributions — DECLARED | 113 | 113 | 0 |
| Attributions — OBSERVED | 169 | 168 | −1 |
| Attributions — INFERRED | 22 | 23 | +1 |
| Attributions — NORMATIVE | 0 | 0 | 0 |
| Attributions with an evidence ref | 221 | 222 | +1 |
| Attributions with no evidence ref | 83 | 82 | −1 |
| Attributions carrying a confidence | 171 | 171 | 0 |
| Attribution confidence — high (≥ 0.75) | 157 | 157 | 0 |
| Attribution confidence — mid (0.25–0.75) | 14 | 6 | −8 |
| Attribution confidence — low (< 0.25) | 0 | 8 | +8 |
| Readiness findings — total | 103 | 115 | +12 |
| Readiness findings — blockers | 0 | 0 | 0 |
| Repositories with an exhaustive walk | 11 of 12 | 11 of 12 | 0 |
| Repositories with a resolved project name | 8 of 12 | 8 of 12 | 0 |

## Reading of what moved

Each figure below was traced to the specific dimension that produced it, by
re-profiling every target under both libraries and diffing per dimension. None of this
is inferred from the shape of the numbers.

* **Readiness +12 is exactly one finding per repository**, and it is the new
  always-present `inspection-completeness` finding. Blockers stay at 0 on both sides:
  the branch reports how completely it looked, and does not turn that report into a
  gate.
* **The OBSERVED → INFERRED shift of 1, and the evidence-ref shift of 1, are the same
  single attribution**: `greenfield-minimal`'s `assurance.conventions-observed`. It
  read `no-conventions-observed` at OBSERVED/1.0 with no evidence ref, and now reads
  `test-invocation` at INFERRED/0.8 citing `pyproject.toml` — the fixture does declare
  `[tool.pytest.ini_options]`, so the old answer was a **false negative** that the
  committed golden had encoded.
* **All 8 attributions that moved from the mid confidence bucket to low are
  `assurance.conventions-observed`,** in 8 different repositories. This is *not* the
  unobservability change; it is the mention demotion (0.5 → 0.15) meeting
  `_conventions_dimension`, which reports `min()` across every convention it
  aggregates. The demoted mentions become the weakest member and the whole dimension
  reports their confidence.
* **Dimension resolution did not move at all** — not in the median, not in the totals,
  and not for any individual dimension's resolved/unknown/conflicted counts. Whatever
  else this branch does, it changes no target's answer about *which* dimensions
  resolve.

### One finding this survey turns from a worry into a measurement

The third bullet is the reason this report is worth reading. Before this branch, no
surveyed repository reported a conventions dimension below 0.25. After it, **8 of 12
do — Agent Foundry's own repository among them** — and those 8 include repositories
whose `test-invocation` is backed by a structured 0.8 declaration parsed out of a real
Makefile or `pyproject.toml`. A consumer gating on confidence ≥ 0.5 would have accepted
those conventions before this branch and would reject them after it, *because the
evidence got better*.

The `min()` rule is pre-existing (SUE-579) and this branch does not touch it; only the
floor it reports moved. But the effect is caused by this branch, it is consumer-visible,
and it is now measured rather than hypothesised. It is raised for review rather than
fixed here, because the candidate fix — one attribution per convention subject, each
carrying its own confidence, which `ProfileDimension.attributions` already supports as
a list — is a change to synthesis aggregation and belongs to whoever owns that
decision, not to a late edit in this work item.

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
