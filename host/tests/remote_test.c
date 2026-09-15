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
 * status word, STATS), and holds a sample of cft_run, cft_reduce,
 * cft_reduce_seg and the composed operations against the software
 * backend, both routes. The segmented reduction (ABI 0.13) is driven
 * end to end here and nowhere else in C: its frame, its two refusals
 * on the wire and the client's own refusal that never becomes one.
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

/* nanosleep - the one wait in this file - is POSIX, not C99; this
 * asks for it on Linux and the Mac before any header is read, and
 * MinGW, which takes the Sleep branch, ignores it. */
#if !defined(_WIN32) && !defined(_POSIX_C_SOURCE)
#  define _POSIX_C_SOURCE 200112L
#endif

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "cft.h"

#if defined(_WIN32)
#  include <windows.h>
#else
#  include <time.h>
#endif

/* A short wait, for the one check that has to let the server catch
 * up with a close it has not seen yet (below). */
static void nap_ms(int ms)
{
#if defined(_WIN32)
    Sleep((DWORD)ms);
#else
    struct timespec ts;
    ts.tv_sec = ms / 1000;
    ts.tv_nsec = (long)(ms % 1000) * 1000000L;
    nanosleep(&ts, NULL);
#endif
}
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
    /* The server releases the truncated connection's device when it
     * sees the EOF. On loopback that happens before the next connect;
     * over a real network it need not, and the next connection then
     * finds the device still held for a few milliseconds - seen from
     * a Mac against the box over Wi-Fi on 2026-09-09. So this asks
     * again for up to two seconds: a wait for the server, not a
     * weakening of what is checked, which is that it recovers. */
    {
        int tries;
        for (tries = 0; tries < 20; tries++) {
            hello_header(hdr, cft_abi_version(), CFTR_OP_HELLO, 0, NULL);
            rc = raw_exchange(host, port, hdr, NULL, 0, &status, msg,
                              sizeof msg);
            if (rc == 1 && status == CFT_OK)
                break;
            nap_ms(100);
        }
    }
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

    /* 9. and 10. REDUCE_SEG's own two refusals (ABI 0.13), each after a
     * HELLO on its own connection: an n that is not a whole number of
     * segments, and a segment of zero. Both are shape rules the server
     * applies before it reads an operand - the payload names none, as
     * item 8's does, so 28 bytes are a complete request - and both are
     * REFUSALS that close the connection, not statuses, because a
     * client that sent either has a wrong idea of the frame rather
     * than an unlucky operand. The library's own client never sends
     * them (protocol_tests holds that); this is what a client that is
     * not libcft gets. */
    {
        static const struct { uint64_t n; uint32_t seg; const char *what; }
            bad_seg[2] = { { 7, 3, "n not a whole number of segments" },
                           { 6, 0, "a segment of zero" } };
        int k;
        for (k = 0; k < 2; k++) {
            cftr_sock s = cftr_sock_connect(host, port);
            CHECK(s != CFTR_BAD_SOCK, "connecting for the REDUCE_SEG %s test",
                  bad_seg[k].what);
            if (s == CFTR_BAD_SOCK)
                continue;
            {
                cftr_hdr h;
                uint8_t *p = NULL;
                char why[256];
                uint32_t crc;
                cftr_sock_timeout(s, 20000);
                hello_header(hdr, cft_abi_version(), CFTR_OP_HELLO, 0, NULL);
                cftr_sock_send_all(s, hdr, 32);
                rc = cftr_recv_frame(s, &h, &p, cft_abi_version(), why,
                                     sizeof why);
                free(p);
                p = NULL;
                CHECK(rc == 0 && h.status == CFT_OK,
                      "HELLO before the REDUCE_SEG %s test: rc %d",
                      bad_seg[k].what, rc);
                memset(payload, 0, 28);
                cftr_put32(payload + 0, (uint32_t)CFT_SUM);
                cftr_put32(payload + 4, 0);            /* fp32 */
                cftr_put32(payload + 8, 0);            /* roundTiesToEven */
                cftr_put32(payload + 12, 0);           /* no operands on the wire */
                cftr_put64(payload + 16, bad_seg[k].n);
                cftr_put32(payload + 24, bad_seg[k].seg);
                hello_header(hdr, cft_abi_version(), CFTR_OP_REDUCE_SEG, 28,
                             payload);
                cftr_put32(hdr + 12, 2);
                cftr_put32(hdr + 24, 0);
                crc = cftr_crc32(0, hdr, 32);
                cftr_put32(hdr + 24, cftr_crc32(crc, payload, 28));
                cftr_sock_send_all(s, hdr, 32);
                cftr_sock_send_all(s, payload, 28);
                rc = cftr_recv_frame(s, &h, &p, cft_abi_version(), why,
                                     sizeof why);
                msg[0] = '\0';
                if (rc == 0 && p)
                    snprintf(msg, sizeof msg, "%.*s", (int)h.length,
                             (const char *)p);
                CHECK(rc == 0 && h.kind == CFTR_KIND_REFUSAL &&
                      strstr(msg, "segment") != NULL,
                      "REDUCE_SEG with %s: rc %d kind %u (%s)",
                      bad_seg[k].what, rc, (unsigned)h.kind, msg);
                free(p);
                p = NULL;
                /* and it closed: the next read is EOF */
                {
                    uint8_t byte;
                    int eof = cftr_sock_recv_all(s, &byte, 1);
                    CHECK(eof == 1, "the REDUCE_SEG %s refusal closed the "
                          "connection (recv %d)", bad_seg[k].what, eof);
                }
                cftr_sock_close(s);
            }
            printf("  REDUCE_SEG %-11s -> refused and closed (%s)\n",
                   k ? "seg 0" : "7 in 3s", msg);
        }
    }
}

/* ---- the operations libcft's client never issues ---------------------- */


/* The caps block, and the four fields appended to it.
 *
 * HELLO's block is what the client's cft_get_caps answers from, so
 * this asks the server for the block a second time (CAPS is the same
 * block on demand) and checks the two agree - and that the sequencer
 * capacities crossed the wire at all. They did not exist before
 * 2026-09-07: a client and a server that disagree about the block's
 * LENGTH is the one compatibility question this change raises, and
 * the client's rule is "at least V1, read what fits", which means a
 * shorter block leaves the new fields zero and cft_caps documents
 * zero as unknown. The pairing that would exercise it - a new client
 * against an old server - cannot be built here and is not simulated;
 * what is checked is the current block, end to end. */
