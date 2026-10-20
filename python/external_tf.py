# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Berkeley TestFloat against libcft: run the pipelines, then arbitrate.

    testfloat_gen ... F | cft-tf-subject F ... | testfloat_ver ... F

for every function this library has over binary32 and binary64 (binary128
with --wide), every rounding mode both libraries share, and the exact /
not-exact variants of the conversions to integer and roundToInt.
testfloat_gen and testfloat_ver are built from TestFloat 3e and SoftFloat 3e
in a directory of the caller's; nothing of theirs is in this repository
(docs/EXTERNAL-GENERATORS.md).

    python3 -I python/external_tf.py run --tf DIR --subject BIN --out DIR
            [--level 1|2] [--wide] [--only A,B] [--skip A,B] [--modes M,N]
            [--limit N] [--ver-flags=-checkNaNs] [--tininess before|after]
            [--max-errors N]
    python3 -I python/external_tf.py arbitrate --out DIR
            [--by-file] [--nan-bits] [--sample N]

`run` prints one row a pipeline (level, function, mode, exactness, tests,
errors, seconds, the exit statuses of all its processes, ok|BAD), appends
them to DIR/summary.tsv, and keeps testfloat_ver's error lines in
DIR/errors/. A level-2 mulAdd is refused without --limit: its stream is
2 x 1936^3 cases a mode at binary32, and --limit N takes its first N lines.
`arbitrate` re-computes each reported case with python/cft_golden - the
authority - and says, class by class, who agrees with whom; a case whose
operands are the fused multiply-add row 0 x infinity + quiet NaN is named
so, from the operands, not assumed.

