# Shared Copilot integration

This guide is self-contained and can also be added to `shared-copilot` for use by other repositories.

## How it works

`vendor/shared-copilot` is a Git submodule pinned to a specific commit. The following files are copies of that commit,
committed in the consuming repository at Copilot's project discovery locations:

- `.github/agents/senior-java-developer.agent.md`
- `.github/skills/software-engineering-principles/` (the complete skill directory)

The copies, not the submodule directory, are what Copilot discovers. They are regular repository files, so they are
available in clean checkouts, linked worktrees and cloud checkouts even when the submodule is not initialized. A submodule
update does not update the copies automatically: review and synchronize both together.

The shared repository's `.github/copilot-instructions.md` is **not** installed or loaded by this integration. Existing
repository-wide instructions and existing agents and skills remain in place. In RCAS, these include the PR Review, QA,
CI and approval gates; the shared Java agent does not replace the RCAS engineer or review agents.

## Initial installation in another repository

From the root of the consuming Git repository, first review the shared agent and skill and check that they are compatible
with the repository's existing policies. The command below requires Git, network access and working GitHub SSH
authentication. It installs the two components listed above, preserves existing agents and skills with different names,
and stops before changing anything if either destination or the submodule path already exists:

```bash
test ! -e vendor/shared-copilot && test ! -L vendor/shared-copilot && test ! -e .github/agents/senior-java-developer.agent.md && test ! -L .github/agents/senior-java-developer.agent.md && test ! -e .github/skills/software-engineering-principles && test ! -L .github/skills/software-engineering-principles && git submodule add git@github.com:martinslavov/shared-copilot.git vendor/shared-copilot && git submodule update --init --recursive && mkdir -p .github/agents .github/skills && cp vendor/shared-copilot/.github/agents/senior-java-developer.agent.md .github/agents/senior-java-developer.agent.md && cp -R vendor/shared-copilot/.github/skills/software-engineering-principles .github/skills/
```

For environments without GitHub SSH access, substitute `https://github.com/martinslavov/shared-copilot.git` for the
SSH URL. If any step fails after the submodule is added, inspect the Git status and finish or undo the partial installation
manually; do not blindly rerun the command. Review the new `.gitmodules`, submodule pointer and copied files, then commit
them together according to the consuming repository's contribution process. The command does not commit or push.

This command installs the components listed above, not future components automatically. Add further agents and entire
skill directories explicitly after checking their names, dependencies and compatibility.

## Using the components

- Select `Senior Java Developer` in the Copilot custom-agent selector, or use the Copilot CLI agent selector (`/agent`).
- Copilot can discover `software-engineering-principles` based on task relevance. The shared agent also directs Copilot
  to consult that skill for applicable work.
- Restart or reload the Copilot session if newly added project configuration is not visible. For cloud-agent selection,
  commit and merge the agent profile into the repository's default branch, then refresh the selector. Availability also
  depends on the Copilot product and its configuration.

The integration makes these components project-specific; it does not install personal agents or skills globally.

## Clone and update

The committed copies work without a submodule checkout. To inspect the pinned source after cloning, run:

```bash
git submodule update --init --recursive
```

To update, first ensure the working tree is clean, fetch the desired shared revision, and review it before changing the
pin. For example, from the consuming repository's root:

```bash
git submodule update --init --recursive
git -C vendor/shared-copilot fetch origin main
git -C vendor/shared-copilot log --oneline HEAD..origin/main
git -C vendor/shared-copilot diff HEAD origin/main -- .github/agents/senior-java-developer.agent.md .github/skills/software-engineering-principles
git -C vendor/shared-copilot checkout --detach origin/main
cp vendor/shared-copilot/.github/agents/senior-java-developer.agent.md .github/agents/senior-java-developer.agent.md
cp -R vendor/shared-copilot/.github/skills/software-engineering-principles/. .github/skills/software-engineering-principles/
git diff --submodule=log
git status --short
```

The copy commands overwrite files at these destinations. Review any local changes before running them. If a newer skill
revision removes or renames resources, manually remove the obsolete copied files after review; `cp -R` does not delete
them. Review and test the resulting agent and skill together with the submodule pointer, then commit them together.
To update to a reviewed tag or commit instead of `origin/main`, substitute it in the diff and checkout commands.

## Verification

With the submodule initialized, compare the pinned files to the installed copies:

```bash
cmp vendor/shared-copilot/.github/agents/senior-java-developer.agent.md .github/agents/senior-java-developer.agent.md
diff -r vendor/shared-copilot/.github/skills/software-engineering-principles .github/skills/software-engineering-principles
copilot skill list
```

Confirm that the skill appears under project skills and that the agent appears in the relevant Copilot selector. Verify
the consuming repository's existing review, QA and CI flows separately; merely listing a component does not prove that a
cloud session will select or execute it.
