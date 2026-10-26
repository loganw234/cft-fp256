#!/usr/bin/env python3
"""hx_ladder.py - parcel HX: the cross-format ladder, settled by exhaustion at toy precisions (scratch beside
docs/studies/HX-wide-sweeps.md, section 2.1; nothing in the tree imports it, and it imports nothing of the tree).

THE QUESTION. A narrow format N (precision p) and a wide one W (precision p' > p, a wider exponent range). For an
operation op and an attribute m, take every narrow input, widen it exactly, compute op in W under m, and round that
wide result back to N under m (the narrowing conversion). Does it equal op computed in N under m, value and flags?
If so, an exhaustively proven narrow result is an oracle for the wide operation on the widened slice.

THE METHOD. Exact arithmetic only: every exact result is a dyadic M 2^E (sum, product, FMA, scaleB, an integer), a
rational N/D 2^E (quotient) or sqrt(M 2^E) (root), and rounding needs just floor(|r| 2^s) and whether it is exact,
which integers give (divmod, isqrt). One rounding routine serves every format: IEEE 754-2019 rounding to p bits
with subnormals below 2^emin, the five attributes, overflow delivered per attribute (7.4), tininess AFTER rounding
(the contract's choice), underflow only when tiny and inexact. Specials follow 754: NaN in, NaN out (quiet; the
canonical class); invalid for inf - inf, 0 x inf, 0/0, inf/inf, sqrt of a negative; divideByZero for finite/0.

  N: p bits, emin = -6, emax = 7 (four exponent bits, like e4m3, at several p); every encoding is an input:
     +-0, every subnormal, every normal, +-inf, a NaN.
  W: p' bits, emin = -100, emax = 100: wide enough that no result of narrow inputs is tiny or overflows in W,
     as at every real rung (fp32's extreme product 2^-298 against fp64's 2^-1022; COMPUTED in the study).

FLAG RULES compared with the narrow operation's flags:
  R1  the narrowing conversion's flags alone (plus invalid and divideByZero, which the operand classes decide);
  R2  R1 OR the wide operation's inexact flag (a soak would OR the wide call's flags with the narrowing's);
  R3  R2 with underflow recomputed: raised when the narrowed value is tiny (after rounding, at N) and EITHER
      rounding was inexact - the narrowing alone cannot know that its exact input was itself a rounding.

PARTS (each prints a table; CHECK lines fail the exit status):
  A  the value and flag ladder: add (every sign pair, so sub too), mul, div at p = 3, 4, 5; sqrt at p = 3..10;
     FMA at p = 3 (emin -4, emax 4); p' from 2p - 2 to 2p + 3, and for FMA to the exact span
  B  conversions and the composed operations: integer -> N directly against integer -> W -> N, every integer of
     p + 6 bits; roundToIntegral (both variants) and scaleB (every n that matters) through W
  C  detection: what a wrong wide result must be to change the narrowed one (errors of 2^j wide ulps injected
     into every inexact wide square root and quotient), measured against 2^(j - (p' - p))
  D  controls: a narrowing with ties rounded up, R1 on addition, FMA at 2p + 2 under RNE - each must go red

  E  the real narrow precision, p = 24: python/hardcases.py's closest-approach divisions (F0) and the inputs nearest
     the squares of midpoints (S0), read only, through W at 2p - 1 .. 2p + 2 and at 53, 113 and 237

usage: python3 hx_ladder.py [TREE]     (TREE: a checkout, for part E; about three and a half minutes on one core)
"""
import sys
import time
from math import isqrt

def print(*args, **kw):
    """The builtin print with every line's trailing blanks removed (the tables pad their cells)."""
    import builtins
    text = " ".join(str(a) for a in args)
    builtins.print("\n".join(line.rstrip() for line in text.split("\n")), **kw)


