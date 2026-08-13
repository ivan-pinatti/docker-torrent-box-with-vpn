#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2022 Ivan Pinatti
#
# Claude Code PreToolUse hook for the Bash tool. Reads the hook payload on
# stdin and refuses two classes of git command. Printing nothing allows the
# command, so every path that is not an explicit refusal must fall through to
# the exit 0 at the bottom.
#
# Enforces three rules that were previously prose in CLAUDE.md and were broken
# anyway:
#
#   1. No skipping the pre-commit hooks. They run the secret scanners, and a
#      bypass is how an unscanned change reaches a public repository.
#   2. No working-tree git operations while the stack is running. pre-commit
#      stashes the working tree, and doing that against live SQLite databases
#      corrupted them on 2026-07-07.
#   3. No committing into a clone where the hooks were never installed. Rule 1
#      catches a deliberate bypass, but a fresh clone reaches the same place
#      with no flag at all: git clone does not install them, so every commit
#      silently runs nothing and still reports success.
set -uo pipefail

# Refusal JSON is built by hand here because this runs before jq is known to
# exist. Everything after the jq check uses jq to encode the reason safely.
deny_without_jq() {
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}' "$1"
  exit 0
}

payload="$(cat)"

# Fail closed. This hook cannot inspect a command it cannot parse, and a hook
# that quietly allows everything the moment a dependency is missing is worse
# than no hook, because it still reads as protection. jq is already a
# requirement of this repository.
if ! command -v jq >/dev/null 2>&1; then
  deny_without_jq "The git guard could not run because jq is not installed, so it cannot tell whether this command is safe. Refusing rather than allowing it unchecked. Install jq to continue."
fi

if ! cmd="$(printf '%s' "$payload" | jq -er '.tool_input.command // ""' 2>/dev/null)"; then
  deny_without_jq "The git guard could not parse the hook payload, so it cannot tell whether this command is safe. Refusing rather than allowing it unchecked."
fi

[ -n "$cmd" ] || exit 0

# Heredoc bodies come off first. They are data, but unlike a quoted span they run
# across lines and each line can look exactly like a command of its own, so a
# commit message written as a heredoc that happens to contain "; git reset
# --hard" reads as a reset. Keep the line carrying the << operator, drop
# everything up to the terminator.
strip_heredoc_bodies() {
  awk '
    in_body { if ($0 == terminator) { in_body = 0 }; next }
    {
      print
      if (match($0, /<<-?[[:space:]]*[A-Za-z_"'"'"'][A-Za-z0-9_"'"'"']*/)) {
        terminator = substr($0, RSTART, RLENGTH)
        sub(/^<<-?[[:space:]]*/, "", terminator)
        gsub(/["'"'"']/, "", terminator)
        in_body = 1
      }
    }
  '
}

cmd_bare="$(printf '%s' "$cmd" | strip_heredoc_bodies)"

# The two rules need opposite things from quoting, so each gets its own form.
#
# Rule 1 asks "is this flag being passed to git", so quote *characters* come
# off and the text inside stays: git commit "--no-verify" really does pass the
# flag. Message option values are dropped first, so a commit message may
# describe the flag without counting as using it.
#
# Rule 2 asks "is this a git command", so whole quoted *spans* come out. Their
# contents are an argument to something else, and a string that merely reads
# like a command must not be treated as one. Sharing rule 1's form here made
# 'git stash list; git reset --hard', written as a test case, look real.
cmd_flags="$(
  printf '%s' "$cmd_bare" |
    sed -E "s/(-m|--message)[[:space:]]*=?[[:space:]]*'[^']*'//g; s/(-m|--message)[[:space:]]*=?[[:space:]]*\"[^\"]*\"//g" |
    tr -d "\"'"
)"

cmd_verbs="$(printf '%s' "$cmd_bare" | sed -E "s/'[^']*'//g; s/\"[^\"]*\"//g")"

# Matches only where a command actually starts: beginning of the string, or
# after a separator. Without this the hook matches any mention of the word,
# including one inside a string, and the first version of it blocked its own
# test command that way.
AT_COMMAND='(^|[;&|(]|&&|\|\|)[[:space:]]*'

# git accepts its own options before the subcommand, so git -C /repo stash is
# a stash and has to be caught as one. Matches a run of option tokens, each
# optionally followed by its value.
GIT_OPTIONS='([[:space:]]+-[^[:space:]]+([[:space:]]+[^-[:space:]][^[:space:]]*)?)*'

# git is not always spelled "git" at the start of the command. Every one of
# `command git`, `env CI=1 git`, `sudo git`, `/usr/bin/git` and `\git` runs it
# just the same, and all of them walked straight past the matchers below.
# env is the awkward one: its assignments sit between it and the command.
WRAPPERS='((command|builtin|exec|sudo|nohup|time|env)([[:space:]]+[A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*)*[[:space:]]+)*'

