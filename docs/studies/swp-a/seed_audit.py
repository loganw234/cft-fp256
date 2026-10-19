# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""seed_audit.py - the soak tools' random operand streams, and what the stress driver's
seed schedule does with them.

1. A PORT of the generator both tools use (host/tools/divsqrt_soak.c and clause5_soak.c):
   rng_state = seed | 1; xorshift64 with shifts 13, 7, 17; banded32() and banded64().
   The port is held to the REAL tools: tool_probe.out holds the first 16 lanes (a, b) the
   tools printed under their sabotage control for three operations and several seeds, and
   the port must reproduce every one of them.

   One thing the port must settle: banded32() and banded64() contain
       e = bands[rng() % 7] + (rng() % 3);
   two calls of rng() in ONE C expression, whose order C leaves unspecified. The port
   tries both orders against the real tool's output and reports which the compiled tool
   used (gcc 11.4 in the capture). A stream that depends on that is not a replay across
   compilers; the fix is two statements.

2. The SCHEDULE: hw/card_stress_lib.py gives the n-th slice of a random item the seed
   base_seed + 7919 n; the tools then set the state to seed | 1. This script counts, for
   the 54 random items and n = 0 .. N-1, how many (item, n) pairs start from the SAME
   state, for the schedule as it is and for two candidate schedules:
     A  state = (item index << 40) | (n << 1) | 1        distinct by construction
     B  state = mix64(key xor ((item index << 32) | n)) | 1   a keyed bijection of the pair
   and checks the stream of two colliding states is identical lane for lane.

3. CONTROLS: the port with a changed shift must stop matching the tools; the port without
   `| 1` must stop reproducing the tools' seeds 2k and 2k+1 collision; the audit of a
   schedule without `| 1` must find no collisions - so the checks can fail.

