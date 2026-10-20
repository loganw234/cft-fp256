# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""UCBTEST's hex test vectors for + - * / and square root, read and run.

    python3 -I python/external_ucblib.py --dir DIR --subject BIN [--show N]

DIR is UCBTEST's ucblib/ directory, extracted by the caller (nothing of it is
in this repository; docs/EXTERNAL-GENERATORS.md). The ten files used are
adds subs muls divs sqrts and addd subd muld divd sqrtd, `.input`. A vector
line is

    <function> <round n|z|p|m> <relation> <exceptions> <argument words> <answer words>

with a value one hex word for single and two (high word first) for double.
The relations of these ten files are eq (the answer's bits), eqz (the same
but for the sign of the answer) and uo (the answer is a NaN); the exceptions
are letters v o u d x (invalid, overflow, underflow, division, inexact), - for
none, and `?x` and its kin (a letter to leave unchecked, a bare `?` to check
none), exactly as ucbtest/lib.c reads them. A line with another relation, or
another function, is counted and named, never skipped silently.

The cases go through cft-tf-subject as external_ibm.py's do, and a
disagreement is arbitrated by python/cft_golden by external_ibm.judge: the
same classes, the same explanation of an underflow flag by tininess before
rounding.
"""

import argparse
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import external_ibm as ibm  # noqa: E402

FUNCS = {"add": "+", "sub": "-", "mul": "*", "div": "/", "sqrt": "V"}
ARITY = {"+": 2, "-": 2, "*": 2, "/": 2, "V": 1}
RDS = {"n": "near_even", "z": "minMag", "p": "max", "m": "min"}
LETTERS = {"v": ibm.INVALID, "o": ibm.OVERFLOW, "u": ibm.UNDERFLOW,
           "d": ibm.DIVZERO, "x": ibm.INEXACT}


def parse_exceptions(word):
    """(expected flag word, mask of the flags to check) as ucbtest/lib.c reads
    the field: letters set flags, `?` and a letter drop that flag from the
    mask, a trailing `?` drops them all."""
    flags, mask, i = 0, 31, 0
    if word == "-":
        return 0, mask
    while i < len(word):
        c = word[i]
        i += 1
        if c in LETTERS:
            flags |= LETTERS[c]
        elif c == "?":
            if i >= len(word):
                mask = 0
            else:
                mask &= ~LETTERS[word[i]]
                i += 1
        else:
            raise ibm.Refusal(f"exception letter {c!r}")
    return flags, mask


def parse_line(line, name):
    """None for a line that is no vector; else a case in external_ibm's shape,
    or a Refusal."""
    t = line.split()
    m = re.fullmatch(r"(add|sub|mul|div|sqrt)([sd])", t[0]) if t else None
    if not m or len(t) < 5:
        return None
    if t[1] not in RDS:
        raise ibm.Refusal(f"rounding word {t[1]!r}")
    fn, p = m.groups()
    op, fmt = FUNCS[fn], "b32" if p == "s" else "b64"
    words = 1 if p == "s" else 2
    want = 4 + words * (ARITY[op] + 1)
    if len(t) != want:
        raise ibm.Refusal(f"{t[0]}: {len(t)} fields where {want} are expected")
    rel = t[2]
    if rel not in ("eq", "eqz", "uo"):
        raise ibm.Refusal(f"relation {rel!r}")
    flags, mask = parse_exceptions(t[3])
    vals = []
    for k in range(ARITY[op] + 1):
        w = [int(x, 16) for x in t[4 + k * words:4 + (k + 1) * words]]
        vals.append(w[0] if words == 1 else (w[0] << 32) | w[1])
    mb, eb = ibm.FORMATS[fmt][2], ibm.FORMATS[fmt][1]
    if rel == "uo":
        res = ("nan", (((1 << eb) - 1) << mb) | (1 << (mb - 1)))
    else:
        res = ("bits" if rel == "eq" else "bitsnz", vals[-1])
    return {"fmt": fmt, "op": op, "round": RDS[t[1]], "traps": "",
            "ops": [("bits", v) for v in vals[:-1]], "res": res,
            "flags": flags, "mask": mask, "where": name}


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--show", type=int, default=10)
    a = ap.parse_args(argv)

    cases, refused, other = [], Counter(), 0
    for stem in ("adds", "subs", "muls", "divs", "sqrts",
                 "addd", "subd", "muld", "divd", "sqrtd"):
        with open(os.path.join(a.dir, stem + ".input"), "rb") as f:
            text = f.read().decode("latin-1")
        for n, line in enumerate(text.split("\n"), 1):
            try:
                c = parse_line(line, f"{stem}.input:{n}")
            except ibm.Refusal as e:
                refused[str(e)] += 1
                continue
            if c is None:
                other += 1
            else:
                cases.append(c)
    print(f"{len(cases)} vectors read, {sum(refused.values())} refused, "
          f"{other} other lines")
    for r, k in refused.most_common():
        print(f"  refused x{k}: {r}")
    print("  by function and format:", dict(Counter(
        (c["fmt"], c["op"]) for c in cases)))
    print("  by rounding:", dict(Counter(c["round"] for c in cases)))

    groups = defaultdict(list)
    for c in cases:
        groups[(ibm.FORMATS[c["fmt"]][0] + "_" + ibm.OPS[c["op"]][0],
                c["round"])].append(c)
    mism, shown, sens = Counter(), Counter(), Counter()
    for (fn, mode), cs in sorted(groups.items()):
        for c, (bits, fl) in zip(cs, ibm.run_subject(a.subject, fn, mode, cs)):
            gb, gf = ibm.golden(c)
            pred = ibm.before_rounding_flags(c, gf)
            if pred != gf:
                sens["vectors the two detections of tininess flag differently"] += 1
                sens["  the vector's flags = the before-rounding prediction"] += \
                    (c["flags"] ^ pred) & c["mask"] == 0
                sens["  the vector's flags = golden's (after rounding)"] += \
                    (c["flags"] ^ gf) & c["mask"] == 0
            cls = ibm.judge(c, bits, fl, gb, gf)
            if cls is None:
                continue
            key = (c["fmt"], c["op"], cls)
            mism[key] += 1
            if shown[key] < a.show:
                shown[key] += 1
                print(f"    {cls}: {c['where']} {c['fmt']}{c['op']} {c['round']}")
    print(f"{len(cases)} vectors run through libcft, {sum(mism.values())} disagreements")
    for k, v in sens.items():
        print(f"  {v:>6}  {k}")
    for k, v in sorted(mism.items()):
        print(f"  {v:>6}  {k[0]}{k[1]}  {k[2]}")
    return 1 if any("DEFECT" in k[2] or "all three" in k[2] for k in mism) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
