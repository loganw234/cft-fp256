# M1 model: the pools and the comparison against transcend.py (scratch).

import importlib.util
import random
import sys
import time

from m1core import sf, evaluate, dec, enc, RNE
from cft_golden import transcend as tr, vectors, FORMATS

import os
import pathlib

ROOT = str(pathlib.Path(__file__).resolve().parents[3])
_spec = importlib.util.spec_from_file_location(
    "transcend_check", os.path.join(ROOT, "host", "tests", "transcend_check.py"))
tc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tc)


def brute_pool(fmt):
    """test_transcend.py's _brute_pool, transcribed (it imports pytest)."""
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
    """The transcend pools: the stage's (transcend_check.unary_pool at
    its default trials and seed), the vector sets' and test_transcend's
    brute pool, deduplicated."""
    t = 64 if fmt.width <= 64 else 16
    a = tc.unary_pool(fmt, t, 5)
    b = vectors.transcend_unary_pool(fmt, t, 9)
    c = brute_pool(fmt)
    return sorted(set(a) | set(b) | set(c))


def domain_sample(fmt, fn, n, seed=1):
    """Random arguments inside the main path, by function: exp-like over
    the whole finite non-overflowing range, log-like over every binade
    and near 1, log1p over (-1, inf)."""
    rng = random.Random(seed * 1000003 + fmt.width)
    out = []
    p = fmt.prec
    lo_e = fmt.emin - p
    for _ in range(n):
        mode = rng.random()
        if fn in ("exp", "expm1"):
            # uniform in x over the range, plus small |x|
            if mode < 0.6:
                xmax = (fmt.emax + 1) * 0.6931471805599453
                xmin = (fmt.emin - p) * 0.6931471805599453
                v = rng.uniform(xmin, xmax)
                b = enc(fmt, __import__("fractions").Fraction(v))
            else:
                e = rng.randint(-(p + 2), 4)
                b = sf.round_pack(fmt, rng.getrandbits(1),
                                  rng.getrandbits(p) | (1 << (p - 1)),
                                  e - p + 1, RNE)[0]
            out.append(b)
        elif fn == "exp2":
            if mode < 0.6:
                v = rng.uniform(fmt.emin - p, fmt.emax + 1)
                b = enc(fmt, __import__("fractions").Fraction(v))
            else:
                e = rng.randint(-(p + 2), 4)
                b = sf.round_pack(fmt, rng.getrandbits(1),
                                  rng.getrandbits(p) | (1 << (p - 1)),
                                  e - p + 1, RNE)[0]
            out.append(b)
        elif fn in ("log", "log2"):
            if mode < 0.5:
                b = rng.getrandbits(fmt.width - 1)      # every positive
            else:
                e = rng.randint(-(p + 2), -1)
                d = sf.round_pack(fmt, 0, rng.getrandbits(p) | (1 << (p - 1)),
                                  e - p + 1, RNE)[0]
                one = sf.one_bits(fmt)
                b = sf.compute(fmt, sf.OP_ADD if rng.random() < .5 else
                               sf.OP_SUB, one, 0, d, RNE)[0]
            out.append(b)
        else:   # log1p
            if mode < 0.4:
                b = rng.getrandbits(fmt.width - 1)
            elif mode < 0.7:
                e = rng.randint(-(p + 2), 0)
                b = sf.round_pack(fmt, rng.getrandbits(1),
                                  rng.getrandbits(p) | (1 << (p - 1)),
                                  e - p + 1, RNE)[0]
            else:
                e = rng.randint(-p, -1)
                b = sf.round_pack(fmt, 1, rng.getrandbits(p) | (1 << (p - 1)),
                                  e - p + 1, RNE)[0]
            out.append(b)
    return out


def compare(f, fn, xs, rnd, stop_on_wrong=20):
    """Each x through the model and through transcend.py.
    -> dict: n, marked, marked_right, wrong (unmarked mismatches), list"""
    fmt = f.fmt
    st = {"n": 0, "marked": 0, "marked_right": 0, "wrong": [], "marks": []}
    for xa in xs:
        bits, fw, _ = evaluate(f, xa)
        gb, gf = tr.compute(fmt, fn, xa, 0, rnd)
        st["n"] += 1
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