The subject opens the software backend unless CFT_SOAK_ARTIFACT names an
.xclbin, exactly as the soak tools do, so the lead can run this on a card.
"""

import argparse
import os
import re
import subprocess
import sys
import time
from collections import Counter

ROUNDS = ("near_even", "near_maxMag", "minMag", "min", "max")
ROUND_OPT = {"near_even": "-rnear_even", "near_maxMag": "-rnear_maxMag",
             "minMag": "-rminMag", "min": "-rmin", "max": "-rmax"}
FLOATS = ("f32", "f64")
ALL_FLOATS = ("f32", "f64", "f128")
# (exponent bits, fraction bits) of each binary format
WIDTHS = {"f32": (8, 23), "f64": (11, 52), "f128": (15, 112)}
INTS = ("ui32", "ui64", "i32", "i64")


def function_table(wide=False):
    """(function, modes, exacts): the pipelines to run, as TestFloat names
    them. modes is ROUNDS or ("near_even",) for a function that does not
    round (its mode argument is ignored by TestFloat); exacts is (False,)
    or (False, True) for the functions that have an -exact. wide=True is
    the binary128 table instead of the binary32 and binary64 one."""
    one = ("near_even",)
    rows = []
    if wide:
        rows += [(f"f128_{op}", ROUNDS, (False,)) for op in
                 ("add", "sub", "mul", "mulAdd", "div", "sqrt")]
        rows.append(("f128_roundToInt", ROUNDS, (False, True)))
        rows += [(f"f128_to_{i}", ROUNDS, (False, True)) for i in INTS]
        rows += [(f"f128_{op}", one, (False,)) for op in
                 ("rem", "eq", "le", "lt", "eq_signaling", "le_quiet",
                  "lt_quiet")]
        rows += [("f128_to_f32", ROUNDS, (False,)),
                 ("f128_to_f64", ROUNDS, (False,)),
                 ("f32_to_f128", one, (False,)),
                 ("f64_to_f128", one, (False,))]
        rows += [(f"{i}_to_f128", one, (False,)) for i in INTS]
        return rows
    for f in FLOATS:
        for op in ("add", "sub", "mul", "mulAdd", "div", "sqrt"):
            rows.append((f"{f}_{op}", ROUNDS, (False,)))
        rows.append((f"{f}_roundToInt", ROUNDS, (False, True)))
        for i in INTS:
            # testfloat_gen and testfloat_ver have no _r_minMag names (those
            # are the all-in-one testfloat's); -rminMag does the same job
            rows.append((f"{f}_to_{i}", ROUNDS, (False, True)))
        for op in ("rem", "eq", "le", "lt", "eq_signaling", "le_quiet",
                   "lt_quiet"):
            rows.append((f"{f}_{op}", one, (False,)))
    rows.append(("f32_to_f64", one, (False,)))
    rows.append(("f64_to_f32", ROUNDS, (False,)))
    for i in INTS:
        rows.append((f"{i}_to_f32", ROUNDS, (False,)))
        rows.append((f"{i}_to_f64", one if i in ("ui32", "i32") else ROUNDS,
                     (False,)))
    return rows


def pipeline(tf, subject, fn, mode, exact, level, limit, ver_flags, errors,
             tininess="after"):
    ro = ROUND_OPT[mode]
    ex = "-exact" if exact else "-notexact"
    common = f"{ro} -tininess{tininess} {ex}"
    gen = f"{tf}/testfloat_gen -level {level} {common} {fn}"
    if limit:
        gen += f" | head -n {int(limit)}"
    subj = f"{subject} {fn} {mode} {'exact' if exact else 'notexact'}"
    ver = f"{tf}/testfloat_ver -errors {errors} {common} {ver_flags} {fn}"
    return f"{gen} | {subj} | {ver}", gen.count("|") + 3


def run_one(tf, subject, out, fn, mode, exact, level, limit, ver_flags,
            tininess="after", max_errors=100000):
    tag = f"L{level}.{fn}.{mode}.{'x' if exact else 'n'}"
    cmd, nproc = pipeline(tf, subject, fn, mode, exact, level, limit,
                          ver_flags, max_errors, tininess)
    ver_out = os.path.join(out, "errors", tag + ".out")
    ver_err = os.path.join(out, "errors", tag + ".err")
    script = (f"{cmd} > '{ver_out}' 2> '{ver_err}'\n"
              'echo "${PIPESTATUS[@]}"\n')
    t0 = time.time()
    p = subprocess.run(["bash", "-c", script], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, universal_newlines=True)
    secs = time.time() - t0
    statuses = p.stdout.split()
    text = open(ver_err, encoding="latin-1").read().replace("\r", "\n")
    m = re.findall(r"(\d+) tests performed(?:; (\d+) errors? found)?\.", text)
    tests = int(m[-1][0]) if m else -1
    errs = int(m[-1][1] or 0) if m else -1
    # the exit statuses must be what a healthy run gives: the generator 0
    # (141 when `head` closed it on purpose), the subject 0, the verifier 0
    # or 1 (1 is "errors found"), and nothing else
    ok = bool(m) and len(statuses) == nproc and statuses[-1] in ("0", "1") \
        and statuses[-2] == "0" and statuses[0] in (("0", "141") if limit
                                                    else ("0",))
    if ok and errs == 0:
        os.remove(ver_out)
        os.remove(ver_err)
    if not ok:
        print("NOT HEALTHY:", tag, statuses, p.stderr[-400:], file=sys.stderr)
    return (level, fn, mode, "exact" if exact else "notexact", tests, errs,
            round(secs, 1), ",".join(statuses), "ok" if ok else "BAD")


def cmd_run(a):
    os.makedirs(os.path.join(a.out, "errors"), exist_ok=True)
    rows = []
    for fn, modes, exacts in function_table(a.wide):
        if a.only and not any(o in fn for o in a.only.split(",")):
            continue
        if a.skip and any(o in fn for o in a.skip.split(",")):
            continue
        if fn.endswith("_mulAdd") and a.level == 2 and not a.limit:
            # 2 * 1936^3 = 14,512,627,712 cases a mode at f32 and 1.8e11 at
            # f64 (genCases_f32.c, genCases_f64.c): never run it unbounded
            print(f"skipped {fn}: level 2 needs --limit", file=sys.stderr)
            continue
        for mode in modes:
            if a.modes and mode not in a.modes.split(","):
                continue
            for exact in exacts:
                r = run_one(a.tf, a.subject, a.out, fn, mode, exact, a.level,
                            a.limit if fn.endswith("_mulAdd") else 0,
                            a.ver_flags, a.tininess, a.max_errors)
                rows.append(r)
                print("\t".join(str(x) for x in r), flush=True)
    with open(os.path.join(a.out, "summary.tsv"), "a") as f:
        for r in rows:
            f.write("\t".join(str(x) for x in r) + "\n")
    bad = [r for r in rows if r[-1] != "ok"]
    tests = sum(r[4] for r in rows if r[4] > 0)
    errs = sum(r[5] for r in rows if r[5] > 0)
    print(f"{len(rows)} pipelines, {tests} tests, {errs} errors reported, "
          f"{len(bad)} pipelines not healthy")
    return 1 if bad else 0


# ---- arbitration -----------------------------------------------------------

_FLT = re.compile(r"^([+-])([0-9A-Fa-f]+)\.([0-9A-Fa-f]+)$")


def decode_value(tok, kind):
    """A value as testfloat_ver prints it back to bits. Floats print as
    sign, encoded exponent, '.', encoded significand; integers as raw hex;
    a Boolean as 0 or 1."""
    m = _FLT.match(tok)
    if m and kind in WIDTHS:
        eb, mb = WIDTHS[kind]
        s, e, f = m.groups()
        return ((1 if s == "-" else 0) << (eb + mb)) | (int(e, 16) << mb) \
            | int(f, 16)
    return int(tok, 16)


def decode_flags(tok):
    """testfloat_ver's five flag characters, v i o u x or a dot each, as
    libcft's flag word (invalid 1, divide by zero 2, overflow 4,
    underflow 8, inexact 16)."""
    assert len(tok) == 5, tok
    w = 0
    for ch, bit in zip(tok, (1, 2, 4, 8, 16)):
        if ch != ".":
            w |= bit
    return w


def split_error_lines(text):
    """testfloat_ver's error lines, continuations (a tab) joined."""
    lines = []
    for ln in text.splitlines():
        if ln.startswith("\t") and lines:
            lines[-1] += " " + ln.strip()
        elif ln.strip() and not ln.startswith("Errors found"):
            lines.append(ln)
    return lines


