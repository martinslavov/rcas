#!/usr/bin/env bash
# Task queue on the RCAS Tracking board (user martinslavov, project 1).
#
#   task_queue.sh list                     open TODO issues, oldest first: "<number>\t<title>"
#   task_queue.sh move <issue> <status>    set the board Status of an issue (adds it to the board if missing)
#
# Status is one of the board columns: Backlog, Assessment, Defining, TODO, In Progress, Done.
set -euo pipefail

OWNER="martinslavov"
REPO="martinslavov/rcas"
PROJECT_NUMBER=1

usage() {
  echo "usage: $0 list | move <issue-number> <status>" >&2
  exit 2
}

project_json() {
  gh api graphql -f query='query($owner: String!, $number: Int!) { user(login: $owner) { projectV2(number: $number) { id field(name: "Status") { ... on ProjectV2SingleSelectField { id options { id name } } } } } }' \
    -f owner="$OWNER" -F number="$PROJECT_NUMBER" --jq '.data.user.projectV2'
}

list_todo() {
  local cursor="" page
  while :; do
    page=$(gh api graphql -f query='query($owner: String!, $number: Int!, $after: String) { user(login: $owner) { projectV2(number: $number) { items(first: 100, after: $after) { pageInfo { hasNextPage endCursor } nodes { status: fieldValueByName(name: "Status") { ... on ProjectV2ItemFieldSingleSelectValue { name } } content { ... on Issue { number title state repository { nameWithOwner } } } } } } } }' \
      -f owner="$OWNER" -F number="$PROJECT_NUMBER" ${cursor:+-f after="$cursor"} --jq '.data.user.projectV2.items')
    jq -r --arg repo "$REPO" '.nodes[]
      | select(.status.name == "TODO" and .content.state == "OPEN" and .content.repository.nameWithOwner == $repo)
      | "\(.content.number)\t\(.content.title)"' <<< "$page"
    [[ $(jq -r '.pageInfo.hasNextPage' <<< "$page") == "true" ]] || break
    cursor=$(jq -r '.pageInfo.endCursor' <<< "$page")
  done | sort -n -k1,1
}

move_issue() {
  local issue="$1" status="$2" project project_id field_id option_id issue_id item_id
  [[ "$issue" =~ ^[1-9][0-9]*$ ]] || { echo "issue must be a positive number: $issue" >&2; exit 2; }
  project=$(project_json)
  project_id=$(jq -r '.id' <<< "$project")
  field_id=$(jq -r '.field.id' <<< "$project")
  option_id=$(jq -r --arg s "$status" '.field.options[] | select(.name == $s) | .id' <<< "$project")
  if [[ -z "$option_id" ]]; then
    echo "unknown status '$status'; valid: $(jq -r '[.field.options[].name] | join(", ")' <<< "$project")" >&2
    exit 2
  fi
  issue_id=$(gh api "repos/$REPO/issues/$issue" --jq '.node_id')
  item_id=$(gh api graphql \
    -f query='mutation($project: ID!, $content: ID!) { addProjectV2ItemById(input: {projectId: $project, contentId: $content}) { item { id } } }' \
    -f project="$project_id" -f content="$issue_id" --jq '.data.addProjectV2ItemById.item.id')
  gh api graphql \
    -f query='mutation($project: ID!, $item: ID!, $field: ID!, $option: String!) { updateProjectV2ItemFieldValue(input: {projectId: $project, itemId: $item, fieldId: $field, value: {singleSelectOptionId: $option}}) { projectV2Item { id } } }' \
    -f project="$project_id" -f item="$item_id" -f field="$field_id" -f option="$option_id" > /dev/null
  echo "#$issue -> $status"
}

case "${1:-}" in
  list) [[ $# -eq 1 ]] || usage; list_todo ;;
  move) [[ $# -eq 3 ]] || usage; move_issue "$2" "$3" ;;
  *) usage ;;
esac
