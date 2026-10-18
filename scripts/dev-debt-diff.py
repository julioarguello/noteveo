#!/usr/bin/env python3
"""dev-debt-diff — what tech-debt markers a branch adds and removes.

Markers cannot reach the integration branch without a pull request somebody
approves, so the approver IS the control on debt proliferation — but only if
the PR tells them. This produces that table.

Both directions matter. A marker REMOVED is a tracked GitHub issue that the
todo-to-issue action auto-closes the moment the branch merges, which is the
half nobody advertises.

Reads the diff from the MERGE BASE (`A...B`, three dots) — exactly what the PR
shows. Two dots would drag in everything the target gained since you branched
and report markers you never wrote.

Usage:
  dev-debt-diff.py                      against origin/main
  dev-debt-diff.py --base origin/develop
  dev-debt-diff.py --head my-branch     default: HEAD
  dev-debt-diff.py --format markdown    a table for the PR body (default)
  dev-debt-diff.py --format plain       one marker per line
  dev-debt-diff.py --format json

Exit codes: 0 always, including when there is nothing to report. Finding no
markers is a normal outcome, not a failure — this never gates a push.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field

# The severity carried by each identifier, per the tech-debt marker vocabulary.
SEVERITY = {"FIXME": "medium", "TODO": "blocked", "HACK": "workaround"}

# The identifier must be IMMEDIATELY preceded by a comment opener. Without that
# guard the pattern matches its own documentation: any page defining the
# vocabulary lists `FIXME(tech-debt): ...` in prose, and a naive grep reports
# the document that defines markers as a file full of them. The tracker
# itself does not have this problem — it only ever looks inside comments — so a
# reporter that is looser than the tracker reports debt that will never exist.
COMMENT_OPENER = r"(?:\#|//|<!--|/\*|--|;|!|\*)[ \t]*"
MARKER = re.compile(COMMENT_OPENER + r"(FIXME|TODO|HACK)\(tech-debt\)\s*:?\s*(.*)$")
HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass(frozen=True)
class Marker:
    """One marker line, on the side of the diff it appeared on."""

    change: str  # "+" added by this branch, "-" removed by it
    path: str
    line: int
    severity: str
    text: str

    def sort_key(self) -> tuple[str, ...]:
        return (self.change, self.path, f"{self.line:08d}")


@dataclass
class Delta:
    added: list[Marker] = field(default_factory=list)
    removed: list[Marker] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.added and not self.removed


def parse_diff(diff: str) -> Delta:
    """Walk a unified diff, tracking line numbers on both sides."""
    delta = Delta()
    old_path = new_path = ""
    old_line = new_line = 0

    for raw in diff.splitlines():
        if raw.startswith("--- a/"):
            old_path = raw[6:]
        elif raw.startswith("+++ b/"):
            new_path = raw[6:]
        elif (hunk := HUNK.match(raw)) is not None:
            old_line, new_line = int(hunk.group(1)), int(hunk.group(2))
        elif raw.startswith("+") and not raw.startswith("+++"):
            if (m := MARKER.search(raw)) is not None:
                delta.added.append(_marker("+", new_path, new_line, m))
            new_line += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            if (m := MARKER.search(raw)) is not None:
                delta.removed.append(_marker("-", old_path, old_line, m))
            old_line += 1
        elif raw.startswith(" "):
            old_line += 1
            new_line += 1

    return delta


def _marker(change: str, path: str, line: int, m: re.Match[str]) -> Marker:
    text = m.group(2).strip()
    # A block comment closes on the same line when the marker is a one-liner.
    for closer in ("-->", "*/", "*/}"):
        if text.endswith(closer):
            text = text[: -len(closer)].strip()
    return Marker(change, path, line, SEVERITY[m.group(1)], text)


def render_markdown(delta: Delta) -> str:
    if delta.is_empty():
        return ""
    head = (
        "## Tech Debt\n\n"
        f"**+{len(delta.added)} added** · **−{len(delta.removed)} resolved**\n\n"
        "| | Location | Severity | What |\n|:--|:--|:--|:--|\n"
    )
    rows = [
        f"| {'+' if m.change == '+' else '−'} | `{m.path}:{m.line}` "
        f"| {m.severity} | {m.text} |"
        for m in sorted(delta.added + delta.removed, key=Marker.sort_key)
    ]
    return head + "\n".join(rows) + "\n"


def render_plain(delta: Delta) -> str:
    if delta.is_empty():
        return "no tech-debt markers added or removed"
    return "\n".join(
        f"{m.change}  {m.path}:{m.line}  [{m.severity}]  {m.text}"
        for m in sorted(delta.added + delta.removed, key=Marker.sort_key)
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="origin/main", help="integration branch (default: origin/main)")
    ap.add_argument("--head", default="HEAD", help="branch under review (default: HEAD)")
    ap.add_argument("--format", choices=("markdown", "plain", "json"), default="markdown")
    args = ap.parse_args()

    cmd = ["git", "diff", f"{args.base}...{args.head}", "-U0"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        # Name the range: "unknown revision" reads like a deleted branch otherwise.
        print(f"git diff {args.base}...{args.head} failed:\n{proc.stderr.strip()}", file=sys.stderr)
        return 0

    delta = parse_diff(proc.stdout)

    if args.format == "json":
        print(json.dumps({
            "added": [vars(m) for m in delta.added],
            "removed": [vars(m) for m in delta.removed],
        }, indent=2, ensure_ascii=False))
    elif args.format == "plain":
        print(render_plain(delta))
    else:
        out = render_markdown(delta)
        print(out if out else "<!-- no tech-debt markers added or removed -->")

    return 0


if __name__ == "__main__":
    sys.exit(main())
