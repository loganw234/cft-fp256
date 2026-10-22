# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The card scheduler's vocabulary, written once: every refusal and every outcome, each with what it means.

A refusal is raised by name (`Refusal`) and leaves a record where its row says:
  job   a `refused` record in the job's own job.jsonl, then an end record whose outcome is `refused`;
  root  a line in <root>/refusals.jsonl (a name filed "job, root" leaves its record in the job when a job raised it, and in
        refusals.jsonl when a command did, such as a hold naming a card that is not there);
  none  nowhere: there is no usable state root to write in, so the name is printed and nothing else is.
  label not a refusal: a word the records carry (`rc-only`), kept in the table because the study lists it among the names.
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
    "window-unsupported": ("S1", "job", "when.window needs the calendar of parcel S3; refused rather than run at the wrong time"),
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
    "job-exists": ("S2", "job", "a path the job would write (a step's log) already exists: refused rather than written over (the study's 5.3: 'refuse if the outputs exist')"),
    "card-busy-foreign": ("S2", "job", "a process the scheduler does not own uses the card, by the driver's own rule (find_card_users): refused at once at a job's start, waited for between steps up to the configured limit"),
    # -- the cards and the windows (S3)
    "card-unavailable": ("S3", "job", "the card did not answer its start-up look"),
    "card-quarantined": ("S3", "job", "the card is quarantined"),
    "window-closed": ("S3", "job", "the named window is not open"),
    "window-bad": ("S3", "job", "the spec names a window the configuration does not hold"),
    "window-too-short": ("S3", "job", "the estimate exceeds the window"),
    "stop-file-present": ("S3", "job", "a window's directory holds a STOP file"),
    "record-write-failed": ("S3", "job", "a record could not be written: nothing runs unrecorded"),
    # -- the disk (S4)
    "disk-floor": ("S4", "job", "free space is under the configured floor"),
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
