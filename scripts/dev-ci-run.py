#!/usr/bin/env python3
"""dev-ci-run — run the project's OWN CI gates locally, before pushing.

The point is not to re-implement the gates: it is to execute the very
steps CI will execute, read from the CI definition itself. Anything
re-implemented drifts, and drift is what makes a branch green locally
and red in CI.

Discovery order (first hit wins):
  1. .github/workflows/*.yml triggered by pull_request, or by a push that
     reaches branches (a push restricted to tags is a release, never a gate)
  2. Makefile target `gate`, else `ci` → `make gate` / `make ci`
  3. package.json script `ci`      → `npm run ci`

Every step is classified and reported. A step that CANNOT run locally is
reported as SKIPPED with the reason — never as passed: a check that
cannot fail is worse than no check. A step that PUBLISHES or DEPLOYS
(PUBLISH_COMMANDS) is always SKIPPED, even under --workflow.

Usage:
  dev-ci-run.py                 run every runnable gate, stop at first failure
  dev-ci-run.py --list          show the plan without running anything
  dev-ci-run.py --only types    run steps whose name matches a substring
  dev-ci-run.py --from build    start at the first step matching, keep going
  dev-ci-run.py --keep-going    run all steps, report every failure
  dev-ci-run.py --workflow F    force a specific workflow file
  dev-ci-run.py --job J         pick a job by id/name (default: the gating one)

Exit codes: 0 all runnable gates passed · 1 a gate failed · 2 nothing to run
(no gate definition found, or the definition parsed to zero steps — that is
an error, not a pass).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

GREEN, RED, YELLOW, DIM, BOLD, OFF = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m",
)
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    GREEN = RED = YELLOW = DIM = BOLD = OFF = ""

EXPR = re.compile(r"\$\{\{\s*([a-zA-Z0-9_.\-]+)\s*\}\}")

# Commands that publish or deploy. A step running one is SKIPPED, always, even
# under --workflow: this script runs from a laptop before a push, with the
# laptop's credentials, and a publish from there is never a gate — it is a
# release nobody cut. Matched per shell command (the text split on && || ; | &
# and newlines, with quoted strings masked so a quoted `;` does not split),
# never in an `echo`/`printf` message or a comment, so a message that QUOTES the
# command does not hide a gate. A command substitution (`$(...)`, backticks) and
# a quoted argument outside a message are scanned as commands of their own:
# `bash -c 'mvn deploy'` and `echo $(mvn deploy)` both run it. Measured
# 2026-10-08 (#653): a Maven reactor's tag-triggered publish-gar.yml listed
# `mvn deploy -f bom/pom.xml -N` — buried in an `if` — as runnable. A table, not
# a heuristic: a publish reached through a wrapper this table does not name
# (`./release.sh`, `$MVN deploy`) is NOT caught.
# The end of a command word: whitespace, a quote or backtick (`tf-env.py -r
# "terraform apply"`), `;`, `)`, a redirect or `&`/`|`, or the end of the text.
_END = r"(?=[\s\"'`;)<>&|]|$)"


def _tool(names: str) -> str:
    """A command word: not inside a path or a hyphenated name (`.mvn/`, `assert-no-mvn`,
    `./docker/build.sh`), but `/usr/bin/mvn`, `./mvnw` and `${MVN:-mvn}` still count."""
    return rf"(?<![\w.])(?<!\w-)(?:{names})(?=[\s}}])"


# Maven options that take the next word as their value: `-pl deploy` names a
# module, `-P deploy` a profile — neither is the deploy phase.
_MVN_ARG = r"(?<!\s-pl)(?<!\s-P)(?<!\s-f)(?<!\s-s)(?<!\s-rf)(?<!--projects)(?<!--file)(?<!--settings)"
PUBLISH_COMMANDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("mvn deploy", re.compile(
        _tool(r"mvn[wd]?") + r".*?(?:" + _MVN_ARG + r"\s(?:deploy(?::[\w-]+)?|release:(?:perform|prepare))"
        r"|maven-deploy-plugin:(?:\S*:)?deploy[\w-]*)" + _END)),
    ("gradle publish", re.compile(_tool(r"gradlew?") + r".*?\s(?::\S*:)?publish(?!\w*ToMavenLocal)\w*" + _END)),
    ("container image push", re.compile(
        _tool(r"docker|podman|buildah") + r".*?\s(?:push|--push(?!=false)(?:=\S*)?)" + _END)),
    ("gcloud deploy/upload", re.compile(_tool(r"gcloud") + r".*?\s(?:deploy|upload)" + _END)),
    ("gh release create/upload", re.compile(_tool(r"gh") + r"\s+release\s+(?:create|upload)\b")),
    ("twine upload", re.compile(_tool(r"twine") + r".*?\supload" + _END)),
    ("npm/yarn/pnpm publish", re.compile(_tool(r"npm|yarn|pnpm") + r".*?\spublish" + _END)),
    ("terraform apply/destroy", re.compile(_tool(r"terraform|tofu") + r".*?\s(?:apply|destroy)" + _END)),
    # A second Maven reactor's tag-triggered publish workflow runs `make deploy` (measured
    # 2026-10-08, #656): the target name is the only thing visible from here, and
    # `deploy`/`publish`/`release` say it.
    ("make deploy/publish/release", re.compile(_tool(r"make") + r".*?\s(?:deploy|publish|release)" + _END)),
)
_QUOTED = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'[^']*'")
_SUBSTITUTION = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")
_SEPARATOR = re.compile(r"&&|\|\||[;|&\n]")
# Words that may stand before the command proper: `then echo …` is still a message.
_PREFIX = r"(?:(?:then|else|do|if|while|until|!|\{|\(|time|sudo|command|exec)\s+|[A-Za-z_]\w*=\S*\s+)*"
# A dry run publishes nothing: `npm publish --dry-run`, `make -n deploy`. `-n` only
# for make — `gh release create -n <notes>` is a real release.
_DRY_RUN = re.compile(r"\s--dry-run(?=[\s;)]|$)|" + _tool(r"make") + r".*?\s(?:-n|--just-print|--recon)(?=[\s;)]|$)")


def _is_message(cmd: str) -> bool:
    """`echo`/`printf` print text; what they print is not a command."""
    return re.match(r"\s*" + _PREFIX + r"(?:echo|printf)\b", cmd) is not None


def _segments(text: str) -> Iterator[tuple[int, str]]:
    """Each shell command of `text` with its offset."""
    start = 0
    for sep in _SEPARATOR.finditer(text):
        yield start, text[start:sep.start()]
        start = sep.end()
    yield start, text[start:]


def publishes(run: str) -> str | None:
    """The PUBLISH_COMMANDS label the shell text runs, or None."""
    text = run.replace("\\\n", " ")
    for sub in _SUBSTITUTION.finditer(text):  # runs even inside an echo
        found = publishes(sub.group(1) if sub.group(1) is not None else sub.group(2))
        if found:
            return found
    # Same length, quotes kept: offsets in `masked` are offsets in `text`, and a
    # `;`, `#` or `|` inside a quoted string no longer splits or truncates.
    masked = _QUOTED.sub(lambda q: q.group(0)[0] + "_" * (len(q.group(0)) - 2) + q.group(0)[-1], text)
    for offset, seg in _segments(masked):
        cmd = re.sub(r"(?:^|\s)#.*$", "", seg)
        if not cmd.strip() or _is_message(cmd) or _DRY_RUN.search(cmd):
            continue
        for label, pattern in PUBLISH_COMMANDS:
            if pattern.search(cmd):
                return label
        for quoted in _QUOTED.finditer(text[offset:offset + len(cmd)]):
            found = publishes(quoted.group(0)[1:-1])
            if found:
                return found
    return None


def unquote(v: str) -> str:
    """Strip quotes only when the WHOLE scalar is quoted.

    A blanket .strip("'\"") corrupts any command that merely contains a
    quote — `echo "all good"` became `echo "all good`, a broken shell line
    that the harness then reported as a failing gate. Caught by the
    positive control, which is the only reason a harness can be trusted.
    """
    v = v.strip()
    if len(v) > 1 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    return v


# ─────────────────────────────────────────────────────────────────────
# YAML: PyYAML when available, else a scanner for the GitHub subset
# ─────────────────────────────────────────────────────────────────────
def load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
        return yaml.safe_load(path.read_text()) or {}
    except ImportError:
        return _scan_workflow(path.read_text())


def _scan_triggers(block: list[str]) -> dict[str, Any]:
    """The `on:` block as {event: {filter: value}} — a trigger's filters stay UNDER it.

    The first version promoted every indented key under `on:` to a trigger, so
    `push: tags: ["v*"]` read as `{"push": {}, "tags": {}}`: the filter that says
    "tags only" was lost and the release workflow looked like a branch gate.
    Measured 2026-10-08 on a Maven reactor repository (#653). Only the direct children of
    a trigger are kept (`branches`, `tags`, `paths`, `types`, ...), with a flow or
    block list as a list and anything nested deeper as True: selection needs their
    names, and the value only of `pull_request: types:`.
    """
    def indent(s: str) -> int:
        return len(s) - len(s.lstrip(" "))

    triggers: dict[str, Any] = {}
    trig_indent: int | None = None
    current: str | None = None
    child_indent: int | None = None
    last_child: str | None = None
    for ln in block:
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        ind = indent(ln)
        if ind == 0:
            break
        if trig_indent is None:
            trig_indent = ind
        m_list = re.match(r"^\s+-\s+([a-z_]+)\s*$", ln)
        m = re.match(r"^\s+([A-Za-z0-9_\-]+):\s*(.*)$", ln)
        if ind == trig_indent:
            if m_list:  # on:\n  - push\n  - pull_request
                triggers[m_list.group(1)] = {}
                current = None
            elif m:
                current, child_indent = m.group(1), None
                inline = m.group(2).strip()
                # `push: {tags: [v*]}` — a flow mapping carries its filters inline
                triggers[current] = ({k: True for k in re.findall(r"([A-Za-z_\-]+)\s*:", inline)}
                                     if inline.startswith("{") else {})
            continue
        m_item = re.match(r"^\s+-\s+(.+?)\s*$", ln)
        if current and last_child and m_item and child_indent is not None and ind > child_indent:
            # `types:\n  - closed` — a block list under a filter
            value = triggers[current][last_child]
            triggers[current][last_child] = [*(value if isinstance(value, list) else []),
                                             unquote(m_item.group(1))]
            continue
        if current is None or not m:
            continue
        if child_indent is None:
            child_indent = ind
        if ind == child_indent:
            last_child = m.group(1)
            triggers[current][last_child] = _inline_value(m.group(2))
    return triggers


def _inline_value(raw: str) -> Any:
    """`[a, b]` → ["a", "b"]; `a` → "a"; nothing (a block follows) → True.

    Selection needs a filter's value only for `pull_request: types:` (#659).
    """
    raw = re.sub(r"\s+#.*$", "", raw).strip()
    if not raw:
        return True
    if raw.startswith("[") and raw.endswith("]"):
        return [unquote(v) for v in raw[1:-1].split(",") if v.strip()]
    return unquote(raw)


def _scan_workflow(text: str) -> dict[str, Any]:
    """Minimal GitHub-workflow reader: on/jobs/steps with name|run|uses|env.

    Deliberately narrow. It reads what a workflow actually contains — a
    steps list of scalars and block scalars — and nothing else. When it
    cannot find steps it returns empty, and the caller treats that as an
    error rather than a pass.
    """
    lines = text.splitlines()

    def indent(s: str) -> int:
        return len(s) - len(s.lstrip(" "))

    doc: dict[str, Any] = {"on": {}, "jobs": {}}
    # triggers: either "on: [a, b]", "on: a" or a block of keys
    for i, ln in enumerate(lines):
        if re.match(r"^on:\s*$", ln):
            doc["on"] = _scan_triggers(lines[i + 1:])
            break
        m = re.match(r"^on:\s*\[?([a-z_,\s]+)\]?\s*$", ln)
        if m:
            for name in re.split(r"[,\s]+", m.group(1).strip()):
                if name:
                    doc["on"][name] = {}
            break

    # jobs → steps
    ji = next((i for i, ln in enumerate(lines) if re.match(r"^jobs:\s*$", ln)), None)
    if ji is None:
        return doc
    job_id, steps, in_steps = None, [], False
    step: dict[str, Any] | None = None
    sub_key, sub_indent = None, 0
    block_key, block_indent, block_lines = None, 0, []

    def flush_block() -> None:
        nonlocal block_key, block_lines
        if step is not None and block_key:
            step[block_key] = "\n".join(block_lines).rstrip("\n")
        block_key, block_lines = None, []

    def flush_step() -> None:
        nonlocal step
        flush_block()
        if step:
            steps.append(step)
        step = None

    job_env: dict[str, str] = {}
    in_job_env = False

    for ln in lines[ji + 1:]:
        if not ln.strip():
            if block_key:
                block_lines.append("")
            continue
        ind = indent(ln)
        if ind == 0:  # left the jobs mapping
            break
        if block_key and ind >= block_indent:
            block_lines.append(ln[block_indent:])
            continue
        if block_key:
            flush_block()

        m = re.match(r"^  ([A-Za-z0-9_\-]+):\s*$", ln)
        if m:  # a job id
            flush_step()
            if job_id and steps:
                doc["jobs"][job_id] = {"steps": list(steps), "env": dict(job_env)}
            job_id, steps, in_steps = m.group(1), [], False
            sub_key, sub_indent = None, 0
            job_env, in_job_env = {}, False
            continue
        if re.match(r"^\s+steps:\s*$", ln):
            in_steps = True
            in_job_env = False
            continue
        if not in_steps:
            # Job-level `env:`, which is where Actions workflows put their
            # variables almost always. Sits between the job id and `steps:`,
            # so it has to be picked up here or not at all.
            if re.match(r"^ {4}env:\s*$", ln):
                in_job_env = True
                continue
            if in_job_env:
                if ln.lstrip().startswith("#"):
                    # A comment inside the block is not the end of it. Measured
                    # 2026-09-17 (#368) on a dbt repository, whose ci.yml explains DBT_TARGET
                    # right under `env:`: the first comment line closed the block
                    # and the variable never reached the subprocess.
                    continue
                m_env = re.match(r"^ {6}([A-Za-z0-9_.\-]+):\s*(.*)$", ln)
                if m_env:
                    job_env[m_env.group(1)] = unquote(m_env.group(2).strip())
                    continue
                in_job_env = False
            continue
        m = re.match(r"^\s+-\s+([A-Za-z0-9_.\-]+):\s*(.*)$", ln)
        if m:  # new step
            flush_step()
            step, sub_key, sub_indent = {}, None, 0
            key, val = m.group(1), m.group(2).strip()
            if val in ("|", ">", "|-", ">-"):
                block_key, block_indent, block_lines = key, ind + 4, []
            else:
                step[key] = unquote(val)
            continue
        m = re.match(r"^\s+([A-Za-z0-9_.\-]+):\s*(.*)$", ln)
        if m and step is not None:
            key, val = m.group(1), m.group(2).strip()
            # a nested map closed when the indentation came back
            if sub_key and ind <= sub_indent:
                sub_key = None
            if sub_key:  # env/with entry — keys here are often UPPERCASE,
                step.setdefault(sub_key, {})[key] = unquote(val)  # which a
                continue                                          # lowercase-only
            if val in ("|", ">", "|-", ">-"):                      # regex missed
                block_key, block_indent, block_lines = key, ind + 2, []
            elif val == "":
                sub_key, sub_indent = key, ind
                step[key] = {}
            else:
                step[key] = unquote(val)
    flush_step()
    if job_id and steps:
        doc["jobs"][job_id] = {"steps": list(steps), "env": dict(job_env)}
    return doc


# ─────────────────────────────────────────────────────────────────────
# discovery
# ─────────────────────────────────────────────────────────────────────
def project_root() -> Path:
    p = Path.cwd().resolve()
    for cand in [p, *p.parents]:
        if (cand / ".git").exists():
            return cand
    return p


def is_gate_trigger(triggers: Any) -> bool:
    """True when the workflow runs on a pull request or on a push TO A BRANCH.

    Only those are pre-push gates. Everything else — `release`, `schedule`,
    `workflow_dispatch`, a `push` restricted to tags, a `pull_request` on
    `types: [closed]` alone (#659) — is a release or an operation, and this
    script runs before every push from a laptop.

    A `push` is tag-only when it filters on `tags`/`tags-ignore` and on neither
    `branches` nor `branches-ignore`: GitHub then never fires it for a branch
    (with both kinds of filter it fires for either; with neither, for both).

    Measured 2026-10-08 on a Maven reactor repository (#653): the first version took any
    `push` key as a gate and scored candidates by runnable steps, so with no
    --workflow it selected `publish-gar.yml` (`push: tags: ["v*"]`, 5 runnable
    steps) over `secrets.yml` (2), and listed `mvn deploy` to the production
    release registry as runnable. Without --keep-going the run stopped at the tag
    guard; with it, the laptop could have published the BOM with its own
    credentials.
    """
    if isinstance(triggers, str):
        triggers = {triggers: None}
    elif isinstance(triggers, list):
        triggers = {str(t): None for t in triggers}
    if not isinstance(triggers, dict):
        return False
    if "pull_request" in triggers and not _closed_only(triggers["pull_request"]):
        return True
    if "push" not in triggers:
        return False
    push = triggers["push"]
    if not isinstance(push, dict):  # bare `push:` — every branch and every tag
        return True
    tag_filtered = "tags" in push or "tags-ignore" in push
    branch_filtered = "branches" in push or "branches-ignore" in push
    return branch_filtered or not tag_filtered


def _closed_only(pull_request: Any) -> bool:
    """`pull_request: types: [closed]` runs after a merge (release-on-merge), never on a change.

    Measured 2026-10-08 in review of #656 (#659): such a workflow was a candidate
    for auto-selection, with only the publish table between it and a publish.
    """
    types = pull_request.get("types") if isinstance(pull_request, dict) else None
    if isinstance(types, str):
        types = [types]
    return isinstance(types, list) and bool(types) and {str(t) for t in types} == {"closed"}


def find_workflow(root: Path, forced: str | None) -> Path | None:
    if forced:
        # Resolve against the repo root: `--workflow .github/workflows/x.yml`
        # is what a person types, and the caller later does relative_to(root),
        # which raises ValueError on a relative path. The escape hatch out of
        # a vacuous plan crashed with a traceback instead of running the gate
        # it was pointed at (measured 2026-08-27).
        f = Path(forced)
        f = f if f.is_absolute() else (root / f)
        if not f.is_file():
            # Fail where the input is read, naming it. Returning None here sent
            # a typo'd --workflow down the auto-discovery fallback, which then
            # ran a DIFFERENT plan (`make gate`) and reported it as a normal
            # run — an explicit choice silently replaced by another one.
            sys.exit(f"{RED}--workflow {forced}: no such file{OFF}")
        return f.resolve()
    wf_dir = root / ".github" / "workflows"
    if not wf_dir.is_dir():
        return None
    best: tuple[int, Path] | None = None
    for f in sorted(wf_dir.glob("*.y*ml")):
        doc = load_yaml(f)
        # YAML 1.1 reads a bare `on:` key as the boolean True, so a workflow
        # written `on: push` lands under doc[True] as the STRING "push" — and
        # set("push") is {"p","u","s","h"}, which intersects nothing. The
        # workflow was then skipped silently, which is indistinguishable from
        # a repo that has no gate workflow at all.
        triggers = doc.get("on") or doc.get(True) or {}
        if not is_gate_trigger(triggers):
            continue
        # Score by RUNNABLE steps, not by step count. The comment here used to
        # say "the most runnable steps" while counting every step — and the two
        # diverge exactly where it matters. Adding a two-step tracker workflow
        # to a repo whose real CI is workflow_dispatch (never eligible here)
        # handed selection to a workflow of two third-party actions, both of
        # which classify as SKIP: the tool then reported a plan of zero gates
        # as a normal run. A candidate that can run nothing is not a gate, so
        # it must not beat the Makefile fallback, which usually IS one.
        _, raw, raw_env = pick_job(doc, None)
        n = sum(1 for st in raw
                if isinstance(st, dict) and not Step(0, st, raw_env).skip_reason)
        if n and (best is None or n > best[0]):
            best = (n, f)
    return best[1] if best else None


def pick_job(doc: dict[str, Any],
             wanted: str | None) -> tuple[str, list[dict], dict[str, str]]:
    """The job's steps AND its `env:` block — the steps are unreadable without it."""
    jobs = doc.get("jobs") or {}
    if wanted:
        for jid, job in jobs.items():
            if wanted in (jid, (job or {}).get("name", "")):
                return jid, (job or {}).get("steps") or [], (job or {}).get("env") or {}
        return wanted, [], {}
    best = ("", [], {})
    for jid, job in jobs.items():
        steps = (job or {}).get("steps") or []
        if len(steps) > len(best[1]):
            best = (jid, steps, (job or {}).get("env") or {})
    return best


# ─────────────────────────────────────────────────────────────────────
# planning
# ─────────────────────────────────────────────────────────────────────
class Step:
    def __init__(self, idx: int, raw: dict[str, Any],
                 job_env: dict[str, str] | None = None):
        self.idx = idx
        self.name = raw.get("name") or raw.get("uses") or f"step {idx}"
        self.run = raw.get("run")
        self.uses = raw.get("uses")
        # Job-level `env:` first, the step's own on top -- the precedence
        # GitHub applies. Dropping the job block used to report FAIL locally on
        # a workflow that is green in CI, because that is where the variables
        # almost always live (origin: #290).
        self.env = {**(job_env or {}), **(raw.get("env") or {})}
        self.skip_reason: str | None = None
        self._classify()

    def _classify(self) -> None:
        if not self.run:
            self.skip_reason = (
                f"action step (`{self.uses}`) — environment setup, not a gate"
                if self.uses else "no shell command"
            )
            return
        # First, so it is the reason shown: the #653 reactor's "Deploy to Artifact Registry"
        # was SKIP only for an unresolved expression — an accident, not a guard.
        published = publishes(self.run)
        if published:
            self.skip_reason = (f"publishes ({published}) — step '{self.name}' is a release, "
                                "never run locally: it would publish with this machine's credentials")
            return
        missing = [
            ref.split(".", 1)[1]
            for ref in EXPR.findall(" ".join(str(v) for v in self.env.values()))
            if ref.startswith("secrets.") and not os.environ.get(ref.split(".", 1)[1])
        ]
        if missing:
            self.skip_reason = f"needs secret(s) {', '.join(missing)} — export them to run it"
            return
        unresolved = [r for r in EXPR.findall(self.run) if not r.startswith(("env.", "github."))]
        if unresolved:
            self.skip_reason = f"unresolved CI expression(s): {', '.join(sorted(set(unresolved)))}"
            return
        # Runner-only files (job summary, outputs, env, path): CI plumbing,
        # not gates. Locally the variable is empty and the redirect fails,
        # which would report a green pipeline as broken.
        runner_files = [v for v in ("GITHUB_STEP_SUMMARY", "GITHUB_OUTPUT",
                                    "GITHUB_ENV", "GITHUB_PATH")
                        if v in self.run and not os.environ.get(v)]
        if runner_files:
            self.skip_reason = (f"writes to {', '.join(runner_files)} — GitHub runner "
                                "reporting, not a gate")

    def command(self) -> str:
        return expand(self.run or "")

    def env_overlay(self) -> dict[str, str]:
        return {k: expand(str(v)) for k, v in self.env.items()}



def expand(text: str) -> str:
    """Resolve `${{ ... }}` against the environment; blank out what we cannot.

    Only `env.` and `secrets.` refs resolve — everything else GitHub would
    expand (`github.*`, `runner.*`, `hashFiles(...)`, bare literals) has no
    local meaning and becomes empty.

    The guard on the prefix is not cosmetic: EXPR's character class matches
    bare identifiers too, so `${{ RUNNER_TEMP }}` captures `RUNNER_TEMP`, and
    splitting that on "." yields one element. Indexing [1] then raises
    IndexError and takes the whole harness down with a traceback instead of a
    verdict — the failure this tool exists to prevent. Both call sites go
    through here so the guard cannot go missing from one of them again.
    """
    def sub(m: "re.Match[str]") -> str:
        ref = m.group(1)
        if ref.startswith(("env.", "secrets.")):
            return os.environ.get(ref.split(".", 1)[1], "")
        return ""

    return EXPR.sub(sub, text)


def refuse_vacuous(source: str) -> int:
    """A plan whose every step is skipped verified NOTHING.

    Measured 2026-08-27: adding a two-step tracker workflow to a repo whose
    real CI is `workflow_dispatch` (and therefore not eligible here) made this
    script select the tracker, classify both of its third-party action steps as
    SKIP, print "0 gate(s) passed" and exit 0. Green, before every push, having
    run nothing. A check that finds no problems and one that CANNOT find
    problems are indistinguishable from outside — so this one says which it is.
    """
    print(f"{RED}Nothing runnable in {source}.{OFF}\n"
          "Every step was skipped, so this run verified NOTHING — it is not a pass.\n"
          "Point it at the real gate:  dev-ci-run.py --workflow <file> [--job <id>]\n"
          "List what it can see:       dev-ci-run.py --list", file=sys.stderr)
    return 2


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True, description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="show the plan, run nothing")
    ap.add_argument("--only", metavar="TEXT", help="run only steps whose name matches")
    ap.add_argument("--from", dest="from_", metavar="TEXT", help="start at the matching step")
    ap.add_argument("--keep-going", action="store_true", help="do not stop at the first failure")
    ap.add_argument("--workflow", metavar="FILE", help="force a workflow file")
    ap.add_argument("--job", metavar="JOB", help="pick a job by id or name")
    args = ap.parse_args()

    root = project_root()
    os.chdir(root)

    wf = find_workflow(root, args.workflow)
    steps: list[Step] = []
    source = ""
    if wf:
        doc = load_yaml(wf)
        jid, raw_steps, job_env = pick_job(doc, args.job)
        steps = [Step(i, s, job_env)
                 for i, s in enumerate(raw_steps, 1) if isinstance(s, dict)]
        source = f"{wf.relative_to(root)} · job {jid}"
        if not steps:
            print(f"{RED}Found {wf} but parsed zero steps.{OFF} "
                  "Refusing to report success on an empty plan — check the file "
                  "or pass --job.", file=sys.stderr)
            return 2
    else:  # fallbacks
        mk = root / "Makefile"
        pkg = root / "package.json"
        # `gate` before `ci`, deliberately. This script is meant to run before
        # EVERY push, and in a project where `ci`
        # ends in a publish step that would push images to a registry on
        # every pre-push check. Where both exist, `gate` is by convention
        # the same battery minus the publish; where only `ci` exists it is
        # still the right answer. The asymmetry is what decides: picking
        # `gate` when `ci` was meant costs one missing publish the operator
        # runs on purpose, picking `ci` when `gate` was meant publishes
        # artifacts nobody asked for.
        mk_text = mk.read_text() if mk.is_file() else ""
        mk_target = next((t for t in ("gate", "ci")
                          if re.search(rf"^{t}:", mk_text, re.M)), None)
        if mk_target:
            steps = [Step(1, {"name": f"make {mk_target}", "run": f"make {mk_target}"})]
            source = f"Makefile target `{mk_target}`"
        elif pkg.is_file() and "ci" in (json.loads(pkg.read_text()).get("scripts") or {}):
            steps = [Step(1, {"name": "npm run ci", "run": "npm run ci"})]
            source = "package.json script `ci`"
        else:
            print(f"{RED}No CI definition found{OFF} (.github/workflows on "
                  "pull_request or a branch push, Makefile `gate`/`ci`, or package.json `ci`).",
                  file=sys.stderr)
            return 2

    if args.from_:
        start = next((i for i, s in enumerate(steps) if args.from_.lower() in s.name.lower()), None)
        if start is None:
            print(f"{RED}--from {args.from_!r} matched no step{OFF}", file=sys.stderr)
            return 2
        steps = steps[start:]
    if args.only:
        steps = [s for s in steps if args.only.lower() in s.name.lower()]
        if not steps:
            print(f"{RED}--only {args.only!r} matched no step{OFF}", file=sys.stderr)
            return 2

    print(f"{BOLD}local CI gates{OFF} — {source}\n")
    if args.list:
        for s in steps:
            mark = f"{YELLOW}SKIP{OFF}" if s.skip_reason else f"{DIM}run {OFF}"
            print(f"  {mark}  {s.name}" + (f"  {DIM}({s.skip_reason}){OFF}" if s.skip_reason else ""))
        runnable = sum(1 for s in steps if not s.skip_reason)
        print(f"\n{runnable} runnable · {len(steps) - runnable} skipped")
        return 0 if runnable else refuse_vacuous(source)

    failures, ran, skipped = [], 0, []
    for s in steps:
        if s.skip_reason:
            skipped.append(s)
            print(f"{YELLOW}SKIP{OFF}  {s.name}  {DIM}({s.skip_reason}){OFF}")
            continue
        print(f"{DIM}····{OFF}  {s.name}", flush=True)
        env = {**os.environ, **s.env_overlay()}
        t0 = time.time()
        proc = subprocess.run(["bash", "-eo", "pipefail", "-c", s.command()], env=env)
        dt = f"{time.time() - t0:.0f}s"
        ran += 1
        if proc.returncode == 0:
            print(f"{GREEN}PASS{OFF}  {s.name} {DIM}({dt}){OFF}")
        else:
            failures.append(s.name)
            print(f"{RED}FAIL{OFF}  {s.name} {DIM}({dt}, exit {proc.returncode}){OFF}")
            if not args.keep_going:
                break

    print()
    if not ran and not failures:
        return refuse_vacuous(source)
    if failures:
        print(f"{RED}{BOLD}{len(failures)} gate(s) failed:{OFF} " + ", ".join(failures))
        print("Fix locally and re-run — CI runs the same steps.")
        return 1
    print(f"{GREEN}{BOLD}{ran} gate(s) passed{OFF}"
          + (f" · {len(skipped)} skipped (see reasons above)" if skipped else ""))
    if skipped:
        print(f"{DIM}Skipped gates were NOT verified — name them in the PR body.{OFF}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