RNE, RTZ, RDN, RUP, RMM = range(5)
MODES = ("rne", "rtz", "rdn", "rup", "rmm")
NX, UF, OF, DZ, NV = 1, 2, 4, 8, 16
FLAGN = ((NV, "NV"), (DZ, "DZ"), (OF, "OF"), (UF, "UF"), (NX, "NX"))
NAN = ("n",)
WEMIN, WEMAX = -100, 100
FAILS = []


def check(name, ok, detail=""):
    print("CHECK %-74s %s%s" % (name, "ok" if ok else "FAILED", (": " + detail) if detail else ""))
    if not ok:
        FAILS.append(name)


# ---- exact reals: ('d', M, E) = M 2^E; ('q', N, D, E) = N/D 2^E; ('r', M, E) = sqrt(M 2^E); all positive ----

def fs(r, s):
    """(floor(r 2^s), exact)."""
    k = r[0]
    if k == "d":
        t = r[2] + s
        if t >= 0:
            return r[1] << t, True
        return r[1] >> -t, (r[1] & ((1 << -t) - 1)) == 0
    if k == "q":
        t = r[3] + s
        q, m = divmod(r[1] << t, r[2]) if t >= 0 else divmod(r[1], r[2] << -t)
        return q, m == 0
    t = r[2] + 2 * s
    if t >= 0:
        y = r[1] << t
        q = isqrt(y)
        return q, q * q == y
    y = r[1] >> -t
    q = isqrt(y)
    return q, (r[1] & ((1 << -t) - 1)) == 0 and q * q == y


def ilog2(r):
    k = r[0]
    if k == "d":
        return r[1].bit_length() - 1 + r[2]
    if k == "q":
        n, d = r[1], r[2]
        e = n.bit_length() - d.bit_length()
        if (n << -e if e < 0 else n) < (d << e if e > 0 else d):
            e -= 1
        return e + r[3]
    return (r[1].bit_length() - 1 + r[2]) >> 1


def incr(mode, sg, lsb, g, st):
    if mode == RNE:
        return g and (st or lsb)
    if mode == RMM:
        return g
    if mode == RTZ:
        return 0
    if mode == RDN:
        return (g or st) and sg == 1
    return (g or st) and sg == 0


def norm(sg, m, e):
    tz = (m & -m).bit_length() - 1
    return ("f", sg, m >> tz, e + tz)


class Fmt:
    def __init__(self, p, emin, emax, name=None):
        self.p, self.emin, self.emax = p, emin, emax
        self.name = name or "p%d" % p
        self.maxf = None

    def max_finite(self, sg):
        return norm(sg, (1 << self.p) - 1, self.emax - self.p + 1)


def rnd(sg, r, F, mode, ties_up=False):
    """Round the positive real r with sign sg into F under mode: (result, flags). ties_up: a planted defect."""
    p = F.p
    e = ilog2(r)
    qe = (e if e > F.emin else F.emin) - (p - 1)
    q2, ex = fs(r, 1 - qe)
    kept, g, st = q2 >> 1, q2 & 1, not ex
    inexact = g or st
    inc = (g and 1) if (ties_up and mode == RNE) else incr(mode, sg, kept & 1, g, st)
    m = kept + inc
    flags = NX if inexact else 0
    if m == 0:
        res = ("z", sg)
    else:
        if m.bit_length() - 1 + qe > F.emax:
            to_inf = mode in (RNE, RMM) or (mode == RDN and sg == 1) or (mode == RUP and sg == 0)
            return (("i", sg) if to_inf else F.max_finite(sg)), flags | OF | NX
        res = norm(sg, m, qe)
    if inexact and e < F.emin:
        qu = e - (p - 1)
        q2u, exu = fs(r, 1 - qu)
        ku = q2u >> 1
        mu = ku + incr(mode, sg, ku & 1, q2u & 1, not exu)
        if mu.bit_length() - 1 + qu < F.emin:
            flags |= UF
    return res, flags


