# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The gravity accumulate, as one program run through an index table.

    python host/tools/gathertime.py [--bodies 64] [--format fp64]
                                    [--reps 5] [--artifact IMAGE]

This is the measurement ABI 0.14's R16 was built for, written to be run
ON THE CARD and runnable today against the software backend, which is
where its correctness half is scored. It is the seq6 day's `segtime.py`
for the gather: same shape, same question - how many round trips does
one entry point replace, and what does the one cost.

THE SHAPE, from cft-rebound's `src/ias15_cft.c` (`build_scatter` at line
665 and `gravity_body` at 762). Every particle receives a ROW of pair
contributions in REBOUND's partner order, and the accumulate is a LEFT
FOLD over that row in that order:

    a = 0
    for t in 0 .. scat_max - 1:
        addend[3p + c] = contribution[side][c][l]   # a host gather
        a = a + addend                              # one vector add

For N bodies that is P = N(N-1)/2 pairs, six contribution vectors of P
elements each (what i receives and what j receives, in x, y and z),
3N lanes, and rows of at most N-1 entries - so `scat_max` vector adds
and `scat_max` host gathers per force evaluation, every one of them a
round trip.

Through R16 it is ONE run: the 3N lanes' scratch block is filled
THROUGH a table of 3N * scat_max entries into the 6P-element pool, and
the program folds the slots:

    LDL r4, s ; ADD r3, r3, r4      for s in 0 .. scat_max - 1
    DEPOSIT r3 ; HALT

r3 and not r0, which is what the round's plan sketched: r0, r1 and r2
are the three INPUT STREAMS and a lane's r0 is a[i], not +0. r3..r31
are the registers that start at +0 (docs/SEQUENCER.md R9), so the fold's
accumulator is one of those - and using it also means the program names
no stream at all, so R10 loads none of the three.

A particle whose row has run out contributes +0, which is
`CFT_IDX_NONE` and costs no read; the requester's own argument for why
that is exact stands unchanged (the running sum starts at +0 and cannot
become -0, so x + (+0) is x).

WHAT IS PRINTED: the wall time of the one run, the wall time of the
`scat_max` dense calls it replaces (with the host gather that goes with
them, which is half of what the ask is about), time per gathered
element, and the call count. Every result is checked against a host
fold of the same values first, so a fast wrong answer is reported as a
failure and not as a time.

