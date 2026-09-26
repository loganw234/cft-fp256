# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Every check the library's index promises.

`make programs-check` at the repo root is this script. It does three
things, in this order, and stops at the first failure:

1. **Two assemblers, one image.** Every `.cfta` is assembled with
   `host/tools/cft-asm` and again with `python/cft_golden/asm.py`, and
   the bytes must be identical - then compared against the MANIFEST,
   so a rebuild that moved a byte is caught here and not in a diff
   nobody read. The MANIFEST and the sources must also match one for
   one: a line whose source is gone is a row that vanished, and until
   2026-09-25 that - or every source gone at once - still passed. Each
   of the MANIFEST's refusals - missing, listing nothing, a malformed
   line, a name twice, a line with no source, a source with no line -
   carries a control that must be refused by name. And gen_odes.py's
   own `--check` runs here, so a generated file that is missing or
   differs fails the run rather than waiting for someone to run the
   generator.

2. **The disassembler is a readback.** Every built image is
   disassembled by both implementations, the two texts must agree, and
   re-assembling either must return the same bytes. A readback that
   cannot be re-assembled is not an attestation.

3. **Each row's own check**, which is what earns a program its place
   in programs/README.md: byte equality with the model's generator for
   the composed div and sqrt, the tool's own records for the Collatz
   kernel, the golden model's executor for the escape map, the hash's
   definition for the draw stream, a model computation with two
   different banks for the BANK_EXT worked example, - for
   revision 3's four scratch rows - the same arithmetic without the
   spill, a softfloat convolution, a longer run's second half, and a
   softfloat Horner over three hundred coefficients, and - for the
   three ODE rows gen_odes.py writes (2026-09-25) - the generator byte
   for byte, each bank slot against the definition of the name the
   source gives it, each row's numbers against literals pinned here and
   programs/README.md's, the source's own and gen_odes.py's docstring's
   statements of them against the image, the census, three executors
   bit for bit, each step
   against the textbook scheme in exact rationals, the 300-digit
   scheme, and resumption. Each of those arms but the header and the
   census's executor count carries a negative control that must fail;
   a control watches the comparison it names, not every clause of its
   arm, and the comment above check_ode says which comparison each one
   watches. The textbook arm's code is held apart from what it judges
   as well (check_textbook_independence). Within this file - its top
   level and the blocks of its top-level if, try, with, for, while and
   match statements, a census holding the walk to every def, class,
   assignment and match capture the file makes there - nothing its
   verdict reaches is the mirror, the generator or an executor, and no
   definition is reached both by its verdict and by them: reached by
   name, by an attribute of the same name, or handed as a value to a
   call of either side's code, through the locals, aliases,
   conditionals, containers and tables the comment above those rules
   defines. That comment also names the shapes known to pass them - code
   in another module, a name built at run time and a copy of the
   mirror's code among them.

Revision 3's rows have two arms and they are not the same claim. The
STATIC arm - constants against their derivation, the header against
what the source declares, the encoding against the contract - runs
today. The EXECUTION arm needs a libcft that knows the four control
codes, the header's `scratch_io` word and the ninth constant-index
bit. Those arrived with the model and host halves of the same round,
so the arm runs; while it did not, it said SKIP and WHICH feature it
waited on, asking `positive-run --capabilities` rather than inferring
it from a failure. The mechanism is kept for the next revision.

A check that cannot run says SKIP and why, and the script still fails
if anything actually disagrees. Nothing here reports a pass it did not
perform.
"""

import argparse
import ast
import contextlib
import hashlib
import io
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import types
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "python"))

from cft_golden import FORMATS, asm, chars, seq, seqprogs   # noqa: E402
from cft_golden import divfull                              # noqa: E402
from cft_golden import softfloat as sf                      # noqa: E402
import gen_odes                                             # noqa: E402
try:                                    # the ODE rows' 300-digit arm only
    import mpmath                                           # noqa: E402
except ImportError:                     # pragma: no cover
    mpmath = None

PASS, FAIL, SKIP = [], [], []
T0 = time.time()


def _write_lf(path, text):
    """Write text with LF line ends on every platform. Path.write_text
    grew its newline= argument in Python 3.10; a Mac's system Python is
    3.9 (found 2026-09-09), so this goes through open()."""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def ok(name, detail=""):
    PASS.append(name)
    print(f"  PASS  {name}" + (f"  {detail}" if detail else ""))


def bad(name, detail):
    FAIL.append(name)
    print(f"  FAIL  {name}  {detail}")


def skip(name, why):
    SKIP.append(name)
    print(f"  SKIP  {name}  {why}")


def sh(cmd, **kw):
    r = subprocess.run([str(c) for c in cmd], capture_output=True,
                       text=True, **kw)
    return r


def values(buf, fmt):
    esz = fmt.width // 8
    return [int.from_bytes(buf[i:i + esz], "little")
            for i in range(0, len(buf), esz)]


def pack(vals, fmt):
    esz = fmt.width // 8
    return b"".join(v.to_bytes(esz, "little") for v in vals)


def to_int(fmt, bits):
    """A non-negative integer held exactly in `fmt` -> a Python int.
    Used to read the Collatz deposits back; raises on anything that is
    not a whole number, which is itself part of the check."""
    u = sf.unpack(fmt, bits)
    if u.kind == sf.ZERO:
        return 0
    if u.kind not in (sf.NORM, sf.SUB):
        raise ValueError(f"{bits:#x} is not finite")
    if u.sign:
        raise ValueError(f"{bits:#x} is negative")
    m, e = u.m, u.e            # value = m * 2^e, m has p bits
    if e >= 0:
        return m << e
    if m & ((1 << -e) - 1):
        raise ValueError(f"{bits:#x} is not an integer")
    return m >> -e


# ---- the two assemblers ------------------------------------------------

def assemble_both(args, src, image_path):
    """-> the image bytes, or None having recorded a failure."""
    name = src.name
    r = sh([args.asm, src, "-o", image_path])
    if r.returncode != 0:
        bad(f"{name}: cft-asm", r.stderr.strip().splitlines()[-1:] or [""])
        return None
    c_bytes = Path(image_path).read_bytes()
    try:
        py_bytes = asm.assemble(src.read_text(encoding="utf-8"), str(src))
    except asm.AsmError as exc:
        bad(f"{name}: asm.py", str(exc))
        return None
    if c_bytes != py_bytes:
        bad(f"{name}: two assemblers",
            f"cft-asm {len(c_bytes)} bytes sha "
            f"{hashlib.sha256(c_bytes).hexdigest()[:16]}, asm.py "
            f"{len(py_bytes)} bytes sha "
            f"{hashlib.sha256(py_bytes).hexdigest()[:16]}")
        return None
    return c_bytes


def roundtrip(args, name, image, tmp):
    """Disassemble with both, compare, and re-assemble both ways."""
    p = tmp / (name + ".rt.cftp")
    p.write_bytes(image)
    r = sh([args.asm, "-d", p])
    if r.returncode != 0:
        bad(f"{name}: cft-asm -d", r.stderr.strip())
        return
    ctext = r.stdout.replace("\r\n", "\n")
    pytext = asm.disassemble(image)
    if ctext != pytext:
        bad(f"{name}: two disassemblers", "the texts differ")
        return
    src = tmp / (name + ".rt.cfta")
    _write_lf(src, pytext)
    back = tmp / (name + ".rt2.cftp")
    r = sh([args.asm, src, "-o", back])
    if r.returncode != 0:
        bad(f"{name}: re-assembly", r.stderr.strip())
        return
    if back.read_bytes() != image or asm.assemble(pytext, name) != image:
        bad(f"{name}: round trip", "assemble(disassemble(x)) != x")
        return
    ok(f"{name}: disassemble/re-assemble round trip")


# ---- the runner --------------------------------------------------------

def runner_caps(args):
    r = sh([args.runner, "--capabilities"])
    if r.returncode != 0:
        return {}
    out = {}
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            out[parts[0]] = parts[1]
    return out


def run_image(args, image_path, tmp, tag, iota=None, a=None, b=None,
              c=None, bank=None, scratch_in=None, scratch_out=None):
    """-> (deposits bytes, report dict), or (None, stderr)."""
    dep = tmp / (tag + ".dep.bin")
    cmd = [args.runner, image_path, "--out", dep]
    if iota is not None:
        cmd += ["--iota", iota]
    if a is not None:
        cmd += ["--a", a]
    if b is not None:
        cmd += ["--b", b]
    if c is not None:
        cmd += ["--c", c]
    if bank is not None:
        cmd += ["--bank", bank]
    if scratch_in is not None:
        cmd += ["--scratch-in", scratch_in]
    if scratch_out is not None:
        cmd += ["--scratch-out", scratch_out]
    r = sh(cmd)
    if r.returncode != 0:
        return None, r.stderr.strip()
    report = {}
    for line in r.stdout.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            report[parts[0]] = parts[1].strip()
    return dep.read_bytes(), report


def model_run(image, a_vals, b_vals=None, c_vals=None):
    """The same image through seq.py's executor - the golden model, and
    the definition of correct. Returns None when the image is outside
    what the model can load today (a BANK_EXT image, or a program that
    names a register above 15), which is a fact worth printing rather
    than an error."""
    try:
        prog = seq.Program.from_bytes(image)
    except seq.ProgramError:
        return None
    n = len(a_vals)
    res = seq.run(prog, a_vals, b_vals or [0] * n, c_vals or [0] * n)
    return res


# ================= the individual rows ==================================

def check_divsqrt(name, image):
    """Byte equality with the image seqprogs.py generates. The
    assembler's strongest single check."""
    kind, fmtname = name.split("-")
    fmt = FORMATS[fmtname]
    prog = (seqprogs.div_program_for(fmt) if kind == "div"
            else seqprogs.sqrt_program_for(fmt))
    want = prog.to_bytes()
    if image != want:
        bad(f"{name}: equals seqprogs", f"{len(image)} bytes vs {len(want)}")
        return
    ok(f"{name}: byte-identical to seqprogs.{kind}_program({fmtname})",
       f"{len(prog.insns)} insns, {len(prog.consts)} consts")


def check_divsqrt_runs(args, name, image_path, tmp, n=48):
    """The core, end to end: the host's prep, the image through
    positive-run, the host's finish, against the library's own divide
    or square root. This is the row's functional arm and it exercises
    libcft's executor as well as the file."""
    kind, fmtname = name.split("-")
    fmt = FORMATS[fmtname]
    rng = random.Random(sum(ord(ch) for ch in name))
    a_in, b_in, prep = [], [], []
    while len(prep) < n:
        xa = rng.getrandbits(fmt.width)
        xb = rng.getrandbits(fmt.width)
        if kind == "div":
            special, core = seqprogs.div_prep(fmt, xa, xb)
            if special is not None:
                continue
            ac, bc, D, sq = core
            a_in.append(ac)
            b_in.append(bc)
            prep.append((xa, xb, D, sq))
        else:
            special, core = seqprogs.sqrt_prep(fmt, xa)
            if special is not None:
                continue
            acen, D2 = core
            a_in.append(acen)
            b_in.append(0)
            prep.append((xa, None, D2, None))
    ap = tmp / (name + ".a.bin")
    bp = tmp / (name + ".b.bin")
    ap.write_bytes(pack(a_in, fmt))
    bp.write_bytes(pack(b_in, fmt))
    dep, report = run_image(args, image_path, tmp, name, a=ap, b=bp)
    if dep is None:
        bad(f"{name}: positive-run", report)
        return
    got = values(dep, fmt)
    for i, (xa, xb, D, sq) in enumerate(prep):
        d0, d1, d2 = got[3 * i:3 * i + 3]
        if kind == "div":
            bits, _fl = seqprogs.div_finish(fmt, d0, d1, d2, D, sq,
                                            sf.RND_RNE)
            want, _wf = sf.div(fmt, xa, xb, sf.RND_RNE)
        else:
            bits, _fl = seqprogs.sqrt_finish(fmt, d0, d1, d2, D,
                                             sf.RND_RNE)
            want, _wf = sf.sqrt(fmt, xa, sf.RND_RNE)
        if bits != want:
            bad(f"{name}: {kind} through the runner",
                f"lane {i}: {bits:#x} vs {want:#x}")
            return
    ok(f"{name}: {n} correctly-rounded {kind}s through positive-run",
       f"deposits {report.get('sha256', '')[:16]}")


def check_collatz(args, name, image, image_path, tmp):
    fmt = FORMATS["fp256"]
    img = asm.Image.from_bytes(image)

    # (a) the nine constants, DERIVED here from the format exactly as
    #     host/tools/collatz.c derives them, against what the file says
    p = fmt.prec
    want = [
        sf.one_bits(fmt) - (1 << fmt.man_w),              # 0.5
        sf.one_bits(fmt),                                 # 1
        (fmt.bias + 1) << fmt.man_w | (1 << (fmt.man_w - 1)),   # 3
        (1 << (fmt.width - 1)) | ((fmt.bias + 1) << fmt.man_w)
        | (1 << (fmt.man_w - 1)),                         # -3
        sf.zero_bits(fmt),                                # +0
        (fmt.bias + p) << fmt.man_w,                      # 2^p
        p - 1,                                            # raw integer
        (p - 1) + fmt.bias,                               # raw integer
        1,                                                # raw integer
    ]
    if img.consts != want:
        for i, (g, w) in enumerate(zip(img.consts, want)):
            if g != w:
                bad(f"{name}: constant {i}", f"{g:#x} vs the derived {w:#x}")
                return
        bad(f"{name}: constants", f"{len(img.consts)} of them, want 9")
        return
    ok(f"{name}: nine constants match their derivation from fp256")

    # (b) the tool as the oracle
    exe = None
    for cand in ("cft-collatz.exe", "cft-collatz"):
        p2 = Path(args.tools_dir) / cand
        if p2.exists():
            exe = p2
            break
    if exe is None:
        skip(f"{name}: against cft-collatz",
             f"no cft-collatz in {args.tools_dir} (make -C host collatz)")
        return
    recs = tmp / "collatz.recs"
    n = 64
    r = sh([exe, "--mode", "sweep", "--from", "1", "--to", str(n + 1),
            "--format", "fp256", "--engine", "program",
            "--records", recs, "--quiet"])
    if r.returncode != 0:
        bad(f"{name}: cft-collatz", r.stderr.strip() or r.stdout.strip())
        return
    tool = {}
    for line in recs.read_text().splitlines():
        f = line.split()
        if len(f) == 5:
            tool[int(f[0])] = (int(f[1]), int(f[2]), f[4])

    # The starting values are FLOATS here, not the index ramp: --iota
    # lays down integer BIT PATTERNS, which is what a hash wants and
    # not what an arithmetic kernel does. All three streams are fed,
    # because all three are lane state the tool carries across calls:
    # a = n, b = the step count so far, c = the peak so far, which on
    # the first call is n itself.
    a_vals = []
    for i in range(n):
        v, _fl = chars.from_decimal(fmt, str(i + 1), sf.RND_RNE)
        a_vals.append(v)
    ap = tmp / (name + ".a.bin")
    bp = tmp / (name + ".b.bin")
    cp = tmp / (name + ".c.bin")
    ap.write_bytes(pack(a_vals, fmt))
    bp.write_bytes(pack([sf.zero_bits(fmt)] * n, fmt))
    cp.write_bytes(pack(a_vals, fmt))
    dep, report = run_image(args, image_path, tmp, name, a=ap, b=bp, c=cp)
    if dep is None:
        bad(f"{name}: positive-run", report)
        return
    got = values(dep, fmt)
    seen = 0
    for i in range(n):
        nfin, steps, peak, esc = got[4 * i:4 * i + 4]
        start = i + 1
        if start not in tool:
            bad(f"{name}: cft-collatz", f"no record for {start}")
            return
        t_steps, t_peak, t_ok = tool[start]
        if to_int(fmt, nfin) != 1:
            bad(f"{name}: n0={start}", "1024 steps did not reach 1")
            return
        if to_int(fmt, steps) != t_steps or to_int(fmt, peak) != t_peak:
            bad(f"{name}: n0={start}",
                f"steps {to_int(fmt, steps)}/{t_steps}, "
                f"peak {to_int(fmt, peak)}/{t_peak}")
            return
        if (to_int(fmt, esc) != 0) != (t_ok == "esc"):
            bad(f"{name}: n0={start}", "escaped disagrees with the tool")
            return
        seen += 1
    ok(f"{name}: {seen} trajectories match cft-collatz's own records",
       f"steps and peak, exactly")


def check_zoom_scan(args, name, image, image_path, tmp):
    """The escape map against seq.py's executor - the model IS the
    definition of correct, and running the same image both ways puts
    libcft's executor and the file in the same sentence."""
    fmt = FORMATS["fp256"]
    n = 32
    # real points from -2 to 0.5: inside the set, on the boundary, and
    # well outside it, so both arms of the SETACT guard are taken
    a_vals = []
    for i in range(n):
        v, _fl = chars.from_decimal(fmt, f"{-2.0 + 2.5 * i / n:.9f}",
                                    sf.RND_RNE)
        a_vals.append(v)
    ap = tmp / (name + ".a.bin")
    ap.write_bytes(pack(a_vals, fmt))
    dep, report = run_image(args, image_path, tmp, name, a=ap)
    if dep is None:
        bad(f"{name}: positive-run", report)
        return
    res = model_run(image, a_vals)
    if res is None:
        skip(f"{name}: against seq.py", "the model cannot load this image")
        return
    got = values(dep, fmt)
    if got != res.deposits:
        for i, (g, w) in enumerate(zip(got, res.deposits)):
            if g != w:
                bad(f"{name}: lane {i}", f"{g:#x} vs the model's {w:#x}")
                return
        bad(f"{name}: deposits", f"{len(got)} vs {len(res.deposits)}")
        return
    if [int(x) for x in res.counts] != [1] * n:
        bad(f"{name}: counts", "a lane deposited the wrong number")
        return
    ok(f"{name}: {n} points bit-identical to seq.py's executor",
       f"deposits {report.get('sha256', '')[:16]}")


def check_lowbias32(args, name, image, image_path, tmp):
    fmt = FORMATS["fp32"]
    K1, K2 = 0x7FEB352D, 0x846CA68B

    def lowbias32(x):
        x ^= x >> 16
        x = (x * K1) & 0xFFFFFFFF
        x ^= x >> 15
        x = (x * K2) & 0xFFFFFFFF
        x ^= x >> 16
        return x

    n = 4096
    dep, report = run_image(args, image_path, tmp, name, iota=str(n))
    if dep is None:
        bad(f"{name}: positive-run", report)
        return
    got = values(dep, fmt)
    for i in range(n):
        if got[i] != lowbias32(i):
            bad(f"{name}: seed {i}", f"{got[i]:#010x} vs "
                                     f"{lowbias32(i):#010x}")
            return
    if not report.get("flags", "").endswith("clean"):
        bad(f"{name}: flags", f"the draw stream signalled: "
                              f"{report.get('flags')}")
        return
    ok(f"{name}: {n} draws over the index ramp match lowbias32",
       "and the run signals nothing")


def check_horner_bank(args, name, image, image_path, tmp, caps):
    fmt = FORMATS["fp64"]
    img = asm.Image.from_bytes(image)
    nk = img.n_consts

    # (a) the shape a BANK_EXT image must have
    if not img.bank_external:
        bad(f"{name}: BANK_EXT", "the image does not set the flag")
        return
    if len(image) != 32 + 8 * len(img.insns):
        bad(f"{name}: image size",
            f"{len(image)} bytes; a BANK_EXT image is 32 + 8 * n_insns "
            f"= {32 + 8 * len(img.insns)}")
        return
    ok(f"{name}: carries no constant section",
       f"{len(image)} bytes = 32 + 8 * {len(img.insns)}, n_consts {nk}")

    # (b) two banks, and a model computation for each

    def bank_exp():
        """C[k] = 1/(nk-1-k)!, so the polynomial is the truncated
        exponential series. Each coefficient is the library's own
        correctly-rounded 1/f rather than a decimal somebody typed."""
        one, _ = chars.from_decimal(fmt, "1", sf.RND_RNE)
        out = []
        for k in range(nk):
            f = 1
            for j in range(2, nk - k):
                f *= j
            den, _ = chars.from_decimal(fmt, str(f), sf.RND_RNE)
            v, _ = sf.div(fmt, one, den, sf.RND_RNE)
            out.append(v)
        return out

    def bank_ramp():
        out = []
        for k in range(nk):
            v, _fl = chars.from_decimal(fmt, str(k + 1), sf.RND_RNE)
            out.append(v)
        return out

    xs = []
    for i in range(16):
        v, _fl = chars.from_decimal(fmt, f"{-1.0 + 2.0 * i / 16:.6f}",
                                    sf.RND_RNE)
        xs.append(v)
    ap = tmp / (name + ".x.bin")
    ap.write_bytes(pack(xs, fmt))

    def model(coeffs):
        out = []
        for x in xs:
            acc = coeffs[0]
            for k in range(1, nk):
                acc, _fl = sf.compute(fmt, sf.OP_FMA, acc, x, coeffs[k],
                                      sf.RND_RNE)
            out.append(acc)
        return out

    # The bank files are COMMITTED DATA, not something this script
    # writes and then compares against itself. They are read from the
    # tree and used as the run's input; separately, each is checked
    # against the derivation its name claims, so that a row cannot pass
    # because the check and the data drifted together.
    banks = {}
    for tag, derive in (("exp", bank_exp), ("ramp", bank_ramp)):
        bpath = HERE / f"{name}.{tag}.bank"
        if not bpath.exists():
            bad(f"{name}: {tag} bank", f"{bpath.name} is not in the tree")
            return
        got = values(bpath.read_bytes(), fmt)
        if len(got) != nk:
            bad(f"{name}: {tag} bank",
                f"{len(got)} values, the program addresses {nk}")
            return
        if got != derive():
            bad(f"{name}: {tag} bank",
                "the committed file does not match its own derivation")
            return
        banks[tag] = got
    ok(f"{name}: both bank files match their derivations",
       f"{nk} fp64 values each, {nk * 8} bytes")

    spliced_out = {}
    for tag, coeffs in banks.items():
        bpath = HERE / f"{name}.{tag}.bank"

        # The arm that runs today: the same instruction stream with the
        # bank spliced in as an ordinary constant section. It is the
        # SAME computation by the definition of BANK_EXT, so it checks
        # the program and the two banks; what it cannot check is the
        # library's bank path, which is the arm below.
        equiv = asm.Image(fmt, img.insns, coeffs, img.max_deposits, flags=0)
        epath = tmp / f"{name}.{tag}.equiv.cftp"
        epath.write_bytes(equiv.to_bytes())
        dep, report = run_image(args, epath, tmp, f"{name}-{tag}", a=ap)
        if dep is None:
            bad(f"{name}: {tag} bank, spliced", report)
            return
        got = values(dep, fmt)
        want = model(coeffs)
        if got != want:
            for i, (g, w) in enumerate(zip(got, want)):
                if g != w:
                    bad(f"{name}: {tag} bank, lane {i}",
                        f"{g:#x} vs the model's {w:#x}")
                    return
        spliced_out[tag] = got
    ok(f"{name}: two banks through the equivalent constant-carrying "
       f"image", f"{len(xs)} points each, against a softfloat Horner")

    if banks["exp"] == banks["ramp"]:
        bad(f"{name}: the two banks", "are the same bank")
        return
    if spliced_out["exp"] == spliced_out["ramp"]:
        bad(f"{name}: the two banks", "produced the same answers")
        return

    # (c) the real bank path, when the runner has one
    if caps.get("bank-path") != "present":
        skip(f"{name}: the BANK_EXT path itself",
             "positive-run reports bank-path absent - "
             "cft_program_run_bank arrives with the host half")
        return
    for tag, coeffs in banks.items():
        bpath = HERE / f"{name}.{tag}.bank"
        dep, report = run_image(args, image_path, tmp, f"{name}-{tag}-bank",
                                a=ap, bank=bpath)
        if dep is None:
            bad(f"{name}: {tag} bank through cft_program_run_bank", report)
            return
        if values(dep, fmt) != spliced_out[tag]:
            bad(f"{name}: {tag} bank through cft_program_run_bank",
                "differs from the spliced image")
            return
    ok(f"{name}: both banks through cft_program_run_bank",
       "identical to the spliced images")


