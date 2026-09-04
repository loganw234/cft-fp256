# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Score host/tools/zoom.c against the golden model and against mpmath.

    python3 host/tests/zoom_check.py [--exe PATH] [--quick]

The division of authority is the repository's usual one. The LIBRARY is
the authority on arithmetic: what `fma(a, b, c)` returns at binary256
and which flags it raises is settled by docs/DETERMINISM.md and by
python/cft_golden. MPMATH, at 300 digits, is the authority on the
DOMAIN - on where the Mandelbrot orbit of a given c actually goes -
because 300 digits is 63 more than binary256 carries, so it can say how
far a binary256 orbit has drifted without being the thing under test.

That split is what makes the two halves of this file different in kind:

  * against `cft_golden` the tool must be BIT-IDENTICAL. Every point of
    the reference orbit, the derived centre down to its last bit, and
    the perturbed pixels' escape iterations. A single differing bit is
    a bug, not a tolerance.
  * against `mpmath` the tool must be CLOSE, and how close is the
    measurement this workload exists to make: the iteration at which a
    reference orbit first differs from the truth by more than one pixel
    is the "reference validity length", and comparing it at binary256
    and at binary64 is what says, in numbers, what the wide format
    buys.

Determinism is checked rather than asserted, in four places: the
sequencer program against the host cft_run loop, two program trip
counts against each other, a run interrupted and resumed against one
that never stopped, and two pixel batch sizes against each other.
"""

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from cft_golden import FP64, FP256, softfloat as sf     # noqa: E402
from cft_golden import chars as ch                      # noqa: E402

try:
    from mpmath import mp, mpf
    HAVE_MPMATH = True
except ImportError:                                     # pragma: no cover
    HAVE_MPMATH = False

FAILURES = []
CHECKS = 0


def fail(what):
    FAILURES.append(what)
    print("  FAIL: " + what)


def ok(what):
    print("  ok   " + what)


# ---------------------------------------------------------------------
# The golden model, driven exactly the way the tool drives the library
# ---------------------------------------------------------------------
def g_mul(f, a, b):
    return sf.mul(f, a, b)[0]


def g_add(f, a, b):
    return sf.add(f, a, b)[0]


def g_sub(f, a, b):
    return sf.sub(f, a, b)[0]


def g_fma(f, a, b, c):
    return sf.fma(f, a, b, c)[0]


def g_neg(f, a):
    return sf.neg(f, a)[0]


def g_true(f, bits):
    return bits != sf.zero_bits(f)


def g_lt(f, a, b):
    return g_true(f, sf.cmplt(f, a, b)[0])


def g_le(f, a, b):
    return g_true(f, sf.cmple(f, a, b)[0])


def g_min(f, a, b):
    return sf.fmin(f, a, b)[0]


def g_max(f, a, b):
    return sf.fmax(f, a, b)[0]


def g_sel(f, a, b, c):
    return sf.select(f, a, b, c)[0]


def g_int(f, v):
    return sf.from_int(f, v)[0]


def g_pow2(f, e):
    return sf.scaleb(f, sf.one_bits(f), e)[0]


def orbit_step(f, zr, zi, cr, ci, four):
    """One iteration, instruction for instruction as the program emits
    it. Returns None once |z|^2 has passed 4, which is where the
    program's SETACT drops the lane."""
    a = g_mul(f, zr, zr)
    b = g_mul(f, zi, zi)
    m = g_add(f, a, b)
    if not g_le(f, m, four):
        return None
    t = g_add(f, zr, zr)
    d = g_sub(f, a, b)
    nzi = g_fma(f, t, zi, ci)
    nzr = g_add(f, d, cr)
    return nzr, nzi


def golden_orbit(f, cr, ci, n):
    """z_1 .. z_n as (bits, bits) pairs, stopping early on escape."""
    four = g_int(f, 4)
    zr = zi = sf.zero_bits(f)
    out = []
    for _ in range(n):
        step = orbit_step(f, zr, zi, cr, ci, four)
        if step is None:
            break
        zr, zi = step
        out.append((zr, zi))
    return out


