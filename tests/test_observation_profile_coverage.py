"""AF22-C3: every emitted observation subject must reach a profile dimension.

`collectors.py` emits `ProjectObservation`s carrying a `subject` string.
`synth.py` consumes subjects via fixed sets keyed by that same string. If a
collector emits a subject no dimension consumes, the observation is silently
dropped — and in the profile output a dropped observation is indistinguishable
from real absence: the dimension reports
``resolution=resolved, kind=observed, confidence=1.0, "none-observed"`` while
the contradicting evidence sits unused in the same `ProjectIntake`. The
reverse also matters: a synth subject key no collector can ever emit is a dead
key that guarantees a permanent false "none-observed".

This module derives both vocabularies mechanically from an AST walk of the
actual source of `collectors.py` and `synth.py` — never from a hand-maintained
``EXPECTED_SUBJECTS = {...}`` list. A second manually-synchronised vocabulary
would reproduce exactly the drift this guard exists to catch (this defect
class already recurred twice during SUE-579).

**Emitted-subject derivation (`collectors.py`).** Two call shapes carry a
subject: ``_observed(<subject>, ...)`` / ``_declared(<subject>, ...)`` (first
positional arg) and ``ProjectObservation(subject=..., ...)`` (keyword form).
The bodies of the `_observed`/`_declared` helper *definitions* themselves
contain `ProjectObservation(subject=subject, ...)` — that is not a call site,
it is the helper's own implementation, and must not be counted (a naive walk
that counted it would report the same subject string as both a literal call
site AND a spurious unresolved variable). Call sites are therefore filtered
by excluding any call whose line falls inside an `_observed`/`_declared`
`FunctionDef`'s own line range. The one real non-literal call site is
`_MAKEFILE_TARGET_SUBJECTS` (a `dict[str, str]`) fed through
`for target, subject in sorted(_MAKEFILE_TARGET_SUBJECTS.items())` and then
`_observed(subject, ...)`: resolved by recognising that specific
for-loop-over-a-module-dict's-`.items()` shape and pulling the dict's
literal values. Anything else non-literal is unresolvable and makes the
derivation raise loudly, naming the line — never silently skipped, since a
silent skip would reintroduce the drift this guard exists to catch.

**Consumed-subject derivation (`synth.py`).** Not every frozenset literal in
that module is a subject set — `_CLASSIFICATION_EXCLUDED_DIMENSIONS` holds a
*profile dimension name* — so this does not scan all frozenset literals. It
scans exactly two consumption seams: the `subjects` argument (3rd positional
or `subjects=` keyword) of every `_aggregate_observation_dimension(...)` call,
and direct `obs.subject == "<literal>"` comparisons (the seam that covers
`file-read-skipped` and `path-unobservable`, consumed only this way — a
frozenset-only scan would miss both and report false drift). Any subjects
argument that is not a `frozenset({...})` literal of string constants is
unresolvable and raises loudly, naming the line.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from agent_foundry.inspect import collectors as collectors_module
from agent_foundry.profile import synth as synth_module

# A conservative floor: proof the derivation actually found something, not
# that it landed on today's exact count (which the dedicated equality test
# below pins precisely).
_MIN_PLAUSIBLE_SUBJECT_COUNT = 10

# A few subjects that must show up in each derived vocabulary today. If a
# derivation silently returned an empty (or wrong) set, `assert emitted ==
# consumed` on two empty sets would pass for the wrong reason — this closes
# that hole.
_KNOWN_EMITTED_SUBJECTS = frozenset(
    {"repository-structure", "test-entrypoint", "foundry-artifact", "path-unobservable"}
)
_KNOWN_CONSUMED_SUBJECTS = frozenset(
    {"repository-structure", "test-entrypoint", "foundry-artifact", "path-unobservable"}
)


class UnresolvableSubject(AssertionError):
    """Raised when a subject-bearing argument cannot be resolved to literals.

    A future collector or synth change that introduces a subject argument
    this derivation cannot account for must make the guard complain loudly,
    not silently under-count and let real drift slip past as a false pass.
    """


def _dict_literal_str_values(node: ast.Dict) -> dict[str, str] | None:
    values: dict[str, str] = {}
    for key, value in zip(node.keys, node.values):
        if (
            isinstance(key, ast.Constant)
            and isinstance(key.value, str)
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
        ):
            values[key.value] = value.value
        else:
            return None
    return values


def _module_str_dict_literals(tree: ast.Module) -> dict[str, dict[str, str]]:
    """Module-level ``NAME: dict[str, str] = {...}`` / ``NAME = {...}`` literals."""
    found: dict[str, dict[str, str]] = {}
    for node in ast.walk(tree):
        target_name = None
        value = None
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                target_name, value = target.id, node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and isinstance(node.value, ast.Dict)
        ):
            target_name, value = node.target.id, node.value
        if target_name is None:
            continue
        literal = _dict_literal_str_values(value)
        if literal is not None:
            found[target_name] = literal
    return found


def _resolve_via_dict_items_loop(
    tree: ast.Module, module_dicts: dict[str, dict[str, str]], name_node: ast.Name
) -> set[str] | None:
    """Resolve a loop variable bound from ``for k, v in sorted(SOME_DICT.items())``.

    ``SOME_DICT`` must be one of the module-level string-literal dict
    assignments this module already found; ``v``'s identifier must match
    ``name_node``. Returns the dict's values (the possible subjects that
    variable can hold at the call site) or ``None`` if the shape does not
    match at all.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        if not (node.lineno <= name_node.lineno <= (node.end_lineno or node.lineno)):
            continue
        target = node.target
        if not (isinstance(target, ast.Tuple) and len(target.elts) == 2):
            continue
        _, value_element = target.elts
        if not (isinstance(value_element, ast.Name) and value_element.id == name_node.id):
            continue
        iterable = node.iter
        if (
            isinstance(iterable, ast.Call)
            and isinstance(iterable.func, ast.Name)
            and iterable.func.id == "sorted"
            and iterable.args
        ):
            iterable = iterable.args[0]
        if (
            isinstance(iterable, ast.Call)
            and isinstance(iterable.func, ast.Attribute)
            and iterable.func.attr == "items"
            and isinstance(iterable.func.value, ast.Name)
            and iterable.func.value.id in module_dicts
        ):
            return set(module_dicts[iterable.func.value.id].values())
    return None


