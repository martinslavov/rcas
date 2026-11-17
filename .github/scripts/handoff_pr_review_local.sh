#!/usr/bin/env bash
set -euo pipefail

REPO="martinslavov/rcas"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

usage() {
  cat <<'EOF'
Usage:
  .github/scripts/handoff_pr_review_local.sh <pr-number> [--dry-run] [--no-watch]

Description:
  Runs local PR handoff end-to-end for a no-task-issue PR:
  1) initialize pending statuses
  2) run pr-review-agent via local Copilot CLI
  3) run senior-qa-engineer after PR Review succeeds

Notes:
  - PR must be local-flow (`<!-- no-task-issue -->`) and target main.
  - Requires authenticated `gh` CLI and `copilot` CLI.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || "${1:-}" == "" ]]; then
  usage
  exit 0
fi

PR=""
DRY_RUN="false"
WATCH="true"

for arg in "$@"; do
  case "$arg" in
    --dry-run)
      DRY_RUN="true"
      ;;
    --no-watch)
      WATCH="false"
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

for bin in gh copilot python3; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "error: required command not found: $bin" >&2
    exit 1
  fi
done

cd "$ROOT_DIR"

INIT_ARGS=("$SCRIPT_DIR/execute_pr_check_local.sh" "$PR")
if [[ "$DRY_RUN" == "true" ]]; then
  INIT_ARGS+=("--dry-run")
fi

bash "${INIT_ARGS[@]}"

if [[ "$DRY_RUN" == "true" ]]; then
  echo "Dry-run only: local handoff validated."
  exit 0
fi

PR_JSON="$(gh pr view "$PR" -R "$REPO" --json url,headRefOid -q '.')"
PR_URL="$(printf '%s' "$PR_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["url"])')"
HEAD_SHA="$(printf '%s' "$PR_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["headRefOid"])')"

status_for() {
  local sha="$1"
  local context="$2"
  gh api "repos/$REPO/commits/$sha/status" \
    | python3 -c 'import json,sys; ctx=sys.argv[1]; payload=json.load(sys.stdin); items=[s for s in payload.get("statuses",[]) if s.get("context")==ctx]; print((items[-1].get("state") if items else ""))' "$context"
}

run_agent() {
  local agent="$1"
  local prompt="$2"
  local session="$3"
  copilot --prompt "$prompt" --agent "$agent" --name "$session" --allow-all-tools --trust-folder -C "$ROOT_DIR"
}

review_prompt=$(cat <<EOF
Review PR #$PR in $REPO using the full diff and set the final PR Review status on the current head SHA.
Do not edit files or push commits.
Post severity-ranked findings in a PR comment and include the required marker <!-- pr-review-round:N -->.
Use the repository workflow rules from .github/copilot-instructions.md.
EOF
)

qa_prompt=$(cat <<EOF
Run QA for PR #$PR in $REPO only after PR Review is success on the current head SHA.
Validate acceptance criteria and set the final QA Agent status on the same SHA.
Do not edit files or push commits.
Use the repository workflow rules from .github/copilot-instructions.md.
EOF
)

echo "Starting local pr-review-agent for PR #$PR ($PR_URL) on $HEAD_SHA"
run_agent "pr-review-agent" "$review_prompt" "pr-$PR-review"

UPDATED_SHA="$(gh pr view "$PR" -R "$REPO" --json headRefOid -q .headRefOid)"
if [[ "$UPDATED_SHA" != "$HEAD_SHA" ]]; then
  echo "error: PR head changed during PR Review ($HEAD_SHA -> $UPDATED_SHA). Re-run handoff." >&2
  exit 1
fi

REVIEW_STATE="$(status_for "$HEAD_SHA" "PR Review")"
if [[ "$REVIEW_STATE" != "success" ]]; then
  echo "PR Review did not pass (state: ${REVIEW_STATE:-missing}). QA will not start."
  exit 1
fi

echo "Starting local senior-qa-engineer for PR #$PR on $HEAD_SHA"
run_agent "senior-qa-engineer" "$qa_prompt" "pr-$PR-qa"

UPDATED_SHA="$(gh pr view "$PR" -R "$REPO" --json headRefOid -q .headRefOid)"
if [[ "$UPDATED_SHA" != "$HEAD_SHA" ]]; then
  echo "error: PR head changed during QA ($HEAD_SHA -> $UPDATED_SHA). Re-run handoff." >&2
  exit 1
fi

QA_STATE="$(status_for "$HEAD_SHA" "QA Agent")"
if [[ "$QA_STATE" != "success" ]]; then
  echo "QA Agent finished with state: ${QA_STATE:-missing}."
  exit 1
fi

echo "Local handoff completed: PR Review=success, QA Agent=success on $HEAD_SHA"
if [[ "$WATCH" == "true" ]]; then
  gh pr checks "$PR" -R "$REPO" --watch
fi

