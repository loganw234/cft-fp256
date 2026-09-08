# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The `.cfta` assembler and disassembler.

Three things are being tested and they are not the same thing:

  1. **The round trip.** `assemble(disassemble(image)) == image`, byte
     for byte, on every program in the corpus. A readback that cannot
     be re-assembled is not an attestation, so this is the property
     the text form exists to have rather than a convenience.

  2. **Agreement with the model, where the model can reach.**
     `asm.py` is written to docs/SEQUENCER.md revision 2 and `seq.py`
     is revision 1, so they overlap on every program that stays inside
     sixteen registers with no BANK_EXT. On that overlap the words
     must be `seq.encode`'s exactly and the image must load into
     `seq.Program` and run identically in `seq.run`. Where they
     disagree there, asm.py is wrong.

  3. **The refusals.** A file that assembles must be a file that
     loads, so every rule docs/SEQUENCER.md's "What the loader
     refuses" states is checked here from the text side - and so are
     revision 2's two additions, the register high bits and the header
     flags word, which no other test in this tree can reach yet.

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


def test_imm_31_to_28_is_reserved():
    src = HEAD + "add r3, r0, r1\nhalt\n"
    image = bytearray(asm.assemble(src, "<test>"))
    word = int.from_bytes(image[-16:-8], "little")
    word |= 1 << (32 + 28)
    image[-16:-8] = word.to_bytes(8, "little")
    with pytest.raises(asm.AsmError, match=r"imm\[31:28\] is reserved"):
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


def test_the_reserved_flag_bits_are_refused():
    image = bytearray(asm.assemble(HEAD + "halt\n", "<test>"))
    image[24:28] = (asm.FLAG_BANK_EXT | 0x2).to_bytes(4, "little")
    with pytest.raises(asm.AsmError, match="only BANK_EXT is defined"):
        asm.Image.from_bytes(bytes(image))


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