def parse_error(line, nops, kinds):
    """(operand bits..., observed bits, observed flags, expected bits,
    expected flags) from `a b => z fl  expected z fl`."""
    head, tail = line.split("=>")
    ops = head.split()
    obs, exp = tail.split("expected")
    ov, ofl = obs.split()
    ev, efl = exp.split()
    assert len(ops) == nops, line
    return ([decode_value(t, k) for t, k in zip(ops, kinds[:nops])],
            decode_value(ov, kinds[-1]), decode_flags(ofl),
            decode_value(ev, kinds[-1]), decode_flags(efl))


def golden_for(fn, mode, exact):
    """A function (operand bits...) -> (result bits, libcft flag word) from
    python/cft_golden, the authority, for a TestFloat function name; None
    where the golden model has no such operation."""
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import cft_golden as g
    rnd = {"near_even": g.RND_RNE, "near_maxMag": g.RND_RMM,
           "minMag": g.RND_RTZ, "min": g.RND_RDN, "max": g.RND_RUP}[mode]
    fm = {"f32": g.FP32, "f64": g.FP64, "f128": g.FP128}
    m = re.match(r"^(f32|f64|f128)_(add|sub|mul|mulAdd|div|sqrt|roundToInt|rem)$",
                 fn)
    if m:
        f, op = fm[m.group(1)], m.group(2)
        return {"add": lambda a, b: g.add(f, a, b, rnd),
                "sub": lambda a, b: g.sub(f, a, b, rnd),
                "mul": lambda a, b: g.mul(f, a, b, rnd),
                "mulAdd": lambda a, b, c: g.fma(f, a, b, c, rnd),
                "div": lambda a, b: g.div(f, a, b, rnd),
                "sqrt": lambda a: g.sqrt(f, a, rnd),
                "rem": lambda a, b: g.remainder(f, a, b),
                "roundToInt": lambda a: g.round_int(f, a, rnd, exact)}[op]
    m = re.match(r"^(f32|f64|f128)_(eq|le|lt|eq_signaling|le_quiet|lt_quiet)$", fn)
    if m:
        f = fm[m.group(1)]
        c = {"eq": g.cmpeq, "le": g.cmple_sig, "lt": g.cmplt_sig,
             "eq_signaling": g.cmpeq_sig, "le_quiet": g.cmple,
             "lt_quiet": g.cmplt}[m.group(2)]
        return lambda a, b: c(f, a, b)
    m = re.match(r"^(f32|f64|f128)_to_(f32|f64|f128)$", fn)
    if m:
        return lambda a: g.convert(fm[m.group(1)], fm[m.group(2)], a, rnd)
    m = re.match(r"^(ui32|ui64|i32|i64)_to_(f32|f64|f128)$", fn)
    if m:
        w = 32 if "32" in m.group(1) else 64
        signed = not m.group(1).startswith("u")

        def from_int(v):
            if signed and v >> (w - 1):
                v -= 1 << w
            return g.from_int(fm[m.group(2)], v, rnd)
        return from_int
    m = re.match(r"^(f32|f64|f128)_to_(ui32|ui64|i32|i64)(_r_minMag)?$", fn)
    if m:
        w = 32 if "32" in m.group(2) else 64
        signed = not m.group(2).startswith("u")
        r = g.RND_RTZ if m.group(3) else rnd

        def to_int(a):
            v, fl = g.to_int(fm[m.group(1)], a, w, signed, r, exact)
            return v & ((1 << w) - 1), fl
        return to_int
    return None


