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
| Open as a **draft** | `Code Check` (pre-commit), then `MegaLinter` if it passes | Fix whatever they report |
| **Mark ready for review** | CodeRabbit reviews (it skips drafts) | Address its comments, pushing fixes |
| Comment **`/run-tests`** | The integration suite, against your PR | Wait for it to go green |
| Merge | | |

Checks run in this order on purpose, so a cheap failure is never paid for
twice and the expensive one is spent only on the version being merged. The
integration suite stands the whole stack up and takes upward of twelve
minutes; it never runs on a push. Only repository collaborators can ask for
it, and the required `Tests Verified` check stays red until it
has passed on the current head commit, so nothing merges untested.

If you are contributing from a fork you cannot start the suite yourself. Say so
in the pull request and a maintainer will run it once the review has settled.

### The detail

1. Fork the repo and create your branch from `main`.
2. If you don't have it yet, please install pre-commit. More info:
   <https://pre-commit.com/>
3. After pre-commit is installed, add the hooks by running `pre-commit install`.
   Do this in every clone, including throwaway ones. `git clone` does not carry
   the hooks over, and a commit made without them runs no checks at all while
   still reporting success, so nothing tells you they were missing until CI
   fails on something the hooks catch locally.
4. MegaLinter runs incrementally at `pre-commit` and as a broader gate at
   `pre-push`, while the focused hooks still run directly in `pre-commit`. CI
   uses its `cupcake` flavor, a 2.64 GB download rather than the default
   image's 4.77 GB, which carries every linter this repository enables. The one
   it does not carry, bandit, is a pre-commit hook instead.
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

   1. **Open the pull request as a draft.** `Code Check` (pre-commit) runs
      first and `MegaLinter` only once that passes. CodeRabbit skips drafts.
   2. **Mark it ready for review once both are green.** That is what starts
      CodeRabbit, so it reviews an already-clean diff once, rather than
      re-reviewing after every formatting fix.
   3. **Address the review, pushing fixes as needed.** Each push re-runs the
      two lint layers, and CodeRabbit re-reviews.
   4. **Comment `/run-tests` once the review is settled.** The suite never runs
      on a push. It stands the whole stack up and takes upward of twelve
      minutes, so it is worth spending once, on the version you intend to
      merge.

      The run publishes its result as a commit status on the exact commit it
      tested. Push again and that status no longer applies to the new head, so
      the required check goes back to waiting; comment again when you are ready
      to spend another run.

   The required `Tests Verified` check is a commit status the suite publishes
   against the head SHA it ran on, not a job. Until a run has passed on the
   current head it is simply absent, which GitHub reports as waiting and which
   blocks the merge. That is deliberate: a job gated on a condition would be
   *skipped* instead, and branch protection counts a skipped job as
   successful, which would let an untested pull request merge.

   `/run-check` re-runs the two lint layers the same way. Both comments are
   restricted to repository collaborators.
8. Dependabot opens weekly pull requests for `.pre-commit-config.yaml` hook revs
   and GitHub Action version bumps. Eligible patch and minor updates are
   approved and marked for auto-merge once the required checks pass.
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
running the pre-commit hooks and allowing MegaLinter to run both locally and in
pull requests before sending changes upstream.

- 2 spaces for indentation rather than tabs
- Use `make sanity_fast` for the normal local validation path
- Use `make sanity_full` before pushing. The pre-commit gitleaks hook only sees
  the staged diff; MegaLinter's betterleaks pass scans commits, narrowed to the
  pull request's own commits when running on a PR. See docs/HARDENING.md
- Use `make sanity_full` when you need the full repository security/IaC pass
- Dependabot handles weekly hook and workflow version bump PRs; major updates
  are left for manual review

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
