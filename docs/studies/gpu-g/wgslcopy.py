#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""GPU-G's copy tool: GPU-D's OpenCL C text (oclcopy.py's derivation, imported and
called, never forked) with a fixed, listed and counted set of exact replacements that
take every 64-bit and every 8-bit integer out of the code the kernel can reach, so that
clspv emits SPIR-V without Int64 or Int8 and Tint turns it into WGSL.

    python3 wgslcopy.py DEVSRC OUT.cl                 # write, then check; prints counts, sha256
    python3 wgslcopy.py DEVSRC OUT.cl --check         # check an existing text, write nothing
    python3 wgslcopy.py DEVSRC - --selftest           # the plants: each must be refused
    python3 wgslcopy.py DEVSRC OUT.c --seedcheck [--plant]   # C for gcc: the rsqrt seed, both ways

DEVSRC is a directory GPU-A's devcopy.py wrote. Each edit is one exact replacement on
oclcopy's text with the number of matches it must find; a count that differs refuses the
text and names the edit, so a change in host/src, in GPU-A's lane or in oclcopy.py that
touches an edited line stops the build here. The kinds:

  W1  a 64-bit product in 32 bits: cft_g_mul (a 32x32 product as (hi, lo) by 16-bit
      halves), cft_bn_mul's schoolbook step through it, IMUL's low half as a u32 product.
  W2  add's carry and sub's borrow found by comparison.
  W3  cft_bn_extract's 64-bit funnel as two 32-bit shifts (guarded at off = 0).
  W4  `1uL << 28` as `1u << 28` (OpenCL C's int is 32 bits).
  W5  seed_rsqrt_entry in 32-bit pieces: 2^44 / m2 by long division in 16-bit steps,
      the squares through cft_g_mul. --seedcheck holds it to the 64-bit original.
  W6  the kernel's `long n` as uint2 (8 bytes, as GPU-D's harness binds a cl_long),
      with the bound n < 2^27 (every index then fits in 32 bits), and `long i` as uint.
  W7  the work-group size, fix (B): reqd_work_group_size(64, 1, 1), so clspv emits
      LocalSize in place of its spec-constant WorkgroupSize, which Tint fails on.
  W8  cft_fmt_desc's `name` pointer out (it and the table's four strings): clspv stopped
      at the struct copy that holds it ("Invalid bitcast" of the pointer to i32).
  W9  the shim's int64_t and uint64_t left undefined: a 64-bit use left anywhere in the
      compiled text then fails to compile, on PoCL and in clspv.
  W10 the bytes as 32-bit words, no 8-bit integer: the kernel's six buffers as uint (a
      lane's rnd and flags byte in word i/4, flags written by atomic AND and OR on that
      byte alone), the lane on words, cft_g_load and cft_g_store (cft_bn_load and
      cft_bn_store on words). Tint refuses the Int8 capability.
  W11 reduce_leaf between #if 0 and #endif: its one caller is cft_sf_reduce, which O4
      took out, and clspv at --int8=false refuses its void pointers. Checked as O4 is:
      its name appears nowhere in the code outside the excluded lines.

At every build the code the kernel can reach (a call graph from cft_fma_ocl, every call
counted whatever the opcode) is scanned: no long, ulong, int64_t, uint64_t, char, uchar,
int8_t, uint8_t, size_t or L-suffixed literal in those functions or the structs they
name; no #define but CFT_EXP_SPAN's carries such a literal, and CFT_EXP_SPAN is read by
#if alone. oclcopy's checks run on the result too: O4's no_caller and no_recursion.
"""
import argparse
import hashlib
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "gpu-d"))
import oclcopy  # noqa: E402  GPU-D's tool: its derivation, inputs and checks

KERNEL_NAME = "cft_fma_ocl"
CALLER_RSQRT = (b"    odd = E & 1;\n    r = seed_rsqrt_entry(((uint32_t)odd << 9) |\n"
                b"                         cft_bn_extract(x, f->man_w - 9, 9));\n")

G_MUL = b"""/* W1: a 32x32-bit product as (hi, lo), by 16-bit halves: no 64-bit integer */
CFT_HD static void cft_g_mul(uint32_t a, uint32_t b, uint32_t *hi, uint32_t *lo)
{
    uint32_t p00 = (a & 0xffffu) * (b & 0xffffu), p01 = (a & 0xffffu) * (b >> 16);
    uint32_t p10 = (a >> 16) * (b & 0xffffu), p11 = (a >> 16) * (b >> 16);
    uint32_t mid = (p00 >> 16) + (p01 & 0xffffu) + (p10 & 0xffffu);
    *lo = (mid << 16) | (p00 & 0xffffu);
    *hi = p11 + (p01 >> 16) + (p10 >> 16) + (mid >> 16);
}