static void caps_block_tests(cft_device *rm, cft_device *sw)
{
    void *hw = cft_device_backend(rm);
    uint8_t *resp = NULL;
    size_t len = 0;
    int status;
    cft_caps c, cs;

    memset(&c, 0, sizeof c);
    c.struct_size = sizeof c;
    CHECK(cft_get_caps(rm, &c) == CFT_OK, "cft_get_caps on the remote handle");

    printf("the caps block:\n");
    CHECK(!cftr_request(hw, CFTR_OP_CAPS, NULL, 0, &status, &resp, &len)
          && status == CFT_OK && len == CFTR_CAPS_BYTES,
          "CAPS answers %u bytes, got %lu", (unsigned)CFTR_CAPS_BYTES,
          (unsigned long)len);
    if (resp && len == CFTR_CAPS_BYTES) {
        /* Every bit of the block, CFT_SEQ_FEAT_INDEXED included, as
         * of parcel P2: the client-side gather makes the bit's claim
         * true on this route (device.c's remote branch gathers and
         * sends a dense program run), so the handle adopts it like
         * every other capability and the mask that used to exclude it
         * here is gone. */
        CHECK(cftr_get32(resp + 56) == c.max_deposits &&
              cftr_get32(resp + 60) == c.max_insns &&
              cftr_get32(resp + 64) == c.max_consts &&
              cftr_get32(resp + 68) == c.seq_features &&
              cftr_get32(resp + 72) == c.max_scratch,
              "the block's sequencer capacities are what cft_get_caps "
              "reports (%lu/%lu/%lu/0x%lx/%lu on the wire, "
              "%lu/%lu/%lu/0x%lx/%lu from the handle)",
              (unsigned long)cftr_get32(resp + 56),
              (unsigned long)cftr_get32(resp + 60),
              (unsigned long)cftr_get32(resp + 64),
              (unsigned long)cftr_get32(resp + 68),
              (unsigned long)cftr_get32(resp + 72),
              (unsigned long)c.max_deposits, (unsigned long)c.max_insns,
              (unsigned long)c.max_consts, (unsigned long)c.seq_features,
              (unsigned long)c.max_scratch);
        printf("  max_deposits %lu, max_insns %lu, max_consts %lu, "
               "seq_features 0x%lx, max_scratch %lu\n",
               (unsigned long)c.max_deposits, (unsigned long)c.max_insns,
               (unsigned long)c.max_consts, (unsigned long)c.seq_features,
               (unsigned long)c.max_scratch);
    }
    free(resp);

    /* A server fronting the software backend must report exactly the
     * caps this process's own software backend has, because it IS one:
     * the two libraries have the same ABI or the handshake would have
     * refused the connection. A server fronting a card reports the
     * card's, which is the whole point and is not comparable here. */
    memset(&cs, 0, sizeof cs);
    cs.struct_size = sizeof cs;
    if (cft_get_caps(sw, &cs) == CFT_OK &&
        strcmp(cftr_server_backend(hw), "software") == 0) {
        CHECK(c.max_deposits == cs.max_deposits &&
              c.max_insns == cs.max_insns &&
              c.max_consts == cs.max_consts &&
              c.seq_features == cs.seq_features &&
              c.max_scratch == cs.max_scratch,
              "a software server's capacities are this library's own");
        /* ...and INDEXED is the one that had to be argued (P2). It is
         * a POSITIVE claim on both sides now: the local software
         * backend has the bit, and a remote handle to that same
         * backend has it too, because the client gathers before the
         * frame and the call really does succeed. A capability word
         * that says yes to a call that says no is what cft_get_caps
         * exists to prevent, and the identity tests below are where
         * the call is made rather than only claimed. */
        CHECK((cs.seq_features & CFT_SEQ_FEAT_INDEXED) != 0,
              "the local software backend publishes "
              "CFT_SEQ_FEAT_INDEXED");
        CHECK((c.seq_features & CFT_SEQ_FEAT_INDEXED) != 0,
              "and so does a REMOTE handle to it, because the program "
              "run's remote route gathers on the client "
              "(docs/ROUND2.md, parcel P2)");
    } else {
        printf("  server backend is '%s', not compared with the local "
               "software backend\n", cftr_server_backend(hw));
    }

    /* And the client ENFORCES what it was told: a program past the
     * server's deposit budget is refused here, before a frame is
     * sent. */
    if (c.max_deposits && c.max_deposits < 0xFFFFFFFFu) {
        uint8_t img[40];
        cft_program *prog = NULL;
        cft_status st;
        memset(img, 0, sizeof img);
        cftr_put32(img + 0, 0x50544643u);      /* "CFTP" */
        cftr_put32(img + 4, 1);                /* version */
        cftr_put32(img + 8, 1);                /* n_insns */
        cftr_put32(img + 12, 0);               /* n_consts */
        cftr_put32(img + 16, c.max_deposits + 1u);
        cftr_put32(img + 20, 0);               /* fp32 */
        img[32] = 0;                           /* HALT, ctrl bit... */
        img[35] = 0x80;                        /* ...at bit 31 */
        st = cft_program_load(rm, img, sizeof img, &prog);
        CHECK(st == CFT_ERR_UNSUPPORTED && !prog,
              "max_deposits %lu + 1 is refused by the client: %s (%s)",
              (unsigned long)c.max_deposits, cft_strerror(st),
              cft_last_error());
        cftr_put32(img + 16, c.max_deposits);
        st = cft_program_load(rm, img, sizeof img, &prog);
        CHECK(st == CFT_OK, "max_deposits %lu exactly is accepted: %s",
              (unsigned long)c.max_deposits, cft_strerror(st));
        cft_program_free(prog);
    }
}

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
    /* the segmented reduction's shape rules are the CLIENT's first: an
     * n that is not a whole number of segments, or a segment of zero,
     * is refused in the library before any frame exists, so the
     * server's REDUCE_SEG counter does not move */
    {
        stats S0, S1;
        uint8_t a7[7 * 4], d7[7 * 4];
        uint32_t fl = 0;
        memset(a7, 0, sizeof a7);
        CHECK(!get_stats(dev, hw, &S0), "STATS before the client refusals");
        CHECK(cft_reduce_seg(dev, CFT_SUM, CFT_FP32, CFT_RNE, a7, NULL, d7,
                             7, 3, &fl, NULL) == CFT_ERR_INVALID_ARGUMENT,
              "7 elements in segments of 3 is refused by the client");
        CHECK(cft_reduce_seg(dev, CFT_SUM, CFT_FP32, CFT_RNE, a7, NULL, d7,
                             6, 0, &fl, NULL) == CFT_ERR_INVALID_ARGUMENT,
              "a segment of zero is refused by the client");
        CHECK(!get_stats(dev, hw, &S1) &&
              S1.op[CFTR_OP_REDUCE_SEG] == S0.op[CFTR_OP_REDUCE_SEG] &&
              S1.requests == S0.requests + 1,
              "neither client refusal became a frame (REDUCE_SEG %llu -> "
              "%llu, requests %llu -> %llu)",
              (unsigned long long)S0.op[CFTR_OP_REDUCE_SEG],
              (unsigned long long)S1.op[CFTR_OP_REDUCE_SEG],
              (unsigned long long)S0.requests, (unsigned long long)S1.requests);
        printf("  REDUCE_SEG shape  refused in the client, no frame sent\n");
    }
    /* R16's argument rules are the CLIENT's in the same way (P2): a
     * table on an operand the OPCODE does not read, an index at or
     * past the source's declared length, and `d` overlapping an
     * indexed source are each refused before any frame exists. That
     * is the "refused by name, with no round trip made" half of this
     * parcel's negative control, and it is measured here rather than
     * argued: the server's RUN counter does not move, and the only
     * new request is the STATS call that reads it. */
    {
        stats S0, S1;
        uint8_t a8[8 * 4], d8[8 * 4];
        uint32_t ix[8];
        cft_elem_args E;
        size_t q;
        memset(a8, 0, sizeof a8);
        for (q = 0; q < 8; q++)
            ix[q] = (uint32_t)q;
        CHECK(!get_stats(dev, hw, &S0), "STATS before the indexed refusals");
        memset(&E, 0, sizeof E);
        E.struct_size = sizeof E;
        E.a = a8; E.b = a8; E.c = a8; E.d = d8; E.n = 8;
        E.idx_b = ix; E.idx_b_src = 8;
        CHECK(cft_run_ex(dev, CFT_ADD, CFT_FP32, CFT_RNE, &E)
                  == CFT_ERR_INVALID_ARGUMENT,
              "a table on operand b of CFT_ADD, which does not read it, "
              "is refused by the client");
        E.idx_b = NULL; E.idx_b_src = 0;
        E.idx_a = ix; E.idx_a_src = 8;
        ix[3] = 8;
        CHECK(cft_run_ex(dev, CFT_ADD, CFT_FP32, CFT_RNE, &E)
                  == CFT_ERR_INVALID_ARGUMENT,
              "an index at the source's length is refused by the client");
        ix[3] = 3;
        E.d = a8;
        CHECK(cft_run_ex(dev, CFT_ADD, CFT_FP32, CFT_RNE, &E)
                  == CFT_ERR_INVALID_ARGUMENT,
              "d overlapping the indexed source is refused by the client");
        CHECK(!get_stats(dev, hw, &S1) &&
              S1.op[CFTR_OP_RUN] == S0.op[CFTR_OP_RUN] &&
              S1.requests == S0.requests + 1,
              "none of the three indexed refusals became a frame (RUN "
              "%llu -> %llu, requests %llu -> %llu)",
              (unsigned long long)S0.op[CFTR_OP_RUN],
              (unsigned long long)S1.op[CFTR_OP_RUN],
              (unsigned long long)S0.requests,
              (unsigned long long)S1.requests);
        printf("  indexed shape     refused in the client, no frame sent "
               "(RUN %llu -> %llu)\n",
               (unsigned long long)S0.op[CFTR_OP_RUN],
               (unsigned long long)S1.op[CFTR_OP_RUN]);
    }
    CHECK(!get_stats(dev, hw, &S) && S.requests > 10 && S.op[CFTR_OP_HELLO] == 1,
          "STATS after the above: %llu requests",
          (unsigned long long)S.requests);
    printf("  after a bad op    the connection continues (STATS: %llu "
           "requests, %llu bytes in, %llu bytes out)\n",
           (unsigned long long)S.requests, (unsigned long long)S.bytes_in,
           (unsigned long long)S.bytes_out);
}