# A leading backslash suppresses alias lookup; a path prefix names the binary
# outright. The optional group needs the trailing slash so that "mygit" is not
# read as git.
GIT='\\?([^[:space:]]*/)?git'

# Everything that rewrites tracked files in the working tree, not just the
# stash that caused the original corruption. reset --hard, restore and clean
# are all at least as destructive.
WORKTREE_VERBS='(stash|commit|checkout|switch|restore|reset|revert|merge|rebase|cherry-pick|am|apply|clean|mv|rm|pull)'

# `git stash list` and `git stash show` only read, so they do not belong in the
# set below. Renaming them here rather than carving out an exception in the
# match keeps that composable: in `git stash list; git reset --hard` only the
# stash is exempted and the reset is still caught. An exception expressed as
# "unless the command mentions stash list" would have let that whole line
# through.
cmd_verbs="$(printf '%s' "$cmd_verbs" | sed -E 's/stash([[:space:]]+(list|show))/stash-readonly\1/g')"

matches_flags() { printf '%s' "$cmd_flags" | grep -qE "$1"; }
matches_verbs() { printf '%s' "$cmd_verbs" | grep -qE "$1"; }

deny() {
  jq -cn --arg reason "$1" \
    '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $reason}}'
  exit 0
}

# 1. Verification bypass. Refused whether or not the stack is running, because
#    the risk here is an unscanned commit rather than a corrupted database.
#    A bare -n on push means --dry-run, so only the long form counts there.
#
#    The flag has to be an argument of that same git command: one regex rather
#    than two, so grep's line orientation confines the match to a single line,
#    and [^;&|]* stops it reaching across a pipe or separator into a different
#    command. Checked separately, a heredoc body naming the flag counted as
#    using it, and this hook refused the commit that introduced it twice over.
ARGUMENTS_BEFORE='([^;&|]*[[:space:]])?'

if matches_flags "${AT_COMMAND}${WRAPPERS}${GIT}${GIT_OPTIONS}[[:space:]]+commit[[:space:]]${ARGUMENTS_BEFORE}(--no-verify|-n)([[:space:]]|\$)"; then
  deny "git commit --no-verify is not allowed in this repository. It skips the pre-commit hooks, which is where the secret scanning runs, so a bypassed commit can publish credentials to a public repo. If pre-commit is failing, fix what it reports. If it is blocked because the stack is running, stop the stack (make stop_all) and commit normally: that is the supported path, and pre-commit's stash cycle is only dangerous against live databases."
fi

if matches_flags "${AT_COMMAND}${WRAPPERS}${GIT}${GIT_OPTIONS}[[:space:]]+push[[:space:]]${ARGUMENTS_BEFORE}--no-verify([[:space:]]|\$)"; then
  deny "git push --no-verify is not allowed in this repository. It skips the pre-push hooks, which run the full MegaLinter pass including the secret scanners."
fi

# 3. Committing where the hooks were never installed. On 2026-08-12 two commits
#    went out of a fresh test-bench clone having run no hooks at all, and CI
#    failed on findings the local run would have caught. Nothing was bypassed:
#    `git clone` just does not install them, and the result is indistinguishable
#    from a clean run.
#
#    Scoped to commit. push is left alone deliberately: pre-push runs the full
#    MegaLinter pass, which is slow enough that blocking on its absence would
#    cost more than it catches, and rule 1 still refuses an explicit
#    --no-verify there.
if matches_verbs "${AT_COMMAND}${WRAPPERS}${GIT}${GIT_OPTIONS}[[:space:]]+commit([[:space:]]|\$)"; then
  command -v git >/dev/null 2>&1 || exit 0

  session_dir="$(printf '%s' "$payload" | jq -r '.cwd // empty' 2>/dev/null)"
  [ -n "$session_dir" ] || session_dir="${CLAUDE_PROJECT_DIR:-$PWD}"

  # Only a `cd` that runs *before* the commit can decide where it lands. Taking
  # the first one anywhere in the string let `git commit -m x && cd /hooked`
  # answer for the wrong directory entirely, which is a refusal turned into a
  # pass (CodeRabbit, PR #40). Newlines are flattened first because they
  # separate commands exactly as `;` does, so a `cd` on a later line is still
  # after the commit.
  flat="$(printf '%s' "$cmd_verbs" | tr '\n' ';')"
  # `#` delimits the expression, not `/`: GIT matches an optional path prefix
  # and so contains a slash of its own, which silently broke `s/.../.../` into
  # an expression sed could not parse, and left this empty.
  before_commit="$(
    printf '%s' "$flat" |
      sed -E "s#${AT_COMMAND}${WRAPPERS}${GIT}${GIT_OPTIONS}[[:space:]]+commit([[:space:]].*)?\$##"
  )"

  # Every directory the commit might run in, not just the likeliest one, and a
  # refusal if any of them is unhooked. Splitting on parentheses means a `cd`
  # inside a subshell is collected too; its effect does not actually outlive the
  # subshell, so the session directory is kept as a candidate alongside it
  # rather than being replaced by it.
  candidates="$(
    printf '%s' "$before_commit" |
      tr ';&|()' '\n\n\n\n\n' |
      sed -nE 's/^[[:space:]]*cd[[:space:]]+([^[:space:]]+).*/\1/p'
  )"
  case "$before_commit" in
  *"("*) candidates="$candidates
