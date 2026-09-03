# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""libcft's reduction tree against the golden model's, over the same inputs.

    python3 host/tests/reduce_check.py                 # standard sweep
    python3 host/tests/reduce_check.py --trials 4000
    python3 host/tests/reduce_check.py --formats fp256 --rounding rdn

Two independent implementations of one tree shape. The arithmetic at
each node is already cross-checked by diff_check.py, so what this adds
is the SHAPE: a reduction is only reproducible if both sides split the
index range the same way, at every level, for every n - and n is where
this goes wrong, because a shape that agrees on powers of two can
disagree on 5, 9 or 13 and never be noticed by a test that only tries
round numbers.

So the sizes here are deliberately awkward. Every n from 0 to 40 is
covered exhaustively, then random larger ones, because the small odd
sizes are exactly where a floor-vs-ceiling midpoint or an
extra-element-goes-left convention diverges.

It also checks the two calling-convention refusals in both directions,
since a reduction issued through cft_run() or an elementwise op issued
through cft_reduce() must be an error rather than a plausible number.

All seven of clause 9.4's reductions are here. The five that arrived
with the 0.6 step bring two kinds of claim beyond "the C agrees with
the model", and both are checked THROUGH THE LIBRARY rather than in the
model, because they are claims about what the library does:

  - the two COMPOSITION IDENTITIES. sumSquare is cft_reduce(CFT_DOT,
    a, a) and sumAbs is an abs pass then CFT_SUM, bit for bit and flag
    for flag, on every input except the one row 9.4 orders differently
    (an infinity beside a NaN). Those are how the device and software
    backends are made to agree, so a run that did not check them would
    be taking the mechanism on trust.
  - the SCALED PRODUCTS' invariant: pr is always in +-[1, 2), and a
    plain scaledProd never signals overflow or underflow no matter how
    far its true product leaves the format. Checked over pools built
    to leave it - twenty maxfinites, twenty minimum subnormals, and
    the two alternating.
