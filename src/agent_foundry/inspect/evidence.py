"""Establish what repository text actually says, carrying out the text it matched on.

Detection and evidence must be one pass. Splitting them — a structural check
followed by a re-scan for the value that check found — lets the two disagree: the
re-scan can land on different text than the detector matched (a YAML anchor
declaration rather than the step that uses it), or fail to find it at all (a
folded scalar spanning several physical lines), producing either a false claim or
a false negative. Every detector here returns the source text it matched on, so
there is nothing to re-find.

Where a claim cannot be soundly established, nothing is returned. A missing
convention is recoverable; a false one is trusted downstream.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import yaml

from agent_foundry.inspect.collectors import makefile_recipe_lines

# make consumes these recipe-line prefixes before handing the rest to the shell, so
# "@# pytest" reaches the shell as "# pytest" — a comment, not an invocation.
_MAKE_RECIPE_PREFIXES = "@-+"

# Longest first: "&&" must win over "&".
_SHELL_SEPARATORS = ("&&", "||", ";;", ";", "|", "&")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_ENV_WRAPPERS = frozenset({"env"})
_MODULE_RUNNER = re.compile(r"^python(3(\.\d+)?)?$")
_SUBCOMMAND_RUNNERS = frozenset({"uv", "poetry", "pdm", "hatch", "pipenv"})


def strip_trailing_comment(line: str) -> str:
    """Return the part of *line* that is not a trailing comment.

    POSIX shell and YAML agree on the rule: ``#`` opens a comment only outside
    quotes and only at the start of a word. A ``#`` inside a quoted string
    (``echo "a # b"``) is data, so treating it as a comment would drop a
    legitimate line — the opposite failure from the one this guards against.
    """
    quote: str | None = None
    index = 0
    while index < len(line):
        char = line[index]
        if quote == "'":
            if char == "'":
                quote = None
        elif quote == '"':
            if char == "\\":
                index += 1
            elif char == '"':
                quote = None
        elif char == "\\":
            index += 1
        elif char in "'\"":
            quote = char
        elif char == "#" and (index == 0 or line[index - 1].isspace()):
            return line[:index]
        index += 1
    return line


def executable_recipe_text(recipe_line: str) -> str:
    """The part of a Makefile recipe line the shell would actually execute."""
    return strip_trailing_comment(
        recipe_line.lstrip("\t").lstrip(_MAKE_RECIPE_PREFIXES)
    ).strip()


@dataclass(frozen=True)
class ShellWord:
    """One shell word, with whether any part of it was quoted.

    Quoting is the difference between a command and data: in ``echo "pytest"``
    the second word is an argument no matter what it spells.
    """

    text: str
    quoted: bool


def shell_command_segments(text: str) -> list[list[ShellWord]]:
    """Split *text* into the command segments a shell would run, word by word.

    This is deliberately not a shell parser. It resolves quoting and the plain
    separators, and returns nothing at all when the line does not parse cleanly
    (an unterminated quote), so an unparsed line can never support a claim.
    """
    segments: list[list[ShellWord]] = [[]]
    chars: list[str] = []
    started = False
    quoted = False
    quote: str | None = None
    index = 0

    def end_word() -> None:
        nonlocal chars, started, quoted
        if started:
            segments[-1].append(ShellWord("".join(chars), quoted))
        chars = []
        started = False
        quoted = False

    while index < len(text):
        char = text[index]
        if quote == "'":
            if char == "'":
                quote = None
            else:
                chars.append(char)
        elif quote == '"':
            if char == "\\" and index + 1 < len(text):
                index += 1
                chars.append(text[index])
            elif char == '"':
                quote = None
            else:
                chars.append(char)
        elif char == "\\" and index + 1 < len(text):
            index += 1
            chars.append(text[index])
            started = True
        elif char in "'\"":
            quote = char
            quoted = True
            started = True
        elif char.isspace():
            end_word()
        else:
            separator = next(
                (sep for sep in _SHELL_SEPARATORS if text.startswith(sep, index)), None
            )
            if separator is not None:
                end_word()
                segments.append([])
                index += len(separator)
                continue
            chars.append(char)
            started = True
        index += 1

    if quote is not None:
        return []
    end_word()
    return [segment for segment in segments if segment]


def _basename(word: str) -> str:
    return word.rsplit("/", 1)[-1]


def _command_of(segment: list[ShellWord]) -> tuple[str | None, list[ShellWord]]:
    """The command a segment runs and its arguments, or ``None`` when unclear.

    Quoting is stripped from the head: a shell runs ``"pytest" -q`` exactly as it
    runs ``pytest -q``. Quoting still matters everywhere else — a quoted word in
    an argument position is data being handed to the head, so ``sh -c "pytest"``
    remains an invocation of ``sh``. Redirections and assignments are only those
    when unquoted; ``"VAR=x"`` is a command name, not an assignment.
    """
    index = 0
    while index < len(segment):
        word = segment[index]
        if not word.quoted:
            if word.text.startswith(("<", ">")):
                return None, []
            if _ASSIGNMENT.match(word.text) or _basename(word.text) in _ENV_WRAPPERS:
                index += 1
                continue
        return word.text, segment[index + 1 :]
    return None, []


def _segment_invokes(segment: list[ShellWord], command: str) -> bool:
    head, arguments = _command_of(segment)
    if head is None:
        return False
    name = _basename(head)
    if name == command:
        return True
    if _MODULE_RUNNER.match(name):
        return any(
            not first.quoted
            and first.text == "-m"
            and not second.quoted
            and _basename(second.text) == command
            for first, second in zip(arguments, arguments[1:])
        )
    if name in _SUBCOMMAND_RUNNERS:
        if not arguments or arguments[0].quoted or arguments[0].text != "run":
            return False
        for argument in arguments[1:]:
            if argument.quoted:
                return False
            if argument.text.startswith("-"):
                continue
            return _basename(argument.text) == command
    return False


def recipe_lines_invoking(content: str, target: str, command: str) -> list[str]:
    """Recipe lines of *target* that invoke *command*.

    Each returned line is both the finding and its own evidence: the line is
    included precisely because *command* stood in a command position on it.

    Known residual, fail-closed by design: physical lines are examined one at a
    time, so a command name split across lines by a shell line continuation
    (``py\\`` / ``test -q``) is not recognised. That drops a convention rather
    than asserting a false one, which is the direction this module errs in.
    """
    invoking: list[str] = []
    for recipe_line in makefile_recipe_lines(content, target):
        executable = executable_recipe_text(recipe_line)
        if not executable:
            continue
        if any(
            _segment_invokes(segment, command)
            for segment in shell_command_segments(executable)
        ):
            invoking.append(recipe_line.strip())
    return invoking


def _mapping_get(node: object, key: str) -> object | None:
    if not isinstance(node, yaml.MappingNode):
        return None
    for key_node, value_node in node.value:
        if isinstance(key_node, yaml.ScalarNode) and key_node.value == key:
            return value_node
    return None


def _written_within(node: yaml.Node, container: yaml.Node) -> bool:
    """Whether *node* is written inside *container*'s own source range."""
    return container.start_mark.line <= node.start_mark.line <= container.end_mark.line


