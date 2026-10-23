# M4 model: the tiny family's centres at fp64 (scratch; the study's 3.5):
# atan and asin at c 2^-e, c 1..16, e 20..33, through the unplanted
# fragments under all five attributes; prints each argument that marks and
# the attributes it marks under. Kept after verifier-VM4S's note, so that
# 3.5's centres can be re-run from the tree.
#
#   python tinyc.py
from m4core import FORMATS, sf, evaluate2, ATTRS, RNE
from m4inv import build, gates, GUARD
fmt = FORMATS["fp64"]; p, G = fmt.prec, GUARD["fp64"]
ga, gs = gates(fmt)
for fn in ("atan", "asin"):
    frs = {r: build(fmt, r, fn) for r in ATTRS}
    hits = {}
    for e in range(20, 34):
        for c in range(1, 17):
            x = sf.round_pack(fmt, 0, c, -e, RNE)[0]
            ms = [sf.RND_NAMES[r] for r in ATTRS if evaluate2(frs[r], x)[1] & 0x80]
            if ms:
                hits[(c, e)] = ms
    print(fn, {f"{c}*2^-{e}": v for (c, e), v in hits.items()})
