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

import pytest

from cft_golden import (
    FP32, FP64, FP128, FP256, FORMATS,
    RND_RNE, RND_RTZ, RND_RDN, RND_RUP, RND_RMM, RND_MODES,
    FLAG_INVALID, FLAG_INEXACT,
    add, mul, zero_bits, one_bits, inf_bits, qnan_bits, snan_bits,
    negate, is_nan, vectors,
)
from cft_golden.reduce import (
    OP_SUM, OP_DOT, REDUCE_OPS, REDUCE_OP_NAMES,
    split, tree_adds, canonical_ranges, reduce_bits, fsum, fdot, combine,
    stream_reduce,
)

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
