# M3 model: is every captured run complete? (the study's 11). The queue
# logs' "rc" field is the status of the `date` beside it, not the run's (the
# queue scripts read $? after a command substitution in the same line; the
# scripts are fixed, the logs kept as made), so this is the check of the
# runs instead: every *.out.txt here, first-b1/ and second-b1/ included,
# holds no traceback (each run's stderr went into its output) and closes
# with its own script's last line - a summary or a timing line, or, for the
# two that close on a list of lanes (poolmarks, rewrites), all their rows.
# Then controls: copies of real outputs, cut short, emptied or given a
# traceback, in memory, each of which must be flagged. With a directory, it
# checks that one's outputs instead (the box's, for the lead; their stderr
# is the job log's, so there a failed job shows as an output without its
# closing line); the controls are always made from this directory's outputs.
#
#   python complete.py [DIR]

import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# The closing line of each script's output, as the script prints it.
CLOSE = {
    "bits": r"^fp256: p 237",
    "budget": r"^\s+\d+ s$",
    "census": r"^fp\d+ \w+: \d+ wrong unmarked",
    "costs": r"distinct bank words over these fragments",
    "onseq": r"^\d+ s$",
    "plants": r"\d+ of \d+ lane and mark cases red; \d+ s",
    "pools_run": r"wrong unmarked lanes in all; \d+ s$",
    "rate": r"^\s+\d+ s$",
    "regions_run": r"wrong unmarked in all; \d+ s$",
    "specials": r"wrong unmarked special lanes; \d+ s$",
    "tw32_ref": r"^fp256 log1p",
    "sched": r"compound\(x, 3\)",
    "share": r"with exp2\(x\), M1's",
}
# The two that close on a list of lanes: their rows, counted.
ROWS = {
    "poolmarks": (r"^fp64 \w+\s+(rne|rtz):", 10),   # five functions, two attributes
    "rewrites": (r"^fp64 \S.* -> ", 11),            # section 6's eleven rows
}


def verdict(script, text):
    """None when the output is complete, else why not."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if "Traceback" in text or "Error" in text:
        return "a traceback or an error"
    if not lines:
        return "empty"
    if script in CLOSE:
        if not re.search(CLOSE[script], lines[-1]):
            return "closes with %r" % lines[-1][:80]
        return None
    if script in ROWS:
        pat, want = ROWS[script]
        got = sum(1 for ln in lines if re.match(pat, ln))
        return None if got == want else "%d rows, %d expected" % (got, want)
    return "no rule for the script %s" % script


def script_of(path):
    return os.path.basename(path).split(".")[0]


def outputs(d):
    files = sorted(glob.glob(os.path.join(d, "*.out.txt"))
                   + glob.glob(os.path.join(d, "first-b1", "*.out.txt"))
                   + glob.glob(os.path.join(d, "second-b1", "*.out.txt")))
    return [f for f in files if not os.path.basename(f).startswith("complete.")]


def read(f):
    return open(f, encoding="utf-8", errors="replace").read()


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else HERE
    files = outputs(d)
    bad = 0
    for f in files:
        why = verdict(script_of(f), read(f))
        if why:
            bad += 1
            print("INCOMPLETE", os.path.relpath(f, d).replace("\\", "/"), why)
    print(f"{len(files)} outputs; {bad} without their closing line or with a "
          f"traceback")

    # The controls, in memory, from this directory's outputs: each must be
    # flagged.
    texts = {os.path.basename(f): read(f)
             for f in glob.glob(os.path.join(HERE, "*.out.txt"))}
    controls = []
    for name in ("pools_run.fp64.out.txt", "budget.fp64-pow-wide.out.txt",
                 "census.fp64-intpow.out.txt", "specials.fp64.out.txt",
                 "onseq.fp64.out.txt", "regions_run.fp64-pow.out.txt"):
        t = texts[name]
        cut = "\n".join(t.splitlines()[:3]) + "\n"
        controls.append((name + " cut to 3 lines", script_of(name), cut))
        controls.append((name + " with a traceback", script_of(name),
                         t + "Traceback (most recent call last):\n"))
        controls.append((name + " empty", script_of(name), ""))
    for name, keep in (("rewrites.fp64.out.txt", 8),
                       ("poolmarks.fp64.out.txt", 30)):
        t = texts[name]
        controls.append((name + " cut to %d lines" % keep, script_of(name),
                         "\n".join(t.splitlines()[:keep]) + "\n"))
    missed = [c[0] for c in controls if verdict(c[1], c[2]) is None]
    for m in missed:
        print("CONTROL NOT FLAGGED", m)
    print(f"{len(controls) - len(missed)} of {len(controls)} controls flagged")
    sys.exit(1 if bad or missed else 0)


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    main()