def derive_emitted_subjects(module) -> set[str]:
    """Every observation ``subject`` value `collectors.py` can emit.

    Derived straight from that module's own AST — see module docstring for
    which two call shapes count and how the one variable-subject call site
    (the Makefile-target loop) is resolved.
    """
    source = inspect.getsource(module)
    tree = ast.parse(source, filename=module.__file__)
    module_dicts = _module_str_dict_literals(tree)

    helper_names = {"_observed", "_declared"}
    helper_ranges = [
        (node.lineno, node.end_lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in helper_names
    ]

    def _inside_a_helper_definition(node: ast.AST) -> bool:
        return any(lo <= node.lineno <= (hi or lo) for lo, hi in helper_ranges)

    def _resolve(value_node: ast.expr, call_lineno: int) -> set[str]:
        if isinstance(value_node, ast.Constant) and isinstance(value_node.value, str):
            return {value_node.value}
        if isinstance(value_node, ast.Name):
            resolved = _resolve_via_dict_items_loop(tree, module_dicts, value_node)
            if resolved is not None:
                return resolved
        raise UnresolvableSubject(
            f"{module.__file__}:{call_lineno}: subject argument "
            f"{ast.dump(value_node)!r} is neither a string literal nor the "
            "known Makefile-target-dict loop-variable shape this derivation "
            "recognises. A future collector emitting a subject this way must "
            "either use a literal or extend this derivation deliberately — "
            "it must not be silently skipped."
        )

    emitted: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _inside_a_helper_definition(node):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in helper_names:
            if not node.args:
                raise UnresolvableSubject(
                    f"{module.__file__}:{node.lineno}: {func.id}() call has no "
                    "positional subject argument"
                )
            emitted |= _resolve(node.args[0], node.lineno)
        elif isinstance(func, ast.Name) and func.id == "ProjectObservation":
            keyword = next((kw for kw in node.keywords if kw.arg == "subject"), None)
            if keyword is not None:
                emitted |= _resolve(keyword.value, node.lineno)
    return emitted


def derive_consumed_subjects(module) -> set[str]:
    """Every observation ``subject`` value `synth.py` will actually route to a dimension.

    Derived from exactly two consumption seams — see module docstring for why
    a blanket frozenset scan is wrong (it would misclassify
    ``_CLASSIFICATION_EXCLUDED_DIMENSIONS``, a set of profile *dimension*
    names, as a subject set).
    """
    source = inspect.getsource(module)
    tree = ast.parse(source, filename=module.__file__)

    def _literal_str_set(node: ast.expr, call_lineno: int) -> set[str]:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "frozenset":
            if node.args and isinstance(node.args[0], ast.Set):
                values: set[str] = set()
                for element in node.args[0].elts:
                    if isinstance(element, ast.Constant) and isinstance(element.value, str):
                        values.add(element.value)
                    else:
                        raise UnresolvableSubject(
                            f"{module.__file__}:{call_lineno}: non-literal element "
                            f"{ast.dump(element)!r} in a subjects frozenset"
                        )
                return values
        raise UnresolvableSubject(
            f"{module.__file__}:{call_lineno}: `subjects` argument to "
            "_aggregate_observation_dimension is not a frozenset({...}) string "
            f"literal: {ast.dump(node)!r}"
        )

    consumed: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "_aggregate_observation_dimension":
                subjects_node = None
                if len(node.args) >= 3:
                    subjects_node = node.args[2]
                else:
                    keyword = next((kw for kw in node.keywords if kw.arg == "subjects"), None)
                    if keyword is not None:
                        subjects_node = keyword.value
                if subjects_node is None:
                    raise UnresolvableSubject(
                        f"{module.__file__}:{node.lineno}: _aggregate_observation_dimension "
                        "call has no `subjects` argument"
                    )
                consumed |= _literal_str_set(subjects_node, node.lineno)
        elif isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq):
            left, right = node.left, node.comparators[0]

            def _is_subject_attr(candidate: ast.expr) -> bool:
                return isinstance(candidate, ast.Attribute) and candidate.attr == "subject"

            if _is_subject_attr(left) and isinstance(right, ast.Constant) and isinstance(right.value, str):
                consumed.add(right.value)
            elif _is_subject_attr(right) and isinstance(left, ast.Constant) and isinstance(left.value, str):
                consumed.add(left.value)
    return consumed


