# M2 model: the reduction's edge arguments (scratch; the study's 2.2 and
# section 8, item 2).
#
# The generator's static proofs bound every piece of the reduction by the
# extremes of its product T_j = M c 2^-(jb) over the chunks c that can
# stand at position j. Random arguments rarely bring a product next to a
# power of two, where a piece's grid changes and a sum the proofs call
# exact is nearest to failing: the exact-add plant (a TwoSum the proofs
# need, replaced by a plain add) passed every random and pool lane. This
# family puts each product there: for every bucket g-1 the range has,
# every position j whose chunk c is nonzero, the significands M around
# M0 = ceil(2^K / c), where 2^K is the power of two inside
# [2^(p-1) c, 2^p c), and the two ends 2^(p-1) and 2^p - 1; at three
# exponents of the bucket (sigma = 2 - b, the middle, 1), positive.
#
#   edges(fmt, P) -> [encodings]

from m2core import sf, RNE


def edges(fmt, P, ms_around=(-2, -1, 0, 1)):
    p = fmt.prec
    lo, hi = 1 << (p - 1), (1 << p) - 1
    out = set()
    for gm1 in range(P.gm1_min, P.gm1_max + 1):
        Ms = {lo, hi}
        for j in range(P.L):
            k = gm1 + j
            if k < 0 or k >= len(P.c) or P.c[k] == 0:
                continue
            c = P.c[k]
            K = (p - 1) + c.bit_length()
            if c & (c - 1) == 0:          # a power of two: the edge is the low end
                K -= 1
            M0 = -((-(1 << K)) // c)       # ceil(2^K / c)
            for d in ms_around:
                M = M0 + d
                if lo <= M <= hi:
                    Ms.add(M)
        for i in (0, P.b // 2, P.b - 1):
            E = gm1 * P.b + i + p + 1      # G0 = E - p - 1 = gm1 b + i
            if not (P.Egate <= E <= P.Emax):
                continue
            for M in Ms:
                out.add(sf.round_pack(fmt, 0, M, E - p + 1, RNE)[0])
    return sorted(out)
