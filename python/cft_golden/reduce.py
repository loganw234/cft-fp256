# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Reductions: sum and dot, with the tree shape fixed by element index.

docs/DETERMINISM.md already committed to the hard part of this before a
line of it existed:

    When reduction ops land, their tree shape is fixed by element
    index, never by arrival time or lane availability.

That sentence is the whole design. Everything below is what it forces.

THE TREE

The shape is a binary tree over the half-open index range, split at the
largest power of two strictly inside it:

    T(lo, hi) = xs[lo]                        if hi - lo == 1
              = add(T(lo, mid), T(mid, hi))   mid = lo + 2**floor(log2(hi-lo-1))

One function, `split`, is the only place the shape is written down.
Anything that needs to agree about the tree - the software backend, the
sequencer, the RTL, a host partitioning across tiles - calls it rather
than re-deriving it, because a reduction where two implementations
disagree about the shape is not a reduction, it is two answers with the
same name.

WHY THE POWER OF TWO AND NOT THE MIDPOINT

The first version of this split at the midpoint, which is the obvious
balanced tree. It is a perfectly good tree and it is index-fixed, so it
satisfied the contract. It is also not streamable, and that turned out
to matter more.

The natural hardware for a reduction is a binary-counter accumulator
stack: hold a partial result per level, add each arriving element into
level 0, and carry upward whenever a level is already occupied. One add
per element, ceil(log2 n) registers, no index arithmetic at all. That
machine produces the power-of-two split exactly - and produces the
midpoint split only when n happens to be a power of two. At n = 3, 5,
6, 7, 9, 11 the two disagree.

So the choice was between a tree the hardware wants and a tree that
merely looks tidier, made before any hardware existed. `stream_reduce`
below is the accumulator algorithm written out, and a test asserts it
agrees with the recursive definition for every n up to several hundred.
That function is the RTL's specification.

Depth is still ceil(log2 n), so the accuracy argument is unchanged -
this is textbook pairwise summation, with error growing as log n rather
than n. That is a happy side effect and NOT the reason for the shape:
the reason is that it is a pure function of the index range, so it
cannot vary with how many tiles ran, how fast they were, or which
finished first.

The final combine is the part that is easy to get wrong. Leftover
accumulator levels are folded LOWEST FIRST, right-associating outward,
so the largest (and lowest-indexed) subtree ends up outermost:

    r = acc[j0]; then r = add(acc[j], r) for each higher occupied j

Folding the other way is also a fixed shape, and also wrong - it is not
the tree this file defines, and it disagrees at n = 7.

WHY THERE IS NO PADDING

The obvious hardware-friendly move - round n up to a power of two and
pad with +0.0 - is wrong, and quietly so. Adding +0.0 is not the
identity on this type: under roundTiesToEven, (-0.0) + (+0.0) is +0.0,
so a reduction whose true result is negative zero would come back
positive as soon as n stopped being a power of two. Padding also
perturbs the directed attributes, where the sign of an exact
cancellation depends on the attribute (754-2019 6.3).

So the tree is defined over the exact n, with odd sizes giving a
slightly lopsided tree. A hardware walker handles that the same way
this function does: by looking at the index range, which it has.

MULTI-TILE, AND WHY THE SLICING IS DIFFERENT FROM ELEMENTWISE

For an elementwise op, any partition of [0, n) gives the same answer, so
libcft slices evenly and never thinks about it. A reduction cannot do
that: a partial sum is only reusable if its range is exactly a node of
the canonical tree.

`canonical_ranges(n, parts)` produces those nodes - it cuts the top
log2(parts) levels of the tree - and combining the partials with the
same tree over `parts` elements reproduces T(0, n) exactly. That is why
it is restricted to powers of two: cutting the top k levels yields 2**k
nodes, and no other count corresponds to a clean cut.

TWO EDGES, STATED RATHER THAN PAPERED OVER

n == 1 performs zero additions, so the result is the input verbatim and
no flags are raised - including for a signalling NaN, which a reduction
over two elements would have quieted and flagged. This is the honest
reading of "a tree of adds": with one leaf there are no adds. It is
tested rather than left to be discovered.

