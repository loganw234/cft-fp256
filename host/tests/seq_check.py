# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Drive libcft's sequencer and the golden model over the same programs.

    python3 host/tests/seq_check.py [--trials 400] [--formats fp32 fp64]

`diff_check.py` does this for arithmetic; this does it for programs.
The two implementations are independent ports of
`python/cft_golden/seq.py` - one in Python, one in C - and they have to
agree on deposits, on deposit counts, on the sticky exception flags and
on the status word, over programs neither was written with in mind.

Three things are compared, and the third is the one worth having:

1. **Results.** Random valid programs, random operands weighted toward
   the values where opcodes differ, whole output compared.
2. **Refusals.** A program the model rejects must be rejected by the C
   loader too. Two validators that disagree about what is legal are a
   device that executes something a host thought it had refused.
3. **Blocking is invisible.** The C side processes lanes in blocks of
   64 to bound its memory; the model runs the whole array at once. That
   they agree IS the P2/P3 argument, executed rather than asserted -
   and it is the same argument that lets the library split a run across
   four compute units.

Since 2026-09-07 every trial is drawn from one of TWO corpora, and the
run says how many came from each. The first is the generator as it
stood, unchanged down to the draw order so the programs this has always
compared are the programs it still compares. The second sets
`extended=True`, which adds `IMUL` to the opcode pool and `kx` -
indexed constants - to the instructions that name one, over a bank
deep enough that indices above fifteen are reached. Two corpora rather
than one widened corpus because a differential that quietly stopped
covering the old encoding while gaining the new one would be a
regression nobody could see in a passing run.

Since 2026-09-08 (evening) a THIRD corpus runs after the two, from
its own generator seed so the first two still draw what they always
drew: revision 3's programs - the four scratch codes `STL`/`LDL`/
`STX`/`LDX`, five-bit registers, `kx` indices past 255 through the
ninth bit, and the per-run scratch block declared in the header -
run through `cft_program_run_ex` on the C side and `run(...,
scratch_in=...)` on the model's, and compared on the scratch-out
block as well as on deposits, counts, flags and status. The scratch
is where a per-lane mistake hides (a store masked by the wrong
lane's active bit, an indexed slot from the wrong lane's `rb`, a
transposed preload), and the two executors were written by two
different hands from the same page, so this is the one comparison
neither half could run alone. The refusals revision 3 added - a
static slot past the depth, a field a scratch code does not read,
a ninth bit on an operand that names a register, `imm[31]`, the
header's `scratch_io` word without its flag or past the depth - are
corrupted in and must be refused by both.

Since 2026-09-15 a FOURTH corpus runs after the three, again from its
own generator seed so the first three still draw what they always drew:
revision 6's R16 - an input block fetched through an index table. Each
program's streams and scratch block are drawn as SOURCES of a length
unrelated to n, with a table per block that carries distinct values and
`CFT_IDX_NONE` in some fraction of its entries, and both executors are
asked for the same run. Three things this corpus reaches that no other
does: the gather itself, blocked in sixty-fours on the C side and whole
in the model (the third claim of this file applied to tables, which
must be sliced the same way); the bound, an index at or past the
declared source length, which both must refuse by name and by value;
and the identity table, which must give BIT-IDENTICAL output to the
dense run the same program makes over the same values - the control
that a table which was quietly ignored would also pass, and which the
permuted half beside it is there to fail.

