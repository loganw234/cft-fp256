"""Table A: the operands (and pairs) vectors.py directs at each group of
functions, by the line of the generator that builds them, against what the
oracle's pools held before and what they hold now.

Usage, from the repository's root:

    python -B host/tools/audit-pools/audit_table.py BEFORE AFTER > tableA.md

BEFORE is the dump of the pools as they were: the dump of the tool at commit
b2fd894f with its extras lines removed (grep -v '^C [^ ]* [^ ]* e '), which
is the dump of the tool before the audit.  AFTER is the dump of the tool now.
Writes Table A of docs/TRANSCENDENTALS.md.
"""
import sys, collections
import os  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_lib import *   # noqa
import vtag

before = parse_dump(sys.argv[1])
after = parse_dump(sys.argv[2])
M = vtag.load()
SRC = open(M.__file__).read().splitlines()

LONG = 2147483647
IO = {26, 42, 44}
NAMES = {
 "transcend_unary_pool": {
    "io": "the specials and extremes of both signs; NaNs with payload",
    246: "1 +- ulp, both signs", 254: "integers 1..24, p, 2p, emax-1..emax+1, emin-1.., to emin-man_w-1",
    261: "powers of two, with a neighbour each side", 269: "powers of ten 5^k 2^k, with neighbours",
    291: "n ln 2, rounded and walked two ulps (overflow and underflow edges)",
    296: "2^-k and 3 2^(-k-1), k = p+2 .. 2p (the neighbour rules)"},
 "trig_unary_pool": {
    "io": "the specials and extremes of both signs; NaNs with payload",
    422: "1 +- ulp, both signs", 435: "halves, quarters, integers and eighths, with neighbours",
    443: "the top of the range, 2^k for k = p-1 .. emax", 450: "2^-k and 3 2^(-k-1), k = p/2 .. 4p",
    456: "1 - 2^-p and 1 - 2^(1-p) (asin's domain edge)"},
 "radian_unary_pool": {
    "io": "the specials and extremes of both signs; NaNs with payload",
    559: "every power of two over the exponent range (sampled at the wide two)",
    565: "2^k and 2^k - 1ulp at the ends and p, 2p", 567: "the reduction's worst cases (pi_worstcase.py)",
    572: "2^-k and 3 2^(-k-1), k = p/2-1 .. 2p"},
 "hyperbolic_unary_pool": {
    "io": "the specials and extremes of both signs; NaNs with payload",
    594: "1 +- ulp, both signs", 603: "small integers, halves, quarters, with neighbours",
    620: "n ln 2 +- 2 ulps (the sinh/cosh overflow edge), both signs", 627: "2^k near 2^bitlen(p+2) (tanh -> 1)",
    633: "2^-k and 3 2^(-k-1), k = p/2-1 .. 4p"},
 "table91_unary_pool": {
    "io": "the specials and extremes of both signs; NaNs with payload",
    804: "1 +- ulp, both signs", 813: "integers 1..11, p-1..p+3, 2p, emax-1..emax+1, emin, emin-man_w",
    819: "powers of ten 5^k 2^k, with neighbours", 821: "10^k - 1", 828: "2^k - 1 and 2^-k (2^k - 1), k <= min(p, 40)",
    835: "powers of two -6..6, +-p, emax, emin, with neighbours", 839: "2^-k and 3 2^(-k-1), k = p+2 .. 2p"},
 "transcend_pow_pairs": {
    315: "the specials against the specials", 326: "integer exponents against 2, 3, 5, 7, 10, 4097",
    333: "perfect powers against dyadic exponents", 334: "perfect powers against dyadic exponents",
    335: "perfect powers against dyadic exponents", 336: "perfect powers against dyadic exponents",
    346: "a base 1 +- dy ulp against exponents across the range", 347: "a base 1 +- dy ulp against exponents across the range",
    358: "pow(1+u, -(1+u)), the escalating family", 359: "pow(1+u, -(1+u)), the escalating family", 360: "pow(1+u, -(1+u)), the escalating family"},
 "transcend_hypot_pairs": {
    377: "the ten pairs, both signs", 378: "the ten pairs, one ulp off", 379: "the ten pairs, one ulp off",
    381: "the ten pairs scaled to the range's ends", 385: "a dominant operand", 386: "a dominant operand", 387: "a dominant operand",
    388: "extremes, zeros, infinities and NaNs"},
 "trig_atan2_pairs": {
    "untagged": "the axes against the axes", 489: "the diagonals and one ulp off them", 492: "min subnormal over 2, 4, 1",
    498: "tiny y against 1, -1, 2, 3", 504: "big and small against 1 and -1"},
 "transcend_int_pow_cases": {
    "io": "the specials and extremes (operand only)", 889: "perfect powers m 2^e, both signs (operand only)",
    892: "perfect powers +- 1 ulp (operand only)", 896: "2^e (operand only)", 899: "2^-k (operand only)",
    "untagged": "the first seventeen operands: zeros, infinities, NaNs, +-1 and its neighbours, +-min subnormal, +-max normal",
    913: "(operand, n) in the generator's stride, n within the host's long", 916: "(operand, n) for n = 0, 1, 2, -1, -2"},
 "transcend_powr_pairs": {
    315: "the specials against the specials", 326: "integer exponents against 2, 3, 5, 7, 10, 4097",
    333: "perfect powers against dyadic exponents", 334: "perfect powers against dyadic exponents",
    335: "perfect powers against dyadic exponents", 336: "perfect powers against dyadic exponents",
    346: "a base 1 +- dy ulp against exponents across the range", 347: "a base 1 +- dy ulp against exponents across the range",
    358: "pow(1+u, -(1+u)), the escalating family", 359: "pow(1+u, -(1+u)), the escalating family", 360: "pow(1+u, -(1+u)), the escalating family",
    857: "powr's own table: negative bases, zeros, infinities, NaNs"},
}
GROUPS = [
 ("exp, expm1, exp2, log, log1p, log2, log10", "transcend_unary_pool", "exp", "u"),
 ("sinpi, cospi, tanpi, asin, acos, atan, asinpi, acospi, atanpi", "trig_unary_pool", "sinpi", "u"),
 ("sin, cos, tan", "radian_unary_pool", "sin", "u"),
 ("sinh, cosh, tanh, asinh, acosh, atanh", "hyperbolic_unary_pool", "sinh", "u"),
 ("exp2m1, exp10, exp10m1, log2p1, log10p1, rsqrt", "table91_unary_pool", "exp2m1", "u"),
 ("pow", "transcend_pow_pairs", "pow", "p"),
 ("hypot", "transcend_hypot_pairs", "hypot", "p"),
 ("atan2, atan2pi", "trig_atan2_pairs", "atan2", "p"),
 ("powr", "transcend_powr_pairs", "powr", "p"),
 ("pown, compound, rootn", "transcend_int_pow_cases", "pown", "i"),
]
FM = ["fp32", "fp64", "fp128", "fp256"]


