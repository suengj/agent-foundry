from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = REPO_ROOT / "docs" / "contracts" / "product-boundary.md"
CONSTITUTION = REPO_ROOT / "docs" / "ai" / "PROJECT_AGENT_CONSTITUTION.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_product_contract_exists_and_covers_acceptance():
    assert CONTRACT.is_file()
    text = _read(CONTRACT)
    required = [
        "Personal MVP first",
        "Business toolbox second",
        "suengj/ai-agent-dev-playbook",
        "dry-run",
        "explicit apply",
        "provider-neutral",
        "planning elapsed time",
        "manual correction rate",
        "generated-task acceptance rate",
        "duplicate/stale-context",
        "authority-boundary miss rate",
        "evidence completeness",
    ]
    for phrase in required:
        assert phrase in text, f"missing contract phrase: {phrase}"


def test_constitution_pins_playbook_without_wholesale_copy():
    assert CONSTITUTION.is_file()
    text = _read(CONSTITUTION)
    assert "suengj/ai-agent-dev-playbook" in text
    assert "daa487c" in text or "playbook.ref" in text
    assert "Linear" in text and "GitHub" in text
    assert "do not copy" in text.lower() or "not copy" in text.lower()