usage: python seed_audit.py        (reads tool_probe.out beside it; imports hw/card_stress_lib.py)
"""
import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
MASK = (1 << 64) - 1

fails = 0


def check(label, ok, detail=""):
    global fails
    print("CHECK %-86s %s %s" % (label, "ok" if ok else "FAILED", detail))
    if not ok:
        fails += 1


# --------------------------------------------------------------------------
# the port
# --------------------------------------------------------------------------
class Rng:
    def __init__(self, seed, force_odd=True, shifts=(13, 7, 17)):
        self.s = (seed | 1) & MASK if force_odd else seed & MASK
        self.a, self.b, self.c = shifts

    def next(self):
        x = self.s
        x ^= (x << self.a) & MASK
        x ^= x >> self.b
        x ^= (x << self.c) & MASK
        self.s = x
        return x


def banded32(r, band_first=True):
    x = r.next() & 0xFFFFFFFF
    if (r.next() & 3) == 0:
        bands = (0, 1, 2, 127, 252, 253, 254)
        if band_first:                       # bands[rng() % 7] evaluated first
            i = r.next() % 7
            j = r.next() % 3
        else:                                # (rng() % 3) evaluated first
            j = r.next() % 3
            i = r.next() % 7
        e = bands[i] + j
        if e > 255:
            e = 255
        x = (x & 0x807FFFFF) | (e << 23)
    return x


def banded64(r, band_first=True):
    x = r.next()
    if (r.next() & 3) == 0:
        bands = (0, 1, 2, 1023, 2044, 2045, 2046)
        if band_first:
            i = r.next() % 7
            j = r.next() % 3
        else:
            j = r.next() % 3
            i = r.next() % 7
        e = bands[i] + j
        if e > 2047:
            e = 2047
        x = (x & 0x800FFFFFFFFFFFFF) | (e << 52)
    return x


def _nan(x, ew, mw):
    return ((x >> mw) & ((1 << ew) - 1)) == (1 << ew) - 1 and (x & ((1 << mw) - 1)) != 0


def _inf(x, ew, mw):
    return (x & ~(1 << (ew + mw))) == (((1 << ew) - 1) << mw)


def _zero(x, ew, mw):
    return (x & ~(1 << (ew + mw))) == 0


def result_is_nan(op, a, b):
    """Whether division or square root gives a NaN. The sabotage control flips the low bit of
    the library's result, and a NaN with a flipped bit still AGREES with the CPU's NaN (the tools
    compare NaNs as a class), so a lane with a NaN result prints nothing: the probe's list is the
    first lanes with a NON-NaN result, and its 'lane' numbers are ordinals, not lane indices."""
    ew, mw = (8, 23) if op == "div32" else (11, 52)
    if op == "sqrt64":
        return _nan(a, ew, mw) or ((a >> (ew + mw)) & 1 and not _zero(a, ew, mw))
    if _nan(a, ew, mw) or _nan(b, ew, mw):
        return True
    return (_zero(a, ew, mw) and _zero(b, ew, mw)) or (_inf(a, ew, mw) and _inf(b, ew, mw))


def lanes(op, seed, n, band_first=True, force_odd=True, shifts=(13, 7, 17), skip_nan=True):
    """The first n lanes' operands for divsqrt-soak's div32 / div64 / sqrt64 whose result is not a
    NaN (skip_nan, as the probe sees them), or the first n lanes (skip_nan False). For the divides
    (a, b) with a then b drawn for each lane; for sqrt64 (a,)."""
    r = Rng(seed, force_odd, shifts)
    out = []
    while len(out) < n:
        if op == "div32":
            a = banded32(r, band_first)
            b = banded32(r, band_first)
            fields = ("a=0x%08x" % a, "b=0x%08x" % b)
        elif op == "div64":
            a = banded64(r, band_first)
            b = banded64(r, band_first)
            fields = ("a=0x%016x" % a, "b=0x%016x" % b)
        else:
            a = banded64(r, band_first)
            b = 0
            fields = ("a=0x%016x" % a,)
        if skip_nan and result_is_nan(op, a, b):
            continue
        out.append(fields)
    return out


def read_probe(path):
    """OPERANDS <op> <seed> <mode> <lane> <fields> lines -> {(op, seed_int, mode): [fields per lane]}"""
    out = {}
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            m = re.match(r"^OPERANDS (\S+) (\S+) (\S+) (\d+) (.*)$", ln.rstrip("\n"))
            if m:
                out.setdefault((m.group(1), int(m.group(2), 0), m.group(3)), []).append(tuple(m.group(5).split()))
    return out


def read_builds(path):
    """eval_order.out: OPERANDS [build] op seed rne ordinal fields -> {build: {(op, seed): [fields]}}"""
    out = {}
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            m = re.match(r"^OPERANDS \[(\S+)\] (\S+) (\S+) rne (\d+) (.*)$", ln.rstrip("\n"))
            if m:
                out.setdefault(m.group(1), {}).setdefault((m.group(2), int(m.group(3), 0)), []).append(tuple(m.group(5).split()))
    return out


def classify(streams):
    """(streams matching bands-first, matching (rng()%3)-first, matching neither, total)"""
    a = b = neither = 0
    for (op, seed), got in streams.items():
        g = [tuple(x) for x in got]
        ma = [tuple(x) for x in lanes(op, seed, len(got), True)] == g
        mb = [tuple(x) for x in lanes(op, seed, len(got), False)] == g
        a += ma and not mb
        b += mb and not ma
        neither += (not ma) and (not mb)
    return a, b, neither, len(streams)


def matches(probe, band_first=True, force_odd=True, shifts=(13, 7, 17)):
    """(streams compared, streams that match the tool lane for lane, lanes compared)."""
    n_ok = n_all = n_lanes = 0
    for (op, seed, mode), got in probe.items():
        want = lanes(op, seed, len(got), band_first, force_odd, shifts)
        n_all += 1
        n_lanes += len(got)
        if [tuple(w) for w in want] == [tuple(g) for g in got]:
            n_ok += 1
    return n_ok, n_all, n_lanes


# --------------------------------------------------------------------------
# the schedule
# --------------------------------------------------------------------------
def load_lib():
    path = os.path.join(ROOT, "hw", "card_stress_lib.py")
    spec = importlib.util.spec_from_file_location("card_stress_lib", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["card_stress_lib"] = mod
    spec.loader.exec_module(mod)
    return mod


def mix64(x):
    """The 64-bit finalizer of splitmix64 (a bijection: xorshift and odd multiplies)."""
    x = (x ^ (x >> 30)) * 0xBF58476D1CE4E5B9 & MASK
    x = (x ^ (x >> 27)) * 0x94D049BB133111EB & MASK
    return x ^ (x >> 31)


def collisions(states_by_item_n):
    """states: {(item, n): state}. Returns (distinct states, colliding (item, n) pairs,
    states shared by two or more items)."""
    seen = {}
    for key, st in states_by_item_n.items():
        seen.setdefault(st, []).append(key)
    shared = {st: ks for st, ks in seen.items() if len(ks) > 1}
    return len(seen), sum(len(ks) for ks in shared.values()), len(shared)


def schedule(items, N, kind, force_odd=True):
    out = {}
    key = 0x5EED5EED5EED5EED
    for idx, it in enumerate(items):
        for n in range(N):
            if kind == "now":
                seed = it.seed_for(n)
                st = (seed | 1) if force_odd else seed
            elif kind == "A":
                st = (idx << 40) | (n << 1) | 1
            else:
                st = mix64(key ^ ((idx << 32) | n)) | 1
            out[(it.name, n)] = st & MASK
    return out


def main():
    try:
        sys.stdout.reconfigure(newline="\n")
    except (AttributeError, ValueError):
        pass
    probe = read_probe(os.path.join(HERE, "tool_probe.out"))
    print("seed_audit.py: the soak tools' operand streams and the stress driver's seed schedule")
    print()
    print("== 1. THE PORT, held to the real tools' operands (tool_probe.out)")
    check("tool_probe.out holds the tools' operands: 3 operations x (3 seeds in B + 3 in C) streams",
          len(probe) >= 12, "(%d streams)" % len(probe))
    lanes_total = sum(len(v) for v in probe.values())
    ok1, all1, nl = matches(probe, band_first=True)
    ok2, all2, _ = matches(probe, band_first=False)
    print("   evaluation order bands[rng() %% 7] first : %d of %d streams match the tool (%d lanes)" % (ok1, all1, nl))
    print("   evaluation order (rng() %% 3) first      : %d of %d streams match the tool (%d lanes)" % (ok2, all2, nl))
    check("one evaluation order reproduces every stream the tool printed, lane for lane", max(ok1, ok2) == all1 and all1 >= 12,
          "(%d of %d, %d lanes)" % (max(ok1, ok2), all1, lanes_total))
    band_first = ok1 >= ok2
    print("   the compiled tool (gcc 11.4, this tree's host/Makefile flags) drew %s first" %
          ("bands[rng() % 7]" if band_first else "(rng() % 3)"))
    # the order matters: the other order must NOT also match (else the probe cannot tell them apart)
    check("the other evaluation order does NOT match (the probe distinguishes the two orders)",
          min(ok1, ok2) < all1, "(%d of %d)" % (min(ok1, ok2), all1))
    # controls
    okc, _, _ = matches(probe, band_first=band_first, shifts=(13, 7, 16))
    check("CONTROL: a port with the third shift 16 instead of 17 does not match the tool", okc < all1, "(%d of %d)" % (okc, all1))
    okc, _, _ = matches(probe, band_first=band_first, force_odd=False)
    check("CONTROL: a port without `| 1` does not match every stream the tool printed", okc < all1, "(%d of %d)" % (okc, all1))
    # seeds 2k and 2k+1: one stream in the tool (probe section C) and in the port
    s2 = lanes("div32", 0x50AC0002, 16, band_first)
    s3 = lanes("div32", 0x50AC0003, 16, band_first)
    s4 = lanes("div32", 0x50AC0004, 16, band_first)
    check("the port gives seeds 0x50AC0002 and 0x50AC0003 one stream, and 0x50AC0003 and 0x50AC0004 two", s2 == s3 and s3 != s4)
    s2 = lanes("div32", 0x50AC0002, 16, band_first, force_odd=False)
    s3 = lanes("div32", 0x50AC0003, 16, band_first, force_odd=False)
    check("CONTROL: without `| 1` the port gives those two seeds two streams", s2 != s3)
    # a shared state is a shared stream for as long as either runs: the shorter slice is a prefix
    a = lanes("div64", 0x50AC0006, 5000, band_first)
    b = lanes("div64", 0x50AC0007, 8000, band_first)
    check("two slices that share a state (counts 5,000 and 8,000): the shorter is the longer's prefix", a == b[:5000])
    print()

    print("== 1b. DOES THE STREAM DEPEND ON THE COMPILER? (eval_order.out: the same source, built several ways)")
    eo = os.path.join(HERE, "eval_order.out")
    if not os.path.exists(eo):
        check("eval_order.out exists", False)
    else:
        builds = read_builds(eo)
        check("eval_order.out holds seven builds of 9 streams each", len(builds) == 7 and all(len(s) == 9 for s in builds.values()),
              "(%d builds)" % len(builds))
        print("   %-10s %14s %14s %9s" % ("build", "bands-first", "(rng()%3)-first", "neither"))
        orders = {}
        for name in sorted(builds):
            a, b, neither, tot = classify(builds[name])
            orders[name] = (a, b, neither, tot)
            print("   %-10s %9d of %d %9d of %d %9d" % (name, a, tot, b, tot, neither))
        check("every build's streams are reproduced by the port in ONE of the two orders (none unexplained)",
              all(v[2] == 0 for v in orders.values()))
        used = {("bands" if v[0] > v[1] else "mod3") for v in orders.values()}
        print("   orders seen across the %d builds: %s" % (len(orders), ", ".join(sorted(used))))
        if len(used) > 1:
            print("   -> the SAME seed gives different operands under different builds of the SAME source: not a replay across compilers")
        else:
            print("   -> every build here drew the same order; C still leaves it unspecified, so a build elsewhere may differ")
    print()

    print("== 2. THE SCHEDULE: how many (item, n) slices start from a state another slice started from")
    lib = load_lib()
    items = [it for it in lib.sweep_items() if it.kind == "random"]
    check("the driver's catalog has 54 random items", len(items) == 54, "(%d)" % len(items))
    N = 57
    print("   54 random items x n = 0 .. %d: the whole GRID of (item, n), n = 0 .. 56 for every item. It is not the run: the run's own 3,038" % (N - 1))
    print("   slices (56 or 57 an item) are counted from its record in stress_records.out: 2,922 of them share a state.")
    print("   %-52s %8s %8s %12s %14s" % ("schedule", "slices", "distinct", "shared states", "slices sharing"))
    results = {}
    for label, kind, odd in (("the driver's formula: seed = base + 7919 n, then | 1", "now", True),
                             ("the same without the | 1 the tools apply", "now", False),
                             ("A: (item << 40) | (n << 1) | 1", "A", True),
                             ("B: mix64(key ^ (item << 32 | n)) | 1", "B", True)):
        st = schedule(items, N, kind, odd)
        d, sl, sh = collisions(st)
        results[kind + str(odd)] = (d, sl, sh)
        print("   %-52s %8d %8d %12d %14d" % (label, len(st), d, sh, sl))
    d, sl, sh = results["nowTrue"]
    check("by the driver's formula, 96% or more of the grid's slices share a state with another item's slice", sl >= 0.96 * 54 * N, "(%d of %d)" % (sl, 54 * N))
    d, sl, sh = results["nowFalse"]
    check("without the `| 1` the same seeds never collide (the collisions ARE the `| 1`)", sl == 0 and sh == 0)
    d, sl, sh = results["AT" + "rue"]
    check("schedule A has no shared state", sl == 0 and sh == 0)
    d, sl, sh = results["BTrue"]
    check("schedule B has no shared state", sl == 0 and sh == 0)
    print()
    # the birthday bound on streams that overlap although their starting states differ: k streams of L draws on a cycle of 2^64 - 1
    k = 3038
    print("   the birthday bound k^2 L / 2^64 on two of the run's k = %d slices overlapping although their starting states differ:" % k)
    for L, what in ((7e8, "L = 7 x 10^8 draws, a 2^28-count slice of a one-operand operation (2.5 draws an operand: the value, the band test, and two more in a quarter)"),
                 (1.3e9, "L = 1.3 x 10^9 draws, a 2^28-count slice of a two-operand operation (5 draws a count)")):
        print("     %s: %.1e" % (what, k * k * L / 2.0 ** 64))
    check("the birthday bound for the run's 3,038 slices is under 10^-3 for either slice length (small, not zero; an enumeration makes it zero)",
          k * k * 1.3e9 / 2.0 ** 64 < 1e-3, "(%.1e)" % (k * k * 1.3e9 / 2.0 ** 64))
    check("CONTROL: ten times the slices (30,380, a run ten times as long) would NOT satisfy it, so the check can fail",
          not (10 * k) ** 2 * 1.3e9 / 2.0 ** 64 < 1e-3, "(%.1e)" % ((10 * k) ** 2 * 1.3e9 / 2.0 ** 64))
    print()
    print("seed_audit: %s" % ("every CHECK held" if fails == 0 else "%d CHECK(s) FAILED" % fails))
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