def kinds_for(fn):
    """The value kinds of a function's operands and result, in order."""
    m = re.match(r"^(f32|f64|f128)_(.*)$", fn)
    if m:
        f, rest = m.groups()
        n = 3 if rest == "mulAdd" else 2 if rest in (
            "add", "sub", "mul", "div", "rem", "eq", "le", "lt",
            "eq_signaling", "le_quiet", "lt_quiet") else 1
        if rest.startswith("to_"):
            tgt = rest[3:].split("_")[0]
            res = tgt if tgt in ALL_FLOATS else "int"
        elif rest in ("eq", "le", "lt", "eq_signaling", "le_quiet",
                      "lt_quiet"):
            res = "bool"
        else:
            res = f
        return [f] * n + [res], n
    m = re.match(r"^(ui32|ui64|i32|i64)_to_(f32|f64|f128)$", fn)
    return ["int", m.group(2)], 1


def classify_error(fn, mode, exact, line, nan_bits=False, gold=None):
    """One testfloat_ver error line, against the golden model: the class
    (name, detail) and the line's decoded parts. The classes:
      libcft = golden != SoftFloat   the outside expected value is the
                                     odd one: a convention difference or an
                                     outside error, named by `why`
      libcft != golden = SoftFloat   a libcft defect
      all three differ               neither side is the golden model
      both agree with golden         the line is no error: a bug in this tool
    nan_bits: the run was made with -checkNaNs, so SoftFloat's NaN bits are
    held to golden's too; by default a NaN against a NaN is equal."""
    kinds, nops = kinds_for(fn)
    ops, ov, ofl, ev, efl = parse_error(line, nops, kinds)
    gold = gold or golden_for(fn, mode, exact)
    if gold is None:
        return ("no golden model for this function", fn)
    gv, gfl = gold(*ops)
    if kinds[-1] == "bool":
        gv = int(gv != 0)
    lib_ok = (ov, ofl) == (gv, gfl)
    sf_ok = (ev == gv if nan_bits else same_value(kinds[-1], ev, gv)) \
        and efl == gfl
    if lib_ok and not sf_ok:
        return ("libcft = golden, SoftFloat differs",
                why(fn, ops, ov, ofl, ev, efl, kinds))
    if sf_ok and not lib_ok:
        return ("LIBCFT DEFECT: libcft differs from golden = SoftFloat", fn)
    if lib_ok and sf_ok:
        return ("both agree with golden (the error line is a bug in this "
                "tool)", fn)
    return ("all three differ", fn)


def cmd_arbitrate(a):
    """Every reported case, class by class (classify_error). The counts go
    to stdout, the cases of a defect or three-way class to stderr: those
    are the findings."""
    edir = os.path.join(a.out, "errors")
    classes = Counter()
    perfile = Counter()
    examples = {}
    total = 0
    for name in sorted(os.listdir(edir)):
        if not name.endswith(".out"):
            continue
        m = re.match(r"^L(\d)\.(.+)\.([^.]+)\.([xn])\.out$", name)
        level, fn, mode, ex = m.groups()
        gold = golden_for(fn, mode, ex == "x")
        text = open(os.path.join(edir, name), encoding="latin-1").read()
        for k, line in enumerate(split_error_lines(text)):
            if a.sample and k >= a.sample:
                classes[(level, "not arbitrated (past --sample)", fn)] += 1
                continue
            total += 1
            cls = classify_error(fn, mode, ex == "x", line, a.nan_bits, gold)
            if cls[0].startswith(("LIBCFT DEFECT", "all three")):
                print("FINDING", name, cls[0], line, file=sys.stderr)
            classes[(level,) + cls] += 1
            perfile[(fn, mode, "exact" if ex == "x" else "notexact") + cls] += 1
            examples.setdefault((level,) + cls, line)
    for k, v in sorted(classes.items()):
        print(f"{v:>9}  L{k[0]}  {k[1]}  [{k[2]}]")
        print(f"           e.g. {examples.get(k, '')}")
    if getattr(a, "by_file", False):
        for k, v in sorted(perfile.items()):
            print(f"{v:>9}  {k[0]} {k[1]} {k[2]}  {k[3]}  [{k[4]}]")
    print(f"{total} reported cases, {len(classes)} classes")
    return 0


