/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The embedded client's codec, proved on a desktop before it is ever
 * put on a board.
 *
 * The SAME cft_remote.cpp an Uno compiles is compiled here by the
 * desktop's g++ and driven against a real cft-serve over a real
 * socket, and every answer it brings back is compared, bit for bit,
 * with what libcft's own software backend computes for the same call
 * in the same process. Two things this buys that a board cannot:
 *
 *   1. THE TRANSCRIBED CONSTANTS ARE HELD TO THEIR SOURCES AT COMPILE
 *      TIME. This file includes host/src/remote.h and host/include/cft.h
 *      beside bindings/arduino/.../cft_remote.h and static_asserts
 *      every pair equal - magic, protocol version, header size, every
 *      opcode, every status, every format, every rounding attribute,
 *      every flag bit, the caps block's three lengths. A client that
 *      is not libcft has to write those numbers down somewhere; this
 *      is what stops them going stale, and it is the only reason the
 *      embedded header is allowed to have them.
 *
 *   2. THE ANSWER IS COMPARED WITH THE LIBRARY, NOT WITH ITSELF. The
 *      point of the whole exercise is that a board gets the same bits
 *      a host does. Here both are in the same process, so "the same
 *      bits" is a memcmp and not a story.
 *
 *   The extension is .cc and the whole file is inside #ifndef ARDUINO,
 *   twice over, because it lives in a directory an Arduino sketch
 *   compiles recursively: the Arduino builder collects .c, .cpp and .S
 *   and not .cc, and if that ever changes the guard still leaves an
 *   empty translation unit on a board.
 *
 * Build and run it with test/host_check.py, which owns the server's
 * lifecycle and stops it by its pid.
 */

#ifndef ARDUINO

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern "C" {
#include "cft.h"
#include "remote.h"
}

#include "../cft_remote.h"
#include "../cft_remote_config.h"
#include "../cft_remote_replay.h"

/* ================= the constants, held to their sources ============= */

/* remote.h */
static_assert(CFT_REMOTE_MAGIC == CFTR_MAGIC, "magic");
static_assert(cftr::PROTO_VERSION == (int)CFTR_PROTO_VERSION, "proto");
static_assert(cftr::HDR_BYTES == (int)CFTR_HDR_BYTES, "header size");
static_assert(cftr::DEFAULT_PORT == (int)CFTR_DEFAULT_PORT, "port");
static_assert(cftr::BACKEND_NAME == (int)CFTR_BACKEND_NAME, "backend name");
static_assert(cftr::CAPS_BYTES_V1 == (int)CFTR_CAPS_BYTES_V1, "caps v1");
static_assert(cftr::CAPS_BYTES_V2 == (int)CFTR_CAPS_BYTES_V2, "caps v2");
static_assert(cftr::CAPS_BYTES_V3 == (int)CFTR_CAPS_BYTES, "caps v3");
static_assert(cftr::KIND_REQUEST == (int)CFTR_KIND_REQUEST, "kind req");
static_assert(cftr::KIND_RESPONSE == (int)CFTR_KIND_RESPONSE, "kind resp");
static_assert(cftr::KIND_REFUSAL == (int)CFTR_KIND_REFUSAL, "kind refusal");
static_assert(cftr::OP_HELLO == (int)CFTR_OP_HELLO, "hello");
static_assert(cftr::OP_CAPS == (int)CFTR_OP_CAPS, "caps");
static_assert(cftr::OP_STATS == (int)CFTR_OP_STATS, "stats");
static_assert(cftr::OP_RUN == (int)CFTR_OP_RUN, "run");
static_assert(cftr::OP_REDUCE == (int)CFTR_OP_REDUCE, "reduce");
static_assert(cftr::OP_PROG_LOAD == (int)CFTR_OP_PROG_LOAD, "prog load");
static_assert(cftr::OP_PROG_RUN == (int)CFTR_OP_PROG_RUN, "prog run");
static_assert(cftr::OP_PROG_FREE == (int)CFTR_OP_PROG_FREE, "prog free");
static_assert(cftr::OP_PROG_RUN_BANK == (int)CFTR_OP_PROG_RUN_BANK, "bank");
static_assert(cftr::OP_PROG_RUN_EX == (int)CFTR_OP_PROG_RUN_EX, "ex");
static_assert(cftr::OP_BUF_ALLOC == (int)CFTR_OP_BUF_ALLOC, "buf alloc");
static_assert(cftr::OP_BUF_FREE == (int)CFTR_OP_BUF_FREE, "buf free");
static_assert(cftr::OP_BUF_WRITE == (int)CFTR_OP_BUF_WRITE, "buf write");
static_assert(cftr::OP_BUF_READ == (int)CFTR_OP_BUF_READ, "buf read");
static_assert(cftr::OP_FLAGS_LOWER == (int)CFTR_OP_FLAGS_LOWER, "lower");
static_assert(cftr::OP_FLAGS_RAISE == (int)CFTR_OP_FLAGS_RAISE, "raise");
static_assert(cftr::OP_FLAGS_TEST == (int)CFTR_OP_FLAGS_TEST, "test");
static_assert(cftr::OP_FLAGS_SAVE == (int)CFTR_OP_FLAGS_SAVE, "save");
static_assert(cftr::OP_FLAGS_RESTORE == (int)CFTR_OP_FLAGS_RESTORE, "restore");
static_assert(cftr::OP_FLAGS_TEST_SAVED == (int)CFTR_OP_FLAGS_TEST_SAVED, "ts");
static_assert(cftr::OP_BYE == (int)CFTR_OP_BYE, "bye");

