# M2 model: the radian pools and the comparison against transcend.py
# (scratch).

import importlib.util
import random

from m2core import sf, evaluate, dec, enc, RNE, ROOT, FORMATS
from cft_golden import transcend as tr, vectors

_spec = importlib.util.spec_from_file_location(
    "transcend_check", str(ROOT / "host" / "tests" / "transcend_check.py"))
tc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tc)


def brute_pool(fmt):
    """test_transcend.py's _brute_pool, transcribed (it imports pytest);
    test_brute_force_enclosure_agrees sweeps it over every function."""
    p = fmt.prec

    def V(sign, m, e):
        b, fl = sf.round_pack(fmt, sign, m, e, RNE)
        assert fl == 0
        return b
    one = sf.one_bits(fmt)
    return [one, one + 1, one - 1, sf.one_bits(fmt, 1),
            sf.one_bits(fmt, 1) + 1, V(0, 3, -1), V(1, 3, -1), V(0, 1, 1),
            V(1, 1, 1), V(0, 3, 0), V(0, 5, -2), sf.min_normal_bits(fmt),
            sf.max_normal_bits(fmt), sf.min_subnormal_bits(fmt),
            sf.max_subnormal_bits(fmt), sf.min_normal_bits(fmt, 1),
            sf.max_normal_bits(fmt, 1), V(0, 1, -p), V(1, 1, -p),
            V(0, 7, -p - 2), V(0, (1 << p) - 1, -p + 1)]


def pools(fmt):
    """The radian pools: the stage's (transcend_check.radian_pool at its
    default trials and seed), the vector sets' (vectors.radian_unary_pool
    as transcend_cases calls it: extra 24, seed 14) and test_transcend's
    brute pool, deduplicated."""
    t = 64 if fmt.width <= 64 else 16
    a = tc.radian_pool(fmt, t, 5)
    b = vectors.radian_unary_pool(fmt, 24, 14)
    c = brute_pool(fmt)
    return sorted(set(a) | set(b) | set(c))


def compare(f, fn, xs, rnd, stop_on_wrong=20):
    """Each x through the model and through transcend.py.
    -> dict: n, marked, marked_right, wrong (unmarked mismatches), marks"""
    fmt = f.fmt
    st = {"n": 0, "marked": 0, "marked_right": 0, "wrong": [], "marks": [],
          "words": set()}
    for xa in xs:
        bits, fw, _ = evaluate(f, xa)
        gb, gf = tr.compute(fmt, fn, xa, 0, rnd)
        st["n"] += 1
        st["words"].add(fw)
        if fw & ~0x9F:
            st["wrong"].append((hex(xa), "flag word bits [6:5]", hex(fw)))
        if fw & 0x80:
            st["marked"] += 1
            st["marks"].append(hex(xa))
            if bits == gb and (fw & 0x1F) == gf:
                st["marked_right"] += 1
            continue
        if bits != gb or fw != gf:
            st["wrong"].append((hex(xa), (hex(bits), fw), (hex(gb), gf)))
            if len(st["wrong"]) >= stop_on_wrong:
                break
    return st
