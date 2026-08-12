"""Tests for .claude/hooks/git-guard.sh, the PreToolUse hook on the Bash tool.

The hook enforces two rules that were prose in CLAUDE.md and got broken anyway:
no skipping the pre-commit hooks, and no working-tree git operations while the
stack is running. Nothing here runs git or touches the real stack; podman is
stubbed on PATH so both stack states are deterministic.

Run explicitly with:
    pytest -m scripts tests/test_git_guard.py
"""

import json
import os
import shutil
import subprocess

import pytest

from conftest import REPO_ROOT

pytestmark = pytest.mark.scripts

GIT_GUARD = REPO_ROOT / ".claude/hooks/git-guard.sh"
SETTINGS = REPO_ROOT / ".claude/settings.json"


def _hook_command():
    settings = json.loads(SETTINGS.read_text())
    entries = [e for e in settings["hooks"]["PreToolUse"] if e["matcher"] == "Bash"]
    assert entries, "no PreToolUse hook on the Bash matcher"
    return entries[0]["hooks"][0]["command"]


@pytest.fixture
def stub_bin(tmp_path):
    """Builds a PATH whose podman reports whichever stack state is asked for."""

    def _build(*, containers_running, with_jq=True):
        binstub = tmp_path / f"bin-{containers_running}-{with_jq}"
        binstub.mkdir(exist_ok=True)
        podman = binstub / "podman"
        podman.write_text(
            "#!/bin/sh\n" + ("echo qbittorrent\n" if containers_running else "exit 0\n")
        )
        podman.chmod(0o755)
        path = f"{binstub}:{os.environ['PATH']}"
        if not with_jq:
            # An isolated PATH with no jq on it at all, rather than a stub that
            # fails: the hook checks availability before it checks parsing. It
            # still needs enough to reach that check and print the refusal.
            for tool in ("bash", "cat"):
                target = shutil.which(tool)
                assert target, f"{tool} not found, cannot build the no-jq PATH"
                link = binstub / tool
                if not link.exists():
                    link.symlink_to(target)
            path = str(binstub)
        return path

    return _build


