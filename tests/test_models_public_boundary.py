"""Provider-neutrality scan over models sources and fixtures."""

from __future__ import annotations

import re
from pathlib import Path

FORBIDDEN_IDENTIFIERS = [
    "openai",
    "anthropic",
    "claude",
    "gpt",
    "gemini",
    "cursor",
    "codex",
    "copilot",
    "linear",
    "github",
    "jira",
    "slack",
]

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = REPO_ROOT / "src" / "agent_foundry" / "models"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"

# Match whole words only to avoid false positives like "wrap" matching nothing bad.
PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(word) for word in FORBIDDEN_IDENTIFIERS) + r")\b",
    re.IGNORECASE,
)


def _scan_paths(paths: list[Path]) -> list[str]:
    violations: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for match in PATTERN.finditer(text):
            violations.append(f"{path.relative_to(REPO_ROOT)}:{match.group(0)}")
    return violations


def test_models_sources_are_provider_neutral() -> None:
    paths = sorted(MODELS_DIR.glob("**/*.py"))
    violations = _scan_paths(paths)
    assert violations == [], f"forbidden identifiers found: {violations}"


def test_fixtures_are_provider_neutral() -> None:
    paths = sorted(FIXTURES_DIR.glob("**/*"))
    text_paths = [p for p in paths if p.is_file() and p.suffix in {".yaml", ".yml", ".json"}]
    violations = _scan_paths(text_paths)
    assert violations == [], f"forbidden identifiers found: {violations}"
