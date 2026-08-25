# The Merge Pipeline

What happens between opening a pull request against this repository and it
landing on `main`, told as one path rather than scattered across the three
documents that each own one facet of it. See
[docs/CONTRIBUTING.md](CONTRIBUTING.md) for the mechanics of contributing (how
to fork, install pre-commit, coding style), [docs/TESTING.md](TESTING.md) for
the test suite itself, and [docs/HARDENING.md](HARDENING.md) for the security
reasoning behind the unattended dependency path. This page is about the path
through the pipeline: what runs, in what order, what each thing proves, and
what is actually standing between a pull request and `main` at any given
moment.

## A human pull request

Open it as a **draft** first. `Code Check` runs the full pre-commit hook set,
both stages, over every file, and CodeRabbit does not review a draft at all:
`.coderabbit.yaml` sets `drafts: false` on purpose, so a review is not spent
on a diff the mechanical linters have not finished cleaning up yet.

**Mark it ready for review** once `Code Check` is green. That is what starts
CodeRabbit. Address what it raises, pushing fixes as needed; each push
re-runs the lint gate and gets a fresh review. The required check here is not
`CodeRabbit` itself, and the next section is about why.

Once the review is settled, **comment `/run-tests`**. Only a maintainer can
do this, and it is worth spending deliberately: the suite stands up the whole
stack and takes upward of twelve minutes, so it runs once, on the version
actually being merged, rather than after every push. See
[docs/TESTING.md](TESTING.md) for what it covers and
[docs/CONTRIBUTING.md](CONTRIBUTING.md) for the comment mechanics
(`/run-check` for the lint layers alone, the maintainer allowlist, and so on).

Once every required check reads green, GitHub adds the pull request to the
**merge queue** on its own, and it merges once the queue's own run of that
same check set passes on the commit the queue actually builds. See "The merge
queue" below for why that extra run exists and what it is trading against.

## A dependency bot pull request

Dependabot and Renovate open pull requests unattended, and patch, minor and
digest bumps merge unattended too, without anyone reviewing them by hand.
Nothing above changes for a major bump; it gets no approval and waits for a
maintainer exactly like a human pull request would. For the ones that do
merge on their own:

1. **The suite starts itself.** `integration-tests.yml` authorizes
   `renovate[bot]` and `dependabot[bot]` directly, on a branch inside this
   repository, so `Tests Verified` runs without anyone commenting
   `/run-tests`. Nothing else about the suite changes: every other pull
   request, forks included, still only runs it when a maintainer asks.
2. **`Pin Only` is graded.** `scripts/assert-pin-only-diff.py` checks that
   every changed line differs from its counterpart in nothing but a version
   or a digest, in a pin position, across five allowed files, and
   `.github/workflows/coderabbit-gate.yml` publishes its verdict as the `Pin
   Only` status. A number that is not a pin does not count as one: `PUID`
   moving, or a `timeout-minutes` changing, is refused the same as an added
   line would be. See [docs/HARDENING.md](HARDENING.md) for why this exists
   and what it is defending against; it is aimed at the bot identity, not at
   the upstream package.
3. **The approval is supplied, conditionally.** `bot-auto-merge.yml` waits
   for `Pin Only` to read `success` and then supplies the approving review
   branch protection requires. A diff that is not pin-only gets no approval
   and waits for a person, same as a major bump does.
4. **GitHub merges it** once every required check, `Review Verified` and the
   merge queue's own run included, is green. Renovate arms auto-merge itself
   when it opens the pull request; the workflow arms it on the Dependabot
   path, since Dependabot cannot.

`Review Verified` is not skipped here, and that is deliberate: see the next
section for what a pin-only diff actually earns it.

## Every required status context

