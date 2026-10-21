#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""What the stress driver's guard calls a card user, held against `pgrep -f`, the lead's guard in its box scripts.

    python -B -I guard_probe.py [--controls]

hw/card_stress.py refuses to start, and waits between legs, while another process uses the card
(card_user, find_card_users). The lead's box scripts ask `pgrep -fc 'card_stress.py|card-stress.sh|...'`
instead, whose pattern is searched in the WHOLE command line of every process, the asker's own shell
included. This script feeds both a synthetic table of processes (no real process is read, no card and no
box is touched; the driver's module is imported read-only and its process listing is replaced by the
table) and prints what each says, so a scheduler's guard can be chosen with the two behaviours in view.

Each CHECK states what the driver's own functions answered. With --controls, the lead's pattern is put
through the same twelve command lines as a classifier (`pgrep -f` model) and must fail the checks: it
misses card users the driver names (the driver names them by the program's name or by an image argument,
and the pattern lists only the soaks, the driver and the gate) and flags processes that use no card.

The output is written with LF line ends on every platform (Windows Python would write CRLF to a redirected stdout), so the
capture beside this script is LF and compares equal as it stands.

Python 3.10 or later; standard library only. Prints no path.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HW = os.path.normpath(os.path.join(HERE, "..", "..", "..", "hw"))
sys.dont_write_bytecode = True
sys.path.insert(0, HW)
import card_stress as CS  # noqa: E402  the driver's own module: card_user, find_card_users, is_verify_run

# the guard of box_nightly.sh and box_resume_stress.sh (READ in those scripts; the other card scripts each have a list
# of their own, from two to six words: this is the nightly's)
PGREP_PATTERN = "card_stress.py|card-stress.sh|divsqrt-soak|clause5-soak|chunk_card.py|verify/run.sh"
IMG = "/images/cft_hw_quad.xclbin"
RESULTS = []


def check(name, good, detail=""):
    RESULTS.append(bool(good))
    print("CHECK %-4s %s%s" % ("ok" if good else "FAIL", name, (" - " + detail) if detail and not good else ""))


def pgrep_f(table, asker_pid):
    """`pgrep -fc PATTERN` as its manual describes it: every process whose full command line matches, except
    pgrep itself (it never excludes the shell that ran it)."""
    rx = re.compile(PGREP_PATTERN)
    return [p for p in table if p["pid"] != asker_pid and rx.search(" ".join(p["args"]))]


def card_user_cases():
    """(what, argv, expected: a substring of the reason or None)."""
    return [
        ("an idle cft-serve fronting the quad image", ["cft-serve", "--artifact", IMG, "--port", "7754"], "an xclbin argument"),
        ("cft-serve on the software backend", ["cft-serve", "--port", "7754"], None),
        ("telemetry: xbutil examine", ["xbutil", "examine", "-d", "0000:02:00.1", "-r", "thermal"], None),
        ("telemetry: xrt-smi examine", ["xrt-smi", "examine", "-d", "0000:02:00.1", "-r", "electrical"], None),
        ("xbutil program (loads an image)", ["xbutil", "program", "-d", "0000:02:00.1", "-u", IMG], "xbutil program"),
        ("device-test on an image", ["host/device-test", IMG, "-i"], "an xclbin argument"),
        ("acceptance.py on the card", ["python3", "programs/acceptance.py", "--device", IMG], "an xclbin argument"),
        ("acceptance.py on the software backend", ["python3", "programs/acceptance.py", "--device", "sw"], None),
        ("a gate: bash verify/run.sh --budget gate", ["bash", "verify/run.sh", "--budget", "gate"], None),
        ("the lead's waiting nightly script", ["bash", "box_nightly.sh", "0b7c959", "bundle", "1021", "2026-10-21 18:00", "2026-10-22 08:00"], None),
        ("cp of an image", ["cp", IMG, "/backup/"], None),
        ("a shell whose one argument is the text of a command that names the pattern and an image",
         ["bash", "-c", "pgrep -fc '%s'; device-test %s" % (PGREP_PATTERN, IMG)], None),
    ]


def pgrep_card_user(p):
    """The lead's guard as a classifier: the nightly's pattern searched in the joined command line (`pgrep -f`)."""
    return "the pattern is in the command line" if re.search(PGREP_PATTERN, " ".join(p["args"])) else None


def run_cases(classify, label):
    """Prints each case; returns (the cases the classifier gets wrong, of them the card users it MISSES, the non-users it FLAGS)."""
    bad, miss, false = [], [], []
    for what, argv, want in card_user_cases():
        got = classify({"pid": 4000, "ppid": 1, "args": argv})
        good = (got is None) if want is None else (got is not None and want in got)
        if label == "pgrep":                      # its reason text is its own: only whether it flags
            good = (got is None) == (want is None)
        verdict = "ok" if good else ("MISS" if want is not None else "FALSE")
        print("  %-5s %-72s -> %s" % (verdict, what[:72], got or "not a card user"))
        if not good:
            bad.append(what)
            (miss if want is not None else false).append(what)
    return bad, miss, false