n == 0 is +0.0 with no flags, the additive identity, and the only result
that is not a function of any input.

DOT

dot is the same tree over rounded products, so

    dot(a, b) == sum(mul(a, b))

exactly, flags included - a composition property that is worth having
because it makes dot testable against machinery that already works, and
because it means a caller who needs the pieces can have them without
changing the answer. It is NOT an exact-product accumulation (the
754-2019 augmented-arithmetic style, one rounding at the end). That is a
genuinely different and much more expensive operation; if it is ever
wanted it gets its own opcode rather than quietly redefining this one.

THE REST OF CLAUSE 9.4 (added 2026-09-03, part of the 0.6 step)

754-2019 9.4 lists seven reductions. sum and dot are two of them; the
other five are here, on the same terms - one pinned tree, one rounding
per node, the caller's attribute at every node.

sumSquare and sumAbs are DEFINITIONALLY compositions of what is above:

    sumSquare(x) == dot(x, x)          node for node
    sumAbs(x)    == sum(|x|)           node for node

with one exception written into 9.4 and nowhere else - the standard
orders the special values differently for these two than for sum and
dot:

    "For sumSquare and sumAbs, if any operand element is an infinity,
     +inf is returned. Otherwise, if any operand element is a NaN a
     quiet NaN is returned."                                   (9.4)

where sum and dot say NaN first. Infinity therefore outranks NaN here,
and the tree cannot produce that: a NaN reaching an add propagates. So
the composition is preceded by a pre-pass, and it fires ONLY when the
vector holds an infinity AND a NaN - the one input on which the tree's
own answer would be a quiet NaN where 9.4 asks for +inf. With an
infinity and no NaN the tree already returns +inf on its own (every
term of either operation is a square or a magnitude, so no term is
negative and no inf - inf can arise), so nothing is overridden and the
two identities above hold verbatim. That exclusion is the whole of it,
and it is tested from both sides.

THE SCALED PRODUCTS

    scaledProd(p, n) returns {pr, sf} so that scaleB(pr, sf) is an
    implementation-defined approximation to prod(p_i)             (9.4)

"implementation-defined" is exactly what a determinism contract may not
leave alone, so this pins it:

  - The SAME index-shaped tree. A node multiplies its two children's
    significands under the caller's attribute - one rounding - and adds
    their scales.
  - Every node's value is carried as a pair (significand, scale) with
    the significand in +-[1, 2) and the scale an exact integer. After
    each multiply the binade is extracted back out: |m_L * m_R| < 4, so
    the extraction is a shift of 0, 1 or 2 binades and is EXACT (a
    power-of-two scaling of a normal number in [1, 4]).
  - The leaf is that same extraction applied to the element, which is
    exact for every finite non-zero operand, subnormals included - a
    subnormal's normalised significand always fits, because it has
    fewer significant bits than the format holds.

The invariant does the work the standard asks for: an operand of the
multiply is always in +-[1, 2), so the product is always in +-[1, 4),
which cannot overflow or underflow at any rung of the ladder. Hence

    "In the absence of any of the above, the scaled result, pr, shall
     not be affected by overflow or underflow."                  (9.4)

holds by construction rather than by testing, and

    "These operations should not signal the divideByZero exception,
     even if implemented with logB."                             (9.4)

is free: the binade comes out of the encoding, and a zero never reaches
the tree at all.

scaledProdSum and scaledProdDiff are the product of (p_i + q_i) and of
(p_i - q_i). The leaf sum or difference is ONE contract rounding in the
caller's attribute - so those two, and only those two, can signal
overflow or underflow, from the addition rather than from the product -
and its result is then the factor the rules above see. That makes them
compositions too:

    scaledProdSum(p, q)  == scaledProd(add(p, q))  + the adds' flags
    scaledProdDiff(p, q) == scaledProd(sub(p, q))  + the subs' flags

THE SCALE, AND ITS RANGE

