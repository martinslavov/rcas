#!/usr/bin/env bash
set -euo pipefail

REPO="martinslavov/rcas"

usage() {
  cat <<'EOF'
Usage:
  .github/scripts/execute_pr_check_local.sh <pr-number> [--dry-run]

Description:
  Validates a local-flow PR and sets local agent gate statuses to pending
  (`PR Review`, `QA Agent`, and `Definition of Done`) on the current head SHA.

Notes:
  - PR must be open, target main, include <!-- no-task-issue -->,
    and must not include <!-- ship-pr -->.
  - Requires authenticated gh CLI access to martinslavov/rcas.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || "${1:-}" == "" ]]; then
  usage
  exit 0
fi

PR=""
DRY_RUN="false"

for arg in "$@"; do
  case "$arg" in
    --dry-run)
      DRY_RUN="true"
      ;;
    *)
      if [[ -z "$PR" ]]; then
        PR="$arg"
      else
        echo "error: unexpected argument '$arg'" >&2
        usage
        exit 1
      fi
      ;;
  esac
done

if [[ ! "$PR" =~ ^[1-9][0-9]*$ ]]; then
  echo "error: <pr-number> must be a positive integer" >&2
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "error: gh CLI is required" >&2
  exit 1
fi

PR_JSON="$(gh pr view "$PR" -R "$REPO" --json number,url,state,isDraft,baseRefName,body,headRefOid -q '.')"
PR_STATE="$(printf '%s' "$PR_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["state"])')"
PR_DRAFT="$(printf '%s' "$PR_JSON" | python3 -c 'import json,sys; print(str(json.load(sys.stdin)["isDraft"]).lower())')"
PR_BASE="$(printf '%s' "$PR_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["baseRefName"])')"
PR_URL="$(printf '%s' "$PR_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["url"])')"
PR_BODY="$(printf '%s' "$PR_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["body"] or "")')"
PR_SHA="$(printf '%s' "$PR_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["headRefOid"])')"

if [[ "$PR_STATE" != "OPEN" ]]; then
  echo "error: PR #$PR is not open" >&2
  exit 1
fi
if [[ "$PR_DRAFT" == "true" ]]; then
  echo "error: PR #$PR is draft" >&2
  exit 1
fi
if [[ "$PR_BASE" != "main" ]]; then
  echo "error: PR #$PR must target main" >&2
  exit 1
fi
if [[ "$PR_BODY" != *"<!-- no-task-issue -->"* ]]; then
  echo "error: PR #$PR is missing <!-- no-task-issue --> marker" >&2
  exit 1
fi
if [[ "$PR_BODY" == *"<!-- ship-pr -->"* ]]; then
  echo "error: PR #$PR has <!-- ship-pr --> marker and must use cloud handoff" >&2
  exit 1
fi

PR_LABELS="$(gh api "repos/$REPO/issues/$PR/labels" --jq '.[].name' 2>/dev/null || true)"
if printf '%s\n' "$PR_LABELS" | grep -qx 'cloud-agent'; then
  echo "error: PR #$PR has cloud-agent label and must use cloud handoff" >&2
  exit 1
fi

if [[ "$DRY_RUN" == "true" ]]; then
  echo "Validated local handoff for PR #$PR ($PR_URL)."
  echo "Would set pending statuses on $PR_SHA: PR Review, QA Agent, Definition of Done"
  exit 0
fi

for pair in \
  "PR Review|Waiting for PR review" \
  "QA Agent|Waiting for QA" \
  "Definition of Done|Manual only - not run by flows"
do
  context="${pair%%|*}"
  description="${pair#*|}"
  gh api -X POST "repos/$REPO/statuses/$PR_SHA" \
    -f "state=pending" \
    -f "context=$context" \
    -f "description=$description" >/dev/null
done

echo "Initialized local PR checks for PR #$PR ($PR_URL) on $PR_SHA."
echo "Next: run pr-review-agent, then senior-qa-engineer after PR Review succeeds."

