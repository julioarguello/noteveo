#!/usr/bin/env python3
"""Check the SHAPE of every layered how-to page: a `TL;DR` per task, step sections, a typed appendix.

A page opts in with the marker line `<!-- doc-type: layered-how-to -->`. Pages
without it are not layered how-tos and are skipped, so a repository can adopt the
standard one page at a time.

    doc-howto-check.py [PATH ...]      # files or directories; default: every tracked *.md

Exit 0 = conformant, or warnings only. Exit 1 = findings, one per line as
`file:line  CODE  detail`. A warning prints in the same shape with ` (warning)`
appended and never changes the exit status.
Exit 2 = no marked page was found (positive control: a green run over an empty
inventory certifies nothing). Exit 3 = usage error: an unknown option or a path
that does not exist.

Shape only. Whether a step is the right step, whether the explanation belongs in
the appendix, whether a warning is needed: that is judgement, and it belongs to the
`doc-reviewer` agent, not to this script.

Codes:
  F1  a task section (`##` before the appendix) has no `TL;DR`
  F2  a `TL;DR` has more than MAX_STEPS steps
  F3  a `TL;DR` step's command is not verbatim in the opening of the step section
      it links, or a step section no `TL;DR` step of its task links
  F4  a step section (`###` in a task) does not open with a lead clause and its
      fenced block
  F5  a date (YYYY-MM-DD) outside the appendix, fenced code and HTML comments
  F6  an empty appendix, or an empty appendix subsection
  F7  an appendix subsection is not typed (Explanation: / Reference: /
      Troubleshooting:), or a Troubleshooting subsection precedes another type
  F8  a step section adds nothing beyond its opening — a heading, a lead and the
      command the `TL;DR` already carries is the `TL;DR` again, one scroll lower
  F9  (warning) five or more Troubleshooting subsections in the appendix: GitLab
      moves them to their own page. Only the count half of the rule; "or one cited
      from another page" needs every page at once and is not checked here

The `TL;DR` is the task's fast path and it is a heading, `### `TL;DR``: the summary
layer outranks the verbose one typographically, the way it does in reading. A step
section is an optional expansion of one of its steps.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

MAX_STEPS = 10
# F9 is a warning on purpose; what it waits on is recorded as tech debt in the SKILL.md of
# the skill that ships this script, not here: this file is copied into every exporting
# project, whose tracker would file it.
MAX_TROUBLESHOOTING = 4

MARKER = re.compile(r"^<!--\s*doc-type:\s*layered-how-to\s*-->\s*$")
ORDINAL = r"(?:\d+(?:\.\d+)*\.?\s+)?"
H2 = re.compile(r"^##\s+(.+?)\s*#*\s*$")
H3 = re.compile(r"^###\s+(.+?)\s*#*\s*$")
APPENDIX = re.compile(rf"^{ORDINAL}Appendix\b", re.I)
TYPED = re.compile(rf"^{ORDINAL}(Explanation|Reference|Troubleshooting):\s*\S")
TLDR_H3 = re.compile(rf"^{ORDINAL}`?TL;DR`?$", re.I)
STEP = re.compile(r"^(\d+)\.\s")
FENCE_OPEN = re.compile(r"^(\s*)(`{3,}|~{3,})")
ALIAS = re.compile(r"<a\s+id=\"([^\"]+)\"")
LINK = re.compile(r"\]\(#([^)\s]+)\)")
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
COMMENT = re.compile(r"<!--.*?-->")


@dataclass
class Finding:
    line: int
    code: str
    detail: str
    warning: bool = False


@dataclass
class Section:
    title: str
    line: int  # 1-based line of the heading
    end: int  # 1-based line of the last line of the section
    level: int
    children: list[Section] = field(default_factory=list)


# --- markdown helpers ---------------------------------------------------------


def slugify(title: str) -> str:
    """GitHub's heading anchor: lowercase, drop punctuation, spaces to hyphens."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", title)
    text = text.replace("`", "").replace("*", "")
    text = re.sub(r"<[^>]+>", "", text).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def code_mask(lines: list[str]) -> list[bool]:
    """True for every line that is part of a fenced block (fences included).

    Handles fences indented under list items and fences inside blockquotes.
    """
    mask = [False] * len(lines)
    fence: str | None = None
    for i, raw in enumerate(lines):
        line = re.sub(r"^(\s*>\s?)+", "", raw)
        m = FENCE_OPEN.match(line)
        if fence is None:
            if m:
                fence = m.group(2)
                mask[i] = True
        else:
            mask[i] = True
            if line.strip().startswith(fence) and line.strip().strip(fence[0]) == "":
                fence = None
    return mask