def test_derivation_is_non_vacuous():
    """A derivation silently returning zero (or near-zero) must fail, not pass.

    ``assert emitted == consumed`` on two empty sets would be worthless — this
    proves both derivations actually discovered a real vocabulary before any
    equality check is allowed to mean anything.
    """
    emitted = derive_emitted_subjects(collectors_module)
    consumed = derive_consumed_subjects(synth_module)

    assert len(emitted) >= _MIN_PLAUSIBLE_SUBJECT_COUNT, sorted(emitted)
    assert len(consumed) >= _MIN_PLAUSIBLE_SUBJECT_COUNT, sorted(consumed)
    assert _KNOWN_EMITTED_SUBJECTS <= emitted, sorted(emitted)
    assert _KNOWN_CONSUMED_SUBJECTS <= consumed, sorted(consumed)


def test_current_emitted_and_consumed_vocabularies_match_exactly():
    """A. Current coverage — pinned to today's known-clean 18/18 state.

    If this ever fails, the failure names the actual asymmetric subjects
    (sorted, deterministic) — do not "fix" `collectors.py` or `synth.py` to
    make it pass; report the mismatch.
    """
    emitted = derive_emitted_subjects(collectors_module)
    consumed = derive_consumed_subjects(synth_module)

    only_emitted = sorted(emitted - consumed)
    only_consumed = sorted(consumed - emitted)
    assert only_emitted == [], (
        "collector(s) emit subject(s) no synth dimension consumes -- these "
        f"observations are silently dropped: {only_emitted}"
    )
    assert only_consumed == [], (
        "synth subject set(s) reference subject(s) no collector can ever "
        f"emit -- these are dead keys guaranteeing false none-observed: {only_consumed}"
    )
    assert sorted(emitted) == sorted(consumed)
    assert len(emitted) == 18, sorted(emitted)
    assert len(consumed) == 18, sorted(consumed)