/* ---- bit identity against the software backend -------------------- */

/* R16 over the wire (ABI 0.14, docs/ROUND2.md P2)
 *
 * The remote route for an index table is a CLIENT-SIDE GATHER: the
 * tables are resolved in this process, the dense run crosses, and the
 * server - which has no field for a table and gains none - answers the
 * call it always could. So what has to be true is that the answer is
 * the LOCAL one, bit for bit and flag for flag, on all three shapes
 * that carry a table: an elementwise run, a program run's streams, and
 * a program run's scratch block.
 *
 * And the controls, because a gather that dropped its table on the
 * floor would pass the first half of every one of them: an identity
 * table is the dense run, and a rotation of it is not.
 *
 * Returns the number of disagreements, which the caller adds to its
 * own count. */
static int indexed_wire(cft_device *sw, cft_device *rm, int fmt, size_t n)
{
    const size_t esz = cft_format_size((cft_format)fmt);
    const size_t src_n = (n / 3) + 1;          /* deliberately short */
    uint8_t *src = NULL, *full = NULL, *bb = NULL, *cc = NULL;
    uint8_t *d_sw = NULL, *d_rm = NULL, *d_dense = NULL, *d_rot = NULL;
    uint8_t *pool = NULL, *ds2 = NULL, *dr2 = NULL, *d_elem = NULL;
    cft_caps rc;
    uint32_t *tab = NULL, *ident = NULL, *rot = NULL, *stab = NULL;
    uint8_t img[64];
    uint64_t ins[3];
    cft_program *pr = NULL, *ps = NULL;
    cft_elem_args E;
    cft_run_args A;
    uint32_t f1 = 0, f2 = 0;
    size_t i;
    int bad = 0;

    if (n < 4)
        return 0;
    src   = (uint8_t *)malloc(src_n * esz);
    full  = (uint8_t *)malloc(n * esz);
    bb    = (uint8_t *)malloc(n * esz);
    cc    = (uint8_t *)malloc(n * esz);
    d_sw  = (uint8_t *)malloc(n * esz);
    d_rm  = (uint8_t *)malloc(n * esz);
    d_dense = (uint8_t *)malloc(n * esz);
    d_rot = (uint8_t *)malloc(n * esz);
    pool  = (uint8_t *)malloc(src_n * esz);
    ds2   = (uint8_t *)malloc(n * esz);
    dr2   = (uint8_t *)malloc(n * esz);
    d_elem = (uint8_t *)malloc(n * esz);
    tab   = (uint32_t *)malloc(n * 4);
    ident = (uint32_t *)malloc(n * 4);
    rot   = (uint32_t *)malloc(n * 4);
    stab  = (uint32_t *)malloc(n * 4);
    if (!src || !full || !bb || !cc || !d_sw || !d_rm || !d_dense ||
        !d_rot || !pool || !ds2 || !dr2 || !d_elem || !tab || !ident ||
        !rot || !stab) {
        CHECK(0, "indexed over the wire: out of memory");
        goto out;
    }
    fill(src, src_n * esz);
    fill(full, n * esz);
    fill(bb, n * esz);
    fill(cc, n * esz);
    fill(pool, src_n * esz);
    for (i = 0; i < n; i++) {
        ident[i] = (uint32_t)i;
        rot[i]   = (uint32_t)((i + 1) % n);
        tab[i]   = (i % 5 == 0) ? CFT_IDX_NONE
                                : (uint32_t)((i * 7 + 1) % src_n);
        stab[i]  = (i % 3 == 0) ? CFT_IDX_NONE
                                : (uint32_t)((i * 5 + 2) % src_n);
    }

#define WIRE_ELEM(dev_, dst_, f_, a_, t_, sn_)                         \
    do {                                                               \
        memset(&E, 0, sizeof E);                                       \
        E.struct_size = sizeof E;                                      \
        E.a = (a_); E.b = bb; E.c = cc;                                \
        E.d = (dst_); E.n = n; E.flags_out = (f_);                     \
        E.idx_a = (t_); E.idx_a_src = (t_) ? (sn_) : 0;                \
        memset((dst_), 0x5a, n * esz);                                 \
    } while (0)

    /* 1. the elementwise run, gathered on the client either way -
     *    locally by the same code, remotely before the frame. */
    WIRE_ELEM(sw, d_sw, &f1, src, tab, src_n);
    CHECK(cft_run_ex(sw, CFT_FMA, (cft_format)fmt, CFT_RNE, &E) == CFT_OK,
          "%s indexed cft_run_ex locally: %s",
          cft_format_name((cft_format)fmt), cft_last_error());
    WIRE_ELEM(rm, d_rm, &f2, src, tab, src_n);
    CHECK(cft_run_ex(rm, CFT_FMA, (cft_format)fmt, CFT_RNE, &E) == CFT_OK,
          "%s indexed cft_run_ex over the wire: %s",
          cft_format_name((cft_format)fmt), cft_last_error());
    CHECK(memcmp(d_sw, d_rm, n * esz) == 0 && f1 == f2,
          "%s indexed cft_run_ex: the server and this process agree "
          "(flags %02x/%02x) %s", cft_format_name((cft_format)fmt),
          f1, f2, memcmp(d_sw, d_rm, n * esz) ? "BYTES DIFFER" : "");
    if (memcmp(d_sw, d_rm, n * esz) || f1 != f2)
        bad++;
    memcpy(d_elem, d_sw, n * esz);     /* kept for the seam check below */

    /* 2. the controls, on the REMOTE handle: an identity table over a
     *    full-length source is the dense run, and a rotation is not. */
    CHECK(cft_run(rm, CFT_FMA, (cft_format)fmt, CFT_RNE, full, bb, cc,
                  d_dense, n, NULL, NULL) == CFT_OK, "%s dense run",
          cft_format_name((cft_format)fmt));
    WIRE_ELEM(rm, d_rm, NULL, full, ident, n);
    CHECK(cft_run_ex(rm, CFT_FMA, (cft_format)fmt, CFT_RNE, &E) == CFT_OK &&
          memcmp(d_rm, d_dense, n * esz) == 0,
          "%s an identity table over the wire is the dense run",
          cft_format_name((cft_format)fmt));
    if (memcmp(d_rm, d_dense, n * esz))
        bad++;
    WIRE_ELEM(rm, d_rot, NULL, full, rot, n);
    CHECK(cft_run_ex(rm, CFT_FMA, (cft_format)fmt, CFT_RNE, &E) == CFT_OK &&
          memcmp(d_rot, d_dense, n * esz) != 0,
          "%s a rotated table over the wire is NOT the dense run - the "
          "table is being carried", cft_format_name((cft_format)fmt));
    if (memcmp(d_rot, d_dense, n * esz) == 0)
        bad++;
#undef WIRE_ELEM

    /* 3. a PROGRAM run's streams through a table. `FMA r3, r0, r1, r2;
     *    DEPOSIT r3; HALT` - the three-instruction shape the library
     *    composes an indexed elementwise run into on a device, run
     *    here as an ordinary program so that the remote branch's
     *    gather is what is under test. */
    ins[0] = 0ull | (3ull << 8) | (0ull << 12) | (1ull << 16) |
             (2ull << 20);                                   /* FMA r3 */
    ins[1] = 3ull | (3ull << 12) | (1ull << 31);             /* DEPOSIT */
    ins[2] = 0ull | (1ull << 31);                            /* HALT */
    memset(img, 0, sizeof img);
    cftr_put32(img + 0, 0x50544643u);
    cftr_put32(img + 4, 1);
    cftr_put32(img + 8, 3);
    cftr_put32(img + 12, 0);
    cftr_put32(img + 16, 1);                   /* max_deposits */
    cftr_put32(img + 20, (uint32_t)fmt);
    cftr_put32(img + 24, 0);
    cftr_put32(img + 28, 0);
    for (i = 0; i < 3; i++)
        cftr_put64(img + 32 + i * 8, ins[i]);
    if (cft_program_load(rm, img, 32 + 3 * 8, &pr) == CFT_OK &&
        cft_program_load(sw, img, 32 + 3 * 8, &ps) == CFT_OK) {
        f1 = f2 = 0;
        memset(&A, 0, sizeof A);
        A.struct_size = sizeof A;
        A.a = src; A.b = bb; A.c = cc;
        A.n = n;
        A.idx_a = tab; A.idx_a_src = src_n;
        A.deposits = d_sw; A.flags_out = &f1;
        memset(d_sw, 0x5a, n * esz);
        CHECK(cft_program_run_ex(ps, &A) == CFT_OK,
              "%s indexed program run locally: %s",
              cft_format_name((cft_format)fmt), cft_last_error());
        A.deposits = d_rm; A.flags_out = &f2;
        memset(d_rm, 0xa5, n * esz);
        CHECK(cft_program_run_ex(pr, &A) == CFT_OK,
              "%s indexed program run over the wire: %s",
              cft_format_name((cft_format)fmt), cft_last_error());
        CHECK(memcmp(d_sw, d_rm, n * esz) == 0 && f1 == f2,
              "%s indexed program run: the server and this process agree "
              "(flags %02x/%02x) %s", cft_format_name((cft_format)fmt),
              f1, f2, memcmp(d_sw, d_rm, n * esz) ? "BYTES DIFFER" : "");
        if (memcmp(d_sw, d_rm, n * esz) || f1 != f2)
            bad++;
        /* ...and the elementwise call in step 1 composes to exactly
         * this, which is the seam the round is built on: the same
         * tables over the same operands, through cft_run_ex and
         * through the three-instruction program, are the same bytes
         * and the same flags. */
        CHECK(memcmp(d_sw, d_elem, n * esz) == 0,
              "%s the three-instruction program with these tables is "
              "cft_run_ex with them", cft_format_name((cft_format)fmt));
        if (memcmp(d_sw, d_elem, n * esz))
            bad++;
    } else {
        CHECK(0, "%s: the three-instruction image would not load (%s)",
              cft_format_name((cft_format)fmt), cft_last_error());
    }
    cft_program_free(pr); pr = NULL;
    cft_program_free(ps); ps = NULL;

    /* 4. a program run's SCRATCH BLOCK through its table, which is the
     *    one remaining table the remote branch gathers and the only
     *    one whose byte count changes meaning when the table goes:
     *    with a table, scratch_in_bytes is the POOL's length, and the
     *    dense block sent to the server is n * n_scratch_in. */
    memset(&rc, 0, sizeof rc);
    rc.struct_size = sizeof rc;
    if (cft_get_caps(rm, &rc) != CFT_OK ||
        !(rc.seq_features & CFT_SEQ_FEAT_SCRATCH_IO)) {
        printf("  %s: the server does not publish SCRATCH_IO, the "
               "indexed scratch block NOT TESTED\n",
               cft_format_name((cft_format)fmt));
        goto out;
    }
    ins[0] = 7ull | (4ull << 8) | (1ull << 31) | (0ull << 32);  /* LDL 0 */
    ins[1] = 3ull | (4ull << 12) | (1ull << 31);                /* DEP r4 */
    ins[2] = 0ull | (1ull << 31);                               /* HALT */
    memset(img, 0, sizeof img);
    cftr_put32(img + 0, 0x50544643u);
    cftr_put32(img + 4, 1);
    cftr_put32(img + 8, 3);
    cftr_put32(img + 12, 0);
    cftr_put32(img + 16, 1);
    cftr_put32(img + 20, (uint32_t)fmt);
    cftr_put32(img + 24, CFT_PROG_FLAG_SCRATCH_IO);
    cftr_put32(img + 28, 1u);                  /* 1 slot in, 0 out */
    for (i = 0; i < 3; i++)
        cftr_put64(img + 32 + i * 8, ins[i]);
    if (cft_program_load(rm, img, 32 + 3 * 8, &pr) == CFT_OK &&
        cft_program_load(sw, img, 32 + 3 * 8, &ps) == CFT_OK) {
        f1 = f2 = 0;
        memset(&A, 0, sizeof A);
        A.struct_size = sizeof A;
        A.a = full;
        A.n = n;
        A.scratch_in = pool;
        A.scratch_in_bytes = src_n * esz;      /* the POOL, not the block */
        A.idx_scratch_in = stab;
        A.idx_scratch_src = src_n;
        A.deposits = ds2; A.flags_out = &f1;
        memset(ds2, 0x5a, n * esz);
        CHECK(cft_program_run_ex(ps, &A) == CFT_OK,
              "%s indexed scratch block locally: %s",
              cft_format_name((cft_format)fmt), cft_last_error());
        A.deposits = dr2; A.flags_out = &f2;
        memset(dr2, 0xa5, n * esz);
        CHECK(cft_program_run_ex(pr, &A) == CFT_OK,
              "%s indexed scratch block over the wire: %s",
              cft_format_name((cft_format)fmt), cft_last_error());
        CHECK(memcmp(ds2, dr2, n * esz) == 0 && f1 == f2,
              "%s indexed scratch block: the server and this process "
              "agree (flags %02x/%02x) %s",
              cft_format_name((cft_format)fmt), f1, f2,
              memcmp(ds2, dr2, n * esz) ? "BYTES DIFFER" : "");
        if (memcmp(ds2, dr2, n * esz) || f1 != f2)
            bad++;
        /* The control: the same program with a DENSE block of the same
         * bytes the table would have gathered must give the same
         * deposits, and a block gathered through a DIFFERENT table
         * must not - so the pool really is being indexed rather than
         * copied. */
        for (i = 0; i < n; i++)
            stab[i] = (uint32_t)((i * 2 + 1) % src_n);
        A.deposits = d_rot; A.flags_out = NULL;
        memset(d_rot, 0x5a, n * esz);
        CHECK(cft_program_run_ex(pr, &A) == CFT_OK,
              "%s a second scratch table over the wire: %s",
              cft_format_name((cft_format)fmt), cft_last_error());
        CHECK(memcmp(d_rot, dr2, n * esz) != 0,
              "%s two scratch tables, two answers over the wire",
              cft_format_name((cft_format)fmt));
        if (memcmp(d_rot, dr2, n * esz) == 0)
            bad++;
    } else {
        CHECK(0, "%s: the SCRATCH_IO image would not load (%s)",
              cft_format_name((cft_format)fmt), cft_last_error());
    }

out:
    printf("  %-6s indexed: run_ex, a program's streams and its scratch "
           "block gathered on the client, %lu lanes through a %lu-element "
           "source; identity == dense, rotated != dense%s\n",
           cft_format_name((cft_format)fmt), (unsigned long)n,
           (unsigned long)src_n, bad ? " - WITH DISAGREEMENTS" : "");
    cft_program_free(pr);
    cft_program_free(ps);
    free(src); free(full); free(bb); free(cc);
    free(d_sw); free(d_rm); free(d_dense); free(d_rot);
    free(pool); free(ds2); free(dr2); free(d_elem);
    free(tab); free(ident); free(rot); free(stab);
    return bad;
}

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
        /* the segmented reduction (ABI 0.13): the REDUCE_SEG frame end
         * to end, every reduction opcode the server serves. Two shapes
         * - n in four segments (one, when n is not divisible by four)
         * and the largest multiple of six below n in segments of six,
         * which is a partial beat at every format - and then seg == n,
         * which the library folds onto cft_reduce: the same bytes from
         * both calls on both handles, the four compared. The operands
         * are the any-bits fill above, so NaN and infinity propagation
         * through the segment trees is in it. */
        {
            static const int sops[5] = { CFT_SUM, CFT_DOT, CFT_SUMSQ,
                                         CFT_SUMABS, CFT_MAXALL };
            size_t lens[2], segs[2], li;
            int r;
            lens[0] = n;           segs[0] = (n % 4 == 0) ? n / 4 : 1;
            lens[1] = n - (n % 6); segs[1] = 6;
            for (r = 0; r < 5; r++) {
                const cft_op op = (cft_op)sops[r];
                if (!cft_supports(rm, op, (cft_format)fmt))
                    continue;
                for (li = 0; li < 2; li++) {
                    const size_t nres = lens[li] / segs[li];
                    uint32_t f1 = 0, f2 = 0;
                    cft_status s1, s2;
                    if (lens[li] == 0)
                        continue;
                    memset(d1, 0xA5, nres * esz);
                    memset(d2, 0x5A, nres * esz);
                    s1 = cft_reduce_seg(sw, op, (cft_format)fmt, CFT_RNE, a, b,
                                        d1, lens[li], segs[li], &f1, NULL);
                    s2 = cft_reduce_seg(rm, op, (cft_format)fmt, CFT_RNE, a, b,
                                        d2, lens[li], segs[li], &f2, NULL);
                    CHECK(s1 == s2 && s1 == CFT_OK && f1 == f2 &&
                          memcmp(d1, d2, nres * esz) == 0,
                          "%s %s n=%lu seg=%lu: status %d/%d flags %02x/%02x %s",
                          cft_format_name((cft_format)fmt), cft_op_name(op),
                          (unsigned long)lens[li], (unsigned long)segs[li],
                          s1, s2, f1, f2,
                          memcmp(d1, d2, nres * esz) ? "BYTES DIFFER" : "");
                    if (s1 != s2 || f1 != f2 || memcmp(d1, d2, nres * esz))
                        bad++;
                }
                {
                    uint8_t r1[32], r2[32], q1[32], q2[32];
                    uint32_t f1 = 0, f2 = 0, f3 = 0, f4 = 0;
                    cft_status s1, s2, s3, s4;
                    s1 = cft_reduce(sw, op, (cft_format)fmt, CFT_RNE, a, b, r1,
                                    n, &f1, NULL);
                    s2 = cft_reduce_seg(sw, op, (cft_format)fmt, CFT_RNE, a, b,
                                        q1, n, n, &f2, NULL);
                    s3 = cft_reduce(rm, op, (cft_format)fmt, CFT_RNE, a, b, r2,
                                    n, &f3, NULL);
                    s4 = cft_reduce_seg(rm, op, (cft_format)fmt, CFT_RNE, a, b,
                                        q2, n, n, &f4, NULL);
                    CHECK(s1 == CFT_OK && s2 == s1 && s3 == s1 && s4 == s1 &&
                          f1 == f2 && f3 == f1 && f4 == f1 &&
                          memcmp(r1, q1, esz) == 0 && memcmp(r1, r2, esz) == 0 &&
                          memcmp(r1, q2, esz) == 0,
                          "%s %s seg == n is cft_reduce: status %d/%d/%d/%d "
                          "flags %02x/%02x/%02x/%02x",
                          cft_format_name((cft_format)fmt), cft_op_name(op),
                          s1, s2, s3, s4, f1, f2, f3, f4);
                    if (s1 != CFT_OK || s2 != s1 || s3 != s1 || s4 != s1 ||
                        f2 != f1 || f3 != f1 || f4 != f1 ||
                        memcmp(r1, q1, esz) || memcmp(r1, r2, esz) ||
                        memcmp(r1, q2, esz))
                        bad++;
                }
            }
        }
        /* R16's tables, over the wire: the elementwise run, a program
         * run's streams and its scratch block, each gathered on the
         * client and each held to the local answer (P2). */
        bad += indexed_wire(sw, rm, fmt, n);

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
        printf("  %-6s elementwise x5 attributes, reductions, per segment, "
               "div, sqrt, rint, scaleb, cmp_sig, status word: %s\n",
               cft_format_name((cft_format)fmt), bad ? "MISMATCH" : "ok");
        free(a); free(b); free(c); free(d1); free(d2);
    }
}

