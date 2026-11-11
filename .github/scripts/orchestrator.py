#!/usr/bin/env python3
"""Issue-backed task state machine for RCAS. Python standard library only."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

OWNER = "martinslavov"
REPO = "martinslavov/rcas"
ENTRY_LABEL = "agent-read"
HUMAN_REVIEW_LABEL = "needs-human-review"
SHIP_PR_MARKER = "<!-- ship-pr -->"
PR_REVIEW_INTAKE_ACTION = "ship_pr_intake"
STATE_MARKER = re.compile(r"<!-- task-state: (\{.*?\}) -->", re.DOTALL)
APPROVAL_DETAILS = re.compile(r"Approved by @[A-Za-z0-9-]+ at \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")

STATE_TABLE: dict[str, tuple[str | None, frozenset[str]]] = {
    "backlog": ("human", frozenset({"todo"})),
    "todo": ("architect-agent", frozenset({"architecture"})),
    "architecture": ("architect-agent", frozenset({"approval-pending", "implementation"})),
    "approval-pending": ("human", frozenset({"implementation", "blocked"})),
    "implementation": ("senior-java-software-engineer", frozenset({"pr-review"})),
    "pr-review": ("pr-review-agent", frozenset({"qa", "implementation"})),
    "qa": ("senior-qa-engineer", frozenset({"merge", "implementation"})),
    "dod": ("dod-validator-agent", frozenset({"merge", "implementation"})),
    "merge": ("senior-java-software-engineer", frozenset({"done"})),
    "done": (None, frozenset()),
    "blocked": (None, frozenset()),
    "human-review": ("human", frozenset()),
}
SEED_STATES = frozenset({"backlog", "todo"})
ACTIVE_STATES = frozenset(STATE_TABLE) - {"done", "blocked", "human-review"}
BOARD_STATUS = {
    "backlog": "Backlog",
    "todo": "TODO",
    "architecture": "Defining",
    "approval-pending": "Assessment",
    "blocked": "Assessment",
    "human-review": "Assessment",
    "implementation": "In Progress",
    "pr-review": "In Progress",
    "qa": "In Progress",
    "dod": "In Progress",
    "merge": "In Progress",
    "done": "Done",
}
REQUIRED_RECORD_FIELDS = {
    "v", "issue", "state", "owner_agent", "head_sha", "updated_at", "updated_by",
    "resume_state", "lock", "actions", "attempts",
}
ATTEMPT_LOOPS = ("pr_review", "qa", "dod", "ci_fix")


class OrchestratorError(Exception):
    """Expected operational or validation failure."""


class GhError(OrchestratorError):
    """A GitHub CLI command failed."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def default_record(issue: int, state: str, updated_by: str, now: str | None = None) -> dict:
    if issue < 1:
        raise OrchestratorError("issue must be a positive number")
    if state not in STATE_TABLE:
        raise OrchestratorError(f"unknown state: {state}")
    return {
        "v": 1,
        "issue": issue,
        "state": state,
        "owner_agent": STATE_TABLE[state][0],
        "head_sha": None,
        "updated_at": now or utc_now(),
        "updated_by": updated_by,
        "resume_state": None,
        "lock": {
            "agent": None,
            "session": None,
            "acquired_at": None,
            "ttl_s": 1800,
            "expires_at": None,
            "takeovers": [],
        },
        "actions": {},
        "attempts": {
            loop: {"count": 0, "last_reason": None, "last_signature": None}
            for loop in ATTEMPT_LOOPS
        },
    }


def serialize_record(record: Mapping) -> str:
    validate_record(record)
    return "<!-- task-state: " + json.dumps(record, separators=(",", ":"), sort_keys=True) + " -->"


def parse_record(comment_body: str) -> dict:
    matches = list(STATE_MARKER.finditer(comment_body))
    if len(matches) != 1:
        raise OrchestratorError(f"expected exactly one task-state record; found {len(matches)}")
    try:
        record = json.loads(matches[0].group(1))
    except json.JSONDecodeError as exc:
        raise OrchestratorError(f"invalid task-state JSON: {exc}") from exc
    validate_record(record)
    return record


