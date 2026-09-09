# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The `.cfta` assembler and disassembler.

Three things are being tested and they are not the same thing:

  1. **The round trip.** `assemble(disassemble(image)) == image`, byte
     for byte, on every program in the corpus. A readback that cannot
     be re-assembled is not an attestation, so this is the property
     the text form exists to have rather than a convenience.

  2. **Agreement with the model, where the model can reach.**
     `asm.py` is written to docs/SEQUENCER.md revision 3 and `seq.py`
     reaches a revision at a time on its own lane, so they overlap on
     every program that stays inside what the model can express. On
     that overlap the words must be `seq.encode`'s exactly and the
     image must load into `seq.Program` and run identically in
     `seq.run`. Where they disagree there, asm.py is wrong. The three
     tests that EXECUTE a revision-3 program are gated on a
     behavioural probe - they assemble the smallest program that needs
     the feature and ask the model to run it - so they skip here and
     turn themselves on the day the model lands.

  3. **The refusals.** A file that assembles must be a file that
     loads, so every rule docs/SEQUENCER.md's "What the loader
     refuses" states is checked here from the text side - and so are
     revision 2's two additions, the register high bits and the header
     flags word, and revision 3's three: the four scratch codes' field
     rules, the `scratch_io` header word, and the ninth
     constant-index bit that leaves `imm[31]` as the last reserved bit
     of the word.

