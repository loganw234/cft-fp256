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
   definition for the draw stream, and a model computation with two
   different banks for the BANK_EXT worked example.

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
              c=None, bank=None):
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

    banks = {"exp": bank_exp(), "ramp": bank_ramp()}
    spliced_out = {}
    for tag, coeffs in banks.items():
        bpath = HERE / f"{name}.{tag}.bank"
        bpath.write_bytes(pack(coeffs, fmt))

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
          f"digest {caps.get('digest', '?')}")

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

    print("\n-- each program's own check --")
    for name, (image, image_path) in sorted(images.items()):
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
