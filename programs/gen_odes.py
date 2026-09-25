# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The library's ODE programs, written out as `.cfta` text.

    python programs/gen_odes.py            write every source and bank below
    python programs/gen_odes.py --check    regenerate in memory, compare byte
                                           for byte with the committed files

Three dynamical systems, the first references for an equations-in,
ensemble-out solver (docs/VALIDATION.md, 2026-09-25): each is the program
a compiler for that service would be expected to emit, written out once
by hand-in-a-loop so that what such programs cost - instructions,
registers, scratch slots, control codes - is measured before anything is
built to emit them.

  lorenz63-rk4-<fmt>     Lorenz (1963), sigma 10, rho 28, beta 8/3 by
                         default, the classic fourth-order Runge-Kutta
                         step; three state values, all of it in
                         registers for the whole segment
  lorenz96-rk4-<fmt>     Lorenz (1996) with N = 40 and forcing F = 8 by
                         default, the same Runge-Kutta step; forty state
                         values, which do not fit thirty-two registers,
                         so every stage vector lives in the per-lane
                         scratch and a four-register window slides round
                         the ring
  henonheiles-lf-<fmt>   Henon-Heiles (1964), Stormer-Verlet in its
                         drift-kick-drift form; four state values in
                         registers

Each is a SEGMENT in docs/ORBITS.md's sense. The state enters through the
per-lane scratch block and leaves it (`.scratch in` / `.scratch out`,
docs/SEQUENCER.md R5), the step and the parameters arrive as the run's
bank (`.bank external`, R3), nothing is deposited, and the image is a
pure schedule of `STEPS` steps: one lane is one ensemble member, and a
member that shifts a PARAMETER rather than a state would need that
parameter in its scratch rather than in the bank, which is shared by
the run.

The instruction stream IS each program's definition - the order of every
rounding is fixed here and nowhere else - so programs/check.py holds the
committed `.cfta` to this file byte for byte. It holds the arithmetic
two ways. Bit for bit against a mirror of this rounding order written
again in check.py: that mirror is NOT independent of this file - an
error made in both places passes it. And against the textbook scheme in
exact rationals, which shares no transcription with this file, one step
at a time within a rounding bound derived from the precision; MUTANTS
below are that comparison's negative controls, each carried by the
mirror too, so that each is an error made in both places. UNRESUMABLE
is the resume check's: a program right at every step that still cannot
be resumed.

