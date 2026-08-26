"""Regenerate the committed example artifacts under `examples/e2e-synthetic/`.

Run as a module to refresh them after an intentional contract change:

    python -m tests.e2e.generate_examples

`tests/e2e/test_e2e_examples.py` fails when the committed files differ from what this
produces, so the examples cannot drift away from the code that makes them.

Everything written here comes from the synthetic fixture repository. No path, name, or
value from any other project appears in the output, and no secret value can: the only
credential in the pipeline is a `SecretRef` naming an environment variable.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_foundry.models.io import dump_yaml

from tests.e2e import support
from tests.e2e.pipeline import PipelineResult, run_pipeline

EXAMPLES_DIR = support.REPO_ROOT / "examples" / "e2e-synthetic"

# The adoption item whose change is evidenced by a real file, so the compiled bundle
# carries a real write scope. Ids are digests of the causal group key, so this is
# stable as long as the fixture and the grouping rule are.
EXAMPLE_WORK_ITEM = "wi-dcc714550913"

README = """# Example Foundry artifacts

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
"""


def _write(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)


def build_result() -> PipelineResult:
    return run_pipeline(
        support.SYNTHETIC,
        run_id="RUN-EXAMPLE-001",
        work_item_id=EXAMPLE_WORK_ITEM,
        integrations=[support.tracker_integration()],
        desired_integration_ids=[support.TRACKER_INTEGRATION_ID],
        observed_health=[support.tracker_health()],
    )


def rendered_examples() -> dict[str, bytes]:
    """Every example file, keyed by relative name."""
    result = build_result()
    validation = result.validation.model_dump(mode="json")
    return {
        "README.md": README.encode("utf-8"),
        "project-manifest.yaml": dump_yaml(result.manifest),
        "adoption-change-set.yaml": dump_yaml(result.change_set),
        "work-plan.yaml": dump_yaml(result.work_plan),
        "work-item.yaml": dump_yaml(result.work_item),
        "toolkit-lock.yaml": dump_yaml(result.project_lock),
        "task-toolkit.yaml": dump_yaml(result.task_toolkit),
        "execution-bundle.yaml": dump_yaml(result.bundle),
        "execution-contract.md": result.markdown.encode("utf-8"),
        "evidence-bundle.yaml": dump_yaml(result.evidence_bundle),
        "execution-receipt.yaml": dump_yaml(result.receipt),
        "slice-validation.json": (
            json.dumps(validation, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        ).encode("utf-8"),
    }


def write_examples(destination: Path = EXAMPLES_DIR) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, payload in rendered_examples().items():
        path = destination / name
        _write(path, payload)
        written.append(path)
    return written


if __name__ == "__main__":  # pragma: no cover - operator entry point
    for path in write_examples():
        print(path.relative_to(support.REPO_ROOT))
