#!/usr/bin/env bash
set -euo pipefail

REPO="martinslavov/rcas"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
ORCHESTRATOR="$SCRIPT_DIR/orchestrator.py"

usage() {
  cat <<'EOF'
Usage:
  .github/scripts/execute_pr_check.sh <pr-number> [--dry-run]

Description:
  Starts PR Review -> QA automation for an existing task-linked PR by running
  orchestrator intake and enabling cloud-agent on the PR.

Notes:
  - PR must be open, target main, include <!-- ship-pr --> and Closes #<issue>.
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

PR_JSON="$(gh pr view "$PR" -R "$REPO" --json number,url,state,isDraft,baseRefName,body -q '.')"
PR_STATE="$(printf '%s' "$PR_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["state"])')"
PR_DRAFT="$(printf '%s' "$PR_JSON" | python3 -c 'import json,sys; print(str(json.load(sys.stdin)["isDraft"]).lower())')"
PR_BASE="$(printf '%s' "$PR_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["baseRefName"])')"
PR_URL="$(printf '%s' "$PR_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["url"])')"
PR_BODY="$(printf '%s' "$PR_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["body"] or "")')"

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
if [[ "$PR_BODY" != *"<!-- ship-pr -->"* ]]; then
  echo "error: PR #$PR is missing <!-- ship-pr --> marker" >&2
  exit 1
fi

ISSUE="$(python3 - "$PR_BODY" <<'PY'
import re
import sys
body = sys.argv[1]
match = re.search(r'(?im)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#([1-9][0-9]*)\b', body)
print(match.group(1) if match else "")
PY
)"

if [[ -z "$ISSUE" ]]; then
  echo "error: PR #$PR does not reference a task issue with Closes/Fixes/Resolves #<issue>" >&2
  exit 1
fi

cd "$ROOT_DIR"

ARGS=("$ORCHESTRATOR" "intake-pr-review" "$ISSUE" "--pr" "$PR" "--cloud-agent")
if [[ "$DRY_RUN" == "true" ]]; then
  ARGS+=("--dry-run")
fi

python3 "${ARGS[@]}"

echo ""
echo "Triggered PR checks handoff for PR #$PR ($PR_URL) linked to issue #$ISSUE."
echo "Follow progress with: gh pr checks $PR -R $REPO --watch"