def check_full(name, image):
    """The whole divide / square root on the chip: byte equality with
    the image divfull.py generates - which is also the image libcft
    carries in host/src/divfull_images.h, so this row and the library's
    generated header are held to the same bytes."""
    kind, fmtname = name.split("-")
    fmt = FORMATS[fmtname]
    prog = (divfull.div_full_program_for(fmt) if kind == "divfull"
            else divfull.sqrt_full_program_for(fmt))
    want = prog.to_bytes()
    if image != want:
        bad(f"{name}: equals divfull", f"{len(image)} bytes vs {len(want)}")
        return
    ok(f"{name}: byte-identical to divfull.{kind[:-4]}_full_program({fmtname})",
       f"{len(prog.insns)} insns, BANK_EXT, {prog.n_consts} bank words")


def check_full_runs(args, name, image_path, tmp, n=64):
    """The run arm: RAW operands - specials, subnormals, the hard
    families and randoms - through positive-run with the RNE bank, and
    both deposits held to the contract. No host prep, no host finish:
    if the deposits are right, the whole operation is on the chip."""
    kind, fmtname = name.split("-")
    fmt = FORMATS[fmtname]
    is_sqrt = kind == "sqrtfull"
    rng = random.Random(sum(ord(ch) for ch in name))
    one = sf.one_bits(fmt)
    xs = [0, fmt.sign_mask, sf.inf_bits(fmt, 0), sf.inf_bits(fmt, 1),
          sf.qnan_bits(fmt), sf.snan_bits(fmt), 1, fmt.man_mask,
          sf.min_normal_bits(fmt), one, one | fmt.sign_mask,
          sf.max_normal_bits(fmt), one + 1, one - 1]
    while len(xs) < n:
        xs.append(rng.getrandbits(fmt.width))
    ys = [rng.getrandbits(fmt.width) for _ in xs]
    ys[:6] = [one, one, one, 0, fmt.sign_mask, sf.inf_bits(fmt, 0)]
    bank = (divfull.bank_sqrt(fmt, sf.RND_RNE) if is_sqrt
            else divfull.bank(fmt, sf.RND_RNE))
    ap = tmp / (name + ".a.bin")
    bp = tmp / (name + ".b.bin")
    kp = tmp / (name + ".bank.bin")
    ap.write_bytes(pack(xs, fmt))
    bp.write_bytes(pack(ys, fmt))
    kp.write_bytes(pack(bank, fmt))
    dep, report = run_image(args, image_path, tmp, name, a=ap,
                            b=None if is_sqrt else bp, bank=kp)
    if dep is None:
        bad(f"{name}: positive-run", report)
        return
    got = values(dep, fmt)
    if len(got) != 2 * len(xs):
        bad(f"{name}: deposits", f"{len(got)} words for {len(xs)} lanes")
        return
    flags = 0
    for i, a in enumerate(xs):
        want, wf = (sf.sqrt(fmt, a, sf.RND_RNE) if is_sqrt
                    else sf.div(fmt, a, ys[i], sf.RND_RNE))
        flags |= wf
        if got[2 * i] != want:
            bad(f"{name}: {kind[:-4]} through the runner",
                f"lane {i}: {got[2 * i]:#x} vs {want:#x}")
            return
        if got[2 * i + 1] != wf:
            bad(f"{name}: flags through the runner",
                f"lane {i}: {got[2 * i + 1]:#x} vs {wf:#x}")
            return
    ok(f"{name}: {len(xs)} raw lanes, bits and flags, through positive-run",
       f"specials included; flags {flags:#07b}")


def check_normalabs(args, name, image, image_path, tmp, n=64):
    """The normal-only mask: byte equality with seqprogs, then every
    class in both signs and randoms through positive-run, held to
    softfloat's class - |x| for a normal, +0 for anything else - and the
    run must signal nothing (integer instructions, not FP compares)."""
    fmt = FORMATS[name.split("-")[1]]
    prog = seqprogs.normal_abs_program_for(fmt)
    want = prog.to_bytes()
    if image != want:
        bad(f"{name}: equals seqprogs", f"{len(image)} bytes vs {len(want)}")
        return
    ok(f"{name}: byte-identical to seqprogs.normal_abs_program({fmt.name})",
       f"{len(prog.insns)} insns, {len(prog.consts)} consts")
    rng = random.Random(sum(ord(ch) for ch in name))
    xs = [0, fmt.sign_mask, sf.inf_bits(fmt, 0), sf.inf_bits(fmt, 1),
          sf.qnan_bits(fmt), sf.snan_bits(fmt), sf.snan_bits(fmt) | fmt.sign_mask,
          1, fmt.man_mask, 1 | fmt.sign_mask, sf.min_normal_bits(fmt),
          sf.min_normal_bits(fmt) | fmt.sign_mask, sf.max_normal_bits(fmt),
          sf.max_normal_bits(fmt, 1), sf.one_bits(fmt), sf.one_bits(fmt, 1)]
    while len(xs) < n:
        xs.append(rng.getrandbits(fmt.width))
    ap = tmp / (name + ".a.bin")
    ap.write_bytes(pack(xs, fmt))
    dep, report = run_image(args, image_path, tmp, name, a=ap)
    if dep is None:
        bad(f"{name}: positive-run", report)
        return
    got = values(dep, fmt)
    for i, x in enumerate(xs):
        w = seqprogs.normal_abs(fmt, x)
        if got[i] != w:
            bad(f"{name}: the mask through the runner",
                f"lane {i}: {x:#x} -> {got[i]:#x} vs {w:#x}")
            return
    flags = report.get("flags", "0").split()[0] if report.get("flags") else "0"
    if int(flags, 0) != 0:
        bad(f"{name}: the mask signalled", f"flags {report.get('flags')}")
        return
    ok(f"{name}: {len(xs)} raw lanes of every class through positive-run",
       "and no flag raised")


# ================= revision 3: the scratch rows =========================
#
# Four programs the round added, and one reference. Each row's check has
# two arms and they are not the same claim:
#
#   the STATIC arm - the constants against their derivation, the header
#   against what the source declares, the encoding against the contract
#   - runs today, on this tree, with no scratch anywhere in it;
#
#   the EXECUTION arm needs libcft to know the four control codes, the
#   header's scratch_io word and the ninth constant-index bit. Those
#   arrived with the model and host halves of the same round, so the
#   arm runs. While it did not, it said SKIP and WHICH feature it
#   waited on, by name, and `positive-run --capabilities` is what it
#   asks rather than inferring it from a failure - which is what the
#   round before did for the BANK_EXT path, and what the next
#   revision will use again.


def spill_model(fmt, xs, nterms=40):
    """The arithmetic both spill rows perform: forty terms
    t_k = x^(k+1), combined as acc = t_0 then acc = fma(acc, W, t_k).
    Written once here, so that "the two programs agree" and "either
    program is right" are two different assertions."""
    one, _ = chars.from_decimal(fmt, "1", sf.RND_RNE)
    w, _ = chars.from_decimal(fmt, "0.5", sf.RND_RNE)
    out = []
    for x in xs:
        p, _ = sf.compute(fmt, sf.OP_MUL, x, one, 0, sf.RND_RNE)
        acc = p
        for _k in range(1, nterms):
            p, _ = sf.compute(fmt, sf.OP_MUL, p, x, 0, sf.RND_RNE)
            acc, _ = sf.compute(fmt, sf.OP_FMA, acc, w, p, sf.RND_RNE)
        out.append(acc)
    return out


def spill_inputs(fmt, n=64):
    """Points in [-1.5, 1.5), which keeps x^40 finite and gives the
    accumulation something to round."""
    xs = []
    for i in range(n):
        v, _fl = chars.from_decimal(fmt, f"{-1.5 + 3.0 * i / n:.9f}",
                                    sf.RND_RNE)
        xs.append(v)
    return xs


def check_spill_ref(args, name, image, image_path, tmp):
    """The no-scratch twin, run and held to the model. This row runs
    TODAY, which is what makes it worth having: when the scratch lands,
    the spill row is compared against a reference that is already
    known-good rather than against another unrun program."""
    fmt = FORMATS["fp64"]
    xs = spill_inputs(fmt)
    ap = tmp / (name + ".a.bin")
    ap.write_bytes(pack(xs, fmt))
    dep, report = run_image(args, image_path, tmp, name, a=ap)
    if dep is None:
        bad(f"{name}: positive-run", report)
        return None
    got = values(dep, fmt)
    want = spill_model(fmt, xs)
    if got != want:
        for i, (g, w) in enumerate(zip(got, want)):
            if g != w:
                bad(f"{name}: lane {i}", f"{g:#x} vs the model's {w:#x}")
                return None
        bad(f"{name}: deposits", f"{len(got)} vs {len(want)}")
        return None
    ok(f"{name}: {len(xs)} lanes against a softfloat model of the same "
       f"forty-term recurrence", f"deposits {report.get('sha256', '')[:16]}")
    return got


def check_spill(args, name, image, image_path, tmp, caps, ref_deposits):
    """The spilling program: the same arithmetic, with all forty terms
    live at once and eight of them therefore in the scratch."""
    fmt = FORMATS["fp64"]
    img = asm.Image.from_bytes(image)

    # (a) the shape the source claims
    one, _ = chars.from_decimal(fmt, "1", sf.RND_RNE)
    half, _ = chars.from_decimal(fmt, "0.5", sf.RND_RNE)
    if img.consts != [one, half]:
        bad(f"{name}: constants", "ONE and W are not 1.0 and 0.5")
        return
    top, indexed = img.scratch_use()
    if top != 39 or indexed:
        bad(f"{name}: the scratch it uses",
            f"highest static slot {top}, indexed={indexed}; want 39 and "
            f"no indexing")
        return
    # The SETS of slots, not just their count and their maximum: a
    # store that moved to a slot another store already writes would
    # leave the highest slot where it was and the counts where they
    # were, and only the MANIFEST would notice.
    stored, loaded = [], []
    for w in img.insns:
        d = asm.decode(w)
        if not d["ctrl"]:
            continue
        if d["op"] == asm.STL:
            stored.append(d["imm"] & asm.SLOT_MASK)
        elif d["op"] == asm.LDL:
            loaded.append(d["imm"] & asm.SLOT_MASK)
    want_slots = list(range(40))
    if sorted(stored) != want_slots or sorted(loaded) != want_slots:
        bad(f"{name}: the spill itself",
            f"{len(stored)} stl over {len(set(stored))} slots and "
            f"{len(loaded)} ldl over {len(set(loaded))}; want each of "
            f"slots 0..39 written once and read once")
        return
    if img.features() != ["SCRATCH"]:
        bad(f"{name}: features", f"{img.features()}, want ['SCRATCH']")
        return
    ok(f"{name}: forty values live across the phase boundary",
       f"40 stl, 40 ldl, slots 0..39, needs SCRATCH")

    # (b) the arithmetic, which needs a libcft that knows the codes
    if caps.get("scratch") != "present":
        skip(f"{name}: the same deposits as spill-ref-fp64",
             "positive-run reports scratch absent - the four control "
             "codes arrive with the model and host halves")
        return
    xs = spill_inputs(fmt)
    ap = tmp / (name + ".a.bin")
    ap.write_bytes(pack(xs, fmt))
    dep, report = run_image(args, image_path, tmp, name, a=ap)
    if dep is None:
        bad(f"{name}: positive-run", report)
        return
    got = values(dep, fmt)
    want = spill_model(fmt, xs)
    if got != want:
        for i, (g, w) in enumerate(zip(got, want)):
            if g != w:
                bad(f"{name}: lane {i}", f"{g:#x} vs the model's {w:#x}")
                return
    if ref_deposits is not None and got != ref_deposits:
        bad(f"{name}: against spill-ref-fp64",
            "the spilled program and the unspilled one disagree")
        return
    ok(f"{name}: {len(xs)} lanes identical to spill-ref-fp64 and to the "
       f"model", f"deposits {report.get('sha256', '')[:16]}")


def conv_model(fmt, xs, nsamp=16, ntap=3):
    """a[0] = x, a[k+1] = a[k]*GROW + SHIFT; then
    y[i] = a[i]*W0 + a[i+1]*W1 + a[i+2]*W2, in that order - one mul and
    two fmas, exactly as the program issues them."""
    grow, _ = chars.from_decimal(fmt, "1.25", sf.RND_RNE)
    shift, _ = chars.from_decimal(fmt, "0.5", sf.RND_RNE)
    w = [chars.from_decimal(fmt, s, sf.RND_RNE)[0]
         for s in ("0.25", "0.5", "0.25")]
    out = []
    for x in xs:
        a = []
        v = x                       # copysign(x, x) is x, exactly
        for _k in range(nsamp):
            a.append(v)
            v, _ = sf.compute(fmt, sf.OP_FMA, v, grow, shift, sf.RND_RNE)
        for i in range(nsamp - ntap + 1):
            acc, _ = sf.compute(fmt, sf.OP_MUL, a[i], w[0], 0, sf.RND_RNE)
            for t in range(1, ntap):
                acc, _ = sf.compute(fmt, sf.OP_FMA, a[i + t], w[t], acc,
                                    sf.RND_RNE)
            out.append(acc)
    return out


def check_conv(args, name, image, image_path, tmp, caps):
    fmt = FORMATS["fp64"]
    img = asm.Image.from_bytes(image)

    # (a) the six constants, derived here rather than transcribed
    want = [1]                                   # IONE, the raw integer 1
    for s in ("1.25", "0.5", "0.25", "0.5", "0.25"):
        want.append(chars.from_decimal(fmt, s, sf.RND_RNE)[0])
    if img.consts != want:
        for i, (g, w) in enumerate(zip(img.consts, want)):
            if g != w:
                bad(f"{name}: constant {i}", f"{g:#x} vs the derived {w:#x}")
                return
        bad(f"{name}: constants", f"{len(img.consts)} of them, want 6")
        return
    top, indexed = img.scratch_use()
    if top is not None or not indexed:
        bad(f"{name}: the scratch it uses",
            f"highest static slot {top}, indexed={indexed}; a convolution "
            f"under loop counters reaches the memory ONLY through "
            f"stx/ldx")
        return
    if img.max_deposits != 14:
        bad(f"{name}: deposits", f"{img.max_deposits}, want 14")
        return
    ok(f"{name}: an indexed local array, no static slot at all",
       f"6 constants derived, 14 deposits a lane, needs SCRATCH")

    # (b) the convolution itself
    if caps.get("scratch") != "present":
        skip(f"{name}: the convolution against the model",
             "positive-run reports scratch absent - stx/ldx arrive with "
             "the model and host halves")
        return
    xs = []
    for i in range(24):
        v, _fl = chars.from_decimal(fmt, f"{-0.75 + 1.5 * i / 24:.9f}",
                                    sf.RND_RNE)
        xs.append(v)
    ap = tmp / (name + ".a.bin")
    ap.write_bytes(pack(xs, fmt))
    dep, report = run_image(args, image_path, tmp, name, a=ap)
    if dep is None:
        bad(f"{name}: positive-run", report)
        return
    got = values(dep, fmt)
    want = conv_model(fmt, xs)
    if got != want:
        for i, (g, w) in enumerate(zip(got, want)):
            if g != w:
                bad(f"{name}: output {i}", f"{g:#x} vs the model's {w:#x}")
                return
        bad(f"{name}: deposits", f"{len(got)} vs {len(want)}")
        return
    ok(f"{name}: {len(xs)} lanes x 14 outputs against a softfloat "
       f"three-tap convolution", f"deposits {report.get('sha256', '')[:16]}")


def _patch_trip(image, was, now, deposits):
    """The same program with its one REPEAT's trip count changed and
    max_deposits scaled to match - which is how the 'single longer run'
    the resumable row is checked against is built. An image transform,
    so that the long run is demonstrably the SAME program rather than a
    second source that might have drifted."""
    img = asm.Image.from_bytes(image)
    insns, found = [], 0
    for word in img.insns:
        d = asm.decode(word)
        if d["ctrl"] and d["op"] == asm.REPEAT and d["imm"] == was:
            word = asm.repeat(now)
            found += 1
        insns.append(word)
    if found != 1:
        raise ValueError(f"{found} repeat {was} in the image, want one")
    return asm.Image(img.fmt, insns, img.consts, deposits, img.flags,
                     scratch_depth=img.scratch_depth,
                     scratch_io=img.scratch_io)


def check_resume(args, name, image, image_path, tmp, caps):
    fmt = FORMATS["fp64"]
    img = asm.Image.from_bytes(image)

    # (a) the header the source declares
    want = [chars.from_decimal(fmt, "1.5", sf.RND_RNE)[0],
            chars.from_decimal(fmt, "0.25", sf.RND_RNE)[0],
            1]
    if img.consts != want:
        bad(f"{name}: constants", "MUL, ADD and the raw integer 1")
        return
    if not img.scratch_io_declared or img.flags != asm.FLAG_SCRATCH_IO:
        bad(f"{name}: flags", f"{img.flags:#010x}, want SCRATCH_IO alone")
        return
    if (img.n_scratch_in, img.n_scratch_out) != (2, 2):
        bad(f"{name}: scratch_io",
            f"in {img.n_scratch_in}, out {img.n_scratch_out}; want 2 and 2")
        return
    if img.scratch_io != (2 | (2 << 16)):
        bad(f"{name}: header word 7", f"{img.scratch_io:#010x}")
        return
    if img.features() != ["SCRATCH", "SCRATCH_IO"]:
        bad(f"{name}: features", f"{img.features()}")
        return
    ok(f"{name}: carries its state in and out",
       f"scratch_io 0x{img.scratch_io:08x} behind flags bit 1, "
       f"{img.max_deposits} deposits a lane")

    # (b) two runs against one longer one
    if caps.get("scratch-io") != "present":
        skip(f"{name}: two runs against one longer run",
             "positive-run reports scratch-io absent - "
             "cft_program_run_ex arrives with the host half")
        return
    n = 32
    xs = [0] * n                       # the streams are unread here
    ap = tmp / (name + ".a.bin")
    ap.write_bytes(pack(xs, fmt))
    # the initial block: v = 1 + i/32, n = 0, lane-major
    state = []
    for i in range(n):
        v, _fl = chars.from_decimal(fmt, f"{1.0 + i / n:.9f}", sf.RND_RNE)
        state += [v, 0]
    s0 = tmp / (name + ".s0.bin")
    s0.write_bytes(pack(state, fmt))

    long_img = _patch_trip(image, 8, 16, 32)
    lp = tmp / (name + ".long.cftp")
    lp.write_bytes(long_img.to_bytes())

    d1, r1 = run_image(args, image_path, tmp, name + "-1", a=ap,
                       scratch_in=s0, scratch_out=tmp / (name + ".s1.bin"))
    if d1 is None:
        bad(f"{name}: first run", r1)
        return
    d2, r2 = run_image(args, image_path, tmp, name + "-2", a=ap,
                       scratch_in=tmp / (name + ".s1.bin"),
                       scratch_out=tmp / (name + ".s2.bin"))
    if d2 is None:
        bad(f"{name}: second run", r2)
        return
    dl, rl = run_image(args, lp, tmp, name + "-long", a=ap,
                       scratch_in=s0, scratch_out=tmp / (name + ".sl.bin"))
    if dl is None:
        bad(f"{name}: the long run", rl)
        return
    a1, a2, al = values(d1, fmt), values(d2, fmt), values(dl, fmt)
    if len(al) != len(a1) + len(a2):
        bad(f"{name}: shapes", f"{len(a1)} + {len(a2)} != {len(al)}")
        return
    for i in range(n):
        first = al[i * 32: i * 32 + 16]
        second = al[i * 32 + 16: i * 32 + 32]
        if a1[i * 16:(i + 1) * 16] != first:
            bad(f"{name}: lane {i}, first half",
                "the first run is not the long run's first eight steps")
            return
        if a2[i * 16:(i + 1) * 16] != second:
            bad(f"{name}: lane {i}, second half",
                "the resumed run is not the long run's second eight steps")
            return
    if a1 == a2:
        bad(f"{name}: the two runs", "produced the same deposits, so the "
                                     "carried state did nothing")
        return
    ok(f"{name}: a resumed run IS the second half of a longer one",
       f"{n} lanes, 8 + 8 steps against 16, "
       f"scratch-out {r1.get('scratch-out', '')[:16]}")


