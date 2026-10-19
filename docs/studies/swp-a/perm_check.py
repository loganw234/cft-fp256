# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""perm_check.py - an independent Python implementation of perm_check.c's keyed Feistel
permutation, held to the C program's printed vectors.

The construction (see perm_check.c): a balanced Feistel network on 2w bits,
    (L, R) -> (R, L xor F(R, k_j)),   F(x, k) = finalizer(x xor k) truncated to w bits,
the 32-bit finalizer for w <= 32, the 64-bit one above; round keys k_j = the j-th output of
splitmix64 seeded with the key. Cycle walking (Black and Rogaway, CT-RSA 2002) maps it onto
[0, N) for any N not above the domain.

Two implementations written separately (C and Python) that print and reproduce the same
vectors cannot share a slip in the round function, the key schedule, the truncation or the
walk; the checks here are the vectors of perm_check.c's section V, and a few of the
properties (the inverse, small-width exhaustion) on this side too.

usage: python perm_check.py perm_check.c.out
"""
import re
import sys

M64 = (1 << 64) - 1
M32 = (1 << 32) - 1
fails = 0


def check(label, ok, detail=""):
    global fails
    print("CHECK %-84s %s %s" % (label, "ok" if ok else "FAILED", detail))
    if not ok:
        fails += 1


def fmix32(h):
    h ^= h >> 16
    h = (h * 0x85EBCA6B) & M32
    h ^= h >> 13
    h = (h * 0xC2B2AE35) & M32
    h ^= h >> 16
    return h


def fmix64(h):
    h ^= h >> 33
    h = (h * 0xFF51AFD7ED558CCD) & M64
    h ^= h >> 33
    h = (h * 0xC4CEB9FE1A85EC53) & M64
    h ^= h >> 33
    return h


def splitmix64_stream(seed, n):
    s, out = seed & M64, []
    for _ in range(n):
        s = (s + 0x9E3779B97F4A7C15) & M64
        z = s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & M64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & M64
        out.append(z ^ (z >> 31))
    return out


class Feistel:
    def __init__(self, w, rounds, key):
        self.w, self.rounds = w, rounds
        self.mask = (1 << w) - 1
        self.k = splitmix64_stream(key, rounds)

    def F(self, x, j):
        if self.w <= 32:
            return fmix32((x ^ self.k[j]) & M32) & self.mask
        return fmix64((x ^ self.k[j]) & M64) & self.mask

    def perm(self, i):
        L, R = (i >> self.w) & self.mask, i & self.mask
        for j in range(self.rounds):
            L, R = R, L ^ self.F(R, j)
        return (L << self.w) | R

    def inv(self, y):
        L, R = (y >> self.w) & self.mask, y & self.mask
        for j in range(self.rounds - 1, -1, -1):
            R, L = L, R ^ self.F(L, j)
        return (L << self.w) | R

    def walk(self, N, i):
        x = i
        while True:
            x = self.perm(x)
            if x < N:
                return x


def parse(path):
    vec = {"VEC64": [], "VEC46": [], "VEC128": [], "VECCW": []}
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            m = re.match(r"^(VEC64|VEC46|VEC128|VECCW) (.*)$", ln.strip())
            if m:
                kv = dict(p.split("=") for p in m.group(2).split())
                vec[m.group(1)].append(kv)
    return vec


def main(path):
    try:
        sys.stdout.reconfigure(newline="\n")
    except (AttributeError, ValueError):
        pass
    vec = parse(path)
    print("perm_check.py: Python reference against the vectors of perm_check.c (%s)" % "section V")
    print()
    check("the C program printed 32 vectors of each of the four kinds", all(len(v) == 32 for v in vec.values()),
          str({k: len(v) for k, v in vec.items()}))
    bad = 0
    for kv in vec["VEC64"]:
        f = Feistel(32, 6, int(kv["key"], 16))
        if f.perm(int(kv["i"], 16)) != int(kv["out"], 16):
            bad += 1
    check("64-bit domain, 6 rounds: Python reproduces every C output", bad == 0 and len(vec["VEC64"]) == 32, "(%d differ)" % bad)
    bad = 0
    for kv in vec["VEC46"]:
        f = Feistel(23, 5, int(kv["key"], 16))
        if f.perm(int(kv["i"], 16)) != int(kv["out"], 16):
            bad += 1
    check("46-bit domain (the significand pairs of fp32 division), 5 rounds: Python reproduces every C output",
          bad == 0 and len(vec["VEC46"]) == 32, "(%d differ)" % bad)
    bad = 0
    for kv in vec["VEC128"]:
        f = Feistel(64, 6, int(kv["key"], 16))
        i = int(kv["i"], 16)
        want = int(kv["out"], 16)
        got = f.perm(i)
        if got != want:
            bad += 1
    check("128-bit domain, 6 rounds: Python reproduces every C output", bad == 0 and len(vec["VEC128"]) == 32, "(%d differ)" % bad)
    bad = 0
    for kv in vec["VECCW"]:
        f = Feistel(23, 5, int(kv["key"], 16))
        N = int(kv["n"])
        if f.walk(N, int(kv["i"])) != int(kv["out"]):
            bad += 1
    check("cycle walking onto N = 5 x 10^13 inside the 46-bit domain: Python reproduces every C output",
          bad == 0 and len(vec["VECCW"]) == 32, "(%d differ)" % bad)
    # a perturbed key schedule must NOT reproduce the vectors (the comparison can fail)
    bad = 0
    for kv in vec["VEC64"]:
        f = Feistel(32, 6, int(kv["key"], 16) ^ 1)
        if f.perm(int(kv["i"], 16)) != int(kv["out"], 16):
            bad += 1
    check("CONTROL: with the key changed by one bit Python does NOT reproduce the C outputs", bad == len(vec["VEC64"]), "(%d of 32 differ)" % bad)
    bad = 0
    for kv in vec["VEC64"]:
        f = Feistel(32, 5, int(kv["key"], 16))
        if f.perm(int(kv["i"], 16)) != int(kv["out"], 16):
            bad += 1
    check("CONTROL: with five rounds instead of six Python does NOT reproduce the C outputs", bad == len(vec["VEC64"]), "(%d of 32 differ)" % bad)
    # the properties on this side
    f = Feistel(32, 6, 0xDEADBEEF)
    import random
    rnd = random.Random(1)
    ok = all(f.inv(f.perm(x)) == x for x in (rnd.getrandbits(64) for _ in range(20000)))
    check("Python: inverse(perm(x)) == x on 20,000 random 64-bit inputs", ok)
    f = Feistel(64, 6, 0xDEADBEEF)
    ok = all(f.inv(f.perm(x)) == x for x in (rnd.getrandbits(128) for _ in range(20000)))
    check("Python: inverse(perm(x)) == x on 20,000 random 128-bit inputs", ok)
    f = Feistel(6, 6, 5)       # a 12-bit domain: exhaustive
    check("Python: w = 6 (a 4,096-element domain) is a bijection by exhaustion", sorted(f.perm(i) for i in range(1 << 12)) == list(range(1 << 12)))
    N = 1000
    f = Feistel(6, 6, 5)
    check("Python: cycle walking onto N = 1,000 inside 4,096 is a bijection of [0, 1,000) by exhaustion",
          sorted(f.walk(N, i) for i in range(N)) == list(range(N)))
    print()
    print("perm_check.py: %s" % ("every CHECK held" if fails == 0 else "%d CHECK(s) FAILED" % fails))
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
