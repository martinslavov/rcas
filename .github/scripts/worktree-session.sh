#!/usr/bin/env bash
set -euo pipefail

is_sourced=0
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  is_sourced=1
fi

die() {
  local code="$1"
  shift
  printf '%s\n' "$*" >&2
  if (( is_sourced )); then
    return "$code"
  fi
  exit "$code"
}

warn() {
  printf '%s\n' "$*" >&2
}

usage() {
  cat >&2 <<'EOF'
usage:
  worktree-session.sh start <session-name> [--open]
  worktree-session.sh cleanup <session-name>

Session names must contain lowercase letters, digits, and hyphens, and start with a letter or digit.
After start, the script switches to the created worktree (interactive shell handoff when executed directly).
IDE auto-open is disabled by default; use --open to launch JetBrains.
Set WORKTREE_SESSION_NO_CHDIR=1 to disable automatic switching.
EOF
  if (( is_sourced )); then
    return 2
  fi
  exit 2
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(git -C "$script_dir/../.." rev-parse --show-toplevel)"
repo_name="$(basename "$repo_root")"
sessions_root="$(dirname "$repo_root")/${repo_name}-sessions"
last_started_worktree=""

validate_name() {
  local name="$1"
  [[ "$name" =~ ^[a-z0-9][a-z0-9-]*$ ]] || {
    die 2 "invalid session name '$name'; use lowercase letters, digits, and hyphens"
  }
}

worktree_path() {
  printf '%s/%s' "$sessions_root" "$1"
}

start_session() {
  local name="$1" open_ide="${2:-true}" branch target
  validate_name "$name"
  branch="session/$name"
  target="$(worktree_path "$name")"

  if [[ -e "$target" || -L "$target" ]]; then
    die 1 "worktree path already exists: $target"
  fi
  if git -C "$repo_root" show-ref --verify --quiet "refs/heads/$branch"; then
    die 1 "branch already exists: $branch"
  fi

  git -C "$repo_root" fetch --quiet origin refs/heads/main:refs/remotes/origin/main
  mkdir -p "$sessions_root"
  git -C "$repo_root" worktree add -b "$branch" "$target" origin/main
  last_started_worktree="$target"
  printf 'Created %s at %s\n' "$branch" "$target"

  if [[ "$open_ide" == true ]]; then
    if ! command -v open >/dev/null 2>&1; then
      warn "worktree created, but macOS 'open' is unavailable; open the path manually: $target"
      return 0
    fi
    if ! open -a "${JETBRAINS_APP:-IntelliJ IDEA}" "$target"; then
      warn "worktree created, but JetBrains could not open it; open the path manually: $target"
    fi
  fi
}

switch_to_started_worktree() {
  local target="$1"

  [[ -n "$target" ]] || return 0
  [[ "${WORKTREE_SESSION_NO_CHDIR:-0}" == "1" ]] && return 0

  if (( is_sourced )); then
    cd "$target"
    printf 'Switched current shell to %s\n' "$target"
    return 0
  fi

  if [[ -t 0 && -t 1 ]]; then
    local shell_bin="${SHELL:-/bin/zsh}"
    printf 'Switching terminal session to %s (exit this shell to return).\n' "$target"
    exec "$shell_bin" -i -c "cd \"$target\" && exec \"$shell_bin\" -i"
  fi
}

cleanup_session() {
  local name="$1" branch target status
  validate_name "$name"
  target="$(worktree_path "$name")"

  if [[ -L "$target" || ! -d "$target" ]]; then
    die 1 "worktree directory not found or is a symlink: $target"
  fi
  if [[ "$(git -C "$target" rev-parse --show-toplevel 2>/dev/null || true)" != "$target" ]]; then
    die 1 "refusing to remove a directory that is not this worktree: $target"
  fi
  branch="$(git -C "$target" branch --show-current)"
  case "$branch" in
    "session/$name"|"feature/$name"|"hotfix/$name") ;;
    *)
      die 1 "refusing to remove worktree: expected session/$name, feature/$name or hotfix/$name"
      ;;
  esac

  status="$(git -C "$target" status --porcelain --untracked-files=all)"
  if [[ -n "$status" ]]; then
    printf '%s\n' "refusing to remove worktree with uncommitted or untracked files:" >&2
    printf '%s\n' "$status" >&2
    if (( is_sourced )); then
      return 1
    fi
    exit 1
  fi

  git -C "$repo_root" fetch --quiet origin refs/heads/main:refs/remotes/origin/main
  if ! git -C "$repo_root" merge-base --is-ancestor "$branch" origin/main; then
    die 1 "refusing to remove $branch: it is not merged into origin/main"
  fi

  git -C "$repo_root" worktree remove "$target"
  git -C "$repo_root" branch -d "$branch"
  printf 'Removed worktree %s and local branch %s\n' "$target" "$branch"
}

[[ $# -ge 2 ]] || usage
command="$1"
name="$2"
shift 2

case "$command" in
  start)
    if [[ $# -eq 0 ]]; then
      start_session "$name" false
    elif [[ $# -eq 1 && "$1" == "--open" ]]; then
      start_session "$name" true
    elif [[ $# -eq 1 && "$1" == "--no-open" ]]; then
      start_session "$name" false
    else
      usage
    fi
    switch_to_started_worktree "$last_started_worktree"
    ;;
  cleanup)
    [[ $# -eq 0 ]] || usage
    cleanup_session "$name"
    ;;
  *)
    usage
    ;;
esac
