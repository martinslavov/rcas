<!-- The tracking issue link is added automatically at the top of this description when the PR is opened. -->

# Description

_Summarize the change with the relevant motivation and context. State any breaking changes clearly._

# Pull-request relations

_List the links to issues, pull requests or dependencies related to or required by this change._

- Tracking issue: added automatically (workflow `PR Issue Tracking`); it is closed when this PR is merged.
- Closes: #<issue> (the issue created for the task; closed and moved to Done on merge)
- Related to:
  - (# other issues, # other pull requests, dependencies)

# How has this been tested?

_Describe the tests you ran to verify the change and how to reproduce them._

- List only local commands actually run and their results, e.g. `./gradlew build` (passed). If no local commands were run, leave this section without test-result entries; do not add prose about unrun tests.

# Acceptance criteria → evidence

_One row per acceptance criterion of the linked issue. Evidence must verify the behaviour: a test (file + method + what it asserts), a CI check, or for docs/process criteria a `file:line` or verified command output._

| Criterion | Evidence (test / check / doc) |
|-----------|-------------------------------|
| <acceptance criterion> | <e.g. `FooTest#expiresAfterTtl` asserts the entry is gone after the TTL> |

# Checklist

_Place `NA` between brackets when an activity is not applicable._

- [ ] I have identified any breaking changes in the description above.
- [ ] I have performed a self-review of my own code.
- [ ] I have added tests that prove my fix is effective or that my feature works.
- [ ] New and existing tests pass locally (`./gradlew build`; component tests: `make build && make up && make component-tests && make down`).
- [ ] Before merging, check GitHub checks and commit statuses on the current head SHA; do not report their status in this PR description.
- [ ] Documentation is updated accordingly (_e.g._, README, API, configuration).
- [ ] Pull request is categorized with labels:
  - **type**: `bug`, `documentation` or `enhancement`.
  - **impact**: `minor` or `major` (`major` = breaking change in API, behavior, configuration, data format or dependencies).

# Additional context

_Add any other context or screenshots about the change, if applicable._