"""

import argparse
import ctypes
import os
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from cft_golden import (  # noqa: E402
    FORMATS, PREC_CODE, RND_NAMES,
    FLAG_OVERFLOW, FLAG_UNDERFLOW, is_nan, max_normal_bits,
    min_subnormal_bits, unpack,
)
from cft_golden.reduce import (  # noqa: E402
    OP_SUM, OP_DOT, OP_SUMSQ, OP_SUMABS, SP_PROD, SP_PROD_SUM,
    SP_PROD_DIFF, SCALED_KINDS, SCALED_KIND_NAMES,
    canonical_ranges, combine, fdot, fsum, fsumabs, fsumsq, reduce_bits,
    scaled_prod, split,
)

RND_BY_NAME = {v: k for k, v in RND_NAMES.items()}

CFT_OK = 0
CFT_ERR_INVALID_ARGUMENT = 1
CFT_ERR_UNSUPPORTED = 2

OP_FMA = 0          # an elementwise opcode, for the refusal check

# The four reductions cft_reduce carries, and the model function each
# is scored against. Keyed by opcode so a new one cannot be added to
# the sweep without also being given a definition to be wrong against.
REDUCE_REF = {
    OP_SUM:    lambda fmt, xs, ys, rnd: fsum(fmt, xs, rnd),
    OP_DOT:    lambda fmt, xs, ys, rnd: fdot(fmt, xs, ys, rnd),
    OP_SUMSQ:  lambda fmt, xs, ys, rnd: fsumsq(fmt, xs, rnd),
    OP_SUMABS: lambda fmt, xs, ys, rnd: fsumabs(fmt, xs, rnd),
}
REDUCE_NAMES = {OP_SUM: "sum", OP_DOT: "dot",
                OP_SUMSQ: "sumsq", OP_SUMABS: "sumabs"}


def load_library():
    override = os.environ.get("CFT_LIB")
    if override:
        path = Path(override)
    else:
        name = {"win32": "cft.dll", "cygwin": "cft.dll",
                "darwin": "libcft.dylib"}.get(sys.platform, "libcft.so")
        path = ROOT / "host" / name
    if not path.exists():
        raise SystemExit(
            f"{path} not found - build it first:\n"
            "    make -C host\n"
            "or point CFT_LIB at the shared library.")
    return ctypes.CDLL(str(path))


def bind(lib):
    u32p = ctypes.POINTER(ctypes.c_uint32)
    lib.cft_open.argtypes = [ctypes.c_char_p, ctypes.c_int,
                             ctypes.POINTER(ctypes.c_void_p)]
    lib.cft_open.restype = ctypes.c_int
    lib.cft_close.argtypes = [ctypes.c_void_p]
    lib.cft_close.restype = None
    lib.cft_reduce.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                               ctypes.c_void_p, ctypes.c_size_t, u32p, u32p]
    lib.cft_reduce.restype = ctypes.c_int
    lib.cft_run.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                            u32p, u32p]
    lib.cft_run.restype = ctypes.c_int
    lib.cft_op_name.argtypes = [ctypes.c_int]
    lib.cft_op_name.restype = ctypes.c_char_p
    lib.cft_supports.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    lib.cft_supports.restype = ctypes.c_int
    i64p = ctypes.POINTER(ctypes.c_int64)
    lib.cft_scaled_prod.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_void_p,
                                    ctypes.c_void_p, i64p, ctypes.c_size_t,
                                    u32p]
    lib.cft_scaled_prod.restype = ctypes.c_int
    for name in ("cft_scaled_prod_sum", "cft_scaled_prod_diff"):
        fn = getattr(lib, name)
        fn.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                       ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                       i64p, ctypes.c_size_t, u32p]
        fn.restype = ctypes.c_int


def to_bytes(fmt, values):
    esz = fmt.width // 8
    buf = bytearray()
    for v in values:
        buf += int(v).to_bytes(esz, "little")
    return bytes(buf)


def rand_finite(fmt, rng, spread=20):
    sign = rng.getrandbits(1)
    e = fmt.bias + rng.randint(-spread, spread)
    m = rng.getrandbits(fmt.man_w)
    return (sign << (fmt.width - 1)) | (e << fmt.man_w) | m


def rand_operand(fmt, rng):
    """Mostly ordinary numbers, with specials mixed in at a rate high
    enough to be hit and low enough that the arithmetic still gets
    exercised. A reduction over nothing but NaNs proves very little."""
    r = rng.random()
    if r < 0.04:
        return (fmt.exp_mask << fmt.man_w) | (1 << (fmt.man_w - 1))   # qNaN
    if r < 0.07:
        return rng.getrandbits(1) << (fmt.width - 1) | \
            (fmt.exp_mask << fmt.man_w)                              # inf
    if r < 0.11:
        return rng.getrandbits(1) << (fmt.width - 1)                 # zero
    if r < 0.15:
        return (rng.getrandbits(1) << (fmt.width - 1)) | \
            rng.randrange(1, 1 << fmt.man_w)                         # subnormal
    return rand_finite(fmt, rng)


class Checker:
    def __init__(self, lib, dev):
        self.lib, self.dev = lib, dev
        self.checked = 0
        self.failed = 0

    def call(self, op, fmt, rnd, xs, ys=None, n=None):
        esz = fmt.width // 8
        if n is None:
            n = len(xs)
        a = ctypes.create_string_buffer(to_bytes(fmt, xs), max(len(xs), 1) * esz)
        b = None
        if ys is not None:
            b = ctypes.create_string_buffer(to_bytes(fmt, ys),
                                            max(len(ys), 1) * esz)
        d = ctypes.create_string_buffer(esz)
        flags = ctypes.c_uint32(0xDEADBEEF)
        st = self.lib.cft_reduce(
            self.dev, op, PREC_CODE[fmt.name], rnd,
            ctypes.cast(a, ctypes.c_void_p),
            ctypes.cast(b, ctypes.c_void_p) if b is not None else None,
            ctypes.cast(d, ctypes.c_void_p), n,
            ctypes.byref(flags), None)
        if st != CFT_OK:
            return st, None, None
        return st, int.from_bytes(d.raw[:esz], "little"), flags.value

    def one(self, op, fmt, rnd, xs, ys):
        st, got, gflags = self.call(op, fmt, rnd, xs, ys if op == OP_DOT
                                    else None)
        want, wflags = REDUCE_REF[op](fmt, xs, ys, rnd)
        self.checked += 1
        if st != CFT_OK:
            self.fail(op, fmt, rnd, xs, ys, f"status {st}")
        elif got != want or gflags != wflags:
            self.fail(op, fmt, rnd, xs, ys,
                      f"got 0x{got:x}/{gflags:02x} "
                      f"want 0x{want:x}/{wflags:02x}")

    def scaled(self, kind, fmt, rnd, xs, ys):
        """One scaled product against the model, pr AND scale AND flags.

        Also asserts the invariant the operation exists for, on every
        call that reaches the tree: pr in +-[1, 2), and no overflow or
        underflow from a plain scaledProd whatever its true product is.
        """
        esz = fmt.width // 8
        n = len(xs)
        a = ctypes.create_string_buffer(to_bytes(fmt, xs), max(n, 1) * esz)
        b = ctypes.create_string_buffer(to_bytes(fmt, ys), max(n, 1) * esz)
        pr = ctypes.create_string_buffer(esz)
        scale = ctypes.c_int64(-0x5EED)
        flags = ctypes.c_uint32(0xDEADBEEF)
        fn = {SP_PROD: self.lib.cft_scaled_prod,
              SP_PROD_SUM: self.lib.cft_scaled_prod_sum,
              SP_PROD_DIFF: self.lib.cft_scaled_prod_diff}[kind]
        args = [self.dev, PREC_CODE[fmt.name], rnd,
                ctypes.cast(a, ctypes.c_void_p)]
        if kind != SP_PROD:
            args.append(ctypes.cast(b, ctypes.c_void_p))
        args += [ctypes.cast(pr, ctypes.c_void_p), ctypes.byref(scale), n,
                 ctypes.byref(flags)]
        st = fn(*args)
        self.checked += 1
        if st != CFT_OK:
            self.fail_scaled(kind, fmt, rnd, xs, ys, f"status {st}")
            return
        got = int.from_bytes(pr.raw[:esz], "little")
        wpr, wsf, wfl = scaled_prod(fmt, xs, ys if kind != SP_PROD else None,
                                    kind, rnd)
        if got != wpr or scale.value != wsf or flags.value != wfl:
            self.fail_scaled(kind, fmt, rnd, xs, ys,
                             f"got 0x{got:x}/{scale.value}/{flags.value:02x} "
                             f"want 0x{wpr:x}/{wsf}/{wfl:02x}")
            return
        # the invariant, asserted on the library's own answer
        if kind == SP_PROD and (flags.value & (FLAG_OVERFLOW |
                                               FLAG_UNDERFLOW)):
            self.fail_scaled(kind, fmt, rnd, xs, ys,
                             "a plain scaledProd raised overflow or "
                             f"underflow (0x{flags.value:02x})")
            return
        if n and not is_nan(fmt, got) and \
                (got & ~fmt.sign_mask) not in (0, fmt.exp_mask << fmt.man_w):
            u = unpack(fmt, got)
            if u.e + u.m.bit_length() - 1 != 0:
                self.fail_scaled(kind, fmt, rnd, xs, ys,
                                 f"pr 0x{got:x} is not in +-[1, 2)")

    def fail(self, op, fmt, rnd, xs, ys, why):
        self.failed += 1
        if self.failed <= 5:
            name = REDUCE_NAMES[op]
            print(f"FAIL {name} {fmt.name} {RND_NAMES[rnd]} n={len(xs)}: {why}")
            print(f"     a = {[hex(x) for x in xs[:6]]}")
            if op == OP_DOT:
                print(f"     b = {[hex(y) for y in ys[:6]]}")

    def fail_scaled(self, kind, fmt, rnd, xs, ys, why):
        self.failed += 1
        if self.failed <= 5:
            print(f"FAIL {SCALED_KIND_NAMES[kind]} {fmt.name} "
                  f"{RND_NAMES[rnd]} n={len(xs)}: {why}")
            print(f"     a = {[hex(x) for x in xs[:6]]}")
            if kind != SP_PROD:
                print(f"     b = {[hex(y) for y in ys[:6]]}")


def check_identities(ck, fmt, rng, trials):
    """The two compositions, THROUGH THE LIBRARY.

    sumSquare must be bit-identical to cft_reduce(CFT_DOT, a, a) and
    sumAbs to an abs pass followed by CFT_SUM - flags included, at every
    n and in every attribute. That is not a nice property that happens
    to hold: it is the mechanism by which a device backend and the
    software backend give the same bits, so it is checked here rather
    than assumed from the fact that the library issues those calls.

    The one input class 9.4 excludes - an infinity AND a NaN in the same
    vector, where the standard puts +inf ahead of the quiet NaN - is
    counted separately and checked against the OVERRIDE instead, with
    the plain dot as the negative control. Skipping it silently would
    hide the day the override stopped firing.
    """
    esz = fmt.width // 8
    bad = 0
    identical = overridden = 0
    for _ in range(trials):
        n = rng.choice([0, 1, 2, 3, 4, 5, 7, 8, 9, 15, 16, 17, 31, 32, 33,
                        63, 64, 65, 127, 128, 129])
        rnd = rng.choice(list(RND_NAMES))
        xs = [rand_operand(fmt, rng) for _ in range(n)]
        has_inf = any(((x >> fmt.man_w) & fmt.exp_mask) == fmt.exp_mask and
                      not (x & fmt.man_mask) for x in xs)
        has_nan = any(((x >> fmt.man_w) & fmt.exp_mask) == fmt.exp_mask and
                      (x & fmt.man_mask) for x in xs)

        st_sq, sq, f_sq = ck.call(OP_SUMSQ, fmt, rnd, xs)
        st_dot, dot, f_dot = ck.call(OP_DOT, fmt, rnd, xs, xs)
        st_ab, ab, f_ab = ck.call(OP_SUMABS, fmt, rnd, xs)
        # the abs pass, through the library, then the sum
        a = ctypes.create_string_buffer(to_bytes(fmt, xs), max(n, 1) * esz)
        w = ctypes.create_string_buffer(max(n, 1) * esz)
        fl = ctypes.c_uint32(0)
        st_abs = ck.lib.cft_run(ck.dev, 4, PREC_CODE[fmt.name], rnd,
                                ctypes.cast(a, ctypes.c_void_p), None, None,
                                ctypes.cast(w, ctypes.c_void_p), n,
                                ctypes.byref(fl), None)
        absed = [int.from_bytes(w.raw[i * esz:(i + 1) * esz], "little")
                 for i in range(n)]
        st_sum, s, f_sum = ck.call(OP_SUM, fmt, rnd, absed)
        ck.checked += 2
        if CFT_OK not in (st_sq, st_dot, st_ab, st_sum) or st_abs != CFT_OK:
            print(f"FAIL identity call status {fmt.name} n={n}")
            bad += 1
            continue

        if has_inf and has_nan:
            overridden += 1
            want = (fmt.exp_mask << fmt.man_w)          # +inf
            if sq != want or ab != want:
                print(f"FAIL override {fmt.name} {RND_NAMES[rnd]} n={n}: "
                      f"sumsq 0x{sq:x} sumabs 0x{ab:x}, want +inf")
                bad += 1
            # the negative control: the plain tree says NaN there
            elif not is_nan(fmt, dot):
                print(f"FAIL override {fmt.name} n={n}: the plain dot did "
                      f"not return a NaN (0x{dot:x}), so the override "
                      "cannot be shown to be doing anything")
                bad += 1
        else:
            identical += 1
            if (sq, f_sq) != (dot, f_dot):
                print(f"FAIL sumsq != dot(a,a) {fmt.name} {RND_NAMES[rnd]} "
                      f"n={n}: 0x{sq:x}/{f_sq:02x} vs 0x{dot:x}/{f_dot:02x}")
                bad += 1
            if (ab, f_ab) != (s, f_sum | fl.value):
                print(f"FAIL sumabs != abs+sum {fmt.name} {RND_NAMES[rnd]} "
                      f"n={n}: 0x{ab:x}/{f_ab:02x} vs 0x{s:x}/"
                      f"{f_sum | fl.value:02x}")
                bad += 1
    print(f"  {fmt.name}: {identical} vectors where both identities hold "
          f"verbatim, {overridden} where 9.4's infinity-over-NaN row "
          f"applies instead")
    if overridden == 0:
        print("FAIL the override was never exercised - this check is not "
              "checking what it says it is")
        bad += 1
    return bad


def scaled_pools(fmt, rng):
    """Vectors whose true product leaves the format many times over.

    The point of a scaled product is that these are ordinary inputs to
    it, so they are the ones it should be scored on.
    """
    big, tiny = max_normal_bits(fmt), min_subnormal_bits(fmt)
    nbig, ntiny = max_normal_bits(fmt, 1), min_subnormal_bits(fmt, 1)
    return [
        [big] * 20,
        [tiny] * 20,
        [big, tiny] * 12,
        [nbig, ntiny, big, tiny] * 6,
        [big] * 9 + [tiny] * 3,
        [rand_operand(fmt, rng) for _ in range(17)],
        [rand_finite(fmt, rng, spread=fmt.emax - 2) for _ in range(33)],
    ]


def check_scaled(ck, fmt, rng, trials):
    """The three scaled products against the model, over both the
    adversarial pools and random vectors, at every length that changes
    the tree's shape.

    Failures are counted by the Checker (ck.failed), which main() adds
    in, so there is nothing to return - unlike check_partition, which
    does its own comparing."""
    lengths = [0, 1, 2, 3, 5, 7, 8, 9, 15, 16, 17, 31, 32, 33, 63, 64, 65]
    for pool in scaled_pools(fmt, rng):
        for kind in SCALED_KINDS:
            for rnd in list(RND_NAMES):
                n = min(len(pool), rng.choice(lengths))
                xs = pool[:n]
                ys = [rand_operand(fmt, rng) for _ in range(n)]
                ck.scaled(kind, fmt, rnd, xs, ys)
    for _ in range(trials):
        n = rng.choice(lengths + [128, 129])
        rnd = rng.choice(list(RND_NAMES))
        xs = [rand_operand(fmt, rng) for _ in range(n)]
        ys = [rand_operand(fmt, rng) for _ in range(n)]
        ck.scaled(rng.choice(SCALED_KINDS), fmt, rnd, xs, ys)


def check_refusals(lib, dev, fmt):
    """The calling-convention boundary, both ways round."""
    esz = fmt.width // 8
    a = ctypes.create_string_buffer(esz * 4)
    d = ctypes.create_string_buffer(esz * 4)
    bad = 0

    st = lib.cft_run(dev, OP_SUM, PREC_CODE[fmt.name], 0,
                     ctypes.cast(a, ctypes.c_void_p), None,
                     ctypes.cast(a, ctypes.c_void_p),
                     ctypes.cast(d, ctypes.c_void_p), 4, None, None)
    if st != CFT_ERR_INVALID_ARGUMENT:
        print(f"FAIL cft_run(sum) returned {st}, want INVALID_ARGUMENT")
        bad += 1

    st = lib.cft_reduce(dev, OP_FMA, PREC_CODE[fmt.name], 0,
                        ctypes.cast(a, ctypes.c_void_p), None,
                        ctypes.cast(d, ctypes.c_void_p), 4, None, None)
    if st != CFT_ERR_INVALID_ARGUMENT:
        print(f"FAIL cft_reduce(fma) returned {st}, want INVALID_ARGUMENT")
        bad += 1

    for op, want in ((OP_SUM, b"sum"), (OP_DOT, b"dot"),
                     (OP_SUMSQ, b"sumsq"), (OP_SUMABS, b"sumabs")):
        if lib.cft_op_name(op) != want:
            print(f"FAIL cft_op_name({op}) is not {want!r}")
            bad += 1
        if not lib.cft_supports(dev, op, PREC_CODE[fmt.name]):
            print(f"FAIL software backend reports {want!r} unsupported")
            bad += 1
        # every one of them must be refused through cft_run
        st = lib.cft_run(dev, op, PREC_CODE[fmt.name], 0,
                         ctypes.cast(a, ctypes.c_void_p), None,
                         ctypes.cast(a, ctypes.c_void_p),
                         ctypes.cast(d, ctypes.c_void_p), 4, None, None)
        if st != CFT_ERR_INVALID_ARGUMENT:
            print(f"FAIL cft_run({want!r}) returned {st}, want "
                  "INVALID_ARGUMENT")
            bad += 1

    # 30 is the first unassigned opcode now that 28 and 29 are taken
    if lib.cft_op_name(30) != b"reserved":
        print("FAIL opcode 30 should still be unassigned")
        bad += 1
    if lib.cft_supports(dev, 30, PREC_CODE[fmt.name]):
        print("FAIL cft_supports says an unassigned opcode is supported")
        bad += 1
    return bad


def check_c_partitioner():
    """The C partitioner against the model, range for range.

    check_partition below uses the MODEL's canonical_ranges, so it
    proves the tree property and says nothing about the C code that
    actually runs on a multi-tile device. cft_sf_canonical_ranges is
    internal and not exported from the shared library, so it cannot be
    reached through ctypes - hence `reduce-parts --dump`, which prints
    what the C code produces for a fixed sweep.

    What is checked is the PROPERTY, not equality, and the difference
    matters. The C version stops splitting when another pass would
    exceed its output cap, and a pass does not split single-element
    ranges - so at n=280, parts=64 it returns 32 eight-wide nodes
    followed by 24 singletons, a mixed depth that is not equal to
    canonical_ranges(280, p) for ANY p. It is still a perfectly valid
    partition, and demanding equality would fail 57 cases that are all
    correct.

    The contract the fold actually needs is three things, so those are
    what get asserted: the ranges tile [0, n) in order with no gap or
    overlap, every range is a NODE of the tree over [0, n) - which is
    what makes combining the partials reproduce T(0, n) - and the count
    fits the cap. Exact agreement with the model is reported as a
    number rather than required.
    """
    exe = None
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in ("reduce-parts", "reduce-parts.exe"):
        p = os.path.join(here, os.pardir, cand)
        if os.path.exists(p):
            exe = p
            break
    if exe is None:
        print("SKIP C partitioner cross-check: reduce-parts not built "
              "(make -C host reduce-parts)")
        return 0

    def nodes(n):
        """Every (lo, hi) the model's tree over [0, n) contains."""
        seen, stack = set(), [(0, n)]
        while stack:
            lo, hi = stack.pop()
            seen.add((lo, hi))
            if hi - lo >= 2:
                mid = split(lo, hi)
                stack.append((lo, mid))
                stack.append((mid, hi))
        return seen

    out = subprocess.run([exe, "--dump"], capture_output=True, text=True,
                         check=True).stdout
    bad = same = differ = 0
    node_cache = {}
    for line in out.splitlines():
        f = line.split()
        n, parts = int(f[0]), int(f[1])
        got = [tuple(int(v) for v in tok.split(":")) for tok in f[2:]]

        if n == 0:
            if got:
                print(f"FAIL C partitioner n=0 parts={parts}: {got}")
                bad += 1
            continue

        if n not in node_cache:
            node_cache[n] = nodes(n)
        tree = node_cache[n]

        why = None
        if len(got) > 64:
            why = f"{len(got)} ranges exceeds the cap of 64"
        elif not got or got[0][0] != 0 or got[-1][1] != n:
            why = f"does not span [0, {n})"
        elif any(got[i][0] != got[i - 1][1] for i in range(1, len(got))):
            why = "gap or overlap between consecutive ranges"
        else:
            outside = [r for r in got if r not in tree]
            if outside:
                why = f"not tree nodes: {outside[:4]}"

        if why:
            print(f"FAIL C partitioner n={n} parts={parts}: {why}")
            bad += 1
        elif got == [tuple(r) for r in canonical_ranges(n, parts)]:
            same += 1
        else:
            differ += 1

    print(f"  C partitioner: {same + differ} partitions, all canonical "
          f"({same} identical to the model, {differ} a different valid "
          f"cut), {bad} bad")
    return bad