def check_horner_wide(args, name, image, image_path, tmp, caps):
    fmt = FORMATS["fp64"]
    img = asm.Image.from_bytes(image)
    nk = img.n_consts

    # (a) the shape: BANK_EXT, 300 coefficients, and the ninth index bit
    if not img.bank_external or nk != 300:
        bad(f"{name}: shape", f"BANK_EXT={img.bank_external}, {nk} consts")
        return
    if len(image) != 32 + 8 * len(img.insns):
        bad(f"{name}: image size", f"{len(image)} bytes")
        return
    ninth = 0
    for word in img.insns:
        d = asm.decode(word)
        if d["ctrl"]:
            continue
        for k, (idx, is_const) in enumerate(asm.sources(d)):
            if is_const and idx >= 256:
                if not ((d["imm"] >> asm.KX9_SHIFT[k]) & 1):
                    bad(f"{name}: constant {idx}",
                        f"index past 255 without imm[{asm.KX9_SHIFT[k]}]")
                    return
                ninth += 1
    if ninth != nk - 256:
        bad(f"{name}: the ninth bits", f"{ninth} of them, want {nk - 256}")
        return
    if "KX9" not in img.features():
        bad(f"{name}: features", f"{img.features()} does not name KX9")
        return
    ok(f"{name}: {nk} coefficients, {ninth} of them past 255",
       f"{len(image)} bytes = 32 + 8 * {len(img.insns)}, "
       f"features {' '.join(img.features())}")

    # (b) the bank file against its derivation - committed DATA, read
    #     from the tree, checked against the claim its name makes
    bpath = HERE / f"{name}.recip.bank"
    if not bpath.exists():
        bad(f"{name}: the bank", f"{bpath.name} is not in the tree")
        return
    one, _ = chars.from_decimal(fmt, "1", sf.RND_RNE)
    derived = []
    for k in range(nk):
        den, _ = chars.from_decimal(fmt, str(k + 1), sf.RND_RNE)
        v, _ = sf.div(fmt, one, den, sf.RND_RNE)
        if k & 1:
            v ^= 1 << (fmt.width - 1)
        derived.append(v)
    coeffs = values(bpath.read_bytes(), fmt)
    if len(coeffs) != nk:
        bad(f"{name}: the bank", f"{len(coeffs)} values, want {nk}")
        return
    if coeffs != derived:
        bad(f"{name}: the bank",
            "the committed file does not match its own derivation, "
            "C[k] = (-1)^k / (k+1)")
        return
    ok(f"{name}: the bank file matches its derivation",
       f"{nk} fp64 values, {nk * 8} bytes, C[k] = (-1)^k / (k+1)")

    # (c) the Horner itself
    if caps.get("kx9") != "present":
        skip(f"{name}: the Horner against a softfloat one",
             "positive-run reports kx9 absent - the ninth constant-index "
             "bit arrives with the model and host halves")
        return
    xs = []
    for i in range(16):
        v, _fl = chars.from_decimal(fmt, f"{-0.9 + 1.8 * i / 16:.6f}",
                                    sf.RND_RNE)
        xs.append(v)
    ap = tmp / (name + ".x.bin")
    ap.write_bytes(pack(xs, fmt))
    dep, report = run_image(args, image_path, tmp, name, a=ap, bank=bpath)
    if dep is None:
        bad(f"{name}: positive-run", report)
        return
    got = values(dep, fmt)
    want = []
    for x in xs:
        acc = coeffs[0]
        for k in range(1, nk):
            acc, _fl = sf.compute(fmt, sf.OP_FMA, acc, x, coeffs[k],
                                  sf.RND_RNE)
        want.append(acc)
    if got != want:
        for i, (g, w) in enumerate(zip(got, want)):
            if g != w:
                bad(f"{name}: lane {i}", f"{g:#x} vs the model's {w:#x}")
                return
        bad(f"{name}: deposits", f"{len(got)} vs {len(want)}")
        return
    ok(f"{name}: {len(xs)} points against a softfloat degree-{nk - 1} "
       f"Horner", f"deposits {report.get('sha256', '')[:16]}")


# ---- the revision-2 corpus ---------------------------------------------
#
# `seq.random_program` is revision 1 - sixteen registers, no BANK_EXT,
# no register high bits - so the library and that corpus between them
# never exercise the encoding this round actually added. This generator
# does: five-bit register fields, an external bank, kx forced and
# chosen, all four formats, and trip counts that set imm[27:24] (which
# are register high bits on an instruction that HAS a register and
# ordinary count bits on REPEAT, and getting that backwards would be
# invisible everywhere else).

def revision2_program(rng):
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
            trip = rng.choice([1, 3, 1 << 24, (0xF << 24) | 7, 0xFFFFF])
            body.append(f"repeat {trip}")
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


# 120 rather than more: each program costs four cft-asm launches and a
# process spawn on Windows is thirty milliseconds, so this stage is
# most of the target's wall clock. It reaches every feature it exists
# for at this size and the check says so rather than assuming it.
def check_revision2_corpus(args, tmp, trials=120):
    import random as _random
    rng = _random.Random(2026)
    n = regs32 = bank = kx = 0
    for trial in range(trials):
        text = revision2_program(rng)
        try:
            py = asm.assemble(text, f"r2-{trial}")
        except asm.AsmError:
            continue                     # a program the loader refuses
        tag = f"rev2-{trial}"
        src = tmp / (tag + ".cfta")
        out = tmp / (tag + ".cftp")
        _write_lf(src, text)
        r = sh([args.asm, src, "-o", out])
        if r.returncode != 0:
            bad(f"revision-2 corpus [{trial}]: cft-asm", r.stderr.strip())
            return
        if out.read_bytes() != py:
            bad(f"revision-2 corpus [{trial}]: two assemblers",
                "the bytes differ")
            return
        r = sh([args.asm, "-d", out])
        if r.returncode != 0:
            bad(f"revision-2 corpus [{trial}]: cft-asm -d", r.stderr.strip())
            return
        if r.stdout.replace("\r\n", "\n") != asm.disassemble(py):
            bad(f"revision-2 corpus [{trial}]: two disassemblers",
                "the texts differ")
            return
        if asm.assemble(asm.disassemble(py), tag) != py:
            bad(f"revision-2 corpus [{trial}]: round trip",
                "assemble(disassemble(x)) != x")
            return
        # -i must agree line for line, the SHA-256 included
        r = sh([args.asm, "-i", out])
        ci = r.stdout.replace("\r\n", "\n").splitlines()
        for pl in asm.info(py).splitlines():
            key = pl.split()[0]
            cl = next((l for l in ci if l.startswith(key)), None)
            if cl != pl:
                bad(f"revision-2 corpus [{trial}]: -i {key}",
                    f"{pl!r} vs {cl!r}")
                return
        img = asm.Image.from_bytes(py)
        feats = img.features()
        regs32 += "REGS32" in feats
        bank += "BANK_PTR" in feats
        kx += "kx" in feats
        n += 1
    if not (regs32 and bank and kx):
        bad("revision-2 corpus", f"never reached the features it exists "
                                 f"for: REGS32={regs32} BANK={bank} "
                                 f"kx={kx}")
        return
    ok(f"revision-2 corpus: {n} programs identical in both languages",
       f"bytes, disassembly, round trip and -i; {regs32} use REGS32, "
       f"{bank} BANK_EXT, {kx} kx")


# ---- the revision-3 corpus ---------------------------------------------
#
# Revision 2's generator above never emits a scratch instruction, a
# per-run block or a constant index past 255, and the five library rows
# that do cannot be executed on this tree - so without this stage the
# round's own encoding would be checked only where a human wrote it.
# This one reaches all of it: the four control codes, static slots on
# both sides of 255 behind a declared depth, indexed slots, the header's
# scratch_io word, and nine-bit constant indices on each of ra, rb and
# rc. It asserts what it reached rather than assuming it.

def revision3_program(rng):
    fmt = FORMATS[rng.choice(["fp32", "fp64", "fp128", "fp256"])]
    # a bank that sometimes needs the ninth index bit and sometimes
    # does not, so both spellings are exercised
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
                    # bias toward the far half of a big bank, so the
                    # ninth index bit is reached often rather than
                    # occasionally
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
                if nslots and rng.random() < 0.4:
                    slot = f"S{rng.randrange(nslots)}"
                else:
                    slot = str(rng.randrange(depth))
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


def check_revision3_corpus(args, tmp, trials=120):
    import random as _random
    rng = _random.Random(20260908)
    n = scratch = scratch_io = kx9 = indexed = deep_slot = 0
    for trial in range(trials):
        text = revision3_program(rng)
        try:
            py = asm.assemble(text, f"r3-{trial}")
        except asm.AsmError:
            continue                     # a program the loader refuses
        tag = f"rev3-{trial}"
        src = tmp / (tag + ".cfta")
        out = tmp / (tag + ".cftp")
        _write_lf(src, text)
        r = sh([args.asm, src, "-o", out])
        if r.returncode != 0:
            bad(f"revision-3 corpus [{trial}]: cft-asm", r.stderr.strip())
            return
        if out.read_bytes() != py:
            bad(f"revision-3 corpus [{trial}]: two assemblers",
                "the bytes differ")
            return
        r = sh([args.asm, "-d", out])
        if r.returncode != 0:
            bad(f"revision-3 corpus [{trial}]: cft-asm -d", r.stderr.strip())
            return
        if r.stdout.replace("\r\n", "\n") != asm.disassemble(py):
            bad(f"revision-3 corpus [{trial}]: two disassemblers",
                "the texts differ")
            return
        if asm.assemble(asm.disassemble(py), tag) != py:
            bad(f"revision-3 corpus [{trial}]: round trip",
                "assemble(disassemble(x)) != x")
            return
        r = sh([args.asm, "-i", out])
        ci = r.stdout.replace("\r\n", "\n").splitlines()
        for pl in asm.info(py).splitlines():
            key = pl.split()[0]
            cl = next((l for l in ci if l.startswith(key)), None)
            if cl != pl:
                bad(f"revision-3 corpus [{trial}]: -i {key}",
                    f"{pl!r} vs {cl!r}")
                return
        img = asm.Image.from_bytes(py)
        feats = img.features()
        scratch += "SCRATCH" in feats
        scratch_io += "SCRATCH_IO" in feats
        kx9 += "KX9" in feats
        top, ix = img.scratch_use()
        indexed += ix
        deep_slot += (top is not None and top >= 256)
        n += 1
    if not (scratch and scratch_io and kx9 and indexed and deep_slot):
        bad("revision-3 corpus",
            f"never reached the features it exists for: SCRATCH={scratch} "
            f"SCRATCH_IO={scratch_io} KX9={kx9} indexed={indexed} "
            f"slot>=256={deep_slot}")
        return
    ok(f"revision-3 corpus: {n} programs identical in both languages",
       f"bytes, disassembly, round trip and -i; {scratch} use the "
       f"scratch, {indexed} index it, {deep_slot} name a slot past 255, "
       f"{scratch_io} carry a per-run block, {kx9} need KX9")


# ================= the ODE rows (programs/gen_odes.py) ===================
#
# Three dynamical systems as segment programs. What each row's check
# establishes, in order; what it holds each claim to; and the negative
# control beside it, whose failure is asserted ("NEGATIVE CONTROL FAILED
# TO FAIL" fails the run). Every control goes through the same function
# as the claim it guards, differing only in the fault it injects.
#
#   generated    the committed .cfta and its bank are gen_odes.py's
#                output, byte for byte - the generator is the one
#                definition of the instruction stream. Control: the
#                generator's text with CRLF line ends, WRITTEN TO DISK
#                and read back through the same reader as the claim
#                (_read_source), must be refused - so a reader that
#                normalised line ends, which would pass a CRLF checkout,
#                fails the run. (Until 2026-09-25 the control CRLF-ed
#                bytes already read, and a text-mode reader passed both
#                it and a CRLF file on disk - verifier-V3.)
#   bank         the value in each slot is the correctly rounded value of
#                the definition of the NAME the source gives that slot -
#                the golden assembler's reading of the .const lines, in
#                order - shown with exact rationals and the value's two
#                neighbours, not by rounding again. The claim and its
#                controls all go through _bank_verdict, which takes the
#                SOURCE and names the slots from it. Controls: gen_odes'
#                own bank_values with two entries transposed, and with
#                one value an ulp off (the comparison), and the source
#                with the same two .const lines transposed over the
#                committed bank (where the names come from: names taken
#                from bank_values' list instead pass every other control,
#                verifier-V3's C-names).
#   pinned       the image's state size, steps a segment, ALU and
#                control codes a step, instruction and bank counts and
#                scratch slots against LITERALS in _ODE_PINNED. Every arm
#                takes N and the step count from there, not from
#                gen_odes.py. Controls: each of the image's numbers
#                moved one on must be refused under its own key (the
#                comparator); and gen_odes.py's own text with its STEPS
#                entry (and Lorenz-96's L96_N) edited, executed as a
#                module and swapped in for gen_odes for the whole verdict
#                - as a real edit would be - then regenerated, must be
#                refused by name (the expectations are not the
#                generator's).
#   prose        programs/README.md's row (its cells, and what its text
#                states), its paragraph, the source's own comments and
#                gen_odes.py's docstring against the IMAGE's numbers and
#                the names of the system and the scheme, so a change the
#                pinned table is made to follow cannot leave any of them
#                stale (_ODE_PROSE says what is held, and what is not).
#                Control: one number changed through each of its five
#                readings - the row's instruction-count cell, the ALU
#                count the row states (a digit put before it, so the
#                phrase's bound is watched too), the state count the
#                paragraph spells, the ALU count the comments state and
#                the state count the docstring spells - each named where
#                it is; then the row's ALU count after a hyphen, and a
#                row phrase with a hyphen, then a letter, after its end
#                (each edge of the bounds).
#   static       the header: BANK_EXT, SCRATCH_IO, no deposits, the slot
#                counts and the bank size the source declares. A read of
#                the header, with no control.
#   census       the golden executor's own count of what one step more
#                runs must be the image's ALU instructions and control
#                codes a lane-step (which the pinned arm holds) and the
#                loop's ENDREP. Two measurements that must agree; no
#                control of its own.
#   identity     the library's executor (positive-run), the golden
#                model's (seq.run) and ode_step agree bit for bit.
#                ode_step is the scheme written again here IN THE
#                PROGRAM'S ROUNDING ORDER - it has to be, to be bit for
#                bit - so it is a second transcription by the same hand,
#                not an independent reference: an error made in both
#                places passes this arm. Control: a source with one
#                instruction's operands swapped, run by the golden
#                executor, must not match ode_step. (The claim's other
#                half, the library's executor against the golden one, has
#                no control of its own.)
#   textbook     the program's first two steps, each from the state the
#                program itself began it with, against the TEXTBOOK step
#                in exact rationals: the vector field in its textbook
#                form, classic Runge-Kutta from its Butcher tableau
#                through a generic stepper, Stormer-Verlet from its
#                textbook update with the force differentiated out of
#                the potential - within a bound derived from the
#                precision (_Tb says how). It shares no transcription
#                with gen_odes.py or ode_step. Controls: every wrong
#                program gen_odes.MUTANTS names is a SHARED error - the
#                generator writes it and ode_step carries it
#                (_mirror_carrying) - and each must pass the mirror
#                arm's comparison (the golden executor's run of it
#                against ode_step carrying it, bit for bit, from this
#                arm's states over two steps: the error really is
#                shared) and fall outside the textbook bound. Re-point
#                the textbook arm at ode_step and these go red. Its code
#                is held apart from theirs as well, by two rules over
#                this file's syntax (check_textbook_independence: nothing
#                it reaches by name, by attribute or handed in by a
#                caller is theirs, and no definition is reached by both,
#                whatever it is called), whose own comment says what they
#                cannot see.
#   scheme       ode_step at 300 digits from the same encodings: over
#                the whole segment the program is within round-off of
#                its own scheme, and not equal to it (the round-off is
#                really there). The same transcription as identity, so
#                not independent either. Control: ode_step with a wrong
#                weight or kick must exceed the ceiling. Without mpmath
#                neither runs, and each is named as skipped.
#   resume       two segments chained through the scratch block are one
#                segment of twice the steps. Controls, through the same
#                code path as the claim: the second segment entered with
#                the ORIGINAL state instead (it watches the plumbing: a
#                deterministic executor decides it once the claim has
#                passed); and, for Henon-Heiles, gen_odes.UNRESUMABLE's
#                program, right step by step (the textbook arm must pass
#                it) but carrying a compensation from step to step that
#                no segment boundary carries - one ulp in one or two
#                lanes, so only a comparison of every lane, bit for bit,
#                against a long run built independently of the chained
#                one refuses it. That difference can vanish when the
#                lanes, steps or states change, and then the golden
#                executor's own runs decide whether the message blames
#                the resume arm or the control (the comment at the
#                control says how).

ODE_ROWS = ("lorenz63-rk4", "lorenz96-rk4", "henonheiles-lf")

# Each ODE row's numbers as LITERALS - the one place this file states
# them. Every arm below takes the state size and the step count from
# here, never from gen_odes.py: check_ode reads them and hands each arm
# the numbers it needs, and no implementation of the program (ode_step,
# _tb_runs, ...) reads this table itself - so the textbook arm may read
# it too without the independence rules' shared rule seeing a table
# both sides reach, and no number needs a second copy. The pinned arm
# holds the image to all of them, and the prose arm holds
# programs/README.md's row and the source's own comments to the image.
# So gen_odes.py's L96_N or STEPS changed and everything regenerated
# fails the run by name until this table - and the README and the
# comments with it - is changed on purpose. Until
# 2026-09-25 every arm imported both, and a ring of 36 or a 50-step
# segment passed the whole gate while the regenerated source still said
# "Forty values" and "760 ALU instructions" (verifier-V3). Lorenz-96's
# counts are 19 N ALU instructions a step (3 for f, and 1 + 2 + 2 + 2
# over the four stages, a component) and 4 (N + 3) + 13 N scratch
# accesses (the window's N + 3 loads a stage, and 2 + 4 + 4 + 3 a
# component over the stages); an image is its step, its loads and stores
# outside the loop, the REPEAT, the ENDREP and the HALT.
_ODE_PINNED = {
    "lorenz63-rk4": {"nstate": 3, "steps": 100, "alu": 53, "ctl": 0,
                     "insns": 62, "consts": 7, "slots": 3},
    "lorenz96-rk4": {"nstate": 40, "steps": 20, "alu": 760, "ctl": 692,
                     "insns": 1455, "consts": 5, "slots": 200},
    "henonheiles-lf": {"nstate": 4, "steps": 100, "alu": 12, "ctl": 0,
                       "insns": 23, "consts": 5, "slots": 4},
}

# The lanes the identity, scheme and resume arms run, and the states the
# textbook arm starts from - programs/README.md states both.
_ODE_LANES = {"lorenz63-rk4": (8, 4), "lorenz96-rk4": (4, 2),
              "henonheiles-lf": (8, 4)}

# The pinned arm's controls: one line of gen_odes.py's own text, edited
# as a person would edit it, and the check each must be refused by.
_PINNED_EDITS = {
    "lorenz63-rk4": (('"lorenz63-rk4": 100,', '"lorenz63-rk4": 50,',
                      "steps"),),
    "lorenz96-rk4": (("L96_N = 40 ", "L96_N = 36 ", "nstate"),
                     ('"lorenz96-rk4": 20,', '"lorenz96-rk4": 10,',
                      "steps")),
    "henonheiles-lf": (('"henonheiles-lf": 100}', '"henonheiles-lf": 50}',
                        "steps"),),
}


def _read_source(path):
    """A committed source as the generated arm reads it: bytes, so a CRLF
    file cannot compare equal to the generator's LF text. The claim and
    its control both read through here, so a reader that normalised line
    ends would fail the control."""
    return path.read_bytes()


def _ode_measure(img):
    """What an ODE image IS, read off its bytes: the numbers the pinned
    and prose arms hold, and the census's static half."""
    alu = ctl = depth = loops = deepest = 0
    trips = []
    for word in img.insns:
        dd = asm.decode(word)
        if dd["ctrl"] and dd["op"] == asm.REPEAT:
            depth += 1
            loops += 1
            deepest = max(deepest, depth)
            trips.append(dd["imm"])
            continue
        if dd["ctrl"] and dd["op"] == asm.ENDREP:
            depth -= 1
            continue
        if depth:
            if dd["ctrl"]:
                ctl += 1
            else:
                alu += 1
    top, indexed = img.scratch_use()
    return {"nstate": img.n_scratch_in, "nstate_out": img.n_scratch_out,
            "steps": trips[0] if len(trips) == 1 else None,
            "loops": loops, "deepest": deepest, "alu": alu, "ctl": ctl,
            "insns": len(img.insns), "consts": img.n_consts,
            "deposits": img.max_deposits,
            "slots": None if top is None or indexed else top + 1,
            "features": img.features()}


# The pinned comparator's control: each number _ode_measure reads that the
# comparator holds, and the key its problem must be led by.
_PINNED_MOVES = (("nstate", "nstate"), ("nstate_out", "nstate"),
                 ("steps", "steps"), ("alu", "alu"), ("ctl", "ctl"),
                 ("insns", "insns"), ("consts", "consts"),
                 ("slots", "slots"), ("loops", "loops"),
                 ("deepest", "loops"))


def _ode_pinned_problems(base, m):
    """[problem] - an image's numbers `m` (_ode_measure) against
    _ODE_PINNED, each problem led by the key it is about."""
    pin = _ODE_PINNED[base]
    problems = []
    if (m["loops"], m["deepest"]) != (1, 1):
        problems.append(f"loops: {m['loops']} loop(s) {m['deepest']} deep, "
                        f"pinned one")
    for key, what in (("nstate", "state values in"),
                      ("steps", "steps a segment"),
                      ("alu", "ALU instructions a step"),
                      ("ctl", "control codes a step besides the ENDREP"),
                      ("insns", "instructions in the image"),
                      ("consts", "bank values"),
                      ("slots", "scratch slots")):
        if m[key] != pin[key]:
            problems.append(f"{key}: {m[key]} {what}, pinned {pin[key]}")
    if m["nstate_out"] != pin["nstate"]:
        problems.append(f"nstate: {m['nstate_out']} state values out, "
                        f"pinned {pin['nstate']}")
    return problems


def _gen_odes_edited(old, new):
    """gen_odes.py with one line of its text edited, executed as a module
    of its own - the pinned arm's controls. Raises, naming the line, if
    `old` is not in the file exactly once."""
    path = Path(gen_odes.__file__)
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise ValueError(f"`{old}` is in gen_odes.py {text.count(old)} "
                         f"times, and the pinned arm's control edits it "
                         f"once")
    mod = types.ModuleType("gen_odes_edited")
    mod.__file__ = str(path)
    saved = list(sys.path)
    try:
        exec(compile(text.replace(old, new), str(path), "exec"),
             mod.__dict__)
    finally:
        sys.path[:] = saved
    return mod


@contextlib.contextmanager
def _as_gen_odes(mod):
    """Inside, this file's `gen_odes` IS `mod`: everything here that
    reads the generator sees the edit, as it would see a real one. So a
    check that took its expectations from gen_odes rather than from its
    own literals would follow the edit, and pass it."""
    global gen_odes
    saved, gen_odes = gen_odes, mod
    try:
        yield
    finally:
        gen_odes = saved