The default banks are data (`<name>.classic.bank`): raw format-width
values, dense, in the order the source declares them. check.py holds
the value in each slot to the derivation of the NAME the source gives
that slot, from exact decimals.
"""

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "python"))

from cft_golden import FORMATS, chars                  # noqa: E402
from cft_golden import softfloat as sf                 # noqa: E402

FORMATS_BUILT = ("fp64", "fp256")

# Steps a segment. A run of any other length is the same image with its
# one REPEAT's trip count changed, which is how check.py builds them.
STEPS = {"lorenz63-rk4": 100, "lorenz96-rk4": 20, "henonheiles-lf": 100}

L96_N = 40          # Lorenz-96's ring


# ---- test-only mutants ----------------------------------------------------
#
# Wrong programs, written by the SAME generators below: programs/check.py
# asks for each one, assembles it, runs it and requires its textbook arm to
# FAIL on it - that arm's permanent negative controls, which make "the
# check can tell this program from a wrong one" something the gate shows
# every run rather than something once believed. check.py's mirror of the
# rounding order (ode_step) carries each of the same mistakes behind a
# switch of its own, so every one of these is a SHARED error, the shape
# that once passed the whole gate: the check requires the mirror arm to
# pass it bit for bit - proof that the error really is shared - and the
# textbook arm to refuse it. None is on by default; outputs() and --check
# never ask for one, so no committed file can be a mutant; and a name not
# listed here is refused rather than ignored, since an ignored name would
# hand back the real program and a control that cannot fail.
MUTANTS = {
    "lorenz63-rk4": {
        "zsign": "z' = x y + beta z",
        "stage4-half": "stage 4 at Y + h/2 k3",
        "rk38": "the 3/8-rule Runge-Kutta",
    },
    "lorenz96-rk4": {
        "index": "x_(i+1) where x_(i-1) belongs",
        "stage4-half": "stage 4 at Y + h/2 k3",
        "rk38": "the 3/8-rule Runge-Kutta",
    },
    "henonheiles-lf": {
        "xforce-sign": "the x force with its sign flipped",
        "kdk": "kick-drift-kick in place of drift-kick-drift",
    },
}

# A program that is RIGHT step by step and still cannot be resumed: it
# carries state from one step to the next in a register the scratch block
# does not carry, so a second segment starts that state afresh where one
# longer segment would have kept it. A compiler that compensates its sums
# emits exactly this. The textbook arm passes it - every step is Stormer-
# Verlet within the rounding bound - and only the resume arm can refuse
# it, which check.py requires every run: that arm's control that is not
# decided by construction (verifier-V3, 2026-09-25). Same rules as
# MUTANTS: never on by default, never written to disk, unknown names
# refused.
UNRESUMABLE = {
    "henonheiles-lf": {
        "kahan": "the px kick Kahan-compensated, its compensation carried "
                 "from step to step in a register the scratch block does "
                 "not carry",
    },
}


def _mutant(name, mutant):
    known = {**MUTANTS.get(name, {}), **UNRESUMABLE.get(name, {})}
    if mutant is not None and mutant not in known:
        raise ValueError(f"{name} has no test mutant {mutant!r}; it has "
                         f"{', '.join(known)}")
    return mutant


def _mutant_note(name, mutant):
    """The mutant's own first comment lines; none for the real program."""
    if mutant is None:
        return []
    known = {**MUTANTS.get(name, {}), **UNRESUMABLE.get(name, {})}
    return [f"TEST-ONLY MUTANT {mutant}: {known[mutant]}. A negative",
            "control for programs/check.py - never written to disk.", ""]


# ---- the banks, from exact decimals --------------------------------------

def _dec(fmt, text):
    bits, _ = chars.from_decimal(fmt, text, sf.RND_RNE)
    return bits


def bank_values(name, fmt, mutant=None):
    """[(constant name, bits)] in declaration order - the default bank, or
    the one a test-only mutant declares (only rk38 declares another)."""
    _mutant(name, mutant)
    h = _dec(fmt, "0.01")
    if mutant == "rk38":
        h3, _ = sf.div(fmt, h, _dec(fmt, "3"))    # one rounding
        mh3, _ = sf.neg(fmt, h3)
        mh, _ = sf.neg(fmt, h)
        h8, _ = sf.mul(fmt, h, _dec(fmt, "0.125"))    # exact
        rk = [("H", h), ("H3", h3), ("MH3", mh3), ("MH", mh), ("H8", h8),
              ("THREE", _dec(fmt, "3"))]
        if name == "lorenz63-rk4":
            beta, _ = sf.div(fmt, _dec(fmt, "8"), _dec(fmt, "3"))
            return rk + [("SIGMA", _dec(fmt, "10")), ("RHO", _dec(fmt, "28")),
                         ("BETA", beta)]
        return rk + [("F", _dec(fmt, "8"))]
    two = _dec(fmt, "2")
    h2, _ = sf.mul(fmt, h, _dec(fmt, "0.5"))      # exact: a power of two
    six = _dec(fmt, "6")
    h6, _ = sf.div(fmt, h, six)                   # one rounding
    if name == "lorenz63-rk4":
        beta, _ = sf.div(fmt, _dec(fmt, "8"), _dec(fmt, "3"))
        return [("H", h), ("H2", h2), ("H6", h6), ("TWO", two),
                ("SIGMA", _dec(fmt, "10")), ("RHO", _dec(fmt, "28")),
                ("BETA", beta)]
    if name == "lorenz96-rk4":
        return [("H", h), ("H2", h2), ("H6", h6), ("TWO", two),
                ("F", _dec(fmt, "8"))]
    if name == "henonheiles-lf":
        mh, _ = sf.neg(fmt, h)
        return [("H", h), ("H2", h2), ("MH", mh), ("ONE", _dec(fmt, "1")),
                ("TWO", two)]
    raise KeyError(name)


