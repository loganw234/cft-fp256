/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * remote-test - the remote backend's protocol, held to docs/REMOTE.md.
 *
 *     remote-test cft://host:port [-n N] [--bench] [--crc]
 *
 * What device-test does not do, this does: it speaks the frames
 * badly on purpose and checks that the server REFUSES - a wrong ABI,
 * a corrupted crc, a bad magic, an oversize length, a request before
 * HELLO, a payload whose length disagrees with its n - and that a
 * well-formed request naming a bad handle or an unknown opcode is
 * answered with a status and the connection continues. It exercises
 * the operations libcft's own client never issues (the buffers, the
 * status word, STATS), and holds a sample of cft_run, cft_reduce and
 * the composed operations against the software backend, both routes.
 *
 * --bench: the composed operations' round trips, read from the
 * server's STATS counters before and after each call rather than
 * inferred, and the raw cost of a round trip. Run twice by the
 * harness, with CFT_DIVSQRT_SEQ=0 and =1, for the two routes.
 *
 * --crc: print the CRC-32 of two byte strings, for tests/remote_check.py
 * to hold against Python's zlib.crc32 - an implementation that shares
 * no code with this one.
 *
 * Exit status 0 only if every check passed.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "cft.h"
#include "remote.h"

static int failures, checks;

#define CHECK(cond, ...) do { checks++; if (!(cond)) { failures++; \
    printf("  FAIL: "); printf(__VA_ARGS__); printf("\n"); } } while (0)

/* A deterministic operand stream: a 64-bit LCG (the constants are
 * Knuth's MMIX ones, in hex as he gives them). Bits, not values -
 * every encoding, NaNs and infinities included, is a legitimate
 * operand for a bit-identity check. */
static uint64_t g_seed = 0x9E3779B97F4A7C15ull;
static uint64_t rnd64(void)
{
    g_seed = g_seed * 6364136223846793005ull + 1442695040888963407ull;
    return g_seed ^ (g_seed >> 29);
}
static void fill(uint8_t *p, size_t bytes)
{
    size_t i;
    for (i = 0; i < bytes; i++)
        p[i] = (uint8_t)(rnd64() >> 24);
}
/* Mostly-normal values: exponent within a few binades of the bias,
 * so div and sqrt do real work rather than hitting the special
 * tables every time. */
static void fill_normal(uint8_t *p, size_t n, int fmt)
{
    static const int exp_w[4] = { 8, 11, 15, 19 };
    const size_t esz = cft_format_size((cft_format)fmt);
    size_t i;
    for (i = 0; i < n; i++) {
        uint8_t *e = p + i * esz;
        int bias = (1 << (exp_w[fmt] - 1)) - 1;
        int ex = bias + (int)(rnd64() % 17) - 8;
        int top_bits = exp_w[fmt] + 1;          /* sign + exponent */
        int man_bits = (int)esz * 8 - top_bits;
        uint64_t top = ((uint64_t)(rnd64() & 1u) << exp_w[fmt]) | (uint64_t)ex;
        int b;
        fill(e, esz);
        /* write the top field bit by bit, MSB of the element last */
        for (b = 0; b < top_bits; b++) {
            int bit = man_bits + b;
            if ((top >> b) & 1u)
                e[bit / 8] |= (uint8_t)(1u << (bit % 8));
            else
                e[bit / 8] &= (uint8_t)~(1u << (bit % 8));
        }
    }
}

static double now_s(void)
{
    return (double)clock() / (double)CLOCKS_PER_SEC;
}

/* ---- STATS ------------------------------------------------------------ */

typedef struct { uint64_t requests, bytes_in, bytes_out; uint64_t op[256]; } stats;

static int get_stats(cft_device *dev, void *hw, stats *S)
{
    uint8_t *resp = NULL;
    size_t len = 0, i;
    int status;
    uint32_t entries;
    memset(S, 0, sizeof *S);
    (void)dev;
    if (cftr_request(hw, CFTR_OP_STATS, NULL, 0, &status, &resp, &len))
        return -1;
    if (status != CFT_OK || len < 32)
        return -1;
    S->requests  = cftr_get64(resp + 0);
    S->bytes_in  = cftr_get64(resp + 8);
    S->bytes_out = cftr_get64(resp + 16);
    entries = cftr_get32(resp + 24);
    for (i = 0; i < entries && 32 + i * 16 + 16 <= len; i++) {
        uint32_t op = cftr_get32(resp + 32 + i * 16);
        if (op < 256)
            S->op[op] = cftr_get64(resp + 32 + i * 16 + 8);
    }
    free(resp);
    return 0;
}

/* The backend handle behind a remote cft_device, through the same
 * internal question program.c asks. */
void *cft_device_backend(const struct cft_device *dev);

/* ---- raw frames on a fresh connection ------------------------------- */