def fences(lines: list[str]) -> list[str]:
    """Bodies of the fenced blocks in `lines`, each dedented and right-stripped."""
    out: list[str] = []
    body: list[str] = []
    fence: str | None = None
    indent = 0
    for line in lines:
        m = FENCE_OPEN.match(line)
        if fence is None:
            if m:
                fence, indent, body = m.group(2), len(m.group(1)), []
        elif line.strip().startswith(fence) and line.strip().strip(fence[0]) == "":
            out.append("\n".join(body).rstrip("\n"))
            fence = None
        else:
            body.append(line[indent:].rstrip() if line[:indent].strip() == "" else line.rstrip())
    return out


def frontmatter_end(lines: list[str]) -> int:
    """Number of leading lines taken by a YAML front matter block (0 when there is none)."""
    if not lines or lines[0].strip() != "---":
        return 0
    return next((i + 1 for i in range(1, len(lines)) if lines[i].strip() in ("---", "...")), 0)


# --- page model ---------------------------------------------------------------


def outline(lines: list[str], start: int, mask: list[bool]) -> list[Section]:
    """`##` sections from `start` (0-based) to the end, each with its `###` children."""
    top: list[Section] = []
    for i in range(start, len(lines)):
        if mask[i]:
            continue
        if m := H2.match(lines[i]):
            top.append(Section(m.group(1), i + 1, len(lines), 2))
        elif (m := H3.match(lines[i])) and top:
            top[-1].children.append(Section(m.group(1), i + 1, len(lines), 3))
    for k, sec in enumerate(top):
        sec.end = top[k + 1].line - 1 if k + 1 < len(top) else len(lines)
        for j, child in enumerate(sec.children):
            child.end = sec.children[j + 1].line - 1 if j + 1 < len(sec.children) else sec.end
    return top


def anchors(lines: list[str], sections: list[Section]) -> dict[str, Section]:
    """Every anchor a link can use to reach a step section: its slug and its aliases."""
    seen: dict[str, int] = {}
    out: dict[str, Section] = {}
    for sec in sections:
        for child in [sec, *sec.children]:
            base = slugify(child.title)
            n = seen.get(base, 0)
            seen[base] = n + 1
            out[base if n == 0 else f"{base}-{n}"] = child
            for probe in (child.line - 1, child.line - 2):  # heading line and the line above
                if 0 <= probe < len(lines):
                    for alias in ALIAS.findall(lines[probe]):
                        out[alias] = child
    return out


def tldr_child(sec: Section) -> Section | None:
    """The `### `TL;DR`` child of a task, or None."""
    return next((child for child in sec.children if TLDR_H3.match(child.title)), None)


def numbered_steps(lines: list[str], start: int, stop: int) -> list[tuple[int, list[str]]]:
    """(step line, step lines) for every `1.` item between the 0-based bounds."""
    steps: list[tuple[int, list[str]]] = []
    for j in range(start, stop):
        line = lines[j]
        if STEP.match(line):
            steps.append((j + 1, [line]))
        elif steps and (line.startswith((" ", "\t")) or not line.strip()):
            steps[-1][1].append(line)
        elif steps:
            break
    return steps