def bank_bytes(name, fmt):
    esz = fmt.width // 8
    return b"".join(v.to_bytes(esz, "little") for _n, v in
                    bank_values(name, fmt))


# ---- the sources ----------------------------------------------------------

class _Src:
    def __init__(self):
        self.lines = []

    def __call__(self, text=""):
        self.lines.append(text)

    def text(self):
        return "\n".join(self.lines) + "\n"


def _header(S, name, fmtname, nstate, consts, what):
    S(f"; {name}-{fmtname} - generated by programs/gen_odes.py; edit that,")
    S("; not this file (programs/check.py compares the two byte for byte).")
    S(";")
    for line in what:
        S(f"; {line}" if line else ";")
    S("")
    S(f".format   {fmtname}")
    S(".deposits 0")
    S(".bank     external")
    S(f".scratch  in {nstate}")
    S(f".scratch  out {nstate}")
    S("")
    for cname, comment in consts:
        S(f".const    {cname:<6}   ; {comment}")
    S("")


def lorenz63(fmtname, mutant=None):
    _mutant("lorenz63-rk4", mutant)
    rk38 = mutant == "rk38"
    S = _Src()
    _header(S, "lorenz63-rk4", fmtname, 3, [
        ("H", "the step h"),
        ("H3", "h / 3, one rounding"),
        ("MH3", "-(h / 3)"),
        ("MH", "-h, exact"),
        ("H8", "h / 8, exact"),
        ("THREE", "3"),
        ("SIGMA", "sigma"),
        ("RHO", "rho"),
        ("BETA", "beta"),
    ] if rk38 else [
        ("H", "the step h"),
        ("H2", "h / 2, exact"),
        ("H6", "h / 6, one rounding"),
        ("TWO", "2"),
        ("SIGMA", "sigma"),
        ("RHO", "rho"),
        ("BETA", "beta"),
    ], _mutant_note("lorenz63-rk4", mutant) + [
        "Lorenz (1963):  x' = sigma (y - x),  y' = x (rho - z) - y,",
        "                z' = x y - beta z,",
        "stepped by the classic fourth-order Runge-Kutta scheme,",
        "",
        "    k1 = f(Y)            k2 = f(Y + h/2 k1)",
        "    k3 = f(Y + h/2 k2)   k4 = f(Y + h k3)",
        "    Y <- Y + h/6 (((k1 + 2 k2) + 2 k3) + k4)",
        "",
        "with the weighted sum formed as that bracketing says, one rounding",
        "an operation. The right-hand side is eight operations, in the order",
        "below; negation is exact, so each FMA rounds once.",
        "",
        "Scratch slots 0..2 carry x, y, z in and out. The state stays in",
        "registers for the whole segment: a step is 53 ALU instructions and",
        "no control code but the loop's own ENDREP.",
    ])
    regs = [("x", 3), ("y", 4), ("z", 5), ("px", 6), ("py", 7), ("pz", 8),
            ("ax", 9), ("ay", 10), ("az", 11), ("bx", 12), ("by", 13),
            ("bz", 14), ("cx", 15), ("cy", 16), ("cz", 17), ("t0", 18),
            ("t1", 19)]
    if rk38:
        regs += [("dx", 20), ("dy", 21), ("dz", 22)]
    S("; x y z: the state   px py pz: a stage's input   ax ay az: k1")
    S("; bx by bz: k2, k3, k4 in turn   cx cy cz: the weighted sum")
    if rk38:
        S("; dx dy dz: Y + h k1 - h k2")
    for r, n in regs:
        S(f".reg      {r:<3} = r{n}")
    S("")
    zc = "t0" if mutant == "zsign" else "t1"

    def f(X, Y, Z, KX, KY, KZ):
        S(f"  sub  t0, {Y}, {X}          ; y - x")
        S(f"  mul  {KX}, SIGMA, t0       ; sigma (y - x)")
        S(f"  sub  t0, RHO, {Z}         ; rho - z")
        S(f"  neg  t1, {Y}")
        S(f"  fma  {KY}, {X}, t0, t1      ; x (rho - z) - y")
        S(f"  mul  t0, BETA, {Z}        ; beta z")
        S("  neg  t1, t0")
        S(f"  fma  {KZ}, {X}, {Y}, {zc}      ; x y - beta z")

    for i, r in enumerate(("x", "y", "z")):
        S(f"ldl  {r}, {i}")
    S(f"repeat {STEPS['lorenz63-rk4']}")
    if rk38:
        # k1 = f(Y), k2 = f(Y + h/3 k1), k3 = f(Y - h/3 k1 + h k2),
        # k4 = f(Y + h k1 - h k2 + h k3), Y + h/8 (k1 + 3 k2 + 3 k3 + k4)
        S("  ; stage 1")
        f("x", "y", "z", "ax", "ay", "az")
        for c in "xyz":
            S(f"  fma  p{c}, H3, a{c}, {c}")
        S("  ; stage 2")
        f("px", "py", "pz", "bx", "by", "bz")
        for c in "xyz":
            S(f"  fma  c{c}, THREE, b{c}, a{c}")
        for c in "xyz":
            S(f"  fma  d{c}, H, a{c}, {c}")
        for c in "xyz":
            S(f"  fma  d{c}, MH, b{c}, d{c}")
        for c in "xyz":
            S(f"  fma  p{c}, MH3, a{c}, {c}")
        for c in "xyz":
            S(f"  fma  p{c}, H, b{c}, p{c}")
        S("  ; stage 3")
        f("px", "py", "pz", "bx", "by", "bz")
        for c in "xyz":
            S(f"  fma  c{c}, THREE, b{c}, c{c}")
        for c in "xyz":
            S(f"  fma  p{c}, H, b{c}, d{c}")
        S("  ; stage 4")
        f("px", "py", "pz", "bx", "by", "bz")
        for c in "xyz":
            S(f"  add  c{c}, c{c}, b{c}")
        for c in "xyz":
            S(f"  fma  {c}, H8, c{c}, {c}")
        S("endrep")
        for i, r in enumerate(("x", "y", "z")):
            S(f"stl  {r}, {i}")
        S("halt")
        return S.text()
    h4 = "H2" if mutant == "stage4-half" else "H"
    S("  ; stage 1")
    f("x", "y", "z", "ax", "ay", "az")
    for c in "xyz":
        S(f"  fma  p{c}, H2, a{c}, {c}")
    S("  ; stage 2")
    f("px", "py", "pz", "bx", "by", "bz")
    for c in "xyz":
        S(f"  fma  c{c}, TWO, b{c}, a{c}       ; k1 + 2 k2")
    for c in "xyz":
        S(f"  fma  p{c}, H2, b{c}, {c}")
    S("  ; stage 3")
    f("px", "py", "pz", "bx", "by", "bz")
    for c in "xyz":
        S(f"  fma  c{c}, TWO, b{c}, c{c}       ; + 2 k3")
    for c in "xyz":
        S(f"  fma  p{c}, {h4}, b{c}, {c}")
    S("  ; stage 4")
    f("px", "py", "pz", "bx", "by", "bz")
    for c in "xyz":
        S(f"  add  c{c}, c{c}, b{c}           ; + k4")
    for c in "xyz":
        S(f"  fma  {c}, H6, c{c}, {c}")
    S("endrep")
    for i, r in enumerate(("x", "y", "z")):
        S(f"stl  {r}, {i}")
    S("halt")
    return S.text()


