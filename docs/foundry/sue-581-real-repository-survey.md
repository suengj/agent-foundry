# SUE-581 — ProjectProfile usability and correction evidence over real repositories

Work Item: SUE-581 (AF24). The question is not whether `ProjectProfile` runs. It is
whether it materially reduces V0.1's defining usability failure: an undeclared
brownfield project resolving to empty or nearly empty operating state.

The short answer is that it improves one half of that and does not touch the other,
and this report is mostly about being precise on which half is which.

## Method

### Corpus

Nine public repositories plus Agent Foundry itself and one adversarial construction,
chosen to be materially different in build, test and runtime shape rather than by
project category:

| target | shape |
|---|---|
| `pallets/click` | Python library, `pyproject.toml` only |
| `benoitc/gunicorn` | Python runtime/service — Makefile, tox.ini, mkdocs.yml, pyproject.toml |
| `chalk/chalk` | Node package, `package.json`, 35 files |
| `spf13/cobra` | Go library, `go.mod` + Makefile |
| `BurntSushi/ripgrep` | Rust, `Cargo.toml` |
| `cncf/foundation` | governance/docs — no build markers at all |
| `github/opensource.guide` | editorial static site — Gemfile, `_config.yml`, package.json |
| `norvig/pytudes` | research notebooks, 258 MB |
| Agent Foundry | Python, `.foundry/project.yaml` owner declaration |
| adversarial | three files, constructed — see below |

Public repositories were chosen deliberately, not as a fallback for private ones. Two
reasons. The survey is reproducible by anyone with the commands in this document, and
— more importantly — **each repository's own declared configuration is independently
verifiable reference evidence**. No label in the correction taxonomy below was invented
by inspection or by a model; every one is a fact a reader can check in the repository.

### Privacy shape

`tests/e2e/real_repository_survey.py` follows the structural argument
`friction_survey.py` and `profile_delta_survey.py` already established: privacy is a
property of the record's type, not a promise about how it is used. Every field is an
`int`, a `bool`, or a tuple of Foundry's own vocabulary — **except** `repository_label`,
the one deliberate identity field, which an operator supplies and which is never derived
from a target's contents. Three tests hold that line: every other field's annotation is
checked; a supplied label is asserted to reach that field and nothing else, including the
computed rejection reasons; and with the label left blank nothing else leaks, which is
the property a future private target depends on.

### What "correction rate" means here, and what it does not

SUE-581's scope names a "correction rate after human review". **No human review pass
occurred**, so no number in this document is a human-reviewed correction rate and none
is presented as one. What is measured instead is agreement against the reference facts
above. That is weaker in one specific way — it can only catch disagreements about facts
a repository declares — and stronger in another: it cannot drift, because the reference
is the repository, not a judgement.

## V0.1 → V0.2

`plan_adoption(intake).manifest` populated fields is the V0.1 usability proxy: it is
what the toolkit and every downstream compilation actually read.

| target | V0.1 manifest | V0.1 roles | V0.2 dims resolved | classification resolved | authority UNKNOWN | conv (structured) | unread |
|---|---|---|---|---|---|---|---|
| agent-foundry | **16**/16 | 3 | 29/31 | 15/15 | 0/2 | 2 (1) | 4 |
| pallets_click | 1/16 | 0 | 16/31 | 1/15 | 2/2 | 8 (1) | 5 |
| spf13_cobra | 1/16 | 0 | 16/31 | 1/15 | 2/2 | 4 (0) | 3 |
| benoitc_gunicorn | 1/16 | 0 | 15/31 | 1/15 | 2/2 | 12 (1) | 6 |
| BurntSushi_ripgrep | 1/16 | 0 | 15/31 | 1/15 | 2/2 | 8 (0) | 7 |
| cncf_foundation | 1/16 | 0 | 15/31 | 1/15 | 2/2 | 7 (0) | 16 |
| github_opensource.guide | 1/16 | 0 | 15/31 | 1/15 | 2/2 | 5 (1) | 25 |
| chalk_chalk | 1/16 | 0 | 14/31 | 1/15 | 2/2 | 2 (1) | 2 |
| norvig_pytudes | 1/16 | 0 | 14/31 | 1/15 | 2/2 | 1 (0) | **104** |
| adversarial | **16**/16 | 2 | **31**/31 | 15/15 | 0/2 | 2 (0) | 0 |