# ---- the prose arm -------------------------------------------------------
#
# What programs/README.md, each source's own comments and gen_odes.py's
# docstring say of a row, as templates filled from the IMAGE's numbers,
# this file's lane counts and the bank's derivations. Each must appear as
# written - whitespace aside, and not as the tail or the head of a longer
# number or word (_phrase_re: "153 ALU" does not say "53 ALU") - or the
# arm names it. "row" is the image's README row, its what and check cells,
# an "as above" read as the cell above; "readme" is anywhere in the
# README; "source" is the source's comment lines run together, so that a
# re-wrapped comment reads the same; "generator" is gen_odes.py's
# docstring. The row's format, insns, consts, deposits and needs cells
# are held besides. Beside the numbers the templates hold each text's
# names for the system, its year and the scheme, which the textbook arm
# holds the program to. Every other word is NOT held: the equations as
# the comments write them, the scratch layout and the bank's comments in
# a source, the README paragraph's account of the arms, what a row says
# of its controls, and an "as `lorenz63-rk4`" cell (Henon-Heiles's lanes
# and states are not read from its row at all).
_ODE_PROSE = {
    "lorenz63-rk4": {
        "row": ("a segment of {steps} classic Runge-Kutta steps of Lorenz "
                "1963",
                "{alu} ALU instructions a step and {ctl_text} but the "
                "loop's ENDREP",
                "own count of a step - {per_step}, the ENDREP included",
                "bit for bit over {lanes} lanes",
                "the first two steps from {states} states"),
        "readme": ("emit them: {word} state values or",),
        "source": ("Lorenz (1963):",
                   "stepped by the classic fourth-order Runge-Kutta scheme",
                   "a step is {alu} ALU instructions and {ctl_text} but "
                   "the loop's own ENDREP"),
        "generator": ("Lorenz (1963), sigma {SIGMA}, rho {RHO}, beta {BETA} "
                      "by default, the classic fourth-order Runge-Kutta "
                      "step; {word} state values",),
    },
    "lorenz96-rk4": {
        "row": ("{steps} Runge-Kutta steps of Lorenz 1996 on a ring of "
                "{nstate}:",
                "({slots} slots)",
                "{alu} ALU instructions, {ctl} scratch accesses and the "
                "loop's ENDREP a step",
                "over {lanes} lanes, the textbook arm from {states} states",
                "the executor counting {per_step:,} a step"),
        "readme": ("step is all arithmetic; {word} do not,",),
        "source": ("Lorenz (1996) on a ring of N = {nstate}:",
                   "Stepped by the same Runge-Kutta scheme as lorenz63-rk4",
                   "{Word} values do not fit thirty-two registers",
                   "- {slots} slots.",
                   "A step is {alu} ALU instructions, {ctl} scratch "
                   "accesses and the loop's ENDREP"),
        "generator": ("Lorenz (1996) with N = {nstate} and forcing F = {F} "
                      "by default, the same Runge-Kutta step; {word} state "
                      "values, which do not fit thirty-two registers",),
    },
    "henonheiles-lf": {
        "row": ("{steps} Stormer-Verlet steps of Henon-Heiles, "
                "drift-kick-drift",
                "{alu} ALU instructions a step"),
        "readme": ("state values or {word} fit the registers",),
        "source": ("Henon-Heiles (1964):",
                   "stepped by Stormer-Verlet, drift-kick-drift:",
                   "a step is {alu} ALU instructions."),
        "generator": ("Henon-Heiles (1964), Stormer-Verlet in its "
                      "drift-kick-drift form; {word} state values in "
                      "registers",),
    },
}

_ONES = ("zero one two three four five six seven eight nine ten eleven "
         "twelve thirteen fourteen fifteen sixteen seventeen eighteen "
         "nineteen").split()
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
         "eighty", "ninety")


def _number_word(n):
    """0..99 as the prose writes it ("forty", "thirty-six"); digits past
    that, which no row's prose spells."""
    if not 0 <= n < 100:
        return str(n)
    if n < 20:
        return _ONES[n]
    return _TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else "")


def _comment_text(src):
    """A source's comment lines, run together as one line of prose."""
    return " ".join(" ".join(line.strip()[1:].split())
                    for line in src.splitlines()
                    if line.strip().startswith(";"))


def _generator_doc():
    """gen_odes.py's docstring, read from its source (python -OO drops
    __doc__, and a check must not change its verdict with a flag)."""
    return ast.get_docstring(ast.parse((HERE / "gen_odes.py").read_text(
        encoding="utf-8"))) or ""


def _phrase_re(phrase):
    """`phrase` as a pattern: its words in order, any whitespace between
    them, and not the tail or the head of a longer number or word - so
    "153 ALU", "20-53 ALU" and "1100 Stormer-Verlet" do not say "53 ALU"
    and "100 Stormer-Verlet", nor "Lorenz 19630" or "kick-drift-kick"
    what ends in "1963" or "drift"."""
    pat = r"\s+".join(re.escape(w) for w in phrase.split())
    if re.match(r"\w", phrase):
        pat = r"(?<![\w.,-])" + pat
    if re.search(r"\w$", phrase):
        pat += r"(?![\w-])"
    return re.compile(pat)


def _readme_rows(text):
    """{program: [its rows' cells]} for every row of programs/README.md's
    index, whitespace collapsed and an "as above" cell read as the one
    above it."""
    rows, prev = {}, None
    for line in text.splitlines():
        mm = re.match(r"\|\s*`([^`]+)`\s*\|", line)
        if not mm:
            prev = None
            continue
        cells = [" ".join(c.split()) for c in line.strip().strip("|")
                 .split("|")]
        if prev is not None and len(prev) == len(cells):
            cells = [p if c == "as above" else c for c, p in
                     zip(cells, prev)]
        rows.setdefault(mm.group(1), []).append(cells)
        prev = cells
    return rows


def _prose_fill(base, m, lanes, states):
    """What _ODE_PROSE's templates are filled with: the image's numbers
    `m`, their sums and words, this file's lane counts, and the bank's
    derivations."""
    words = _number_word(m["nstate"])
    return dict(m, per_step=m["alu"] + m["ctl"] + 1, lanes=lanes,
                states=states, word=words, Word=words.capitalize(),
                ctl_text=("no control code" if m["ctl"] == 0 else
                          f"{m['ctl']} control codes"),
                **{c: str(v) for c, v in _bank_derivations(base).items()})


def _ode_prose_problems(base, name, fmtname, m, texts, lanes, states):
    """[problem] - programs/README.md's row for `name`, the source's own
    comments and gen_odes.py's docstring (`texts`: "readme" as written,
    "source" run together by _comment_text, "generator") against the
    image's numbers `m` (_ode_measure), this file's lane counts and the
    bank's derivations. Each problem is led by where it is."""
    fill = _prose_fill(base, m, lanes, states)
    problems = []
    rows = _readme_rows(texts["readme"]).get(name, [])
    if len(rows) != 1:
        problems.append(f"readme: programs/README.md has {len(rows)} rows "
                        f"for {name}, not one")
    else:
        cells = rows[0]
        want = (("format", fmtname), ("insns", f"{m['insns']:,}"),
                ("consts", str(m["consts"])),
                ("deposits", str(m["deposits"])),
                ("needs", ", ".join(f"`{f}`" for f in m["features"])))
        for i, (label, w) in enumerate(want, 1):
            have = cells[i] if i < len(cells) else None
            if have != w:
                problems.append(f"readme {label}: the row says {have!r}, "
                                f"the image {w!r}")
        text = " ".join(cells[6:])
        for tpl in _ODE_PROSE[base]["row"]:
            if not _phrase_re(tpl.format(**fill)).search(text):
                problems.append(f"readme: the row does not say "
                                f"{tpl.format(**fill)!r}")
    for where, what in (("readme", "it does not say"),
                        ("source", "its comments do not say"),
                        ("generator", "its docstring does not say")):
        for tpl in _ODE_PROSE[base][where]:
            if not _phrase_re(tpl.format(**fill)).search(texts[where]):
                problems.append(f"{where}: {what} {tpl.format(**fill)!r}")
    return problems


def _ode_base(name):
    for base in ODE_ROWS:
        if name.startswith(base + "-"):
            return base, name[len(base) + 1:]
    return None, None


class _SfOps:
    """The five operations these programs use, as the golden model
    defines them, returning bits. The flags are not part of these
    checks - an ODE step is inexact everywhere, as docs/ORBITS.md says
    of its own."""

    def __init__(self, fmt):
        self.fmt = fmt

    def fma(self, a, b, c):
        return sf.fma(self.fmt, a, b, c)[0]

    def add(self, a, b):
        return sf.add(self.fmt, a, b)[0]

    def sub(self, a, b):
        return sf.sub(self.fmt, a, b)[0]

    def mul(self, a, b):
        return sf.mul(self.fmt, a, b)[0]

    def neg(self, a):
        return sf.neg(self.fmt, a)[0]


class _MpOps:
    """The same five, in mpmath at the context's precision: the scheme
    with its roundings taken out, from the same starting values."""

    @staticmethod
    def fma(a, b, c):
        return a * b + c

    @staticmethod
    def add(a, b):
        return a + b

    @staticmethod
    def sub(a, b):
        return a - b

    @staticmethod
    def mul(a, b):
        return a * b

    @staticmethod
    def neg(a):
        return -a


# ---- the mirror's test-only mistakes -------------------------------------
#
# The textbook arm is worth having only while it stays independent of
# the mirror. Re-point it at ode_step - a "de-duplication" that would
# look like a clean-up - and an error written into gen_odes.py and
# ode_step alike passes the whole gate again: verifier-V3 did exactly
# that on 2026-09-25, and a shared error passed 234 checks with every
# negative control green, because each control was a wrong PROGRAM
# against a right mirror, which the mirror arm rejects as well. So the
# textbook arm's controls are SHARED errors: each of gen_odes.MUTANTS,
# written by the generator AND carried by ode_step behind this switch,
# with both halves asserted - the mirror arm's comparison passes it (the
# golden executor's run of the program against ode_step carrying the
# mistake, bit for bit: the error really is shared) and the textbook arm
# refuses it.
#
# The mistake reaches ode_step through this module-level switch, not
# through an argument, on purpose: a mistake written into ode_step
# reaches every caller of ode_step, so the control's must too. If the
# textbook reference is computed through THIS module's ode_step, it
# carries the program's mistake, the program lands inside the bound, and
# the control fails to fail - which is the alarm. Through a second
# instance of the module (importlib.import_module("check"), verifier-V5's
# O1) it does not: that instance's switch is never set, its ode_step is
# right, and every control passes - the attribute read the independence
# rules name (check_textbook_independence) is what catches that.
_MIRROR_MUTANTS = {"lorenz63-rk4": ("zsign", "stage4-half", "rk38"),
                   "lorenz96-rk4": ("index", "stage4-half", "rk38"),
                   "henonheiles-lf": ("xforce-sign", "kdk")}
_MIRROR_MUTANT = None


@contextlib.contextmanager
def _mirror_carrying(base, mutant):
    """Inside, ode_step carries `mutant` - named as gen_odes.MUTANTS
    names the generator's - for every caller, as a mistake written into
    it would. Unknown names are refused rather than ignored: an ignored
    one would hand back the right mirror, and the control's first half
    would fail for the wrong reason."""
    global _MIRROR_MUTANT
    if mutant not in _MIRROR_MUTANTS.get(base, ()):
        raise ValueError(f"ode_step has no test mutant {mutant!r} for "
                         f"{base}")
    saved, _MIRROR_MUTANT = _MIRROR_MUTANT, mutant
    try:
        yield
    finally:
        _MIRROR_MUTANT = saved


def _rk_mirror(o, rk, f, Y, steps, detuned, m):
    """The Runge-Kutta rows' stages in the program's rounding order, the
    weighted sum bracketed as gen_odes.py brackets it; `rk` the bank's
    step multiples, `f` the row's right-hand side. Under the test-only
    rk38 the 3/8 rule, exactly as the generator's rk38 mutant writes it
    (the same operations on the same values, so the same bits)."""
    if m == "rk38":
        H, H3, MH3, MH, H8, THREE = rk
        for _ in range(steps):
            k1 = f(Y)
            k2 = f([o.fma(H3, k, v) for k, v in zip(k1, Y)])
            C = [o.fma(THREE, k, a) for k, a in zip(k2, k1)]
            D = [o.fma(MH, k, o.fma(H, a, v)) for k, a, v in
                 zip(k2, k1, Y)]
            k3 = f([o.fma(H, k, o.fma(MH3, a, v)) for k, a, v in
                    zip(k2, k1, Y)])
            C = [o.fma(THREE, k, c) for k, c in zip(k3, C)]
            k4 = f([o.fma(H, k, d) for k, d in zip(k3, D)])
            Y = [o.fma(H8, o.add(c, k), v) for c, k, v in zip(C, k4, Y)]
        return Y
    H, H2, H6, TWO = rk
    h4 = H2 if m == "stage4-half" else H
    for _ in range(steps):
        k1 = f(Y)
        k2 = f([o.fma(H2, k, v) for k, v in zip(k1, Y)])
        A = [(o.add(k, a) if detuned else o.fma(TWO, k, a))
             for k, a in zip(k2, k1)]
        k3 = f([o.fma(H2, k, v) for k, v in zip(k2, Y)])
        A = [o.fma(TWO, k, a) for k, a in zip(k3, A)]
        k4 = f([o.fma(h4, k, v) for k, v in zip(k3, Y)])
        Y = [o.fma(H6, o.add(a, k), v) for a, k, v in zip(A, k4, Y)]
    return Y


def ode_step(base, o, K, s, steps, detuned=False):
    """The scheme written again, in the PROGRAM'S rounding order - which
    it must share to be bit-identical, so it mirrors gen_odes.py rather
    than being independent of it: an error written into both passes every
    comparison with this function. The textbook arm (_tb_step) is the
    reference that shares no transcription. `o` is _SfOps (bits) or
    _MpOps (values); `K` the bank in declaration order; `s` one lane's
    state. `detuned` is the 300-digit arm's negative control: a wrong
    weight (Runge-Kutta) or a half kick (Stormer-Verlet). The test-only
    mistakes of _mirror_carrying are read from _MIRROR_MUTANT."""
    m = _MIRROR_MUTANT
    if m is not None and m not in _MIRROR_MUTANTS.get(base, ()):
        raise ValueError(f"ode_step has no test mutant {m!r} for {base}")
    if base == "lorenz63-rk4":
        *rk, SIG, RHO, BETA = K

        def f(Y):
            x, y, z = Y
            bz = o.mul(BETA, z)
            return [o.mul(SIG, o.sub(y, x)),
                    o.fma(x, o.sub(RHO, z), o.neg(y)),
                    o.fma(x, y, bz if m == "zsign" else o.neg(bz))]
        return _rk_mirror(o, rk, f, list(s), steps, detuned, m)
    if base == "lorenz96-rk4":
        *rk, F = K
        N = len(s)
        j = 1 if m == "index" else -1

        def f(X):
            return [o.fma(o.sub(X[(i + 1) % N], X[(i - 2) % N]),
                          X[(i + j) % N], o.sub(F, X[i]))
                    for i in range(N)]
        return _rk_mirror(o, rk, f, list(s), steps, detuned, m)
    if base == "henonheiles-lf":
        H, H2, MH, ONE, TWO = K
        x, y, px, py = s
        kick = H2 if detuned else H
        mkick = H if m == "xforce-sign" else (o.neg(H2) if detuned else MH)
        for _ in range(steps):
            if m == "kdk":              # half kick, drift h, half kick
                for half in (0, 1):
                    px = o.fma(H2, o.neg(o.mul(x, o.fma(TWO, y, ONE))), px)
                    py = o.fma(H2, o.fma(y, o.sub(y, ONE),
                                         o.neg(o.mul(x, x))), py)
                    if not half:
                        x = o.fma(H, px, x)
                        y = o.fma(H, py, y)
                continue
            x = o.fma(H2, px, x)
            y = o.fma(H2, py, y)
            px = o.fma(mkick, o.mul(x, o.fma(TWO, y, ONE)), px)
            py = o.fma(kick, o.fma(y, o.sub(y, ONE), o.neg(o.mul(x, x))),
                       py)
            x = o.fma(H2, px, x)
            y = o.fma(H2, py, y)
        return [x, y, px, py]
    raise KeyError(base)