static int parse_url(const char *url, char *host, char *port)
{
    const char *p = url + 6, *c = strrchr(p, ':');
    if (strncmp(url, "cft://", 6) || !c)
        return -1;
    memcpy(host, p, (size_t)(c - p));
    host[c - p] = '\0';
    strcpy(port, c + 1);
    return 0;
}

/* Send one raw frame (optionally with a hand-edited header) and report
 * what came back: 2 for a refusal, 1 for a response, 0 for EOF, -1 for
 * a transport failure. *status is the header's status field. */
static int raw_exchange(const char *host, const char *port,
                        const uint8_t *hdr32, const void *payload,
                        size_t len, int *status, char *msg, size_t msg_size)
{
    cftr_sock s = cftr_sock_connect(host, port);
    cftr_hdr h;
    uint8_t *p = NULL;
    char why[256];
    int rc;
    *status = -1;
    msg[0] = '\0';
    if (s == CFTR_BAD_SOCK)
        return -1;
    cftr_sock_timeout(s, 10000);
    if (cftr_sock_send_all(s, hdr32, 32) ||
        (len && cftr_sock_send_all(s, payload, len))) {
        cftr_sock_close(s);
        return -1;
    }
    rc = cftr_recv_frame(s, &h, &p, cft_abi_version(), why, sizeof why);
    if (rc == 1) {
        cftr_sock_close(s);
        return 0;
    }
    if (rc) {
        snprintf(msg, msg_size, "%s", why);
        cftr_sock_close(s);
        return -1;
    }
    *status = h.status;
    if (p)
        snprintf(msg, msg_size, "%.*s", (int)h.length, (const char *)p);
    free(p);
    /* After a refusal the server closes: confirm with a read. */
    if (h.kind == CFTR_KIND_REFUSAL) {
        uint8_t byte;
        int eof = cftr_sock_recv_all(s, &byte, 1);
        cftr_sock_close(s);
        return eof == 1 ? 2 : 3;      /* 3 = refused but did NOT close */
    }
    cftr_sock_close(s);
    return 1;
}

static void hello_header(uint8_t out[32], uint32_t abi, uint16_t op,
                         uint32_t length, const void *payload)
{
    cftr_hdr h;
    uint32_t crc;
    memset(&h, 0, sizeof h);
    h.proto = CFTR_PROTO_VERSION;
    h.kind = CFTR_KIND_REQUEST;
    h.abi = abi;
    h.id = 1;
    h.op = op;
    h.length = length;
    cftr_hdr_pack(&h, out);
    crc = cftr_crc32(0, out, 32);
    if (length)
        crc = cftr_crc32(crc, payload, length);
    cftr_put32(out + 24, crc);
}