On the software backend the time is the C executor's and says nothing
about the tile; what it says today is that the answers agree and the
script runs. Point it at an xclbin on the box to get the number.
"""

import argparse
import ctypes
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from cft_golden import FORMATS  # noqa: E402
from cft_golden import seq  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

CFT_OK = 0
CFT_ADD = 1
FMT_CODE = {"fp32": 0, "fp64": 1, "fp128": 2, "fp256": 3}


class RunArgs(ctypes.Structure):
    """cft_run_args, field for field (host/include/cft.h, ABI 0.14)."""
    _fields_ = [("struct_size", ctypes.c_size_t),
                ("a", ctypes.c_void_p), ("b", ctypes.c_void_p),
                ("c", ctypes.c_void_p),
                ("n", ctypes.c_size_t),
                ("bank", ctypes.c_void_p), ("bank_bytes", ctypes.c_size_t),
                ("scratch_in", ctypes.c_void_p),
                ("scratch_in_bytes", ctypes.c_size_t),
                ("scratch_out", ctypes.c_void_p),
                ("scratch_out_bytes", ctypes.c_size_t),
                ("deposits", ctypes.c_void_p),
                ("counts", ctypes.POINTER(ctypes.c_uint32)),
                ("flags_out", ctypes.POINTER(ctypes.c_uint32)),
                ("bus_out", ctypes.POINTER(ctypes.c_uint32)),
                ("idx_a", ctypes.c_void_p),
                ("idx_b", ctypes.c_void_p),
                ("idx_c", ctypes.c_void_p),
                ("idx_a_src", ctypes.c_size_t),
                ("idx_b_src", ctypes.c_size_t),
                ("idx_c_src", ctypes.c_size_t),
                ("idx_scratch_in", ctypes.c_void_p),
                ("idx_scratch_src", ctypes.c_size_t),
                ("lane_mask", ctypes.c_void_p),
                ("lane_mask_bytes", ctypes.c_size_t)]


def load_library():
    override = os.environ.get("CFT_LIB")
    if override:
        path = Path(override)
    else:
        name = {"win32": "cft.dll", "cygwin": "cft.dll",
                "darwin": "libcft.dylib"}.get(sys.platform, "libcft.so")
        path = ROOT / "host" / name
    if not path.exists():
        raise SystemExit(f"{path} not found - run `make -C host` first "
                         f"(and XRT=1 for a card)")
    lib = ctypes.CDLL(str(path))
    u32p = ctypes.POINTER(ctypes.c_uint32)
    lib.cft_open.argtypes = [ctypes.c_char_p, ctypes.c_int,
                             ctypes.POINTER(ctypes.c_void_p)]
    lib.cft_open.restype = ctypes.c_int
    lib.cft_close.argtypes = [ctypes.c_void_p]
    lib.cft_program_load.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                     ctypes.c_size_t,
                                     ctypes.POINTER(ctypes.c_void_p)]
    lib.cft_program_load.restype = ctypes.c_int
    lib.cft_program_free.argtypes = [ctypes.c_void_p]
    lib.cft_program_run_ex.argtypes = [ctypes.c_void_p,
                                       ctypes.POINTER(RunArgs)]
    lib.cft_program_run_ex.restype = ctypes.c_int
    lib.cft_run.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                            ctypes.c_void_p, ctypes.c_void_p,
                            ctypes.c_size_t, u32p, u32p]
    lib.cft_run.restype = ctypes.c_int
    lib.cft_strerror.argtypes = [ctypes.c_int]
    lib.cft_strerror.restype = ctypes.c_char_p
    lib.cft_last_error.restype = ctypes.c_char_p
    return lib


def build_scatter(nbody, nactive=None, tptype=0):
    """cft-rebound's `build_scatter`, for one system: particle p's row,
    in REBOUND's partner order, of `2 * l + side` encodings.

    Reproduced rather than imported - that file is another repository's
    and this script must not depend on it - and reproduced from its
    loops rather than from a description of them, so the ORDER is the
    order the fold is exact in.

    `nactive` below nbody is the TEST PARTICLE case, and it is the one
    that makes the rows ragged: a test particle receives from every
    active particle, and with `tptype` zero it gives back nothing, so
    the active particles' rows are shorter than the test particles'.
    Every row is folded to the longest, and the short ones contribute
    +0 for the rest of it - which is what CFT_IDX_NONE is."""
    na = nbody if nactive is None else min(nactive, nbody)
    rows = [[] for _ in range(nbody)]
    for i in range(1, na):
        for j in range(0, i):
            pair = i * (i - 1) // 2 + j
            rows[i].append(2 * pair)
            rows[j].append(2 * pair + 1)
    for i in range(max(na, 1), nbody):
        for j in range(0, na):
            pair = i * (i - 1) // 2 + j
            rows[i].append(2 * pair)
            if tptype:
                rows[j].append(2 * pair + 1)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bodies", type=int, default=64)
    ap.add_argument("--format", default="fp64", choices=list(FMT_CODE))
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--active", type=int, default=None,
                    help="N_active: particles at or above it are TEST "
                         "particles, which makes the rows ragged and so "
                         "exercises CFT_IDX_NONE (the default is every "
                         "particle active, where every row is full)")
    ap.add_argument("--artifact", default=None,
                    help="an xclbin, or cft://host:port; omitted is the "
                         "software backend")
    args = ap.parse_args()

    fmt = FORMATS[args.format]
    esz = fmt.width // 8
    nb = args.bodies
    npairs = nb * (nb - 1) // 2
    lanes = 3 * nb
    rows = build_scatter(nb, args.active)
    scat_max = max(len(r) for r in rows)
    pool_n = 6 * npairs

    lib = load_library()
    dev = ctypes.c_void_p()
    art = args.artifact.encode() if args.artifact else None
    st = lib.cft_open(art, 0, ctypes.byref(dev))
    if st != CFT_OK:
        raise SystemExit(f"cft_open: {lib.cft_strerror(st).decode()}: "
                         f"{lib.cft_last_error().decode()}")

    # The contributions: six vectors of P, in the pool the table indexes.
    # Values a fold can be checked on exactly - small integers, so the
    # sum is exact at every format and a wrong element is a wrong
    # number rather than a rounding difference.
    pool = [sf.from_int(fmt, (k % 97) + 1)[0] for k in range(pool_n)]

    # The table, lane-major: lane 3p + c, slot s. `enc >> 1` is the pair
    # and `enc & 1` says which side of it this particle is, so the
    # contribution's index in the pool is ((side * 3) + c) * P + pair -
    # the same arithmetic gravity_body does with three memcpys.
    NONE = seq.IDX_NONE
    table = []
    for p in range(nb):
        row = rows[p]
        for c in range(3):
            for s in range(scat_max):
                if s >= len(row):
                    table.append(NONE)
                    continue
                enc = row[s]
                table.append((((enc & 1) * 3) + c) * npairs + (enc >> 1))
    assert len(table) == lanes * scat_max

    # The fold, as a program. LDL into r4 and ADD into r3, which starts
    # at +0 because r3..r31 do; the three input streams are never named,
    # so R10 loads none of them.
    insns = []
    for s in range(scat_max):
        insns.append(seq.ldl(4, s))
        insns.append(seq.alu(sf.OP_ADD, rd=3, ra=3, rc=4))
    insns += [seq.deposit(3), seq.halt()]
    prog = seq.Program(fmt, insns, [], max_deposits=1,
                       flags=seq.FLAG_SCRATCH_IO,
                       n_scratch_in=scat_max, n_scratch_out=0)
    image = prog.to_bytes()

    # What the answer must be: the same left fold, on the host, in the
    # same order - which is the definition the requester's exactness
    # argument is about.
    zero = sf.zero_bits(fmt, 0)
    want = []
    for lane in range(lanes):
        acc = zero
        for s in range(scat_max):
            t = table[lane * scat_max + s]
            v = zero if t == NONE else pool[t]
            acc, _fl = sf.compute(fmt, sf.OP_ADD, acc, 0, v)
        want.append(acc)

    handle = ctypes.c_void_p()
    st = lib.cft_program_load(dev, image, len(image), ctypes.byref(handle))
    if st != CFT_OK:
        raise SystemExit(f"cft_program_load: "
                         f"{lib.cft_strerror(st).decode()}: "
                         f"{lib.cft_last_error().decode()}")

    buf_pool = ctypes.create_string_buffer(
        b"".join(v.to_bytes(esz, "little") for v in pool), pool_n * esz)
    buf_tab = ctypes.create_string_buffer(
        b"".join(int(t).to_bytes(4, "little") for t in table),
        len(table) * 4)
    buf_dep = ctypes.create_string_buffer(lanes * esz)
    buf_zero = ctypes.create_string_buffer(lanes * esz)
    counts = (ctypes.c_uint32 * lanes)()
    flags = ctypes.c_uint32(0)
    bus = ctypes.c_uint32(0)

    A = RunArgs()
    A.struct_size = ctypes.sizeof(RunArgs)
    A.a = ctypes.cast(buf_zero, ctypes.c_void_p)
    A.b = ctypes.cast(buf_zero, ctypes.c_void_p)
    A.c = ctypes.cast(buf_zero, ctypes.c_void_p)
    A.n = lanes
    A.scratch_in = ctypes.cast(buf_pool, ctypes.c_void_p)
    A.scratch_in_bytes = pool_n * esz
    A.idx_scratch_in = ctypes.cast(buf_tab, ctypes.c_void_p)
    A.idx_scratch_src = pool_n
    A.deposits = ctypes.cast(buf_dep, ctypes.c_void_p)
    A.counts = counts
    A.flags_out = ctypes.pointer(flags)
    A.bus_out = ctypes.pointer(bus)

    times = []
    for _ in range(max(1, args.reps)):
        t0 = time.perf_counter()
        st = lib.cft_program_run_ex(handle, ctypes.byref(A))
        times.append(time.perf_counter() - t0)
        if st != CFT_OK:
            raise SystemExit(f"cft_program_run_ex: "
                             f"{lib.cft_strerror(st).decode()}: "
                             f"{lib.cft_last_error().decode()}")
    got = [int.from_bytes(buf_dep.raw[i * esz:(i + 1) * esz], "little")
           for i in range(lanes)]
    bad = [i for i in range(lanes) if got[i] != want[i]]
    one = sorted(times)[len(times) // 2]

    # ...and the calls it replaces: scat_max host gathers, each feeding
    # one dense vector add over the same 3N lanes. Timed the same way,
    # against the same device, so the two numbers are comparable.
    acc = ctypes.create_string_buffer(lanes * esz)
    addend = ctypes.create_string_buffer(lanes * esz)
    raw_pool = buf_pool.raw
    many_t, gath_t = [], []
    for _ in range(max(1, args.reps)):
        ctypes.memset(acc, 0, lanes * esz)
        gathered = 0.0
        t0 = time.perf_counter()
        for s in range(scat_max):
            # The host gather, timed SEPARATELY and subtracted below.
            # In the integrator it is three memcpys a lane in C; here it
            # is Python, and reporting a Python loop's cost as the
            # thing the tile beats would be a measurement of this
            # script. What the comparison is about is the CALLS.
            g0 = time.perf_counter()
            blob = bytearray(lanes * esz)
            for lane in range(lanes):
                t = table[lane * scat_max + s]
                if t == NONE:
                    continue
                blob[lane * esz:(lane + 1) * esz] = \
                    raw_pool[t * esz:(t + 1) * esz]
            ctypes.memmove(addend, bytes(blob), lanes * esz)
            gathered += time.perf_counter() - g0
            rc = lib.cft_run(dev, CFT_ADD, FMT_CODE[args.format], 0,
                             acc, None, addend, acc, lanes, None, None)
            if rc != CFT_OK:
                raise SystemExit(f"cft_run: "
                                 f"{lib.cft_strerror(rc).decode()}")
        many_t.append(time.perf_counter() - t0 - gathered)
        gath_t.append(gathered)
    many = sorted(many_t)[len(many_t) // 2]
    gath = sorted(gath_t)[len(gath_t) // 2]
    got2 = [int.from_bytes(acc.raw[i * esz:(i + 1) * esz], "little")
            for i in range(lanes)]

    elems = lanes * scat_max
    print(f"{args.format}, {nb} bodies: {npairs} pairs, {lanes} lanes, "
          f"rows of at most {scat_max}, a {pool_n}-element pool")
    print(f"  table {len(table)} entries, "
          f"{sum(1 for t in table if t == NONE)} of them CFT_IDX_NONE "
          f"(+0, and no read)")
    print(f"  ONE program run        {one * 1e3:9.3f} ms   "
          f"{one / elems * 1e9:8.1f} ns a gathered element")
    print(f"  the calls it replaces  {many * 1e3:9.3f} ms   "
          f"{scat_max} cft_run calls over {lanes} lanes "
          f"(+{gath * 1e3:.3f} ms of host gather, not counted: it is "
          f"this script's Python, and in the integrator it is C)")
    if one > 0:
        print(f"  one run against {scat_max} calls: x{many / one:.2f}"
              f"    {scat_max} host gathers removed as well")
    if not args.artifact:
        print("  (the software backend makes no round trip, so this "
              "ratio is not the ask's number - point --artifact at an "
              "xclbin on the box for that)")
    print(f"  deposits agree with the host fold: "
          f"{'YES' if not bad else f'NO - {len(bad)} lanes differ'}")
    print(f"  the replaced route agrees too:     "
          f"{'YES' if got2 == want else 'NO'}")
    print(f"  flags {flags.value:#07b}  status {bus.value:#07b}")

    lib.cft_program_free(handle)
    lib.cft_close(dev)
    return 1 if (bad or got2 != want) else 0


if __name__ == "__main__":
    sys.exit(main())
