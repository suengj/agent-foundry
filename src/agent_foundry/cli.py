"""Minimal bootstrap CLI for Agent Foundry."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_foundry import __version__
from agent_foundry.adopt import plan_adoption
from agent_foundry.inspect import inspect_project
from agent_foundry.models.io import dump_json, dump_yaml

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


def _cmd_inspect(args: argparse.Namespace) -> int:
    try:
        intake = inspect_project(args.project_path)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.format == "json":
        payload = dump_json(intake)
    else:
        payload = dump_yaml(intake)

    sys.stdout.buffer.write(payload)
    return 0


def _cmd_adopt(args: argparse.Namespace) -> int:
    try:
        intake = inspect_project(args.project_path)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    result = plan_adoption(intake)

    if args.format == "json":
        payload = dump_json(result)
    else:
        payload = dump_yaml(result)

    sys.stdout.buffer.write(payload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-foundry",
        description=(
            "Agent Foundry\n"
            "Provider-neutral tooling for turning new or existing projects "
            "into bounded AI-native execution environments"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    version_cmd = sub.add_parser("version", help="Show package version")
    version_cmd.set_defaults(func=_cmd_version)

    doctor_cmd = sub.add_parser("doctor", help="Validate bootstrap contract artifacts")
    doctor_cmd.set_defaults(func=_cmd_doctor)

    inspect_cmd = sub.add_parser("inspect", help="Read-only project inventory and readiness assessment")
    inspect_cmd.add_argument("project_path", help="Path to the project repository to inspect")
    inspect_cmd.add_argument(
        "--format",
        choices=("json", "yaml"),
        default="json",
        help="Structured output format (default: json)",
    )
    inspect_cmd.set_defaults(func=_cmd_inspect)

    adopt_cmd = sub.add_parser(
        "adopt",
        help="Preview greenfield bootstrap or brownfield adoption plan from inspection evidence",
    )
    adopt_cmd.add_argument("project_path", help="Path to the project repository to plan adoption for")
    adopt_cmd.add_argument(
        "--format",
        choices=("json", "yaml"),
        default="json",
        help="Structured output format (default: json)",
    )
    adopt_cmd.set_defaults(func=_cmd_adopt)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