"""

G_WORDS = b"""
/* W10: cft_bn_load and cft_bn_store on 32-bit words, no 8-bit integer. For a
 * little-endian byte string of 4*nwords bytes they read and write the same bits:
 * its words are the limbs. */
CFT_HD static void cft_g_load(cft_bn *r, const uint32_t *w, int nwords)
{
    int i;
    for (i = 0; i < nwords; i++)
        r->v[i] = w[i];
    r->n = nwords;
    bn_norm(r);
}

CFT_HD static void cft_g_store(const cft_bn *a, uint32_t *w, int nwords)
{
    int i;
    for (i = 0; i < nwords; i++)
        w[i] = (i < a->n) ? a->v[i] : 0u;
}
"""

SEED_OLD = b"""    uint32_t odd = j >> 9, i = j & 511u;
    uint64_t m2 = (uint64_t)(((1u << 10) + (i << 1) + 1u)) << odd;
    uint64_t target = 1ull << 44;
    uint64_t t = target / m2;
    uint64_t q = 0, bit;
    /* floor(sqrt(t)); t < 2^34, so 18 candidate bits cover it */
    for (bit = 1ull << 17; bit; bit >>= 1) {
        uint64_t c = q | bit;
        if (c * c <= t)
            q = c;
    }
    while ((q + 1) * (q + 1) * m2 <= target)
        q++;
    /* round up when (q + 1/2)^2 * m2 < 2^44 */
    if ((2 * q + 1) * (2 * q + 1) * m2 < (1ull << 46))
        q++;
    return (uint32_t)q;
}
"""

SEED_NEW = b"""    /* W5: the 64-bit original in 32-bit pieces. A value below 2^64 is (vh, vl);
     * products by cft_g_mul; 2^44 / m2 by long division in 16-bit steps. */
    uint32_t odd = j >> 9, i = j & 511u;
    uint32_t m2 = ((1u << 10) + (i << 1) + 1u) << odd;          /* < 2^12 */
    uint32_t th, tl, r, x, q = 0, bit, ph, pl, s;
    th = (1u << 12) / m2;                       /* t = floor(2^44 / m2) = (th, tl) */
    r = (1u << 12) % m2;
    x = r << 16;
    tl = (x / m2) << 16;
    r = x % m2;
    x = r << 16;
    tl |= x / m2;
    /* floor(sqrt(t)); t < 2^34, so 18 candidate bits cover it */
    for (bit = 1u << 17; bit; bit >>= 1) {
        uint32_t c = q | bit;
        cft_g_mul(c, c, &ph, &pl);                               /* c*c < 2^36 */
        if (ph < th || (ph == th && pl <= tl))
            q = c;
    }
    for (;;) {                                  /* while ((q + 1)^2 * m2 <= 2^44) q++ */
        s = q + 1u;
        cft_g_mul(s, s, &ph, &pl);
        cft_g_mul(pl, m2, &x, &pl);
        ph = ph * m2 + x;
        if (!(ph < (1u << 12) || (ph == (1u << 12) && pl == 0u)))
            break;
        q++;
    }
    /* round up when (q + 1/2)^2 * m2 < 2^44: (2q + 1)^2 * m2 < 2^46 */
    s = 2u * q + 1u;
    cft_g_mul(s, s, &ph, &pl);
    cft_g_mul(pl, m2, &x, &pl);
    ph = ph * m2 + x;
    if (ph < (1u << 14))
        q++;
    return q;
}
"""

EDITS = (  # (kind, old, new, matches it must find), applied in order to oclcopy's text
    ("W9", b"typedef long  int64_t; typedef ulong  uint64_t;\n",
     b"/* W9: no int64_t and no uint64_t: a 64-bit use left in the text fails to compile */\n", 1),
    ("W8", b"    __constant const char *name;\n",
     b"    /* W8: the name pointer out: clspv cannot copy a struct that holds it */\n", 1),
    ("W8", b"""    /* name    exp_w man_w width prec  bias    emax     emin    exp_mask */
    { "fp32",      8,   23,   32,  24,    127,    127,    -126,      255u },
    { "fp64",     11,   52,   64,  53,   1023,   1023,   -1022,     2047u },
    { "fp128",    15,  112,  128, 113,  16383,  16383,  -16382,    32767u },
    { "fp256",    19,  236,  256, 237, 262143, 262143, -262142,   524287u }
