#!/usr/bin/env python3
"""Print an epic's sub-issue tree across repositories, with blockers and what is ready now.

Sub-issues and dependencies both work across repositories AND across owners, so the tree of a
single epic routinely spans three remotes. `gh issue list` cannot show that; this can.

Every line carries a full URL on purpose: the output is meant to be acted on, not looked up again.

The shape trap this exists to survive
-------------------------------------
`gh issue view --json subIssues,blockedBy,blocking` does NOT return arrays. Each of those fields
is an object: {"nodes": [...], "totalCount": N}.

    .subIssues.nodes[]      correct
    .subIssues[]            loud failure — gojq: expected an object but got: array
    .blockedBy | length     SILENT failure — returns 2, counting the object's two keys, for an
                            issue with no blockers at all, and reads exactly like "two blockers"

See rules/git-issues.md §5.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from typing import Any

FIELDS = "number,title,state,url,issueType,labels,milestone,subIssues,blockedBy"
MAX_DEPTH = 8  # GitHub's own sub-issue nesting limit


class GhError(RuntimeError):
    """A `gh` invocation failed; the message names the input and what gh said."""


def _color(enabled: bool) -> dict[str, str]:
    if not enabled:
        return dict.fromkeys(("bold", "green", "yellow", "dim", "off"), "")
    return {
        "bold": "\033[1m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "dim": "\033[2m",
        "off": "\033[0m",
    }


def view(ref: str) -> dict[str, Any]:
    """Read one issue. `ref` is a URL, or `owner/repo#N` / a bare number with -R already implied."""
    proc = subprocess.run(
        ["gh", "issue", "view", ref, "--json", FIELDS],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise GhError(f"gh issue view {ref} failed: {proc.stderr.strip() or 'no output'}")
    return json.loads(proc.stdout)


def type_of(issue: dict[str, Any]) -> str:
    """The issue's type.

    Native issue types are an ORGANISATION-level feature, so a personal-account repository has
    none and carries the type in a `type:*` label instead. Read both, or the tree is blank for
    exactly the repositories that need it most.
    """
    native = (issue.get("issueType") or {}).get("name")
    if native:
        return native
    for label in issue.get("labels") or []:
        name = label.get("name", "")
        if name.startswith("type:"):
            return name.removeprefix("type:").capitalize()
    return "—"


def open_blockers(issue: dict[str, Any]) -> list[dict[str, Any]]:
    return [b for b in issue["blockedBy"]["nodes"] if b["state"] == "OPEN"]


def short(url: str) -> str:
    return url.replace("https://github.com/", "").replace("/issues/", "#")


def render(ref: str, depth: int, c: dict[str, str], seen: set[str]) -> None:
    epic = view(ref)
    url = epic["url"]
    if url in seen:
        print(f"{'  ' * depth}{c['dim']}(already shown above: {url}){c['off']}")
        return
    seen.add(url)

    children = [view(n["url"]) for n in epic["subIssues"]["nodes"]]
    done = sum(1 for k in children if k["state"] != "OPEN")
    pad = "  " * depth

    print(f"\n{pad}{c['bold']}{epic['title']}{c['off']}")
    print(f"{pad}  {url}")
    milestone = (epic.get("milestone") or {}).get("title") or "—"
    print(
        f"{pad}  type={type_of(epic)}  state={epic['state']}  "
        f"progress={done}/{len(children)}  milestone={milestone}"
    )

    if not children:
        # Say it. Empty sections below would read as "nothing is blocked", which is a different
        # statement from "this issue has no children at all".
        print(f"{pad}  {c['dim']}no sub-issues — this is not a parent{c['off']}")
        return

    ready: list[dict[str, Any]] = []
    blocked: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    closed: list[dict[str, Any]] = []
    for kid in children:
        if kid["state"] != "OPEN":
            closed.append(kid)
            continue
        blockers = open_blockers(kid)
        if blockers:
            blocked.append((kid, blockers))
        else:
            ready.append(kid)

    print(f"\n{pad}  {c['green']}READY NOW ({len(ready)}){c['off']}")
    for kid in ready:
        print(f"{pad}    [{type_of(kid):<7}] {kid['title']}")
        print(f"{pad}              {kid['url']}")

    print(f"\n{pad}  {c['yellow']}BLOCKED ({len(blocked)}){c['off']}")
    for kid, blockers in blocked:
        print(f"{pad}    [{type_of(kid):<7}] {kid['title']}")
        print(f"{pad}              {kid['url']}")
        for b in blockers:
            print(f"{pad}              {c['dim']}← blocked by {short(b['url'])}  {b['url']}{c['off']}")

    if closed:
        print(f"\n{pad}  CLOSED ({len(closed)})")
        for kid in closed:
            print(f"{pad}    {kid['url']}  {kid['title']}")

    if depth + 1 < MAX_DEPTH:
        for kid in children:
            if kid["subIssues"]["totalCount"]:
                render(kid["url"], depth + 1, c, seen)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print an epic's sub-issue tree across repositories, with blockers.",
    )
    parser.add_argument("epic", nargs="+", help="epic issue URL (repeatable)")
    parser.add_argument(
        "--no-color", action="store_true", help="plain output (also implied when not a TTY)"
    )
    args = parser.parse_args(argv)

    if shutil.which("gh") is None:
        print("gh is not on PATH — install the GitHub CLI", file=sys.stderr)
        return 1

    use_color = not args.no_color and sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
    c = _color(use_color)

    try:
        for ref in args.epic:
            render(ref, 0, c, seen=set())
    except GhError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