Aggregate: 8 of 10 targets have a manifest of 1/16; `v01_repositories_resolving_any_role
= 2` — only the two declared ones; `classification_dimensions_unknown_total = 112`;
`authority_dimensions_unknown_total = 16`, being 8 targets with *every* authority
dimension unknown; `conventions_inferred_total = 46` against
`conventions_structured_total = 5`.

### Where it improves

For the eight undeclared repositories the profile adds 13–15 structural dimensions each
— deploy surface, package metadata, CI and test entrypoints, config schema, integration
surface, instruction fragmentation, ownership boundaries, traversal accounting — carrying
109 attributions with evidence refs across the corpus. Under V0.1 those repositories
produced a manifest with one populated field and nothing else. **Undeclared brownfield
state went from almost entirely illegible to substantially described, with evidence.**

### Where it does not improve — stated plainly

**The V0.1 manifest goes from 1/16 to 1/16, and the toolkit from 0 roles to 0 roles.**
`synthesize_project_profile` is imported only by `cli.py`; it feeds no downstream
consumer. So the profile improves *legibility* and improves *operating readiness* not at
all. The substantive half — the 15 classification dimensions an owner declares or
inference supplies — stays at 1 of 15 for every undeclared repository.

`test_toolkit_readiness_does_not_move_with_profile_coverage` pins this, so the
non-improvement cannot later be quoted away by pointing at a rising dimension count.

This is the honest answer to the acceptance criterion asking where ProjectProfile
improves *or fails to improve* V0.1 usability. It is not a defect — nothing in M1
claimed the profile would populate the manifest — but anyone reading "coverage went from
1 to 15 dimensions" as "projects are now 15× more ready to compile" would be wrong.

## Correction taxonomy

Measured against the reference facts. Every row is checkable in the repository itself.

| target | verifiable declared fact | Foundry | verdict |
|---|---|---|---|
| pallets/click | `pyproject.toml [tool.pytest.ini_options]` | `test-invocation` DECLARED 0.8 | correct |
| benoitc/gunicorn | `pyproject.toml [tool.pytest.ini_options]` | `test-invocation` DECLARED 0.8 | correct |
| chalk/chalk | `scripts.test = "xo && c8 ava && tsc …"` | DECLARED 0.8, quoted verbatim, no runner claimed | correct |
| github/opensource.guide | `scripts.test = "script/test"` | DECLARED 0.8, quoted verbatim | correct |
| **spf13/cobra** | **Makefile `test:` → `go test -v …`** | **no `test-invocation`** | **false negative** |
| BurntSushi/ripgrep | nothing Foundry parses | none | correct — missing is the right answer |
| cncf/foundation | no build markers at all | none | correct |
| norvig/pytudes | no markers; 104 files unread | none, and absence not asserted | correct |
| agent-foundry | `.foundry/project.yaml` | declared values preserved as DECLARED | correct |

**False positives: 0 of 9.** No convention was claimed that the repository does not
support. That is the direction the product rule cares about — a false convention is worse
than a missing one — and it is clean across the corpus.

