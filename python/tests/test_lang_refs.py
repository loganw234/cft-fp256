# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The language's reference interpreter against seq.py, on the images
programs/gen_odes.py wrote by hand - and the plants that show the
comparison can fail.

For each reference system (programs/systems/*.cftl) at fp64 and fp256,
the committed .cfta is assembled by asm.py (its bytes held to
programs/MANIFEST's .cftp line, so this is the image the library ships),
its one REPEAT is patched to 1, 2, 5 and its own count, and seq.py runs
it on the committed classic bank. The interpreter runs the system's step
graph once to the own count, recording at 1, 2 and 5. Every lane's state
and the run's FLAGS must be equal at every count, bit for bit. Among the
lanes: one that overflows, one holding a signaling NaN and one holding a
subnormal, each asserted to raise what it is there to raise.

The plants are wrong semantics built here, as modified copies of a step
graph run by the shipped interpreter - never in the shipped code - and
each must DISAGREE with seq.py: a reassociated sum, a contraction, a
contraction undone, and constants rounded through a narrower format.
"""

import hashlib
import random
import sys
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))

from cft_golden import FORMATS, asm, chars, lang, seq  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
from cft_golden.lang.graph import Section  # noqa: E402

PROGRAMS = REPO / "programs"
SYSTEMS = PROGRAMS / "systems"
NAMES = ("lorenz63-rk4", "lorenz96-rk4", "henonheiles-lf")
FORMATS_BUILT = ("fp64", "fp256")
CASES = [(n, f) for n in NAMES for f in FORMATS_BUILT]

# Each image's own step count - its one REPEAT - as a literal, the way
# programs/check.py pins it; the test holds the image to it.
OWN_STEPS = {"lorenz63-rk4": 100, "lorenz96-rk4": 20, "henonheiles-lf": 100}
CHECKPOINTS = (1, 2, 5)
# Lanes: random full-significand states, and the three special lanes.
RANDOM_LANES = {"lorenz63-rk4": 32, "lorenz96-rk4": 6, "henonheiles-lf": 32}
BOX = {"lorenz63-rk4": [(-15, 15), (-20, 20), (5, 40)],
       "lorenz96-rk4": None,                     # every component in (-1, 9)
       "henonheiles-lf": [(Fraction(-2, 5), Fraction(2, 5))] * 4}
# The flags each system's lanes raise, as a literal: invalid (the
# signaling NaN), overflow, inexact, and underflow where the subnormal
# lane reaches it. Lorenz-96 at F = 8 does not: every product there
# feeds an fma whose result is near F (measured here, at both formats).
FLAGS = {"lorenz63-rk4": 0x1d, "lorenz96-rk4": 0x15, "henonheiles-lf": 0x1d}

INVALID, OVERFLOW, UNDERFLOW, INEXACT = (sf.FLAG_INVALID, sf.FLAG_OVERFLOW,
                                         sf.FLAG_UNDERFLOW, sf.FLAG_INEXACT)


# ---- the images, the banks, the lanes ---------------------------------

def _manifest():
    out = {}
    for line in (PROGRAMS / "MANIFEST").read_text().splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].endswith(".cftp"):
            out[parts[1]] = parts[0]
    return out


@lru_cache(maxsize=None)
def image(name, fmtname):
    """The committed source assembled by asm.py, and its own REPEAT."""
    text = (PROGRAMS / f"{name}-{fmtname}.cfta").read_text()
    img = asm.assemble_image(text, f"{name}-{fmtname}.cfta")
    return img


def program(name, fmtname, steps):
    """The image with its one REPEAT's trip count set to `steps` - the
    same program, as programs/check.py's _patch_trip builds it."""
    img = image(name, fmtname)
    insns, found = [], 0
    for word in img.insns:
        d = asm.decode(word)
        if d["ctrl"] and d["op"] == asm.REPEAT:
            assert d["imm"] == OWN_STEPS[name]
            word = asm.repeat(steps)
            found += 1
        insns.append(word)
    assert found == 1
    patched = asm.Image(img.fmt, insns, img.consts, img.max_deposits,
                        img.flags, scratch_depth=img.scratch_depth,
                        scratch_io=img.scratch_io)
    return seq.Program.from_bytes(patched.to_bytes())


@lru_cache(maxsize=None)
def bank(name, fmtname):
    fmt = FORMATS[fmtname]
    raw = (PROGRAMS / f"{name}-{fmtname}.classic.bank").read_bytes()
    esz = fmt.width // 8
    return tuple(int.from_bytes(raw[i:i + esz], "little")
                 for i in range(0, len(raw), esz))


@lru_cache(maxsize=None)
def graph(name, fmtname):
    return lang.load(SYSTEMS / f"{name}-{fmtname}.cftl").graph


def _rounded(fmt, value):
    sign = 1 if value < 0 else 0
    v = abs(value)
    return chars._round_rational(fmt, sign, v.numerator, v.denominator,
                                 sf.RND_RNE)[0]


def _random_state(fmt, rng, lo, hi):
    """A value in [lo, hi] with about twice the format's precision,
    rounded once: a full significand, so no product is exact by
    accident of small integers."""
    num = rng.randrange(1 << (2 * fmt.prec))
    v = Fraction(lo) + (Fraction(hi) - Fraction(lo)) * Fraction(
        num, 1 << (2 * fmt.prec))
    return _rounded(fmt, v) if v else 0


@lru_cache(maxsize=None)
def lanes(name, fmtname):
    """(lanes, {role: lane index}) - the random lanes, then the special
    ones, and for Lorenz-63 a lane of small integers too."""
    fmt = FORMATS[fmtname]
    g = graph(name, fmtname)
    n = g.n_state
    rng = random.Random(f"lang-refs {name} {fmtname}")
    out = []
    for _ in range(RANDOM_LANES[name]):
        out.append([_random_state(fmt, rng, *(BOX[name][c] if BOX[name]
                                               else (-1, 9)))
                    for c in range(n)])
    roles = {}
    huge = sf.round_pack(fmt, 0, 1, fmt.emax // 2 + 10)[0]
    over = list(out[0])
    over[0] = over[1] = huge
    roles["overflow"] = len(out)
    out.append(over)
    snan = list(out[1])
    snan[0] = sf.snan_bits(fmt, 1)
    roles["snan"] = len(out)
    out.append(snan)
    sub = list(out[2])
    tiny = sf.min_subnormal_bits(fmt)
    if name == "lorenz63-rk4":
        sub[2] = tiny                    # beta z rounds below the normals
    elif name == "henonheiles-lf":
        sub[0], sub[2] = tiny, 0         # x stays tiny through the drift
    else:
        # every component subnormal: at F = 0 each right-hand side is
        # -x_i plus a product far below it, tiny and inexact
        sub = [tiny] + [rng.randrange(1, 1 << fmt.man_w)
                        for _ in range(n - 1)]
    roles["subnormal"] = len(out)
    out.append(sub)
    if name == "lorenz63-rk4":
        roles["integers"] = len(out)
        out.append([sf.one_bits(fmt)] * n)
    return tuple(tuple(x) for x in out), roles


@lru_cache(maxsize=None)
def seq_run(name, fmtname, steps, bank_override=None):
    """seq.py's run of the patched image: (states, flags)."""
    ls, _roles = lanes(name, fmtname)
    n = graph(name, fmtname).n_state
    prog = program(name, fmtname, steps)
    b = list(bank(name, fmtname) if bank_override is None else bank_override)
    res = seq.run(prog, [0] * len(ls), [0] * len(ls), bank=b,
                  scratch_in=[v for lane in ls for v in lane])
    assert res.status == 0
    states = [list(res.scratch_out[k * n:(k + 1) * n])
              for k in range(len(ls))]
    return states, res.flags


@lru_cache(maxsize=None)
def interp_run(name, fmtname):
    ls, _roles = lanes(name, fmtname)
    return lang.run(graph(name, fmtname), [list(x) for x in ls],
                    OWN_STEPS[name], at=CHECKPOINTS)


def _counts():
    return CHECKPOINTS + (None,)


def _interp_at(run, name, s):
    if s is None:
        return run.states, run.flags
    return run.at[s]


# ---- the image is the library's -----------------------------------------

@pytest.mark.parametrize("name,fmtname", CASES)
def test_image_is_the_manifests(name, fmtname):
    """The source assembles to the bytes programs/MANIFEST names, so the
    comparison below is with the image the library ships."""
    data = image(name, fmtname).to_bytes()
    assert hashlib.sha256(data).hexdigest() == \
        _manifest()[f"{name}-{fmtname}.cftp"]


# ---- the interpreter is seq.py, bit for bit --------------------------------

@pytest.mark.parametrize("name,fmtname", CASES)
def test_interpreter_equals_seq(name, fmtname):
    run = interp_run(name, fmtname)
    for s in _counts():
        steps = OWN_STEPS[name] if s is None else s
        want_states, want_flags = seq_run(name, fmtname, steps)
        got_states, got_flags = _interp_at(run, name, s)
        bad = [k for k, (a, b) in enumerate(zip(got_states, want_states))
               if a != b]
        assert not bad, (f"{name}-{fmtname} after {steps} steps: lanes {bad} "
                         f"differ from seq.py")
        assert got_flags == want_flags, (
            f"{name}-{fmtname} after {steps} steps: FLAGS {got_flags:#x}, "
            f"seq.py {want_flags:#x}")


@pytest.mark.parametrize("name,fmtname", CASES)
def test_special_lanes_raise_what_they_are_for(name, fmtname):
    """The run's FLAGS are the literal above, and each special lane, run
    alone, raises the flag it is there for - so the comparison really
    did cross an overflow, a signaling NaN and (where reachable) an
    underflow."""
    run = interp_run(name, fmtname)
    assert run.flags == FLAGS[name]
    ls, roles = lanes(name, fmtname)
    g = graph(name, fmtname)
    steps = OWN_STEPS[name]
    alone = {role: lang.run(g, [list(ls[k])], steps).flags
             for role, k in roles.items() if role != "integers"}
    assert alone["overflow"] & OVERFLOW
    assert alone["snan"] & INVALID
    if FLAGS[name] & UNDERFLOW:
        assert alone["subnormal"] & UNDERFLOW
    else:
        assert not alone["subnormal"] & UNDERFLOW
    tiny = sf.min_subnormal_bits(g.fmt)
    assert tiny in ls[roles["subnormal"]]


# ---- run values against seq.py ---------------------------------------------

@pytest.mark.parametrize("name,param,value,slot", [
    ("lorenz63-rk4", "sigma", 12, "SIGMA"),
    ("lorenz96-rk4", "F", 0, "F"),
])
@pytest.mark.parametrize("fmtname", FORMATS_BUILT)
def test_param_override_equals_seq_on_that_bank(name, param, value, slot,
                                                fmtname):
    """A run value for a param is the bank slot rounded once: the
    interpreter with params={...} equals seq.py on the classic bank with
    that one slot replaced. Lorenz-96 with F = 0 reaches underflow."""
    fmt = FORMATS[fmtname]
    order = {"lorenz63-rk4": ["H", "H2", "H6", "TWO", "SIGMA", "RHO",
                              "BETA"],
             "lorenz96-rk4": ["H", "H2", "H6", "TWO", "F"]}[name]
    b = list(bank(name, fmtname))
    b[order.index(slot)] = _rounded(fmt, Fraction(value)) if value else 0
    steps = 5
    want_states, want_flags = seq_run(name, fmtname, steps, tuple(b))
    ls, _roles = lanes(name, fmtname)
    run = lang.run(graph(name, fmtname), [list(x) for x in ls], steps,
                   params={param: value})
    assert run.states == want_states
    assert run.flags == want_flags
    if name == "lorenz96-rk4":
        assert run.flags & UNDERFLOW


@pytest.mark.parametrize("name,fmtname", CASES)
def test_halved_step_is_the_halved_bank(name, fmtname):
    """h = h/2 recomputes every h-scaled constant from the exact value
    and rounds it once - and that is the bank with each h-scaled slot
    halved exactly, which is what a step-halving estimate runs on."""
    g = graph(name, fmtname)
    fmt = g.fmt
    half = sf.one_bits(fmt) - (1 << fmt.man_w)          # 0.5
    ls, _roles = lanes(name, fmtname)
    few = [list(x) for x in ls[:3]]
    halved_consts = []
    for value, factor, bits, flags in g.const:
        if factor is not None:
            hb, hf = sf.mul(fmt, bits, half)
            assert hf == 0, "halving an h-scaled slot is exact"
            halved_consts.append((value / 2, factor, hb, flags))
        else:
            halved_consts.append((value, factor, bits, flags))
    by_halving = lang.run(g.copy(const=halved_consts), few, 3)
    by_h = lang.run(g, few, 3, h=g.integrator[1] / 2)
    assert by_h.states == by_halving.states
    assert by_h.flags == by_halving.flags


# ---- the plants: wrong semantics, built here, each disagreeing ------------

class _P:
    """A node of a planted copy: an operation on refs and other _P."""
    __slots__ = ("op", "args", "label")

    def __init__(self, op, args, label=None):
        self.op, self.args, self.label = op, list(args), label


def _objects(sec):
    nodes = []
    for op, args, label in sec.nodes:
        nodes.append(_P(op, [nodes[int(a[1:])] if a[0] == "n" else a
                             for a in args], label))
    outs = [nodes[int(o[1:])] if o[0] == "n" else o for o in sec.out]
    return nodes, outs


def _section(outs):
    """A Section from planted objects: a post-order walk from the
    outputs, so every operand comes first and dead nodes drop out."""
    order, index = [], {}

    def visit(p):
        stack = [(p, 0)]
        while stack:
            node, i = stack.pop()
            if id(node) in index:
                continue
            if i < len(node.args):
                stack.append((node, i + 1))
                a = node.args[i]
                if isinstance(a, _P) and id(a) not in index:
                    stack.append((a, 0))
                continue
            index[id(node)] = len(order)
            order.append(node)
    for o in outs:
        if isinstance(o, _P):
            visit(o)

    def ref(a):
        return f"n{index[id(a)]}" if isinstance(a, _P) else a
    return Section([ref(o) for o in outs],
                   [(p.op, tuple(ref(a) for a in p.args), p.label)
                    for p in order])


def _const_ref(g, value):
    for k, (v, factor, _b, _f) in enumerate(g.const):
        if v == value and factor is None:
            return f"c{k}"
    raise KeyError(value)


def plant_reassociated(g):
    """The rk4 sum as (k1 + 2 k2) + (2 k3 + k4), not ((k1 + 2 k2) + 2 k3)
    + k4: the same three operations, associated differently."""
    nodes, outs = _objects(g.step)
    by = {p.label: p for p in nodes if p.label}
    two = _const_ref(g, 2)
    for c in g.components():
        s4 = by[f"S4.{c}"]
        t = _P("fma", [two, by[f"k3.{c}"], by[f"k4.{c}"]])
        s4.op, s4.args = "add", [by[f"S2.{c}"], t]
    return g.copy(step=_section(outs))


def plant_contraction(g):
    """a*b + c made one fma: every add whose operand is a mul used only
    there (S3.x + k4.x in Lorenz-63, k4.x = sigma * (...))."""
    nodes, outs = _objects(g.step)
    uses = {}
    for p in nodes:
        for a in p.args:
            if isinstance(a, _P):
                uses[id(a)] = uses.get(id(a), 0) + 1
    sites = 0
    for p in nodes:
        if p.op != "add":
            continue
        for side in (1, 0):
            m = p.args[side]
            if isinstance(m, _P) and m.op == "mul" and uses[id(m)] == 1:
                other = p.args[1 - side]
                p.op, p.args = "fma", [m.args[0], m.args[1], other]
                sites += 1
                break
    assert sites, "the plant found nothing to contract"
    return g.copy(step=_section(outs))


def plant_uncontracted(g):
    """Every fma split into a mul and an add (verifier-P1's plant)."""
    nodes, outs = _objects(g.step)
    for p in nodes:
        if p.op == "fma":
            m = _P("mul", p.args[:2])
            p.op, p.args = "add", [m, p.args[2]]
    return g.copy(step=_section(outs))


def plant_narrow_constants(g):
    """Every constant rounded through a narrower format first (binary32
    for fp64, binary64 for fp256), then widened exactly - the route a
    Python float or a narrower literal takes."""
    fmt = g.fmt
    narrow = FORMATS["fp32" if fmt.name == "fp64" else "fp64"]
    consts = []
    for value, factor, bits, flags in g.const:
        nb = _rounded(narrow, value) if value else 0
        wide, _f = sf.convert(narrow, fmt, nb)
        consts.append((value, factor, wide, flags))
    return g.copy(const=consts)


PLANTS = {"reassociated-sum": plant_reassociated,
          "contraction": plant_contraction,
          "contraction-undone": plant_uncontracted,
          "narrow-constants": plant_narrow_constants}


def plant_outcome(plant, name, fmtname):
    """(lanes differing from seq.py at the own count, of how many, the
    first count at which any lane differs, the integers lane's verdict)."""
    g = PLANTS[plant](graph(name, fmtname))
    ls, roles = lanes(name, fmtname)
    run = lang.run(g, [list(x) for x in ls], OWN_STEPS[name],
                   at=CHECKPOINTS)
    first = None
    for s in _counts():
        steps = OWN_STEPS[name] if s is None else s
        want, _f = seq_run(name, fmtname, steps)
        got, _g = _interp_at(run, name, s)
        if got != want and first is None:
            first = steps
    want, _f = seq_run(name, fmtname, OWN_STEPS[name])
    differ = [k for k, (a, b) in enumerate(zip(run.states, want)) if a != b]
    ints = roles.get("integers")
    return differ, len(ls), first, (None if ints is None else ints in differ)


@pytest.mark.parametrize("plant", list(PLANTS))
@pytest.mark.parametrize("fmtname", FORMATS_BUILT)
def test_plant_disagrees_with_seq(plant, fmtname):
    name = "lorenz63-rk4"
    differ, total, first, ints = plant_outcome(plant, name, fmtname)
    print(f"plant {plant} on {name}-{fmtname}: {len(differ)} of {total} "
          f"lanes differ from seq.py after {OWN_STEPS[name]} steps; the "
          f"first count with a difference is {first}; the small-integer "
          f"lane {'differs' if ints else 'agrees'}")
    assert differ, f"plant {plant} stayed green at {total} lanes"
    assert first is not None