def is_nan(kind, bits):
    if kind not in WIDTHS:
        return False
    eb, mb = WIDTHS[kind]
    return ((bits >> mb) & ((1 << eb) - 1)) == (1 << eb) - 1 and \
        (bits & ((1 << mb) - 1)) != 0


def same_value(kind, x, y):
    """Equal, or both NaNs: TestFloat does not check NaN bits by default
    (its docs, section 8.2), so SoftFloat's value is held to that."""
    return x == y or (is_nan(kind, x) and is_nan(kind, y))


def why(fn, ops, ov, ofl, ev, efl, kinds):
    """Name the feature on which libcft (= golden) and SoftFloat part: the
    flag bits that differ and whether the values do (a NaN against a NaN
    does not count: the payload is a convention of its own)."""
    names = ((1, "invalid"), (2, "divByZero"), (4, "overflow"),
             (8, "underflow"), (16, "inexact"))
    diff = "+".join(n for b, n in names if (ofl ^ efl) & b)
    if ov == ev:
        vtxt = "flags only"
    elif is_nan(kinds[-1], ov) and is_nan(kinds[-1], ev):
        vtxt = "NaN bits"
    else:
        vtxt = "value"
    note = ""
    if fn.endswith("_mulAdd"):
        note = ("; product 0*inf, quiet-NaN addend"
                if fma_inf_zero_qnan(kinds[0], ops)
                else "; NOT the 0*inf + quiet NaN row")
    return f"{fn}: {vtxt}" + (f", flag {diff}" if diff else "") + note


def fma_inf_zero_qnan(kind, ops):
    """True when a fused multiply-add's product is 0 * infinity (either way
    round) and its addend a quiet NaN: the one row on which TestFloat expects
    invalid and the contract's NaN-in rule gives none."""
    a, b, c = ops
    eb, mb = WIDTHS[kind]
    expmask = ((1 << eb) - 1) << mb

    def mag(x):
        return x & ~(1 << (eb + mb))
    prod = (mag(a) == 0 and mag(b) == expmask) or \
        (mag(a) == expmask and mag(b) == 0)
    return prod and is_nan(kind, c) and bool(c & (1 << (mb - 1)))


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--tf", required=True, help="dir with testfloat_gen/ver")
    r.add_argument("--subject", required=True, help="cft-tf-subject")
    r.add_argument("--out", required=True)
    r.add_argument("--level", type=int, choices=(1, 2), default=1)
    r.add_argument("--only", default="", help="functions containing this")
    r.add_argument("--skip", default="", help="but not these (comma-separated)")
    r.add_argument("--modes", default="", help="only these rounding modes (comma-separated, TestFloat's words)")
    r.add_argument("--limit", type=int, default=0,
                   help="mulAdd only: the first N generated lines")
    r.add_argument("--ver-flags", default="", help="extra testfloat_ver flags")
    r.add_argument("--max-errors", type=int, default=100000,
                   help="testfloat_ver -errors (0: unlimited)")
    r.add_argument("--wide", action="store_true",
                   help="the binary128 functions instead of binary32 and binary64")
    r.add_argument("--tininess", choices=("after", "before"), default="after",
                   help="given to testfloat_gen and testfloat_ver (libcft: after)")
    r.set_defaults(fn=cmd_run)
    b = sub.add_parser("arbitrate")
    b.add_argument("--out", required=True)
    b.add_argument("--nan-bits", action="store_true",
                   help="the run was made with -checkNaNs: NaN bits count")
    b.add_argument("--by-file", action="store_true",
                   help="also the count of each class for every function and mode")
    b.add_argument("--sample", type=int, default=0,
                   help="arbitrate at most this many cases a file (0: all)")
    b.set_defaults(fn=cmd_arbitrate)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
