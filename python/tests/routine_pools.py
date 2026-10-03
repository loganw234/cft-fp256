# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The lanes a routine is held on (C4): test_divfull's pools, gathered in
one place so that python/tests/test_routines.py and the lang stage's full
leg (programs/lang_check.py) run the same lanes.

  div_pairs(fmt, light)  every special against every special (test_divfull's
                         specials), the subnormal boundary (quotients on,
                         above and below the subnormal grid, and the carry
                         at emin - 1 that is not tiny), the overflow
                         boundary, test_sequences' pool against its divisor
                         head, and the hard families
  sqrt_xs(fmt, light)    both signs of the specials, subnormals, exponents
                         of both parities about the bias and near emin and
                         emax, the pool, the hard families

`light` takes fewer random lanes of each family (the golden stage's cut);
the specials and the hard families are whole either way.
"""

import random

from cft_golden import min_normal_bits, one_bits

from test_divfull import specials
from test_sequences import pool_for

_EXTRA = {32: 24, 64: 24, 128: 8, 256: 6}


def div_pairs(fmt, light=True):
    S = specials(fmt)
    pairs = [(a, b) for a in S for b in S]
    mw = fmt.man_w
    rng = random.Random(fmt.width)
    for _ in range(20 if light else 80):
        ea = fmt.emin + rng.randrange(-2, fmt.prec + 3)
        a = ((ea + fmt.bias) << mw) | rng.getrandbits(mw) \
            if ea + fmt.bias > 0 else rng.getrandbits(mw)
        b = (fmt.bias << mw) | rng.getrandbits(mw)
        pairs += [(a, b), (a | fmt.sign_mask, b), (a, b | fmt.sign_mask)]
    a = ((fmt.emin - 1 + fmt.bias) << mw) | fmt.man_mask
    one = one_bits(fmt)
    pairs += [(a, one), (a | fmt.sign_mask, one), (a, one + 1), (a, one - 1)]
    rng = random.Random(fmt.width + 1)
    for _ in range(15 if light else 60):
        a = ((fmt.emax - rng.randrange(0, 3) + fmt.bias) << mw) | \
            rng.getrandbits(mw)
        b = ((fmt.bias - rng.randrange(0, 3)) << mw) | rng.getrandbits(mw)
        pairs += [(a, b), (a | fmt.sign_mask, b), (a, b | fmt.sign_mask)]
    pool = pool_for(fmt, _EXTRA[fmt.width])
    dens = pool[:min(len(pool), 18 if fmt.width <= 64 else 8)]
    if light:
        dens = dens[:6]
    pairs += [(a, b) for a in pool for b in dens]
    pairs += [(one, one - 1), (one, one + 1), (one - 1, one), (one + 1, one),
              (one, one | fmt.man_mask), (one | fmt.man_mask, one)]
    return pairs


def sqrt_xs(fmt, light=True):
    xs = specials(fmt) + [1 | fmt.sign_mask, fmt.man_mask | fmt.sign_mask,
                          min_normal_bits(fmt) | fmt.sign_mask]
    rng = random.Random(fmt.width + 3)
    mw = fmt.man_w
    k = 20 if light else 80
    xs += [rng.getrandbits(mw) for _ in range(k)]
    for _ in range(k):
        e = fmt.emin + rng.randrange(0, 2 * fmt.prec)
        xs.append(((e + fmt.bias) << mw) | rng.getrandbits(mw))
    for _ in range(k):
        e = rng.randrange(-8, 9)
        xs.append(((fmt.bias + e) << mw) | rng.getrandbits(mw))
    for _ in range(k // 2):
        e = fmt.emax - rng.randrange(0, 4)
        xs.append(((fmt.bias + e) << mw) | rng.getrandbits(mw))
    one = one_bits(fmt)
    mn = min_normal_bits(fmt)
    xs += pool_for(fmt, _EXTRA[fmt.width]) + [
        one + 1, mn + 1, mn - 1, one - 1, one, one | fmt.man_mask,
        mn | (fmt.man_mask >> 1), ((fmt.bias + 1) << fmt.man_w) + 1]
    return xs