# Lorenz-96's scratch layout: five stage vectors of N.
L96_Y, L96_TA, L96_TB, L96_K1, L96_ACC = (0, L96_N, 2 * L96_N, 3 * L96_N,
                                          4 * L96_N)
L96_TC = 5 * L96_N      # the rk38 mutant's sixth: Y + h k1 - h k2


def _l96_rk38(S, s, i, w):
    """Component i's share of stage s under the 3/8 rule (the rk38
    mutant): k1 = f(Y), k2 = f(Y + h/3 k1), k3 = f(Y - h/3 k1 + h k2),
    k4 = f(Y + h k1 - h k2 + h k3), Y + h/8 (k1 + 3 k2 + 3 k3 + k4)."""
    if s == 1:
        S(f"  stl  k, {L96_K1 + i}")
        S(f"  fma  t0, H3, k, {w(i)}")
        S(f"  stl  t0, {L96_TB + i}")
    elif s == 2:
        S(f"  ldl  y, {L96_Y + i}")
        S(f"  ldl  a, {L96_K1 + i}")
        S("  fma  t0, MH3, a, y")
        S("  fma  t0, H, k, t0")
        S(f"  stl  t0, {L96_TA + i}")
        S("  fma  t1, H, a, y")
        S("  fma  t1, MH, k, t1")
        S(f"  stl  t1, {L96_TC + i}")
        S("  fma  a, THREE, k, a")
        S(f"  stl  a, {L96_ACC + i}")
    elif s == 3:
        S(f"  ldl  t0, {L96_TC + i}")
        S("  fma  t0, H, k, t0")
        S(f"  stl  t0, {L96_TB + i}")
        S(f"  ldl  a, {L96_ACC + i}")
        S("  fma  a, THREE, k, a")
        S(f"  stl  a, {L96_ACC + i}")
    else:
        S(f"  ldl  a, {L96_ACC + i}")
        S("  add  a, a, k")
        S(f"  ldl  y, {L96_Y + i}")
        S("  fma  y, H8, a, y")
        S(f"  stl  y, {L96_Y + i}")


