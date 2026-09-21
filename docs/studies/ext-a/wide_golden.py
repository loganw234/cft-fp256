# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""wide_golden.py - an instrument of docs/studies/EXT-A-wide-ladder.md.

Does the UNMODIFIED golden model already compute binary512 .. binary8192?
Nothing in python/cft_golden is edited or patched here: the wide formats
are FpFormat(name, exp_w, man_w) with IEEE 754-2019's own parameters
(clause 3.6: exp_w = round(4 log2 k) - 13), which is one line each.

    python docs/studies/ext-a/wide_golden.py > docs/studies/ext-a/wide_golden.out.txt

Who is the witness. python/tests/ref754.py is the repository's independent
oracle - exact Fraction arithmetic, no code shared with cft_golden - and it
was written as a microscope for EIGHT-bit formats. Two things stop it
being used directly at width:

  * ref_pack builds 2^emax and 2^emin as Fractions on EVERY call. That is
    a 2^30-bit integer at binary2048;
  * Fraction normalises with a gcd on every operation, which at
    2^(+-4 million) is seconds a check.

So this file has two witnesses, and says which one each result rests on:

  INTERIOR  exponents within a few thousand of zero, where neither range
            test can fire. The reference is the oracle's OWN primitives -
            floor_log2, rnd_int, enc_exact - with ref_pack's two range
            tests left out. Still no code shared with the model.
  EDGES     both ends of the exponent range, subnormals, the widest
            alignments a format admits. The reference is a restatement of
            754's rounding on plain integers (value = N/D * 2^E, no gcd),
            and BEFORE it is trusted it is scored against ref754.ref_pack
            itself wherever that is affordable: every finite encoding of
            the three tiny formats, and the edges of binary256.

