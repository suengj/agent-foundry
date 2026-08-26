# Example Foundry artifacts

Every file in this directory is generated, byte for byte, by running the V0.1 vertical
slice over the synthetic fixture repository at
`tests/fixtures/projects/e2e-synthetic/`. Nothing here was written by hand, and
nothing here comes from a private project.

Regenerate with:

```bash
python -m tests.e2e.generate_examples
```

`tests/e2e/test_e2e_examples.py` fails if the committed files stop matching, so these
are a checked projection of the current contracts rather than a snapshot that ages.

## What each file is

| File | Stage | What it is |
|---|---|---|
| `project-manifest.yaml` | adopt | Durable project characteristics, synthesized from the fixture's owner declaration |
| `adoption-change-set.yaml` | adopt | The current -> proposed delta, kept separate from the manifest above |
| `work-plan.yaml` | work | Causal Work Items derived from the actionable changes |
| `work-item.yaml` | work | The single Work Item the rest of these artifacts were compiled for |
| `toolkit-lock.yaml` | toolkit | Version-pinned Project Toolkit, with the decision record that produced it |
| `task-toolkit.yaml` | toolkit | The minimum subset resolved for one Work Item |
| `execution-bundle.yaml` | compile | The compiled execution contract for one role and one run |
| `execution-contract.md` | render | The concise agent-facing projection of that bundle |
| `evidence-bundle.yaml` | verify | Evidence for the run, typed by evidence class |
| `execution-receipt.yaml` | verify | Receipt binding the run to the exact artifacts it consumed |
| `slice-validation.json` | verify | Every validator in the published catalog, what each returned, and anything that could not run |

## What these examples do NOT show

* **No execution runtime.** V0.1 compiles and verifies contracts. Nothing executed this
  bundle; the evidence bundle is what a runtime *would* report, and the receipt records
  that substitution as a limitation.
* **No secret values.** `IntegrationSpec.auth.credential_ref` is a `SecretRef` naming a
  provider and a name. There is no position in any of these files where a credential
  value could be written.
* **A narrower grant than the Work Item asked for.** The compiled write scope is the
  intersection of the Work Item scope with the envelope the fixture declares in
  `.foundry/project.yaml` under `authority.write_scope`. Nothing here uses a custom
  registry: the builtin one is used as shipped.
