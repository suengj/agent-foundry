from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = REPO_ROOT / "docs" / "contracts" / "product-boundary.md"
CONSTITUTION = REPO_ROOT / "docs" / "ai" / "PROJECT_AGENT_CONSTITUTION.md"
OVERVIEW = REPO_ROOT / "docs" / "foundry" / "00-overview.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_product_contract_exists_and_covers_public_boundaries():
    assert CONTRACT.is_file()
    text = _read(CONTRACT)
    required = [
        "provider-neutral",
        "Greenfield",
        "Brownfield",
        "Objective",
        "Work Package",
        "Work Item",
        "Project Toolkit",
        "Task Toolkit",
        "dry-run",
        "explicit apply",
        "credential references",
        "raw secrets",
        "evidence completeness",
    ]
    for phrase in required:
        assert phrase in text, f"missing product contract phrase: {phrase}"


def test_constitution_freezes_core_agent_foundry_invariants():
    assert CONSTITUTION.is_file()
    text = _read(CONSTITUTION)
    required = [
        "Provider-neutral core",
        "Causal work decomposition",
        "Brownfield is first-class",
        "Evidence over agent self-report",
        "Secrets are referenced, never embedded",
        "Public contracts are self-contained",
    ]
    for phrase in required:
        assert phrase in text, f"missing constitution invariant: {phrase}"


def test_operating_model_has_no_private_dependency_language():
    assert OVERVIEW.is_file()
    text = _read(OVERVIEW).lower()
    forbidden = [
        "ai-agent-dev-playbook",
        "trading lab",
        "signal trading",
        "~/developer/pjt",
    ]
    for phrase in forbidden:
        assert phrase not in text, f"private/internal reference leaked: {phrase}"