static void refusal_tests(const char *url)
{
    char host[200], port[16], msg[256];
    uint8_t hdr[32], payload[128];
    int rc, status;

    if (parse_url(url, host, port)) {
        CHECK(0, "cannot parse %s", url);
        return;
    }
    printf("refusals, each on a fresh connection:\n");

    /* 1. an ABI one minor version away */
    hello_header(hdr, cft_abi_version() + 1, CFTR_OP_HELLO, 0, NULL);
    rc = raw_exchange(host, port, hdr, NULL, 0, &status, msg, sizeof msg);
    CHECK(rc == 2 && status == CFT_ERR_UNSUPPORTED,
          "ABI mismatch: rc %d status %d (%s)", rc, status, msg);
    printf("  ABI mismatch      -> %s, %s\n",
           rc == 2 ? "refused and closed" : "NOT refused",
           status >= 0 ? cft_strerror((cft_status)status) : "-");

    /* 2. a corrupted crc: one bit of the payload flipped after signing */
    memset(payload, 0, 8);
    payload[0] = 0x55;
    hello_header(hdr, cft_abi_version(), CFTR_OP_BUF_ALLOC, 8, payload);
    payload[0] ^= 0x01;
    rc = raw_exchange(host, port, hdr, payload, 8, &status, msg, sizeof msg);
    CHECK(rc == 2 && status == CFT_ERR_INTERNAL,
          "corrupted crc: rc %d status %d (%s)", rc, status, msg);
    printf("  corrupted crc     -> %s (%s)\n",
           rc == 2 ? "refused and closed" : "NOT refused", msg);

    /* 3. a wrong magic */
    hello_header(hdr, cft_abi_version(), CFTR_OP_HELLO, 0, NULL);
    hdr[0] = 'X';
    rc = raw_exchange(host, port, hdr, NULL, 0, &status, msg, sizeof msg);
    CHECK(rc == 2 && status == CFT_ERR_INTERNAL,
          "bad magic: rc %d status %d (%s)", rc, status, msg);
    printf("  bad magic         -> %s\n",
           rc == 2 ? "refused and closed" : "NOT refused");

    /* 4. a length past the cap, crc correct for the header it claims */
    {
        cftr_hdr h;
        uint32_t crc;
        memset(&h, 0, sizeof h);
        h.proto = CFTR_PROTO_VERSION;
        h.kind = CFTR_KIND_REQUEST;
        h.abi = cft_abi_version();
        h.id = 1;
        h.op = CFTR_OP_HELLO;
        h.length = CFTR_MAX_PAYLOAD + 1u;
        cftr_hdr_pack(&h, hdr);
        crc = cftr_crc32(0, hdr, 32);
        cftr_put32(hdr + 24, crc);
    }
    rc = raw_exchange(host, port, hdr, NULL, 0, &status, msg, sizeof msg);
    CHECK(rc == 2 && status == CFT_ERR_INTERNAL,
          "oversize length: rc %d status %d (%s)", rc, status, msg);
    printf("  oversize length   -> %s\n",
           rc == 2 ? "refused before reading it" : "NOT refused");

    /* 5. a RUN before HELLO, well formed (its 24 fixed bytes, n = 0) */
    memset(payload, 0, 24);
    hello_header(hdr, cft_abi_version(), CFTR_OP_RUN, 24, payload);
    rc = raw_exchange(host, port, hdr, payload, 24, &status, msg, sizeof msg);
    CHECK(rc == 2 && status == CFT_ERR_INVALID_ARGUMENT,
          "RUN before HELLO: rc %d status %d (%s)", rc, status, msg);
    printf("  RUN before HELLO  -> %s\n",
           rc == 2 ? "refused and closed" : "NOT refused");

    /* 6. a wrong protocol version */
    hello_header(hdr, cft_abi_version(), CFTR_OP_HELLO, 0, NULL);
    cftr_put16(hdr + 4, CFTR_PROTO_VERSION + 1);
    cftr_put32(hdr + 24, 0);
    cftr_put32(hdr + 24, cftr_crc32(0, hdr, 32));
    rc = raw_exchange(host, port, hdr, NULL, 0, &status, msg, sizeof msg);
    CHECK(rc == 2 && status == CFT_ERR_UNSUPPORTED,
          "protocol version: rc %d status %d (%s)", rc, status, msg);
    printf("  protocol version  -> %s\n",
           rc == 2 ? "refused and closed" : "NOT refused");

    /* 7. a truncated frame: a header promising 100 bytes, then EOF.
     * Nothing can come back - the sender closed - so what is checked
     * is that the server is still there for the next connection. */
    {
        cftr_sock s = cftr_sock_connect(host, port);
        if (s != CFTR_BAD_SOCK) {
            memset(payload, 0, sizeof payload);
            hello_header(hdr, cft_abi_version(), CFTR_OP_PROG_LOAD, 100, payload);
            cftr_sock_send_all(s, hdr, 32);
            cftr_sock_send_all(s, payload, 10);
            cftr_sock_close(s);
        }
    }
    hello_header(hdr, cft_abi_version(), CFTR_OP_HELLO, 0, NULL);
    rc = raw_exchange(host, port, hdr, NULL, 0, &status, msg, sizeof msg);
    CHECK(rc == 1 && status == CFT_OK,
          "after a truncated frame the server still answers: rc %d "
          "status %d", rc, status);
    printf("  truncated frame   -> dropped; the next connection is served\n");

    /* 8. a RUN whose ANSWER cannot fit a frame.
     *
     * The operand mask names no operand, which is legal for an
     * unassigned opcode (cft_sf_op_operands gives it none, and the
     * contract gives it a defined canonical-qNaN result), so the
     * payload's length says nothing about n and twenty-four bytes ask
     * for 2^28 fp32 results. That is one gigabyte, and the answer
     * carries eight bytes of flags and status in front of it, so it is
     * eight bytes past what cftr_send_frame will send.
     *
     * Until 2026-09-07 the server did the whole run and the gigabyte
     * allocation first and discovered that afterwards, when the send
     * failed - work that could not have been delivered whatever
     * happened. Found by host/fuzz. This has to come back promptly as
     * a refusal; if it does not, the test hangs for as long as 2^28
     * fp256-path elements take, which is itself the finding. */
    {
        cftr_sock s = cftr_sock_connect(host, port);
        CHECK(s != CFTR_BAD_SOCK, "connecting for the oversize-answer test");
        if (s != CFTR_BAD_SOCK) {
            cftr_hdr h;
            uint8_t *p = NULL;
            char why[256];
            cftr_sock_timeout(s, 20000);
            hello_header(hdr, cft_abi_version(), CFTR_OP_HELLO, 0, NULL);
            cftr_sock_send_all(s, hdr, 32);
            rc = cftr_recv_frame(s, &h, &p, cft_abi_version(), why,
                                 sizeof why);
            free(p);
            p = NULL;
            CHECK(rc == 0 && h.status == CFT_OK,
                  "HELLO before the oversize-answer test: rc %d", rc);
            memset(payload, 0, 24);
            cftr_put32(payload + 0, 165);      /* an unassigned opcode */
            cftr_put32(payload + 4, 0);        /* fp32 */
            cftr_put32(payload + 8, 0);        /* roundTiesToEven */
            cftr_put32(payload + 12, 0);       /* no operands on the wire */
            cftr_put64(payload + 16, (uint64_t)CFTR_MAX_PAYLOAD / 4u);
            hello_header(hdr, cft_abi_version(), CFTR_OP_RUN, 24, payload);
            cftr_put32(hdr + 12, 2);           /* id 2, the second request */
            cftr_put32(hdr + 24, 0);
            {
                uint32_t crc = cftr_crc32(0, hdr, 32);
                cftr_put32(hdr + 24, cftr_crc32(crc, payload, 24));
            }
            cftr_sock_send_all(s, hdr, 32);
            cftr_sock_send_all(s, payload, 24);
            rc = cftr_recv_frame(s, &h, &p, cft_abi_version(), why,
                                 sizeof why);
            msg[0] = '\0';
            if (rc == 0 && p)
                snprintf(msg, sizeof msg, "%.*s", (int)h.length,
                         (const char *)p);
            CHECK(rc == 0 && h.kind == CFTR_KIND_REFUSAL,
                  "a RUN whose answer is past the frame cap: rc %d kind %u "
                  "(%s)", rc, (unsigned)h.kind, msg);
            free(p);
            cftr_sock_close(s);
        }
    }
    printf("  answer past cap   -> refused before the run, not after\n");
}