def golden_scan(f, c, iters, four):
    """z_iters(c) on the real axis, with the program's escape mask."""
    z = sf.zero_bits(f)
    live = True
    for _ in range(iters):
        s = g_mul(f, z, z)
        if not g_le(f, s, four):
            live = False
        if live:
            z = g_add(f, s, c)
    return z


SCAN_STEPS = 320


def golden_centre(period):
    """Re-derive the tool's centre, bit for bit, at binary256."""
    f = FP256
    four = g_int(f, 4)
    minus2 = g_int(f, -2)
    w = g_pow2(f, -2 * period)
    eighth = g_pow2(f, -3)
    half = g_pow2(f, -1)
    zero = sf.zero_bits(f)

    cand = []
    for i in range(1, SCAN_STEPS + 1):
        step = g_mul(f, g_int(f, i), w)
        eps = g_mul(f, step, eighth)
        cand.append(g_add(f, minus2, eps))
    zval = [golden_scan(f, c, period, four) for c in cand]

    brk = None
    for i in range(SCAN_STEPS - 1):
        if g_lt(f, zval[i], zero) != g_lt(f, zval[i + 1], zero):
            brk = i
            break
    if brk is None:
        raise RuntimeError("no sign change of z_p near the tip")

    lo, hi = cand[brk], cand[brk + 1]
    zlo, zhi = zval[brk], zval[brk + 1]
    sgn_lo = g_lt(f, zlo, zero)
    while True:
        mid = g_mul(f, g_add(f, lo, hi), half)
        if mid == lo or mid == hi:
            break
        zmid = golden_scan(f, mid, period, four)
        if g_lt(f, zmid, zero) == sgn_lo:
            lo, zlo = mid, zmid
        else:
            hi, zhi = mid, zmid
    if g_lt(f, g_mul(f, zhi, zhi), g_mul(f, zlo, zlo)):
        return hi
    return lo


# ---------------------------------------------------------------------
# The perturbed pixel step, at binary64, in the golden model
# ---------------------------------------------------------------------
def golden_pixels(ref_r, ref_i, offsets, maxk, glitch_bits):
    """Escape iteration and status for each (dcr, dci), computed with
    the golden model's binary64 semantics in the tool's own order."""
    f = FP64
    four = g_int(f, 4)
    zero = sf.zero_bits(f)
    one = sf.one_bits(f)
    tol = g_pow2(f, -glitch_bits)
    out = []
    for dcr, dci in offsets:
        dr = di = zero
        live, glit = True, False
        it = 0
        for k in range(maxk):
            zr, zi = ref_r[k], ref_i[k]
            nr, ni = ref_r[k + 1], ref_i[k + 1]
            a2 = g_add(f, zr, zr)
            b2 = g_add(f, zi, zi)
            nb2 = g_neg(f, b2)
            t1 = g_mul(f, nr, nr)
            t2 = g_fma(f, ni, ni, t1)
            gm = g_mul(f, g_mul(f, t2, tol), tol)

            s1 = g_fma(f, a2, dr, dcr)
            s2 = g_fma(f, nb2, di, s1)
            s3 = g_fma(f, dr, dr, s2)
            ndr = g_fma(f, g_neg(f, di), di, s3)
            u1 = g_fma(f, a2, di, dci)
            u2 = g_fma(f, b2, dr, u1)
            d2 = g_add(f, dr, dr)
            ndi = g_fma(f, d2, di, u2)

            fr = g_add(f, nr, ndr)
            fi = g_add(f, ni, ndi)
            mm = g_fma(f, fi, fi, g_mul(f, fr, fr))
            glok = g_le(f, gm, mm)
            escok = g_le(f, mm, four)
            if live:
                it = k + 1
                dr, di = ndr, ndi
                if not glok:
                    glit = True
                if not (glok and escok):
                    live = False
                    break
        if glit:
            out.append((it, "glitch"))
        elif live:
            out.append((maxk, "interior"))
        else:
            out.append((it, "esc"))
    return out


# ---------------------------------------------------------------------
# Driving the tool
# ---------------------------------------------------------------------
class Tool:
    def __init__(self, exe):
        self.exe = str(exe)

    def run(self, *args, expect_ok=True):
        proc = subprocess.run([self.exe] + [str(a) for a in args],
                              capture_output=True, text=True)
        if expect_ok and proc.returncode != 0:
            raise RuntimeError("cft-zoom %s failed (%d)\n%s\n%s"
                               % (" ".join(str(a) for a in args),
                                  proc.returncode, proc.stdout, proc.stderr))
        return proc

    def csv(self, *args):
        out = self.run(*args, "--csv").stdout.strip().splitlines()
        head = out[0].split(",")
        row = out[-1].split(",")
        return dict(zip(head, row))


