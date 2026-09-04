# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Reductions: the tree shape, and the properties that shape exists for.

The individual adds and muls are already verified elsewhere, exhaustively
and against the definition. What is new here is COMPOSITION, so that is
what these test: that the shape is what it says it is, that splitting a
reduction across tiles cannot change the answer, and that the edges
nobody thinks about (n of 0 and 1, signed zero, padding) behave the way
the module documents rather than the way they happen to fall out.

Several tests are negative controls - they assert that a WRONG way of
doing it produces a DIFFERENT answer. Without those, a property like
partition invariance can pass because everything collapses to the same
number for boring reasons rather than because the machinery works.
"""

import random
import sys
from fractions import Fraction
from pathlib import Path

import pytest

# CI runs `python -m pytest python/tests -q` from the repo root, where
# python/ is not on the path and cft_golden is not installed. Every
# other test here does this; this one did not, and imported fine on any
# machine whose shell already had the package reachable - which is why
# it was green locally and red the moment it was pushed.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cft_golden import (  # noqa: E402
    FP32, FP64, FP128, FP256, FORMATS,
    RND_RNE, RND_RTZ, RND_RDN, RND_RUP, RND_RMM, RND_MODES,
    FLAG_INVALID, FLAG_INEXACT, FLAG_OVERFLOW, FLAG_UNDERFLOW,
    add, sub, mul, fabs, unpack, zero_bits, one_bits, inf_bits, qnan_bits,
    snan_bits, max_normal_bits, min_subnormal_bits, min_normal_bits,
    negate, is_nan, vectors,
)
from cft_golden.reduce import (  # noqa: E402
    OP_SUM, OP_DOT, OP_SUMSQ, OP_SUMABS, REDUCE_OPS, REDUCE_OP_NAMES,
    SP_PROD, SP_PROD_SUM, SP_PROD_DIFF, SCALED_KINDS, SCALED_KIND_NAMES,
    SCALE_MIN, SCALE_MAX,
    split, tree_adds, canonical_ranges, reduce_bits, fsum, fdot, combine,
    stream_reduce, fsumsq, fsumabs, norm_split, scaled_prod,
)
import cft_golden.reduce as _reduce  # noqa: E402  (for the scale-guard test)

ALL_FORMATS = (FP32, FP64, FP128, FP256)


# ---------------------------------------------------------------
# operand generation
# ---------------------------------------------------------------
def rand_finite(fmt, rng, spread=6):
    """A random normal number with a full random significand.

    Exponents cluster so that sums actually interact: operands many
    orders of magnitude apart reduce to "the biggest one wins", which
    exercises nothing.
    """
    sign = rng.getrandbits(1)
    e = fmt.bias + rng.randint(-spread, spread)
    m = rng.getrandbits(fmt.man_w)
    return (sign << (fmt.width - 1)) | (e << fmt.man_w) | m


def seq_sum(fmt, xs, rnd=RND_RNE):
    """Left-to-right accumulation - the thing the tree is NOT."""
    if not xs:
        return zero_bits(fmt, 0), 0
    acc, flags = xs[0], 0
    for x in xs[1:]:
        acc, f = add(fmt, acc, x, rnd)
        flags |= f
    return acc, flags


# ---------------------------------------------------------------
# the shape
# ---------------------------------------------------------------
def test_split_is_the_largest_power_of_two_inside():
    """The left child is always a perfect subtree; the remainder goes
    right. This is what makes the tree a streaming accumulation."""
    assert split(0, 2) == 1
    assert split(0, 3) == 2        # T(0,3) = add(add(x0,x1), x2)
    assert split(0, 4) == 2
    assert split(0, 5) == 4        # T(0,5) = add(T(0,4), x4)
    assert split(0, 7) == 4
    assert split(0, 8) == 4
    assert split(0, 9) == 8
    assert split(3, 10) == 3 + 4   # offsets do not change the rule
    with pytest.raises(ValueError):
        split(0, 1)


@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_stream_matches_recursive(fmt):
    """The accumulator algorithm IS the tree.

    stream_reduce is the RTL's specification: one add per element in
    index order, ceil(log2 n) accumulator levels, carry when a level is
    occupied, then fold the leftovers lowest-first. If it ever stops
    agreeing with the recursive definition, the hardware and the
    contract have parted company and this is where that shows.
    """
    rng = random.Random(31337)
    for n in list(range(0, 40)) + [64, 65, 100, 127, 128, 129, 255, 300]:
        xs = [rand_finite(fmt, rng, spread=20) for _ in range(n)]
        for rnd in RND_MODES:
            assert stream_reduce(fmt, xs, rnd) == reduce_bits(fmt, xs, rnd), \
                f"{fmt.name} n={n} rnd={rnd}: streaming and recursive differ"


@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_add_is_commutative_so_operand_order_is_free(fmt):
    """add(a,b) == add(b,a), bit for bit, in every attribute.

    This lives here rather than with the softfloat tests because it is
    what the reduction hardware leans on. The accumulator pairs values
    by index but is free to present a pair to the adder in either order,
    which removes a whole class of thing that could otherwise go wrong
    in the RTL - and it means an injected "swap the operands" bug is a
    genuine no-op rather than a missed defect.

    It holds because this design has no order-dependent add: magnitude
    is symmetric, the sign of an exact cancellation is set by the
    rounding attribute (754-2019 6.3) and not by which operand came
    first, and NaN results are always the canonical quiet NaN rather
    than a propagated payload. Change any of those three and this test
    is where it shows.

    Two sweeps, because they fail differently. The pool cross is
    EXHAUSTIVE over the interesting operands - every signalling and
    quiet NaN, both infinities, both zeros, subnormals and the extreme
    normals, against each other - which is where an asymmetry would
    live if one existed. The random draws then cover the ordinary
    middle of the space that a curated pool does not reach.

    DRAWS is 4,000 because two files cite this test's pair count as the
    licence for the accumulator to swap operands freely, and the number
    they cited was 80,000 when the test was doing 10,000. Rather than
    write a smaller number into the documents, the test now does the
    work: 4,000 draws x 5 attributes x 4 formats is 80,000, and the
    count is asserted below so the two cannot drift apart again.
    """
    rng = random.Random(11)
    pool = vectors.interesting_operands(fmt)
    pairs = 0

    for a in pool:
        for b in pool:
            for rnd in RND_MODES:
                assert add(fmt, a, b, rnd) == add(fmt, b, a, rnd), \
                    f"{fmt.name} {a:#x} + {b:#x} depends on operand order"

    DRAWS = 4000
    for _ in range(DRAWS):
        a = (pool[rng.randrange(len(pool))] if rng.random() < 0.5
             else rng.getrandbits(fmt.width))
        b = (pool[rng.randrange(len(pool))] if rng.random() < 0.5
             else rng.getrandbits(fmt.width))
        for rnd in RND_MODES:
            pairs += 1
            assert add(fmt, a, b, rnd) == add(fmt, b, a, rnd), \
                f"{fmt.name} {a:#x} + {b:#x} depends on operand order"

    # 4,000 x 5 = 20,000 per format, x4 formats = the 80,000 the
    # accumulator's comment and DETERMINISM.md both claim.
    assert pairs == DRAWS * len(RND_MODES) == 20_000, pairs


def test_stream_final_combine_order_is_load_bearing():
    """Negative control for the test above.

    Folding leftover accumulator levels the other way round - highest
    first, left-associating - is also a fixed, deterministic shape. It
    is simply a DIFFERENT tree, and the difference first appears at
    n = 7. Without this, 'the streaming form matches' could be true of
    an implementation that had the fold backwards and happened to agree
    on the sizes tested.
    """
    def wrong_fold(fmt, xs, rnd):
        acc, flags = {}, 0
        for x in xs:
            v, j = x, 0
            while j in acc:
                v, f = add(fmt, acc.pop(j), v, rnd)
                flags |= f
                j += 1
            acc[j] = v
        r = None
        for j in sorted(acc, reverse=True):        # highest first
            if r is None:
                r = acc[j]
            else:
                r, f = add(fmt, r, acc[j], rnd)    # left-associating
                flags |= f
        return r, flags

    rng = random.Random(7)
    differed = 0
    for _ in range(300):
        xs = [rand_finite(FP64, rng, spread=20) for _ in range(7)]
        if wrong_fold(FP64, xs, RND_RNE)[0] != reduce_bits(FP64, xs, RND_RNE)[0]:
            differed += 1
    assert differed > 0, (
        "folding the leftovers the other way produced the same answer on "
        "every trial at n=7; the fold order is then not load-bearing and "
        "the docstring claiming it is needs correcting")


@pytest.mark.parametrize("n", list(range(2, 40)) + [64, 100, 1000])
def test_tree_has_exactly_n_minus_one_adds(n):
    """A binary tree over n leaves has n-1 internal nodes. If this ever
    fails the shape has grown or lost a node, which is a numerics change
    however innocent it looks."""
    assert len(tree_adds(n)) == n - 1


def test_tree_is_post_order_and_covers_every_index():
    """Children before parents, and every leaf reachable exactly once."""
    n = 11
    adds = tree_adds(n)
    seen_ranges = set()
    for lo, mid, hi in adds:
        # both children must already exist as ranges (or be leaves)
        for a, b in ((lo, mid), (mid, hi)):
            assert b - a == 1 or (a, b) in seen_ranges, \
                f"parent ({lo},{hi}) emitted before child ({a},{b})"
        seen_ranges.add((lo, hi))
    assert (0, n) in seen_ranges


@pytest.mark.parametrize("n", [1, 2, 3, 5, 8, 17, 64, 129])
def test_tree_depth_is_ceil_log2(n):
    depth = {}
    for lo, mid, hi in tree_adds(n):
        d = max(depth.get((lo, mid), 0), depth.get((mid, hi), 0)) + 1
        depth[(lo, hi)] = d
    got = depth.get((0, n), 0)
    want = (n - 1).bit_length()
    assert got == want


# ---------------------------------------------------------------
# the edges, stated in the docstring and pinned here
# ---------------------------------------------------------------
@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_empty_reduction_is_positive_zero_no_flags(fmt):
    assert fsum(fmt, []) == (zero_bits(fmt, 0), 0)


@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_single_element_is_verbatim_and_raises_nothing(fmt):
    """One leaf means zero adds, so nothing can be raised - and that
    holds even for a signalling NaN, which two elements would quiet."""
    s = snan_bits(fmt)
    assert fsum(fmt, [s]) == (s, 0)
    x = one_bits(fmt, 1)
    assert fsum(fmt, [x]) == (x, 0)


@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_two_elements_is_exactly_add(fmt):
    rng = random.Random(20260830)
    for _ in range(200):
        a, b = rand_finite(fmt, rng), rand_finite(fmt, rng)
        for rnd in RND_MODES:
            assert fsum(fmt, [a, b], rnd) == add(fmt, a, b, rnd)


# ---------------------------------------------------------------
# why there is no padding - the decision, as a test
# ---------------------------------------------------------------
@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_padding_with_positive_zero_would_change_the_answer(fmt):
    """Rounding n up to a power of two and padding with +0.0 is the
    obvious hardware shortcut and it is wrong: -0.0 + 0.0 is +0.0 under
    rne, so a negative-zero result would come back positive. This test
    exists so that anyone tempted by the shortcut sees the cost first."""
    nz = zero_bits(fmt, 1)
    true_result, _ = fsum(fmt, [nz, nz, nz], RND_RNE)
    assert true_result == zero_bits(fmt, 1)

    padded, _ = fsum(fmt, [nz, nz, nz, zero_bits(fmt, 0)], RND_RNE)
    assert padded == zero_bits(fmt, 0)
    assert padded != true_result


@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_signed_zero_follows_the_rounding_attribute(fmt):
    """An exact cancellation is -0.0 under rdn and +0.0 otherwise
    (754-2019 6.3). The reduction inherits it from add, and it must
    survive being a tree rather than a single op."""
    x = one_bits(fmt, 0)
    nx = negate(fmt, x)
    for rnd in RND_MODES:
        got, _ = fsum(fmt, [x, nx], rnd)
        want, _ = add(fmt, x, nx, rnd)
        assert got == want
        assert got == zero_bits(fmt, 1 if rnd == RND_RDN else 0)


# ---------------------------------------------------------------
# the tree is genuinely a tree
# ---------------------------------------------------------------
@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_tree_differs_from_sequential_somewhere(fmt):
    """Negative control for every partition test below. If the tree and
    a left-to-right accumulation always agreed, partition invariance
    would be vacuous - it would hold for a broken implementation too."""
    rng = random.Random(0xC0FFEE)
    differed = 0
    for _ in range(400):
        xs = [rand_finite(fmt, rng, spread=20) for _ in range(9)]
        if fsum(fmt, xs)[0] != seq_sum(fmt, xs)[0]:
            differed += 1
    assert differed > 0, \
        "tree and sequential never disagreed; the partition tests below " \
        "would prove nothing"


# ---------------------------------------------------------------
# partition invariance - the property the whole design is for
# ---------------------------------------------------------------
@pytest.mark.parametrize("fmt", ALL_FORMATS)
@pytest.mark.parametrize("parts", [1, 2, 4, 8, 16, 32, 64])
def test_canonical_partition_reproduces_the_whole(fmt, parts):
    """Splitting the work across `parts` tiles and combining the partial
    results must give bit-identical output and identical flags. This is
    the reduction's version of the elementwise partition-invariance
    property, and it is the reason canonical_ranges exists."""
    rng = random.Random(1234 + parts)
    for n in (1, 2, 3, 5, 7, 8, 9, 16, 17, 33, 64):
        xs = [rand_finite(fmt, rng, spread=20) for _ in range(n)]
        for rnd in RND_MODES:
            whole = fsum(fmt, xs, rnd)

            ranges = canonical_ranges(n, parts)
            assert ranges, "no ranges for a non-empty reduction"
            assert ranges[0][0] == 0 and ranges[-1][1] == n
            for (_, a), (b, _) in zip(ranges, ranges[1:]):
                assert a == b, "ranges must tile [0,n) without gaps"

            partials, flags = [], 0
            for lo, hi in ranges:
                p, f = reduce_bits(fmt, xs, rnd, lo, hi)
                partials.append(p)
                flags |= f
            got, cf = combine(fmt, partials, rnd)
            assert (got, flags | cf) == whole, \
                f"n={n} parts={parts} rnd={rnd} fmt={fmt.name}"


@pytest.mark.parametrize("fmt", [FP32, FP256])
def test_even_slicing_is_not_a_valid_partition(fmt):
    """Negative control for the one above. The even slicing libcft uses
    for elementwise work does NOT generally land on tree nodes, so
    reusing it for a reduction changes the answer. If this ever stops
    failing, canonical_ranges has become decoration and the elementwise
    slicer could be used instead - which would be worth knowing."""
    rng = random.Random(99)
    mismatches = 0
    for _ in range(200):
        n = rng.choice([5, 6, 7, 9, 10, 11, 13])
        xs = [rand_finite(fmt, rng, spread=20) for _ in range(n)]
        whole, _ = fsum(fmt, xs)

        parts, cut = 4, []
        base, extra = divmod(n, parts)
        pos = 0
        for i in range(parts):
            take = base + (1 if i < extra else 0)
            if take:
                cut.append((pos, pos + take))
            pos += take
        partials = [reduce_bits(fmt, xs, RND_RNE, lo, hi)[0] for lo, hi in cut]
        if combine(fmt, partials)[0] != whole:
            mismatches += 1
    assert mismatches > 0, \
        "even slicing always matched the canonical tree; canonical_ranges " \
        "is then not load-bearing and this claim needs re-examining"


# ---------------------------------------------------------------
# dot
# ---------------------------------------------------------------
@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_dot_equals_sum_of_products(fmt):
    """The composition property, bits and flags. It is what makes dot
    testable against machinery that is already trusted."""
    rng = random.Random(4242)
    for _ in range(150):
        n = rng.randint(0, 12)
        xs = [rand_finite(fmt, rng) for _ in range(n)]
        ys = [rand_finite(fmt, rng) for _ in range(n)]
        for rnd in RND_MODES:
            prods, pf = [], 0
            for a, b in zip(xs, ys):
                p, f = mul(fmt, a, b, rnd)
                prods.append(p)
                pf |= f
            s, sf = fsum(fmt, prods, rnd)
            assert fdot(fmt, xs, ys, rnd) == (s, pf | sf)


@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_dot_is_not_an_exact_accumulation(fmt):
    """Guards against someone "improving" dot into a single-rounding
    augmented dot product. That is a different operation with different
    results; if it is ever wanted it takes a new opcode. Constructed so
    the rounded-product form loses information the exact form keeps."""
    # Let u = 2^-man_w, the ulp of 1.0.
    #   a = b = 1 + u        a*b exactly = 1 + 2u + u^2
    #                        rounded     = 1 + 2u   (u^2 falls off the end)
    #   c = -1, d = 1 + 2u   c*d exactly = -(1 + 2u), representable
    #
    # Summing the ROUNDED products cancels exactly to zero. Summing the
    # EXACT products leaves u^2, a tiny positive. So the result being a
    # zero is a direct observation that the rounding happens at each
    # product, which is what this opcode promises.
    a = b = (fmt.bias << fmt.man_w) | 1
    c = fmt.sign_mask | (fmt.bias << fmt.man_w)
    d = (fmt.bias << fmt.man_w) | 2

    prod0, _ = mul(fmt, a, b, RND_RNE)
    assert prod0 == d, "the first product must round to 1 + 2u"
    prod1, _ = mul(fmt, c, d, RND_RNE)
    assert prod1 == negate(fmt, d), "the second product must be exact"

    got, _ = fdot(fmt, [a, c], [b, d], RND_RNE)
    assert got == zero_bits(fmt, 0), \
        "rounded products cancel to zero; a nonzero result here means " \
        "dot has become an exact accumulation, which is a different op"


def test_dot_length_mismatch_is_refused():
    with pytest.raises(ValueError):
        fdot(FP64, [one_bits(FP64)], [])


# ---------------------------------------------------------------
# specials
# ---------------------------------------------------------------
@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_opposite_infinities_raise_invalid(fmt):
    pos, neg = inf_bits(fmt, 0), inf_bits(fmt, 1)
    got, flags = fsum(fmt, [pos, neg])
    assert is_nan(fmt, got)
    assert flags & FLAG_INVALID


@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_nan_propagates_through_the_tree(fmt):
    rng = random.Random(7)
    xs = [rand_finite(fmt, rng) for _ in range(7)]
    xs[3] = qnan_bits(fmt)
    got, _ = fsum(fmt, xs)
    assert is_nan(fmt, got)


@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_infinity_survives_finite_neighbours(fmt):
    rng = random.Random(8)
    xs = [rand_finite(fmt, rng) for _ in range(6)]
    xs[2] = inf_bits(fmt, 1)
    got, _ = fsum(fmt, xs)
    assert got == inf_bits(fmt, 1)


# ---------------------------------------------------------------
# exactness where the answer is knowable independently
# ---------------------------------------------------------------
@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_small_integers_sum_exactly(fmt):
    """Integers small enough to be exact must sum exactly, in every
    rounding attribute, with no inexact flag - the tree shape cannot
    matter when nothing rounds."""
    def int_bits(v):
        assert v > 0
        e = v.bit_length() - 1
        m = (v << (fmt.man_w - e)) & fmt.man_mask
        return ((fmt.bias + e) << fmt.man_w) | m

    xs = [int_bits(v) for v in range(1, 33)]
    want = sum(range(1, 33))          # 528
    for rnd in RND_MODES:
        got, flags = fsum(fmt, xs, rnd)
        assert got == int_bits(want), f"rnd={rnd}"
        assert not (flags & FLAG_INEXACT)


# ---------------------------------------------------------------
# opcode bookkeeping
# ---------------------------------------------------------------
def test_reduction_opcodes_are_in_the_reserved_range():
    """docs/DETERMINISM.md reserves 15 and 24+ and says reductions land
    there. Anything below 24 would collide with an assigned elementwise
    op, which is a contract break, not a bug."""
    for op in REDUCE_OPS:
        assert op >= 24
    assert OP_SUM != OP_DOT
    assert set(REDUCE_OP_NAMES) == set(REDUCE_OPS)


def test_canonical_ranges_refuses_non_power_of_two():
    with pytest.raises(ValueError):
        canonical_ranges(16, 3)
    assert canonical_ranges(0, 4) == []
    # n smaller than parts: fewer ranges, still tiling [0, n)
    r = canonical_ranges(3, 8)
    assert r[0][0] == 0 and r[-1][1] == 3
    assert all(hi - lo == 1 for lo, hi in r)


# ===============================================================
# The rest of clause 9.4: sumSquare, sumAbs, and the three scaled
# products.
# ===============================================================

# Vector lengths chosen where a tree shape goes wrong: every small n,
# then each power of two and its neighbours, so the lopsided nodes and
# the perfect ones are both exercised.
TREE_SIZES = tuple(range(0, 18)) + (31, 32, 33, 63, 64, 65, 127, 128, 129)


def sq_pool(fmt, rng, n):
    """Operands with the specials at a rate high enough to be hit."""
    out = []
    for _ in range(n):
        r = rng.random()
        if r < 0.05:
            out.append(qnan_bits(fmt))
        elif r < 0.09:
            out.append(inf_bits(fmt, rng.getrandbits(1)))
        elif r < 0.14:
            out.append(zero_bits(fmt, rng.getrandbits(1)))
        elif r < 0.18:
            out.append((rng.getrandbits(1) << (fmt.width - 1)) |
                       rng.randrange(1, 1 << fmt.man_w))
        else:
            out.append(rand_finite(fmt, rng))
    return out


def has_inf_and_nan(fmt, xs):
    """The one input class on which 9.4 orders sumSquare's and sumAbs's
    special values differently from the tree's own answer."""
    return (any(is_nan(fmt, x) for x in xs) and
            any(((x >> fmt.man_w) & fmt.exp_mask) == fmt.exp_mask and
                not (x & fmt.man_mask) for x in xs))


