# Skills

Skills are reusable, repeatable procedures for Copilot. They live in `.github/skills/<name>/SKILL.md` and are invoked with a
single command (for example `/create-pr-cloud`) or picked automatically when the description matches the request.

## Skill, agent or instruction?

| Kind | Location | Use it for |
|------|----------|------------|
| Instruction | `.github/copilot-instructions.md` | Passive rules and context that always apply; it is not executed |
| Agent | `.github/agents/*.agent.md` | A specialist persona with its own role, tools and context (reviewer, QA, ...) |
| Skill | `.github/skills/<name>/SKILL.md` | A multi-step procedure run on demand that may delegate to agents and call `git`/`gh` |

A skill orchestrates; it does not replace the agents. Do not duplicate agent or workflow rules in a skill: link to
`.github/copilot-instructions.md` and the agent files instead.

## Writing a skill

- One directory per skill, kebab-case name matching the `name` frontmatter.
- `SKILL.md` starts with frontmatter containing `name` and a `description` that says what it does and when to use it.
- State the rules first (guards, stop conditions), then numbered steps with exact commands.
- Never weaken repository gates: no merge unless all required checks and agent statuses succeed on the current head SHA.
- Do not put secrets in a skill.

## Available skills

### `create-issue`

File: `.github/skills/create-issue/SKILL.md`. Invoke with `/create-issue` when you want the Product Owner to create a TODO
issue, then plan to implement it yourself. It stops after issue creation and does not start Architect, Engineer, branch, or PR work.

### `create-pr-cloud`

File: `.github/skills/create-pr-cloud/SKILL.md`. Invoke with `/create-pr-cloud`, or ask to ship, finish or merge the current change.

Pipeline: task issue (create if missing) → commit → push → pull request → `pr-review-agent` → `senior-qa-engineer` → merge. `dod-validator-agent` is manual only and is never run by this skill.

| Rule | Behaviour |
|------|-----------|
| Branch | If already on a `feature/*` or `hotfix/*` branch, it is reused and no branch is created; a new `feature/<slug>` is created only from `main`. Never pushes to `main` |
| Issue | Reuses the task issue explicitly identified for the change; otherwise creates a Product Owner-style task issue before the PR, without `cloud-agent` or `backlog` |
| PR creation | A marked task PR may be reused, but an unmarked existing PR is not adopted |
| PR handoff | Adds `<!-- ship-pr -->`, `Closes #<issue>`, and records the head SHA/start marker via the guarded orchestrator intake |
| PR number | Captured once as `<number>` and substituted in all later steps (`Review PR #<number> in martinslavov/rcas.`, `Run QA for PR #<number> in martinslavov/rcas.`) |
| PR body | Built from `.github/PULL_REQUEST_TEMPLATE/pull_request_template.md`; assigned to the current user; no review/QA/check claims |
| Gates | Cloud dispatch starts PR Review and then QA; after a fix push the engineer resets both to `pending`. Each must be `success` on the current head SHA |
| Failures | Blocker/major findings are fixed, pushed and the gates restart; loops are bounded to 5 rounds per gate |
| Stop | `needs-human-review` label, exhausted rounds, or an empty change: stops and reports, no merge |
| Merge | Only when all required checks and the `PR Review` and `QA Agent` statuses succeed on the current head SHA (`Definition of Done` is excluded: manual only, not a gate), using `gh pr merge --merge --delete-branch` |
| Report | Issue and PR links and cloud handoff status; automation records elapsed time after merge |

Arguments: `/create-pr-cloud [label[,label...]]`.

| Invocation | Behaviour |
|------------|-----------|
| `/create-pr-cloud` | Creates/reuses a task issue and PR, then hands review, QA, bounded fixes and gated merge to cloud automation |
| `/create-pr-cloud <label>` | Default labels plus the given ones; unknown labels are reported, not created; `needs-human-review` is refused |
| `/create-pr-local` | Creates a PR without a task or tracking issue; the current local session runs PR Review and QA and merges after all gates pass. Failures stop for human action. |
