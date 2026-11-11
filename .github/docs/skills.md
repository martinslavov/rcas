# Skills

Skills are reusable, repeatable procedures for Copilot. They live in `.github/skills/<name>/SKILL.md` and are invoked with a
single command (for example `/ship-pr`) or picked automatically when the description matches the request.

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

### `ship-pr`

File: `.github/skills/ship-pr/SKILL.md`. Invoke with `/ship-pr`, or ask to ship, finish or merge the current change.

Pipeline: commit → push → pull request → `pr-review-agent` → `senior-qa-engineer` → merge. `dod-validator-agent` is manual only and is never run by this skill.

| Rule | Behaviour |
|------|-----------|
| Branch | If already on a `feature/*` or `hotfix/*` branch, it is reused and no branch is created; a new `feature/<slug>` is created only from `main`. Never pushes to `main` |
| Existing PR | If the branch already has an open PR, its number is reused and creation is skipped |
| PR number | Captured once as `<number>` and substituted in all later steps (`Review PR #<number> in martinslavov/rcas.`, `Run QA for PR #<number> in martinslavov/rcas.`) |
| PR body | Built from `.github/PULL_REQUEST_TEMPLATE/pull_request_template.md`; assigned to the current user; no review/QA/check claims |
| Gates | `PR Review` and `QA Agent` are reset to `pending` after every push and each must be `success` on the current head SHA, in that order |
| Failures | Blocker/major findings are fixed, pushed and the gates restart; loops are bounded to 5 rounds per gate |
| Stop | `needs-human-review` label, exhausted rounds, or an empty change: stops and reports, no merge |
| Merge | Only when all required checks and the `PR Review` and `QA Agent` statuses succeed on the current head SHA (`Definition of Done` is excluded: manual only, not a gate), using `gh pr merge --merge --delete-branch` |
| Report | PR link, merge status and total elapsed time |

Arguments: `/ship-pr [label[,label...]]`.

| Invocation | Behaviour |
|------------|-----------|
| `/ship-pr` | Default labels only (type and impact); full pipeline through merge |
| `/ship-pr <label>` | Default labels plus the given ones; unknown labels are reported, not created; `needs-human-review` is refused |
| `/ship-pr agent-read` | Commit, push and PR with the `agent-read` label, then stop. The agent automation (dispatch, PR Review, QA, auto-merge) owns the rest, so the skill does not set gates, call `pr-review-agent` or `senior-qa-engineer`, and does not merge, to avoid duplicates. See [Agent automation](agent-automation.md) |
