"""SUE-580 Required Evidence: bounded traversal/performance test and no-mutation proof.

Three properties, each with the assertion that actually matters:

1. **Traversal is bounded.** A repository built to exceed every declared limit
   (deep nesting, many entries, an oversized file) never causes the walk to
   exceed those limits — and, because absence is not evidence, a bounded walk
   must make ``inspect_project`` say so: ``inspection-completeness`` reads as
   not fully observed, and dimensions that would otherwise claim a confident
   negative ("No test entrypoints observed") instead read "not confirmed".

2. **Performance is bounded, honestly.** The primary assertion is on work done
   (entries visited, files opened for content) rather than wall-clock time,
   because a wall-clock threshold on shared CI hardware is a flaky test by
   construction. A wall-clock assertion is included too, but only as a smoke
   check with a margin wide enough that it cannot flake, and the reasoning for
   the chosen number is written down rather than left implicit.

3. **Inspection does not mutate the target.** A full before/after snapshot
   (every path, size, mtime, content hash) proves nothing changed and nothing
   new appeared — including a case (a `.foundry/project.yaml` declaration and
   a `.git/HEAD` ref) that inspection is tempted to read-and-maybe-normalize.
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import pytest

from agent_foundry.inspect import inspect_project
from agent_foundry.inspect.traversal import walk_repository


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _build_bounded_stress_repo(root: Path, *, wide_count: int, deep_levels: int) -> None:
    """A repository engineered to exceed max_depth, max_entries, and max_file_bytes.

    - A "wide" directory holding more files than any reasonable ``max_entries``.
    - A directory nested far deeper than any reasonable ``max_depth``.
    - An oversized file, well above any reasonable ``max_file_bytes``, whose
      content is a distinctive marker that a naive "read everything" bug would
      have to have read to reproduce.
    """
    (root / "README.md").write_text("stress fixture\n")

    wide = root / "wide"
    wide.mkdir()
    for i in range(wide_count):
        (wide / f"file_{i:05d}.txt").write_text("x")

    current = root / "deep"
    current.mkdir()
    for level in range(deep_levels):
        current = current / f"level_{level:03d}"
        current.mkdir()
        (current / "marker.txt").write_text(f"depth {level}\n")

    big = root / "oversized.bin"
    big.write_bytes(b"UNREAD-MARKER-" + b"z" * 200_000)


def _snapshot_tree(root: Path) -> dict[str, dict]:
    """Full-fidelity snapshot: every path, its kind, size, mtime, and content hash.

    Uses stdlib ``os.walk`` directly (never Foundry's own walker) so the proof
    does not depend on the correctness of the code under test. ``followlinks``
    stays False — inspection itself never follows outbound symlinks, so the
    snapshot should not either.
    """
    snapshot: dict[str, dict] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        rel_dir = os.path.relpath(dirpath, root)
        for name in sorted(dirnames):
            rel = os.path.normpath(os.path.join(rel_dir, name))
            snapshot[rel] = {"kind": "dir"}
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = os.path.normpath(os.path.join(rel_dir, name))
            try:
                st = os.lstat(path)
            except OSError as error:  # pragma: no cover - defensive
                snapshot[rel] = {"kind": "stat-error", "error": str(error)}
                continue
            entry: dict = {
                "kind": "symlink" if os.path.islink(path) else "file",
                "size": st.st_size,
                "mtime_ns": st.st_mtime_ns,
            }
            if not os.path.islink(path):
                try:
                    entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                except OSError:
                    entry["sha256"] = None
            snapshot[rel] = entry
    return snapshot


def _path_depth(relative_path: str) -> int:
    return relative_path.count("/")


# ---------------------------------------------------------------------------
# Property 1 — traversal is bounded, and absence is not evidence
# ---------------------------------------------------------------------------


def test_traversal_stops_at_declared_bounds(tmp_path: Path) -> None:
    max_depth = 3
    max_entries = 150
    max_file_bytes = 1_000

    _build_bounded_stress_repo(tmp_path, wide_count=500, deep_levels=20)

    intake = inspect_project(
        tmp_path,
        max_depth=max_depth,
        max_entries=max_entries,
        max_file_bytes=max_file_bytes,
    )
    stats = intake.traversal_stats

    # The bound is never exceeded — the walk visits at most max_entries paths,
    # never more, regardless of how many files actually exist on disk (500 wide
    # + 20 deep + extras, all far more than max_entries).
    assert stats.entries_visited <= max_entries
    assert stats.entry_limit_reached is True

    # No visited entry is deeper than max_depth. relative_path uses "/" as the
    # separator (traversal.py builds child_rel with "/"), so depth is the
    # segment count.
    walked = walk_repository(tmp_path, max_depth=max_depth, max_entries=100_000)
    assert walked.entries, "sanity: the raw walk should have visited something"
    for entry in walked.entries:
        assert _path_depth(entry.relative_path) <= max_depth
    assert walked.depth_limit_reached is True

    # The oversized file was never read for content — only its size was
    # observed, and it was flagged as skipped rather than silently ignored.
    unread = [o for o in intake.observations if o.subject == "file-read-skipped"]
    assert any("oversized.bin" in o.content for o in unread)
    assert any(f"> {max_file_bytes} bytes" in o.content for o in unread)
    # No observation anywhere quotes the marker bytes that only content-reading
    # could have produced.
    assert not any("UNREAD-MARKER" in o.content for o in intake.observations)

    # --- The consequence that matters: absence is not evidence. -----------
    completeness = next(
        f for f in intake.readiness_findings if f.dimension == "inspection-completeness"
    )
    assert "not fully observed" in completeness.message
    assert completeness.severity.value == "high"

    # A dimension that would otherwise assert a confident negative ("No test
    # entrypoints observed") instead reads as withheld, because the walk that
    # would need to have been exhaustive to support that negative was not.
    testability = next(f for f in intake.readiness_findings if f.dimension == "testability")
    assert "No test entrypoints observed" not in testability.message
    assert "not confirmed" in testability.message
    assert "not fully observed" in testability.message
    assert testability.provenance.confidence == 0.0

    reproducibility = next(
        f for f in intake.readiness_findings if f.dimension == "reproducibility"
    )
    assert "not confirmed" in reproducibility.message
    assert reproducibility.provenance.confidence == 0.0


def test_fully_covered_small_repo_does_make_confident_absence_claims(tmp_path: Path) -> None:
    """Contrast case: with generous bounds the same shape of claim IS confident.

    This is what makes the withheld claim in the bounded test above meaningful
    rather than a test artifact — the code path for a confident "not observed"
    exists and fires under sufficient bounds.
    """
    (tmp_path / "README.md").write_text("small\n")
    intake = inspect_project(tmp_path)
    testability = next(f for f in intake.readiness_findings if f.dimension == "testability")
    assert testability.message == "No test entrypoints observed"
    assert testability.provenance.confidence == 0.7


# ---------------------------------------------------------------------------
# Property 2 — performance is bounded, and the bound is on work, not the clock
# ---------------------------------------------------------------------------


def test_walk_work_is_bounded_by_limits_not_by_tree_size(tmp_path: Path, monkeypatch) -> None:
    """The dominant, load-bearing assertions are on work done, not wall time.

    The fixture tree holds several thousand files, deliberately far more than
    max_entries. An unbounded (buggy) traversal would visit all of them and
    open every file within the read-size limit for content; a bounded one
    visits and opens no more than the declared limits allow, independent of
    how fast or slow the underlying disk happens to be on this run.
    """
    wide_count = 4_000
    max_entries = 200
    max_file_bytes = 200

    _build_bounded_stress_repo(tmp_path, wide_count=wide_count, deep_levels=5)
    on_disk_file_count = sum(1 for _ in (tmp_path / "wide").iterdir())
    assert on_disk_file_count == wide_count  # sanity: fixture actually built

    read_calls: list[str] = []
    original_read_text = Path.read_text

    def _counting_read_text(self: Path, *args, **kwargs):
        read_calls.append(str(self))
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _counting_read_text)

    start = time.perf_counter()
    intake = inspect_project(
        tmp_path,
        max_depth=8,
        max_entries=max_entries,
        max_file_bytes=max_file_bytes,
    )
    elapsed = time.perf_counter() - start

    # --- Deterministic, non-flaky assertions: work done. -------------------
    # entries_visited is bounded by max_entries, never by the 4000+ files that
    # actually exist on disk.
    assert intake.traversal_stats.entries_visited <= max_entries
    assert intake.traversal_stats.entries_visited < on_disk_file_count
    assert intake.traversal_stats.entry_limit_reached is True

    # Every file opened for content (read_text) is one the walk actually
    # visited — content-reading can never outrun the bounded set of visited
    # entries, so the number of opens is bounded by the same max_entries limit
    # that bounds entries_visited, regardless of how many files exist on disk.
    assert len(read_calls) <= intake.traversal_stats.entries_visited
    assert len(read_calls) <= max_entries

    # --- Wall-clock assertion: a generous smoke check, not the real proof. --
    # 30 seconds is chosen to be roughly two orders of magnitude above the
    # sub-second time this same assertion takes on ordinary developer/CI
    # hardware (this test's own measured runtime is reported alongside the
    # other tests in this file — see the task report). The point of this
    # number is *not* to catch a modest slowdown; it is a tripwire for a
    # traversal that stopped being bounded at all (e.g. actually visiting all
    # 4000+ files and/or reading their content), which would fail this by a
    # wide margin rather than a narrow one. A busy shared CI box being a few
    # times slower than a laptop must never fail this test.
    assert elapsed < 30.0, (
        f"traversal took {elapsed:.2f}s; a bounded walk over a small fixture "
        "should never approach this, even on slow/loaded hardware"
    )


# ---------------------------------------------------------------------------
# Property 3 — inspection does not mutate the target
# ---------------------------------------------------------------------------


def _build_tempting_repo(root: Path) -> None:
    """A repository containing things inspection is tempted to touch.

    - `.git/HEAD` — inspection reads the current revision from here.
    - `.foundry/project.yaml` — inspection parses this for nested-project
      overrides; a "helpful" implementation might be tempted to normalize or
      rewrite it.
    - An ordinary source tree, so the walk does real collector work.
    """
    (root / "README.md").write_text("tempting fixture\n")
    (root / "pyproject.toml").write_text("[project]\nname = 'tempting'\n")

    git_dir = root / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
    refs_dir = git_dir / "refs" / "heads"
    refs_dir.mkdir(parents=True)
    (refs_dir / "main").write_text("a" * 40 + "\n")

    foundry_dir = root / ".foundry"
    foundry_dir.mkdir()
    (foundry_dir / "project.yaml").write_text(
        "inspection:\n  nested_project_overrides:\n    include: []\n    exclude: []\n"
    )

    src = root / "src" / "pkg"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("")
    (src / "main.py").write_text("def run():\n    return 1\n")

    tests_dir = root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_main.py").write_text("def test_run():\n    assert True\n")


def test_inspect_project_does_not_mutate_the_target(tmp_path: Path) -> None:
    _build_tempting_repo(tmp_path)

    before = _snapshot_tree(tmp_path)
    assert before, "sanity: fixture actually has content"

    inspect_project(tmp_path)

    after = _snapshot_tree(tmp_path)

    # No path disappeared and, just as importantly, no *new* path appeared —
    # a written cache file or lockfile would show up here even though every
    # pre-existing file stayed byte-identical.
    assert set(after.keys()) == set(before.keys())

    changed = {
        path: (before[path], after[path])
        for path in before
        if before[path] != after[path]
    }
    assert changed == {}


def test_inspect_project_does_not_mutate_a_readonly_target(tmp_path: Path) -> None:
    """Best-effort proof against a read-only tree.

    chmod-based read-only enforcement is unreliable across containers (a
    process running as root, as this sandbox sometimes does, ignores write
    permission bits entirely) — so this test is intentionally tolerant: if the
    environment does not actually enforce the read-only bit (proven by a
    direct write probe before trusting the chmod at all), the test is skipped
    with an explicit reason rather than shipped as a false proof.
    """
    _build_tempting_repo(tmp_path)

    probe = tmp_path / "write_probe.txt"
    for p in tmp_path.rglob("*"):
        if p.is_dir():
            os.chmod(p, 0o555)
    os.chmod(tmp_path, 0o555)

    try:
        probe.write_text("x")
    except OSError:
        enforced = True
    else:
        enforced = False
        probe.unlink()

    if not enforced:
        os.chmod(tmp_path, 0o755)
        for p in tmp_path.rglob("*"):
            if p.is_dir():
                os.chmod(p, 0o755)
        pytest.skip(
            "read-only permission bits are not enforced in this sandbox "
            "(likely running as root); skipping rather than shipping a "
            "test that cannot actually fail"
        )

    try:
        before = _snapshot_tree(tmp_path)
        intake = inspect_project(tmp_path)
        after = _snapshot_tree(tmp_path)
        assert intake.observations  # it still did real work
        assert set(after.keys()) == set(before.keys())
        assert before == after
    finally:
        os.chmod(tmp_path, 0o755)
        for p in tmp_path.rglob("*"):
            if p.is_dir():
                os.chmod(p, 0o755)
