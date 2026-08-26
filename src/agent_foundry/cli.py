"""Minimal bootstrap CLI for Agent Foundry."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_foundry import __version__
from agent_foundry.adopt import plan_adoption
from agent_foundry.inspect import inspect_project
from agent_foundry.models import ProjectManifest, ToolkitLock, WorkItemContract, load_yaml
from agent_foundry.models.io import dump_json, dump_yaml
from agent_foundry.compile import compile_work_item
from agent_foundry.render import render_execution_bundle_markdown
from agent_foundry.toolkit import check_integrations, resolve_task_toolkit_for_work_item, resolve_toolkit

# Project artifacts live in a *target project*, never at a path derived from where
# this package happens to be installed. Resolving them relative to __file__ works only
# from a source checkout; from site-packages it points into the interpreter's lib
# directory, so every check fails on a clean install.
CONTRACT_RELPATH = Path("docs") / "contracts" / "product-boundary.md"
CONSTITUTION_RELPATH = Path("docs") / "ai" / "PROJECT_AGENT_CONSTITUTION.md"

# Exit codes are distinct so a caller can tell "this install is broken" from
# "this directory is not a Foundry-managed project".
DOCTOR_OK = 0
DOCTOR_PACKAGE_FAILED = 1
DOCTOR_PROJECT_FAILED = 2


def find_project_root(start: Path) -> Path | None:
    """Walk upward from `start` looking for a Foundry-managed project.

    Discovery is anchored on the project's own contract artifacts, so it works for a
    consumer project and for this repository alike, and it never consults the
    installed package's location.
    """
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / CONTRACT_RELPATH).is_file() or (
            candidate / CONSTITUTION_RELPATH
        ).is_file():
            return candidate
    return None


def _cmd_version(_: argparse.Namespace) -> int:
    print(f"agent-foundry {__version__}")
    return 0


def _package_self_check() -> list[tuple[str, bool, str]]:
    """Is the installed distribution intact and usable? Must hold anywhere."""
    checks: list[tuple[str, bool, str]] = []

    checks.append(("package version", bool(__version__), __version__ or "(unset)"))

    try:
        from agent_foundry.models.base import FOUNDRY_SCHEMA_VERSION

        checks.append(
            ("schema version", bool(FOUNDRY_SCHEMA_VERSION), str(FOUNDRY_SCHEMA_VERSION))
        )
    except Exception as exc:  # pragma: no cover - only on a broken install
        checks.append(("schema version", False, f"unavailable: {exc}"))

    try:
        from agent_foundry.toolkit import default_registry

        registry = default_registry()
        capability_count = len(registry.capabilities)
        checks.append(
            (
                "capability registry",
                capability_count > 0,
                f"{capability_count} builtin capabilities",
            )
        )
    except Exception as exc:  # pragma: no cover - only on a broken install
        checks.append(("capability registry", False, f"unavailable: {exc}"))

    return checks


def _project_check(project_root: Path) -> list[tuple[str, bool, str]]:
    """Does this target project carry the artifacts Foundry expects?"""
    contract = project_root / CONTRACT_RELPATH
    constitution = project_root / CONSTITUTION_RELPATH
    return [
        ("project root", project_root.is_dir(), str(project_root)),
        ("product contract", contract.is_file(), str(contract)),
        ("project constitution", constitution.is_file(), str(constitution)),
    ]


def _report(checks: list[tuple[str, bool, str]]) -> bool:
    failed = False
    for name, ok, detail in checks:
        print(f"[{'ok' if ok else 'FAIL'}] {name}: {detail}")
        failed = failed or not ok
    return failed


def _cmd_doctor(args: argparse.Namespace) -> int:
    print("== package self-check ==")
    package_failed = _report(_package_self_check())

    print("== project check ==")
    explicit = getattr(args, "project_path", None)
    if explicit is not None:
        project_root: Path | None = Path(explicit)
        if not project_root.is_dir():
            print(f"[FAIL] project root: {project_root} is not a directory")
            return DOCTOR_PROJECT_FAILED
    else:
        project_root = find_project_root(Path.cwd())

    if project_root is None:
        # Not being inside a Foundry-managed project is a normal state for an
        # installed package, not a broken one. Say so rather than failing.
        print("[skip] no Foundry-managed project found from the current directory")
        print("       pass a path (agent-foundry doctor PROJECT_PATH) to check one")
        return DOCTOR_PACKAGE_FAILED if package_failed else DOCTOR_OK

    project_failed = _report(_project_check(project_root))

    if package_failed:
        return DOCTOR_PACKAGE_FAILED
    return DOCTOR_PROJECT_FAILED if project_failed else DOCTOR_OK


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


def _load_manifest(path: Path) -> ProjectManifest:
    data = path.read_bytes()
    if path.suffix.lower() == ".json":
        from agent_foundry.models.io import load_json

        return load_json(ProjectManifest, data)
    return load_yaml(ProjectManifest, data)


def _cmd_resolve_toolkit(args: argparse.Namespace) -> int:
    if args.manifest:
        manifest = _load_manifest(Path(args.manifest))
    elif args.project_path:
        try:
            intake = inspect_project(args.project_path)
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        manifest = plan_adoption(intake).manifest
    else:
        print("resolve-toolkit requires project_path or --manifest", file=sys.stderr)
        return 1

    resolution, lock = resolve_toolkit(manifest)

    if args.work_item:
        work_item = load_yaml(WorkItemContract, Path(args.work_item).read_bytes())
        task_toolkit = resolve_task_toolkit_for_work_item(work_item, lock)
        payload_model = task_toolkit
    elif args.include_resolution:
        from agent_foundry.models.toolkit import ToolkitResolution

        payload_model = ToolkitResolution(
            resolved_capabilities=resolution.resolved_capabilities,
            resolved_skills=resolution.resolved_skills,
            resolved_workflows=resolution.resolved_workflows,
            integration_ids=resolution.integration_ids,
            role_ids=resolution.role_ids,
            validator_ids=resolution.validator_ids,
            permission_profile_ids=resolution.permission_profile_ids,
            budget_profile_ids=resolution.budget_profile_ids,
            decisions=resolution.decisions,
            integration_health=resolution.integration_health,
        )
    else:
        payload_model = lock

    if args.format == "json":
        payload = dump_json(payload_model)
    else:
        payload = dump_yaml(payload_model)

    sys.stdout.buffer.write(payload)
    return 0


def _cmd_compile(args: argparse.Namespace) -> int:
    if args.manifest:
        manifest = _load_manifest(Path(args.manifest))
    elif args.project_path:
        try:
            intake = inspect_project(args.project_path)
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        manifest = plan_adoption(intake).manifest
    else:
        print("compile requires project_path or --manifest", file=sys.stderr)
        return 1

    work_item_path = Path(args.work_item)
    work_item = load_yaml(WorkItemContract, work_item_path.read_bytes())

    if args.toolkit_lock:
        lock = load_yaml(ToolkitLock, Path(args.toolkit_lock).read_bytes())
    else:
        _, lock = resolve_toolkit(manifest)

    result = compile_work_item(
        work_item,
        manifest,
        lock,
        args.role_id,
        args.run_id,
    )

    if args.render:
        payload = render_execution_bundle_markdown(result.bundle).encode("utf-8")
        sys.stdout.buffer.write(payload)
        return 0

    payload_model = result.bundle if args.include_bundle else result.task_toolkit
    if args.format == "json":
        payload = dump_json(payload_model)
    else:
        payload = dump_yaml(payload_model)

    sys.stdout.buffer.write(payload)
    return 0


def _cmd_integration_check(args: argparse.Namespace) -> int:
    from agent_foundry.models import IntegrationSpec
    from agent_foundry.models.io import dump_json_raw, dump_yaml_raw, parse_json, parse_yaml

    integrations_path = Path(args.integrations)
    data = integrations_path.read_bytes()
    if integrations_path.suffix.lower() == ".json":
        raw = parse_json(data)
    else:
        raw = parse_yaml(data)
    if not isinstance(raw, list):
        print("integrations file must be a list of IntegrationSpec objects", file=sys.stderr)
        return 1

    integrations = [IntegrationSpec.model_validate(item) for item in raw]
    health = check_integrations(
        integrations,
        required_ids=args.required_id,
        observed_health=[],
    )

    payload_data = [item.model_dump() for item in health]
    if args.format == "json":
        payload = dump_json_raw(payload_data)
    else:
        payload = dump_yaml_raw(payload_data)

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

    doctor_cmd = sub.add_parser(
        "doctor",
        help="Check this installation, and a target project if one is found",
        description=(
            "Exit 0 when both checks pass or when no project is in scope; "
            "1 when the installed package itself is broken; "
            "2 when a target project is missing expected artifacts."
        ),
    )
    doctor_cmd.add_argument(
        "project_path",
        nargs="?",
        default=None,
        help="Project to check. Defaults to searching upward from the current directory.",
    )
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

    resolve_cmd = sub.add_parser(
        "resolve-toolkit",
        help="Resolve version-pinned Project Toolkit or Task Toolkit from manifest",
    )
    resolve_cmd.add_argument(
        "project_path",
        nargs="?",
        help="Path to project (inspect+adopt manifest when --manifest not set)",
    )
    resolve_cmd.add_argument(
        "--manifest",
        help="Path to ProjectManifest YAML/JSON instead of synthesizing from project",
    )
    resolve_cmd.add_argument(
        "--work-item",
        help="Path to WorkItemContract YAML for Task Toolkit resolution",
    )
    resolve_cmd.add_argument(
        "--include-resolution",
        action="store_true",
        help="Emit ToolkitResolution metadata instead of ToolkitLock",
    )
    resolve_cmd.add_argument(
        "--format",
        choices=("json", "yaml"),
        default="json",
        help="Structured output format (default: json)",
    )
    resolve_cmd.set_defaults(func=_cmd_resolve_toolkit)

    compile_cmd = sub.add_parser(
        "compile",
        help="Compile Work Item to Task Toolkit and ExecutionBundle (or rendered Markdown)",
    )
    compile_cmd.add_argument(
        "project_path",
        nargs="?",
        help="Path to project (inspect+adopt manifest when --manifest not set)",
    )
    compile_cmd.add_argument(
        "--manifest",
        help="Path to ProjectManifest YAML/JSON instead of synthesizing from project",
    )
    compile_cmd.add_argument(
        "--work-item",
        required=True,
        help="Path to WorkItemContract YAML/JSON",
    )
    compile_cmd.add_argument(
        "--toolkit-lock",
        help="Path to ToolkitLock YAML/JSON (resolve from manifest when omitted)",
    )
    compile_cmd.add_argument(
        "--role-id",
        required=True,
        help="Logical role id for the compiled bundle",
    )
    compile_cmd.add_argument(
        "--run-id",
        required=True,
        help="Execution run identifier",
    )
    compile_cmd.add_argument(
        "--render",
        action="store_true",
        help="Emit concise Markdown projection instead of structured output",
    )
    compile_cmd.add_argument(
        "--include-bundle",
        action="store_true",
        help="Emit ExecutionBundle instead of TaskToolkit (ignored with --render)",
    )
    compile_cmd.add_argument(
        "--format",
        choices=("json", "yaml"),
        default="json",
        help="Structured output format (default: json)",
    )
    compile_cmd.set_defaults(func=_cmd_compile)

    integration_cmd = sub.add_parser(
        "integration-check",
        help="Preflight integration health without exposing credentials",
    )
    integration_cmd.add_argument(
        "integrations",
        help="Path to integrations YAML/JSON (list of IntegrationSpec)",
    )
    integration_cmd.add_argument(
        "--required-id",
        action="append",
        default=[],
        dest="required_id",
        help="Integration id to check (repeatable)",
    )
    integration_cmd.add_argument(
        "--format",
        choices=("json", "yaml"),
        default="json",
        help="Structured output format (default: json)",
    )
    integration_cmd.set_defaults(func=_cmd_integration_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