/* cft.h: status */
static_assert(cftr::OK == (int)CFT_OK, "ok");
static_assert(cftr::ERR_INVALID_ARGUMENT == (int)CFT_ERR_INVALID_ARGUMENT, "s1");
static_assert(cftr::ERR_UNSUPPORTED == (int)CFT_ERR_UNSUPPORTED, "s2");
static_assert(cftr::ERR_NO_DEVICE == (int)CFT_ERR_NO_DEVICE, "s3");
static_assert(cftr::ERR_ARTIFACT == (int)CFT_ERR_ARTIFACT, "s4");
static_assert(cftr::ERR_BUS_FAULT == (int)CFT_ERR_BUS_FAULT, "s5");
static_assert(cftr::ERR_OUT_OF_MEMORY == (int)CFT_ERR_OUT_OF_MEMORY, "s6");
static_assert(cftr::ERR_TIMEOUT == (int)CFT_ERR_TIMEOUT, "s7");
static_assert(cftr::ERR_INTERNAL == (int)CFT_ERR_INTERNAL, "s8");

/* cft.h: formats, rounding, flags */
static_assert(cftr::FP32 == (int)CFT_FP32, "fp32");
static_assert(cftr::FP64 == (int)CFT_FP64, "fp64");
static_assert(cftr::FP128 == (int)CFT_FP128, "fp128");
static_assert(cftr::FP256 == (int)CFT_FP256, "fp256");
static_assert(cftr::RNE == (int)CFT_RNE, "rne");
static_assert(cftr::RTZ == (int)CFT_RTZ, "rtz");
static_assert(cftr::RDN == (int)CFT_RDN, "rdn");
static_assert(cftr::RUP == (int)CFT_RUP, "rup");
static_assert(cftr::RMM == (int)CFT_RMM, "rmm");
static_assert(cftr::FLAG_INVALID == (int)CFT_FLAG_INVALID, "f0");
static_assert(cftr::FLAG_DIVBYZERO == (int)CFT_FLAG_DIVBYZERO, "f1");
static_assert(cftr::FLAG_OVERFLOW == (int)CFT_FLAG_OVERFLOW, "f2");
static_assert(cftr::FLAG_UNDERFLOW == (int)CFT_FLAG_UNDERFLOW, "f3");
static_assert(cftr::FLAG_INEXACT == (int)CFT_FLAG_INEXACT, "f4");

/* cft.h: every opcode this client names */
static_assert(cftr::OP_FMA == (int)CFT_FMA, "o0");
static_assert(cftr::OP_ADD == (int)CFT_ADD, "o1");
static_assert(cftr::OP_SUB == (int)CFT_SUB, "o2");
static_assert(cftr::OP_MUL == (int)CFT_MUL, "o3");
static_assert(cftr::OP_ABS == (int)CFT_ABS, "o4");
static_assert(cftr::OP_NEG == (int)CFT_NEG, "o5");
static_assert(cftr::OP_COPYSIGN == (int)CFT_COPYSIGN, "o6");
static_assert(cftr::OP_MIN == (int)CFT_MIN, "o7");
static_assert(cftr::OP_MAX == (int)CFT_MAX, "o8");
static_assert(cftr::OP_MINNUM == (int)CFT_MINNUM, "o9");
static_assert(cftr::OP_MAXNUM == (int)CFT_MAXNUM, "o10");
static_assert(cftr::OP_SELECT == (int)CFT_SELECT, "o11");
static_assert(cftr::OP_CMPLT == (int)CFT_CMPLT, "o12");
static_assert(cftr::OP_CMPLE == (int)CFT_CMPLE, "o13");
static_assert(cftr::OP_CMPEQ == (int)CFT_CMPEQ, "o14");
static_assert(cftr::OP_IAND == (int)CFT_IAND, "o16");
static_assert(cftr::OP_IOR == (int)CFT_IOR, "o17");
static_assert(cftr::OP_IXOR == (int)CFT_IXOR, "o18");
static_assert(cftr::OP_IADD == (int)CFT_IADD, "o19");
static_assert(cftr::OP_ISUB == (int)CFT_ISUB, "o20");
static_assert(cftr::OP_ISHL == (int)CFT_ISHL, "o21");
static_assert(cftr::OP_ISHR == (int)CFT_ISHR, "o22");
static_assert(cftr::OP_ICMPLT == (int)CFT_ICMPLT, "o23");
static_assert(cftr::OP_SUM == (int)CFT_SUM, "o24");
static_assert(cftr::OP_DOT == (int)CFT_DOT, "o25");
static_assert(cftr::OP_RECIP_SEED == (int)CFT_RECIP_SEED, "o26");
static_assert(cftr::OP_RSQRT_SEED == (int)CFT_RSQRT_SEED, "o27");
static_assert(cftr::OP_SUMSQ == (int)CFT_SUMSQ, "o28");
static_assert(cftr::OP_SUMABS == (int)CFT_SUMABS, "o29");
static_assert(cftr::OP_IMUL == (int)CFT_IMUL, "o30");