/* ---- the operations libcft's client never issues ---------------------- */

static void protocol_tests(cft_device *dev)
{
    void *hw = cft_device_backend(dev);
    uint8_t req[64], *resp = NULL;
    size_t len = 0;
    int status;
    uint32_t handle;
    stats S;

    printf("operations the library's client never issues:\n");

    /* buffers: alloc, write a pattern, read it back, free */
    cftr_put64(req, 4096);
    CHECK(!cftr_request(hw, CFTR_OP_BUF_ALLOC, req, 8, &status, &resp, &len)
          && status == CFT_OK && len == 4, "BUF_ALLOC");
    handle = resp ? cftr_get32(resp) : 0;
    free(resp);
    {
        uint8_t *w = (uint8_t *)malloc(16 + 4096), *pat = (uint8_t *)malloc(4096);
        size_t i;
        for (i = 0; i < 4096; i++)
            pat[i] = (uint8_t)(i * 7 + 3);
        cftr_put32(w, handle);
        cftr_put32(w + 4, 0);
        cftr_put64(w + 8, 0);
        memcpy(w + 16, pat, 4096);
        CHECK(!cftr_request(hw, CFTR_OP_BUF_WRITE, w, 16 + 4096, &status,
                            &resp, &len) && status == CFT_OK, "BUF_WRITE");
        free(resp);
        cftr_put32(req, handle);
        cftr_put32(req + 4, 0);
        cftr_put64(req + 8, 100);
        cftr_put64(req + 16, 3000);
        CHECK(!cftr_request(hw, CFTR_OP_BUF_READ, req, 24, &status, &resp,
                            &len) && status == CFT_OK && len == 3000 &&
              memcmp(resp, pat + 100, 3000) == 0,
              "BUF_READ returns the bytes written");
        free(resp);
        /* past the end: an argument error, connection intact */
        cftr_put64(req + 8, 4000);
        cftr_put64(req + 16, 200);
        CHECK(!cftr_request(hw, CFTR_OP_BUF_READ, req, 24, &status, &resp,
                            &len) && status == CFT_ERR_INVALID_ARGUMENT,
              "BUF_READ past the end is refused with a status");
        free(resp);
        free(w);
        free(pat);
    }
    cftr_put32(req, handle);
    CHECK(!cftr_request(hw, CFTR_OP_BUF_FREE, req, 4, &status, &resp, &len)
          && status == CFT_OK, "BUF_FREE");
    free(resp);
    CHECK(!cftr_request(hw, CFTR_OP_BUF_FREE, req, 4, &status, &resp, &len)
          && status == CFT_ERR_INVALID_ARGUMENT,
          "BUF_FREE of a freed handle is an argument error");
    free(resp);
    printf("  buffers           alloc, write, read back, bounds, free: ok\n");

    /* the server's status word: 5.7.4 on the far end */
    cftr_put32(req, CFT_FLAGS_ALL);
    CHECK(!cftr_request(hw, CFTR_OP_FLAGS_LOWER, req, 4, &status, &resp, &len)
          && status == CFT_OK, "FLAGS_LOWER");
    free(resp);
    cftr_put32(req, CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT);
    CHECK(!cftr_request(hw, CFTR_OP_FLAGS_RAISE, req, 4, &status, &resp, &len)
          && status == CFT_OK, "FLAGS_RAISE");
    free(resp);
    CHECK(!cftr_request(hw, CFTR_OP_FLAGS_SAVE, NULL, 0, &status, &resp, &len)
          && status == CFT_OK && len == 4 &&
          cftr_get32(resp) == (CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT),
          "FLAGS_SAVE reads back what was raised");
    free(resp);
    cftr_put32(req, CFT_FLAG_OVERFLOW);
    CHECK(!cftr_request(hw, CFTR_OP_FLAGS_TEST, req, 4, &status, &resp, &len)
          && status == CFT_OK && len == 4 && cftr_get32(resp) == 1,
          "FLAGS_TEST answers 1 for a raised flag");
    free(resp);
    cftr_put32(req, CFT_FLAG_INVALID);
    CHECK(!cftr_request(hw, CFTR_OP_FLAGS_TEST, req, 4, &status, &resp, &len)
          && status == CFT_OK && len == 4 && cftr_get32(resp) == 0,
          "FLAGS_TEST answers 0 for a lowered flag");
    free(resp);
    cftr_put32(req, 0);
    cftr_put32(req + 4, CFT_FLAGS_ALL);
    CHECK(!cftr_request(hw, CFTR_OP_FLAGS_RESTORE, req, 8, &status, &resp,
                        &len) && status == CFT_OK, "FLAGS_RESTORE");
    free(resp);
    CHECK(!cftr_request(hw, CFTR_OP_FLAGS_SAVE, NULL, 0, &status, &resp, &len)
          && status == CFT_OK && len == 4 && cftr_get32(resp) == 0,
          "FLAGS_RESTORE of zero lowers everything in the mask");
    free(resp);
    cftr_put32(req, CFT_FLAG_UNDERFLOW | CFT_FLAG_INEXACT);
    cftr_put32(req + 4, CFT_FLAG_INEXACT);
    CHECK(!cftr_request(hw, CFTR_OP_FLAGS_TEST_SAVED, req, 8, &status, &resp,
                        &len) && status == CFT_OK && cftr_get32(resp) == 1,
          "FLAGS_TEST_SAVED");
    free(resp);
    printf("  status word       lower, raise, test, save, restore: ok\n");

    /* an unknown opcode is a status, not a broken stream */
    CHECK(!cftr_request(hw, 0x0777, NULL, 0, &status, &resp, &len) &&
          status == CFT_ERR_UNSUPPORTED, "unknown opcode -> UNSUPPORTED");
    free(resp);
    /* and a bad program handle likewise */
    cftr_put32(req, 999);
    CHECK(!cftr_request(hw, CFTR_OP_PROG_FREE, req, 4, &status, &resp, &len)
          && status == CFT_ERR_INVALID_ARGUMENT, "bad program handle");
    free(resp);
    CHECK(!get_stats(dev, hw, &S) && S.requests > 10 && S.op[CFTR_OP_HELLO] == 1,
          "STATS after the above: %llu requests",
          (unsigned long long)S.requests);
    printf("  after a bad op    the connection continues (STATS: %llu "
           "requests, %llu bytes in, %llu bytes out)\n",
           (unsigned long long)S.requests, (unsigned long long)S.bytes_in,
           (unsigned long long)S.bytes_out);
}