def soak_env_cases():
    """A soak is a card user only through CFT_SOAK_ARTIFACT in its environment (/proc/PID/environ), which the driver reads;
    here the environment reader is replaced by a table, so the rule is shown and nothing real is read."""
    envs = {4242: {"CFT_SOAK_ARTIFACT": IMG}, 4243: {}}
    real = CS.proc_environ
    CS.proc_environ = lambda pid: envs.get(pid, {})
    try:
        a = CS.card_user({"pid": 4242, "ppid": 1, "args": ["host/clause5-soak", "scaleb32-wide", "0", "1048576", "rne"]})
        b = CS.card_user({"pid": 4243, "ppid": 1, "args": ["host/clause5-soak", "scaleb32-wide", "0", "1048576", "rne"]})
    finally:
        CS.proc_environ = real
    return a, b


def main(argv):
    try:
        sys.stdout.reconfigure(newline="\n")      # LF on every platform, so a capture is the same bytes everywhere
    except (AttributeError, ValueError):
        pass
    me = os.getpid()
    print("== card_user on single processes (the driver's own function)")
    bad, _, _ = run_cases(CS.card_user, "driver")
    check("every command line above is classified as the driver's design says (%d cases)" % len(card_user_cases()), not bad, "; ".join(bad))
    soak_card, soak_pool = soak_env_cases()
    check("a soak with CFT_SOAK_ARTIFACT in its environment is a card user, and the same soak without it (a host-pool job) is not",
          soak_card is not None and soak_card.startswith("CFT_SOAK_ARTIFACT=") and soak_pool is None, "%r / %r" % (soak_card, soak_pool))
    print()

    print("== a table of processes: what the driver's find_card_users and `pgrep -fc` each say")
    shell_text = "pgrep -fc '%s'" % PGREP_PATTERN
    table = [
        {"pid": 1, "ppid": 0, "args": ["init"]},
        {"pid": 100, "ppid": 1, "args": ["sshd:", "logan@pts/0"]},
        {"pid": 200, "ppid": 100, "args": ["bash", "-c", shell_text]},           # the shell that asks, as an ssh command line makes it
        {"pid": me, "ppid": 200, "args": ["python3", "scheduler.py", "run"]},    # the asker (a driver or a scheduler), a child of that shell
        {"pid": 400, "ppid": 100, "args": ["bash", "verify/run.sh", "--budget", "gate"]},
        {"pid": 500, "ppid": 100, "args": ["bash", "box_nightly.sh", "0b7c959", "bundle", "1021", "2026-10-21 18:00", "2026-10-22 08:00"]},
        {"pid": 600, "ppid": 1, "args": ["cft-serve", "--artifact", IMG, "--port", "7754"]},
    ]
    real_list = CS.list_processes
    CS.list_processes = lambda: [dict(p) for p in table]
    try:
        users, beside = CS.find_card_users()
    finally:
        CS.list_processes = real_list
    pg = pgrep_f(table, asker_pid=me)
    print("driver  : foreign card users %s; verify/run.sh beside %s" % ([u["pid"] for u in users], [b["pid"] for b in beside]))
    print("pgrep -f: matches %s (%d)" % ([p["pid"] for p in pg], len(pg)))
    check("the driver's guard names the idle cft-serve (pid 600) and nothing else as a card user", [u["pid"] for u in users] == [600],
          str([u["pid"] for u in users]))
    check("the driver allows the gate (pid 400) and records it as beside, as docs/CARDDAY.md says", [b["pid"] for b in beside] == [400])
    check("the driver does not count the asker's own launching shell (pid 200: its one argument is a command text that holds the pattern)",
          200 not in [u["pid"] for u in users])
    check("pgrep -f counts the asker's launching shell (pid 200) and the gate (pid 400): %d matches where no process uses the card" % len(pg),
          sorted(p["pid"] for p in pg) == [200, 400], str([p["pid"] for p in pg]))
    print()

    if "--controls" in argv:
        print("== controls: the lead's pgrep pattern, put through the same twelve cases, must fail the checks above")
        bad2, miss2, false2 = run_cases(pgrep_card_user, "pgrep")
        shell_flagged = pgrep_card_user({"pid": 200, "ppid": 100, "args": ["bash", "-c", shell_text]}) is not None
        ok = bool(bad2) and shell_flagged
        print("CONTROL %-4s the pattern guard gets %d of %d cases wrong (it MISSES %d card users the driver names, and FLAGS %d processes that use no card)"
              " and flags the launching shell; the checks above would go red on it" %
              ("ok" if ok else "FAIL", len(bad2), len(card_user_cases()), len(miss2), len(false2)))
        RESULTS.append(ok)
        t2 = [p for p in table if p["pid"] != 600]          # the same table without the idle cft-serve
        CS.list_processes = lambda: [dict(p) for p in t2]
        try:
            users2, _ = CS.find_card_users()
        finally:
            CS.list_processes = real_list
        pg2 = pgrep_f(t2, asker_pid=me)
        ok2 = users2 == [] and len(pg2) == 2
        print("CONTROL %-4s with the cft-serve gone the driver's guard finds nothing and `pgrep -f` still counts %d (the shell and the gate)" %
              ("ok" if ok2 else "FAIL", len(pg2)))
        RESULTS.append(ok2)
    allok = all(RESULTS)
    print("guard_probe: %s" % ("every check held" if allok else "A CHECK FAILED"))
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
