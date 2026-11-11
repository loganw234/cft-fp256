/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * GPU-A part 2: libcft's sequencer programs on GPUs through HIP, one thread
 * a lane, from one source for the CPU, NVIDIA and AMD (build_seq.sh).
 *
 * What is libcft's here and what is not:
 *
 *   libcft's, by devcopy.py --seq (checked at every build): the executor,
 *   seq_run_block, with every function, type and constant it reaches, in
 *   src/seqcore.c, byte for byte but for E1 (CFT_HD), E3 (BLOCK_LANES 1) and
 *   E4 (its one ALU call through CFT_GPUA_ALU); the arithmetic, bigint.c and
 *   softfloat.c, as in part 1; cft.h, unedited.
 *
 *   NOT libcft's, a second implementation of the sequencer's run semantics
 *   (program.c's seq_program_run and its loader), held bit for bit to libcft
 *   by seq_ref.c on the same corpus: gpua_parse (the image's header,
 *   constants and instructions, and seq_scratch_footprint's two fields),
 *   gpua_konst (the bank decoded once), gpua_seq_lane (one lane's setup and
 *   read-back: the registers, the R17 mask, the deposits' zero-fill, the
 *   scratch block, the counts and the R23 lane byte) and the OR of the
 *   run's flags and status, which is an atomic OR on a GPU. It does not
 *   validate an image: every image in the corpus was loaded, and so
 *   validated, by libcft in seq_ref.
 *
 *   NOT libcft's either: gpua_alu's fp256 path under -DCFT_GPUA_FIXED, which
 *   takes FMA, ADD, SUB and MUL through libcft's own operand steering
 *   (sf_steer) into part 1's second kernel (fma256_fixed.h).
 *
 * Refused by name, never computed approximately: augmentedAddition (control
 * codes 10 and 11; augmented.c is not in the device copy), a format this
 * build does not carry, and an image whose header this parser does not know.
 *
 *   cft_seq run CORPUS OUT|- [--expect FILE] [--device N] [--block B]
 *   cft_seq bench CORPUS --case K --lanes N [--reps R] [--device N] [--block B]
 *   cft_seq info [--device N]
 *
 * Plants (each must turn `run --expect` red, by name): CFT_GPUA_PLANT_SEQ_MASK
 * (the runner ignores the R17 lane mask) and CFT_GPUA_PLANT_SEQ_KONST (an
 * operand source: constant k read from the bank's entry k + 1).
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <algorithm>
#include <chrono>
#include <string>
#include <vector>

#ifdef CFT_GPUA_CPU
#  define CFT_HD
#else
#  include <hip/hip_runtime.h>
#  define CFT_HD __host__ __device__
#endif

#include "src/bigint.c"           /* devcopy.py's copies: E1 alone */
#include "src/softfloat.c"
#include "cft.h"                  /* include/cft.h: host/include/cft.h unedited */
#include "sha256.h"               /* host/src as it is; sha256.o */
#ifdef CFT_GPUA_FIXED
#  include "fma256_fixed.h"       /* part 1's second kernel: NOT libcft's code */
#endif

/* E4's hook: seq_run_block's one ALU call. cft_sf_compute itself, unless
 * the fp256 path is built; then FMA, ADD, SUB and MUL at fp256 go through
 * sf_steer (libcft's steering, the identities ADD = FMA(a, 1, c), SUB =
 * FMA(a, 1, -c), MUL = FMA(a, b, +-0 by the product's sign)) into the
 * second kernel. Every other operation and format is cft_sf_compute. */
CFT_HD static int gpua_alu(const cft_fmt_desc *f, int op, int rnd, const cft_bn *a,
                           const cft_bn *b, const cft_bn *c, cft_bn *out, uint32_t *fl)
{
#ifdef CFT_GPUA_FIXED
    if (f->width == 256 && op >= CFT_SF_FMA && op <= CFT_SF_MUL && rnd >= 0 &&
        rnd <= CFT_SF_RMM) {
        cft_bn sa, sb, sc;
        uint8_t pa[32], pb[32], pc[32], pd[32], pf = 0;
        *fl = 0;
        if (sf_steer(f, op, a, b, c, &sa, &sb, &sc))
            return 1;
        cft_bn_store(&sa, pa, 32);
        cft_bn_store(&sb, pb, 32);
        cft_bn_store(&sc, pc, 32);
        f256_fma_lane(pa, pb, pc, rnd, pd, &pf);
        cft_bn_zero(out);
        cft_bn_load(out, pd, 32);
        *fl = pf;
        return 0;
    }
#endif
    return cft_sf_compute(f, op, rnd, a, b, c, out, fl);
}
#define CFT_GPUA_ALU gpua_alu
#include "src/seqcore.c"          /* devcopy.py --seq: program.c's executor */

/* One run's buffers, device pointers on a GPU. */
typedef struct {
    const uint8_t *a, *b, *c, *mask, *sin;
    uint8_t *dep, *lf, *sout;
    uint32_t *counts;
    cft_bn *scratch;              /* scr_reach slots a lane, or NULL */
    uint32_t scr_reach;
    uint32_t *acc;                /* [0] flags, [1] status, [2] error, [3] first lane in error */
} gpua_io;

#if defined(__CUDA_ARCH__) || defined(__HIP_DEVICE_COMPILE__)
#  define GPUA_OR(p, v) atomicOr((p), (v))     /* OR and min: no order can change them */
#  define GPUA_MIN(p, v) atomicMin((p), (v))
#else
#  define GPUA_OR(p, v) (*(p) |= (v))
#  define GPUA_MIN(p, v) (*(p) = *(p) < (v) ? *(p) : (v))
#endif

/* One lane: what seq_program_run does for lane i of a run, around the
 * copied seq_run_block, with a block of one lane. */
CFT_HD static void gpua_seq_lane(const cft_program *P, const cft_bn *konst,
                                 const gpua_io *io, int64_t i)
{
    seq_block B;
    const size_t esz = (size_t)P->f->width / 8;
    uint32_t fl = 0, st = 0, s;
    cft_status rc;
    int r;
    for (r = 0; r < SEQ_NREG; r++)
        cft_bn_zero(&B.regs[0][r]);
    seq_load_in(&B.regs[0][0], io->a, NULL, (size_t)i, esz);
    if (io->b)
        seq_load_in(&B.regs[0][1], io->b, NULL, (size_t)i, esz);
    if (io->c)
        seq_load_in(&B.regs[0][2], io->c, NULL, (size_t)i, esz);
    B.keep[0] = (!io->mask || (io->mask[i >> 3] & (uint8_t)(1u << (i & 7)))) ? 1 : 0;
#ifdef CFT_GPUA_PLANT_SEQ_MASK
    B.keep[0] = 1;
#endif
    B.active[0] = B.keep[0];
    B.counts[0] = 0;
    B.lflags[0] = 0;
    B.depth = P->scratch_depth;
    B.scratch = NULL;
    if (P->scratch_active) {
        B.scratch = io->scratch + (size_t)i * io->scr_reach;
        for (s = 0; s < io->scr_reach; s++)
            cft_bn_zero(&B.scratch[s]);
        for (s = 0; io->sin && s < P->n_scratch_in; s++)
            seq_load_in(&B.scratch[s], io->sin, NULL, (size_t)i * P->n_scratch_in + s, esz);
    }
    /* every slot of a lane the caller has is written: +0 where nothing lands */
    if (io->dep && P->max_deposits && B.keep[0]) {
        uint8_t *d = io->dep + (size_t)i * P->max_deposits * esz;
        size_t k;
        for (k = 0; k < (size_t)P->max_deposits * esz; k++)
            d[k] = 0;
    }
    rc = seq_run_block(P, konst, &B, 1, io->dep, (size_t)i, esz, &fl, &st);
    if (rc != CFT_OK) {
        GPUA_OR(&io->acc[2], (uint32_t)rc);
        GPUA_MIN(&io->acc[3], (uint32_t)i);
        return;
    }
    if (B.keep[0]) {
        io->counts[i] = B.counts[0];
        if (io->lf)
            io->lf[i] = B.lflags[0];
        if (io->sout)
            for (s = 0; s < P->n_scratch_out; s++)
                cft_bn_store(&B.scratch[s], io->sout + ((size_t)i * P->n_scratch_out + s) * esz,
                             (int)esz);
    }
    if (fl)
        GPUA_OR(&io->acc[0], fl);
    if (st)
        GPUA_OR(&io->acc[1], st);
}

#ifndef CFT_GPUA_CPU
__global__ void __launch_bounds__(256)
gpua_seq_kernel(cft_program Pin, cft_fmt_desc f, const cft_bn *konst, gpua_io io, int64_t n)
{
    int64_t i = (int64_t)blockIdx.x * blockDim.x + threadIdx.x;
    cft_program P = Pin;
    P.f = &f;
    if (i < n)
        gpua_seq_lane(&P, konst, &io, i);
}

#define CK(x) do { hipError_t e_ = (x); if (e_ != hipSuccess) { \
    fprintf(stderr, "%s:%d: %s: %s\n", __FILE__, __LINE__, #x, \
            hipGetErrorString(e_)); exit(2); } } while (0)
#endif

typedef std::chrono::steady_clock clk;
static double ms_since(clk::time_point t0)
{
    return std::chrono::duration<double, std::milli>(clk::now() - t0).count();
}

/* ---- the corpus (gen_programs.py's layout), one case at a time ---------- */
struct scase {
    std::string name;
    uint32_t fmt, n, image_bytes, bank_bytes, present, fill, fill_count, nsi, nso;
    const uint8_t *image, *bank, *a, *b, *c, *mask, *sin;
    size_t esz;
    /* gpua_parse's */
    uint32_t n_insns, n_consts, maxdep, flags, scratch_used;
    int scratch_active;
    std::vector<uint64_t> insns;
};

static uint32_t rd32(const uint8_t *p) { uint32_t v; memcpy(&v, p, 4); return v; }

static std::vector<uint8_t> slurp(const char *path)
{
    std::vector<uint8_t> v;
    uint8_t buf[1 << 16];
    size_t got;
    FILE *fp = fopen(path, "rb");
    if (!fp) { fprintf(stderr, "cannot open %s\n", path); exit(2); }
    while ((got = fread(buf, 1, sizeof buf, fp)) > 0)
        v.insert(v.end(), buf, buf + got);
    fclose(fp);
    return v;
}

static std::vector<scase> load_cases(const std::vector<uint8_t> &raw, const char *path)
{
    std::vector<scase> out;
    size_t off = 0;
    while (off < raw.size()) {
        scase k;
        const uint8_t *p = raw.data() + off;
        size_t need = 48, nl;
        if (raw.size() - off < need || memcmp(p, "CFTSEQA1", 8)) {
            fprintf(stderr, "%s: not a GPU-A program corpus at byte %zu\n", path, off); exit(2);
        }
        k.fmt = rd32(p + 8); k.n = rd32(p + 12); k.image_bytes = rd32(p + 16);
        k.bank_bytes = rd32(p + 20); k.present = rd32(p + 24); k.fill = rd32(p + 28);
        k.fill_count = rd32(p + 32); k.nsi = rd32(p + 36); k.nso = rd32(p + 40);
        nl = rd32(p + 44);
        if (k.fmt > 3) { fprintf(stderr, "%s: format code %u\n", path, k.fmt); exit(2); }
        k.esz = (size_t)cft_sf_formats[k.fmt].width / 8;
        p += 48;
        k.name.assign((const char *)p, nl); p += nl;
        k.image = p; p += k.image_bytes;
        k.bank = p; p += k.bank_bytes;
        k.a = p; p += k.n * k.esz;
        k.b = (k.present & 1) ? p : NULL; if (k.b) p += k.n * k.esz;
        k.c = (k.present & 2) ? p : NULL; if (k.c) p += k.n * k.esz;
        k.mask = (k.present & 4) ? p : NULL; if (k.mask) p += (k.n + 7) / 8;
        k.sin = (k.present & 16) ? p : NULL; if (k.sin) p += (size_t)k.n * k.nsi * k.esz;
        if (p > raw.data() + raw.size()) { fprintf(stderr, "%s: truncated case\n", path); exit(2); }
        off = (size_t)(p - raw.data());
        out.push_back(k);
    }
    return out;
}

/* The image: program.c's loader re-expressed for this runner (header,
 * constants, instructions) and seq_scratch_footprint's two fields, at a
 * software handle's depth. Returns a refusal sentence, or NULL. */
static const char *gpua_parse(scase *k, cft_program *P, std::vector<cft_bn> *konst)
{
    const uint8_t *p = k->image;
    uint32_t n_stored, i, used = 0;
    int touched = 0, indexed = 0;
    if (k->image_bytes < 32 || rd32(p) != 0x50544643u || rd32(p + 4) != 1u)
        return "an image whose header this parser does not know (magic and version)";
    k->n_insns = rd32(p + 8); k->n_consts = rd32(p + 12); k->maxdep = rd32(p + 16);
    k->flags = rd32(p + 24);
    if (rd32(p + 20) != k->fmt)
        return "an image whose format is not its case's";
    if (CFT_FMT_ABSENT(k->fmt))
        return "a format this build does not carry (CFT_MAX_FORMAT)";
    n_stored = (k->flags & CFT_PROG_FLAG_BANK_EXT) ? 0u : k->n_consts;
    if ((uint64_t)k->image_bytes != 32ull + (uint64_t)n_stored * k->esz + 8ull * k->n_insns)
        return "an image whose size is not its header's";
    k->insns.resize(k->n_insns);
    for (i = 0; i < k->n_insns; i++)
        memcpy(&k->insns[i], p + 32 + n_stored * k->esz + 8u * i, 8);
    for (i = 0; i < k->n_insns; i++) {
        seq_insn d;
        seq_decode(k->insns[i], &d);
        if (!d.ctrl)
            continue;
        if (d.op == SEQ_AUGADD || d.op == SEQ_AUGERR)
            return "augmentedAddition (control codes 10 and 11): augmented.c is not in "
                   "the device copy (CFT_NO_AUGMENTED)";
        if (d.op == SEQ_STL || d.op == SEQ_LDL) {
            touched = 1;
            if ((d.imm & SEQ_KX_INDICES) + 1u > used)
                used = (d.imm & SEQ_KX_INDICES) + 1u;
        } else if (d.op == SEQ_STX || d.op == SEQ_LDX) {
            touched = indexed = 1;
        }
    }
    memset(P, 0, sizeof *P);
    P->f = &cft_sf_formats[k->fmt];
    P->insns = k->insns.data();       /* the CPU's; a GPU run puts its copy here */
    P->fmt_code = (int)k->fmt;
    P->max_deposits = k->maxdep;
    P->n_insns = k->n_insns;
    P->n_consts = k->n_consts;
    P->flags = k->flags;
    if (k->flags & CFT_PROG_FLAG_SCRATCH_IO) {
        P->n_scratch_in = rd32(p + 28) & 0xFFFFu;
        P->n_scratch_out = (rd32(p + 28) >> 16) & 0xFFFFu;
    }
    if (P->n_scratch_in != k->nsi || P->n_scratch_out != k->nso)
        return "a case whose scratch block is not its image's";
    P->scratch_depth = 256;               /* a plain software handle's */
    P->scratch_log2 = 8;
    P->scratch_used = indexed ? P->scratch_depth : used;
    P->scratch_active = touched || (k->flags & CFT_PROG_FLAG_SCRATCH_IO) != 0;
    k->scratch_used = P->scratch_used;
    k->scratch_active = P->scratch_active;
    /* the constants, decoded once: the run's bank where one is given */
    konst->assign(k->n_consts, cft_bn());
    for (i = 0; i < k->n_consts; i++) {
        const uint8_t *src = k->bank_bytes ? k->bank + (size_t)i * k->esz
                                           : p + 32 + (size_t)i * k->esz;
#ifdef CFT_GPUA_PLANT_SEQ_KONST
        if (k->n_consts > 1)
            src = (k->bank_bytes ? k->bank : p + 32) + (size_t)((i + 1) % k->n_consts) * k->esz;
#endif
        cft_bn_zero(&(*konst)[i]);
        cft_bn_load(&(*konst)[i], src, (int)k->esz);
    }
    if (k->bank_bytes && k->bank_bytes != k->n_consts * k->esz)
        return "a bank whose size is not n_consts elements";
    return NULL;
}

static int device_index = 0, block = 128, reps = 10;
static int64_t lanes = 0, one_case = -1;
static char device_name[320] = "cpu, one thread";

static void pick_device(void)
{
#ifndef CFT_GPUA_CPU
    hipDeviceProp_t p;
    char bus[32] = {0};
    memset(&p, 0, sizeof p);              /* part 1: gcnArchName unwritten on NVIDIA */
    CK(hipSetDevice(device_index));
    CK(hipGetDeviceProperties(&p, device_index));
    CK(hipDeviceGetPCIBusId(bus, (int)sizeof bus, device_index));
    if (!strncmp(p.gcnArchName, "gfx", 3))
        snprintf(device_name, sizeof device_name, "%.200s (%.60s, bus %s)", p.name,
                 p.gcnArchName, bus);
    else
        snprintf(device_name, sizeof device_name, "%.200s (sm_%d%d, bus %s)", p.name,
                 p.major, p.minor, bus);
#endif
}

/* The output a case writes, byte for byte the layout seq_ref.c writes:
 * meta (7 words), rc, flags, status, deposits, counts, lane bytes when
 * asked, scratch-out when declared. */
struct sout {
    std::vector<uint8_t> dep, lf, so;
    std::vector<uint32_t> counts;
    uint32_t acc[4];
};

/* Runs n lanes of case k, lane j taking the case's lane j % k.n (n = k.n
 * for a check). Returns the kernel's (or the CPU loop's) milliseconds a
 * repetition, median of `nrep`, with min and max in mm[0], mm[1]. */
static double run_case(scase *k, const cft_program *P0, const std::vector<cft_bn> &konst,
                       int64_t n, int nrep, sout *o, double *mm)
{
    const size_t esz = k->esz;
    const uint32_t md = k->maxdep;
    const uint32_t reach = k->scratch_active ? std::min<uint32_t>(256u,
        std::max(std::max(k->scratch_used, k->nsi), k->nso)) : 0u;
    std::vector<uint8_t> a(n * esz), b, c, m, si;
    std::vector<double> t;
    int64_t j;
    for (j = 0; j < n; j++)
        memcpy(&a[j * esz], k->a + (j % k->n) * esz, esz);
    if (k->b) { b.resize(n * esz); for (j = 0; j < n; j++) memcpy(&b[j * esz], k->b + (j % k->n) * esz, esz); }
    if (k->c) { c.resize(n * esz); for (j = 0; j < n; j++) memcpy(&c[j * esz], k->c + (j % k->n) * esz, esz); }
    if (k->mask) {
        m.assign((n + 7) / 8, 0);
        for (j = 0; j < n; j++)
            if (k->mask[(j % k->n) >> 3] & (1u << ((j % k->n) & 7)))
                m[j >> 3] |= (uint8_t)(1u << (j & 7));
    }
    if (k->sin) {
        si.resize((size_t)n * k->nsi * esz);
        for (j = 0; j < n; j++)
            memcpy(&si[(size_t)j * k->nsi * esz], k->sin + (size_t)(j % k->n) * k->nsi * esz,
                   (size_t)k->nsi * esz);
    }
    o->dep.assign((size_t)n * md * esz, (uint8_t)(k->fill & 0xFF));
    o->counts.assign(n, k->fill_count);
    o->lf.assign((k->present & 8) ? n : 0, (uint8_t)((k->fill >> 8) & 0xFF));
    o->so.assign((size_t)n * k->nso * esz, (uint8_t)(k->fill & 0xFF));
    o->acc[0] = o->acc[1] = o->acc[2] = 0;
    o->acc[3] = 0xFFFFFFFFu;
#ifdef CFT_GPUA_CPU
    {
        std::vector<cft_bn> scr((size_t)(reach ? n : 0) * reach);
        gpua_io io;
        int rep;
        io.a = a.data(); io.b = k->b ? b.data() : NULL; io.c = k->c ? c.data() : NULL;
        io.mask = k->mask ? m.data() : NULL; io.sin = k->sin ? si.data() : NULL;
        io.dep = md ? o->dep.data() : NULL; io.lf = (k->present & 8) ? o->lf.data() : NULL;
        io.sout = k->nso ? o->so.data() : NULL; io.counts = o->counts.data();
        io.scratch = reach ? scr.data() : NULL; io.scr_reach = reach; io.acc = o->acc;
        for (rep = 0; rep < nrep; rep++) {
            clk::time_point t0 = clk::now();
            for (j = 0; j < n; j++)
                gpua_seq_lane(P0, konst.data(), &io, j);
            t.push_back(ms_since(t0));
        }
    }
#else
    {
        uint8_t *da, *db = NULL, *dc = NULL, *dm = NULL, *dsi = NULL, *ddep = NULL, *dlf = NULL,
                *dso = NULL;
        uint32_t *dcount, *dacc;
        cft_bn *dk = NULL, *dscr = NULL;
        uint64_t *dins;
        cft_program P = *P0;
        gpua_io io;
        hipEvent_t e0, e1;
        int rep;
        const int64_t nb = (n + block - 1) / block;
        CK(hipMalloc((void **)&da, a.size()));
        CK(hipMemcpy(da, a.data(), a.size(), hipMemcpyHostToDevice));
        if (k->b) { CK(hipMalloc((void **)&db, b.size())); CK(hipMemcpy(db, b.data(), b.size(), hipMemcpyHostToDevice)); }
        if (k->c) { CK(hipMalloc((void **)&dc, c.size())); CK(hipMemcpy(dc, c.data(), c.size(), hipMemcpyHostToDevice)); }
        if (k->mask) { CK(hipMalloc((void **)&dm, m.size())); CK(hipMemcpy(dm, m.data(), m.size(), hipMemcpyHostToDevice)); }
        if (k->sin) { CK(hipMalloc((void **)&dsi, si.size())); CK(hipMemcpy(dsi, si.data(), si.size(), hipMemcpyHostToDevice)); }
        if (md) { CK(hipMalloc((void **)&ddep, o->dep.size())); CK(hipMemcpy(ddep, o->dep.data(), o->dep.size(), hipMemcpyHostToDevice)); }
        if (k->present & 8) { CK(hipMalloc((void **)&dlf, n)); CK(hipMemcpy(dlf, o->lf.data(), n, hipMemcpyHostToDevice)); }
        if (k->nso) { CK(hipMalloc((void **)&dso, o->so.size())); CK(hipMemcpy(dso, o->so.data(), o->so.size(), hipMemcpyHostToDevice)); }
        CK(hipMalloc((void **)&dcount, n * 4));
        CK(hipMemcpy(dcount, o->counts.data(), n * 4, hipMemcpyHostToDevice));
        CK(hipMalloc((void **)&dacc, 16));
        CK(hipMemcpy(dacc, o->acc, 16, hipMemcpyHostToDevice));
        if (konst.size()) {
            CK(hipMalloc((void **)&dk, konst.size() * sizeof(cft_bn)));
            CK(hipMemcpy(dk, konst.data(), konst.size() * sizeof(cft_bn), hipMemcpyHostToDevice));
        }
        if (reach)
            CK(hipMalloc((void **)&dscr, (size_t)n * reach * sizeof(cft_bn)));
        CK(hipMalloc((void **)&dins, 8 * (size_t)std::max<uint32_t>(1, k->n_insns)));
        CK(hipMemcpy(dins, k->insns.data(), 8 * (size_t)k->n_insns, hipMemcpyHostToDevice));
        P.insns = dins;
        io.a = da; io.b = db; io.c = dc; io.mask = dm; io.sin = dsi; io.dep = ddep; io.lf = dlf;
        io.sout = dso; io.counts = dcount; io.scratch = dscr; io.scr_reach = reach; io.acc = dacc;
        CK(hipEventCreate(&e0));
        CK(hipEventCreate(&e1));
        for (rep = 0; rep < nrep + (nrep > 1); rep++) {     /* a warm-up when timing */
            float ms = 0;
            CK(hipEventRecord(e0, 0));
            gpua_seq_kernel<<<(unsigned)nb, block>>>(P, *P0->f, dk, io, n);
            CK(hipEventRecord(e1, 0));
            CK(hipGetLastError());
            CK(hipDeviceSynchronize());
            CK(hipEventElapsedTime(&ms, e0, e1));
            if (nrep == 1 || rep > 0)
                t.push_back(ms);
        }
        if (md) CK(hipMemcpy(o->dep.data(), ddep, o->dep.size(), hipMemcpyDeviceToHost));
        if (k->present & 8) CK(hipMemcpy(o->lf.data(), dlf, n, hipMemcpyDeviceToHost));
        if (k->nso) CK(hipMemcpy(o->so.data(), dso, o->so.size(), hipMemcpyDeviceToHost));
        CK(hipMemcpy(o->counts.data(), dcount, n * 4, hipMemcpyDeviceToHost));
        CK(hipMemcpy(o->acc, dacc, 16, hipMemcpyDeviceToHost));
        CK(hipFree(da)); if (db) CK(hipFree(db)); if (dc) CK(hipFree(dc)); if (dm) CK(hipFree(dm));
        if (dsi) CK(hipFree(dsi)); if (ddep) CK(hipFree(ddep)); if (dlf) CK(hipFree(dlf));
        if (dso) CK(hipFree(dso)); if (dk) CK(hipFree(dk)); if (dscr) CK(hipFree(dscr));
        CK(hipFree(dcount)); CK(hipFree(dacc)); CK(hipFree(dins));
        CK(hipEventDestroy(e0)); CK(hipEventDestroy(e1));
    }
#endif
    std::sort(t.begin(), t.end());
    mm[0] = t.front();
    mm[1] = t.back();
    return t[t.size() / 2];
}

static void put32(std::vector<uint8_t> *v, uint32_t x)
{
    v->insert(v->end(), (uint8_t *)&x, (uint8_t *)&x + 4);
}

/* The case's output bytes; rc is the run's status (CFT_OK, or the first
 * lane's error), as cft_program_run_ex returns it. */
static void case_bytes(const scase *k, const sout *o, std::vector<uint8_t> *v)
{
    put32(v, k->n_insns); put32(v, k->n_consts); put32(v, k->maxdep); put32(v, k->flags);
    put32(v, k->nsi); put32(v, k->nso); put32(v, k->scratch_used);
    put32(v, o->acc[2] ? o->acc[2] : (uint32_t)CFT_OK);
    put32(v, o->acc[0]); put32(v, o->acc[1]);
    v->insert(v->end(), o->dep.begin(), o->dep.end());
    v->insert(v->end(), (const uint8_t *)o->counts.data(),
              (const uint8_t *)o->counts.data() + 4 * o->counts.size());
    v->insert(v->end(), o->lf.begin(), o->lf.end());
    v->insert(v->end(), o->so.begin(), o->so.end());
}

/* The first difference between two cases' outputs, by field and lane. */
static void name_diff(const scase *k, const uint8_t *g, const uint8_t *w, size_t len)
{
    static const char *meta[10] = {"n_insns", "n_consts", "max_deposits", "flags word",
                                   "n_scratch_in", "n_scratch_out", "scratch_used", "rc",
                                   "FLAGS", "STATUS"};
    const size_t dl = (size_t)k->n * k->maxdep * k->esz, cl = 4 * (size_t)k->n;
    const size_t ll = (k->present & 8) ? k->n : 0;
    size_t i;
    for (i = 0; i < len && g[i] == w[i]; i++)
        ;
    if (i < 40)
        printf("  DIFF %s: %s here 0x%x, libcft 0x%x\n", k->name.c_str(), meta[i / 4],
               rd32(g + i / 4 * 4), rd32(w + i / 4 * 4));
    else if ((i -= 40) < dl)
        printf("  DIFF %s: deposit lane %zu slot %zu\n", k->name.c_str(),
               i / (k->maxdep * k->esz), i / k->esz % k->maxdep);
    else if ((i -= dl) < cl)
        printf("  DIFF %s: count lane %zu: here %u, libcft %u\n", k->name.c_str(), i / 4,
               rd32(g + 40 + dl + i / 4 * 4), rd32(w + 40 + dl + i / 4 * 4));
    else if ((i -= cl) < ll)
        printf("  DIFF %s: lane byte %zu: here 0x%02x, libcft 0x%02x\n", k->name.c_str(), i,
               g[40 + dl + cl + i], w[40 + dl + cl + i]);
    else
        printf("  DIFF %s: scratch-out byte %zu\n", k->name.c_str(), i - ll);
}

static int do_run(const char *cpath, const char *opath, const char *epath)
{
    std::vector<uint8_t> raw = slurp(cpath), outv, want;
    std::vector<scase> cs = load_cases(raw, cpath);
    size_t woff = 0, k;
    long long nl = 0, nins = 0, bad = 0, refused = 0;
    double tms = 0;
    uint8_t dg[32];
    char hx[65];
    cft_sha256_ctx s;
    pick_device();
    if (epath)
        want = slurp(epath);
    for (k = 0; k < cs.size(); k++) {
        cft_program P;
        std::vector<cft_bn> konst;
        sout o;
        double mm[2];
        const char *why = gpua_parse(&cs[k], &P, &konst);
        size_t before = outv.size();
        if (why) {
            printf("refused: %s: %s\n", cs[k].name.c_str(), why);
            refused++;
            continue;
        }
        tms += run_case(&cs[k], &P, konst, cs[k].n, 1, &o, mm);
        case_bytes(&cs[k], &o, &outv);
        nl += cs[k].n;
        nins += (long long)cs[k].n * cs[k].n_insns;
        if (epath) {
            const size_t len = outv.size() - before;
            if (woff + len > want.size() || memcmp(&outv[before], &want[woff], len)) {
                if (bad < 8 && woff + len <= want.size())
                    name_diff(&cs[k], &outv[before], &want[woff], len);
                bad++;
            }
            woff += len;
        }
    }
    cft_sha256_init(&s);
    cft_sha256_update(&s, outv.data(), outv.size());
    cft_sha256_final(&s, dg);
    cft_sha256_hex(dg, hx);
    if (opath) {
        FILE *fp = fopen(opath, "wb");
        if (!fp || fwrite(outv.data(), 1, outv.size(), fp) != outv.size()) {
            fprintf(stderr, "cannot write %s\n", opath); exit(2);
        }
        fclose(fp);
    }
    if (epath && woff != want.size())
        bad++;
    printf("run: %s on %s: %zu cases, %lld lanes, %lld lanes x program length, %lld refused; "
           "sha256 %s; %.1f ms%s%s\n", cpath, device_name, cs.size(), nl, nins, refused, hx,
           tms, epath ? (bad ? "; RED: " : "; GREEN against ") : "", epath ? epath : "");
    if (epath && bad)
        printf("run: %lld of %zu cases differ from libcft's\n", bad, cs.size());
    return (epath && bad) || refused ? 1 : 0;
}

static int do_bench(const char *cpath)
{
    std::vector<uint8_t> raw = slurp(cpath);
    std::vector<scase> cs = load_cases(raw, cpath);
    cft_program P;
    std::vector<cft_bn> konst;
    sout o;
    double mm[2], med;
    const char *why;
    if (one_case < 0 || (size_t)one_case >= cs.size() || lanes < 1) {
        fprintf(stderr, "refused: bench needs --case K (0..%zu) and --lanes N\n", cs.size() - 1);
        return 2;
    }
    pick_device();
    why = gpua_parse(&cs[one_case], &P, &konst);
    if (why) {
        printf("refused: %s: %s\n", cs[one_case].name.c_str(), why);
        return 1;
    }
    med = run_case(&cs[one_case], &P, konst, lanes, reps, &o, mm);
    printf("bench: %s case %lld (%s, %u instructions) on %s, block %d: %lld lanes, kernel "
           "%.3f ms (min %.3f, max %.3f, %d reps): %.4g lane-programs/s, %.4g "
           "lane-instructions/s\n", cpath, (long long)one_case, cs[one_case].name.c_str(),
           cs[one_case].n_insns, device_name, block, (long long)lanes, med, mm[0], mm[1], reps,
           lanes / (med * 1e-3), (double)lanes * cs[one_case].n_insns / (med * 1e-3));
    return o.acc[2] ? 1 : 0;
}

static int do_info(void)
{
#ifdef CFT_GPUA_CPU
    printf("info: the CPU build; sizeof(cft_bn) %d, CFT_BN_LIMBS %d, sizeof(seq_block) %d\n",
           (int)sizeof(cft_bn), (int)CFT_BN_LIMBS, (int)sizeof(seq_block));
#else
    hipDeviceProp_t p;
    hipFuncAttributes fa;
    size_t stack0 = 0, stack1 = 0;
    int bs;
    pick_device();
    CK(hipGetDeviceProperties(&p, device_index));
    CK(hipFuncGetAttributes(&fa, (const void *)gpua_seq_kernel));
    CK(hipDeviceGetLimit(&stack0, hipLimitStackSize));
    printf("info: %s: %d CUs/SMs; runner kernel: %d registers a thread, %d bytes local a "
           "thread; sizeof(cft_bn) %d, CFT_BN_LIMBS %d, sizeof(seq_block) %d\n", device_name,
           p.multiProcessorCount, fa.numRegs, (int)fa.localSizeBytes, (int)sizeof(cft_bn),
           (int)CFT_BN_LIMBS, (int)sizeof(seq_block));
    for (bs = 32; bs <= 256; bs *= 2) {
        int nb = 0;
        CK(hipOccupancyMaxActiveBlocksPerMultiprocessor(&nb, gpua_seq_kernel, bs, 0));
        printf("info: block %d: %d blocks a CU/SM resident, occupancy %.1f %%\n", bs, nb,
               100.0 * nb * bs / p.maxThreadsPerMultiProcessor);
    }
    {
        cft_program P;
        gpua_io io;
        memset(&P, 0, sizeof P);
        memset(&io, 0, sizeof io);
        gpua_seq_kernel<<<1, 1>>>(P, cft_sf_formats[1], NULL, io, 0);
        CK(hipGetLastError());
        CK(hipDeviceSynchronize());
    }
    CK(hipDeviceGetLimit(&stack1, hipLimitStackSize));
    printf("info: stack limit a thread: %zu bytes before any launch, %zu after one\n",
           stack0, stack1);
#endif
    return 0;
}

int main(int argc, char **argv)
{
    int i;
    const char *pos[2] = {NULL, NULL}, *expect = NULL;
    int npos = 0;
    if (argc < 2) {
        fprintf(stderr, "usage: %s run CORPUS OUT|- [--expect FILE] | bench CORPUS --case K "
                "--lanes N | info  [--device N] [--block B] [--reps R]\n", argv[0]);
        return 2;
    }
    for (i = 2; i < argc; i++) {          /* an unknown option is refused, never ignored */
        if (!strcmp(argv[i], "--device") && i + 1 < argc) device_index = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--block") && i + 1 < argc) block = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--reps") && i + 1 < argc) reps = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--lanes") && i + 1 < argc) lanes = atoll(argv[++i]);
        else if (!strcmp(argv[i], "--case") && i + 1 < argc) one_case = atoll(argv[++i]);
        else if (!strcmp(argv[i], "--expect") && i + 1 < argc) expect = argv[++i];
        else if (!strncmp(argv[i], "--", 2) || npos == 2) {
            fprintf(stderr, "refused: argument '%s' is not one this build knows\n", argv[i]);
            return 2;
        } else
            pos[npos++] = argv[i];
    }
    if (block < 1 || block > 256 || reps < 1) {
        fprintf(stderr, "refused: --block is 1..256 and --reps at least 1\n");
        return 2;
    }
    if (!strcmp(argv[1], "run") && npos == 2)
        return do_run(pos[0], strcmp(pos[1], "-") ? pos[1] : NULL, expect);
    if (!strcmp(argv[1], "bench") && npos == 1)
        return do_bench(pos[0]);
    if (!strcmp(argv[1], "info") && npos == 0)
        return do_info();
    fprintf(stderr, "refused: unknown command or wrong number of arguments\n");
    return 2;
}