$session_dir" ;;
  esac
  [ -n "$candidates" ] || candidates="$session_dir"

  # `git -c core.hooksPath=<dir> commit` applies to that one command, so asking
  # the repository where its hooks live answers about a different directory than
  # the one git is about to use.
  hooks_override="$(
    printf '%s' "$cmd_flags" |
      sed -nE 's/.*core\.hooksPath=([^[:space:]]+).*/\1/p' | head -1
  )"

  while IFS= read -r candidate; do
    [ -n "$candidate" ] || continue
    case "$candidate" in
    /*) ;;
    *) candidate="$session_dir/$candidate" ;;
    esac

    # Not a repository at all: git itself will say so, and refusing here would
    # only replace a clear error with a confusing one.
    git -C "$candidate" rev-parse --git-dir >/dev/null 2>&1 || continue
    toplevel="$(git -C "$candidate" rev-parse --show-toplevel 2>/dev/null)"
    # Only repositories that actually configure pre-commit are held to this.
    # Without the check, every unrelated repository this agent ever commits in
    # would be refused for missing a hook it never wanted.
    [ -n "$toplevel" ] && [ -f "$toplevel/.pre-commit-config.yaml" ] || continue

    if [ -n "$hooks_override" ]; then
      hooks_dir="$hooks_override"
    else
      # --git-path rather than a hardcoded .git/hooks: it resolves core.hooksPath
      # when set, and points a worktree at the parent's hooks directory, which is
      # where a worktree's hooks genuinely live (verified, git 2.55.0).
      hooks_dir="$(git -C "$candidate" rev-parse --git-path hooks 2>/dev/null)"
    fi
    case "$hooks_dir" in
    /*) ;;
    *) hooks_dir="$toplevel/$hooks_dir" ;;
    esac

    if [ ! -x "$hooks_dir/pre-commit" ]; then
      deny "This repository configures pre-commit, but ${hooks_dir}/pre-commit does not exist, so this commit would run no hooks at all and still report success. That is how two commits left an unhooked clone on 2026-08-12 and failed CI on findings the hooks catch, and the same gap would let an unscanned secret through. Run 'pre-commit install' in ${toplevel} first, then repeat this command."
    fi
  done <<EOF
$candidates
EOF
fi

# 2. Working-tree operations against a running stack. podman is queried only
#    once the command already matched, so the common case costs nothing.
if matches_verbs "${AT_COMMAND}${WRAPPERS}${GIT}${GIT_OPTIONS}[[:space:]]+${WORKTREE_VERBS}([[:space:]]|\$)"; then
  command -v podman >/dev/null 2>&1 || exit 0
  # Same precedence the Makefile uses for COMPOSE_PROJECT_NAME, which is
  # `?=` and so takes the environment first, falling back to the directory
  # name. Deriving it from the directory alone means an install that overrides
  # it finds no containers and this guard quietly passes everything.
  root="${CLAUDE_PROJECT_DIR:-$PWD}"
  project="${COMPOSE_PROJECT_NAME:-}"
  if [ -z "$project" ] && [ -f "$root/.env" ]; then
    project="$(sed -n 's/^COMPOSE_PROJECT_NAME=//p' "$root/.env" | head -1 | tr -d '"'"'"'')"
  fi
  [ -n "$project" ] || project="$(basename "$root")"
  running="$(podman ps --filter "label=com.docker.compose.project=${project}" --format '{{.Names}}' 2>/dev/null)"
  if [ -n "$running" ]; then
    deny "The stack is running, so this would rewrite a working tree the containers are actively writing to. pre-commit stashes the tree, and on 2026-07-07 that rewrote tracked runtime files mid-flight and corrupted live SQLite databases. Run 'make stop_all' first, then repeat this command. Do not reach for --no-verify: that skips the secret scanning and is refused separately."
  fi
fi

exit 0