def tiny_at(w, F, mode):
    """Whether the finite value w is tiny after rounding at F (the unbounded-exponent rounding below 2^emin)."""
    if w[0] != "f":
        return False
    sg, r = w[1], ("d", w[2], w[3])
    e = ilog2(r)
    if e >= F.emin:
        return False
    qu = e - (F.p - 1)
    q2u, exu = fs(r, 1 - qu)
    ku = q2u >> 1
    mu = ku + incr(mode, sg, ku & 1, q2u & 1, not exu)
    return mu.bit_length() - 1 + qu < F.emin


def narrow(w, N, mode, ties_up=False):
    if w[0] == "f":
        return rnd(w[1], ("d", w[2], w[3]), N, mode, ties_up)
    return w, 0


def values(F, specials=True):
    """Every encoding of F as a value: zeros, subnormals, normals (each sign), and inf and NaN if asked."""
    out = [("z", 0), ("z", 1)]
    for sg in (0, 1):
        for k in range(1, 1 << (F.p - 1)):
            out.append(norm(sg, k, F.emin - F.p + 1))
        for e in range(F.emin, F.emax + 1):
            for m in range(1 << (F.p - 1), 1 << F.p):
                out.append(norm(sg, m, e - F.p + 1))
    if specials:
        out += [("i", 0), ("i", 1), NAN]
    return out


# ---- the operations' exact results: ('x', result, flags) for a special or exact zero, or ('r', sign, real) ----

def zero_sum_sign(sa, sb, mode):
    return sa if sa == sb else (1 if mode == RDN else 0)


def add_dyadic(sa, ma, ea, sb, mb, eb, mode):
    e = min(ea, eb)
    v = (-1 if sa else 1) * (ma << (ea - e)) + (-1 if sb else 1) * (mb << (eb - e))
    if v == 0:
        return ("x", ("z", 1 if mode == RDN else 0), 0)
    return ("r", 1 if v < 0 else 0, ("d", abs(v), e))


def ex_add(x, y, mode):
    if x[0] == "n" or y[0] == "n":
        return ("x", NAN, 0)
    if x[0] == "i" or y[0] == "i":
        if x[0] == "i" and y[0] == "i" and x[1] != y[1]:
            return ("x", NAN, NV)
        return ("x", x if x[0] == "i" else y, 0)
    if x[0] == "z" and y[0] == "z":
        return ("x", ("z", zero_sum_sign(x[1], y[1], mode)), 0)
    if x[0] == "z":
        return ("r", y[1], ("d", y[2], y[3]))
    if y[0] == "z":
        return ("r", x[1], ("d", x[2], x[3]))
    return add_dyadic(x[1], x[2], x[3], y[1], y[2], y[3], mode)


def ex_mul(x, y, mode):
    if x[0] == "n" or y[0] == "n":
        return ("x", NAN, 0)
    sg = x[1] ^ y[1]
    if x[0] == "i" or y[0] == "i":
        if x[0] == "z" or y[0] == "z":
            return ("x", NAN, NV)
        return ("x", ("i", sg), 0)
    if x[0] == "z" or y[0] == "z":
        return ("x", ("z", sg), 0)
    return ("r", sg, ("d", x[2] * y[2], x[3] + y[3]))


def ex_div(x, y, mode):
    if x[0] == "n" or y[0] == "n":
        return ("x", NAN, 0)
    sg = x[1] ^ y[1]
    if x[0] == "i":
        return ("x", NAN, NV) if y[0] == "i" else ("x", ("i", sg), 0)
    if y[0] == "i":
        return ("x", ("z", sg), 0)
    if y[0] == "z":
        return ("x", NAN, NV) if x[0] == "z" else ("x", ("i", sg), DZ)
    if x[0] == "z":
        return ("x", ("z", sg), 0)
    return ("r", sg, ("q", x[2], y[2], x[3] - y[3]))