/* ================= a byte pipe made of a socket ===================== *
 *
 * The transport this file gives the client is the same shape a
 * HardwareSerial gives it: writeBytes, readBytes, flushOut, and no
 * notion of a message. The socket underneath is the repository's own
 * shim from remote.h, so no platform code is written twice and the
 * thing being tested is the codec and not a winsock call.
 */
class SockTransport : public cftr::Transport {
public:
    SockTransport() : s_(CFTR_BAD_SOCK), corruptAt_(-1), seen_(0),
                      wrote_(0), read_(0) {}

    bool open(const char *host, const char *port)
    {
        if (cftr_sock_init())
            return false;
        s_ = cftr_sock_connect(host, port);
        if (s_ == CFTR_BAD_SOCK)
            return false;
        cftr_sock_timeout(s_, 30000);
        return true;
    }
    void close()
    {
        if (s_ != CFTR_BAD_SOCK)
            cftr_sock_close(s_);
        s_ = CFTR_BAD_SOCK;
    }

    /* The negative control: flip one bit of the n'th byte this
     * transport ever hands back, so that a frame the server sent
     * correctly arrives corrupt. */
    void corruptByte(long n) { corruptAt_ = n; seen_ = 0; }

    virtual int writeBytes(const uint8_t *p, uint16_t n)
    {
        wrote_ += n;
        return cftr_sock_send_all(s_, p, n);
    }
    virtual int readBytes(uint8_t *p, uint16_t n, uint32_t timeoutMs)
    {
        (void)timeoutMs;
        if (cftr_sock_recv_all(s_, p, n))
            return -1;
        read_ += n;
        for (uint16_t i = 0; i < n; i++, seen_++)
            if (corruptAt_ >= 0 && seen_ == corruptAt_)
                p[i] ^= 0x40;
        return 0;
    }
    virtual bool alive() { return s_ != CFTR_BAD_SOCK; }

    long wrote() const { return wrote_; }
    long read() const { return read_; }

private:
    cftr_sock s_;
    long      corruptAt_, seen_, wrote_, read_;
};

/* ================= the harness ====================================== */

static int g_pass, g_fail;

static void check(int ok, const char *what)
{
    printf("  %-4s %s\n", ok ? "ok" : "FAIL", what);
    if (ok) g_pass++; else g_fail++;
}

static void checkf(int ok, const char *fmt, ...)
{
    char buf[400];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    check(ok, buf);
}

/* A deterministic bit source, so a failure is reproducible: the
 * lowbias32 finaliser of docs/ATLAS.md over a counter. */
static uint32_t g_seed;
static uint32_t nextWord(void)
{
    uint32_t x = ++g_seed;
    x ^= x >> 16; x *= 0x7feb352dul;
    x ^= x >> 15; x *= 0x846ca68bul;
    x ^= x >> 16;
    return x;
}
static void fillRandom(uint8_t *p, size_t n)
{
    for (size_t i = 0; i < n; i++)
        p[i] = (uint8_t)nextWord();
}

/* Random bit patterns are not all finite numbers, and that is on
 * purpose - a NaN payload and a signalling NaN are exactly where two
 * implementations part company - but a run of pure noise at binary256
 * is almost all NaN. This biases the exponent field towards something
 * ordinary so the arithmetic paths are actually exercised, and leaves
 * one element in eight as raw noise. */
