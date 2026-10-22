# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Two loaders, one image with two faults: do they name the same fault?

    python3 host/tests/loader_order_check.py [--lib PATH]

host/src/program.c's cft_program_load and python/cft_golden/seq.py's
Program.from_bytes are two ports of one specification (docs/SEQUENCER.md,
"What the loader refuses"). An image with ONE fault is refused by both -
host/tests/seq_check.py's refusal corpus holds that over corrupted valid
programs, host/fuzz/program_differential.py over mutated bytes - but an
image with TWO is refused for whichever fault a loader reaches first, and
until 2026-10-22 (KL-438) the two reached them in different orders: the
C loader read the header's flags after its scratch word, checked the
image's length after the capacities, took the register high bits operand by
operand and a register operand's ninth bit before its byte, tested imm[31]
before kx, left a static scratch slot to its device pass, and met the
worst-case bound at the top of every instruction where the model meets it
at the bottom of a control instruction. Both refused, with true sentences,
and named different faults; and the model's sentence for a constant under
kx gave the low byte of a nine-bit index.

Against the base's library (f707fa3b's cft.dll) THIS check, as committed,
finds 653 disagreements over its 26,889 images with the committed seq.py
and 726 with the base's own seq.py, the 73 more being that sentence. The
653 are 398 + 70 + 7 + 134 + 34 + 3 + 7: the register high bits, the
ninth bit before the byte, imm[31] before kx, the worst-case bound (115
named at another instruction, 19 named ahead of an instruction's own
fault), the static slot, the flags before the scratch word, the length
before the capacities, in that order. The first version of this check,
before its 2^64 and closing-test images and its comparison of the
constant, found 580 over 26,745 with the base's seq.py (398 + 70 + 7 +
64 + 31 + 3 + 7); those are that version's figures, not this one's.

This feeds both loaders images with two faults, and compares the faults
BY NAME: each sentence is read back to the rule it states and the
instruction it names (RULES below, one row per refusal the model can make,
in the words of each side), and the two must give the same rule at the
same instruction - and, for a constant under kx or past the bank, the same
operand and the same constant (FACTS: the nine-bit index). The words differ
by design - libcft's sentences name the opcode and the field in its own
style, the model's are shorter - so what is compared is the fault, not the
string; but a sentence this file cannot place is a failure too, so a
refusal added to either loader without a row here is seen.

