# M3 model: the fragments as programs on seq.py (scratch; the study's 3.3).
# Each fragment is SCHEDULED (Build.fragment(): the tree's schedule_order)
# and run by routines.program / routines.run, x in r0 and y in r1, on every
# pool lane at one format and every attribute; the lane's result and flag
# word are compared with the model's own (Build.run, op by op through
# softfloat.compute) and with transcend.py.
#
#   python onseq.py FMT [fn ...] [--ns N,N,...]

import sys
import time

from m3core import FORMATS, ATTRS, AN, INTARG, routines, golden
import m3harness as H
import m3pow as M


def main():
    args = sys.argv[1:]
    ns_only = None
    if "--ns" in args:
        i = args.index("--ns")
        ns_only = {int(v) for v in args[i + 1].split(",")}
        del args[i:i + 2]
    fmt = FORMATS[args[0]]
    fns = args[1:] or ("pow", "powr", "pown", "rootn", "compound")
    t0 = time.time()
    for fn in fns:
        lanes = H.pool(fmt, fn)
        if fn in INTARG and ns_only is not None:
            lanes = [ln for ln in lanes if ln[1] in ns_only]
        groups = {}
        for ln in lanes:
            key = ln[1] if fn in INTARG else None
            groups.setdefault(key, []).append(ln)
        for rnd in ATTRS:
            tot = diff = wrong = marked = progs = 0
            live = 0
            for key, lns in groups.items():
                bld = H.builder(fn, fmt, rnd, key)
                if isinstance(bld, Exception):
                    continue
                f = bld.fragment()
                live = max(live, f.live_max())
                xs = [ln[0] for ln in lns]
                ys = [ln[1] for ln in lns] if fn not in INTARG else None
                outs, words = routines.run(f, xs, ys)
                progs += 1
                for ln, o, w in zip(lns, outs, words):
                    tot += 1
                    mb, mf, _ = M.run(bld, fn, ln)
                    if (o, w) != (mb, mf):
                        diff += 1
                    if w & H.MARK:
                        marked += 1
                        continue
                    if (o, w) != golden(fmt, fn, ln, rnd):
                        wrong += 1
            print(f"{fmt.name} {fn:8s} {AN[rnd]}: {progs} programs, "
                  f"{tot} lanes on seq.py, {diff} differing from the model, "
                  f"marked {marked}, WRONG UNMARKED {wrong}, most live "
                  f"{live}", flush=True)
    print(f"{time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