def lorenz96(fmtname, mutant=None):
    _mutant("lorenz96-rk4", mutant)
    rk38 = mutant == "rk38"
    N = L96_N
    S = _Src()
    _header(S, "lorenz96-rk4", fmtname, N, [
        ("H", "the step h"),
        ("H3", "h / 3, one rounding"),
        ("MH3", "-(h / 3)"),
        ("MH", "-h, exact"),
        ("H8", "h / 8, exact"),
        ("THREE", "3"),
        ("F", "the forcing"),
    ] if rk38 else [
        ("H", "the step h"),
        ("H2", "h / 2, exact"),
        ("H6", "h / 6, one rounding"),
        ("TWO", "2"),
        ("F", "the forcing"),
    ], _mutant_note("lorenz96-rk4", mutant) + [
        f"Lorenz (1996) on a ring of N = {N}:",
        "",
        "    x_i' = (x_(i+1) - x_(i-2)) x_(i-1) - x_i + F,  indices mod N,",
        "",
        "evaluated as  fma(x_(i+1) - x_(i-2), x_(i-1), F - x_i): two SUBs",
        "and one FMA a component. Stepped by the same Runge-Kutta scheme as",
        "lorenz63-rk4, component by component in index order.",
        "",
        f"Forty values do not fit thirty-two registers, so every stage",
        f"vector lives in the scratch: Y at {L96_Y}..{L96_Y + N - 1} (the",
        f"state, carried in and out), TA at {L96_TA}.. and TB at {L96_TB}..",
        f"(the stage inputs, alternating), K1 at {L96_K1}.. and the weighted",
        f"sum at {L96_ACC}.. - {5 * N} slots. A four-register window slides",
        "round the ring, so each component loads one new value; the other",
        "loads and stores are the stage vectors'. A step is 760 ALU",
        "instructions, 692 scratch accesses and the loop's ENDREP: this is",
        "the program the scratch's cost is measured on.",
    ])
    S("; w0..w3: the window, x_(i-2) .. x_(i+1) rotating through the four")
    S("; t0, t1: temporaries   k: the component's f   y: Y_i   a: k1 or the sum")
    for r, n in (("w0", 3), ("w1", 4), ("w2", 5), ("w3", 6), ("t0", 7),
                 ("t1", 8), ("k", 9), ("y", 10), ("a", 11)):
        S(f".reg      {r:<3} = r{n}")
    S("")
    W = ("w0", "w1", "w2", "w3")

    def w(j):
        return W[j % 4]

    stages = ((1, L96_Y), (2, L96_TB), (3, L96_TA), (4, L96_TB))
    S(f"repeat {STEPS['lorenz96-rk4']}")
    for s, IN in stages:
        S(f"  ; stage {s}, reading the stage input at {IN}")
        S(f"  ldl  {w(-2)}, {IN + N - 2}")
        S(f"  ldl  {w(-1)}, {IN + N - 1}")
        S(f"  ldl  {w(0)}, {IN + 0}")
        S(f"  ldl  {w(1)}, {IN + 1}")
        for i in range(N):
            S(f"  sub  t0, {w(i + 1)}, {w(i - 2)}")
            S(f"  sub  t1, F, {w(i)}")
            S(f"  fma  k, t0, {w(i + 1) if mutant == 'index' else w(i - 1)}"
              f", t1")
            if rk38:
                _l96_rk38(S, s, i, w)
            elif s == 1:
                S(f"  stl  k, {L96_K1 + i}")
                S(f"  fma  t0, H2, k, {w(i)}")
                S(f"  stl  t0, {L96_TB + i}")
            elif s == 2:
                S(f"  ldl  y, {L96_Y + i}")
                S("  fma  t0, H2, k, y")
                S(f"  stl  t0, {L96_TA + i}")
                S(f"  ldl  a, {L96_K1 + i}")
                S("  fma  a, TWO, k, a")
                S(f"  stl  a, {L96_ACC + i}")
            elif s == 3:
                S(f"  ldl  y, {L96_Y + i}")
                S(f"  fma  t0, {'H2' if mutant == 'stage4-half' else 'H'}, "
                  f"k, y")
                S(f"  stl  t0, {L96_TB + i}")
                S(f"  ldl  a, {L96_ACC + i}")
                S("  fma  a, TWO, k, a")
                S(f"  stl  a, {L96_ACC + i}")
            else:
                S(f"  ldl  a, {L96_ACC + i}")
                S("  add  a, a, k")
                S(f"  ldl  y, {L96_Y + i}")
                S("  fma  y, H6, a, y")
                S(f"  stl  y, {L96_Y + i}")
            if i + 2 <= N:
                S(f"  ldl  {w(i + 2)}, {IN + (i + 2) % N}")
    S("endrep")
    S("halt")
    return S.text()