def ex_sqrt(x, mode):
    if x[0] == "n":
        return ("x", NAN, 0)
    if x[0] == "z":
        return ("x", x, 0)
    if x[1] == 1:
        return ("x", NAN, NV)
    if x[0] == "i":
        return ("x", x, 0)
    m, e = x[2], x[3]
    if e & 1:
        m, e = m << 1, e - 1
    return ("r", 0, ("r", m, e))


def ex_fma(a, b, c, mode):
    if a[0] == "n" or b[0] == "n" or c[0] == "n":
        return ("x", NAN, 0)
    sp = a[1] ^ b[1]
    if a[0] == "i" or b[0] == "i":
        if a[0] == "z" or b[0] == "z":
            return ("x", NAN, NV)
        if c[0] == "i" and c[1] != sp:
            return ("x", NAN, NV)
        return ("x", ("i", sp), 0)
    if c[0] == "i":
        return ("x", c, 0)
    if a[0] == "z" or b[0] == "z":
        if c[0] == "z":
            return ("x", ("z", zero_sum_sign(sp, c[1], mode)), 0)
        return ("r", c[1], ("d", c[2], c[3]))
    if c[0] == "z":
        return ("r", sp, ("d", a[2] * b[2], a[3] + b[3]))
    return add_dyadic(sp, a[2] * b[2], a[3] + b[3], c[1], c[2], c[3], mode)


def finish(ex, F, mode, ties_up=False):
    if ex[0] == "x":
        return ex[1], ex[2]
    return rnd(ex[1], ex[2], F, mode, ties_up)


def v2s(x):
    if x[0] == "f":
        return "%s%d*2^%d" % ("-" if x[1] else "+", x[2], x[3])
    if x[0] == "z":
        return "-0" if x[1] else "+0"
    if x[0] == "i":
        return "-inf" if x[1] else "+inf"
    return "nan"


def flagstr(f):
    return "".join(n for b, n in FLAGN if f & b) or "-"


# ---- part A: the ladder by exhaustion ----

def ladder(opname, exfn, N, inputs, pws, modes=range(5), ties_up=False, quiet=False):
    """For each p' and mode: (inputs, value mismatches, R1 mismatches, R2 mismatches, wide inexact, an example)."""
    exs = [(xs, exfn(*xs, RNE)) for xs in inputs]          # the exact real does not depend on the mode
    out = {}
    for mode in modes:
        exm = [(xs, exfn(*xs, mode) if e[0] == "x" else e) for xs, e in exs]
        ref = [finish(e, N, mode) for _, e in exm]
        for pw in pws:
            W = Fmt(pw, WEMIN, WEMAX)
            nv = n1 = n2 = n3 = winx = 0
            ex1 = None
            for (xs, e), (rv, rf) in zip(exm, ref):
                w, wf = finish(e, W, mode)
                b, bf = narrow(w, N, mode, ties_up)
                if wf & NX:
                    winx += 1
                base = wf & (NV | DZ)
                if b != rv:
                    nv += 1
                    if ex1 is None:
                        ex1 = (xs, rv, b)
                if (base | bf) != rf:
                    n1 += 1
                if (base | bf | (wf & NX)) != rf:
                    n2 += 1
                f3 = base | (wf & NX) | (bf & (OF | NX))
                if (f3 & NX) and tiny_at(w, N, mode):
                    f3 |= UF
                if f3 != rf:
                    n3 += 1
            out[(mode, pw)] = (len(exm), nv, n1, n2, winx, ex1, n3)
    return out


def show(opname, N, res, pws):
    print("\n%s, N = (p %d, emin %d, emax %d): mismatches out of %d inputs a cell (value / R1 / R2 / R3 flags)"
          % (opname, N.p, N.emin, N.emax, next(iter(res.values()))[0]))
    print("  p'   " + "".join("%-22s" % m for m in MODES))
    for pw in pws:
        row = "  %-4d " % pw
        for mode in range(5):
            if (mode, pw) in res:
                _, nv, n1, n2, _, _, n3 = res[(mode, pw)]
                row += "%-22s" % ("%d/%d/%d/%d" % (nv, n1, n2, n3))
        print(row)