def validate_record(record: Mapping) -> None:
    if not isinstance(record, Mapping) or REQUIRED_RECORD_FIELDS - record.keys():
        missing = sorted(REQUIRED_RECORD_FIELDS - record.keys()) if isinstance(record, Mapping) else sorted(REQUIRED_RECORD_FIELDS)
        raise OrchestratorError(f"task-state record is missing fields: {', '.join(missing)}")
    if type(record["v"]) is not int or record["v"] != 1 or type(record["issue"]) is not int or record["issue"] < 1:
        raise OrchestratorError("unsupported task-state schema or invalid issue number")
    state = record["state"]
    if not isinstance(state, str) or state not in STATE_TABLE:
        raise OrchestratorError(f"unknown state in record: {state}")
    if record["owner_agent"] != STATE_TABLE[state][0]:
        raise OrchestratorError(f"owner_agent does not match state {state}")
    if not isinstance(record["updated_at"], str) or not isinstance(record["updated_by"], str):
        raise OrchestratorError("updated_at and updated_by must be strings")
    if record["head_sha"] is not None and not isinstance(record["head_sha"], str):
        raise OrchestratorError("head_sha must be a string or null")
    resume_state = record["resume_state"]
    if resume_state is not None and (not isinstance(resume_state, str) or resume_state not in ACTIVE_STATES):
        raise OrchestratorError("resume_state must be an active state or null")
    lock_fields = {"agent", "session", "acquired_at", "ttl_s", "expires_at", "takeovers"}
    if not isinstance(record["lock"], Mapping) or lock_fields - record["lock"].keys():
        raise OrchestratorError("lock must contain all default lock fields")
    if type(record["lock"]["ttl_s"]) is not int or record["lock"]["ttl_s"] < 1:
        raise OrchestratorError("lock ttl_s must be a positive integer")
    if not isinstance(record["lock"]["takeovers"], list) or not isinstance(record["actions"], Mapping):
        raise OrchestratorError("lock takeovers must be a list and actions must be an object")
    if not isinstance(record["attempts"], Mapping):
        raise OrchestratorError("attempts must be an object")
    for loop in ATTEMPT_LOOPS:
        attempt = record["attempts"].get(loop)
        if not isinstance(attempt, Mapping) or {"count", "last_reason", "last_signature"} - attempt.keys():
            raise OrchestratorError("attempts must contain all retry loop defaults")
        if type(attempt["count"]) is not int or attempt["count"] < 0:
            raise OrchestratorError(f"attempts.{loop}.count must be a non-negative integer")


def validate_transition(record: Mapping, target: str, agent: str) -> None:
    """Validate a state change without performing I/O."""
    validate_record(record)
    if not isinstance(target, str) or target not in STATE_TABLE:
        raise OrchestratorError(f"unknown target state: {target}")
    if not isinstance(agent, str) or not agent:
        raise OrchestratorError("--agent is required")

    source = record["state"]
    owner, ordinary_targets = STATE_TABLE[source]
    if source in {"blocked", "human-review"}:
        resume_state = record["resume_state"]
        if agent != "human":
            raise OrchestratorError(f"only human may resume state {source}")
        if resume_state is None or target != resume_state:
            raise OrchestratorError(f"{source} may resume only to its saved resume_state")
        return

    allowed = set(ordinary_targets)
    if source in ACTIVE_STATES:
        allowed.update({"blocked", "human-review"})
    if target not in allowed:
        raise OrchestratorError(f"transition {source} -> {target} is not allowed")

    # Human intervention can suspend any active stage; ordinary progression is owned by that stage.
    authorized = {owner}
    if target in {"blocked", "human-review"} and source in ACTIVE_STATES:
        authorized.add("human")
    if agent not in authorized:
        expected = " or ".join(sorted(value for value in authorized if value)) or "no agent"
        raise OrchestratorError(f"agent {agent!r} cannot transition from {source}; expected {expected}")


def transition_record(
    record: Mapping,
    target: str,
    agent: str,
    head_sha: str | None = None,
    now: str | None = None,
) -> dict:
    validate_transition(record, target, agent)
    updated = deepcopy(dict(record))
    previous_state = updated["state"]
    updated["state"] = target
    updated["owner_agent"] = STATE_TABLE[target][0]
    updated["updated_at"] = now or utc_now()
    updated["updated_by"] = agent
    if head_sha is not None:
        if not re.fullmatch(r"[0-9a-fA-F]{7,64}", head_sha):
            raise OrchestratorError("--head-sha must be a 7-64 character hexadecimal SHA")
        updated["head_sha"] = head_sha
    if target in {"blocked", "human-review"}:
        updated["resume_state"] = previous_state
    else:
        updated["resume_state"] = None
    validate_record(updated)
    return updated


