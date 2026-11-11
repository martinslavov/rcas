#!/usr/bin/env python3
"""Parse the control lines accepted by the Product Owner task intake."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass


class TaskInputError(ValueError):
    """The task input does not follow the supported intake contract."""


@dataclass(frozen=True)
class TaskInput:
    task_name: str
    description: str
    labels: tuple[str, ...]


TAG_LINE = re.compile(r"^TAG:\s*([a-z][a-z0-9-]*)\s*$")
TASK_LINE = re.compile(r"^TASK-NAME:\s*(.*?)\s*$")
BACKLOG_TASK_LINE = re.compile(r"^LABEL:BACKLOG,TASK-NAME:\s*(.*?)\s*$", re.IGNORECASE)


def parse_task_input(text: str) -> TaskInput:
    """Consume optional control metadata and return only issue content."""
    lines = text.splitlines()
    if not lines:
        raise TaskInputError("task input is empty")

    labels: list[str] = []
    if lines[0].startswith("TAG:"):
        tag_match = TAG_LINE.fullmatch(lines[0])
        if tag_match is None:
            raise TaskInputError("TAG must be a single supported label on the first line")
        if tag_match.group(1) != "agent-read":
            raise TaskInputError(f"unsupported TAG: {tag_match.group(1)}")
        labels.append("agent-read")
        lines = lines[1:]
        if not lines:
            raise TaskInputError("TASK-NAME is required after TAG")

    first_line = lines[0]
    task_match = TASK_LINE.fullmatch(first_line)
    if task_match is None:
        task_match = BACKLOG_TASK_LINE.fullmatch(first_line)
        if task_match is not None:
            labels.append("backlog")
    if task_match is None or not task_match.group(1):
        raise TaskInputError("expected TASK-NAME:<name> or LABEL:BACKLOG,TASK-NAME:<name>")

    task_name = task_match.group(1).strip()
    if not task_name:
        raise TaskInputError("task name must not be empty")
    description = "\n".join(lines[1:]).lstrip("\n")
    return TaskInput(task_name=task_name, description=description, labels=tuple(labels))


def main() -> int:
    try:
        parsed = parse_task_input(sys.stdin.read())
    except TaskInputError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps({
        "task_name": parsed.task_name,
        "description": parsed.description,
        "labels": list(parsed.labels),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
