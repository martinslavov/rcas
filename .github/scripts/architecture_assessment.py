#!/usr/bin/env python3
"""Shared Product Owner architecture-assessment contract."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

ASSESSMENT_MARKER = re.compile(
    r"<!--\s*architecture-assessment:\s*([^<>]*?)\s*-->",
    re.IGNORECASE,
)
ASSESSMENT_SECTION = re.compile(
    r"(?ims)^#{2,4}\s*Architecture assessment\s*$([\s\S]*?)(?=^#{1,4}\s|\Z)",
)
RATIONALE = re.compile(r"(?im)^\s*Rationale:\s*(\S.*)$")
DECISION = re.compile(r"(?im)^\s*Decision:\s*(required|not-required|uncertain)\s*$")
REASSESSMENT_MARKER = "<!-- architecture-review-requested -->"
DESIGN_MARKERS = ("<!-- architect-design-note -->", "<!-- architect-skipped -->")
APPROVAL_MARKER = "<!-- architecture-approved -->"

REQUIRED = "required"
NOT_REQUIRED = "not-required"
UNCERTAIN = "uncertain"


def assessment_from_body(body: str | None) -> str:
    """Treat absent, duplicated, or malformed assessments as requiring Architect."""
    matches = ASSESSMENT_MARKER.findall(body or "")
    if len(matches) != 1:
        return REQUIRED
    value = matches[0].strip().lower()
    sections = ASSESSMENT_SECTION.findall(body or "")
    if value not in {REQUIRED, NOT_REQUIRED, UNCERTAIN} or len(sections) != 1:
        return REQUIRED
    decision = DECISION.search(sections[0])
    rationale = RATIONALE.search(sections[0])
    if not decision or decision.group(1).lower() != value or not rationale:
        return REQUIRED
    if rationale.group(1).strip().lower() in {
        "pending product owner assessment.",
        "pending assessment.",
        "pending",
        "tbd",
        "n/a",
    }:
        return REQUIRED
    return value


def requires_architect(body: str | None, labels: Iterable[str] = ()) -> bool:
    label_set = set(labels)
    if "skip-architect" in label_set:
        return False
    return (
        assessment_from_body(body) != NOT_REQUIRED
        or "architecture-approval-required" in label_set
    )


def reassessment_count(comments: Iterable[Mapping[str, object]]) -> int:
    return sum(
        1
        for comment in comments
        if REASSESSMENT_MARKER in str(comment.get("body") or "")
    )


def has_current_approval(comments: Iterable[Mapping[str, object]], owner: str) -> bool:
    comment_list = list(comments)
    trusted_authors = {owner, "copilot-swe-agent", "copilot-swe-agent[bot]"}
    design_indexes = []
    for index, comment in enumerate(comment_list):
        user = comment.get("user")
        author = comment.get("author")
        login = user.get("login") if isinstance(user, Mapping) else author
        if login in trusted_authors and any(
            marker in str(comment.get("body") or "") for marker in DESIGN_MARKERS
        ):
            design_indexes.append(index)
    if not design_indexes:
        return False
    latest_design_index = design_indexes[-1]
    return any(
        index > latest_design_index
        and (comment.get("user", {}).get("login") if isinstance(comment.get("user"), Mapping)
             else comment.get("author")) == owner
        and APPROVAL_MARKER in str(comment.get("body") or "")
        and re.search(
            rf"Approved by @{re.escape(owner)} at \d{{4}}-\d{{2}}-\d{{2}}T\d{{2}}:\d{{2}}:\d{{2}}Z",
            str(comment.get("body") or ""),
        )
        for index, comment in enumerate(comment_list)
    )
