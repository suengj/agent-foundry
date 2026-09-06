"""Bounded, deterministic repository traversal for read-only inspection."""

from __future__ import annotations

import errno
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Documented traversal bounds — keep in sync with TraversalLimits defaults.
DEFAULT_MAX_DEPTH = 12
DEFAULT_MAX_ENTRIES = 2000
DEFAULT_MAX_FILE_BYTES = 65_536

SKIP_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        "target",
        "vendor",
        ".next",
        ".nuxt",
        "coverage",
        "htmlcov",
        ".eggs",
        "*.egg-info",
    }
)

AGENT_RULE_RELATIVE_PATHS: tuple[str, ...] = (
    "AGENTS.md",
    "CLAUDE.md",
    ".cursorrules",
    ".github/copilot-instructions.md",
)

PACKAGE_METADATA_FILES: frozenset[str] = frozenset(
    {
        "pyproject.toml",
        "package.json",
        "Cargo.toml",
        "go.mod",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
        "Pipfile",
        "poetry.lock",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
    }
)

# Files that declare "this directory is a project in its own right". Deliberately
# narrower than PACKAGE_METADATA_FILES: a lock file or a requirements list travels with
# a project, it does not constitute one, and treating either as a boundary would split
# an ordinary repository into pieces.
NESTED_PROJECT_MARKERS: frozenset[str] = frozenset(
    {
        ".git",
        "pyproject.toml",
        "package.json",
        "Cargo.toml",
        "go.mod",
        "setup.py",
    }
)


def nested_project_roots(root: Path, entries: list[RepoEntry]) -> list[str]:
    """Directories below the root that declare themselves separate projects.

    Foundry inspects one target. A directory carrying its own project manifest is a
    distinct unit of ownership, and its `Dockerfile` is not the target's deployment,
    its `env.example` is not the target's credential surface, and its `pyproject.toml`
    is not the target's build metadata. Attributing them to the target produces a
    diagnosis of a project that does not exist — measured on Agent Foundry itself,
    where seven fixture repositories under `tests/fixtures/projects/` supplied 22 of 25
    adoption evidence references, two wrong readiness findings, and a compiled write
    scope over seven files nobody wanted changed.

    The repository root is never a nested project: it is the target. Only the outermost
    boundary is returned for any path, so a project inside a project inside the target
    is excluded once rather than twice.
    """
    boundaries: set[str] = set()
    for entry in entries:
        if entry.is_dir:
            continue
        parent, _, name = entry.relative_path.rpartition("/")
        if not parent:
            # A marker at the repository root describes the target itself.
            continue
        if name in NESTED_PROJECT_MARKERS:
            boundaries.add(parent)
    # A `.git` entry never appears in the walk at all — `.git` is a skipped directory
    # name, so nothing inside it and nothing named it is ever recorded. A separate
    # repository is the least ambiguous nested project there is, so each visited
    # directory is probed for one directly. One stat per directory, bounded by the same
    # traversal limits as everything else.
    for entry in entries:
        if not entry.is_dir:
            continue
        try:
            if (root / entry.relative_path / ".git").exists():
                boundaries.add(entry.relative_path)
        except OSError:
            continue

    outermost: list[str] = []
    for candidate in sorted(boundaries):
        if any(_is_within(candidate, other) for other in boundaries if other != candidate):
            continue
        outermost.append(candidate)
    return outermost


def _is_within(path: str, bound: str) -> bool:
    return path == bound or path.startswith(bound + "/")


def entries_outside(entries: list[RepoEntry], boundaries: list[str]) -> list[RepoEntry]:
    """Entries belonging to the target project rather than to a nested one.

    The boundary directory itself is kept: that a nested project exists is a fact about
    the target, and dropping it would make the exclusion invisible.
    """
    if not boundaries:
        return list(entries)
    return [
        entry
        for entry in entries
        if not any(
            entry.relative_path.startswith(bound + "/") for bound in boundaries
        )
    ]


