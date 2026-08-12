#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2022 Ivan Pinatti
#
# Claude Code PreToolUse hook for the Bash tool. Reads the hook payload on
# stdin and refuses two classes of git command. Printing nothing allows the
# command, so every path that is not an explicit refusal must fall through to
# the exit 0 at the bottom.
#
# Enforces two rules that were previously prose in CLAUDE.md and were broken
# anyway:
#
#   1. No skipping the pre-commit hooks. They run the secret scanners, and a
#      bypass is how an unscanned change reaches a public repository.
#   2. No working-tree git operations while the stack is running. pre-commit
#      stashes the working tree, and doing that against live SQLite databases
#      corrupted them on 2026-07-07.
set -uo pipefail

payload="$(cat)"
command -v jq >/dev/null 2>&1 || exit 0
cmd="$(printf '%s' "$payload" | jq -r '.tool_input.command // ""' 2>/dev/null)" || exit 0
[ -n "$cmd" ] || exit 0

# Matches only where a command actually starts: beginning of the string, or
# after a separator. Without this the hook matches any mention of the word,
# including one inside a string, and the first version of it blocked its own
# test command that way.
AT_COMMAND='(^|[;&|(]|&&|\|\|)[[:space:]]*'

# Quoted spans are data, not syntax: a commit message is free to talk about
# --no-verify, and matching that as though it were the flag blocks writing
# about the rule at all. This hook refused its own commit that way. Stripping
# the spans first also means a mention inside 'quotes' can never look like a
# command, which the anchoring above handles only for unquoted text.
cmd_syntax="$(printf '%s' "$cmd" | sed -E "s/'[^']*'//g; s/\"[^\"]*\"//g")"

matches() { printf '%s' "$cmd_syntax" | grep -qE "$1"; }

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
ARGS_UP_TO='([^;&|]*[[:space:]])?'

if matches "${AT_COMMAND}git[[:space:]]+commit[[:space:]]${ARGS_UP_TO}(--no-verify|-n)([[:space:]]|\$)"; then
  deny "git commit --no-verify is not allowed in this repository. It skips the pre-commit hooks, which is where the secret scanning runs, so a bypassed commit can publish credentials to a public repo. If pre-commit is failing, fix what it reports. If it is blocked because the stack is running, stop the stack (make stop_all) and commit normally: that is the supported path, and pre-commit's stash cycle is only dangerous against live databases."
fi

if matches "${AT_COMMAND}git[[:space:]]+push[[:space:]]${ARGS_UP_TO}--no-verify([[:space:]]|\$)"; then
  deny "git push --no-verify is not allowed in this repository. It skips the pre-push hooks, which run the full MegaLinter pass including the secret scanners."
fi

# 2. Working-tree operations against a running stack. podman is queried only
#    once the command already matched, so the common case costs nothing.
if matches "${AT_COMMAND}git[[:space:]]+(stash|commit|checkout|switch)([[:space:]]|\$)"; then
  command -v podman >/dev/null 2>&1 || exit 0
  project="$(basename "${CLAUDE_PROJECT_DIR:-$PWD}")"
  running="$(podman ps --filter "label=com.docker.compose.project=${project}" --format '{{.Names}}' 2>/dev/null)"
  if [ -n "$running" ]; then
    deny "The stack is running, so this would operate on a working tree the containers are actively writing to. pre-commit stashes the tree, and on 2026-07-07 that rewrote tracked runtime files mid-flight and corrupted live SQLite databases. Run 'make stop_all' first, then repeat this command. Do not reach for --no-verify: that skips the secret scanning and is refused separately."
  fi
fi

exit 0