def _workflow_step_nodes(root: object) -> list[yaml.MappingNode]:
    """Steps whose own source text is the step — never a copy of another one.

    A YAML alias resolves to the anchored node, source marks included, so an
    aliased step (``- *checkout``) is the very same object as the step it copies.
    Taking it at face value emits a second finding carrying the first step's
    source line as its evidence, which that line does not support. Its own text
    does not say what it uses either, so it is not accepted: a step counts once,
    where it is actually written, inside its own steps sequence.
    """
    jobs = _mapping_get(root, "jobs")
    if not isinstance(jobs, yaml.MappingNode):
        return []
    steps: list[yaml.MappingNode] = []
    seen: set[int] = set()
    for _, job in jobs.value:
        step_list = _mapping_get(job, "steps")
        if not isinstance(step_list, yaml.SequenceNode):
            continue
        for step in step_list.value:
            if not isinstance(step, yaml.MappingNode):
                continue
            if id(step) in seen or not _written_within(step, step_list):
                continue
            seen.add(id(step))
            steps.append(step)
    return steps


def _source_span(lines: list[str], key_node: yaml.Node, value_node: yaml.Node) -> str | None:
    """The physical source lines carrying one mapping entry, or ``None``.

    ``None`` when the value is not written where its key is — a YAML alias, whose
    node carries the anchor declaration's position. That declaration is not the
    step configuring anything, and this entry's own text does not say what it
    uses, so nothing here establishes the claim.
    """
    start = key_node.start_mark.line
    if value_node.start_mark.line < start:
        return None
    end = value_node.end_mark.line
    if value_node.end_mark.column == 0 and end > start:
        end -= 1
    end = min(end, len(lines) - 1)
    if end < start:
        return None
    span = [lines[index].strip() for index in range(start, end + 1)]
    while span and not span[-1]:
        span.pop()
    return "\n".join(span) if span else None


def workflow_steps_using(content: str, action: str) -> list[str]:
    """Source text of every workflow step whose ``uses`` names *action*.

    Read structurally: the action named in a comment, in a ``run:`` script, or
    anywhere outside ``jobs.*.steps[*].uses`` configures nothing. The composed
    node graph carries source positions, so the returned text is the step that
    was matched — never a different line that happens to contain the same value.
    A step whose text cannot yield that evidence is not accepted as a match.
    """
    try:
        root = yaml.compose(content, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        return []
    if root is None:
        return []
    lines = content.splitlines()
    matched: list[str] = []
    for step in _workflow_step_nodes(root):
        for key_node, value_node in step.value:
            if not (isinstance(key_node, yaml.ScalarNode) and key_node.value == "uses"):
                continue
            if not isinstance(value_node, yaml.ScalarNode):
                continue
            if value_node.value.split("@", 1)[0].strip() != action:
                continue
            span = _source_span(lines, key_node, value_node)
            if span is not None:
                matched.append(span)
    return matched