The tests that matter most are the ones about fields an instruction
does NOT read. Those are what make the encoding canonical, and a
canonical encoding is the whole reason a program's SHA-256 means
anything.
"""

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cft_golden import FORMATS, chars                    # noqa: E402
from cft_golden import asm, seq, seqprogs                # noqa: E402
from cft_golden import softfloat as sf                   # noqa: E402

FP32 = FORMATS["fp32"]
FP64 = FORMATS["fp64"]
PROGRAMS = Path(__file__).resolve().parents[2] / "programs"


def corpus(n=40, formats=("fp32", "fp64")):
    """The shared fuzz corpus, as images. `seq.random_program` is the
    generator every other sequencer check uses, so the assembler is
    held to the same programs the RTL and libcft are."""
    out = []
    for seed in range(n):
        rng = random.Random(seed)
        for extended in (False, True):
            for name in formats:
                fmt = FORMATS[name]
                insns, consts = seq.random_program(fmt, rng,
                                                   extended=extended)
                try:
                    prog = seq.Program(fmt, insns, consts, max_deposits=4)
                except seq.ProgramError:
                    continue
                out.append((f"s{seed}-{name}-{int(extended)}",
                            prog.to_bytes()))
    return out


CORPUS = corpus()
SOURCES = sorted(PROGRAMS.glob("*.cfta"))


# ---- 1. the round trip -------------------------------------------------

def test_round_trip_on_the_whole_fuzz_corpus():
    assert len(CORPUS) > 100, "the corpus generator produced almost nothing"
    for name, image in CORPUS:
        text = asm.disassemble(image)
        assert asm.assemble(text, name) == image, f"{name}\n{text}"


def test_round_trip_on_the_committed_library():
    assert SOURCES, "programs/ has no .cfta sources"
    for src in SOURCES:
        image = asm.assemble(src.read_text(encoding="utf-8"), str(src))
        text = asm.disassemble(image)
        assert asm.assemble(text, src.name) == image, src.name


def test_the_corpus_actually_reaches_the_interesting_forms():
    """A round trip over programs with no kx, no wide index and no
    unread non-zero field would pass while checking nothing the plain
    encoding does not already cover."""
    kx = wide = unread = ctrl_ra = 0
    for _name, image in CORPUS:
        img = asm.Image.from_bytes(image)
        for word in img.insns:
            d = asm.decode(word)
            if d["ctrl"]:
                if d["op"] in (asm.DEPOSIT, asm.SETACT) and d["ra"]:
                    ctrl_ra += 1
                continue
            if d["kx"]:
                kx += 1
            for idx, is_const in asm.sources(d):
                if is_const and idx >= asm.KADDR_PLAIN:
                    wide += 1
            fields = asm.OP_FIELDS.get(d["op"])
            if fields:
                for f in ("ra", "rb", "rc"):
                    if f not in fields and (d[f] or d["k" + f[1]]):
                        unread += 1
    assert kx > 0 and wide > 0 and unread > 0 and ctrl_ra > 0, (
        f"kx={kx} wide={wide} unread={unread} ctrl_ra={ctrl_ra}")


def revision2_source(rng):
    """A random program the revision-1 generator cannot produce: five-bit
    register fields, an external bank, kx both chosen and forced, all
    four formats, and REPEAT trip counts that set imm[27:24]."""
    fmt = FORMATS[rng.choice(["fp32", "fp64", "fp128", "fp256"])]
    nk = rng.randrange(0, 40)
    bank_ext = rng.random() < 0.3
    head = [f".format {fmt.name}", ".deposits 4"]
    if bank_ext:
        head.append(".bank external")
    for i in range(nk):
        head.append(f".const K{i}" if bank_ext else
                    f".const K{i} = 0x{rng.getrandbits(fmt.width):x}")
    body, depth = [], 0
    for _ in range(rng.randint(4, 20)):
        pick = rng.random()
        if pick < 0.5:
            op = rng.choice(list(asm.OP_FIELDS))
            fields = asm.OP_FIELDS[op]
            args = []
            for _f in (fields if rng.random() < 0.6 else ("ra", "rb", "rc")):
                if nk and rng.random() < 0.35:
                    args.append(f"K{rng.randrange(nk)}")
                else:
                    args.append(f"r{rng.randrange(asm.NREG)}")
            mods = []
            if rng.random() < 0.4:
                mods.append(sf.RND_NAMES[rng.randrange(5)])
            if nk and any(a[0] == "K" for a in args) and rng.random() < 0.3:
                mods.append("kx")
            name = asm.OP_NAMES[op] + "".join("." + m for m in mods)
            body.append(f"{name} r{rng.randrange(asm.NREG)}, "
                        + ", ".join(args))
        elif pick < 0.62 and depth < asm.MAX_LOOP_DEPTH:
            body.append("repeat " + str(rng.choice(
                [1, 3, 1 << 24, (0xF << 24) | 7, 0xFFFFF])))
            depth += 1
        elif pick < 0.72 and depth > 0:
            body.append("endrep")
            depth -= 1
        elif pick < 0.85:
            body.append(f"deposit r{rng.randrange(asm.NREG)}")
        elif pick < 0.95:
            body.append(f"setact r{rng.randrange(asm.NREG)}")
        elif depth == 0:
            body.append("actall")
    body += ["endrep"] * depth
    body.append("halt")
    return "\n".join(head + [""] + body) + "\n"


def test_round_trip_on_a_revision_two_corpus():
    """`seq.random_program` is revision 1, so the corpus above never
    reaches the encoding this round added. This one does, and reports
    what it reached - a round trip that never saw a five-bit register
    field would be a round trip over revision 1 with extra steps."""
    rng = random.Random(2026)
    n = regs32 = bank = kx = 0
    for i in range(200):
        text = revision2_source(rng)
        try:
            image = asm.assemble(text, f"r2-{i}")
        except asm.AsmError:
            continue                     # a program the loader refuses
        assert asm.assemble(asm.disassemble(image), f"r2-{i}") == image, text
        feats = asm.Image.from_bytes(image).features()
        regs32 += "REGS32" in feats
        bank += "BANK_PTR" in feats
        kx += "kx" in feats
        n += 1
    assert n > 100, n
    assert regs32 > 50 and bank > 20 and kx > 20, (
        f"REGS32={regs32} BANK_PTR={bank} kx={kx}")


def test_disassembly_of_an_unnamed_opcode_reassembles():
    """An image may carry an opcode this ISA does not name - 24 and 25
    are the reductions, and 31..255 are unassigned. The numeric escape
    is what keeps such an image readable-back."""
    word = asm.encode(24, rd=1, ra=2, rb=3, rc=4)
    img = asm.Image(FP64, [word, asm.halt()], max_deposits=1)
    text = asm.disassemble(img.to_bytes())
    assert "op24 r1, r2, r3, r4" in text
    assert asm.assemble(text, "op24") == img.to_bytes()


# ---- 2. agreement with the model ---------------------------------------

def test_encode_agrees_with_seq_encode_inside_revision_one():
    rng = random.Random(4)
    for _ in range(4000):
        fields = dict(
            op=rng.randrange(256), rd=rng.randrange(16),
            ra=rng.randrange(16), rb=rng.randrange(16),
            rc=rng.randrange(16), rnd=rng.randrange(5),
            ka=bool(rng.getrandbits(1)), kb=bool(rng.getrandbits(1)),
            kc=bool(rng.getrandbits(1)), ctrl=bool(rng.getrandbits(1)))
        assert asm.encode(**fields) == seq.encode(**fields), fields


def test_alu_agrees_with_seq_alu_including_kx():
    rng = random.Random(9)
    seen_kx = 0
    for _ in range(3000):
        kb = bool(rng.getrandbits(1))
        kc = bool(rng.getrandbits(1))
        kx = (kb or kc) and bool(rng.getrandbits(1))
        top = 200 if kx else 16
        args = dict(op=rng.choice([sf.OP_FMA, sf.OP_MUL, sf.OP_IXOR]),
                    rd=rng.randrange(16), ra=rng.randrange(16),
                    rb=rng.randrange(top) if kb else rng.randrange(16),
                    rc=rng.randrange(top) if kc else rng.randrange(16),
                    rnd=rng.randrange(5), kb=kb, kc=kc)
        mine = asm.alu(kx=(True if kx else None), **args)
        theirs = seq.alu(kx=kx, **args)
        if kx and max((args["rb"] if kb else 0),
                      (args["rc"] if kc else 0)) < asm.KADDR_PLAIN:
            # seq.alu was ASKED for the indexed form; asm.alu chooses
            # it only when an index needs it, so force it the way the
            # `.kx` suffix does.
            mine = asm.alu(kx=True, **args)
        assert mine == theirs, args
        seen_kx += int(kx)
    assert seen_kx > 100


@pytest.mark.parametrize("name", ["fp32", "fp64", "fp128", "fp256"])
def test_the_library_sources_are_seqprogs_byte_for_byte(name):
    fmt = FORMATS[name]
    for kind, prog in (("div", seqprogs.div_program_for(fmt)),
                       ("sqrt", seqprogs.sqrt_program_for(fmt))):
        src = PROGRAMS / f"{kind}-{name}.cfta"
        got = asm.assemble(src.read_text(encoding="utf-8"), str(src))
        assert got == prog.to_bytes(), f"{src.name}"


def test_corpus_images_load_and_run_identically_in_the_model():
    """The overlap, run rather than merely encoded: assemble the text
    the disassembler produced, hand THAT image to seq.Program, and run
    it beside the original. Same deposits, same counts, same flags,
    same registers."""
    ran = 0
    for name, image in CORPUS[:80]:
        text = asm.disassemble(image)
        mine = asm.assemble(text, name)
        original = seq.Program.from_bytes(image)
        rebuilt = seq.Program.from_bytes(mine)
        fmt = original.fmt
        rng = random.Random(hash(name) & 0xFFFF)
        n = 8
        a = seq.random_inputs(fmt, rng, n)
        b = seq.random_inputs(fmt, rng, n)
        c = seq.random_inputs(fmt, rng, n)
        r1 = seq.run(original, a, b, c)
        r2 = seq.run(rebuilt, a, b, c)
        assert r1.state() == r2.state(), name
        ran += 1
    assert ran == 80


def test_a_hand_written_source_runs_in_the_model():
    src = """
        .format   fp64
        .deposits 2
        .const    TWO = 2.0
        .reg      y = r3
        .reg      e = r4

        recip_seed y, r0            ; y ~ 1/b
        repeat 4
          neg  e, r0
          fma  e, e, y, TWO         ; e = 2 - b*y
          mul  y, y, e              ; y *= e
        endrep
        deposit y
        halt
    """
    image = asm.assemble(src, "newton")
    prog = seq.Program.from_bytes(image)
    xs = [chars.from_decimal(FP64, s)[0] for s in ("1", "2", "4", "0.5")]
    res = seq.run(prog, xs, [0] * len(xs))
    for i, s in enumerate(("1", "0.5", "0.25", "2")):
        want, _fl = chars.from_decimal(FP64, s)
        assert res.deposits[i * 2] == want, s


# ---- 3. the refusals ---------------------------------------------------

def refuses(src, fragment):
    with pytest.raises(asm.AsmError) as exc:
        asm.assemble(src, "<test>")
    assert fragment in str(exc.value), str(exc.value)


HEAD = ".format fp64\n.deposits 1\n"


def test_unbalanced_loops_are_refused():
    refuses(HEAD + "repeat 3\nadd r3, r0, r1\n", "left open at the end")
    refuses(HEAD + "endrep\nhalt\n", "endrep without repeat")
    refuses(HEAD + "repeat 2\nrepeat 2\nendrep\n", "left open at the end")


def test_loops_deeper_than_four_are_refused():
    body = "repeat 2\n" * 5 + "endrep\n" * 5 + "halt\n"
    refuses(HEAD + body, "nest deeper than 4")
    body = "repeat 2\n" * 4 + "endrep\n" * 4 + "halt\n"
    asm.assemble(HEAD + body, "<test>")          # four is fine


def test_halt_inside_a_loop_is_refused():
    refuses(HEAD + "repeat 2\nhalt\nendrep\nhalt\n", "halt inside a loop")


def test_actall_inside_a_loop_is_refused():
    refuses(HEAD + "repeat 2\nactall\nendrep\nhalt\n",
            "actall inside a loop")


def test_repeat_zero_is_refused():
    refuses(HEAD + "repeat 0\nendrep\nhalt\n", "repeat 0 is not a loop")


def test_the_worst_case_bound_is_enforced():
    """Four nested `repeat 0xffffffff` fit in a few lines and describe
    3.4e38 iterations, which terminates in the same sense the heat
    death of the universe does."""
    body = "repeat 4294967295\n" * 4 + "add r3, r0, r1\n" + \
           "endrep\n" * 4 + "halt\n"
    refuses(HEAD + body, "worst-case instruction count")
    # and a nest that IS bounded assembles
    body = "repeat 1000\n" * 3 + "add r3, r0, r1\n" + \
           "endrep\n" * 3 + "halt\n"
    asm.assemble(HEAD + body, "<test>")


def test_a_constant_index_outside_the_bank_is_refused():
    src = HEAD + ".const K = 1.0\nadd r3, r0, K\nhalt\n"
    asm.assemble(src, "<test>")
    image = bytearray(asm.assemble(src, "<test>"))
    # point the operand at constant 5 of a one-entry bank
    word = int.from_bytes(image[-16:-8], "little")
    word = (word & ~(0xF << 20)) | (5 << 20)
    image[-16:-8] = word.to_bytes(8, "little")
    with pytest.raises(asm.AsmError, match="but the bank holds 1"):
        asm.Image.from_bytes(bytes(image))


def test_a_deposit_of_a_constant_is_refused():
    refuses(HEAD + ".const K = 1.0\ndeposit K\nhalt\n",
            "must be a register")


def test_the_directives_are_required_and_ordered():
    refuses(".deposits 1\nhalt\n", ".format must come first")
    refuses(".format fp64\nhalt\n", ".deposits is required")
    refuses(".format fp64\n.deposits 1\n.format fp32\nhalt\n",
            ".format appears twice")


# ---- 3b. the encoding corners ------------------------------------------

def test_kx_is_selected_exactly_when_an_index_needs_it():
    consts = "".join(f".const K{i} = {i}.0\n" for i in range(20))
    src = HEAD + consts + "add r3, r0, K15\nadd r4, r0, K16\nhalt\n"
    img = asm.Image.from_bytes(asm.assemble(src, "<test>"))
    plain, indexed = asm.decode(img.insns[0]), asm.decode(img.insns[1])
    assert not plain["kx"], "index 15 fits the four-bit field"
    assert plain["rc"] == 15 and plain["imm"] == 0
    assert indexed["kx"], "index 16 does not"
    assert indexed["rc_lo"] == 0, "the field must be zero under kx"
    assert (indexed["imm"] >> asm.KX_SHIFT[2]) & 0xFF == 16
    assert asm.sources(indexed)[2] == (16, True)


def test_the_kx_suffix_forces_the_indexed_form():
    src = HEAD + ".const K = 1.0\nadd.kx r3, r0, K\nhalt\n"
    img = asm.Image.from_bytes(asm.assemble(src, "<test>"))
    d = asm.decode(img.insns[0])
    assert d["kx"] and d["rc_lo"] == 0 and d["imm"] == 0
    assert asm.sources(d)[2] == (0, True)
    # and the disassembler says it, or the round trip would lose it
    assert "add.kx" in asm.disassemble(img.to_bytes())


def test_kx_with_no_constant_operand_is_refused():
    refuses(HEAD + "add.kx r3, r0, r1\nhalt\n", "selects nothing")


def test_a_constant_operand_has_no_register_high_bit():
    """R1's rule, applied to an operand that names a constant: its
    high bit is not read, so it must be zero. Under kx too."""
    src = HEAD + ".const K = 1.0\nadd r3, r0, K\nhalt\n"
    image = bytearray(asm.assemble(src, "<test>"))
    word = int.from_bytes(image[-16:-8], "little")
    word |= 1 << (32 + asm.RHI_SHIFT["rc"])     # rc names a constant
    image[-16:-8] = word.to_bytes(8, "little")
    with pytest.raises(asm.AsmError, match="high bit"):
        asm.Image.from_bytes(bytes(image))


def test_an_alu_instruction_without_kx_has_no_low_immediate():
    src = HEAD + "add r3, r0, r1\nhalt\n"
    image = bytearray(asm.assemble(src, "<test>"))
    word = int.from_bytes(image[-16:-8], "little")
    word |= 1 << 32                              # imm[0]
    image[-16:-8] = word.to_bytes(8, "little")
    with pytest.raises(asm.AsmError, match="no immediate below imm"):
        asm.Image.from_bytes(bytes(image))


# ---- 3c. revision 2: five-bit register fields --------------------------

def test_registers_above_fifteen_use_the_high_bits_of_imm():
    src = HEAD + "add r31, r16, r17\nhalt\n"
    img = asm.Image.from_bytes(asm.assemble(src, "<test>"))
    d = asm.decode(img.insns[0])
    assert (d["rd"], d["ra"], d["rc"]) == (31, 16, 17)
    assert d["rd_lo"] == 15 and d["ra_lo"] == 0 and d["rc_lo"] == 1
    assert d["imm"] == ((1 << asm.RHI_SHIFT["rd"]) |
                        (1 << asm.RHI_SHIFT["ra"]) |
                        (1 << asm.RHI_SHIFT["rc"]))
    assert img.features() == ["REGS32"]
    assert asm.assemble(asm.disassemble(img.to_bytes()), "x") == \
        img.to_bytes()


def test_a_register_above_thirty_one_is_refused():
    refuses(HEAD + "add r32, r0, r1\nhalt\n", "outside r0..r31")


def test_deposit_and_setact_reach_the_high_registers():
    src = HEAD.replace(".deposits 1", ".deposits 2") + \
        "deposit r20\nsetact r31\nhalt\n"
    img = asm.Image.from_bytes(asm.assemble(src, "<test>"))
    d0, d1 = asm.decode(img.insns[0]), asm.decode(img.insns[1])
    assert d0["ra"] == 20 and d0["imm"] == (1 << asm.RHI_SHIFT["ra"])
    assert d1["ra"] == 31 and d1["imm"] == (1 << asm.RHI_SHIFT["ra"])
    assert img.features() == ["REGS32"]


def test_a_control_instruction_that_reads_nothing_carries_nothing():
    src = HEAD + "actall\nhalt\n"
    image = bytearray(asm.assemble(src, "<test>"))
    word = int.from_bytes(image[-16:-8], "little")
    word |= 1 << (32 + asm.RHI_SHIFT["ra"])     # actall reads no ra
    image[-16:-8] = word.to_bytes(8, "little")
    with pytest.raises(asm.AsmError, match="does not read imm"):
        asm.Image.from_bytes(bytes(image))


def test_a_repeat_trip_count_is_not_a_register_field():
    """imm[27:24] are register high bits on an instruction that HAS a
    register to extend. REPEAT has not: its immediate is a trip count
    and every bit of it is the count."""
    trip = (1 << 24) | (1 << 25) | (1 << 26) | (1 << 27) | 5
    src = HEAD + f"repeat {trip}\nendrep\nhalt\n"
    img = asm.Image.from_bytes(asm.assemble(src, "<test>"))
    d = asm.decode(img.insns[0])
    assert d["imm"] == trip
    assert img.features() == [], "a trip count is not a REGS32 program"
    assert asm.assemble(asm.disassemble(img.to_bytes()), "x") == \
        img.to_bytes()


# ---- 3d. revision 2: the header's flags word ---------------------------

def test_bank_ext_carries_no_constant_section():
    src = (".format fp64\n.deposits 1\n.bank external\n"
           ".const A\n.const B\n"
           "add r3, A, B\ndeposit r3\nhalt\n")
    image = asm.assemble(src, "<test>")
    img = asm.Image.from_bytes(image)
    assert img.bank_external and img.flags == asm.FLAG_BANK_EXT
    assert img.n_consts == 2
    assert len(image) == 32 + 8 * len(img.insns)
    assert img.features() == ["BANK_PTR"]
    assert asm.assemble(asm.disassemble(image), "x") == image


def test_bank_ext_still_bounds_the_constant_indices():
    src = (".format fp64\n.deposits 1\n.bank external\n.const A\n"
           "add r3, A, A\nhalt\n")
    image = bytearray(asm.assemble(src, "<test>"))
    word = int.from_bytes(image[-16:-8], "little")
    word = (word & ~(0xF << 20)) | (3 << 20)     # constant 3 of a bank of 1
    image[-16:-8] = word.to_bytes(8, "little")
    with pytest.raises(asm.AsmError, match="but the bank holds 1"):
        asm.Image.from_bytes(bytes(image))


def test_the_bank_buffer_is_dense_and_exact():
    src = (".format fp64\n.deposits 1\n.bank external\n.const A\n.const B\n"
           "add r3, A, B\nhalt\n")
    img = asm.Image.from_bytes(asm.assemble(src, "<test>"))
    one, _fl = chars.from_decimal(FP64, "1")
    two, _fl = chars.from_decimal(FP64, "2")
    buf = img.bank_bytes([one, two])
    assert len(buf) == 2 * 8
    assert int.from_bytes(buf[:8], "little") == one
    with pytest.raises(asm.AsmError, match="the program addresses 2"):
        img.bank_bytes([one])


def test_the_second_reserved_header_word_is_still_reserved():
    image = bytearray(asm.assemble(HEAD + "halt\n", "<test>"))
    image[28:32] = (1).to_bytes(4, "little")
    with pytest.raises(asm.AsmError, match="word 7 must be zero"):
        asm.Image.from_bytes(bytes(image))


def test_trailing_bytes_are_a_different_program():
    image = asm.assemble(HEAD + "halt\n", "<test>") + b"\0"
    with pytest.raises(asm.AsmError, match="header describes"):
        asm.Image.from_bytes(image)


def test_the_digest_covers_the_bank():
    src = (".format fp64\n.deposits 1\n.bank external\n.const A\n"
           "add r3, A, A\nhalt\n")
    img = asm.Image.from_bytes(asm.assemble(src, "<test>"))
    one, _fl = chars.from_decimal(FP64, "1")
    two, _fl = chars.from_decimal(FP64, "2")
    assert img.digest(img.bank_bytes([one])) != \
        img.digest(img.bank_bytes([two])), (
            "two runs with different data must have different digests")
    assert img.digest() != img.digest(img.bank_bytes([one]))


# ---- literals ----------------------------------------------------------

def test_a_decimal_literal_is_correctly_rounded():
    for text in ("0.1", "2.0", "-0.0", "1e-320", "3.14159265358979323846"):
        src = f".format fp64\n.deposits 1\n.const K = {text}\nhalt\n"
        img = asm.Image.from_bytes(asm.assemble(src, "<test>"))
        want, _fl = chars.from_decimal(FP64, text, sf.RND_RNE)
        assert img.consts[0] == want, text


def test_a_hex_significand_literal_is_the_5_12_3_form():
    for name in ("fp32", "fp64", "fp128", "fp256"):
        fmt = FORMATS[name]
        src = (f".format {name}\n.deposits 1\n"
               f".const K = 0x1p10\n.const M = -0x1.8p-3\nhalt\n")
        img = asm.Image.from_bytes(asm.assemble(src, "<test>"))
        want, _fl = chars.from_hex(fmt, "0x1p10", sf.RND_RNE)
        assert img.consts[0] == want, name
        want2, _fl = chars.from_hex(fmt, "-0x1.8p-3", sf.RND_RNE)
        assert img.consts[1] == want2, name


def test_a_raw_hex_literal_is_the_encoding_not_the_value():
    src = ".format fp64\n.deposits 1\n.const K = 0x3ff0000000000000\nhalt\n"
    img = asm.Image.from_bytes(asm.assemble(src, "<test>"))
    assert img.consts[0] == 0x3FF0000000000000
    one, _fl = chars.from_decimal(FP64, "1")
    assert img.consts[0] == one, "which happens to be 1.0 at fp64"
    refuses(".format fp32\n.deposits 1\n.const K = 0x1ffffffff\nhalt\n",
            "wider than fp32")
    refuses(".format fp64\n.deposits 1\n.const K = -0x1\nhalt\n",
            "carries its own sign bit")


def test_specials_spell_what_they_say():
    src = (".format fp32\n.deposits 1\n"
           ".const I = inf\n.const M = -inf\n.const N = nan\nhalt\n")
    img = asm.Image.from_bytes(asm.assemble(src, "<test>"))
    assert img.consts[0] == sf.inf_bits(FP32)
    assert img.consts[1] == sf.inf_bits(FP32, 1)
    assert img.consts[2] == sf.qnan_bits(FP32)


# ---- the operand forms -------------------------------------------------

def test_an_opcode_names_the_operands_it_reads():
    """ADD is a + c and does not read b, so two operands fill ra and
    rc. Getting this wrong would put every addend in the wrong field
    and every test above would still pass."""
    src = HEAD + "add r3, r0, r1\nmul r4, r0, r1\nabs r5, r0\nhalt\n"
    img = asm.Image.from_bytes(asm.assemble(src, "<test>"))
    add, mul, ab = (asm.decode(w) for w in img.insns[:3])
    assert (add["ra"], add["rb"], add["rc"]) == (0, 0, 1)
    assert (mul["ra"], mul["rb"], mul["rc"]) == (0, 1, 0)
    assert (ab["ra"], ab["rb"], ab["rc"]) == (0, 0, 0)


def test_the_three_field_form_reaches_a_field_the_opcode_ignores():
    src = HEAD + "abs r3, r0, r1, r2\nhalt\n"
    img = asm.Image.from_bytes(asm.assemble(src, "<test>"))
    d = asm.decode(img.insns[0])
    assert (d["ra"], d["rb"], d["rc"]) == (0, 1, 2)
    # and the disassembler must use the long form to keep those bits
    assert "abs r3, r0, r1, r2" in asm.disassemble(img.to_bytes())


def test_the_wrong_number_of_operands_is_refused():
    refuses(HEAD + "add r3, r0\nhalt\n", "reads 2 operand")
    refuses(HEAD + "fma r3, r0, r1\nhalt\n", "reads 3 operand")


def test_a_rounding_suffix_selects_the_attribute():
    for suffix, code in (("rne", 0), ("rtz", 1), ("rdn", 2), ("rup", 3),
                         ("rmm", 4)):
        src = HEAD + f"fma.{suffix} r3, r0, r1, r2\nhalt\n"
        img = asm.Image.from_bytes(asm.assemble(src, "<test>"))
        assert asm.decode(img.insns[0])["rnd"] == code
    refuses(HEAD + "fma.rtn r3, r0, r1, r2\nhalt\n", "is not rne, rtz")


def test_names_are_case_insensitive_and_comments_are_nothing():
    a = asm.assemble(HEAD + "ADD R3, r0, R1 ; a comment\nHALT\n", "x")
    b = asm.assemble(HEAD + "add r3, r0, r1\nhalt\n", "x")
    assert a == b


# ---- 3e. revision 3: the four scratch codes -----------------------------
#
# The encoding rule for all four is one sentence - the register fields
# the code names, plus imm[23:0] on the two static forms, and every
# other field zero - so the tests below are that sentence, once per
# code, from both sides: what the assembler emits, and what the loader
# refuses when a bit it does not read is set.

SCR = ".format fp64\n.deposits 1\n.scratch 512\n"


def _only(d, *fields):
    """The raw four-bit fields that are non-zero, as a set of names."""
    live = {f for f in ("rd", "ra", "rb", "rc") if d[f + "_lo"]}
    return live == set(fields)


def test_stl_reads_ra_and_the_slot():
    img = asm.Image.from_bytes(asm.assemble(SCR + "stl r20, 300\nhalt\n",
                                            "<test>"))
    d = asm.decode(img.insns[0])
    assert d["ctrl"] and d["op"] == asm.STL
    assert d["ra"] == 20 and d["ra_lo"] == 4
    assert d["imm"] == 300 | (1 << asm.RHI_SHIFT["ra"])
    assert _only(d, "ra")
    assert not (d["rnd"] or d["ka"] or d["kb"] or d["kc"] or d["kx"])
    assert "stl r20, 300" in asm.disassemble(img.to_bytes())


def test_ldl_reads_rd_and_the_slot():
    img = asm.Image.from_bytes(asm.assemble(SCR + "ldl r31, 511\nhalt\n",
                                            "<test>"))
    d = asm.decode(img.insns[0])
    assert d["op"] == asm.LDL and d["rd"] == 31 and d["rd_lo"] == 15
    assert d["imm"] == 511 | (1 << asm.RHI_SHIFT["rd"])
    assert _only(d, "rd")
    assert "ldl r31, 511" in asm.disassemble(img.to_bytes())


def test_stx_reads_ra_and_rb_and_carries_no_slot():
    img = asm.Image.from_bytes(asm.assemble(SCR + "stx r17, r30\nhalt\n",
                                            "<test>"))
    d = asm.decode(img.insns[0])
    assert d["op"] == asm.STX and d["ra"] == 17 and d["rb"] == 30
    assert d["imm"] == (1 << asm.RHI_SHIFT["ra"]) | (1 << asm.RHI_SHIFT["rb"])
    assert d["imm"] & asm.SLOT_MASK == 0
    assert _only(d, "ra", "rb")
    assert "stx r17, r30" in asm.disassemble(img.to_bytes())


def test_ldx_reads_rd_and_rb_and_carries_no_slot():
    # r17 and not r16: _only() reads the raw four-bit fields, and r16's
    # low nibble is zero, which would make "rd is used" and "rd is
    # zero" the same observation
    img = asm.Image.from_bytes(asm.assemble(SCR + "ldx r17, r19\nhalt\n",
                                            "<test>"))
    d = asm.decode(img.insns[0])
    assert d["op"] == asm.LDX and d["rd"] == 17 and d["rb"] == 19
    assert d["imm"] == (1 << asm.RHI_SHIFT["rd"]) | (1 << asm.RHI_SHIFT["rb"])
    assert d["imm"] & asm.SLOT_MASK == 0
    assert _only(d, "rd", "rb")
    assert "ldx r17, r19" in asm.disassemble(img.to_bytes())


def _tamper(src, mutate, match):
    """Assemble, flip a bit of the FIRST instruction, and require the
    loader to refuse it. The instruction stream begins right after the
    header and the constants, and every source here has none."""
    image = bytearray(asm.assemble(src, "<test>"))
    off = asm.HEADER_BYTES
    word = int.from_bytes(image[off:off + 8], "little")
    image[off:off + 8] = mutate(word).to_bytes(8, "little")
    with pytest.raises(asm.AsmError, match=match):
        asm.Image.from_bytes(bytes(image))


@pytest.mark.parametrize("line,field,shift", [
    ("stl r3, 4", "rd", 8),      # STL writes nothing
    ("stl r3, 4", "rb", 16),
    ("stl r3, 4", "rc", 20),
    ("ldl r3, 4", "ra", 12),     # LDL reads no source register
    ("ldl r3, 4", "rb", 16),
    ("stx r3, r4", "rd", 8),     # STX writes nothing
    ("stx r3, r4", "rc", 20),
    ("ldx r3, r4", "ra", 12),    # LDX's source is rb, not ra
    ("ldx r3, r4", "rc", 20),
])
def test_a_scratch_code_refuses_a_register_field_it_does_not_read(
        line, field, shift):
    _tamper(SCR + line + "\nhalt\n", lambda w: w | (1 << shift),
            f"does not read {field}")


@pytest.mark.parametrize("line", ["stl r3, 4", "ldl r3, 4",
                                  "stx r3, r4", "ldx r3, r4"])
@pytest.mark.parametrize("bit,what", [(24, "rnd"), (27, "ka"), (28, "kb"),
                                      (29, "kc"), (30, "kx")])
def test_a_scratch_code_is_not_arithmetic(line, bit, what):
    """No rounding attribute, no constant operand, no indexed form:
    neither a load nor a store is arithmetic, so every one of those
    fields is unread and must be zero."""
    _tamper(SCR + line + "\nhalt\n", lambda w: w | (1 << bit),
            f"does not read {what}")


@pytest.mark.parametrize("line", ["stx r3, r4", "ldx r3, r4"])
def test_an_indexed_access_carries_no_slot(line):
    """STX and LDX take the slot from rb, so imm[23:0] is read by
    nothing and a stray bit there would be a second encoding of the
    same instruction."""
    _tamper(SCR + line + "\nhalt\n", lambda w: w | (1 << 32),
            "does not read imm")


@pytest.mark.parametrize("line", ["stl r3, 4", "ldl r3, 4",
                                  "stx r3, r4", "ldx r3, r4"])
def test_no_scratch_code_reads_the_rc_high_bit(line):
    """None of the four names rc, so imm[27] is unread on all of them -
    the same rule DEPOSIT and SETACT have carried since revision 2."""
    _tamper(SCR + line + "\nhalt\n",
            lambda w: w | (1 << (32 + asm.RHI_SHIFT["rc"])),
            "does not read imm")


def test_a_static_slot_past_the_declared_depth_is_refused():
    refuses(HEAD + "stl r3, 256\nhalt\n", "declares a scratch of 256")
    refuses(".format fp64\n.deposits 1\n.scratch 16\nldl r3, 16\nhalt\n",
            "declares a scratch of 16")
    # and one INSIDE the declared depth assembles
    asm.assemble(".format fp64\n.deposits 1\n.scratch 512\n"
                 "stl r3, 511\nhalt\n", "<test>")


def test_the_declared_depth_is_a_power_of_two():
    refuses(".format fp64\n.deposits 1\n.scratch 100\nhalt\n",
            "power of two")
    refuses(".format fp64\n.deposits 1\n.scratch 0\nhalt\n",
            "power of two")
    refuses(".format fp64\n.deposits 1\n.scratch 64\n.scratch 128\nhalt\n",
            "appears twice")
    refuses(HEAD + "halt\n.scratch 64\n", "before the instructions")


def test_the_depth_is_inferred_on_readback():
    """The depth is not in the image, so a reader that defaulted to 256
    would refuse a legal program written for a deeper tile. Both
    implementations infer the smallest power of two that covers what
    the image does, and the disassembler writes it back."""
    image = asm.assemble(".format fp64\n.deposits 1\n.scratch 2048\n"
                         "stl r3, 1000\nhalt\n", "<test>")
    img = asm.Image.from_bytes(image)
    assert img.scratch_depth == 1024, "1000 needs 1024, not 2048"
    text = asm.disassemble(image)
    assert ".scratch  1024" in text
    assert asm.assemble(text, "x") == image
    # and an image with no deep slot says nothing at all
    plain = asm.assemble(HEAD + "stl r3, 255\nhalt\n", "<test>")
    assert asm.Image.from_bytes(plain).scratch_depth == 256
    assert ".scratch" not in asm.disassemble(plain)


def test_a_slot_name_is_an_alias_in_the_same_namespace():
    a = asm.assemble(HEAD + ".slot ACC = 7\nstl r3, ACC\nldl r4, acc\n"
                     "halt\n", "<test>")
    b = asm.assemble(HEAD + "stl r3, 7\nldl r4, 7\nhalt\n", "<test>")
    assert a == b
    refuses(HEAD + ".reg q = r5\n.slot q = 1\nhalt\n", "already defined")
    refuses(HEAD + ".const K = 1.0\n.slot K = 1\nhalt\n", "already defined")
    refuses(HEAD + ".slot r4 = 1\nhalt\n", "shadow a register")
    refuses(HEAD + ".reg q = r5\nstl r3, q\nhalt\n", "is a register")
    refuses(HEAD + ".const K = 1.0\nldl r3, K\nhalt\n", "is a constant")


# ---- 3f. revision 3: the header's scratch_io word -----------------------

def test_scratch_io_sets_the_flag_and_the_header_word():
    src = (".format fp64\n.deposits 1\n.scratch in 3\n.scratch out 5\n"
           "ldl r3, 0\nstl r3, 4\nhalt\n")
    image = asm.assemble(src, "<test>")
    img = asm.Image.from_bytes(image)
    assert img.flags == asm.FLAG_SCRATCH_IO
    assert img.scratch_io == (3 | (5 << 16))
    assert (img.n_scratch_in, img.n_scratch_out) == (3, 5)
    assert img.features() == ["SCRATCH", "SCRATCH_IO"]
    # bytes 28..31 ARE the word
    assert int.from_bytes(image[28:32], "little") == (3 | (5 << 16))
    assert asm.assemble(asm.disassemble(image), "x") == image


def test_either_half_declares_the_block_even_at_zero():
    """The flag says the word is MEANINGFUL, so a program that carries
    nothing in and something out can say exactly that - and one that
    declares `in 0` alone is still a SCRATCH_IO program, which is what
    makes the round trip well-defined."""
    img = asm.Image.from_bytes(
        asm.assemble(".format fp64\n.deposits 1\n.scratch out 4\nhalt\n",
                     "<test>"))
    assert img.flags == asm.FLAG_SCRATCH_IO
    assert (img.n_scratch_in, img.n_scratch_out) == (0, 4)
    zero = asm.assemble(".format fp64\n.deposits 1\n.scratch in 0\nhalt\n",
                        "<test>")
    zimg = asm.Image.from_bytes(zero)
    assert zimg.flags == asm.FLAG_SCRATCH_IO and zimg.scratch_io == 0
    assert asm.assemble(asm.disassemble(zero), "x") == zero


def test_the_header_word_is_zero_without_the_flag():
    image = bytearray(asm.assemble(HEAD + "halt\n", "<test>"))
    image[28:32] = (7).to_bytes(4, "little")
    with pytest.raises(asm.AsmError, match="word 7 must be zero"):
        asm.Image.from_bytes(bytes(image))


def test_a_scratch_io_count_past_the_declared_depth_is_refused():
    refuses(".format fp64\n.deposits 1\n.scratch 16\n.scratch in 17\n"
            "halt\n", "more than the 16 slots")
    refuses(".format fp64\n.deposits 1\n.scratch 16\n.scratch out 32\n"
            "halt\n", "more than the 16 slots")
    refuses(".format fp64\n.deposits 1\n.scratch in 65536\nhalt\n",
            "sixteen-bit count")


def test_the_reserved_flag_bits_after_revision_three():
    """BANK_EXT and SCRATCH_IO are the two defined bits; bit 2 up is
    still reserved-must-be-zero."""
    image = bytearray(asm.assemble(HEAD + "halt\n", "<test>"))
    image[24:28] = (asm.FLAG_BANK_EXT | 0x4).to_bytes(4, "little")
    with pytest.raises(asm.AsmError, match="only BANK_EXT and SCRATCH_IO"):
        asm.Image.from_bytes(bytes(image))


# ---- 3g. revision 3: the ninth constant-index bit -----------------------

def _wide_head(n, fmt="fp32"):
    return (f".format {fmt}\n.deposits 1\n"
            + "".join(f".const K{i} = {i}.5\n" for i in range(n)))


@pytest.mark.parametrize("slot,line", [
    (0, "fma r3, K300, r0, r1"),
    (1, "fma r3, r0, K300, r1"),
    (2, "fma r3, r0, r1, K300"),
])
def test_each_operand_has_its_own_ninth_index_bit(slot, line):
    """imm[28], imm[29] and imm[30] are ka's, kb's and kc's ninth bits
    respectively. Wiring two of them to the same operand would be
    invisible in any program that used one constant at a time."""
    img = asm.Image.from_bytes(
        asm.assemble(_wide_head(320) + line + "\nhalt\n", "<test>"))
    d = asm.decode(img.insns[0])
    assert d["kx"], "an index past 15 needs the indexed form"
    assert asm.sources(d)[slot] == (300, True)
    assert (d["imm"] >> asm.KX9_SHIFT[slot]) & 1 == 1
    others = [k for k in range(3) if k != slot]
    for k in others:
        assert (d["imm"] >> asm.KX9_SHIFT[k]) & 1 == 0
    assert (d["imm"] >> asm.KX_SHIFT[slot]) & 0xFF == 300 - 256
    assert img.features() == ["kx", "KX9"]
    assert asm.assemble(asm.disassemble(img.to_bytes()), "x") == \
        img.to_bytes()


def test_the_bank_reaches_five_hundred_and_twelve():
    img = asm.Image.from_bytes(
        asm.assemble(_wide_head(512) + "fma r3, K511, K511, K511\nhalt\n",
                     "<test>"))
    d = asm.decode(img.insns[0])
    assert asm.sources(d) == [(511, True)] * 3
    assert (d["imm"] >> 28) & 0x7 == 0x7
    refuses(_wide_head(513) + "halt\n", "at most 512 constants")


def test_a_ninth_bit_is_read_only_under_kx_for_a_constant():
    """Set anywhere else it is an unread field, and the program is
    refused - the same rule the register high bits carry."""
    # no kx at all
    image = bytearray(asm.assemble(HEAD + "add r3, r0, r1\nhalt\n",
                                   "<test>"))
    off = asm.HEADER_BYTES
    for bit in asm.KX9_SHIFT:
        w = int.from_bytes(image[off:off + 8], "little")
        tampered = bytearray(image)
        tampered[off:off + 8] = (w | (1 << (32 + bit))).to_bytes(8, "little")
        with pytest.raises(asm.AsmError, match="ninth bit"):
            asm.Image.from_bytes(bytes(tampered))
    # kx, but on an operand that names a REGISTER
    src = _wide_head(20) + "add.kx r3, K17, r1\nhalt\n"
    base = bytearray(asm.assemble(src, "<test>"))
    off = len(base) - 16
    w = int.from_bytes(base[off:off + 8], "little")
    base[off:off + 8] = (w | (1 << (32 + asm.KX9_SHIFT[2]))).to_bytes(
        8, "little")
    with pytest.raises(asm.AsmError, match="ninth bit"):
        asm.Image.from_bytes(bytes(base))


def test_imm_31_is_the_only_reserved_bit_left():
    """R7 spent imm[30:28] on the ninth index bits and kept imm[31] as
    the cheap version guard for whatever comes after revision 3."""
    src = HEAD + "add r3, r0, r1\nhalt\n"
    image = bytearray(asm.assemble(src, "<test>"))
    off = asm.HEADER_BYTES
    word = int.from_bytes(image[off:off + 8], "little")
    image[off:off + 8] = (word | (1 << (32 + 31))).to_bytes(8, "little")
    with pytest.raises(asm.AsmError, match=r"imm\[31\] is reserved"):
        asm.Image.from_bytes(bytes(image))


# ---- 3h. the revision-3 corpus ------------------------------------------

def revision3_source(rng):
    """A random program neither generator above can produce: the four
    scratch codes, static slots on both sides of 255 behind a declared
    depth, indexed slots, a per-run block, and nine-bit constant
    indices on each of ra, rb and rc."""
    fmt = FORMATS[rng.choice(["fp32", "fp64", "fp128", "fp256"])]
    nk = (rng.randrange(0, 40) if rng.random() < 0.6
          else rng.randrange(250, 330))
    bank_ext = rng.random() < 0.3
    depth = rng.choice([16, 256, 256, 512, 1024])
    head = [f".format {fmt.name}", ".deposits 4", f".scratch {depth}"]
    if rng.random() < 0.4:
        head.append(f".scratch in {rng.randrange(0, min(depth, 8) + 1)}")
    if rng.random() < 0.4:
        head.append(f".scratch out {rng.randrange(0, min(depth, 8) + 1)}")
    if bank_ext:
        head.append(".bank external")
    for i in range(nk):
        head.append(f".const K{i}" if bank_ext else
                    f".const K{i} = 0x{rng.getrandbits(fmt.width):x}")
    nslots = rng.randrange(0, 4)
    for i in range(nslots):
        head.append(f".slot S{i} = {rng.randrange(depth)}")
    body, nest = [], 0
    for _ in range(rng.randint(6, 24)):
        pick = rng.random()
        if pick < 0.40:
            op = rng.choice(list(asm.OP_FIELDS))
            fields = asm.OP_FIELDS[op]
            args = []
            for _f in (fields if rng.random() < 0.6 else ("ra", "rb", "rc")):
                if nk and rng.random() < 0.45:
                    lo = 256 if (nk > 256 and rng.random() < 0.5) else 0
                    args.append(f"K{rng.randrange(lo, nk)}")
                else:
                    args.append(f"r{rng.randrange(asm.NREG)}")
            mods = []
            if rng.random() < 0.4:
                mods.append(sf.RND_NAMES[rng.randrange(5)])
            if nk and any(a[0] == "K" for a in args) and rng.random() < 0.3:
                mods.append("kx")
            name = asm.OP_NAMES[op] + "".join("." + m for m in mods)
            body.append(f"{name} r{rng.randrange(asm.NREG)}, "
                        + ", ".join(args))
        elif pick < 0.62:
            what = rng.choice(["stl", "ldl", "stx", "ldx"])
            if what in ("stl", "ldl"):
                slot = (f"S{rng.randrange(nslots)}"
                        if nslots and rng.random() < 0.4
                        else str(rng.randrange(depth)))
                body.append(f"{what} r{rng.randrange(asm.NREG)}, {slot}")
            else:
                body.append(f"{what} r{rng.randrange(asm.NREG)}, "
                            f"r{rng.randrange(asm.NREG)}")
        elif pick < 0.72 and nest < asm.MAX_LOOP_DEPTH:
            body.append("repeat " + str(rng.choice(
                [1, 3, 1 << 24, (0xF << 24) | 7, 0xFFFFF])))
            nest += 1
        elif pick < 0.80 and nest > 0:
            body.append("endrep")
            nest -= 1
        elif pick < 0.90:
            body.append(f"deposit r{rng.randrange(asm.NREG)}")
        elif pick < 0.97:
            body.append(f"setact r{rng.randrange(asm.NREG)}")
        elif nest == 0:
            body.append("actall")
    body += ["endrep"] * nest
    body.append("halt")
    return "\n".join(head + [""] + body) + "\n"


def test_round_trip_on_a_revision_three_corpus():
    rng = random.Random(20260908)
    n = scratch = scratch_io = kx9 = indexed = deep = 0
    for i in range(200):
        text = revision3_source(rng)
        try:
            image = asm.assemble(text, f"r3-{i}")
        except asm.AsmError:
            continue                     # a program the loader refuses
        assert asm.assemble(asm.disassemble(image), f"r3-{i}") == image, text
        img = asm.Image.from_bytes(image)
        feats = img.features()
        scratch += "SCRATCH" in feats
        scratch_io += "SCRATCH_IO" in feats
        kx9 += "KX9" in feats
        top, ix = img.scratch_use()
        indexed += ix
        deep += (top is not None and top >= 256)
        n += 1
    assert n > 100, n
    assert scratch > 100 and scratch_io > 30 and kx9 > 20, (
        f"SCRATCH={scratch} SCRATCH_IO={scratch_io} KX9={kx9}")
    assert indexed > 50 and deep > 10, f"indexed={indexed} deep={deep}"


def test_the_library_scratch_rows_round_trip():
    """The five committed revision-3 sources, through the disassembler
    and back. `test_round_trip_on_the_committed_library` covers them
    too; this one names them, so a row that quietly stopped being a
    scratch program would show up here rather than in a count."""
    seen = {}
    for stem in ("spill-fp64", "conv-fp64", "resume-fp64",
                 "horner-wide-fp64", "spill-ref-fp64"):
        src = PROGRAMS / f"{stem}.cfta"
        assert src.exists(), src
        image = asm.assemble(src.read_text(encoding="utf-8"), str(src))
        assert asm.assemble(asm.disassemble(image), stem) == image
        seen[stem] = asm.Image.from_bytes(image).features()
    assert seen["spill-fp64"] == ["SCRATCH"]
    assert seen["spill-ref-fp64"] == []
    assert seen["conv-fp64"] == ["SCRATCH"]
    assert seen["resume-fp64"] == ["SCRATCH", "SCRATCH_IO"]
    assert seen["horner-wide-fp64"] == ["kx", "BANK_PTR", "KX9"]


# ---- 4. what waits on the model ----------------------------------------
#
# `seq.py` reaches revision 3 on its own lane - the four control codes,
# `SCRATCH_D`, the header's `scratch_io` word and the ninth
# constant-index bit. Until it does, a test that EXECUTES one of those
# programs cannot run here, so each is gated on a behavioural probe
# rather than on a version number or an attribute name: the probe
# assembles the smallest program that needs the feature and asks the
# model to run it. The day the model lands, these turn themselves on.
#
# INTEGRATOR: these three are the tests that need the widened seq.py.


def _model_runs(src, inputs, want):
    try:
        image = asm.assemble(src, "<probe>")
        prog = seq.Program.from_bytes(image)
        res = seq.run(prog, inputs, [0] * len(inputs), [0] * len(inputs))
        return res.deposits[:len(want)] == want
    except Exception:                                    # noqa: BLE001
        return False


def _model_loads(src):
    try:
        return seq.Program.from_bytes(asm.assemble(src, "<probe>")) is not None
    except Exception:                                    # noqa: BLE001
        return False


THREE = chars.from_decimal(FP64, "3")[0]
MODEL_HAS_SCRATCH = _model_runs(
    ".format fp64\n.deposits 1\nstl r0, 5\nldl r3, 5\ndeposit r3\nhalt\n",
    [THREE], [THREE])
MODEL_HAS_INDEXED = _model_runs(
    ".format fp64\n.deposits 1\nstx r0, r4\nldx r3, r4\ndeposit r3\nhalt\n",
    [THREE], [THREE])
MODEL_HAS_KX9 = _model_loads(
    ".format fp32\n.deposits 1\n"
    + "".join(f".const K{i} = {i}.0\n" for i in range(300))
    + "add r3, r0, K299\ndeposit r3\nhalt\n")
MODEL_HAS_SCRATCH_IO = _model_loads(
    ".format fp64\n.deposits 1\n.scratch in 2\n.scratch out 2\n"
    "ldl r3, 0\nstl r3, 1\ndeposit r3\nhalt\n")


@pytest.mark.skipif(not MODEL_HAS_SCRATCH,
                    reason="seq.py has no scratch yet (R4's four control "
                           "codes arrive on the model's own lane)")
def test_the_spill_and_its_twin_agree_in_the_model():
    """The library's whole argument for spill-fp64, run: the spilling
    program and the unspilled one must deposit the same bits."""
    a = asm.assemble((PROGRAMS / "spill-fp64.cfta").read_text("utf-8"), "a")
    b = asm.assemble((PROGRAMS / "spill-ref-fp64.cfta").read_text("utf-8"),
                     "b")
    xs = [chars.from_decimal(FP64, f"{-1.5 + 3.0 * i / 16:.9f}")[0]
          for i in range(16)]
    zero = [0] * len(xs)
    ra = seq.run(seq.Program.from_bytes(a), xs, zero, zero)
    rb = seq.run(seq.Program.from_bytes(b), xs, zero, zero)
    assert ra.deposits == rb.deposits
    assert ra.flags == rb.flags


@pytest.mark.skipif(not MODEL_HAS_INDEXED,
                    reason="seq.py has no stx/ldx yet")
def test_the_convolution_runs_in_the_model():
    image = asm.assemble((PROGRAMS / "conv-fp64.cfta").read_text("utf-8"),
                         "conv")
    xs = [chars.from_decimal(FP64, f"{-0.75 + 1.5 * i / 8:.9f}")[0]
          for i in range(8)]
    zero = [0] * len(xs)
    res = seq.run(seq.Program.from_bytes(image), xs, zero, zero)
    grow = chars.from_decimal(FP64, "1.25")[0]
    shift = chars.from_decimal(FP64, "0.5")[0]
    w = [chars.from_decimal(FP64, s)[0] for s in ("0.25", "0.5", "0.25")]
    want = []
    for x in xs:
        arr, v = [], x
        for _k in range(16):
            arr.append(v)
            v, _fl = sf.compute(FP64, sf.OP_FMA, v, grow, shift, sf.RND_RNE)
        for i in range(14):
            acc, _fl = sf.compute(FP64, sf.OP_MUL, arr[i], w[0], 0,
                                  sf.RND_RNE)
            for t in (1, 2):
                acc, _fl = sf.compute(FP64, sf.OP_FMA, arr[i + t], w[t],
                                      acc, sf.RND_RNE)
            want.append(acc)
    assert res.deposits == want


@pytest.mark.skipif(not MODEL_HAS_KX9,
                    reason="seq.py addresses 256 constants, not 512 "
                           "(R7's ninth index bit)")
def test_a_constant_past_255_reaches_the_model():
    n = 300
    src = (".format fp64\n.deposits 1\n"
           + "".join(f".const K{i} = {i}.0\n" for i in range(n))
           + f"add r3, r0, K{n - 1}\ndeposit r3\nhalt\n")
    image = asm.assemble(src, "wide")
    prog = seq.Program.from_bytes(image)
    one = chars.from_decimal(FP64, "1")[0]
    res = seq.run(prog, [one], [0], [0])
    want, _fl = sf.compute(FP64, sf.OP_ADD, one,
                           chars.from_decimal(FP64, str(n - 1))[0], 0,
                           sf.RND_RNE)
    assert res.deposits[0] == want


def test_a_scratch_io_header_is_at_least_well_formed_here():
    """Not gated: this asserts what THIS tree can say about the R5
    header - the flag, the word and the byte offsets - without asking
    the model to run anything. Executing a scratch-I/O program needs a
    `seq.run` that takes the block, and only the model's own lane can
    name that argument."""
    src = (".format fp64\n.deposits 1\n.scratch in 2\n.scratch out 3\n"
           "ldl r3, 0\nstl r3, 1\ndeposit r3\nhalt\n")
    image = asm.assemble(src, "io")
    assert int.from_bytes(image[24:28], "little") == asm.FLAG_SCRATCH_IO
    assert int.from_bytes(image[28:32], "little") == (2 | (3 << 16))
    img = asm.Image.from_bytes(image)
    assert (img.n_scratch_in, img.n_scratch_out) == (2, 3)
    assert asm.assemble(asm.disassemble(image), "io") == image
