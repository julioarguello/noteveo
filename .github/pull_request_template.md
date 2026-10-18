<!-- AUTO-GENERATED — DO NOT EDIT MANUALLY. Your edits are overwritten on the next setup run. This project's own items live in .github/pull_request_template.project.md and are appended last. -->

## Review Checklist (Process)
- [ ] The project's own gates ran on THIS branch — the full set, not a subset; every SKIP is named below
- [ ] The gates ran on the target's current head: `git fetch origin && git rev-list --count HEAD..origin/<target>` printed `0` (a merge or rebase after the run means running them again)
- [ ] Conventions checked against this repository's own CONTRIBUTING and `docs/`; any convention accepted rather than followed is named below
- [ ] Every numbered item and acceptance criterion of the issue is done, or the deviation is named below with its reason
- [ ] Every acceptance criterion has a test that goes red when the behaviour it names is removed — name the mutation you tried
- [ ] Not stacked: nothing here depends on another open pull request; a change that needs another waits for it to merge
- [ ] Tech-debt delta reported — markers added AND removed, never one side alone
- [ ] `Closes #<ISSUE>` resolves to the issue this branch is named after (check the sidebar, not the text)
- [ ] **Not verified**: gates skipped, findings accepted, and anything changed but not exercised — "none" only when every box above was ticked from evidence; a reviewer who has to guess assumes everything was checked