def _mirror_out(base, fmt, K, block, nstate, steps):
    """ode_step in bits over every lane of `block` (lane-major) ->
    lane-major bits: the identity arm's reference, and the shared-error
    controls' mirror half."""
    o = _SfOps(fmt)
    out = []
    for i in range(len(block) // nstate):
        out += ode_step(base, o, K, block[i * nstate:(i + 1) * nstate],
                        steps)
    return out


def ode_initial(base, fmt, n):
    """n lanes' starting states, lane-major bits: a small ensemble each
    member of which is displaced by an exact dyadic amount - which is
    also what a controlled-divergence run looks like."""
    def d(text):
        return chars.from_decimal(fmt, text, sf.RND_RNE)[0]
    out = []
    for i in range(n):
        if base == "lorenz63-rk4":
            out += [d(repr(1 + i / 64)), d("1"), d("1")]
        elif base == "lorenz96-rk4":
            out += [d(repr(8 + (i + 1) / 1024))] + \
                   [d("8")] * (_ODE_PINNED[base]["nstate"] - 1)
        else:
            out += [d("0"), d(repr(0.1 + i / 1024)), d("0.5"), d("0")]
    return out


def _frac(fmt, bits):
    """An encoding's exact value, as a Fraction. Finite only."""
    u = sf.unpack(fmt, bits)
    if u.kind == sf.ZERO:
        return Fraction(0)
    if u.kind not in (sf.NORM, sf.SUB):
        raise ValueError(f"{bits:#x} is not finite")
    v = Fraction(u.m) * (Fraction(2) ** u.e)
    return -v if u.sign else v


def _nearest(fmt, bits, target):
    """Is `bits` the correctly rounded (to nearest, ties to even)
    encoding of the exact rational `target`? Decided against the two
    neighbouring encodings, for a positive normal value - which every
    bank value these programs use is, their negations aside."""
    v = _frac(fmt, bits)
    lo, hi = _frac(fmt, bits - 1), _frac(fmt, bits + 1)
    dv, dl, dh = abs(v - target), abs(lo - target), abs(hi - target)
    if dv > dl or dv > dh:
        return False
    if dv == dl or dv == dh:            # a tie: the even one wins
        return (bits & 1) == 0
    return True


def _bank_derivations(base):
    """name -> the exact rational each default bank value rounds. H2, H6
    and MH are exact operations on (or one rounding of) the value in the
    slot named H, and _bank_problems derives them from it."""
    common = {"H": Fraction(1, 100), "TWO": Fraction(2), "ONE": Fraction(1)}
    if base == "lorenz63-rk4":
        common.update({"SIGMA": Fraction(10), "RHO": Fraction(28),
                       "BETA": Fraction(8, 3)})
    if base == "lorenz96-rk4":
        common.update({"F": Fraction(8)})
    return common


def _bank_problems(fmt, base, names, bits):
    """[problem], one sentence each, for a bank read BY NAME: `names` are
    the constants the SOURCE declares, in slot order, and `bits` what the
    bank holds in those slots. A value is held to the definition of the
    name its slot has, never to a list of names written beside the
    values - which is how a transposition inside gen_odes.bank_values
    once passed, the program running rho = 8/3 and beta = 28."""
    if len(names) != len(bits):
        return [f"the source declares {len(names)} constants and the bank "
                f"holds {len(bits)} values"]
    exact = _bank_derivations(base)
    byname = dict(zip(names, bits))
    problems = []
    for cname, b in zip(names, bits):
        if cname in exact:
            if not _nearest(fmt, b, exact[cname]):
                problems.append(f"{cname} is not RN({exact[cname]})")
        elif cname in ("H2", "H6", "MH") and "H" not in byname:
            problems.append(f"{cname} is derived from H, and the source "
                            f"declares no H")
        elif cname == "H2":
            if _frac(fmt, b) != _frac(fmt, byname["H"]) / 2:
                problems.append("H2 is not exactly H / 2")
        elif cname == "H6":
            if not _nearest(fmt, b, _frac(fmt, byname["H"]) / 6):
                problems.append("H6 is not RN(H / 6)")
        elif cname == "MH":
            if _frac(fmt, b) != -_frac(fmt, byname["H"]):
                problems.append("MH is not exactly -H")
        else:
            problems.append(f"{cname} has no derivation here")
    return problems


def _bank_verdict(fmt, base, src_text, bits):
    """The bank arm -> (the slot names, [problem]): the values `bits`
    under the names the SOURCE `src_text` gives the slots, the golden
    assembler's reading of its .const lines in order. The claim and all
    three of its controls go through here, so the names cannot come from
    anywhere but the text handed in without the third control - the same
    source with two .const lines transposed - passing."""
    names = list(asm.assemble_image(src_text, "<bank arm>").const_names)
    return names, _bank_problems(fmt, base, names, bits)


def _swap_const_lines(src, a, b):
    """The source with its `.const a` and `.const b` lines exchanged, or
    None unless each is declared exactly once."""
    lines = src.split("\n")
    at = {c: [i for i, line in enumerate(lines)
              if re.match(rf"\.const\s+{c}\b", line)] for c in (a, b)}
    if len(at[a]) != 1 or len(at[b]) != 1:
        return None
    i, j = at[a][0], at[b][0]
    lines[i], lines[j] = lines[j], lines[i]
    return "\n".join(lines)


# The bank arm's controls, a row each: the entries transposed inside
# bank_values (the shape that passed on 2026-09-25: RHO and BETA), the
# constant nudged one ulp, and the same two .const lines transposed in
# the source over the committed bank.
_ODE_TRANSPOSE = {"lorenz63-rk4": ("RHO", "BETA"),
                  "lorenz96-rk4": ("H2", "H6"),
                  "henonheiles-lf": ("ONE", "TWO")}
_ODE_NUDGE = {"lorenz63-rk4": "RHO", "lorenz96-rk4": "F",
              "henonheiles-lf": "H"}


# ---- the textbook arm --------------------------------------------------
#
# Written from the textbooks, not from gen_odes.py or ode_step: each
# vector field in its textbook vector form (Lorenz-96 by cyclic indexing
# of the whole ring, not by the program's sliding window), classic
# Runge-Kutta from its published Butcher tableau through a generic
# explicit stepper rather than hand-written stages, and Stormer-Verlet
# from its textbook drift-kick-drift update with the Henon-Heiles force
# taken out of the potential V by dual numbers rather than derived by
# hand. Exact rationals throughout, from the standard library, so this
# arm never skips.


class _Tb:
    """An exact value `v` with the two numbers its rounding bound needs:
    `a`, the same expression evaluated over absolute values - the sum of
    |t| over the terms t of its expansion - and `k`, the most roundings
    any of those terms can pass through when a program evaluates the
    same expression in floating point. An operation counts one; a
    product counts both factors' and one; a sum of n terms counts n - 1
    whatever its association (_tb_sum); the step multiples h a_ij and
    h b_i count as carried rounded once (_tb_rounded), as a bank carries
    H6. A program that evaluates the same expression - fused or not,
    reassociated or not - leaves each term with at most k factors
    (1 + d), |d| <= u = 2^-p under round to nearest, so

        |program - v| <= gamma_k a,   gamma_k = k u / (1 - k u)

    (the gamma_n lemma: Higham, Accuracy and Stability of Numerical
    Algorithms, chapter 3; no value here comes near the subnormal
    range). Nothing in the bound is chosen: u is the format's, k and a
    are the textbook step's own. Measured for the six shipped images
    at both steps this arm checks (2026-09-25, an exact run of each
    image's step carrying the same k and a through ITS operations, from
    this arm's states and then from the program's own state after one
    step): in every component the program's own k is 11 to 62 below
    this k (20-30 Lorenz-63, 62 Lorenz-96, 11-13 Henon-Heiles), its a
    is this a within a relative 3.4e-17, and its exact result is within
    0.24 u a of this v (0.2227 at the first step and 0.2372 at the
    second, Lorenz-63 fp64: H6 is RN(h/6), not h/6); at fp256, and for
    Henon-Heiles at both formats, a and v are this step's exactly. The
    program's whole rigorous error is at most 0.533 of the bound - so
    the bound holds with room."""

    __slots__ = ("v", "a", "k")

    def __init__(self, v, a, k):
        self.v, self.a, self.k = v, a, k

    def __add__(self, o):
        return _Tb(self.v + o.v, self.a + o.a, max(self.k, o.k) + 1)

    def __sub__(self, o):
        return _Tb(self.v - o.v, self.a + o.a, max(self.k, o.k) + 1)

    def __mul__(self, o):
        return _Tb(self.v * o.v, self.a * o.a, self.k + o.k + 1)


def _tb_exact(v):
    """An input, or a constant a program holds exactly."""
    v = Fraction(v)
    return _Tb(v, abs(v), 0)


def _tb_rounded(v):
    """A constant a program may carry rounded once (h/6, h/3, h/2)."""
    v = Fraction(v)
    return _Tb(v, abs(v), 1)


def _tb_sum(terms):
    return _Tb(sum((t.v for t in terms), Fraction(0)),
               sum((t.a for t in terms), Fraction(0)),
               max(t.k for t in terms) + len(terms) - 1)


def _tb_lorenz63(P):
    """Lorenz (1963): x' = sigma (y - x), y' = x (rho - z) - y,
    z' = x y - beta z."""
    sigma, rho, beta = P["SIGMA"], P["RHO"], P["BETA"]

    def f(Y):
        x, y, z = Y
        return [sigma * (y - x), x * (rho - z) - y, x * y - beta * z]
    return f


def _tb_lorenz96(P):
    """Lorenz (1996): x_i' = (x_(i+1) - x_(i-2)) x_(i-1) - x_i + F, the
    indices cyclic over the whole ring."""
    F = P["F"]

    def f(X):
        N = len(X)
        return [(X[(i + 1) % N] - X[(i - 2) % N]) * X[(i - 1) % N]
                - X[i] + F for i in range(N)]
    return f


# The classic fourth-order Runge-Kutta method's tableau (Butcher,
# Numerical Methods for Ordinary Differential Equations): A below the
# diagonal, row by row, and the weights b; c = (0, 1/2, 1/2, 1) is
# implied by A's row sums.
_RK4_TABLEAU = (((), (Fraction(1, 2),), (Fraction(0), Fraction(1, 2)),
                 (Fraction(0), Fraction(0), Fraction(1))),
                (Fraction(1, 6), Fraction(1, 3), Fraction(1, 3),
                 Fraction(1, 6)))


def _tb_erk(f, h, Y, tableau):
    """One step of the explicit Runge-Kutta method `tableau` = (A, b):
    k_i = f(Y + h sum_j a_ij k_j), Y + h sum_i b_i k_i."""
    A, b = tableau
    ks = []
    for i in range(len(b)):
        Yi = [_tb_sum([Y[m]] + [_tb_rounded(h * A[i][j]) * ks[j][m]
                                for j in range(i) if A[i][j]])
              for m in range(len(Y))]
        ks.append(f(Yi))
    return [_tb_sum([Y[m]] + [_tb_rounded(h * b[i]) * ks[i][m]
                              for i in range(len(b)) if b[i]])
            for m in range(len(Y))]


class _Dual:
    """Forward-mode differentiation: a value and its derivative, both
    _Tb, so the derivative carries its own rounding bound."""

    __slots__ = ("x", "d")

    def __init__(self, x, d):
        self.x, self.d = x, d

    def __add__(self, o):
        return _Dual(self.x + o.x, self.d + o.d)

    def __sub__(self, o):
        return _Dual(self.x - o.x, self.d - o.d)

    def __mul__(self, o):
        return _Dual(self.x * o.x, self.d * o.x + self.x * o.d)


def _tb_henon_heiles_V(x, y, half, third):
    """Henon and Heiles (1964): V = (x^2 + y^2)/2 + x^2 y - y^3/3."""
    return (x * x + y * y) * half + x * x * y - y * y * y * third


def _tb_grad_V(q):
    zero, one = _tb_exact(0), _tb_exact(1)
    half = _Dual(_tb_exact(Fraction(1, 2)), zero)
    third = _Dual(_tb_exact(Fraction(1, 3)), zero)
    out = []
    for j in range(len(q)):
        args = [_Dual(qi, one if i == j else zero) for i, qi in enumerate(q)]
        out.append(_tb_henon_heiles_V(*args, half, third).d)
    return out


def _tb_verlet(h, S):
    """Stormer-Verlet, drift-kick-drift, for H = |p|^2/2 + V(q):
    q' = q + h/2 p, p1 = p - h grad V(q'), q1 = q' + h/2 p1."""
    q, p = S[:2], S[2:]
    half_h, full_h = _tb_rounded(h / 2), _tb_exact(h)
    qh = [qi + half_h * pi for qi, pi in zip(q, p)]
    p1 = [pi - full_h * gi for pi, gi in zip(p, _tb_grad_V(qh))]
    q1 = [qi + half_h * pi for qi, pi in zip(qh, p1)]
    return q1 + p1


def _tb_step(base, P, h, Y):
    """The textbook step of row `base` from Y (a list of _Tb)."""
    if base == "henonheiles-lf":
        return _tb_verlet(h, Y)
    f = _tb_lorenz63(P) if base == "lorenz63-rk4" else _tb_lorenz96(P)
    return _tb_erk(f, h, Y, _RK4_TABLEAU)


_TB_NEEDS = {"lorenz63-rk4": ("H", "SIGMA", "RHO", "BETA"),
             "lorenz96-rk4": ("H", "F"), "henonheiles-lf": ("H",)}


def _tb_params(base, fmt, names, bits):
    """-> (h, {name: _Tb}): the step and the system's parameters, taken
    from the bank BY THE NAMES the source declares - the bank arm holds
    each name to its definition. Raises, naming what is missing."""
    byname = dict(zip(names, bits))
    missing = [c for c in _TB_NEEDS[base] if c not in byname]
    if missing:
        raise ValueError(f"the source declares no {', '.join(missing)}")
    P = {c: _tb_exact(_frac(fmt, byname[c])) for c in _TB_NEEDS[base]}
    return P["H"].v, P


def _tb_states(base, fmt, n):
    """n generic starting states, lane-major bits, far from every
    equilibrium. Classic Runge-Kutta and the 3/8 rule share their whole
    linear behaviour, so only a state where the nonlinear terms are as
    large as the linear ones can tell them apart - which the rk38
    controls show these do, every run."""
    rng = random.Random({"lorenz63-rk4": 1963, "lorenz96-rk4": 1996,
                         "henonheiles-lf": 1964}[base])

    def d(lo, hi):
        return chars.from_decimal(fmt, f"{rng.uniform(lo, hi):.6f}",
                                  sf.RND_RNE)[0]
    out = []
    for _ in range(n):
        if base == "lorenz63-rk4":
            out += [d(-15, 15), d(-20, 20), d(5, 40)]
        elif base == "lorenz96-rk4":
            out += [d(-4, 12) for _ in range(_ODE_PINNED[base]["nstate"])]
        else:
            out += [d(-0.4, 0.4), d(-0.4, 0.4), d(-0.3, 0.3), d(-0.3, 0.3)]
    return out


def _tb_runs(image, steps, bank, s_in, n, trips):
    """{trip: seq.Result} - the program after `trip` steps from s_in: the
    same image, whose one REPEAT runs `steps`, with that trip count
    changed (_patch_trip, as the resume arm builds its long run), through
    the golden executor. The caller hands in `steps` rather than this
    reading _ODE_PINNED, so that no implementation reads the table the
    verdict may read (check_textbook_independence's shared rule)."""
    out = {}
    for t in trips:
        img = _patch_trip(image, steps, t, 0)
        out[t] = seq.run(seq.Program.from_bytes(img.to_bytes()), [0] * n,
                         [0] * n, None, bank=bank, scratch_in=s_in)
    return out


def _tb_worst(fmt, got, refs):
    """max over every component of |program - exact| / (gamma_k a); a
    component whose bound is 0 (every term exact) is infinitely far if it
    is not exact. `got` is lane-major bits, `refs` a list of _Tb a lane."""
    u = Fraction(1, 2 ** fmt.prec)
    flat = [r for lane in refs for r in lane]
    if len(got) != len(flat):
        return float("inf")         # a run of the wrong shape is no match
    worst = Fraction(0)
    for bits, r in zip(got, flat):
        e = abs(_frac(fmt, bits) - r.v)
        tol = r.k * u / (1 - r.k * u) * r.a
        if tol == 0:
            if e:
                return float("inf")
            continue
        worst = max(worst, e / tol)
    return worst


def _tb_refs(base, fmt, P, h, block, nstate):
    """The textbook step from each lane of `block` (lane-major bits) ->
    a list of _Tb a lane."""
    return [_tb_step(base, P, h, [_tb_exact(_frac(fmt, b)) for b in
                                  block[i * nstate:(i + 1) * nstate]])
            for i in range(len(block) // nstate)]


def _tb_verdict(base, fmt, P, h, nstate, s_tb, runs):
    """The textbook arm's comparison -> (the worst |program - exact| /
    bound over the program's first two steps, the largest k): runs[1] is
    the program run one step from s_tb, runs[2] two, and each step is
    held to the textbook step from the state the program began it with.
    The claim and every control of the arm go through here."""
    got1 = runs[1].scratch_out
    refs1 = _tb_refs(base, fmt, P, h, s_tb, nstate)
    worst = max(_tb_worst(fmt, got1, refs1),
                _tb_worst(fmt, runs[2].scratch_out,
                          _tb_refs(base, fmt, P, h, got1, nstate)))
    return worst, max(r.k for lane in refs1 for r in lane)


# ---- the textbook arm's independence, by its code's structure -----------
#
# HonestFramework METHOD section 1: the authority "must not share code
# with the thing it judges", and "the authority's module must not import
# anything from the implementations. That is one grep, and it belongs in
# the gate." For the ODE rows the textbook step is the authority, and the
# implementations are the mirror, the generator and the program's
# executors. Two rules, over this file's own source read as a syntax
# tree. A DEFINITION is a function, a class or an assignment this file
# makes at module level - at its top level, or inside a top-level if,
# try, with, for, while or match block at any depth (verifier-V5 hid a
# helper in such a block, N6a, and bound a second instance of this
# module's ode_step in another, N6c). An import is not one: what it
# brings in is code outside this file. A module-level table also holds
# what the file puts into it - `X[k] = v`, `X.a = v`, or a statement
# `X.m(v)` such as X.update(v) - at module level, or inside a function or
# class that binds no X of its own (verifier-V5's M5). A side's REACH is
# every definition reached from its roots, and from what it reaches in
# turn:
#
#   by name       a definition loads the name;
#   by attribute  a definition reads an attribute of the same name, so
#                 sys.modules[__name__].x and a second instance's .x are
#                 x (verifier-V5's N6b, O1);
#   handed        it is handed as a value to a call of the side's code,
#                 from anywhere in this file (verifier-V5's N7): what a
#                 call's arguments hold - a function or table handed
#                 whole, a class or an instance of one (a class the
#                 calling function defines among them), a lambda
#                 (everything it names), what a wrapper such as
#                 functools.partial is given, every part of a
#                 conditional (`a if c else b`, `a or b`) and every
#                 member of a container, and a table's entry when it is
#                 indexed: for a module-level table, what the table
#                 names; for a local or literal one, the entry itself,
#                 and an entry that names a function or class is that
#                 function or class (verifier-V5's M1-M3). A local is
#                 what it is bound to - a parameter's default among that
#                 - and what its function puts into it (a subscript, an
#                 attribute, a method-call statement), when that can
#                 hold code: a name, an attribute, a lambda, a def or
#                 class, an instance, a table's entry, or a conditional
#                 or container any part of which can. A call is a call
#                 of what its callee holds: through a local, a
#                 module-level alias or a table's entry, the definition
#                 it names (verifier-V5's M4). What a call computes
#                 before it hands anything over - a function's result, a
#                 number read from a table - is data, not a definition
#                 handed, and so is a local a call computed: it is
#                 followed no further.
#
# The verdict's roots are _TB_ROOTS; the implementations' are the
# _TB_FORBIDDEN names this file defines.
#
#   named   no forbidden name may be in the verdict's reach - loaded,
#           read as an attribute, or handed to it, whole or indexed.
#   shared  no definition may be in both reaches, whatever it is called:
#           a function, a class, or data such as a coefficient table. A
#           helper shared under a new name passed a wrong Lorenz-63
#           through the whole gate on 2026-09-25 (verifier-V5's O2b), and
#           one that only slices lanes would share its mistakes the same
#           way: give the textbook arm its own. The image's numbers are
#           not an exception to this but outside it: _ODE_PINNED is read
#           by check_ode, which hands each side the numbers it needs (a
#           number read from a table is data), and by no implementation,
#           so the verdict may read it as well.
#
# A census comes first: every name this file binds at module level - by
# a def, a class, an assignment, a for, a with, a walrus or a match
# pattern, outside any function, class or lambda, found by a walk of its
# own that shares no code with the rules' walk - must be a definition the
# rules' walk records, a def or a class as one, so that a place the walk
# does not look is named rather than passed over (verifier-V5's B3b: the
# rules' walk narrowed to the top level passed the whole gate, with N6c's
# second instance bound in a top-level try beside it). The walk never
# records a walrus or a match capture, so the census refuses any at
# module level.
#
# The shared-error controls in check_ode catch the arm computing through
# the mirror by what it computes; these name it by the code's shape, and
# see what those cannot - a helper that carries an error the controls do
# not, a second instance of this module whose switch no control sets, or
# the generator's own default output taken as the reference. What the
# walk does not follow, neither rule sees. The shapes known to pass:
# code outside this file (a helper in another module both import, the
# generator's source, the golden model's); a name built at run time
# (globals()[...], getattr with a string); a COPY of the mirror's code
# under new names; a value handed through a parameter of the calling
# function by its own caller (verifier-V5's S4; a default is followed);
# a local a call computed, such as functools.partial(helper) put in a
# variable first, or a factory function's result; an instance made
# through a table or an attribute rather than by a class's name; a
# definition made from inside a function (global) or by exec or setattr;
# a call made through an attribute whose name is not the callee's own,
# such as a class attribute holding it (obj.alias(...)); and whether
# check_ode's claim calls _tb_verdict at all (verifier-V5's O16).
# Only review guards against those. The attribute rule is broad on
# purpose: an attribute read that merely shares a definition's name is
# taken to be it, and the message names the attribute - a loud false
# alarm, never a quiet pass.
_TB_ROOTS = ("_tb_verdict", "_tb_refs", "_tb_worst", "_tb_params")
_TB_FORBIDDEN = frozenset((
    # the mirror of the program's rounding order, and its switches
    "ode_step", "_rk_mirror", "_mirror_out", "_SfOps", "_MpOps",
    "_MIRROR_MUTANT", "_mirror_carrying",
    # the generator
    "gen_odes", "_gen_odes_edited", "_as_gen_odes",
    # the program, assembled or run
    "asm", "seq", "run_image", "model_run", "_patch_trip", "_tb_runs",
    "mpmath"))

# The rules' controls: each a small module whose definitions replace this
# file's own before the same walk (_walk), the rule that must refuse it,
# and what the walk must then report - for "named", the forbidden name
# and the tail of the path to it; for "shared", the one definition in
# both reaches and the kind the message gives it. Each replaces _tb_step,
# which _tb_refs calls, or hands a value to _tb_verdict, rather than
# touching anything deeper in the arm, so that a control still applies
# when the arm's insides change. A probe that replaces a definition this
# file no longer has is named stale, not run.
_TB_PROBE_SHARED = """
def ode_step(base, o, K, s, steps, detuned=False):
    return _tb_probe_rhs(o, K, s)


def _tb_probe_rhs(o, K, Y):
    return Y
"""
_TB_PROBE_N6A = """
if True:
    try:
        def _tb_step(base, P, h, Y):
            return _tb_probe_rhs(None, P, Y)
    except NameError:
        pass
""" + _TB_PROBE_SHARED
# The census's control: a def and every kind of assignment the walk
# records, in top-level blocks - plain, unpacked with a star, annotated, a
# for's and a with's - and a walrus and a match capture at the top level,
# which the walk never records.
_TB_PROBE_CENSUS = """
if True:
    try:
        def _tb_probe_def():
            pass
    except NameError:
        _tb_probe_data = None
        _tb_probe_a, *_tb_probe_b = 1, 2
        _tb_probe_ann: int = 1
        for _tb_probe_i in ():
            pass
        with open(__file__) as _tb_probe_w:
            pass
(_tb_probe_walrus := 1)
match 1:
    case _tb_probe_case:
        pass
"""
_TB_CENSUS_BLIND = ["_tb_probe_a", "_tb_probe_ann", "_tb_probe_b",
                    "_tb_probe_case", "_tb_probe_data", "_tb_probe_def",
                    "_tb_probe_i", "_tb_probe_w", "_tb_probe_walrus"]
_TB_CENSUS_SEEN = ["_tb_probe_case", "_tb_probe_walrus"]
# A coefficient table the mirror's step reads, for a probe that shares
# data rather than a function.
_TB_PROBE_COEFFS = """
_tb_probe_coeffs = (1, 2, 2, 1)


def ode_step(base, o, K, s, steps, detuned=False):
    return _tb_probe_coeffs
"""


def _tb_handing(body, rhs, callee="_tb_verdict", params="",
                shared=_TB_PROBE_SHARED):
    """A probe's source: the textbook step generic over its right-hand
    side, what ode_step shares (`shared`), and a caller with `params`
    beside the verdict's own that runs `body` (lines of a function) and
    hands `rhs` to `callee`."""
    return ("\ndef _tb_step(base, P, h, Y, rhs=None):\n    return rhs(Y)\n"
            "\n\ndef _tb_probe_caller(base, fmt, P, h, nstate, s_tb, "
            f"runs{params}):\n" + "".join(f"    {line}\n" for line in body) +
            f"    return {callee}(base, fmt, P, h, nstate, s_tb, runs,\n"
            f"        rhs={rhs})\n" + shared)


_TB_SHARED_RHS = ("_tb_probe_rhs", "a function")
_TB_PROBES = (
    ("_tb_step re-pointed at ode_step through a helper", "named",
     ("ode_step", ("_tb_step", "_tb_probe_hop", "ode_step")), """
def _tb_step(base, P, h, Y):
    return _tb_probe_hop(base, Y)


def _tb_probe_hop(base, Y):
    return ode_step(base, None, None, Y, 1)
"""),
    ("_tb_step computing through a second instance of this module "
     "(verifier-V5's O1)", "named", ("ode_step", ("_tb_step", ".ode_step")),
     """
def _tb_step(base, P, h, Y):
    import importlib
    return importlib.import_module("check").ode_step(base, None, None, Y,
                                                     1)
"""),
    ("one helper for the textbook step and ode_step alike (verifier-V5's "
     "O2a)", "shared", _TB_SHARED_RHS, """
def _tb_step(base, P, h, Y):
    return _tb_probe_rhs(None, P, Y)
""" + _TB_PROBE_SHARED),
    ("that helper handed to a generic textbook arm by its caller "
     "(verifier-V5's N7)", "shared", _TB_SHARED_RHS,
     _tb_handing([], "_tb_probe_rhs")),
    ("that helper handed inside a lambda, through a local lambda and a "
     "local alias", "shared", _TB_SHARED_RHS,
     _tb_handing(["f = _tb_probe_rhs", "g = lambda Y: f(None, P, Y)"],
                 "lambda Y: g(Y)")),
    ("that helper handed through a local conditional with a None branch "
     "(verifier-V5's M1)", "shared", _TB_SHARED_RHS,
     _tb_handing(['tb_rhs = _tb_probe_rhs if base == "l63" else None'],
                 "tb_rhs")),
    ("that helper handed through a local `or` (a default)", "shared",
     _TB_SHARED_RHS,
     _tb_handing(['tb_rhs = P.get("rhs") or _tb_probe_rhs'], "tb_rhs")),
    ("that helper handed out of a local container beside a number, "
     "indexed (verifier-V5's M2)", "shared", _TB_SHARED_RHS,
     _tb_handing(['tb_cfg = {"rhs": _tb_probe_rhs, "digits": 17}'],
                 'tb_cfg["rhs"]')),
    ("that helper handed out of a local table, indexed (verifier-V5's "
     "M3)", "shared", _TB_SHARED_RHS,
     _tb_handing(['tb_table = {"l63": _tb_probe_rhs, "l96": '
                  '_tb_probe_rhs}'], "tb_table[base]")),
    ("that helper handed out of a literal table of tables, indexed twice",
     "shared", _TB_SHARED_RHS,
     _tb_handing([], '{"l63": {"rhs": _tb_probe_rhs}}[base]["rhs"]')),
    ("that helper put into a local table by subscript, then handed out of "
     "it", "shared", _TB_SHARED_RHS,
     _tb_handing(["tb_table = {}", "tb_table[base] = _tb_probe_rhs"],
                 "tb_table[base]")),
    ("that helper put into a local table by a method call's keyword, then "
     "handed out of it", "shared", _TB_SHARED_RHS,
     _tb_handing(["tb_table = {}", "tb_table.update(l63=_tb_probe_rhs)"],
                 "tb_table[base]")),
    ("that helper handed through a local alias of _tb_verdict "
     "(verifier-V5's M4)", "shared", _TB_SHARED_RHS,
     _tb_handing(["verdict = _tb_verdict"], "_tb_probe_rhs",
                 callee="verdict")),
    ("that helper handed through a parameter's default", "shared",
     _TB_SHARED_RHS,
     _tb_handing([], "tb_rhs", params=", tb_rhs=_tb_probe_rhs")),
    ("that helper handed through a keyword-only parameter's default",
     "shared", _TB_SHARED_RHS,
     _tb_handing([], "tb_rhs", params=", *, tb_rhs=_tb_probe_rhs")),
    ("a coefficient table the mirror reads, handed out of a local table "
     "through a conditional and an `or`, indexed", "shared",
     ("_tb_probe_coeffs", "data"),
     _tb_handing(['tb_t = {"c": _tb_probe_coeffs}', "tb_u = {}"],
                 '((tb_t if base else None) or tb_u)["c"]',
                 shared=_TB_PROBE_COEFFS)),
    ("that helper handed through a local alias of _tb_verdict read as an "
     "attribute of this module", "shared", _TB_SHARED_RHS,
     _tb_handing(["import sys",
                  "verdict = sys.modules[__name__]._tb_verdict"],
                 "_tb_probe_rhs", callee="verdict")),
    ("that helper handed through a module-level alias of _tb_verdict",
     "shared", _TB_SHARED_RHS, """
_tb_probe_verdict = _tb_verdict
""" + _tb_handing([], "_tb_probe_rhs", callee="_tb_probe_verdict")),
    ("that helper handed to _tb_verdict called out of a module-level "
     "table", "shared", _TB_SHARED_RHS, """
_tb_probe_calls = {"verdict": _tb_verdict}
""" + _tb_handing([], "_tb_probe_rhs", callee='_tb_probe_calls["verdict"]')),
    ("that helper inside an instance of a class the caller defines",
     "shared", _TB_SHARED_RHS,
     _tb_handing(["class Rhs:", "    def __call__(self, Y):",
                  "        return _tb_probe_rhs(None, None, Y)"], "Rhs()")),
    ("that helper handed out of a module-level table, indexed", "shared",
     _TB_SHARED_RHS, """
_tb_probe_table = {"lorenz63-rk4": _tb_probe_rhs}
""" + _tb_handing([], "_tb_probe_table[base]")),
    ("that helper put into a module-level registry by .update() "
     "(verifier-V5's M5)", "shared", _TB_SHARED_RHS, """
_tb_probe_reg = {}
_tb_probe_reg.update({"lorenz63-rk4": _tb_probe_rhs})


def _tb_step(base, P, h, Y):
    return _tb_probe_reg[base](None, P, Y)
""" + _TB_PROBE_SHARED),
    ("that helper put into a module-level registry by subscript "
     "(verifier-V5's M5a)", "shared", _TB_SHARED_RHS, """
_tb_probe_reg = {}
_tb_probe_reg["lorenz63-rk4"] = _tb_probe_rhs


def _tb_step(base, P, h, Y):
    return _tb_probe_reg[base](None, P, Y)
""" + _TB_PROBE_SHARED),
    ("that helper put into a module-level registry from inside a function "
     "neither side reaches", "shared", _TB_SHARED_RHS, """
_tb_probe_reg = {}


def _tb_probe_install():
    _tb_probe_reg["lorenz63-rk4"] = _tb_probe_rhs


def _tb_step(base, P, h, Y):
    return _tb_probe_reg[base](None, P, Y)
""" + _TB_PROBE_SHARED),
    ("an entry of the generator's table handed to the verdict", "named",
     ("gen_odes", ("_tb_probe_caller hands what gen_odes holds to "
                   "_tb_verdict",)),
     _tb_handing([], "gen_odes.GENERATORS[base]")),
    ("an instance of a class ode_step also uses, handed to the textbook "
     "arm", "shared", ("_tb_probe_ops", "a class"), """
class _tb_probe_ops:
    def fma(self, a, b, c):
        return a


def _tb_step(base, P, h, Y, ops=None):
    return ops.fma(Y, Y, Y)


def ode_step(base, o, K, s, steps, detuned=False):
    return _tb_probe_ops().fma(s, s, s)


def _tb_probe_caller(base, fmt, P, h, nstate, s_tb, runs):
    return _tb_verdict(base, fmt, P, h, nstate, s_tb, runs,
                       ops=_tb_probe_ops())
"""),
    ("the shared helper's user defined in a try inside a top-level if "
     "(verifier-V5's N6a, a level deeper)", "shared", _TB_SHARED_RHS,
     _TB_PROBE_N6A),
    ("the second instance used inside a top-level try (verifier-V5's "
     "N6c)", "named", ("ode_step", ("_tb_step", ".ode_step")), """
try:
    import importlib as _tb_probe_il

    def _tb_step(base, P, h, Y):
        return _tb_probe_il.import_module("check").ode_step(base, None,
                                                             None, Y, 1)
except ImportError:
    _tb_probe_il = None
"""),
    ("the shared helper read as an attribute of this module "
     "(verifier-V5's N6b)", "shared", _TB_SHARED_RHS, """
def _tb_step(base, P, h, Y):
    import sys
    return sys.modules[__name__]._tb_probe_rhs(None, P, Y)
""" + _TB_PROBE_SHARED),
    ("a coefficient table read by both (verifier-V5's N3a)", "shared",
     ("_tb_probe_table", "data"), """
_tb_probe_table = (1, 2, 2, 1)


def _tb_step(base, P, h, Y):
    return _tb_probe_table


def ode_step(base, o, K, s, steps, detuned=False):
    return _tb_probe_table
"""),
)


class _Def:
    """A module-level definition: its kind, what it reads (names, and
    attributes as ".attr"), and the calls in it - (callee, what each call
    hands over) - for the handed rule."""

    __slots__ = ("kind", "reads", "calls")

    def __init__(self, kind):
        self.kind, self.reads, self.calls = kind, set(), []


def _module_statements(body, blocks):
    """Every statement at module level: the top level and, with
    `blocks`, the bodies of top-level if, try, with, for, while and
    match statements at any depth - never a function's or a class's."""
    for node in body:
        yield node
        if not blocks or isinstance(node, (ast.FunctionDef,
                                           ast.AsyncFunctionDef,
                                           ast.ClassDef)):
            continue
        for field in ("body", "orelse", "finalbody"):
            yield from _module_statements(getattr(node, field, None) or [],
                                          blocks)
        for h in getattr(node, "handlers", None) or []:
            yield from _module_statements(h.body, blocks)
        for c in getattr(node, "cases", None) or []:
            yield from _module_statements(c.body, blocks)


def _owner(e):
    """The name under a chain of subscripts and attributes - the
    container `x[k].a` or `x.m` belongs to - or None."""
    while isinstance(e, (ast.Subscript, ast.Attribute)):
        e = e.value
    return e.id if isinstance(e, ast.Name) else None


def _stored(target):
    """-> ([names an assignment target binds], [containers it fills]):
    `x = v` binds x; `x[k] = v` and `x.a = v` fill the container x, which
    then holds v. The names in an index are read, not bound."""
    bound, filled = [], []

    def walk(t):
        if isinstance(t, ast.Name):
            bound.append(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                walk(e)
        elif isinstance(t, ast.Starred):
            walk(t.value)
        elif isinstance(t, (ast.Subscript, ast.Attribute)):
            owner = _owner(t)
            if owner:
                filled.append(owner)
    walk(target)
    return bound, filled


def _call_fill(stmt):
    """(the container, what is put into it) for a statement that is a
    method call on a container - `x.update(v)`, `x.append(v)` - or
    None: the call's arguments, as one expression."""
    if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Attribute)):
        return None
    owner = _owner(stmt.value.func.value)
    if owner is None:
        return None
    return owner, ast.Tuple(elts=list(stmt.value.args) +
                            [k.value for k in stmt.value.keywords],
                            ctx=ast.Load())


def _local_binds(node):
    """({name: [what it is bound to]}, {name: [what is put into it]})
    for a function or class, nested ones included. A binding is an
    expression, a nested function, class or lambda, a parameter's
    default, or None for a value a caller passes, an import or an
    exception, which this file does not show; what is put into a name
    comes from `x[k] = v`, `x.a = v` or a statement `x.m(v)`. A name
    filled here and bound nowhere in it is not a local: it is the
    module's, and _code_map gives the module's definition what is put
    into it."""
    binds, fills = {}, {}

    def bind(target, value):
        bound, filled = _stored(target)
        for n in bound:
            binds.setdefault(n, []).append(value)
        for n in filled:
            fills.setdefault(n, []).append(value)
    for n in ast.walk(node):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                          ast.Lambda)):
            a = n.args
            positional = a.posonlyargs + a.args
            defaults = ([None] * (len(positional) - len(a.defaults)) +
                        list(a.defaults))
            for arg, default in (list(zip(positional, defaults)) +
                                 list(zip(a.kwonlyargs, a.kw_defaults)) +
                                 [(a.vararg, None), (a.kwarg, None)]):
                if arg is not None:
                    binds.setdefault(arg.arg, []).append(None)
                    if default is not None:     # what a call may omit
                        binds[arg.arg].append(default)
            if n is not node and not isinstance(n, ast.Lambda):
                binds.setdefault(n.name, []).append(n)
        elif isinstance(n, ast.ClassDef) and n is not node:
            binds.setdefault(n.name, []).append(n)
        elif isinstance(n, ast.Assign):
            for target in n.targets:
                bind(target, n.value)
        elif isinstance(n, (ast.AnnAssign, ast.AugAssign)) and n.value:
            bind(n.target, n.value)
        elif isinstance(n, (ast.For, ast.AsyncFor, ast.comprehension)):
            bind(n.target, n.iter)
        elif isinstance(n, (ast.With, ast.AsyncWith)):
            for item in n.items:
                if item.optional_vars is not None:
                    bind(item.optional_vars, item.context_expr)
        elif isinstance(n, ast.NamedExpr):
            bind(n.target, n.value)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            binds.setdefault(n.name, []).append(None)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for alias in n.names:
                binds.setdefault((alias.asname or alias.name)
                                 .split(".")[0], []).append(None)
        else:
            fill = _call_fill(n)
            if fill:
                fills.setdefault(fill[0], []).append(fill[1])
    return binds, fills


