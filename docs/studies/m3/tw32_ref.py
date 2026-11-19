# M3 model: the built fp32 triple-word log2 and exp2 fragments (M1's, in the
# tree), the reference for fp32's ESTIMATE (the study's 2.6), and the double
# word's at fp64 beside them for scale. MEASURED from mathlib.fragment.
#
#   python tw32_ref.py

from m3core import ml, FP32, FP64, FP128, FP256, ATTRS, AN, routines

for fmt in (FP32, FP64, FP128, FP256):
    for name in ("log2", "exp2", "log1p"):
        rows = []
        for rnd in ATTRS:
            f = ml.fragment(name, fmt, rnd)
            rows.append((len(f.body), len(f.words), f.live_max()))
        ins = "/".join(str(r[0]) for r in rows)
        print(f"{fmt.name} {name:6s} instructions {ins} (rne..rmm), words "
              f"{rows[0][1]}, live {max(r[2] for r in rows)}")
