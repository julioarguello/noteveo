#!/usr/bin/env python3
"""Check that a page states no value it cannot keep — words that age, versions, undated measurements.

A quantity written into prose is a cached query, and prose has no cache invalidation.
This script checks the part of that a machine can see: words that age, a version that
restates what the repository already declares, and a date that does not say what
happened on it.

A page opts in with the marker line `<!-- doc-check: timeless -->`. Pages without it
are skipped, so a repository adopts the standard one page at a time — ordinary
English words over prose that narrates its own history would fire hundreds of
correct-but-unwanted findings on day one, and a gate that shouts on day one is switched
off on day two.

    doc-timeless-check.py [PATH ...]    # files or directories; default: every tracked *.md

Exit 0 = conformant. Exit 1 = findings, one per line as `file:line  CODE  detail`.
Exit 2 = no marked page was found (positive control: a green run over an empty
inventory certifies nothing). Exit 3 = usage error.

Codes:
  T1  one of the terms in TERMS — a word that anchors the page to a point in time
  T2  a version equal to the one this repository declares TODAY (an earlier release is
      a historical floor and passes). With no declaration to compare against, T2 does
      not run, and the summary line names the codes that did — a green states its scope
      instead of implying four checks ran when three did
  T3  `Measured` without a date after it
  T4  a date that no evidentiary verb introduces

What this does NOT do: detect a stale count. `45 of 81 scripts` is indistinguishable
from prose holding two numbers, and a heuristic that guessed would produce the most
expensive class of false finding. Counts stay with the `doc-reviewer` agent, which is
advisory by design.

Quotations are exempt: a blockquote is somebody else's prose, and so are fenced blocks,
inline code, HTML comments and link targets. All are masked before any check runs.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

MARKER = re.compile(r"^<!--\s*doc-check:\s*timeless\s*-->\s*$")

# Google developer documentation style guide, "Timeless documentation", transcribed from
# that page. Each entry is one term; the multi-word ones are written as they are read.
TERMS: tuple[str, ...] = (
    "as of this writing",
    "currently",
    "does not yet",
    "eventually",
    "existing",
    "in the future",
    "future",
    "latest",
    "newer",
    "new",
    "now",
    "older",
    "old",
    "presently",
    "at present",
    "soon",
)

# A date earns its place by saying what happened on it. These are the verbs that do that.
ANCHOR_VERBS: tuple[str, ...] = (
    "measured",
    "verified",
    "audited",
    "transcribed",
    "observed",
    "checked",
    "tested",
    "read",
    "released",
    "tagged",
    "cleaned",
)

DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
SEMVER = re.compile(r"\bv?\d+\.\d+\.\d+(?:[-.][0-9A-Za-z][0-9A-Za-z-]*)*\b")
MEASURED = re.compile(r"\bMeasured\b")
# Must match at the END of the text preceding one date: an anchored date elsewhere on the
# line is not this date's warrant. `[^.;:)\]]` stops the match crossing a clause boundary.
ANCHOR_BEFORE = re.compile(
    r"\b(?:" + "|".join(ANCHOR_VERBS) + r")\b[^.;:)\]]{0,30}$",
    re.I,
)
TERM_RE = tuple(
    (term, re.compile(r"(?<![\w-])" + re.escape(term).replace(r"\ ", r"\s+") + r"(?![\w-])", re.I)) for term in TERMS
)

FENCE = re.compile(r"^\s*(?:```+|~~~+)")
INLINE_CODE = re.compile(r"`[^`]*`")
LINK_TARGET = re.compile(r"\]\([^)]*\)")
BARE_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+")
BLOCKQUOTE = re.compile(r"^\s{0,3}>")


def _blank(match: re.Match[str]) -> str:
    """Replace a span with spaces, so every later offset and line number still holds."""
    return " " * (match.end() - match.start())


def mask(lines: list[str]) -> list[str]:
    """Blank out what is not this page's own prose, preserving line numbers."""
    out: list[str] = []
    in_fence = False
    in_comment = False
    for raw in lines:
        line = raw.rstrip("\n")
        if FENCE.match(line):
            in_fence = not in_fence
            out.append("")
            continue
        if in_fence:
            out.append("")
            continue
        if in_comment:
            out.append("")
            in_comment = "-->" not in line
            continue
        if "<!--" in line and "-->" not in line:
            in_comment = True
            out.append("")
            continue
        if BLOCKQUOTE.match(line):  # a quotation is somebody else's prose
            out.append("")
            continue
        line = re.sub(r"<!--.*?-->", _blank, line)
        line = INLINE_CODE.sub(_blank, line)
        line = LINK_TARGET.sub(_blank, line)
        line = BARE_URL.sub(_blank, line)
        out.append(line)
    return out


def _is_virtual_project(text: str) -> bool:
    """`[tool.uv] package = false`: a uv project that is never built, only synced.

    A Maven repository that owns its gates' Python declares one at the root, and uv requires
    `[project] version` even then (measured 2026-10-09: without it `uv lock` stops). That
    version is a placeholder, not the repository's — reading it as "today's version" made T2
    hunt for `0` and lose the real one in pom.xml.
    """
    block = re.search(r"(?ms)^\[tool\.uv\]\s*$(.*?)(?=^\[|\Z)", text)
    return bool(block and re.search(r"(?m)^\s*package\s*=\s*false\b", block.group(1)))


