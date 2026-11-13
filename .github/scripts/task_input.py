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


TAG_LINE = re.compile(r"^TAG:\s*([a-z][a-z0-9-]*(?:,[a-z][a-z0-9-]*)*)\s*$")
DEVELOPMENT_LINE = re.compile(r"^DEVELOPMENT:\s*(low|medium|high)\s*$", re.IGNORECASE)
TASK_LINE = re.compile(r"^TASK-NAME:\s*(.*?)\s*$")
BACKLOG_TASK_LINE = re.compile(r"^LABEL:BACKLOG,TASK-NAME:\s*(.*?)\s*$", re.IGNORECASE)
DESCRIPTION_PREFIX = re.compile(r"^DESCRIPTION:[ \t]*")
SUPPORTED_TAGS = frozenset({"cloud-agent", "local-agent", "skip-architect", "skip-product-owner"})


def parse_task_input(text: str) -> TaskInput:
    """Consume optional control metadata and return only issue content."""
    lines = text.splitlines()
    if not lines:
        raise TaskInputError("task input is empty")

    labels: list[str] = []
    if lines[0].startswith("TAG:"):
        tag_match = TAG_LINE.fullmatch(lines[0])
        if tag_match is None:
            raise TaskInputError("TAG must contain supported labels separated by commas")
        labels.extend(_parse_tags(tag_match.group(1)))
        lines = lines[1:]
        if not lines:
            raise TaskInputError("TASK-NAME is required after TAG")

    task_match = TASK_LINE.fullmatch(lines[0])
    if task_match is None:
        task_match = BACKLOG_TASK_LINE.fullmatch(lines[0])
        if task_match is not None:
            labels.append("backlog")
    if task_match is None:
        raise TaskInputError("expected TASK-NAME:<name> or LABEL:BACKLOG,TASK-NAME:<name>")

    task_name = task_match.group(1).strip()
    if not task_name:
        raise TaskInputError("task name must not be empty")

    description_lines = lines[1:]
    development = None
    while description_lines and (
        description_lines[0].startswith("DEVELOPMENT:")
        or description_lines[0].startswith("TAG:")
    ):
        control_line = description_lines.pop(0)
        if control_line.startswith("DEVELOPMENT:"):
            development_match = DEVELOPMENT_LINE.fullmatch(control_line)
            if development_match is None:
                raise TaskInputError("DEVELOPMENT must be low, medium, or high")
            if development is not None:
                raise TaskInputError("DEVELOPMENT may be specified only once")
            development = development_match.group(1).lower()
            continue
        tag_match = TAG_LINE.fullmatch(control_line)
        if tag_match is None:
            raise TaskInputError("TAG must contain supported labels separated by commas")
        labels.extend(_parse_tags(tag_match.group(1)))

    description = "\n".join(description_lines).lstrip("\n")
    description = DESCRIPTION_PREFIX.sub("", description, count=1)
    if development is not None:
        labels.append(f"development:{development}")
    if "cloud-agent" in labels and "local-agent" in labels:
        raise TaskInputError("cloud-agent and local-agent are mutually exclusive")
    ordered = ("cloud-agent", "local-agent", "skip-architect", "skip-product-owner", "backlog")
    ordered_labels = tuple(label for label in ordered if label in labels)
    if development is not None:
        ordered_labels += (f"development:{development}",)
    return TaskInput(task_name=task_name, description=description, labels=ordered_labels)


def _parse_tags(value: str) -> list[str]:
    tags = value.split(",")
    if any(not tag or tag.strip() != tag for tag in tags):
        raise TaskInputError("TAG must contain supported labels separated by commas")
    unsupported = [tag for tag in tags if tag not in SUPPORTED_TAGS]
    if unsupported:
        raise TaskInputError(f"unsupported TAG: {unsupported[0]}")
    return tags


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