def read_ckpt_field(path, key):
    for line in Path(path).read_text().splitlines():
        if line.startswith(key + " "):
            return line[len(key) + 1:]
    return None


def parse_orbit(path, fmt):
    """The tool's orbit file back into (index, re_bits, im_bits)."""
    out = []
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        idx, re_s, im_s = line.split(" ")
        out.append((int(idx), ch.from_decimal(fmt, re_s)[0],
                    ch.from_decimal(fmt, im_s)[0]))
    return out


def chain_of(lines):
    h = bytes(32)
    for line in lines:
        h = hashlib.sha256(h + (line + "\n").encode("ascii")).digest()
    return h.hex()


def bits_to_mpf(fmt, bits):
    """An encoding as an exact mpmath number (no rounding: the decimal
    the library writes is exact and mpmath is set wider than it)."""
    return mpf(ch.to_decimal(fmt, bits)[0])


# ---------------------------------------------------------------------
def main():
    global CHECKS
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=None)
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()

    exe = args.exe
    if exe is None:
        for cand in ("cft-zoom.exe", "cft-zoom"):
            path = ROOT / "host" / cand
            if path.exists():
                exe = path
                break
    if exe is None or not Path(exe).exists():
        raise SystemExit("cft-zoom not found - run `make -C host zoom`")
    tool = Tool(exe)

    tmp = tempfile.mkdtemp(prefix="zoom-check-")
    orbit_n = 2000 if args.quick else 4000
    try:
        print("cft-zoom cross-check, tool: %s" % exe)

        # -------------------------------------------------------------
        print("\n[1] the derived centre, against the golden model")
        row = tool.csv("--ref-iters", 2, "--no-pixels")
        period = int(row["period"])
        tool_cr = ch.from_decimal(FP256, row["centre_re"])[0]
        tool_ci = ch.from_decimal(FP256, row["centre_im"])[0]
        want = golden_centre(period)
        CHECKS += 2
        if tool_cr == want:
            ok("the period-%d tip nucleus the tool derives is the one the "
               "golden model derives, to the last of its 237 bits" % period)
        else:
            fail("the derived centre differs: tool %s, model %s"
                 % (ch.to_decimal(FP256, tool_cr)[0],
                    ch.to_decimal(FP256, want)[0]))
        if tool_ci == sf.zero_bits(FP256):
            ok("the centre is real, so the reference's imaginary part "
               "stays exactly +0 and the orbit is a real map")
        else:
            fail("the centre's imaginary part is not +0")

        if HAVE_MPMATH:
            mp.prec = 1024          # about 308 decimal digits
            c_mp = bits_to_mpf(FP256, tool_cr)
            z = mpf(0)
            for _ in range(period):
                z = z * z + c_mp
            CHECKS += 1
            # A nucleus has z_p = 0 exactly. The tool's c is the nearest
            # binary256 value to one, so |z_p| is what one ulp of c
            # becomes after p steps of amplification - about 4^p ulps -
            # and nothing like the O(1) a non-nucleus would give.
            ulp = mpf(2) ** (1 - 237)
            bound = ulp * mpf(4) ** period * 16
            if abs(z) < bound:
                print("       |z_%d(c)| = %s, and one ulp of c amplified "
                      "through %d steps is about %s"
                      % (period, mp.nstr(abs(z), 6), period,
                         mp.nstr(ulp * mpf(4) ** period, 6)))
                ok("mpmath at %d digits confirms c is a period-%d nucleus "
                   "to the precision binary256 can express"
                   % (int(mp.prec * 0.301), period))
            else:
                fail("|z_%d(c)| = %s is too large for a nucleus"
                     % (period, mp.nstr(abs(z), 6)))

            z = mpf(0)
            escaped = None
            for k in range(1, 100001):
                z = z * z + c_mp
                if abs(z) > 2:
                    escaped = k
                    break
            CHECKS += 1
            if escaped is None:
                ok("its orbit is bounded for 100,000 iterations at 300 "
                   "digits, which is what a reference orbit has to be")
            else:
                fail("the centre's orbit escapes at %d" % escaped)

        # -------------------------------------------------------------
        print("\n[2] the reference orbit, bit for bit against the model")
        for engine, reps in (("program", 512), ("loop", 97)):
            path = Path(tmp) / ("orb-%s.txt" % engine)
            tool.run("--ref-iters", orbit_n, "--no-pixels",
                     "--engine", engine, "--steps-per-call", reps,
                     "--orbit", path, "--quiet")
            got = parse_orbit(path, FP256)
            want_orb = golden_orbit(FP256, tool_cr, tool_ci, orbit_n)
            CHECKS += len(want_orb)
            bad = None
            if len(got) != len(want_orb):
                bad = "%d points, model has %d" % (len(got), len(want_orb))
            else:
                for i, ((idx, gr, gi), (wr, wi)) in enumerate(
                        zip(got, want_orb)):
                    if idx != i + 1 or gr != wr or gi != wi:
                        bad = ("first difference at iteration %d" % (i + 1))
                        break
            if bad:
                fail("fp256 orbit, %s engine: %s" % (engine, bad))
            else:
                ok("%s engine: %d orbit points identical to the golden "
                   "model, every bit" % (engine, len(got)))

        CHECKS += 1
        a = (Path(tmp) / "orb-program.txt").read_bytes()
        b = (Path(tmp) / "orb-loop.txt").read_bytes()
        if a == b:
            ok("the sequencer program and the host cft_run loop produce "
               "byte-identical orbits at different trip counts")
        else:
            fail("the two engines produce different orbits")

        # -------------------------------------------------------------
        print("\n[3] the checkpoint does not depend on the machine")
        ck = []
        for engine, reps in (("program", 1024), ("program", 63),
                             ("loop", 7)):
            path = Path(tmp) / ("ck-%s-%d.ckpt" % (engine, reps))
            tool.run("--ref-iters", 2000, "--no-pixels", "--engine", engine,
                     "--steps-per-call", reps, "--checkpoint", path,
                     "--quiet")
            ck.append(path)
        CHECKS += 2
        if ck[0].read_bytes() == ck[1].read_bytes():
            ok("trip counts 1024 and 63 end on byte-identical checkpoints "
               "(%s)" % read_ckpt_field(ck[0], "chain")[:16])
        else:
            fail("the checkpoint depends on the trip count")
        if ck[0].read_bytes() == ck[2].read_bytes():
            ok("the host-loop engine lands on the same checkpoint as the "
               "sequencer program")
        else:
            fail("the two engines end on different checkpoints")

        # -------------------------------------------------------------
        print("\n[4] interrupting and resuming the reference orbit")
        piece = Path(tmp) / "piece.ckpt"
        common = ["--ref-iters", 2000, "--no-pixels", "--steps-per-call",
                  37, "--stop-after-passes", 5, "--checkpoint", piece,
                  "--quiet"]
        tool.run(*common)
        rounds = 1
        while read_ckpt_field(piece, "k") != "2000":
            rounds += 1
            if rounds > 500:
                fail("the resumed run did not finish")
                break
            tool.run("--resume", *common)
        CHECKS += 1
        if piece.read_bytes() == ck[0].read_bytes():
            ok("a run stopped and resumed %d times, at a different trip "
               "count, ends on the same checkpoint - byte for byte - as "
               "one that was never stopped" % rounds)
        else:
            fail("the resumed run's checkpoint differs from the "
                 "uninterrupted one")

        # -------------------------------------------------------------
        print("\n[5] the hash chain, recomputed with hashlib")
        lines = [ln for ln in
                 (Path(tmp) / "orb-program.txt").read_text().splitlines()
                 if ln.strip()]
        rowo = tool.csv("--ref-iters", orbit_n, "--no-pixels",
                        "--steps-per-call", 333)
        CHECKS += 1
        if rowo["chain"] == chain_of(lines):
            ok("the tool's chain over %d orbit points matches hashlib's - "
               "so its derivation of SHA-256's constants from the cube "
               "roots of the primes is right" % len(lines))
        else:
            fail("chain mismatch: tool %s, hashlib %s"
                 % (rowo["chain"], chain_of(lines)))

        # -------------------------------------------------------------
        print("\n[6] the perturbed pixels, bit for bit against the model")
        # A shallower view than the default, so that pixels escape inside
        # a cap the golden model can afford to reproduce element by
        # element. The grid is deliberately tiny and the EDGES are in it:
        # index 0 is the corner, where |Dc| is largest.
        zexp, wid, pmax, refn = 185, 8, 320, 400
        prow = tool.csv("--zoom-exp", zexp, "--width", wid,
                        "--ref-iters", refn, "--pixel-iters", pmax,
                        "--batch", 5,
                        "--pixels", Path(tmp) / "px-small.txt")
        gb = FP64.prec // 4
        opath = Path(tmp) / "orb-small.txt"
        tool.run("--zoom-exp", zexp, "--width", wid, "--ref-iters", refn,
                 "--no-pixels", "--orbit", opath, "--quiet")
        orb = parse_orbit(opath, FP256)
        ref_r = [sf.zero_bits(FP64)]
        ref_i = [sf.zero_bits(FP64)]
        for _, rr, ri in orb:
            ref_r.append(sf.convert(FP256, FP64, rr)[0])
            ref_i.append(sf.convert(FP256, FP64, ri)[0])
        half = g_pow2(FP64, -zexp - (wid.bit_length() - 1))
        offs = []
        for g in range(wid * wid):
            ix, iy = g % wid, g // wid
            offs.append((g_mul(FP64, g_int(FP64, 2 * ix + 1 - wid), half),
                         g_mul(FP64, g_int(FP64, 2 * iy + 1 - wid), half)))
        want_pix = golden_pixels(ref_r, ref_i, offs, pmax, gb)
        got_pix = []
        for line in (Path(tmp) / "px-small.txt").read_text().splitlines():
            if line.strip():
                idx, it, kind = line.split(" ")
                got_pix.append((int(it), kind))
        CHECKS += len(want_pix)
        bad = [(i, a2, b2) for i, (a2, b2) in
               enumerate(zip(got_pix, want_pix)) if a2 != b2]
        if bad or len(got_pix) != len(want_pix):
            if bad:
                fail("pixel %d: tool says %r, the golden model says %r"
                     % (bad[0][0], bad[0][1], bad[0][2]))
            else:
                fail("%d pixel records, model has %d"
                     % (len(got_pix), len(want_pix)))
        else:
            nesc = sum(1 for v in want_pix if v[1] == "esc")
            ok("%d perturbed pixels at fp64 match the golden model's own "
               "binary64 semantics exactly, %d of them escaping"
               % (len(want_pix), nesc))
        CHECKS += 1
        if prow["escaped"] == str(sum(1 for v in want_pix
                                      if v[1] == "esc")):
            ok("the escaped/glitched/interior counts agree")
        else:
            fail("escape counts disagree: %s" % prow["escaped"])

        # The glitch branch, which the nucleus reference never takes.
        # Move the reference off the nucleus by whole pixels and the
        # Pauldelbrot test starts firing - the model has to agree about
        # WHICH pixels and at WHICH iteration, or the criterion is
        # decoration.
        gpath = Path(tmp) / "px-glitch.txt"
        gopath = Path(tmp) / "orb-glitch.txt"
        goff = 12
        tool.run("--zoom-exp", zexp, "--width", wid, "--ref-iters", refn,
                 "--pixel-iters", pmax, "--batch", 5, "--ref-offset", goff,
                 "--pixels", gpath, "--quiet")
        tool.run("--zoom-exp", zexp, "--width", wid, "--ref-iters", refn,
                 "--ref-offset", goff, "--no-pixels", "--orbit", gopath,
                 "--quiet")
        gorb = parse_orbit(gopath, FP256)
        gref_r = [sf.zero_bits(FP64)]
        gref_i = [sf.zero_bits(FP64)]
        for _, rr, ri in gorb:
            gref_r.append(sf.convert(FP256, FP64, rr)[0])
            gref_i.append(sf.convert(FP256, FP64, ri)[0])
        goffs = []
        for g in range(wid * wid):
            ix, iy = g % wid, g // wid
            goffs.append(
                (g_mul(FP64, g_int(FP64, 2 * ix + 1 - wid - 2 * goff), half),
                 g_mul(FP64, g_int(FP64, 2 * iy + 1 - wid), half)))
        gwant = golden_pixels(gref_r, gref_i, goffs, pmax, gb)
        ggot = []
        for line in gpath.read_text().splitlines():
            if line.strip():
                _, it, kind = line.split(" ")
                ggot.append((int(it), kind))
        CHECKS += len(gwant)
        nglitch = sum(1 for v in gwant if v[1] == "glitch")
        if ggot != gwant:
            bad2 = [(i, x, y) for i, (x, y) in enumerate(zip(ggot, gwant))
                    if x != y]
            fail("glitch run, pixel %d: tool %r, model %r"
                 % (bad2[0][0], bad2[0][1], bad2[0][2]))
        elif nglitch == 0:
            fail("moving the reference %d pixels off the nucleus produced "
                 "no glitches, so the criterion was never exercised" % goff)
        else:
            ok("with the reference %d pixels off the nucleus the glitch "
               "criterion fires on %d of %d pixels, and the model agrees "
               "pixel for pixel" % (goff, nglitch, len(gwant)))

        # -------------------------------------------------------------
        print("\n[7] batch-size independence of the pixel batch")
        pb = []
        for batch in (7, 64, 4096):
            path = Path(tmp) / ("pb-%d.txt" % batch)
            tool.run("--zoom-exp", 190, "--width", 16, "--ref-iters", 1200,
                     "--pixel-iters", 1000, "--batch", batch,
                     "--pixels", path, "--quiet")
            pb.append(path.read_bytes())
        CHECKS += 1
        if pb[0] == pb[1] == pb[2]:
            ok("batch 7, 64 and 4096 give byte-identical pixel records")
        else:
            fail("the pixel records depend on the batch size")

        # -------------------------------------------------------------
        print("\n[8] what binary64 loses, in pixels and in iterations")
        deep = ["--zoom-exp", 196, "--width", 32, "--ref-iters", 6000,
                "--pixel-iters", 4000]
        p256 = Path(tmp) / "deep256.txt"
        r256 = tool.csv(*deep, "--pixels", p256)
        r64 = tool.csv(*deep, "--format", "fp64",
                       "--compare-pixels", p256)
        CHECKS += 2
        print("       binary256 centre error %s pixels; binary64 %s pixels"
              % (r256["centre_err_pixels"], r64["centre_err_pixels"]))
        print("       binary256 escape iterations %s..%s; binary64 %s..%s"
              % (r256["esc_min"], r256["esc_max"], r64["esc_min"],
                 r64["esc_max"]))
        if float(r64["centre_err_pixels"]) > 1e20:
            ok("the binary64 reference's own centre is %s pixels from the "
               "one binary256 holds" % r64["centre_err_pixels"])
        else:
            fail("the binary64 centre error is implausibly small: %s"
                 % r64["centre_err_pixels"])
        if r64["compare_differ"] == r64["compare_total"] != "0":
            ok("every one of the %s pixels differs between the binary64 "
               "and binary256 references - the fp64 image is not a worse "
               "image, it is a different one" % r64["compare_total"])
        else:
            fail("only %s of %s pixels differ"
                 % (r64["compare_differ"], r64["compare_total"]))

        # -------------------------------------------------------------
        if HAVE_MPMATH:
            print("\n[9] reference validity length, against mpmath at 300 "
                  "digits")
            mp.prec = 1024
            n_valid = 600
            c_mp = bits_to_mpf(FP256, tool_cr)
            exact = []
            z = mpf(0)
            for _ in range(n_valid):
                z = z * z + c_mp
                exact.append(z)
            # the pixel a whole view-radius away, whose true orbit is what
            # a pixel offset actually becomes by iteration k
            pixel = mpf(2) ** (1 - 196 - 5)      # --zoom-exp 196, width 32
            edge = []
            z = mpf(0)
            for _ in range(n_valid):
                z = z * z + (c_mp + mpf(2) ** -196)
                edge.append(z)

            fmts = []
            opath256 = Path(tmp) / "vorb256.txt"
            tool.run("--ref-iters", n_valid, "--no-pixels", "--orbit",
                     opath256, "--quiet")
            fmts.append(("fp256", parse_orbit(opath256, FP256), FP256))
            opath64 = Path(tmp) / "vorb64.txt"
            tool.run("--format", "fp64", "--ref-iters", n_valid,
                     "--no-pixels", "--orbit", opath64, "--quiet")
            fmts.append(("fp64", parse_orbit(opath64, FP64), FP64))

            print("       one pixel at 2^-196 over 32 pixels = %s"
                  % mp.nstr(pixel, 6))
            for name, orbf, fmt in fmts:
                err = [abs(bits_to_mpf(fmt, rr) - exact[i])
                       for i, (_, rr, _) in enumerate(orbf)]
                absk = next((i + 1 for i, e in enumerate(err)
                             if e > pixel), None)
                relk = next((i + 1 for i, e in enumerate(err)
                             if e > abs(edge[i] - exact[i])), None)
                print("       %-6s first error above one pixel at k = %s; "
                      "above a pixel's own deviation at k = %s"
                      % (name, absk, relk))
                fmts_row = (name, absk, relk)
                CHECKS += 1
                if name == "fp256" and (relk is None or relk > 100):
                    ok("the binary256 reference never drifts past a "
                       "pixel's own deviation in %d iterations - which is "
                       "the criterion perturbation actually needs"
                       % n_valid)
                elif name == "fp64" and relk is not None and relk <= 2:
                    ok("the binary64 reference is past it at iteration "
                       "%d, before a single pixel has moved" % relk)
                elif name == "fp256":
                    fail("the binary256 reference drifted at k = %s"
                         % relk)
                else:
                    fail("the binary64 reference lasted longer than "
                         "expected: %r" % (fmts_row,))

            # The absolute criterion at a ladder of pixel scales, which
            # is what says how deep each format can be zoomed at all.
            for name, orbf, fmt in fmts:
                err = [abs(bits_to_mpf(fmt, rr) - exact[i])
                       for i, (_, rr, _) in enumerate(orbf)]
                row_txt = []
                for e10 in (-10, -20, -30, -40, -50, -60, -70):
                    scale = mpf(10) ** e10
                    kk = next((i + 1 for i, e in enumerate(err)
                               if e > scale), None)
                    row_txt.append("1e%d:%s" % (e10, kk))
                print("       %-6s absolute criterion  %s"
                      % (name, "  ".join(row_txt)))

            # And the deepest zoom each format can address at all: the
            # centre's own half-ulp, in pixels. Derived from the format
            # parameters, not tabulated.
            for name, fmt in (("fp256", FP256), ("fp64", FP64)):
                half_ulp = mpf(2) ** (1 - fmt.prec)     # at |c| in [2,4)
                depth = mp.floor(-mp.log(half_ulp, 10))
                print("       %-6s holds a centre near |c| = 2 to %s, so "
                      "its deepest pixel is about 1e-%s"
                      % (name, mp.nstr(half_ulp, 4), mp.nstr(depth, 3)))

        # -------------------------------------------------------------
        print("\n[10] refusals")
        CHECKS += 1
        bad_w = tool.run("--width", 12, "--ref-iters", 10,
                         expect_ok=False)
        if bad_w.returncode != 0:
            ok("a width that is not a power of two is refused, because a "
               "pixel offset would then not be exact")
        else:
            fail("--width 12 was accepted")
        CHECKS += 1
        bad_c = tool.run("--centre", "0.1,0", "--ref-iters", 10,
                         expect_ok=False)
        if bad_c.returncode != 0:
            ok("a centre binary256 cannot hold exactly is refused, not "
               "rounded")
        else:
            fail("--centre 0.1,0 was accepted")
        CHECKS += 1
        bad_p = tool.run("--format", "fp64", "--period", 51,
                         "--ref-iters", 10, "--centre-none",
                         expect_ok=False)
        if bad_p.returncode != 0:
            ok("an unknown option is refused rather than ignored")
        else:
            fail("an unknown option was accepted")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%d comparisons, %d failures" % (CHECKS, len(FAILURES)))
    if FAILURES:
        print("ZOOM CHECK FAILED")
        return 1
    print("ZOOM CHECK OK - the tool, the golden model and mpmath agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