It runs the software device, which accepts every format and feature, so
what only a device can refuse is not here: libcft makes those refusals
after all of the model's (seq_check_header_against_device and
seq_check_against_device in program.c), which this file cannot see. (A
capacity a device publishes for a quantity the model also bounds, the
deposit budget and the scratch block, is refused at the device's number
where the model's bound comes; on this device the two are one number.)

Where the library cannot be loaded, or has no sequencer, it prints
"SKIP loader-order check: ..." (the form verify/run.sh counts) and exits 0;
where the file is not there it fails.

The images:
  * every fault alone, which both loaders must name as the rule it is
    (this holds the table itself);
  * every ordered pair of the faults that stand alone - a header fault and
    a stream fault, two header faults, two stream faults, each stream
    fault before and after the other;
  * every pair, triple and quadruple of the field faults of one ALU
    instruction, and every one, pair, triple and quadruple of those of one
    control instruction at each of the sixteen codes (15 is no control
    code), set in the one word.
"""

import argparse
import ctypes
import itertools
import os
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from cft_golden import seq                                  # noqa: E402

MAGIC = 0x50544643
FL_BANK_EXT, FL_SCRATCH_IO = 1, 2
M64 = (1 << 64) - 1

# ---- the refusals, as each side words them ---------------------------------
# key, the model's words, libcft's words. First match wins, so the more
# particular row comes first.
RULES = [
    ("short", r"shorter than a header", r"shorter than the 32-byte header"),
    ("magic", r"bad magic", r"magic is 0x"),
    ("version", r"program version", r"program-image version"),
    ("flags", r"header flags .* set a bit this loader does not know",
     r"header flags are 0x"),
    ("word7", r"header word 7 is", r"header word 7, scratch_io"),
    ("prec", r"precision code \d+ is not on the ladder",
     r"precision code is \d+, which is not on the ladder"),
    ("length", r"bytes, header describes", r"and its header describes"),
    ("max_deposits", r"max_deposits=\d+, cap", r"max_deposits is"),
    ("n_consts", r"n_consts=\d+: an index is nine bits",
     r"header declares \d+ constants \(n_consts\)"),
    ("scratch_block", r"n_scratch_(in|out)=\d+ past the",
     r"n_scratch_(in|out) is|scratch block preloads"),
    ("kx_selects_nothing", r"kx is set and no operand names a constant",
     r"sets kx and no operand names a constant"),
    ("imm31", r"imm\[31\] is reserved", r"imm\[31\] is reserved"),
    ("imm_without_kx", r"without kx has no immediate",
     r"has no kx, so it reads no immediate|"
     r"has no kx, so the ninth constant-index bits"),
    ("high_bit_on_constant", r"names a constant, so its register high bit",
     r"names a constant, so its register high bit"),
    ("field_under_kx",
     r"names constant \d+ through imm under kx, so the \w+ field must be zero",
     r"names constant \d+ through imm under kx, so the \w+ field must be "
     r"zero"),
    ("byte_on_register", r"names a register, so its byte of imm is not read",
     r"names a register under kx, so its byte of imm"),
    ("ninth_on_register",
     r"names a register, so its ninth constant-index bit",
     r"names a register, so its ninth constant-index bit"),
    ("index_past_bank", r"names constant \d+ but the bank holds",
     r"names constant \d+, and the program's header declares"),
    ("rnd_reserved", r"rnd=\d+ is reserved",
     r"its rounding attribute rnd is"),
    ("unknown_control", r"unknown control code",
     r"is control code \d+, and the control codes are"),
    ("control_reads_no_reg", r"does not read (rd|ra|rb|rc), so it must be",
     r"which does not read (rd|ra|rb|rc), so it must be zero"),
    ("control_reads_no_flag",
     r"does not read (rnd|ka|kb|kc|kx), so it must be",
     r"which does not read (rnd|ka|kb|kc|kx)"),
    ("control_imm", r"reads only imm &", r"which reads only imm &"),
    ("scratch_slot", r"names scratch slot", r"scratch slot is"),
    ("repeat_zero", r"repeat 0 is not a loop",
     r"is REPEAT 0, which is not a loop"),
    ("loops_too_deep", r"loops nest deeper than",
     r"is a REPEAT inside \d+ open loops"),
    ("endrep_without_repeat", r"endrep without repeat",
     r"an ENDREP with no REPEAT open"),
    ("endrep_around_region", r"endrep closes its loop while the quiet region",
     r"an ENDREP that closes its loop while the quiet region"),
    ("regions_too_deep", r"quiet regions nest deeper than",
     r"is a QUIET inside \d+ open quiet regions"),
    ("endquiet_without_quiet", r"endquiet with no quiet region open",
     r"an ENDQUIET with no quiet region open"),
    ("endquiet_around_loop", r"endquiet inside the loop opened at",
     r"an ENDQUIET inside the loop opened at"),
    ("actall_in_loop", r"actall inside a loop", r"ACTALL inside a loop"),
    ("halt_in_loop", r"halt inside a loop", r"HALT inside a loop"),
    ("halt_in_region", r"halt inside the quiet region opened at",
     r"HALT inside the quiet region"),
    ("worst_case", r"worst-case instruction count",
     r"worst-case instruction count"),
    ("loops_left_open", r"loop\(s\) left open at the end",
     r"inside \d+ open loop"),
    ("regions_left_open", r"quiet region\(s\) left open at the end",
     r"inside \d+ open quiet region"),
]
RX = [(k, re.compile(m), re.compile(c)) for k, m, c in RULES]
PC = (re.compile(r"^\[(\d+)\] "), re.compile(r"^instruction (\d+)\b"))


# What two sentences of one rule must also agree on: the operand, the
# constant it names - the nine-bit index, where the model's sentence gave the
# low byte of it until 2026-10-22 (KL-438) - and the number beside it.
FACTS = {
    "field_under_kx": re.compile(r"(\w+) names constant (\d+) through imm "
                                 r"under kx, so the \w+ field must be zero"
                                 r",? and it is (\d+)"),
    "index_past_bank": re.compile(r"(\w+) names constant (\d+)\D+(\d+)"),
}


def facts(msg, key):
    rx = FACTS.get(key)
    m = rx.search(msg) if rx else None
    return m.groups() if m else None


def named(msg, side):
    """(rule, instruction or None) a sentence states; side 0 the model's,
    1 libcft's. A sentence no row places is ("?", the sentence)."""
    m = PC[side].match(msg)
    pc = int(m.group(1)) if m else None
    for row in RX:
        if row[1 + side].search(msg):
            return row[0], pc
    return "?", msg


# ---- the two loaders -------------------------------------------------------

class Skip(Exception):
    """This check cannot run here; the reason is printed by name."""


def load_library(path):
    try:
        lib = ctypes.CDLL(str(path))
        lib.cft_program_load
    except OSError as e:
        raise Skip("%s cannot be loaded by this Python (%s): a library of "
                   "another architecture, or one the loader cannot resolve"
                   % (path, e))
    except AttributeError:
        raise Skip("%s has no cft_program_load: a build without the "
                   "sequencer (CFT_NO_PROGRAM)" % path)
    lib.cft_open.argtypes = [ctypes.c_char_p, ctypes.c_int,
                             ctypes.POINTER(ctypes.c_void_p)]
    lib.cft_open.restype = ctypes.c_int
    lib.cft_close.argtypes = [ctypes.c_void_p]
    lib.cft_program_load.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                     ctypes.c_size_t,
                                     ctypes.POINTER(ctypes.c_void_p)]
    lib.cft_program_load.restype = ctypes.c_int
    lib.cft_program_free.argtypes = [ctypes.c_void_p]
    lib.cft_last_error.argtypes = []
    lib.cft_last_error.restype = ctypes.c_char_p
    return lib


