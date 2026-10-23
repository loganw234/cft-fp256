# M4 model: fp64's fragments at G = 46 against G = 44 (scratch; the study's
# question 4): the plan (head steps K, tail degree D), the instruction
# count, and which words differ.
#
#   python gcheck.py

from m4core import FORMATS, RNE
from m4inv import build, FNS


def main():
    fmt = FORMATS["fp64"]
    for fn in FNS:
        a, b = build(fmt, RNE, fn), build(fmt, RNE, fn, G=46)
        diff = sorted(k for k in set(a.words) | set(b.words)
                      if a.words.get(k) != b.words.get(k))
        same_body = [op for op, *_ in a.body] == [op for op, *_ in b.body]
        print(f"fp64 {fn}: G 44 K {a.meta['K']} D {a.meta['D']} "
              f"{len(a.body)} instructions; G 46 K {b.meta['K']} D "
              f"{b.meta['D']} {len(b.body)} instructions; the same opcodes "
              f"in order: {same_body}; words that differ: {diff}", flush=True)


if __name__ == "__main__":
    main()
