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
    finally:
        lib.cft_close(dev)

    print(f"\n{total} programs run through both implementations, "
          f"{refused_both} refused by both")
    print(f"{blocked} of them crossed libcft's 64-lane block boundary")
    print(f"{extended} programs drawn from the extended corpus: "
          f"{saw_imul} IMUL instructions, {saw_kx} indexed-constant "
          f"instructions, {saw_wide} constant indices above "
          f"{seq.KADDR_PLAIN - 1}")
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
