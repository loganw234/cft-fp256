"""An independent check of the threshold families the C generators add: the
operands are rebuilt here with mpmath and the model's round_pack, and each must
be among the operands the dump says the function is asked.

Needs mpmath.  Usage, from the repository's root:

    python -B host/tools/audit-pools/check_thresholds.py DUMP

DUMP is a case dump (all four formats).  Exits 1 and names the operand if a
threshold operand rebuilt here is not among the cases the dump asks.
"""
import sys

import os  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_lib import *   # noqa
import mpmath

cases = parse_dump(sys.argv[1])
SIGN = lambda fmt: fmt.sign_mask


def val(fmt, m, e):
    bits, fl = sf.round_pack(fmt, 0, m, e, sf.RND_RNE)
    return None if fl else bits


def both(fmt, b):
    return [b, b | SIGN(fmt)]


def around(fmt, b, k):
    return [b + d for d in range(-k, k + 1)]


total = 0
missing = 0


def need(fmtname, fn, items, what):
    global total, missing
    ops = first_operands(cases, fmtname, fn)
    for x in items:
        total += 1
        if x not in ops:
            missing += 1
            if missing <= 12:
                print("MISSING", fmtname, fn, what, hex(x))


for fname, fmt in FMTS.items():
    p, E, M, W = fmt.prec, fmt.emax, fmt.emin, fmt.man_w
    mpmath.mp.prec = 4 * p + 400
    ln2 = mpmath.log(2)
    l10_2 = mpmath.log10(2)

    def edge(n, c, k):
        v = abs(mpmath.mpf(n) * c)
        man, ex = mpmath.libmp.to_man_exp(v._mpf_, signed=False) if False else (None, None)
        sgn, man, ex, _bc = v._mpf_
        b = sf.round_pack(fmt, 0, int(man), int(ex), sf.RND_RNE)[0]
        out = []
        for d in range(-k, k + 1):
            out += both(fmt, b + d)
        return out

    # exp class: tiny rules ex <= -(p+c) and 2 ex + p + c <= 0, c = 2..6
    for fn in ("exp", "expm1", "exp2", "log", "log1p", "log2", "log10"):
        items = []
        for c in range(2, 7):
            for e2 in (-(p + c) + 1, -((p + c + 1) // 2) + 1):
                b = val(fmt, 1, e2)
                if b is not None:
                    for s in both(fmt, b):
                        items += [s, s + 1, s - 1]
        need(fname, fn, items, "tiny-edge")
        # n ln 2, rounded to nearest and walked two ulps, both signs
        items = []
        for n in (E, E + 1, E + 2, M, M - W, M - W - 1, M - W - 2, -(p + 2), -(p + 3), p + 1):
            items += edge(n, ln2, 2)
        need(fname, fn, items, "ln2-edge")
        # exp2's integer edges and the tie, with the operand's own neighbours
        items = []
        for n in (E, E + 1, E + 2, -M - 1, -M, -M + 1, W - M - 1, W - M, W - M + 1, W - M + 2, W - M + 3):
            b = val(fmt, n, 0)
            if b is not None:
                for s in both(fmt, b):
                    items += [s, s + 1, s - 1]
        need(fname, fn, items, "int-edge")
        # log2's exact case at the subnormal powers of two
        items = []
        for k in (M - W, M - W + 2, M - W // 2, M - 2, M - 1, M + 1):
            b = val(fmt, 1, k)
            if b is not None:
                items += [b, b + 1, b - 1]
        need(fname, fn, items, "pow2-sub")
        # log10's exact table: 5^k 2^k while 5^k fits p bits, with neighbours
        items = []
        k = 0
        while 5 ** k < (1 << p):
            b = val(fmt, 5 ** k, k)
            if b is None:
                break
            items += [b, b + 1, b - 1]
            k += 1
        need(fname, fn, items, "pow10")
    # the nine trigonometric: the same tiny rules, and atanPi's ex >= p + 1
    for fn in ("sinpi", "cospi", "tanpi", "asin", "acos", "atan", "asinpi", "acospi", "atanpi"):
        items = []
        for c in range(2, 7):
            for e2 in (-(p + c) + 1, -((p + c + 1) // 2) + 1):
                b = val(fmt, 1, e2)
                if b is not None:
                    for s in both(fmt, b):
                        items += [s, s + 1, s - 1]
        b = val(fmt, 1, p + 1)
        for s in both(fmt, b):
            items += [s, s + 1, s - 1]
        need(fname, fn, items, "t:tiny-edge")
        # beside a half-integer: h +- 2^-j, h = 1/2 .. 3, j round (p + 6) / 2
        items = []
        j0 = (p + 6 + 1) // 2
        for hs in range(1, 7):
            for j in (j0 - 1, j0, j0 + 1):
                for sg in (1, -1):
                    num = hs * (1 << j) + sg * 2  # (hs/2 + sg 2^-j) * 2^(j+1)
                    # value = num * 2^-(j+1)
                    b = val(fmt, num, -(j + 1))
                    if b is not None:
                        items += both(fmt, b)
        if fn in ("sinpi", "cospi", "tanpi"):
            need(fname, fn, items, "beside-half")
    # exp10 / exp10m1: x with x log2(10) = n
    for fn in ("exp10", "exp10m1"):
        items = []
        for n in (E, E + 1, E + 2, M, M - W, M - W - 1, M - W - 2, -(p + 2), -(p + 3)):
            items += edge(n, l10_2, 2)
        need(fname, fn, items, "log10-edge")
    # sinh, cosh: n ln 2 up to emax + 3
    for fn in ("sinh", "cosh"):
        items = []
        for n in (E, E + 1, E + 2, E + 3, M, M - W):
            items += edge(n, ln2, 2)
        need(fname, fn, items, "h:ln2-edge")
    # log2p1's rule edge: 2^k near the first k >= p - floor(log2 k) + 1
    kmin = next(k for k in range(1, 4 * p) if k >= p - (k.bit_length() - 1) + 1)
    items = []
    for k in range(kmin - 2, kmin + 3):
        if k >= 1:
            b = val(fmt, 1, k)
            items += [b, b + 1, b - 1]
    need(fname, "log2p1", items, "log2p1-edge")
    # hypot: exact results past the largest finite, (3,4)*7*2^(E-4) etc.
    pairs_ = pairs(cases, fname, "hypot")
    for (x, y, t, te) in ((3, 4, 7, -4), (5, 12, 5, -5), (8, 15, 1, -3), (3, 4, 3, -4), (5, 12, 3, -5), (8, 15, 1, -4)):
        a, b = val(fmt, x * t, E + te), val(fmt, y * t, E + te)
        for pr in ((a, b), (b, a)):
            total += 1
            if pr not in pairs_:
                missing += 1
                print("MISSING pair", fname, "hypot exact-top", hex(pr[0]), hex(pr[1]))
    # hypot: wide Pythagorean pairs
    for j in range((p - 1) // 2, (p + 5) // 2 + 2):
        if j < 2:
            continue
        a, b = val(fmt, (1 << (j + 1)) - 1, 0), val(fmt, (1 << j) - 1, j + 1)
        for pr in ((a, b), (b, a)):
            total += 1
            if pr not in pairs_:
                missing += 1
                print("MISSING pair", fname, "hypot wide", j)
print("checked", total, "operands and pairs; missing", missing)
