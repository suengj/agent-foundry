"""The committed examples are a checked projection of the current contracts.

An example that ages is worse than no example: it documents a shape the code no longer
produces. These tests regenerate every file and compare bytes, so an intentional
contract change fails here until `python -m tests.e2e.generate_examples` is re-run, and
an unintentional one fails here first.
"""

from __future__ import annotations

import pytest
import yaml

from agent_foundry.secrets import ConfidenceTier, scan_for_embedded_secrets

from tests.e2e import support
from tests.e2e.generate_examples import EXAMPLES_DIR, rendered_examples

EXPECTED = rendered_examples()


def test_the_examples_directory_holds_exactly_the_generated_files() -> None:
    on_disk = {path.name for path in EXAMPLES_DIR.iterdir() if path.is_file()}
    assert on_disk == set(EXPECTED)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_each_committed_example_matches_a_fresh_run(name: str) -> None:
    committed = (EXAMPLES_DIR / name).read_bytes()
    assert committed == EXPECTED[name], (
        f"{name} is stale; run `python -m tests.e2e.generate_examples`"
    )


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_no_example_carries_a_secret_or_a_private_reference(name: str) -> None:
    text = (EXAMPLES_DIR / name).read_text(encoding="utf-8")

    findings = [
        finding
        for finding in scan_for_embedded_secrets({"text": text})
        if finding.confidence_tier is ConfidenceTier.TIER_A
    ]
    assert not findings, f"{name}: {findings}"

    # A committed example must be reproducible by a reader, which means it may name
    # this repository and the fixture inside it and nothing else. An absolute path or
    # a home directory would be both unreproducible and a private reference.
    for marker in ("/Users/", "/home/", "C:\\\\", str(support.REPO_ROOT)):
        assert marker not in text, f"{name} leaks a host path: {marker}"


def test_the_structured_examples_load_back_as_contracts() -> None:
    """A committed artifact a consumer cannot load is a screenshot, not an example."""
    from agent_foundry.models import (
        AdoptionChangeSet,
        EvidenceBundle,
        ExecutionBundle,
        ExecutionReceipt,
        ProjectManifest,
        TaskToolkit,
        ToolkitLock,
        WorkItemContract,
        WorkPlan,
        load_yaml,
    )

    for name, model in (
        ("project-manifest.yaml", ProjectManifest),
        ("adoption-change-set.yaml", AdoptionChangeSet),
        ("work-plan.yaml", WorkPlan),
        ("work-item.yaml", WorkItemContract),
        ("toolkit-lock.yaml", ToolkitLock),
        ("task-toolkit.yaml", TaskToolkit),
        ("execution-bundle.yaml", ExecutionBundle),
        ("evidence-bundle.yaml", EvidenceBundle),
        ("execution-receipt.yaml", ExecutionReceipt),
    ):
        loaded = load_yaml(model, (EXAMPLES_DIR / name).read_bytes())
        assert loaded.schema_version


def test_the_example_slice_validation_covers_the_whole_catalog_and_passes() -> None:
    """A committed acceptance has to be an acceptance of everything, not of a subset."""
    import json

    from agent_foundry.verify import VALIDATOR_IDS

    validation = json.loads((EXAMPLES_DIR / "slice-validation.json").read_text())
    assert validation["not_run"] == []
    ran = {
        finding["validator_id"]
        for report in validation["reports"]
        for finding in report["findings"]
    }
    assert ran == set(VALIDATOR_IDS)
    for report in validation["reports"]:
        assert report["findings"], "an empty report is not a pass"
        assert all(
            finding["outcome"] in {"PASS", "NOT_REQUIRED"} for finding in report["findings"]
        ), report


def test_the_rendered_contract_is_much_smaller_than_the_bundle_it_projects() -> None:
    """Concision, measured rather than asserted."""
    bundle_bytes = len((EXAMPLES_DIR / "execution-bundle.yaml").read_bytes())
    markdown_bytes = len((EXAMPLES_DIR / "execution-contract.md").read_bytes())
    assert markdown_bytes < bundle_bytes // 4
    # And it does not silently drop what it leaves out.
    markdown = (EXAMPLES_DIR / "execution-contract.md").read_text(encoding="utf-8")
    bundle = yaml.safe_load((EXAMPLES_DIR / "execution-bundle.yaml").read_text())
    selected = [record for record in bundle["provenance"] if record["selected"]]
    if len(selected) > 10:
        assert "further selection record(s)" in markdown