static void fillOperand(uint8_t *p, size_t esz, size_t n)
{
    for (size_t i = 0; i < n; i++) {
        uint8_t *e = p + i * esz;
        fillRandom(e, esz);
        if ((nextWord() & 7u) == 0)
            continue;
        /* clear one exponent bit so the pattern is a finite number */
        e[esz - 1] &= 0xBFu;
    }
}

/* Operands that answer out of a plain array but COUNT how often they
 * are asked, so the two-pass discipline is a measured fact and not a
 * claim in a comment. */
class CountingOperands : public cftr::Operands {
public:
    CountingOperands(uint8_t fmt, const void *a, const void *b, const void *c)
        : in_(fmt, a, b, c), calls_(0) {}
    virtual void element(uint8_t role, uint32_t index, uint8_t *out)
    {
        calls_++;
        in_.element(role, index, out);
    }
    uint8_t present() const { return in_.present(); }
    long calls() const { return calls_; }
private:
    cftr::RamOperands in_;
    long calls_;
};

/* ================= the checks ======================================== */

static cft_device *g_local;

static const char *fmtName(int f)
{
    return f == 0 ? "fp32" : f == 1 ? "fp64" : f == 2 ? "fp128" : "fp256";
}

static void checkCrc(void)
{
    uint8_t buf[600];
    int agree = 1;
    printf("\nCRC-32: the bitwise implementation against the library's table\n");
    check(cftr::crcSelfcheck() == 0,
          "the check value for \"123456789\" is 0xCBF43926");
    for (int t = 0; t < 512 && agree; t++) {
        uint16_t n = (uint16_t)(nextWord() % sizeof buf);
        fillRandom(buf, n);
        if (cftr::crc32(buf, n) != cftr_crc32(0, buf, n))
            agree = 0;
    }
    check(agree, "512 random buffers agree with cftr_crc32 from libcft.a");
}

static void checkCaps(cftr::Client &dev)
{
    cft_caps c;
    memset(&c, 0, sizeof c);
    c.struct_size = sizeof c;
    cft_get_caps(g_local, &c);
    printf("\nHELLO: the caps block against the local software device\n");
    checkf(dev.formatMask() == c.format_mask,
           "format_mask 0x%x", (unsigned)dev.formatMask());
    checkf(dev.tiles() == c.tiles, "tiles %u", (unsigned)dev.tiles());
    checkf(dev.serverAbi() == cft_abi_version(),
           "the server's ABI word is 0x%08x (%u.%u), the same libcft this "
           "process links", (unsigned)dev.serverAbi(),
           (unsigned)(dev.serverAbi() >> 16),
           (unsigned)(dev.serverAbi() & 0xFFFFu));
    checkf(dev.flagsReadable() == (c.flags_readable != 0),
           "flags_readable %d", (int)dev.flagsReadable());
#if CFT_REMOTE_BACKEND_NAME_BYTES > 0
    checkf(strcmp(dev.backend(), c.backend) == 0,
           "backend \"%s\"", dev.backend());
#endif
    checkf(dev.capsBytes() >= cftr::CAPS_BYTES_V1,
           "the block is %u bytes, at least the %d this protocol has always "
           "carried", (unsigned)dev.capsBytes(), (int)cftr::CAPS_BYTES_V1);
#if CFT_REMOTE_KEEP_SEQ_CAPS
    checkf(dev.maxDeposits() == c.max_deposits &&
           dev.maxInsns() == c.max_insns &&
           dev.maxConsts() == c.max_consts &&
           dev.seqFeatures() == c.seq_features,
           "the four sequencer capacities match (%u, %u, %u, 0x%x)",
           (unsigned)dev.maxDeposits(), (unsigned)dev.maxInsns(),
           (unsigned)dev.maxConsts(), (unsigned)dev.seqFeatures());
#endif
}

/* One RUN through the embedded client against the same call through
 * libcft, bit for bit, flags and all. */