# ---------------------------------------------------------------
# the two composition identities
# ---------------------------------------------------------------
@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_sumsq_is_dot_with_itself(fmt):
    """sumSquare(x) == dot(x, x), node for node, bits AND flags.

    This is the contract, not an optimisation: the library computes
    sumSquare by issuing that dot, so the device and software backends
    agree by construction. The identity holds on every input except the
    one 9.4 singles out - see the next test, which pins that row.
    """
    rng = random.Random(0x5119 ^ fmt.man_w)
    checked = 0
    for n in TREE_SIZES:
        for rnd in RND_MODES:
            for _ in range(3):
                xs = sq_pool(fmt, rng, n)
                if has_inf_and_nan(fmt, xs):
                    continue
                assert fsumsq(fmt, xs, rnd) == fdot(fmt, xs, xs, rnd), \
                    f"n={n} rnd={rnd}"
                checked += 1
    assert checked >= 250


@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_sumabs_is_abs_then_sum(fmt):
    """sumAbs(x) == sum(|x|), node for node, bits AND flags. abs signals
    nothing at all (5.5.1), so the pass contributes no flags."""
    rng = random.Random(0xAB5 ^ fmt.man_w)
    checked = 0
    for n in TREE_SIZES:
        for rnd in RND_MODES:
            for _ in range(3):
                xs = sq_pool(fmt, rng, n)
                if has_inf_and_nan(fmt, xs):
                    continue
                want = fsum(fmt, [fabs(fmt, x)[0] for x in xs], rnd)
                assert fsumabs(fmt, xs, rnd) == want, f"n={n} rnd={rnd}"
                checked += 1
    assert checked >= 250