def least_safe(res, pws, mode):
    """The least p' from which every listed p' has no value and no R2 mismatch (None if not even the last)."""
    best = None
    for pw in sorted(pws, reverse=True):
        _, nv, _, n2, _, _, _ = res[(mode, pw)]
        if nv or n2:
            break
        best = pw
    return best


def part_a():
    print("== A. the value and flag ladder, every narrow input, exact arithmetic")
    summary = []
    for p in (3, 4, 5):
        N = Fmt(p, -6, 7)
        vs = values(N)
        pairs = [(x, y) for x in vs for y in vs]
        pws = list(range(2 * p - 2, 2 * p + 4))
        for name, fn in (("add", ex_add), ("mul", ex_mul), ("div", ex_div)):
            t0 = time.time()
            res = ladder(name, fn, N, pairs, pws)
            show(name, N, res, pws)
            print("  (%.1f s)" % (time.time() - t0))
            summary.append((name, p, res, pws))
    for p in range(3, 11):
        N = Fmt(p, -6, 7)
        ins = [(x,) for x in values(N)]
        pws = list(range(max(p + 1, 2 * p - 3), 2 * p + 4))
        res = ladder("sqrt", ex_sqrt, N, ins, pws)
        show("sqrt", N, res, pws)
        summary.append(("sqrt", p, res, pws))
    N = Fmt(3, -4, 4)
    vs = values(N)
    triples = [(a, b, c) for a in vs for b in vs for c in vs]
    pws = [7, 8, 12, 16, 20, 24, 28]
    t0 = time.time()
    res = ladder("fma", ex_fma, N, triples, pws)
    show("fma", N, res, pws)
    print("  (%.1f s)" % (time.time() - t0))
    summary.append(("fma", 3, res, pws))

    print("\n== A summary: the least p' from which the value ladder and R2 hold at every larger p' tried")
    print("  op    p   2p+2  " + "".join("%-6s" % m for m in MODES) + "  R1 (flags of the narrowing alone) at 2p+2")
    for name, p, res, pws in summary:
        cells = []
        for mode in range(5):
            s = least_safe(res, pws, mode)
            cells.append("%-6s" % (s if s is not None else "none"))
        top = 2 * p + 2 if (0, 2 * p + 2) in res else max(pws)
        r1 = sum(res[(m, top)][2] for m in range(5))
        print("  %-5s %-3d %-5d %s  %d mismatches over the five attributes" % (name, p, 2 * p + 2, "".join(cells), r1))
    for name, p, res, pws in summary:
        if name == "fma":
            continue
        ok = all(res[(m, pw)][1] == 0 and res[(m, pw)][3] == 0 for m in range(5) for pw in pws if pw >= 2 * p + 2)
        check("%s p=%d: value and R2 flags hold at every p' >= 2p+2 tried, all five attributes" % (name, p), ok)
        ok = all(res[(m, pw)][1] == 0 for m in (RTZ, RDN, RUP) for pw in pws)
        check("%s p=%d: directed attributes: the VALUE holds at every p' tried (>= %d)" % (name, p, min(pws)), ok)
        ok = all(res[(m, pw)][6] == 0 for m in (RTZ, RDN, RUP) for pw in pws)
        check("%s p=%d: directed attributes: R3 flags hold at every p' tried (>= %d)" % (name, p, min(pws)), ok)
        ok = all(res[(m, pw)][6] == 0 for m in range(5) for pw in pws if pw >= 2 * p + 2)
        check("%s p=%d: R3 flags hold at every p' >= 2p+2 tried, all five attributes" % (name, p), ok)
    # FMA: the nearest attributes fail until W holds every exact result; the directed ones never fail
    res = summary[-1][2]
    fails = {pw: sum(res[(m, pw)][1] for m in (RNE, RMM)) for pw in summary[-1][3]}
    print("  fma p=3: value mismatches under RNE + RMM by p': " + ", ".join("%d: %d" % kv for kv in sorted(fails.items())))
    check("fma p=3: RNE and RMM fail at p' = 2p+2 = 8 (double rounding of a*b + tiny c)", fails[8] > 0)
    check("fma p=3: directed attributes: the VALUE holds at every p' tried",
          all(res[(m, pw)][1] == 0 for m in (RTZ, RDN, RUP) for pw in summary[-1][3]))
    check("fma p=3: directed attributes: R3 flags hold at every p' tried",
          all(res[(m, pw)][6] == 0 for m in (RTZ, RDN, RUP) for pw in summary[-1][3]))
    ex = res[(RNE, 8)][5]
    print("  fma first RNE failure at p' = 8: operands %s, narrow %s, via W %s"
          % (", ".join(v2s(x) for x in ex[0]), v2s(ex[1]), v2s(ex[2])))
    return summary


