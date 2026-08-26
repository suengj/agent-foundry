"""Bounded, deterministic repository traversal for read-only inspection."""

from __future__ import annotations

import errno
import os
from dataclasses import dataclass, field
from pathlib import Path

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

            if is_dir and _should_skip_dir(child.name):
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
