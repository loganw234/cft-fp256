# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The lanes, the measurements and the checks parcels E1, MB1 and MB2 hold the
fragments of exp, exp2, expm1, log, log2 and log1p to (cft_golden/mathlib.py;
docs/studies/M1-exp-log.md, section 8, items 1 to 5), gathered in one place so
that python/tests/test_mathlib.py (quick, for the golden stage) and
python/tests/mathlib_runs.py (the larger runs, for the lead's box) run the
same lanes and the same checks.

A CHECK takes a fragment or its instrumented build and returns FINDINGS: a
list of strings, each beginning with the check's name and a colon, empty
when it holds. So a planted fault is "caught by name" when the check it is
meant for returns a finding that begins with that name, and the test that
plants it says which. A check that works on a fragment or a build finds its
routine in it (f.op, b.meta["fn"]); one that takes only a format has a
`fn` argument, "exp" by default.

  pools:        every lane of the transcend pools, at one format and
                attribute, through one fragment: every unmarked lane equals
                transcend's in bits AND flag word; every marked lane is
                replayed and its guess counted; the marked set is the
                committed one (exp: the committed centres; exp2 and expm1:
                where the theory of mathlib_family says a lane is within the
                bound of a boundary)
  seq:          the fragment as a stand-alone program on seq.py (C4's
                routines.program and routines.run) equal to evaluate() and
                to transcend's
  r24:          the compiled shape - QUIET, the body, ENDQUIET, RAISE of the
                flag word - on seq.py: each lane's byte is exactly the
                operation's IEEE flags, the mark is bit 7
  bound:        |V - mpmath| / Bv under 1, mpmath at 4p + 200 bits, over
                random arguments with every bit random and over the places
                each path's reduced argument is largest
  budget:       the first-order budget's bound under 1 (mathlib_budget)
  rate:         the mark-rate law with the bound inflated by a fixed factor:
                the count of marks against the sample's own expectation, by
                its exact two-sided tail, a run of cells judged together
  rategeom:     the same build marks exactly the lanes whose true value lies
                within the inflated bound of a boundary, lane for lane
  family:       the structured family (mathlib_family): the committed list
                against the theory's generation; the centres and their
                neighbours, inside and outside the windows
  nofamily:     exp2 and log2 have no family: the census, the deep arguments
                and the neighbours of the exact cases are all unmarked and
                right
  census:       at fp32 the study's census finds no window
  census_counts at fp64, fp128 and fp256 the study's census marks the
                counted lanes, among them every committed centre
  recip:        RECIP_SEED's 512 cells (log, log2, log1p): the instruction
                gives the table's value at both ends of each, C is 8 to 16,
                and max |r| is under the plan's rho
  edges:        pools: the thresholds with their signs and the cells' ends
  lanes:        pools: random and weighted lanes
  shape:        the fragment's instruction, word and live counts are the
                pinned ones
  sums:         the fragment's opcodes are the design's ALU set (no
                augmented addition), and its error-free sums are counted
  specialised:  the fragment is in C4's specialised form, and the
                instrumented form (the unpruned body the budget reads, its
                phases and probes) agrees with it
  reorder:      the scheduled fragment is the design's, reordered: the same
                dataflow graph, no more values live than in the design's order
  fixed_grid:   the fixed grid's one rounding, on states of V_h and V_l
                that no argument is known to reach
  spot:         constants read against an enclosure independent of the
                generator: ln 2, the table's high words, the Cody-Waite sum
  invariants:   mathlib.invariants()
  constants:    mathlib.check_constants()
"""

import functools
import importlib.util
import math
import random
import sys
from fractions import Fraction
from pathlib import Path

import mpmath

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cft_golden import FP32, FP64, FP128, FP256, routines, seq  # noqa: E402
from cft_golden import mathlib as ml  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
from cft_golden import transcend, vectors  # noqa: E402

FORMATS = (FP32, FP64, FP128, FP256)
RND_MODES = sf.RND_MODES
N = ml.N
FUNCS = ml.NAMES                        # exp, exp2, expm1, log, log2, log1p
EXP_FUNCS = ml.EXP_NAMES
LOG_FUNCS = ml.LOG_NAMES
NOFAMILY = ("exp2", "log2")             # the routines with no structured family
TRANSCEND = {"exp": transcend.exp, "exp2": transcend.exp2,
             "expm1": transcend.expm1, "log": transcend.log,
             "log2": transcend.log2, "log1p": transcend.log1p}


# ---- the definition, memoised -----------------------------------------------

@functools.lru_cache(maxsize=None)
def golden(fmt, rnd, x, fn="exp"):
    """transcend.<fn>: the definition. Cached, since a plant re-runs the
    lanes of the clean fragment."""
    return TRANSCEND[fn](fmt, x, rnd)


def value(fmt, bits):
    return ml._dec(fmt, bits)


# ---- the pools --------------------------------------------------------------

_TC = []


def _transcend_check():
    """host/tests/transcend_check.py as a module (it is a script of the
    libcft stage; its pools are what that stage replays)."""
    if not _TC:
        spec = importlib.util.spec_from_file_location(
            "mathlib_transcend_check", ROOT / "host" / "tests" /
            "transcend_check.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _TC.append(mod)
    return _TC[0]


@functools.lru_cache(maxsize=None)
def pools(fmt):
    """The transcend pools, deduplicated and sorted: transcend_check's
    unary_pool at its default trials (64 random encodings at fp32 and fp64,
    16 at fp128 and fp256) and seed 5, the vector sets' transcend_unary_pool
    at the same counts and its seed 9, and test_transcend's brute pool. One
    pool for all of exp, exp2 and expm1 (the stage's unary pool serves seven
    functions)."""
    from test_transcend import _brute_pool
    t = 64 if fmt.width <= 64 else 16
    a = _transcend_check().unary_pool(fmt, t, 5)
    b = vectors.transcend_unary_pool(fmt, t, 9)
    return tuple(sorted(set(a) | set(b) | set(_brute_pool(fmt))))


def tiny_two(fmt, sign):
    """+-2^-p as an encoding: the argument whose exp sits 2^-(2p+1) from a
    rounding boundary, the one lane of the pools the in-lane test cannot
    decide."""
    return sf.round_pack(fmt, sign, 1, -fmt.prec, sf.RND_RNE)[0]


def expected_pool_marks(fmt, rnd, fn="exp"):
    """The marked lanes of `pools`, committed. None at fp32 (at G = 40 the
    structured windows are empty, mathlib_family), and none of exp2's at any
    format (it has no family). At fp64, fp128 and fp256 exp's are exactly
    exp(2^-p) under rne and rmm, whose true value 1 + 2^-p + 2^-(2p+1) is
    2^-(2p+1) above a midpoint, and exp(-2^-p) under the directed three,
    2^-(2p+1) from the grid point 1 - 2^-p (the study's 3.4, MEASURED again
    in parcel E1's entry); expm1's are expm1(-2^-p) under rne and rmm, whose
    true value -2^-p + 2^-(2p+1) - 2^-(3p)/6 is that far under the midpoint
    -2^-p + 2^-(2p+1) (the study's 3.4), and none under the directed three.
    The log family's (parcel MB2, MEASURED, and equal to the theory's "must
    mark" lanes of the pools): log marks x = 1 + ulp under the directed three,
    where log(1 + eps) = eps - eps^2/2 + eps^3/3 - ... sits eps^3/3 above the
    grid point pred(eps) = eps - eps^2/2, and none under rne and rmm; log1p
    marks x = 2^-p under rne and rmm, where log1p(x) = x - x^2/2 + x^3/3 - ...
    sits x^3/3 above the midpoint x - x^2/2 between pred(x) and x, and none
    under the directed three; log2 marks none."""
    if fmt.name == "fp32" or fn in NOFAMILY:
        return set()
    if fn == "log":
        return set() if rnd in (sf.RND_RNE, sf.RND_RMM) \
            else {sf.one_bits(fmt) + 1}
    if fn == "log1p":
        return {tiny_two(fmt, 0)} if rnd in (sf.RND_RNE, sf.RND_RMM) else set()
    if fn == "expm1":
        return {tiny_two(fmt, 1)} if rnd in (sf.RND_RNE, sf.RND_RMM) else set()
    return {tiny_two(fmt, 0 if rnd in (sf.RND_RNE, sf.RND_RMM) else 1)}


# ---- tallying lanes against the definition ----------------------------------

class Tally:
    """The lanes of one run: n, how many marked, how many marked guesses
    were right, the unmarked lanes that were wrong, and the marked lanes."""

    def __init__(self):
        self.n = 0
        self.marked = []
        self.guess_wrong = []
        self.wrong = []
        self.stray = []

    @property
    def marked_right(self):
        return len(self.marked) - len(self.guess_wrong)


def tally(fmt, rnd, xs, results, fn="exp"):
    t = Tally()
    for x, (bits, fw) in zip(xs, results):
        gb, gf = golden(fmt, rnd, x, fn)
        t.n += 1
        if fw & ~(ml.MARK | 0x1F):
            t.stray.append((x, fw))
        if fw & ml.MARK:
            t.marked.append(x)
            if (bits, fw & 0x1F) != (gb, gf):
                t.guess_wrong.append((x, bits, gb))
        elif (bits, fw) != (gb, gf):
            t.wrong.append((x, (bits, fw), (gb, gf)))
    return t


def _hexes(xs, k=3):
    return ", ".join(hex(x) for x in list(xs)[:k])


def structured_arguments(fmt, rnd, fn="exp"):
    """The arguments of the committed structured list (mathlib_family.FAMILY)
    for this routine, format and attribute: the only arguments of exp's pools
    that may be marked."""
    import mathlib_family as F
    return {F.argument(fmt, c)
            for c in F.FAMILY[fn][fmt.name][sf.RND_NAMES[rnd]]}


def theory_marks(fmt, rnd, xs, fn):
    """(may, must): of the arguments xs, those the theory of mathlib_family
    allows to be marked (d < 1.3) and those it demands marked (d < 0.7); a
    gated argument is neither."""
    import mathlib_family as F
    may, must = set(), set()
    for x in xs:
        if sf.unpack(fmt, x).kind in (sf.NAN, sf.INF):
            continue
        c = F.classify(fmt, rnd, x, None, fn)
        if c == "mark":
            may.add(x)
            must.add(x)
        elif c == "either":
            may.add(x)
    return may, must


def check_lanes(name, fmt, rnd, xs, results, allowed_marks=None, fn="exp",
                theory=False):
    """[finding], Tally: results[i] = (bits, flag word) of xs[i], against
    transcend's: every unmarked lane equal in bits and flags; no flag bit
    but [4:0] and the mark; and, where `allowed_marks` is given (exp's
    committed structured list), a marked lane only at one of those
    arguments, and every lane at one of them marked: each is a centre the
    theory puts inside its window. With `theory` (exp2 and expm1) the
    allowed marks are the lanes among xs the theory of mathlib_family puts
    within the bound of a boundary (d < 1.3) and the required ones those with
    d < 0.7."""
    t = tally(fmt, rnd, xs, results, fn)
    where = f"{name}: {fn} {fmt.name} {sf.RND_NAMES[rnd]}"
    out = []
    if t.wrong:
        x, got, want = t.wrong[0]
        out.append(f"{where}: {len(t.wrong)} unmarked lanes differ from "
                   f"transcend.{fn}, first {hex(x)}: got "
                   f"({got[0]:#x}, {got[1]:#x}), want ({want[0]:#x}, "
                   f"{want[1]:#x})")
    if t.stray:
        out.append(f"{where}: {len(t.stray)} flag words carry bits other "
                   f"than [4:0] and the mark, first {hex(t.stray[0][0])}")
    required = allowed_marks
    if theory:
        allowed_marks, required = theory_marks(fmt, rnd, xs, fn)
    if allowed_marks is not None:
        off = [x for x in t.marked if x not in allowed_marks]
        if off:
            out.append(f"{where}: {len(off)} lanes are marked off the "
                       f"structured list, first {_hexes(off)}")
        marked = set(t.marked)
        unmarked = [x for x in xs if x in required and x not in marked]
        if unmarked:
            out.append(f"{where}: {len(unmarked)} lanes on the structured "
                       f"list are not marked, first {_hexes(unmarked)}")
    return out, t


# ---- the lanes through a fragment -------------------------------------------

def evaluate_all(f, xs):
    return [ml.evaluate(f, x) for x in xs]


def _marks_for(f, fmt, rnd):
    """The keyword arguments of check_lanes for fragment f's routine: exp
    keeps E1's committed list, exp2 and expm1 the theory."""
    if f.op == "exp":
        return {"allowed_marks": structured_arguments(fmt, rnd, "exp")}
    return {"theory": True}


def check_pools(f, rnd=None, xs=None):
    """pools: one fragment over the pools of its format. A lane may be
    marked only where the structured family has its argument (the study
    found the pools' only marks to be those, exp(+-2^-p): a mark anywhere
    else is a fault)."""
    fmt = f.fmt
    rnd = f.rnd if rnd is None else rnd
    xs = pools(fmt) if xs is None else xs
    return check_lanes("pools", fmt, rnd, xs, evaluate_all(f, xs), fn=f.op,
                       **_marks_for(f, fmt, rnd))


def check_random_lanes(f, n, seed):
    """lanes: n random main-path arguments with every bit random
    (random_main) and n of the weighted sampler (weighted) through the
    fragment, as the pools are: every unmarked lane equal to transcend's
    in bits and flags, a mark only where the family allows. A random lane is
    marked with probability about 2^(0.53 - G), 2^-43.5 at fp64 (the study's
    3.4): none of these is."""
    fmt, rnd = f.fmt, f.rnd
    xs = sorted(set(random_main(fmt, n, seed, f.op)
                    + weighted(fmt, n, seed + 1, f.op)))
    return check_lanes("lanes", fmt, rnd, xs, evaluate_all(f, xs), fn=f.op,
                       **_marks_for(f, fmt, rnd))


def _around(fmt, v, out, steps=(-2, -1, 0, 1, 2)):
    """Add the encoding of the exact value v (rounded once) and the floats
    `steps` apart from it in the encoding to the set `out`."""
    b = ml._enc(fmt, v)
    out.update(b + d for d in steps)


def edge_pool(fmt, fn="exp"):
    """The arguments of the routine's edges.

    exp: x = n ln2 rounded, with neighbours at +-1 and +-2 ulps, for the n of
    transcend_check.unary_pool's exp edges (emax, emax + 1, emin, emin -
    man_w, emin - man_w - 1, -(p+2), -(p+3), p+1), BOTH signs of each; and
    placed(), the ends of every cell of n at the ends of the range and across
    k = emin, where the fixed grid takes over.

    The pools' generators (vectors.transcend_unary_pool and
    host/tests/transcend_check.unary_pool) took x = n ln2 from
    mpmath.libmp.to_man_exp, which returns the mantissa unsigned by default
    (mpmath 1.3), so through profile 3 every negative n came out positive:
    the pools held exp(+708.39...), exp's overflow, where the underflow
    thresholds - the argument of emin ln2 and the screen of (emin - p) ln2
    - should have been. This pool was made to hold both, so that the
    tininess decision at k = emin and the fixed grid were met. Since
    profile 3.1 (parcel PS) the pools read the mpf's raw tuple instead,
    call to_man_exp nowhere, and hold the signed image of each negative n
    beside the positive one; this pool holds more than they, both signs of
    the three positive n as well, and the cell ends.

    exp2: the integers at its edges, both signs, with neighbours: emax + 1
    (overflow), emax, emax - 1, emin, emin - 1, the subnormal range's ends
    emin - man_w + 1 and emin - man_w, the tie emin - p and the screen's
    neighbours emin - p - 1 and - 2, and small integers; j/8 near them
    (r' = 0, j != 0: not an integer, the study's defect 6); the tiny gate
    2^-(p+3) and 2^-(p+2); and the ends of every cell of n.

    expm1: x = n ln2 for the n of the clamp and the overflow (p, p + 1,
    p + 2, p + 3, emax, emax + 1, both signs); the second family's
    RN(-n ln 2) for n from G/2 to p + 3; the tiny path's edges 2^-(p+2),
    2^-(p+3) and the smallest normal's, subnormals' and their negatives,
    each with neighbours; and the ends of every cell of n, the first clamped
    k's among them.

    log, log2, log1p (parcel MB2): see _log_edges."""
    p, man_w = fmt.prec, fmt.man_w
    l2 = ml._ln2()
    out = set(placed(fmt, fn))
    if fn == "exp":
        ns = (fmt.emax, fmt.emax + 1, fmt.emin, fmt.emin - man_w,
              fmt.emin - man_w - 1, -(p + 2), -(p + 3), p + 1)
        for n in ns:
            for sgn in (1, -1):
                _around(fmt, sgn * n * l2, out)
    elif fn == "exp2":
        ints = (fmt.emax + 1, fmt.emax, fmt.emax - 1, fmt.emin,
                fmt.emin - 1, fmt.emin - man_w + 1, fmt.emin - man_w,
                fmt.emin - p, fmt.emin - p - 1, fmt.emin - p - 2, 0, 1, 2, 3,
                4, 7, 8, 9, 16, p, p + 1)
        for n in ints:
            for sgn in (1, -1):
                if n:
                    _around(fmt, sgn * n, out)
                for j in (1, 3, 7):
                    out.add(ml._enc(fmt, Fraction(sgn * (8 * n + j), 8)))
        for k in (p + 3, p + 2):
            for sgn in (1, -1):
                _around(fmt, sgn * Fraction(1, 2 ** k), out)
        # the last tenth of the binade k = emin, where V is in (1.875, 2): C
        # + V reaches 2 there, and a fixed grid whose offset is wrong doubles
        for i in range(14):
            out.add(ml._enc(fmt, fmt.emin + Fraction(907 + 7 * i, 1000)))
    elif fn in LOG_FUNCS:
        out.update(_log_edges(fmt, fn))
    else:
        G = ml.GUARD[fmt.name]
        for n in (p, p + 1, p + 2, p + 3, fmt.emax, fmt.emax + 1):
            for sgn in (1, -1):
                _around(fmt, sgn * n * l2, out)
        # the second family: RN(-n ln 2) with n up to p + 3, from G/2 on (the
        # theory's first centre is near G + log2 n)
        for n in sorted({G // 2, G - 3, G - 1, G, G + 2, G + 5, 50, 52, 53,
                         p - 2, p - 1, p, p + 1, p + 2, p + 3}):
            if n >= 1:
                _around(fmt, -n * l2, out)
        for k in (p + 2, p + 3):
            for sgn in (1, -1):
                _around(fmt, sgn * Fraction(1, 2 ** k), out)
        for b in (sf.min_normal_bits(fmt), sf.max_subnormal_bits(fmt),
                  sf.min_subnormal_bits(fmt)):
            for sg in (0, 1):
                bb = b | (fmt.sign_mask if sg else 0)
                out.update(bb + d for d in (-2, -1, 0, 1, 2))
    return tuple(sorted(x for x in out
                        if 0 <= x < 1 << fmt.width and not _nonfinite(fmt, x)))


def _nonfinite(fmt, x):
    return sf.unpack(fmt, x).kind in (sf.NAN, sf.INF)


def check_edges(f, xs=None):
    """edges: the signed thresholds and the cell ends (edge_pool) through the
    fragment, as the pools are: every unmarked lane equal to transcend's, a
    mark only where the family allows."""
    fmt, rnd = f.fmt, f.rnd
    xs = edge_pool(fmt, f.op) if xs is None else xs
    return check_lanes("edges", fmt, rnd, xs, evaluate_all(f, xs), fn=f.op,
                       **_marks_for(f, fmt, rnd))


def check_seq(f, xs=None, evaluator=None):
    """seq: the fragment as a program on seq.py equal to evaluate() lane
    for lane, and to transcend's unless marked. `evaluator` is the
    function standing for evaluate(), for the test that plants a fault in
    it."""
    fmt, rnd = f.fmt, f.rnd
    xs = pools(fmt) if xs is None else xs
    outs, words = routines.run(f, xs)
    got = list(zip(outs, words))
    out, t = check_lanes("seq", fmt, rnd, xs, got, fn=f.op)
    ev = [(evaluator or ml.evaluate)(f, x) for x in xs]
    bad = [x for x, a, b in zip(xs, got, ev) if a != b]
    if bad:
        out.append(f"seq: {f.op} {fmt.name} {sf.RND_NAMES[rnd]}: seq.py and "
                   f"evaluate() differ on {len(bad)} lanes, first "
                   f"{hex(bad[0])}")
    return out, t


def r24_program(f, loud=False):
    """The fragment as the compiler inlines it (cftc/inline.py): QUIET, the
    body, ENDQUIET, RAISE of the flag word, the result deposited. `loud`
    leaves the first instruction that can raise a flag outside the region,
    the fault the check must see."""
    prog, bank = routines.program(f)
    insns = list(prog.insns)
    res, flg = seq.decode(insns[-3]), seq.decode(insns[-2])
    assert res["op"] == seq.DEPOSIT and flg["op"] == seq.DEPOSIT
    body = insns[:-3]
    head = []
    if loud:
        for k, word in enumerate(body):
            if seq.decode(word)["op"] in routines.ROUNDED:
                head, body = body[:k + 1], body[k + 1:]
                break
    insns = head + [seq.quiet()] + body + [seq.endquiet(),
                                           seq.raise_(flg["ra"]),
                                           seq.deposit(res["ra"]),
                                           seq.halt()]
    return seq.Program(f.fmt, insns, consts=(), max_deposits=1,
                       flags=seq.FLAG_BANK_EXT, n_consts=len(bank)), bank


def check_r24(f, xs=None, loud=False):
    """r24: on seq.py, each lane's byte is the operation's IEEE flags and
    nothing else, with bit 7 where the lane is marked, and FLAGS and STATUS
    are what the bytes make them (docs/SEQUENCER.md, R23 and R24)."""
    fmt, rnd = f.fmt, f.rnd
    xs = pools(fmt) if xs is None else xs
    prog, bank = r24_program(f, loud)
    res = seq.run(prog, list(xs), [0] * len(xs), bank=bank)
    out, flags_or, marked = [], 0, False
    tag = f"r24: {f.op} {fmt.name} {sf.RND_NAMES[rnd]}"
    for i, x in enumerate(xs):
        bits, fw = ml.evaluate(f, x)
        gb, gf = golden(fmt, rnd, x, f.op)
        byte = res.lane_flags[i]
        flags_or |= byte & seq.LANE_FLAGS_IEEE
        if fw & ml.MARK:
            marked = True
            want = (fw & 0x1F) | seq.LANE_MARKED
        else:
            want = gf
            if res.deposits[i] != gb:
                out.append(f"{tag}: lane {hex(x)} deposited "
                           f"{res.deposits[i]:#x}, want {gb:#x}")
        if byte != want:
            out.append(f"{tag}: lane {hex(x)} raised {byte:#x}, want "
                       f"{want:#x}")
    if res.flags != flags_or:
        out.append(f"{tag}: FLAGS {res.flags:#x} is not the OR of the "
                   f"lanes' bytes {flags_or:#x}")
    if bool(res.status & seq.STATUS_MARKED) != marked:
        status6 = bool(res.status & seq.STATUS_MARKED)
        out.append(f"{tag}: STATUS[6] is {status6}"
                   f", a marked lane was {'' if marked else 'not '}run")
    return out[:6]


# ---- the main path ----------------------------------------------------------

def screens(fmt, fn="exp"):
    """(hi, lo) as values: the main path lies between them. exp: the overflow
    and underflow screens ((emax + 1) ln 2 rounded up, (emin - p) ln 2 rounded
    down); exp2: emax + 1 and emin - p; expm1: the overflow screen and the
    clamp to -1, -(p + 2) ln 2 rounded down."""
    if fn == "exp2":
        return (Fraction(fmt.emax + 1), Fraction(fmt.emin - fmt.prec))
    hi = value(fmt, ml._screens(fmt)[0])
    if fn == "expm1":
        return hi, value(fmt, ml._screen_expm1(fmt))
    return hi, value(fmt, ml._screens(fmt)[1])


def in_main(fmt, x, fn="exp"):
    """Whether the main path answers x: no NaN, infinity, zero, screen,
    tiny-argument gate or (exp2) exact integer does. The log family's main
    path: log, x > 0 and not 1; log2, x > 0 and not a power of two (an exact
    case); log1p, x > -1, not 0 and not under the tiny path's gate
    2^-(p+2)."""
    u = sf.unpack(fmt, x)
    if u.kind in (sf.NAN, sf.INF, sf.ZERO):
        return False
    xv = value(fmt, x)
    if fn in LOG_FUNCS:
        if fn == "log1p":
            return xv > -1 and abs(xv) >= Fraction(1, 2 ** (fmt.prec + 2))
        if xv <= 0:
            return False
        if fn == "log":
            return xv != 1
        n, d = xv.numerator, xv.denominator
        return not (n & (n - 1) == 0 and d & (d - 1) == 0)
    hi, lo = screens(fmt, fn)
    if not lo < xv < hi:
        return False
    if fn == "expm1":
        return abs(xv) >= Fraction(1, 2 ** (fmt.prec + 2))
    if fn == "exp2" and xv.denominator == 1:
        return False
    return abs(xv) >= Fraction(1, 2 ** (fmt.prec + 3))


def _rng(fmt, seed, mult, fn):
    """random.Random for a sampler: the routine's index (0 for exp, so exp's
    streams are E1's) keeps the routines' samples apart."""
    return random.Random((seed * mult + fmt.width) + 7919 * FUNCS.index(fn))


def random_main(fmt, n, seed, fn="exp"):
    """n arguments of the main path with every bit random: 60% a real
    drawn uniformly over the whole range between the screens (p + 20 random
    bits, rounded), 40% a random mantissa at a random exponent from
    -(p + 2) to 4 and a random sign (the study's domain_sample, with the
    low bits random, not 53 of them)."""
    if fn in LOG_FUNCS:
        return _log_random(fmt, n, seed, fn)
    rng = _rng(fmt, seed, 1000003, fn)
    p = fmt.prec
    hi, lo = screens(fmt, fn)
    out = []
    while len(out) < n:
        if rng.random() < 0.6:
            x = ml._enc(fmt, lo + (hi - lo) *
                        Fraction(rng.getrandbits(p + 20), 2 ** (p + 20)))
        else:
            e = rng.randint(-(p + 2), 4)
            x = sf.round_pack(fmt, rng.getrandbits(1),
                              rng.getrandbits(p) | (1 << (p - 1)),
                              e - p + 1, sf.RND_RNE)[0]
        if in_main(fmt, x, fn):
            out.append(x)
    return out


def uniform_m1rate(fmt, n, seed=7, fn="exp"):
    """The arguments the study's m1rate.py draws, its uniform_sample: n
    reals from random.Random(seed + width), each a Python float taken
    exactly: exp, uniform on ((emin - p) 0.693 + 1, (emax + 1) 0.693 - 1);
    expm1 the same but above -(p + 2) 0.693 + 1; exp2 on (emin - p + 1,
    emax). They lie between the screens, so all are on the main path; the few
    of exp and exp2 under emin have subnormal results, which the fixed grid
    rounds and the in-lane test marks as it marks the others (check_rate's
    docstring). The log family's (the same file): log and log2,
    n random positive normal encodings (the exponent field uniform), log1p n
    random normal encodings of either sign, kept where x > -1 and |x| >=
    2^-(p+2); the exact cases (x = 1, powers of two) are dropped."""
    rng = random.Random(seed + fmt.width)
    p = fmt.prec
    out = []
    if fn in LOG_FUNCS:
        while len(out) < n:
            b = rng.getrandbits(fmt.width - 1)
            if fn == "log1p":
                b |= rng.getrandbits(1) << (fmt.width - 1)
            if sf.unpack(fmt, b).kind != sf.NORM or not in_main(fmt, b, fn):
                continue
            out.append(b)
        return out
    while len(out) < n:
        if fn == "exp2":
            v = rng.uniform(fmt.emin - p + 1, fmt.emax)
        else:
            v = rng.uniform((fmt.emin - p) * 0.693 + 1,
                            (fmt.emax + 1) * 0.693 - 1)
            if fn == "expm1" and v < -(p + 2) * 0.693 + 1:
                continue
        out.append(ml._enc(fmt, Fraction(v)))
    return out


# the n whose cells' ends are measured: small ones, every residue j at a few
# k, and the ends of the main path, at both of each cell's ends
_PLACED_N = (-41, -17, -9, -1, 0, 1, 3, 9, 33, 77, 401)


def placed(fmt, fn="exp"):
    """The arguments where this path's reduced r is largest: x next to
    (n +- 1/2) ln2/8 (exp, expm1) or (n +- 1/2)/8 (exp2), the ends of each
    cell of n, for the study's n and for every residue j = n mod 8 at k =
    emin - 1, emin, emin + 1, -1, 0, 1 and at the ends of the main path (the
    study's worstcase.py, extended to the ends of n's range and to every j);
    expm1's also at the first clamped k, p + G + 3, and its neighbours; each
    with its two neighbours in the encoding. The log family's: see
    _log_placed."""
    if fn in LOG_FUNCS:
        return _log_placed(fmt, fn)
    p = fmt.prec
    unit = Fraction(1) if fn == "exp2" else ml._ln2()
    hi, lo = screens(fmt, fn)
    k_top, k_bot = math.floor(hi * N / unit) // N, math.ceil(lo * N / unit) // N
    ns = set(_PLACED_N)
    ks = [fmt.emin - 1, fmt.emin, fmt.emin + 1, -1, 0, 1, k_top, k_top - 1,
          k_bot, k_bot + 1]
    if fn == "expm1":
        # 2^-k is dropped past k = clamp = p + G + 2: the cells either side,
        # the first dropped k (clamp + 1) among them
        clamp = p + ml.GUARD[fmt.name] + 2
        ks += [clamp + d for d in range(-4, 4)]
    for k in ks:
        ns.update(N * k + j for j in range(N))
    out = set()
    for n in sorted(ns):
        for s in (-1, 1):
            mid = (Fraction(n) + Fraction(s, 2)) * unit / N
            if fn == "exp2":
                b = ml._enc(fmt, mid)
            else:
                b = ml._enc(fmt, Fraction(math.floor(mid * 2 ** (p + 60)),
                                          2 ** (p + 60)))
            out.update((b, b + 1, b - 1))
    return sorted(x for x in out if in_main(fmt, x, fn))


def key_encoding(fmt, k):
    """The encoding of the key k: the magnitude k for k >= 0, the negative
    encoding of magnitude -k otherwise (the keys of a sweep, monotone in
    value)."""
    return k if k >= 0 else fmt.sign_mask | -k


def range_keys(fmt, lo, hi):
    """(first, stop): the keys of the finite encodings whose value lies in
    [lo, hi] (Fractions), once each and in increasing order of value, are
    range(first, stop) (zero once, for +0 and -0; key_encoding gives the
    encoding). The keys are the encodings' magnitudes, negated for the
    negative ones, which is monotone in value; the ends are found by
    bisection, so no encoding of the range is walked."""
    top = sf.max_normal_bits(fmt)

    def val(k):
        return ml._dec(fmt, key_encoding(fmt, k))

    def first_where(pred):
        """The smallest key in [-top, top] with pred(value), else top + 1
        (pred is monotone: false, then true)."""
        a, b = -top, top + 1
        while a < b:
            mid = (a + b) // 2
            if pred(val(mid)):
                b = mid
            else:
                a = mid + 1
        return a
    lo, hi = Fraction(lo), Fraction(hi)
    return (first_where(lambda v: v >= lo), first_where(lambda v: v > hi))


def range_encodings(fmt, lo, hi):
    """Every finite encoding whose value lies in [lo, hi] (Fractions), once,
    in increasing order of value (zero once, for +0 and -0): the lanes of an
    exhaustive sweep."""
    first, stop = range_keys(fmt, lo, hi)
    for k in range(first, stop):
        yield key_encoding(fmt, k)


def sweep_keys(fmt, lo, hi, stride=1, shard=(0, 1)):
    """The keys of one shard of a strided sweep of [lo, hi]: every stride-th
    encoding of the range, shard i of n of those (shard = (i, n), so that n
    processes cover it), in O(its lanes), not O(the range): the lanes are the
    arithmetic progression first + stride i, + stride n, ... The slow form,
    which walks every encoding and keeps those with idx % stride == 0 and
    (idx // stride) % n == i, is the test's oracle."""
    first, stop = range_keys(fmt, lo, hi)
    i, n = shard
    return range(first + stride * i, stop, stride * n)


def uniform_unit(fmt, n, seed, fn="exp"):
    """n arguments uniform on [-1, 1] with every bit random (p + 20 random
    bits, rounded): the region of VM1b's budget for exp, 0.164 Bv at fp64
    and G = 44 (the study's 3.3), and for expm1 near n = +-1. The log family's
    cancelling cells (the study's 3.2, A up to 22): log and log2 x uniform on
    [0.84, 0.9415) (k = -1, C = 9), log1p x uniform on [-0.1597, -15/256) and
    [15/256, 1/8), half each."""
    rng = _rng(fmt, seed, 15485863, fn)
    p = fmt.prec
    if fn in LOG_FUNCS:
        def frac():
            return Fraction(rng.getrandbits(p + 20), 2 ** (p + 20))
        out = []
        for i in range(n):
            if fn != "log1p":
                v = Fraction(84, 100) + (Fraction(9415, 10000) -
                                         Fraction(84, 100)) * frac()
            elif i % 2:
                v = Fraction(15, 256) + (Fraction(1, 8) - Fraction(15, 256)) \
                    * frac()
            else:
                v = -(Fraction(15, 256) + (Fraction(1597, 10000) -
                                           Fraction(15, 256)) * frac())
            out.append(ml._enc(fmt, v))
        return out
    return [ml._enc(fmt, 2 * Fraction(rng.getrandbits(p + 20), 2 ** (p + 20))
                    - 1) for _ in range(n)]


def weighted(fmt, n, seed, fn="exp"):
    """n arguments of VM1's sampler for the exp family, weighted to where
    the terms are largest: x = (m + d) ln2/8 ((m + d)/8 for exp2), m half the
    time near 0 and half over the whole range, d 40% uniform in (-1/2, 1/2),
    40% within 0.0003 of an end and 20% small (verifier-VM1's p8_bound.py,
    vm1b). The log family's: see _log_weighted."""
    if fn in LOG_FUNCS:
        return _log_weighted(fmt, n, seed, fn)
    rng = _rng(fmt, seed, 104729, fn)
    unit = Fraction(1) if fn == "exp2" else ml._ln2()
    hi, lo = screens(fmt, fn)
    nlo, nhi = math.ceil(lo * N / unit), math.floor(hi * N / unit)
    out = []
    while len(out) < n:
        m = rng.randint(-24, 24) if rng.random() < 0.5 else \
            rng.randint(nlo + 16, nhi - 16)
        r = rng.random()
        if r < 0.4:
            d = Fraction(rng.randint(-499999, 499999), 10 ** 6)
        elif r < 0.8:
            d = (1 if rng.random() < 0.5 else -1) * (
                Fraction(1, 2) - Fraction(rng.randint(0, 3000), 10 ** 7))
        else:
            d = Fraction(rng.randint(-5, 5), 100)
        x = ml._enc(fmt, (Fraction(m) + d) * unit / N)
        if in_main(fmt, x, fn):
            out.append(x)
    return out


# ---- the log family's lanes (parcel MB2) ------------------------------------

@functools.lru_cache(maxsize=None)
def seed_runs(fmt):
    """((C, first m, last m), ...): the runs of consecutive RECIP_SEED cells
    that share one C, in order of m, from the table (mathlib._seed_C), each by
    its first and last float in [1, 2) at the format: C = 16, 15, ..., 9, 8
    (the wrap). The reduction's |r| is largest at the ends of a run, and the
    study's cancelling cell, k = -1 and C = 9, is the run of 9."""
    ulp = Fraction(1, 2 ** (fmt.prec - 1))
    runs = []
    for i in range(512):
        C = ml._seed_C(i)
        hi = 1 + Fraction(i + 1, 512) - ulp
        if runs and runs[-1][0] == C:
            runs[-1][2] = hi
        else:
            runs.append([C, 1 + Fraction(i, 512), hi])
    return tuple(tuple(r) for r in runs)


def _log_random(fmt, n, seed, fn):
    """n main-path arguments of the log family with every bit random. log and
    log2: 55% a random mantissa at a random exponent over the whole range, the
    subnormals included; 25% 1 + d with d = +-f 2^-j, j from 1 to p + 1; 20% a
    random mantissa (p + 20 random bits, rounded) at k = -1, 0 or 1, the
    cancelling cell among them. log1p: 35% a random mantissa at an exponent
    from -(p + 2) to -1, either sign; 15% uniform on the band [0.8 15/256,
    1/8], either sign; 20% positive with exponent 0 to 30; 15% positive with
    exponent 31 to emax (past the 2^-k clamp); 15% -1 + f 2^-j, j from 1 to p
    (u = 1 + x small, k down to -p)."""
    rng = _rng(fmt, seed, 1000003, fn)
    p, mw = fmt.prec, fmt.man_w
    big = 2 ** 20

    def mant():
        return 1 + Fraction(rng.getrandbits(p + 20), 2 ** (p + 20))

    def sample(e, sign=0):
        return sf.round_pack(fmt, sign, rng.getrandbits(p) | (1 << (p - 1)),
                             e - p + 1, sf.RND_RNE)[0]
    out = []
    while len(out) < n:
        r = rng.random()
        if fn != "log1p":
            if r < 0.55:
                x = sample(rng.randint(fmt.emin - mw, fmt.emax))
            elif r < 0.8:
                d = Fraction(rng.randint(1, big), big) * rng.choice((1, -1)) \
                    / 2 ** rng.randint(1, p + 1)
                x = ml._enc(fmt, 1 + d)
            else:
                x = ml._enc(fmt, mant() * Fraction(2) ** rng.randint(-1, 1))
        elif r < 0.35:
            x = sample(rng.randint(-(p + 2), -1), rng.getrandbits(1))
        elif r < 0.5:
            v = Fraction(4, 5) * SMALL + (Fraction(1, 8) - Fraction(4, 5) *
                                          SMALL) * Fraction(rng.getrandbits(
                                              p + 20), 2 ** (p + 20))
            x = ml._enc(fmt, v * rng.choice((1, -1)))
        elif r < 0.7:
            x = sample(rng.randint(0, 30))
        elif r < 0.85:
            x = sample(rng.randint(31, fmt.emax))
        else:
            x = ml._enc(fmt, -1 + Fraction(rng.randint(1, big), big)
                        / 2 ** rng.randint(1, p))
        if in_main(fmt, x, fn):
            out.append(x)
    return out


SMALL = ml.SMALL_LOG                        # 15/256: log1p's r = x path ends


def _log_placed(fmt, fn):
    """The log family's arguments where the reduction leaves |r| largest
    (the study's worstcase.py, extended): the first and last float of each
    run of RECIP_SEED cells that share a C (seed_runs), as m 2^k for log and
    log2 at k = -1, 0 and 1 with their two neighbours, and at the ends of the
    exponent range (a subnormal binade, emin, emax); for log1p as x = m 2^k - 1
    at k = -1 to 2 with neighbours (u = 1 + x is then m 2^k, the cancelling
    cell k = -1, C = 9 among them, and the reduction path's lower end), the r = x
    path's end 15/256 and 1/16, both signs, with neighbours, and the first
    k past 2^-k's clamp, p + G + 2, and its neighbours."""
    p, mw = fmt.prec, fmt.man_w
    ms = [m for _C, lo, hi in seed_runs(fmt) for m in (lo, hi)]
    out = set()
    if fn != "log1p":
        for k in (-1, 0, 1):
            for m in ms:
                b = ml._enc(fmt, m * Fraction(2) ** k)
                out.update((b - 1, b, b + 1))
        for k in (fmt.emin - mw // 2, fmt.emin, fmt.emax):
            for m in ms:
                out.add(ml._enc(fmt, m * Fraction(2) ** k))
    else:
        for k in (-1, 0, 1, 2):
            for m in ms:
                b = ml._enc(fmt, m * Fraction(2) ** k - 1)
                out.update((b - 1, b, b + 1))
        for edge in (SMALL, Fraction(1, 16)):
            for s in (1, -1):
                b = ml._enc(fmt, s * edge)
                out.update(b + d for d in range(-3, 4))
        clamp = p + ml.GUARD[fmt.name] + 2
        for k in (clamp - 1, clamp, clamp + 1, clamp + 2):
            for m in ms:
                out.add(ml._enc(fmt, m * Fraction(2) ** k))
    return sorted(x for x in out if in_main(fmt, x, fn))


def _log_weighted(fmt, n, seed, fn):
    """n arguments of the log family weighted to where its terms are
    largest, as VM1's sampler: the mantissa m within f 2^-j of an end of a
    run of seed cells (j from 3 to p - 1, 40%; from 8 to 56, 40%; exactly the
    end, 20%), at k = -1, 0 or 1 half the time and anywhere in the exponent
    range otherwise (log, log2); log1p x = m 2^k - 1 at k = -1 to 2 or beyond
    (up to p + 3), 15% at +-(15/256 + a few hundred ulps either way)."""
    rng = _rng(fmt, seed, 104729, fn)
    p, mw = fmt.prec, fmt.man_w
    ulp = Fraction(1, 2 ** (p - 1))
    ends = sorted({m for _C, lo, hi in seed_runs(fmt) for m in (lo, hi)}
                  | {Fraction(1), 2 - ulp})
    out = []
    while len(out) < n:
        b = rng.choice(ends)
        r = rng.random()
        if r < 0.4:
            d = Fraction(rng.randint(1, 10 ** 6), 10 ** 6) \
                / 2 ** rng.randint(3, p - 1)
        elif r < 0.8:
            d = Fraction(1, 2 ** rng.randint(8, max(8, min(56, p - 1))))
        else:
            d = Fraction(0)
        m = min(max(b + d * rng.choice((1, -1)), Fraction(1)), 2 - ulp)
        if fn == "log1p":
            if rng.random() < 0.15:
                x = ml._enc(fmt, rng.choice((1, -1)) * (
                    SMALL + Fraction(rng.randint(-300, 300), 2 ** (p + 3))))
            else:
                k = rng.choice((-1, 0, 0, 1, 1, 2, 3, rng.randint(4, p + 3)))
                x = ml._enc(fmt, m * Fraction(2) ** k - 1)
        else:
            k = rng.choice((-1, 0, 1, rng.randint(fmt.emin - mw, fmt.emax)))
            x = ml._enc(fmt, m * Fraction(2) ** k)
        if in_main(fmt, x, fn):
            out.append(x)
    return out


def _log_edges(fmt, fn):
    """The log family's edge lanes: log and log2 - 1 +- c ulp for c up to 16
    (the census), every power of two the exact cases sit at (the ends of the
    exponent range, the subnormals', small k, p) with two neighbours either
    side, the smallest and largest subnormal and normal with neighbours, and
    the first and last float of each run of seed cells at k = -1, 0, 1 and the
    ends; log1p - x = -1 with neighbours (the pole and the NaN below it),
    the tiny path's gate 2^-(p+2) and 2^-(p+3) and the smallest normal's,
    subnormals', their negatives, 15/256 and 1/16 (the r = x path's end and
    the reduction's), each with neighbours, u - 1 for u = 2^k at every s-th k
    from -p to p (s = max(3, p // 8): 3, 6, 14 and 29 at fp32 to fp256; the
    pool is thinned to keep the tests quick, and `mathlib_runs.py pools
    --edges` runs this same pool), the seed runs' ends for k = -1 to 2, 2^-k's
    clamp (p + G + 2) with neighbours, and the largest normal."""
    p, mw = fmt.prec, fmt.man_w
    out = set()

    def near(v, ds=(-2, -1, 0, 1, 2)):
        b = ml._enc(fmt, v)
        out.update(b + d for d in ds)
    runs = seed_runs(fmt)
    if fn != "log1p":
        out.update(sf.one_bits(fmt) + c for c in range(-16, 17))
        for k in (fmt.emin - mw, fmt.emin - mw + 1, fmt.emin - 1, fmt.emin,
                  fmt.emin + 1, -p, -3, -2, -1, 1, 2, 3, 4, 7, 8, 9, 16, p,
                  fmt.emax - 1, fmt.emax):
            near(Fraction(2) ** k)
        for b in (sf.min_normal_bits(fmt), sf.max_subnormal_bits(fmt),
                  sf.min_subnormal_bits(fmt), sf.max_normal_bits(fmt)):
            out.update(b + d for d in (-2, -1, 0, 1, 2))
        for _C, lo, hi in runs:
            for k in (-1, 0, 1, fmt.emax):
                for m in (lo, hi):
                    near(m * Fraction(2) ** k, (-1, 0, 1))
    else:
        near(Fraction(-1))
        for k in (p + 2, p + 3):
            for s in (1, -1):
                near(s * Fraction(1, 2 ** k))
        for b in (sf.min_normal_bits(fmt), sf.max_subnormal_bits(fmt),
                  sf.min_subnormal_bits(fmt)):
            for sg in (0, 1):
                bb = b | (fmt.sign_mask if sg else 0)
                out.update(bb + d for d in (-2, -1, 0, 1, 2))
        for edge in (SMALL, Fraction(1, 16)):
            for s in (1, -1):
                near(s * edge, tuple(range(-4, 5)))
        for k in range(-p, p + 1, max(3, p // 8)):
            near(Fraction(2) ** k - 1)
        for _C, lo, hi in runs:
            for k in (-1, 0, 1, 2):
                for m in (lo, hi):
                    near(m * Fraction(2) ** k - 1, (-1, 0, 1))
        clamp = p + ml.GUARD[fmt.name] + 2
        for k in (clamp - 1, clamp, clamp + 1, clamp + 2):
            near(Fraction(2) ** k)
        out.add(sf.max_normal_bits(fmt))
    return out


# ---- the bound against mpmath -----------------------------------------------

def _v_names(b):
    return ("V0", "V1", "V2") if b.meta["family"] == "triple word" \
        else ("Vh", "Vl")


def true_value(fn, xv):
    """f(x) by mpmath at the working precision of the caller."""
    if fn == "exp2":
        return mpmath.power(2, xv)
    if fn == "expm1":
        return mpmath.expm1(xv)
    if fn == "log":
        return mpmath.log(xv)
    if fn == "log2":
        return mpmath.log(xv) / mpmath.log(2)
    if fn == "log1p":
        return mpmath.log1p(xv)
    return mpmath.exp(xv)


def bound_log2(b, x):
    """log2(|V - f(x) 2^-k| / Bv) for one main-path lane of the build b:
    V from its probes (V_h + V_l, or the three words at fp32), k from Ek (the
    log family is not scaled: k = 0), the true value from mpmath at 4p + 200
    bits. None where V is exact."""
    fmt = b.fmt
    names = _v_names(b)
    scaled = b.meta.get("scaled", True)
    _res, _fl, pr = b.run(x, names + ("Bv",) + (("Ek",) if scaled else ()))
    k = pr["Ek"] - fmt.bias - b.meta["OFF"] if scaled else 0
    with mpmath.workprec(4 * fmt.prec + 200):
        T = true_value(b.meta["fn"], _mp(value(fmt, x))) * mpmath.mpf(2) ** (-k)
        V = sum(_mp(value(fmt, pr[nm])) for nm in names)
        err = abs(V - T)
        if err == 0:
            return None
        return float(mpmath.log(err / _mp(value(fmt, pr["Bv"])), 2))


def _mp(q):
    return mpmath.mpf(q.numerator) / q.denominator


def check_bound(b, xs, label="random"):
    """[finding], (worst log2(err/Bv), lanes measured): bound: every
    measured lane under 1 Bv."""
    worst, n, bad = -1e9, 0, []
    fn = b.meta["fn"]
    for x in xs:
        if not in_main(b.fmt, x, fn):
            continue
        r = bound_log2(b, x)
        n += 1
        if r is None:
            continue
        if r > worst:
            worst = r
        if r >= 0:
            bad.append((r, x))
    out = []
    if bad:
        r, x = max(bad)
        out.append(f"bound: {fn} {b.fmt.name} {sf.RND_NAMES[b.rnd]} {label}: "
                   f"{len(bad)} of {n} lanes are past the bound, the worst "
                   f"{hex(x)} at 2^{r:+.2f} of Bv")
    return out, (worst, n)


def check_budget(b, xs, label="budget", plant=None):
    """[finding], summary: budget: the first-order budget's bound
    (mathlib_budget: the method's largest error plus the rounding
    instructions' largest capacities, in Bv) under 1, and no sampled lane's
    error past it. `plant` names a fault of the tool itself
    (mathlib_budget.PLANTS), for the test that shows the second branch."""
    import mathlib_budget as MB
    s = MB.Budget(b, plant=plant).add(xs).summary()
    out = []
    where = f"budget: {b.meta['fn']} {b.fmt.name} {sf.RND_NAMES[b.rnd]} {label}"
    if s["bound"] >= 1:
        out.append(f"{where}: the budget's bound is {s['bound']:.3g} Bv "
                   f"(M {s['Mmax']:.3g} + capacities {s['S_cap']:.3g}), "
                   f"not under 1")
    if s["Emax"] > s["bound"] * 1.001:
        out.append(f"{where}: a lane's error {s['Emax']:.3g} Bv is past the "
                   f"budget's bound {s['bound']:.3g}")
    return out, s


# ---- the mark-rate law ------------------------------------------------------
#
# The law (the study's 3.4), derived from the code (parcel RC). With the bound
# inflated to 2^-(p + G'), a fragment's Bv is |V_h| BREL, BREL = 2^-(p + G')
# exactly (mathlib's bound_shift is G - G'; the planted bounds shift it, and
# the law is of the unplanted one). R1 = rnd(V_h + RD(V_l - Bv)) and
# R2 = rnd(V_h + RU(V_l + Bv)) differ - the lane is marked - exactly when
# V - Bv .. V + Bv holds a boundary of the attribute: a float under rtz, rdn
# and rup, a midpoint under rne and rmm. (The rounding of the low word widens
# the interval by 2^-(p-6) of its width at most at each end; fp32's V_l is
# V1 + V2 and its ends are the round-to-odd sums of V1 with RD(V2 - Bv) and
# RU(V2 + Bv), the same size.) Boundaries of either kind are one ulp of V
# apart and the window is 2^-5 of an ulp wide at the most, so the lane is
# marked when V is within Bv of one. With V's place u in its rounding cell
# uniform that has probability 2 Bv / ulp(V) = 2^-G' m_V, where |V| = m_V 2^E,
# m_V in [1, 2), ulp(V) = 2^(E - p + 1). (A lane at a binade's edge has an ulp
# on one side twice the other's, but its window holds one boundary all the
# same, its m_V is its own and the sum below is the same; a lane whose window
# holds the edge itself is about one in 2^(p+4) of all.) The count of marks is
# then a sum of independent Bernoulli(2^-G' m_V) lanes, whose mean is 2^-G'
# times the sum of the lanes' m_V and whose variance is the sum of p (1 - p):
# the SAMPLE'S OWN centre and sigma, from the significand of each lane's true
# value.

# A run's false-alarm rate (check_rate's rule).
RATE_ALPHA = 0.001
RATE_NEAREST = (sf.RND_RNE, sf.RND_RMM)


def rate_class(rnd):
    """The lane set an attribute marks: "nearest" for rne and rmm (a midpoint
    within the bound), "directed" for rtz, rdn and rup (a float within it)."""
    return "nearest" if rnd in RATE_NEAREST else "directed"


def rate_statistics(fns, formats, rnds=None):
    """How many independent statistics a run of rate checks judges: one a
    routine, format and class of attribute (rate_class). rtz, rdn and rup mark
    the same lanes, as do rne and rmm, so the five cells of a routine and
    format are two statistics, not five: 18 for the 45 cells of the log family
    at three formats, 36 for the committed test's 90."""
    rnds = sf.RND_MODES if rnds is None else rnds
    return len(fns) * len(formats) * len({rate_class(r) for r in rnds})


def rate_level(statistics=1, alpha=RATE_ALPHA):
    """The two-sided tail under which one statistic of a run is flagged,
    alpha / statistics (Bonferroni): a run in which nothing is wrong is
    flagged with probability at most alpha."""
    if statistics < 1:
        raise ValueError(f"a run has at least one statistic, not {statistics}")
    return alpha / statistics


def lane_cell(fmt, fn, x):
    """(E, m, u) of the true value V = f(x) of the main-path lane x: |V| =
    m 2^E with m in [1, 2), and u in [0, 1) the place of |V| in its p-bit
    rounding cell, 2^(E - p + 1) wide (0 at the float below |V|, 1 at the float
    above): the cell the in-lane test works in. mpmath at p + 96 bits with x
    exact, read from the `_mpf_` tuple: |V| = man 2^ex, E = ex + bc - 1 and
    m = man / 2^(bc - 1) for the bc bits of man, u the bits of man below its
    top p. (The exp family's lanes with a subnormal result are rounded on the
    fixed grid, a coarser cell; the in-lane test runs before it, in the scaled
    domain, in this one.)"""
    p = fmt.prec
    u_ = sf.unpack(fmt, x)
    with mpmath.workprec(p + 96):
        xv = mpmath.ldexp(mpmath.mpf(u_.m), u_.e)
        if u_.sign:
            xv = -xv
        _sign, man, ex, bc = true_value(fn, xv)._mpf_
    if not man:
        raise ValueError(f"{fn}({hex(x)}) is zero: not a main-path lane")
    man = int(man)
    m = man / (1 << (bc - 1))
    u = (man & ((1 << (bc - p)) - 1)) / (1 << (bc - p)) if bc > p else 0.0
    return ex + bc - 1, m, u


def poisson_binomial_pmf(ps, kmax):
    """[P(X = k) for k = 0 .. kmax], X the number of successes among
    independent trials of probabilities `ps`: the dynamic programme over the
    trials, f[k] <- f[k] (1 - p) + f[k - 1] p, with the entries above kmax
    dropped (which leaves those below exact). O(len(ps) kmax): about 0.75 s
    for 20,000 trials and kmax 669."""
    f = [1.0] + [0.0] * kmax
    for p in ps:
        q = 1.0 - p
        f = [a * q + b * p for a, b in zip(f, [0.0] + f)]
    return f


def pmf_top(mean, n, eps=1e-20):
    """The top of a table of P(count = k) that leaves under `eps` above it:
    the least k above `mean` at which exp(-mean) (e mean / k)^k is under `eps`,
    or n when the table can hold every count (then nothing is above it). That
    product is the multiplicative Chernoff bound on P(count >= k) for ANY sum
    of independent trials of that mean (E exp(t count) <= exp(mean (e^t - 1)),
    and Markov's inequality at t = ln(k / mean)), so P(count > top) < eps
    whatever the trials' probabilities are, at every mean."""
    if n < 1 or mean <= 0.0:
        return 0
    k = int(mean) + 1
    bound = math.log(eps)
    while k < n and k * (1.0 + math.log(mean / k)) - mean >= bound:
        k += 1
    return min(k, n)


class RateSample:
    """The lanes of uniform_m1rate(fmt, n, seed, fn) with the law of the count
    of marks that the build with the bound 2^-(p + g_inflated) |V_h| gives
    them: lane i is marked with probability p_i = 2^-g m_i (m_i the significand
    of its true value, lane_cell), independently of the others. `mean` and
    `sigma` are that law's; `tails` and `p_value` its exact tails; `rejection`
    its exact probability of a flag; `geometric_marks` the lanes it says are
    marked."""

    def __init__(self, fmt, fn, n, seed, g_inflated=6):
        self.fmt, self.fn, self.n, self.seed = fmt, fn, n, seed
        self.g = g_inflated
        self.xs = uniform_m1rate(fmt, n, seed, fn)
        self.cells = [lane_cell(fmt, fn, x) for x in self.xs]
        self.p = [m * 2.0 ** -g_inflated for _e, m, _u in self.cells]
        self.mean = math.fsum(self.p)
        self.var = math.fsum(q * (1.0 - q) for q in self.p)
        self.sigma = math.sqrt(self.var)
        self._pmf = None

    def pmf(self):
        """P(count = k) for k = 0 .. pmf_top(mean, n): what is past the table
        is under 1e-20 at every mean (Chernoff, pmf_top), or nothing when the
        table holds every count."""
        if self._pmf is None:
            self._pmf = poisson_binomial_pmf(self.p,
                                             pmf_top(self.mean, self.n))
        return self._pmf

    def tails(self, c):
        """(P(count <= c), P(count >= c)), exactly to about 1e-12; a count
        past pmf()'s table has the second as 0.0."""
        f = self.pmf()
        if c >= len(f):
            return 1.0, 0.0
        return math.fsum(f[:c + 1]), math.fsum(f[c:])

    def p_value(self, c):
        """The two-sided tail of the count c: twice the smaller tail, at most
        1."""
        lo, hi = self.tails(c)
        return min(1.0, 2.0 * min(lo, hi))

    def rejection(self, level):
        """The law's own probability that a count's two-sided tail is under
        `level`: the sum of the law over the counts flagged (the table's top
        and everything above it included). At most `level`, since the tails of
        a discrete law are conservative."""
        f = self.pmf()
        mass = math.fsum(f)
        lo = 0.0
        hi = mass
        flagged = 1.0 - mass if mass < 1.0 else 0.0
        for c, pc in enumerate(f):
            lo += pc
            if min(1.0, 2.0 * min(lo, hi)) < level:
                flagged += pc
            hi -= pc
        return flagged

    def geometric_marks(self, rnd):
        """[bool] a lane: the true-value geometry marks it. The window is
        w = m 2^-(g + 1) cells either side of |V| (Bv / ulp); directed
        attributes mark a float inside it (u < w or u > 1 - w), rne and rmm a
        midpoint (|u - 1/2| < w)."""
        out = []
        for _e, m, u in self.cells:
            w = m * 2.0 ** -(self.g + 1)
            out.append(abs(u - 0.5) < w if rnd in RATE_NEAREST
                       else (u < w or u > 1.0 - w))
        return out


@functools.lru_cache(maxsize=None)
def rate_sample(fmt, fn, n, seed, g_inflated=6):
    """The RateSample of these arguments, cached: it holds the clean sample,
    which a planted fault does not touch, and the five attributes of a cell
    share it."""
    return RateSample(fmt, fn, n, seed, g_inflated)


def check_rate(fmt, rnd, n=2000, seed=7, sigmas=None, g_inflated=6,
               plant=None, fn="exp", statistics=1, alpha=RATE_ALPHA):
    """[finding], stats: rate: the mark-rate law (the study's 3.4), held to
    the sample's own count. The bound is inflated to 2^-(p + G'), G' =
    g_inflated = 6, so that marks are common enough to count; n arguments of
    uniform_m1rate (the study used 2,000 a cell) run through the fragment.

    THE CENTRE (derived in the comment above RATE_ALPHA; check_rate_geometry
    holds it to the fragment lane for lane). A lane is marked with probability
    2^-G' m_V, m_V in [1, 2) the significand of its true value, provided the
    place of that value in its rounding cell is uniform and independent of the
    other lanes': the one premise that is measured and not derived (the entry,
    and `mathlib_runs.py rategeom`). The count then has mean 2^-G' sum(m_V) and
    variance sum(p (1 - p)), from the sample's own true values (RateSample),
    not from a law of the significand. For a log-uniform significand the mean
    of m_V is 1/ln 2 and the sum is n 2^-G' / ln 2 = n 2^(0.5288 - G'), the
    study's n 2^(0.53 - G') to 0.09%: exp's and exp2's samplers (x uniform
    makes ln V uniform) give it (20,000 lanes: 0.09% under the study's figure).
    The log family's sampler draws the exponent field uniformly, so |V| is
    about the exponent: log2's significand is uniform and its sum 3.9% over
    the study's figure, log's 2.0% and log1p's 1.5% to 2.0% under it; expm1's
    at fp64 is 1.7% over (the 5% of its lanes at x < 0 have |V| just under 1).
    The exp family's lanes with a subnormal result mark as the others do (the
    in-lane test runs in the scaled domain), and under rne and rmm a few more,
    by the fixed grid's own test: 4.3% to 4.8% more of them at fp32 and 0.9% to
    2.4% at fp64, under 0.4% of the sample's count (measured in the entry).

    THE RULE. The cell is judged by the EXACT two-sided tail of its count
    under that law (twice the smaller of P(count <= c) and P(count >= c), by
    the dynamic programme RateSample.pmf). A normal z misjudges the small
    counts the committed test runs at: it calls 0 marks of 16 expected a 4
    sigma event (6e-5) when the exact two-sided tail is 2e-7. A run of cells is
    judged together: the five attributes of a routine and format mark two lane
    sets (rtz, rdn and rup the same lanes, rne and rmm the same), so a run
    holds `statistics` independent statistics (rate_statistics: 18 for the log
    family's 45 cells, 36 for the committed test's 90), and a cell is flagged
    when its tail is under alpha / statistics (Bonferroni): a run with nothing
    wrong is flagged with probability at most `alpha`, RATE_ALPHA, 0.1% (the
    entry measures it over seeds). With `sigmas` given, the plain line
    instead: the cell is flagged beyond that many sigma of the sample's own
    mean, no multiplicity. Either way every unmarked lane must be right, and
    every marked guess is counted (the study found them all right; a wrong one
    is a finding here)."""
    G = ml.GUARD[fmt.name]
    build = ml.build(fn, fmt, rnd, bound_shift=G - g_inflated, plant=plant)
    f = build.fragment()
    smp = rate_sample(fmt, fn, n, seed, g_inflated)
    t = tally(fmt, rnd, smp.xs, evaluate_all(f, smp.xs), fn)
    c, mean, sd = len(t.marked), smp.mean, smp.sigma
    lo, hi = smp.tails(c)
    p = min(1.0, 2.0 * min(lo, hi))
    level = rate_level(statistics, alpha)
    z = (c - mean) / sd
    st = {"n": n, "marked": c, "expected": mean, "sigma": sd, "z": z,
          "p": p, "level": level, "statistics": statistics,
          "class": rate_class(rnd), "wrong": len(t.wrong),
          "guess_wrong": len(t.guess_wrong)}
    where = f"rate: {fn} {fmt.name} {sf.RND_NAMES[rnd]} (G' = {g_inflated})"
    out = []
    if sigmas is not None:
        if abs(z) > sigmas:
            out.append(f"{where}: {c} of {n} lanes marked, {mean:.1f} "
                       f"expected (sigma {sd:.1f}): {z:+.1f} sigma")
    elif p < level:
        out.append(f"{where}: {c} of {n} lanes marked, {mean:.1f} expected "
                   f"(sigma {sd:.1f}): {z:+.1f} sigma, an exact two-sided "
                   f"tail of {p:.2g}, under the {level:.2g} of this run "
                   f"(alpha {alpha:g} over {statistics} statistics)")
    if t.wrong:
        out.append(f"{where}: {len(t.wrong)} unmarked lanes are wrong")
    if t.guess_wrong:
        out.append(f"{where}: {len(t.guess_wrong)} marked guesses are wrong")
    return out, st


def check_rate_geometry(fmt, rnd, n=600, seed=5, g_inflated=6, plant=None,
                        fn="exp"):
    """[finding], stats: rategeom: the inflated build marks exactly the lanes
    whose true value the geometry puts within the bound of a boundary: for each
    lane of rate_sample(n, seed) with a normal result, the fragment's mark
    (bound 2^-(p + G') |V_h|, planted if `plant`) against RateSample.
    geometric_marks. This is the premise of check_rate's centre, lane for
    lane. The exp family's lanes with a subnormal result are left out: under
    rne and rmm the fixed grid's own test marks a few more of them."""
    G = ml.GUARD[fmt.name]
    f = ml.build(fn, fmt, rnd, bound_shift=G - g_inflated,
                 plant=plant).fragment()
    smp = rate_sample(fmt, fn, n, seed, g_inflated)
    want = smp.geometric_marks(rnd)
    extra, missing, lanes, marks = [], [], 0, 0
    for x, (e, _m, _u), w in zip(smp.xs, smp.cells, want):
        if e < fmt.emin:
            continue
        lanes += 1
        got = bool(ml.evaluate(f, x)[1] & ml.MARK)
        marks += got
        if got and not w:
            extra.append(x)
        elif w and not got:
            missing.append(x)
    st = {"lanes": lanes, "marked": marks, "extra": len(extra),
          "missing": len(missing)}
    out = []
    if extra or missing:
        out.append(f"rategeom: {fn} {fmt.name} {sf.RND_NAMES[rnd]}: "
                   f"{len(extra)} lanes of {lanes} are marked that the "
                   f"geometry does not mark and {len(missing)} are not marked "
                   f"that it does, first {_hexes(extra + missing)}")
    return out, st


# ---- the structured family --------------------------------------------------

def family_lanes(fmt, rnd, centres, G=None, fn="exp"):
    """[(x, label, what the theory demands)] for the centres and their
    neighbours, each lane once (mathlib_family.classify)."""
    import mathlib_family as F
    seen, out = set(), []
    for cen in centres:
        x0 = F.argument(fmt, cen)
        if cen[0] == "n":
            name = f"-{cen[1]} ln 2"
        elif cen[0] in ("u", "d"):
            name = f"1 {'+' if cen[0] == 'u' else '-'} {cen[1]} ulp"
        else:
            name = f"{cen[0]} 2^-{cen[1]}"
        for x, lab in [(x0, "centre")] + F.neighbours(fmt, cen, G):
            if x not in seen:
                seen.add(x)
                out.append((x, f"{name} {lab}", F.classify(fmt, rnd, x, G, fn)))
    return out


def check_family_list(committed, generated=None):
    """family: the committed centres (mathlib_family.FAMILY, or a copy a test
    has tampered with) are exactly what the theory generates."""
    import mathlib_family as F
    generated = F.generate() if generated is None else generated
    out = []
    for fn in sorted(set(committed) | set(generated)):
        cfn, gfn = committed.get(fn, {}), generated.get(fn, {})
        for fmt_name in sorted(set(cfn) | set(gfn)):
            for rnd_name in sorted(set(cfn.get(fmt_name, {})) |
                                   set(gfn.get(fmt_name, {}))):
                have = cfn.get(fmt_name, {}).get(rnd_name)
                want = gfn.get(fmt_name, {}).get(rnd_name)
                if have != want:
                    miss = sorted(set(want or ()) - set(have or ()), key=str)
                    extra = sorted(set(have or ()) - set(want or ()), key=str)
                    out.append(f"family: the committed centres of {fn} "
                               f"{fmt_name} {rnd_name} are not the theory's: "
                               f"missing {miss[:3]}, extra {extra[:3]}")
    return out


def census_run(f):
    """Tally: the study's census (mathlib_family.census, 240 arguments
    x = c 2^-e at the fragment's format; for log the 32 arguments 1 +- c ulp,
    census_log) through the fragment, against transcend's. The study's
    census.py counted the marks of these."""
    import mathlib_family as F
    xs = sorted(F.census_log(f.fmt) if f.op in ("log", "log2")
                else F.census(f.fmt))
    return tally(f.fmt, f.rnd, xs, evaluate_all(f, xs), f.op)


def check_census_empty(f):
    """census: the study's census finds no window - no lane marked, every
    lane right - which is what fp32 must show at G = 40: marks need an
    exponent from (p + G)/2 = 32 down to p = 24, an empty range."""
    t = census_run(f)
    out = []
    where = f"census: {f.op} {f.fmt.name} {sf.RND_NAMES[f.rnd]}"
    if t.marked:
        out.append(f"{where}: {len(t.marked)} of the census's {t.n} "
                   f"arguments are marked, first {_hexes(t.marked)}; the "
                   f"windows are meant to be empty")
    if t.wrong:
        out.append(f"{where}: {len(t.wrong)} census lanes are wrong "
                   f"unmarked, first {hex(t.wrong[0][0])}")
    return out, t


def check_census_counts(f, want):
    """census_counts: the study's census (240 arguments) through the
    fragment marks `want` = (under rne and rmm, under the directed three)
    lanes at this format and the decided G, every committed centre of its
    first family is among them, and no unmarked lane is wrong. The count is a
    measure of the bound's calibration: the study's 3.5 counts are at G = 46,
    and at fp64's G = 44 the directed attributes mark 39 of exp's."""
    import mathlib_family as F
    t = census_run(f)
    fmt, rnd = f.fmt, f.rnd
    expect = want[0] if rnd in (sf.RND_RNE, sf.RND_RMM) else want[1]
    where = f"census_counts: {f.op} {fmt.name} {sf.RND_NAMES[rnd]}"
    out = []
    if len(t.marked) != expect:
        out.append(f"{where}: {len(t.marked)} of the census's {t.n} "
                   f"arguments are marked, {expect} expected")
    if t.wrong:
        out.append(f"{where}: {len(t.wrong)} census lanes are wrong "
                   f"unmarked, first {hex(t.wrong[0][0])}")
    centres = {F.argument(fmt, c)
               for c in F.FAMILY[f.op][fmt.name][sf.RND_NAMES[rnd]]
               if c[0] != "n"}
    # an anchor of log1p's one-sided windows is clear itself: not a mark
    centres = {x for x in centres
               if F.classify(fmt, rnd, x, None, f.op) == "mark"}
    missing = sorted(centres - set(t.marked))
    if missing:
        out.append(f"{where}: {len(missing)} committed centres are not "
                   f"marked, first {_hexes(missing)}")
    return out


def check_family(f, centres, G=None, extra=(), deep=False):
    """[finding], stats: family: on the centres and their neighbours, on
    `extra` (the census arguments that are not centres) and, with `deep`, on
    the arguments between the first exponent a window can start at and the
    census (mathlib_family.deep_arguments), the routine marks every lane the
    theory says is inside a window, marks none that is outside or gated, and
    is right on every lane it does not mark."""
    fmt, rnd, fn = f.fmt, f.rnd, f.op
    import mathlib_family as F
    lanes = family_lanes(fmt, rnd, centres, G, fn)
    seen = {x for x, _l, _c in lanes}
    more = [(x, f"census {hex(x)}") for x in extra]
    if deep:
        more += [(x, f"deep {lab}")
                 for x, lab in F.deep_arguments(fmt, G, fn)]
    for x, lab in more:
        if x not in seen:
            seen.add(x)
            lanes.append((x, lab, F.classify(fmt, rnd, x, G, fn)))
    xs = [x for x, _l, _c in lanes]
    res = evaluate_all(f, xs)
    out = []
    st = {"lanes": len(lanes), "guess_wrong": 0, "wrong": 0}
    for w in ("mark", "clear", "either", "gated"):
        st[w] = st["marked_" + w] = 0
    tag = f"family: {fn} {fmt.name} {sf.RND_NAMES[rnd]}"
    for (x, lab, want), (bits, fw) in zip(lanes, res):
        marked = bool(fw & ml.MARK)
        gb, gf = golden(fmt, rnd, x, fn)
        st[want] += 1
        if marked:
            st["marked_" + want] += 1
            if (bits, fw & 0x1F) != (gb, gf):
                st["guess_wrong"] += 1
        elif (bits, fw) != (gb, gf):
            st["wrong"] += 1
            out.append(f"{tag}: {lab} ({hex(x)}) is unmarked and wrong: got "
                       f"({bits:#x}, {fw:#x}), want ({gb:#x}, {gf:#x})")
        if want == "mark" and not marked:
            out.append(f"{tag}: {lab} ({hex(x)}) is inside a window, "
                       f"d = {F.distance(fmt, rnd, x, G, fn):.3f}, and not "
                       f"marked")
        if want in ("clear", "gated") and marked:
            where = "gated" if want == "gated" else "outside every window"
            out.append(f"{tag}: {lab} ({hex(x)}) is {where} and marked")
    return out[:8], st


def nofamily_lanes(fmt, deep=True, fn="exp2"):
    """The lanes of exp2 or log2 that would be a family if it had one. exp2:
    the study's census (c 2^-e), the deep arguments below it (with `deep`),
    and the floats next to the integers 1, 2, 3, 4, 7, 8, 16, 100, p and
    -emin, both signs, at 1, 2, 4 and 8 ulps either side - the exact cases
    2^N, where a window would sit. log2: the 32 arguments 1 +- c ulp
    (census_log), the deep ones 1 +- 2^a ulp and 3, 5 times it (with `deep`),
    and the floats next to the powers of two 2^k and 2^-k for k = 1, 2, 3, 4,
    7, 8, 16, p and -emin, at 1 to 16 ulps either side - the exact cases
    2^k, where log2 is k and a window would sit."""
    import mathlib_family as F
    if fn == "log2":
        out = set(F.census_log(fmt)) | (
            {x for x, _l in F.deep_arguments(fmt, None, "log2")} if deep
            else set())
        for k in (1, 2, 3, 4, 7, 8, 16, fmt.prec, -fmt.emin):
            for sg in (1, -1):
                b = ml._enc(fmt, Fraction(2) ** (sg * k))
                out.update(b + d for d in (-16, -8, -4, -2, -1, 1, 2, 4, 8,
                                           16))
        return sorted(x for x in out if in_main(fmt, x, "log2"))
    out = set(F.census(fmt)) | ({x for x, _l in F.deep_arguments(fmt)}
                                if deep else set())
    for n in (1, 2, 3, 4, 7, 8, 16, 100, fmt.prec, -fmt.emin):
        for sg in (1, -1):
            b = ml._enc(fmt, sg * n)
            out.update(b + d for d in (-8, -4, -2, -1, 1, 2, 4, 8))
    return sorted(x for x in out if in_main(fmt, x, "exp2"))


def check_nofamily(f):
    """nofamily: exp2 and log2 have no structured family (the study's 3.5;
    the committed list is empty at every format and attribute,
    mathlib_family): the census, the deep arguments and the floats next to
    the exact cases are all unmarked and equal to transcend's, and the theory
    agrees - none is within the bound of a boundary. The deep arguments,
    which pin the windows' lower edge, are run under rne and rtz."""
    import mathlib_family as F
    fmt, rnd = f.fmt, f.rnd
    xs = nofamily_lanes(fmt, deep=rnd in (sf.RND_RNE, sf.RND_RTZ), fn=f.op)
    t = tally(fmt, rnd, xs, evaluate_all(f, xs), f.op)
    where = f"nofamily: {f.op} {fmt.name} {sf.RND_NAMES[rnd]}"
    out = []
    if t.marked:
        out.append(f"{where}: {len(t.marked)} of {t.n} lanes are marked, "
                   f"first {_hexes(t.marked)}; {f.op} has no family")
    if t.wrong:
        out.append(f"{where}: {len(t.wrong)} lanes are wrong unmarked, first "
                   f"{hex(t.wrong[0][0])}")
    near = [x for x in xs if F.classify(fmt, rnd, x, None, f.op) in
            ("mark", "either")]
    if near:
        out.append(f"{where}: the theory puts {len(near)} of the {t.n} "
                   f"lanes within the bound of a boundary, first "
                   f"{_hexes(near)}")
    return out, t


# ---- invariants and constants, as findings ----------------------------------

def check_invariants(f, **kw):
    return [f"invariants: {s}" for s in ml.invariants(f, **kw)]


def check_constants(**kw):
    lines, findings = ml.check_constants(**kw)
    return [f"constants: {s}" for s in findings], lines


# ---- the fragment's shape, its sums and its instrumented form ---------------

# The design's ALU opcodes, by name. No augmented addition: R21's AUGADD and
# AUGERR are control instructions, not ALU opcodes, so a fragment's body
# cannot hold one (revision 8's question 9); and none of min, max, copysign,
# RSQRT_SEED or IMUL, which the design does not use (the exp family uses no
# seed; the log family's reduction reads RECIP_SEED). expm1 has no fixed grid
# and so no tininess compare: it holds every opcode but CMPLT. The log family
# (MEASURED, the same at every format and attribute): log and log2 hold 15
# opcodes - no compare but CMPEQ and ICMPLT, no shift but ISHR - and log1p 18,
# with CMPLT (x < -1), ISHL and ISUB (2^-k).
ALU_OPS = frozenset({
    "fma", "add", "sub", "mul", "neg", "abs", "select", "cmplt", "cmple",
    "cmpeq", "iand", "ior", "ixor", "iadd", "isub", "ishl", "ishr",
    "icmplt"})
LOG_OPS = frozenset({
    "fma", "add", "sub", "mul", "neg", "abs", "select", "cmpeq", "iand",
    "ior", "ixor", "iadd", "ishr", "icmplt", "recip_seed"})
ALU_OPS_BY_FN = {"exp": ALU_OPS, "exp2": ALU_OPS,
                 "expm1": ALU_OPS - {"cmplt"},
                 "log": LOG_OPS, "log2": LOG_OPS,
                 "log1p": LOG_OPS | {"cmplt", "ishl", "isub"}}

# The error-free sums the builders make, (Fast2Sums, where the exponents are
# ordered, and TwoSums elsewhere), by routine and format: nine and one in the
# double-word exp (the study's table of augadd, 5.3), 20 and 18 in fp32's
# triple word; exp2 has no TwoSum in its double-word reduction, and expm1 two
# (the reduction's and T_h - 2^-k); at fp32 exp2 holds 21 and 15 and expm1 22
# and 23 (MEASURED, Build.meta). The log family's (MEASURED, Build.meta): at
# the double word K + 3 Fast2Sums - the K head steps and the sum's three - and
# one TwoSum (log: A + r Y), none (log2) or two (log1p: and 1 + x); K is 11 at
# fp64 and 12 at fp128 and fp256. At fp32 log holds 25 and 19, log2 29 and 18,
# log1p 25 and 21.
EFT_COUNTS = {("exp", "fp32"): (20, 18), ("exp", "dw"): (9, 1),
              ("exp2", "fp32"): (21, 15), ("exp2", "dw"): (9, 0),
              ("expm1", "fp32"): (22, 23), ("expm1", "dw"): (10, 2),
              ("log", "fp32"): (25, 19), ("log2", "fp32"): (29, 18),
              ("log1p", "fp32"): (25, 21),
              ("log", "fp64"): (14, 1), ("log", "fp128"): (15, 1),
              ("log", "fp256"): (15, 1), ("log2", "fp64"): (14, 0),
              ("log2", "fp128"): (15, 0), ("log2", "fp256"): (15, 0),
              ("log1p", "fp64"): (14, 2), ("log1p", "fp128"): (15, 2),
              ("log1p", "fp256"): (15, 2)}


def eft_key(fn, fmt):
    if fn in LOG_FUNCS:
        return (fn, fmt.name)
    return (fn, "fp32" if fmt.name == "fp32" else "dw")


def check_shape(f, want):
    """shape: the fragment's (instructions, bank words, values live) are the
    pinned `want`: a change of any of them is a change of design."""
    got = (len(f), len(f.words), f.live_max())
    if got == tuple(want):
        return []
    return [f"shape: {f.op} {f.fmt.name} {sf.RND_NAMES[f.rnd]}: {got[0]} "
            f"instructions, {got[1]} words, {got[2]} values live; the pinned "
            f"shape is {want[0]}, {want[1]}, {want[2]}"]


def check_sums(b, f=None):
    """sums: the fragment's opcodes are exactly the design's ALU set
    (ALU_OPS_BY_FN), so there is no augmented addition in it and no opcode
    the design does not use, and the builder made the design's number of
    Fast2Sums and TwoSums (EFT_COUNTS)."""
    f = b.fragment() if f is None else f
    fn = b.meta["fn"]
    where = f"sums: {fn} {b.fmt.name} {sf.RND_NAMES[b.rnd]}"
    names = {sf.OP_NAMES.get(op, f"opcode {op}") for op, _r, _s in f.body}
    out = []
    if names != ALU_OPS_BY_FN[fn]:
        out.append(f"{where}: the opcodes are not the design's ALU set: "
                   f"outside it {sorted(names - ALU_OPS_BY_FN[fn])}, missing "
                   f"{sorted(ALU_OPS_BY_FN[fn] - names)}")
    got = (b.meta["fast_two_sum"], b.meta["two_sum"])
    want = EFT_COUNTS[eft_key(fn, b.fmt)]
    if got != want:
        out.append(f"{where}: {got[0]} Fast2Sums and {got[1]} TwoSums, the "
                   f"design has {want[0]} and {want[1]}")
    return out


def check_specialised(b, f=None, xs=None):
    """specialised: the fragment (b.fragment(), or `f`) is in C4's
    specialised form, which cftc's internal check will instantiate - C4's
    specialise() leaves it as it is - and the instrumented form beside it,
    the unpruned body the budget reads, agrees with it: no shorter than the
    fragment, a phase for every instruction, the probes the budget reads,
    and the same (result, flag word) on every lane of `xs` (a ninth of the
    pools, by default)."""
    fmt = b.fmt
    f = b.fragment() if f is None else f
    where = f"specialised: {b.meta['fn']} {fmt.name} {sf.RND_NAMES[b.rnd]}"
    out = []
    g = routines.specialise(f)
    if (g.body, g.result, g.flags, g.words) != \
            (f.body, f.result, f.flags, f.words):
        out.append(f"{where}: specialise() changes the fragment, "
                   f"{len(f.body)} instructions to {len(g.body)}: it is not "
                   f"in the specialised form")
    if len(b.body) < len(f.body):
        out.append(f"{where}: the unpruned body has {len(b.body)} "
                   f"instructions, fewer than the fragment's {len(f.body)}")
    if len(b.phase_of) != len(b.body):
        out.append(f"{where}: phase_of has {len(b.phase_of)} entries for "
                   f"{len(b.body)} instructions")
    need = ("V0", "V1", "V2", "Vh", "Bv") \
        if b.meta["family"] == "triple word" else ("Vh", "Vl", "Bv")
    if b.meta.get("scaled", True):          # the log family is not scaled
        need += ("Ek",)
    lost = [k for k in need if k not in b.probes]
    if lost:
        out.append(f"{where}: the instrumented form lacks the probes {lost}")
    xs = list(pools(fmt))[::9] if xs is None else xs
    bad = [x for x in xs if b.run(x)[:2] != ml.evaluate(f, x)]
    if bad:
        out.append(f"{where}: the instrumented form and the fragment differ "
                   f"on {len(bad)} of {len(xs)} lanes, first {hex(bad[0])}")
    return out


def check_reorder(b, f=None):
    """reorder: the scheduled fragment (b.fragment(), or `f`) is the design's
    own order's, reordered and nothing more: the order-free digest of its
    dataflow graph (mathlib.dag_digest) is that of b.fragment(schedule=False),
    it is a permutation of the same instructions and the same words, every
    instruction comes after what it reads (invariants), and it keeps no more
    values live than the design's order does."""
    f = b.fragment() if f is None else f
    g = b.fragment(schedule=False)
    where = f"reorder: {b.meta['fn']} {b.fmt.name} {sf.RND_NAMES[b.rnd]}"
    out = []
    if len(f.body) != len(g.body) or f.words != g.words:
        out.append(f"{where}: {len(f.body)} instructions and {len(f.words)} "
                   f"words, the design's order has {len(g.body)} and "
                   f"{len(g.words)}")
    bad = [s for s in ml.invariants(f, live_cap=None)
           if "before it is defined" in s]
    if bad:
        out.append(f"{where}: not a topological order: {bad[0]}")
        return out
    if ml.dag_digest(f) != ml.dag_digest(g):
        out.append(f"{where}: the dataflow graph is not the design's: the "
                   f"digests differ")
    if f.live_max() > g.live_max():
        out.append(f"{where}: {f.live_max()} values live, the design's "
                   f"order keeps {g.live_max()}")
    return out


# ---- the fixed grid's rounding, on states no argument is known to reach -----

def check_fixed_grid(b, grid_bits=(16, 8)):
    """fixed_grid: the fixed grid's one rounding of a result that may be
    subnormal, on states of (V_h, V_l) that no argument is known to reach.

    At k = emin - p + 1 + g the result's grid, in the scaled domain V lives
    in, is u = 2^-g, and V_h = 1 + u/2 sits exactly on a half-grid point.
    V_l = +-8 Bv: |V_l| > Bv, so the fixed grid's own test (it marks only
    where |V_l| <= Bv) does not mark, and V_l is under half an ulp of the
    remainder u/2, so a sum rounded to nearest keeps nothing of it. The grid
    point is then decided by the sign of V_l alone, which round-to-odd of
    the remainder plus V_l keeps and round-to-nearest loses: the tie goes to
    even (rne) or away from zero (rmm), wrong for one sign of V_l each, and
    right for the directed attributes. The routine is run through its own
    instructions with V_h, V_l and the exponent handed to it (Build.run's
    `over`) and must give the correct rounding of V 2^k under its attribute,
    exact arithmetic (mathlib._enc), unmarked. The argument is 1 (exp) or
    1.5 (exp2: 1 is an integer, an exact lane, whose flag word is zero
    whatever the mark says)."""
    fmt, rnd, p = b.fmt, b.rnd, b.fmt.prec
    tw = b.meta["family"] == "triple word"
    x = ml._enc(fmt, Fraction(3, 2)) if b.meta["fn"] == "exp2" \
        else sf.one_bits(fmt)
    vl_mag = Fraction(1, 2 ** (p + b.meta["G"] - 3))
    out = []
    for g in grid_bits:
        k = fmt.emin - p + 1 + g
        vh = 1 + Fraction(1, 2 ** (g + 1))
        for sign in (1, -1):
            vl = sign * vl_mag
            over = {"Ek": k + fmt.bias + b.meta["OFF"]}
            if tw:
                over.update(V0=ml._enc_exact(fmt, vh),
                            V1=ml._enc_exact(fmt, vl), V2=0)
            else:
                over.update(Vh=ml._enc_exact(fmt, vh),
                            Vl=ml._enc_exact(fmt, vl))
            bits, fw, _pr = b.run(x, over=over)
            want = ml._enc(fmt, (vh + vl) * Fraction(2) ** k, rnd)
            tag = (f"fixed_grid: {b.meta['fn']} {fmt.name} "
                   f"{sf.RND_NAMES[rnd]} k = emin - {fmt.emin - k}, V_l "
                   f"{'>' if sign > 0 else '<'} 0")
            if bits != want:
                out.append(f"{tag}: the result is {bits:#x}, the rounding of "
                           f"V 2^k is {want:#x}")
            if fw & ml.MARK:
                out.append(f"{tag}: marked, though |V_l| is 8 Bv")
    return out


# ---- constants read from outside the generator ------------------------------

def _role_value(fmt, b, role):
    """The exact value of the word the build holds for `role`, None if it
    holds none (a plant can leave a constant out)."""
    ref = b.roles.get(role)
    return None if ref is None else ml._dec(fmt, b.words[ref[1]])


def check_spot(builder=None, formats=FORMATS, rnd=sf.RND_RNE, ln2=None,
               enclosure=None, fn="exp"):
    """spot: constants read against values the generator did not make. ln 2
    as the generator derives it (`ln2`, mathlib._ln2() by default) against
    an enclosure from the atanh series in integers (`enclosure` = (lo, hi),
    3,200 bits by default); and, in each format's build (`builder(fmt, rnd)`,
    mathlib.build_exp by default), the table's high words TH_j (T_j's first
    word at fp32) within half an ulp of 2^(j/8), enclosed by an integer 8th
    root, and, for exp and expm1, the Cody-Waite words' sum within 2^-2p of
    ln 2/8, for exp2 ln 2's words' sum within 2^-2p of ln 2. The log family:
    the table's high words within half an ulp of log(16/C), enclosed by the
    atanh series in integers, and the words of ln 2 (log, log1p) or 1/ln 2
    (log2) summing to it within 2^-2p. `--check` (mathlib.check_constants)
    asks every word its rounding rule; this is the short look that shares
    nothing with the generator."""
    lo, hi = ml._check_ln2() if enclosure is None else enclosure
    derived = ml._ln2() if ln2 is None else ln2
    out = []
    if hi - lo >= Fraction(1, 2 ** 3180):
        out.append("spot: the independent enclosure of ln 2 is wider than "
                   "2^-3180")
    if abs(derived - lo) >= Fraction(1, 2 ** 2990):
        out.append("spot: the derived ln 2 is not the independent "
                   "enclosure's, within 2^-2990")
    build = builder or (lambda fmt, r: ml.build(fn, fmt, r))
    for fmt in formats:
        b = build(fmt, rnd)
        p = fmt.prec
        half = Fraction(1, 2 ** p)
        logs = fn in LOG_FUNCS
        for j in range(N):
            if logs:
                tlo, thi = ml._check_log16(16 if j == 0 else 8 + j)
                role = f"L{j}_0" if fmt is FP32 else f"LH{j}"
                what = f"log(16/{16 if j == 0 else 8 + j})"
            else:
                tlo, thi = ml._check_two_to_eighth(j)
                role = f"T{j}_0" if fmt is FP32 else f"TH{j}"
                what = f"2^({j}/8)"
            w = _role_value(fmt, b, role)
            if w is None:
                out.append(f"spot: {fmt.name}: the build holds no word "
                           f"{role}")
            elif not tlo - half <= w <= thi + half:
                out.append(f"spot: {fmt.name}: the table's high word of "
                           f"{what} is {float(w)!r}, over half an ulp "
                           f"from it")
        # the log family's constant: ln 2 in three words (log, log1p), 1/ln 2
        # in two or three (log2), the words signed as the build holds them
        if logs:
            if fn == "log2":
                tlo, thi = ml._check_inv_ln2()
                signed = ((("IL2_0", 1), ("NIL2_1", -1), ("IL2_2", 1))
                          if fmt is FP32 else (("IL2H", 1), ("NIL2L", -1)))
            else:
                tlo, thi = lo, hi
                signed = ((("LN2_0", 1), ("LN2_1", 1), ("LN2_2", 1))
                          if fmt is FP32 else
                          (("LN2H", 1), ("LN2M", 1), ("LN2L", 1)))
            words = [(r, sg, _role_value(fmt, b, r)) for r, sg in signed]
            gone = [r for r, _sg, v in words if v is None]
            if gone:
                out.append(f"spot: {fmt.name}: the build holds no word "
                           f"{', '.join(gone)}")
                continue
            off = sum(sg * v for _r, sg, v in words) - (tlo + thi) / 2
            if abs(off) > Fraction(1, 2 ** (2 * p)):
                out.append(f"spot: {fmt.name}: the words of "
                           f"{'1/ln 2' if fn == 'log2' else 'ln 2'} sum to "
                           f"{float(off):+.3g} off, past 2^-{2 * p}")
            continue
        # ln 2/8 as the build holds it: C1 (stored negated), C2, C3 at the
        # double word's formats; five words at fp32. exp2 holds ln 2 itself:
        # the high word, the negated low words
        if fn == "exp2":
            scale = 1
            if fmt is FP32:
                signed = (("LN2_0", 1), ("NLN2_1", -1), ("LN2_2", 1))
            else:
                signed = (("LN2H", 1), ("NLN2L", -1))
        else:
            scale = N
            if fmt is FP32:
                signed = (("NL1", -1), ("NL2", -1), ("NL3", -1), ("L4", 1),
                          ("NL5", -1))
            else:
                signed = (("NC1", -1), ("C2", 1), ("C3", 1))
        words = [(r, sg, _role_value(fmt, b, r)) for r, sg in signed]
        gone = [r for r, _sg, v in words if v is None]
        if gone:
            out.append(f"spot: {fmt.name}: the build holds no Cody-Waite "
                       f"word {', '.join(gone)}")
            continue
        off = sum(sg * v for _r, sg, v in words) - (lo + hi) / (2 * scale)
        if abs(off) > Fraction(1, 2 ** (2 * p)):
            out.append(f"spot: {fmt.name}: the Cody-Waite words sum to "
                       f"ln 2/{scale} {float(off):+.3g} off, past 2^-{2 * p}")
    return out


# ---- RECIP_SEED's cells (the log family's reduction) ------------------------

def check_recip(fmt=None, entry=None):
    """recip: RECIP_SEED's 512 cells, at one format or all four
    (mathlib._check_recip_cells): the instruction gives the table's value at
    both ends of every cell, C = round(16 seed) takes every value from 8 to 16
    and none outside, and max |r| of r = m' c - 1 (c = C/16; m' = m/2, c = 1
    where C = 8 wraps) is under the plan's RHO_LOG, with log1p's 15/256 under it
    too. `entry` replaces the table's definition (mathlib._seed_entry), for
    the test that plants a fault in it."""
    out = []
    for fm in (FORMATS if fmt is None else (fmt,)):
        found, _rmax, cs = ml._check_recip_cells(fm, entry or ml._seed_entry)
        out += [f"recip: {s}" for s in found]
        if cs != set(range(8, 17)):
            out.append(f"recip: RECIP_SEED at {fm.name}: C takes "
                       f"{sorted(cs)}, not every value from 8 to 16")
    return out
