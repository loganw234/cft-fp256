#!/usr/bin/env python3
"""hx_spaces.py - parcel HX: the wide formats' finite spaces and the oracles' speeds, measured on the desktop
(scratch beside docs/studies/HX-wide-sweeps.md, sections 1 and 2; nothing in the tree imports it).

It imports the tree READ ONLY (python/hardcases.py, python/c5_class_enum.py, python/cft_golden) and changes nothing
there: the hard-case spaces at fp128 and fp256 are new Space objects built from hardcases' own constructor and
registered in this process's copy of its SPACES table, so that hardcases.verify - the exact, builder-independent
check - can run on them.

  S1  the class-level (L2) spaces of c5_class_enum's enumerators at fp128 and fp256 (their generators are generic in
      the format), with the cases an index makes on the tile's lanes at that format
  S2  the hard-case spaces of python/hardcases.py's families at p = 113 and 237, segment by segment; a sample of
      every segment built and verified exactly (hardcases.verify), its skips counted, and the build time
  S3  the oracles' speed, one desktop core in WSL: gmpy2 (MPFR 4.1.0) emulating binary128 and binary256 (precision,
      emin, emax, subnormalize) for add, mul, fma, div, sqrt; the golden model's softfloat for the same; and an
      exact residual check of a square root and a quotient in Python integers (a verifier that shares no code
      with MPFR or the model)

usage: python3 hx_spaces.py TREE        (TREE: a checkout; about two minutes)
"""
import random
import sys
import time

FAILS = []


def check(name, ok, detail=""):
    print("CHECK %-78s %s%s" % (name, "ok" if ok else "FAILED", (": " + detail) if detail else ""))
    if not ok:
        FAILS.append(name)


def s1(tree):
    import c5_class_enum as C
    from cft_golden.formats import FP64, FP128, FP256, FP32
    print("== S1. class-level (L2) spaces at the wide formats, from python/c5_class_enum.py's generic enumerators")
    lanes = {"fp64": 4, "fp128": 2, "fp256": 1}
    rows = [("rint64-class (as built)", C.RoundEnum("rint", FP64), "tile", lanes["fp64"]),
            ("rint, fp128", C.RoundEnum("rint", FP128), "tile", lanes["fp128"]),
            ("rint, fp256", C.RoundEnum("rint", FP256), "tile", lanes["fp256"]),
            ("scaleb64-class (as built)", C.ScalebEnum(FP64), "tile", lanes["fp64"]),
            ("scaleb, fp128", C.ScalebEnum(FP128), "tile", lanes["fp128"]),
            ("scaleb, fp256", C.ScalebEnum(FP256), "tile", lanes["fp256"]),
            ("conv64to32-class (as built)", C.RoundEnum("conv", FP64, FP32), "host", 1),
            ("conv, fp128 -> fp64", C.RoundEnum("conv", FP128, FP64), "host", 1),
            ("conv, fp256 -> fp128", C.RoundEnum("conv", FP256, FP128), "host", 1),
            ("cvtto, fp128 -> 64-bit integers", C.RoundEnum("cvtto", FP128, B=64), "host", 4),
            ("cvtto, fp256 -> 64-bit integers", C.RoundEnum("cvtto", FP256, B=64), "host", 4),
            ("cvtfrom, 64-bit integers -> fp128", C.CvtfromEnum(FP128), "host", 1),
            ("cvtfrom, 64-bit integers -> fp256", C.CvtfromEnum(FP256), "host", 1)]
    print("  %-34s %-5s %12s %4s %14s  %s" % ("space", "reach", "indices", "k", "cases/attr", "formula"))
    sizes = {}
    for name, en, reach, k in rows:
        print("  %-34s %-5s %12d %4d %14d  %s" % (name, reach, en.N, k, en.N * k, en.size_formula()))
        sizes[name] = en.N
    check("S1: the generators reproduce the built spaces' sizes (rint64 35,840, scaleb64 72,648, conv64to32 136,192)",
          sizes["rint64-class (as built)"] == 35840 and sizes["scaleb64-class (as built)"] == 72648
          and sizes["conv64to32-class (as built)"] == 136192)
    return sizes