def tldr_steps(lines: list[str], sec: Section) -> tuple[int, list[tuple[int, list[str]]]] | None:
    """(TL;DR line, [(step line, step lines)]) for the task's `TL;DR`, or None.

    The `TL;DR` is a `### `TL;DR`` child of the task, so it carries the same
    typographic weight as the step sections it summarises and appears in the page
    outline. A task without one has no fast path, which is F1.
    """
    child = tldr_child(sec)
    return (child.line, numbered_steps(lines, child.line, child.end)) if child else None


def opening(lines: list[str], sec: Section) -> tuple[int, list[str]]:
    """(first content line, the lead and the fenced block that open the section).

    The opening is defined by its fence, not by a blockquote: a lead clause, then
    the command. A section that opens with a quoted block has no opening this
    function can find, which is F4 — and F3 then fires with it, because a quoted
    fence carries no command either.
    """
    i = sec.line
    while i < sec.end and (not lines[i].strip() or ALIAS.search(lines[i])):
        i += 1
    if i >= sec.end:
        return i + 1, []
    j = i
    while j < sec.end and lines[j].strip() and not FENCE_OPEN.match(lines[j]):
        j += 1
    lead_end = j
    while j < sec.end and not lines[j].strip():
        j += 1
    opener = FENCE_OPEN.match(lines[j]) if j < sec.end else None
    if opener is None:
        return i + 1, lines[i:lead_end]
    fence = opener.group(2)
    j += 1
    while j < sec.end:
        closer = lines[j].strip()
        j += 1
        if closer.startswith(fence) and not closer.strip(fence[0]):
            break
    return i + 1, lines[i:j]


def opens_well(block: list[str]) -> bool:
    """The section opens with a lead clause and its fenced block."""
    if not block:
        return False
    return bool(fences(block)) and not FENCE_OPEN.match(block[0])


# --- the checks ---------------------------------------------------------------


def check_task(lines: list[str], sec: Section, index: dict[str, Section]) -> list[Finding]:
    found: list[Finding] = []
    tldr = tldr_steps(lines, sec)
    if tldr is None or not tldr[1]:
        return [Finding(sec.line, "F1", f"task '{sec.title}' has no `TL;DR`")]
    tldr_line, steps = tldr
    if len(steps) > MAX_STEPS:
        found.append(Finding(tldr_line, "F2", f"{len(steps)} steps (max {MAX_STEPS}): split the task"))

    heading = tldr_child(sec)
    expansions = [child for child in sec.children if child is not heading]
    for child in expansions:
        first, block = opening(lines, child)
        if not opens_well(block):
            found.append(Finding(first, "F4", f"'{child.title}' does not open with a lead clause and its command"))
        elif not [line for line in lines[first - 1 + len(block) : child.end] if line.strip() not in ("", "---")]:
            found.append(Finding(child.line, "F8", f"'{child.title}' adds nothing beyond its opening"))

    linked: set[int] = set()
    for step_line, step in steps:
        targets = [index[a] for a in LINK.findall(" ".join(step)) if a in index and index[a] in expansions]
        linked.update(target.line for target in targets)
        commands = fences(step)
        if not commands or not targets:
            continue
        opener = fences(opening(lines, targets[0])[1])
        for cmd in commands:
            if cmd not in opener:
                head = cmd.splitlines()[0] if cmd else "(empty)"
                found.append(
                    Finding(step_line, "F3", f"'{head}' is not verbatim in the opening of '{targets[0].title}'")
                )
    found += [
        Finding(child.line, "F3", f"no `TL;DR` step links '{child.title}'")
        for child in expansions
        if child.line not in linked
    ]
    return found