/* ---- the constant bank over the wire (ABI 0.9) -------------------------- *
 *
 * PROG_RUN_BANK, docs/REMOTE.md's newest message. Three claims:
 *
 *  - the bank crosses the wire and is what the run computed on, which
 *    is checked the only way it can be - two banks, two answers, each
 *    equal to the local software run of the same image with the same
 *    bank;
 *  - the server serves the opcode, and an opcode it does NOT serve is
 *    refused by name on a connection that stays open, which is the
 *    property the whole "new opcode rather than a longer PROG_RUN"
 *    decision rests on;
 *  - the client never sends it where the server's device cannot take
 *    it, which needs no test here because the image does not LOAD
 *    against such a device - and that refusal is device_test's.
 */
static void program_bank_tests(cft_device *sw, cft_device *rm)
{
    void *hw = cft_device_backend(rm);
    const size_t esz = 4;                     /* fp32 */
    uint8_t img[56], bank[2][8], a[16 * 4];
    uint8_t d_rm[16 * 4], d_sw[16 * 4];
    uint32_t c_rm[16], c_sw[16];
    uint64_t ins[3];
    cft_program *pr = NULL, *ps = NULL;
    uint8_t *resp = NULL;
    size_t len = 0, i;
    int status, b;
    cft_caps c;

    memset(&c, 0, sizeof c);
    c.struct_size = sizeof c;
    cft_get_caps(rm, &c);

    printf("the constant bank over the wire:\n");
    if (!(c.seq_features & CFT_SEQ_FEAT_BANK_PTR)) {
        printf("  the server's device does not publish BANK_PTR "
               "(seq_features 0x%lx), NOT TESTED\n",
               (unsigned long)c.seq_features);
        return;
    }

    /* r4 = r0 * k[0] + k[1]; deposit r4; halt - both constants from
     * the bank, so nothing about the answer survives losing it. */
    ins[0] = 0u | (4ull << 8) | (1ull << 20) | (1ull << 28) | (1ull << 29);
    ins[1] = 3ull | (4ull << 12) | (1ull << 31);
    ins[2] = 0ull | (1ull << 31);
    memset(img, 0, sizeof img);
    cftr_put32(img + 0, 0x50544643u);          /* "CFTP" */
    cftr_put32(img + 4, 1);
    cftr_put32(img + 8, 3);                    /* n_insns */
    cftr_put32(img + 12, 2);                   /* n_consts, addressed only */
    cftr_put32(img + 16, 1);                   /* max_deposits */
    cftr_put32(img + 20, 0);                   /* fp32 */
    cftr_put32(img + 24, CFT_PROG_FLAG_BANK_EXT);
    cftr_put32(img + 28, 0);
    for (i = 0; i < 3; i++)
        cftr_put64(img + 32 + i * 8, ins[i]);

    cftr_put32(bank[0] + 0, 0x3fc00000u);      /* 1.5  */
    cftr_put32(bank[0] + 4, 0x3fa00000u);      /* 1.25 */
    cftr_put32(bank[1] + 0, 0x3fa00000u);      /* the same two, swapped */
    cftr_put32(bank[1] + 4, 0x3fc00000u);
    fill_normal(a, 16, 0);

    CHECK(cft_program_load(rm, img, 32 + 3 * 8, &pr) == CFT_OK && pr,
          "a BANK_EXT image loads on the remote handle: %s",
          cft_last_error());
    CHECK(cft_program_load(sw, img, 32 + 3 * 8, &ps) == CFT_OK && ps,
          "and on the local software one");
    if (!pr || !ps) {
        cft_program_free(pr);
        cft_program_free(ps);
        return;
    }
    for (b = 0; b < 2; b++) {
        uint32_t f_rm = 0, f_sw = 0, s_rm = 0, s_sw = 0;
        memset(d_rm, 0x5a, sizeof d_rm);
        memset(d_sw, 0xa5, sizeof d_sw);
        CHECK(cft_program_run_bank(pr, bank[b], 8, a, NULL, NULL, d_rm,
                                   c_rm, 16, &f_rm, &s_rm) == CFT_OK,
              "run_bank %d over the wire: %s", b, cft_last_error());
        CHECK(cft_program_run_bank(ps, bank[b], 8, a, NULL, NULL, d_sw,
                                   c_sw, 16, &f_sw, &s_sw) == CFT_OK,
              "run_bank %d locally", b);
        CHECK(memcmp(d_rm, d_sw, 16 * esz) == 0 &&
              memcmp(c_rm, c_sw, sizeof c_rm) == 0 &&
              f_rm == f_sw && s_rm == s_sw,
              "bank %d: the server and this process agree, bits, counts and "
              "flags (%02x/%02x)", b, f_rm, f_sw);
    }
    /* And the two banks did not give the same answer, which is what
     * fails if the bank never left this process. */
    {
        uint8_t d0[16 * 4];
        memcpy(d0, d_rm, sizeof d0);
        CHECK(cft_program_run_bank(pr, bank[0], 8, a, NULL, NULL, d_rm,
                                   NULL, 16, NULL, NULL) == CFT_OK &&
              memcmp(d0, d_rm, 16 * esz) != 0,
              "two banks, two answers over the wire");
    }
    /* A BANK_EXT program still refuses PROG_RUN's entry point. */
    CHECK(cft_program_run(pr, a, NULL, NULL, d_rm, NULL, 16, NULL, NULL) ==
          CFT_ERR_INVALID_ARGUMENT,
          "a BANK_EXT program refuses cft_program_run on a remote handle");
    cft_program_free(pr);
    cft_program_free(ps);

    /* The versioning claim, tested from the only side this process
     * can: an opcode the server does not serve is the OPERATION's
     * failure and not a broken stream - CFT_ERR_UNSUPPORTED, a message
     * naming the opcode, and a connection that answers the next
     * request. That is exactly what a pre-0.9 server does with
     * PROG_RUN_BANK, and it is why the message got a new opcode
     * instead of four more bytes in PROG_RUN's payload. */
    CHECK(!cftr_request(hw, 0x00A0u, NULL, 0, &status, &resp, &len) &&
          status == CFT_ERR_UNSUPPORTED,
          "an opcode this server does not serve is refused, not fatal "
          "(status %d)", status);
    free(resp);
    resp = NULL;
    CHECK(!cftr_request(hw, CFTR_OP_STATS, NULL, 0, &status, &resp, &len) &&
          status == CFT_OK,
          "and the connection is still there afterwards");
    free(resp);
    printf("  two banks, two answers; an unserved opcode is refused by "
           "name and the connection survives\n");
}