def s2(tree):
    import hardcases as H
    print("\n== S2. hard-case spaces at p = 113 and 237, from python/hardcases.py's constructor and builders")
    spaces = {
        "div64-hard (as built)": H.SPACES["div64-hard"],
        "div128-hard": H._div_space("div128-hard", 113, 128, 16383, 1 << 26),
        "div256-hard": H._div_space("div256-hard", 237, 256, 262143, 1 << 26),
        "sqrt128-hard": H.Space("sqrt128-hard", 113, 128, 16383, 1, [("S1", 4 << 16), ("S0", 4 << 20)]),
        "sqrt256-hard": H.Space("sqrt256-hard", 237, 256, 262143, 1, [("S1", 4 << 16), ("S0", 4 << 20)]),
    }
    for name in ("div128-hard", "div256-hard", "sqrt128-hard", "sqrt256-hard"):
        H.SPACES[name] = spaces[name]
    for name, sp in spaces.items():
        print("  %-22s p %3d  k %d  indices %13d  segments: %s" % (name, sp.p, sp.k, sp.total,
              ", ".join("%s %d" % (n, c) for n, _, c in sp.segs)))
    rng = random.Random(20261026)
    per = 300
    for name in ("div128-hard", "div256-hard", "sqrt128-hard", "sqrt256-hard"):
        sp = spaces[name]
        cases = idxs = 0
        bad = None
        cannot = {}                 # segment -> the builder's own error, where it cannot build at this p at all
        t0 = time.time()
        for segname, start, count in sp.segs:
            picks = range(start, start + count) if count <= per else [start + rng.randrange(count) for _ in range(per)]
            for idx in picks:
                try:
                    c = H.verify(name, idx)
                except AssertionError as e:
                    bad = "%d: %s" % (idx, e)
                    break
                except ValueError as e:                   # a builder that does not reach this precision
                    cannot[segname] = "%s: %s" % (type(e).__name__, e)
                    break
                idxs += 1
                cases += c
            if bad:
                break
        dt = time.time() - t0
        slots = idxs * sp.k
        print("  %-12s verified %6d indices (every one of the small segments, %d of each large one): %d cases, "
              "%d skipped slots (%.1f%%), %.0f us an index (build and exact check)"
              % (name, idxs, per, cases, slots - cases, 100.0 * (slots - cases) / slots, 1e6 * dt / idxs))
        for segname, err in cannot.items():
            print("  %-12s segment %s CANNOT BE BUILT at p = %d: %s" % (name, segname, sp.p, err))
        check("S2: %s - every sampled index's construction verified exactly" % name, bad is None, bad or "")
        if name == "div256-hard":
            check("S2: div256-hard - the one segment that cannot be built is F1 (64-bit odd-part draw; p <= 131)",
                  list(cannot) == ["F1"] and "negative shift count" in cannot["F1"])
        else:
            check("S2: %s - every segment can be built" % name, not cannot, "; ".join(cannot) if cannot else "")
    # the builders alone, timed on F0 (the largest family)
    for name in ("div128-hard", "div256-hard"):
        sp = spaces[name]
        start = [s for s in sp.segs if s[0] == "F0A"][0][1]
        t0 = time.time()
        n = 0
        for idx in range(start, start + 4000):
            n += H.base_case(sp, idx) is not None
        dt = time.time() - t0
        print("  %-12s F0A builder alone: %d of 4000 indices yield a pair, %.1f us an index" % (name, n, 1e6 * dt / 4000))


