#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Score host/tools/tf_subject.c (cft-tf-subject) against the golden model.

    python3 host/tests/tf_subject_check.py ./cft-tf-subject      (make tf-subject-test)

The subject is the libcft end of a Berkeley TestFloat pipe. What it can get
wrong, however right libcft is, is the glue: which operand goes where in
cft_run (ADD and SUB read a and c), which comparison is the signaling one,
the order of the flag bits (TestFloat's run the other way round), the word
for each rounding mode, the exact flag, the width and case of the hex it
writes, and the integers' two's complement. This script feeds it cases of
our own - special values, boundaries, a few numbers - for every function name
it takes, in every rounding mode, and holds each output line to
python/cft_golden, the authority, in TestFloat's line format. No TestFloat
source or output is used; the cases are ours.

Two negative controls: with CFT_SOAK_SABOTAGE set the subject must write
lines this script then finds wrong (a harness that cannot fail proves
nothing), and a function it refuses must be refused by name with status 2.
"""

import itertools
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

import external_tf as xtf  # noqa: E402

MODES = ("near_even", "near_maxMag", "minMag", "min", "max")

F32 = [0x00000000, 0x80000000, 0x00000001, 0x007FFFFF, 0x00800000, 0x3F800000,
       0xBF800000, 0x40000000, 0x40490FDB, 0x7F7FFFFF, 0xFF7FFFFF, 0x7F800000,
       0xFF800000, 0x7FC00000, 0x7F800001, 0x3EAAAAAB, 0x4B000000, 0x4B800001,
       0x5F000000, 0xDF000000, 0x3F7FFFFF, 0x33800000, 0x00800001, 0x3FC00000,
       0x40200000, 0xC0200000, 0x3F000000, 0xBF000000, 0x4EFFFFFF, 0x4F000000]
F64 = [0x0000000000000000, 0x8000000000000000, 0x0000000000000001,
       0x000FFFFFFFFFFFFF, 0x0010000000000000, 0x3FF0000000000000,
       0xBFF0000000000000, 0x4000000000000000, 0x400921FB54442D18,
       0x7FEFFFFFFFFFFFFF, 0xFFEFFFFFFFFFFFFF, 0x7FF0000000000000,
       0xFFF0000000000000, 0x7FF8000000000000, 0x7FF0000000000001,
       0x3FD5555555555555, 0x4330000000000000, 0x4340000000000001,
       0x43E0000000000000, 0xC3E0000000000000, 0x3FEFFFFFFFFFFFFF,
       0x3CA0000000000000, 0x0010000000000001, 0x3FF8000000000000,
       0x4004000000000000, 0xC004000000000000, 0x3FE0000000000000,
       0xBFE0000000000000, 0x41DFFFFFFFC00000, 0x41E0000000000000]
# binary128: zeros, the least and greatest subnormal, the least and greatest
# normal, 1, 2, 1/3, pi, 1.5, 2.5, the infinities, a quiet and a signaling NaN,
# 2^112 and 2^112 + 1, 2^31, 2^32, 2^63, 2^64 and the largest below 2^63
def _q(sign, exp, frac):
    return (sign << 127) | (exp << 112) | frac


F128 = [_q(0, 0, 0), _q(1, 0, 0), _q(0, 0, 1), _q(0, 0, (1 << 112) - 1),
        _q(0, 1, 0), _q(0, 0x7FFE, (1 << 112) - 1), _q(1, 0x7FFE, (1 << 112) - 1),
        _q(0, 0x3FFF, 0), _q(1, 0x3FFF, 0), _q(0, 0x4000, 0),
        0x4000921FB54442D18469898CC51701B8, 0x3FFD5555555555555555555555555555,
        _q(0, 0x3FFF, 1 << 111), _q(0, 0x4000, 1 << 110), _q(1, 0x4000, 1 << 110),
        _q(0, 0x7FFF, 0), _q(1, 0x7FFF, 0), _q(0, 0x7FFF, 1 << 111),
        _q(0, 0x7FFF, 1), _q(0, 0x406F, 0), _q(0, 0x406F, 1),
        _q(0, 0x401E, 0), _q(0, 0x401F, 0), _q(0, 0x403E, 0), _q(1, 0x403E, 0),
        _q(0, 0x403F, 0), _q(0, 0x403D, ((1 << 62) - 1) << 50),
        _q(0, 0x3FFE, 0), _q(1, 0x3FFE, 0), _q(0, 0x3FFF, (1 << 112) - 1)]
I32 = [0, 1, 0xFFFFFFFF, 0x7FFFFFFF, 0x80000000, 0x01000001, 0x00FFFFFF,
       0x12345678, 0xFEDCBA98, 0x80000001, 0x7FFFFFC0, 0x7FFFFFC1]
I64 = [0, 1, 0xFFFFFFFFFFFFFFFF, 0x7FFFFFFFFFFFFFFF, 0x8000000000000000,
       0x0020000000000001, 0x001FFFFFFFFFFFFF, 0x123456789ABCDEF0,
       0xFEDCBA9876543210, 0x8000000000000001, 0x7FFFFFFFFFFFFC00,
       0x7FFFFFFFFFFFFC01, 0x00000000FFFFFFFF, 0x0000000100000000]

# TestFloat's flag byte from golden's word - written here from the two
# definitions, not taken from the code under test
GOLDEN_TO_TF = {1: 16, 2: 8, 4: 4, 8: 2, 16: 1}


def tf_flags(word):
    return sum(tf for g, tf in GOLDEN_TO_TF.items() if word & g)


def hexw(v, digits):
    return "%0*X" % (digits, v)


def digits_of(kind):
    return {"f32": 8, "f64": 16, "f128": 32, "i32": 8, "i64": 16,
            "bool": 1}[kind]


def run_subject(binary, fn, mode, exact, lines, env=None):
    args = [binary, fn, mode, "exact" if exact else "notexact"]
    return subprocess.run(args, input=("\n".join(lines) + "\n").encode(),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          env=env)


def cases(fn):
    """Operand tuples (bits) for a function name, ours."""
    kinds, n = xtf.kinds_for(fn)
    if kinds[0] == "int":                       # <int>_to_<float>
        pool = I32 if "32" in fn.split("_")[0] else I64
        return [(v,) for v in pool]
    pool = {"f32": F32, "f64": F64, "f128": F128}[kinds[0]]
    if n == 3:
        small = pool[::3]                        # 10 values: 1,000 triples
        return list(itertools.product(small, repeat=3))
    if n == 2:
        return list(itertools.product(pool, repeat=2))
    return [(v,) for v in pool]


def out_digits(fn):
    kinds, _ = xtf.kinds_for(fn)
    if kinds[-1] == "int":                      # float -> integer
        return 8 if fn.split("_to_")[1].lstrip("u")[1:3] == "32" else 16
    return digits_of(kinds[-1])


def expected_lines(fn, mode, exact):
    kinds, n = xtf.kinds_for(fn)
    gold = xtf.golden_for(fn, mode, exact)
    od = out_digits(fn)
    res = []
    for ops in cases(fn):
        v, fl = gold(*ops)
        if kinds[-1] == "bool":
            v = int(v != 0)
        res.append((" ".join(hexw(o, digits_of(k) if k != "int" else
                                  (8 if "32" in fn.split("_")[0] else 16))
                             for o, k in zip(ops, kinds)),
                    hexw(v, od), hexw(tf_flags(fl), 2)))
    return res


def functions():
    out = []
    for f in ("f32", "f64", "f128"):
        for op in ("add", "sub", "mul", "mulAdd", "div", "sqrt", "rem",
                   "roundToInt", "eq", "le", "lt", "eq_signaling", "le_quiet",
                   "lt_quiet"):
            out.append(f"{f}_{op}")
        for i in ("ui32", "ui64", "i32", "i64"):
            out.append(f"{f}_to_{i}")
            out.append(f"{f}_to_{i}_r_minMag")
    out += ["f32_to_f64", "f64_to_f32", "f128_to_f32", "f128_to_f64",
            "f32_to_f128", "f64_to_f128"]
    for i in ("ui32", "ui64", "i32", "i64"):
        out += [f"{i}_to_f32", f"{i}_to_f64", f"{i}_to_f128"]
    return out


def main(argv):
    if len(argv) != 2:
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    binary = argv[1]
    bad = ntot = 0
    for fn in functions():
        # the _r_minMag names round toward zero whatever mode is given
        modes = ("near_even",) if "_r_minMag" in fn else MODES
        exacts = (False, True) if fn.endswith("roundToInt") or (
            "_to_" in fn and fn.split("_to_")[1].split("_r_")[0]
            in ("ui32", "ui64", "i32", "i64")) else (False,)
        for mode in modes:
            for exact in exacts:
                exp = expected_lines(fn, mode, exact)
                p = run_subject(binary, fn, mode, exact,
                                [e[0] for e in exp])
                if p.returncode != 0:
                    print(f"FAIL {fn} {mode}: rc {p.returncode}: {p.stderr.decode()[-200:]}")
                    bad += 1
                    continue
                got = p.stdout.decode().split("\n")[:-1]
                if len(got) != len(exp):
                    print(f"FAIL {fn} {mode}: {len(got)} lines for {len(exp)} cases")
                    bad += 1
                    continue
                for g, (ops, v, fl) in zip(got, exp):
                    ntot += 1
                    want = f"{ops} {v} {fl}"
                    if g != want:
                        bad += 1
                        if bad <= 12:
                            print(f"FAIL {fn} {mode}{' exact' if exact else ''}: got {g!r} want {want!r}")
    print(f"{ntot} cases over {len(functions())} function names and {len(MODES)} rounding modes: "
          f"{bad} wrong")

    # negative control 1: the sabotage switches must make this check fail
    stream = [e[0] for e in expected_lines("f32_add", "near_even", False)]
    stream = (stream * 4)[:2100]                 # past two sabotaged cases
    exp = expected_lines("f32_add", "near_even", False)
    exp = (exp * 4)[:2100]
    # (switch, period, lines sent, the fewest wrong lines that count as caught):
    # the default period 1,024 and a short stream with CFT_SOAK_SABOTAGE_EVERY
    for sab, every, nlines, least in (("1", None, 2100, 2), ("2", None, 2100, 2),
                                      ("1", "10", 100, 10), ("2", "10", 100, 10)):
        env = dict(os.environ, CFT_SOAK_SABOTAGE=sab)
        if every:
            env["CFT_SOAK_SABOTAGE_EVERY"] = every
        p = run_subject(binary, "f32_add", "near_even", False, stream[:nlines], env)
        got = p.stdout.decode().split("\n")[:-1]
        wrong = sum(g != f"{o} {v} {fl}" for g, (o, v, fl) in zip(got, exp))
        print(f"sabotage {sab} every {every or 1024}: {wrong} wrong lines of {len(got)}")
        if p.returncode != 0 or wrong < least:
            print("FAIL: the sabotaged subject was not caught")
            bad += 1

    # negative control 2: what it does not take is refused by name, status 2
    for name in ("f16_add", "f16_to_f32", "extF80_add", "f128_to_f128",
                 "f32_to_i16",
                 "f32_bogus", "bogus"):
        p = run_subject(binary, name, "near_even", False, [])
        if p.returncode != 2 or b"refused" not in p.stderr:
            print(f"FAIL: {name} not refused by name (rc {p.returncode})")
            bad += 1
    p = run_subject(binary, "f32_add", "near_even", False, ["3F800000"])
    if p.returncode != 2 or b"operand" not in p.stderr:
        print("FAIL: a short line was not refused")
        bad += 1
    print("PASS" if not bad else f"FAILED: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