def check_appendix(lines: list[str], sec: Section) -> list[Finding]:
    if not sec.children:
        empty = not any(line.strip() for line in lines[sec.line : sec.end])
        return [Finding(sec.line, "F6", "empty appendix: remove it")] if empty else []
    found: list[Finding] = []
    seen_troubleshooting = False
    troubleshooting: list[Section] = []
    for child in sec.children:
        if not any(line.strip() for line in lines[child.line : child.end]):
            found.append(Finding(child.line, "F6", f"empty appendix subsection '{child.title}'"))
        m = TYPED.match(child.title)
        if not m:
            detail = f"'{child.title}' is not typed Explanation:/Reference:/Troubleshooting:"
            found.append(Finding(child.line, "F7", detail))
        elif m.group(1) == "Troubleshooting":
            seen_troubleshooting = True
            troubleshooting.append(child)
        elif seen_troubleshooting:
            found.append(Finding(child.line, "F7", f"'{child.title}' follows a Troubleshooting subsection"))
    if len(troubleshooting) > MAX_TROUBLESHOOTING:
        count = len(troubleshooting)
        detail = f"{count} Troubleshooting subsections (max {MAX_TROUBLESHOOTING}): move them to their own page"
        found.append(Finding(troubleshooting[MAX_TROUBLESHOOTING].line, "F9", detail, warning=True))
    return found


def check_dates(lines: list[str], mask: list[bool], appendix: Section | None) -> list[Finding]:
    found: list[Finding] = []
    in_comment = False
    front = frontmatter_end(lines)
    for i, line in enumerate(lines):
        if i < front or mask[i]:
            continue
        if appendix and appendix.line - 1 <= i < appendix.end:
            continue
        text = COMMENT.sub("", line)
        if in_comment:
            if "-->" not in text:
                continue
            text, in_comment = text.split("-->", 1)[1], False
        if "<!--" in text:
            text, in_comment = text.split("<!--", 1)[0], True
        if m := DATE.search(text):
            detail = f"date {m.group(0)} outside the appendix: move it to a Reference subsection"
            found.append(Finding(i + 1, "F5", detail))
    return found


def check_page(path: Path) -> list[Finding] | None:
    """Findings for one page, or None when the page is not a layered how-to."""
    lines = path.read_text(encoding="utf-8").splitlines()
    mask = code_mask(lines)
    start = next((i for i, line in enumerate(lines) if not mask[i] and MARKER.match(line)), None)
    if start is None:
        return None
    sections = outline(lines, start, mask)
    index = anchors(lines, sections)
    appendix = next((s for s in sections if APPENDIX.match(s.title)), None)
    found: list[Finding] = []
    for sec in sections:
        if sec is appendix:
            found += check_appendix(lines, sec)
        elif appendix is None or sec.line < appendix.line:
            found += check_task(lines, sec, index)
    found += check_dates(lines, mask, appendix)
    return sorted(found, key=lambda f: (f.line, f.code))


# --- driver -------------------------------------------------------------------


def _tracked_markdown(root: Path) -> list[Path]:
    cmd = ["git", "-C", str(root), "ls-files", "-z", "--", "*.md"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    # A sparse checkout or a vendored symlink lists paths that are not on disk: not pages to check.
    return [root / p for p in out.stdout.split("\0") if p and (root / p).is_file()]


def _expand(args: list[str]) -> list[Path]:
    if not args:
        return _tracked_markdown(Path.cwd())
    out: list[Path] = []
    for arg in args:
        p = Path(arg)
        out += sorted(p.rglob("*.md")) if p.is_dir() else [p]
    return out


def main(argv: list[str]) -> int:
    if any(a in ("-h", "--help") for a in argv):
        print(__doc__)
        return 0
    bad = [a for a in argv if a.startswith("-")] + [a for a in argv if not a.startswith("-") and not Path(a).exists()]
    if bad:
        for a in bad:
            reason = "unknown option" if a.startswith("-") else "no such file or directory"
            print(f"doc-howto-check: {a}: {reason}", file=sys.stderr)
        return 3
    pages = 0
    findings = 0
    warnings = 0
    for path in _expand(argv):
        result = check_page(path)
        if result is None:
            continue
        pages += 1
        for f in result:
            print(f"{path}:{f.line}  {f.code}  {f.detail}{' (warning)' if f.warning else ''}")
            if f.warning:
                warnings += 1
            else:
                findings += 1
    if pages == 0:
        print("doc-howto-check: no page carries <!-- doc-type: layered-how-to --> (nothing checked)", file=sys.stderr)
        return 2
    print(f"doc-howto-check: {pages} page(s), {findings} finding(s), {warnings} warning(s)", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