# ---- part B: conversions, roundToIntegral, scaleB ----

def rint_exact(x, mode):
    """roundToIntegral's exact result: an integer value (as a value tuple), or the special; and the exact flag."""
    if x[0] != "f":
        return x, False
    sg, m, e = x[1], x[2], x[3]
    if e >= 0:
        return x, False
    q, rem = m >> -e, m & ((1 << -e) - 1)
    half = 1 << (-e - 1)
    inc = 0 if rem == 0 else incr(mode, sg, q & 1, rem >= half, rem != 0 and rem != half)
    q += inc
    return (("z", sg) if q == 0 else norm(sg, q, 0)), rem != 0


def part_b():
    print("\n== B. conversions and the composed operations through W")
    p = 4
    N = Fmt(p, -6, 7)
    nbits = 2 * p + 6
    ints = range(-(1 << nbits) + 1, 1 << nbits)
    print("  integer -> N against integer -> W -> N, every integer of |i| < 2^%d (%d of them), N p = %d:" % (nbits, len(ints), p))
    print("  p'   " + "".join("%-8s" % m for m in MODES) + "(value mismatches)")
    NI = Fmt(p, -6, nbits + 2)                # N's precision with room for every integer: no overflow hides a case
    for pw in (2 * p + 2, nbits - 2, nbits - 1, nbits, nbits + 1):
        W = Fmt(pw, WEMIN, WEMAX)
        row = []
        for mode in range(5):
            bad = 0
            for i in ints:
                if i == 0:
                    continue
                r = ("d", abs(i), 0)
                sg = 1 if i < 0 else 0
                ref, rf = rnd(sg, r, NI, mode)
                w, wf = rnd(sg, r, W, mode)
                b, bf = narrow(w, NI, mode)
                bad += (b != ref) or ((bf | (wf & NX)) != rf)
            row.append(bad)
        print("  %-4d " % pw + "".join("%-8d" % b for b in row))
        if pw == 2 * p + 2:
            check("cvtfrom: integer -> W -> N fails under RNE at p' = 2p+2 < integer width", row[RNE] > 0)
        if pw == nbits:
            check("cvtfrom: holds once W holds every integer exactly (p' = %d, the integers' width)" % pw, sum(row) == 0)
    # roundToIntegral: rint_W(widen x) narrowed equals rint_N(x), and the W result equals it EXACTLY
    vs = values(N)
    bad = exact_w = 0
    for mode in range(5):
        for x in vs:
            r1, c1 = rint_exact(x, mode)
            # the same operation in W on the widened x gives the same exact integer, which is representable in N:
            # an integer of at most p bits when |x| < 2^p, and x itself (an integer already) above that
            w = r1
            b, bf = narrow(w, N, mode)
            bad += b != r1 or bf != 0
            exact_w += 1
    check("rint: the exact integer narrows exactly, no flag, for every input and attribute (%d pairs)" % exact_w,
          bad == 0)
    # scaleB: exact in W for every n with x 2^n inside W's range, then one rounding to N
    W = Fmt(2 * p + 2, WEMIN, WEMAX)
    span = (N.emax - N.emin) + 2 * p + 3
    bad = n_cases = 0
    for mode in range(5):
        for x in vs:
            for n in range(-span, span + 1):
                if x[0] == "f":
                    r = ("d", x[2], x[3] + n)
                    ref, rf = rnd(x[1], r, N, mode)
                    w, wf = rnd(x[1], r, W, mode)
                    b, bf = narrow(w, N, mode)
                    bad += b != ref or (bf | (wf & NX)) != rf
                    n_cases += 1
    check("scaleB: through W (p' = %d) equals scaleB in N, values and R2 flags, %d cases, n in [-%d, %d]"
          % (2 * p + 2, n_cases, span, span), bad == 0)