def _named_in(node):
    """Every name a piece of code loads, and every attribute it reads as
    ".attr" - what a lambda or a nested function carries with it."""
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            out.append(n.id)
        elif isinstance(n, ast.Attribute):
            out.append("." + n.attr)
    return out


_CONTAINERS = (ast.Tuple, ast.List, ast.Set, ast.Dict)


def _members(v):
    """What indexing a literal container may yield: a dict's values, the
    others' elements."""
    return v.values if isinstance(v, ast.Dict) else v.elts


def _code_shaped(v, classes):
    """Can a local bound to `v` hold code - a name, an attribute, a
    lambda, a nested function or class, an instance of one of `classes`,
    an entry of a table, or a conditional or container ANY part of which
    can (a None branch or a number beside the code is no reason to stop:
    verifier-V5's M1, M2)? A value a call computes, or arithmetic, a
    comprehension or a literal makes, is data: a local bound to one is
    not followed (in check_ode, whose locals are reused for many things,
    following those tied every table the function reads to the
    verdict)."""
    if isinstance(v, (ast.Name, ast.Attribute, ast.Lambda, ast.FunctionDef,
                      ast.AsyncFunctionDef, ast.ClassDef)):
        return True
    if isinstance(v, ast.Call):
        return isinstance(v.func, ast.Name) and v.func.id in classes
    if isinstance(v, (ast.Subscript, ast.Starred)):
        return _code_shaped(v.value, classes)
    if isinstance(v, _CONTAINERS):
        return any(_code_shaped(e, classes) for e in _members(v))
    if isinstance(v, ast.IfExp):
        return (_code_shaped(v.body, classes) or
                _code_shaped(v.orelse, classes))
    if isinstance(v, ast.BoolOp):
        return any(_code_shaped(e, classes) for e in v.values)
    return False


def _handed(exprs, local, classes, memo):
    """What the expressions `exprs` hand over when a call is given them:
    module-level names, ".attr" for an attribute, and "[" + x for an
    entry of the module-level table x (resolved by _entries_of, once the
    whole file is known). `local` is _local_binds' (binds, fills) of the
    definition the call is in: a local resolves through what it is bound
    to and what is put into it, where that can hold code (_code_shaped),
    each once (`memo`, one per definition; a local that depends on itself
    adds nothing more). A local or literal table indexed hands its
    entries themselves. A call made on the way hands over its result, not
    its callee, unless the callee is one of `classes` (an instance carries
    its class) - but its arguments go on being read, since a wrapper
    (functools.partial) keeps what it is given."""
    binds, fills = local

    def follow(name, how):
        """The local `name` as a whole ("whole") or indexed ("entry")."""
        key = (how, name)
        if key not in memo:
            memo[key] = set()
            got = set()
            for v in binds.get(name, ()):
                if v is not None and _code_shaped(v, classes):
                    got |= whole(v) if how == "whole" else entries(v)
            for v in fills.get(name, ()):
                if _code_shaped(v, classes):
                    got |= whole(v)
            memo[key] = got
        return memo[key]

    def whole(v):
        if isinstance(v, (ast.FunctionDef, ast.AsyncFunctionDef,
                          ast.ClassDef, ast.Lambda)):
            return names(_named_in(v))
        return expr(v)

    def names(items):
        got = set()
        for s in items:
            if s[:1] != "." and s in binds:
                got |= follow(s, "whole")
            else:
                got.add(s)
        return got

    def entries(e):
        """What indexing `e` yields: a local's entries, a module-level
        table's as "[" + its name, a literal's members themselves, both
        branches' of a conditional; anything else's as "[" + what it
        hands (a table of tables indexed twice among that)."""
        if isinstance(e, ast.Name):
            if e.id in binds:
                return follow(e.id, "entry")
            return {"[" + e.id}
        if isinstance(e, _CONTAINERS):
            return exprs_of(_members(e))
        if isinstance(e, ast.IfExp):
            return entries(e.body) | entries(e.orelse)
        if isinstance(e, ast.BoolOp):
            got = set()
            for v in e.values:
                got |= entries(v)
            return got
        return {"[" + x for x in expr(e)}

    def exprs_of(es):
        got = set()
        for e in es:
            got |= expr(e)
        return got

    def expr(e):
        got, todo = set(), [e]
        while todo:
            e = todo.pop()
            if isinstance(e, ast.Lambda):
                got |= names(_named_in(e))
            elif isinstance(e, ast.Call):
                if isinstance(e.func, ast.Name) and e.func.id in classes:
                    got |= names([e.func.id])
                todo.extend(e.args)
                todo.extend(k.value for k in e.keywords)
            elif isinstance(e, ast.Subscript):
                got |= entries(e.value)
            elif isinstance(e, ast.Name):
                if isinstance(e.ctx, ast.Load):
                    got |= names([e.id])
            elif isinstance(e, ast.Attribute):
                got.add("." + e.attr)
                todo.append(e.value)
            else:
                todo.extend(ast.iter_child_nodes(e))
        return got
    return exprs_of(exprs)


def _callees(f, local, classes, memo):
    """What a call's function may be: a name or an attribute's name as
    written; through a local, or any other expression (a lambda, a table's
    entry), what it holds - an attribute by its name, as when called
    directly, and an entry of a module-level table x as "[x". _reach
    resolves those tables, and a module-level alias, to what they name
    (verifier-V5's M4: a local alias of _tb_verdict)."""
    if isinstance(f, ast.Attribute):
        return {f.attr}
    if isinstance(f, ast.Name) and f.id not in local[0]:
        return {f.id}
    return {x.lstrip(".") for x in _handed([f], local, classes, memo)}


def _record(d, node, local, classes):
    """Add what `node` reads and the calls in it to the definition d. A
    class `node` defines inside itself is a class there, as the module's
    are everywhere."""
    d.reads.update(_named_in(node))
    classes = set(classes) | {n for n, vs in local[0].items()
                              if any(isinstance(v, ast.ClassDef)
                                     for v in vs)}
    memo = {}
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            handed = frozenset(_handed(
                list(n.args) + [k.value for k in n.keywords], local,
                classes, memo))
            for callee in _callees(n.func, local, classes, memo):
                d.calls.append((callee, handed))


def _code_map(tree, classes, blocks):
    """{name: _Def} for every definition `tree` makes at module level
    (_module_statements, into top-level blocks when `blocks`), with what
    each reads and the calls in it; and what the file puts into a
    module-level table - `X[k] = v`, `X.a = v`, a statement `X.m(v)`, at
    module level or inside a function or class that does not bind X -
    joins X's reads. `classes` are classes defined elsewhere (a probe's
    host file)."""
    entries, fills = [], []
    for s in _module_statements(tree.body, blocks):
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef,
                          ast.ClassDef)):
            local = _local_binds(s)
            entries.append((s.name, "a class" if isinstance(s, ast.ClassDef)
                            else "a function", s, local))
            fills.extend((name, v) for name, vs in local[1].items()
                         if name not in local[0] for v in vs)
        elif _call_fill(s):
            fills.append(_call_fill(s))
        else:
            pairs = []
            if isinstance(s, ast.Assign):
                pairs = [(target, s.value) for target in s.targets]
            elif isinstance(s, (ast.AnnAssign, ast.AugAssign)) and s.value:
                pairs = [(s.target, s.value)]
            elif isinstance(s, (ast.For, ast.AsyncFor)):
                pairs = [(s.target, s.iter)]
            elif isinstance(s, (ast.With, ast.AsyncWith)):
                pairs = [(i.optional_vars, i.context_expr) for i in s.items
                         if i.optional_vars is not None]
            for target, value in pairs:
                kind = ("a function" if isinstance(value, ast.Lambda)
                        else "data")
                bound, filled = _stored(target)
                for name in bound:
                    entries.append((name, kind, value, ({}, {})))
                fills.extend((name, value) for name in filled)
    classes = set(classes) | {n for n, k, _v, _b in entries if k == "a class"}
    defs = {}
    for name, kind, node, local in entries:
        d = defs.get(name)
        if d is None:
            d = defs[name] = _Def(kind)
        elif kind != "data":
            d.kind = kind
        _record(d, node, local, classes)
    for name, node in fills:
        if name in defs:
            _record(defs[name], node, ({}, {}), classes)
    return defs


def _walk(tree, classes=()):
    """The one walk the rules use - for this file, for the census's
    control and for every probe - so that where it looks cannot change
    for one of them alone."""
    return _code_map(tree, classes, True)


# The nodes a match pattern binds a name with (Python 3.10 on).
_MATCH_CAPTURES = tuple(getattr(ast, n) for n in
                        ("MatchAs", "MatchStar", "MatchMapping")
                        if hasattr(ast, n))


def _census(tree):
    """{name: kind} for every name `tree` binds outside any function,
    class or lambda - "a function" or "a class" for a def or class
    statement, "data" for a name an assignment, a for, a with or a walrus
    stores, or a match pattern captures - found by a walk of its own that
    shares no code with the rules' walk (_module_statements, _code_map,
    _stored), so that a place that walk does not look shows as a
    difference. An import binds no definition: what it brings in is code
    outside this file."""
    out = {}

    def visit(node, inside):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef)):
                if not inside:
                    out[child.name] = ("a class" if isinstance(
                        child, ast.ClassDef) else "a function")
                visit(child, True)
                continue
            if not inside:
                targets = []
                if isinstance(child, ast.Assign):
                    targets = child.targets
                elif isinstance(child, (ast.AnnAssign, ast.AugAssign)):
                    targets = [child.target] if child.value else []
                elif isinstance(child, (ast.For, ast.AsyncFor)):
                    targets = [child.target]
                elif isinstance(child, (ast.With, ast.AsyncWith)):
                    targets = [i.optional_vars for i in child.items
                               if i.optional_vars is not None]
                elif isinstance(child, ast.NamedExpr):
                    targets = [child.target]
                for target in targets:
                    for n in ast.walk(target):
                        if (isinstance(n, ast.Name) and
                                isinstance(n.ctx, ast.Store)):
                            out.setdefault(n.id, "data")
                if isinstance(child, _MATCH_CAPTURES):
                    name = (getattr(child, "name", None) or
                            getattr(child, "rest", None))
                    if name:
                        out.setdefault(name, "data")
            visit(child, inside or isinstance(child, ast.Lambda))
    visit(tree, False)
    return out


def _census_gaps(tree, defs):
    """What the census finds and `defs` (from a walk) does not hold -
    at all, or, for a def or class, as one."""
    return sorted(n for n, k in _census(tree).items()
                  if n not in defs or (k != "data" and
                                       defs[n].kind == "data"))


def _entries_of(defs, item):
    """What an entry of `item` may be, as items: for a module-level table
    (data), what it names; for a function or class, itself - a local or
    literal table reaches the walk already flattened to its entries, so
    an entry that names a function is that function (verifier-V5's M3b,
    a table of tables); for "[x", the entries of x's entries; for a name
    this file does not define, itself."""
    if item[:1] == "[":
        out = set()
        for e in _entries_of(defs, item[1:]):
            out |= _entries_of(defs, e)
        return out
    bare = item.lstrip(".")
    d = defs.get(bare)
    if d is None or d.kind != "data":
        return {bare}
    return set(d.reads)


def _reach(defs, roots, forbidden):
    """-> (the reach, {forbidden name: the path to it}, [root not
    defined], how each definition was reached): everything reached from
    `roots` by name, by attribute, or handed to a call of something
    reached - called by its own name, or through a module-level alias or
    table that names it - from anywhere in `defs`, until nothing more is.
    A path is a tuple of names; a handing reads "caller hands x to
    callee". An indexed item whose innermost name is forbidden is a
    hit."""
    missing = [r for r in roots if r not in defs]
    how = {r: (r,) for r in roots if r in defs}
    hits, reach, todo, names = {}, set(), list(how), {}

    def consider(item, path):
        if item[:1] == "[":
            base = item.lstrip("[.")
            if base in forbidden:
                hits.setdefault(base, path)
                return
            for e in sorted(_entries_of(defs, item[1:])):
                consider(e, path + (e,))
            return
        bare = item.lstrip(".")
        if bare in forbidden:
            hits.setdefault(bare, path)
        elif bare in defs and bare not in how:
            how[bare] = path
            todo.append(bare)
    while True:
        while todo:
            name = todo.pop()
            if name in reach:
                continue
            reach.add(name)
            for r in sorted(defs[name].reads):
                consider(r, how[name] + (r,))
        for caller in sorted(defs):
            for callee, handed in defs[caller].calls:
                # What is called: the definition itself, and what a
                # module-level alias or table ("[x") names.
                if callee not in names:
                    names[callee] = {callee} | {e.lstrip(".") for e in (
                        _entries_of(defs, callee[1:] if callee[:1] == "["
                                    else callee))}
                called = sorted(names[callee] & reach)
                shown = (callee if called == [callee] else
                         f"{' or '.join(called)}, through "
                         f"{callee.lstrip('[.')}")
                if called:
                    for item in sorted(handed):
                        what = (f"what {item.lstrip('[')} holds"
                                if item[:1] == "[" else item.lstrip("."))
                        consider(item, (f"{caller} hands {what} to "
                                        f"{shown}",))
        if not todo:
            return reach, hits, missing, how


