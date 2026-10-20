# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""IBM's FPgen test vectors (.fptest) read and run against libcft.

    python3 -I python/external_ibm.py --dir DIR --subject BIN [--show N]

DIR holds IBM's .fptest files (this repository holds none of them: they
carry IBM's copyright and no licence; docs/EXTERNAL-GENERATORS.md). The
syntax is the one IBM's syntax.txt describes: a line is

    <format><op> <round> [<traps>] <operands...> -> <result> [<flags>]

for binary32 and binary64 and the operations + - * *+ / V. Every case is
exactly one of

    comparable     run through cft-tf-subject, value and flags compared
    trap taken     a trap is enabled for an exception the case raises:
                   IEEE 754-1985's trapped results (an overflow or underflow
                   result with the exponent wrapped, no inexact beside it)
                   are not libcft's: flags are sticky data here, never traps
    no result      the result is `#`, which a trap leaves
    unsupported    an operation or format libcft has no TestFloat-style
                   entry for, or a line this reader refuses (counted by
                   reason, never skipped silently)

and every disagreement among the comparable is arbitrated by
python/cft_golden: libcft = golden against IBM's value is a CONVENTION or an
outside error (named below where the cause is identified), libcft against a
golden that agrees with IBM is a libcft defect.
"""

import argparse
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# IBM's rounding words and TestFloat's (the subject's) for the same attribute
ROUNDS = {">": "max", "<": "min", "0": "minMag", "=0": "near_even",
          "=^": "near_maxMag"}
# IBM's operation -> (TestFloat function name suffix, operand count)
OPS = {"+": ("add", 2), "-": ("sub", 2), "*": ("mul", 2),
       "*+": ("mulAdd", 3), "/": ("div", 2), "V": ("sqrt", 1)}
# format -> (TestFloat prefix, exponent bits, fraction bits, bias)
FORMATS = {"b32": ("f32", 8, 23, 127), "b64": ("f64", 11, 52, 1023)}
# libcft's flag word
INVALID, DIVZERO, OVERFLOW, UNDERFLOW, INEXACT = 1, 2, 4, 8, 16
LETTER_FLAG = {"i": INVALID, "z": DIVZERO, "o": OVERFLOW, "u": UNDERFLOW,
               "v": UNDERFLOW, "w": UNDERFLOW, "x": INEXACT}


class Refusal(Exception):
    """A line or an operand this reader will not interpret; the message is
    the reason the count is kept under."""


def encode(tok, fmt):
    """An IBM operand or result word as bits: ('bits', n) for a number or an
    infinity or a zero, ('nan', n) for Q or S (quiet or signaling, signed),
    ('none', 0) for `#`. The significand is <hex integer digit>.<hex digits>
    with the fraction field right-aligned: the digits are the field's bits,
    not a hex fraction."""
    _, eb, mb, bias = FORMATS[fmt]
    top = (1 << (eb + mb))
    if tok == "#":
        return ("none", 0)
    m = re.fullmatch(r"([+-]?)(Q|S)", tok)
    if m:
        quiet = 1 << (mb - 1)
        pay = quiet if m.group(2) == "Q" else 1
        return ("nan", (top if m.group(1) == "-" else 0)
                | (((1 << eb) - 1) << mb) | pay)
    m = re.fullmatch(r"([+-])(Inf|Zero)", tok)
    if m:
        s = top if m.group(1) == "-" else 0
        return ("bits", s | (((1 << eb) - 1) << mb if m.group(2) == "Inf"
                             else 0))
    m = re.fullmatch(r"([+-])([01])\.([0-9A-Fa-f]+)P(-?[0-9]+)", tok)
    if not m:
        raise Refusal("operand is not in the .fptest number syntax")
    s, i, f, e = m.groups()
    frac, e = int(f, 16), int(e)
    if len(f) * 4 < mb or frac >> mb:
        raise Refusal("significand field wider than the format's fraction")
    sign = top if s == "-" else 0
    if i == "1":
        if not (1 - bias <= e <= bias):
            raise Refusal("normal operand with an exponent out of range")
        return ("bits", sign | ((e + bias) << mb) | frac)
    if e != 1 - bias or frac == 0:
        raise Refusal("subnormal operand off the subnormal exponent")
    return ("bits", sign | frac)


def parse_line(line):
    """None for a line that is not a case; else a dict, or a Refusal."""
    if " -> " not in line:
        return None
    t = line.split()
    m = re.fullmatch(r"(b[0-9]+)(\S+)", t[0])
    if not m or len(t) < 4:
        raise Refusal("line does not start <format><op> <round> ...")
    fmt, op = m.groups()
    if fmt not in FORMATS:
        raise Refusal(f"format {fmt}: not binary32 or binary64")
    if op not in OPS:
        raise Refusal(f"operation {op!r}: no libcft entry in this runner")
    if t[1] not in ROUNDS:
        raise Refusal(f"rounding word {t[1]!r}")
    arrow = t.index("->")
    pre, post = t[2:arrow], t[arrow + 1:]
    traps = ""
    if pre and re.fullmatch(r"[xuozi]+", pre[0]):
        traps, pre = pre[0], pre[1:]
    if len(pre) != OPS[op][1]:
        raise Refusal(f"operation {op}: {len(pre)} operands, {OPS[op][1]} expected")
    flags = ""
    if len(post) == 2 and re.fullmatch(r"[xuvwozi]+", post[1]):
        flags = post[1]
    elif len(post) != 1:
        raise Refusal("text after the result that is not a flag word")
    return {"fmt": fmt, "op": op, "round": ROUNDS[t[1]], "traps": traps,
            "ops": [encode(x, fmt) for x in pre], "res": encode(post[0], fmt),
            "flags": sum({LETTER_FLAG[c] for c in flags}),
            "letters": flags}


def classify(c):
    """('comparable'|'trap taken'|'no result', detail)."""
    if c["res"][0] == "none":
        return "no result", "result is #"
    taken = {LETTER_FLAG[l] for l in c["traps"]} & _bits(c["flags"])
    if not taken:
        return "comparable", "no enabled exception occurs" if c["traps"] \
            else "no traps"
    if taken == {INEXACT}:
        # an inexact trap delivers the rounded result: value comparable
        return "comparable", "inexact trap taken (rounded result delivered)"
    return "trap taken", "".join(sorted(
        n for b, n in ((INVALID, "i"), (DIVZERO, "z"), (OVERFLOW, "o"),
                       (UNDERFLOW, "u")) if b in taken))


def _bits(w):
    return {b for b in (INVALID, DIVZERO, OVERFLOW, UNDERFLOW, INEXACT)
            if w & b}


def tf_to_cft(w):
    """TestFloat's flag byte (inexact 1, underflow 2, overflow 4, infinite
    8, invalid 16) as libcft's word."""
    return ((INEXACT if w & 1 else 0) | (UNDERFLOW if w & 2 else 0)
            | (OVERFLOW if w & 4 else 0) | (DIVZERO if w & 8 else 0)
            | (INVALID if w & 16 else 0))