**False negatives: 1 of 9**, tracked as SUE-641. `inspect/conventions.py` emits a
Makefile `test-invocation` only when the recipe invokes pytest, so cobra's `go test`
yields nothing. It is bounded rather than fixed, for reasons stated in that issue: it
fails in the safe direction, the *existence* of a test surface is still captured
(cobra's `testability.test-entrypoint` resolves to `"Makefile declares 'test' target"`),
and the remaining work is a real design choice — a Makefile recipe is a sequence of
lines, and cobra's begins with `$(info …)` before the command, so quoting the first line
would be misleading.

### Absence handled correctly under real load

`BurntSushi/ripgrep` resolves `testability.test-entrypoint` to **UNKNOWN**, not to a
confident `none-observed`, because seven files went unread. This is the branch's central
claim holding on a real repository rather than a fixture: the walk could not see the
evidence, so no absence is asserted.

## The adversarial case

`build_adversarial_project` writes exactly three files: one `.foundry/project.yaml`
declaring every characteristic with valid values, one `AGENTS.md` carrying two prose
lines, and nothing else. The result:

**31 of 31 dimensions resolved. 0 unknown. 0 conflicted. Walk fully exhaustive. V0.1
manifest 16/16.** Every number a scorer would look at is maximal, from three files.

`rejection_reasons` is a property computed from the record's own counts, and returns
four: `single-source-classification` (all 15 classification dimensions DECLARED from one
source), `uncorroborated-authority-declaration`, `conventions-without-structured-declaration`,
and `evidence-sparse-coverage` (3 distinct evidence sources under 31 resolved dimensions).

Two properties make this more than a hand-written note. `dataclasses.replace` on the
underlying counts changes the verdict, so the signal is computed rather than annotated.
And Agent Foundry is *also* declared and high-coverage yet does **not** trip
`evidence-sparse-coverage` — so the signal discriminates rather than firing on any
declaration.

There is no `correct` field anywhere in the record. `coverage_is_supported` is documented
and tested as the *absence of a reason to reject*, never as certification.

Honest limitation: `single-source-classification` and `uncorroborated-authority-declaration`
fire on **both** declared targets in this corpus. That is a true property of V0.2 — a
declaration is never corroborated by observation — but those two reasons therefore do not
discriminate between a rich declaration and an empty one. Only `evidence-sparse-coverage`
and `conventions-without-structured-declaration` do.

## Inspection truncation — not where it was expected

No repository hit the entry or depth limit. `pytudes` is 258 MB but only 229 filesystem
entries, so size did not translate into traversal pressure at all.

The binding bound is `max_file_bytes = 65536`: **172 files unread across the corpus**,
104 of them in `pytudes` (46% of its visited entries), 25 in `opensource.guide`, 16 in
`cncf/foundation`. So 9 of 10 walks are non-exhaustive **for content and never for
paths**, which is exactly what gates the content-derived dimensions to UNKNOWN while
leaving filename-derived ones resolved.

That distinction — introduced in SUE-580 and argued there from fixtures — is what the
real corpus exercises, and it is doing the work it was built for. Had content and path
holes still been conflated, every one of these nine repositories would have had its
filename-derived dimensions forced to UNKNOWN by an unread notebook.

## Authority

`authority_dimensions_unknown_total = 16`: eight repositories with **every**
authority-bearing dimension unknown. This is recorded and deliberately not optimised. An
undeclared project leaving `execution.autonomy` and `impact.external_effect` unknown is
the correct outcome, and a test pins it as such rather than treating it as a coverage gap
to close. `adoption_changes_requiring_explicit_authority_total = 0` across the corpus.

Authority-bearing dimensions are derived from `adopt.authority.AuthorityAxis` —
production's own definition of what moves the authority envelope — rather than from a
list restated in the harness.

## Reproducing

```bash
mkdir /tmp/corpus && cd /tmp/corpus
for r in pallets/click benoitc/gunicorn chalk/chalk spf13/cobra \
         BurntSushi/ripgrep cncf/foundation github/opensource.guide norvig/pytudes; do
  git clone --depth 1 "https://github.com/$r.git" "$(echo $r | tr '/' '_')"
done

PYTHONPATH="src:." python -m tests.e2e.real_repository_survey \
    --public-labels --under /tmp/corpus --label agent-foundry=. \
    --adversarial /tmp/adversarial
```

Print `agent_foundry.__file__` and check it before trusting the result: an import that
silently resolves to another checkout produces a clean, plausible, meaningless survey.
