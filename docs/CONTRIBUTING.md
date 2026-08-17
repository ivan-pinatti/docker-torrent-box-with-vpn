# Contributing

I would love your inputs and ideas! My goal is to make contributing to this
project as easy and transparent as possible, whether it's:

- Reporting a bug
- Discussing the current state of the code
- Submitting a fix
- Proposing new features
- Becoming a maintainer

## Github Rocks

Everything is hosted in Github, issue tracking, feature requests, as well as accept pull requests.

## Github Flow

This project uses [Github Flow](https://guides.github.com/introduction/flow/index.html),
so all code changes happen through pull requests.

Pull requests are the best way to propose changes to the codebase. I actively
welcome your pull requests.

### The short version

| Stage | What runs | What you do |
| --- | --- | --- |
| Open as a **draft** | `Code Check` (the pre-commit hooks) | Fix whatever it reports |
| **Mark ready for review** | CodeRabbit reviews (it skips drafts) | Address its comments, pushing fixes |
| Comment **`/run-tests`** | The integration suite, against your PR | Wait for it to go green |
| Merge | | |

Checks run in this order on purpose, so a cheap failure is never paid for
twice and the expensive one is spent only on the version being merged. The
integration suite stands the whole stack up and takes upward of twelve
minutes; it never runs on a push. Only a maintainer can ask for it. The
required `Tests Verified` check is absent on a head no run has covered, which
reads as waiting and blocks the merge, `pending` while a run is under way, and
`success` or `failure` once it ends, so nothing merges untested.

Pull requests from forks are tested exactly the same way. You cannot start the
suite yourself, so say in the pull request when your change has settled and a
maintainer will comment for you.

### The detail

1. Fork the repo and create your branch from `main`.
2. If you don't have it yet, please install pre-commit. More info:
   <https://pre-commit.com/>
3. After pre-commit is installed, add the hooks by running `pre-commit install`.
   Do this in every clone, including throwaway ones. `git clone` does not carry
   the hooks over, and a commit made without them runs no checks at all while
   still reporting success, so nothing tells you they were missing until CI
   fails on something the hooks catch locally.
4. The hooks are split across two stages. `pre-commit` runs the fast,
   file-scoped ones against what you changed, including shellcheck, shfmt,
   ruff, yamllint, markdownlint, actionlint, hadolint and cspell. `pre-push`
   adds the four that walk the whole repository rather than a list of files:
   the full-history secret scan, checkov, trivy, and the documentation link
   check.
   `pre-push` also sweeps the fast hooks across every file, which is the scope
   CI uses. Without that sweep a violation in a file your branch never touched
   passes locally and fails in CI, which is what a linter version bump
   produces.
5. Pull requests run the same checks in GitHub Actions, so they are enforced
   even if local hooks are not installed.
6. Use `make sanity_fast` for the normal local check path and `make sanity_full`
   for the full repository check path.
7. Checks run in order rather than all at once, so a cheap failure is not paid
   for twice, and the review flow is:

   1. **Open the pull request as a draft.** `Code Check` runs the hooks over
      every file in one `--hook-stage pre-push` sweep, which selects the
      pre-push hooks and the ordinary ones together. CodeRabbit skips drafts.
   2. **Mark it ready for review once it is green.** That is what starts
      CodeRabbit, so it reviews an already-clean diff once, rather than
      re-reviewing after every formatting fix.
   3. **Address the review, pushing fixes as needed.** Each push re-runs the
      lint gate, and CodeRabbit re-reviews.
   4. **Comment `/run-tests` once the review is settled.** The suite never runs
      on a push. It stands the whole stack up and takes upward of twelve
      minutes, so it is worth spending once, on the version you intend to
      merge.

      The run publishes its result as a commit status on the exact commit it
      tested. Push again and that status no longer applies to the new head, so
      the required check goes back to waiting; comment again when you are ready
      to spend another run.

   The required `Tests Verified` check is a commit status the suite publishes
   against the head SHA it ran on, not a job. Its full lifecycle: absent on a
   head no run has covered, `pending` from the moment a run is authorized, then
   `success` or `failure` when the suite ends. A pull request that changes
   nothing but prose gets `success` published for it by the docs-only waiver
   instead, without a run.

   The absent state is the load-bearing one, and it is deliberate. GitHub
   reports it as waiting, which blocks the merge, where a job gated on a
   condition would be *skipped* instead, and branch protection counts a skipped
   job as successful, which would let an untested pull request merge.

   `/run-check` re-runs the two lint layers the same way. `/run-tests` is
   restricted to the maintainer list in
   `.github/workflows/integration-tests.yml`, and `/run-check`, which costs a
   couple of lint runs rather than a whole stack, to repository collaborators.
8. Dependency updates are the one exception to all of the above, and they merge
   without anyone reviewing them. Dependabot opens weekly pull requests for
   `.pre-commit-config.yaml` hook revs, GitHub Action versions and
   `tests/requirements.txt`; Renovate opens them for the image versions pinned in
   `.env.example` and the pins annotated inline in workflows and pre-commit hooks.
   Patch, minor and digest updates then take this path, while a major bump gets
   no approval and waits for the maintainer:

   1. The suite starts itself. `integration-tests.yml` carries a
      `pull_request_target` trigger that authorizes `renovate[bot]` and
      `dependabot[bot]` on a branch in this repository, so `Tests Verified` is
      published without anyone commenting `/run-tests`. Nothing else changes
      about the suite: for every other pull request, forks included, it still
      only runs when a maintainer asks.
   2. `bot-auto-merge.yml` supplies the approving review branch protection
      requires, but only after `scripts/assert-pin-only-diff.py` confirms the
      diff changes nothing but a version or a digest in a pin position, in one
      of four allowed files. A number that is not a pin does not count, so a
      `PUID` or a timeout moving is refused just as an added line would be. A
      bump that reaches anything else waits, which is what should happen when a
      dependency bot steps outside its lane.
   3. CodeRabbit reviews it as the reader nobody else provides. Its comments
      land as unresolved conversations, which branch protection will not let
      past, and neither bot ever resolves a thread, so anything it objects to
      waits for the maintainer. It has nothing to say about a pure digest bump,
      which is a real limit rather than an oversight; see
      [docs/HARDENING.md](HARDENING.md) for what covers that instead.
   4. GitHub merges it once every required check is green. Renovate arms
      auto-merge itself when it opens the pull request; the workflow does it on
      the Dependabot path, which cannot.

   Two coupled settings make this work, and both need writing down because
   neither is visible in the repository:

   - **`main` does not require a code owner review.** CODEOWNERS accepts only
     users and teams, so no bot can ever satisfy such a rule, and a dependency
     bump could not merge without a person or a stored credential belonging to
     one. Turning it off cost nothing, because an approving review only counts
     from an account with write access and this repository has exactly one, so
     the rule was excluding the bot and nobody else. **If a second write
     collaborator is ever added that stops being true**, and the choice is then
     between giving new collaborators Triage rather than Write, or restoring the
     rule and moving the review requirement into a ruleset with the bots in its
     bypass list.
   - **A required approval is still required.** It comes from
     `github-actions[bot]`, which is why "Allow GitHub Actions to create and
     approve pull requests" is enabled. For a contributor's pull request nothing
     has changed: their own approvals do not count, so the maintainer's review is
     still what unblocks it.
9. Adhere to the commit message guidelines as this repository uses
   [semantic versioning](https://semver.org/). More info:
   <https://github.com/mathieudutour/github-tag-action#bumping>
10. The repository has a pytest suite under `tests/` covering container health,
   security hardening, credential rotation, app-to-app wiring, and VPN
   killswitch behavior. `make test` runs it against a running stack (needs
   `make bootstrap` first); `make test_extended` adds the slower
   `rinse_and_repeat` lifecycle tests on top; `make test_prerequisites` runs
   just the pre-flight checks with no containers needed at all; and
   `make bootstrap_tests` does a full clean bootstrap and runs
   `test_extended` in one step (only against a disposable clone, it
   rewrites every credential). See [docs/TESTING.md](TESTING.md) for the
   marker/tier breakdown and how to add a test, and
   [docs/MAKE_COMMANDS.md](MAKE_COMMANDS.md) for the full list of test
   targets. Pull requests do not run the suite on their own: a maintainer
   comments `/run-tests`, which runs it in
   `.github/workflows/integration-tests.yml`. `/run-check` re-runs the lint
   layers (see `.github/workflows/comment-dispatch.yml`). Still test manually
   for anything the suite doesn't cover.
11. Update the documentation accordingly
12. Issue the pull request!

## Any contributions you make will be under the Apache License 2.0

In short, when you submit code changes, your submissions are understood to be
under the same [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)
that covers the project. Feel free to contact the maintainers if that's a
concern.

## Report bugs using Github's [issues](https://github.com/briandk/transcriptase-atom/issues)

I use GitHub issues to track public bugs. Report a bug by
[opening a new issue](https://github.com/ivan-pinatti/docker-torrent-box-with-vpn/issues/new);
it's that easy!

## Write bug reports with detail, background, and sample code

[This is an example](http://stackoverflow.com/q/12488905/180626) of a bug
report I wrote, and I think it's not a bad model. Here's
[another example from Craig Hockenberry](http://www.openradar.me/11905408), an
app developer whom I greatly respect.

## Use a Consistent Coding Style

The repository is already using some tools to help with that. Make sure you are
running the pre-commit hooks, including the pre-push stage, before sending
changes upstream.

- 2 spaces for indentation rather than tabs
- Use `make sanity_fast` for the normal local validation path
- Use `make sanity_full` before pushing. The pre-commit gitleaks hook only sees
  the staged diff, while the pre-push pass scans the full git history. See
  docs/HARDENING.md
- Use `make sanity_full` when you need the full repository security/IaC pass
- Security scanner findings are also published to the repository's Security tab
  by the `Security Reports` job, which reports rather than gates. See
  docs/HARDENING.md
- Dependabot and Renovate handle weekly dependency bump PRs, and patch, minor and
  digest updates merge unattended once the suite passes; major updates are left
  for manual review. See step 8 above for the whole path and what gates it

## Scripts

Helper scripts live in a flat `scripts/` directory (no subfolders) and follow
these conventions:

- Kebab-case, verb-first names: `rotate-api-keys.sh`, `prune-nginx-cache.sh`,
  `seed-secrets.sh`.
- `.sh` for shell and `.py` for Python. Shell scripts use
  `#!/usr/bin/env bash` with `set -euo pipefail`, or `#!/bin/sh` with
  `set -eu` when no bash features are needed.
- Scripts resolve the repository root from their own location and `cd` there,
  so they work from any directory.
- Each user-facing script has a Makefile wrapper whose target name is the
  snake_case mirror of the script name, for example `rotate_nginx_logs` runs
  `scripts/rotate-nginx-logs.sh`.
- Never commit live application state. Runtime databases and configs the app
  rewrites on shutdown stay gitignored; commit a sanitized `<file>.example`
  seed instead. See docs/HARDENING.md.
- Never hardcode secrets. Secret values are written only to gitignored files
  (`.env.secrets`, `certs/cert.conf`), secrets printed to the terminal are
  masked, and lines that trip secret scanners on variable names carry a
  `# pragma: allowlist secret` comment.

## License

By contributing, you agree that your contributions will be licensed under its Apache License 2.0.

## References

This document was adapted from the Github Gist <https://gist.github.com/briandk/3d2e8b3ec8daf5a27a62>

---

See also: [README.md](../README.md), [docs/MAKE_COMMANDS.md](MAKE_COMMANDS.md),
[docs/TESTING.md](TESTING.md)