""", b"""    /* W8: exp_w man_w width prec  bias    emax     emin    exp_mask (names out) */
    {      8,   23,   32,  24,    127,    127,    -126,      255u },
    {     11,   52,   64,  53,   1023,   1023,   -1022,     2047u },
    {     15,  112,  128, 113,  16383,  16383,  -16382,    32767u },
    {     19,  236,  256, 237, 262143, 262143, -262142,   524287u }
""", 1),
    ("W3", b"    uint64_t acc;\n", b"    uint32_t acc;\n", 1),
    ("W3", b"    acc = ((uint64_t)l1 << 32) | (uint64_t)l0;\n    acc >>= off;\n",
     b"    acc = off ? (l0 >> off) | (l1 << (32 - off)) : l0;   /* W3: the funnel in 32 bits */\n", 1),
    ("W2", b"""    uint64_t carry = 0;
    for (i = 0; i < n; i++) {
        uint64_t s = carry;
        if (i < a->n) s += a->v[i];
        if (i < b->n) s += b->v[i];
        r->v[i] = (uint32_t)s;
        carry = s >> 32;
    }
""", b"""    uint32_t carry = 0;
    for (i = 0; i < n; i++) {
        uint32_t s = carry, c = 0;               /* W2: the carry by comparison */
        if (i < a->n) { s += a->v[i]; c = s < a->v[i]; }
        if (i < b->n) { s += b->v[i]; c |= s < b->v[i]; }
        r->v[i] = s;
        carry = c;
    }
""", 1),
    ("W2", b"""    uint64_t borrow = 0;
    for (i = 0; i < n; i++) {
        uint64_t x = a->v[i];
        uint64_t y = (i < b->n ? b->v[i] : 0u) + borrow;
        borrow = (x < y) ? 1u : 0u;
        r->v[i] = (uint32_t)(x - y + (borrow ? ((uint64_t)1 << 32) : 0));
    }
""", b"""    uint32_t borrow = 0;
    for (i = 0; i < n; i++) {
        uint32_t x = a->v[i];
        uint32_t y = i < b->n ? b->v[i] : 0u;
        uint32_t d = x - y - borrow;             /* W2: the borrow by comparison */
        borrow = (x < y || (x == y && borrow)) ? 1u : 0u;
        r->v[i] = d;
    }
""", 1),
    ("W1", b"CFT_HD int cft_bn_mul(cft_bn *r, const cft_bn *a, const cft_bn *b)\n{\n",
     G_MUL + b"CFT_HD int cft_bn_mul(cft_bn *r, const cft_bn *a, const cft_bn *b)\n{\n", 1),
    ("W1", b"""        uint64_t carry = 0, ai = a->v[i];
        for (j = 0; j < b->n; j++) {
            uint64_t cur = (uint64_t)t.v[i + j] + ai * (uint64_t)b->v[j] + carry;
            t.v[i + j] = (uint32_t)cur;
            carry = cur >> 32;
        }
""", b"""        uint32_t carry = 0, ai = a->v[i];
        for (j = 0; j < b->n; j++) {
            uint32_t hi, lo, tv = t.v[i + j];    /* W1: t + ai*bj + carry < 2^64 as (hi, lo) */
            cft_g_mul(ai, b->v[j], &hi, &lo);
            lo += tv;
            hi += lo < tv;
            lo += carry;
            hi += lo < carry;
            t.v[i + j] = lo;
            carry = hi;
        }