static int runPair(cftr::Client &dev, int op, int fmt, int rnd,
                   int useA, int useB, int useC, uint32_t n)
{
    size_t esz = cft_format_size((cft_format)fmt);
    uint8_t *a = useA ? (uint8_t *)malloc(n * esz) : 0;
    uint8_t *b = useB ? (uint8_t *)malloc(n * esz) : 0;
    uint8_t *c = useC ? (uint8_t *)malloc(n * esz) : 0;
    uint8_t *dr = (uint8_t *)malloc(n * esz);
    uint8_t *dl = (uint8_t *)malloc(n * esz);
    uint32_t fr = 0, br = 0, fl = 0, bl = 0;
    int ok;

    if (a) fillOperand(a, esz, n);
    if (b) fillOperand(b, esz, n);
    if (c) fillOperand(c, esz, n);
    memset(dr, 0xA5, n * esz);
    memset(dl, 0x5A, n * esz);

    CountingOperands in((uint8_t)fmt, a, b, c);
    cftr::RamResults out((uint8_t)fmt, dr);
    int str = dev.run((uint8_t)op, (uint8_t)fmt, (uint8_t)rnd, in.present(),
                      n, in, out, &fr, &br);
    cft_status stl = cft_run(g_local, (cft_op)op, (cft_format)fmt,
                             (cft_round)rnd, a, b, c, dl, n, &fl, &bl);

    ok = (str == (int)stl) && (str != 0 || (memcmp(dr, dl, n * esz) == 0 &&
                                            fr == fl && br == bl));
    /* the two-pass discipline: every present operand asked for twice a
     * frame, and never a third time */
    {
        uint8_t np = (uint8_t)((useA ? 1 : 0) + (useB ? 1 : 0) + (useC ? 1 : 0));
        long want = 2L * np * (long)n;
        if (in.calls() != want)
            ok = 0;
    }
    free(a); free(b); free(c); free(dr); free(dl);
    return ok;
}

static int reducePair(cftr::Client &dev, int op, int fmt, int rnd,
                      int useB, uint32_t n)
{
    size_t esz = cft_format_size((cft_format)fmt);
    uint8_t *a = (uint8_t *)malloc(n * esz);
    uint8_t *b = useB ? (uint8_t *)malloc(n * esz) : 0;
    uint8_t dr[32], dl[32];
    uint32_t fr = 0, br = 0, fl = 0, bl = 0;
    int ok;

    fillOperand(a, esz, n);
    if (b) fillOperand(b, esz, n);
    memset(dr, 0xA5, sizeof dr);
    memset(dl, 0x5A, sizeof dl);

    cftr::RamOperands in((uint8_t)fmt, a, b, 0);
    int str = dev.reduce((uint8_t)op, (uint8_t)fmt, (uint8_t)rnd,
                         in.present(), n, in, dr, &fr, &br);
    cft_status stl = cft_reduce(g_local, (cft_op)op, (cft_format)fmt,
                                (cft_round)rnd, a, b, dl, n, &fl, &bl);
    ok = (str == (int)stl) && (str != 0 || (memcmp(dr, dl, esz) == 0 &&
                                            fr == fl && br == bl));
    free(a); free(b);
    return ok;
}