def henonheiles(fmtname, mutant=None):
    _mutant("henonheiles-lf", mutant)
    S = _Src()
    _header(S, "henonheiles-lf", fmtname, 4, [
        ("H", "the step h"),
        ("H2", "h / 2, exact"),
        ("MH", "-h, exact"),
        ("ONE", "1"),
        ("TWO", "2"),
    ], _mutant_note("henonheiles-lf", mutant) + [
        "Henon-Heiles (1964):  H = (px^2 + py^2)/2 + (x^2 + y^2)/2",
        "                          + x^2 y - y^3/3,",
        "",
        "    px' = -x (1 + 2 y),   py' = y (y - 1) - x^2,",
        "",
        "stepped by Stormer-Verlet, drift-kick-drift: q += h/2 p; p += h",
        "a(q); q += h/2 p. Scratch slots 0..3 carry x, y, px, py in and out;",
        "the state stays in registers, and a step is 12 ALU instructions.",
    ])
    kahan = mutant == "kahan"
    for r, n in (("x", 3), ("y", 4), ("px", 5), ("py", 6), ("t0", 7),
                 ("t1", 8), ("t2", 9)) + ((("e", 10),) if kahan else ()):
        S(f".reg      {r:<3} = r{n}")
    S("")
    for i, r in enumerate(("x", "y", "px", "py")):
        S(f"ldl  {r}, {i}")
    S(f"repeat {STEPS['henonheiles-lf']}")
    if kahan:
        # e is minus the rounding error the last px sum lost. A register
        # starts every run at +0 (docs/SEQUENCER.md), so e starts afresh
        # with each segment - and nothing else in the step differs.
        S("  fma  x, H2, px, x         ; drift")
        S("  fma  y, H2, py, y")
        S("  fma  t0, TWO, y, ONE      ; 1 + 2 y")
        S("  mul  t0, x, t0            ; x (1 + 2 y)")
        S("  fma  t1, MH, t0, e        ; the kick, compensated")
        S("  add  t2, px, t1")
        S("  sub  e, px, t2            ; what the sum lost, negated,")
        S("  add  e, e, t1             ; carried to the next step")
        S("  mul  px, t2, ONE          ; px = the sum, exactly")
        S("  mul  t1, x, x             ; x^2")
        S("  neg  t1, t1")
        S("  sub  t2, y, ONE           ; y - 1")
        S("  fma  t2, y, t2, t1        ; y (y - 1) - x^2")
        S("  fma  py, H, t2, py        ; kick: py + h (...)")
        S("  fma  x, H2, px, x         ; drift")
        S("  fma  y, H2, py, y")
        S("endrep")
        for i, r in enumerate(("x", "y", "px", "py")):
            S(f"stl  {r}, {i}")
        S("halt")
        return S.text()
    if mutant == "kdk":
        def half_kick():
            S("  fma  t0, TWO, y, ONE")
            S("  mul  t0, x, t0")
            S("  neg  t0, t0")
            S("  fma  px, H2, t0, px")
            S("  mul  t1, x, x")
            S("  neg  t1, t1")
            S("  sub  t2, y, ONE")
            S("  fma  t2, y, t2, t1")
            S("  fma  py, H2, t2, py")
        half_kick()
        S("  fma  x, H, px, x")
        S("  fma  y, H, py, y")
        half_kick()
        S("endrep")
        for i, r in enumerate(("x", "y", "px", "py")):
            S(f"stl  {r}, {i}")
        S("halt")
        return S.text()
    S("  fma  x, H2, px, x         ; drift")
    S("  fma  y, H2, py, y")
    S("  fma  t0, TWO, y, ONE      ; 1 + 2 y")
    S("  mul  t0, x, t0            ; x (1 + 2 y)")
    S(f"  fma  px, {'H' if mutant == 'xforce-sign' else 'MH'}, t0, px"
      f"       ; kick: px - h x (1 + 2 y)")
    S("  mul  t1, x, x             ; x^2")
    S("  neg  t1, t1")
    S("  sub  t2, y, ONE           ; y - 1")
    S("  fma  t2, y, t2, t1        ; y (y - 1) - x^2")
    S("  fma  py, H, t2, py        ; kick: py + h (...)")
    S("  fma  x, H2, px, x         ; drift")
    S("  fma  y, H2, py, y")
    S("endrep")
    for i, r in enumerate(("x", "y", "px", "py")):
        S(f"stl  {r}, {i}")
    S("halt")
    return S.text()


GENERATORS = {"lorenz63-rk4": lorenz63, "lorenz96-rk4": lorenz96,
              "henonheiles-lf": henonheiles}


def outputs():
    """{filename: bytes} - every file this generator owns."""
    out = {}
    for name, gen in GENERATORS.items():
        for fmtname in FORMATS_BUILT:
            fmt = FORMATS[fmtname]
            out[f"{name}-{fmtname}.cfta"] = gen(fmtname).encode("ascii")
            out[f"{name}-{fmtname}.classic.bank"] = bank_bytes(name, fmt)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="compare with the committed files; write nothing")
    args = ap.parse_args(argv)
    bad = 0
    for fname, data in outputs().items():
        path = HERE / fname
        if args.check:
            have = path.read_bytes() if path.exists() else None
            if have != data:
                print(f"gen_odes: {fname} "
                      f"{'is missing' if have is None else 'differs'} - "
                      f"run `python programs/gen_odes.py`")
                bad += 1
        else:
            with open(path, "wb") as fh:
                fh.write(data)
            print(f"  wrote {fname} ({len(data)} bytes)")
    if args.check:
        print(f"gen_odes: {len(outputs()) - bad} of {len(outputs())} files "
              f"match the generator")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