Since 2026-09-29 a SIXTH corpus runs after the five, from its own seed:
revision 8 (proposed; docs/SEQUENCER.md) - `augadd`/`augerr`, the two
halves of 754-2019 9.5's augmentedAddition, and STX/LDX with a signed
post-step. Besides the generator's arm it runs the recommended pair over
augmented.py's own stress families (ties, cancellations, subnormal
residuals, the overflow threshold), and a directed walk whose indices
start at the depth's edge and near zero, so a strict program crosses the
depth and a decrement wraps at the register's width. Its refusals -
imm[23:12], every field the pair does not read, control code 15 - are
corrupted in and also listed once each. `ldx rX, rX, step`, a load into
its own index, has a directed leg of its own: the loaded value wins and
the step is discarded (CORE-V's rule), strict and not. And one leg that
needs no corpus: a remote handle to a server whose HELLO publishes the
round-2 tile's word, where every revision-8 form must be refused BY NAME
on the client, and loads when the word publishes the bit.

Since the step-6 round (2026-10-02, ABI 0.17) a SEVENTH corpus runs
after the six, from its own seed: R24's flag control - `quiet`,
`endquiet`, `raise` - and R23's per-lane flags, asked for on every run
(docs/SEQUENCER.md). Both executors must agree on FLAGS, STATUS with
its mark, every deposit, count and scratch-out slot and every lane
byte, under a mask a third of the time, whose masked lanes' bytes must
stay the caller's; the model's own identities are checked beside them.
The bracket rules and every field the three do not read are refused by
both, directed and corrupted in, and a remote handle to a server
publishing a revision-7 tile's word refuses each code at load and a run
asking for the block, by name and before any frame.
"""

import argparse
import ctypes
import os
import random
import socket
import struct
import sys
import threading
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from cft_golden import FORMATS, vectors  # noqa: E402
from cft_golden import seq  # noqa: E402

CFT_OK = 0
CFT_ERR_INVALID_ARGUMENT = 1
CFT_ERR_UNSUPPORTED = 2


def load_library():
    override = os.environ.get("CFT_LIB")
    if override:
        path = Path(override)
    else:
        name = {"win32": "cft.dll", "cygwin": "cft.dll",
                "darwin": "libcft.dylib"}.get(sys.platform, "libcft.so")
        path = ROOT / "host" / name
    if not path.exists():
        raise SystemExit(f"{path} not found - run `make -C host` first")
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
    lib.cft_program_run.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.c_void_p, u32p, ctypes.c_size_t,
                                    u32p, u32p]
    lib.cft_program_run.restype = ctypes.c_int
    lib.cft_program_run_ex.argtypes = [ctypes.c_void_p,
                                       ctypes.POINTER(RunArgs)]
    lib.cft_program_run_ex.restype = ctypes.c_int
    lib.cft_strerror.argtypes = [ctypes.c_int]
    lib.cft_strerror.restype = ctypes.c_char_p
    lib.cft_last_error.argtypes = []
    lib.cft_last_error.restype = ctypes.c_char_p
    return lib


def run_in_c(lib, dev, prog, a, b, c):
    """-> (deposits, counts, flags, status) or raises."""
    fmt = prog.fmt
    esz = fmt.width // 8
    n = len(a)
    image = prog.to_bytes()

    handle = ctypes.c_void_p()
    st = lib.cft_program_load(dev, image, len(image), ctypes.byref(handle))
    if st != CFT_OK:
        raise RuntimeError(f"cft_program_load: "
                           f"{lib.cft_strerror(st).decode()}")
    try:
        def pack(vals):
            return ctypes.create_string_buffer(
                b"".join(v.to_bytes(esz, "little") for v in vals), n * esz)

        buf_a, buf_b, buf_c = pack(a), pack(b), pack(c)
        ndep = n * prog.max_deposits
        buf_d = ctypes.create_string_buffer(max(1, ndep * esz))
        counts = (ctypes.c_uint32 * max(1, n))()
        flags = ctypes.c_uint32(0)
        bus = ctypes.c_uint32(0)
        st = lib.cft_program_run(handle, buf_a, buf_b, buf_c, buf_d,
                                 counts, n, ctypes.byref(flags),
                                 ctypes.byref(bus))
        if st != CFT_OK:
            raise RuntimeError(f"cft_program_run: "
                               f"{lib.cft_strerror(st).decode()}")
        raw = buf_d.raw
        deposits = [int.from_bytes(raw[i * esz:(i + 1) * esz], "little")
                    for i in range(ndep)]
        return deposits, list(counts)[:n], flags.value, bus.value
    finally:
        lib.cft_program_free(handle)


class RunArgs(ctypes.Structure):
    """cft_run_args, field for field (host/include/cft.h, ABI 0.17)."""
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
                # ABI 0.14 (docs/ROUND2.md), appended in cft.h's order.
                # The size handshake refuses a struct this mirror gets
                # wrong, which is how a missing field is found: every
                # program run "refused by C" at once (2026-09-15).
                ("idx_a", ctypes.c_void_p),
                ("idx_b", ctypes.c_void_p),
                ("idx_c", ctypes.c_void_p),
                ("idx_a_src", ctypes.c_size_t),
                ("idx_b_src", ctypes.c_size_t),
                ("idx_c_src", ctypes.c_size_t),
                ("idx_scratch_in", ctypes.c_void_p),
                ("idx_scratch_src", ctypes.c_size_t),
                ("lane_mask", ctypes.c_void_p),
                ("lane_mask_bytes", ctypes.c_size_t),
                # ABI 0.17 (docs/SEQUENCER.md R23), appended the same way
                ("lane_flags", ctypes.c_void_p),
                ("lane_flags_bytes", ctypes.c_size_t)]


def run_in_c_idx(lib, dev, prog, a, b, c, n, scratch_in, idx):
    """-> (deposits, counts, flags, status, scratch_out), or the
    library's refusal as a RuntimeError, through cft_program_run_ex
    with ABI 0.14's index tables.

    `a`, `b`, `c` and `scratch_in` are the SOURCES the tables index and
    have no reason to hold n elements; `idx` is
    (idx_a, idx_b, idx_c, idx_scratch_in), each a list or None. This is
    a separate entry point from run_in_c_ex and not a widening of it,
    so that the three corpora above keep calling the function they have
    always called with the arguments they have always passed."""
    fmt = prog.fmt
    esz = fmt.width // 8
    image = prog.to_bytes()
    nsin, nsout = prog.n_scratch_in, prog.n_scratch_out

    handle = ctypes.c_void_p()
    st = lib.cft_program_load(dev, image, len(image), ctypes.byref(handle))
    if st != CFT_OK:
        raise RuntimeError(f"cft_program_load: "
                           f"{lib.cft_strerror(st).decode()}")
    try:
        def pack(vals):
            return ctypes.create_string_buffer(
                b"".join(v.to_bytes(esz, "little") for v in vals),
                max(1, len(vals) * esz))

        def pack_idx(vals):
            if vals is None:
                return None
            return ctypes.create_string_buffer(
                b"".join(int(v).to_bytes(4, "little") for v in vals),
                max(1, len(vals) * 4))

        buf_a, buf_b, buf_c = pack(a), pack(b), pack(c)
        ndep = n * prog.max_deposits
        buf_d = ctypes.create_string_buffer(max(1, ndep * esz))
        counts = (ctypes.c_uint32 * max(1, n))()
        flags = ctypes.c_uint32(0)
        bus = ctypes.c_uint32(0)
        buf_si = pack(scratch_in) if nsin else None
        buf_so = (ctypes.create_string_buffer(max(1, n * nsout * esz))
                  if nsout else None)
        tabs = [pack_idx(t) for t in idx]

        args = RunArgs()
        args.struct_size = ctypes.sizeof(RunArgs)
        args.a = ctypes.cast(buf_a, ctypes.c_void_p)
        args.b = ctypes.cast(buf_b, ctypes.c_void_p)
        args.c = ctypes.cast(buf_c, ctypes.c_void_p)
        args.n = n
        args.bank, args.bank_bytes = None, 0
        args.scratch_in = (ctypes.cast(buf_si, ctypes.c_void_p)
                           if buf_si is not None else None)
        # With a table this is the POOL's length, not the block's -
        # which is the one shape rule the indexed scratch block adds.
        args.scratch_in_bytes = (len(scratch_in) * esz) if nsin else 0
        args.scratch_out = (ctypes.cast(buf_so, ctypes.c_void_p)
                            if buf_so is not None else None)
        args.scratch_out_bytes = n * nsout * esz
        args.deposits = ctypes.cast(buf_d, ctypes.c_void_p)
        args.counts = counts
        args.flags_out = ctypes.pointer(flags)
        args.bus_out = ctypes.pointer(bus)
        for field, src, buf, srclen in (
                ("idx_a", idx[0], tabs[0], len(a)),
                ("idx_b", idx[1], tabs[1], len(b)),
                ("idx_c", idx[2], tabs[2], len(c))):
            if src is None:
                continue
            setattr(args, field, ctypes.cast(buf, ctypes.c_void_p))
            setattr(args, field + "_src", srclen)
        if idx[3] is not None:
            args.idx_scratch_in = ctypes.cast(tabs[3], ctypes.c_void_p)
            args.idx_scratch_src = len(scratch_in)
        st = lib.cft_program_run_ex(handle, ctypes.byref(args))
        if st != CFT_OK:
            raise RuntimeError(f"cft_program_run_ex: "
                               f"{lib.cft_strerror(st).decode()}")
        raw = buf_d.raw
        deposits = [int.from_bytes(raw[i * esz:(i + 1) * esz], "little")
                    for i in range(ndep)]
        sout = []
        if nsout:
            raw = buf_so.raw
            sout = [int.from_bytes(raw[i * esz:(i + 1) * esz], "little")
                    for i in range(n * nsout)]
        return deposits, list(counts)[:n], flags.value, bus.value, sout
    finally:
        lib.cft_program_free(handle)


def make_table(rng, n, src_len, none_frac):
    """A table of n entries into a source of src_len, with some
    fraction of them CFT_IDX_NONE. Distinct where the source is long
    enough to allow it, so an entry read one place out lands on a value
    the right entry could not have given."""
    if src_len >= n:
        vals = rng.sample(range(src_len), n)
    else:
        vals = [rng.randrange(src_len) for _ in range(n)]
    for i in range(n):
        if rng.random() < none_frac:
            vals[i] = seq.IDX_NONE
    return vals


def indexed_corpus(lib, dev, fmt, name, args, S):
    """The fourth corpus, for one format. Mutates the counters in S."""
    rng = random.Random(args.seed ^ (fmt.width * 6151) ^ 0x1D6ED)
    checked = 0
    for _trial in range(max(1, args.trials // 2)):
        insns, consts = seq.random_program(fmt, rng, nconst=3,
                                           extended=True, wide_regs=True,
                                           scratch=True)
        maxdep = rng.choice([1, 2, 4])
        io = rng.random() < 0.5
        nsin = rng.choice([1, 2, 3]) if io else 0
        nsout = rng.choice([0, 1, 2]) if io else 0
        flags = seq.FLAG_SCRATCH_IO if io else 0
        try:
            prog = seq.Program(fmt, insns, consts, maxdep, flags=flags,
                               n_scratch_in=nsin, n_scratch_out=nsout)
        except seq.ProgramError:
            continue
        # n and the SOURCE lengths are drawn independently: a source
        # shorter than the run is the shape this feature exists for,
        # and a source longer than it is the one where an index past n
        # is still perfectly legal.
        n = rng.choice([1, 2, 63, 64, 65, 100, 129])
        if n > 64:
            S["blocked"] += 1
        alen = rng.choice([1, 3, max(1, n // 2), n, n + 37])
        blen = rng.choice([1, max(1, n // 3), n, 2 * n])
        clen = rng.choice([1, 7, n, n + 5])
        a = seq.random_inputs(fmt, rng, alen)
        b = seq.random_inputs(fmt, rng, blen)
        c = seq.random_inputs(fmt, rng, clen)
        none_frac = rng.choice([0.0, 0.1, 0.4])
        # Which blocks are indexed: at least one, or there is nothing
        # here this file does not already test.
        want_idx = [rng.random() < 0.6 for _ in range(3)]
        want_si = io and nsin and rng.random() < 0.6
        if not any(want_idx) and not want_si:
            want_idx[0] = True
        tabs = [make_table(rng, n, ln, none_frac) if w else None
                for w, ln in zip(want_idx, (alen, blen, clen))]
        pool = None
        if io and nsin:
            plen = rng.choice([1, 5, n, n * nsin])
            pool = seq.random_inputs(fmt, rng, plen)
        si_tab = (make_table(rng, n * nsin, len(pool), none_frac)
                  if want_si else None)
        for t in tabs + [si_tab]:
            if t is None:
                continue
            S["tables"] += 1
            S["none"] += sum(1 for v in t if v == seq.IDX_NONE)
        # Streams with no table must be exactly n long, as they always
        # were; the gathered ones are their own length.
        for r, t in enumerate(tabs):
            if t is not None:
                continue
            vals = seq.random_inputs(fmt, rng, n)
            if r == 0:
                a = vals
            elif r == 1:
                b = vals
            else:
                c = vals
        sin_dense = (seq.random_inputs(fmt, rng, n * nsin)
                     if (io and nsin and not want_si) else None)
        sin_arg = pool if want_si else sin_dense

        # One trial in six puts an index AT the source's length - the
        # off-by-one the bound exists for - and both sides must refuse
        # it by name and by value, before the run.
        if rng.random() < 1 / 6:
            which = next((i for i, t in enumerate(tabs) if t is not None),
                         None)
            if which is not None:
                lens = (len(a), len(b), len(c))
                tabs[which] = list(tabs[which])
                tabs[which][rng.randrange(n)] = lens[which]
                try:
                    seq.run(prog, a, b, c, scratch_in=sin_arg,
                            idx_a=tabs[0], idx_b=tabs[1], idx_c=tabs[2],
                            idx_scratch_in=si_tab)
                    print(f"  MISMATCH {name} (indexed corpus): the model "
                          f"ACCEPTED an index at the source's length")
                    S["bad"] += 1
                    continue
                except seq.ProgramError:
                    pass
                try:
                    run_in_c_idx(lib, dev, prog, a, b, c, n, sin_arg,
                                 (tabs[0], tabs[1], tabs[2], si_tab))
                    print(f"  MISMATCH {name} (indexed corpus): libcft ran "
                          f"a program whose index is at the source's "
                          f"length, which the model refuses")
                    S["bad"] += 1
                except RuntimeError:
                    S["oob"] += 1
                continue

        want = seq.run(prog, a, b, c, scratch_in=sin_arg,
                       idx_a=tabs[0], idx_b=tabs[1], idx_c=tabs[2],
                       idx_scratch_in=si_tab)
        try:
            got = run_in_c_idx(lib, dev, prog, a, b, c, n, sin_arg,
                               (tabs[0], tabs[1], tabs[2], si_tab))
        except RuntimeError as e:
            print(f"  MISMATCH {name} (indexed corpus): the model runs "
                  f"this program and libcft refuses it: {e}")
            S["bad"] += 1
            continue
        got_dep, got_counts, got_flags, got_status, got_so = got
        if (got_dep != want.deposits or got_counts != want.counts
                or got_flags != want.flags or got_status != want.status
                or got_so != want.scratch_out):
            S["bad"] += 1
            if S["bad"] <= 3:
                print(f"  MISMATCH {name} (indexed corpus) n={n} "
                      f"lens={len(a)},{len(b)},{len(c)} "
                      f"tables={[t is not None for t in tabs]} "
                      f"si={si_tab is not None}")
                print(f"    program  {[hex(i) for i in insns]}")
                print(f"    flags    model 0x{want.flags:02x}  "
                      f"libcft 0x{got_flags:02x}")
                for i, (w, g) in enumerate(zip(want.deposits, got_dep)):
                    if w != g:
                        print(f"    deposit[{i}] model 0x{w:x} "
                              f"libcft 0x{g:x}")
                        break
        checked += 1
        S["total"] += 1

        # The control, on one trial in five. Its program is not the
        # random one: DEPOSIT r0 puts the gathered element itself in
        # the output, so an identity table is bit-identical to the
        # dense run BY CONSTRUCTION and a rotated one cannot be -
        # which is what makes the first half a gate rather than a
        # tautology. A random program may never read r0 at all, and
        # then both halves pass and neither proves anything.
        if rng.random() < 0.2:
            ctl = seq.Program(fmt, [seq.deposit(0), seq.halt()],
                              max_deposits=1)
            vals = seq.random_inputs(fmt, rng, n)
            ident = list(range(n))
            dense = run_in_c_idx(lib, dev, ctl, vals, vals, vals, n,
                                 None, (None, None, None, None))
            same = run_in_c_idx(lib, dev, ctl, vals, vals, vals, n,
                                None, (ident, None, None, None))
            if dense != same:
                print(f"  MISMATCH {name} (indexed corpus): an identity "
                      f"table is not the dense run, in libcft")
                S["bad"] += 1
            S["identity"] += 1
            if n > 1 and len(set(vals)) > 1:
                perm = [(i + 1) % n for i in range(n)]
                other = run_in_c_idx(lib, dev, ctl, vals, vals, vals, n,
                                     None, (perm, None, None, None))
                if other == dense:
                    print(f"  MISMATCH {name} (indexed corpus): a rotated "
                          f"table gave the DENSE answer from a program "
                          f"that deposits r0, so the identity half of "
                          f"this control could not have failed")
                    S["bad"] += 1
                else:
                    S["permuted"] += 1
                # ...and the rotation is what the model says it is.
                want_rot = seq.run(ctl, vals, vals, vals, idx_a=perm)
                if other[0] != want_rot.deposits:
                    print(f"  MISMATCH {name} (indexed corpus): the "
                          f"rotated run differs from the model")
                    S["bad"] += 1
    print(f"{name}: {checked} indexed-corpus programs compared")


def run_in_c_mask(lib, dev, prog, a, b, c, n, scratch_in, keep,
                  fill=0xA5):
    """-> (deposits, counts, flags, status, scratch_out), each read
    back RAW, through cft_program_run_ex with ABI 0.14's lane mask.

    Every output buffer is filled with `fill` BEFORE the call rather
    than left zeroed, which is the whole point of this entry point: R17
    says a masked lane's deposit slots, count and scratch-out slots are
    not written, and against a zeroed buffer "not written" and "written
    with +0" are the same bytes. Against a pattern they are not.

    The deposits and the scratch-out block come back as byte strings,
    not as integers, so a masked lane can be compared against the
    pattern without inventing a number for it; the counts come back as
    a list of the uint32s, pattern included."""
    fmt = prog.fmt
    esz = fmt.width // 8
    image = prog.to_bytes()
    nsin, nsout = prog.n_scratch_in, prog.n_scratch_out

    handle = ctypes.c_void_p()
    st = lib.cft_program_load(dev, image, len(image), ctypes.byref(handle))
    if st != CFT_OK:
        raise RuntimeError(f"cft_program_load: "
                           f"{lib.cft_strerror(st).decode()}")
    try:
        def pack(vals):
            return ctypes.create_string_buffer(
                b"".join(v.to_bytes(esz, "little") for v in vals),
                max(1, len(vals) * esz))

        buf_a, buf_b, buf_c = pack(a), pack(b), pack(c)
        ndep = n * prog.max_deposits
        buf_d = ctypes.create_string_buffer(
            bytes([fill]) * max(1, ndep * esz), max(1, ndep * esz))
        counts = (ctypes.c_uint32 * max(1, n))()
        for i in range(n):
            counts[i] = 0xA5A5A5A5
        flags = ctypes.c_uint32(0)
        bus = ctypes.c_uint32(0)
        buf_si = pack(scratch_in) if nsin else None
        buf_so = (ctypes.create_string_buffer(
                      bytes([fill]) * max(1, n * nsout * esz),
                      max(1, n * nsout * esz))
                  if nsout else None)
        mbytes = (n + 7) // 8
        raw = bytearray(mbytes)
        for i, k in enumerate(keep):
            if k:
                raw[i >> 3] |= 1 << (i & 7)
        buf_m = ctypes.create_string_buffer(bytes(raw), max(1, mbytes))

        args = RunArgs()
        args.struct_size = ctypes.sizeof(RunArgs)
        args.a = ctypes.cast(buf_a, ctypes.c_void_p)
        args.b = ctypes.cast(buf_b, ctypes.c_void_p)
        args.c = ctypes.cast(buf_c, ctypes.c_void_p)
        args.n = n
        args.bank, args.bank_bytes = None, 0
        args.scratch_in = (ctypes.cast(buf_si, ctypes.c_void_p)
                           if buf_si is not None else None)
        args.scratch_in_bytes = (n * nsin * esz) if nsin else 0
        args.scratch_out = (ctypes.cast(buf_so, ctypes.c_void_p)
                            if buf_so is not None else None)
        args.scratch_out_bytes = n * nsout * esz
        args.deposits = ctypes.cast(buf_d, ctypes.c_void_p)
        args.counts = counts
        args.flags_out = ctypes.pointer(flags)
        args.bus_out = ctypes.pointer(bus)
        args.lane_mask = ctypes.cast(buf_m, ctypes.c_void_p)
        args.lane_mask_bytes = mbytes
        st = lib.cft_program_run_ex(handle, ctypes.byref(args))
        if st != CFT_OK:
            raise RuntimeError(f"cft_program_run_ex: "
                               f"{lib.cft_strerror(st).decode()}")
        dep = buf_d.raw[:ndep * esz]
        sout = buf_so.raw[:n * nsout * esz] if nsout else b""
        return dep, list(counts)[:n], flags.value, bus.value, sout
    finally:
        lib.cft_program_free(handle)


def masked_corpus(lib, dev, fmt, name, args, M):
    """The fifth corpus (R17), for one format. Mutates the counters in M.

    Its own seed, so the four corpora above draw exactly what they drew
    before it existed. Its claim is two claims, and they fail
    differently: an UNMASKED lane must be bit-for-bit the model's, and
    a MASKED lane's bytes must be the ones the caller put there - which
    is why the buffers are filled with a pattern rather than zeroed.
    """
    rng = random.Random(args.seed ^ (fmt.width * 7919) ^ 0x5A5E1)
    esz = fmt.width // 8
    checked = 0
    for _trial in range(max(1, args.trials // 2)):
        insns, consts = seq.random_program(fmt, rng, nconst=3,
                                           extended=True, wide_regs=True,
                                           scratch=True)
        maxdep = rng.choice([1, 2, 4])
        io = rng.random() < 0.5
        nsin = rng.choice([1, 2, 3]) if io else 0
        nsout = rng.choice([0, 1, 2]) if io else 0
        flags = seq.FLAG_SCRATCH_IO if io else 0
        try:
            prog = seq.Program(fmt, insns, consts, maxdep, flags=flags,
                               n_scratch_in=nsin, n_scratch_out=nsout)
        except seq.ProgramError:
            continue
        # The block boundary matters more here than anywhere: libcft
        # runs 64 lanes at a time and the mask is indexed by the GLOBAL
        # lane, so a mask sliced per block rather than read per lane
        # gives every block after the first somebody else's bits.
        n = rng.choice([1, 2, 63, 64, 65, 100, 129, 193])
        if n > 64:
            M["blocked"] += 1
        # Four shapes of mask, because they fail differently: all ones
        # (which must be the unmasked run), all zeros (which must write
        # nothing at all), a sparse mask and a dense one.
        shape = rng.choice(["ones", "zeros", "sparse", "dense", "dense"])
        if shape == "ones":
            keep = [True] * n
        elif shape == "zeros":
            keep = [False] * n
        elif shape == "sparse":
            keep = [rng.random() < 0.2 for _ in range(n)]
        else:
            keep = [rng.random() < 0.8 for _ in range(n)]
        M[shape] += 1
        kept = sum(1 for k in keep if k)
        M["kept"] += kept
        M["masked_lanes"] += n - kept

        a = seq.random_inputs(fmt, rng, n)
        b = seq.random_inputs(fmt, rng, n)
        c = seq.random_inputs(fmt, rng, n)
        sin_arg = (seq.random_inputs(fmt, rng, n * nsin)
                   if (io and nsin) else None)

        want = seq.run(prog, a, b, c, scratch_in=sin_arg, lane_mask=keep)
        try:
            got = run_in_c_mask(lib, dev, prog, a, b, c, n, sin_arg, keep)
        except RuntimeError as e:
            print(f"  MISMATCH {name} (masked corpus): the model runs "
                  f"this program and libcft refuses it: {e}")
            M["bad"] += 1
            continue
        got_dep, got_counts, got_flags, got_status, got_so = got
        bad = []
        if got_flags != want.flags:
            bad.append(f"flags model 0x{want.flags:02x} "
                       f"libcft 0x{got_flags:02x}")
        if got_status != want.status:
            bad.append(f"status model 0x{want.status:02x} "
                       f"libcft 0x{got_status:02x}")
        pat_el = bytes([0xA5]) * esz
        for i in range(n):
            if keep[i]:
                if got_counts[i] != want.counts[i]:
                    bad.append(f"count[{i}] model {want.counts[i]} "
                               f"libcft {got_counts[i]}")
                for s in range(maxdep):
                    j = i * maxdep + s
                    g = int.from_bytes(got_dep[j * esz:(j + 1) * esz],
                                       "little")
                    if g != want.deposits[j]:
                        bad.append(f"deposit[lane {i} slot {s}] model "
                                   f"0x{want.deposits[j]:x} libcft 0x{g:x}")
                        break
                for s in range(nsout):
                    j = i * nsout + s
                    g = int.from_bytes(got_so[j * esz:(j + 1) * esz],
                                       "little")
                    if g != want.scratch_out[j]:
                        bad.append(f"scratch_out[lane {i} slot {s}] model "
                                   f"0x{want.scratch_out[j]:x} "
                                   f"libcft 0x{g:x}")
                        break
            else:
                if got_counts[i] != 0xA5A5A5A5:
                    bad.append(f"count[{i}] was WRITTEN ({got_counts[i]}) "
                               f"for a lane the mask cleared")
                for s in range(maxdep):
                    j = i * maxdep + s
                    if got_dep[j * esz:(j + 1) * esz] != pat_el:
                        bad.append(f"deposit[lane {i} slot {s}] was "
                                   f"WRITTEN for a lane the mask cleared")
                        break
                for s in range(nsout):
                    j = i * nsout + s
                    if got_so[j * esz:(j + 1) * esz] != pat_el:
                        bad.append(f"scratch_out[lane {i} slot {s}] was "
                                   f"WRITTEN for a lane the mask cleared")
                        break
        if bad:
            M["bad"] += 1
            if M["bad"] <= 3:
                print(f"  MISMATCH {name} (masked corpus) n={n} "
                      f"shape={shape} kept={kept} maxdep={maxdep} "
                      f"nsin={nsin} nsout={nsout}")
                print(f"    program  {[hex(i) for i in insns]}")
                for line in bad[:6]:
                    print(f"    {line}")
        checked += 1
        M["total"] += 1

        # The control, on one trial in five, and it is the negative
        # control of the parcel written as a corpus check: an all-ones
        # mask must be bit-identical to NO mask, and a mask with holes
        # must not be - the second half being what makes the first a
        # gate rather than a tautology. The program is the random one,
        # so this is the same claim over arbitrary programs.
        if rng.random() < 0.2:
            plain = run_in_c_ex(lib, dev, prog, a, b, c, sin_arg)
            ones = run_in_c_mask(lib, dev, prog, a, b, c, n, sin_arg,
                                 [True] * n, fill=0x00)
            plain_dep = b"".join(v.to_bytes(esz, "little")
                                 for v in plain[0])
            plain_so = b"".join(v.to_bytes(esz, "little") for v in plain[4])
            if (ones[0] != plain_dep or ones[1] != plain[1]
                    or ones[2] != plain[2] or ones[3] != plain[3]
                    or ones[4] != plain_so):
                print(f"  MISMATCH {name} (masked corpus): an all-ones "
                      f"mask is not the unmasked run, in libcft")
                M["bad"] += 1
            M["allones"] += 1
            # ...and the half that makes it a gate. Only where the
            # program actually deposits something: with every count
            # zero, a holed mask and an all-ones mask write the same
            # +0 everywhere and the comparison would prove nothing.
            if n > 1 and any(plain[1]):
                holes = [i % 2 == 0 for i in range(n)]
                other = run_in_c_mask(lib, dev, prog, a, b, c, n, sin_arg,
                                      holes, fill=0x00)
                if other[0] == ones[0] and other[1] == ones[1]:
                    print(f"  MISMATCH {name} (masked corpus): a mask with "
                          f"holes gave the unmasked answer, so the "
                          f"all-ones half of this control could not have "
                          f"failed")
                    M["bad"] += 1
                else:
                    M["holed"] += 1
    print(f"{name}: {checked} masked-corpus programs compared")


def run_in_c_ex(lib, dev, prog, a, b, c, scratch_in):
    """-> (deposits, counts, flags, status, scratch_out) through
    cft_program_run_ex, the entry point a program that declares scratch
    I/O must take; a program that declares none goes through it too,
    with both scratch pointers NULL, which the contract says is the
    same run cft_program_run makes."""
    fmt = prog.fmt
    esz = fmt.width // 8
    n = len(a)
    image = prog.to_bytes()
    nsin, nsout = prog.n_scratch_in, prog.n_scratch_out

    handle = ctypes.c_void_p()
    st = lib.cft_program_load(dev, image, len(image), ctypes.byref(handle))
    if st != CFT_OK:
        raise RuntimeError(f"cft_program_load: "
                           f"{lib.cft_strerror(st).decode()}")
    try:
        def pack(vals, count):
            return ctypes.create_string_buffer(
                b"".join(v.to_bytes(esz, "little") for v in vals),
                max(1, count * esz))

        buf_a, buf_b, buf_c = pack(a, n), pack(b, n), pack(c, n)
        ndep = n * prog.max_deposits
        buf_d = ctypes.create_string_buffer(max(1, ndep * esz))
        counts = (ctypes.c_uint32 * max(1, n))()
        flags = ctypes.c_uint32(0)
        bus = ctypes.c_uint32(0)
        buf_si = pack(scratch_in, n * nsin) if nsin else None
        buf_so = (ctypes.create_string_buffer(max(1, n * nsout * esz))
                  if nsout else None)

        args = RunArgs()
        args.struct_size = ctypes.sizeof(RunArgs)
        args.a = ctypes.cast(buf_a, ctypes.c_void_p)
        args.b = ctypes.cast(buf_b, ctypes.c_void_p)
        args.c = ctypes.cast(buf_c, ctypes.c_void_p)
        args.n = n
        args.bank, args.bank_bytes = None, 0
        args.scratch_in = (ctypes.cast(buf_si, ctypes.c_void_p)
                           if buf_si is not None else None)
        args.scratch_in_bytes = n * nsin * esz
        args.scratch_out = (ctypes.cast(buf_so, ctypes.c_void_p)
                            if buf_so is not None else None)
        args.scratch_out_bytes = n * nsout * esz
        args.deposits = ctypes.cast(buf_d, ctypes.c_void_p)
        args.counts = counts
        args.flags_out = ctypes.pointer(flags)
        args.bus_out = ctypes.pointer(bus)
        st = lib.cft_program_run_ex(handle, ctypes.byref(args))
        if st != CFT_OK:
            raise RuntimeError(f"cft_program_run_ex: "
                               f"{lib.cft_strerror(st).decode()}")
        raw = buf_d.raw
        deposits = [int.from_bytes(raw[i * esz:(i + 1) * esz], "little")
                    for i in range(ndep)]
        sout = []
        if nsout:
            raw = buf_so.raw
            sout = [int.from_bytes(raw[i * esz:(i + 1) * esz], "little")
                    for i in range(n * nsout)]
        return deposits, list(counts)[:n], flags.value, bus.value, sout
    finally:
        lib.cft_program_free(handle)


def corrupt_scratch(insns, rng):
    """The refusals revision 3 added, one per program: a static slot at
    the depth, a field a scratch code does not read, a ninth index bit
    where nothing reads it, imm[31], and a ninth-bit index past the
    bank. Each is an instruction the model must refuse and the C
    loader must refuse too."""
    out = list(insns)
    what = rng.choice(["stl_past_depth", "ldl_past_depth", "stx_with_imm",
                       "ldx_stray_kx", "stl_stray_rd", "ldl_stray_rb",
                       "kx9_without_kx", "kx9_on_register_operand",
                       "imm31", "kx9_past_bank"])
    D = seq.SCRATCH_D
    if what == "stl_past_depth":
        out.insert(0, seq.encode(seq.STL, ra=0, ctrl=True, imm=D))
    elif what == "ldl_past_depth":
        out.insert(0, seq.encode(seq.LDL, rd=3, ctrl=True, imm=D))
    elif what == "stx_with_imm":
        # STX takes its slot from rb; imm[23:12] is read by nothing. It
        # was imm = 1 - all of imm[23:0] unread - until revision 8
        # (proposed 2026-09-29) made imm[11:0] the post-step, so the bit
        # moved to imm[12], the lowest that stays reserved.
        out.insert(0, seq.encode(seq.STX, ra=0, rb=1, ctrl=True,
                                 imm=1 << 12))
    elif what == "ldx_stray_kx":
        out.insert(0, seq.encode(seq.LDX, rd=3, rb=1, ctrl=True, kx=True))
    elif what == "stl_stray_rd":
        # STL reads ra and the slot; rd is not read
        out.insert(0, seq.encode(seq.STL, ra=0, rd=3, ctrl=True, imm=0))
    elif what == "ldl_stray_rb":
        out.insert(0, seq.encode(seq.LDL, rd=3, rb=1, ctrl=True, imm=0))
    elif what == "kx9_without_kx":
        # a ninth index bit on an instruction with no kx at all
        out.insert(0, seq.encode(seq.sf.OP_ADD, 0, ra=1, rb=2,
                                 imm=1 << 28))
    elif what == "kx9_on_register_operand":
        # kb is the constant operand (index 5 through imm[15:8]);
        # imm[28] is ka's ninth bit and ka names a register
        out.insert(0, seq.encode(seq.sf.OP_ADD, 0, ra=1, rb=0, kb=True,
                                 kx=True, imm=(5 << 8) | (1 << 28)))
    elif what == "imm31":
        out.insert(0, seq.encode(seq.sf.OP_ADD, 0, rb=0, kb=True,
                                 kx=True, imm=(1 << 8) | (1 << 31)))
    else:                                   # kx9_past_bank
        # index 300 = 44 in the byte plus the ninth bit, over a bank of
        # a handful of constants: outside the bank, refused by name
        out.insert(0, seq.encode(seq.sf.OP_ADD, 0, rb=0, kb=True,
                                 kx=True, imm=((300 & 0xFF) << 8)
                                 | (1 << 29)))
    return out, what


def scratch_corpus(lib, dev, fmt, name, args, S):
    """The third corpus, for one format. Mutates the counters in S."""
    rng = random.Random(args.seed ^ (fmt.width * 7919) ^ 0x5CA7C4)
    checked = 0
    for trial in range(max(1, args.trials // 2)):
        # Half the corpus draws over a 300-constant bank, so that kx
        # indices at or past 256 - the ninth bit - are reached; the
        # generator's own floor is 40 and never gets there.
        nconst = 300 if rng.random() < 0.5 else 3
        insns, consts = seq.random_program(fmt, rng, nconst=nconst,
                                           extended=True,
                                           wide_regs=True, scratch=True)
        for w in insns:
            dd = seq.decode(w)
            if dd["ctrl"]:
                if dd["op"] == seq.STL:
                    S["stl"] += 1
                elif dd["op"] == seq.LDL:
                    S["ldl"] += 1
                elif dd["op"] == seq.STX:
                    S["stx"] += 1
                elif dd["op"] == seq.LDX:
                    S["ldx"] += 1
            elif dd["kx"]:
                for idx, is_k in seq.sources(dd):
                    if is_k and idx >= 256:
                        S["kx9"] += 1
        maxdep = rng.choice([0, 1, 2, 4])
        io = rng.random() < 0.6
        nsin = rng.choice([0, 1, 2, 3, 5]) if io else 0
        nsout = rng.choice([0, 1, 2, 4]) if io else 0
        # Revision 4 R8: with SCRATCH_STRICT an indexed access at or
        # past the depth is reported rather than reduced modulo it.
        strict = rng.random() < 0.35
        flags = ((seq.FLAG_SCRATCH_IO if io else 0)
                 | (seq.FLAG_SCRATCH_STRICT if strict else 0))
        kind = None
        if rng.random() < 0.3:
            insns, kind = corrupt_scratch(insns, rng)
        elif rng.random() < 0.12:
            # a header the model must refuse: the word without its
            # flag, or a count past the depth
            kind = rng.choice(["io_word_without_flag", "in_past_depth",
                               "out_past_depth"])
            if kind == "io_word_without_flag":
                flags, nsin, nsout = 0, 1, 0
            elif kind == "in_past_depth":
                flags, nsin = seq.FLAG_SCRATCH_IO, seq.SCRATCH_D + 1
            else:
                flags, nsout = seq.FLAG_SCRATCH_IO, seq.SCRATCH_D + 1
        try:
            prog = seq.Program(fmt, insns, consts, maxdep, flags=flags,
                               n_scratch_in=nsin, n_scratch_out=nsout)
        except seq.ProgramError:
            bogus = seq.Program.__new__(seq.Program)
            bogus.fmt, bogus.insns = fmt, insns
            bogus.consts, bogus.max_deposits = consts, maxdep
            bogus.flags = flags
            bogus.n_scratch_in, bogus.n_scratch_out = nsin, nsout
            bogus._n_consts = len(consts)
            handle = ctypes.c_void_p()
            image = bogus.to_bytes()
            rc = lib.cft_program_load(dev, image, len(image),
                                      ctypes.byref(handle))
            if rc == CFT_OK:
                lib.cft_program_free(handle)
                print(f"  MISMATCH {name} (scratch corpus, {kind}): the "
                      f"model refuses this program and libcft loads it")
                S["bad"] += 1
            else:
                S["refused"] += 1
            continue
        if kind is not None:
            # the corruption was meant to be refused and the model let
            # it through: that is a finding about the model, and the C
            # side gets to say so below if it disagrees
            print(f"  NOTE {name} (scratch corpus): the model ACCEPTED a "
                  f"program corrupted as {kind}")
        if io:
            S["io"] += 1
        if prog.flags & seq.FLAG_SCRATCH_STRICT:
            S["strict"] += 1
        n = rng.choice([1, 2, 63, 64, 65, 100, 129])
        if n > 64:
            S["blocked"] += 1
        a = seq.random_inputs(fmt, rng, n)
        b = seq.random_inputs(fmt, rng, n)
        c = seq.random_inputs(fmt, rng, n)
        sin = seq.random_inputs(fmt, rng, n * nsin) if nsin else None
        want = seq.run(prog, a, b, c, scratch_in=sin)
        # The bit is what R8 adds; a strict corpus that never sets it
        # compared the modulo path twice and proved nothing.
        if want.status & seq.STATUS_SCRATCH_RANGE:
            S["range"] += 1
        try:
            got_dep, got_counts, got_flags, got_status, got_so = \
                run_in_c_ex(lib, dev, prog, a, b, c, sin)
        except RuntimeError as e:
            print(f"  MISMATCH {name} (scratch corpus): the model runs "
                  f"this program and libcft refuses it: {e}")
            S["bad"] += 1
            continue
        if (got_dep != want.deposits or got_counts != want.counts
                or got_flags != want.flags or got_status != want.status
                or got_so != want.scratch_out):
            S["bad"] += 1
            if S["bad"] <= 3:
                print(f"  MISMATCH {name} (scratch corpus) n={n} "
                      f"max_deposits={maxdep} in={nsin} out={nsout}")
                print(f"    program  {[hex(i) for i in insns]}")
                print(f"    flags    model 0x{want.flags:02x}  "
                      f"libcft 0x{got_flags:02x}")
                print(f"    status   model 0x{want.status:02x}  "
                      f"libcft 0x{got_status:02x}")
                print(f"    counts   model {want.counts}")
                print(f"             libcft {got_counts}")
                for i, (w, g) in enumerate(zip(want.deposits, got_dep)):
                    if w != g:
                        print(f"    deposit[{i}] model 0x{w:x} "
                              f"libcft 0x{g:x}")
                        break
                for i, (w, g) in enumerate(zip(want.scratch_out, got_so)):
                    if w != g:
                        print(f"    scratch_out[{i}] model 0x{w:x} "
                              f"libcft 0x{g:x}")
                        break
        checked += 1
        S["total"] += 1
    print(f"{name}: {checked} scratch-corpus programs compared")


def corrupt(insns, rng):
    """Turn a valid instruction list into one the model must refuse.

    Without this the fuzz only ever produced legal programs, so the
    refusal comparison counted zero cases and proved nothing. Two
    validators that disagree about what is legal are a device
    executing something the host believed it had refused, which is
    worth more attention than a wrong answer - it is a wrong answer
    nobody is looking for.
    """
    out = list(insns)
    loop_at = [i for i, w in enumerate(out)
               if seq.decode(w)["ctrl"] and seq.decode(w)["op"] == seq.REPEAT]
    choices = ["repeat0", "stray_field", "alu_imm", "kx_empty", "unbalanced",
               "huge_trip", "wrap_trip", "bad_const",
               # the refusals indexed constants added (2026-09-07)
               "kx_wide_const", "kx_stray_reg", "kx_stray_imm",
               "kx_reserved_byte", "kx_on_control",
               # and the one revision 2 added (2026-09-08)
               "kx_const_reghi"]
    if loop_at:
        choices += ["halt_in_loop", "actall_in_loop"]
    what = rng.choice(choices)

    if what == "halt_in_loop":
        out.insert(rng.choice(loop_at) + 1, seq.halt())
    elif what == "actall_in_loop":
        out.insert(rng.choice(loop_at) + 1, seq.actall())
    elif what == "repeat0":
        zero = seq.encode(seq.REPEAT, ctrl=True, imm=0)
        if loop_at:
            out[rng.choice(loop_at)] = zero
        else:
            out.insert(0, zero)
            out.insert(1, seq.endrep())
    elif what == "stray_field":
        out.insert(0, seq.encode(seq.DEPOSIT, ra=0, ka=True, ctrl=True))
    elif what == "alu_imm":
        out.insert(0, seq.encode(seq.sf.OP_FMA, 0, imm=1))
    elif what == "kx_empty":
        # bit 30 is kx since 2026-09-07. Set with no operand naming a
        # constant it selects nothing, so it is refused for exactly the
        # reason it was refused as a reserved bit: a second encoding.
        out.insert(0, seq.encode(seq.sf.OP_FMA, 0, kx=True))
    elif what == "kx_wide_const":
        # the index kx makes reachable, pointed past the bank
        out.insert(0, seq.alu(seq.sf.OP_ADD, 0, rb=255, kb=True, kx=True))
    elif what == "kx_stray_reg":
        # the 4-bit field of an operand whose index came from imm
        out.insert(0, seq.encode(seq.sf.OP_ADD, 0, rb=1, kb=True,
                                 kx=True, imm=1 << 8))
    elif what == "kx_stray_imm":
        # an imm byte for an operand that names a register
        out.insert(0, seq.encode(seq.sf.OP_ADD, 0, ra=1, rb=0, kb=True,
                                 kx=True, imm=(1 << 0) | (1 << 8)))
    elif what == "kx_reserved_byte":
        # imm[28], not imm[24].
        #
        # `kx` reserved the whole of imm[31:24]. Revision 2 of
        # docs/SEQUENCER.md (2026-09-08) took the low nibble of that
        # byte for the five-bit register fields - imm[24] is rd's
        # fifth bit, and on an instruction whose destination is a
        # register it is READ - so a bit that used to be reserved is
        # now part of the encoding, and this case moved up to
        # imm[31:28], which stays reserved-must-be-zero and is refused
        # by both implementations under either revision.
        #
        # The rule that replaced it at imm[26] is the next case.
        out.insert(0, seq.encode(seq.sf.OP_ADD, 0, rb=0, kb=True,
                                 kx=True, imm=(1 << 8) | (1 << 28)))
    elif what == "kx_const_reghi":
        # A constant operand's register high bit. An operand whose `k`
        # bit is set names a CONSTANT, whose index is four bits or a
        # byte of imm and never five, so its fifth register bit is not
        # read and must be zero - the reserved-field rule applied to
        # what revision 2 added, and refused under revision 1 too,
        # where the whole byte was reserved.
        out.insert(0, seq.encode(seq.sf.OP_ADD, 0, rb=0, kb=True,
                                 kx=True, imm=(1 << 8) | (1 << 26)))
    elif what == "kx_on_control":
        # a field a control instruction does not read
        out.insert(0, seq.encode(seq.DEPOSIT, ra=1, ctrl=True, kx=True))
    elif what == "huge_trip":
        # the termination bound: finite is not the same as bounded, and
        # the two implementations compute the worst case separately
        out = ([seq.repeat(0xFFFFFFFF)] * 4 +
               [seq.alu(seq.sf.OP_ADD, 0, 0, 0, 0)] +
               [seq.endrep()] * 4 + out)
    elif what == "wrap_trip":
        # The same bound, reached by a trip-count product that
        # OVERFLOWS sixty-four bits rather than one that is merely
        # huge. 2^16 * 2^17 * 2^31 is exactly 2^64, which is zero in a
        # uint64_t and passed libcft's "> MAX_INSTRUCTIONS" test until
        # 2026-09-07; the model computes the same product in Python
        # integers, so it has always refused this program. Found by
        # host/fuzz; the image is host/fuzz/crashes/
        # program-differential/repeat-trip-product-wraps.
        out = ([seq.repeat(1 << 16), seq.repeat(1 << 17),
                seq.repeat(1 << 31),
                seq.alu(seq.sf.OP_ADD, 0, 0, 0, 0)] +
               [seq.endrep()] * 3 + out)
    elif what == "bad_const":
        out.insert(0, seq.encode(seq.sf.OP_FMA, 0, rb=15, kb=True))
    else:                                   # unbalanced
        out.insert(0, seq.endrep())
    return out, what


# ---- the sixth corpus: revision 8 (proposed, 2026-09-29) ----------------

# Scratch slots 0 and 1 of every lane carry the two indices the directed
# walk below starts from: near the depth's edge, so a +1 walk crosses it
# and a strict program reports, and near zero, so a -1 walk wraps.
_WALK_STARTS = (0, 1, 2, 250, 253, 255, 256, 300)


def corrupt_rev8(insns, rng):
    """The refusals revision 8 adds, one per program: a set bit in
    imm[23:12] of a stepped access, and every field augadd/augerr do not
    read - rc and its high bit, rnd, a k flag, kx, imm[23:0] and
    imm[31:28] - and the next control code, 15, which is still unknown (12
    to 14 are R24's since the step-6 round, and flags_corpus's).
    Each is refused by the model and must be by libcft. (An LDX into its
    own stepped index was a refusal here until the send-back of
    2026-09-29 took rung 2: it loads, the step discarded - see
    rev8_own_index_leg.)"""
    out = list(insns)
    what = rng.choice(["step_reserved_bit", "aug_rc",
                       "aug_rnd", "aug_kx", "aug_kb", "aug_imm_low",
                       "aug_imm_high", "code_15"])
    code = rng.choice([seq.AUGADD, seq.AUGERR])
    regs = dict(rd=1, ra=2, rb=3, ctrl=True)
    if what == "step_reserved_bit":
        op = rng.choice([seq.STX, seq.LDX])
        fields = dict(ra=1, rb=2) if op == seq.STX else dict(rd=1, rb=2)
        word = seq.encode(op, ctrl=True,
                          imm=(1 << rng.randrange(12, 24))
                          | rng.randrange(1 << 12), **fields)
    elif what == "aug_rc":
        word = seq.encode(code, rc=rng.randrange(1, 32), **regs)
    elif what == "aug_rnd":
        word = seq.encode(code, rnd=rng.randrange(1, 5), **regs)
    elif what == "aug_kx":
        word = seq.encode(code, kx=True, **regs)
    elif what == "aug_kb":
        word = seq.encode(code, kb=True, **regs)
    elif what == "aug_imm_low":
        word = seq.encode(code, imm=1 << rng.randrange(0, 24), **regs)
    elif what == "aug_imm_high":
        word = seq.encode(code, imm=1 << rng.randrange(27, 32), **regs)
    else:
        word = seq.encode(15, ctrl=True)
    out.insert(rng.randrange(len(out)), word)
    return out, what


def rev8_refusal_words():
    """Every revision-8 refusal, once, as (label, word): each bit of
    imm[23:12] on a stepped STX and a stepped LDX; and on augadd and
    augerr each field they do not read - rc, rc's high bit, each rnd, each
    k flag, kx, each bit of imm[23:0] and of imm[31:27] - and three codes
    that stay unknown. corrupt_rev8 above DRAWS from the same kinds, which
    reaches each one only by luck at a small trial count; this reaches each
    one every run (a C plant that accepted imm[23:12] on LDX went uncaught
    by the draw at 120 programs, 2026-09-29)."""
    words = []
    for op, fields in ((seq.STX, dict(ra=1, rb=2)),
                       (seq.LDX, dict(rd=1, rb=2))):
        for b in range(12, 24):
            words.append((f"{seq.CTRL_NAMES[op]} imm[{b}]", seq.encode(
                op, ctrl=True, imm=(1 << b) | 1, **fields)))
    for op in (seq.AUGADD, seq.AUGERR):
        base = dict(rd=1, ra=2, rb=3, ctrl=True)
        extra = [("rc", dict(rc=4)), ("rc hi", dict(rc=16)),
                 ("ka", dict(ka=True)), ("kb", dict(kb=True)),
                 ("kc", dict(kc=True)), ("kx", dict(kx=True))]
        extra += [(f"rnd {r}", dict(rnd=r)) for r in range(1, 5)]
        extra += [(f"imm[{b}]", dict(imm=1 << b))
                  for b in list(range(24)) + [27, 28, 29, 30, 31]]
        for label, f in extra:
            words.append((f"{seq.CTRL_NAMES[op]} {label}",
                          seq.encode(op, **{**base, **f})))
    for code in (15, 16, 255):
        words.append((f"control code {code}", seq.encode(code, ctrl=True)))
    return words


def rev8_directed_refusals(lib, dev, fmt, name, R):
    """rev8_refusal_words(), each in a program of its own: the model must
    refuse it and libcft must refuse it too."""
    for label, word in rev8_refusal_words():
        insns = [word, seq.halt()]
        try:
            seq.Program(fmt, insns, max_deposits=0)
            print(f"  MISMATCH {name} (revision-8 refusals, {label}): the "
                  f"model ACCEPTS a word this corpus lists as refused")
            R["bad"] += 1
            continue
        except seq.ProgramError:
            pass
        bogus = seq.Program.__new__(seq.Program)
        bogus.fmt, bogus.insns, bogus.consts = fmt, insns, []
        bogus.max_deposits, bogus.flags = 0, 0
        bogus.n_scratch_in = bogus.n_scratch_out = 0
        bogus._n_consts = 0
        image = bogus.to_bytes()
        handle = ctypes.c_void_p()
        rc = lib.cft_program_load(dev, image, len(image),
                                  ctypes.byref(handle))
        if rc == CFT_OK:
            lib.cft_program_free(handle)
            print(f"  MISMATCH {name} (revision-8 refusals, {label}): the "
                  f"model refuses this word and libcft loads it")
            R["bad"] += 1
        else:
            R["directed"] += 1


def rev8_own_index_leg(lib, dev, fmt, name, R):
    """`ldx rX, rX, step`: the load lands in its own index register, the
    loaded value wins it and the step is discarded - RISC-V CORE-V's rule
    for post-incremented loads, which rung 2 of Logan's rule takes.

    Each program chases pointers - the loaded value is the next index -
    through a scratch block of small indices, large ones and a float's
    bits, four times, depositing each, then stores the index through
    itself with a step (`stx rX, rX, step`, which keeps its step) and
    deposits it again. Three registers, the four edge steps, strict and
    not, n across the 64-lane block. Held two ways: libcft against the
    model, and the model against the same program with the load's step
    written as 0 - which a discarded step must equal exactly."""
    rng = random.Random(fmt.width * 131 + 7)
    W = fmt.width
    pool = [0, 1, 2, 3, 5, 9, 15, 255, 256, 300, (1 << W) - 1,
            sf_one(fmt)]
    k = 0
    for r in (0, 5, 31):
        for step in (1, -1, seq.STEP_MAX, seq.STEP_MIN):
            for strict in (False, True):
                def body(s):
                    return [seq.ldl(r, 0), seq.repeat(4),
                            seq.ldx(r, r, s), seq.deposit(r), seq.endrep(),
                            seq.stx(r, r, step), seq.deposit(r),
                            seq.halt()]
                flags = (seq.FLAG_SCRATCH_IO
                         | (seq.FLAG_SCRATCH_STRICT if strict else 0))
                prog = seq.Program(fmt, body(step), max_deposits=5,
                                   flags=flags, n_scratch_in=16,
                                   n_scratch_out=16)
                zero = seq.Program(fmt, body(0), max_deposits=5,
                                   flags=flags, n_scratch_in=16,
                                   n_scratch_out=16)
                n = (1, 65, 129)[k % 3]
                k += 1
                a = seq.random_inputs(fmt, rng, n)
                b = seq.random_inputs(fmt, rng, n)
                c = seq.random_inputs(fmt, rng, n)
                sin = [rng.choice(pool) for _ in range(16 * n)]
                want = seq.run(prog, a, b, c, scratch_in=sin)
                same = seq.run(zero, a, b, c, scratch_in=sin)
                if want.state() != same.state():
                    print(f"  MISMATCH {name} (own-index leg) r{r} step "
                          f"{step:+d} strict={strict}: the model's stepped "
                          f"load is not its unstepped one")
                    R["bad"] += 1
                try:
                    got = run_in_c_ex(lib, dev, prog, a, b, c, sin)
                except RuntimeError as e:
                    print(f"  MISMATCH {name} (own-index leg) r{r} step "
                          f"{step:+d}: libcft refuses what the model runs: "
                          f"{e}")
                    R["bad"] += 1
                    continue
                if got != (want.deposits, want.counts, want.flags,
                           want.status, want.scratch_out):
                    print(f"  MISMATCH {name} (own-index leg) r{r} step "
                          f"{step:+d} strict={strict} n={n}: libcft and "
                          f"the model differ")
                    R["bad"] += 1
                    continue
                R["own_index"] += 1
                if strict and want.status & seq.STATUS_SCRATCH_RANGE:
                    R["own_index_range"] += 1


def sf_one(fmt):
    """1.0's bits in `fmt`: an index no depth reaches, and a float."""
    return seq.sf.one_bits(fmt)


def rev8_corpus(lib, dev, fmt, name, args, R):
    """The sixth corpus, for one format. Mutates the counters in R.

    Three kinds of program, from their own seed so the five corpora above
    draw what they always drew:
    * the generator with its revision-8 arm - augadd, augerr, their
      recommended pair and stepped STX/LDX - over random operands;
    * the same behind a directed prefix that runs the recommended pair on
      r0 and r1 and deposits both halves, with the lanes' operands drawn
      from augmented.py's stress families (ties from odd significands,
      cancellations in every sign, subnormal residuals, the overflow
      threshold), so the pair meets what 9.5 is about;
    * the same behind a directed WALK: two indices loaded from the
      scratch block near the depth's edge and near zero, stepped by
      loads and stores in a loop - so a strict program crosses the depth
      (and reports) and a -1 walk wraps at the register's width."""
    rev8_directed_refusals(lib, dev, fmt, name, R)
    rev8_own_index_leg(lib, dev, fmt, name, R)
    rng = random.Random(args.seed ^ (fmt.width * 7919) ^ 0x8E7D)
    checked = 0
    stress = vectors.augmented_pairs(fmt, 0)
    for trial in range(max(1, args.trials // 2)):
        insns, consts = seq.random_program(fmt, rng, extended=True,
                                           wide_regs=True, scratch=True,
                                           rev8=True)
        shape = rng.choice(["plain", "pair", "walk"])
        maxdep = rng.choice([0, 1, 2, 4])
        nsin = nsout = 0
        io = rng.random() < 0.5 or shape == "walk"
        if shape == "pair":
            insns = [seq.augerr(5, 0, 1), seq.augadd(6, 0, 1),
                     seq.deposit(6), seq.deposit(5)] + insns
            maxdep = max(maxdep, 2)
        elif shape == "walk":
            k = rng.randint(4, 12)
            # ...and the two index registers deposited after the loop, so
            # a step lost where SCRATCH_STRICT suppressed the access shows
            # in the output and not only in a later load (verifier-R3's
            # plant C4 went green at 60 trials without them).
            insns = [seq.ldl(7, 0), seq.ldl(9, 1), seq.repeat(k),
                     seq.ldx(8, 7, rng.choice([1, 1, -1, 3])),
                     seq.stx(8, 9, rng.choice([1, -1, -1, 5])),
                     seq.deposit(8), seq.endrep(),
                     seq.deposit(7), seq.deposit(9)] + insns
            maxdep = max(maxdep, k + 2)
            R["walks"] += 1
        if io:
            nsin = max(2 if shape == "walk" else 0, rng.choice([0, 1, 3]))
            nsout = rng.choice([0, 1, 4])
        strict = rng.random() < 0.4
        flags = ((seq.FLAG_SCRATCH_IO if io else 0)
                 | (seq.FLAG_SCRATCH_STRICT if strict else 0))
        kind = None
        if rng.random() < 0.25:
            insns, kind = corrupt_rev8(insns, rng)
        try:
            prog = seq.Program(fmt, insns, consts, maxdep, flags=flags,
                               n_scratch_in=nsin, n_scratch_out=nsout)
        except seq.ProgramError:
            bogus = seq.Program.__new__(seq.Program)
            bogus.fmt, bogus.insns = fmt, insns
            bogus.consts, bogus.max_deposits = consts, maxdep
            bogus.flags = flags
            bogus.n_scratch_in, bogus.n_scratch_out = nsin, nsout
            bogus._n_consts = len(consts)
            handle = ctypes.c_void_p()
            image = bogus.to_bytes()
            rc = lib.cft_program_load(dev, image, len(image),
                                      ctypes.byref(handle))
            if rc == CFT_OK:
                lib.cft_program_free(handle)
                print(f"  MISMATCH {name} (revision-8 corpus, {kind}): the "
                      f"model refuses this program and libcft loads it")
                R["bad"] += 1
            else:
                R["refused"] += 1
            continue
        if kind is not None:
            print(f"  NOTE {name} (revision-8 corpus): the model ACCEPTED a "
                  f"program corrupted as {kind}")
        prev = None
        for w in insns:
            d = seq.decode(w)
            if d["ctrl"] and d["op"] == seq.AUGADD:
                R["augadd"] += 1
                if prev is not None and prev["op"] == seq.AUGERR and \
                        (prev["ra"], prev["rb"]) == (d["ra"], d["rb"]):
                    R["pair"] += 1
            elif d["ctrl"] and d["op"] == seq.AUGERR:
                R["augerr"] += 1
            elif seq.index_step(d):
                R["ldx_step" if d["op"] == seq.LDX else "stx_step"] += 1
            prev = d if d["ctrl"] else None
        n = rng.choice([1, 2, 63, 64, 65, 100, 129])
        if n > 64:
            R["blocked"] += 1
        if shape == "pair":
            picks = [rng.choice(stress) for _ in range(n)]
            a = [x for x, _ in picks]
            b = [y for _, y in picks]
        else:
            a = seq.random_inputs(fmt, rng, n)
            b = seq.random_inputs(fmt, rng, n)
        c = seq.random_inputs(fmt, rng, n)
        sin = None
        if nsin:
            sin = seq.random_inputs(fmt, rng, n * nsin)
            if shape == "walk":
                for i in range(n):
                    sin[i * nsin] = rng.choice(_WALK_STARTS)
                    sin[i * nsin + 1] = rng.choice(_WALK_STARTS)
        want = seq.run(prog, a, b, c, scratch_in=sin)
        if strict:
            R["strict"] += 1
            if want.status & seq.STATUS_SCRATCH_RANGE:
                R["range"] += 1
        for bit, key in ((0x01, "inv"), (0x04, "ovf"), (0x08, "unf")):
            if want.flags & bit:
                R[key] += 1
        try:
            got_dep, got_counts, got_flags, got_status, got_so = \
                run_in_c_ex(lib, dev, prog, a, b, c, sin)
        except RuntimeError as e:
            print(f"  MISMATCH {name} (revision-8 corpus): the model runs "
                  f"this program and libcft refuses it: {e}")
            R["bad"] += 1
            continue
        if (got_dep != want.deposits or got_counts != want.counts
                or got_flags != want.flags or got_status != want.status
                or got_so != want.scratch_out):
            R["bad"] += 1
            if R["bad"] <= 3:
                print(f"  MISMATCH {name} (revision-8 corpus, {shape}) n={n} "
                      f"max_deposits={maxdep} in={nsin} out={nsout} "
                      f"strict={strict}")
                print(f"    program  {[hex(i) for i in insns]}")
                print(f"    flags    model 0x{want.flags:02x}  "
                      f"libcft 0x{got_flags:02x}")
                print(f"    status   model 0x{want.status:02x}  "
                      f"libcft 0x{got_status:02x}")
                for i, (w, g) in enumerate(zip(want.deposits, got_dep)):
                    if w != g:
                        print(f"    deposit[{i}] model 0x{w:x} "
                              f"libcft 0x{g:x}")
                        break
        checked += 1
        R["total"] += 1
    print(f"{name}: {checked} revision-8-corpus programs compared")


class _FakeServer:
    """A cft:// server that answers HELLO with a caps block whose
    seq_features word is the one it was given, answers BYE, and speaks
    nothing else.

    That is enough to hold cft_program_load on a remote handle: the
    client checks a program against the HELLO caps and sends no frame
    for a load (program.c keeps the image and ships it at the first run),
    so a refusal there is the client's own, made from the word alone -
    the path a remote handle to a tile takes. Any other frame means the
    load reached the wire, and is recorded so the check can say so."""

    CAPS_V3 = 76

    def __init__(self, features, backend=b"xrt", max_deposits=64):
        self.features = features
        self.backend = backend
        # 0 is what cft_caps calls unknown - what a server older than the
        # field publishes - and the one way a handle reaches
        # cft_program_load's own deposit ceiling (deposit_ceiling_remote).
        self.max_deposits = max_deposits
        self.other_ops = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    @staticmethod
    def _recv(conn, k):
        buf = b""
        while len(buf) < k:
            part = conn.recv(k - len(buf))
            if not part:
                return None
            buf += part
        return buf

    @staticmethod
    def _frame(abi, fid, op, payload):
        hdr = bytearray(struct.pack("<IHHIIHHIII", 0x52544643, 1, 1, abi,
                                    fid, op, 0, len(payload), 0, 0))
        crc = zlib.crc32(bytes(hdr) + payload) & 0xFFFFFFFF
        struct.pack_into("<I", hdr, 24, crc)
        return bytes(hdr) + payload

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                while True:
                    hdr = self._recv(conn, 32)
                    if hdr is None:
                        break
                    (_m, _p, _k, abi, fid, op, _s, length, _c,
                     _r) = struct.unpack("<IHHIIHHIII", hdr)
                    if length and self._recv(conn, length) is None:
                        break
                    if op == 0x0001:                         # HELLO
                        caps = (struct.pack("<6I", 0xF, 0xFF, 1, 0xA00, 1,
                                            abi)
                                + self.backend.ljust(32, b"\0")
                                + struct.pack("<5I", self.max_deposits,
                                              16384, 512, self.features,
                                              256))
                        assert len(caps) == self.CAPS_V3
                        conn.sendall(self._frame(abi, fid, op, caps))
                    elif op == 0x00FF:                       # BYE
                        conn.sendall(self._frame(abi, fid, op, b""))
                        break
                    else:
                        self.other_ops.append(op)
                        break

    def close(self):
        self.sock.close()


def rev8_remote_refusals(lib, R):
    """A device without the revision-8 bits refuses both forms BY NAME.

    The tile today publishes neither (CAPS2[11] and [12] read zero), and
    this desktop has no tile - so the device here is a remote handle to a
    fake server whose HELLO says what a round-2 tile's word says,
    0x7f1f: the refusal is made on the client, from the word, by the
    same check that refuses on an xclbin handle. Held both ways: each
    program is refused where the bit is clear, naming the instruction
    and the bit, and loads where the fake publishes it; a program that
    needs neither loads either way; no load reaches the wire."""
    tile_word = 0x7F1F
    cases = [
        ("augadd", [seq.augadd(3, 0, 1)], "CFT_SEQ_FEAT_AUGADD", "AUGADD",
         seq.FEAT_AUGADD),
        ("augerr", [seq.augerr(3, 0, 1)], "CFT_SEQ_FEAT_AUGADD", "AUGERR",
         seq.FEAT_AUGADD),
        ("stepped ldx", [seq.ldx(3, 4, -1)], "CFT_SEQ_FEAT_SCRATCH_STEP",
         "LDX with a post-step of -1", seq.FEAT_SCRATCH_STEP),
        ("stepped stx", [seq.stx(3, 4, 7)], "CFT_SEQ_FEAT_SCRATCH_STEP",
         "STX with a post-step of +7", seq.FEAT_SCRATCH_STEP),
        ("an unstepped ldx", [seq.ldx(3, 4, 0)], None, None, 0),
    ]
    for word, published in ((tile_word, False),
                            (tile_word | seq.FEAT_AUGADD
                             | seq.FEAT_SCRATCH_STEP, True)):
        srv = _FakeServer(word)
        dev = ctypes.c_void_p()
        url = f"cft://127.0.0.1:{srv.port}".encode()
        st = lib.cft_open(url, 0, ctypes.byref(dev))
        if st != CFT_OK:
            print(f"  MISMATCH (revision-8 remote leg): cft_open of the fake "
                  f"server failed: {lib.cft_last_error().decode()}")
            R["bad"] += 1
            srv.close()
            continue
        try:
            for label, body, macro, instr, bit in cases:
                prog = seq.Program(FORMATS["fp64"], body + [seq.halt()],
                                   max_deposits=0)
                assert seq.features_rev8(prog.insns) == bit
                image = prog.to_bytes()
                handle = ctypes.c_void_p()
                rc = lib.cft_program_load(dev, image, len(image),
                                          ctypes.byref(handle))
                # cft_last_error is only this call's after a refusal: a
                # load that succeeds left the previous sentence there
                # (verifier-R3), so it is read for a refusal alone. Since
                # 2026-09-30 a load clears the library's own slot on entry,
                # and a successful one leaves it empty - but a device
                # backend's older message still shows through an empty
                # slot, so the rule stands.
                msg = (lib.cft_last_error().decode() if rc != CFT_OK
                       else "(loaded; no error)")
                if rc == CFT_OK:
                    lib.cft_program_free(handle)
                must_refuse = bool(bit) and not published
                if must_refuse:
                    named = (rc == CFT_ERR_UNSUPPORTED and macro in msg
                             and instr in msg)
                    if not named:
                        print(f"  MISMATCH (revision-8 remote leg): {label} "
                              f"on a server publishing 0x{word:x} gave rc "
                              f"{rc} and {msg!r} - wanted "
                              f"CFT_ERR_UNSUPPORTED naming {instr} and "
                              f"{macro}")
                        R["bad"] += 1
                    else:
                        R["remote_refused"] += 1
                elif rc != CFT_OK:
                    print(f"  MISMATCH (revision-8 remote leg): {label} on a "
                          f"server publishing 0x{word:x} was refused: rc "
                          f"{rc}, {msg!r}")
                    R["bad"] += 1
                else:
                    R["remote_loaded"] += 1
        finally:
            lib.cft_close(dev)
            srv.close()
        if srv.other_ops:
            print(f"  MISMATCH (revision-8 remote leg): a load reached the "
                  f"wire, ops {[hex(o) for o in srv.other_ops]}")
            R["bad"] += 1
    print(f"revision-8 remote leg: {R['remote_refused']} refused by name on a "
          f"server without the bits, {R['remote_loaded']} loaded where "
          f"published or not needed")


def deposit_ceiling_remote(lib):
    """cft_program_load's own ceiling on max_deposits, by name - the one
    refusal of the load path that a software handle cannot reach
    (the fixes round's Q5, 2026-09-30).

    A handle that publishes a deposit cap refuses a program past it by
    name, first; the library's ceiling of 2^20 is reached only where a
    device published no cap (0, unknown - a server older than the field)
    or one above it. So the handle here is a remote one to a fake server
    whose HELLO publishes max_deposits 0. The load is the client's own,
    made from that word, and no load reaches the wire.

    Before each load a failing call plants a DEVICE BACKEND's sentence: a
    program run, which the fake server does not answer. That is the case
    the entry clear alone cannot cover - cft_last_error() falls through an
    empty library slot to the remote backend's message - so the refusal
    must carry its own sentence, or it shows the remote's. Held three
    ways: 2^20 loads, 2^20 + 1 and 2^32 - 1 are CFT_ERR_INVALID_ARGUMENT
    naming both numbers and the unknown cap, and the golden model refuses
    what the C refuses and loads what it loads. -> failures"""
    bad = 0
    srv = _FakeServer(0x7F1F, max_deposits=0)
    dev = ctypes.c_void_p()
    url = f"cft://127.0.0.1:{srv.port}".encode()
    if lib.cft_open(url, 0, ctypes.byref(dev)) != CFT_OK:
        print(f"  MISMATCH (deposit-ceiling leg): cft_open of the fake "
              f"server failed: {lib.cft_last_error().decode()}")
        srv.close()
        return 1
    fmt = FORMATS["fp64"]
    plant = ctypes.c_void_p()
    a = ctypes.create_string_buffer(fmt.width // 8)
    good = seq.Program(fmt, [seq.halt()], max_deposits=0).to_bytes()
    try:
        if lib.cft_program_load(dev, good, len(good),
                                ctypes.byref(plant)) != CFT_OK:
            print(f"  MISMATCH (deposit-ceiling leg): a one-HALT program "
                  f"did not load: {lib.cft_last_error().decode()}")
            return 1
        for maxdep, loads in ((1 << 20, True), ((1 << 20) + 1, False),
                              (0xFFFFFFFF, False)):
            image = bytearray(good)
            struct.pack_into("<I", image, 16, maxdep)
            image = bytes(image)
            rc = lib.cft_program_run(plant, a, None, None, None, None, 1,
                                     None, None)
            planted = lib.cft_last_error().decode()
            if rc == CFT_OK or not planted:
                print(f"  MISMATCH (deposit-ceiling leg): the run meant to "
                      f"plant the remote backend's sentence gave rc {rc} "
                      f"and {planted!r}")
                bad += 1
            handle = ctypes.c_void_p()
            st = lib.cft_program_load(dev, image, len(image),
                                      ctypes.byref(handle))
            msg = lib.cft_last_error().decode()
            if st == CFT_OK:
                lib.cft_program_free(handle)
            try:
                seq.Program.from_bytes(image)
                golden_loads = True
            except seq.ProgramError:
                golden_loads = False
            if golden_loads != loads:
                print(f"  MISMATCH (deposit-ceiling leg): the golden model "
                      f"{'loads' if golden_loads else 'refuses'} "
                      f"max_deposits {maxdep}")
                bad += 1
            if loads:
                if st != CFT_OK:
                    print(f"  MISMATCH (deposit-ceiling leg): max_deposits "
                          f"{maxdep} is at the ceiling and was refused: rc "
                          f"{st}, {msg!r}")
                    bad += 1
                continue
            want = (f"max_deposits is {maxdep}, past {1 << 20}",
                    "cft_caps.max_deposits, is 0 (unknown)")
            if (st != CFT_ERR_INVALID_ARGUMENT or planted and planted in msg
                    or not all(w in msg for w in want)):
                print(f"  MISMATCH (deposit-ceiling leg): max_deposits "
                      f"{maxdep} on a handle that publishes no cap gave rc "
                      f"{st} and {msg!r} - wanted "
                      f"CFT_ERR_INVALID_ARGUMENT ({CFT_ERR_INVALID_ARGUMENT}) "
                      f"saying {want}, and not the remote backend's "
                      f"{planted!r}")
                bad += 1
        # A run ships its image first (PROG_LOAD, 0x0020), and the fake
        # server answers nothing but HELLO and BYE - so the planting run
        # is the one frame it may see. cft_program_load sends none.
        stray = [op for op in srv.other_ops if op != 0x0020]
        if stray:
            print(f"  MISMATCH (deposit-ceiling leg): something other than "
                  f"the planting run reached the wire: "
                  f"{[hex(o) for o in stray]}")
            bad += 1
    finally:
        if plant:
            lib.cft_program_free(plant)
        lib.cft_close(dev)
        srv.close()
    print(f"deposit-ceiling leg: max_deposits 2^20, 2^20 + 1 and 2^32 - 1 "
          f"on a handle publishing no deposit cap, each after the remote "
          f"backend's own sentence was planted, against the golden model: "
          f"{bad} disagreements")
    return bad


# ---- the seventh corpus: flag control (R24) and per-lane flags (R23) -------
#
# The step-6 round's revision-8 work, ABI 0.17: `quiet`, `endquiet` and
# `raise`, and the byte a lane a run may ask for. Random programs with the
# generator's flag-control arm (and the scratch and revision-8 arms beside
# it) run through both executors with the per-lane block asked for, under
# a mask a third of the time; FLAGS, STATUS - the mark among it - every
# deposit, count, scratch-out slot and lane byte must agree, and a masked
# lane's byte must be the caller's pattern on the C side. The bracket rules
# and every field the three do not read are refused by both, directed and
# corrupted in; and a remote handle to a server publishing a revision-7
# tile's word refuses each code at load, and a run asking for the block,
# by name and before any frame.

def run_in_c_flags(lib, dev, prog, a, b, c, n, scratch_in, keep=None,
                   fill=0xEE):
    """-> (deposits, counts, flags, status, scratch_out, lane_flags)
    through cft_program_run_ex with ABI 0.17's lane_flags asked for, and
    ABI 0.14's mask where `keep` is given; the library's refusal as a
    RuntimeError. The block is filled with `fill` first, so a masked
    lane's byte - the caller's - is told from one written 0."""
    fmt = prog.fmt
    esz = fmt.width // 8
    image = prog.to_bytes()
    nsin, nsout = prog.n_scratch_in, prog.n_scratch_out

    handle = ctypes.c_void_p()
    st = lib.cft_program_load(dev, image, len(image), ctypes.byref(handle))
    if st != CFT_OK:
        raise RuntimeError(f"cft_program_load: "
                           f"{lib.cft_last_error().decode()}")
    try:
        def pack(vals):
            return ctypes.create_string_buffer(
                b"".join(v.to_bytes(esz, "little") for v in vals),
                max(1, len(vals) * esz))

        buf_a, buf_b, buf_c = pack(a), pack(b), pack(c)
        ndep = n * prog.max_deposits
        buf_d = ctypes.create_string_buffer(max(1, ndep * esz))
        counts = (ctypes.c_uint32 * max(1, n))()
        flags = ctypes.c_uint32(0)
        bus = ctypes.c_uint32(0)
        buf_si = pack(scratch_in) if nsin else None
        buf_so = (ctypes.create_string_buffer(max(1, n * nsout * esz))
                  if nsout else None)
        buf_lf = ctypes.create_string_buffer(bytes([fill]) * max(1, n),
                                             max(1, n))
        args = RunArgs()
        args.struct_size = ctypes.sizeof(RunArgs)
        args.a = ctypes.cast(buf_a, ctypes.c_void_p)
        args.b = ctypes.cast(buf_b, ctypes.c_void_p)
        args.c = ctypes.cast(buf_c, ctypes.c_void_p)
        args.n = n
        args.scratch_in = (ctypes.cast(buf_si, ctypes.c_void_p)
                           if buf_si is not None else None)
        args.scratch_in_bytes = (n * nsin * esz) if nsin else 0
        args.scratch_out = (ctypes.cast(buf_so, ctypes.c_void_p)
                            if buf_so is not None else None)
        args.scratch_out_bytes = n * nsout * esz
        args.deposits = ctypes.cast(buf_d, ctypes.c_void_p)
        args.counts = counts
        args.flags_out = ctypes.pointer(flags)
        args.bus_out = ctypes.pointer(bus)
        if keep is not None:
            mbytes = (n + 7) // 8
            raw = bytearray(mbytes)
            for i, k in enumerate(keep):
                if k:
                    raw[i >> 3] |= 1 << (i & 7)
            buf_m = ctypes.create_string_buffer(bytes(raw), max(1, mbytes))
            args.lane_mask = ctypes.cast(buf_m, ctypes.c_void_p)
            args.lane_mask_bytes = mbytes
        args.lane_flags = ctypes.cast(buf_lf, ctypes.c_void_p)
        args.lane_flags_bytes = n
        st = lib.cft_program_run_ex(handle, ctypes.byref(args))
        if st != CFT_OK:
            raise RuntimeError(f"cft_program_run_ex: "
                               f"{lib.cft_last_error().decode()}")
        rawd = buf_d.raw
        deposits = [int.from_bytes(rawd[i * esz:(i + 1) * esz], "little")
                    for i in range(ndep)]
        sout = []
        if nsout:
            rs = buf_so.raw
            sout = [int.from_bytes(rs[i * esz:(i + 1) * esz], "little")
                    for i in range(n * nsout)]
        return (deposits, list(counts)[:n], flags.value, bus.value, sout,
                list(buf_lf.raw[:n]))
    finally:
        lib.cft_program_free(handle)


def flags_refusal_programs():
    """Every R24 refusal, once, as (label, insns): the bracket rules, and
    each field the three codes do not read."""
    q, e, h = seq.quiet(), seq.endquiet(), seq.halt()
    r, x = seq.repeat(2), seq.endrep()
    out = [("endquiet with none open", [e, h]),
           ("endquiet inside a loop around a region", [q, r, e, x, h]),
           ("endrep around an open region", [r, q, x, e, h]),
           ("five nested regions", [q] * 5 + [e] * 5 + [h]),
           ("halt inside a region", [q, h, e, h]),
           ("a region open at the end", [q, h])]
    for code in (seq.QUIET, seq.ENDQUIET, seq.RAISE):
        pre = [q] if code == seq.ENDQUIET else []
        post = [e] if code == seq.QUIET else []
        base = dict(ra=3 if code == seq.RAISE else 0, ctrl=True)
        extra = [("rd", dict(rd=1)), ("rb", dict(rb=2)), ("rc", dict(rc=3)),
                 ("rnd", dict(rnd=1)), ("ka", dict(ka=True)),
                 ("kx", dict(kx=True))]
        if code != seq.RAISE:
            extra.append(("ra", dict(ra=1)))
        extra += [(f"imm[{b}]", dict(imm=1 << b))
                  for b in (0, 11, 23, 24, 26, 27, 31)]
        for label, f in extra:
            out.append((f"{seq.CTRL_NAMES[code]} {label}",
                        pre + [seq.encode(code, **{**base, **f})] + post
                        + [h]))
    return out


def _refused_by_c(lib, dev, fmt, insns, maxdep=0):
    """Whether libcft refuses an image of `insns` the model could not
    build - serialised past the constructor, as the first corpus does."""
    bogus = seq.Program.__new__(seq.Program)
    bogus.fmt, bogus.insns = fmt, insns
    bogus.consts, bogus.max_deposits = [], maxdep
    bogus.flags = 0
    bogus.n_scratch_in = bogus.n_scratch_out = 0
    bogus._n_consts = 0
    image = bogus.to_bytes()
    handle = ctypes.c_void_p()
    rc = lib.cft_program_load(dev, image, len(image), ctypes.byref(handle))
    if rc == CFT_OK:
        lib.cft_program_free(handle)
        return False
    return True


def flags_corpus(lib, dev, fmt, name, args, F):
    """The seventh corpus, for one format. Mutates the counters in F."""
    for label, insns in flags_refusal_programs():
        try:
            seq.Program(fmt, insns, max_deposits=0)
            model_refused = False
        except seq.ProgramError:
            model_refused = True
        c_refused = _refused_by_c(lib, dev, fmt, insns)
        if not (model_refused and c_refused):
            print(f"  MISMATCH {name} (flag-control refusal): {label}: model "
                  f"{'refuses' if model_refused else 'loads'}, libcft "
                  f"{'refuses' if c_refused else 'loads'}")
            F["bad"] += 1
        else:
            F["directed"] += 1

    rng = random.Random((args.seed * 2654435761 + fmt.width) & 0xFFFFFFFF
                        ^ 0x24F1A6)
    trials = max(1, args.trials // 4)
    for _trial in range(trials):
        insns, consts = seq.random_program(fmt, rng, scratch=True,
                                           wide_regs=True, rev8=True,
                                           flags=True)
        strict = rng.random() < 0.4
        pflags = seq.FLAG_SCRATCH_IO | (seq.FLAG_SCRATCH_STRICT
                                        if strict else 0)
        maxdep = rng.choice([0, 1, 2])
        if rng.random() < 0.15:
            # one R24 word broken, at a random place: both must refuse
            what = rng.randrange(3)
            if what == 0:
                word = seq.endquiet()              # an unbalanced close
            elif what == 1:
                word = seq.quiet()                 # an unclosed open
            else:
                word = seq.encode(seq.RAISE, ra=1, rb=rng.randrange(1, 16),
                                  ctrl=True)       # a field it does not read
            insns = list(insns)
            insns.insert(rng.randrange(len(insns)), word)
            try:
                seq.Program(fmt, insns, consts, maxdep, flags=pflags,
                            n_scratch_out=2)
            except seq.ProgramError:
                bogus = seq.Program.__new__(seq.Program)
                bogus.fmt, bogus.insns = fmt, insns
                bogus.consts, bogus.max_deposits = consts, maxdep
                bogus.flags = pflags
                bogus.n_scratch_in, bogus.n_scratch_out = 0, 2
                bogus._n_consts = len(consts)
                image = bogus.to_bytes()
                handle = ctypes.c_void_p()
                rc = lib.cft_program_load(dev, image, len(image),
                                          ctypes.byref(handle))
                if rc == CFT_OK:
                    lib.cft_program_free(handle)
                    print(f"  MISMATCH {name} (flag-control corpus): the "
                          f"model refuses a broken program and libcft "
                          f"loads it")
                    F["bad"] += 1
                else:
                    F["refused"] += 1
                continue
            # an inserted word that happened to stay legal runs as any
            # other program below
        prog = seq.Program(fmt, insns, consts, maxdep, flags=pflags,
                           n_scratch_out=2)
        qd = 0
        for w in insns:
            d = seq.decode(w)
            if not d["ctrl"]:
                continue
            if d["op"] == seq.QUIET:
                qd += 1
                F["quiet"] += 1
                F["nested"] += qd > 1
            elif d["op"] == seq.ENDQUIET:
                qd -= 1
            elif d["op"] == seq.RAISE:
                F["raise_quiet" if qd else "raise_loud"] += 1
        n = rng.choice([1, 2, 63, 64, 65, 100, 129])
        a = seq.random_inputs(fmt, rng, n)
        b = seq.random_inputs(fmt, rng, n)
        c = seq.random_inputs(fmt, rng, n)
        keep = None
        if rng.random() < 0.3:
            keep = [rng.random() < 0.7 for _ in range(n)]
        if n > 64:
            F["blocked"] += 1
        want = seq.run(prog, a, b, c, lane_mask=keep)
        try:
            dep, counts, fl, st, sout, lf = run_in_c_flags(
                lib, dev, prog, a, b, c, n, None, keep)
        except RuntimeError as exc:
            print(f"  MISMATCH {name} (flag-control corpus): libcft refused "
                  f"a program the model ran: {exc}")
            F["bad"] += 1
            continue
        owned = [i for i in range(n) if keep is None or keep[i]]
        esz_dep = prog.max_deposits
        same = (fl == want.flags and st == want.status)
        for i in owned:
            if (lf[i] != want.lane_flags[i]
                    or counts[i] != want.counts[i]
                    or dep[i * esz_dep:(i + 1) * esz_dep]
                    != want.deposits[i * esz_dep:(i + 1) * esz_dep]
                    or sout[2 * i:2 * i + 2] != want.scratch_out[2 * i:2 * i + 2]):
                same = False
        for i in range(n):
            if keep is not None and not keep[i] and lf[i] != 0xEE:
                same = False                  # a masked lane's byte written
        o = 0
        for i in owned:
            o |= want.lane_flags[i]
        if (o & 0x1F) != want.flags or ((o >> 1) & 0x70) != (want.status
                                                             & 0x70):
            same = False                      # R23's identities, the model's
        if not same:
            F["bad"] += 1
            if F["bad"] <= 3:
                print(f"  MISMATCH {name} n={n} (flag-control corpus)")
                print(f"    program  {[hex(i) for i in insns]}")
                print(f"    flags    model 0x{want.flags:02x}  libcft "
                      f"0x{fl:02x}; status model 0x{want.status:02x}  "
                      f"libcft 0x{st:02x}")
                print(f"    bytes    model {[hex(v) for v in want.lane_flags[:8]]}")
                print(f"             libcft {[hex(v) for v in lf[:8]]}")
        F["total"] += 1
        F["lanes"] += len(owned)
        F["marked"] += bool(want.status & seq.STATUS_MARKED)
        F["masked"] += keep is not None and len(owned) < n
        F["strict"] += strict
        F["range"] += bool(want.status & seq.STATUS_SCRATCH_RANGE)
        F["overflow"] += bool(want.status & seq.STATUS_DEPOSIT_OVERFLOW)


def flags_remote_refusals(lib, F):
    """A device without R24's or R23's bit refuses each BY NAME.

    No tile publishes either (CAPS2[13] and [14] read zero), so the device
    is a remote handle to the fake server of rev8_remote_refusals, whose
    HELLO publishes a revision-7 tile's word, 0x7f1f. Each of the three
    codes is refused at load naming the instruction and
    CFT_SEQ_FEAT_FLAG_CONTROL, and loads where the word publishes the bit;
    a program that needs neither loads, and a RUN of it that asks for the
    per-lane flags is refused naming CFT_SEQ_FEAT_LANE_FLAGS - on the
    client, before any frame, which the server's record holds."""
    tile_word = 0x7F1F
    cases = [("quiet", [seq.quiet(), seq.endquiet()], "QUIET"),
             ("endquiet", [seq.quiet(), seq.endquiet()], "QUIET"),
             ("raise", [seq.raise_(3)], "RAISE")]
    fmt = FORMATS["fp64"]
    for word, published in ((tile_word, False),
                            (tile_word | seq.FEAT_FLAG_CONTROL, True)):
        srv = _FakeServer(word)
        dev = ctypes.c_void_p()
        url = f"cft://127.0.0.1:{srv.port}".encode()
        st = lib.cft_open(url, 0, ctypes.byref(dev))
        if st != CFT_OK:
            print(f"  MISMATCH (flag-control remote leg): cft_open of the "
                  f"fake server failed: {lib.cft_last_error().decode()}")
            F["bad"] += 1
            srv.close()
            continue
        try:
            for label, body, instr in cases:
                prog = seq.Program(fmt, body + [seq.halt()], max_deposits=0)
                image = prog.to_bytes()
                handle = ctypes.c_void_p()
                rc = lib.cft_program_load(dev, image, len(image),
                                          ctypes.byref(handle))
                msg = (lib.cft_last_error().decode() if rc != CFT_OK
                       else "(loaded)")
                if rc == CFT_OK:
                    lib.cft_program_free(handle)
                if not published:
                    if (rc == CFT_ERR_UNSUPPORTED and instr in msg
                            and "CFT_SEQ_FEAT_FLAG_CONTROL" in msg):
                        F["remote_refused"] += 1
                    else:
                        print(f"  MISMATCH (flag-control remote leg): "
                              f"{label} on 0x{word:x}: rc {rc}, {msg!r}")
                        F["bad"] += 1
                elif rc != CFT_OK:
                    print(f"  MISMATCH (flag-control remote leg): {label} "
                          f"refused where the bit is published: {msg!r}")
                    F["bad"] += 1
                else:
                    F["remote_loaded"] += 1
            # the block, asked of a run on a server whose word lacks it
            if not published:
                prog = seq.Program(fmt, [seq.halt()], max_deposits=0)
                try:
                    run_in_c_flags(lib, dev, prog, [0, 0], [0, 0], [0, 0],
                                   2, None)
                    print("  MISMATCH (flag-control remote leg): a run "
                          "asking for the per-lane flags ran on a server "
                          "without the bit")
                    F["bad"] += 1
                except RuntimeError as exc:
                    if "CFT_SEQ_FEAT_LANE_FLAGS" in str(exc):
                        F["remote_refused"] += 1
                    else:
                        print(f"  MISMATCH (flag-control remote leg): the "
                              f"block was refused without its name: {exc}")
                        F["bad"] += 1
        finally:
            lib.cft_close(dev)
            srv.close()
        if srv.other_ops:
            print(f"  MISMATCH (flag-control remote leg): a load or run "
                  f"reached the wire, ops {[hex(o) for o in srv.other_ops]}")
            F["bad"] += 1
    print(f"flag-control remote leg: {F['remote_refused']} refused by name on "
          f"a server without the bits, {F['remote_loaded']} loaded where "
          f"published")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--formats", nargs="+", default=["fp32", "fp64"],
                    choices=list(FORMATS))
    ap.add_argument("--trials", type=int, default=400)
    ap.add_argument("--seed", type=int, default=17)
    args = ap.parse_args()

    lib = load_library()
    dev = ctypes.c_void_p()
    st = lib.cft_open(None, 0, ctypes.byref(dev))
    if st != CFT_OK:
        raise SystemExit(f"cft_open: {lib.cft_strerror(st).decode()}")

    total = bad = refused_both = 0
    blocked = 0
    extended = saw_kx = saw_imul = saw_wide = 0
    S = dict(total=0, refused=0, bad=0, stl=0, ldl=0, stx=0, ldx=0,
             io=0, kx9=0, blocked=0, strict=0, range=0)
    # The fourth corpus keeps its own counters, so a form it fails to
    # reach is named as the indexed corpus's and not hidden in the
    # scratch corpus's totals (R16, 2026-09-15).
    X = dict(total=0, bad=0, blocked=0, tables=0, none=0, oob=0,
             identity=0, permuted=0)
    # ...and the fifth's, for the same reason: a mask shape this corpus
    # never drew must be visible as a zero here and not hidden in a
    # total (R17, 2026-09-15).
    M = dict(total=0, bad=0, blocked=0, kept=0, masked_lanes=0,
             ones=0, zeros=0, sparse=0, dense=0, allones=0, holed=0)
    # ...and the sixth's (revision 8, proposed 2026-09-29).
    R = dict(total=0, refused=0, bad=0, blocked=0, augadd=0, augerr=0,
             pair=0, ldx_step=0, stx_step=0, walks=0, strict=0, range=0,
             inv=0, ovf=0, unf=0, remote_refused=0, remote_loaded=0,
             directed=0, own_index=0, own_index_range=0)
    # ...and the seventh's (R24 and R23, the step-6 round, ABI 0.17)
    F = dict(total=0, refused=0, bad=0, blocked=0, directed=0, quiet=0,
             nested=0, raise_quiet=0, raise_loud=0, marked=0, masked=0,
             lanes=0, strict=0, range=0, overflow=0, remote_refused=0,
             remote_loaded=0)
    try:
        for name in args.formats:
            fmt = FORMATS[name]
            rng = random.Random(args.seed ^ (fmt.width * 7919))
            checked = 0
            for trial in range(args.trials):
                # Alternate the two corpora rather than mixing them, so
                # a run's counts say plainly how much of each was
                # compared. The old arm draws exactly what it always
                # drew for a given seed.
                ext = (trial % 2) == 1
                insns, consts = seq.random_program(fmt, rng, extended=ext)
                if ext:
                    extended += 1
                    for w in insns:
                        dd = seq.decode(w)
                        if dd["ctrl"]:
                            continue
                        if dd["op"] == seq.sf.OP_IMUL:
                            saw_imul += 1
                        if dd["kx"]:
                            saw_kx += 1
                            for idx, is_k in seq.sources(dd):
                                if is_k and idx >= seq.KADDR_PLAIN:
                                    saw_wide += 1
                maxdep = rng.choice([0, 1, 2, 4])
                if rng.random() < 0.3:
                    insns, _kind = corrupt(insns, rng)
                try:
                    prog = seq.Program(fmt, insns, consts, maxdep)
                except seq.ProgramError:
                    # The model refused it; the C loader must too - so
                    # the refused program still has to be serialised,
                    # which means building the object WITHOUT the
                    # constructor that just rejected it.
                    #
                    # Every field to_bytes() reads is set here by name,
                    # including the two the constructor computes:
                    # `flags` and the private `_n_consts` behind the
                    # n_consts property. Revision 2 added both and this
                    # bypass was not updated, so the stage had been
                    # failing with an AttributeError before it compared
                    # anything (found 2026-09-08 evening).
                    bogus = seq.Program.__new__(seq.Program)
                    bogus.fmt, bogus.insns = fmt, insns
                    bogus.consts, bogus.max_deposits = consts, maxdep
                    bogus.flags = 0
                    # ...and the two scratch counts revision 3's
                    # model reads through scratch_io_word, which
                    # the same bypass missed a second time when the
                    # two halves merged (2026-09-08, evening)
                    bogus.n_scratch_in = bogus.n_scratch_out = 0
                    bogus._n_consts = len(consts)
                    handle = ctypes.c_void_p()
                    image = bogus.to_bytes()
                    rc = lib.cft_program_load(dev, image, len(image),
                                              ctypes.byref(handle))
                    if rc == CFT_OK:
                        lib.cft_program_free(handle)
                        print(f"  MISMATCH {name}: the model refuses this "
                              f"program and libcft loads it")
                        bad += 1
                    else:
                        refused_both += 1
                    continue

                # a spread either side of the 64-lane block, so the C
                # side's blocking is exercised rather than skipped
                n = rng.choice([1, 2, 63, 64, 65, 100, 129])
                a = seq.random_inputs(fmt, rng, n)
                b = seq.random_inputs(fmt, rng, n)
                c = seq.random_inputs(fmt, rng, n)
                if n > 64:
                    blocked += 1

                want = seq.run(prog, a, b, c)
                got_dep, got_counts, got_flags, got_status = \
                    run_in_c(lib, dev, prog, a, b, c)

                if (got_dep != want.deposits or got_counts != want.counts
                        or got_flags != want.flags
                        or got_status != want.status):
                    bad += 1
                    if bad <= 3:
                        print(f"  MISMATCH {name} n={n} "
                              f"max_deposits={maxdep}")
                        print(f"    program  {[hex(i) for i in insns]}")
                        print(f"    flags    model 0x{want.flags:02x}  "
                              f"libcft 0x{got_flags:02x}")
                        print(f"    status   model 0x{want.status:02x}  "
                              f"libcft 0x{got_status:02x}")
                        print(f"    counts   model {want.counts}")
                        print(f"             libcft {got_counts}")
                        for i, (w, g) in enumerate(zip(want.deposits,
                                                       got_dep)):
                            if w != g:
                                print(f"    deposit[{i}] model 0x{w:x} "
                                      f"libcft 0x{g:x}")
                                break
                checked += 1
                total += 1
            print(f"{name}: {checked} programs compared")
            scratch_corpus(lib, dev, fmt, name, args, S)
            indexed_corpus(lib, dev, fmt, name, args, X)
            masked_corpus(lib, dev, fmt, name, args, M)
            rev8_corpus(lib, dev, fmt, name, args, R)
            flags_corpus(lib, dev, fmt, name, args, F)
    finally:
        lib.cft_close(dev)
    rev8_remote_refusals(lib, R)
    flags_remote_refusals(lib, F)
    ceiling_bad = deposit_ceiling_remote(lib)

    print(f"\n{total} programs run through both implementations, "
          f"{refused_both} refused by both")
    print(f"{blocked} of them crossed libcft's 64-lane block boundary")
    print(f"{extended} programs drawn from the extended corpus: "
          f"{saw_imul} IMUL instructions, {saw_kx} indexed-constant "
          f"instructions, {saw_wide} constant indices above "
          f"{seq.KADDR_PLAIN - 1}")
    print(f"{S['total']} programs from the scratch corpus run through "
          f"both, {S['refused']} refused by both, {S['blocked']} across "
          f"the block boundary: {S['stl']} STL, {S['ldl']} LDL, "
          f"{S['stx']} STX, {S['ldx']} LDX, {S['io']} with a scratch "
          f"block declared, {S['kx9']} constant indices at or past "
          f"256, {S['strict']} with SCRATCH_STRICT of which "
          f"{S['range']} reported an out-of-range index")
    print(f"{X['total']} programs from the indexed corpus run through "
          f"both, {X['blocked']} across the block boundary: {X['tables']} "
          f"tables with {X['none']} CFT_IDX_NONE entries among them, "
          f"{X['oob']} indices at the source's length refused by both, "
          f"{X['identity']} identity-table controls and {X['permuted']} "
          f"permuted ones")
    print(f"{M['total']} programs from the masked corpus run through "
          f"both, {M['blocked']} across the block boundary: "
          f"{M['kept']} lanes run and {M['masked_lanes']} masked, "
          f"{M['ones']} all-ones masks, {M['zeros']} all-zero, "
          f"{M['sparse']} sparse and {M['dense']} dense, "
          f"{M['allones']} all-ones controls and {M['holed']} holed ones")
    print(f"{R['total']} programs from the revision-8 corpus run through "
          f"both, {R['refused']} refused by both, {R['blocked']} across the "
          f"block boundary: {R['augadd']} augadd, {R['augerr']} augerr, "
          f"{R['pair']} recommended pairs, {R['ldx_step']} stepped LDX, "
          f"{R['stx_step']} stepped STX, {R['walks']} directed walks, "
          f"{R['strict']} strict of which {R['range']} reported an "
          f"out-of-range index; runs raising invalid {R['inv']}, overflow "
          f"{R['ovf']}, underflow {R['unf']}; {R['directed']} directed "
          f"refusals refused by both; {R['own_index']} own-index loads "
          f"(ldx rX, rX, step) equal in both and to their unstepped "
          f"twins, {R['own_index_range']} of them strict and reporting")
    print(f"{F['total']} programs from the flag-control corpus run through "
          f"both with the per-lane block asked for, {F['refused']} broken ones "
          f"refused by both, {F['blocked']} across the block boundary: "
          f"{F['quiet']} quiet regions ({F['nested']} nested), "
          f"{F['raise_loud']} raises outside a region and "
          f"{F['raise_quiet']} inside one, {F['marked']} runs with a lane "
          f"marked, {F['masked']} masked runs, {F['lanes']} lane bytes "
          f"compared, {F['strict']} strict runs of which {F['range']} "
          f"reported, {F['overflow']} with a deposit overflow; "
          f"{F['directed']} directed refusals refused by both")
    bad += S["bad"] + X["bad"] + M["bad"] + R["bad"] + ceiling_bad + F["bad"]
    if F["total"] and not all(F[k] for k in (
            "refused", "blocked", "directed", "quiet", "nested",
            "raise_quiet", "raise_loud", "marked", "masked", "range",
            "overflow", "remote_refused", "remote_loaded")):
        print("THE FLAG-CONTROL CORPUS DID NOT REACH EVERY FORM - a counter "
              "above is zero, so a region, a raise, the mark, a mask, a "
              "report or the remote refusal went uncompared")
        return 1
    if R["total"] and not all(R[k] for k in (
            "refused", "blocked", "augadd", "augerr", "pair", "ldx_step",
            "stx_step", "walks", "strict", "range", "inv", "ovf", "unf",
            "remote_refused", "remote_loaded", "directed",
            "own_index", "own_index_range")):
        print("THE REVISION-8 CORPUS DID NOT REACH EVERY FORM - a counter "
              "above is zero, so a form, a flag class, the strict report "
              "or the remote refusal went uncompared")
        return 1
    if M["total"] and not (M["kept"] and M["masked_lanes"] and M["zeros"]
                           and M["allones"] and M["holed"]):
        print("THE MASKED CORPUS DID NOT REACH EVERY FORM - no lane was "
              "masked, no lane ran, no all-zero mask was drawn, or no "
              "all-ones/holed control pair, which would mean R17 was not "
              "actually compared")
        return 1
    if X["total"] and not (X["tables"] and X["none"] and X["oob"]
                           and X["identity"] and X["permuted"]):
        print("THE INDEXED CORPUS DID NOT REACH EVERY FORM - no table, "
              "no CFT_IDX_NONE entry, no index refused at the source's "
              "length, or no identity/permuted control pair, which "
              "would mean R16 was not actually compared")
        return 1
    if S["total"] and not (S["stl"] and S["ldl"] and S["stx"]
                           and S["ldx"] and S["io"] and S["kx9"]
                           and S["refused"] and S["strict"]
                           and S["range"]):
        print("THE SCRATCH CORPUS DID NOT REACH EVERY FORM - a code, "
              "the block or the ninth bit went uncompared, no refusal "
              "was exercised, or no SCRATCH_STRICT program reported an "
              "out-of-range index (revision 4 R8), which would mean the "
              "strict path was never actually compared")
        return 1
    if not total:
        print("NO PROGRAM WAS COMPARED - the generator produced nothing "
              "valid, so this proved nothing")
        return 1
    if not refused_both:
        print("NO PROGRAM WAS REFUSED - the two validators were never "
              "asked to disagree, so half of this check did not run")
        return 1
    if not (saw_imul and saw_kx and saw_wide):
        # The same failure the counts above exist to make visible: a
        # generator that stopped emitting the new forms would leave
        # this differential passing while covering nothing new.
        print("THE EXTENDED CORPUS REACHED NEITHER FEATURE - no IMUL, no "
              "kx, or no constant index past the old sixteen, so the "
              "2026-09-07 additions were not compared at all")
        return 1
    if bad:
        print(f"{bad} DISAGREEMENTS")
        return 1
    print("libcft and the golden model agree on every program: deposits, "
          "counts, flags and status")
    return 0


if __name__ == "__main__":
    sys.exit(main())