def pr_review_intake_record(
    record: Mapping,
    pr_number: int,
    head_sha: str,
    now: str | None = None,
) -> dict:
    """Record the narrow ship-pr handoff directly into PR Review."""
    validate_record(record)
    if type(pr_number) is not int or pr_number < 1:
        raise OrchestratorError("PR number must be a positive integer")
    if not isinstance(head_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{7,64}", head_sha):
        raise OrchestratorError("PR head SHA must be a 7-64 character hexadecimal SHA")

    state = record["state"]
    if state not in {"todo", "implementation", "pr-review"}:
        raise OrchestratorError(f"cannot start PR Review from task state {state!r}")
    prior_intake = record["actions"].get(PR_REVIEW_INTAKE_ACTION)
    if prior_intake is not None:
        if (
            not isinstance(prior_intake, Mapping)
            or type(prior_intake.get("pr")) is not int
            or prior_intake.get("pr") < 1
            or not isinstance(prior_intake.get("head_sha"), str)
            or not re.fullmatch(r"[0-9a-fA-F]{7,64}", prior_intake.get("head_sha", ""))
        ):
            raise OrchestratorError("existing ship-pr intake metadata is malformed")
        if prior_intake["pr"] != pr_number:
            raise OrchestratorError("task state is already linked to a different ship-pr PR")
    if state == "pr-review" and not prior_intake and record["head_sha"] != head_sha:
        raise OrchestratorError("PR Review already started on a different head SHA")
    if (
        state == "pr-review"
        and prior_intake
        and prior_intake.get("pr") == pr_number
        and prior_intake.get("head_sha") == head_sha
    ):
        return deepcopy(dict(record))

    updated = deepcopy(dict(record))
    updated["state"] = "pr-review"
    updated["owner_agent"] = STATE_TABLE["pr-review"][0]
    updated["updated_by"] = "ship-pr"
    updated["head_sha"] = head_sha
    updated["updated_at"] = now or utc_now()
    updated["resume_state"] = None
    updated["actions"][PR_REVIEW_INTAKE_ACTION] = {
        "pr": pr_number,
        "head_sha": head_sha,
    }
    validate_record(updated)
    return updated


def _subprocess_runner(args: list[str]) -> str:
    try:
        result = subprocess.run(args, check=True, text=True, capture_output=True)
    except FileNotFoundError as exc:
        raise GhError(f"required command not found: {args[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise GhError(f"command failed ({' '.join(args[:3])}): {detail}") from exc
    return result.stdout


class Orchestrator:
    def __init__(self, runner: Callable[[list[str]], str] = _subprocess_runner):
        self.runner = runner

    def call(self, *args: str) -> str:
        return self.runner(list(args)).strip()

    def get_comments(self, issue: int) -> list[dict]:
        endpoint = f"repos/{REPO}/issues/{issue}/comments"
        output = self.call("gh", "api", "--paginate", "--jq", ".[] | {id, body, author: .user.login}", endpoint)
        comments = []
        for line in output.splitlines():
            try:
                comments.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise OrchestratorError("GitHub returned malformed issue comments") from exc
        return comments

    def get_record(self, issue: int) -> tuple[dict, int]:
        if issue < 1:
            raise OrchestratorError("issue must be a positive number")
        comments = self.get_comments(issue)
        found = []
        for comment in comments:
            if STATE_MARKER.search(comment.get("body", "")):
                found.append((parse_record(comment["body"]), int(comment["id"])))
        if len(found) != 1:
            raise OrchestratorError(f"expected exactly one task-state comment for issue #{issue}; found {len(found)}")
        record, comment_id = found[0]
        if record["issue"] != issue:
            raise OrchestratorError("task-state issue number does not match requested issue")
        return record, comment_id

    def write_record(self, issue: int, record: dict, comment_id: int | None) -> None:
        body = serialize_record(record)
        if comment_id is None:
            self.call("gh", "api", "-X", "POST", f"repos/{REPO}/issues/{issue}/comments", "-f", f"body={body}")
        else:
            self.call("gh", "api", "-X", "PATCH", f"repos/{REPO}/issues/comments/{comment_id}", "-f", f"body={body}")

    def ensure_state_label(self, state: str) -> None:
        self.call(
            "gh", "label", "create", f"state:{state}", "--color", "1D76DB",
            "--description", f"Orchestrator task state: {state}", "--force", "-R", REPO,
        )

    def project(self, issue: int, state: str) -> None:
        state_label = f"state:{state}"
        self.ensure_state_label(state)
        names = self.call("gh", "api", "--paginate", "--jq", ".[].name", f"repos/{REPO}/issues/{issue}/labels")
        labels = [line for line in names.splitlines() if line]
        if state_label not in labels:
            self.call("gh", "api", "-X", "POST", f"repos/{REPO}/issues/{issue}/labels", "-f", f"labels[]={state_label}")
        for label in labels:
            if (label.startswith("state:") and label != state_label) or (state == "todo" and label == "backlog"):
                self.call("gh", "api", "-X", "DELETE", f"repos/{REPO}/issues/{issue}/labels/{label}")
        script = Path(__file__).resolve().with_name("task_queue.sh")
        self.call(str(script), "move", str(issue), BOARD_STATUS[state])

    def init(self, issue: int, state: str, agent: str) -> dict:
        if not isinstance(agent, str) or not agent:
            raise OrchestratorError("--agent is required")
        if state not in SEED_STATES:
            raise OrchestratorError(
                f"init may seed only backlog or todo, not {state!r}; later states must be reached with transition"
            )
        if issue < 1:
            raise OrchestratorError("issue must be a positive number")
        if state not in STATE_TABLE:
            raise OrchestratorError(f"unknown state: {state}")
        issue_data = json.loads(self.call("gh", "api", f"repos/{REPO}/issues/{issue}"))
        if issue_data.get("pull_request"):
            raise OrchestratorError(f"#{issue} is a pull request, not an issue")
        for comment in self.get_comments(issue):
            if STATE_MARKER.search(comment.get("body", "")):
                raise OrchestratorError(f"issue #{issue} already has a task-state record")
        record = default_record(issue, state, agent)
        self.write_record(issue, record, None)
        self.project_or_report(issue, state)
        return record

    def project_or_report(self, issue: int, state: str) -> None:
        try:
            self.project(issue, state)
        except Exception as exc:
            raise OrchestratorError(
                f"state comment was updated, but projection failed: {exc}; "
                f"run `orchestrator.py reconcile {issue}` to repair the label and board"
            ) from exc

    def reconcile(self, issue: int) -> dict:
        """Re-project the canonical state to label and board; never changes the record."""
        record, _ = self.get_record(issue)
        self.project(issue, record["state"])
        return record

    def prepare_transition(
        self, record: Mapping, target: str, agent: str, head_sha: str | None = None,
    ) -> dict:
        return transition_record(record, target, agent, head_sha)

    def transition(self, issue: int, target: str, agent: str, head_sha: str | None, dry_run: bool) -> dict:
        record, comment_id = self.get_record(issue)
        updated = self.prepare_transition(record, target, agent, head_sha)
        if record["state"] == "architecture" and target == "implementation":
            labels = self.call("gh", "api", "--paginate", "--jq", ".[].name", f"repos/{REPO}/issues/{issue}/labels")
            if "architecture-approval-required" in labels.splitlines():
                raise OrchestratorError("architecture approval is required; transition to approval-pending first")
        if record["state"] == "approval-pending" and target == "implementation":
            approvals = [
                comment for comment in self.get_comments(issue)
                if comment.get("author") == OWNER
                and "<!-- architecture-approved -->" in comment.get("body", "")
                and APPROVAL_DETAILS.search(comment.get("body", ""))
            ]
            if not approvals:
                raise OrchestratorError("explicit architecture-approved comment is required")
        if dry_run:
            return updated
        self.write_record(issue, updated, comment_id)
        self.project_or_report(issue, target)
        return updated

    def intake_pr_review(self, issue: int, pr_number: int, enable_agent_read: bool, dry_run: bool) -> dict:
        if issue < 1 or pr_number < 1:
            raise OrchestratorError("issue and PR numbers must be positive")

        issue_data = json.loads(self.call("gh", "api", f"repos/{REPO}/issues/{issue}"))
        if issue_data.get("pull_request"):
            raise OrchestratorError(f"#{issue} is a pull request, not an issue")
        if issue_data.get("state") != "open":
            raise OrchestratorError(f"issue #{issue} must be open")

        pr = json.loads(self.call("gh", "api", f"repos/{REPO}/pulls/{pr_number}"))
        if pr.get("state") != "open" or pr.get("base", {}).get("ref") != "main":
            raise OrchestratorError(f"PR #{pr_number} must be open and target main")
        body = pr.get("body") or ""
        closes_issue = re.search(
            rf"(?im)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#{issue}\b",
            body,
        )
        if SHIP_PR_MARKER not in body or not closes_issue:
            raise OrchestratorError(
                f"PR #{pr_number} must have been created by /ship-pr and close issue #{issue}"
            )
        head_sha = (pr.get("head") or {}).get("sha")
        if not isinstance(head_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{7,64}", head_sha):
            raise OrchestratorError(f"PR #{pr_number} has no valid head SHA")

        record, comment_id = self.get_record(issue)
        issue_labels = {label.get("name") for label in issue_data.get("labels", [])}
        if record["state"] == "todo" and ENTRY_LABEL in issue_labels:
            raise OrchestratorError(
                f"issue #{issue} is opted into Architect/Engineer automation; do not skip it at TODO"
            )
        pr_labels = {label.get("name") for label in pr.get("labels", [])}
        if HUMAN_REVIEW_LABEL in issue_labels or HUMAN_REVIEW_LABEL in pr_labels:
            raise OrchestratorError("cannot start PR Review while needs-human-review is present")
        updated = pr_review_intake_record(record, pr_number, head_sha)
        if dry_run:
            return updated

        if updated != record:
            self.write_record(issue, updated, comment_id)
        self.project_or_report(issue, "pr-review")

        comments = self.get_comments(issue)
        if not any(re.search(r"<!-- agent-automation-start:\d+ -->", comment.get("body", "")) for comment in comments):
            self.call(
                "gh", "api", "-X", "POST", f"repos/{REPO}/issues/{issue}/comments",
                "-f", f"body=<!-- agent-automation-start:{int(datetime.now(timezone.utc).timestamp())} -->",
            )

        if ENTRY_LABEL in issue_labels:
            self.call(
                "gh", "api", "-X", "DELETE",
                f"repos/{REPO}/issues/{issue}/labels/{ENTRY_LABEL}",
            )
        if enable_agent_read and ENTRY_LABEL not in pr_labels:
            self.call(
                "gh", "api", "-X", "POST", f"repos/{REPO}/issues/{pr_number}/labels",
                "-f", f"labels[]={ENTRY_LABEL}",
            )
        return updated


def issue_number(value: str) -> int:
    if not re.fullmatch(r"[1-9][0-9]*", value):
        raise argparse.ArgumentTypeError("issue must be a positive number")
    return int(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    state_parser = subparsers.add_parser("state", help="print the canonical task state")
    state_parser.add_argument("issue", type=issue_number)
    init_parser = subparsers.add_parser("init", help="seed a backlog or todo record for an issue without one")
    init_parser.add_argument("issue", type=issue_number)
    init_parser.add_argument("--state", default="todo", choices=sorted(STATE_TABLE))
    init_parser.add_argument("--agent", required=True, help="seeding actor id")
    reconcile_parser = subparsers.add_parser("reconcile", help="re-project the canonical state to label and board")
    reconcile_parser.add_argument("issue", type=issue_number)
    transition_parser = subparsers.add_parser("transition", help="validate and record a state transition")
    transition_parser.add_argument("issue", type=issue_number)
    transition_parser.add_argument("to", choices=sorted(STATE_TABLE))
    transition_parser.add_argument("--agent", required=True)
    transition_parser.add_argument("--head-sha")
    transition_parser.add_argument("--dry-run", action="store_true")
    intake_parser = subparsers.add_parser(
        "intake-pr-review",
        help="record a /ship-pr handoff to PR Review without broadening normal transitions",
    )
    intake_parser.add_argument("issue", type=issue_number)
    intake_parser.add_argument("--pr", required=True, type=issue_number)
    intake_parser.add_argument("--agent-read", action="store_true")
    intake_parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None, runner: Callable[[list[str]], str] = _subprocess_runner) -> int:
    args = build_parser().parse_args(argv)
    orchestrator = Orchestrator(runner)
    try:
        if args.command == "state":
            record, _ = orchestrator.get_record(args.issue)
        elif args.command == "init":
            record = orchestrator.init(args.issue, args.state, args.agent)
        elif args.command == "reconcile":
            record = orchestrator.reconcile(args.issue)
        elif args.command == "intake-pr-review":
            record = orchestrator.intake_pr_review(args.issue, args.pr, args.agent_read, args.dry_run)
        else:
            record = orchestrator.transition(args.issue, args.to, args.agent, args.head_sha, args.dry_run)
        print(json.dumps(record, indent=2, sort_keys=True))
        return 0
    except (OrchestratorError, subprocess.SubprocessError, ValueError) as exc:
        print(f"orchestrator: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