/* ---- bit identity against the software backend -------------------- */

static void identity_tests(cft_device *sw, cft_device *rm, size_t n)
{
    static const int ops[] = { CFT_FMA, CFT_ADD, CFT_MUL, CFT_MIN, CFT_CMPLT,
                               CFT_IADD, CFT_RECIP_SEED, 15 };
    int fmt, k, rnd;
    uint8_t *a, *b, *c, *d1, *d2;

    printf("bit identity against the software backend, %lu elements:\n",
           (unsigned long)n);
    for (fmt = 0; fmt < 4; fmt++) {
        const size_t esz = cft_format_size((cft_format)fmt);
        int bad = 0;
        if (!cft_supports(rm, CFT_FMA, (cft_format)fmt)) {
            printf("  %-6s skipped, not on the server\n",
                   cft_format_name((cft_format)fmt));
            continue;
        }
        a = (uint8_t *)malloc(n * esz); b = (uint8_t *)malloc(n * esz);
        c = (uint8_t *)malloc(n * esz);
        d1 = (uint8_t *)malloc(n * esz); d2 = (uint8_t *)malloc(n * esz);
        fill(a, n * esz); fill(b, n * esz); fill(c, n * esz);
        for (k = 0; k < (int)(sizeof ops / sizeof ops[0]); k++) {
            for (rnd = 0; rnd < 5; rnd++) {
                uint32_t f1 = 0, f2 = 0;
                cft_status s1, s2;
                s1 = cft_run(sw, (cft_op)ops[k], (cft_format)fmt, (cft_round)rnd,
                             a, b, c, d1, n, &f1, NULL);
                s2 = cft_run(rm, (cft_op)ops[k], (cft_format)fmt, (cft_round)rnd,
                             a, b, c, d2, n, &f2, NULL);
                CHECK(s1 == s2 && s1 == CFT_OK && f1 == f2 &&
                      memcmp(d1, d2, n * esz) == 0,
                      "%s %s %d: status %d/%d flags %02x/%02x %s",
                      cft_format_name((cft_format)fmt),
                      cft_op_name((cft_op)ops[k]), rnd, s1, s2, f1, f2,
                      memcmp(d1, d2, n * esz) ? "BYTES DIFFER" : "");
                if (s1 != s2 || f1 != f2 || memcmp(d1, d2, n * esz))
                    bad++;
            }
        }
        /* reductions, over an awkward length and a power of two */
        {
            size_t lens[2], li;
            lens[0] = n > 5 ? n - 3 : n;
            lens[1] = n;
            for (li = 0; li < 2; li++) {
                static const int rops[4] = { CFT_SUM, CFT_DOT, CFT_SUMSQ, CFT_SUMABS };
                int r;
                for (r = 0; r < 4; r++) {
                    uint32_t f1 = 0, f2 = 0;
                    cft_status s1, s2;
                    memset(d1, 0, esz); memset(d2, 0, esz);
                    s1 = cft_reduce(sw, (cft_op)rops[r], (cft_format)fmt, CFT_RNE,
                                    a, b, d1, lens[li], &f1, NULL);
                    s2 = cft_reduce(rm, (cft_op)rops[r], (cft_format)fmt, CFT_RNE,
                                    a, b, d2, lens[li], &f2, NULL);
                    CHECK(s1 == s2 && s1 == CFT_OK && f1 == f2 &&
                          memcmp(d1, d2, esz) == 0,
                          "%s %s n=%lu: status %d/%d flags %02x/%02x",
                          cft_format_name((cft_format)fmt),
                          cft_op_name((cft_op)rops[r]), (unsigned long)lens[li],
                          s1, s2, f1, f2);
                    if (s1 != s2 || f1 != f2 || memcmp(d1, d2, esz))
                        bad++;
                }
            }
        }
        /* the composed operations, on whatever route the environment
         * selects: div and sqrt through the program route by default
         * on a remote device, the chunk route under CFT_DIVSQRT_SEQ=0 */
        fill_normal(a, n, fmt);
        fill_normal(b, n, fmt);
        {
            uint32_t f1 = 0, f2 = 0;
            cft_status s1, s2;
            s1 = cft_div(sw, (cft_format)fmt, CFT_RNE, a, b, d1, n, &f1, NULL);
            s2 = cft_div(rm, (cft_format)fmt, CFT_RNE, a, b, d2, n, &f2, NULL);
            CHECK(s1 == s2 && s1 == CFT_OK && f1 == f2 &&
                  memcmp(d1, d2, n * esz) == 0, "%s div: %d/%d %02x/%02x %s",
                  cft_format_name((cft_format)fmt), s1, s2, f1, f2,
                  memcmp(d1, d2, n * esz) ? "BYTES DIFFER" : "");
            if (s1 != s2 || f1 != f2 || memcmp(d1, d2, n * esz)) bad++;
            s1 = cft_sqrt(sw, (cft_format)fmt, CFT_RDN, a, d1, n, &f1, NULL);
            s2 = cft_sqrt(rm, (cft_format)fmt, CFT_RDN, a, d2, n, &f2, NULL);
            CHECK(s1 == s2 && s1 == CFT_OK && f1 == f2 &&
                  memcmp(d1, d2, n * esz) == 0, "%s sqrt: %d/%d %02x/%02x",
                  cft_format_name((cft_format)fmt), s1, s2, f1, f2);
            if (s1 != s2 || f1 != f2 || memcmp(d1, d2, n * esz)) bad++;
            s1 = cft_rint(sw, (cft_format)fmt, CFT_RUP, 1, a, d1, n, &f1, NULL);
            s2 = cft_rint(rm, (cft_format)fmt, CFT_RUP, 1, a, d2, n, &f2, NULL);
            CHECK(s1 == s2 && s1 == CFT_OK && f1 == f2 &&
                  memcmp(d1, d2, n * esz) == 0, "%s rint: %d/%d %02x/%02x",
                  cft_format_name((cft_format)fmt), s1, s2, f1, f2);
            if (s1 != s2 || f1 != f2 || memcmp(d1, d2, n * esz)) bad++;
            s1 = cft_scaleb(sw, (cft_format)fmt, CFT_RNE, a, -3, d1, n, &f1, NULL);
            s2 = cft_scaleb(rm, (cft_format)fmt, CFT_RNE, a, -3, d2, n, &f2, NULL);
            CHECK(s1 == s2 && s1 == CFT_OK && f1 == f2 &&
                  memcmp(d1, d2, n * esz) == 0, "%s scaleb: %d/%d %02x/%02x",
                  cft_format_name((cft_format)fmt), s1, s2, f1, f2);
            if (s1 != s2 || f1 != f2 || memcmp(d1, d2, n * esz)) bad++;
            s1 = cft_cmp_sig(sw, CFT_CMPLE, (cft_format)fmt, a, b, d1, n, &f1, NULL);
            s2 = cft_cmp_sig(rm, CFT_CMPLE, (cft_format)fmt, a, b, d2, n, &f2, NULL);
            CHECK(s1 == s2 && s1 == CFT_OK && f1 == f2 &&
                  memcmp(d1, d2, n * esz) == 0, "%s cmp_sig: %d/%d %02x/%02x",
                  cft_format_name((cft_format)fmt), s1, s2, f1, f2);
            if (s1 != s2 || f1 != f2 || memcmp(d1, d2, n * esz)) bad++;
        }
        /* the status word: the two handles saw the same calls */
        CHECK(cft_save_all_flags(sw) == cft_save_all_flags(rm),
              "%s: status words differ, %02x local %02x remote",
              cft_format_name((cft_format)fmt),
              (unsigned)cft_save_all_flags(sw),
              (unsigned)cft_save_all_flags(rm));
        printf("  %-6s elementwise x5 attributes, reductions, div, sqrt, "
               "rint, scaleb, cmp_sig, status word: %s\n",
               cft_format_name((cft_format)fmt), bad ? "MISMATCH" : "ok");
        free(a); free(b); free(c); free(d1); free(d2);
    }
}

