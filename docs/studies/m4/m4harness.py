# M4 model: the inverse-trigonometric pools and the comparison against
# transcend.py (scratch).
#
# The unary pool is the stage's (transcend_check.trig_pool at its default
# trials and seed, 64 random at fp32 and fp64 and 16 above, seed 5) with the
# vector sets' (vectors.trig_unary_pool as transcend_cases calls it: extra
# 24, seed 12), deduplicated. atan2's pairs are the stage's
# (transcend_check.atan2_pairs, same trials and seed) with the vector sets'
# (vectors.trig_atan2_pairs: extra 24, seed 13).

import importlib.util

from m4core import sf, evaluate2, ROOT
from cft_golden import transcend as tr, vectors

_spec = importlib.util.spec_from_file_location(
    "transcend_check", str(ROOT / "host" / "tests" / "transcend_check.py"))
tc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tc)


def trials(fmt):
    return 64 if fmt.width <= 64 else 16


def unary_pool(fmt):
    a = tc.trig_pool(fmt, trials(fmt), 5)
    b = vectors.trig_unary_pool(fmt, 24, 12)
    return sorted(set(a) | set(b))


def pair_pool(fmt):
    a = tc.atan2_pairs(fmt, trials(fmt), 5)
    b = vectors.trig_atan2_pairs(fmt, 24, 13)
    seen, out = set(), []
    for pr in list(a) + list(b):
        if pr not in seen:
            seen.add(pr)
            out.append(pr)
    return out


def pool(fmt, fn):
    return pair_pool(fmt) if fn == "atan2" else unary_pool(fmt)


def golden(fmt, fn, args, rnd):
    if fn == "atan2":
        return tr.compute(fmt, fn, args[0], args[1], rnd)
    return tr.compute(fmt, fn, args, 0, rnd)


def compare(f, fn, xs, rnd, stop_on_wrong=20):
    """Each argument through the model and through transcend.py.
    -> dict: n, marked, marked_right, wrong (unmarked mismatches), marks,
    the flag words seen."""
    fmt = f.fmt
    st = {"n": 0, "marked": 0, "marked_right": 0, "wrong": [], "marks": [],
          "words": set()}
    for xa in xs:
        bits, fw, _ = evaluate2(f, xa)
        gb, gf = golden(fmt, fn, xa, rnd)
        st["n"] += 1
        st["words"].add(fw)
        shown = (tuple(hex(v) for v in xa) if isinstance(xa, tuple)
                 else hex(xa))
        if fw & ~0x9F:
            st["wrong"].append((shown, "flag word bits [6:5]", hex(fw)))
        if fw & 0x80:
            st["marked"] += 1
            st["marks"].append(shown)
            if bits == gb and (fw & 0x1F) == gf:
                st["marked_right"] += 1
            continue
        if bits != gb or fw != gf:
            st["wrong"].append((shown, (hex(bits), fw), (hex(gb), gf)))
            if len(st["wrong"]) >= stop_on_wrong:
                break
    return st