def _tb_independence(defs):
    """Both rules over `defs` (_walk) -> ([roots not defined],
    {forbidden name: path}, [definitions in both reaches], how many the
    verdict reaches, the implementations' roots, how the verdict reached
    each definition)."""
    tb, hits, missing, how = _reach(defs, _TB_ROOTS, _TB_FORBIDDEN)
    impl = sorted(n for n in _TB_FORBIDDEN if n in defs)
    impl_reach, _h, _m, _how = _reach(defs, impl, frozenset())
    return missing, hits, sorted(tb & impl_reach), len(tb), impl, how


def _golden_unresumed(image, bank, s_in, n, nstate, steps):
    """[lanes] where two segments of `image` chained through the golden
    executor end differently from one segment of twice the steps - the
    resume arm's question asked without segment() or resumes(), to tell a
    comparison gone blind from a control that has lost its difference."""
    z = [0] * n
    prog = seq.Program.from_bytes(image)
    twice = seq.Program.from_bytes(_patch_trip(image, steps, 2 * steps,
                                               0).to_bytes())
    first = seq.run(prog, z, z, None, bank=bank, scratch_in=s_in)
    two = seq.run(prog, z, z, None, bank=bank,
                  scratch_in=first.scratch_out).scratch_out
    one = seq.run(twice, z, z, None, bank=bank, scratch_in=s_in).scratch_out
    return [i for i in range(n) if two[i * nstate:(i + 1) * nstate] !=
            one[i * nstate:(i + 1) * nstate]]


def check_textbook_independence():
    """The census, the two rules above over this file's own source, and
    their controls."""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    defs = _walk(tree)
    gaps = _census_gaps(tree, defs)
    if gaps:
        bad("textbook arm: independence", f"check.py binds "
            f"{', '.join(gaps)} at module level where the walk does not "
            f"record it, so neither rule can see into it")
        return
    ok(f"textbook arm: the walk records every one of the "
       f"{len(_census(tree))} names check.py binds at module level - defs, "
       f"classes and assignments, in its top-level blocks too")
    probe = ast.parse(_TB_PROBE_CENSUS)
    blind = _census_gaps(probe, _code_map(probe, (), False))
    seen = _census_gaps(probe, _walk(probe))
    if (blind, seen) != (_TB_CENSUS_BLIND, _TB_CENSUS_SEEN):
        bad("textbook arm: NEGATIVE CONTROL FAILED TO FAIL",
            f"the census named {blind} against a walk of the top level "
            f"alone and {seen} against the rules' walk; it must name "
            f"{_TB_CENSUS_BLIND} - a def and every kind of assignment in "
            f"top-level blocks, a walrus and a match capture - against the "
            f"first, and {_TB_CENSUS_SEEN} against the second")
        return
    ok("textbook arm: NEGATIVE CONTROL - against a walk of the top level "
       "alone the census names a def and every kind of assignment in "
       "top-level blocks (plain, starred, annotated, a for's, a with's), a "
       "walrus and a match capture; against the rules' walk, the walrus and "
       "the match capture alone", f"{len(_TB_CENSUS_BLIND)} names")
    missing, hits, shared, followed, impl, how = _tb_independence(defs)
    if missing or not impl:
        bad("textbook arm: independence",
            f"check.py defines no {', '.join(missing or ['implementation'])}"
            f" - the rules' roots are stale, so they would check nothing")
        return
    if hits or shared:
        bad("textbook arm: independence", "; ".join(
            [f"the textbook verdict reaches {' -> '.join(p)}"
             for p in hits.values()] +
            [f"{s} ({defs[s].kind}; the verdict reaches it by "
             f"{' -> '.join(how[s])}) is reached from the implementations "
             f"too - the authority shares it with what it judges"
             for s in shared]))
        return
    ok(f"textbook arm: from {', '.join(_TB_ROOTS)}, no path through "
       f"check.py reaches the mirror, the generator or an executor of the "
       f"program - by name, by attribute, or handed in by a caller",
       f"{followed} definitions followed")
    ok(f"textbook arm: none of those {followed} definitions is reached from "
       f"the implementations' {len(impl)} roots as well, whatever it is "
       f"called")
    classes = {n for n, d in defs.items() if d.kind == "a class"}
    for what, rule, want, source in _TB_PROBES:
        replaced = _walk(ast.parse(source), classes)
        stale = [d for d in replaced
                 if not d.startswith("_tb_probe") and d not in defs]
        if stale:
            bad("textbook arm: control", f"{what}: it replaces "
                f"{', '.join(stale)}, which check.py no longer defines - "
                f"the probe is stale; rewrite it against the arm as it is")
            return
        probed = dict(defs)
        probed.update(replaced)
        _m, hits2, shared2, _n, _i, _how2 = _tb_independence(probed)
        if rule == "named":
            key, tail = want
            got = hits2.get(key, ())
            caught = got[-len(tail):] == tail
            said = " -> ".join(got)
        else:
            kinds = [probed[s].kind for s in shared2]
            caught = (shared2, kinds) == ([want[0]], [want[1]])
            said = "; ".join(f"{s} ({k}), reached by "
                             f"{' -> '.join(_how2[s])}"
                             for s, k in zip(shared2, kinds))
        if not caught:
            bad("textbook arm: NEGATIVE CONTROL FAILED TO FAIL",
                f"{what} was not refused by the {rule} rule as {want} (it "
                f"found {hits2 or 'no path'} and shared "
                f"{shared2 or 'nothing'}; if _tb_refs no longer calls "
                f"_tb_step, or _tb_verdict is no longer one of _TB_ROOTS, "
                f"the probe is what needs rewriting)")
            return
        ok(f"textbook arm: NEGATIVE CONTROL - {what} is refused by the "
           f"{rule} rule", said)