# ---- part C: what the ladder can detect ----

def part_c():
    print("\n== C. detection: an error of 2^j wide ulps in every inexact wide result; the fraction the ladder sees")
    for name, fn, p, mk in (("sqrt", ex_sqrt, 10, lambda vs: [(x,) for x in vs if x[0] == "f" and x[1] == 0]),
                            ("div", ex_div, 5, lambda vs: [(x, y) for x in vs if x[0] == "f" for y in vs if y[0] == "f"])):
        N = Fmt(p, -6, 7)
        pw = 2 * p + 2
        W = Fmt(pw, WEMIN, WEMAX)
        ins = mk(values(N, specials=False))
        cases = []
        for xs in ins:
            e = fn(*xs, RNE)
            if e[0] != "r":
                continue
            w, wf = rnd(e[1], e[2], W, RNE)
            if not (wf & NX) or w[0] != "f":
                continue
            ref, _ = rnd(e[1], e[2], N, RNE)
            cases.append((w, ref))
        print("  %s, p = %d, p' = %d, %d inexact results; predicted fraction 2^(j - (p' - p)) = 2^(j - %d)"
              % (name, p, pw, len(cases), pw - p))
        print("    j   detected   fraction    predicted")
        worst = 0.0
        for j in range(0, pw - p + 2):
            det = 0
            for w, ref in cases:
                sg, m, e = w[1], w[2], w[3]
                # the wide result's own quantum: m 2^e with m odd; scale to p' bits
                sh = pw - m.bit_length()
                mm, ee = m << sh, e - sh
                for d in (1 << j, -(1 << j)):
                    m2 = mm + d
                    if m2 <= 0:
                        continue
                    b, _ = rnd(sg, ("d", m2, ee), N, RNE)
                    det += b != ref
            frac = det / (2.0 * len(cases))
            pred = min(1.0, 2.0 ** (j - (pw - p)))
            if j <= pw - p - 2:
                worst = max(worst, frac / pred)
            print("    %-3d %-10d %-11.3e %.3e" % (j, det, frac, pred))
        check("%s: detection fraction within 4x of 2^(j - (p'-p)) below the top bits (max ratio %.2f)" % (name, worst),
              worst < 4.0)


# ---- part D: controls ----

def part_d(summary):
    print("\n== D. controls: each must go red")
    p = 4
    N = Fmt(p, -6, 7)
    vs = values(N)
    pairs = [(x, y) for x in vs for y in vs]
    res = ladder("add", ex_add, N, pairs, [2 * p + 2], modes=[RNE], ties_up=True)
    nv = res[(RNE, 2 * p + 2)][1]
    check("control: a narrowing whose RNE rounds ties up is caught by the add ladder (%d mismatches)" % nv, nv > 0)
    add4 = [s for s in summary if s[0] == "add" and s[1] == 4][0][2]
    n1 = sum(add4[(m, 10)][2] for m in range(5))
    check("control: R1 (the narrowing's flags alone) loses inexact on add at p' = 10 (%d mismatches)" % n1, n1 > 0)
    sq = [s for s in summary if s[0] == "sqrt" and s[1] == 6][0][2]
    low = min(sq_pw for (m, sq_pw) in sq)
    nlow = sum(sq[(m, low)][1] for m in range(5))
    print("  sqrt p=6 at p' = %d: %d value mismatches (below 2p+2 the ladder may break)" % (low, nlow))