@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_infinity_outranks_nan_for_sumsq_and_sumabs(fmt):
    """9.4: "For sumSquare and sumAbs, if any operand element is an
    infinity, +inf is returned. Otherwise, if any operand element is a
    NaN a quiet NaN is returned." - the opposite order from sum and dot,
    and the ONE place these two are not the plain composition.

    A negative control comes free: the same vector through dot gives a
    quiet NaN, so this is a real override rather than a coincidence.
    """
    for sign in (0, 1):
        for pos in (0, 1):
            xs = [qnan_bits(fmt), zero_bits(fmt)]
            xs.insert(pos, inf_bits(fmt, sign))
            for rnd in RND_MODES:
                bits, flags = fsumsq(fmt, xs, rnd)
                assert bits == inf_bits(fmt, 0)      # +inf, either sign in
                assert flags == 0                    # quiet NaN signals nothing
                assert fsumabs(fmt, xs, rnd) == (inf_bits(fmt, 0), 0)
                # the negative control: the tree alone would say NaN
                assert is_nan(fmt, fdot(fmt, xs, xs, rnd)[0])

    # a signalling NaN beside an infinity: still +inf, but 9.4's
    # blanket rule signals invalid.
    xs = [inf_bits(fmt), snan_bits(fmt)]
    assert fsumsq(fmt, xs) == (inf_bits(fmt, 0), FLAG_INVALID)
    assert fsumabs(fmt, xs) == (inf_bits(fmt, 0), FLAG_INVALID)


