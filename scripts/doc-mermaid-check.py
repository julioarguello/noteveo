#!/usr/bin/env python3
"""Check every Mermaid fence in a repository against the project style sheet.

The style sheet is this file's PALETTE/BAND/PIN constants, not prose: a role name
has exactly one colour triplet and a colour triplet has exactly one role name, so
`ext is terracotta here and violet there` cannot survive a run.

    doc-mermaid-check.py [PATH ...]        # default: every tracked *.md

Exit 0 = conformant. Exit 1 = findings, one per line as `file:line  CODE  detail`.
Exit 2 = the scan found no fences at all (positive control: a green run over an
empty inventory certifies nothing).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# --- the style sheet -------------------------------------------------------
# role -> (fill, stroke, text). Seven roles, seven triplets, no synonyms.
PALETTE: dict[str, tuple[str, str, str]] = {
    "external": ("#fdf3e7", "#c2703d", "#4a2c15"),  # not ours / the far side
    "store": ("#fbf4e0", "#b8912e", "#4a3a10"),  # where the truth is declared
    "ours": ("#f3eef8", "#7a5ba6", "#33204d"),  # ours, at rest
    "runtime": ("#e8f1fb", "#3d6fa8", "#12314f"),  # ours, in motion
    "outcome": ("#eef5ec", "#4f8a52", "#1d3a1f"),  # the good end
    "fault": ("#fbeceb", "#b8474a", "#4d1417"),  # the bad end
    "inert": ("#f4f2ee", "#9a9285", "#5a5248"),  # declared, not live
}
STROKE_WIDTH = "2.4px"
BAND = "fill:#fcfcfa,stroke:#b8b2a8,stroke-dasharray:4 4,color:#5a5248"
PIN = ('"theme":"base"', '"lineColor":"#5a5248"', '"edgeLabelBackground":"#f4f2ee"')
# `classDef` is a parse error in these kinds, so their init block is the only lever.
KIND_KEYS = {"sequence": "actorBkg", "gantt": "taskBkgColor"}

FENCE = re.compile(r"^\s*```+\s*mermaid\s*$", re.I)
CLOSE = re.compile(r"^\s*```+\s*$")
CLASSDEF = re.compile(r"^\s*classDef\s+(\w+)\s+(.*)$")
SUBGRAPH = re.compile(r"^\s*subgraph\s+(\w+)\s*\[\s*\"(.*)\"\s*\]\s*$")
BARE_SUBGRAPH = re.compile(r"^\s*subgraph\s+(\w+)\s*$")
STYLE = re.compile(r"^\s*style\s+(\w+)\s+(.*)$")
HR_LABEL = re.compile(r"<hr\s*/?>(.*?)(?=\"|\]|$)")
# A font set inline in a label: Mermaid sizes the box with it, and a renderer that drops or
# overrides the attribute (GitHub's sanitizer, an editor's CSS) draws the text wider than the box.
INLINE_FONT = re.compile(r"<[A-Za-z]+\b[^>]*\sstyle\s*=\s*['\"][^'\"]*font", re.I)
DIRECTIVE = re.compile(r"^\s*(classDef|style|linkStyle|%%)")
FONT_TAG = re.compile(r"<(tt|code|small|span|font|sub|sup|kbd|samp)\b", re.I)


def _tracked_markdown(root: Path) -> list[Path]:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "*.md"],
        capture_output=True, text=True, check=True,
    )
    return [root / p for p in out.stdout.split("\n") if p]


def _blocks(lines: list[str]):
    """Yield (start_line_1based, body_lines, legend_line_or_None)."""
    i = 0
    while i < len(lines):
        if FENCE.match(lines[i]):
            j = i + 1
            while j < len(lines) and not CLOSE.match(lines[j]):
                j += 1
            k = i - 1
            while k >= 0 and not lines[k].strip():
                k -= 1
            yield i + 1, lines[i + 1:j], (lines[k] if k >= 0 else None)
            i = j
        i += 1


def _kind(body: list[str]) -> str:
    for ln in body:
        s = ln.strip()
        if s.startswith("%%") or not s:
            continue
        if s.startswith("sequenceDiagram"):
            return "sequence"
        if s.startswith("gantt"):
            return "gantt"
        return "flowchart"
    return "flowchart"


def check_block(start: int, body: list[str], legend: str | None) -> list[tuple[int, str, str]]:
    f: list[tuple[int, str, str]] = []
    kind = _kind(body)
    text = "\n".join(body)

    init = body[0] if body and body[0].lstrip().startswith("%%{init") else None
    if init is None:
        f.append((start, "INIT-MISSING", "the fence does not open with an %%{init}%% block"))
    else:
        for key in PIN:
            if key not in init:
                f.append((start, "INIT-PIN", f"init block does not pin {key}"))
        need = KIND_KEYS.get(kind)
        if need and need not in init:
            f.append((start, "INIT-KIND", f"a {kind} diagram cannot carry classDef; its init "
                                          f"block must theme it — {need} is missing"))
    if "handDrawn" in text:
        f.append((start, "HANDDRAWN", 'look:"handDrawn" is not the house style — remove it'))

    if legend is None or legend.lstrip().startswith("#") or not legend.strip():
        f.append((start, "LEGEND", "no line above the fence saying what a node and an edge are"))

    seen: dict[str, str] = {}
    for n, ln in enumerate(body, start=start + 1):
        m = CLASSDEF.match(ln)
        if m:
            name, decl = m.group(1), m.group(2)
            if name not in PALETTE:
                f.append((n, "ROLE-UNKNOWN", f"classDef {name} — not one of {', '.join(PALETTE)}"))
                continue
            fill, stroke, color = PALETTE[name]
            want = f"fill:{fill},stroke:{stroke},stroke-width:{STROKE_WIDTH},color:{color}"
            if decl.strip() != want:
                f.append((n, "ROLE-COLOUR", f"classDef {name} must be exactly `{want}`"))
            if name in seen:
                f.append((n, "ROLE-DUP", f"classDef {name} declared twice in one diagram"))
            seen[name] = decl

        m = SUBGRAPH.match(ln)
        if m:
            sid, title = m.group(1), m.group(2)
            if not (title.startswith("&nbsp;&nbsp;&nbsp;") and title.endswith("&nbsp;&nbsp;&nbsp;")):
                f.append((n, "BAND-PAD", f"subgraph {sid} title needs three &nbsp; each side "
                                         "or the renderer clips its last character"))
            if not any(STYLE.match(s) and STYLE.match(s).group(1) == sid
                       and STYLE.match(s).group(2).strip() == BAND for s in body):
                f.append((n, "BAND-STYLE", f"subgraph {sid} has no `style {sid} {BAND}` — an "
                                           "unstyled cluster renders yellow under the default theme"))
        elif BARE_SUBGRAPH.match(ln):
            f.append((n, "BAND-PAD", f"subgraph {BARE_SUBGRAPH.match(ln).group(1)} has no "
                                     "bracketed title, so it cannot be padded or styled"))

        for tail in HR_LABEL.findall(ln):
            if FONT_TAG.match(tail.lstrip()):
                f.append((n, "LABEL-ZONE", "after <hr/> the detail is plain text — a tag that "
                                           "changes the font (<tt>, <code>, <small>, <span>) is "
                                           "measured with one font and drawn with another by "
                                           "renderers that restyle it, clipped mid-word"))
        if not DIRECTIVE.match(ln) and INLINE_FONT.search(ln):
            f.append((n, "LABEL-SIZE", "a font set inline in a label — Mermaid sizes the box with "
                                       "it and a renderer that drops the attribute draws the text "
                                       "wider than the box, clipped mid-word"))
    return f


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve()
    targets = [Path(a) for a in argv[1:]]
    if not targets:
        for up in root.parents:
            if (up / ".git").exists():
                targets = _tracked_markdown(up)
                break
        else:
            print("no git repository found above this script", file=sys.stderr)
            return 2

    # A tracked page a sparse checkout never materialised drops out of `files` here, and so
    # does an unreadable one below — recorded as tech debt in the SKILL.md of the skill that
    # ships this script, not here: this file is copied into every exporting project, whose
    # tracker would file it.
    files = [p for t in targets for p in ([t] if t.is_file() else sorted(t.rglob("*.md")))]
    findings: list[str] = []
    blocks = 0
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").split("\n")
        except (OSError, UnicodeDecodeError):
            continue
        for start, body, legend in _blocks(lines):
            blocks += 1
            for line, code, detail in check_block(start, body, legend):
                findings.append(f"{path}:{line}  {code}  {detail}")

    if not blocks:
        print(f"scanned {len(files)} files and found NO mermaid fence — the scan is the "
              "suspect, not the corpus", file=sys.stderr)
        return 2
    for line in findings:
        print(line)
    print(f"\n{blocks} diagrams in {len(files)} files · {len(findings)} findings",
          file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