int main(int argc, char **argv)
{
    const char *host = "127.0.0.1";
    const char *port = "7754";
    SockTransport io;
    cftr::Client dev;
    uint32_t abi = cft_abi_version();

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--host") && i + 1 < argc) host = argv[++i];
        else if (!strcmp(argv[i], "--port") && i + 1 < argc) port = argv[++i];
        else { fprintf(stderr, "usage: host_check [--host H] [--port P]\n");
               return 2; }
    }
    g_seed = 0x9E3779B9ul;

    printf("cft embedded remote client - host-side proof\n");
    printf("  server        %s:%s\n", host, port);
    printf("  abi claimed   0x%08x (%u.%u)\n", (unsigned)abi,
           (unsigned)(abi >> 16), (unsigned)(abi & 0xFFFFu));
    printf("  sizeof(cftr::Client)      %u bytes on this compiler\n",
           (unsigned)sizeof(cftr::Client));
    printf("  CFT_REMOTE_CHUNK_BYTES    %lu\n",
           (unsigned long)CFT_REMOTE_CHUNK_BYTES);
    printf("  CFT_REMOTE_MAX_ELEM_BYTES %lu\n",
           (unsigned long)CFT_REMOTE_MAX_ELEM_BYTES);
    printf("  err %lu, backend name %lu, seq caps %d\n",
           (unsigned long)CFT_REMOTE_ERR_BYTES,
           (unsigned long)CFT_REMOTE_BACKEND_NAME_BYTES,
           (int)CFT_REMOTE_KEEP_SEQ_CAPS);

    if (cft_open(NULL, 0, &g_local) != CFT_OK) {
        fprintf(stderr, "host_check: cannot open the local software device\n");
        return 2;
    }

    checkCrc();

    printf("\nthe chunk arithmetic\n");
    for (int f = 0; f < 4; f++) {
        uint32_t k1 = cftr::Client::chunkElements((uint8_t)f, 1);
        uint32_t k3 = cftr::Client::chunkElements((uint8_t)f, 3);
        size_t esz = cft_format_size((cft_format)f);
        checkf(k1 == (CFT_REMOTE_CHUNK_BYTES / (2 * esz)) &&
               k3 == (CFT_REMOTE_CHUNK_BYTES / (4 * esz)),
               "%-5s one operand %u elements a frame, three operands %u",
               fmtName(f), (unsigned)k1, (unsigned)k3);
    }

    if (!io.open(host, port)) {
        fprintf(stderr, "host_check: cannot reach %s:%s - %s\n", host, port,
                cftr_sock_error());
        return 2;
    }
    if (dev.begin(io, abi) != cftr::OK) {
        fprintf(stderr, "host_check: HELLO failed: status %d, %s\n",
                dev.status(), dev.message());
        return 2;
    }
    checkCaps(dev);

    /* ---- RUN, every format, one element and many ------------------ */
    printf("\nRUN: the embedded client against libcft, bit for bit\n");
    {
        struct { int op; int a, b, c; const char *name; } cases[] = {
            { CFT_FMA,      1, 1, 1, "fma" },
            { CFT_ADD,      1, 0, 1, "add" },
            { CFT_SUB,      1, 0, 1, "sub" },
            { CFT_MUL,      1, 1, 0, "mul" },
            { CFT_ABS,      1, 0, 0, "abs" },
            { CFT_NEG,      1, 0, 0, "neg" },
            { CFT_COPYSIGN, 1, 1, 0, "copysign" },
            { CFT_MINNUM,   1, 1, 0, "minnum" },
            { CFT_MAXNUM,   1, 1, 0, "maxnum" },
            { CFT_SELECT,   1, 1, 1, "select" },
            { CFT_CMPLT,    1, 1, 0, "cmplt" },
            { CFT_IXOR,     1, 1, 0, "ixor" },
            { CFT_IADD,     1, 1, 0, "iadd" },
            { CFT_IMUL,     1, 1, 0, "imul" },
            { CFT_RECIP_SEED, 1, 0, 0, "recip_seed" },
            { CFT_RSQRT_SEED, 1, 0, 0, "rsqrt_seed" }
        };
        for (int f = 0; f < 4; f++) {
            int all = 1;
            for (unsigned k = 0; k < sizeof cases / sizeof cases[0]; k++)
                if (!runPair(dev, cases[k].op, f, CFT_RNE, cases[k].a,
                             cases[k].b, cases[k].c, 1))
                    { all = 0; printf("       (%s)\n", cases[k].name); }
            checkf(all, "%-5s %u opcodes, one element each, identical",
                   fmtName(f), (unsigned)(sizeof cases / sizeof cases[0]));
        }
    }

    printf("\nRUN: every rounding attribute\n");
    for (int f = 0; f < 4; f++) {
        int all = 1;
        for (int r = 0; r < 5; r++)
            if (!runPair(dev, CFT_FMA, f, r, 1, 1, 1, 7))
                all = 0;
        checkf(all, "%-5s fma over 7 elements at rne/rtz/rdn/rup/rmm",
               fmtName(f));
    }

    /* ---- chunking: more elements than one frame carries ------------ */
    printf("\nRUN: chunking - a run longer than one frame\n");
    for (int f = 0; f < 4; f++) {
        uint32_t k = cftr::Client::chunkElements((uint8_t)f, 3);
        uint32_t n = k * 3 + 1;              /* four frames, last one short */
        checkf(runPair(dev, CFT_FMA, f, CFT_RNE, 1, 1, 1, n),
               "%-5s fma over %u elements in %u frames of at most %u",
               fmtName(f), (unsigned)n, (unsigned)((n + k - 1) / k),
               (unsigned)k);
    }

    /* ---- REDUCE ---------------------------------------------------- */
    printf("\nREDUCE: n elements in, one element out\n");
    for (int f = 0; f < 4; f++) {
        int all = 1;
        all &= reducePair(dev, CFT_SUM, f, CFT_RNE, 0, 33);
        all &= reducePair(dev, CFT_DOT, f, CFT_RNE, 1, 33);
        all &= reducePair(dev, CFT_SUMSQ, f, CFT_RNE, 0, 33);
        all &= reducePair(dev, CFT_SUMABS, f, CFT_RNE, 0, 33);
        checkf(all, "%-5s sum, dot, sumsq, sumabs over 33 elements",
               fmtName(f));
    }
    printf("\nREDUCE: a reduction wider than this board could ever store\n");
    {
        /* 4096 binary256 elements is 128 kB of operand streamed out of
         * a generator through a client whose whole RAM budget is under
         * two hundred bytes - the response is eight bytes and one
         * element, so nothing about it is chunked or held. */
        const uint32_t N = 4096;
        size_t esz = 32;
        uint8_t *a = (uint8_t *)malloc(N * esz);
        uint8_t dr[32], dl[32];
        uint32_t fr, br, fl, bl;
        fillOperand(a, esz, N);
        cftr::RamOperands in(cftr::FP256, a, 0, 0);
        int str = dev.reduce(cftr::OP_SUM, cftr::FP256, cftr::RNE, 1, N,
                             in, dr, &fr, &br);
        cft_status stl = cft_reduce(g_local, CFT_SUM, CFT_FP256, CFT_RNE,
                                    a, NULL, dl, N, &fl, &bl);
        checkf(str == (int)stl && memcmp(dr, dl, esz) == 0 && fr == fl,
               "binary256 sum over %u elements, %u kB streamed in one frame",
               (unsigned)N, (unsigned)(N * esz / 1024));
        free(a);
    }

    /* ---- the sweep RemoteReplay runs on the board ------------------- */
    printf("\nthe RemoteReplay sweep: %d generated cases, one number back\n",
           (int)cftr::replay::CASES);
    {
        const int fmt = cftr::replay::FMT;
        const size_t esz = cft_format_size((cft_format)fmt);
        cftr::replay::Operands in((uint8_t)fmt);
        cftr::replay::Digest dg((uint8_t)fmt);
        uint32_t fl = 0, bs = 0, lf = 0;
        uint8_t a[32], b[32], c[32], d[32];
        uint32_t running = cftr::crcBegin();

        int st = dev.run((uint8_t)cftr::replay::OP, (uint8_t)fmt,
                         (uint8_t)cftr::replay::RND,
                         cftr::replay::Operands::present(),
                         (uint32_t)cftr::replay::CASES, in, dg, &fl, &bs);
        for (uint32_t i = 0; i < (uint32_t)cftr::replay::CASES; i++) {
            uint32_t f = 0;
            cftr::replay::operand(0, i, (uint8_t)esz, a);
            cftr::replay::operand(1, i, (uint8_t)esz, b);
            cftr::replay::operand(2, i, (uint8_t)esz, c);
            cft_run(g_local, (cft_op)cftr::replay::OP, (cft_format)fmt,
                    (cft_round)cftr::replay::RND, a, b, c, d, 1, &f, NULL);
            lf |= f;
            running = cftr::crcUpdate(running, d, (uint16_t)esz);
        }
        uint32_t want = cftr::crcFinal(running);
        checkf(st == cftr::OK && dg.count() == (uint32_t)cftr::replay::CASES &&
               dg.value() == want,
               "the board's digest would be 0x%08lX, and libcft agrees "
               "(flags 0x%02x)", (unsigned long)want, (unsigned)fl);
        checkf(fl == lf, "the flag union matches too (0x%02x)", (unsigned)fl);
        checkf(want == (uint32_t)CFT_REMOTE_REPLAY_DIGEST,
               "and it is the constant cft_remote_replay.h carries "
               "(0x%08lX)", (unsigned long)CFT_REMOTE_REPLAY_DIGEST);
    }

    /* ---- the status word ------------------------------------------- */
    printf("\nthe status word, which libcft's own client never asks for\n");
    {
        /* cft_test_flags and cft_test_saved_flags are PREDICATES - 1 or
         * 0, never an intersection - and cft_save_all_flags is the word
         * itself. The distinction is cft.h's and this holds the client
         * to it rather than to a guess. */
        const uint32_t RAISED = (uint32_t)(CFT_FLAG_INEXACT | CFT_FLAG_OVERFLOW);
        uint32_t saved = 0xFFFFFFFFul, t = 0xFFFFFFFFul, w = 0xFFFFFFFFul;
        int ok;

        ok = dev.flagsLower(CFT_FLAGS_ALL) == cftr::OK;
        ok &= dev.flagsTest(CFT_FLAGS_ALL, &t) == cftr::OK && t == 0;
        check(ok, "lower(all) then test(all) is 0 - a clean word");

        ok = dev.flagsRaise(RAISED) == cftr::OK;
        ok &= dev.flagsTest(CFT_FLAGS_ALL, &t) == cftr::OK && t == 1;
        ok &= dev.flagsTest(CFT_FLAG_OVERFLOW, &t) == cftr::OK && t == 1;
        ok &= dev.flagsTest(CFT_FLAG_INVALID, &t) == cftr::OK && t == 0;
        check(ok, "raise(inexact|overflow): test answers the predicate, "
                  "one flag at a time");

        ok = dev.flagsSave(&saved) == cftr::OK && saved == RAISED;
        checkf(ok, "save gives back the word itself, 0x%02x",
               (unsigned)saved);

        ok = dev.flagsLower(CFT_FLAGS_ALL) == cftr::OK;
        ok &= dev.flagsTestSaved(saved, CFT_FLAG_OVERFLOW, &t) == cftr::OK &&
              t == 1;
        ok &= dev.flagsTestSaved(saved, CFT_FLAG_INVALID, &t) == cftr::OK &&
              t == 0;
        check(ok, "test_saved reads the saved word and not the device's");

        ok = dev.flagsRestore(saved, CFT_FLAGS_ALL) == cftr::OK;
        ok &= dev.flagsSave(&w) == cftr::OK && w == saved;
        ok &= dev.flagsLower(CFT_FLAGS_ALL) == cftr::OK;
        check(ok, "restore(saved, all) puts the word back exactly");
    }

    /* ---- the operation's own failure, on a connection that lives ---- */
    printf("\na failed operation is not a failed connection\n");
    {
        uint8_t a[32], d[32];
        fillRandom(a, sizeof a);
        /* CFT_SUM is a reduction: cft_run refuses it, and the refusal
         * is the OPERATION's, carried in a kind-1 response whose status
         * is not OK. The connection must survive it. */
        int st = dev.runOne(cftr::OP_SUM, cftr::FP64, cftr::RNE, a, 0, 0, d);
        checkf(st == cftr::ERR_INVALID_ARGUMENT && !dev.poisoned(),
               "a reduction opcode through RUN is status %d and the handle "
               "is not poisoned", st);
#if CFT_REMOTE_ERR_BYTES > 0
        checkf(dev.message()[0] != '\0',
               "and it carries the server's own words: \"%.60s\"",
               dev.message());
#endif
        check(runPair(dev, CFT_FMA, CFT_FP64, CFT_RNE, 1, 1, 1, 4),
              "the very next RUN on the same connection is correct");
    }

    /* ---- a format the client refuses locally ----------------------- */
    {
        uint8_t a[32], d[32];
        memset(a, 0, sizeof a);
        int st = dev.runOne(cftr::OP_FMA, 7, cftr::RNE, a, a, a, d);
        checkf(st == cftr::ERR_INVALID_ARGUMENT && !dev.poisoned(),
               "an unknown format is refused here, before a frame is sent");
    }

    dev.end();
    io.close();

    /* ---- the negative controls: a corrupted frame, a wrong ABI ------ */
    printf("\nthe negative controls\n");
    {
        SockTransport io2;
        cftr::Client dev2;
        if (!io2.open(host, port)) { check(0, "reconnect"); }
        else {
            /* Byte 40 is inside the caps block of the HELLO response:
             * the header is 32 bytes, so this is payload byte 8. */
            io2.corruptByte(40);
            int st = dev2.begin(io2, abi);
            checkf(st == cftr::ERR_INTERNAL && dev2.reason() == cftr::R_CRC,
                   "one flipped bit in a HELLO response is refused as a crc "
                   "failure (status %d, reason %d)", st, (int)dev2.reason());
            check(dev2.poisoned(), "and the handle is poisoned");
            uint8_t a[8], d[8];
            checkf(dev2.runOne(cftr::OP_FMA, cftr::FP64, cftr::RNE, a, a, a, d)
                       == cftr::ERR_INTERNAL &&
                   dev2.reason() == cftr::R_POISONED,
                   "every later call answers without touching the pipe");
            io2.close();
        }
    }
    {
        SockTransport io3;
        cftr::Client dev3;
        if (!io3.open(host, port)) { check(0, "reconnect"); }
        else {
            int st = dev3.begin(io3, abi + 1);
            checkf(st == cftr::ERR_UNSUPPORTED && dev3.reason() == cftr::R_ABI,
                   "an ABI one minor step out is refused, not warned about "
                   "(status %d, reason %d)", st, (int)dev3.reason());
            checkf(dev3.serverAbi() == abi,
                   "and the client kept what the server said it was: "
                   "0x%08x against the 0x%08x it claimed",
                   (unsigned)dev3.serverAbi(), (unsigned)(abi + 1));
            io3.close();
        }
    }
    {
        /* Not a cft frame at all: a stream that never had the magic. A
         * board sharing one UART with a print statement is exactly how
         * this happens, which is why the bridge has --framed. */
        SockTransport io4;
        cftr::Client dev4;
        if (io4.open(host, port)) {
            const uint8_t junk[8] = { 'h', 'e', 'l', 'l', 'o', '\r', '\n', 0 };
            io4.writeBytes(junk, sizeof junk);
            int st = dev4.begin(io4, abi);
            checkf(st != cftr::OK,
                   "a line of text before the first frame ends the "
                   "connection (status %d, reason %d)", st,
                   (int)dev4.reason());
            io4.close();
        }
    }

    cft_close(g_local);
    printf("\n%d checks passed, %d failed\n", g_pass, g_fail);
    return g_fail ? 1 : 0;
}

#endif /* !ARDUINO */
