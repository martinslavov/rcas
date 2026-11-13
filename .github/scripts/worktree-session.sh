#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
usage:
  worktree-session.sh start <session-name> [--no-open]
  worktree-session.sh cleanup <session-name>

Session names must contain lowercase letters, digits, and hyphens, and start with a letter or digit.
EOF
  exit 2
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(git -C "$script_dir/../.." rev-parse --show-toplevel)"
repo_name="$(basename "$repo_root")"
sessions_root="$(dirname "$repo_root")/${repo_name}-sessions"

validate_name() {
  local name="$1"
  [[ "$name" =~ ^[a-z0-9][a-z0-9-]*$ ]] || {
    echo "invalid session name '$name'; use lowercase letters, digits, and hyphens" >&2
    exit 2
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
    echo "worktree path already exists: $target" >&2
    exit 1
  fi
  if git -C "$repo_root" show-ref --verify --quiet "refs/heads/$branch"; then
    echo "branch already exists: $branch" >&2
    exit 1
  fi

  git -C "$repo_root" fetch --quiet origin refs/heads/main:refs/remotes/origin/main
  mkdir -p "$sessions_root"
  git -C "$repo_root" worktree add -b "$branch" "$target" origin/main
  printf 'Created %s at %s\n' "$branch" "$target"

  if [[ "$open_ide" == true ]]; then
    if ! command -v open >/dev/null 2>&1; then
      echo "worktree created, but macOS 'open' is unavailable; open the path manually: $target" >&2
      exit 1
    fi
    if ! open -a "${JETBRAINS_APP:-IntelliJ IDEA}" "$target"; then
      echo "worktree created, but JetBrains could not open it; open the path manually: $target" >&2
      exit 1
    fi
  fi
}

cleanup_session() {
  local name="$1" branch target status
  validate_name "$name"
  target="$(worktree_path "$name")"

  if [[ -L "$target" || ! -d "$target" ]]; then
    echo "worktree directory not found or is a symlink: $target" >&2
    exit 1
  fi
  if [[ "$(git -C "$target" rev-parse --show-toplevel 2>/dev/null || true)" != "$target" ]]; then
    echo "refusing to remove a directory that is not this worktree: $target" >&2
    exit 1
  fi
  branch="$(git -C "$target" branch --show-current)"
  case "$branch" in
    "session/$name"|"feature/$name"|"hotfix/$name") ;;
    *)
      echo "refusing to remove worktree: expected session/$name, feature/$name or hotfix/$name" >&2
      exit 1
      ;;
  esac

  status="$(git -C "$target" status --porcelain --untracked-files=all)"
  if [[ -n "$status" ]]; then
    echo "refusing to remove worktree with uncommitted or untracked files:" >&2
    printf '%s\n' "$status" >&2
    exit 1
  fi

  git -C "$repo_root" fetch --quiet origin refs/heads/main:refs/remotes/origin/main
  if ! git -C "$repo_root" merge-base --is-ancestor "$branch" origin/main; then
    echo "refusing to remove $branch: it is not merged into origin/main" >&2
    exit 1
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
      start_session "$name"
    elif [[ $# -eq 1 && "$1" == "--no-open" ]]; then
      start_session "$name" false
    else
      usage
    fi
    ;;
  cleanup)
    [[ $# -eq 0 ]] || usage
    cleanup_session "$name"
    ;;
  *)
    usage
    ;;
esac
