# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The card scheduler's vocabulary, written once: every refusal and every outcome, each with what it means.

A refusal is raised by name (`Refusal`) and leaves a record where its row says:
  job   a `refused` record in the job's own job.jsonl, then an end record whose outcome is `refused`;
  root  a line in <root>/refusals.jsonl (a name filed "job, root" leaves its record in the job when a job raised it, and in
        refusals.jsonl when a command did, such as a hold naming a card that is not there);
  none  nowhere: there is no usable state root to write in, so the name is printed and nothing else is.
  label not a refusal: a word the records carry (`rc-only`), kept in the table because the study lists it among the names.
  closeout  a PART of a window's close-out (parcel S4a) refused: a `closeout_part` record of the job with `status: refused` and the name, and
        the end record's `closeout`. The job's outcome is the driver's and is not changed by it, and a part refusing does not stop the others.
`by` is the parcel that raises it (docs/studies/SCHED-A-card-scheduler.md, section 6): a name whose parcel
has not landed is here so that the vocabulary is whole, and the test holds every S1 name to a scenario
that raises it. An outcome is the last word of a job's last record.
"""
from __future__ import annotations

# name: (by, where, what it refuses)
REFUSALS = {
    # -- the spec (S1)
    "spec-form": ("S1", "job", "the spec is not JSON, is not an object, repeats a key, or has a field missing, unknown or of the wrong type; the message names the field"),
    "spec-version": ("S1", "job", "the spec's `v` is not 1, the only version this build reads"),
    "commit-not-full": ("S1", "job", "code.commit is not a full SHA (40 lowercase hex digits); an abbreviation is refused, never expanded"),
    "image-unknown": ("S1", "job", "the spec names an image that is not in the configuration's registry"),
    "card-unknown": ("S1", "job, root", "a card id the configuration does not hold (a spec, or a hold or release naming one)"),
    "window-unsupported": ("S2", "job", "the staged runner was handed a job of kind window (S1 raised it for any when.window, which had no calendar; since S3a the window runner runs those and only a staged runner used by itself raises it)"),
    "step-unknown": ("S1", "job", "a step type the registry does not hold (S1's registry is the fake runner's four steps)"),
    "deadline-passed": ("S1", "job", "when.deadline had passed when the job reached the front of the queue"),
    "queue-corrupt": ("S1", "job", "a queued job whose spec.json cannot be read when it is claimed (one that reads but no longer validates is refused by the name of what it breaks)"),
    # -- the state root and its configuration (S1)
    "root-unset": ("S1", "none", "neither --root nor CFT_SCHED_ROOT names a state root"),
    "root-missing": ("S1", "none", "the state root does not exist, or is not a directory (only `init` creates one)"),
    "root-in-checkout": ("S1", "none", "the state root is inside a git working tree: a checkout would make the tree untracked and change the build id"),
    "config-missing": ("S1", "root", "the root has no config.json (run `init`)"),
    "config-form": ("S1", "root", "config.json is not JSON or has a section, key or value that is unknown, missing or of the wrong type; the message names it"),
    "config-exists": ("S1", "root", "`init` will not overwrite an existing config.json"),
    # -- the locks and the queue's verbs (S1)
    "lock-held": ("S1", "root", "another service holds this root's lock: one service per root"),
    "locks-unavailable": ("S1", "root", "this platform has no flock(2); `serve --no-locks` runs without locks and says so in its records"),
    "locks-required": ("S1", "root", "`serve --no-locks` was asked where flock(2) exists: the option is for a platform without it, and a service without its lock cannot be seen by `status`"),
    "card-held": ("S1", "root", "the card already has a hold; the message names who holds it"),
    "card-not-held": ("S1", "root", "release of a card that has no hold"),
    "job-unknown": ("S1", "root", "no job has this id (or it is not an id: j and six or more digits)"),
    "job-ended": ("S1", "root", "cancel of a job that already has an outcome"),
    # -- the code, the build, the images, the guard and the steps (S2)
    "commit-missing": ("S2", "job", "the commit is not in the source: the bundle or the remote is not configured or cannot be read, or does not hold it"),
    "commit-unpushed": ("S2", "job", "the commit is not shown to be on the remote (no branch of it holds it, or the remote cannot be read) and the spec does not allow it"),
    "head-mismatch": ("S2", "job", "the clone's HEAD is not the spec's commit"),
    "tree-dirty": ("S2", "job", "the clone's status is not clean: a changed tracked file, or an untracked one"),
    "rtl-mismatch": ("S2", "job", "the rtl/ tree is not the one the spec names"),
    "content-missing": ("S2", "job", "a string the spec names was not found the stated number of times in its file, or the file is not there"),
    "ancestor-missing": ("S2", "job", "a commit the spec names is not in the clone, or is not an ancestor of the job's commit"),
    "clone-built": ("S2", "job", "the dry tests were asked of a clone holding ignored build products under host/ (parcel P5, KL-13, removes the cause; this one check can then be retired)"),
    "build-failed": ("S2", "job", "the build did not succeed: make failed, or a tool it was to make is not there"),
    "xrt-not-linked": ("S2", "job", "a built tool does not link XRT (ldd)"),
    "build-id-mismatch": ("S2", "job", "the tools' build id is not the tree's, or the tree's does not name the job's commit on a clean tree"),
    "image-digest": ("S2", "job", "an image's SHA-256 differs between the file, the registry, its directory's SHA256SUMS and its manifest, or the file or its sums cannot be read"),
    "image-tiles": ("S2", "job", "an image's tile count (its manifest's clock_cus) differs from the registry's, or the manifest or the registry's count is not there"),
    "image-platform": ("S2", "job", "an image's platform (its manifest's) is not the registry's and the card's, or one of them is not given"),
    "parser-unknown": ("S2", "job", "a step type has neither a parser nor the rc_only label: its output could not be judged"),
    "no-verdict": ("S2", "job", "a step's log holds nothing at all, so no verdict can be read from it (the leg is recorded parse_error)"),
    "rc-only": ("S2", "label", "a LABEL, never raised: a verdict that is only an exit status is recorded `verdict_kind: rc_only` wherever it appears"),
    "dry-run-as-card": ("S2", "job", "a stand-in's output was offered as a card's"),
    "job-exists": ("S2", "job", "a path the job would write (a step's log) already exists: refused rather than written over (the study's 5.3: 'refuse if the outputs exist'); a window that is to START a new run (driver.resume false) finds a metrics.jsonl in driver.out"),
    "card-busy-foreign": ("S2", "job", "a process the scheduler does not own uses the card, by the driver's own rule (find_card_users): refused at once at a job's start, waited for between steps up to the configured limit"),
    # -- the cards and the windows (S3)
    "card-unavailable": ("S3", "job", "the card did not answer its start-up look"),
    "card-quarantined": ("S3", "job", "the card is quarantined"),
    "window-closed": ("S3", "job", "the named window is not open when the job is claimed or starts, or none of its occurrences is left (every date it starts on has passed)"),
    "window-bad": ("S3", "job", "the spec names a window the configuration does not hold"),
    "window-too-short": ("S3", "job", "the job's `estimate_s` exceeds what is left of the window when the job is claimed"),
    "stop-file-present": ("S3", "job", "a window's driver directory holds a STOP file (the driver itself would refuse to start)"),
    "out-in-checkout": ("S3", "job", "a window's driver.out is inside a git working tree (it or an ancestor holds a .git): the driver's files there would make the tree untracked and change the build id the tools carry"),
    "resume-missing": ("S3", "job", "a window that resumes its driver directory finds no metrics.jsonl there (the launcher's refusal; `driver.resume: false` starts a new run)"),
    "preflight-failed": ("S3", "job", "a preflight step failed on a commit whose window has passed before, or on the commit the night fell back to: the night's failure, and no fall back from it"),
    "no-fallback": ("S3", "job", "the preflight failed on a commit whose window never passed and no commit's window has passed (or the last one cannot be run): nothing can run tonight"),
    "record-write-failed": ("S3", "job", "a record could not be written: nothing runs unrecorded"),
    # -- the disk (S4)
    "disk-floor": ("S4", "job", "free space is under the configured floor"),
    # -- the close-out of a window: the night's report, sums and summary, and the page's data commit prepared (S4a)
    "report-failed": ("S4a", "closeout", "the report tool of the clone that ran the night is not there, did not start, ran past its limit or exited with a status other than 0 (the text it printed is kept)"),
    "summary-unreadable": ("S4a", "closeout", "the report's --json file is not there, is not JSON, or is not a summary with a report_version"),
    "sums-incomplete": ("S4a", "closeout", "one of the run's five files (metrics.jsonl, driver.log, status.txt, settings.json, report.txt) cannot be read to be summed; the list is written without it"),
    "publish-no-remote": ("S4a", "closeout", "config.json's code.remote names no URL: there is nowhere to fetch the repository's main from"),
    "remote-unreachable": ("S4a", "closeout", "the remote could not be cloned or fetched, or has no main: the message is kept. Nothing is ever pushed or written to the remote"),
    "reducer-refused": ("S4a", "closeout", "main's reducer refused the run or failed (its status 2 or 3, its message kept): no data file is made"),
    "check-differs": ("S4a", "closeout", "main's `--check` does not find the data file to be what the run reduces to"),
    "metrics-sha-differs": ("S4a", "closeout", "the data file's source.metrics_sha256 is not the sums' line for the run's metrics.jsonl (or the sums have none)"),
    "earlier-night-changed": ("S4a", "closeout", "a night the published data file already holds is not the same in the new one, or is missing from it"),
    "nothing-to-publish": ("S4a", "closeout", "the new data file is the published one but for its `made`: there is no night to add, and an empty commit is not made"),
    "publish-touches-more": ("S4a", "closeout", "the clone shows a change to a file other than site/nightly.json, or the commit would hold one: no commit is made"),
    "publish-failed": ("S4a", "closeout", "a git step of the data commit failed in the scheduler's own clone (checkout, add, commit, the branch); the message is kept"),
}

# name: (by, what it says). The last word of a job's last record; `ended` carries it.
OUTCOMES = {
    "done": ("S1", "every step ran and passed, and none found anything"),
    "done-with-findings": ("S1", "every step ran, none failed, and at least one reported a finding (Logan, 2026-10-21: go on, and mark it)"),
    "failed": ("S1", "a step failed; the steps after it are recorded as skipped"),
    "refused": ("S1", "the job never started: a named refusal (the `refused` record before it)"),
    "cancelled": ("S1", "stopped at a safe point, or removed from the queue, at a person's request"),
    "interrupted": ("S1", "found in running/ at a service start with no service to own it; recorded, never re-run (recovery proper is S3)"),
    "missed-window": ("S3", "a window passed with the card unavailable"),
}


class Refusal(Exception):
    """A refusal, by name. An unnamed one is a bug: the name must be a row of REFUSALS."""

    def __init__(self, name: str, why: str):
        if name not in REFUSALS:
            raise KeyError(f"refusal {name!r} is not in REFUSALS: name it there first")
        super().__init__(f"{name}: {why}")
        self.name, self.why = name, why
