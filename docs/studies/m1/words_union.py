# The bank words: per function, per family, all six, and with C4's div
# and sqrt, under each attribute (the first run took rne and rtz only).
from m1core import sf
from m1exp import build_exp
from m1log import build_log
from m1harness import FORMATS
from cft_golden import routines as R
for name in ("fp64", "fp128", "fp256"):
    fmt = FORMATS[name]
    for rnd in sf.RND_MODES:
        allw, per = set(), {}
        for fn in ("exp", "exp2", "expm1", "log", "log2", "log1p"):
            f = build_exp(fmt, rnd, fn) if fn.startswith("exp") else build_log(fmt, rnd, fn)
            per[fn] = len(set(f.words.values()))
            allw |= set(f.words.values())
        expfam = set(); logfam = set()
        for fn in ("exp", "exp2", "expm1"):
            expfam |= set(build_exp(fmt, rnd, fn).words.values())
        for fn in ("log", "log2", "log1p"):
            logfam |= set(build_log(fmt, rnd, fn).words.values())
        c4 = set(R.fragment("div", fmt, rnd).words.values()) | set(R.fragment("sqrt", fmt, rnd).words.values())
        print(f"{name} {sf.RND_NAMES[rnd]}: per function {per}; exp family {len(expfam)}, log family {len(logfam)}, all six {len(allw)}; with C4's div and sqrt {len(allw | c4)} (C4's alone {len(c4)})")