/* ---- the per-run scratch block over the wire (ABI 0.10) ----------------- *
 *
 * PROG_RUN_EX, docs/REMOTE.md's newest message again. The claims are
 * the bank's, one call further along, plus the one that is new:
 *
 *  - the block crosses in BOTH directions and is LANE-MAJOR, so the
 *    run is done over 96 lanes - more than one 64-lane block here and
 *    more than one chunk's worth is not needed to catch the slicing,
 *    since the client cuts the block by lane and a client that cut it
 *    by bytes would hand the wrong lanes their slots;
 *  - the answer equals the same program run locally, bits, counts,
 *    flags and status;
 *  - a resumable run: the state that came back goes in again, and two
 *    runs of three doublings equal one run of six. Doubling is exact,
 *    so the comparison is memcmp and not a tolerance;
 *  - and the frame's own layout, asserted by building a PROG_RUN_EX
 *    payload BY HAND rather than inferring it from the answer.
 */
static void program_scratch_tests(cft_device *sw, cft_device *rm)
{
    void *hw = cft_device_backend(rm);
    const size_t esz = 4;                     /* fp32 */
    const size_t N = 96;
    uint8_t img[96];
    uint8_t *a, *sin_buf, *sout_rm, *sout_sw, *d_rm, *d_sw, *state, *once;
    uint32_t *c_rm, *c_sw;
    uint64_t ins[7];
    cft_program *pr = NULL, *ps = NULL;
    cft_run_args A;
    size_t i;
    cft_caps c;

    memset(&c, 0, sizeof c);
    c.struct_size = sizeof c;
    cft_get_caps(rm, &c);

    printf("the per-run scratch block over the wire:\n");
    if (!(c.seq_features & CFT_SEQ_FEAT_SCRATCH_IO)) {
        printf("  the server's device does not publish SCRATCH_IO "
               "(seq_features 0x%lx), NOT TESTED\n",
               (unsigned long)c.seq_features);
        return;
    }
    printf("  max_scratch %lu\n", (unsigned long)c.max_scratch);

    a        = (uint8_t *)malloc(N * esz);
    sin_buf  = (uint8_t *)malloc(N * 2 * esz);
    sout_rm  = (uint8_t *)malloc(N * 2 * esz);
    sout_sw  = (uint8_t *)malloc(N * 2 * esz);
    d_rm     = (uint8_t *)malloc(N * esz);
    d_sw     = (uint8_t *)malloc(N * esz);
    state    = (uint8_t *)malloc(N * esz);
    once     = (uint8_t *)malloc(N * esz);
    c_rm     = (uint32_t *)malloc(N * 4);
    c_sw     = (uint32_t *)malloc(N * 4);
    if (!a || !sin_buf || !sout_rm || !sout_sw || !d_rm || !d_sw ||
        !state || !once || !c_rm || !c_sw) {
        printf("  FAIL: out of memory\n");
        goto out;
    }

    /* LDL r4 <- slot 1; deposit r4; STL r0 -> slot 0; STL r4 -> slot 1;
     * halt. Two slots in, two out, and the deposit is the second
     * preloaded slot - so a block delivered a lane early, transposed,
     * or read from the first lane for every lane gives a different
     * answer in at least one of the three places. */
    ins[0] = 7ull  | (4ull << 8)  | (1ull << 31) | (1ull << 32);   /* LDL */
    ins[1] = 3ull  | (4ull << 12) | (1ull << 31);                  /* DEP */
    ins[2] = 6ull  | (0ull << 12) | (1ull << 31) | (0ull << 32);   /* STL */
    ins[3] = 6ull  | (4ull << 12) | (1ull << 31) | (1ull << 32);   /* STL */
    ins[4] = 0ull  | (1ull << 31);                                 /* HALT */
    memset(img, 0, sizeof img);
    cftr_put32(img + 0, 0x50544643u);
    cftr_put32(img + 4, 1);
    cftr_put32(img + 8, 5);                    /* n_insns */
    cftr_put32(img + 12, 0);
    cftr_put32(img + 16, 1);                   /* max_deposits */
    cftr_put32(img + 20, 0);                   /* fp32 */
    cftr_put32(img + 24, CFT_PROG_FLAG_SCRATCH_IO);
    cftr_put32(img + 28, 2u | (2u << 16));     /* 2 in, 2 out */
    for (i = 0; i < 5; i++)
        cftr_put64(img + 32 + i * 8, ins[i]);

    fill_normal(a, N, 0);
    fill_normal(sin_buf, N * 2, 0);

    CHECK(cft_program_load(rm, img, 32 + 5 * 8, &pr) == CFT_OK && pr,
          "a SCRATCH_IO image loads on the remote handle: %s",
          cft_last_error());
    CHECK(cft_program_load(sw, img, 32 + 5 * 8, &ps) == CFT_OK && ps,
          "and on the local software one");
    if (!pr || !ps)
        goto out;

    {
        uint32_t f_rm = 0, f_sw = 0, s_rm = 0, s_sw = 0;
        memset(sout_rm, 0x5a, N * 2 * esz);
        memset(sout_sw, 0xa5, N * 2 * esz);
        memset(&A, 0, sizeof A);
        A.struct_size       = sizeof A;
        A.a                 = a;
        A.n                 = N;
        A.deposits          = d_rm;
        A.counts            = c_rm;
        A.scratch_in        = sin_buf;
        A.scratch_in_bytes  = N * 2 * esz;
        A.scratch_out       = sout_rm;
        A.scratch_out_bytes = N * 2 * esz;
        A.flags_out         = &f_rm;
        A.bus_out           = &s_rm;
        CHECK(cft_program_run_ex(pr, &A) == CFT_OK,
              "run_ex over the wire: %s", cft_last_error());
        A.deposits    = d_sw;
        A.counts      = c_sw;
        A.scratch_out = sout_sw;
        A.flags_out   = &f_sw;
        A.bus_out     = &s_sw;
        CHECK(cft_program_run_ex(ps, &A) == CFT_OK, "and locally");
        CHECK(memcmp(d_rm, d_sw, N * esz) == 0 &&
              memcmp(sout_rm, sout_sw, N * 2 * esz) == 0 &&
              memcmp(c_rm, c_sw, N * 4) == 0 &&
              f_rm == f_sw && s_rm == s_sw,
              "the server and this process agree over %lu lanes - deposits, "
              "the scratch-out block, counts, flags and status",
              (unsigned long)N);
        /* And the block really did cross, both ways: the deposit is
         * lane i's own slot 1 and the scratch-out is lane i's own r0
         * and r4. A block that never left this process, or that
         * handed every chunk the first lanes' slots, fails here. */
        {
            int bad = 0;
            for (i = 0; i < N; i++)
                if (memcmp(d_rm + i * esz, sin_buf + (2 * i + 1) * esz,
                           esz) != 0 ||
                    memcmp(sout_rm + (2 * i) * esz, a + i * esz, esz) != 0 ||
                    memcmp(sout_rm + (2 * i + 1) * esz,
                           sin_buf + (2 * i + 1) * esz, esz) != 0)
                    bad = 1;
            CHECK(!bad, "each lane got its own slots, lane-major, over the "
                        "wire");
        }
    }

    /* A SCRATCH_IO program refuses the two older entry points on a
     * remote handle too - the refusal is the library's and reaches no
     * frame, which is the point: it costs no round trip. */
    CHECK(cft_program_run(pr, a, NULL, NULL, d_rm, NULL, N, NULL, NULL) ==
          CFT_ERR_INVALID_ARGUMENT,
          "a SCRATCH_IO program refuses cft_program_run remotely");
    cft_program_free(pr);
    cft_program_free(ps);
    pr = ps = NULL;

    /* The resumable claim, over the wire. */
    ins[0] = 7ull | (4ull << 8)  | (1ull << 31) | (0ull << 32);   /* LDL 0 */
    ins[1] = 1ull | (1ull << 31);                                 /* REPEAT */
    ins[2] = 1ull | (4ull << 8) | (4ull << 12) | (4ull << 20);    /* r4+=r4 */
    ins[3] = 2ull | (1ull << 31);                                 /* ENDREP */
    ins[4] = 6ull | (4ull << 12) | (1ull << 31) | (0ull << 32);   /* STL 0 */
    ins[5] = 3ull | (4ull << 12) | (1ull << 31);                  /* DEP */
    ins[6] = 0ull | (1ull << 31);                                 /* HALT */
    cftr_put32(img + 8, 7);
    cftr_put32(img + 28, 1u | (1u << 16));     /* 1 in, 1 out */
    {
        int step;
        for (step = 0; step < 2; step++) {
            const uint64_t trips = step ? 6u : 3u;
            ins[1] = 1ull | (1ull << 31) | (trips << 32);
            for (i = 0; i < 7; i++)
                cftr_put64(img + 32 + i * 8, ins[i]);
            if (cft_program_load(rm, img, 32 + 7 * 8, &pr) != CFT_OK) {
                CHECK(0, "the resumable image loads remotely: %s",
                      cft_last_error());
                break;
            }
            memset(&A, 0, sizeof A);
            A.struct_size       = sizeof A;
            A.a                 = a;
            A.n                 = N;
            A.deposits          = d_rm;
            A.scratch_in        = a;
            A.scratch_in_bytes  = N * esz;
            A.scratch_out       = step ? once : state;
            A.scratch_out_bytes = N * esz;
            CHECK(cft_program_run_ex(pr, &A) == CFT_OK,
                  "%llu doublings over the wire: %s",
                  (unsigned long long)trips, cft_last_error());
            if (step == 0) {
                A.scratch_in  = state;
                A.scratch_out = sout_rm;
                CHECK(cft_program_run_ex(pr, &A) == CFT_OK,
                      "and the run resumed from what came back: %s",
                      cft_last_error());
            }
            cft_program_free(pr);
            pr = NULL;
        }
        CHECK(memcmp(sout_rm, once, N * esz) == 0,
              "two runs of three doublings, chained through the block over "
              "the wire, equal one run of six");
        CHECK(memcmp(state, once, N * esz) != 0,
              "and three doublings are not six, so that comparison proves "
              "something");
    }

    /* The frame's own layout, built by hand: handle, present, counts,
     * bank_bytes, n, then the two slot counts, then the scratch-in
     * block, then the operands. Inferring the layout from an answer
     * the same client produced would prove only that the client
     * agrees with itself. */
    {
        uint8_t *req;
        uint8_t *resp = NULL;
        size_t len = 0, k = 4, req_len;
        int status;
        uint32_t handle = 0;

        /* one lane block's worth is unnecessary here; four lanes is
         * enough for a layout, and the layout is what is under test */
        if (cft_program_load(rm, img, 32 + 7 * 8, &pr) == CFT_OK) {
            /* the handle the server holds is the one the client's last
             * run established, which STATS cannot report - so this
             * runs the program once through the library to establish
             * it, then asks the raw frame with handle 1, which is the
             * first slot a connection hands out. */
            memset(&A, 0, sizeof A);
            A.struct_size       = sizeof A;
            A.a                 = a;
            A.n                 = k;
            A.deposits          = d_rm;
            A.scratch_in        = a;
            A.scratch_in_bytes  = k * esz;
            A.scratch_out       = sout_rm;
            A.scratch_out_bytes = k * esz;
            if (cft_program_run_ex(pr, &A) == CFT_OK) {
                handle = 1;
                req_len = 32 + k * esz + k * esz;
                req = (uint8_t *)malloc(req_len);
                if (req) {
                    cftr_put32(req + 0, handle);
                    cftr_put32(req + 4, 1u);     /* present: a only */
                    cftr_put32(req + 8, 0u);     /* no counts */
                    cftr_put32(req + 12, 0u);    /* no bank */
                    cftr_put64(req + 16, (uint64_t)k);
                    cftr_put32(req + 24, 1u);    /* n_scratch_in */
                    cftr_put32(req + 28, 1u);    /* n_scratch_out */
                    memcpy(req + 32, a, k * esz);
                    memcpy(req + 32 + k * esz, a, k * esz);
                    CHECK(!cftr_request(hw, CFTR_OP_PROG_RUN_EX, req,
                                        req_len, &status, &resp, &len) &&
                          status == CFT_OK &&
                          len == 8 + k * esz + k * esz,
                          "a hand-built PROG_RUN_EX frame is served "
                          "(status %d, %lu bytes)", status,
                          (unsigned long)len);
                    if (resp && len == 8 + k * esz + k * esz)
                        CHECK(memcmp(resp + 8 + k * esz, sout_rm,
                                     k * esz) == 0,
                              "and its scratch-out block is the one the "
                              "library's own call produced");
                    free(resp);
                    free(req);
                }
            }
            cft_program_free(pr);
            pr = NULL;
        }
    }
    printf("  the block crosses both ways lane-major, a run resumes, and "
           "the frame's layout is asserted by hand\n");

out:
    cft_program_free(pr);
    cft_program_free(ps);
    free(a); free(sin_buf); free(sout_rm); free(sout_sw);
    free(d_rm); free(d_sw); free(state); free(once);
    free(c_rm); free(c_sw);
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
    printf("  %-14s %6s %8s %9s %8s %7s %9s %10s\n", "operation", "n", "RUN",
           "PROG_RUN", "REDUCE", "REDSEG", "frames", "ms");

    a = (uint8_t *)malloc(4096 * 32); b = (uint8_t *)malloc(4096 * 32);
    d = (uint8_t *)malloc(4096 * 32);
    for (i = 0; i < 3; i++) {
        const size_t n = ns[i];
        int k;
        fill_normal(a, n, CFT_FP64);
        fill_normal(b, n, CFT_FP64);
        for (k = 0; k < 8; k++) {
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
            case 7: name = "reduce_seg";
                /* eight segments, or one: one REDUCE_SEG frame either way */
                st = cft_reduce_seg(rm, CFT_SUM, CFT_FP64, CFT_RNE, a, NULL, d,
                                    n, n >= 8 ? n / 8 : 1, &fl, NULL);
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
            printf("  %-14s %6lu %8llu %9llu %8llu %7llu %9llu %10.2f\n", name,
                   (unsigned long)n,
                   (unsigned long long)(s1.op[CFTR_OP_RUN] - s0.op[CFTR_OP_RUN]),
                   (unsigned long long)(s1.op[CFTR_OP_PROG_RUN] - s0.op[CFTR_OP_PROG_RUN]),
                   (unsigned long long)(s1.op[CFTR_OP_REDUCE] - s0.op[CFTR_OP_REDUCE]),
                   (unsigned long long)(s1.op[CFTR_OP_REDUCE_SEG] - s0.op[CFTR_OP_REDUCE_SEG]),
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
        caps_block_tests(rm, sw);
        protocol_tests(rm);
        program_bank_tests(sw, rm);
        program_scratch_tests(sw, rm);
        identity_tests(sw, rm, n);
    } else {
        bench(rm);
    }

    cft_close(rm);
    cft_close(sw);
    printf("%d checks, %d failures\n", checks, failures);
    return failures ? 1 : 0;
}
