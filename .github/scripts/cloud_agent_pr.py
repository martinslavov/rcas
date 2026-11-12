#!/usr/bin/env python3
"""Create and intake PRs for verified, approved Copilot Engineer pushes."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable


API_ROOT = "https://api.github.com"
API_VERSION = "2022-11-28"
REPOSITORY = "martinslavov/rcas"
ENTRY_LABEL = "agent-read"
BACKLOG_LABEL = "backlog"
APPROVAL_LABEL = "architecture-approval-required"
SKIP_ARCHITECT_LABEL = "skip-architect"
HUMAN_REVIEW_LABEL = "needs-human-review"
SHIP_PR_MARKER = "<!-- ship-pr -->"
AUTHORIZATION_MARKER = re.compile(r"<!-- cloud-agent-pr-authorized:(\{.*?\}) -->")
TASK_STATE_MARKER = re.compile(r"<!-- task-state: (\{.*?\}) -->")
BRANCH_PATTERN = re.compile(r"^feature/(?P<issue>[1-9][0-9]*)-[a-z0-9]+(?:-[a-z0-9]+)*$")
TRUSTED_ACTORS = frozenset({"copilot-swe-agent", "copilot-swe-agent[bot]"})


class CloudPrError(RuntimeError):
    """The cloud PR flow could not safely complete."""


class GitHubApi:
    def __init__(self, token: str, repository: str = REPOSITORY):
        if repository != REPOSITORY:
            raise CloudPrError("unexpected repository")
        if not token:
            raise CloudPrError("GitHub token is required")
        self.token = token
        self.repository = repository

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            API_ROOT + path,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": "Bearer " + self.token,
                "X-GitHub-Api-Version": API_VERSION,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read()
        except urllib.error.HTTPError as error:
            raise CloudPrError(f"GitHub API {method} {path} failed with HTTP {error.code}") from error
        return json.loads(payload) if payload else None

    def pages(self, path: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        page = 1
        while True:
            separator = "&" if "?" in path else "?"
            batch = self.request("GET", f"{path}{separator}per_page=100&page={page}")
            if not isinstance(batch, list):
                raise CloudPrError(f"Expected a list from GitHub API: {path}")
            result.extend(batch)
            if len(batch) < 100:
                return result
            page += 1


def _labels(issue: dict[str, Any]) -> set[str]:
    return {item.get("name", "") for item in issue.get("labels", [])}


def _issue_state(comments: list[dict[str, Any]], issue_number: int) -> dict[str, Any] | None:
    matches = []
    for comment in comments:
        match = TASK_STATE_MARKER.search(comment.get("body") or "")
        if match:
            try:
                record = json.loads(match.group(1))
            except json.JSONDecodeError:
                return None
            if isinstance(record, dict) and record.get("issue") == issue_number:
                matches.append(record)
    return matches[0] if len(matches) == 1 else None


def _issue_is_ready(api: GitHubApi, issue: dict[str, Any], comments: list[dict[str, Any]]) -> bool:
    issue_number = issue.get("number")
    issue_labels = _labels(issue)
    if (
        not isinstance(issue_number, int)
        or "pull_request" in issue
        or issue.get("state") != "open"
        or HUMAN_REVIEW_LABEL in issue_labels
        or BACKLOG_LABEL in issue_labels
    ):
        return False
    state = _issue_state(comments, issue_number)
    if not state or state.get("owner_agent") not in {
        "senior-java-software-engineer", "pr-review-agent"
    }:
        return False
    initial_intake = state.get("state") == "implementation" and ENTRY_LABEL in issue_labels
    actions = state.get("actions")
    if not isinstance(actions, dict):
        return False
    prior_intake = actions.get("ship_pr_intake")
    recovering_intake = (
        state.get("state") == "pr-review"
        and isinstance(prior_intake, dict)
        and isinstance(prior_intake.get("pr"), int)
        and isinstance(prior_intake.get("head_sha"), str)
        and re.fullmatch(r"[0-9a-fA-F]{7,64}", prior_intake["head_sha"]) is not None
    )
    if not initial_intake and not recovering_intake:
        return False

    trusted_authors = {api_owner(api), *TRUSTED_ACTORS}
    engineer_dispatch = any(
        (comment.get("user") or {}).get("login") == "github-actions[bot]"
        and "<!-- copilot-agent-dispatch:senior-java-software-engineer:" in (comment.get("body") or "")
        for comment in comments
    )
    if not engineer_dispatch:
        return False
    if SKIP_ARCHITECT_LABEL in issue_labels:
        return True
    design_notes = [
        comment
        for comment in comments
        if (comment.get("user") or {}).get("login") in trusted_authors
        and ("<!-- architect-design-note -->" in (comment.get("body") or "")
             or "<!-- architect-skipped -->" in (comment.get("body") or ""))
    ]
    if not design_notes:
        return False
    requested = any(
        re.search(r"Approval required:\s*yes", comment.get("body") or "", re.IGNORECASE)
        for comment in design_notes
    )
    approval_required = APPROVAL_LABEL in issue_labels or requested
    if approval_required:
        approved = any(
            (comment.get("user") or {}).get("login") == api_owner(api)
            and "<!-- architecture-approved -->" in (comment.get("body") or "")
            and re.search(
                rf"Approved by @{re.escape(api_owner(api))} at \d{{4}}-\d{{2}}-\d{{2}}T\d{{2}}:\d{{2}}:\d{{2}}Z",
                comment.get("body") or "",
            )
            for comment in comments
        )
        if (APPROVAL_LABEL in issue_labels and not requested) or not approved:
            return False
    return True


def api_owner(api: GitHubApi) -> str:
    return api.repository.split("/", 1)[0]


def _verified_actor(api: GitHubApi, login: str, actor_id: Any) -> dict[str, Any] | None:
    if login not in TRUSTED_ACTORS or not isinstance(actor_id, int):
        return None
    encoded_login = urllib.parse.quote(login, safe="")
    actor = api.request("GET", f"/users/{encoded_login}")
    if not isinstance(actor, dict):
        return None
    if actor.get("login") != login or actor.get("id") != actor_id or actor.get("type") != "Bot":
        return None
    return actor


def _branch_details(branch: str) -> tuple[int, str] | None:
    match = BRANCH_PATTERN.fullmatch(branch)
    if match is None:
        return None
    return int(match.group("issue")), branch


def _branch_head(api: GitHubApi, branch: str) -> str | None:
    encoded_branch = urllib.parse.quote(branch, safe="")
    try:
        result = api.request("GET", f"/repos/{api.repository}/branches/{encoded_branch}")
    except CloudPrError as error:
        if "HTTP 404" in str(error):
            return None
        raise
    if not isinstance(result, dict):
        return None
    sha = (result.get("commit") or {}).get("sha")
    return sha if isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha) else None


def _authorization_body(issue_number: int, branch: str, sha: str, actor: dict[str, Any]) -> str:
    data = {
        "issue": issue_number,
        "branch": branch,
        "sha": sha,
        "actor": actor["login"],
        "actor_id": actor["id"],
    }
    return "<!-- cloud-agent-pr-authorized:" + json.dumps(data, separators=(",", ":"), sort_keys=True) + " -->"


def _authorized_push_records(comments: list[dict[str, Any]], issue_number: int) -> list[dict[str, Any]]:
    records = []
    for comment in comments:
        if (comment.get("user") or {}).get("login") != "github-actions[bot]":
            continue
        if comment.get("created_at") != comment.get("updated_at"):
            continue
        for match in AUTHORIZATION_MARKER.finditer(comment.get("body") or ""):
            try:
                record = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get("issue") == issue_number:
                record["created_at"] = comment.get("created_at") or ""
                records.append(record)
    return records


def _authorize_push(api: GitHubApi, issue: dict[str, Any], branch: str, sha: str,
                    actor: dict[str, Any], comments: list[dict[str, Any]]) -> None:
    issue_number = issue["number"]
    body = _authorization_body(issue_number, branch, sha, actor)
    if any(
        record.get("branch") == branch and record.get("sha") == sha
        for record in _authorized_push_records(comments, issue_number)
    ):
        return
    api.request(
        "POST",
        f"/repos/{api.repository}/issues/{issue_number}/comments",
        {"body": body},
    )


def _validate_authorized_record(api: GitHubApi, issue: dict[str, Any], comments: list[dict[str, Any]],
                                record: dict[str, Any]) -> bool:
    branch = record.get("branch")
    sha = record.get("sha")
    details = _branch_details(branch) if isinstance(branch, str) else None
    if (
        details is None
        or details[0] != issue.get("number")
        or record.get("actor") not in TRUSTED_ACTORS
        or not isinstance(record.get("actor_id"), int)
        or not isinstance(sha, str)
        or not re.fullmatch(r"[0-9a-f]{40}", sha)
        or not _issue_is_ready(api, issue, comments)
    ):
        return False
    actor = _verified_actor(api, record["actor"], record["actor_id"])
    if actor is None:
        return False
    return _branch_head(api, branch) == sha


def _pr_body(issue_number: int, template: str) -> str:
    relation = "- Closes #<issue> (the issue created for the task; closed and moved to Done on merge)"
    replacement = f"- Closes #{issue_number} (the issue created for the task; closed and moved to Done on merge)"
    body = template.replace(relation, replacement)
    return body.rstrip() + f"\n\n{SHIP_PR_MARKER}\n"


def _matching_prs(api: GitHubApi, branch: str) -> list[dict[str, Any]]:
    head = urllib.parse.quote(f"{api_owner(api)}:{branch}", safe="")
    return api.pages(f"/repos/{api.repository}/pulls?state=open&head={head}")


def _create_or_reuse_pr(api: GitHubApi, issue: dict[str, Any], branch: str,
                        expected_sha: str, root: Path,
                        pr_creation_api: GitHubApi | None) -> dict[str, Any]:
    issue_number = issue["number"]
    prs = [
        pr for pr in _matching_prs(api, branch)
        if (pr.get("head") or {}).get("ref") == branch
        and ((pr.get("head") or {}).get("repo") or {}).get("full_name") == api.repository
    ]
    if len(prs) > 1:
        raise CloudPrError(f"Multiple open PRs already exist for {branch}")
    if prs:
        pr = prs[0]
        linked = re.search(rf"(?im)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#{issue_number}\b",
                           pr.get("body") or "")
        if (
            pr.get("state") != "open"
            or (pr.get("base") or {}).get("ref") != "main"
            or SHIP_PR_MARKER not in (pr.get("body") or "")
            or linked is None
            or (pr.get("head") or {}).get("sha") != expected_sha
        ):
            raise CloudPrError(f"Existing PR for {branch} does not match the guarded task PR contract")
        return pr

    template_path = root / ".github" / "PULL_REQUEST_TEMPLATE" / "pull_request_template.md"
    template = template_path.read_text(encoding="utf-8")
    creation_api = pr_creation_api or _pr_creation_api(api)
    pr = creation_api.request(
        "POST",
        f"/repos/{api.repository}/pulls",
        {
            "title": issue.get("title") or f"Implement task #{issue_number}",
            "head": branch,
            "base": "main",
            "body": _pr_body(issue_number, template),
        },
    )
    if not isinstance(pr, dict):
        raise CloudPrError("GitHub did not return the created PR")
    if (pr.get("head") or {}).get("sha") != expected_sha:
        pr_number = pr.get("number") if isinstance(pr, dict) else None
        if isinstance(pr_number, int):
            api.request("PATCH", f"/repos/{api.repository}/pulls/{pr_number}", {"state": "closed"})
        raise CloudPrError("The PR head changed during creation; closed the unverified PR")
    return pr


def _pr_creation_api(api: GitHubApi) -> GitHubApi:
    token = os.environ.get("COPILOT_AGENT_TOKEN", "")
    if not token:
        raise CloudPrError("COPILOT_AGENT_TOKEN is required to create a task PR")
    return GitHubApi(token, api.repository)


def _run_intake(issue_number: int, pr_number: int, root: Path,
                runner: Callable[..., subprocess.CompletedProcess[str]]) -> None:
    command = [
        sys.executable,
        str(root / ".github" / "scripts" / "orchestrator.py"),
        "intake-pr-review",
        str(issue_number),
        "--pr",
        str(pr_number),
        "--agent-read",
    ]
    environment = os.environ.copy()
    environment.pop("COPILOT_AGENT_TOKEN", None)
    environment["GH_TOKEN"] = os.environ.get("GITHUB_TOKEN", "")
    result = runner(command, check=False, capture_output=True, text=True, env=environment)
    if result.returncode != 0:
        raise CloudPrError("Guarded PR Review intake failed; scheduled recovery will retry")


def _process_authorized(api: GitHubApi, issue: dict[str, Any], comments: list[dict[str, Any]],
                        record: dict[str, Any], root: Path,
                        runner: Callable[..., subprocess.CompletedProcess[str]],
                        pr_creation_api: GitHubApi | None) -> bool:
    if not _validate_authorized_record(api, issue, comments, record):
        return False
    pr = _create_or_reuse_pr(
        api, issue, record["branch"], record["sha"], root, pr_creation_api
    )
    pr_number = pr["number"]
    current_pr = api.request("GET", f"/repos/{api.repository}/pulls/{pr_number}")
    if (
        not isinstance(current_pr, dict)
        or _branch_head(api, record["branch"]) != record["sha"]
        or current_pr.get("state") != "open"
        or (current_pr.get("head") or {}).get("sha") != record["sha"]
    ):
        return False
    pr = current_pr
    state = _issue_state(comments, issue["number"])
    if state and state.get("state") == "pr-review":
        intake = state.get("actions", {}).get("ship_pr_intake", {})
        if intake.get("pr") != pr.get("number") or intake.get("head_sha") != (pr.get("head") or {}).get("sha"):
            return False
        if ENTRY_LABEL in _labels(pr):
            return True
    _run_intake(issue["number"], pr["number"], root, runner)
    print("Completed PR intake for issue #{} and PR #{}".format(issue["number"], pr["number"]))
    return True


def _handle_push(api: GitHubApi, event: dict[str, Any], root: Path,
                 runner: Callable[..., subprocess.CompletedProcess[str]],
                 pr_creation_api: GitHubApi | None) -> bool:
    ref = event.get("ref")
    branch = ref.removeprefix("refs/heads/") if isinstance(ref, str) else ""
    details = _branch_details(branch)
    sender = event.get("sender") or {}
    if details is None or not isinstance(event.get("after"), str):
        return False
    issue_number, _ = details
    actor = _verified_actor(api, sender.get("login"), sender.get("id"))
    if actor is None or _branch_head(api, branch) != event["after"]:
        return False
    issue = api.request("GET", f"/repos/{api.repository}/issues/{issue_number}")
    if issue.get("number") != issue_number:
        return False
    comments = api.pages(f"/repos/{api.repository}/issues/{issue_number}/comments")
    if not _issue_is_ready(api, issue, comments):
        return False
    _authorize_push(api, issue, branch, event["after"], actor, comments)
    comments = api.pages(f"/repos/{api.repository}/issues/{issue_number}/comments")
    records = [
        record for record in _authorized_push_records(comments, issue_number)
        if record.get("branch") == branch and record.get("sha") == event["after"]
    ]
    return bool(records) and _process_authorized(
        api, issue, comments, records[-1], root, runner, pr_creation_api
    )


EVENTS_MAX_PAGES = 10  # GitHub exposes at most 300 repository events (10 pages of 30-100)


def _push_candidate(ref: Any, head: Any, actor: Any) -> dict[str, Any] | None:
    if not isinstance(ref, str) or not isinstance(head, str) or not ref.startswith("refs/heads/"):
        return None
    if _branch_details(ref.removeprefix("refs/heads/")) is None:
        return None
    actor = actor if isinstance(actor, dict) else {}
    return {"ref": ref, "after": head,
            "sender": {"login": actor.get("login"), "id": actor.get("id")}}


def _scan_events(api: GitHubApi, newest: dict[str, dict[str, Any]]) -> None:
    """Add the newest push per feature branch from every page the events feed offers."""
    for page in range(1, EVENTS_MAX_PAGES + 1):
        try:
            events = api.request("GET", f"/repos/{api.repository}/events?per_page=100&page={page}")
        except CloudPrError:
            if page == 1:
                raise
            return  # beyond the feed limit; the durable fallback covers older pushes
        if not isinstance(events, list):
            return
        for item in events:
            payload = item.get("payload") if isinstance(item, dict) else None
            if not isinstance(payload, dict) or item.get("type") != "PushEvent":
                continue
            candidate = _push_candidate(payload.get("ref"), payload.get("head"), item.get("actor"))
            if candidate is not None:
                newest.setdefault(candidate["ref"].removeprefix("refs/heads/"), candidate)
        if len(events) < 100:
            return


def _open_task_issues(api: GitHubApi) -> dict[int, dict[str, Any]]:
    issues: dict[int, dict[str, Any]] = {}
    for label in (ENTRY_LABEL, "state:pr-review"):
        query = urllib.parse.urlencode({"state": "open", "labels": label})
        for issue in api.pages(f"/repos/{api.repository}/issues?{query}"):
            if "pull_request" not in issue and isinstance(issue.get("number"), int):
                issues[issue["number"]] = issue
    return issues


def _scan_branch_activity(api: GitHubApi, issues: dict[int, dict[str, Any]],
                          newest: dict[str, dict[str, Any]]) -> None:
    """Durable fallback: ask GitHub's per-branch push activity for open task issues.

    The activity feed is written by GitHub (actor is not commit text) and is not limited
    to the newest events, so an old push is still found. Failures for one branch (deleted
    branch, no activity, rate limit) only skip that branch; the next poll retries it.
    """
    for issue_number in sorted(issues):
        try:
            refs = api.pages(f"/repos/{api.repository}/git/matching-refs/heads/feature/{issue_number}-")
        except CloudPrError as error:
            print(f"branch discovery skipped for issue #{issue_number}: {error}", file=sys.stderr)
            continue
        for item in refs:
            ref = item.get("ref") if isinstance(item, dict) else None
            if not isinstance(ref, str) or ref.removeprefix("refs/heads/") in newest:
                continue
            details = _branch_details(ref.removeprefix("refs/heads/"))
            if details is None or details[0] != issue_number:
                continue
            query = urllib.parse.urlencode(
                {"ref": ref, "activity_type": "push", "per_page": 1})
            try:
                activity = api.request("GET", f"/repos/{api.repository}/activity?{query}")
            except CloudPrError as error:
                print(f"push activity skipped for {ref}: {error}", file=sys.stderr)
                continue
            if not isinstance(activity, list) or not activity or not isinstance(activity[0], dict):
                continue
            latest = activity[0]
            if latest.get("ref") != ref:
                continue
            candidate = _push_candidate(ref, latest.get("after"), latest.get("actor"))
            if candidate is not None:
                newest[ref.removeprefix("refs/heads/")] = candidate


def _discover_pushes(api: GitHubApi, issues: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the newest GitHub-recorded push per feature branch, as push-like events.

    Actor identity comes from GitHub's events/activity feeds, never from forgeable commit
    text. Each result is re-verified (actor via the Users API, branch, issue, current SHA,
    approvals) by ``_handle_push`` before anything is authorized.
    """
    newest: dict[str, dict[str, Any]] = {}
    _scan_events(api, newest)
    _scan_branch_activity(api, issues, newest)
    return list(newest.values())