def check_ode(args, name, image, image_path, tmp):
    base, fmtname = _ode_base(name)
    fmt = FORMATS[fmtname]
    pin = _ODE_PINNED[base]
    nstate, steps = pin["nstate"], pin["steps"]
    n, n_tb = _ODE_LANES[base]
    bank_path = HERE / (name + ".classic.bank")

    # -- generated ---------------------------------------------------------
    have_src = _read_source(HERE / (name + ".cfta"))
    have_bank = bank_path.read_bytes() if bank_path.exists() else None
    want_src = gen_odes.GENERATORS[base](fmtname).encode("ascii")
    want_bank = gen_odes.bank_bytes(base, fmt)

    def generated(src_bytes):
        return src_bytes == want_src and have_bank == want_bank

    if not generated(have_src):
        bad(f"{name}: generated", "the committed source or bank is not "
                                  "gen_odes.py's output, byte for byte - "
                                  "run it")
        return
    ok(f"{name}: source and bank are gen_odes.py's output, byte for byte")
    crlf_path = tmp / (name + ".crlf.cfta")
    crlf_path.write_bytes(want_src.replace(b"\n", b"\r\n"))
    if generated(_read_source(crlf_path)):
        bad(f"{name}: NEGATIVE CONTROL FAILED TO FAIL",
            "the generator's text with CRLF line ends, written to disk and "
            "read back through the claim's reader, still matched it - the "
            "reader normalises line ends")
        return
    ok(f"{name}: NEGATIVE CONTROL - the generator's text with CRLF line "
       f"ends, written to disk and read back through the claim's reader, "
       f"is refused", f"{crlf_path.stat().st_size - len(want_src)} bytes "
                      f"more")
    src = have_src.decode("ascii")

    # -- bank, slot by slot under the names the source declares ---------------
    simg = asm.assemble_image(src, name)
    if simg.to_bytes() != image:
        bad(f"{name}: bank", "the source's own assembly is not the image "
                             "checked above, so its names are not this "
                             "image's")
        return
    K = values(have_bank, fmt)
    names, problems = _bank_verdict(fmt, base, src, K)
    if problems:
        bad(f"{name}: bank", "; ".join(problems))
        return
    ok(f"{name}: each of the {len(K)} bank values is the correctly rounded "
       f"value of the definition of the name the source gives its slot",
       ", ".join(names))
    vals = gen_odes.bank_values(base, fmt)
    order = [c for c, _v in vals]
    ta, tb = _ODE_TRANSPOSE[base]
    moved = [v for _c, v in vals]
    moved[order.index(ta)], moved[order.index(tb)] = \
        moved[order.index(tb)], moved[order.index(ta)]
    nudged = [v for _c, v in vals]
    nudged[order.index(_ODE_NUDGE[base])] += 1
    swapped = _swap_const_lines(src, ta, tb)
    if swapped is None:
        bad(f"{name}: control", f"the source does not declare {ta} and "
                                f"{tb} once each, so the control cannot "
                                f"transpose them")
        return
    for what, text, bits in (
            (f"bank_values with {ta} and {tb} transposed", src, moved),
            (f"bank_values with {_ODE_NUDGE[base]} one ulp off", src,
             nudged),
            (f"the source with its {ta} and {tb} .const lines transposed "
             f"over the committed bank", swapped, K)):
        _names, why = _bank_verdict(fmt, base, text, bits)
        if not why:
            bad(f"{name}: NEGATIVE CONTROL FAILED TO FAIL",
                f"{what} passed the bank check")
            return
        ok(f"{name}: NEGATIVE CONTROL - {what} is refused", "; ".join(why))

    # -- pinned: the row's numbers, against this file's literals ------------
    img = asm.Image.from_bytes(image)
    m = _ode_measure(img)
    problems = _ode_pinned_problems(base, m)
    if problems:
        bad(f"{name}: pinned", "; ".join(problems))
        return
    ok(f"{name}: {m['nstate']} state values, {m['steps']} steps a segment, "
       f"{m['alu']} ALU instructions and {m['ctl']} control codes a step, "
       f"{m['insns']} instructions, {m['consts']} bank values, "
       f"{m['slots']} scratch slots - as pinned here, not as gen_odes.py "
       f"says")
    # The comparator, number by number: each of the image's numbers moved
    # one on must be refused, and under its own key. (verifier-V5's O11:
    # a comparator cut down to the state size and the steps passed every
    # control below, which move only those two.)
    moved = [(field, key) for field, key in _PINNED_MOVES
             if [p.split(":")[0] for p in _ode_pinned_problems(
                 base, dict(m, **{field: m[field] + 1}))] != [key]]
    if moved:
        bad(f"{name}: NEGATIVE CONTROL FAILED TO FAIL",
            "moved one on, " + ", ".join(f"{f}" for f, _k in moved) +
            " went unrefused, or refused under another key")
        return
    ok(f"{name}: NEGATIVE CONTROL - each of the image's "
       f"{len(_PINNED_MOVES)} pinned numbers, moved one on, is refused "
       f"under its own key")
    for old, new, key in _PINNED_EDITS[base]:
        try:
            mod = _gen_odes_edited(old, new)
        except ValueError as exc:
            bad(f"{name}: control", str(exc))
            return
        with _as_gen_odes(mod):
            etext = gen_odes.GENERATORS[base](fmtname)
            why = _ode_pinned_problems(
                base, _ode_measure(asm.assemble_image(etext, name + "-ed")))
        mine = [p for p in why if p.startswith(key + ":")]
        if not mine:
            bad(f"{name}: NEGATIVE CONTROL FAILED TO FAIL",
                f"gen_odes.py with `{new}` in place of `{old}`, "
                f"regenerated, passed the pinned check's {key}" +
                (f" (it named only: {'; '.join(why)})" if why else ""))
            return
        ok(f"{name}: NEGATIVE CONTROL - gen_odes.py with `{new}` in place "
           f"of `{old}`, regenerated, is refused", "; ".join(mine))

    # -- prose: the README's row, the source's comments and the generator's
    # docstring, against the image
    texts = {"readme": (HERE / "README.md").read_text(encoding="utf-8"),
             "source": _comment_text(src), "generator": _generator_doc()}
    problems = _ode_prose_problems(base, name, fmtname, m, texts, n, n_tb)
    if problems:
        bad(f"{name}: prose", "; ".join(problems))
        return
    said = sum(len(v) for v in _ODE_PROSE[base].values())
    ok(f"{name}: programs/README.md's row, the source's own comments and "
       f"gen_odes.py's docstring state the image's numbers",
       f"5 cells and {said} phrases")
    # The control: one number changed through each of the arm's five
    # readings, and each must be named where it is - the row's
    # instruction-count cell moved one on; the ALU count the row's text
    # states with a digit put before it ("153 ALU" for "53 ALU"), which
    # also watches that a phrase is not found inside a longer number
    # (verifier-V5's O5); and one on, the state count the README's
    # paragraph spells, the ALU count the source's comments state (run
    # together, as the claim reads them, so that a re-wrapped comment is
    # moved the same way - its O5h) and the state count the generator's
    # docstring spells. The trailing bound (_phrase_re) has no control
    # of its own; of the templates, only "of Lorenz 1963" ends in a
    # number.
    words = _number_word(m["nstate"])
    wrong = _number_word(m["nstate"] + 1)
    para = _ODE_PROSE[base]["readme"][0]
    gdoc = _ODE_PROSE[base]["generator"][0].format(
        **{c: str(v) for c, v in _bank_derivations(base).items()},
        nstate=m["nstate"], word="{word}")
    edits = (
        ("readme", f"| `{name}` | {fmtname} | {m['insns']:,} |",
         f"| `{name}` | {fmtname} | {m['insns'] + 1:,} |", "readme insns:"),
        ("readme", f"{m['alu']} ALU instructions",
         f"1{m['alu']} ALU instructions", "readme: the row does not say"),
        ("readme", para.format(word=words), para.format(word=wrong),
         "readme: it does not say"),
        ("source", f"is {m['alu']} ALU", f"is {m['alu'] + 1} ALU",
         "source: its comments do not say"),
        ("generator", gdoc.format(word=words), gdoc.format(word=wrong),
         "generator: its docstring does not say"))
    # Every mention is moved - a second, harmless mention of a number is
    # no reason for the control to fail (verifier-V5's P3), and that is
    # watched below.
    def moved_texts(changes, start=None):
        out = dict(texts if start is None else start)
        for where, was, now in changes:
            pat = _phrase_re(was)
            if was == now or not pat.search(out[where]):
                return None, f"`{was}` is not in the {where}"
            out[where] = pat.sub(lambda _m, now=now: now, out[where])
        return out, ""
    moved, missing = moved_texts([e[:3] for e in edits])
    if moved is None:
        bad(f"{name}: control", f"{missing}, so the prose control cannot "
                                f"move it")
        return
    why = _ode_prose_problems(base, name, fmtname, m, moved, n, n_tb)
    unnamed = [was for _w, was, _n, named in edits
               if not any(p.startswith(named) for p in why)]
    # And the bounds' other edges, a pass each: a hyphen before the row's
    # ALU count ("20-53 ALU", a range) and one after the end of the first
    # row phrase that ends in a word and holds no ALU count; then a letter
    # after that phrase's end. Each phrase must be named.
    tail = next(t.format(**_prose_fill(base, m, n, n_tb))
                for t in _ODE_PROSE[base]["row"]
                if "{alu}" not in t and re.search(r"\w$", t))
    alu = f"{m['alu']} ALU instructions"
    edges = ([("readme", alu, f"20-{alu}"), ("readme", tail, tail + "-x")],
             [("readme", tail, tail + "x")])
    counts = [len(why)]
    for changes in edges:
        moved2, missing = moved_texts(changes)
        if moved2 is None:
            bad(f"{name}: control", f"{missing}, so the prose control "
                                    f"cannot move it")
            return
        why2 = _ode_prose_problems(base, name, fmtname, m, moved2, n, n_tb)
        counts.append(len(why2))
        unnamed += [f"{now} (a bound)" for _w, was, now in changes
                    if not any(p.startswith("readme: the row does not say")
                               and was in p for p in why2)]
    if unnamed:
        bad(f"{name}: NEGATIVE CONTROL FAILED TO FAIL",
            f"with each changed, {'; '.join(unnamed)} went unnamed "
            f"(it named: {'; '.join(why) or 'nothing'})")
        return
    ok(f"{name}: NEGATIVE CONTROL - the row's instruction count one on "
       f"and its ALU count with a digit before it, and the paragraph's "
       f"state count, the source's ALU count and the generator's state "
       f"count each one on, are each named; so are the row's ALU count "
       f"after a hyphen, and a phrase with a hyphen, then a letter, after "
       f"its end", " + ".join(str(c) for c in counts) + " problems")
    # The move itself: the source's ALU phrase said a second time must be
    # moved both times, or a page that says a number twice would turn the
    # control red on a sound arm (verifier-V5's P3; at 98d7b05 a
    # once-only move passed the gate, the texts saying each number once).
    said = f"is {m['alu']} ALU"
    twice = dict(texts, source=f"{texts['source']} So a step {said} "
                               f"instructions long.")
    moved3, missing = moved_texts([("source", said,
                                    f"is {m['alu'] + 1} ALU")], twice)
    if moved3 is None or _phrase_re(said).search(moved3["source"]):
        bad(f"{name}: control", f"`{said}` said twice in the source was "
            f"not moved both times ({missing or 'one left'}), so a page "
            f"that says a number twice would fail the prose control")
        return
    ok(f"{name}: the prose control moves every mention - `{said}` said "
       f"twice in the source is moved twice")

    # -- static --------------------------------------------------------------
    feats = set(img.features())
    if (img.flags != (asm.FLAG_BANK_EXT | asm.FLAG_SCRATCH_IO) or
            img.max_deposits != 0 or img.n_consts != len(K) or
            (img.n_scratch_in, img.n_scratch_out) != (nstate, nstate) or
            not {"BANK_PTR", "SCRATCH", "SCRATCH_IO"} <= feats):
        bad(f"{name}: header", f"flags {img.flags:#x}, deposits "
            f"{img.max_deposits}, consts {img.n_consts}, io "
            f"{img.n_scratch_in}/{img.n_scratch_out}, {sorted(feats)}")
        return
    ok(f"{name}: BANK_EXT and SCRATCH_IO, no deposits, {nstate} slots in "
       f"and out, {len(K)} bank values", " ".join(img.features()))

    # The textbook arm's states, and the program's first two steps from
    # them through the golden executor. The census reads that executor's
    # instruction count off the same two runs.
    s_tb = _tb_states(base, fmt, n_tb)
    runs = _tb_runs(image, steps, K, s_tb, n_tb, (1, 2))

    # -- census ----------------------------------------------------------------
    alu, ctl = m["alu"], m["ctl"]
    per_step = runs[2].insns_executed - runs[1].insns_executed
    if per_step != alu + ctl + 1:
        bad(f"{name}: census", f"the golden executor runs {per_step} "
            f"instructions a step; the image's {alu} ALU instructions and "
            f"{ctl} control codes a step and its ENDREP are "
            f"{alu + ctl + 1}")
        return
    ok(f"{name}: census - a lane-step is {alu} ALU instructions and {ctl} "
       f"control codes besides the loop's ENDREP "
       f"({100.0 * ctl / (alu + ctl):.1f}% of those {alu + ctl}); the golden "
       f"executor runs {per_step} a step, the ENDREP included",
       f"{len(img.insns)} instructions in the image")

    # -- identity -----------------------------------------------------------------
    s_in = ode_initial(base, fmt, n)
    ap, bp = tmp / (name + ".a.bin"), tmp / (name + ".bank")
    sip, sop = tmp / (name + ".s0.bin"), tmp / (name + ".s1.bin")
    ap.write_bytes(pack([0] * n, fmt))
    bp.write_bytes(have_bank)
    sip.write_bytes(pack(s_in, fmt))
    dep, rep = run_image(args, image_path, tmp, name, a=ap, bank=bp,
                         scratch_in=sip, scratch_out=sop)
    if dep is None:
        bad(f"{name}: library run", rep)
        return
    lib = values(sop.read_bytes(), fmt)
    prog = seq.Program.from_bytes(image)
    gold = seq.run(prog, [0] * n, [0] * n, None, bank=K, scratch_in=s_in)
    ref = _mirror_out(base, fmt, K, s_in, nstate, steps)
    if not (len(lib) == n * nstate and lib == gold.scratch_out == ref and
            gold.status == 0 and ref != s_in):
        which = ("library != golden" if lib != gold.scratch_out else
                 "golden != ode_step" if gold.scratch_out != ref else
                 "the state did not move" if ref == s_in else
                 f"status {gold.status}")
        bad(f"{name}: identity", which)
        return
    ok(f"{name}: the library's executor, the golden model's and ode_step - "
       f"this file's mirror of the program's rounding order - agree bit "
       f"for bit", f"{n} lanes x {steps} steps, scratch-out "
       f"{hashlib.sha256(sop.read_bytes()).hexdigest()[:16]}")

    # the control: one instruction's operands swapped must be caught
    swap = {"lorenz63-rk4": ("  sub  t0, y, x", "  sub  t0, x, y"),
            "lorenz96-rk4": ("  sub  t1, F, w0", "  sub  t1, w0, F"),
            "henonheiles-lf": ("  sub  t2, y, ONE", "  sub  t2, ONE, y")}
    old, new = swap[base]
    if src.count(old) < 1:
        bad(f"{name}: control", f"the line to mutate, {old.strip()!r}, is "
                                f"not in the source")
        return
    mut = asm.assemble(src.replace(old, new, 1), name + "-mutant")
    mres = seq.run(seq.Program.from_bytes(mut), [0] * n, [0] * n, None,
                   bank=K, scratch_in=s_in)
    if mres.scratch_out == ref:
        bad(f"{name}: NEGATIVE CONTROL FAILED TO FAIL",
            f"{old.strip()} -> {new.strip()} still matched ode_step")
        return
    ok(f"{name}: NEGATIVE CONTROL - `{new.strip()}` in place of "
       f"`{old.strip()}` is caught by the same comparison")

    # -- textbook -------------------------------------------------------------
    scheme = ("Stormer-Verlet step" if base == "henonheiles-lf" else
              "classic Runge-Kutta step")
    try:
        h, P = _tb_params(base, fmt, names, K)
    except ValueError as exc:
        bad(f"{name}: textbook", str(exc))
        return
    worst, kmax = _tb_verdict(base, fmt, P, h, nstate, s_tb, runs)
    got1, got2 = runs[1].scratch_out, runs[2].scratch_out
    if not (worst <= 1 and got1 != s_tb and got2 != got1 and
            runs[1].status == 0 and runs[2].status == 0):
        bad(f"{name}: textbook", f"the program's step is {float(worst):.3g} "
            f"x the rounding bound from the textbook {scheme}"
            if worst > 1 else "the state did not move, or the run's status "
            "is not 0")
        return
    ok(f"{name}: its first two steps from {n_tb} states are the textbook "
       f"{scheme} in exact rationals, within gamma_k a",
       f"worst {float(worst):.3g} of the bound, k up to {kmax}")
    alone = sorted(set(gen_odes.MUTANTS[base]) - set(_MIRROR_MUTANTS[base]))
    if alone:
        bad(f"{name}: textbook controls", f"gen_odes.MUTANTS names "
            f"{', '.join(alone)}, which ode_step cannot carry: a wrong "
            f"program against a right mirror, which the mirror arm refuses "
            f"too, shows nothing about this arm")
        return
    for mutant, what in gen_odes.MUTANTS[base].items():
        text = gen_odes.GENERATORS[base](fmtname, mutant=mutant)
        if text == src:
            bad(f"{name}: NEGATIVE CONTROL FAILED TO FAIL",
                f"gen_odes.py's {mutant} switch changed nothing")
            return
        mimg = asm.assemble_image(text, f"{name}-{mutant}")
        mvals = dict(gen_odes.bank_values(base, fmt, mutant=mutant))
        lost = [c for c in mimg.const_names if c not in mvals]
        if lost:
            bad(f"{name}: control {mutant}", f"its bank has no "
                                             f"{', '.join(lost)}")
            return
        mbank = [mvals[c] for c in mimg.const_names]
        try:
            mh, mP = _tb_params(base, fmt, mimg.const_names, mbank)
        except ValueError as exc:
            bad(f"{name}: control {mutant}", str(exc))
            return
        mruns = _tb_runs(mimg.to_bytes(), steps, mbank, s_tb, n_tb,
                         (1, 2))
        # Both halves inside: whatever computes them sees ode_step as a
        # mistake written into it would leave it.
        with _mirror_carrying(base, mutant):
            mirror = _mirror_out(base, fmt, mbank, s_tb, nstate, 2)
            r, _k = _tb_verdict(base, fmt, mP, mh, nstate, s_tb, mruns)
        if mirror != mruns[2].scratch_out:
            bad(f"{name}: control {mutant}", f"ode_step carrying {mutant} "
                f"is not bit for bit the program gen_odes.py writes with "
                f"it, so this control is not the shared error it claims "
                f"to be - make the two agree")
            return
        if not r > 1:
            bad(f"{name}: NEGATIVE CONTROL FAILED TO FAIL",
                f"{what}, in gen_odes.py and ode_step alike, is within "
                f"the textbook bound ({float(r):.3g} of it) - is the "
                f"textbook arm computing through the mirror?")
            return
        ok(f"{name}: NEGATIVE CONTROL - {what}, written by gen_odes.py AND "
           f"carried by ode_step: the mirror arm cannot tell it from the "
           f"program, the textbook arm refuses it", f"{float(r):.3g} x "
                                                   f"the bound")

    # -- scheme ----------------------------------------------------------------------
    if mpmath is None:
        # Two checks do not run - the claim and its control - and each is
        # named, one SKIP line apiece, which is what verify/run.sh counts
        # as an inner skip. (One line stood for both until 2026-09-25:
        # "6 inner skips" over 12 checks that had not run - verifier-V4.)
        for what in ("the 300-digit scheme", "the 300-digit scheme's "
                     "negative control (a weight or a kick changed)"):
            skip(f"{name}: {what}", "python has no mpmath module")
    else:
        mp = mpmath.mp
        saved = mp.dps
        mp.dps = 300
        try:
            def mpf_of(bits):
                fr = _frac(fmt, bits)
                return mpmath.mpf(fr.numerator) / fr.denominator
            Km = [mpf_of(b) for b in K]
            worst = worst_mut = mpmath.mpf(0)
            for i in range(n):
                s_mp = [mpf_of(b) for b in s_in[i * nstate:(i + 1) * nstate]]
                exact = ode_step(base, _MpOps, Km, s_mp, steps)
                wrong = ode_step(base, _MpOps, Km, s_mp, steps, detuned=True)
                got = [mpf_of(b) for b in lib[i * nstate:(i + 1) * nstate]]
                for g, e, w in zip(got, exact, wrong):
                    scale = max(abs(e), mpmath.mpf(1))
                    worst = max(worst, abs(g - e) / scale)
                    worst_mut = max(worst_mut, abs(g - w) / scale)
            ceiling = mpmath.mpf(steps) ** 2 * \
                mpmath.mpf(2) ** (-(fmt.prec - 1)) * 64
            good = 0 < worst < ceiling
            control = worst_mut > ceiling
        finally:
            mp.dps = saved
        if not good:
            bad(f"{name}: the 300-digit scheme",
                f"worst relative deviation {mpmath.nstr(worst, 4)}, ceiling "
                f"{mpmath.nstr(ceiling, 4)} (it must be above 0 and below)")
            return
        ok(f"{name}: within round-off of ode_step's scheme at 300 digits "
           f"over all {steps} steps", f"worst relative deviation "
           f"{mpmath.nstr(worst, 4)} against a {mpmath.nstr(ceiling, 3)} "
           f"ceiling (steps^2 2^-(p-1) x 64)")
        if not control:
            bad(f"{name}: NEGATIVE CONTROL FAILED TO FAIL",
                f"a wrong scheme is within the ceiling "
                f"({mpmath.nstr(worst_mut, 4)})")
            return
        ok(f"{name}: NEGATIVE CONTROL - the program against ode_step with "
           f"a weight or a kick changed exceeds the ceiling",
           f"{mpmath.nstr(worst_mut, 4)}")

    # -- resume -------------------------------------------------------------------------
    s0 = sip.read_bytes()
    lane = nstate * fmt.width // 8

    def segment(img_path, block, tag):
        """One segment of the image at img_path entered with `block` ->
        its scratch-out bytes, or None having recorded a failure. Every
        run this arm makes, claim and controls alike, is one of these."""
        bin_in = tmp / f"{name}.{tag}.in.bin"
        bin_out = tmp / f"{name}.{tag}.out.bin"
        bin_in.write_bytes(block)
        d, r = run_image(args, img_path, tmp, f"{name}-{tag}", a=ap,
                         bank=bp, scratch_in=bin_in, scratch_out=bin_out)
        if d is None:
            bad(f"{name}: resume, a segment ({tag})", r)
            return None
        return bin_out.read_bytes()

    def resumes(img_path, first, tag):
        """The claim's comparison for the image at img_path, whose first
        segment from the original state gave `first`: the SAME image with
        its REPEAT doubled, run once from the original state, against a
        second segment entered with `first` - every lane, every bit. ->
        (resumable, [lanes that differ]), or None having recorded a
        failure."""
        long_path = tmp / f"{name}.{tag}.long.cftp"
        long_path.write_bytes(_patch_trip(img_path.read_bytes(), steps,
                                          2 * steps, 0).to_bytes())
        one = segment(long_path, s0, f"{tag}-long")
        two = None if one is None else segment(img_path, first,
                                               f"{tag}-chained")
        if two is None:
            return None
        differ = [i for i in range(len(one) // lane)
                  if two[i * lane:(i + 1) * lane] !=
                  one[i * lane:(i + 1) * lane]]
        return (two == one and two != first, differ), one

    first = sop.read_bytes()
    got = resumes(image_path, first, "claim")
    if got is None:
        return
    (good, differ), one = got
    if not good:
        bad(f"{name}: resume", "two chained segments are not one segment of "
                               "twice the steps" +
            (f" (lanes {differ} differ)" if differ else ""))
        return
    ok(f"{name}: two segments chained through the scratch block ARE one "
       f"segment of {2 * steps} steps", f"{n} lanes, every bit")
    # The plumbing: once the claim has passed, a deterministic executor
    # entered with the ORIGINAL state gives back the first segment, which
    # the claim has just shown is not the long run - so this can fail to
    # fail only if segment() stops handing the image the block it was
    # given. (A one-ulp change to one carried slot is no control here: in
    # some lanes of four of the six rows it merges back bit for bit
    # before the segment ends - measured 2026-09-25, both executors.)
    orig = segment(image_path, s0, "original")
    if orig is None:
        return
    if orig == one:
        bad(f"{name}: NEGATIVE CONTROL FAILED TO FAIL", "the second segment "
            "entered with the original state still matched the long run")
        return
    ok(f"{name}: NEGATIVE CONTROL - the second segment entered with the "
       f"original state instead is not the long run")
    # A program that is right step by step and still cannot be resumed.
    # Its difference is small - measured 2026-09-25, one ulp in one
    # component, lane 5 of 8 at fp64 and lanes 0 and 4 of 8 at fp256 - so
    # the claim's comparison must read every lane, bit for bit. And it can
    # VANISH: with 4 lanes no lane differs at fp64, nor at either format
    # with 4 lanes and 150-step segments (verifier-V5's sweep), so a
    # change to _ODE_LANES, the steps or ode_initial can take it away, and
    # this control then goes red though the resume arm is sound - a false
    # alarm, loud. So when the resume arm's comparison does not refuse
    # it, the golden executor, asked the same question without segment()
    # or resumes(), tells the two apart: if its chained and long runs
    # differ, the comparison has gone blind; if they do not, the control
    # has lost its difference, and the message says that. The witness
    # chooses the message; the run is red either way.
    for mutant, what in gen_odes.UNRESUMABLE.get(base, {}).items():
        kimg = asm.assemble_image(gen_odes.GENERATORS[base](
            fmtname, mutant=mutant), f"{name}-{mutant}")
        if list(kimg.const_names) != names:
            bad(f"{name}: control {mutant}", f"it declares "
                f"{', '.join(kimg.const_names)}, not the row's bank")
            return
        kbytes = kimg.to_bytes()
        kw, _k = _tb_verdict(base, fmt, P, h, nstate, s_tb,
                             _tb_runs(kbytes, steps, K, s_tb, n_tb, (1, 2)))
        if not kw <= 1:
            bad(f"{name}: control {mutant}", f"the textbook arm refuses it "
                f"({float(kw):.3g} x the bound), so it cannot show what "
                f"only the resume arm sees")
            return
        kp = tmp / f"{name}-{mutant}.cftp"
        kp.write_bytes(kbytes)
        kfirst = segment(kp, s0, f"{mutant}-first")
        got = None if kfirst is None else resumes(kp, kfirst, mutant)
        if got is None:
            return
        (kgood, kdiffer), _one = got
        if kgood or not kdiffer:
            gl = _golden_unresumed(kbytes, K, s_in, n, nstate, steps)
            if gl:
                bad(f"{name}: NEGATIVE CONTROL FAILED TO FAIL",
                    f"{what}: the resume arm's comparison did not refuse "
                    f"it, yet the golden executor's chained and long runs "
                    f"differ in lane(s) {gl} of {n} - the comparison has "
                    f"gone blind")
            else:
                bad(f"{name}: control {mutant}",
                    f"{what}: its difference is gone - no lane of {n} "
                    f"differs, in the golden executor's runs either. This "
                    f"says nothing against the resume arm: the lanes, the "
                    f"{steps}-step segments or ode_initial's states it was "
                    f"measured at have changed; restore them, or find a "
                    f"setting where it differs and pin that")
            return
        ok(f"{name}: NEGATIVE CONTROL - {what}: the textbook arm passes it "
           f"({float(kw):.3g} of the bound) and the resume arm refuses it",
           f"lane(s) {kdiffer} of {n} differ")


# ================= main =================================================

def read_manifest(path):
    """-> ({image name: digest}, [problem]). A missing MANIFEST, one that
    lists nothing, a line that is not `sha256 name`, and a name listed
    twice are each a problem, by name - never a quieter run."""
    if not path.exists():
        return {}, [f"{path.name} is missing"]
    manifest, problems = {}, []
    for lineno, line in enumerate(path.read_text().splitlines(), 1):
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split()
        if len(parts) != 2 or len(parts[0]) != 64 or \
                parts[0].strip("0123456789abcdef"):
            problems.append(f"line {lineno} is not `sha256 image`")
        elif parts[1] in manifest:
            problems.append(f"{parts[1]} is listed twice (line {lineno})")
        else:
            manifest[parts[1]] = parts[0]
    if not manifest and not problems:
        problems.append("it lists no image")
    return manifest, problems


def manifest_gaps(manifest, stems):
    """-> (MANIFEST lines whose source is gone, sources with no line):
    `stems` are the .cfta sources' stems, `manifest` read_manifest's."""
    built = {s + ".cftp" for s in stems}
    return (sorted(set(manifest) - built),
            sorted(s for s in stems if s + ".cftp" not in manifest))


def check_manifest_complete(manifest, stems):
    """Every MANIFEST line has a source and every source a line. With
    lorenz96-rk4-fp256.cfta deleted this script once said 173 passed,
    and with every source deleted "2 passed ... 0 images", exit 0:
    nothing asked that a line still had its source. The controls take
    one source away from the same comparison, and then that source's
    line instead, and each must be named."""
    gone, unlisted = manifest_gaps(manifest, stems)
    for image_name in gone:
        bad(f"{image_name[:-len('.cftp')]}: MANIFEST",
            "a line for an image with no source - the row vanished, or "
            "the line is stale (`make programs` rewrites it)")
    for stem in unlisted:
        bad(f"{stem}: MANIFEST", "a source with no line")
    if gone or unlisted or not stems:
        return
    taken = "lorenz96-rk4-fp256" if "lorenz96-rk4-fp256" in stems \
        else stems[len(stems) // 2]
    gone2, unlisted2 = manifest_gaps(manifest,
                                     [s for s in stems if s != taken])
    if gone2 != [taken + ".cftp"] or unlisted2:
        bad("MANIFEST: NEGATIVE CONTROL FAILED TO FAIL",
            f"with {taken}.cfta taken away the comparison named {gone2} "
            f"and {unlisted2}")
        return
    gone3, unlisted3 = manifest_gaps(
        {k: v for k, v in manifest.items() if k != taken + ".cftp"}, stems)
    if unlisted3 != [taken] or gone3:
        bad("MANIFEST: NEGATIVE CONTROL FAILED TO FAIL",
            f"with {taken}'s line taken away the comparison named "
            f"{unlisted3} and {gone3}")
        return
    ok(f"MANIFEST: each of its {len(manifest)} lines has a source, and "
       f"each of the {len(stems)} sources a line")
    ok(f"MANIFEST: NEGATIVE CONTROL - {taken}.cfta taken away is named")
    ok(f"MANIFEST: NEGATIVE CONTROL - {taken}'s line taken away is named")


def check_manifest_refusals(tmp):
    """read_manifest's four refusals, each watched: the same reader over
    a MANIFEST that is missing, one of comments only, one with a line
    that is not `sha256 image`, and one naming an image twice must each
    be refused by name. (They had worked and been claimed "each with a
    control" on 2026-09-25 with none - verifier-V3.)"""
    line = "0" * 64 + " stray-fp64.cftp"
    for i, (what, text, want) in enumerate((
            ("a MANIFEST that is missing", None, "is missing"),
            ("a MANIFEST of comments only", "# nothing here\n\n",
             "it lists no image"),
            ("a line that is not `sha256 image`",
             line + "\n" + "0" * 63 + " short-fp64.cftp\n",
             "is not `sha256 image`"),
            ("an image listed twice", line + "\n" + line + "\n",
             "stray-fp64.cftp is listed twice"))):
        path = tmp / f"MANIFEST.control{i}"
        if text is not None:
            _write_lf(path, text)
        _listed, problems = read_manifest(path)
        if not any(want in p for p in problems):
            bad("MANIFEST: NEGATIVE CONTROL FAILED TO FAIL",
                f"{what} was not refused by name ({problems})")
            return
        ok(f"MANIFEST: NEGATIVE CONTROL - {what} is refused",
           "; ".join(problems))


def _gen_odes_check(where=None):
    """gen_odes.main(["--check"]) in this process -> (exit code, its
    lines). `where` points it at a copy of its files - the control's
    only use - and gen_odes.HERE is put back whatever happens."""
    saved = gen_odes.HERE
    buf = io.StringIO()
    try:
        if where is not None:
            gen_odes.HERE = Path(where)
        with contextlib.redirect_stdout(buf):
            rc = gen_odes.main(["--check"])
    finally:
        gen_odes.HERE = saved
    return rc, buf.getvalue().splitlines()


def check_gen_odes(tmp):
    """gen_odes.py's own --check: every file it owns exists and is its
    output byte for byte. Nothing ran it before 2026-09-25, so a missing
    or CRLF generated file passed. Control: the same check over a copy
    of its files with one deleted and one given CRLF line ends must name
    both."""
    rc, lines = _gen_odes_check()
    if rc != 0:
        bad("gen_odes.py --check", "; ".join(lines))
        return
    ok("gen_odes.py --check", lines[-1] if lines else "")
    copy = tmp / "gen_odes-control"
    copy.mkdir()
    for fname in gen_odes.outputs():
        shutil.copyfile(HERE / fname, copy / fname)
    gone, crlf = "lorenz96-rk4-fp256.cfta", "henonheiles-lf-fp64.cfta"
    (copy / gone).unlink()
    (copy / crlf).write_bytes(
        (copy / crlf).read_bytes().replace(b"\n", b"\r\n"))
    rc2, lines2 = _gen_odes_check(copy)
    named = (any(gone in s and "missing" in s for s in lines2) and
             any(crlf in s and "differs" in s for s in lines2))
    if rc2 == 0 or not named:
        bad("gen_odes.py --check: NEGATIVE CONTROL FAILED TO FAIL",
            f"exit {rc2}: {'; '.join(lines2)}")
        return
    ok(f"gen_odes.py --check: NEGATIVE CONTROL - {gone} deleted and {crlf} "
       f"with CRLF line ends are both named", lines2[-1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asm", required=True)
    ap.add_argument("--runner", required=True)
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--tools-dir", default=str(ROOT / "host"))
    args = ap.parse_args()
    # Absolute, because Windows CreateProcess will not resolve a
    # relative path written with forward slashes even when the file is
    # plainly there - a half hour of "the system cannot find the file
    # specified" beside an os.path.exists that says True.
    args.asm = str(Path(args.asm).resolve())
    args.runner = str(Path(args.runner).resolve())
    args.tools_dir = str(Path(args.tools_dir).resolve())

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="cft-programs-"))
    caps = runner_caps(args)
    print(f"runner: bank-path {caps.get('bank-path', '?')}, "
          f"digest {caps.get('digest', '?')}, "
          f"kx9 {caps.get('kx9', '?')}, "
          f"scratch {caps.get('scratch', '?')}, "
          f"scratch-io {caps.get('scratch-io', '?')}, "
          f"run-path {caps.get('run-path', '?')}")

    manifest, problems = read_manifest(HERE / "MANIFEST")
    for problem in problems:
        bad("MANIFEST", problem)

    print("\n-- the two assemblers, and the readback --")
    images = {}
    sources = sorted(HERE.glob("*.cfta"))
    for src in sources:
        image_path = out / (src.stem + ".cftp")
        image = assemble_both(args, src, image_path)
        if image is None:
            continue
        images[src.stem] = (image, image_path)
        digest = hashlib.sha256(image).hexdigest()
        want = manifest.get(image_path.name)
        if want is None:
            pass                # named once, by check_manifest_complete
        elif want != digest:
            bad(f"{src.stem}: MANIFEST",
                f"{digest[:16]} vs the recorded {want[:16]} - run "
                f"`make programs`")
        else:
            ok(f"{src.stem}: cft-asm == asm.py == MANIFEST",
               f"{len(image)} bytes, {digest[:16]}")
        roundtrip(args, src.stem, image, tmp)

    print("\n-- the MANIFEST against the sources, and gen_odes.py's own "
          "check --")
    check_manifest_complete(manifest, [s.stem for s in sources])
    check_manifest_refusals(tmp)
    check_gen_odes(tmp)

    print("\n-- the ODE rows' textbook arm, held apart from the mirror, the "
          "generator and the executors --")
    check_textbook_independence()

    print("\n-- the revision-2 corpus, in both languages --")
    check_revision2_corpus(args, tmp)

    print("\n-- the revision-3 corpus, in both languages --")
    check_revision3_corpus(args, tmp)

    print("\n-- each program's own check --")
    # spill-ref-fp64 is the reference spill-fp64 is compared against, so
    # it runs first whatever the alphabet says.
    order = sorted(images)
    if "spill-ref-fp64" in order:
        order.remove("spill-ref-fp64")
        order.insert(0, "spill-ref-fp64")
    ref_deposits = None
    for name in order:
        image, image_path = images[name]
        if name.startswith("div-") or name.startswith("sqrt-"):
            check_divsqrt(name, image)
            check_divsqrt_runs(args, name, image_path, tmp)
        elif name.startswith("divfull-") or name.startswith("sqrtfull-"):
            check_full(name, image)
            check_full_runs(args, name, image_path, tmp)
        elif name.startswith("normalabs-"):
            check_normalabs(args, name, image, image_path, tmp)
        elif name == "collatz-fp256":
            check_collatz(args, name, image, image_path, tmp)
        elif name == "zoom-scan-fp256":
            check_zoom_scan(args, name, image, image_path, tmp)
        elif name == "lowbias32-fp32":
            check_lowbias32(args, name, image, image_path, tmp)
        elif name == "horner-bank-fp64":
            check_horner_bank(args, name, image, image_path, tmp, caps)
        elif name == "spill-ref-fp64":
            ref_deposits = check_spill_ref(args, name, image, image_path,
                                           tmp)
        elif name == "spill-fp64":
            check_spill(args, name, image, image_path, tmp, caps,
                        ref_deposits)
        elif name == "conv-fp64":
            check_conv(args, name, image, image_path, tmp, caps)
        elif name == "resume-fp64":
            check_resume(args, name, image, image_path, tmp, caps)
        elif name == "horner-wide-fp64":
            check_horner_wide(args, name, image, image_path, tmp, caps)
        elif _ode_base(name)[0]:
            check_ode(args, name, image, image_path, tmp)
        else:
            skip(f"{name}: own check", "no row in programs/README.md")

    shutil.rmtree(tmp, ignore_errors=True)
    dt = time.time() - T0
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed, {len(SKIP)} skipped, "
          f"{len(images)} images, in {dt:.1f}s")
    if SKIP:
        print("skipped:")
        for s in SKIP:
            print(f"  {s}")
    if FAIL:
        print("FAILED:")
        for f in FAIL:
            print(f"  {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
