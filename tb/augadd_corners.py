"""The corners of augmentedAddition (R21), as operand pools: verifier-VC56's
generator (2026-10-05, its scratch vc56_gen.py), adopted as it wrote it for
the two cases of its that the benches carry - tb/test_seq_core.py's
`augadd_stream_need_by_role` and tb/test_krnl_seq.py's
`krnl_elementwise_after_augadd_at_ties`. Model side only: no cocotb here.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from cft_golden import softfloat as sf  # noqa: E402


def mk(fmt, sign, ef, frac):
    return ((sign << (fmt.width - 1)) | (ef << fmt.man_w)
            | (frac & fmt.man_mask))


def dedup(vals):
    seen, out = set(), []
    for v in vals:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def corner_pool(fmt):
    """About sixty encodings at the corners of augmentedAddition: signed
    zeros, subnormals, the binade edges, one and its neighbours, the top
    binade, half and quarter ulps of one and of the top binade (the exact
    ties), both infinities, and NaNs of three kinds."""
    mb = fmt.man_w
    p = mb + 1
    top = fmt.exp_mask - 1
    bias = fmt.bias
    v = []
    for s in (0, 1):
        v += [mk(fmt, s, 0, 0)]
        v += [mk(fmt, s, 0, 1), mk(fmt, s, 0, 2), mk(fmt, s, 0, fmt.man_mask),
              mk(fmt, s, 0, fmt.man_mask - 1)]
        v += [mk(fmt, s, 1, 0), mk(fmt, s, 1, 1)]
        v += [mk(fmt, s, bias, 0), mk(fmt, s, bias, 1), mk(fmt, s, bias, 2),
              mk(fmt, s, bias, 3), mk(fmt, s, bias, 1 << (mb - 1)),
              mk(fmt, s, bias - 1, fmt.man_mask), mk(fmt, s, bias + 1, 0)]
        v += [mk(fmt, s, top, fmt.man_mask), mk(fmt, s, top, fmt.man_mask - 1),
              mk(fmt, s, top, 0), mk(fmt, s, top - 1, fmt.man_mask)]
        for d in (p - 1, p, p + 1, p + 2):          # ulp, half, quarter of 1.0
            v += [mk(fmt, s, bias - d, 0), mk(fmt, s, bias - d, 1)]
        for d in (p - 1, p, p + 1):                 # the same in the top binade
            v += [mk(fmt, s, top - d, 0), mk(fmt, s, top - d, 1)]
        v += [mk(fmt, s, fmt.exp_mask, 0)]          # infinities
    v += [sf.qnan_bits(fmt), sf.snan_bits(fmt, 1),
          sf.snan_bits(fmt, (1 << (mb - 1)) - 1),
          mk(fmt, 1, fmt.exp_mask, (1 << (mb - 1)) | 5)]
    return dedup(v)


def pool_pairs(fmt, limit=None):
    """Every unordered pair of the corner pool (with itself): the program
    computes each pair in both operand orders, so ordered pairs would be
    repeats."""
    pool = corner_pool(fmt)
    out = []
    for i, x in enumerate(pool):
        for y in pool[i:]:
            out.append((x, y))
    return out if limit is None else out[:limit]