""", 1),
    ("W10", b"        le[i] = (uint8_t)(w >> (8 * (i & 3)));\n    }\n}\n",
     b"        le[i] = (uint8_t)(w >> (8 * (i & 3)));\n    }\n}\n" + G_WORDS, 1),
    ("W1", b"        cft_bn_set_u32(out, (uint32_t)((uint64_t)pa * (uint64_t)pb));\n",
     b"        cft_bn_set_u32(out, pa * pb);   /* W1: the low half, a 32-bit product */\n", 1),
    ("W4", b"    uint32_t num = 1uL << 28;", b"    uint32_t num = 1u << 28;  /* W4: 1u */", 1),
    ("W5", SEED_OLD, SEED_NEW, 1),
    ("W11", b"CFT_HD static int reduce_leaf(const cft_fmt_desc *f, int op, int rnd,\n",
     b"#if 0 /* W11: reduce_leaf, whose one caller O4 took out */\n"
     b"CFT_HD static int reduce_leaf(const cft_fmt_desc *f, int op, int rnd,\n", 1),
    ("W11", b"    *flags = 0;\n    return 0;\n}\n#if 0 /* O4:",
     b"    *flags = 0;\n    return 0;\n}\n#endif /* W11 */\n#if 0 /* O4:", 1),
    ("W10", b"""                                 const uint8_t *pa, const uint8_t *pb,
                                 const uint8_t *pc, int rnd,
                                 uint8_t *pd, uint8_t *pflags)
""", b"""                                 const uint32_t *pa, const uint32_t *pb,
                                 const uint32_t *pc, int rnd,
                                 uint32_t *pd, uint32_t *pflags)   /* W10: words */
""", 1),
    ("W10", b"""    cft_bn_load(&ba, pa, esz);
    cft_bn_load(&bb, pb, esz);
    cft_bn_load(&bc, pc, esz);
""", b"""    cft_g_load(&ba, pa, esz / 4);          /* W10: words */
    cft_g_load(&bb, pb, esz / 4);
    cft_g_load(&bc, pc, esz / 4);
""", 1),
    ("W10", b"        for (k = 0; k < esz; k++)\n            pd[k] = 0;\n",
     b"        for (k = 0; k < esz / 4; k++)     /* W10: words */\n            pd[k] = 0;\n", 1),
    ("W10", b"    cft_bn_store(&bo, pd, esz);\n    *pflags = (uint8_t)fl;\n",
     b"    cft_g_store(&bo, pd, esz / 4);         /* W10: words */\n    *pflags = fl & 0xffu;\n", 1),
    ("W7", b"__kernel void cft_fma_ocl(",
     b"__kernel __attribute__((reqd_work_group_size(64, 1, 1)))  /* W7: LocalSize 64 */\n"
     b"void cft_fma_ocl(", 1),
    ("W6", b"int esz, long n,",
     b"int esz, uint2 n, /* W6: n in two 32-bit words, 8 bytes as the harness's cl_long */", 1),
    ("W10", b"""                          __global const uchar *a, __global const uchar *b,
                          __global const uchar *c, __global const uchar *rnd,
                          __global uchar *d, __global uchar *flags)
""", b"""                          __global const uint *a, __global const uint *b,
                          __global const uint *c, __global const uint *rnd,
                          __global uint *d, volatile __global uint *flags)  /* W10: words */
""", 1),
    ("W6", b"    const long i = (long)get_global_id(0);", b"    const uint i = (uint)get_global_id(0);", 1),
    ("W10", b"    uint8_t pa[32], pb[32], pc[32], pd[32], fl = 0;\n    int k;\n",
     b"    uint32_t pa[8], pb[8], pc[8], pd[8], fl = 0;      /* W10: words */\n    uint k, w, s;\n", 1),
    ("W6", b"    if (i >= n || fmt < 0",
     b"    if (n.y != 0u || n.x > (1u << 27) || i >= n.x || fmt < 0", 1),
    ("W10", b"""    for (k = 0; k < esz; k++) {
        pa[k] = a[i * esz + k];
        pb[k] = b[i * esz + k];
        pc[k] = c[i * esz + k];
    }
    gpua_fma_lane(&f, esz, pa, pb, pc, rnd[i], pd, &fl);
    for (k = 0; k < esz; k++)
        d[i * esz + k] = pd[k];
    flags[i] = fl;
""", b"""    w = (uint)esz / 4u;                    /* W10: an operand is w 32-bit words */
    s = 8u * (i & 3u);                     /* W10: lane i's byte in rnd's and flags' word i/4 */
    for (k = 0; k < w; k++) {
        pa[k] = a[i * w + k];
        pb[k] = b[i * w + k];
        pc[k] = c[i * w + k];
    }
    gpua_fma_lane(&f, esz, pa, pb, pc, (int)((rnd[i >> 2] >> s) & 0xffu), pd, &fl);
    for (k = 0; k < w; k++)
        d[i * w + k] = pd[k];
    atomic_and(&flags[i >> 2], ~(0xffu << s));   /* W10: lane i's byte alone, */
    atomic_or(&flags[i >> 2], fl << s);          /* its neighbours' untouched */
