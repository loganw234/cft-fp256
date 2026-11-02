"""The first eighteen members of the oracle's pools, before and after.

build_trigpool and build_p3pool take their first eighteen entries from the
array main hands them.  Until 2026-11-02 that array held fp256's eighteen
specials for every format; this prints the head of each pool at each
format, from two case dumps, so that the change (and the pools that did not
change) can be read.  Pools: x exponential, t trigonometric, h third.

Usage, from the repository's root:

    python -B host/tools/audit-pools/first18.py BEFORE AFTER

BEFORE is the dump of the pools as they were: the dump of the tool at commit
b2fd894f with its extras lines removed (grep -v '^C [^ ]* [^ ]* e '), AFTER
the dump of the tool now (CFT_MPFR_DUMP_CASES=1 ./mpfr-check 24 7, run in
host/).  Operands wider than 18 hex digits are shortened to their ends.
"""
import sys


def load(path):
    pools = {}      # (format, pool) -> {index: set of operands}
    funcs = {}
    with open(path, errors="replace") as fh:
        for line in fh:
            p = line.split()
            # C <format> <function> <pool> <i> <j> <d> <a> <b> <n> [<family>]
            if len(p) < 9 or p[0] != "C" or p[3] == "e":
                continue
            fmt, fn, pool, idx = p[1], p[2], p[3], int(p[4])
            if idx < 18 and p[7] != "-":
                pools.setdefault((fmt, pool), {}).setdefault(idx, set()).add(p[7])
                funcs.setdefault((fmt, pool), set()).add(fn)
    return pools, funcs


def short(x):
    return x if len(x) <= 18 else x[:8] + ".." + x[-4:]


def row(d):
    out = []
    for i in range(18):
        s = d.get(i, set())
        out.append("/".join(sorted(s)) if len(s) != 1 else next(iter(s)))
    return out


def main(argv):
    if len(argv) != 3:
        sys.stderr.write(__doc__)
        return 2
    before, _ = load(argv[1])
    after, funcs = load(argv[2])
    for fmt in ("fp32", "fp64", "fp128", "fp256"):
        for pool in ("t", "h", "x"):
            key = (fmt, pool)
            if key not in after:
                continue
            rb, ra = row(before.get(key, {})), row(after[key])
            print("%s pool %s (%d functions)" % (fmt, pool, len(funcs[key])))
            print("  before:", " ".join(short(x) for x in rb))
            print("  after: ", " ".join(short(x) for x in ra))
            print("  changed:", rb != ra)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