def libcft_says(lib, dev, image):
    """None if libcft loads the image, else its sentence."""
    handle = ctypes.c_void_p()
    st = lib.cft_program_load(dev, image, len(image), ctypes.byref(handle))
    if st == 0:
        lib.cft_program_free(handle)
        return None
    return (lib.cft_last_error() or b"").decode("utf-8", "replace")


def model_says(image):
    try:
        seq.Program.from_bytes(image)
        return None
    except seq.ProgramError as e:
        return str(e)


# ---- images ----------------------------------------------------------------

def W(op, rd=0, ra=0, rb=0, rc=0, rnd=0, ka=0, kb=0, kc=0, kx=0, ctrl=0,
      imm=0):
    """One instruction word, field by field: the raw encoding, which is not
    seq.encode's (that refuses what this builds)."""
    return (op | rd << 8 | ra << 12 | rb << 16 | rc << 20 | rnd << 24 |
            ka << 27 | kb << 28 | kc << 29 | kx << 30 | ctrl << 31 |
            (imm & 0xFFFFFFFF) << 32) & M64


ADD = W(1, rd=1)                       # add r1 = r0 + r0: clean
HALT, ENDREP, ACTALL = W(0, ctrl=1), W(2, ctrl=1), W(5, ctrl=1)
QUIET, ENDQUIET = W(12, ctrl=1), W(13, ctrl=1)


def REPEAT(n):
    return W(1, ctrl=1, imm=n)


def base():
    return dict(magic=MAGIC, ver=1, prec=0, flags=0, word7=0, maxdep=1,
                consts=[0x3F800000, 0x40000000], n_consts=None, insns=[ADD],
                trailer=b"", cut=None)


def assemble(s):
    esz = {0: 4, 1: 8, 2: 16, 3: 32}.get(s["prec"], 4)
    n = len(s["consts"]) if s["n_consts"] is None else s["n_consts"]
    out = struct.pack("<8I", s["magic"], s["ver"], len(s["insns"]), n,
                      s["maxdep"], s["prec"], s["flags"], s["word7"])
    if not s["flags"] & FL_BANK_EXT:
        out += b"".join(k.to_bytes(esz, "little") for k in s["consts"])
    out += b"".join(struct.pack("<Q", w) for w in s["insns"]) + s["trailer"]
    return out[:s["cut"]] if s["cut"] is not None else out