@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_sumsq_and_sumabs_are_never_negative_and_never_invalid(fmt):
    """Every term is a square or a magnitude, so no inf - inf can arise
    and a finite vector can never make the operation invalid. That is
    the property the infinity rule above rests on."""
    rng = random.Random(0xF00D ^ fmt.man_w)
    for _ in range(120):
        n = rng.randint(2, 40)
        xs = [rand_finite(fmt, rng, spread=fmt.emax // 2) for _ in range(n)]
        xs += [inf_bits(fmt, rng.getrandbits(1)), zero_bits(fmt, 1)]
        rng.shuffle(xs)
        for f in (fsumsq, fsumabs):
            bits, flags = f(fmt, xs, RND_RNE)
            assert not (flags & FLAG_INVALID)
            assert bits == inf_bits(fmt, 0)      # an infinity is in there


@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_sumsq_sumabs_edges(fmt):
    """n = 0 and n = 1, which the tree decides and 9.4 does not
    contradict for these two."""
    assert fsumsq(fmt, [], RND_RNE) == (zero_bits(fmt, 0), 0)
    assert fsumabs(fmt, [], RND_RNE) == (zero_bits(fmt, 0), 0)

    # n = 1: one leaf. sumAbs performs zero operations at all, so even a
    # signalling NaN comes back with its sign cleared and no flag - the
    # module's stated edge. sumSquare's leaf IS a multiply, so it
    # quiets and signals, exactly as dot does.
    assert fsumabs(fmt, [snan_bits(fmt)], RND_RNE) == (snan_bits(fmt), 0)
    assert fsumsq(fmt, [snan_bits(fmt)], RND_RNE) == \
        fdot(fmt, [snan_bits(fmt)], [snan_bits(fmt)], RND_RNE)
    assert fsumsq(fmt, [snan_bits(fmt)], RND_RNE)[1] == FLAG_INVALID

    # a negative element: sumAbs takes its magnitude, sumSquare squares.
    neg_one = one_bits(fmt, 1)
    assert fsumabs(fmt, [neg_one], RND_RNE)[0] == one_bits(fmt)
    assert fsumsq(fmt, [neg_one], RND_RNE)[0] == one_bits(fmt)


# ---------------------------------------------------------------
# the scaling rule
# ---------------------------------------------------------------
@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_norm_split_is_exact_and_lands_in_one_two(fmt):
    """The leaf and the node extraction: |sig| in [1, 2), and
    sig * 2**k reproduces the operand EXACTLY. Subnormals included -
    that is the mechanism by which the product cannot underflow."""
    rng = random.Random(0x513 ^ fmt.man_w)
    pool = [one_bits(fmt), one_bits(fmt, 1),
            min_subnormal_bits(fmt), min_subnormal_bits(fmt, 1),
            max_normal_bits(fmt), max_normal_bits(fmt, 1),
            min_normal_bits(fmt), (1 << (fmt.man_w - 1))]
    pool += [rand_finite(fmt, rng, spread=fmt.emax - 1) for _ in range(200)]
    for x in pool:
        sig, k = norm_split(fmt, x)
        u = unpack(fmt, sig)
        # |sig| in [1, 2): a normal number whose unbiased exponent is 0
        assert u.e + u.m.bit_length() - 1 == 0, hex(x)
        assert (sig >> (fmt.width - 1)) == (x >> (fmt.width - 1))
        # exact: value(sig) * 2**k == value(x). In Fractions, because
        # 2 ** -1074 in floats is the zero this test exists to rule out.
        ux = unpack(fmt, x)
        two = Fraction(2)
        assert u.m * two ** (u.e + k) == ux.m * two ** ux.e, hex(x)


@pytest.mark.parametrize("fmt", ALL_FORMATS)
@pytest.mark.parametrize("kind", SCALED_KINDS)
def test_scaled_pr_is_always_in_one_two(fmt, kind):
    """The invariant the whole design rests on, over every tree size and
    every attribute: the delivered significand is normal with unbiased
    exponent 0, so the multiply's operands are in +-[1, 2), its result
    is in +-[1, 4), and neither overflow nor underflow is reachable.

        "In the absence of any of the above, the scaled result, pr,
         shall not be affected by overflow or underflow."       (9.4)
    """
    rng = random.Random(0x5CA1 ^ fmt.man_w ^ kind)
    for n in TREE_SIZES:
        if n == 0:
            continue
        for rnd in RND_MODES:
            xs = [rand_finite(fmt, rng, spread=fmt.emax - 2)
                  for _ in range(n)]
            ys = [rand_finite(fmt, rng, spread=fmt.emax - 2)
                  for _ in range(n)]
            pr, sf, flags = scaled_prod(fmt, xs, ys, kind, rnd)
            if is_nan(fmt, pr) or (pr & ~fmt.sign_mask) in (
                    0, fmt.exp_mask << fmt.man_w):
                continue          # a leaf sum landed on zero or infinity
            u = unpack(fmt, pr)
            assert u.e + u.m.bit_length() - 1 == 0, (n, rnd, hex(pr))
            if kind == SP_PROD:
                # nothing but a leaf add can raise these, and there is
                # no leaf add in a plain scaledProd
                assert not (flags & (FLAG_OVERFLOW | FLAG_UNDERFLOW))


@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_scaled_prod_never_overflows_where_the_product_would(fmt):
    """The point of the operation. A product that leaves the format's
    range by hundreds of binades in both directions is delivered exactly
    the same way as one that does not: no overflow, no underflow, no
    infinity, no zero - only inexact.

    The negative control is the plain product of the same vector, which
    is an infinity (or a zero) long before the end.
    """
    big = max_normal_bits(fmt)
    tiny = min_subnormal_bits(fmt)
    # `escapes` says whether the PLAIN product of this vector must leave
    # the format. None for the alternating one, where the answer is
    # format-dependent - fp32 decays to zero inside 24 elements and
    # fp64 does not - so asserting either way would be asserting an
    # accident. The scaled product's own invariant is checked for it
    # like the rest.
    for xs, escapes, label in (([big] * 20, True, "20 x maxfinite"),
                               ([tiny] * 20, True, "20 x min subnormal"),
                               ([big, tiny] * 12, None, "alternating"),
                               ([big] * 9 + [tiny] * 3, True, "mixed")):
        for rnd in RND_MODES:
            pr, sf, flags = scaled_prod(fmt, xs, None, SP_PROD, rnd)
            assert not (flags & (FLAG_OVERFLOW | FLAG_UNDERFLOW |
                                 FLAG_INVALID)), label
            u = unpack(fmt, pr)
            assert u.e + u.m.bit_length() - 1 == 0, label

        # the negative control: multiplying in the format saturates
        acc, saturated = xs[0], False
        for x in xs[1:]:
            acc, _ = mul(fmt, acc, x, RND_RNE)
            if (acc & ~fmt.sign_mask) in (0, fmt.exp_mask << fmt.man_w):
                saturated = True
        if escapes is not None:
            assert saturated == escapes, \
                f"{label}: plain product escapes={saturated}, want {escapes}"


@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_scaled_prod_reproduces_the_true_product(fmt):
    """scaleB(pr, sf) is the product, to the precision the tree keeps.

    Checked exactly, in integers: for a vector of exact powers of two
    the tree is exact at every node, so the delivered pair must equal
    the true product with NO error and no inexact flag at all.
    """
    for exps in ([0, 1, 2, 3], [-5, 7, -100, 3, 60], [1] * 17,
                 [fmt.emax - 1, fmt.emax - 1, fmt.emin, fmt.emin]):
        xs = [((fmt.bias + e) << fmt.man_w) for e in exps]
        for rnd in RND_MODES:
            pr, sf, flags = scaled_prod(fmt, xs, None, SP_PROD, rnd)
            assert flags == 0, exps
            assert pr == one_bits(fmt)          # every factor is a power of 2
            assert sf == sum(exps), exps

    # and with signs: the sign of pr is the product's sign
    for signs in ([0, 0], [1, 0], [0, 1], [1, 1], [1, 1, 1]):
        xs = [(s << (fmt.width - 1)) | (fmt.bias << fmt.man_w) for s in signs]
        pr, sf, flags = scaled_prod(fmt, xs)
        assert pr == one_bits(fmt, sum(signs) & 1)
        assert sf == 0 and flags == 0


@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_scaled_prod_uses_the_same_tree(fmt):
    """A negative control for the SHAPE: a left-to-right scaled product
    disagrees with the tree somewhere, so "the same tree" is a claim
    with content."""
    rng = random.Random(0x7EEE ^ fmt.man_w)
    differed = 0
    for _ in range(200):
        n = rng.choice([3, 5, 6, 7, 9, 11, 13])
        xs = [rand_finite(fmt, rng, spread=4) for _ in range(n)]
        pr, sf, _ = scaled_prod(fmt, xs)
        # sequential: same leaf rule, same node rule, wrong association
        acc_sig, acc_k = norm_split(fmt, xs[0])
        for x in xs[1:]:
            s, k = norm_split(fmt, x)
            p, _f = mul(fmt, acc_sig, s, RND_RNE)
            acc_sig, kk = norm_split(fmt, p)
            acc_k += k + kk
        if (acc_sig, acc_k) != (pr, sf):
            differed += 1
    assert differed > 0, "sequential and tree agreed on every vector"


# ---------------------------------------------------------------
# the scaled products' special values (9.4's own rows)
# ---------------------------------------------------------------
@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_scaled_prod_empty_vector_is_one(fmt):
    """9.4: "When the vector length operand is zero, pr is 1 and sf is
    +0 without exception." - the multiplicative identity, where sum's
    empty answer is the additive one."""
    for kind in SCALED_KINDS:
        assert scaled_prod(fmt, [], [], kind) == (one_bits(fmt), 0, 0)


@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_scaled_prod_special_value_precedence(fmt):
    """9.4's rows, in 9.4's order: NaN, then inf x 0 (invalid), then an
    infinity, then a zero."""
    z, zn = zero_bits(fmt, 0), zero_bits(fmt, 1)
    inf, ninf = inf_bits(fmt, 0), inf_bits(fmt, 1)
    two = one_bits(fmt) + (1 << fmt.man_w)          # 2.0
    ntwo = negate(fmt, two)

    # NaN outranks everything, and a quiet one signals nothing
    for extra in ([], [inf], [z], [inf, z]):
        assert scaled_prod(fmt, [qnan_bits(fmt)] + extra) == \
            (qnan_bits(fmt), 0, 0)
    # a signalling NaN raises invalid (9.4's blanket rule) and quiets
    assert scaled_prod(fmt, [snan_bits(fmt), two]) == \
        (qnan_bits(fmt), 0, FLAG_INVALID)

    # inf x 0 is invalid and delivers the canonical quiet NaN
    assert scaled_prod(fmt, [inf, z]) == (qnan_bits(fmt), 0, FLAG_INVALID)
    assert scaled_prod(fmt, [ninf, zn, two]) == \
        (qnan_bits(fmt), 0, FLAG_INVALID)

    # an infinity with no zero: an infinity, no exception, the sign of
    # the true product
    assert scaled_prod(fmt, [inf, two]) == (inf, 0, 0)
    assert scaled_prod(fmt, [inf, ntwo]) == (ninf, 0, 0)
    assert scaled_prod(fmt, [ninf, ntwo]) == (inf, 0, 0)
    assert scaled_prod(fmt, [ninf, ninf, ninf]) == (ninf, 0, 0)

    # a zero with no infinity: a zero with the product's sign
    assert scaled_prod(fmt, [z, two]) == (z, 0, 0)
    assert scaled_prod(fmt, [zn, two]) == (zn, 0, 0)
    assert scaled_prod(fmt, [zn, ntwo]) == (z, 0, 0)
    assert scaled_prod(fmt, [zn, zn]) == (z, 0, 0)


@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_scaled_prod_never_signals_divide_by_zero(fmt):
    """9.4: "These operations should not signal the divideByZero
    exception, even if implemented with logB." Ours is not implemented
    with logB - the binade comes out of the encoding - and a zero never
    reaches the tree at all."""
    rng = random.Random(0xD10 ^ fmt.man_w)
    from cft_golden import FLAG_DIVZERO
    for _ in range(200):
        n = rng.randint(1, 12)
        xs = sq_pool(fmt, rng, n)
        ys = sq_pool(fmt, rng, n)
        for kind in SCALED_KINDS:
            for rnd in RND_MODES:
                _pr, _sf, flags = scaled_prod(fmt, xs, ys, kind, rnd)
                assert not (flags & FLAG_DIVZERO)


@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_scaled_prod_sum_and_diff_are_the_composition(fmt):
    """scaledProdSum(p, q) == scaledProd(add(p, q)) with the adds' flags
    OR'd in, and the same for Diff with sub. One rounding per leaf."""
    rng = random.Random(0x5D1F ^ fmt.man_w)
    for n in TREE_SIZES:
        for rnd in RND_MODES:
            xs = sq_pool(fmt, rng, n)
            ys = sq_pool(fmt, rng, n)
            for kind, op in ((SP_PROD_SUM, add), (SP_PROD_DIFF, sub)):
                leaves, lf = [], 0
                for a, b in zip(xs, ys):
                    s, f = op(fmt, a, b, rnd)
                    leaves.append(s)
                    lf |= f
                pr, sf, flags = scaled_prod(fmt, xs, ys, kind, rnd)
                wpr, wsf, wfl = scaled_prod(fmt, leaves, None, SP_PROD, rnd)
                assert (pr, sf) == (wpr, wsf), (n, rnd, kind)
                assert flags == (wfl | lf), (n, rnd, kind)


@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_only_the_leaf_add_can_overflow_or_underflow(fmt):
    """The product tree cannot signal either; the leaf sum can, and
    then 9.4's infinity or zero row takes over. Both directions
    demonstrated with witnesses rather than asserted."""
    big = max_normal_bits(fmt)
    # maxfinite + maxfinite overflows to +inf under rne, and the
    # infinity row then delivers +inf.
    pr, sf, flags = scaled_prod(fmt, [big, one_bits(fmt)],
                                [big, one_bits(fmt)], SP_PROD_SUM, RND_RNE)
    assert flags & FLAG_OVERFLOW and flags & FLAG_INEXACT
    assert pr == inf_bits(fmt, 0) and sf == 0

    # two neighbouring subnormals whose difference underflows to a
    # smaller subnormal is EXACT (no flag); one whose sum rounds is not.
    sub2 = min_subnormal_bits(fmt) + 1
    pr, sf, flags = scaled_prod(fmt, [sub2], [min_subnormal_bits(fmt)],
                                SP_PROD_DIFF, RND_RNE)
    assert flags == 0                       # exact subnormal: no underflow
    assert sf == fmt.emin - fmt.man_w and pr == one_bits(fmt)

    # a plain scaledProd over the same operands raises nothing but
    # inexact, ever - that is the invariant, sampled here.
    rng = random.Random(0x0F1 ^ fmt.man_w)
    for _ in range(200):
        xs = [rand_finite(fmt, rng, spread=fmt.emax - 2)
              for _ in range(rng.randint(1, 24))]
        _pr, _sf, flags = scaled_prod(fmt, xs, None, SP_PROD,
                                      rng.choice(RND_MODES))
        assert not (flags & (FLAG_OVERFLOW | FLAG_UNDERFLOW | FLAG_INVALID))


def test_scale_out_of_range_is_invalid_and_a_quiet_nan():
    """9.4: "If the scale factor is too large in magnitude to be
    represented exactly in the format of sf, then these operations shall
    signal the invalid operation exception and by default return quiet
    NaN for pr".

    Unreachable with a real int64 - a vector would need ~3.5e13 fp256
    elements - so the RULE is tested by narrowing the bound, which is
    the only honest way to exercise it at all. The real bound is
    asserted separately, below.
    """
    fmt = FP32
    xs = [((fmt.bias + 100) << fmt.man_w)] * 4        # 2^100 each
    assert scaled_prod(fmt, xs) == (one_bits(fmt), 400, 0)

    lo, hi = _reduce.SCALE_MIN, _reduce.SCALE_MAX
    try:
        _reduce.SCALE_MIN, _reduce.SCALE_MAX = -350, 350
        pr, sf, flags = scaled_prod(fmt, xs)
        assert pr == qnan_bits(fmt)
        assert sf == 0
        assert flags == FLAG_INVALID
        # and one that still fits comes back normally
        assert scaled_prod(fmt, xs[:3]) == (one_bits(fmt), 300, 0)
    finally:
        _reduce.SCALE_MIN, _reduce.SCALE_MAX = lo, hi


def test_scale_bound_is_int64():
    """The scale's declared range, which the C entry points return as an
    int64_t and the header pins."""
    assert SCALE_MIN == -(2 ** 63)
    assert SCALE_MAX == 2 ** 63 - 1
    # the per-element contribution that makes the guard unreachable:
    # a leaf adds at most emax + p - 1 and a node at most 2.
    worst = FP256.emax + FP256.prec - 1
    assert worst == 262379
    assert SCALE_MAX // (worst + 2) > 3.4e13


def test_scaled_kinds_are_distinct_and_named():
    assert len(set(SCALED_KINDS)) == 3
    assert set(SCALED_KIND_NAMES) == set(SCALED_KINDS)
    assert SCALED_KIND_NAMES[SP_PROD] == "scaledProd"


def test_new_reduction_opcodes_are_appended_not_inserted():
    """28 and 29, after the divide/sqrt seeds at 26 and 27. An opcode
    number is on the wire and in every published vector set, so this
    asserts the NUMBERS rather than the order of an enum."""
    assert OP_SUM == 24 and OP_DOT == 25
    assert OP_SUMSQ == 28 and OP_SUMABS == 29
    assert REDUCE_OPS == (24, 25, 28, 29)
    assert REDUCE_OP_NAMES[OP_SUMSQ] == "sumsq"
    assert REDUCE_OP_NAMES[OP_SUMABS] == "sumabs"