# -----------------------------------------------------------------------------
# Nested-project ownership: owner-declared override
# -----------------------------------------------------------------------------
#
# `nested_project_roots` above is a heuristic, and a sound one — but an owner
# sometimes knows better than the marker: a vendored subtree with its own
# `pyproject.toml` that is nonetheless maintained as part of this project, or a
# quiet subdirectory with no marker at all that the owner wants treated as if it
# were somebody else's. Neither case is inferable from the walk; both are a
# scoping decision only the owner can make. `.foundry/project.yaml` is the
# surface Foundry already owns for owner declarations (see
# `inspect/classification.py`), so the override lives there rather than in a
# new file.
FOUNDRY_PROJECT_YAML_CANDIDATES: tuple[str, ...] = (
    ".foundry/project.yaml",
    ".foundry/project.yml",
)

# Dotted key path inside the declaration file. Kept separate from
# classification.py's `_DECLARED_PATHS` table: that table feeds manifest
# dimensions through `adopt.manifest`, and this key feeds traversal directly —
# conflating them would make one file's parsing depend on the other's schema.
NESTED_OVERRIDE_KEY_PATH: tuple[str, ...] = ("inspection", "nested_project_overrides")
NESTED_OVERRIDE_INCLUDE_KEY = "include"
NESTED_OVERRIDE_EXCLUDE_KEY = "exclude"


@dataclass(frozen=True)
class NestedProjectOverrides:
    """Owner-declared adjustment to the nested-project heuristic.

    Absent entirely (no declaration file, no key, or an explicit empty
    mapping/list) this carries no paths and `malformed=False`: that is the
    "no override declared" case, and the default heuristic applies exactly as
    before. `malformed=True` means a declaration existed but could not be
    trusted — the default heuristic still applies, but the fact that an
    override was attempted and rejected is preserved rather than discarded, so
    a reader is never left believing nothing was ever declared.
    """

    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    source_ref: str | None = None
    malformed: bool = False
    malformed_reason: str | None = None


@dataclass(frozen=True)
class NestedProjectOverrideDecision:
    """One override outcome — recorded whether or not it changed anything.

    A no-op override (naming a path that was never excluded, or that some
    other boundary already covers) is exactly as visible as one that took
    effect: silently accepting a no-op would look identical to silently
    ignoring a typo.
    """

    path: str
    action: str  # "include" (re-include a nested subtree) | "exclude" | "malformed"
    applied: bool
    reason: str


def _clean_override_path(value: object) -> str | None:
    """Normalize one declared override path, or None when it cannot be trusted.

    `.` is accepted here and rejected later, by name, when it is used to name
    the repository root — that keeps "the root can't be a nested project" a
    legible, specific decision instead of a blanket parse failure.
    """
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate:
        return None
    candidate = candidate.strip("/")
    if not candidate:
        return "."
    parts = candidate.split("/")
    if any(part in ("", "..") for part in parts):
        return None
    return candidate


