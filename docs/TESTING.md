# Testing

The pytest suite under `tests/` covers container health, security hardening,
credential rotation, app-to-app wiring, and VPN killswitch behavior. See
[docs/CONTRIBUTING.md](CONTRIBUTING.md) for how it fits into pre-commit, CI,
and pull requests; this page covers the suite itself.

## Markers and tiers

Every test carries a marker registered in `pytest.ini`, and `make test` runs
them in three passes instead of one invocation:

1. Everything **not** marked `rotation`, `pw_rotation`, `wiring`, `killswitch`,
   or `rinse_and_repeat`, in parallel (`pytest-xdist`, `-n auto`). This is
   the bulk of the suite: container health, connectivity, TLS, auth,
   security hardening, observability, and so on, all read-only or
   self-contained.
2. `rotation_isolated`, in parallel (`-n 4`). A subset of the arr-app
   rotation cases that only ever touch their own container and their own
   Prowlarr Application row, safe to run concurrently with itself.
3. Everything else marked `rotation`, `pw_rotation`, `wiring`, or
   `killswitch` (excluding what tier 2 already covered), serially. These
   touch shared state (Prowlarr's Applications list, Homepage's restart,
   LazyLibrarian's Torznab entries) and can't safely run in parallel with
   each other.

`make test_ci` runs tiers 1 and 2 only, no tier 3: the serial rotation/
wiring/killswitch tier needs a real app restart to complete and report
healthy within its own wait budget, over and over, for dozens of apps in a
row, and that isn't reliable on a GitHub-hosted runner's shared, more
constrained resources, confirmed live. This is what `pull-request-validation.yml`'s
own integration job actually runs; it is not a substitute for `make test`
or `make bootstrap_tests` and should not be reached for outside CI.

That suite does not run on a push. It stands the whole stack up and takes
upward of twelve minutes, so a code owner asks for it by commenting
`/run-tests` on the pull request once the change has settled.

The run happens in the workflow that comment triggers
(`.github/workflows/integration-tests.yml`), rather than starting another one,
and publishes its result as a commit status on the pull request's head SHA.
Two earlier designs failed on exactly that point: a `workflow_dispatch` run is
dispatched off `main`, so its check lands on `main`'s head commit while a
required check is judged against the pull request's, and a label applied by a
workflow does nothing at all, because GitHub suppresses runs from events its
own token creates.

The required `Tests Verified` check is therefore a status the suite writes, not
a job. Until a run has passed on the current head it is absent, which reads as
waiting and blocks the merge. A job gated on a condition would be *skipped*
instead, and branch protection counts a skipped job as successful, which is the
trap this shape avoids.

The exception is a pull request that changes nothing but prose: when the `code`
paths filter reports no runtime files touched, `docs_only_waiver` publishes a
passing status for the same context, since prose cannot break an integration
test. It only ever publishes success, and only on a positive answer from the
filter, so anything unclear leaves the check waiting.

An `issue_comment` workflow always runs the default branch's copy of itself, so
a pull request cannot alter the checks that gate it. The code under test is
checked out explicitly from the merge ref.

`make test_extended` runs `make test` plus a fourth pass: `rinse_and_repeat`
(stop/start and down/start lifecycle cycles), the single most expensive
marker by far and the only one that exercises the whole stack's startup
path rather than one credential or connection. It's kept out of the default
`make test` so day-to-day runs stay fast; run it deliberately before a
release.

`make test_prerequisites` runs only the `prerequisites` marker (pre-flight
checks, no containers needed at all). `make test_no_rotate_passwords` runs
everything except `pw_rotation`, useful when iterating on something
unrelated to password rotation without paying for its slowest tier.

`PYTEST_ARGS="..."` appends extra arguments to whichever pytest invocations
a target runs. Note `make test`/`test_extended` are multiple separate
pytest calls, each with its own `-m` marker filter, and pytest's `-m` is
single-value: passing `PYTEST_ARGS="-m security"` to those targets
overrides each pass's own filter rather than combining with it. Invoke
`tests/.venv/bin/pytest -m security` directly instead when you want just
one marker.

## Full test coverage: `make bootstrap_tests`

`.env.example` ships several profiles disabled by default (an optional
observability stack, a couple of alternate/legacy apps), so a normal
bootstrap never exercises their code paths. `make bootstrap_tests` enables
every profile that has real pytest coverage, bootstraps from scratch, and
runs `test_extended`, including a local, credential-free WireGuard endpoint
(see [docs/VPN_MOCK.md](VPN_MOCK.md)) so qBittorrent, SABnzbd, and
everything wired through them can start and get exercised without a real
VPN provider account:

```shell
make bootstrap_tests
```

The profile overrides it applies come from `.env.tests`, merged onto `.env`
by `scripts/enable-test-profiles.sh`: for each `KEY=value` line in
`.env.tests`, it replaces that key's value in `.env` if the key already
exists there, or appends the line if it doesn't. `.env.tests` itself only
lists the lines that need to differ from `.env.example`'s own defaults.

**Run this only against a disposable clone, never a real deployment.** It
changes which profiles are enabled in `.env` and rewrites every credential,
exactly like plain `make bootstrap` already does. This is the
release-validation command: a clean `make bootstrap_tests` run with 0
failures is the bar every change in this repo is held to before release.

## Adding a test

Register a new marker in `pytest.ini` before using it (an unregistered
marker fails collection under `--strict-markers`-style configs and is easy
to typo). Prefer extending an existing test file's parametrization over
adding a new file when the new case is another instance of an existing
pattern (another app rotating, another indexer wiring); see
`tests/conftest.py` for the shared fixtures (`docker_client`,
`running_containers`, `skip_if_not_running_fresh`, `SERVICES`, and so on)
before writing your own container/HTTP helpers.

---

See also: [README.md](../README.md), [docs/MAKE_COMMANDS.md](MAKE_COMMANDS.md),
[docs/CONTRIBUTING.md](CONTRIBUTING.md)
