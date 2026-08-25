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
constrained resources, confirmed live. This is what `integration-tests.yml`'s
own suite job actually runs; it is not a substitute for `make test`
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

The required `Tests Verified` check is therefore a status the workflow
publishes, not a job. It is absent on a head no run has covered, which reads as
waiting and blocks the merge; `pending` from the moment a run is authorized;
and `success` or `failure` once the suite ends. A job gated on a condition
would be *skipped* instead, and branch protection counts a skipped job as
successful, which is the trap this shape avoids.

The exception is a pull request that changes nothing but prose: when the `code`
paths filter reports no runtime files touched, `docs_only_waiver` publishes a
passing status for the same context, since prose cannot break an integration
test. It only ever publishes success, and only on a positive answer from the
filter, so anything unclear leaves the check waiting.

An `issue_comment` workflow always runs the default branch's copy of itself, so
a pull request cannot alter the checks that gate it. The code under test is
checked out explicitly from the merge ref.

That matters more here than under the `pull_request` trigger this replaced,
because a comment triggered workflow holds the full secret set and a write
token where a fork's `pull_request` run holds neither. So the workflow is three
jobs, and the split is the boundary: `gate` decides who may ask and writes the
pending status, `suite` checks the pull request's code out and runs it with a
read-only token, and `publish` writes the result. Only `gate` and `publish` can
write a status, and neither ever sees the code. A secret reaches `suite` only
when the head branch lives in this repository, which takes write access to push
to, and the only secret left there is the Docker Hub login: a fork pulls
anonymously with a retry instead.

The VPN is the credential-free mock (see [docs/VPN_MOCK.md](VPN_MOCK.md)) on
every run, fork or not. There is no real provider credential in CI and there is
not meant to be one. Nothing is lost by that: `make test_ci` excludes the
`killswitch` tier, which is the only one that exercises a real VPN credential.

CI also runs an older podman than a bench does, on purpose, and this is the one
place the two deliberately differ. The `ubuntu-latest` image ships a podman
built without systemd support, and such a build cannot schedule container
healthchecks: every container stays `starting` indefinitely, nothing satisfies
`depends_on: condition: service_healthy`, and the stack never finishes starting.
The distributions build podman with systemd support, so a bench on 5.x is
unaffected and needs no pinning; CI installs the Ubuntu archive's 4.x instead.
Do not "fix" this by matching CI to your bench's version, and do not pin your
bench to CI's. What the suite exercises is the compose files, scripts, wiring
and tests, none of which are podman-version-specific, and
`make bootstrap_tests` on a real bench remains the release gate for the runtime
actually in use.

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

That marker also carries the static checks, the ones that read files rather
than a running stack, which is why the `Prerequisite Checks` job can run them
on every pull request without standing anything up.
`tests/test_prerequisites.py` holds the pre-flight system requirements and the
repo hygiene checks (live databases stay untracked, every seeded config has a
committed `.example`). `tests/test_renovate_pins.py` holds the dependency pin
checks: every image version variable a compose file interpolates carries a
`# renovate:` annotation unless the tag deliberately floats, every annotated
pin carries a digest unless it cannot hold one, that annotation names the image
the compose file actually pulls, the `customManagers` regex in
`.github/renovate.json5` captures every annotation in `.env.example`, and
every `matchPackageNames` entry names a package some annotation declares, and
every service running a file bind mounted out of `patches/` has its image held
at a fixed version. Twelve pins once sat there unannotated and froze, and one
rule matched none of the five images it listed; neither state breaks anything
at runtime, so nothing but a static check can catch either. Its exemptions are explicit
tables in the module (`FLOATING`, `NO_DIGEST`, `NO_SERVICE`) and a stale entry
in one fails rather than quietly covering nothing. See
[docs/DEPENDENCY_UPDATES.md](DEPENDENCY_UPDATES.md) for what the two bots own.

`PYTEST_ARGS="..."` appends extra arguments to whichever pytest invocations
a target runs. Note `make test`/`test_extended` are multiple separate
pytest calls, each with its own `-m` marker filter, and pytest's `-m` is
single-value: passing `PYTEST_ARGS="-m security"` to those targets
overrides each pass's own filter rather than combining with it. Invoke
`tests/.venv/bin/pytest -m security` directly instead when you want just
one marker.

## Why the suite also runs in a merge queue

`main` required `strict` status checks until #117: a pull request had to be
up to date with the current `main` before it could merge, so every merge put
every other open pull request behind and each of those needed a rebase and a
fresh suite run to catch back up. That got worse as this stack grew, not
better: the suite now starts 34 services rather than 22, since CI began
applying `.env.tests` and the observability profiles came on, so a rerun costs
more wall clock than it used to, and the number of open pull requests the
churn multiplies against is driven by Renovate and Dependabot, which are
deliberately scheduled to spread bumps across the week rather than land them
one at a time. See [docs/MERGE_PIPELINE.md](MERGE_PIPELINE.md) for what
replaced `strict`, why the two are paired, and what runs against the queue's
own commit; this section covers only why a cheaper alternative was rejected.

Selective or per-service testing (running only the tests a change plausibly
touches, rather than the whole suite) was considered as a cheaper answer to
the same churn and rejected. Bootstrap, not the tests themselves, is where the
suite's cost actually is: on run 32863340140, standing the stack up was 77% of
the 681 second run and running the tests was 23%. A selective suite would
still pay to stand the stack up and save only the smaller half, for a
correctness question (which tests a change could plausibly affect) that is
itself expensive to answer accurately in a stack this interconnected.

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

See also: [README.md](../README.md), [docs/MERGE_PIPELINE.md](MERGE_PIPELINE.md),
[docs/MAKE_COMMANDS.md](MAKE_COMMANDS.md), [docs/CONTRIBUTING.md](CONTRIBUTING.md)