def s3(tree):
    import gmpy2
    from cft_golden import softfloat as sf
    from cft_golden.formats import FP128, FP256
    print("\n== S3. the oracles, one desktop core (WSL cft2204, niced): ns a case")
    print("  gmpy2 %s, MPFR %s; a Python loop around each call, so an upper bound on MPFR's own cost"
          % (gmpy2.version(), gmpy2.mpfr_version()))
    rng = random.Random(7)
    n = 20000
    for fname, prec, bits in (("binary128", 113, 128), ("binary256", 237, 256)):
        for rname, rmode in (("rne", gmpy2.RoundToNearest), ("rdn", gmpy2.RoundDown)):
            ctx = gmpy2.ieee(bits)                      # precision, emin, emax and subnormalize of the format
            ctx.round = rmode
            gmpy2.set_context(ctx)
            if rname == "rne":
                print("  %s context: precision %d, emin %d, emax %d, subnormalize %s"
                      % (fname, ctx.precision, ctx.emin, ctx.emax, ctx.subnormalize))
            xs = [gmpy2.mpfr(rng.getrandbits(prec) | (1 << (prec - 1))) * gmpy2.mpfr(2) ** (rng.randrange(-40, 40) - prec)
                  for _ in range(n)]
            ys = [gmpy2.mpfr(rng.getrandbits(prec) | (1 << (prec - 1))) * gmpy2.mpfr(2) ** (rng.randrange(-40, 40) - prec)
                  for _ in range(n)]
            out = []
            for opname, fn in (("add", lambda a, b: a + b), ("mul", lambda a, b: a * b),
                               ("fma", lambda a, b: gmpy2.fma(a, b, a)), ("div", lambda a, b: a / b),
                               ("sqrt", lambda a, b: gmpy2.sqrt(a))):
                t0 = time.perf_counter()
                for a, b in zip(xs, ys):
                    fn(a, b)
                dt = time.perf_counter() - t0
                out.append("%s %.0f" % (opname, 1e9 * dt / n))
            print("  gmpy2 %s %s: %s" % (fname, rname, ", ".join(out)))
    gmpy2.set_context(gmpy2.context())
    # the golden model
    for fmt, w in ((FP128, 128), (FP256, 256)):
        bias = (1 << (fmt.exp_w - 1)) - 1
        def enc():
            return ((bias + rng.randrange(-8, 9)) << fmt.man_w) | rng.getrandbits(fmt.man_w)
        xa = [enc() for _ in range(400)]
        xb = [enc() for _ in range(400)]
        out = []
        for opname, fn in (("add", lambda a, b: sf.add(fmt, a, b)), ("mul", lambda a, b: sf.mul(fmt, a, b)),
                           ("fma", lambda a, b: sf.fma(fmt, a, b, a)), ("div", lambda a, b: sf.div(fmt, a, b)),
                           ("sqrt", lambda a, b: sf.sqrt(fmt, a))):
            t0 = time.perf_counter()
            for a, b in zip(xa, xb):
                fn(a, b)
            dt = time.perf_counter() - t0
            out.append("%s %.1f us" % (opname, 1e6 * dt / len(xa)))
        print("  golden model (python/cft_golden/softfloat.py) %s: %s" % (fmt.name, ", ".join(out)))
    # an exact residual check: y = RNE(sqrt(x)) at precision P for an fp32 input x, in integers only
    for P in (113, 237):
        nchk = 20000
        xs = [(rng.getrandbits(23) | (1 << 23), rng.randrange(-60, 60)) for _ in range(nchk)]
        ys = []
        for m, e in xs:                                   # x = m 2^e; the root's P-bit significand, by isqrt
            if (e - 23) & 1:
                m2, e2 = m << 1, e - 1
            else:
                m2, e2 = m, e
            # sqrt(m2 2^e2) = sqrt(m2 2^(2s)) 2^((e2 - 2s)/2) with enough bits: take 2s so the root has P + 2 bits
            s = P + 2 - (m2.bit_length() + 1) // 2
            r = gmpy_free_isqrt(m2 << (2 * s))
            ys.append((m2, e2, s, r))
        claims = []
        for m2, e2, s, r in ys:
            # the claimed RNE root, as a device would return it: r = floor(sqrt(m2 2^(2s))) rounded half up at bit sh
            # (no root of a non-square is ever exactly halfway, so this is the correctly rounded P-bit significand)
            sh = r.bit_length() - P
            y = ((r >> (sh - 1)) + 1) >> 1
            if y.bit_length() > P:                        # a carry out of the top: the root rounds up a binade
                y >>= 1
                sh += 1
            claims.append((m2, s, sh, y))
        for label, delta in (("the correct claims", 0), ("CONTROL, every claim one ulp high", 1)):
            t0 = time.perf_counter()
            good = 0
            for m2, s, sh, y in claims:
                yy = y + delta
                # yy 2^sh is the RNE root of X = m2 2^(2s) iff (2 yy - 1)^2 2^(2 sh) < 4 X < (2 yy + 1)^2 2^(2 sh):
                # integers only; never equal, since the left and right are odd squares times 2^(2 sh) and X is no square
                X4 = m2 << (2 * s + 2)
                good += ((2 * yy - 1) ** 2 << (2 * sh)) < X4 < ((2 * yy + 1) ** 2 << (2 * sh))
            dt = time.perf_counter() - t0
            print("  exact residual check, %d-bit root of an fp32 input, %s: %.2f us a case in Python, %d of %d pass"
                  % (P, label, 1e6 * dt / nchk, good, nchk))
            if delta == 0:
                check("S3: the residual check passes every correct %d-bit root" % P, good == nchk)
            else:
                check("S3: the residual check refuses every root one ulp high (%d-bit)" % P, good == 0)


def gmpy_free_isqrt(n):
    from math import isqrt
    return isqrt(n)


def main():
    tree = sys.argv[1]
    sys.path.insert(0, tree + "/python")
    t0 = time.time()
    s1(tree)
    s2(tree)
    s3(tree)
    print("\nhx_spaces: %d check(s) failed%s; %.0f s" % (len(FAILS), (": " + "; ".join(FAILS)) if FAILS else "",
                                                       time.time() - t0))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