| Context | What it actually proves | Who publishes it |
| --- | --- | --- |
| `Code Check` | The full pre-commit hook set (both stages) passed over every file | `pull-request-validation.yml`, as a job |
| `Prerequisite Checks` | The static, no-containers-needed test tier passed (pin annotations, repo hygiene) | `pull-request-validation.yml`, as a job |
| `Detect Changed Paths` | Nothing more than that the path filter itself ran; other jobs read its output | `pull-request-validation.yml`, as a job |
| `Tests Verified` | The integration suite passed on this exact commit, or the change touched no runtime file | `integration-tests.yml`, published directly onto the head SHA |
| `Pin Only` | A dependency bot's diff changes nothing but a version or digest in a pin position; `success` with a "not a dependency bot pull request" description on everything else | `coderabbit-gate.yml`, published directly onto the head SHA |
| `Review Verified` | CodeRabbit's actual review outcome, not merely that it reported something | `coderabbit-gate.yml`, published directly onto the head SHA |

`Code Check`, `Prerequisite Checks` and `Detect Changed Paths` are ordinary
workflow jobs: GitHub reports a job's own pass or fail as the check. The other
three are commit statuses, written directly by a workflow step rather than
read off a job's outcome, for the reason [docs/TESTING.md](TESTING.md)
explains for `Tests Verified`: a job gated on a condition is *skipped* when
the condition does not hold, and branch protection counts a skipped job as
successful, which would let an untested pull request merge. A status that a
workflow chooses whether to write, and what to write, does not have that
failure mode: absent reads as waiting, not as passed.

## `Review Verified`, and the bug it exists to fix