def _handle_schedule(api: GitHubApi, root: Path,
                     runner: Callable[..., subprocess.CompletedProcess[str]],
                     pr_creation_api: GitHubApi | None) -> bool:
    completed = False
    handled: set[tuple[str, str]] = set()
    first_error: CloudPrError | None = None
    issues = _open_task_issues(api)
    for push in _discover_pushes(api, issues):
        handled.add((push["ref"].removeprefix("refs/heads/"), push["after"]))
        try:
            completed = _handle_push(api, push, root, runner, pr_creation_api) or completed
        except CloudPrError as error:
            first_error = first_error or error
    for issue in issues.values():
        if "pull_request" in issue or not isinstance(issue.get("number"), int):
            continue
        issue_number = issue["number"]
        comments = api.pages(f"/repos/{api.repository}/issues/{issue_number}/comments")
        records = _authorized_push_records(comments, issue_number)
        latest_by_branch: dict[str, dict[str, Any]] = {}
        for record in records:
            branch = record.get("branch")
            if isinstance(branch, str) and (
                branch not in latest_by_branch
                or record.get("created_at", "") > latest_by_branch[branch].get("created_at", "")
            ):
                latest_by_branch[branch] = record
        for record in latest_by_branch.values():
            if (record.get("branch"), record.get("sha")) in handled:
                continue
            try:
                completed = _process_authorized(
                    api, issue, comments, record, root, runner, pr_creation_api
                ) or completed
            except CloudPrError as error:
                first_error = first_error or error
    if first_error is not None:
        raise first_error
    return completed


def run(event_name: str, event: dict[str, Any], api: GitHubApi | None = None,
        root: Path | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        pr_creation_api: GitHubApi | None = None) -> bool:
    root = root or Path(__file__).resolve().parents[2]
    api = api or GitHubApi(os.environ.get("GITHUB_TOKEN", ""), os.environ.get("GITHUB_REPOSITORY", REPOSITORY))
    if event_name == "push":
        return _handle_push(api, event, root, runner, pr_creation_api)
    if event_name == "schedule":
        return _handle_schedule(api, root, runner, pr_creation_api)
    return False


def main() -> int:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        print("GITHUB_EVENT_PATH is required", file=sys.stderr)
        return 2
    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
        run(os.environ.get("GITHUB_EVENT_NAME", ""), event)
        return 0
    except (CloudPrError, OSError, json.JSONDecodeError) as error:
        print(f"cloud PR automation stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
