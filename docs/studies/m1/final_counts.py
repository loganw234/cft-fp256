# The final fragments, built and counted at every format and attribute
# (no lanes run): instructions, bank words, most values live, K, D.
from m1core import sf
from m1exp import build_exp
from m1log import build_log
from m1harness import FORMATS
for name in ("fp64", "fp128", "fp256"):
    fmt = FORMATS[name]
    for fn in ("exp", "exp2", "expm1", "log", "log2", "log1p"):
        ins, wds, live = [], [], []
        for rnd in sf.RND_MODES:
            f = build_exp(fmt, rnd, fn) if fn.startswith("exp") else build_log(fmt, rnd, fn)
            ins.append(len(f.body)); wds.append(len(f.words)); live.append(f.live_max())
        print(f"{name} {fn:5s} K{f.meta['K']} D{f.meta['D']}: instructions {min(ins)}-{max(ins)} {ins}, words {min(wds)}-{max(wds)}, live {min(live)}-{max(live)}")
