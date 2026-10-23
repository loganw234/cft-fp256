# M4 model: one fingerprint of every default fragment (scratch; the study's
# 11): the 80 double-word fragments (four functions, five attributes, fp32's
# double word, fp64, fp128, fp256) and the 20 of fp32's triple word, each
# body, result, flag word and words, hashed in order. A change to the
# model that moves no fragment leaves it unchanged.
#
#   python fingerprint.py

import hashlib

from m4core import FORMATS, ATTRS
from m4inv import build, FNS
import m4tw


def digest(f):
    h = hashlib.sha256()
    h.update(repr((f.body, f.result, f.flags, sorted(f.words.items()))).encode())
    return h.hexdigest()


def main():
    all_ = hashlib.sha256()
    n = 0
    for name in ("fp32", "fp64", "fp128", "fp256"):
        for fn in FNS:
            for rnd in ATTRS:
                all_.update(digest(build(FORMATS[name], rnd, fn)).encode())
                n += 1
    dw = all_.hexdigest()
    for fn in FNS:
        for rnd in ATTRS:
            all_.update(digest(m4tw.build(FORMATS["fp32"], rnd, fn)).encode())
            n += 1
    print(f"{n} default fragments: double word {dw[:16]}..., with the triple "
          f"word {all_.hexdigest()[:16]}...")


if __name__ == "__main__":
    main()