Runs in about five minutes; binary1024's edges are most of it, because
the MODEL aligns with a plain shift by the exponent difference and that
difference is 134 million bits there. Section 4 times exactly that.
"""
import math
import pathlib
import random
import sys
import time
from fractions import Fraction as F

# LF on every platform, like the vector sets: a captured run should diff
# clean against a re-run wherever either was made.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(newline="\n")

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "python" / "tests"))

from cft_golden.formats import FpFormat          # noqa: E402
from cft_golden import softfloat as sf            # noqa: E402
import ref754 as orc                              # noqa: E402

NV, DZ, OF, UF, NX = 1, 2, 4, 8, 16
RNE, RTZ, RDN, RUP, RMM = 0, 1, 2, 3, 4
OPS = (("fma", 3, sf.fma), ("add", 2, sf.add), ("mul", 2, sf.mul), ("div", 2, sf.div))
FLAGNAME = {0: "exact", 16: "inexact", 20: "overflow", 24: "underflow"}


def say(*a):
    print(*a, flush=True)


def ieee(k):
    w = round(4 * math.log2(k)) - 13
    return w, k - w - 1                      # exp_w, man_w


def operands(op, a, b, c):
    return (a, c) if op == "add" else (a, b, c)[:3 if op == "fma" else 2]


# ---- operand shapes ---------------------------------------------------

def shaped_frac(fmt, rng):
    r = rng.random()
    if r < 0.15:
        return 0
    if r < 0.30:
        return fmt.man_mask
    if r < 0.45:                              # long runs: carry and cancellation
        return (1 << rng.randint(1, fmt.man_w)) - 1
    if r < 0.55:
        return 1 << rng.randint(0, fmt.man_w - 1)
    return rng.getrandbits(fmt.man_w)


def rand_interior(fmt, rng, spread):
    e = rng.randint(-spread, spread) + fmt.bias
    return (rng.getrandbits(1) << (fmt.width - 1)) | (e << fmt.man_w) | shaped_frac(fmt, rng)


def rand_edge(fmt, rng):
    r = rng.random()
    if r < 0.30:                              # subnormal
        ef, fr = 0, (shaped_frac(fmt, rng) or 1)
    elif r < 0.55:                            # just above emin
        ef, fr = rng.randint(1, 4), shaped_frac(fmt, rng)
    elif r < 0.80:                            # just below emax
        ef, fr = fmt.exp_mask - rng.randint(1, 4), shaped_frac(fmt, rng)
    elif r < 0.90:                            # a mid-range partner
        ef, fr = fmt.bias + rng.randint(-fmt.prec - 8, fmt.prec + 8), shaped_frac(fmt, rng)
    else:                                     # half range: products land on the edges
        ef = fmt.bias + rng.choice((-1, 1)) * (fmt.bias // 2 + rng.randint(-3, 3))
        fr = shaped_frac(fmt, rng)
    return (rng.getrandbits(1) << (fmt.width - 1)) | (ef << fmt.man_w) | fr


# ---- witness 1: the oracle's primitives, range tests left out ----------

def ref_interior(of, op, xs, rnd):
    v = [orc.dec(of, x)[2] for x in xs]
    v = (v[0] * v[1] + v[2] if op == "fma" else v[0] + v[1] if op == "add"
         else v[0] * v[1] if op == "mul" else v[0] / v[1])
    if v == 0:
        return None
    q = orc.floor_log2(abs(v)) - (of.p - 1)
    rb = F(orc.rnd_int(v / F(2) ** q, rnd)) * F(2) ** q
    bits = orc.enc_exact(of, rb)
    assert bits is not None
    return bits, (NX if rb != v else 0)


# ---- witness 2: 754's rounding restated on integers --------------------

def fields(f, bits):
    s = bits >> (f.width - 1)
    ef = (bits >> f.man_w) & f.exp_mask
    fr = bits & f.man_mask
    if ef == 0:
        return s, fr, f.emin - f.man_w
    return s, fr | (1 << f.man_w), ef - f.bias - f.man_w


def round_div(num, den, s, rnd):
    fl, rem = divmod(num, den)
    if rem == 0:
        return fl, False
    if rnd == RTZ:
        up = False
    elif rnd == RDN:
        up = bool(s)
    elif rnd == RUP:
        up = not s
    else:
        c = 2 * rem - den
        up = c > 0 or (c == 0 and (rnd == RMM or (fl & 1)))
    return fl + (1 if up else 0), True


def pack_int(f, s, N, D, E, rnd):
    """(bits, flags) of the exact nonzero value (-1)^s * (N/D) * 2^E:
    7.4 overflow, 7.5 tininess AFTER rounding, underflow = tiny and inexact."""
    p = f.prec
    k = N.bit_length() - D.bit_length()
    if (N << max(0, -k)) < (D << max(0, k)):
        k -= 1
    e2 = k + E

    def at(q):
        sh = E - q
        return round_div(N << sh if sh > 0 else N, D << -sh if sh < 0 else D, s, rnd)

    nu, _ = at(e2 - (p - 1))
    tiny = (e2 - (p - 1)) + nu.bit_length() - 1 < f.emin
    q = max(e2, f.emin) - (p - 1)
    n, inexact = at(q)
    flags = NX if inexact else 0
    sign = s << (f.width - 1)
    if n == 0:
        return sign, flags | UF
    e_res = q + n.bit_length() - 1
    if e_res > f.emax:
        flags |= OF | NX
        if rnd in (RNE, RMM) or (rnd == RDN and s) or (rnd == RUP and not s):
            return sign | (f.exp_mask << f.man_w), flags
        return sign | ((f.exp_mask - 1) << f.man_w) | f.man_mask, flags
    if tiny and inexact:
        flags |= UF
    if e_res < f.emin:
        return sign | n, flags
    if n.bit_length() == p + 1:
        n >>= 1
    return sign | ((e_res + f.bias) << f.man_w) | (n - (1 << (p - 1))), flags


def ref_edge(f, op, xs, rnd):
    sa, ma, ea = fields(f, xs[0])
    sb, mb, eb = fields(f, xs[1])
    if op == "mul":
        return None if not (ma and mb) else pack_int(f, sa ^ sb, ma * mb, 1, ea + eb, rnd)
    if op == "div":
        return None if not (ma and mb) else pack_int(f, sa ^ sb, ma, mb, ea - eb, rnd)
    if op == "add":
        terms = [(sa, ma, ea), (sb, mb, eb)]
    else:
        sc, mc, ec = fields(f, xs[2])
        terms = [(sa ^ sb, ma * mb, ea + eb), (sc, mc, ec)]
    e0 = min(t[2] for t in terms)
    tot = sum((-1 if s else 1) * (m << (e - e0)) for s, m, e in terms)
    return None if tot == 0 else pack_int(f, 1 if tot < 0 else 0, abs(tot), 1, e0, rnd)


def oracle_value(of, op, xs):
    v = [orc.dec(of, x)[2] for x in xs]
    return (v[0] * v[1] + v[2] if op == "fma" else v[0] + v[1] if op == "add"
            else v[0] * v[1] if op == "mul" else v[0] / v[1])


def prove_reference():
    total = bad = 0
    for ew, mw in ((4, 3), (5, 2), (3, 4)):
        f, of = FpFormat(f"e{ew}m{mw}", ew, mw), orc.Fmt(ew, mw)
        finite = [x for x in range(1 << f.width) if ((x >> mw) & f.exp_mask) != f.exp_mask]
        rng = random.Random(ew * 10 + mw)
        for a in finite:
            for b in rng.sample(finite, 24):
                c = rng.choice(finite)
                for rnd in orc.MODES:
                    for op, _, _ in OPS:
                        xs = operands(op, a, b, c)
                        mine = ref_edge(f, op, xs, rnd)
                        if mine is None:
                            continue
                        total += 1
                        bad += tuple(mine) != tuple(orc.ref_pack(of, oracle_value(of, op, xs), rnd))
    say(f"  integer reference vs ref754.ref_pack, e4m3/e5m2/e3m4: {total:,} checks, {bad} disagreements")
    f, of = FpFormat("fp256", 19, 236), orc.Fmt(19, 236)
    rng = random.Random(99)
    t2 = b2 = 0
    for _ in range(14):
        a, b, c = (rand_edge(f, rng) for _ in range(3))
        for rnd in orc.MODES:
            for op, _, _ in OPS:
                xs = operands(op, a, b, c)
                mine = ref_edge(f, op, xs, rnd)
                if mine is None:
                    continue
                t2 += 1
                b2 += tuple(mine) != tuple(orc.ref_pack(of, oracle_value(of, op, xs), rnd))
    say(f"  integer reference vs ref754.ref_pack, binary256 edges:  {t2:,} checks, {b2} disagreements")
    return bad == 0 and b2 == 0


# ---- the runs ----------------------------------------------------------

def run(k, n, gen, reference, of, label):
    w, mw = ieee(k)
    f = FpFormat(f"fp{k}", w, mw)
    rng = random.Random(7 * 100003 + k)
    total = bad = 0
    seen = {}
    t_model = 0.0
    for i in range(n):
        a, b, c = gen(f, rng), gen(f, rng), gen(f, rng)
        if i % 5 == 0:                        # catastrophic cancellation: c ~ -(a*b)
            pb, _ = sf.mul(f, a, b, sf.RND_RNE)
            if 0 < (pb & ~f.sign_mask) < sf.inf_bits(f):
                c = sf.negate(f, pb)
                if rng.random() < 0.6:
                    c ^= 1 << rng.randint(0, 6)
        for rnd in orc.MODES:
            for op, _, fn in OPS:
                xs = operands(op, a, b, c)
                want = reference(of if of else f, op, xs, rnd)
                if want is None:
                    continue
                t0 = time.perf_counter()
                got = fn(f, *xs, rnd)
                t_model += time.perf_counter() - t0
                total += 1
                seen[got[1]] = seen.get(got[1], 0) + 1
                if tuple(got) != tuple(want):
                    bad += 1
                    if bad <= 3:
                        say("   MISMATCH", f.name, op, rnd, hex(got[0])[:20], got[1], hex(want[0])[:20], want[1])
    # sqrt under all five attributes, by exact bracket: no square root is a midpoint
    sq_total = sq_bad = 0
    dec = orc.dec
    ofm = orc.Fmt(w, mw)
    for _ in range(max(10, n // 4)):
        a = rand_interior(f, rng, 2 * f.prec) & ~f.sign_mask
        x = dec(ofm, a)[2]
        for rnd in orc.MODES:
            r, fl = sf.sqrt(f, a, rnd)
            v = dec(ofm, r)[2]
            dn = dec(ofm, sf.next_down(f, r)[0])[2]
            up = dec(ofm, sf.next_up(f, r)[0])[2]
            if v * v == x:
                ok = fl == 0
            elif rnd in (RTZ, RDN):
                ok = v * v < x < up * up
            elif rnd == RUP:
                ok = dn * dn < x < v * v
            else:
                ok = ((v + dn) / 2) ** 2 < x < ((v + up) / 2) ** 2
            sq_total += 1
            sq_bad += not ok
    mix = ", ".join(f"{FLAGNAME.get(fl, hex(fl))} {cnt}" for fl, cnt in sorted(seen.items()))
    say(f"  binary{k:<5} {label:<8} exp_w={w:<2} p={mw + 1:<5} {total:>5} arithmetic checks, {bad} mismatches; "
        f"{sq_total:>3} sqrt checks, {sq_bad} failures   [{mix}]   model {t_model:.2f}s")
    return bad + sq_bad


def alignment_cost(k):
    w, mw = ieee(k)
    f = FpFormat(f"fp{k}", w, mw)
    big, tiny = sf.max_normal_bits(f), sf.min_subnormal_bits(f)
    span = f.emax - (f.emin - f.man_w)
    t0 = time.perf_counter()
    bits, fl = sf.fma(f, big, sf.one_bits(f), tiny, sf.RND_RUP)
    t_fma = time.perf_counter() - t0
    t0 = time.perf_counter()
    sf.remainder(f, big, tiny | (1 << (f.man_w // 2)))
    t_rem = time.perf_counter() - t0
    say(f"  binary{k:<5} widest alignment {span:>13,} bits ({span / 8 / 2**20:8.2f} MiB integer): "
        f"fma(max, 1, min_subnormal) {t_fma * 1e3:8.1f} ms (flags {fl:#04x}, +inf {bits == sf.inf_bits(f)}); "
        f"remainder(max, small) {t_rem * 1e3:8.1f} ms")


if __name__ == "__main__":
    failures = 0
    say("1. interior - the oracle's own primitives as the witness")
    for k, n, spread in ((256, 300, 600), (512, 300, 1200), (1024, 300, 2400),
                         (2048, 200, 4800), (4096, 120, 9000), (8192, 60, 9000)):
        failures += run(k, n, (lambda f, r, s=spread: rand_interior(f, r, s)),
                        ref_interior, orc.Fmt(*ieee(k)), "interior")
    say("2. is the integer reference right? scored by ref754.ref_pack where that is affordable")
    if not prove_reference():
        sys.exit("the integer reference disagrees with the oracle; nothing below would mean anything")
    say("3. edges - overflow, underflow, tininess, subnormals, the widest alignments")
    for k, n in ((256, 200), (512, 200), (1024, 40)):
        failures += run(k, n, rand_edge, ref_edge, None, "edges")
    say("4. what the model's plain-shift alignment costs at the widest spread a format admits")
    for k in (256, 512, 1024, 2048):
        alignment_cost(k)
    say(f"total mismatches and failures: {failures}")
    sys.exit(1 if failures else 0)
