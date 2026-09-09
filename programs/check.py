# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Every check the library's index promises.

`make programs-check` at the repo root is this script. It does three
things, in this order, and stops at the first failure:

1. **Two assemblers, one image.** Every `.cfta` is assembled with
   `host/tools/cft-asm` and again with `python/cft_golden/asm.py`, and
   the bytes must be identical - then compared against the MANIFEST,
   so a rebuild that moved a byte is caught here and not in a diff
   nobody read.

2. **The disassembler is a readback.** Every built image is
   disassembled by both implementations, the two texts must agree, and
   re-assembling either must return the same bytes. A readback that
   cannot be re-assembled is not an attestation.

3. **Each row's own check**, which is what earns a program its place
   in programs/README.md: byte equality with the model's generator for
   the composed div and sqrt, the tool's own records for the Collatz
   kernel, the golden model's executor for the escape map, the hash's
   definition for the draw stream, a model computation with two
   different banks for the BANK_EXT worked example, and - for
   revision 3's four scratch rows - the same arithmetic without the
   spill, a softfloat convolution, a longer run's second half, and a
   softfloat Horner over three hundred coefficients.

Revision 3's rows have two arms and they are not the same claim. The
STATIC arm - constants against their derivation, the header against
what the source declares, the encoding against the contract - runs
today. The EXECUTION arm needs a libcft that knows the four control
codes, the header's `scratch_io` word and the ninth constant-index
bit, and those arrive with the model and host halves of the same
round; until then it says SKIP and WHICH feature it waited on, asking
`positive-run --capabilities` rather than inferring it from a failure.

A check that cannot run says SKIP and why, and the script still fails
if anything actually disagrees. Nothing here reports a pass it did not
perform.
"""

import argparse
import hashlib
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "python"))

from cft_golden import FORMATS, asm, chars, seq, seqprogs   # noqa: E402
from cft_golden import softfloat as sf                      # noqa: E402

PASS, FAIL, SKIP = [], [], []
T0 = time.time()


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
    src.write_text(pytext, encoding="utf-8", newline="\n")
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
#   arrive with the model and host halves of the same round. Until then
#   the arm says SKIP and WHICH feature it waited on, by name, and
#   `positive-run --capabilities` is what it asks rather than inferring
#   it from a failure. This is exactly what last round did for the
#   BANK_EXT path.


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
        src.write_text(text, encoding="utf-8", newline="\n")
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
        src.write_text(text, encoding="utf-8", newline="\n")
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


# ================= main =================================================

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

    manifest = {}
    mpath = HERE / "MANIFEST"
    if mpath.exists():
        for line in mpath.read_text().splitlines():
            if line.startswith("#") or not line.strip():
                continue
            digest, image_name = line.split()
            manifest[image_name] = digest

    print("\n-- the two assemblers, and the readback --")
    images = {}
    for src in sorted(HERE.glob("*.cfta")):
        image_path = out / (src.stem + ".cftp")
        image = assemble_both(args, src, image_path)
        if image is None:
            continue
        images[src.stem] = (image, image_path)
        digest = hashlib.sha256(image).hexdigest()
        want = manifest.get(image_path.name)
        if want is None:
            bad(f"{src.stem}: MANIFEST", "no line for this image")
        elif want != digest:
            bad(f"{src.stem}: MANIFEST",
                f"{digest[:16]} vs the recorded {want[:16]} - run "
                f"`make programs`")
        else:
            ok(f"{src.stem}: cft-asm == asm.py == MANIFEST",
               f"{len(image)} bytes, {digest[:16]}")
        roundtrip(args, src.stem, image, tmp)

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
