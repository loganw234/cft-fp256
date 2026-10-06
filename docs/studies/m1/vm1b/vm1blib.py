# verifier-VM1b's probes: common setup. Written by verifier-VM1b for its check
# of b252824 (2026-10-05; its ledger, Data/runs/2026-10-02-step6-round/ledger/
# verifier-VM1b.md, which is outside the tree), and committed here by parcel
# M1 with one change: the model is imported from the directory above this
# one (docs/studies/m1), not from VM1b's frozen tree.
#
# The tool: adlib.py attributes a lane's error V - true to each rounding, to
# first order; p5_budget.py (uniform arguments) and p5c_budget_end.py (half
# of them at one end of the region) sum each rounding's capacity, the most it
# could add, over a region. p10_cells.py and p8_bound_g.py are the sampling
# scripts of the box batch VM1b-1. Run from this directory, e.g. the box's
# job budget-G46-log2:
#     python p5_budget.py fp64 log2 46 7/8 241/256 3000 173 12
# (PYTHONDONTWRITEBYTECODE=1 keeps __pycache__ out of the tree.)
import os
import sys

M1DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.dont_write_bytecode = True
sys.path.insert(0, M1DIR)           # m1core puts <tree>/python on the path itself

from fractions import Fraction      # noqa: E402

import mpmath                        # noqa: E402

from m1core import (Frag, enc, enc_exact, dec, pow2_bits, evaluate, RNE, RTZ,   # noqa: E402,F401
                    RDN, RUP, RMM, sf)
from m1exp import build_exp, exp_plan                    # noqa: E402,F401
from m1log import build_log, log_plan, RHO, SMALL        # noqa: E402,F401
from m1harness import FORMATS, tr, pools, domain_sample, compare  # noqa: E402,F401
from cft_golden import routines, seq                     # noqa: E402,F401

ATTRS = (RNE, RTZ, RDN, RUP, RMM)
FNS = ("exp", "exp2", "expm1", "log", "log2", "log1p")


def build(fmt, rnd, fn, **kw):
    return build_exp(fmt, rnd, fn, **kw) if fn.startswith("exp") else build_log(fmt, rnd, fn, **kw)


def fr(mp):
    """mpf -> exact Fraction."""
    man, ex = mpmath.libmp.to_man_exp(mp._mpf_)
    return Fraction(int(man)) * (Fraction(2) ** int(ex))


def M(q):
    """Fraction -> mpf."""
    return mpmath.mpf(q.numerator) / q.denominator