# A header fault is a change to the spec; a stream fault is the words it
# adds to a clean program. Each is (name, change or words, the rule it is).
HEADER = [
    ("short", dict(cut=31), "short"),
    ("magic", dict(magic=0x12345678), "magic"),
    ("version", dict(ver=2), "version"),
    ("flag bit", dict(flags=0x80), "flags"),
    ("scratch_io word without its flag", dict(word7=0x00010002), "word7"),
    ("precision code", dict(prec=4), "prec"),
    ("length", dict(trailer=b"\0"), "length"),
    ("max_deposits", dict(maxdep=(1 << 20) + 1), "max_deposits"),
    ("n_consts", dict(flags=FL_BANK_EXT, n_consts=513, consts=[]),
     "n_consts"),
    ("scratch block", dict(flags=FL_SCRATCH_IO, word7=300), "scratch_block"),
]
STREAM = [
    ("kx, no constant", [W(1, rd=1, kx=1)], "kx_selects_nothing"),
    ("imm[31]", [W(1, rd=1, imm=1 << 31)], "imm31"),
    ("imm[23:0] without kx", [W(1, rd=1, imm=5)], "imm_without_kx"),
    ("imm[30:28] without kx", [W(1, rd=1, imm=1 << 29)], "imm_without_kx"),
    ("high bit on a constant", [W(1, rd=1, kb=1, imm=1 << 26)],
     "high_bit_on_constant"),
    ("ninth bit on a register", [W(1, rd=1, kb=1, kx=1, imm=(1 << 8) |
                                   (1 << 28))], "ninth_on_register"),
    ("register field under kx", [W(1, rd=1, rb=3, kb=1, kx=1, imm=1 << 8)],
     "field_under_kx"),
    ("byte on a register", [W(1, rd=1, kb=1, kx=1, imm=5 | (1 << 8))],
     "byte_on_register"),
    ("index past the bank", [W(1, rd=1, rb=5, kb=1)], "index_past_bank"),
    ("nine-bit index past the bank",
     [W(1, rd=1, kb=1, kx=1, imm=(0x10 << 8) | (1 << 29))],
     "index_past_bank"),
    ("rnd 5", [W(1, rd=1, rnd=5)], "rnd_reserved"),
    ("control code 15", [W(15, ctrl=1)], "unknown_control"),
    ("HALT reading rb", [W(0, rb=3, ctrl=1)], "control_reads_no_reg"),
    ("ACTALL with rnd", [W(5, rnd=2, ctrl=1)], "control_reads_no_flag"),
    ("DEPOSIT with a stray imm bit", [W(3, ctrl=1, imm=1 << 24)],
     "control_imm"),
    ("STL slot 300", [W(6, ctrl=1, imm=300)], "scratch_slot"),
    ("REPEAT 0", [REPEAT(0), ENDREP], "repeat_zero"),
    ("five nested loops", [REPEAT(1)] * 5 + [ENDREP] * 5, "loops_too_deep"),
    ("ENDREP, no REPEAT", [ENDREP], "endrep_without_repeat"),
    ("ENDREP around a region", [REPEAT(2), QUIET, ENDREP, ENDQUIET],
     "endrep_around_region"),
    ("five nested regions", [QUIET] * 5 + [ENDQUIET] * 5,
     "regions_too_deep"),
    ("ENDQUIET, no QUIET", [ENDQUIET], "endquiet_without_quiet"),
    ("ENDQUIET around a loop", [QUIET, REPEAT(2), ENDQUIET, ENDREP],
     "endquiet_around_loop"),
    ("ACTALL in a loop", [REPEAT(2), ACTALL, ENDREP], "actall_in_loop"),
    ("HALT in a loop", [REPEAT(2), HALT, ENDREP], "halt_in_loop"),
    ("HALT in a region", [QUIET, HALT, ENDQUIET], "halt_in_region"),
    ("worst case past 2^40, an ALU instruction takes it",
     [REPEAT(1 << 20), REPEAT(1 << 20), ADD, ENDREP, ENDREP], "worst_case"),
    ("trip-count product past 2^40",
     [REPEAT(1 << 20), REPEAT(1 << 21), ENDREP, ENDREP], "worst_case"),
    ("trip-count product past 2^64",
     [REPEAT(1 << 16), REPEAT(1 << 17), REPEAT(1 << 31), ENDREP, ENDREP,
      ENDREP], "worst_case"),
    # 2^40 - 3 at the last ENDREP (1 + 2a + ab, a = 2097148, b = 524287),
    # then four ALU instructions at depth 0 take it to 2^40 + 1: the only way
    # past the bound with no control instruction after it, so the closing test
    ("the bound passed only by the ALU instructions after the last loop",
     [REPEAT(2097148), REPEAT(524287), ENDREP, ENDREP, ADD, ADD, ADD, ADD],
     "worst_case"),
    ("a loop left open", [REPEAT(2)], "loops_left_open"),
    ("a region left open", [QUIET], "regions_left_open"),
]