def run_subject(subject, fn, mode, cases):
    """cft-tf-subject over the operands of `cases` (one function, one mode):
    the (result bits, libcft flag word) of each, in order."""
    fmt = FORMATS[cases[0]["fmt"]]
    nd = 8 if fmt[0] == "f32" else 16
    text = "".join(" ".join("%0*X" % (nd, o[1]) for o in c["ops"]) + "\n"
                   for c in cases)
    p = subprocess.run([subject, fn, mode], input=text.encode(),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise SystemExit(f"{subject} {fn} {mode}: rc {p.returncode}: "
                         f"{p.stderr.decode()[-300:]}")
    out = []
    for ln in p.stdout.decode().split("\n")[:-1]:
        w = ln.split()
        out.append((int(w[-2], 16), tf_to_cft(int(w[-1], 16))))
    assert len(out) == len(cases), (fn, mode, len(out), len(cases))
    return out


def golden(c):
    import cft_golden as g
    f = {"b32": g.FP32, "b64": g.FP64}[c["fmt"]]
    rnd = {"max": g.RND_RUP, "min": g.RND_RDN, "minMag": g.RND_RTZ,
           "near_even": g.RND_RNE, "near_maxMag": g.RND_RMM}[c["round"]]
    a = [o[1] for o in c["ops"]]
    return {"+": lambda: g.add(f, a[0], a[1], rnd),
            "-": lambda: g.sub(f, a[0], a[1], rnd),
            "*": lambda: g.mul(f, a[0], a[1], rnd),
            "*+": lambda: g.fma(f, a[0], a[1], a[2], rnd),
            "/": lambda: g.div(f, a[0], a[1], rnd),
            "V": lambda: g.sqrt(f, a[0], rnd)}[c["op"]]()


def value_ok(c, got):
    kind, want = c["res"]
    if kind == "nan":
        mb = FORMATS[c["fmt"]][2]
        eb = FORMATS[c["fmt"]][1]
        return ((got >> mb) & ((1 << eb) - 1)) == (1 << eb) - 1 and \
            (got & ((1 << mb) - 1)) != 0
    if kind == "bitsnz":     # the bits but for the sign (UCBTEST's `eqz`)
        eb, mb = FORMATS[c["fmt"]][1:3]
        return (got ^ want) & ~(1 << (eb + mb)) == 0
    return got == want


def tiny_before(c):
    """Would tininess detected BEFORE rounding hold for this case: the exact
    result non-zero and below the smallest normal in magnitude. Fractions,
    for + - * *+ / over finite operands; None where it does not apply."""
    _, eb, mb, bias = FORMATS[c["fmt"]]

    def val(bits):
        s = -1 if bits >> (eb + mb) else 1
        e = (bits >> mb) & ((1 << eb) - 1)
        f = bits & ((1 << mb) - 1)
        if e == (1 << eb) - 1:
            return None
        return s * (Fraction(f, 1 << mb) * Fraction(2) ** (1 - bias) if e == 0
                    else (1 + Fraction(f, 1 << mb)) * Fraction(2) ** (e - bias))
    v = [val(o[1]) for o in c["ops"]]
    if None in v:
        return None
    op = c["op"]
    if op == "+": x = v[0] + v[1]
    elif op == "-": x = v[0] - v[1]
    elif op == "*": x = v[0] * v[1]
    elif op == "*+": x = v[0] * v[1] + v[2]
    elif op == "/":
        if v[1] == 0:
            return None
        x = v[0] / v[1]
    else:
        return None
    return x != 0 and abs(x) < Fraction(2) ** (1 - bias)


def before_rounding_flags(c, gf):
    """The flags tininess detected BEFORE rounding would give a case whose
    golden flags (tininess after rounding) are gf: underflow iff the exact
    result is non-zero and below the smallest normal and the delivered
    result inexact; every other bit as golden has it."""
    tb = tiny_before(c)
    if tb is None:
        return gf
    return (gf | UNDERFLOW) if (tb and gf & INEXACT) else (gf & ~UNDERFLOW)


def judge(c, bits, fl, gb, gf):
    """None if libcft's (bits, fl) is what the case expects; else the name
    of the class of the disagreement, arbitrated by golden's (gb, gf):
      libcft = golden, IBM expects otherwise   a convention or an outside
                                               error, named where the cause
                                               is identified
      LIBCFT DEFECT                            golden agrees with IBM
      all three differ                         neither side is golden"""
    mask = c.get("mask", 31)     # the flags a vector leaves unchecked (UCBTEST's `?x`)
    v_ok = value_ok(c, bits)
    if v_ok and (fl ^ c["flags"]) & mask == 0:
        return None
    if (bits, fl) == (gb, gf):
        cls = "libcft = golden, IBM expects otherwise"
        diff = (fl ^ c["flags"]) & mask
        if v_ok and diff == UNDERFLOW:
            # the structural check of the explanation: the two detections of
            # tininess differ only when rounding carries the result up to the
            # smallest normal number
            eb, mb = FORMATS[c["fmt"]][1:3]
            at_min_normal = (gb & ~(1 << (eb + mb))) == (1 << mb)
            cls += (": underflow flag only, = tininess BEFORE rounding"
                    if (before_rounding_flags(c, gf) ^ c["flags"]) & mask == 0
                    else
                    ": underflow flag only, NOT explained by tininess "
                    "before rounding")
            cls += (", result = smallest normal" if at_min_normal
                    else ", result NOT the smallest normal")
        else:
            cls += ": value" if not v_ok else ": flags " + "".join(
                n for b, n in ((INVALID, "i"), (DIVZERO, "z"),
                               (OVERFLOW, "o"), (UNDERFLOW, "u"),
                               (INEXACT, "x")) if diff & b)
        return cls
    if value_ok(c, gb) and (gf ^ c["flags"]) & mask == 0:
        return "LIBCFT DEFECT: libcft differs from golden = IBM"
    return "all three differ"


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--show", type=int, default=10,
                    help="how many cases of each disagreement class to name")
    a = ap.parse_args(argv)

    cases, refused, nheader = [], Counter(), 0
    for name in sorted(os.listdir(a.dir)):
        if not name.endswith(".fptest"):
            continue
        with open(os.path.join(a.dir, name), "rb") as f:
            text = f.read().decode("latin-1")
        for n, line in enumerate(text.split("\n"), 1):
            try:
                c = parse_line(line)
            except Refusal as e:
                refused[str(e)] += 1
                continue
            if c is None:
                nheader += 1
                continue
            c["where"] = f"{name}:{n}"
            c["kind"], c["why"] = classify(c)
            cases.append(c)

    print(f"{len(cases)} cases read, {sum(refused.values())} lines refused, "
          f"{nheader} other lines")
    for r, k in refused.most_common():
        print(f"  refused x{k}: {r}")
    by_kind = Counter((c["fmt"], c["kind"], c["why"]) for c in cases)
    for k, v in sorted(by_kind.items()):
        print(f"  {v:>6}  {k[0]}  {k[1]}: {k[2]}")
    print("  by operation and format:", dict(Counter(
        (c["fmt"], c["op"]) for c in cases)))

    # trapped cases whose operands also appear untrapped in the same file
    twin = {(c["where"].split(":")[0], c["fmt"], c["op"], c["round"],
             tuple(c["ops"])) for c in cases if not c["traps"]}
    taken = [c for c in cases if c["kind"] == "trap taken"]
    withtwin = sum((c["where"].split(":")[0], c["fmt"], c["op"], c["round"],
                    tuple(c["ops"])) in twin for c in taken)
    print(f"  trap taken: {len(taken)}, of which {withtwin} have the same "
          f"operands and rounding untrapped in the same file")

    groups = defaultdict(list)
    for c in cases:
        if c["kind"] == "comparable":
            groups[(FORMATS[c["fmt"]][0] + "_" + OPS[c["op"]][0],
                    c["round"])].append(c)
    mism = Counter()
    shown = Counter()
    ncomp = 0
    sens = Counter()   # tininess-sensitive cases, and whom IBM sides with
    for (fn, mode), cs in sorted(groups.items()):
        for c, (bits, fl) in zip(cs, run_subject(a.subject, fn, mode, cs)):
            ncomp += 1
            gb, gf = golden(c)
            pred = before_rounding_flags(c, gf)
            if pred != gf:
                sens["cases the two conventions flag differently"] += 1
                sens["  IBM's flags = the before-rounding prediction"] += \
                    c["flags"] == pred
                sens["  IBM's flags = golden's (after rounding)"] += \
                    c["flags"] == gf
                sens["  libcft's flags = golden's (after rounding)"] += \
                    fl == gf
            cls = judge(c, bits, fl, gb, gf)
            if cls is None:
                continue
            key = (c["fmt"], c["op"], cls)
            mism[key] += 1
            if shown[key] < a.show:
                shown[key] += 1
                print(f"    {cls}: {c['where']} {c['fmt']}{c['op']} "
                      f"{c['round']} traps={c['traps'] or '-'}")
    print(f"{ncomp} comparable cases run through libcft, "
          f"{sum(mism.values())} disagreements")
    for k, v in sens.items():
        print(f"  {v:>6}  {k}")
    for k, v in sorted(mism.items()):
        print(f"  {v:>6}  {k[0]}{k[1]}  {k[2]}")
    return 1 if any("DEFECT" in k[2] or "all three" in k[2] for k in mism) \
        else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