A green `CodeRabbit` check does not mean a review happened. CodeRabbit posts
through the legacy commit status API, which offers only `error`, `failure`,
`pending` and `success`, with no fifth state for "green, but not for the
reason you think." An exhausted review quota resolves to `success` with the
description `Review rate limited`. A skipped draft resolves to `success` with
`Review skipped: draft pull request`. Both read identically to `success` with
`Review completed`, and there is nothing in the status itself, or in what
branch protection reads from it, that can tell the three apart. Three pull
requests merged with no review having actually happened on 2026-08-19 as a
direct result (#114).

`scripts/coderabbit-review-verdict.py`, published as `Review Verified` by
`coderabbit-gate.yml`, is the fix: it reads the actual description behind the
`CodeRabbit` status rather than its color, and grades in three lanes.

1. **A draft is `pending`**, not `failure`. CodeRabbit has not reviewed it
   because it was told not to, which is a deliberate wait rather than a
   decline, and a required context reading red for a pull request's entire
   draft phase would teach nothing. Pending blocks the merge exactly as hard
   as failure does, so nothing merges early either way.
2. **A dependency bot pull request is graded on `Pin Only` first.** A clean
   verdict returns `success` with no CodeRabbit review at all, because
   CodeRabbit never reviews a bot's pull request in the first place, hardcoded
   upstream (#113), so requiring one here would block every bot pull request
   forever; a pin-only diff has nothing in it a review would catch beyond what
   the assertion already read line by line, which is what makes passing it
   unattended safe rather than merely convenient. A diff that is *not*
   pin-only falls through to lane 3 instead, and is graded exactly like a
   human pull request from there: it already gets no automatic approval
   either way, since `bot-auto-merge.yml` withholds one from anything but a
   clean `Pin Only` verdict, so a person is already looking at it regardless
   of what `Review Verified` says. Requiring a real review on top of that
   cannot stall the happy path, since there was never an unattended path for
   this diff to begin with, and it cannot deadlock either: CodeRabbit will
   never review a bot's pull request on its own, but
   `coderabbit-review-queue.yml`'s hourly nudge reaches exactly this pull
   request, asking for the review this lane needs on its behalf.
3. **Everything else** (a human pull request, a fork, or a bot pull request
   that fell through from lane 2) is `success` only for the literal
   description `Review completed`. Absent is `pending`. A rate limited
   decline, a skipped-draft description reaching this lane (it should not,
   since lane 1 already caught an actual draft), an error state, or a
   description this script has never seen before, is `failure`. No
   exceptions: this is the lane the three unreviewed merges happened in, and
   a status this narrow is the point.

Read the reason beside a `CodeRabbit` check, not its color, if you are
looking at it directly; `Review Verified` is what makes that reading a
required check rather than a habit a person has to remember.

## The merge queue

`main` used to require `strict` status checks: a pull request had to be
rebased onto the current `main` before it could merge. That guarantee is real
for a stack whose suite stands the whole thing up, but the cost compounded
with every dependency bot pull request in flight, since one merge invalidated
every other open pull request's checks and each one needed a fresh rebase and
a fresh twelve-minute run to catch back up (#117).

A merge queue replaces `strict` rather than sitting alongside it. It tests a
throwaway merge commit against the current `main` instead of moving a pull
request's own head, so the "tested against what it lands on" guarantee still
holds without a pull request's checks ever being invalidated by someone
else's merge. Every context in the table above runs a second time, against
that commit, before anything actually merges: `Code Check`, `Prerequisite
Checks`, `Detect Changed Paths`, `Tests Verified`, `Pin Only` and `Review
Verified`. The PR-stage suite run stays required exactly as it is; the queue
run is an addition, because a dependency bot's approval has to carry test
evidence behind it, and the queue commit is not the commit that evidence was
originally read on.

There is deliberately no post-merge canary on `main` and no revert-based
recovery. `main` has to be green by construction, which is the whole reason
every required check runs again on the queue's own commit instead of trusting
each pull request's copy of them. See [docs/TESTING.md](TESTING.md) for the
full reasoning, including why selective or per-service testing was
considered and rejected as a cheaper alternative to the queue.

## What blocks, and what clears it

Some blocks recover on their own; others need a person, and it is worth
knowing which is which before assuming a stuck pull request needs
intervention.

**Clears on its own:**

- **An absent or stale `Review Verified`.** `coderabbit-gate.yml` re-grades
  every open pull request hourly, so a missed or failed run recovers without
  anyone noticing it was ever wrong.
- **A quota-exhausted `CodeRabbit` status, or a bot pull request CodeRabbit has
  never looked at.** `coderabbit-review-queue.yml` nudges CodeRabbit hourly
  with `@coderabbitai review`, one pull request at a time, whenever
  `Review Verified` reads `failure` or reads `pending` specifically for
  "waiting for a CodeRabbit review", which is the state a bot pull request
  that fell out of the pin-only lane sits in forever otherwise, since
  CodeRabbit never reviews one on its own. It skips a pull request that is
  failing something else, has a merge conflict, or already has an unresolved
  thread of its own, since a review cannot fix any of those and the quota slot
  would be wasted.
- **A pull request behind on `main`.** The merge queue tests it fresh against
  the current `main` rather than requiring a rebase, which is the entire
  point of dropping `strict`.
- **A rejected bot pull request that later becomes mergeable.** Ejection from
  the merge queue does not disable a pull request's auto-merge; GitHub
  re-enqueues it once the blocking condition clears, the same way the hourly
  re-grade above clears a bad `Review Verified` run without a person acting.

**Needs a person:**

- **An unresolved CodeRabbit conversation.** Branch protection blocks on it
  regardless of what either status says, and neither bot ever resolves a
  thread, so anything CodeRabbit objects to on a bot pull request waits for a
  maintainer.
- **A bot diff that is not pin-only.** `Pin Only` reads `failure`, no
  approval is supplied, and `Review Verified` falls into the human lane; a
  maintainer has to read it.
- **A major dependency bump.** No automatic approval either way, by design.
- **A genuine test failure or merge conflict.** Neither self-heals; someone
  has to change the code.

---

See also: [README.md](../README.md), [docs/CONTRIBUTING.md](CONTRIBUTING.md),
[docs/TESTING.md](TESTING.md), [docs/HARDENING.md](HARDENING.md)