# The field faults of one word, set together. An ALU word's faults carry
# what each needs to be the fault it is (a register operand under kx needs
# another operand to name a constant, or kx selects nothing), and the masks
# are ORed, so a word may hold two, three or four faults at once, and either
# loader may reach any of them first. The same at each control code.
K = 32                                  # imm[0] is word bit 32
ALU_FAULTS = [
    ("kx alone", 1 << 30),
    ("imm[31]", 1 << 63),
    ("imm[23:0] = 5", 5 << K),
    ("imm[29]", 1 << (K + 29)),
    ("a names a constant, its high bit set", (1 << 27) | (1 << (K + 25))),
    ("b names a constant, its high bit set", (1 << 28) | (1 << (K + 26))),
    ("c names a constant, its high bit set", (1 << 29) | (1 << (K + 27))),
    ("b under kx with its register field set",
     (1 << 28) | (1 << 30) | (1 << (K + 8)) | (3 << 16)),
    ("register a under kx with a byte of imm",
     (1 << 28) | (1 << 30) | (1 << (K + 8)) | (5 << K)),
    ("register a under kx with its ninth bit",
     (1 << 28) | (1 << 30) | (1 << (K + 8)) | (1 << (K + 28))),
    ("register c under kx with its ninth bit",
     (1 << 28) | (1 << 30) | (1 << (K + 8)) | (1 << (K + 30))),
    ("register c under kx with a byte of imm",
     (1 << 28) | (1 << 30) | (1 << (K + 8)) | (7 << (K + 16))),
    ("a four-bit index past the bank", (1 << 27) | (5 << 12)),
    ("a nine-bit index past the bank",
     (1 << 28) | (1 << 30) | (0x10 << (K + 8)) | (1 << (K + 29))),
    ("rnd 5", 5 << 24),
]
CTRL_FAULTS = [
    ("rd = 3", 3 << 8), ("ra = 3", 3 << 12), ("rb = 3", 3 << 16),
    ("rc = 3", 3 << 20), ("rnd = 1", 1 << 24), ("ka", 1 << 27),
    ("kb", 1 << 28), ("kc", 1 << 29), ("kx", 1 << 30),
    ("imm = 5", 5 << K), ("imm[13]", 1 << (K + 13)),
    ("imm[24]", 1 << (K + 24)), ("imm[31]", 1 << 63),
    ("imm = 300", 300 << K),
]


def with_stream(words):
    s = base()
    s["insns"] = list(words)
    return s