def _decision(tool_command, path):
    """Returns "allow" or "deny" for a command, plus the refusal reason."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": tool_command}})
    result = subprocess.run(  # noqa: S603 - GIT_GUARD is a path inside this repo
        ["bash", str(GIT_GUARD)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "PATH": path, "CLAUDE_PROJECT_DIR": str(REPO_ROOT)},
    )
    assert result.returncode == 0, "the hook must never fail the tool call"
    if not result.stdout.strip():
        return "allow", ""
    payload = json.loads(result.stdout)["hookSpecificOutput"]
    return payload["permissionDecision"], payload["permissionDecisionReason"]


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def test_settings_json_is_valid():
    """A malformed settings.json silently disables every setting in it."""
    json.loads(SETTINGS.read_text())


def test_settings_json_keeps_its_permission_rules():
    """The hook was merged into a file that already carried allow rules."""
    settings = json.loads(SETTINGS.read_text())
    assert len(settings["permissions"]["allow"]) >= 30


def test_hook_script_exists_and_is_executable():
    """settings.json refers to it by path, so a missing or non-executable file
    means the hook silently never fires."""
    assert GIT_GUARD.is_file(), f"{GIT_GUARD} does not exist"
    assert os.access(GIT_GUARD, os.X_OK), f"{GIT_GUARD} is not executable"
    assert "git-guard.sh" in _hook_command()


def test_hook_derives_the_project_name_rather_than_hardcoding_it():
    """A clone under a different directory name has a different Compose
    project label, and a hardcoded one would find no containers and allow
    everything. storage-mount.sh derives it the same way."""
    source = GIT_GUARD.read_text()
    assert "CLAUDE_PROJECT_DIR" in source
    assert "docker-torrent-box-with-vpn" not in source


# ---------------------------------------------------------------------------
# Rule 1: never skip the pre-commit hooks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bypass",
    [
        "git commit --no-verify -m x",
        "git commit -n -m x",
        "git commit -m x --no-verify",
        "git push --no-verify",
        "git push origin main --no-verify",
        "cd /tmp && git commit --no-verify -m x",
        "true; git push --no-verify",
        # Global options before the subcommand.
        "git -C . commit --no-verify",
        "git -C /repo push --no-verify",
        "git -c user.email=x commit --no-verify -m y",
        # Quoting the flag still passes it to git.
        'git commit "--no-verify" -m x',
        "git commit '--no-verify' -m x",
        # Scoping the flag to the command's own arguments must not open a way
        # through by parking a heredoc after it.
        "git commit --no-verify -F - <<MSG\nbody\nMSG",
    ],
)
def test_blocks_skipping_the_pre_commit_hooks(bypass, stub_bin):
    """The secret scanners run as pre-commit hooks.

    A bypassed commit is an unscanned commit, and this repository is public, so
    that is how a credential gets published. Refused whether or not the stack
    is running: the risk is the missing scan, not the stash.
    """
    decision, _ = _decision(bypass, stub_bin(containers_running=False))
    assert decision == "deny", f"{bypass!r} was not blocked"


def test_bypass_refusal_explains_the_supported_path(stub_bin):
    """A refusal that does not say what to do instead invites working around
    it, which is how --no-verify got used in the first place."""
    _, reason = _decision(
        "git commit --no-verify -m x", stub_bin(containers_running=False)
    )
    assert "make stop_all" in reason
    assert "secret" in reason.lower()


@pytest.mark.parametrize(
    "allowed",
    [
        "git commit -m x",
        "git push",
        "git push -n",  # -n on push is --dry-run, which is harmless
        "git push --dry-run",
        "git status",
        "git log --oneline -5",
        "git diff",
        "git log -n 5",
        # Quoted spans naming the flag are data. This hook refused the very
        # commit that introduced it, because the message explained the rule.
        'git commit -m "do not use --no-verify here"',
        "git commit -m 'refuse -n and --no-verify'",
        "echo 'git commit --no-verify'",
        'echo "--no-verify"',
        # A heredoc body is data too, and is not a quoted span, so the flag had
        # to be scoped to that git command's own arguments. This refused the
        # introducing commit a second time, via its message.
        "git commit -F - <<MSG\nA bare -n on push is allowed\nabout --no-verify\nMSG",
        # -n here belongs to grep, on the far side of a pipe.
        "git commit -F - | grep -n foo",
    ],
)
def test_allows_verified_git_with_the_stack_stopped(allowed, stub_bin):
    decision, _ = _decision(allowed, stub_bin(containers_running=False))
    assert decision == "allow", f"{allowed!r} was blocked"


# ---------------------------------------------------------------------------
# Rule 2: no working-tree rewrites against a running stack
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "subcommand",
    [
        "stash -u",
        "commit -m x",
        "checkout main",
        "switch -c topic",
        # Everything below rewrites tracked files at least as thoroughly as the
        # stash that caused the original corruption, and all of it was allowed
        # until CodeRabbit pointed it out on PR #38.
        "restore .",
        "reset --hard",
        "revert abc123",
        "merge main",
        "rebase main",
        "cherry-pick abc123",
        "am patch.mbox",
        "apply patch.diff",
        "clean -fdx",
        "mv a b",
        "rm -r x",
        "pull",
    ],
)
def test_blocks_working_tree_rewrites_while_the_stack_runs(subcommand, stub_bin):
    """pre-commit's stash cycle rewrote tracked runtime files mid-flight and
    corrupted live SQLite databases. CLAUDE.md warned about it and the warning
    was not enough, so this is enforced."""
    decision, _ = _decision(f"git {subcommand}", stub_bin(containers_running=True))
    assert decision == "deny", f"git {subcommand} was not blocked"


@pytest.mark.parametrize(
    "invocation",
    [
        "git -C . stash",
        "git -C /repo restore .",
        "git --no-pager reset --hard",
        "git -c core.editor=true commit -m x",
        "cd /tmp && git -C . checkout main",
    ],
)
def test_global_options_do_not_bypass_the_stack_guard(invocation, stub_bin):
    """git accepts its own options before the subcommand, so `git -C /repo
    stash` is a stash and has to be caught as one."""
    decision, _ = _decision(invocation, stub_bin(containers_running=True))
    assert decision == "deny", f"{invocation!r} was not blocked"


@pytest.mark.parametrize(
    "readonly",
    ["git status", "git log --oneline -5", "git diff", "git show HEAD", "git push"],
)
def test_allows_read_only_git_while_the_stack_runs(readonly, stub_bin):
    """Reading history mutates nothing and must stay available."""
    decision, _ = _decision(readonly, stub_bin(containers_running=True))
    assert decision == "allow", f"{readonly!r} was blocked"


@pytest.mark.parametrize(
    "benign",
    [
        "echo 'git commit'",
        "grep -r 'git stash' docs/",
        # The unquoted cases are the ones that exercise the anchoring. A
        # mention ending in a quote is rejected by the trailing
        # ([[:space:]]|$) whatever the anchor does, so quoted cases alone pass
        # even with the anchor removed. Mutation testing surfaced that.
        "echo git commit -n",
        "echo git stash here",
        "printf '%s' git checkout main",
        "ls -la",
        "cat README.md",
    ],
)
def test_ignores_commands_that_merely_mention_git(benign, stub_bin):
    """The first version of this hook matched substrings and blocked its own
    test command."""
    decision, _ = _decision(benign, stub_bin(containers_running=True))
    assert decision == "allow", f"{benign!r} was blocked"


def test_allows_working_tree_rewrites_once_the_stack_is_stopped(stub_bin):
    """The rule is about live containers, not about the commands themselves."""
    path = stub_bin(containers_running=False)
    for subcommand in ("stash -u", "restore .", "reset --hard", "commit -m x"):
        decision, _ = _decision(f"git {subcommand}", path)
        assert decision == "allow", f"git {subcommand} was blocked with no stack"


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_fails_closed_when_the_payload_cannot_be_parsed():
    """A hook that allows everything the moment something goes wrong is worse
    than no hook, because it still reads as protection."""
    result = subprocess.run(  # noqa: S603 - GIT_GUARD is a path inside this repo
        ["bash", str(GIT_GUARD)],
        input="not-json",
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(REPO_ROOT)},
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == (
        "deny"
    )


def test_fails_closed_when_jq_is_unavailable(stub_bin):
    """Without jq the hook cannot read the command at all."""
    decision, reason = _decision(
        "ls -la", stub_bin(containers_running=False, with_jq=False)
    )
    assert decision == "deny"
    assert "jq" in reason


def test_consults_podman_only_after_the_command_matches(stub_bin):
    """A command that is not a git working-tree operation must not depend on
    podman at all, so the common case costs nothing and cannot misfire."""
    decision, _ = _decision("ls -la", stub_bin(containers_running=True))
    assert decision == "allow"


def test_never_fails_the_tool_call(stub_bin):
    """Any non-zero exit from a PreToolUse hook is itself disruptive."""
    path = stub_bin(containers_running=True)
    for command in ("git stash", "ls -la", "git commit --no-verify -m x"):
        decision, _ = _decision(command, path)
        assert decision in ("allow", "deny")


# ---------------------------------------------------------------------------
# Telling commands apart from text that reads like one
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "readonly_stash",
    ["git stash list", "git stash show", "git stash show -p", "git -C . stash list"],
)
def test_allows_read_only_stash_subcommands(readonly_stash, stub_bin):
    """These only read. Blocking them was a live false positive: inspecting
    the stash list while the stack ran got refused."""
    decision, _ = _decision(readonly_stash, stub_bin(containers_running=True))
    assert decision == "allow", f"{readonly_stash!r} was blocked"


def test_read_only_stash_does_not_exempt_the_rest_of_the_line(stub_bin):
    """Written as "unless the command mentions stash list", this exemption
    would have let the reset through with it."""
    decision, _ = _decision(
        "git stash list; git reset --hard", stub_bin(containers_running=True)
    )
    assert decision == "deny"


@pytest.mark.parametrize(
    "quoted",
    [
        "echo 'git stash list; git reset --hard'",
        'echo "git reset --hard"',
        "grep -r 'git clean -fdx' docs/",
    ],
)
def test_quoted_text_that_reads_like_a_command_is_not_one(quoted, stub_bin):
    """Rule 2 removes whole quoted spans rather than just the quote
    characters. Sharing rule 1's normalization here, which strips the
    characters so that git commit "--no-verify" is still caught, made these
    test-case strings look like real commands."""
    decision, _ = _decision(quoted, stub_bin(containers_running=True))
    assert decision == "allow", f"{quoted!r} was blocked"


def test_heredoc_bodies_are_data(stub_bin):
    """A heredoc body runs across lines and each line can look exactly like a
    command, so writing a test case or a commit message in one was reading as
    the command it described."""
    decision, _ = _decision(
        "cat > f <<PYEOF\ngit stash list; git reset --hard\nPYEOF",
        stub_bin(containers_running=True),
    )
    assert decision == "allow"


def test_a_command_after_a_heredoc_still_counts(stub_bin):
    """Skipping to the terminator, not to the end of the command."""
    decision, _ = _decision(
        "cat > f <<PYEOF\nharmless\nPYEOF\ngit reset --hard",
        stub_bin(containers_running=True),
    )
    assert decision == "deny"