def rows_for(builder, fn, kind):
    out = collections.OrderedDict()
    for fname in FM:
        fmt = FMTS[fname]
        vtag.TAG.clear()
        vec = getattr(M, builder)(fmt, 0)
        io = set(M.interesting_operands(fmt)) if kind in ("u", "i") else set()
        if kind == "i":
            opset = set(a for (a, k) in vec)
            vec = [("op", a) for a in sorted(opset)] + [e for e in vec]
        tag = {k: set(v) for k, v in vtag.TAG.items()}
        if kind == "u":
            ob = first_operands(before, fname, fn); oa = first_operands(after, fname, fn)
        elif kind == "i":
            ob = pairs(before, fname, fn) | {("op", a) for a in first_operands(before, fname, fn)}
            oa = pairs(after, fname, fn) | {("op", a) for a in first_operands(after, fname, fn)}
        else:
            ob = pairs(before, fname, fn); oa = pairs(after, fname, fn)
        fam = collections.defaultdict(set)
        for e in vec:
            ls = tag.get(e, set())
            if kind == "u":
                if e in io or ls & IO:
                    fam["io"].add(e)
                for ln in ls - IO:
                    fam[NAMES[builder].get(ln, "L%d" % ln)].add(e) if False else fam[ln].add(e)
            elif kind == "i":
                if isinstance(e, tuple) and e[0] == "op":
                    a = e[1]
                    ls2 = tag.get(a, set())
                    if a in io or ls2 & IO:
                        fam["io"].add(e)
                    if not ls2 and a not in io:
                        fam["untagged"].add(e)
                    for ln in ls2 - IO:
                        if ln in (889, 892, 896, 899):
                            fam[ln].add(e)
                else:
                    if -LONG <= e[1] <= LONG:
                        for ln in ls:
                            fam[ln].add(e)
            else:
                if not ls:
                    fam["untagged"].add(e)
                for ln in ls:
                    fam[ln].add(e)
        for key, es in fam.items():
            name = NAMES[builder].get(key, "L%s" % key)
            r = out.setdefault(name, {f: [0, 0, 0] for f in FM})
            # merge lines of one name: union of elements
            r.setdefault("_set", {})
            r["_set"].setdefault(fname, set()).update(es)
        for name, r in out.items():
            s = r.get("_set", {}).get(fname, set())
            r[fname] = [len(s), len(s & ob), len(s & oa)]
    return out


md = []
for title, builder, fn, kind in GROUPS:
    rows = rows_for(builder, fn, kind)
    md.append("**%s**" % title)
    md.append("")
    md.append("| family | need | held before | held after |")
    md.append("|---|---|---|---|")
    for name, r in rows.items():
        need = "/".join(str(r[f][0]) for f in FM)
        hb = "/".join(str(r[f][1]) for f in FM)
        ha = "/".join(str(r[f][2]) for f in FM)
        md.append("| %s | %s | %s | %s |" % (name, need, hb, ha))
    md.append("")
print("\n".join(md))