def images():
    """(label, bytes) for every image this checks."""
    for name, change, key in HEADER:
        s = base()
        s.update(change)
        yield "header: " + name, assemble(s), (key,)
    for name, words, key in STREAM:
        yield "stream: " + name, assemble(with_stream(words)), (key,)
    # pairs
    for (n1, c1, k1), (n2, c2, k2) in itertools.product(HEADER, HEADER):
        if n1 != n2:
            s = base()
            s.update(c1)
            s.update(c2)
            yield "pair: %s + %s" % (n1, n2), assemble(s), (k1, k2)
    for (n1, c1, k1), (n2, w2, k2) in itertools.product(HEADER, STREAM):
        s = with_stream(w2)
        s.update(c1)
        yield "pair: %s + %s" % (n1, n2), assemble(s), (k1, k2)
    for (n1, w1, k1), (n2, w2, k2) in itertools.product(STREAM, STREAM):
        if n1 != n2:
            yield ("pair: %s, then %s" % (n1, n2),
                   assemble(with_stream(w1 + w2)), (k1, k2))
    # one word, several faults
    for r in (2, 3, 4):
        for combo in itertools.combinations(ALU_FAULTS, r):
            w = ADD
            for _name, m in combo:
                w |= m
            yield ("word: ALU add + %s" % " + ".join(n for n, _ in combo),
                   assemble(with_stream([w])), ())
    for op in range(16):                  # 15 is no control code at all
        for r in (1, 2, 3, 4):
            for combo in itertools.combinations(CTRL_FAULTS, r):
                w = W(op, ctrl=1)
                for _name, m in combo:
                    w |= m
                yield ("word: control %d + %s" % (
                    op, " + ".join(n for n, _ in combo)),
                    assemble(with_stream([w])), ())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", default=None, help="the shared library")
    ap.add_argument("--show", type=int, default=12,
                    help="how many disagreements to print in full")
    args = ap.parse_args()
    name = {"win32": "cft.dll", "cygwin": "cft.dll",
            "darwin": "libcft.dylib"}.get(sys.platform, "libcft.so")
    path = Path(args.lib or os.environ.get("CFT_LIB") or ROOT / "host" / name)
    if not path.exists():
        raise SystemExit("%s not found - run `make -C host` first" % path)
    try:
        lib = load_library(path)
    except Skip as e:
        # The marker verify/run.sh counts as a check skipped inside a
        # stage that passed (its INNER_SKIP_RE), and --require-all fails
        print("SKIP loader-order check: %s" % e)
        return 0
    dev = ctypes.c_void_p()
    st = lib.cft_open(None, 0, ctypes.byref(dev))
    if st:
        raise SystemExit("cft_open: status %d" % st)

    bad = []
    n = agree = accepted_both = 0
    unplaced = set()
    by_expect = {}
    clean = assemble(base())
    if libcft_says(lib, dev, clean) is not None or model_says(clean):
        raise SystemExit("the clean program is refused: the harness is wrong")
    for label, image, expect in images():
        n += 1
        c, m = libcft_says(lib, dev, image), model_says(image)
        if c is None and m is None:
            accepted_both += 1
            if len(expect) == 1:
                bad.append((label, image, "both ACCEPT an image listed as "
                            "faulty", c, m))
            continue
        if c is None or m is None:
            bad.append((label, image, "%s ACCEPTS what the other refuses"
                        % ("libcft" if c is None else "the model"), c, m))
            continue
        nc, nm = named(c, 1), named(m, 0)
        for side, nm_ in (("libcft", nc), ("the model", nm)):
            if nm_[0] == "?":
                unplaced.add((side, nm_[1]))
        if nc[0] == "?" or nm[0] == "?":
            bad.append((label, image, "a sentence no row of RULES places",
                        c, m))
        elif nc[0] != nm[0]:
            bad.append((label, image, "libcft names %s, the model names %s"
                        % (nc[0], nm[0]), c, m))
        elif nc[1] is not None and nm[1] is not None and nc[1] != nm[1]:
            bad.append((label, image, "both name %s, libcft at instruction "
                        "%d, the model at %d" % (nc[0], nc[1], nm[1]), c, m))
        elif facts(c, nc[0]) != facts(m, nm[0]):
            bad.append((label, image, "both name %s and state different "
                        "operands or constants: libcft %s, the model %s"
                        % (nc[0], facts(c, nc[0]), facts(m, nm[0])), c, m))
        elif len(expect) == 1 and nm[0] != expect[0]:
            bad.append((label, image, "a fault alone is %s and both loaders "
                        "name %s" % (expect[0], nm[0]), c, m))
        else:
            agree += 1
            by_expect[len(expect)] = by_expect.get(len(expect), 0) + 1
    lib.cft_close(dev)

    print("loader-order check: %d images through both loaders: %d refused "
          "by both and named alike (%d faults alone, %d two-fault images, "
          "%d one-word images), %d accepted by both, %d disagreements"
          % (n, agree, by_expect.get(1, 0), by_expect.get(2, 0),
             by_expect.get(0, 0), accepted_both, len(bad)))
    for label, image, why, c, m in bad[:args.show]:
        print("  DISAGREE %s\n    %s\n    libcft: %s\n    model : %s\n"
              "    image : %s" % (label, why, c, m, image.hex()))
    if len(bad) > args.show:
        print("  ... and %d more" % (len(bad) - args.show))
    if unplaced:
        print("  sentences no row of RULES places (add a row):")
        for side, s in sorted(unplaced)[:10]:
            print("    %s: %s" % (side, s))
    if bad:
        print("LOADER ORDER CHECK FAILED")
        return 1
    print("libcft and the model name the same fault, at the same "
          "instruction, for every image")
    return 0


if __name__ == "__main__":
    sys.exit(main())
