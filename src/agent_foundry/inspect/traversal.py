"""Bounded, deterministic repository traversal for read-only inspection."""

from __future__ import annotations

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


@dataclass
class TraversalResult:
    entries: list[RepoEntry] = field(default_factory=list)
    entries_visited: int = 0
    entries_skipped: int = 0
    depth_limit_reached: bool = False
    entry_limit_reached: bool = False


def _should_skip_dir(name: str) -> bool:
    if name in SKIP_DIR_NAMES:
        return True
    return name.endswith(".egg-info")


def _resolve_inside_root(root: Path, candidate: Path) -> Path | None:
    """Resolve candidate; return None if it escapes the repository root."""
    try:
        resolved = candidate.resolve()
        root_resolved = root.resolve()
        resolved.relative_to(root_resolved)
    except (OSError, ValueError, RuntimeError):
        return None
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
        except OSError:
            result.entries_skipped += 1
            return

        for child in children:
            if result.entry_limit_reached:
                return

            child_rel = f"{current_rel}/{child.name}" if current_rel else child.name

            resolved = _resolve_inside_root(root, child)
            if resolved is None:
                result.entries_skipped += 1
                continue

            is_symlink = child.is_symlink()
            is_dir = resolved.is_dir()

            if is_symlink and not is_dir:
                result.entries_skipped += 1
                continue

            if is_dir and _should_skip_dir(child.name):
                result.entries_skipped += 1
                continue

            size_bytes: int | None = None
            if not is_dir:
                try:
                    size_bytes = resolved.stat().st_size
                except OSError:
                    result.entries_skipped += 1
                    continue

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


def git_head_revision(root: Path) -> str | None:
    """Return current git HEAD SHA when readable inside *root*; never mutates the repository."""
    root = root.resolve()
    git_resolved = _resolve_inside_root(root, root / ".git")
    if git_resolved is None or not git_resolved.exists():
        return None
    head_resolved = _resolve_inside_root(root, git_resolved / "HEAD")
    if head_resolved is None or not head_resolved.is_file():
        return None
    try:
        head_ref = head_resolved.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if head_ref.startswith("ref: "):
        ref_name = head_ref[5:].strip()
        if ".." in Path(ref_name).parts:
            return None
        ref_resolved = _resolve_inside_root(root, git_resolved / ref_name)
        if ref_resolved is None or not ref_resolved.is_file():
            return None
        try:
            value = ref_resolved.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return value if _is_git_sha(value) else None
    return head_ref if _is_git_sha(head_ref) else None


def _is_git_sha(value: str) -> bool:
    return len(value) == 40 and all(char in "0123456789abcdef" for char in value.lower())