def _import_module_from_source(tmp_path, name: str, source: str):
    import importlib.util

    module_path = tmp_path / f"{name}.py"
    module_path.write_text(source)
    spec = importlib.util.spec_from_file_location(name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_derivation_rejects_an_unresolvable_emitted_subject_argument(tmp_path):
    """B/E support: a subject argument this derivation cannot resolve must raise.

    Exercises `derive_emitted_subjects` itself (not a copy of its logic)
    against a synthetic module standing in for a hostile future collector
    doing `_observed(some_var, ...)` where `some_var` is not the recognised
    Makefile-dict loop shape. Proves the "fail loudly, never silently skip"
    contract this guard requires.
    """
    hostile_source = (
        "def _observed(subject, content, source_ref, *, confidence=1.0):\n"
        "    return (subject, content, source_ref)\n"
        "\n"
        "def emit(some_var):\n"
        "    return _observed(some_var, 'content', 'ref')\n"
    )
    hostile_module = _import_module_from_source(tmp_path, "hostile_collectors", hostile_source)

    with pytest.raises(UnresolvableSubject):
        derive_emitted_subjects(hostile_module)


def test_derivation_rejects_an_unresolvable_consumed_subjects_argument(tmp_path):
    """D support: a `subjects` argument synth-side that isn't a literal frozenset must raise."""
    hostile_source = (
        "def _aggregate_observation_dimension(name, observations, subjects, *, stats):\n"
        "    return None\n"
        "\n"
        "SOME_DYNAMIC_SET = frozenset({'a'})\n"
        "\n"
        "def build(observations, stats):\n"
        "    return _aggregate_observation_dimension('x', observations, SOME_DYNAMIC_SET, stats=stats)\n"
    )
    hostile_module = _import_module_from_source(tmp_path, "hostile_synth", hostile_source)

    with pytest.raises(UnresolvableSubject):
        derive_consumed_subjects(hostile_module)


@pytest.mark.parametrize(
    "extra_subject",
    ["totally-new-subject-no-dimension-consumes"],
)
def test_forward_drift_a_new_emitted_subject_with_no_consumer_is_detected(extra_subject):
    """B. Forward drift — simulated: an emitted set gains a subject synth never consumes."""
    emitted = derive_emitted_subjects(collectors_module) | {extra_subject}
    consumed = derive_consumed_subjects(synth_module)
    only_emitted = sorted(emitted - consumed)
    assert only_emitted == [extra_subject], only_emitted


def test_lost_consumption_removing_a_subject_from_synth_is_detected():
    """C. Lost consumption — simulated: synth's consumed set loses a subject the collector still emits."""
    emitted = derive_emitted_subjects(collectors_module)
    consumed = derive_consumed_subjects(synth_module)
    victim = sorted(consumed)[0]
    reduced_consumed = consumed - {victim}
    only_emitted = sorted(emitted - reduced_consumed)
    assert only_emitted == [victim], only_emitted


def test_dead_synthesis_key_a_synth_only_subject_is_detected():
    """D. Dead synthesis key — simulated: synth references a subject no collector emits."""
    emitted = derive_emitted_subjects(collectors_module)
    consumed = derive_consumed_subjects(synth_module) | {"synth-only-phantom-subject"}
    only_consumed = sorted(consumed - emitted)
    assert only_consumed == ["synth-only-phantom-subject"], only_consumed


def test_failure_output_is_sorted_and_deterministic():
    """F. Determinism — repeated derivation yields identical sorted output, twice in a row."""
    first_emitted = sorted(derive_emitted_subjects(collectors_module))
    second_emitted = sorted(derive_emitted_subjects(collectors_module))
    assert first_emitted == second_emitted
    assert first_emitted == sorted(set(first_emitted)), "must already be sorted, not set-order"

    first_consumed = sorted(derive_consumed_subjects(synth_module))
    second_consumed = sorted(derive_consumed_subjects(synth_module))
    assert first_consumed == second_consumed
    assert first_consumed == sorted(set(first_consumed))
