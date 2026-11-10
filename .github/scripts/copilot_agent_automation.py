#!/usr/bin/env python3
"""Dispatch RCAS issue/PR stages to Copilot and merge only fully validated PRs."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


API_ROOT = "https://api.github.com"
API_VERSION = "2022-11-28"
ENTRY_LABEL = "agent-read"
HUMAN_REVIEW_LABEL = "needs-human-review"
ARCHITECTURE_APPROVAL_LABEL = "architecture-approval-required"
REQUIRED_CHECKS = (
    "unit-tests",
    "Component Tests (make up && make component-tests)",
    "Sanity Tests (make up && make sanity-tests)",
    "Static Review (checkstyle)",
    "analyze",
    "dependency-review",
    "secret-scan",
    "PR Review",
    "QA Agent",
)
AGENT_STATUSES = {
    ("PR Review", "pending"): "pr-review-agent",
    ("PR Review", "success"): "senior-qa-engineer",
    ("PR Review", "failure"): "senior-java-software-engineer",
    ("PR Review", "error"): "senior-java-software-engineer",
    ("QA Agent", "success"): "dod-validator-agent",
    ("QA Agent", "failure"): "senior-java-software-engineer",
    ("QA Agent", "error"): "senior-java-software-engineer",
    ("Definition of Done", "failure"): "senior-java-software-engineer",
    ("Definition of Done", "error"): "senior-java-software-engineer",
}
AGENT_FILES = {
    "architect-agent": "architect.agent.md",
    "senior-java-software-engineer": "engineer.agent.md",
    "pr-review-agent": "pr-review.agent.md",
    "senior-qa-engineer": "qa.agent.md",
    "dod-validator-agent": "dod-validator.agent.md",
}
APPROVAL_MARKER = "<!-- architecture-approved -->"
DESIGN_MARKER = "<!-- architect-design-note -->"
SKIP_MARKER = "<!-- architect-skipped -->"
AGENT_COMMENT_MARKERS = (
    "<!-- agent-run:",
    "<!-- pr-review-round:",
    "<!-- qa-round:",
    "<!-- dod-round:",
    "<!-- dod-validation sha:",
    "<!-- copilot-agent-dispatch:",
    "<!-- agent-automation-start:",
)
START_EPOCH_RE = re.compile(r"<!-- agent-automation-start:(\d+) -->")


class AutomationError(RuntimeError):
    """An API or workflow invariant failed."""


@dataclass(frozen=True)
class Dispatch:
    resource: str
    number: int
    stage: str
    sha: str | None = None
    resume: bool = False

    @property
    def marker(self) -> str:
        suffix = self.sha or "issue"
        if self.resume:
            suffix += ":human-resume"
        return f"<!-- copilot-agent-dispatch:{self.stage}:{suffix} -->"


class GitHub:
    def __init__(self, token: str, repository: str):
        if "/" not in repository:
            raise AutomationError("GITHUB_REPOSITORY must be owner/repository")
        self.owner, self.name = repository.split("/", 1)
        self.repository = repository
        self.token = token

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        payload = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            API_ROOT + path,
            data=payload,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": API_VERSION,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read()
        except urllib.error.HTTPError as error:
            raise AutomationError(
                f"GitHub API {method} {path} failed with HTTP {error.code}"
            ) from error
        if not data:
            return None
        return json.loads(data)

    def pages(self, path: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        page = 1
        while True:
            separator = "&" if "?" in path else "?"
            batch = self.request("GET", f"{path}{separator}per_page=100&page={page}")
            if not isinstance(batch, list):
                raise AutomationError(f"Expected a list from GitHub API: {path}")
            result.extend(batch)
            if len(batch) < 100:
                return result
            page += 1

    def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            API_ROOT + "/graphql",
            data=json.dumps({"query": query, "variables": variables}).encode(),
            method="POST",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "GraphQL-Features": "issues_copilot_assignment_api_support,coding_agent_model_selection",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as error:
            raise AutomationError(f"GitHub GraphQL request failed with HTTP {error.code}") from error
        if payload.get("errors"):
            messages = "; ".join(error.get("message", "unknown GraphQL error") for error in payload["errors"])
            raise AutomationError(f"GitHub GraphQL request failed: {messages}")
        return payload["data"]


def _labels(item: dict[str, Any]) -> set[str]:
    return {label["name"] for label in item.get("labels", [])}


def _is_pr(issue: dict[str, Any]) -> bool:
    return "pull_request" in issue


def _linked_issue_number(body: str) -> int | None:
    match = re.search(r"(?im)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#([1-9][0-9]*)", body)
    return int(match.group(1)) if match else None


def _comment_is_agent_generated(comment: dict[str, Any]) -> bool:
    user = comment.get("user") or {}
    login = user.get("login", "")
    body = comment.get("body") or ""
    return user.get("type") == "Bot" or login.endswith("[bot]") or any(
        marker in body for marker in AGENT_COMMENT_MARKERS
    )


def _status_state(status: dict[str, Any], context: str) -> str | None:
    matches = [item for item in status.get("statuses", []) if item.get("context") == context]
    if not matches:
        return None
    matches.sort(key=lambda item: item.get("updated_at") or item.get("created_at") or "")
    return matches[-1].get("state")


def _dispatch_for_issue_comment(
    event: dict[str, Any], api: GitHub
) -> Dispatch | None:
    issue = event.get("issue") or {}
    issue_labels = _labels(issue)
    if (
        _is_pr(issue)
        or issue.get("state") != "open"
        or ENTRY_LABEL not in issue_labels
        or HUMAN_REVIEW_LABEL in issue_labels
    ):
        return None
    comment = event.get("comment") or {}
    body = comment.get("body") or ""
    author = (comment.get("user") or {}).get("login")
    trusted_agent_authors = {api.owner, "copilot-swe-agent", "copilot-swe-agent[bot]"}
    if author not in trusted_agent_authors or not any(
        marker in body for marker in (DESIGN_MARKER, SKIP_MARKER, APPROVAL_MARKER)
    ):
        return None
    return _ready_issue_dispatch(api, issue)


def _ready_issue_dispatch(api: GitHub, issue: dict[str, Any]) -> Dispatch | None:
    issue_labels = _labels(issue)
    if (
        _is_pr(issue)
        or issue.get("state") != "open"
        or ENTRY_LABEL not in issue_labels
        or HUMAN_REVIEW_LABEL in issue_labels
    ):
        return None
    number = issue["number"]
    comments = api.pages(f"/repos/{api.repository}/issues/{number}/comments")
    architect_dispatch = Dispatch("issue", number, "architect-agent")
    if not any(architect_dispatch.marker in (comment.get("body") or "") for comment in comments):
        return architect_dispatch
    implementation_dispatch = Dispatch("issue", number, "senior-java-software-engineer")
    if any(implementation_dispatch.marker in (comment.get("body") or "") for comment in comments):
        return None

    trusted_agent_authors = {api.owner, "copilot-swe-agent", "copilot-swe-agent[bot]"}
    design_notes = [
        comment
        for comment in comments
        if (comment.get("user") or {}).get("login") in trusted_agent_authors
        and (DESIGN_MARKER in (comment.get("body") or "") or SKIP_MARKER in (comment.get("body") or ""))
    ]
    approval_required = ARCHITECTURE_APPROVAL_LABEL in issue_labels
    if approval_required:
        has_design_approval_request = any(
            re.search(r"Approval required:\s*yes", item.get("body") or "", re.IGNORECASE)
            for item in design_notes
        )
        has_owner_approval = any(
            (comment.get("user") or {}).get("login") == api.owner
            and APPROVAL_MARKER in (comment.get("body") or "")
            and re.search(
                rf"Approved by @{re.escape(api.owner)} at \d{{4}}-\d{{2}}-\d{{2}}T\d{{2}}:\d{{2}}:\d{{2}}Z",
                comment.get("body") or "",
            )
            for comment in comments
        )
        if has_design_approval_request and has_owner_approval:
            return implementation_dispatch
        return None
    if any(
        SKIP_MARKER in (item.get("body") or "")
        or re.search(r"Approval required:\s*no", item.get("body") or "", re.IGNORECASE)
        for item in design_notes
    ):
        return implementation_dispatch
    return None


def _candidate_prs(api: GitHub, sha: str) -> list[dict[str, Any]]:
    return api.pages(f"/repos/{api.repository}/commits/{urllib.parse.quote(sha, safe='')}/pulls")


def _task_issue_for_pr(api: GitHub, pr: dict[str, Any]) -> dict[str, Any] | None:
    if pr.get("state") != "open" or pr.get("base", {}).get("ref") != "main":
        return None
    number = _linked_issue_number(pr.get("body") or "")
    if number is None:
        return None
    issue = api.request("GET", f"/repos/{api.repository}/issues/{number}")
    if issue.get("state") != "open" or ENTRY_LABEL not in _labels(issue):
        return None
    if HUMAN_REVIEW_LABEL in _labels(issue) or HUMAN_REVIEW_LABEL in _labels(pr):
        return None
    return issue


def _dispatch_from_status(event: dict[str, Any], api: GitHub) -> list[Dispatch]:
    context = event.get("context")
    state = event.get("state")
    agent = AGENT_STATUSES.get((context, state))
    if agent is None:
        return []
    sha = event.get("sha")
    if not isinstance(sha, str):
        return []
    dispatches = []
    for pr in _candidate_prs(api, sha):
        if pr.get("head", {}).get("sha") != sha or _task_issue_for_pr(api, pr) is None:
            continue
        if state in {"failure", "error"} and _failure_round_limit_reached(api, pr["number"], context):
            continue
        dispatches.append(Dispatch("pull", pr["number"], agent, sha))
    return dispatches


def _dispatch_from_check_suite(event: dict[str, Any], api: GitHub) -> list[Dispatch]:
    suite = event.get("check_suite") or {}
    if event.get("action") != "completed" or suite.get("conclusion") not in {
        "failure", "timed_out", "cancelled",
    }:
        return []
    sha = suite.get("head_sha")
    if not isinstance(sha, str):
        return []
    ci_checks = tuple(name for name in REQUIRED_CHECKS if name not in {"PR Review", "QA Agent"})
    check_runs = _check_runs(api, sha)
    failures = {
        name
        for name in ci_checks
        if _latest_check_result(check_runs, [], name)[0] in {"failure", "timed_out", "cancelled"}
    }
    if not failures:
        return []
    return [
        Dispatch("pull", pr["number"], "senior-java-software-engineer", sha)
        for pr in _candidate_prs(api, sha)
        if pr.get("head", {}).get("sha") == sha and _task_issue_for_pr(api, pr) is not None
    ]


def _dispatch_from_schedule(api: GitHub) -> list[Dispatch]:
    result: list[Dispatch] = []
    for issue in api.pages(f"/repos/{api.repository}/issues?state=open&labels={ENTRY_LABEL}"):
        dispatch = _ready_issue_dispatch(api, issue)
        if dispatch is not None:
            result.append(dispatch)

    ci_checks = tuple(name for name in REQUIRED_CHECKS if name not in {"PR Review", "QA Agent"})
    for pr in api.pages(f"/repos/{api.repository}/pulls?state=open&base=main"):
        if _task_issue_for_pr(api, pr) is None:
            continue
        sha = pr["head"]["sha"]
        status = api.request("GET", f"/repos/{api.repository}/commits/{sha}/status")
        review_state = _status_state(status, "PR Review")
        qa_state = _status_state(status, "QA Agent")
        dod_state = _status_state(status, "Definition of Done")

        if review_state in {"failure", "error"}:
            if not _failure_round_limit_reached(api, pr["number"], "PR Review"):
                result.append(Dispatch("pull", pr["number"], "senior-java-software-engineer", sha))
            continue
        if review_state == "pending":
            result.append(Dispatch("pull", pr["number"], "pr-review-agent", sha))
            continue
        if review_state == "success":
            if qa_state in {"failure", "error"}:
                if not _failure_round_limit_reached(api, pr["number"], "QA Agent"):
                    result.append(Dispatch("pull", pr["number"], "senior-java-software-engineer", sha))
                continue
            if qa_state == "pending":
                result.append(Dispatch("pull", pr["number"], "senior-qa-engineer", sha))
                continue
            if qa_state == "success":
                if dod_state in {"failure", "error"}:
                    if not _failure_round_limit_reached(api, pr["number"], "Definition of Done"):
                        result.append(Dispatch("pull", pr["number"], "senior-java-software-engineer", sha))
                    continue
                if dod_state == "pending":
                    result.append(Dispatch("pull", pr["number"], "dod-validator-agent", sha))
                    continue

        check_runs = _check_runs(api, sha)
        if any(
            _latest_check_result(check_runs, [], name)[0] in {"failure", "timed_out", "cancelled"}
            for name in ci_checks
        ):
            result.append(Dispatch("pull", pr["number"], "senior-java-software-engineer", sha))
    return result


def _failure_round_limit_reached(api: GitHub, pr_number: int, context: str) -> bool:
    marker = {
        "PR Review": "pr-review-round",
        "QA Agent": "qa-round",
        "Definition of Done": "dod-round",
    }.get(context)
    if marker is None:
        return False
    comments = api.pages(f"/repos/{api.repository}/issues/{pr_number}/comments")
    rounds = {
        int(value)
        for comment in comments
        for value in re.findall(rf"<!-- {re.escape(marker)}:(\d+) -->", comment.get("body") or "")
    }
    if context == "PR Review":
        reviews = api.pages(f"/repos/{api.repository}/pulls/{pr_number}/reviews")
        rounds.update(
            int(value)
            for review in reviews
            for value in re.findall(rf"<!-- {re.escape(marker)}:(\d+) -->", review.get("body") or "")
        )
    return max(rounds, default=0) >= 5


def get_dispatches(event_name: str, event: dict[str, Any], api: GitHub) -> list[Dispatch]:
    if event_name == "issues":
        issue = event.get("issue") or {}
        label = (event.get("label") or {}).get("name")
        if event.get("action") == "labeled" and label == ENTRY_LABEL and issue.get("state") == "open":
            if not _is_pr(issue) and HUMAN_REVIEW_LABEL not in _labels(issue):
                return [Dispatch("issue", issue["number"], "architect-agent")]
        if event.get("action") == "unlabeled" and label == HUMAN_REVIEW_LABEL and _is_pr(issue):
            number = issue["number"]
            pr = api.request("GET", f"/repos/{api.repository}/pulls/{number}")
            if _task_issue_for_pr(api, pr) is not None:
                status = api.request(
                    "GET", f"/repos/{api.repository}/commits/{pr['head']['sha']}/status"
                )
                check_runs = _check_runs(api, pr["head"]["sha"])
                agent_failed = any(
                    _status_state(status, name) in {"failure", "error"}
                    for name in ("PR Review", "QA Agent", "Definition of Done")
                )
                ci_failed = any(
                    _latest_check_result(check_runs, [], name)[0]
                    in {"failure", "timed_out", "cancelled"}
                    for name in REQUIRED_CHECKS
                    if name not in {"PR Review", "QA Agent"}
                )
                if agent_failed or ci_failed:
                    return [
                        Dispatch(
                            "pull",
                            number,
                            "senior-java-software-engineer",
                            pr["head"]["sha"],
                            resume=True,
                        )
                    ]
    elif event_name == "issue_comment" and event.get("action") in {"created", "edited"}:
        dispatch = _dispatch_for_issue_comment(event, api)
        if dispatch:
            return [dispatch]
    elif event_name == "status":
        return _dispatch_from_status(event, api)
    elif event_name == "check_suite":
        return _dispatch_from_check_suite(event, api)
    elif event_name == "schedule":
        return _dispatch_from_schedule(api)
    return []


def _resource_path(api: GitHub, dispatch: Dispatch) -> str:
    resource = "issues" if dispatch.resource == "issue" else "issues"
    return f"/repos/{api.repository}/{resource}/{dispatch.number}"


def _already_dispatched(api: GitHub, dispatch: Dispatch) -> bool:
    comments = api.pages(f"{_resource_path(api, dispatch)}/comments")
    return any(dispatch.marker in (item.get("body") or "") for item in comments)


def _add_dispatch_marker(api: GitHub, dispatch: Dispatch) -> None:
    api.request(
        "POST",
        f"{_resource_path(api, dispatch)}/comments",
        {"body": dispatch.marker},
    )


def _record_start_time(api: GitHub, issue_number: int) -> None:
    comments = api.pages(f"/repos/{api.repository}/issues/{issue_number}/comments")
    if any(START_EPOCH_RE.search(comment.get("body") or "") for comment in comments):
        return
    api.request(
        "POST",
        f"/repos/{api.repository}/issues/{issue_number}/comments",
        {"body": f"<!-- agent-automation-start:{int(time.time())} -->"},
    )


def assign_to_copilot(api: GitHub, dispatch: Dispatch) -> None:
    if _already_dispatched(api, dispatch):
        print(f"Skipping duplicate {dispatch.stage} dispatch for #{dispatch.number}")
        return

    query = """
      query($owner: String!, $name: String!, $number: Int!) {
        repository(owner: $owner, name: $name) {
          id
          suggestedActors(capabilities: [CAN_BE_ASSIGNED], first: 100) {
            nodes { login ... on Bot { id } }
          }
          issue(number: $number) { id }
          pullRequest(number: $number) { id }
        }
      }
    """
    data = api.graphql(
        query,
        {"owner": api.owner, "name": api.name, "number": dispatch.number},
    )["repository"]
    repo_id = data["id"]
    bot = next(
        (
            actor for actor in data["suggestedActors"]["nodes"]
            if actor.get("login") == "copilot-swe-agent" and actor.get("id")
        ),
        None,
    )
    if bot is None:
        raise AutomationError(
            "Copilot cloud agent is not assignable in this repository; enable it in repository settings"
        )
    item = data["issue"] if dispatch.resource == "issue" else data["pullRequest"]
    if item is None:
        raise AutomationError(f"Could not find {dispatch.resource} #{dispatch.number}")
    profile = AGENT_FILES[dispatch.stage]
    custom_instructions = (
        f"Follow the custom agent profile `.github/agents/{profile}` and the task workflow in "
        "`.github/copilot-instructions.md`. This is a staged `agent-read` task. Preserve the "
        "architecture-approval, required-status, bounded-retry, and human-review gates."
    )
    mutation = """
      mutation($assignable: ID!, $actor: ID!, $repository: ID!, $baseRef: String!,
               $instructions: String!, $customAgent: String!) {
        addAssigneesToAssignable(input: {
          assignableId: $assignable
          actorIds: [$actor]
          agentAssignment: {
            targetRepositoryId: $repository
            baseRef: $baseRef
            customInstructions: $instructions
            customAgent: $customAgent
          }
        }) {
          assignable {
            ... on Issue { id }
            ... on PullRequest { id }
          }
        }
      }
    """
    result = api.graphql(
        mutation,
        {
            "assignable": item["id"],
            "actor": bot["id"],
            "repository": repo_id,
            "baseRef": "main",
            "instructions": custom_instructions,
            "customAgent": dispatch.stage,
        },
    )
    if not result.get("addAssigneesToAssignable", {}).get("assignable"):
        raise AutomationError(f"GitHub did not assign {dispatch.stage} to #{dispatch.number}")
    if dispatch.resource == "issue" and dispatch.stage == "architect-agent":
        _record_start_time(api, dispatch.number)
    _add_dispatch_marker(api, dispatch)
    print(f"Dispatched {dispatch.stage} to Copilot for #{dispatch.number}")


def _latest_check_result(
    check_runs: list[dict[str, Any]], statuses: list[dict[str, Any]], name: str
) -> tuple[str | None, str]:
    candidates: list[tuple[str, str, str]] = []
    for run in check_runs:
        if run.get("name") == name:
            candidates.append((
                run.get("completed_at") or run.get("started_at") or run.get("created_at") or "",
                (run.get("conclusion") or run.get("status") or "").lower(),
                "check",
            ))
    for status in statuses:
        if status.get("context") == name:
            candidates.append((
                status.get("updated_at") or status.get("created_at") or "",
                (status.get("state") or "").lower(),
                "status",
            ))
    if not candidates:
        return None, "missing"
    candidates.sort(key=lambda result: result[0])
    return candidates[-1][1], candidates[-1][2]


def _check_runs(api: GitHub, sha: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    page = 1
    while True:
        path = f"/repos/{api.repository}/commits/{urllib.parse.quote(sha, safe='')}/check-runs"
        response = api.request("GET", f"{path}?per_page=100&page={page}")
        batch = response.get("check_runs", [])
        result.extend(batch)
        if len(batch) < 100:
            return result
        page += 1


def _has_human_comments(api: GitHub, number: int) -> bool:
    paths = (
        f"/repos/{api.repository}/issues/{number}/comments",
        f"/repos/{api.repository}/pulls/{number}/reviews",
        f"/repos/{api.repository}/pulls/{number}/comments",
    )
    for path in paths:
        for comment in api.pages(path):
            if not _comment_is_agent_generated(comment):
                return True
    return False


def merge_if_ready(api: GitHub, number: int) -> bool:
    pr = api.request("GET", f"/repos/{api.repository}/pulls/{number}")
    issue = _task_issue_for_pr(api, pr)
    if issue is None or pr.get("draft"):
        print(f"PR #{number} is not an open agent-read PR; not merging")
        return False
    sha = pr["head"]["sha"]
    labels = api.request("GET", f"/repos/{api.repository}/issues/{number}/labels")
    if HUMAN_REVIEW_LABEL in {label["name"] for label in labels}:
        print(f"PR #{number} has {HUMAN_REVIEW_LABEL}; not merging")
        return False
    status = api.request("GET", f"/repos/{api.repository}/commits/{sha}/status")
    check_runs = _check_runs(api, sha)
    for name in REQUIRED_CHECKS + ("Definition of Done",):
        state, source = _latest_check_result(check_runs, status.get("statuses", []), name)
        if state != "success":
            print(f"PR #{number} is waiting for {name} ({state or 'missing'}, {source})")
            return False
    if _has_human_comments(api, number):
        print(f"PR #{number} has a human comment or review; not merging")
        return False

    issue_comments = api.pages(f"/repos/{api.repository}/issues/{issue['number']}/comments")
    start_epoch = next(
        (
            int(match.group(1))
            for comment in issue_comments
            if (match := START_EPOCH_RE.search(comment.get("body") or ""))
        ),
        None,
    )
    if start_epoch is None:
        raise AutomationError(f"Issue #{issue['number']} has no agent automation start marker")
    result = api.request(
        "PUT",
        f"/repos/{api.repository}/pulls/{number}/merge",
        {"sha": sha, "merge_method": "merge"},
    )
    if not result.get("merged"):
        raise AutomationError(f"GitHub did not merge PR #{number}")
    print(f"Merged PR #{number}: {result.get('message', 'success')}")
    subprocess.run(
        [
            "bash",
            ".github/scripts/post_task_elapsed.sh",
            str(issue["number"]),
            str(number),
            str(start_epoch),
        ],
        check=True,
    )
    head_repo = (pr.get("head", {}).get("repo") or {}).get("full_name")
    head_ref = pr.get("head", {}).get("ref", "")
    if head_repo == api.repository and re.fullmatch(r"(?:feature|hotfix)/[A-Za-z0-9._/-]+", head_ref):
        ref = urllib.parse.quote(head_ref, safe="/")
        api.request("DELETE", f"/repos/{api.repository}/git/refs/heads/{ref}")
    return True


def _event_pr_numbers(event_name: str, event: dict[str, Any], api: GitHub) -> list[int]:
    if event_name == "issue_comment" and _is_pr(event.get("issue") or {}):
        return [event["issue"]["number"]]
    if event_name == "pull_request_review":
        return [event["pull_request"]["number"]]
    if event_name == "schedule":
        return [
            pr["number"]
            for pr in api.pages(f"/repos/{api.repository}/pulls?state=open&base=main")
            if _task_issue_for_pr(api, pr) is not None
        ]
    if event_name == "status":
        sha = event.get("sha")
    elif event_name == "check_suite":
        sha = (event.get("check_suite") or {}).get("head_sha")
    else:
        sha = None
    if not sha:
        return []
    return [
        pr["number"]
        for pr in _candidate_prs(api, sha)
        if pr.get("head", {}).get("sha") == sha and _task_issue_for_pr(api, pr) is not None
    ]


def main() -> int:
    mode = os.environ.get("MODE", "dispatch")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not event_path:
        raise AutomationError("GITHUB_EVENT_PATH is not available")
    with open(event_path, encoding="utf-8") as event_file:
        event = json.load(event_file)

    if mode == "dispatch":
        read_token = os.environ.get("GITHUB_TOKEN")
        if not read_token:
            raise AutomationError("GITHUB_TOKEN is required to inspect the event")
        read_api = GitHub(read_token, repository)
        for dispatch in get_dispatches(event_name, event, read_api):
            agent_token = os.environ.get("COPILOT_AGENT_TOKEN")
            if not agent_token:
                raise AutomationError(
                    "Add the COPILOT_AGENT_TOKEN repository secret to dispatch Copilot tasks"
                )
            assign_to_copilot(GitHub(agent_token, repository), dispatch)
    elif mode == "merge":
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise AutomationError("GITHUB_TOKEN is required to evaluate and merge pull requests")
        api = GitHub(token, repository)
        for number in _event_pr_numbers(event_name, event, api):
            merge_if_ready(api, number)
    else:
        raise AutomationError(f"Unknown MODE: {mode}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AutomationError as error:
        print(f"agent automation: {error}", file=sys.stderr)
        sys.exit(1)