/* ---- the cost ------------------------------------------------------------ */

static void bench(cft_device *rm)
{
    void *hw = cft_device_backend(rm);
    static const size_t ns[3] = { 1, 64, 4096 };
    const char *route = getenv("CFT_DIVSQRT_SEQ");
    size_t i;
    uint8_t *a, *b, *d;
    stats s0, s1;
    double t0, t1;

    printf("round trips, from the server's counters (CFT_DIVSQRT_SEQ=%s):\n",
           route ? route : "unset, the program route on a device");
    printf("  %-14s %6s %8s %9s %8s %9s %10s\n", "operation", "n", "RUN",
           "PROG_RUN", "REDUCE", "frames", "ms");

    a = (uint8_t *)malloc(4096 * 32); b = (uint8_t *)malloc(4096 * 32);
    d = (uint8_t *)malloc(4096 * 32);
    for (i = 0; i < 3; i++) {
        const size_t n = ns[i];
        int k;
        fill_normal(a, n, CFT_FP64);
        fill_normal(b, n, CFT_FP64);
        for (k = 0; k < 7; k++) {
            const char *name = "";
            uint32_t fl = 0;
            cft_status st = CFT_OK;
            get_stats(rm, hw, &s0);
            t0 = now_s();
            switch (k) {
            case 0: name = "run fma";
                st = cft_run(rm, CFT_FMA, CFT_FP64, CFT_RNE, a, b, a, d, n, &fl, NULL);
                break;
            case 1: name = "div";
                st = cft_div(rm, CFT_FP64, CFT_RNE, a, b, d, n, &fl, NULL);
                break;
            case 2: name = "sqrt";
                st = cft_sqrt(rm, CFT_FP64, CFT_RNE, a, d, n, &fl, NULL);
                break;
            case 3: name = "rint";
                st = cft_rint(rm, CFT_FP64, CFT_RNE, 0, a, d, n, &fl, NULL);
                break;
            case 4: name = "scaleb";
                st = cft_scaleb(rm, CFT_FP64, CFT_RNE, a, 5, d, n, &fl, NULL);
                break;
            case 5: name = "cmp_sig";
                st = cft_cmp_sig(rm, CFT_CMPLT, CFT_FP64, a, b, d, n, &fl, NULL);
                break;
            default: name = "formatof_add";
                /* fp32 -> fp64: the widening route, a convert then a pass */
                st = cft_formatof_add(rm, CFT_FP32, CFT_FP64, CFT_RNE, a, b, d,
                                      n, &fl, NULL);
                break;
            }
            t1 = now_s();
            get_stats(rm, hw, &s1);
            CHECK(st == CFT_OK, "%s n=%lu: %s", name, (unsigned long)n,
                  cft_strerror(st));
            printf("  %-14s %6lu %8llu %9llu %8llu %9llu %10.2f\n", name,
                   (unsigned long)n,
                   (unsigned long long)(s1.op[CFTR_OP_RUN] - s0.op[CFTR_OP_RUN]),
                   (unsigned long long)(s1.op[CFTR_OP_PROG_RUN] - s0.op[CFTR_OP_PROG_RUN]),
                   (unsigned long long)(s1.op[CFTR_OP_REDUCE] - s0.op[CFTR_OP_REDUCE]),
                   (unsigned long long)(s1.requests - s0.requests - 1),
                   (t1 - t0) * 1000.0);
        }
    }

    /* the raw round trip: one-element FMAs, then a chunk's worth */
    {
        const int reps = 2000;
        int r;
        fill_normal(a, 4096, CFT_FP64);
        t0 = now_s();
        for (r = 0; r < reps; r++)
            cft_run(rm, CFT_FMA, CFT_FP64, CFT_RNE, a, a, a, d, 1, NULL, NULL);
        t1 = now_s();
        printf("round trip, one fp64 element per cft_run: %.1f us each "
               "(%d calls, %.0f/s)\n", (t1 - t0) * 1e6 / reps, reps,
               reps / (t1 - t0));
        t0 = now_s();
        for (r = 0; r < 20; r++)
            cft_run(rm, CFT_FMA, CFT_FP64, CFT_RNE, a, a, a, d, 4096, NULL, NULL);
        t1 = now_s();
        printf("4096 fp64 elements per cft_run: %.2f ms each, %.0f elements/s\n",
               (t1 - t0) * 1000.0 / 20, 20 * 4096 / (t1 - t0));
    }
    free(a); free(b); free(d);
}

