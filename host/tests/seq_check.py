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

Since parcel MP (M1's build, item 2, 2026-10-14) an EIGHTH corpus runs after
the seven, from its own seed per format; its first part is M1's routines - exp,
exp2, expm1, log, log2 and log1p, the 120 fragments of
python/cft_golden/mathlib.py at fp32, fp64, fp128 and fp256 under each
attribute - which until then had run on seq.py alone (its second part, sin,
cos and tan, since parcel M2P, follows below). Each is run in two shapes
through libcft and the golden model.
STAND-ALONE is routines.program's: the input in r0, the words in a BANK_EXT
bank, the result and the flag word deposited, no quiet region and no raise, so
the body's own flags reach FLAGS. COMPILED is what the compiler inlines
(python/tests/mathlib_harness.py's r24_program): QUIET, the body, ENDQUIET,
RAISE of the flag word and the result deposited - the shape that carries R24's
mark to STATUS[6] and R23's byte. It is also the first corpus here to hand
cft_program_run_ex a bank. A program's lanes are drawn from the special
encodings (+-0, +-inf, NaNs with payloads, subnormals), the routine's edge
pool, the transcend pools, its structured family (the committed windows'
centres, which it marks, and the lanes beside them; fp32 exp's marked lanes)
and random encodings; the edge pools, the pools, the centres and the samplers
are python/tests', the ones the fragments are held to there.
There are 1, 2, 63, 64, 65, 100 or 129 lanes, half the programs past libcft's
64-lane block, each with a one in three chance of a mask, whose masked lanes'
bytes must stay the caller's, the per-lane block asked for on every compiled
run and half the stand-alone ones. FLAGS, STATUS - the mark among it -, every
deposit, count and lane byte are compared, and how many lanes were, which must
be every lane the run owns. Beside them is the model's own identity: on a dozen
lanes of each stand-alone program, and on every marked one, the deposits seq.py
makes are mathlib.evaluate's - routines.run's outputs. A fragment the model
runs and libcft refuses is a mismatch, named. A reach check fails the run,
naming them, if a source or a class of lane, a form of run, a flag, the
identity or a refusal of the remote leg was never reached, or a fragment never
drawn. One ROUND draws every fragment in both shapes from fresh lanes: the
default is one round for each 250 --trials, at least one, and --math-rounds N
sets it. The lanes come from python/tests, which needs mpmath and pytest; a
host without them prints one SKIP line, which verify/run.sh counts as an
inner skip, and runs the seven corpora as before.
The run then states the programs' sizes against libcft's limits (cft_get_caps),
and a remote leg loads every program on fake servers whose HELLO publishes a
revision-7 tile's word, that word with BANK_PTR, WIDE_CONST or REGS32 cleared,
a revision-8 tile's, and that at max_insns or max_consts lowered, each load
refused by name where the program needs what the word lacks.

Since parcel M2P (M2's build, wave 3, 2026-10-29) the eighth corpus has a second
part, run after the six at each format that has it: sin, cos and tan, the 45
fragments of parcel M2G2a (mathlib.TRIG_NAMES at fp64, fp128 and fp256 under
each attribute), which had run on seq.py alone. They go through the same two
shapes, lane counts, masks, comparisons, refusals and remote leg, from a stream
of their own (a salt beside the six's), so that the six's programs, lanes and
masks are what they were at every --math-rounds; their lanes are
python/tests/mathlib_trig_harness.py's and mathlib_trig_family.py's, in the
same five categories (trig_lanes). The part keeps counters of its own, so that
a form it never reached is named as the trig part's ("THE ROUTINE CORPUS'S TRIG
PART DID NOT REACH EVERY FORM"), and a summary, a limits line and a line of the
bits its programs need (cft_caps.seq_features) of its own. sin, cos and tan are
not built at fp32 until parcel M2F: the summary line says "fp32: sin, cos and
tan not built (parcel M2F's)", which is no SKIP - a by-design absence, and a
SKIP line would fail every --require-all run. The formats come from
mathlib.TRIG_FORMATS, so when M2F adds fp32 to it the same loop takes the
format and the clause goes, with no edit here. Their programs write past r15 at
fp64 and fp128 and so need REGS32 there, where the six need it at fp32 alone.

    python3 host/tests/seq_check.py --device <xclbin | cft://host:port | sw>

Since revision 8's round 2 (parcel E, 2026-10-05) the corpora can run
through a DEVICE's handle against the model (docs/ROADMAP.md, "Revision
8", part 4's host legs). Without --device every corpus runs on the
software backend, as the gate's `seq` stage always has, and nothing below
changes. With it, two things are the device's rather than assumed: its
scratch depth - the model runs, and holds every program, at the device's
max_scratch, and the corpora's depth-edge cases move with it - and its
features. A program needing a bit the device does not publish (an image
bit at load; an index table, a lane mask or the per-lane flags block at
run, the first two only where the backend does not resolve them on the
client, as a remote handle does) is not compared: it must be REFUSED,
CFT_ERR_UNSUPPORTED, by a sentence naming the absent bit's CAPS place, and
is counted refused by name, corpus by corpus. A device that runs such a
program, or refuses it otherwise, is a mismatch. So on a revision-7 card
the revision-8 and flag-control corpora record their programs' refusals
by name while every other corpus compares - the routine corpus, whose
compiled programs are refused for QUIET and RAISE, and any run of its that
asks for the lane block, while its stand-alone programs compare; on a
revision-8 quad without R21 the augmented-addition programs are refused and
the rest compare. A routine program past a capacity the device publishes -
its instruction count against max_insns, its highest constant index against
max_consts, its deposits against max_deposits - is refused the same way,
naming cft_caps.<field>, and counted on a line of its own (the trig part's on
its own, "routine corpus, trig").
On a device that lacks AUGADD or SCRATCH_STEP the flag-control corpus is
drawn WITHOUT its revision-8 arm, because nearly every program that arm
touches holds an augadd, and on such a quad R24's regions and R23's block,
which it carries, would otherwise go uncompared behind refusals that have
nothing to do with them; the revision-8 corpus still holds those refusals
by name. The draw stays deterministic: each corpus's generator is seeded
from --seed and the format as always, whether the arm is drawn is a
function of the device's feature word alone, and the scratch depth moves
the programs of every corpus whose generator draws scratch instructions
(`scratch=True`: the third to the seventh), because `seq.random_program`
names the depth's last slot among the slots it draws. So one seed, one
feature word and one scratch depth give one corpus at a format and a trial
count; the same seed and word at another depth give another (the first two
corpora take no depth and do not move). Formats the device does not carry
are not compared, by name.
The remote legs' fake servers are the library's own and run as always.
"""

import argparse
import collections
import ctypes
import os
import random
import socket
import struct
import sys
import threading
import zlib
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from cft_golden import FORMATS, vectors  # noqa: E402
from cft_golden import asm, seq  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
# cft_caps.seq_features's names, bits and CAPS places: one table, the
# compiler's, which python/tests/test_cftc.py holds to every name asm.py's
# features() reports
from cftc import targets as T  # noqa: E402

CFT_OK = 0
CFT_ERR_INVALID_ARGUMENT = 1
CFT_ERR_UNSUPPORTED = 2
# cft_format's codes, for cft_caps.format_mask
FORMAT_CODE = {"fp32": 0, "fp64": 1, "fp128": 2, "fp256": 3}


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
    lib.cft_get_caps.argtypes = [ctypes.c_void_p, ctypes.POINTER(Caps)]
    lib.cft_get_caps.restype = ctypes.c_int
    lib.cft_open_ex.argtypes = [ctypes.POINTER(OpenArgs),
                                ctypes.POINTER(ctypes.c_void_p)]
    lib.cft_open_ex.restype = ctypes.c_int
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


# ---- --device (parcel E, 2026-10-05; the module's text) ------------------

class Caps(ctypes.Structure):
    """cft_caps, field for field (host/include/cft.h, to ABI 0.11's last
    field): an output struct, so the size handshake fills what this
    mirror holds and no more."""
    _fields_ = [("struct_size", ctypes.c_size_t),
                ("format_mask", ctypes.c_uint32),
                ("tiles", ctypes.c_uint32),
                ("abi_version", ctypes.c_uint32),
                ("device_version", ctypes.c_uint32),
                ("flags_readable", ctypes.c_int),
                ("backend", ctypes.c_char * 32),
                ("max_deposits", ctypes.c_uint32),
                ("max_insns", ctypes.c_uint32),
                ("max_consts", ctypes.c_uint32),
                ("seq_features", ctypes.c_uint32),
                ("max_scratch", ctypes.c_uint32),
                ("buffers_resident", ctypes.c_int)]


class OpenArgs(ctypes.Structure):
    """cft_open_args (ABI 0.16): --device sw:N opens the software backend
    at N scratch slots a lane, which is what a tile of that depth
    computes (docs/HOSTAPI.md, "A software handle at a tile's depth")."""
    _fields_ = [("struct_size", ctypes.c_size_t),
                ("artifact", ctypes.c_char_p),
                ("index", ctypes.c_int),
                ("scratch_depth", ctypes.c_uint32)]


class _Device:
    """What --device's handle publishes, and what it refused by name."""

    def __init__(self, handle, caps):
        self.handle = handle.value
        self.backend = caps.backend.decode("ascii", "replace")
        self.features = caps.seq_features
        self.format_mask = caps.format_mask
        self.max_scratch = caps.max_scratch
        # the three other capacities cft_get_caps publishes, 0 for unknown:
        # the eighth corpus holds a program past one of them refused by name
        self.max_insns = caps.max_insns
        self.max_consts = caps.max_consts
        self.max_deposits = caps.max_deposits
        self.version = caps.device_version
        self.tiles = caps.tiles
        self.refused = collections.Counter()    # (corpus, CAPS place)
        self.bad = 0

    def absent(self, need):
        return [f for f in need if not self.features & T.FEATURE_BITS[f]]

    def refused_in(self, corpus):
        return sum(k for (c, _p), k in self.refused.items() if c == corpus)


# The model's scratch depth - the device's under --device, else the
# model's own default - and the device. Read at each call, so every corpus
# below takes them as they stand when main() has set them.
DEPTH = seq.SCRATCH_D
DEVICE = None


def mprog(*args, **kw):
    """seq.Program written for the model's depth (DEPTH)."""
    kw.setdefault("scratch_depth", DEPTH)
    return seq.Program(*args, **kw)


def mrun(*args, **kw):
    """seq.run at the model's depth (DEPTH): the device's under
    --device, which a non-strict STX/LDX reduces its index modulo."""
    kw.setdefault("scratch_depth", DEPTH)
    return seq.run(*args, **kw)


def _needs(prog, idx=False, mask=False, lf=False):
    """The cft_caps.seq_features names a run of `prog` needs: its image's
    (asm.py's features(), in the compiler's names, and the header's strict
    flag) and its run's - an index table and a lane mask only where the
    device's backend does not resolve them on the client, as a remote
    handle does (device.c), and the per-lane flags block everywhere, since
    only the device that runs a lane can say what it raised."""
    img = asm.Image.from_bytes(prog.to_bytes())
    need = [T.ASM_FEATURE.get(f, f) for f in img.features()]
    if prog.flags & seq.FLAG_SCRATCH_STRICT:
        need.append("SCRATCH_STRICT")
    client_side = DEVICE is not None and DEVICE.backend == "remote"
    if idx and not client_side:
        need.append("INDEXED")
    if mask and not client_side:
        need.append("LANE_MASK")
    if lf:
        need.append("LANE_FLAGS")
    return need


def _run_one_lane(lib, handle, prog, idx, mask, lf):
    """`prog` run once, on one lane, with the run options a corpus run of
    it has: -> (status, the library's sentence, or "" on success)."""
    esz = prog.fmt.width // 8
    keep = []

    def buf(nbytes, fill=b""):
        b = ctypes.create_string_buffer(fill.ljust(max(1, nbytes), b"\0"),
                                        max(1, nbytes))
        keep.append(b)
        return ctypes.cast(b, ctypes.c_void_p)

    args = RunArgs()
    args.struct_size = ctypes.sizeof(RunArgs)
    args.a = args.b = args.c = buf(esz)
    args.n = 1
    if prog.bank_ext:
        args.bank, args.bank_bytes = buf(prog.n_consts * esz), \
            prog.n_consts * esz
    if prog.scratch_io and prog.n_scratch_in:
        args.scratch_in = buf(prog.n_scratch_in * esz)
        args.scratch_in_bytes = prog.n_scratch_in * esz
    if prog.scratch_io and prog.n_scratch_out:
        args.scratch_out = buf(prog.n_scratch_out * esz)
        args.scratch_out_bytes = prog.n_scratch_out * esz
    args.deposits = buf(prog.max_deposits * esz)
    counts = (ctypes.c_uint32 * 1)()
    flags, bus = ctypes.c_uint32(0), ctypes.c_uint32(0)
    args.counts = counts
    args.flags_out = ctypes.pointer(flags)
    args.bus_out = ctypes.pointer(bus)
    if idx:
        args.idx_a, args.idx_a_src = buf(4), 1          # index 0 of 1
    if mask:
        args.lane_mask, args.lane_mask_bytes = buf(1, b"\x01"), 1
    if lf:
        args.lane_flags, args.lane_flags_bytes = buf(1), 1
    rc = lib.cft_program_run_ex(handle, ctypes.byref(args))
    msg = lib.cft_last_error().decode("utf-8", "replace") if rc else ""
    return rc, msg


def device_refuses(lib, dev, prog, corpus, idx=False, mask=False, lf=False):
    """Under --device: True when a run of `prog` with these options needs
    a feature `dev`, the device under test, does not publish. Such a
    program is held REFUSED BY NAME rather than compared: loaded - an
    image's bit is refused at load - and, where it loads, run once on one
    lane with the same options, a run's option being refused at run. The
    refusal must be CFT_ERR_UNSUPPORTED with a sentence naming an absent
    bit's CAPS place, and is counted by corpus and place; the device taking
    the program, or refusing it otherwise, is a mismatch, printed. False,
    and nothing done, without --device, on any other handle - the remote
    legs' fake servers - and for a program the device can run."""
    if DEVICE is None or dev.value != DEVICE.handle:
        return False
    absent = DEVICE.absent(_needs(prog, idx, mask, lf))
    if not absent:
        return False
    places = [T.CAPS_PLACE[f] for f in absent]
    image = prog.to_bytes()
    handle = ctypes.c_void_p()
    rc = lib.cft_program_load(dev, image, len(image), ctypes.byref(handle))
    msg = lib.cft_last_error().decode("utf-8", "replace") if rc else ""
    where = "at load"
    if rc == CFT_OK:
        try:
            rc, msg = _run_one_lane(lib, handle, prog, idx, mask, lf)
            where = "at run"
        finally:
            lib.cft_program_free(handle)
    named = [p for p in places if p in msg]
    if rc == CFT_ERR_UNSUPPORTED and named:
        DEVICE.refused[(corpus, named[0])] += 1
        return True
    DEVICE.bad += 1
    if DEVICE.bad <= 5:
        print(f"  MISMATCH {prog.fmt.name} ({corpus}, --device): a program "
              f"needing {', '.join(f'{f} ({T.CAPS_PLACE[f]})' for f in absent)}"
              f", which the device does not publish, gave rc {rc} {where}: "
              f"{msg!r} - wanted CFT_ERR_UNSUPPORTED naming "
              f"{' or '.join(places)}")
    return True


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
                                           scratch=True, scratch_depth=DEPTH)
        maxdep = rng.choice([1, 2, 4])
        io = rng.random() < 0.5
        nsin = rng.choice([1, 2, 3]) if io else 0
        nsout = rng.choice([0, 1, 2]) if io else 0
        flags = seq.FLAG_SCRATCH_IO if io else 0
        try:
            prog = mprog(fmt, insns, consts, maxdep, flags=flags,
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
                    mrun(prog, a, b, c, scratch_in=sin_arg,
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

        want = mrun(prog, a, b, c, scratch_in=sin_arg,
                    idx_a=tabs[0], idx_b=tabs[1], idx_c=tabs[2],
                    idx_scratch_in=si_tab)
        if device_refuses(lib, dev, prog, "indexed corpus", idx=True):
            continue
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
            ctl = mprog(fmt, [seq.deposit(0), seq.halt()],
                        max_deposits=1)
            if device_refuses(lib, dev, ctl, "indexed corpus", idx=True):
                continue
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
                want_rot = mrun(ctl, vals, vals, vals, idx_a=perm)
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
                                           scratch=True, scratch_depth=DEPTH)
        maxdep = rng.choice([1, 2, 4])
        io = rng.random() < 0.5
        nsin = rng.choice([1, 2, 3]) if io else 0
        nsout = rng.choice([0, 1, 2]) if io else 0
        flags = seq.FLAG_SCRATCH_IO if io else 0
        try:
            prog = mprog(fmt, insns, consts, maxdep, flags=flags,
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

        want = mrun(prog, a, b, c, scratch_in=sin_arg, lane_mask=keep)
        if device_refuses(lib, dev, prog, "masked corpus", mask=True):
            continue
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
    D = DEPTH
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
                                           wide_regs=True, scratch=True,
                                           scratch_depth=DEPTH)
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
                flags, nsin = seq.FLAG_SCRATCH_IO, DEPTH + 1
            else:
                flags, nsout = seq.FLAG_SCRATCH_IO, DEPTH + 1
        try:
            prog = mprog(fmt, insns, consts, maxdep, flags=flags,
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
        want = mrun(prog, a, b, c, scratch_in=sin)
        # The bit is what R8 adds; a strict corpus that never sets it
        # compared the modulo path twice and proved nothing.
        if want.status & seq.STATUS_SCRATCH_RANGE:
            S["range"] += 1
        if device_refuses(lib, dev, prog, "scratch corpus"):
            continue
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
# and a strict program reports, and near zero, so a -1 walk wraps. The
# edge is the model's depth - 256, (0, 1, 2, 250, 253, 255, 256, 300) as
# these always were, and the device's under --device.
def _walk_starts():
    return (0, 1, 2, DEPTH - 6, DEPTH - 3, DEPTH - 1, DEPTH, DEPTH + 44)


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
            mprog(fmt, insns, max_deposits=0)
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
                prog = mprog(fmt, body(step), max_deposits=5,
                             flags=flags, n_scratch_in=16,
                             n_scratch_out=16)
                zero = mprog(fmt, body(0), max_deposits=5,
                             flags=flags, n_scratch_in=16,
                             n_scratch_out=16)
                n = (1, 65, 129)[k % 3]
                k += 1
                a = seq.random_inputs(fmt, rng, n)
                b = seq.random_inputs(fmt, rng, n)
                c = seq.random_inputs(fmt, rng, n)
                sin = [rng.choice(pool) for _ in range(16 * n)]
                want = mrun(prog, a, b, c, scratch_in=sin)
                same = mrun(zero, a, b, c, scratch_in=sin)
                if want.state() != same.state():
                    print(f"  MISMATCH {name} (own-index leg) r{r} step "
                          f"{step:+d} strict={strict}: the model's stepped "
                          f"load is not its unstepped one")
                    R["bad"] += 1
                if device_refuses(lib, dev, prog,
                                  "revision-8 own-index leg"):
                    continue
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
                                           rev8=True, scratch_depth=DEPTH)
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
            prog = mprog(fmt, insns, consts, maxdep, flags=flags,
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
                    sin[i * nsin] = rng.choice(_walk_starts())
                    sin[i * nsin + 1] = rng.choice(_walk_starts())
        want = mrun(prog, a, b, c, scratch_in=sin)
        if strict:
            R["strict"] += 1
            if want.status & seq.STATUS_SCRATCH_RANGE:
                R["range"] += 1
        for bit, key in ((0x01, "inv"), (0x04, "ovf"), (0x08, "unf")):
            if want.flags & bit:
                R[key] += 1
        if device_refuses(lib, dev, prog, "revision-8 corpus"):
            continue
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

    def __init__(self, features, backend=b"xrt", max_deposits=64,
                 max_insns=16384, max_consts=512):
        self.features = features
        self.backend = backend
        # 0 is what cft_caps calls unknown - what a server older than the
        # field publishes - and the one way a handle reaches
        # cft_program_load's own deposit ceiling (deposit_ceiling_remote).
        self.max_deposits = max_deposits
        # the two other capacities, which the eighth corpus's remote leg
        # lowers to hold a program past one refused by name
        self.max_insns = max_insns
        self.max_consts = max_consts
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
                                              self.max_insns,
                                              self.max_consts, self.features,
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

    A revision-7 tile publishes neither (CAPS2[11] and [12] read zero), and
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
                # cft_last_error is read for a refusal alone. Until
                # 2026-09-30 a load that succeeded left the previous
                # sentence there (verifier-R3); since 2026-10-22 (KL-490)
                # every call that returns a status empties the library's
                # slot and both device backends' first, so a successful
                # load leaves it empty, and the rule stands because an
                # empty slot says nothing.
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
            mprog(fmt, insns, max_deposits=0)
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
    # Under --device, the revision-8 arm only where the device carries both
    # its bits: on a quad without R21 nearly every program the arm touches
    # holds an augadd and would be refused for it, and this corpus's own
    # forms - R24's regions and R23's block, which that quad carries - would
    # go uncompared. Without --device, and on a device with both, the arm
    # draws as it always has.
    rev8_arm = DEVICE is None or not DEVICE.absent(["AUGADD", "SCRATCH_STEP"])
    for _trial in range(trials):
        insns, consts = seq.random_program(fmt, rng, scratch=True,
                                           wide_regs=True, rev8=rev8_arm,
                                           flags=True, scratch_depth=DEPTH)
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
                mprog(fmt, insns, consts, maxdep, flags=pflags,
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
        prog = mprog(fmt, insns, consts, maxdep, flags=pflags,
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
        want = mrun(prog, a, b, c, lane_mask=keep)
        if device_refuses(lib, dev, prog, "flag-control corpus",
                          mask=keep is not None, lf=True):
            continue
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

    A revision-7 tile publishes neither (CAPS2[13] and [14] read zero), and
    the device is a remote handle to the fake server of rev8_remote_refusals,
    whose HELLO publishes that tile's word, 0x7f1f. Each of the three
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


# ---- the eighth corpus: M1's routines (parcel MP); sin, cos and tan, below ---
#
# exp, exp2, expm1, log, log2 and log1p are tile routines: fragments of
# existing instructions (python/cft_golden/mathlib.py), at fp32, fp64, fp128
# and fp256 under each of the five attributes - 120 of them, which until this
# corpus had run on seq.py alone. Each is run through libcft's sequencer and
# through the golden model in two shapes. STAND-ALONE is the harness's own
# (routines.program): the input in r0, the words in a BANK_EXT bank, two
# deposits a lane - the result and the flag word, whose bit 7 is the mark -
# and no quiet region and no raise, so the body's own flags reach FLAGS. The
# COMPILED shape is what the compiler inlines (mathlib_harness.r24_program):
# QUIET, the body, ENDQUIET, RAISE of the flag word and the result deposited,
# the only one that reaches R24's mark and R23's byte, and so STATUS[6] and
# the lane block. This is also the first corpus here to give a program a
# bank through cft_program_run_ex.
#
# The lanes of a program are drawn from five categories, shuffled, from a
# seed of the corpus's own per format and a stream of its own per fragment:
# the special encodings (+-0, +-inf, NaNs with payloads of both signs and
# both kinds, subnormals, the extremes), the edge pool of the routine (its
# thresholds, screens and the ends of its cells: mathlib_harness.edge_pool),
# the transcend pools the tests use (mathlib_harness.pools), the structured
# family (the committed windows' centres, which the routine marks, and their
# neighbours and the census beside them; fp32's exp marks) and random
# encodings (the main path's samplers and raw bit patterns). A program has 1,
# 2, 63, 64, 65, 100 or 129 lanes, half of them past libcft's 64-lane block,
# each with a one in three chance of a mask, whose masked lanes' bytes must
# stay the caller's pattern, and the per-lane block is asked for on every
# compiled run and half the stand-alone ones.
#
# Compared on every run: FLAGS, STATUS - with its mark -, every deposit,
# every count, and every lane byte where asked; and how many lanes were
# compared, which must be every lane the run owns. Beside them the model's
# own identity: on a dozen lanes of each stand-alone program, and on every
# marked one, the result and flag word seq.py deposits are mathlib.evaluate's
# - routines.run's outputs. A fragment the model runs and libcft refuses is a
# mismatch, named. Under --device a program needing a bit the device does not
# publish, or past a capacity it does, is refused by name and counted; the
# remote leg shows the refusals, on fake servers whose HELLO publishes a
# revision-7 tile's word and the same word with a bit cleared, and past a
# capacity lowered.

ROUTINE_NS = (1, 2, 63, 64, 65, 65, 100, 129)       # lanes a program
ROUTINE_SHARES = (("special", 0.15), ("edge", 0.25), ("pool", 0.15),
                  ("struct", 0.15), ("random", 0.30))
ROUTINE_MINIMA = (3, 3, 1, 1, 1)        # at 8 lanes or more, each category
ROUTINE_IDENT = 12                      # lanes a stand-alone run evaluates
ROUTINE_SHAPES = ("stand-alone", "compiled")
# the remote leg: seven servers, two of them with a capacity lowered to these
ROUTINE_LEGS = 7
ROUTINE_LEG_INSNS = 300
ROUTINE_LEG_CONSTS = 64
ROUTINE_FLAGS = (("invalid", sf.FLAG_INVALID),
                 ("divideByZero", sf.FLAG_DIVZERO),
                 ("overflow", sf.FLAG_OVERFLOW),
                 ("underflow", sf.FLAG_UNDERFLOW),
                 ("inexact", sf.FLAG_INEXACT))
ROUTINE_FILL = (0xA5, 0xA5A5A5A5, 0xEE)     # a deposit byte, a count, a lane
                                            # byte: the caller's own pattern
ROUTINE_SALT = 0x4D4C4942               # "MLIB": the six's stream (parcel MP)
TRIG_SALT = 0x4D325047                  # "M2PG": the trig part's own (parcel M2P)
TRIG_EDGE_N = 32                        # arguments of each edge region drawn
TRIG_EDGE_SEEDS = (("edge", 31), ("near", 32), ("zero", 33))
# the sources of a trig lane, in the order the summary gives them
TRIG_SOURCES = ("special", "edge", "pool", "centre", "family", "near",
                "struct", "random")
# the two IEEE flags sin, cos and tan are not expected to raise on any
# argument (no float is a pole of tan, |sin| and |cos| are at most 1, and a
# float's tan is far under the largest finite number): counted like the
# others, and not required of the run
TRIG_NEVER_RAISED = ("divideByZero", "overflow")
_ROUTINE = {"progs": {}, "cache": {}, "needs": {}, "sizes": set()}


def routine_counters():
    """The eighth corpus's counters - one set for the six, one for the trig
    part (parcel M2P) - a defaultdict, since it counts lanes by their class
    and runs by the flags they raised."""
    C = collections.defaultdict(int)
    C["by_format"] = {}
    C["capref"] = collections.Counter()
    C["remote_names"] = collections.Counter()   # what the remote leg named
    C["formats"] = []           # the formats the part ran at
    C["fragments"] = set()      # (format, routine, attribute) it drew
    C["absent"] = []            # the formats its routines are not built at
    return C


def routine_modules():
    """(mathlib, mathlib_harness, mathlib_family), imported on first use, or
    None - after one SKIP line, which verify/run.sh counts as an inner skip -
    on a host without mpmath or pytest: the lanes come from python/tests,
    which the golden stage runs and which need both. A host that has them
    runs the corpus; one that has not runs the seven corpora as before."""
    if "mods" not in _ROUTINE:
        mods = None
        try:
            import mpmath  # noqa: F401
            import pytest  # noqa: F401
        except ModuleNotFoundError as exc:
            print(f"SKIP  the routine corpus (the eighth): {exc.name} is not "
                  f"installed here, and its lanes come from python/tests/"
                  f"mathlib_harness.py, which needs mpmath and pytest")
        else:
            tests = str(ROOT / "python" / "tests")
            if tests not in sys.path:
                sys.path.append(tests)
            from cft_golden import mathlib as ml  # noqa: E402
            import mathlib_family as fam  # noqa: E402
            import mathlib_harness as har  # noqa: E402
            mods = (ml, har, fam)
        _ROUTINE["mods"] = mods
    return _ROUTINE["mods"]


def routine_programs(fmt, fn, rnd):
    """(fragment, (stand-alone program, bank), (compiled program, bank)):
    the programs of one fragment, built once."""
    key = (fmt.name, fn, rnd)
    if key not in _ROUTINE["progs"]:
        from cft_golden import routines
        ml, har, _fam = routine_modules()
        f = ml.fragment(fn, fmt, rnd)
        built = (f, routines.program(f), har.r24_program(f))
        _ROUTINE["progs"][key] = built
        for shape, (prog, _bank) in zip(ROUTINE_SHAPES, built[1:]):
            # what the limits line reports: instructions, bank words, the
            # highest register written, deposits a lane
            top_reg = max((d["rd"] for d in map(seq.decode, prog.insns)
                           if not d["ctrl"]), default=0)
            _ROUTINE["sizes"].add((fmt.name, fn, sf.RND_NAMES[rnd], shape,
                                   len(prog.insns), prog.n_consts, top_reg,
                                   prog.max_deposits))
    return _ROUTINE["progs"][key]


def _routine_cached(key, make):
    if key not in _ROUTINE["cache"]:
        _ROUTINE["cache"][key] = make()
    return _ROUTINE["cache"][key]


def routine_specials(fmt):
    """The special encodings, each a lane a routine must answer by its
    specification: +-0, +-inf, the canonical quiet NaN, quiet NaNs with
    payloads and of both signs, signalling NaNs with the smallest, a middle
    and the largest payload and of both signs, the smallest and largest
    subnormals and normals of both signs, +-1 and the floats beside 1."""
    mw, sign = fmt.man_w, fmt.sign_mask
    qn = sf.qnan_bits(fmt)
    one = sf.one_bits(fmt)
    out = [sf.zero_bits(fmt), sf.zero_bits(fmt, 1), sf.inf_bits(fmt),
           sf.inf_bits(fmt, 1), qn, qn | 0x5, qn | ((1 << (mw - 1)) - 1),
           sign | qn, sign | qn | 0x5, sf.snan_bits(fmt),
           sf.snan_bits(fmt, 0x5), sf.snan_bits(fmt, 1 << (mw - 2)),
           sf.snan_bits(fmt, (1 << (mw - 1)) - 1), sign | sf.snan_bits(fmt),
           one, one + 1, one - 1, sf.one_bits(fmt, 1),
           sf.one_bits(fmt, 1) + 1, sf.one_bits(fmt, 1) - 1]
    for s in (0, 1):
        out += [sf.min_subnormal_bits(fmt, s), sf.max_subnormal_bits(fmt, s),
                sf.min_normal_bits(fmt, s), sf.max_normal_bits(fmt, s)]
    return out


def routine_ln1p_marks(ml, fmt):
    """The floats nearest ln(1 + t) for t = 2^-23, 2^-22, 2^-21, -2^-22 and
    -2^-21: at fp32 exp marks all five under rtz, rdn and rup, and under
    neither rne nor rmm (docs/ROADMAP.md's account of E1's brief correction 1:
    its verifiers found them). They are the only lanes of fp32 the corpus
    draws that mark - the committed windows are empty at its guard of 40 - and
    it counts the marks the model gives them, as it counts every other."""
    import mpmath
    out = []
    with mpmath.workprec(4 * fmt.prec + 100):
        for t in (Fraction(1, 2 ** 23), Fraction(1, 2 ** 22),
                  Fraction(1, 2 ** 21), Fraction(-1, 2 ** 22),
                  Fraction(-1, 2 ** 21)):
            v = mpmath.log(1 + mpmath.mpf(t.numerator) / t.denominator)
            out.append(ml._enc(fmt, ml._frac(v)))
    return out


def routine_struct_pool(ml, har, fam, fn, fmt, rnd):
    """(centres, marked, rest): the committed centres of the routine's
    structured family at this format and attribute, their arguments - the
    lanes the routine marks (and, at fp32, exp's) - and the lanes beside
    them: the census, which a window would start at, or for exp2 and log2,
    which have no family, the lanes next to their exact cases."""
    def make():
        if fn in ("exp2", "log2"):
            return [], [], list(har.nofamily_lanes(fmt, deep=False, fn=fn))
        cens = list(fam.FAMILY[fn][fmt.name][sf.RND_NAMES[rnd]])
        marked = [fam.argument(fmt, c) for c in cens]
        if fn == "exp" and fmt.name == "fp32":
            marked += routine_ln1p_marks(ml, fmt)
        census = fam.census_log(fmt) if fn == "log" else fam.census(fmt)
        return cens, marked, list(census)
    return _routine_cached(("struct", fmt.name, fn, rnd), make)


def routine_quotas(n):
    """The lanes of each category for an n-lane program, in ROUTINE_SHARES'
    order: the shares, the remainder to the largest fractions, and, from as
    many lanes as ROUTINE_MINIMA add up to, at least that many of each - a
    category short of its minimum taking from the one with the most beyond
    its own."""
    shares = [s for _c, s in ROUTINE_SHARES]
    q = [int(n * s) for s in shares]
    order = sorted(range(len(q)), key=lambda i: (-(n * shares[i] - q[i]), i))
    for i in order[:n - sum(q)]:
        q[i] += 1
    if n >= sum(ROUTINE_MINIMA):
        for i, lo in enumerate(ROUTINE_MINIMA):
            while q[i] < lo:
                j = max((k for k in range(len(q)) if k != i),
                        key=lambda k: q[k] - ROUTINE_MINIMA[k])
                q[j] -= 1
                q[i] += 1
    return q


def routine_lanes(ml, har, fam, fmt, fn, rnd, n, sub):
    """(xs, tags): n argument encodings for a program of fragment (fn, fmt,
    rnd), from the stream `sub`, and the category each came from - special,
    edge, pool, centre (a committed window's centre, or fp32 exp's mark),
    struct (the lanes beside the windows and the exact cases) or random: the
    quotas of each category, a category short of lanes handing its remainder
    to the random one, the whole shuffled."""
    q = dict(zip((c for c, _s in ROUTINE_SHARES), routine_quotas(n)))
    pairs, short = [], 0
    for cat, pool in (
            ("special", routine_specials(fmt)),
            ("edge", _routine_cached(("edge", fmt.name, fn),
                                     lambda: list(har.edge_pool(fmt, fn)))),
            ("pool", list(har.pools(fmt)))):
        take = min(q[cat], len(pool))
        pairs += [(x, cat) for x in sub.sample(pool, take)]
        short += q[cat] - take
    cens, marked, rest = routine_struct_pool(ml, har, fam, fn, fmt, rnd)
    if q["struct"]:
        m = min(len(marked), max(1, q["struct"] // 2)) if marked else 0
        centres = sub.sample(marked, m) if m else []
        near = []
        for c in sub.sample(cens, min(4, len(cens))):
            near += [x for x, _lab in fam.neighbours(fmt, c)]
        beside = rest + near
        others = sub.sample(beside, min(q["struct"] - m, len(beside)))
        pairs += [(x, "centre") for x in centres]
        pairs += [(x, "struct") for x in others]
        short += q["struct"] - len(centres) - len(others)
    k = q["random"] + short
    k_main, k_weighted = k // 2, k // 4
    rand = []
    if k_main:
        rand += har.random_main(fmt, k_main, sub.getrandbits(30), fn)
    if k_weighted:
        rand += har.weighted(fmt, k_weighted, sub.getrandbits(30), fn)
    rand += [sub.getrandbits(fmt.width)
             for _ in range(k - k_main - k_weighted)]
    pairs += [(x, "random") for x in rand]
    sub.shuffle(pairs)
    return [x for x, _t in pairs], [t for _x, t in pairs]


# ---- the eighth corpus's second part: sin, cos and tan (parcel M2P) ----------
#
# Beside the six the routine corpus runs sin, cos and tan (mathlib.TRIG_NAMES):
# the 45 fragments of parcel M2G2a at fp64, fp128 and fp256 under each
# attribute, which until this part had run on seq.py alone. They go through
# the same two shapes, lane counts and masks and the same comparisons
# (routine_corpus, trig=True), from a stream of their own (TRIG_SALT, where the
# six's is ROUTINE_SALT) so that the six's programs, lanes and masks are what
# they were at every round count. fp32 has no sin, cos or tan until parcel M2F:
# the summary says so by name, and it is not a SKIP (a by-design absence).
#
# The lanes are python/tests/mathlib_trig_harness.py's and
# mathlib_trig_family.py's, the ones the fragments are held to there, in the
# corpus's five categories:
#
#   special  routine_specials and the rows of the study's section 4
#            (special_rows): NaNs, infinities, zeros, subnormals, the gates
#            and, past the range, 2^R and the largest finite
#   edge     sample() at "edge", "near" and "zero" - arguments within three
#            ulps of the odd multiples of pi/4 and of the multiples of pi/2,
#            where the reduction cancels deepest - and the range's end: the
#            arguments at and past 2^R (fp128 and fp256), which the routine marks
#   pool     radian_pools
#   struct   "centre": the cell's committed marks (TRIG_POOL_MARKS, the
#            radian pools' structured marks, and structured_lanes); "family":
#            centres of TRIG_FAMILY (parcel M2G2b's: c 2^-e and the
#            minimisers' neighbours), a sign each at random; "near": the
#            neighbours of four of the family's centres; "struct": the
#            study's tiny census. All but the census are lanes the routine
#            marks or that sit at a window's edge
#   random   sample() at "random" and "small", and raw bit patterns

def trig_modules():
    """(mathlib_trig_harness, mathlib_trig_family), imported on first use: the
    lanes of parcel M2G2a and the committed families of parcel M2G2b. None
    wherever routine_modules() is (mpmath or pytest absent: one SKIP line,
    printed there)."""
    if routine_modules() is None:
        return None
    if "tmods" not in _ROUTINE:
        import mathlib_trig_family as tf  # noqa: E402
        import mathlib_trig_harness as th  # noqa: E402
        _ROUTINE["tmods"] = (th, tf)
    return _ROUTINE["tmods"]


def trig_specials(th, fmt):
    """The special encodings of the six (routine_specials) and the rows of the
    study's section 4 (special_rows), each lane once, in order."""
    def make():
        out = list(routine_specials(fmt))
        for _label, _kind, lanes in th.special_rows(fmt):
            out += lanes
        return list(dict.fromkeys(out))
    return _routine_cached(("tspecial", fmt.name), make)


def trig_range_end(ml, th, fmt):
    """The range's end: at fp128 and fp256 the arguments at and past 2^R (R =
    TRIG_RANGE), which the routine marks whatever the test says - 2^R and its
    successor, and two significands in each of a spread of binades up to the
    largest finite, from a generator of the corpus's own, both signs. Each is
    past_range(): a lane that is not is a defect of this list, and stops the
    run. None at fp64, which has no range."""
    R = ml.TRIG_RANGE[fmt.name]
    if R is None:
        return []
    rng = random.Random(0x52414E47 ^ fmt.width)         # "RANG"
    p, top = fmt.prec, ml._pow2(fmt, R)
    out = [top, top + 1]
    for e in sorted({R, R + 1, R + 9, 2 * R, 4 * R + 3,
                     (R + fmt.emax) // 2, fmt.emax - 1, fmt.emax}):
        for _ in range(2):
            out.append(sf.round_pack(fmt, 0, rng.getrandbits(p - 1)
                                     | (1 << (p - 1)), e - p + 1,
                                     sf.RND_RNE)[0])
    out += [x | fmt.sign_mask for x in out]
    stray = [x for x in out if not th.past_range(fmt, x)]
    if stray:
        raise RuntimeError(f"the trig corpus's range end holds {len(stray)} "
                           f"arguments that are not past 2^{R} at "
                           f"{fmt.name}, first {stray[0]:#x}")
    return out


def trig_edge_pool(ml, th, fmt):
    """The edge pool of sin, cos and tan: sample() at "edge", "near" and
    "zero" (TRIG_EDGE_N arguments of each, seeds of the corpus's own) and the
    range's end, each lane once."""
    def make():
        out = []
        for mode, seed in TRIG_EDGE_SEEDS:
            out += th.sample(fmt, mode, TRIG_EDGE_N, seed)
        return list(dict.fromkeys(out + trig_range_end(ml, th, fmt)))
    return _routine_cached(("tedge", fmt.name), make)


def trig_struct(th, tf, fn, fmt, rnd):
    """(marks, centres) of the cell (fn, fmt, rnd): the committed marks - the
    radian pools' structured marks for the cell (TRIG_POOL_MARKS) and
    structured_lanes, both signs - and the cell's TRIG_FAMILY centres as
    expand() gives them, (c, e) and ("m", v, j), whose arguments are made when
    one is drawn (a minimiser costs a search of its binade, seconds at fp256
    for all of them)."""
    def make():
        marks = (sorted(th.pool_marks(fn, fmt.name, sf.RND_NAMES[rnd]))
                 + th.structured_lanes(fn, fmt, rnd))
        return (list(dict.fromkeys(marks)),
                tf.expand(tf.TRIG_FAMILY[fn][fmt.name][sf.RND_NAMES[rnd]]))
    return _routine_cached(("tstruct", fmt.name, fn, rnd), make)


def trig_lanes(ml, th, tf, fmt, fn, rnd, n, sub):
    """(xs, tags): n argument encodings for a program of fragment (fn, fmt,
    rnd), sin, cos or tan, from the stream `sub`, and the source of each -
    special, edge, pool, centre, family, near, struct (the census) or random
    (the module's text): routine_quotas' lanes of each category, a category
    short of lanes handing its remainder to the random one, the whole
    shuffled. The struct category is up to half centres (the cell's committed
    marks and its family's, up to half each) and the rest lanes beside them,
    half from the neighbours of four family centres and half the census."""
    q = dict(zip((c for c, _s in ROUTINE_SHARES), routine_quotas(n)))
    pairs, short = [], 0
    for cat, pool in (("special", trig_specials(th, fmt)),
                      ("edge", trig_edge_pool(ml, th, fmt)),
                      ("pool", list(th.radian_pools(fmt)))):
        take = min(q[cat], len(pool))
        pairs += [(x, cat) for x in sub.sample(pool, take)]
        short += q[cat] - take
    marks, cens = trig_struct(th, tf, fn, fmt, rnd)
    if q["struct"]:
        m = min(len(marks) + len(cens), max(1, q["struct"] // 2))
        m_marks = min(len(marks), (m + 1) // 2)
        m_fam = min(len(cens), m - m_marks)
        pairs += [(x, "centre") for x in sub.sample(marks, m_marks)]
        for c in sub.sample(cens, m_fam):
            x = tf.argument(fmt, c)
            pairs.append((x | fmt.sign_mask if sub.random() < 0.5 else x,
                          "family"))
        near = []
        for c in sub.sample(cens, min(4, len(cens))):
            near += [(x, "near") for x, _lab in tf.neighbours(fmt, fn, c)]
        census = _routine_cached(("tcensus", fmt.name),
                                 lambda: [(x, "struct")
                                          for x in tf.census(fmt)])
        rest = q["struct"] - m_marks - m_fam
        k_near = min(len(near), (rest + 1) // 2)
        others = (sub.sample(near, k_near)
                  + sub.sample(census, min(len(census), rest - k_near)))
        pairs += others
        short += rest - len(others)
    k = q["random"] + short
    k_main, k_small = k // 2, k // 4
    rand = []
    if k_main:
        rand += th.sample(fmt, "random", k_main, sub.getrandbits(30))
    if k_small:
        rand += th.sample(fmt, "small", k_small, sub.getrandbits(30))
    rand += [sub.getrandbits(fmt.width) for _ in range(k - k_main - k_small)]
    pairs += [(x, "random") for x in rand]
    sub.shuffle(pairs)
    return [x for x, _t in pairs], [t for _x, t in pairs]


def run_in_c_routine(lib, dev, prog, bank, xs, keep=None, lf=False):
    """-> (deposit bytes, counts, flags, status, lane bytes or None), each
    read back RAW, through cft_program_run_ex with a BANK_EXT program's
    bank - the input stream xs, zero streams b and c as routines.run gives
    them - ABI 0.14's mask where `keep` is given and ABI 0.17's lane block
    where `lf` asks. The deposits, the counts and the block are filled with
    the caller's pattern (ROUTINE_FILL) first, so that a masked lane's bytes,
    which the library must leave alone, are told from ones written 0; the
    library's refusal is a RuntimeError."""
    fmt = prog.fmt
    esz = fmt.width // 8
    n = len(xs)
    image = prog.to_bytes()

    handle = ctypes.c_void_p()
    st = lib.cft_program_load(dev, image, len(image), ctypes.byref(handle))
    if st != CFT_OK:
        why = lib.cft_last_error().decode("utf-8", "replace")
        raise RuntimeError(f"cft_program_load: {why}")
    try:
        def pack(vals):
            return ctypes.create_string_buffer(
                b"".join(v.to_bytes(esz, "little") for v in vals),
                max(1, len(vals) * esz))

        buf_a, buf_b, buf_c = pack(xs), pack([0] * n), pack([0] * n)
        buf_k = pack(bank)
        ndep = n * prog.max_deposits
        buf_d = ctypes.create_string_buffer(
            bytes([ROUTINE_FILL[0]]) * max(1, ndep * esz), max(1, ndep * esz))
        counts = (ctypes.c_uint32 * max(1, n))()
        for i in range(n):
            counts[i] = ROUTINE_FILL[1]
        flags = ctypes.c_uint32(0)
        bus = ctypes.c_uint32(0)
        args = RunArgs()
        args.struct_size = ctypes.sizeof(RunArgs)
        args.a = ctypes.cast(buf_a, ctypes.c_void_p)
        args.b = ctypes.cast(buf_b, ctypes.c_void_p)
        args.c = ctypes.cast(buf_c, ctypes.c_void_p)
        args.n = n
        args.bank = ctypes.cast(buf_k, ctypes.c_void_p)
        args.bank_bytes = len(bank) * esz
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
        buf_lf = None
        if lf:
            buf_lf = ctypes.create_string_buffer(
                bytes([ROUTINE_FILL[2]]) * max(1, n), max(1, n))
            args.lane_flags = ctypes.cast(buf_lf, ctypes.c_void_p)
            args.lane_flags_bytes = n
        st = lib.cft_program_run_ex(handle, ctypes.byref(args))
        if st != CFT_OK:
            why = lib.cft_last_error().decode("utf-8", "replace")
            raise RuntimeError(f"cft_program_run_ex: {why}")
        return (buf_d.raw[:ndep * esz], list(counts)[:n], flags.value,
                bus.value, list(buf_lf.raw[:n]) if lf else None)
    finally:
        lib.cft_program_free(handle)


def routine_top_const(prog):
    """The highest constant index an instruction of `prog` names, -1 for
    none."""
    top = -1
    for w in prog.insns:
        d = seq.decode(w)
        if d["ctrl"]:
            continue
        for idx, is_k in seq.sources(d):
            if is_k:
                top = max(top, idx)
    return top


def routine_needs(prog):
    """The cft_caps.seq_features names a load of `prog` needs, once."""
    key = id(prog)
    if key not in _ROUTINE["needs"]:
        _ROUTINE["needs"][key] = (prog, _needs(prog))
    return _ROUTINE["needs"][key][1]


def routine_refuses(lib, dev, prog, mask, lf, MR, corpus="routine corpus"):
    """Under --device: True when a run of `prog` needs a bit the device does
    not publish (device_refuses holds that, by name, and counts it) or is past
    a capacity it does - the instruction count against max_insns, the highest
    constant index against max_consts, the deposits against max_deposits.
    Past a capacity the load must be CFT_ERR_UNSUPPORTED naming
    cft_caps.<field> (device.c's cft_seq_cap_refusal), counted in MR; a
    device that takes such a program, or refuses it otherwise, is a mismatch,
    printed. False, and nothing done, without --device, on any other handle,
    and for a program the device can run. `corpus` names the part for the
    count and the mismatch (the trig part's is "routine corpus, trig"), and
    `MR` is its counters."""
    if DEVICE is None or dev.value != DEVICE.handle:
        return False
    over = []
    if DEVICE.max_insns and len(prog.insns) > DEVICE.max_insns:
        over.append(("max_insns", len(prog.insns), DEVICE.max_insns))
    top = routine_top_const(prog)
    if DEVICE.max_consts and top >= DEVICE.max_consts:
        over.append(("max_consts", top, DEVICE.max_consts - 1))
    if DEVICE.max_deposits and prog.max_deposits > DEVICE.max_deposits:
        over.append(("max_deposits", prog.max_deposits, DEVICE.max_deposits))
    if not over:
        return device_refuses(lib, dev, prog, corpus, mask=mask, lf=lf)
    absent = DEVICE.absent(_needs(prog, False, mask, lf))
    names = ([f"cft_caps.{f}" for f, _a, _c in over]
             + [T.CAPS_PLACE[f] for f in absent])
    image = prog.to_bytes()
    handle = ctypes.c_void_p()
    rc = lib.cft_program_load(dev, image, len(image), ctypes.byref(handle))
    msg = lib.cft_last_error().decode("utf-8", "replace") if rc else ""
    if rc == CFT_OK:
        lib.cft_program_free(handle)
    named = [nm for nm in names if nm in msg]
    if rc == CFT_ERR_UNSUPPORTED and named:
        MR["capref"][named[0]] += 1
        return True
    DEVICE.bad += 1
    if DEVICE.bad <= 5:
        print(f"  MISMATCH {prog.fmt.name} ({corpus}, --device): a "
              f"program past "
              f"{', '.join(f'{f} ({a} against {c})' for f, a, c in over)} "
              f"gave rc {rc} at load: {msg!r} - wanted CFT_ERR_UNSUPPORTED "
              f"naming {' or '.join(names)}")
    return True


def routine_rounds(args):
    """Rounds of the eighth corpus: --math-rounds, else one for each 250
    --trials, and at least one, so that every fragment runs."""
    return (args.math_rounds if args.math_rounds is not None
            else max(1, args.trials // 250))


def routine_corpus(lib, dev, fmt, name, args, MR, trig=False):
    """The eighth corpus, for one format. Mutates the counters in MR. With
    `trig` the corpus's second part (parcel M2P): sin, cos and tan, from a
    stream of their own and lanes of their own, MR being that part's
    counters; a format they are not built at (fp32 until parcel M2F) is
    recorded by name in MR["absent"] and nothing is run."""
    mods = routine_modules()
    if mods is None:
        return
    ml, har, fam = mods
    if trig:
        if fmt not in ml.TRIG_FORMATS:
            MR["absent"].append(name)
            return
        th, tf = trig_modules()
    corpus = "routine corpus, trig" if trig else "routine corpus"
    names = ml.TRIG_NAMES if trig else ml.NAMES
    MR["formats"].append(name)
    rounds = routine_rounds(args)
    rng = random.Random((args.seed * 2654435761 + fmt.width * 40503)
                        & 0xFFFFFFFF ^ (TRIG_SALT if trig else ROUTINE_SALT))
    esz = fmt.width // 8
    pat = bytes([ROUTINE_FILL[0]]) * esz
    checked = lanes_done = 0
    for _round in range(rounds):
        for fn in names:
            for rnd in sf.RND_MODES:
                # a stream of its own per fragment, so that the lanes of one
                # never depend on how many another drew
                sub = random.Random(rng.getrandbits(64))
                f, standalone, compiled = routine_programs(fmt, fn, rnd)
                MR["fragments"].add((name, fn, rnd))
                for shape, (prog, bank) in zip(ROUTINE_SHAPES,
                                               (standalone, compiled)):
                    MR["drawn"] += 1
                    tag = f"{fn} {sf.RND_NAMES[rnd]} {shape}"
                    n = sub.choice(ROUTINE_NS)
                    if trig:
                        xs, tags = trig_lanes(ml, th, tf, fmt, fn, rnd, n,
                                              sub)
                    else:
                        xs, tags = routine_lanes(ml, har, fam, fmt, fn, rnd,
                                                 n, sub)
                    keep = None
                    if sub.random() < 1 / 3:
                        keep = [sub.random() < 0.7 for _ in range(n)]
                        if not any(keep):
                            keep[sub.randrange(n)] = True
                    lf = shape == "compiled" or sub.random() < 0.5
                    if routine_refuses(lib, dev, prog, keep is not None, lf,
                                       MR, corpus):
                        continue
                    zeros = [0] * n
                    want = mrun(prog, xs, zeros, zeros, bank=bank,
                                lane_mask=keep)
                    try:
                        dep, counts, fl, st, lb = run_in_c_routine(
                            lib, dev, prog, bank, xs, keep, lf)
                    except RuntimeError as exc:
                        print(f"  MISMATCH {name} ({corpus}) {tag} "
                              f"n={n}: the model runs this fragment and "
                              f"libcft refuses it: {exc}")
                        MR["bad"] += 1
                        continue
                    owned = [i for i in range(n)
                             if keep is None or keep[i]]
                    md = prog.max_deposits
                    diffs = []
                    # the run's accounting: every comparison below tallies
                    # itself in n_cmp, and a run that made fewer than it owes
                    # (a statement gone, a loop cut short) is a difference
                    n_cmp = 1
                    if fl != want.flags:
                        diffs.append(f"FLAGS model 0x{want.flags:02x} "
                                     f"libcft 0x{fl:02x}")
                    n_cmp += 1
                    if st != want.status:
                        diffs.append(f"STATUS model 0x{want.status:02x} "
                                     f"libcft 0x{st:02x}")
                    if lf and lb is None:
                        diffs.append("the lane block was asked for and none "
                                     "came back")
                    compared = lane_bytes = 0
                    for i in range(n):
                        if keep is not None and not keep[i]:
                            # a masked lane: the caller's bytes, untouched
                            if counts[i] != ROUTINE_FILL[1]:
                                diffs.append(f"count[lane {i}] was WRITTEN "
                                             f"({counts[i]:#x}) for a lane "
                                             f"the mask cleared")
                            if dep[i * md * esz:(i + 1) * md * esz] \
                                    != pat * md:
                                diffs.append(f"deposits[lane {i}] were "
                                             f"WRITTEN for a lane the mask "
                                             f"cleared")
                            if lb is not None and lb[i] != ROUTINE_FILL[2]:
                                diffs.append(f"lane byte[{i}] was WRITTEN "
                                             f"(0x{lb[i]:02x}) for a lane "
                                             f"the mask cleared")
                            continue
                        compared += 1
                        n_cmp += 1
                        if counts[i] != want.counts[i]:
                            diffs.append(f"count[lane {i}] model "
                                         f"{want.counts[i]} libcft "
                                         f"{counts[i]}")
                        for s in range(md):
                            n_cmp += 1
                            j = i * md + s
                            g = int.from_bytes(dep[j * esz:(j + 1) * esz],
                                               "little")
                            if g != want.deposits[j]:
                                diffs.append(f"deposit[lane {i} slot {s}] "
                                             f"(x = 0x{xs[i]:x}) model "
                                             f"0x{want.deposits[j]:x} libcft "
                                             f"0x{g:x}")
                                break
                        if lb is not None:
                            lane_bytes += 1
                            n_cmp += 1
                            if lb[i] != want.lane_flags[i]:
                                diffs.append(
                                    f"lane byte[{i}] (x = 0x{xs[i]:x}) "
                                    f"model 0x{want.lane_flags[i]:02x} "
                                    f"libcft 0x{lb[i]:02x}")
                    if compared != len(owned):
                        diffs.append(f"compared {compared} of the "
                                     f"{len(owned)} lanes the run owns")
                    # FLAGS and STATUS, and for each lane compared its count,
                    # each deposit and, with the block, its byte (the mark in
                    # bit 7 among them); a difference already found stops the
                    # deposits at the first, so the tally is held only then
                    owed = 2 + compared * (1 + md + (lb is not None))
                    if not diffs and n_cmp != owed:
                        diffs.append(f"{n_cmp} comparisons made where the "
                                     f"run owes {owed}: FLAGS, STATUS and, "
                                     f"for each of {compared} lanes, the "
                                     f"count, {md} deposit"
                                     f"{'s' if md != 1 else ''}"
                                     f"{' and the lane byte' if lb is not None else ''}")
                    if shape == "stand-alone":
                        # the model's own identity: routines.run's outputs
                        # (the deposits seq.py made) are mathlib.evaluate's,
                        # on the first dozen lanes and on every marked one
                        words = [i for i in owned
                                 if want.deposits[2 * i + 1] & ml.MARK]
                        MR["marked_words"] += len(words)
                        head = owned[:ROUTINE_IDENT]
                        for i in head + [i for i in words if i not in head]:
                            ev = ml.evaluate(f, xs[i])
                            if ev == (want.deposits[2 * i],
                                      want.deposits[2 * i + 1]):
                                MR["ident"] += 1
                            else:
                                diffs.append(
                                    f"model identity: lane {i} (x = "
                                    f"0x{xs[i]:x}) seq.py deposited "
                                    f"(0x{want.deposits[2 * i]:x}, "
                                    f"0x{want.deposits[2 * i + 1]:x}), "
                                    f"mathlib.evaluate gives "
                                    f"(0x{ev[0]:x}, 0x{ev[1]:x})")
                    else:
                        MR["marked_lanes"] += sum(
                            1 for i in owned
                            if want.lane_flags[i] & seq.LANE_MARKED)
                        MR["marked_runs"] += bool(want.status
                                                  & seq.STATUS_MARKED)
                        for label, bit in ROUTINE_FLAGS:
                            MR["raised_" + label] += bool(want.flags & bit)
                    if diffs:
                        MR["bad"] += 1
                        if MR["bad"] <= 3:
                            print(f"  MISMATCH {name} ({corpus}) {tag} "
                                  f"n={n} mask="
                                  f"{'no' if keep is None else 'yes'} "
                                  f"lane block={'yes' if lf else 'no'}: "
                                  f"{len(diffs)} difference"
                                  f"{'s' if len(diffs) != 1 else ''}")
                            for line in diffs[:6]:
                                print(f"    {line}")
                    for i in owned:
                        MR["kind_" + sf.unpack(fmt, xs[i]).kind] += 1
                        MR["cat_" + tags[i]] += 1
                        if trig and tags[i] in ("centre", "family", "near"):
                            # the lanes of the committed marks and families,
                            # by format and attribute (the entry's table)
                            MR[f"{tags[i]} {name} {sf.RND_NAMES[rnd]}"] += 1
                        if trig and tags[i] == "edge":
                            # the range's end, drawn as an edge (not as a
                            # special or a raw pattern, which also reach it)
                            MR["range_end"] += th.past_range(fmt, xs[i])
                    checked += 1
                    lanes_done += compared
                    MR["total"] += 1
                    MR["lanes"] += compared
                    MR["lane_bytes"] += lane_bytes
                    MR[shape] += 1
                    MR["blocked"] += n > 64
                    MR["mask_runs"] += keep is not None
                    MR["masked"] += keep is not None and compared < n
                    MR["masked_lanes"] += n - compared
                    MR["lane_block"] += lf
                    per = MR["by_format"].setdefault(name, [0, 0])
                    per[0] += 1
                    per[1] += compared
    print(f"{name}: {checked} routine-corpus{' (trig)' if trig else ''} "
          f"programs compared, {lanes_done} lanes")


def routine_caps(lib, dev):
    """(max_insns, max_consts, max_deposits, whose) of the handle in use, as
    cft_get_caps publishes them, or None."""
    if DEVICE is not None:
        return (DEVICE.max_insns, DEVICE.max_consts, DEVICE.max_deposits,
                f"the device ({DEVICE.backend})'s")
    c = Caps()
    c.struct_size = ctypes.sizeof(Caps)
    if lib.cft_get_caps(dev, ctypes.byref(c)) != CFT_OK:
        return None
    return (c.max_insns, c.max_consts, c.max_deposits,
            "the software backend's")


def routine_rows(trig):
    """The sizes of the programs this run built (routine_programs): the six's,
    or with `trig` sin's, cos's and tan's, each (format, routine, attribute,
    shape, instructions, bank words, highest register, deposits a lane)."""
    names = routine_modules()[0].TRIG_NAMES
    return sorted(r for r in _ROUTINE["sizes"] if (r[1] in names) == trig)


def routine_limits(caps, trig=False):
    """One line: the routines' programs against libcft's own limits - the
    sizes read off the programs this run built, the limits off the library
    through cft_get_caps. `trig` is the line of sin, cos and tan's."""
    rows = routine_rows(trig)
    if not rows or caps is None:
        return

    def span(col):
        lo = min(r[col] for r in rows)
        hi = max(rows, key=lambda r: r[col])
        return lo, hi[col], f"{hi[1]} {hi[0]} {hi[2]} {hi[3]}"
    ilo, ihi, iat = span(4)
    wlo, whi, wat = span(5)
    rlo, rhi, rat = span(6)
    dlo, dhi, _dat = span(7)
    print(f"the {'trig ' if trig else ''}routines' programs against "
          f"{caps[3]} limits (cft_get_caps; "
          f"{len(rows)} programs): {ilo} to {ihi} instructions against "
          f"max_insns {caps[0]} (the most: {iat}), {wlo} to {whi} bank words "
          f"against max_consts {caps[1]} (the most: {wat}), registers r{rlo} "
          f"to r{rhi} of {seq.NREG} (the most: {rat}), {dlo} to {dhi} "
          f"deposits a lane against max_deposits {caps[2]}, one quiet region "
          f"of the {seq.MAX_QUIET_DEPTH} that nest")


def routine_summary(MC, what, trig=False):
    """The summary line of one part of the eighth corpus: the programs run
    through both, the lanes compared, by class and by source, the flags the
    compiled runs raised and the lanes where the model is its own identity.
    `what` names the part; `trig` gives the sources of sin, cos and tan's
    lanes (trig_lanes) in the place of the six's."""
    by = ", ".join(f"{k} {v[0]} programs and {v[1]} lanes"
                   for k, v in MC["by_format"].items())
    if trig:
        src = (f"{MC['cat_special']} special, {MC['cat_edge']} edge (the "
               f"reduction's worst arguments and the range's end), "
               f"{MC['cat_pool']} radian pools, {MC['cat_centre']} committed "
               f"marks, {MC['cat_family']} family centres, {MC['cat_near']} "
               f"beside a family centre, {MC['cat_struct']} tiny census, "
               f"{MC['cat_random']} random, the edge lanes at or past the "
               f"range's end 2^R {MC['range_end']}")
    else:
        src = (f"{MC['cat_special']} special, {MC['cat_edge']} edge pool, "
               f"{MC['cat_pool']} transcend pools, {MC['cat_centre']} "
               f"committed centres or fp32 marks, {MC['cat_struct']} beside "
               f"them, {MC['cat_random']} random")
    return (f"{MC['total']} programs from {what} run through "
            f"both, {MC['stand-alone']} stand-alone and {MC['compiled']} "
            f"compiled ({by}), {MC['blocked']} across the block boundary: "
            f"{MC['lanes']} lanes compared, {MC['mask_runs']} runs under a "
            f"mask of which {MC['masked']} masked a lane "
            f"({MC['masked_lanes']} lanes masked), {MC['lane_block']} runs "
            f"with the per-lane block asked for ({MC['lane_bytes']} lane "
            f"bytes compared), {MC['marked_lanes']} marked lanes in "
            f"{MC['marked_runs']} compiled runs with STATUS[6] set and "
            f"{MC['marked_words']} marked flag words in the stand-alone "
            f"ones; lanes compared by class: {MC['kind_nan']} NaN, "
            f"{MC['kind_inf']} infinite, {MC['kind_zero']} zero, "
            f"{MC['kind_sub']} subnormal, {MC['kind_norm']} normal; and "
            f"by source: {src}; compiled runs raising "
            + ", ".join(f"{label} {MC['raised_' + label]}"
                        for label, _b in ROUTINE_FLAGS)
            + f"; {MC['ident']} lanes where seq.py's deposits are "
            f"mathlib.evaluate's")


def routine_needed(trig=False):
    """One line: the cft_caps.seq_features bits the programs of one part need,
    counted over the programs this run built (routine_needs, the loader's own
    account of an image) - what the remote leg refuses by name where a word
    lacks the bit. A run asking for the lane block needs LANE_FLAGS besides."""
    names = routine_modules()[0].TRIG_NAMES
    progs = [p for key, (_f, stand, comp) in _ROUTINE["progs"].items()
             if (key[1] in names) == trig for p in (stand[0], comp[0])]
    if not progs:
        return
    need = collections.Counter(x for p in progs for x in routine_needs(p))
    print(f"the {'trig ' if trig else ''}routines' programs need "
          f"({len(progs)} programs; cft_caps.seq_features, its CAPS place): "
          + ", ".join(f"{x} ({T.CAPS_PLACE[x]}) {k}"
                      for x, k in sorted(need.items()))
          + f"; and LANE_FLAGS ({T.CAPS_PLACE['LANE_FLAGS']}) of a run that "
            f"asks for the lane block")


def trig_family_line(MT):
    """One line: the lanes of sin, cos and tan compared that came from the
    committed marks, TRIG_FAMILY's centres and the neighbours of four of them,
    by format and attribute, in a round or the rounds run - the arguments the
    structured families contribute (parcel M2G2b's lists)."""
    parts = []
    for name in MT["formats"]:
        cells = []
        for rnd in sf.RND_MODES:
            r = sf.RND_NAMES[rnd]
            cells.append(f"{r} " + "/".join(
                str(MT[f"{tag} {name} {r}"])
                for tag in ("centre", "family", "near")))
        parts.append(f"{name}: " + ", ".join(cells))
    return ("trig lanes from the committed marks / TRIG_FAMILY's centres / "
            "beside four centres, by format and attribute: "
            + "; ".join(parts))


def routine_expected_refusals(trig=False):
    """The names the remote leg's refusals must have given, by the programs
    this run built (the six's, or with `trig` sin's, cos's and tan's): every
    program needs BANK_PTR and WIDE_CONST (CAPS[6] and CAPS[4]), a compiled
    one FLAG_CONTROL (CAPS2[14]), and a run asking for the block LANE_FLAGS
    (CAPS2[13]); REGS32 (CAPS[5]) only where a program writes past r15 (the
    six's at fp32, the trig programs' at fp64 and fp128), and a capacity only
    where a program is past the one the leg lowers."""
    rows = routine_rows(trig)
    want = {"CAPS[4]", "CAPS[6]", "CAPS2[13]", "CAPS2[14]"}
    if any(r[6] > 15 for r in rows):
        want.add("CAPS[5]")
    if any(r[4] > ROUTINE_LEG_INSNS for r in rows):
        want.add("cft_caps.max_insns")
    if any(r[5] > ROUTINE_LEG_CONSTS for r in rows):
        want.add("cft_caps.max_consts")
    return sorted(want)


def routine_remote_refusals(lib, MR, MT=None):
    """Every program of the corpus, loaded on a remote handle to a fake server
    whose HELLO publishes a revision-7 tile's word (0x7f1f: no R23, no R24),
    and the same word with one bit cleared, and a revision-8 tile's word at a
    capacity lowered - each load refused BY NAME where the program needs what
    the word lacks, and loaded where it does not. The client makes the check
    from the word alone and no load reaches the wire, which the server's record
    holds. A stand-alone program needs BANK_PTR (its bank) and WIDE_CONST (kx),
    and REGS32 at fp32 alone, the other formats staying in r15 - but for the
    trig programs (parcel M2P), which write r25 at fp64 and r16 at fp128; a
    compiled program needs FLAG_CONTROL besides, and a run asking for the lane
    block needs LANE_FLAGS: refused on the client, naming it, before any
    frame. The six's programs count in MR and the trig programs in MT (their
    own counters, so that a trig program dropped from this leg is told from
    the six's still being refused), the leg's own failures in MR."""
    if "mods" not in _ROUTINE or _ROUTINE["mods"] is None:
        return
    trig_names = routine_modules()[0].TRIG_NAMES
    bits = T.FEATURE_BITS
    tile = 0x7F1F
    rev8 = tile | bits["LANE_FLAGS"] | bits["FLAG_CONTROL"]
    legs = [("a revision-7 tile's word", tile, {}),
            ("that word without BANK_PTR", tile & ~bits["BANK_PTR"], {}),
            ("that word without WIDE_CONST", tile & ~bits["WIDE_CONST"], {}),
            ("that word without REGS32", tile & ~bits["REGS32"], {}),
            ("a revision-8 tile's word", rev8, {}),
            (f"a revision-8 tile's word at max_insns {ROUTINE_LEG_INSNS}",
             rev8, {"max_insns": ROUTINE_LEG_INSNS}),
            (f"a revision-8 tile's word at max_consts {ROUTINE_LEG_CONSTS}",
             rev8, {"max_consts": ROUTINE_LEG_CONSTS})]
    first = {}              # the first stand-alone program of each part
    for what, word, caps in legs:
        srv = _FakeServer(word, **caps)
        dev = ctypes.c_void_p()
        url = f"cft://127.0.0.1:{srv.port}".encode()
        if lib.cft_open(url, 0, ctypes.byref(dev)) != CFT_OK:
            print(f"  MISMATCH (routine remote leg): cft_open of the fake "
                  f"server failed: {lib.cft_last_error().decode()}")
            MR["bad"] += 1
            srv.close()
            continue
        try:
            for key, (_f, stand, comp) in _ROUTINE["progs"].items():
                C = MT if MT is not None and key[1] in trig_names else MR
                for shape, (prog, pbank) in zip(ROUTINE_SHAPES,
                                                (stand, comp)):
                    if shape == "stand-alone":
                        first.setdefault(C is MT, (prog, pbank))
                    absent = [x for x in routine_needs(prog)
                              if not word & bits[x]]
                    over = []
                    if len(prog.insns) > srv.max_insns:
                        over.append("cft_caps.max_insns")
                    if routine_top_const(prog) >= srv.max_consts:
                        over.append("cft_caps.max_consts")
                    names = over + [T.CAPS_PLACE[x] for x in absent]
                    image = prog.to_bytes()
                    handle = ctypes.c_void_p()
                    rc = lib.cft_program_load(dev, image, len(image),
                                              ctypes.byref(handle))
                    msg = (lib.cft_last_error().decode("utf-8", "replace")
                           if rc != CFT_OK else "(loaded; no error)")
                    if rc == CFT_OK:
                        lib.cft_program_free(handle)
                    where = f"{key[0]} {key[1]} {sf.RND_NAMES[key[2]]} {shape}"
                    if names:
                        named = [x for x in names if x in msg]
                        # the instruction and the macro too, where the bit is
                        # R24's alone, as the flag-control leg holds it
                        if absent == ["FLAG_CONTROL"] and not over:
                            named = [x for x in named
                                     if "QUIET" in msg
                                     and "CFT_SEQ_FEAT_FLAG_CONTROL" in msg]
                        if rc == CFT_ERR_UNSUPPORTED and named:
                            C["remote_refused"] += 1
                            C["remote_names"][named[0]] += 1
                        else:
                            print(f"  MISMATCH (routine remote leg): "
                                  f"{where} on {what} (0x{word:x}) gave rc "
                                  f"{rc} and {msg!r} - wanted "
                                  f"CFT_ERR_UNSUPPORTED naming "
                                  f"{' or '.join(names)}")
                            C["bad"] += 1
                    elif rc != CFT_OK:
                        print(f"  MISMATCH (routine remote leg): {where} on "
                              f"{what} (0x{word:x}) was refused: rc {rc}, "
                              f"{msg!r}")
                        C["bad"] += 1
                    else:
                        C["remote_loaded"] += 1
            # the block, asked of a run on a server whose word lacks it - and
            # only where the program loads there: a word without BANK_PTR,
            # WIDE_CONST or REGS32 refuses it at load, which the loop above
            # holds, before a run could ask for anything
            for C, part in ((MR, False), (MT, True)):
                if (C is None or word & bits["LANE_FLAGS"]
                        or part not in first
                        or not all(word & bits[x]
                                   for x in routine_needs(first[part][0]))):
                    continue
                prog, pbank = first[part]
                try:
                    run_in_c_routine(lib, dev, prog, pbank, [0, 0], None, True)
                    print(f"  MISMATCH (routine remote leg): a run asking "
                          f"for the per-lane flags ran on {what}")
                    C["bad"] += 1
                except RuntimeError as exc:
                    if "CFT_SEQ_FEAT_LANE_FLAGS" in str(exc):
                        C["remote_refused"] += 1
                        C["remote_names"][T.CAPS_PLACE["LANE_FLAGS"]] += 1
                    else:
                        print(f"  MISMATCH (routine remote leg): the block "
                              f"was refused without its name on {what}: "
                              f"{exc}")
                        C["bad"] += 1
        finally:
            lib.cft_close(dev)
            srv.close()
        if srv.other_ops:
            print(f"  MISMATCH (routine remote leg): a load or run reached "
                  f"the wire on {what}, ops "
                  f"{[hex(o) for o in srv.other_ops]}")
            MR["bad"] += 1
        MR["legs_run"] += 1
        if MT is not None:
            MT["legs_run"] += 1
    for C, what in ((MR, "routine-corpus"), (MT, "trig routine-corpus")):
        if C is None or (C is MT and not C["formats"]):
            continue
        by = ", ".join(f"{k} {v}"
                       for k, v in sorted(C["remote_names"].items()))
        print(f"{what} remote leg: {C['remote_refused']} refused by "
              f"name on servers without a bit or a capacity the program needs "
              f"({by}), {C['remote_loaded']} loaded where published")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--formats", nargs="+", default=["fp32", "fp64"],
                    choices=list(FORMATS))
    ap.add_argument("--trials", type=int, default=400)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--math-rounds", type=int, default=None, metavar="N",
                    help="rounds of the eighth corpus - M1's routines and "
                         "sin, cos and tan, every fragment of the formats in "
                         "both shapes a round, from fresh lanes - where the "
                         "default is one for each 250 --trials and at least "
                         "one (the module's text)")
    ap.add_argument("--device", metavar="ARTIFACT",
                    help="run the corpora through this device's handle - "
                         "an xclbin, cft://host:port, sw, or sw:N (the "
                         "software backend at N scratch slots a lane, as a "
                         "tile of that depth) - at its scratch depth, a "
                         "program needing a bit it does not publish held "
                         "refused by name (the module's text)")
    args = ap.parse_args()

    global DEPTH, DEVICE
    lib = load_library()
    dev = ctypes.c_void_p()
    if args.device is not None and args.device.startswith("sw:"):
        depth = args.device[3:]
        if not depth.isascii() or not depth.isdigit():
            raise SystemExit(f"--device {args.device}: sw:N takes N, a "
                             f"power of two of scratch slots a lane")
        oa = OpenArgs()
        oa.struct_size = ctypes.sizeof(OpenArgs)
        oa.artifact, oa.index, oa.scratch_depth = None, 0, int(depth)
        st = lib.cft_open_ex(ctypes.byref(oa), ctypes.byref(dev))
    else:
        artifact = None if args.device in (None, "sw") else args.device
        st = lib.cft_open(artifact.encode("utf-8") if artifact else None, 0,
                          ctypes.byref(dev))
    if st != CFT_OK:
        raise SystemExit(f"cft_open({args.device or 'the software backend'}): "
                         f"{lib.cft_strerror(st).decode()}: "
                         f"{lib.cft_last_error().decode('utf-8', 'replace')}")
    if args.device is not None:
        caps = Caps()
        caps.struct_size = ctypes.sizeof(Caps)
        st = lib.cft_get_caps(dev, ctypes.byref(caps))
        if st != CFT_OK:
            raise SystemExit(f"cft_get_caps({args.device}): "
                             f"{lib.cft_strerror(st).decode()}")
        DEVICE = _Device(dev, caps)
        # A device that publishes no depth (0, unknown) is held at the
        # model's own, which is the library's for such a device too
        DEPTH = DEVICE.max_scratch or seq.SCRATCH_D
        print(f"device {args.device}: backend {DEVICE.backend}, "
              f"{DEVICE.tiles} tile{'s' if DEVICE.tiles != 1 else ''}, "
              f"contract 0x{DEVICE.version:08x}, seq_features "
              f"0x{DEVICE.features:x}, max_scratch {DEVICE.max_scratch}; "
              f"the model runs at {DEPTH} scratch slots a lane")
        lacks = [f for f in T.FEATURE_BITS
                 if not DEVICE.features & T.FEATURE_BITS[f]]
        print(f"  it does not publish: "
              f"{', '.join(f'{f} ({T.CAPS_PLACE[f]})' for f in lacks)}"
              if lacks else "  it publishes every bit cft.h defines")

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
    # ...and the eighth's (M1's routines, parcel MP): a defaultdict, since it
    # counts lanes by their class and runs by the flags they raised; and its
    # second part's (sin, cos and tan, parcel M2P), kept apart so that a form
    # it fails to reach is named as the trig part's and not hidden in the
    # six's totals
    MR = routine_counters()
    MT = routine_counters()
    if args.math_rounds is not None and args.math_rounds < 1:
        ap.error("--math-rounds takes at least 1")
    try:
        for name in args.formats:
            fmt = FORMATS[name]
            if DEVICE is not None and \
                    not DEVICE.format_mask & (1 << FORMAT_CODE[name]):
                # each corpus draws from its own seed per format, so the
                # formats compared draw what they always drew
                print(f"{name}: NOT COMPARED - the device does not carry "
                      f"it (format_mask 0x{DEVICE.format_mask:x})")
                continue
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
                    prog = mprog(fmt, insns, consts, maxdep)
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

                want = mrun(prog, a, b, c)
                if device_refuses(lib, dev, prog, "first corpus"):
                    continue
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
            routine_corpus(lib, dev, fmt, name, args, MR)
            routine_corpus(lib, dev, fmt, name, args, MT, trig=True)
        MR["caps"] = MT["caps"] = routine_caps(lib, dev)  # before it closes
    finally:
        lib.cft_close(dev)
    rev8_remote_refusals(lib, R)
    flags_remote_refusals(lib, F)
    routine_remote_refusals(lib, MR, MT)
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
    if MR["total"]:
        print(routine_summary(MR, "the routine corpus"))
        routine_limits(MR["caps"])
        routine_needed()
    if MT["total"]:
        # sin, cos and tan (parcel M2P), beside the six; fp32 is named, not
        # skipped: a by-design absence until parcel M2F builds them
        print(routine_summary(MT, "the routine corpus's trig part (sin, cos "
                                  "and tan)", trig=True)
              + ("" if not MT["absent"] else
                 f"; {', '.join(MT['absent'])}: sin, cos and tan not built "
                 f"(parcel M2F's)"))
        routine_limits(MT["caps"], trig=True)
        routine_needed(trig=True)
        print(trig_family_line(MT))
    elif MT["absent"]:
        print(f"{', '.join(MT['absent'])}: sin, cos and tan not built "
              f"(parcel M2F's)")
    bad += (S["bad"] + X["bad"] + M["bad"] + R["bad"] + ceiling_bad
            + F["bad"] + MR["bad"] + MT["bad"])
    if DEVICE is not None:
        # --device: what the device refused by name, corpus by corpus
        by = collections.defaultdict(list)
        for (corpus, place), k in sorted(DEVICE.refused.items()):
            by[corpus].append(f"{place} {k}")
        for corpus, parts in by.items():
            print(f"{corpus}: {DEVICE.refused_in(corpus)} programs NOT "
                  f"COMPARED - each needs a bit the device does not "
                  f"publish, and each was refused by name "
                  f"(CFT_ERR_UNSUPPORTED naming {', '.join(parts)})")
        for MC, what in ((MR, "routine corpus"),
                         (MT, "routine corpus, trig")):
            if MC["capref"]:
                refs = ", ".join(f"{k} {v}"
                                 for k, v in sorted(MC["capref"].items()))
                print(f"{what}: {sum(MC['capref'].values())} programs "
                      f"NOT COMPARED - each is past a capacity the device "
                      f"publishes, and each was refused by name "
                      f"(CFT_ERR_UNSUPPORTED naming {refs})")
        if not by and not MR["capref"] and not MT["capref"]:
            print("the device refused no program for a bit it lacks: every "
                  "program was compared")
        bad += DEVICE.bad

    def relaxed(*corpora):
        """Under --device, a corpus the device refused programs of by name
        has forms only those programs carry - so a form not reached among
        the programs it ran is named, not failed."""
        held = DEVICE.refused_in if DEVICE is not None else (lambda c: 0)
        n_held = sum(held(c) for c in corpora)
        if n_held:
            print(f"NOTE (--device): the {corpora[0]} did not reach every "
                  f"form among the programs the device ran; {n_held} of its "
                  f"programs were refused by name instead (above)")
        return n_held > 0

    routine_held = sum(MR["capref"].values())
    trig_held = sum(MT["capref"].values())
    routine_ran = routine_modules() is not None
    for MC, part, what, trig in (
            (MR, "THE ROUTINE CORPUS", "routine corpus", False),
            (MT, "THE ROUTINE CORPUS'S TRIG PART",
             "routine corpus, trig", True)):
        said = "routine corpus's trig part" if trig else what
        if not routine_ran or (trig and not MC["formats"]):
            continue
        held_here = sum(MC["capref"].values())
        # the drawn programs against the corpus's own arithmetic: every
        # routine at every attribute in both shapes, a round at a time, at
        # every format that was run - so a loop that drops a fragment, a
        # shape or a round is counted short here, whatever else it compares
        mlib = routine_modules()[0]
        frags = len(mlib.TRIG_NAMES if trig else mlib.NAMES)             * len(sf.RND_MODES)
        per_format = frags * len(ROUTINE_SHAPES)
        rounds = routine_rounds(args)
        want_drawn = rounds * per_format * len(MC["formats"])
        short = [] if MC["drawn"] == want_drawn else [
            f"{MC['drawn']} programs were drawn where {rounds} round"
            f"{'s' if rounds != 1 else ''} of {per_format} programs at each "
            f"of {len(MC['formats'])} formats is {want_drawn}"]
        for k in MC["formats"]:
            have = len({f for f in MC["fragments"] if f[0] == k})
            if have != frags:
                short.append(f"{k} ran {have} of {frags} fragments")
        if short:
            print(f"{part} DID NOT RUN EVERY FRAGMENT - "
                  + "; ".join(short))
            return 1
        # the remote leg: every one of its servers, and every name the
        # programs here can be refused by, given at least once
        gaps = []
        if MC["legs_run"] != ROUTINE_LEGS:
            gaps.append(f"the remote leg ran {MC['legs_run']} of its "
                        f"{ROUTINE_LEGS} servers")
        unnamed = [nm for nm in routine_expected_refusals(trig)
                   if not MC["remote_names"][nm]]
        if unnamed:
            gaps.append(f"the remote leg never refused by name: "
                        f"{', '.join(unnamed)}")
        if gaps:
            print(f"{part} DID NOT REACH EVERY FORM - "
                  + "; ".join(gaps))
            return 1
        if MC["total"] or held_here:
            # sin, cos and tan raise no divideByZero and no overflow
            # (TRIG_NEVER_RAISED): counted in the summary, not required
            flags = [f"raised_{label}" for label, _b in ROUTINE_FLAGS
                     if not (trig and label in TRIG_NEVER_RAISED)]
            sources = (["cat_" + t for t in TRIG_SOURCES] if trig else
                       ["cat_special", "cat_edge", "cat_pool", "cat_centre",
                        "cat_struct", "cat_random"])
            if trig and any(mlib.TRIG_RANGE[k] for k in MC["formats"]):
                sources.append("range_end")     # fp128 and fp256 have a range
            zero = [k for k in (
                ["blocked", "masked", "lane_bytes", "marked_lanes",
                 "marked_runs", "marked_words", "kind_nan", "kind_inf",
                 "kind_zero", "kind_sub", "kind_norm"] + flags
                + ["ident", "remote_refused", "remote_loaded"] + sources)
                if not MC[k]]
            held = (DEVICE.refused_in(what) if DEVICE is not None
                    else 0) + held_here
            if zero and held:
                print(f"NOTE (--device): the {said} did not reach every "
                      f"form among the programs the device ran "
                      f"({', '.join(zero)} counted nothing); {held} of its "
                      f"programs were refused by name instead (above)")
            elif zero:
                print(f"{part} DID NOT REACH EVERY FORM - "
                      f"{', '.join(zero)} counted nothing, so a block "
                      f"boundary, a mask, the lane block, a mark, a class or "
                      f"a source of lane, a flag, the model's identity or a "
                      f"remote refusal went uncompared")
                return 1

    if F["total"] and not all(F[k] for k in (
            "refused", "blocked", "directed", "quiet", "nested",
            "raise_quiet", "raise_loud", "marked", "masked", "range",
            "overflow", "remote_refused", "remote_loaded")) and \
            not relaxed("flag-control corpus"):
        print("THE FLAG-CONTROL CORPUS DID NOT REACH EVERY FORM - a counter "
              "above is zero, so a region, a raise, the mark, a mask, a "
              "report or the remote refusal went uncompared")
        return 1
    if R["total"] and not all(R[k] for k in (
            "refused", "blocked", "augadd", "augerr", "pair", "ldx_step",
            "stx_step", "walks", "strict", "range", "inv", "ovf", "unf",
            "remote_refused", "remote_loaded", "directed",
            "own_index", "own_index_range")) and \
            not relaxed("revision-8 corpus", "revision-8 own-index leg"):
        print("THE REVISION-8 CORPUS DID NOT REACH EVERY FORM - a counter "
              "above is zero, so a form, a flag class, the strict report "
              "or the remote refusal went uncompared")
        return 1
    if M["total"] and not (M["kept"] and M["masked_lanes"] and M["zeros"]
                           and M["allones"] and M["holed"]) and \
            not relaxed("masked corpus"):
        print("THE MASKED CORPUS DID NOT REACH EVERY FORM - no lane was "
              "masked, no lane ran, no all-zero mask was drawn, or no "
              "all-ones/holed control pair, which would mean R17 was not "
              "actually compared")
        return 1
    if X["total"] and not (X["tables"] and X["none"] and X["oob"]
                           and X["identity"] and X["permuted"]) and \
            not relaxed("indexed corpus"):
        print("THE INDEXED CORPUS DID NOT REACH EVERY FORM - no table, "
              "no CFT_IDX_NONE entry, no index refused at the source's "
              "length, or no identity/permuted control pair, which "
              "would mean R16 was not actually compared")
        return 1
    if S["total"] and not (S["stl"] and S["ldl"] and S["stx"]
                           and S["ldx"] and S["io"] and S["kx9"]
                           and S["refused"] and S["strict"]
                           and S["range"]) and \
            not relaxed("scratch corpus"):
        print("THE SCRATCH CORPUS DID NOT REACH EVERY FORM - a code, "
              "the block or the ninth bit went uncompared, no refusal "
              "was exercised, or no SCRATCH_STRICT program reported an "
              "out-of-range index (revision 4 R8), which would mean the "
              "strict path was never actually compared")
        return 1
    if DEVICE is not None:
        # every corpus exercised: something compared, or refused by name
        corpora = [("scratch corpus", S["total"]),
                   ("indexed corpus", X["total"]),
                   ("masked corpus", M["total"]),
                   ("revision-8 corpus", R["total"]),
                   ("flag-control corpus", F["total"])]
        if routine_ran:
            corpora.append(("routine corpus", MR["total"] + routine_held))
            if MT["formats"]:
                corpora.append(("routine corpus, trig",
                                MT["total"] + trig_held))
        for corpus, compared in corpora:
            if total and not compared and not DEVICE.refused_in(corpus):
                print(f"THE {corpus.upper()} COMPARED NOTHING AND THE DEVICE "
                      f"REFUSED NOTHING OF IT - it was not exercised")
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
    if DEVICE is not None:
        print(f"the device ({args.device}) and the golden model agree on "
              f"every program it ran: deposits, counts, flags and status, "
              f"and every lane byte where asked; it refused by name every "
              f"program needing a bit it does not publish")
        return 0
    print("libcft and the golden model agree on every program: deposits, "
          "counts, flags and status")
    return 0


if __name__ == "__main__":
    sys.exit(main())
