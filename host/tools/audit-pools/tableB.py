"""tableB.py: part of the pool audit; see docs/TRANSCENDENTALS.md.

Usage, from the repository's root:

    python -B host/tools/audit-pools/tableB.py PREFIX

PREFIX_fp32.txt ... PREFIX_fp256.txt as for merge_fam.py.  Writes the
markdown of Table B of docs/TRANSCENDENTALS.md.
"""
import re, sys, collections
pref = sys.argv[1]
FM = ["fp32", "fp64", "fp128", "fp256"]
rows = collections.OrderedDict()
for k, f in enumerate(FM):
    for line in open("%s_%s.txt" % (pref, f)):
        m = re.match(r"^  (\S+)\s+(.*)$", line)
        g = re.findall(r"(\d+)-\s*(\d+)=\s*(\d+)/(\d+)", line)
        if m and len(g) == 4:
            rows.setdefault(m.group(1), {})[f] = tuple(int(x) for x in g[k])
SRC = collections.OrderedDict([
 ("x:int-edge", ("exp, expm1, exp2, log, log1p, log2, log10", "`_exp_family`'s integer branch: `n > emax`, `n < emin - man_w - 1`, and the tie at `emin - man_w - 1`", "the integers at both ends and each side of the tie, with the operand's own neighbours")),
 ("x:pow2-sub", ("the same seven", "log2's exact case `M == 1` at the subnormal powers of two", "2^k for k from emin - man_w to emin + 1, with neighbours")),
 ("x:ln2-edge", ("the same seven", "the screens at emax + 2 and emin - man_w - 2, and the true edges at emax + 1 and emin - man_w - 1", "n ln 2 for ten n, walked two ulps, both signs")),
 ("x:tiny-edge", ("the same seven", "the tiny rules, `ex <= -(p+c)` and `2 ex + p + c <= 0` for c = 2..6", "the binade boundary of each, straddled")),
 ("t:tiny-edge", ("the nine trigonometric", "the same rules, and atanPi's `ex >= p + 1`", "the same")),
 ("t:beside-half", ("sinPi, cosPi, tanPi", "`2 s_vexp + p + 6 <= 0`, s the distance from a half-integer", "h +- 2^-j for h = 1/2 .. 3 and j round (p + 6)/2")),
 ("r:tiny-edge", ("sin, cos, tan", "the same rules", "the same")),
 ("r:worst", ("sin, cos, tan", "the reduction's hardest binades (`_reduction_worst_cases`)", "the representable numbers nearest a multiple of pi/2, found from MPFR's pi by the continued fraction, with a neighbour each side")),
 ("h:ln2-edge", ("the six hyperbolics", "`_cosh_sinh_overflow` at emax + 3 and the true edge at emax + 2", "n ln 2, walked two ulps")),
 ("h:tiny-edge", ("the six hyperbolics", "the same rules", "the same")),
 ("m:int-edge", ("exp2m1, exp10, exp10m1, log2p1, log10p1, rSqrt", "exp2m1's `n == emax + 1`, `n > emax + 1`, `abs(n) <= p + 1`", "the integers round each, with neighbours")),
 ("m:tiny-edge", ("the same six", "the same rules", "the same")),
 ("m:log2p1-edge", ("log2p1", "`_logp1_family`: x = 2^k from `k >= p - g + 1`", "2^k for the five k round the first")),
 ("m:log10-edge", ("exp10, exp10m1", "their screens: `x log2(10)` against emax + 2 and -(p + 3)", "n log10(2), walked two ulps")),
 ("pow:edge", ("pow", "`_screen_exponent`'s thresholds, and the overflow and underflow edges beneath them", "(x, y) with y at n / log2(abs(x)) for x = 3, 5, 10, 3/2, 5/4, 3/4 and n at the top and the bottom of the range, walked two ulps, and the integers round it")),
 ("powr:edge", ("powr", "the same", "the same")),
 ("pow:dyadic-wide", ("pow", "`_pow_dyadic`: `Y > p + 1`, and `root^Y` wider than p + 1 bits", "a perfect square or fourth power to Y / 2^k with Y odd, across both edges")),
 ("powr:dyadic-wide", ("powr", "the same", "the same")),
 ("hypot:exact-top", ("hypot", "`hypot:898`, the exact hypot past the largest finite", "(3, 4), (5, 12), (8, 15) scaled so that the hypot passes 2^(emax+1) and so that it does not")),
 ("hypot:wide-triples", ("hypot", "`_hypot_dyadic`: an exact hypot wider than p + 1 bits", "(2^(j+1) - 1, (2^j - 1) 2^(j+1)) for j round p/2")),
 ("atan2:tiny-over-unit", ("atan2, atan2Pi", "`2 qv + p + 3 <= 0`, `ey - ex <= -(p+1)`", "the vector set's tiny y against +-1, 2, 3, with the thresholds' k added")),
 ("int:specials", ("pown, compound, rootn", "9.2.1's rows for the zeros, infinities and NaNs", "the 18 specials against the 15 n the oracle uses")),
 ("int:exact-edge", ("pown, compound", "`_pown_dyadic`: `n > p + 1`, `M^n` wider than p + 1 bits", "M, -M and M - 1 for odd M against the n round where M^n leaves p + 1 bits")),
 ("int:perfect-power", ("rootn", "`_rootn_dyadic`: the odd significand a perfect n-th power in absolute value", "r^n, with neighbours, for r = 2 .. 13 and n = 2 .. 12")),
 ("int:subnormal-recip", ("rootn", "`rootn:2862`, the overflow screen", "3, 5, 7 times a power of two just under the format's range, against n = -1, -2, 1")),
 ("int:power-edge", ("pown", "the screens", "3, 5, 10 and their negatives against the n that takes them to 2^(emax+1) and 2^(emin-man_w-1)")),
])
print("| family | functions | where the model or the standard asks | what it holds | added of intended (fp32 / fp64 / fp128 / fp256) | cases |")
print("|---|---|---|---|---|---|")
for name, (fn, src, what) in SRC.items():
    d = rows.get(name)
    if not d:
        continue
    add = " / ".join("%d of %d" % (d.get(f, (0,0,0,0))[2], d.get(f, (0,0,0,0))[0]) for f in FM)
    cs = " / ".join("{:,}".format(d.get(f, (0,0,0,0))[3]) for f in FM)
    print("| `%s` | %s | %s | %s | %s | %s |" % (name, fn, src, what, add, cs))
