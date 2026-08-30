# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Reductions: sum and dot, with the tree shape fixed by element index.

docs/DETERMINISM.md already committed to the hard part of this before a
line of it existed:

    When reduction ops land, their tree shape is fixed by element
    index, never by arrival time or lane availability.

That sentence is the whole design. Everything below is what it forces.

THE TREE

The shape is a balanced binary tree over the half-open index range,
split at the midpoint:

    T(lo, hi) = xs[lo]                            if hi - lo == 1
              = add(T(lo, mid), T(mid, hi))       mid = lo + (hi-lo)//2

One function, `split`, is the only place the shape is written down.
Anything that needs to agree about the tree - the software backend, the
sequencer, a future RTL walker, a host partitioning across tiles - calls
it rather than re-deriving it, because a reduction where two
implementations disagree about the shape is not a reduction, it is two
different answers with the same name.

Depth is ceil(log2 n), which is also why the accuracy is better than a
sequential accumulation. That is a happy side effect and NOT the reason:
the reason is that the shape is a pure function of the index range, so
it cannot vary with how many tiles ran, how fast they were, or which
finished first.

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
"""

from .formats import FpFormat
from .softfloat import (
    RND_RNE, add as _add, mul as _mul, zero_bits, _check_mode,
)

__all__ = [
    "OP_SUM", "OP_DOT", "REDUCE_OPS", "REDUCE_OP_NAMES",
    "split", "tree_adds", "canonical_ranges",
    "reduce_bits", "fsum", "fdot", "combine",
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

REDUCE_OPS = (OP_SUM, OP_DOT)
REDUCE_OP_NAMES = {OP_SUM: "sum", OP_DOT: "dot"}


def split(lo: int, hi: int) -> int:
    """The midpoint of a tree node. The one definition of the shape.

    Floor division, so an odd range puts the extra element on the RIGHT:
    T(0,3) is add(xs[0], add(xs[1], xs[2])). Either convention would be
    deterministic; this one is written down so both sides pick the same.
    """
    if hi - lo < 2:
        raise ValueError("split() needs a range of at least two elements")
    return lo + (hi - lo) // 2


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

    Fewer than `parts` ranges come back when n is too small to split
    that far - a range of one element has no midpoint. Callers handle
    that by using the ranges they get; the combine tree adapts.
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