def _validate_override_path_list(raw: object) -> tuple[str, ...] | None:
    """Return a normalized, deduplicated, sorted path tuple, or None if unusable."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        return None
    cleaned: list[str] = []
    for item in raw:
        path = _clean_override_path(item)
        if path is None:
            return None
        cleaned.append(path)
    return tuple(sorted(set(cleaned)))


def load_nested_project_overrides(
    root: Path,
    entries: list[RepoEntry],
    *,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> NestedProjectOverrides:
    """Read the owner's nested-project override declaration, failing closed on doubt.

    Only `.foundry/project.yaml` (or `.yml`) is consulted. Anything short of a
    clean `{include: [...], exclude: [...]}` mapping of relative path strings
    under `inspection.nested_project_overrides` is treated as malformed: an
    owner who misconfigures the override must see that it was rejected, not
    have Foundry silently fall back to "no exclusion at all" or silently guess
    at a shape.
    """
    key_label = ".".join(NESTED_OVERRIDE_KEY_PATH)
    rel = next(
        (c for c in FOUNDRY_PROJECT_YAML_CANDIDATES if c in file_path_set(entries)), None
    )
    if rel is None:
        return NestedProjectOverrides()

    content = read_text_bounded(root / rel, max_bytes=max_file_bytes)
    if content is None:
        # The declaration file exists but could not be read within bounds — that
        # is a fact `collect_unread_file_observations`/`unobservable` already
        # surfaces elsewhere; here it simply means no override was read.
        return NestedProjectOverrides(source_ref=rel)

    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError:
        return NestedProjectOverrides(
            source_ref=rel, malformed=True, malformed_reason=f"{rel} is not valid YAML"
        )

    if parsed is None:
        return NestedProjectOverrides(source_ref=rel)
    if not isinstance(parsed, dict):
        return NestedProjectOverrides(source_ref=rel)

    node: object = parsed
    for key in NESTED_OVERRIDE_KEY_PATH:
        if not isinstance(node, dict):
            node = None
            break
        node = node.get(key)
    if node is None:
        return NestedProjectOverrides(source_ref=rel)
    if not isinstance(node, dict):
        return NestedProjectOverrides(
            source_ref=rel,
            malformed=True,
            malformed_reason=f"{key_label} in {rel} must be a mapping with 'include'/'exclude' lists",
        )

    unknown_keys = set(node.keys()) - {NESTED_OVERRIDE_INCLUDE_KEY, NESTED_OVERRIDE_EXCLUDE_KEY}
    if unknown_keys:
        return NestedProjectOverrides(
            source_ref=rel,
            malformed=True,
            malformed_reason=(
                f"{key_label} in {rel} has unrecognised key(s): "
                + ", ".join(sorted(str(k) for k in unknown_keys))
            ),
        )

    include = _validate_override_path_list(node.get(NESTED_OVERRIDE_INCLUDE_KEY))
    exclude = _validate_override_path_list(node.get(NESTED_OVERRIDE_EXCLUDE_KEY))
    if include is None or exclude is None:
        return NestedProjectOverrides(
            source_ref=rel,
            malformed=True,
            malformed_reason=(
                f"{key_label} in {rel}: 'include'/'exclude' must each be a list of "
                "relative path strings"
            ),
        )

    return NestedProjectOverrides(include=include, exclude=exclude, source_ref=rel)


def resolve_nested_project_boundaries(
    root: Path,
    entries: list[RepoEntry],
    overrides: NestedProjectOverrides,
) -> tuple[list[str], list[NestedProjectOverrideDecision]]:
    """Apply an owner override to the default heuristic, one decision per entry.

    The default heuristic (`nested_project_roots`) always runs first and is
    never weakened: an override only ever adds an explicit decision on top of
    it. A malformed override changes nothing and produces exactly one decision
    explaining why. An empty override (nothing declared) changes nothing and
    produces no decisions at all — there is nothing to make visible when
    nothing was declared.
    """
    default_boundaries = nested_project_roots(root, entries)

    if overrides.malformed:
        reason = overrides.malformed_reason or "nested-project override could not be parsed"
        return default_boundaries, [
            NestedProjectOverrideDecision(
                path=overrides.source_ref or ".",
                action="malformed",
                applied=False,
                reason=f"{reason}; default heuristic applied unchanged",
            )
        ]

    if not overrides.include and not overrides.exclude:
        return default_boundaries, []

    dir_paths = {entry.relative_path for entry in entries if entry.is_dir}
    boundaries: set[str] = set(default_boundaries)
    decisions: list[NestedProjectOverrideDecision] = []

    for path in overrides.include:
        covering = next(
            (bound for bound in default_boundaries if _is_within(path, bound)), None
        )
        if covering is None:
            decisions.append(
                NestedProjectOverrideDecision(
                    path=path,
                    action="include",
                    applied=False,
                    reason="not an excluded nested-project boundary; override has no effect",
                )
            )
            continue
        boundaries.discard(covering)
        if covering == path:
            reason = f"override re-included nested-project boundary {covering}"
        else:
            reason = (
                f"override re-included nested-project boundary {covering} "
                f"(named via {path})"
            )
        decisions.append(
            NestedProjectOverrideDecision(path=covering, action="include", applied=True, reason=reason)
        )

    for path in overrides.exclude:
        if path == ".":
            decisions.append(
                NestedProjectOverrideDecision(
                    path=path,
                    action="exclude",
                    applied=False,
                    reason="the repository root can never be declared a nested project",
                )
            )
            continue
        if path not in dir_paths:
            decisions.append(
                NestedProjectOverrideDecision(
                    path=path,
                    action="exclude",
                    applied=False,
                    reason="override path does not exist as a directory in this repository",
                )
            )
            continue
        if any(_is_within(path, bound) for bound in boundaries):
            decisions.append(
                NestedProjectOverrideDecision(
                    path=path,
                    action="exclude",
                    applied=False,
                    reason="already covered by an existing nested-project boundary",
                )
            )
            continue
        boundaries.add(path)
        decisions.append(
            NestedProjectOverrideDecision(
                path=path,
                action="exclude",
                applied=True,
                reason=f"override excluded {path} as a nested-project boundary despite no project manifest",
            )
        )

    final = sorted(boundaries)
    outermost = [
        candidate
        for candidate in final
        if not any(_is_within(candidate, other) for other in final if other != candidate)
    ]
    decisions.sort(key=lambda decision: (decision.path, decision.action))
    return sorted(outermost), decisions


CI_WORKFLOW_PREFIX = ".github/workflows/"
FOUNDRY_DIR_PREFIX = ".foundry/"
CURSOR_RULES_PREFIX = ".cursor/rules/"
DOCS_AI_PREFIX = "docs/ai/"
FOUNDRY_DIR_NAME = ".foundry"


@dataclass
class RepoEntry:
    """One visited path relative to the repository root."""

    relative_path: str
    is_dir: bool
    size_bytes: int | None = None


# Why a path could not be resolved or read. "containment-refused" means looking
# would have left the repository — a deliberate decision, not a gap in evidence.
# The other two mean the OS would not let us look, which does leave a gap.
SKIP_REASON_REFUSED = "containment-refused"
UNOBSERVABLE_PERMISSION_DENIED = "permission-denied"
UNOBSERVABLE_UNREADABLE = "unreadable"


@dataclass(frozen=True)
class UnobservablePath:
    """A path whose contents could not be observed — a hole, not an absence."""

    relative_path: str
    is_dir: bool
    reason: str


@dataclass
class TraversalResult:
    entries: list[RepoEntry] = field(default_factory=list)
    entries_visited: int = 0
    # A single skip total cannot be reasoned about: a skipped cache directory means
    # "deliberately not looked at", a refusal means "looking would have left the
    # repository", and unreadable means "the OS would not let us look". Only the last
    # leaves a hole. entries_skipped stays the total of the three counters below.
    entries_skipped: int = 0
    entries_skipped_ignored_dir: int = 0
    entries_skipped_refused: int = 0
    entries_skipped_unreadable: int = 0
    unobservable: list[UnobservablePath] = field(default_factory=list)
    depth_limit_reached: bool = False
    entry_limit_reached: bool = False

    def skip_ignored_dir(self) -> None:
        self.entries_skipped += 1
        self.entries_skipped_ignored_dir += 1

    def skip_refused(self) -> None:
        self.entries_skipped += 1
        self.entries_skipped_refused += 1

    def skip_unreadable(self) -> None:
        self.entries_skipped += 1
        self.entries_skipped_unreadable += 1

    def record_unobservable(self, relative_path: str, *, is_dir: bool, reason: str) -> None:
        self.unobservable.append(
            UnobservablePath(relative_path=relative_path, is_dir=is_dir, reason=reason)
        )


# The file a Python virtual environment always carries at its root, whatever the
# directory is called. Name matching alone missed `.venv-lane`, `env`, `.direnv/python*`
# and every other local convention, and a virtualenv holds thousands of files: the
# traversal budget was spent inside it before the repository's own source was reached,
# and inspection then reported "no test entrypoints observed" about a repository with
# a full test suite. Absence of evidence produced by a truncated walk reads exactly
# like evidence of absence, so the walk must not be truncated by an environment.
VENV_MARKER_FILENAME = "pyvenv.cfg"


def _is_virtualenv_dir(path: Path) -> bool:
    """True when *path* is a Python virtual environment root, by its marker file."""
    try:
        return (path / VENV_MARKER_FILENAME).is_file()
    except OSError:
        return False


def _should_skip_dir(name: str) -> bool:
    if name in SKIP_DIR_NAMES:
        return True
    return name.endswith(".egg-info")


def _unobservable_reason(error: OSError) -> str:
    """Classify an OS refusal without leaking host-specific text into evidence."""
    if error.errno in {errno.EACCES, errno.EPERM}:
        return UNOBSERVABLE_PERMISSION_DENIED
    return UNOBSERVABLE_UNREADABLE


def _resolve_with_reason(root: Path, candidate: Path) -> tuple[Path | None, str | None]:
    """Resolve candidate inside *root*, reporting why resolution failed when it does."""
    try:
        resolved = candidate.resolve()
        root_resolved = root.resolve()
    except OSError as error:
        return None, _unobservable_reason(error)
    except RuntimeError:
        return None, UNOBSERVABLE_UNREADABLE
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return None, SKIP_REASON_REFUSED
    return resolved, None


def _resolve_inside_root(root: Path, candidate: Path) -> Path | None:
    """Resolve candidate; return None if it escapes the repository root."""
    resolved, _ = _resolve_with_reason(root, candidate)
    return resolved


def walk_repository(
    root: Path,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> TraversalResult:
    """Walk *root* with explicit depth/count limits; never follow outbound symlinks."""
    root = root.resolve()
    result = TraversalResult()

    def _visit(current: Path, current_rel: str, depth: int) -> None:
        if result.entry_limit_reached:
            return
        if depth > max_depth:
            result.depth_limit_reached = True
            return

        try:
            children = sorted(current.iterdir(), key=lambda p: p.name)
        except OSError as error:
            # The subtree exists but the OS would not list it. Recording only the
            # skip would make it indistinguishable from an empty directory.
            result.skip_unreadable()
            result.record_unobservable(
                current_rel or ".",
                is_dir=True,
                reason=_unobservable_reason(error),
            )
            return

        for child in children:
            if result.entry_limit_reached:
                return

            child_rel = f"{current_rel}/{child.name}" if current_rel else child.name

            resolved, failure = _resolve_with_reason(root, child)
            if resolved is None:
                if failure == SKIP_REASON_REFUSED:
                    result.skip_refused()
                else:
                    result.skip_unreadable()
                    result.record_unobservable(
                        child_rel,
                        is_dir=False,
                        reason=failure or UNOBSERVABLE_UNREADABLE,
                    )
                continue

            is_symlink = child.is_symlink()
            is_dir = resolved.is_dir()

            if is_symlink and not is_dir:
                result.skip_refused()
                continue

            if is_dir and (_should_skip_dir(child.name) or _is_virtualenv_dir(resolved)):
                result.skip_ignored_dir()
                continue

            size_bytes: int | None = None
            if not is_dir:
                try:
                    size_bytes = resolved.stat().st_size
                except OSError as error:
                    result.skip_unreadable()
                    result.record_unobservable(
                        child_rel,
                        is_dir=False,
                        reason=_unobservable_reason(error),
                    )
                    continue
                if not os.access(resolved, os.R_OK):
                    # The file's existence and size are observable; its content is not.
                    # It is still a visited entry, but its contents are a hole.
                    result.record_unobservable(
                        child_rel,
                        is_dir=False,
                        reason=UNOBSERVABLE_PERMISSION_DENIED,
                    )

            result.entries.append(
                RepoEntry(
                    relative_path=child_rel,
                    is_dir=is_dir,
                    size_bytes=size_bytes,
                )
            )
            result.entries_visited += 1

            if result.entries_visited >= max_entries:
                result.entry_limit_reached = True
                return

            if is_dir and not is_symlink:
                _visit(resolved, child_rel, depth + 1)

    _visit(root, "", depth=0)
    result.entries.sort(key=lambda e: e.relative_path)
    result.unobservable.sort(key=lambda u: (u.relative_path, u.reason))
    return result


def relative_posix(root: Path, path: Path) -> str | None:
    """Return repo-relative POSIX path, or None when *path* escapes *root*."""
    resolved = _resolve_inside_root(root, path)
    if resolved is None:
        return None
    return resolved.relative_to(root.resolve()).as_posix()


def file_entries(entries: list[RepoEntry]) -> list[RepoEntry]:
    return [entry for entry in entries if not entry.is_dir]


def file_path_set(entries: list[RepoEntry]) -> set[str]:
    return {entry.relative_path for entry in file_entries(entries)}


def read_text_bounded(path: Path, *, max_bytes: int = DEFAULT_MAX_FILE_BYTES) -> str | None:
    """Read a file only when its size is within *max_bytes*; return None otherwise."""
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size > max_bytes:
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def read_entry_text(
    root: Path,
    entry: RepoEntry,
    *,
    max_bytes: int,
) -> str | None:
    """Read bounded text for a file discovered by the walk."""
    if entry.is_dir:
        return None
    resolved = _resolve_inside_root(root, root / entry.relative_path)
    if resolved is None or not resolved.is_file():
        return None
    return read_text_bounded(resolved, max_bytes=max_bytes)


# git metadata files hold a ref name or a 40-char SHA; anything larger is not one.
GIT_METADATA_MAX_BYTES = 4096


def _is_existing_file(path: Path) -> bool:
    """Probe a path without letting an OS-level error escape.

    The path is built from repo-controlled content, so a hostile or merely broken
    .git/HEAD can produce a name that stat() rejects outright (ENAMETOOLONG).
    """
    try:
        return path.is_file()
    except OSError:
        return False


def _read_git_metadata(root: Path, candidate: Path) -> str | None:
    resolved = _resolve_inside_root(root, candidate)
    if resolved is None or not _is_existing_file(resolved):
        return None
    text = read_text_bounded(resolved, max_bytes=GIT_METADATA_MAX_BYTES)
    return None if text is None else text.strip()


def git_head_revision(root: Path) -> str | None:
    """Return current git HEAD SHA when readable inside *root*; never mutates the repository."""
    root = root.resolve()
    git_resolved = _resolve_inside_root(root, root / ".git")
    if git_resolved is None:
        return None
    try:
        if not git_resolved.exists():
            return None
    except OSError:
        return None

    head_ref = _read_git_metadata(root, git_resolved / "HEAD")
    if head_ref is None:
        return None

    if head_ref.startswith("ref: "):
        ref_name = head_ref[5:].strip()
        if not ref_name or ".." in Path(ref_name).parts:
            return None
        value = _read_git_metadata(root, git_resolved / ref_name)
        return value if value is not None and _is_git_sha(value) else None
    return head_ref if _is_git_sha(head_ref) else None


def _is_git_sha(value: str) -> bool:
    return len(value) == 40 and all(char in "0123456789abcdef" for char in value.lower())