def part_e(tree):
    """The ladder at the REAL narrow precision on the cases closest to its rounding boundaries: python/hardcases.py's
    constructions (read only) at p = 24 - F0, the quotients at the least distance an odd divisor allows from a midpoint
    or a representable number, and S0, the inputs nearest the squares of midpoints - through W at 2p - 1 .. 2p + 2 and at
    fp64's 53, fp128's 113 and fp256's 237."""
    sys.path.insert(0, tree + "/python")
    import hardcases as H
    print("\n== E. the ladder at p = 24 on the constructed hard cases (python/hardcases.py, read only)")
    N = Fmt(24, -126, 127, "fp32")
    sq = H.Space("sqrt32-hx", 24, 32, 127, 1, [("S1", 4 << 8), ("S0", 4 << 12)])
    dv = H.SPACES["div32-hard"]
    seg = {s[0]: s for s in dv.segs}
    div_cases, sq_cases = [], []
    for segname in ("F0A", "F0D"):
        start = seg[segname][1]
        for idx in range(start, start + 6000):
            c = H.base_case(dv, idx)
            if c is None:
                continue
            sa, ma, ta = H.decode(dv, c[0])
            sb, mb, tb = H.decode(dv, c[1])
            div_cases.append(("r", 0, ("q", ma, mb, ta - tb)))
    sseg = {s[0]: s for s in sq.segs}
    for idx in range(sseg["S0"][1], sseg["S0"][1] + sseg["S0"][2]):
        c = H.base_case(sq, idx)
        if c is None:
            continue
        s, m, t = H.decode(sq, c[0])
        if t & 1:
            m, t = m << 1, t - 1
        sq_cases.append(("r", 0, ("r", m, t)))
    pws = (47, 48, 49, 50, 53, 113, 237)
    print("  value mismatches, RNE + RMM, through W at p' (div: %d F0 cases; sqrt: %d S0 cases)" % (len(div_cases), len(sq_cases)))
    print("  op     " + "".join("%-8d" % pw for pw in pws))
    res = {}
    for name, cases in (("div", div_cases), ("sqrt", sq_cases)):
        row = []
        for pw in pws:
            W = Fmt(pw, -16382, 16383)              # fp128's range; no fp32 quotient or root comes near either end
            bad = 0
            for mode in (RNE, RMM):
                for _, sg, r in cases:
                    ref, rf = rnd(sg, r, N, mode)
                    w, wf = rnd(sg, r, W, mode)
                    b, bf = narrow(w, N, mode)
                    bad += b != ref
            row.append(bad)
        res[name] = dict(zip(pws, row))
        print("  %-6s " % name + "".join("%-8d" % b for b in row))
    check("p=24 div F0: the ladder fails below 2p = 48 and holds from 48, and at 53, 113, 237",
          res["div"][47] > 0 and all(res["div"][pw] == 0 for pw in pws if pw >= 48))
    check("p=24 sqrt S0: the ladder fails at 2p+1 = 49 and holds from 2p+2 = 50, and at 53, 113, 237",
          res["sqrt"][49] > 0 and all(res["sqrt"][pw] == 0 for pw in pws if pw >= 50))


def main():
    t0 = time.time()
    tree = sys.argv[1] if len(sys.argv) > 1 else None
    summary = part_a()
    part_b()
    part_c()
    part_d(summary)
    if tree:
        part_e(tree)
    print("\nhx_ladder: %d check(s) failed%s; %.0f s" % (len(FAILS), (": " + "; ".join(FAILS)) if FAILS else "",
                                                       time.time() - t0))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