def check_partition(lib, dev, fmt, rng, trials):
    """A reduction split across tiles must equal the whole.

    Done here rather than only in the model because this is the property
    a multi-tile host will depend on, and it depends on libcft's tree
    agreeing with the model's at EVERY node, not just at the root.
    """
    bad = 0
    ck = Checker(lib, dev)
    for _ in range(trials):
        n = rng.choice([1, 2, 3, 5, 7, 9, 13, 16, 17, 31, 33, 64, 65])
        xs = [rand_finite(fmt, rng) for _ in range(n)]
        rnd = rng.choice(list(RND_NAMES))
        st, whole, wflags = ck.call(OP_SUM, fmt, rnd, xs)
        if st != CFT_OK:
            print(f"FAIL partition base call status {st}")
            bad += 1
            continue
        for parts in (2, 4, 8, 16, 32, 64):
            partials, flags = [], 0
            for lo, hi in canonical_ranges(n, parts):
                p, f = reduce_bits(fmt, xs, rnd, lo, hi)
                partials.append(p)
                flags |= f
            got, cf = combine(fmt, partials, rnd)
            if got != whole or (flags | cf) != wflags:
                print(f"FAIL partition n={n} parts={parts} {fmt.name} "
                      f"{RND_NAMES[rnd]}: 0x{got:x} vs 0x{whole:x}")
                bad += 1
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=1500)
    ap.add_argument("--formats", nargs="+", default=list(FORMATS))
    ap.add_argument("--rounding", nargs="+", default=list(RND_BY_NAME))
    ap.add_argument("--seed", type=int, default=20260830)
    args = ap.parse_args()

    lib = load_library()
    bind(lib)
    dev = ctypes.c_void_p()
    st = lib.cft_open(None, 0, ctypes.byref(dev))
    if st != CFT_OK:
        raise SystemExit(f"cft_open failed: {st}")

    rng = random.Random(args.seed)
    ck = Checker(lib, dev)
    bad = 0

    for fname in args.formats:
        fmt = FORMATS[fname]
        rounds = [RND_BY_NAME[r] for r in args.rounding]

        # Every small n, exhaustively. This is where a shape bug lives:
        # an implementation that agrees on 2, 4, 8 and 16 can still
        # disagree on 5, and only trying round numbers would miss it.
        for n in range(0, 41):
            for rnd in rounds:
                xs = [rand_operand(fmt, rng) for _ in range(n)]
                ys = [rand_operand(fmt, rng) for _ in range(n)]
                for op in (OP_SUM, OP_DOT, OP_SUMSQ, OP_SUMABS):
                    ck.one(op, fmt, rnd, xs, ys)

        for _ in range(args.trials):
            n = rng.randint(41, 400)
            rnd = rng.choice(rounds)
            xs = [rand_operand(fmt, rng) for _ in range(n)]
            ys = [rand_operand(fmt, rng) for _ in range(n)]
            ck.one(rng.choice((OP_SUM, OP_DOT, OP_SUMSQ, OP_SUMABS)),
                   fmt, rnd, xs, ys)

        bad += check_refusals(lib, dev, fmt)
        bad += check_partition(lib, dev, fmt, rng, 60)
        bad += check_identities(ck, fmt, rng, max(120, args.trials // 8))
        check_scaled(ck, fmt, rng, max(200, args.trials // 4))
    bad += check_c_partitioner()

    lib.cft_close(dev)

    total = ck.checked
    bad += ck.failed
    print(f"{total} reductions checked across "
          f"{len(args.formats)} formats, all seven of clause 9.4, "
          f"{bad} failures")
    if total < 1000:
        raise SystemExit("suspiciously few checks ran - the sweep did not "
                         "cover what it claims to")
    if bad:
        raise SystemExit(1)
    print("libcft and the golden model agree on the tree, the scaling, "
          "the bits and the flags")


if __name__ == "__main__":
    main()
