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
| `toolkit-lock.yaml` | toolkit | Version-pinned Project Toolkit, with the decision record that produced it |
| `task-toolkit.yaml` | toolkit | The minimum subset resolved for one Work Item |
| `execution-bundle.yaml` | compile | The compiled execution contract for one role and one run |
| `execution-contract.md` | render | The concise agent-facing projection of that bundle |
| `evidence-bundle.yaml` | verify | Evidence for the run, typed by evidence class |
| `execution-receipt.yaml` | verify | Receipt binding the run to the exact artifacts it consumed |
| `validation-report.json` | verify | Every validator that ran, and what each returned |

## What these examples do NOT show

* **No execution runtime.** V0.1 compiles and verifies contracts. Nothing executed this
  bundle; the evidence bundle is what a runtime *would* report, and the receipt records
  that substitution as a limitation.
* **No secret values.** `IntegrationSpec.auth.credential_ref` is a `SecretRef` naming a
  provider and a name. There is no position in any of these files where a credential
  value could be written.
* **A project-supplied registry.** The builtin `builder` role declares
  `write_scope: ["src/", "tests/"]`. Adoption work touches instruction surfaces and
  build files, so these examples were produced with a registry whose builder write
  scope matches the fixture. See the V0.1 readiness report for why that is a finding.
