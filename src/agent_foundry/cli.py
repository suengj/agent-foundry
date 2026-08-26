"""Minimal bootstrap CLI for Agent Foundry."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_foundry import __version__

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPO_ROOT / "docs" / "contracts" / "product-boundary.md"
CONSTITUTION_PATH = REPO_ROOT / "docs" / "ai" / "PROJECT_AGENT_CONSTITUTION.md"


def _cmd_version(_: argparse.Namespace) -> int:
    print(f"agent-foundry {__version__}")
    return 0


def _cmd_doctor(_: argparse.Namespace) -> int:
    checks: list[tuple[str, bool, str]] = []

    checks.append(
        (
            "repository identity",
            (REPO_ROOT / "pyproject.toml").is_file(),
            str(REPO_ROOT),
        )
    )
    checks.append(
        (
            "product contract",
            CONTRACT_PATH.is_file(),
            str(CONTRACT_PATH),
        )
    )
    checks.append(
        (
            "project constitution",
            CONSTITUTION_PATH.is_file(),
            str(CONSTITUTION_PATH),
        )
    )

    failed = False
    for name, ok, detail in checks:
        status = "ok" if ok else "FAIL"
        print(f"[{status}] {name}: {detail}")
        failed = failed or not ok

    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-foundry",
        description="Agent Foundry\nPersonal-first AI-native project toolbox",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    version_cmd = sub.add_parser("version", help="Show package version")
    version_cmd.set_defaults(func=_cmd_version)

    doctor_cmd = sub.add_parser("doctor", help="Validate bootstrap contract artifacts")
    doctor_cmd.set_defaults(func=_cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