/* ---- main ---------------------------------------------------------------- */

int main(int argc, char **argv)
{
    const char *url = NULL;
    size_t n = 64;
    int do_bench = 0, i;
    cft_device *sw = NULL, *rm = NULL;
    cft_caps caps;
    cft_status st;

    /* Unbuffered, so that a harness reading a pipe sees every line a
     * refusal test printed before the thing it was testing. */
    setvbuf(stdout, NULL, _IONBF, 0);

    for (i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--crc")) {
            /* two byte strings for zlib.crc32 to agree on: the standard
             * check string, and 1000 bytes of the LCG stream */
            uint8_t buf[1000];
            fill(buf, sizeof buf);
            printf("crc32 check     %08x\n",
                   (unsigned)cftr_crc32(0, "123456789", 9));
            printf("crc32 stream    %08x\n",
                   (unsigned)cftr_crc32(0, buf, sizeof buf));
            printf("stream sha-free %02x%02x%02x%02x...%02x%02x\n", buf[0],
                   buf[1], buf[2], buf[3], buf[998], buf[999]);
            return cftr_crc32_selfcheck() ? 1 : 0;
        } else if (!strcmp(argv[i], "--bench")) {
            do_bench = 1;
        } else if (!strcmp(argv[i], "-n") && i + 1 < argc) {
            n = (size_t)strtoul(argv[++i], NULL, 10);
        } else if (!url) {
            url = argv[i];
        } else {
            fprintf(stderr, "usage: remote-test cft://host:port [-n N] "
                            "[--bench] [--crc]\n");
            return 2;
        }
    }
    if (!url || n == 0) {
        fprintf(stderr, "usage: remote-test cft://host:port [-n N] [--bench] "
                        "[--crc]\n");
        return 2;
    }

    printf("remote-test: libcft ABI %u.%u, %s\n",
           (unsigned)(cft_abi_version() >> 16),
           (unsigned)(cft_abi_version() & 0xFFFFu), url);
    CHECK(cftr_crc32_selfcheck() == 0, "CRC-32 self check");

    /* The refusals first, each on a connection of its own, before this
     * process holds a handle open. */
    if (!do_bench)
        refusal_tests(url);

    st = cft_open(url, 0, &rm);
    if (st != CFT_OK) {
        printf("cft_open(%s): %s\n  %s\n", url, cft_strerror(st),
               cft_last_error());
        return 2;
    }
    st = cft_open(NULL, 0, &sw);
    if (st != CFT_OK) {
        printf("cft_open(software): %s\n", cft_strerror(st));
        return 2;
    }
    memset(&caps, 0, sizeof caps);
    caps.struct_size = sizeof caps;
    cft_get_caps(rm, &caps);
    printf("backend %s (the server's: %s), tiles %u, flags readable %s, "
           "formats", caps.backend, cftr_server_backend(cft_device_backend(rm)),
           (unsigned)caps.tiles, caps.flags_readable ? "yes" : "NO");
    for (i = 0; i < 4; i++)
        if (caps.format_mask & (1u << i))
            printf(" %s", cft_format_name((cft_format)i));
    printf("\n");
    CHECK(strcmp(caps.backend, "remote") == 0, "backend name is %s", caps.backend);
    {
        cft_device *tmp = NULL;
        CHECK(cft_open(url, 1, &tmp) == CFT_ERR_NO_DEVICE && !tmp,
              "index 1 is no device");
        CHECK(cft_open("cft://nowhere", 0, &tmp) == CFT_ERR_INVALID_ARGUMENT,
              "a URL without a port is an invalid argument");
        CHECK(cft_open("cft://127.0.0.1:1", 0, &tmp) == CFT_ERR_NO_DEVICE,
              "a port nothing listens on is no device");
    }

    if (!do_bench) {
        protocol_tests(rm);
        identity_tests(sw, rm, n);
    } else {
        bench(rm);
    }

    cft_close(rm);
    cft_close(sw);
    printf("%d checks, %d failures\n", checks, failures);
    return failures ? 1 : 0;
}