sf is an int64. The tree accumulates it as a sequence of int64
additions, and an addition that would leave the int64 range makes the
operation signal invalid and return a quiet NaN for pr, which is what
9.4 requires:

    "If the scale factor is too large in magnitude to be represented
     exactly in the format of sf, then these operations shall signal
     the invalid operation exception and by default return quiet NaN
     for pr, and also for sf if integralFormat is a floating-point
     format."                                                    (9.4)

integralFormat here is int64, which is not a floating-point format, so
sf still needs a value and gets 0. The guard is unreachable in
practice: a leaf contributes at most emax + p - 1 = 262,378 to the
magnitude at fp256 and a node at most 2, so a vector would need about
3.5e13 elements - 1.1 petabytes of fp256 - to reach it. It is stated
and implemented anyway, because "cannot happen" is not a result.
"""

from .formats import FpFormat
from .softfloat import (
    FLAG_INEXACT, FLAG_INVALID, RND_RNE, add as _add, mul as _mul,
    sub as _sub, fabs as _fabs, inf_bits, one_bits, qnan_bits, unpack,
    zero_bits, _check_mode,
)

__all__ = [
    "OP_SUM", "OP_DOT", "OP_SUMSQ", "OP_SUMABS",
    "REDUCE_OPS", "REDUCE_OP_NAMES",
    "SP_PROD", "SP_PROD_SUM", "SP_PROD_DIFF",
    "SCALED_KINDS", "SCALED_KIND_NAMES", "SCALE_MIN", "SCALE_MAX",
    "split", "tree_adds", "canonical_ranges",
    "reduce_bits", "fsum", "fdot", "fsumsq", "fsumabs", "combine",
    "stream_reduce",
    "norm_split", "scaled_prod", "ScaleOverflow",
]

# Opcodes. docs/DETERMINISM.md reserves 15 and everything from 24 up,
# and says reductions land there. 24 and 25 are the first two free.
#
# They share the numbering space with the elementwise ops so the
# device's opcode field stays one field, but they do NOT share the
# elementwise calling convention - n inputs produce one output - which
# is why libcft exposes them through cft_reduce() rather than cft_run().
OP_SUM = 24
OP_DOT = 25

# The other two 9.4 sum reductions, appended 2026-09-03 - never
# inserted, never reordered: an opcode number is on the wire and in
# every published vector set. 28 and 29 were the next unassigned codes
# after the divide/sqrt seeds took 26 and 27, so docs/DETERMINISM.md's
# "everything from 28 up is unassigned" now reads 30.
#
# They take opcode numbers although no tile streams them, for the same
# reason CFT_DOT has one: they are issued through cft_reduce(), whose
# first argument is an opcode, and a caller naming an operation should
# not have to know which of them the accumulator happens to implement.
# Both compose from what the tile already streams - see fsumsq/fsumabs.
OP_SUMSQ = 28
OP_SUMABS = 29

REDUCE_OPS = (OP_SUM, OP_DOT, OP_SUMSQ, OP_SUMABS)
REDUCE_OP_NAMES = {OP_SUM: "sum", OP_DOT: "dot",
                   OP_SUMSQ: "sumsq", OP_SUMABS: "sumabs"}

# The scaled products. NOT opcodes: they return a pair, so they cannot
# come back through cft_reduce()'s one-element output, and no tile
# accumulator can carry them. They are named library entry points on
# the host, the shape every other pair-returning or host-only operation
# in this contract takes.
SP_PROD = 0
SP_PROD_SUM = 1
SP_PROD_DIFF = 2

SCALED_KINDS = (SP_PROD, SP_PROD_SUM, SP_PROD_DIFF)
SCALED_KIND_NAMES = {SP_PROD: "scaledProd",
                     SP_PROD_SUM: "scaledProdSum",
                     SP_PROD_DIFF: "scaledProdDiff"}

# integralFormat for the scale factor: a two's-complement int64, which
# is what the C entry points return and what the header pins.
SCALE_MIN = -(1 << 63)
SCALE_MAX = (1 << 63) - 1


def split(lo: int, hi: int) -> int:
    """Where a tree node divides. The one definition of the shape.

    The largest power of two strictly less than the range length, so the
    LEFT child is always a perfect subtree and the right child carries
    the remainder: T(0,5) is add(T(0,4), xs[4]). That is what makes the
    tree equal to a streaming binary-counter accumulation - see the
    module docstring and `stream_reduce`.
    """
    n = hi - lo
    if n < 2:
        raise ValueError("split() needs a range of at least two elements")
    return lo + (1 << ((n - 1).bit_length() - 1))


def tree_adds(n: int):
    """Every add the tree performs, as (lo, mid, hi), children first.

    Exists so a test can assert the SHAPE directly rather than inferring
    it from results, and so an RTL walker has something to be checked
    against. Post-order: a node is emitted only after both its children,
    which is the order any evaluator must respect.
    """
    if n < 0:
        raise ValueError("n must not be negative")
    out = []

    def walk(lo, hi):
        if hi - lo < 2:
            return
        mid = split(lo, hi)
        walk(lo, mid)
        walk(mid, hi)
        out.append((lo, mid, hi))

    walk(0, n)
    return out


def canonical_ranges(n: int, parts: int):
    """The `parts` index ranges that are exact nodes of T(0, n).

    Cuts the top log2(parts) levels. Combining the partial results with
    `combine` reproduces T(0, n) bit for bit, which is what lets a
    reduction be split across tiles without the tile count reaching the
    answer.

    The count is NOT bounded by `parts`, in either direction. Fewer
    come back when n is too small to split that far - a range of one
    element cannot be cut. But MORE come back whenever n is a power of
    two plus a remainder, because a level cut of this tree splits the
    perfect left subtree and leaves the remainder beside it: parts=4
    gives five ranges at n = 5, 9, 17, 33, 65, and parts=8 exceeds
    eight for 49 of the first thousand n.

    Callers handle both by using the ranges they get - the combine tree
    adapts - but a caller with one buffer per tile must size for the
    RANGES, not for `parts`, and must not assume it can run them all at
    once. cft_sf_canonical_ranges() in the C library is this function
    with a hard cap on the output count, so the two diverge once
    `parts` reaches that cap; tests/reduce_check.py is what compares
    them.
    """
    if parts < 1 or (parts & (parts - 1)) != 0:
        raise ValueError("parts must be a power of two: only a clean cut "
                         "of the top levels yields canonical nodes")
    if n <= 0:
        return []
    ranges = [(0, n)]
    while len(ranges) < parts:
        nxt = []
        for lo, hi in ranges:
            if hi - lo < 2:
                nxt.append((lo, hi))
            else:
                mid = split(lo, hi)
                nxt.append((lo, mid))
                nxt.append((mid, hi))
        if len(nxt) == len(ranges):
            break          # every range is a single element; cannot cut further
        ranges = nxt
    return ranges


def reduce_bits(fmt: FpFormat, xs, rnd: int = RND_RNE, lo: int = 0, hi=None):
    """T(lo, hi) over a sequence of bit patterns -> (bits, flags)."""
    _check_mode(rnd)
    if hi is None:
        hi = len(xs)
    if hi < lo:
        raise ValueError("hi must not be less than lo")
    if hi == lo:
        return zero_bits(fmt, 0), 0
    if hi - lo == 1:
        # No adds happen here, so no flags - see the module docstring.
        return xs[lo], 0
    mid = split(lo, hi)
    la, lf = reduce_bits(fmt, xs, rnd, lo, mid)
    ra, rf = reduce_bits(fmt, xs, rnd, mid, hi)
    s, sf = _add(fmt, la, ra, rnd)
    return s, lf | rf | sf


def stream_reduce(fmt: FpFormat, xs, rnd: int = RND_RNE):
    """The same tree, computed the way hardware will compute it.

    A binary-counter stack of accumulators. Element i goes into level 0;
    whenever a level is already occupied its contents (the LOWER indices)
    are added to the incoming value and the sum carries up a level, the
    same way a ripple counter carries. At the end the occupied levels are
    folded lowest first, right-associating outward.

    Properties the RTL inherits from this and needs:

      - one add per element, in index order, no lookahead
      - ceil(log2 n) accumulator registers plus their occupancy bits;
        64 levels covers any n a 64-bit count can express
      - n is not needed in advance. The stack does not care how long the
        stream is, which means a tile can start reducing before the host
        has told it how much there is - and it means the same machine
        handles every n with no special cases for the tail.

    Returns (bits, flags), identical to reduce_bits for every input.
    test_stream_matches_recursive is what holds that to be true.
    """
    _check_mode(rnd)
    xs = list(xs)
    if not xs:
        return zero_bits(fmt, 0), 0

    acc = {}                 # level -> partial result
    flags = 0
    for x in xs:
        v, j = x, 0
        while j in acc:
            v, f = _add(fmt, acc.pop(j), v, rnd)   # acc[j] is the lower half
            flags |= f
            j += 1
        acc[j] = v

    r = None
    for j in sorted(acc):
        if r is None:
            r = acc[j]
        else:
            r, f = _add(fmt, acc[j], r, rnd)
            flags |= f
    return r, flags


def combine(fmt: FpFormat, partials, rnd: int = RND_RNE):
    """Fold per-range partial results with the same tree.

    Used by a multi-tile host on the results of `canonical_ranges`.
    Deliberately just `reduce_bits` over the partials: the tree over
    2**k leaves is exactly the top k levels that were cut out, so
    combining this way rebuilds the node that was removed. If those two
    ever stopped being the same function the property would rot
    silently, so they are the same function.
    """
    return reduce_bits(fmt, list(partials), rnd)


def fsum(fmt: FpFormat, xs, rnd: int = RND_RNE):
    """Sum of a vector of bit patterns -> (bits, flags)."""
    return reduce_bits(fmt, list(xs), rnd)


def fdot(fmt: FpFormat, xs, ys, rnd: int = RND_RNE):
    """Dot product -> (bits, flags). Rounded products, then the tree."""
    xs = list(xs)
    ys = list(ys)
    if len(xs) != len(ys):
        raise ValueError("dot needs two vectors of the same length")
    _check_mode(rnd)
    prods = []
    flags = 0
    for a, b in zip(xs, ys):
        p, pf = _mul(fmt, a, b, rnd)
        prods.append(p)
        flags |= pf
    s, sf = reduce_bits(fmt, prods, rnd)
    return s, flags | sf


# ---------------------------------------------------------------------
# The rest of clause 9.4
# ---------------------------------------------------------------------
#
# Classification helpers. Deliberately local and tiny: these decide
# 9.4's special-value rows, which are stated over operand CLASSES, and
# reaching for the full unpack() to ask "is this an infinity" would put
# the answer one refactor away from the question.

def _is_inf(fmt: FpFormat, x: int) -> bool:
    return (((x >> fmt.man_w) & fmt.exp_mask) == fmt.exp_mask and
            (x & fmt.man_mask) == 0)


def _is_nan(fmt: FpFormat, x: int) -> bool:
    return (((x >> fmt.man_w) & fmt.exp_mask) == fmt.exp_mask and
            (x & fmt.man_mask) != 0)


def _is_snan(fmt: FpFormat, x: int) -> bool:
    return _is_nan(fmt, x) and not ((x >> (fmt.man_w - 1)) & 1)


def _is_zero(fmt: FpFormat, x: int) -> bool:
    return (x & ~fmt.sign_mask) == 0


def _sign(fmt: FpFormat, x: int) -> int:
    return (x >> (fmt.width - 1)) & 1


def _inf_over_nan(fmt: FpFormat, xs):
    """9.4's special-value order for sumSquare and sumAbs, which is not
    sum's and dot's: infinity outranks NaN.

        "For sumSquare and sumAbs, if any operand element is an
         infinity, +inf is returned. Otherwise, if any operand element
         is a NaN a quiet NaN is returned."                      (9.4)

    Returns (bits, flags) when the tree's answer would differ from
    that, and None when it would not - which is every input except one
    holding an infinity AND a NaN. With an infinity and no NaN the tree
    already delivers +inf, because every term of either operation is a
    square or a magnitude: no term is negative, so no inf - inf exists
    to make a NaN, and inf + anything-finite is inf.

    The flags are 9.4's own blanket rule and nothing else -

        "All reduction operations signal the invalid operation
         exception if any operand is a signaling NaN."           (9.4)

    - because the result is decided by this table rather than computed:

        "only one exception is signaled per reduction operation
         invocation; exceptions are not signaled for each exceptional
         intermediate operand or result."                        (9.4)
    """
    if not any(_is_inf(fmt, x) for x in xs):
        return None
    if not any(_is_nan(fmt, x) for x in xs):
        return None
    flags = FLAG_INVALID if any(_is_snan(fmt, x) for x in xs) else 0
    return inf_bits(fmt, 0), flags


def fsumsq(fmt: FpFormat, xs, rnd: int = RND_RNE):
    """sumSquare: the dot tree over (x, x) -> (bits, flags).

    Bit-identical to fdot(fmt, xs, xs, rnd) on every input that does not
    hold an infinity AND a NaN at once, which is the single row 9.4
    orders differently for this operation (see _inf_over_nan). The
    library computes it by issuing exactly that dot, so the device and
    software backends agree by construction rather than by testing.
    """
    xs = list(xs)
    special = _inf_over_nan(fmt, xs)
    if special is not None:
        return special
    return fdot(fmt, xs, xs, rnd)


def fsumabs(fmt: FpFormat, xs, rnd: int = RND_RNE):
    """sumAbs: the sum tree over |x| -> (bits, flags).

    Bit-identical to an abs pass followed by fsum, with the same single
    exclusion fsumsq carries. abs signals nothing at all (5.5.1), so the
    pass contributes no flags and the tree's are the operation's.

    The n == 1 edge is the one the module docstring already states:
    one leaf is zero adds, so sumAbs of a single signalling NaN is
    |sNaN| - the pattern with its sign cleared - and raises nothing,
    where n >= 2 would quiet it and signal invalid. That is inherited
    from the tree rather than chosen here, and it is the one place this
    operation does not meet 9.4's blanket signalling-NaN rule; the
    reason is that at n == 1 there is no operation to signal from.
    """
    xs = list(xs)
    special = _inf_over_nan(fmt, xs)
    if special is not None:
        return special
    return fsum(fmt, [_fabs(fmt, x)[0] for x in xs], rnd)


# ---- the scaled products --------------------------------------------

class ScaleOverflow(Exception):
    """The scale left the int64 range. 9.4 makes this invalid + qNaN."""


def norm_split(fmt: FpFormat, x: int):
    """(sig, k) with x == value(sig) * 2**k EXACTLY, |value(sig)| in
    [1, 2). x must be finite and non-zero.

    This is the whole of the scaling rule, and it is exact at both ends
    it is used on:

      - a leaf, where x is any finite non-zero operand. A subnormal's
        normalised significand always fits, because a subnormal has
        FEWER significant bits than the format holds - which is the
        mechanism by which a scaled product cannot underflow.
      - a node's product, where |x| < 4 before rounding and so |x| <= 4
        after it, giving k in {0, 1, 2}. Scaling a normal number by a
        power of two within the exponent range is exact, so no rounding
        happens here and none is hidden.
    """
    u = unpack(fmt, x)
    b = u.m.bit_length() - 1
    frac = (u.m << (fmt.man_w - b)) & fmt.man_mask
    return (((u.sign << (fmt.width - 1)) | (fmt.bias << fmt.man_w) | frac),
            u.e + b)


def _scale_add(a: int, b: int) -> int:
    """One int64 addition of the scale accumulator, checked.

    The C accumulates in an int64 and cannot let a transient partial
    wrap silently, so the model checks every addition too rather than
    only the total - the two must refuse on exactly the same inputs.
    """
    s = a + b
    if s < SCALE_MIN or s > SCALE_MAX:
        raise ScaleOverflow(s)
    return s


def _scaled_tree(fmt: FpFormat, xs, rnd: int, lo: int, hi: int):
    """T(lo, hi) over factors as (significand, scale) -> (sig, k, flags).

    The same shape `split` defines, so a scaled product and a sum pair
    their elements identically - which is what makes "the tree" one
    thing in this contract rather than two.
    """
    if hi - lo == 1:
        sig, k = norm_split(fmt, xs[lo])
        return sig, k, 0
    mid = split(lo, hi)
    ls, lk, lf = _scaled_tree(fmt, xs, rnd, lo, mid)
    rs, rk, rf = _scaled_tree(fmt, xs, rnd, mid, hi)
    p, pf = _mul(fmt, ls, rs, rnd)          # the one rounding of the node
    sig, k = norm_split(fmt, p)             # exact
    return sig, _scale_add(_scale_add(lk, rk), k), lf | rf | pf


def scaled_prod(fmt: FpFormat, xs, ys=None, kind: int = SP_PROD,
                rnd: int = RND_RNE):
    """scaledProd / scaledProdSum / scaledProdDiff -> (pr, sf, flags).

    scaleB(pr, sf) approximates the product of the elements (of their
    pairwise sums, of their pairwise differences), with pr always in
    +-[1, 2) - for n == 0 too, where 9.4 fixes the result:

        "When the vector length operand is zero, pr is 1 and sf is +0
         without exception."                                     (9.4)

    The special-value rows are 9.4's, in 9.4's order, over the FACTORS -
    which for the two binary forms are the rounded sums or differences,
    not the raw operands:

        "if any operand element is a NaN a quiet NaN is returned. A
         product of inf x 0 signals the invalid operation exception. A
         sum of infinities of different signs (or a difference of
         infinities of like signs) signals the invalid operation
         exception. Otherwise, if there are infinities in the product,
         an infinity is returned and the invalid operation exception is
         not signaled. Otherwise, if there are zeros in the product, a
         zero is returned and the invalid operation exception is not
         signaled."                                              (9.4)

    The sum-of-unlike-infinities row needs no code: that addition raises
    invalid and produces a quiet NaN on its own, and the NaN row then
    delivers it. The sign of the returned infinity or zero is the sign
    of the true product - the XOR over every factor's sign bit - which
    9.4 leaves open and a determinism contract may not.

    Flags: invalid for a signalling NaN operand, for inf x 0, and for a
    scale that leaves the int64 range; inexact from any node multiply
    (and from any leaf add or subtract); overflow and underflow only
    ever from a leaf add or subtract, never from the product tree.
    divideByZero never.
    """
    _check_mode(rnd)
    xs = list(xs)
    flags = 0

    if kind == SP_PROD:
        if ys is not None and len(ys) != len(xs):
            raise ValueError("scaledProd takes one vector")
        factors = xs
    elif kind in (SP_PROD_SUM, SP_PROD_DIFF):
        ys = list(ys if ys is not None else [])
        if len(ys) != len(xs):
            raise ValueError("scaledProdSum/Diff need two vectors of the "
                             "same length")
        combine_leaf = _add if kind == SP_PROD_SUM else _sub
        factors = []
        for a, b in zip(xs, ys):
            s, f = combine_leaf(fmt, a, b, rnd)
            factors.append(s)
            flags |= f
    else:
        raise ValueError("unknown scaled-product kind %r" % (kind,))

    if not factors:
        return one_bits(fmt, 0), 0, 0

    if any(_is_nan(fmt, v) for v in factors):
        if any(_is_snan(fmt, v) for v in factors):
            flags |= FLAG_INVALID
        return qnan_bits(fmt), 0, flags

    sign = 0
    for v in factors:
        sign ^= _sign(fmt, v)
    has_inf = any(_is_inf(fmt, v) for v in factors)
    has_zero = any(_is_zero(fmt, v) for v in factors)
    if has_inf and has_zero:
        return qnan_bits(fmt), 0, flags | FLAG_INVALID
    if has_inf:
        return inf_bits(fmt, sign), 0, flags
    if has_zero:
        return zero_bits(fmt, sign), 0, flags

    try:
        sig, scale, tf = _scaled_tree(fmt, factors, rnd, 0, len(factors))
    except ScaleOverflow:
        # The product is not delivered, so the tree's own flags are not
        # either; 7.2's precedence has invalid pre-empt inexact
        # everywhere else in this contract and does here too. The leaf
        # adds' flags stand, because those roundings did happen.
        return qnan_bits(fmt), 0, flags | FLAG_INVALID
    return sig, scale, flags | tf
