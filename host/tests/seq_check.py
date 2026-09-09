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
"""

import argparse
import ctypes
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from cft_golden import FORMATS  # noqa: E402
from cft_golden import seq  # noqa: E402

CFT_OK = 0


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
    """cft_run_args, field for field (host/include/cft.h, ABI 0.10)."""
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
                ("bus_out", ctypes.POINTER(ctypes.c_uint32))]


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
        # STX takes its slot from rb; imm[23:0] is read by nothing
        out.insert(0, seq.encode(seq.STX, ra=0, rb=1, ctrl=True, imm=1))
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
        flags = seq.FLAG_SCRATCH_IO if io else 0
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
        n = rng.choice([1, 2, 63, 64, 65, 100, 129])
        if n > 64:
            S["blocked"] += 1
        a = seq.random_inputs(fmt, rng, n)
        b = seq.random_inputs(fmt, rng, n)
        c = seq.random_inputs(fmt, rng, n)
        sin = seq.random_inputs(fmt, rng, n * nsin) if nsin else None
        want = seq.run(prog, a, b, c, scratch_in=sin)
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
             io=0, kx9=0, blocked=0)
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
    finally:
        lib.cft_close(dev)

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
          f"block declared, {S['kx9']} constant indices at or past 256")
    bad += S["bad"]
    if S["total"] and not (S["stl"] and S["ldl"] and S["stx"]
                           and S["ldx"] and S["io"] and S["kx9"]
                           and S["refused"]):
        print("THE SCRATCH CORPUS DID NOT REACH EVERY REVISION-3 FORM - "
              "a code, the block or the ninth bit went uncompared, or "
              "no refusal was exercised")
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