def declared_version(root: Path) -> tuple[str, str] | None:
    """The one version this repository declares, and the file that declares it."""
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8", errors="replace")
        block = None if _is_virtual_project(text) else re.search(r"(?ms)^\[project\]\s*$(.*?)(?=^\[|\Z)", text)
        if block:
            found = re.search(r"""(?m)^\s*version\s*=\s*["']([^"']+)["']""", block.group(1))
            if found:
                return found.group(1), "pyproject.toml"
    config = root / ".mvn" / "maven.config"
    if config.is_file():
        found = re.search(r"-Drevision=(\S+)", config.read_text(encoding="utf-8", errors="replace"))
        if found:
            return found.group(1), ".mvn/maven.config"
    pom = root / "pom.xml"
    if pom.is_file():
        found = re.search(r"<revision>([^<]+)</revision>", pom.read_text(encoding="utf-8", errors="replace"))
        if found:
            return found.group(1).strip(), "pom.xml"
    return None


def _same_version(token: str, declared: str) -> bool:
    return token.lstrip("vV") == declared.lstrip("vV")


def check(lines: list[str], version: tuple[str, str] | None) -> list[tuple[int, str, str]]:
    """Every finding on one already-masked page, as (line_number, code, detail)."""
    findings: list[tuple[int, str, str]] = []
    for n, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        hits = [term for term, pattern in TERM_RE if pattern.search(line)]
        if hits:
            shown = ", ".join(f"`{term}`" for term in hits)
            verb = "anchors" if len(hits) == 1 else "anchor"
            findings.append((n, "T1", f"{shown} {verb} the page to a point in time — delete it"))
        for token in SEMVER.findall(line):
            if version is None:
                continue  # T2 did not run; the summary says so instead of inventing a finding
            if _same_version(token, version[0]):
                findings.append(
                    (n, "T2", f"`{token}` is what {version[1]} declares today — cite a release, not the present")
                )
        if MEASURED.search(line) and not DATE.search(line):
            findings.append((n, "T3", "`Measured` without a date — the form is `Measured YYYY-MM-DD against …`"))
        for found in DATE.finditer(line):
            before = line[max(0, found.start() - 60) : found.start()]
            if not ANCHOR_BEFORE.search(before):
                findings.append((n, "T4", f"`{found.group(0)}` says nothing about what happened on it"))
    return findings


def repo_root(start: Path) -> Path:
    """The repository root, so T2 reads one manifest wherever the script is invoked from.

    Reading it from the working directory made T2 skip silently when the script ran from a
    subdirectory — the check's vantage decided its result, which is the failure this repo
    calls out in ai-verification.md. Falls back to `start` outside a repository.
    """
    out = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    return Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else start


def _tracked_markdown(root: Path) -> list[Path]:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "*.md"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [root / p for p in out.stdout.split("\n") if p]


def _expand(paths: list[str], root: Path) -> list[Path]:
    if not paths:
        return _tracked_markdown(root)
    files: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            files.extend(sorted(path.rglob("*.md")))
        elif path.is_file():
            files.append(path)
        else:
            print(f"doc-timeless-check.py: no such path: {raw}", file=sys.stderr)
            raise SystemExit(3)
    return files


def main(argv: list[str]) -> int:
    if any(a in ("-h", "--help") for a in argv):
        print(__doc__)
        return 0
    unknown = [a for a in argv if a.startswith("-")]
    if unknown:
        print(f"doc-timeless-check.py: unknown option: {unknown[0]}", file=sys.stderr)
        return 3

    root = repo_root(Path.cwd())
    version = declared_version(root)
    if version is None:
        print(
            f"doc-timeless-check.py: NOTE: no version declaration found under {root} "
            "(pyproject.toml, .mvn/maven.config, pom.xml) — T2 did not run. "
            "A green run below certifies T1, T3 and T4 only.",
            file=sys.stderr,
        )

    findings: list[str] = []
    marked = 0
    absent = 0
    for path in _expand(argv, root):
        if not path.is_file():
            # Tracked but not materialised: a sparse checkout hides paths `git ls-files`
            # still lists. Counted and reported, never skipped in silence — a green over a
            # corpus half of which was never read is not a green.
            absent += 1
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
        if not any(MARKER.match(line) for line in lines):
            continue
        marked += 1
        rel = path.relative_to(root) if path.is_absolute() and root in path.parents else path
        for n, code, detail in check(mask(lines), version):
            findings.append(f"{rel}:{n}  {code}  {detail}")

    if marked == 0:
        detail = f" ({absent} tracked page(s) are not on disk — sparse checkout)" if absent else ""
        print(
            "doc-timeless-check.py: no page carries `<!-- doc-check: timeless -->` — "
            f"nothing was checked, so nothing is certified{detail}.",
            file=sys.stderr,
        )
        return 2

    for line in findings:
        print(line)
    ran = "T1 T2 T3 T4" if version else "T1 T3 T4 (T2 skipped: no version declaration)"
    unread = f"; {absent} tracked page(s) not on disk (sparse checkout), not read" if absent else ""
    print(
        f"doc-timeless-check.py: {len(findings)} finding(s) over {marked} marked page(s); codes run: {ran}{unread}",
        file=sys.stderr,
    )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