""", 1),
)

FORBIDDEN = re.compile(r"\b(long|ulong|u?int64_t|u?int8_t|u?char|size_t)\b"
                       r"|\b(?:0[xX][0-9a-fA-F]+|\d+)(?:[uU]?[lL]{1,2}|[lL]{1,2}[uU])\b")


def apply_edits(text, edits):
    """Each edit in order, refused by name when its count differs. Returns (text, counts)."""
    counts = {}
    for kind, old, new, want in edits:
        got = text.count(old)
        if got != want:
            raise ValueError(f"edit {kind}: {old[:70].decode()!r} found {got} times, not {want}")
        text = text.replace(old, new)
        counts[kind] = counts.get(kind, 0) + want
    return text, counts


def code_view(text):
    """oclcopy's code_only (O4's lines out, comments and strings blanked), W11's lines out first."""
    if b"#if 0 /* W11" in text:
        lo, hi = text.index(b"#if 0 /* W11"), text.index(b"#endif /* W11 */")
        text = text[:lo] + text[hi:]
    return oclcopy.code_only(text)


def functions(code):
    """{name: (signature and body)} for every definition: a name, a parameter list, a brace."""
    defs = {}
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\([^;{}()]*\)\s*\{", code):
        if m.group(1) in oclcopy.KEYWORDS:
            continue
        depth = 0
        for j in range(m.end() - 1, len(code)):
            depth += {"{": 1, "}": -1}.get(code[j], 0)
            if depth == 0:
                break
        defs[m.group(1)] = code[m.start():j + 1]
    return defs


def scan(code):
    """The reachable code holds no 64-bit or 8-bit integer. Returns (functions, reachable)."""
    defs = functions(code)
    if KERNEL_NAME not in defs:
        raise ValueError(f"scan: no definition of {KERNEL_NAME}")
    seen, todo = set(), [KERNEL_NAME]
    while todo:
        f = todo.pop()
        if f not in seen:
            seen.add(f)
            todo += [c for c in re.findall(r"\b([A-Za-z_]\w*)\s*\(", defs[f]) if c in defs]
    structs = {m.group(2): m.group(1) for m in
               re.finditer(r"typedef struct\s*\{([^}]*)\}\s*(\w+)\s*;", code)}
    parts = {f"function {f}": defs[f] for f in sorted(seen)}
    used = " ".join(parts.values())
    parts.update({f"struct {s}": body for s, body in structs.items() if re.search(rf"\b{s}\b", used)})
    for what, body in parts.items():
        m = FORBIDDEN.search(body)
        if m:
            raise ValueError(f"scan: {what} holds {m.group(0)!r}, a 64-bit or 8-bit integer")
    for line in code.splitlines():
        s = line.strip()
        if s.startswith("#define") and FORBIDDEN.search(s) and not re.fullmatch(
                r"#define CFT_EXP_SPAN \d+L", s):
            raise ValueError(f"scan: a #define holds a 64-bit or 8-bit integer: {s!r}")
        if re.search(r"\bCFT_EXP_SPAN\b", s) and not (s.startswith("#if") or s.startswith("#define")):
            raise ValueError(f"scan: CFT_EXP_SPAN (an L literal) read outside #if: {s!r}")
    return len(defs), len(seen)


def no_caller_w11(code):
    n = len(re.findall(r"\breduce_leaf\b", code))
    if n:
        raise ValueError(f"W11: reduce_leaf appears {n} times in the code outside the excluded lines")


def derive(files, hip, kernel, edits=EDITS):
    """The whole text and both tools' counts. Deterministic: no date, no path."""
    base, ocounts = oclcopy.derive(files, hip, kernel)
    text, counts = apply_edits(base, edits)
    head = (b"/* GENERATED by docs/studies/gpu-g/wgslcopy.py - do not edit. oclcopy.py's text "
            b"(sha256 %s)\n * with GPU-G's edits %s: no 64-bit and no 8-bit integer where the "
            b"kernel reaches. */\n" % (hashlib.sha256(base).hexdigest()[:16].encode(),
                                       b", ".join(b"%s %d" % (k.encode(), n)
                                                  for k, n in sorted(counts.items()))))
    text = head + text
    code = code_view(text)
    oclcopy.no_caller(code)
    no_caller_w11(code)
    oclcopy.no_recursion(code)
    scan(code)
    if b"#include <" in text or b'#include "' in text:
        raise ValueError("an #include survived the edits")
    return text, ocounts, counts


def function_text(text, signature):
    """One function's text, from its signature line to the first column-0 brace after it."""
    if text.count(signature) != 1:
        raise ValueError(f"{signature.decode()!r} found {text.count(signature)} times, not once")
    start = text.index(signature)
    return text[start:text.index(b"\n}\n", start) + 3]


def seedcheck(files, hip, kernel, plant):
    """C for gcc: seed_rsqrt_entry as host/src has it and as W5 has it, over all 1,024
    inputs its one caller can pass: (odd << 9) | a 9-bit field, odd = E & 1."""
    base, _ = oclcopy.derive(files, hip, kernel)
    text, _, _ = derive(files, hip, kernel)
    if text.count(CALLER_RSQRT) != 1:
        raise ValueError("seedcheck: the one caller's argument is no longer (odd << 9) | 9 bits")
    sig = b"CFT_HD static uint32_t seed_rsqrt_entry(uint32_t j)\n"
    old = function_text(base, sig).replace(b"seed_rsqrt_entry", b"seed_orig")
    new = function_text(text, sig).replace(b"seed_rsqrt_entry", b"seed_w5")
    if plant:
        new, _ = apply_edits(new, [("plant", b"    return q;\n}\n",
                                    b"    if (j == 300u)\n        q ^= 1u;    /* the plant: one "
                                    b"wrong entry */\n    return q;\n}\n", 1)])
    mul = function_text(text, b"CFT_HD static void cft_g_mul(")
    return b"".join([
        b"/* GENERATED by docs/studies/gpu-g/wgslcopy.py --seedcheck%s: seed_rsqrt_entry as\n"
        % (b" --plant" if plant else b""),
        b" * host/src has it (64-bit) and as W5 rewrites it (32-bit), on every input its one\n"
        b" * caller passes: j = (odd << 9) | m, odd = E & 1 in {0, 1}, m 9 bits: 1,024. */\n",
        b"#include <stdint.h>\n#include <stdio.h>\n#define CFT_HD\n\n", old, b"\n", mul, b"\n", new,
        b"""
int main(void)
{
    uint32_t j, n = 0, bad = 0;
    for (j = 0; j < 1024u; j++, n++) {
        uint32_t x = seed_orig(j), y = seed_w5(j);
        if (x != y && bad++ < 5)
            printf("seedcheck: j %u: 64-bit %u, 32-bit %u\\n", j, x, y);
    }
    printf("seedcheck: %u inputs, %u differ: %s\\n", n, bad, bad ? "REFUSED" : "OK");
    return bad != 0;
}
"""])


def selftest(files, hip, kernel):
    """A fault of each kind the counts and scans exist for; each must be refused by name."""
    good, _, _ = derive(files, hip, kernel)
    bc, sf = files["src/bigint.c"], files["src/softfloat.c"]
    doctored = tuple((k, o, n, 2 if o.startswith(b"        uint64_t carry = 0, ai") else c)
                     for k, o, n, c in EDITS)
    shim = oclcopy.SHIM
    plants = {
        "a doctored count: W1's schoolbook step said to match twice": ("edits", doctored),
        "host/src's schoolbook step changed (W1 finds 0)": ("files", dict(files, **{
            "src/bigint.c": bc.replace(b"ai * (uint64_t)b->v[j]", b"(uint64_t)b->v[j] * ai", 1)})),
        "a second `1uL << 28` in host/src (W4 finds 2)": ("files", dict(files, **{
            "src/softfloat.c": sf.replace(b"    uint32_t num = 1uL << 28;",
                                          b"    uint32_t num = 1uL << 28;\n    uint32_t num = 1uL << 28;", 1)})),
        "oclcopy.py's shim changed (W9 finds 0: a change there reaches this tool)":
            ("shim", shim.replace(b"typedef long  int64_t;", b"typedef long int64_t;")),
        "a ulong in the kernel (the scan)": ("text", good.replace(
            b"    uint k, w, s;\n", b"    uint k, w, s;\n    ulong z = 0;\n", 1)),
        "a uchar in the lane (the scan)": ("text", good.replace(
            b"    uint32_t fl = 0;\n    int k;\n", b"    uint32_t fl = 0;\n    uchar z = 0;\n    int k;\n", 1)),
        "`1uL << 28` back in seed_recip_entry, which cft_sf_compute reaches (the scan)":
            ("text", good.replace(b"1u << 28;  /* W4", b"1uL << 28;  /* W4", 1)),
        "a #define with a 64-bit literal (the scan)":
            ("text", good.replace(b"#define CFT_HD\n", b"#define CFT_HD\n#define CFT_G_BIG 1uL\n", 1)),
        "a caller of the excluded reduce_leaf in the kernel (W11's check)": ("text", good.replace(
            b"    gpua_fma_lane(&f", b"    (void)reduce_leaf;\n    gpua_fma_lane(&f", 1)),
        "cft_g_mul calling itself (the call-graph scan)": ("text", good.replace(
            b"    *hi = p11 + (p01 >> 16)", b"    cft_g_mul(a, b, hi, lo);\n    *hi = p11 + (p01 >> 16)", 1)),
        "one byte of the written text changed": ("check", good.replace(b"(1u << 27)", b"(1u << 28)", 1)),
    }
    bad = 0
    for what, (kind, val) in plants.items():
        try:
            if kind == "edits":
                derive(files, hip, kernel, val)
            elif kind == "files":
                derive(val, hip, kernel)
            elif kind == "shim":
                oclcopy.SHIM = val
                try:
                    derive(files, hip, kernel)
                finally:
                    oclcopy.SHIM = shim
            elif kind == "text":
                assert val != good
                code = code_view(val)
                no_caller_w11(code)
                oclcopy.no_recursion(code)
                scan(code)
            else:
                oclcopy.check(val, good)
            print(f"selftest: plant '{what}' PASSED - the check is broken")
            bad += 1
        except ValueError as e:
            print(f"selftest: plant '{what}' refused: {e}")
    oclcopy.check(good, derive(files, hip, kernel)[0])
    print(f"selftest: honest text accepted, sha256 {hashlib.sha256(good).hexdigest()}")
    if bad:
        sys.exit(1)
    print(f"selftest: OK, {len(plants)} plants refused by name")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("devsrc", type=Path)
    ap.add_argument("out")
    ap.add_argument("--hip", type=Path, default=oclcopy.HIP)
    ap.add_argument("--kernel", type=Path, default=oclcopy.KERNEL)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--seedcheck", action="store_true")
    ap.add_argument("--plant", action="store_true")
    a = ap.parse_args()
    try:
        files, hip, kernel = oclcopy.read_inputs(a.devsrc, a.hip, a.kernel)
        if a.selftest:
            return selftest(files, hip, kernel)
        if a.seedcheck:
            Path(a.out).write_bytes(seedcheck(files, hip, kernel, a.plant))
            print(f"wgslcopy: --seedcheck{' --plant' if a.plant else ''} -> {Path(a.out).name}")
            return
        text, ocounts, counts = derive(files, hip, kernel)
        if not a.check:
            Path(a.out).write_bytes(text)
        oclcopy.check(Path(a.out).read_bytes(), text)
        nf, nr = scan(code_view(text))
        print(f"wgslcopy: oclcopy's edits {', '.join(f'{k} {n}' for k, n in sorted(ocounts.items()))}"
              f" ({sum(ocounts.values())}); GPU-G's {', '.join(f'{k} {n}' for k, n in sorted(counts.items(), key=lambda kv: int(kv[0][1:])))}"
              f" ({sum(counts.values())}); {sum(ocounts.values()) + sum(counts.values())} in all")
        print(f"wgslcopy: -> {Path(a.out).name}, {len(text)} bytes, sha256 {hashlib.sha256(text).hexdigest()}")
        print(f"wgslcopy: {nr} of {nf} functions reachable from {KERNEL_NAME}: no 64-bit or 8-bit "
              f"integer in them or their structs; no recursion; cft_sf_reduce and reduce_leaf uncalled")
    except (ValueError, OSError) as e:
        print(f"wgslcopy: REFUSED: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
