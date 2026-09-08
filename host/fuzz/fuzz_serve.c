/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The server side of docs/REMOTE.md, in process.
 *
 * cft-serve's request handlers are static, and the smallest possible
 * diff to fuzz them is no diff at all: this file includes the server
 * whole, with its main() renamed out of the way, and calls the
 * handlers directly. Two other agents are editing that file today
 * (a WebSocket layer, the HELLO caps block); including it rather than
 * refactoring it keeps this harness out of both their ways.
 *
 * An input is a sequence of requests
 *
 *     u16 op | u32 length | length bytes of payload
 *
 * against ONE connection, so the state a single frame cannot reach -
 * BUF_WRITE into a buffer BUF_ALLOC made, PROG_RUN against a handle
 * PROG_LOAD returned - is reachable. The socket is not involved: the
 * handlers take (payload, length) and fill an `answer`, and the frame
 * layer around them is fuzz_frame's target.
 *
 * One harness-side policy, stated because it changes what is tested:
 * REPEAT immediates inside a PROG_LOAD image are clamped to 1..8
 * before the image is loaded. A validated program may legally
 * describe 2^40 instructions, so without the clamp the fuzzer's
 * budget goes into legitimate long runs rather than into decode
 * paths. What the loader ACCEPTS is not touched by this - fuzz_program
 * loads the unclamped images, and does not run them.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define main cft_serve_main_unused
#include "../tools/cft-serve.c"
#undef main

#include "cft_fuzz.h"

#define MAX_REQUESTS 8

static conn g_c;

static void init(void)
{
    memset(&g_c, 0, sizeof g_c);
    g_c.open = 1;
    g_c.s = CFTR_BAD_SOCK;
    g_c.id = 1;
    g_c.open_status = cft_open(NULL, 0, &g_c.dev);
    if (g_c.open_status != CFT_OK) {
        fprintf(stderr, "cft_open(software) failed\n");
        exit(2);
    }
}

/* Everything a connection accumulated, released - but not the device,
 * which is opened once and is not what is under test. */
static void reset(void)
{
    uint32_t i;
    for (i = 0; i < g_c.nprogs; i++)
        cft_program_free(g_c.progs[i]);
    for (i = 0; i < g_c.nbufs; i++)
        cft_buffer_free(g_c.bufs[i]);
    free(g_c.progs);
    free(g_c.bufs);
    free(g_c.buf_bytes);
    g_c.progs = NULL;
    g_c.bufs = NULL;
    g_c.buf_bytes = NULL;
    g_c.nprogs = g_c.nbufs = 0;
    g_c.hello_done = 0;
    memset(g_c.op_count, 0, sizeof g_c.op_count);
    g_c.requests = g_c.bytes_in = g_c.bytes_out = 0;
}

static uint64_t get64(const uint8_t *p)
{
    return (uint64_t)cftr_get32(p) | ((uint64_t)cftr_get32(p + 4) << 32);
}

static void put64(uint8_t *p, uint64_t v)
{
    cftr_put32(p, (uint32_t)v);
    cftr_put32(p + 4, (uint32_t)(v >> 32));
}

/* See the header comment: keep loops short so the fuzzer measures
 * decoding rather than arithmetic. */
static void clamp_repeats(uint8_t *img, size_t len)
{
    uint32_t n_insns, n_consts, prec, esz;
    size_t off, i;
    if (len < 32)
        return;
    if (cftr_get32(img) != 0x50544643u)
        return;
    n_insns  = cftr_get32(img + 8);
    n_consts = cftr_get32(img + 12);
    prec     = cftr_get32(img + 20);
    if (prec > 3)
        return;
    esz = 4u << prec;
    off = 32u + (size_t)n_consts * esz;
    if (off > len || (len - off) / 8u < n_insns)
        return;
    for (i = 0; i < n_insns; i++) {
        uint8_t *w = img + off + i * 8u;
        uint64_t v = get64(w);
        if (((v >> 31) & 1u) && (v & 0xFFu) == 1u) {   /* ctrl, REPEAT */
            uint32_t imm = (uint32_t)(v >> 32) & 7u;
            if (!imm)
                imm = 1;
            put64(w, (v & 0xFFFFFFFFull) | ((uint64_t)imm << 32));
        }
    }
}

/* The second harness-side policy, and for the same reason as the
 * first. RUN, REDUCE and PROG_RUN check the payload's length against
 * `n` and the operand mask - but a mask of zero names no operands, so
 * with an UNASSIGNED opcode (cft_sf_op_operands: no operands, a
 * defined canonical-qNaN result) twenty-four bytes legitimately ask
 * for 2^25 fp256 elements. That is a real property of the protocol and
 * it is written up in docs/VALIDATION.md and docs/REMOTE.md; here it
 * is just half an hour of arithmetic per input, so an operand-less
 * request has its lane count trimmed. A request that DOES name an
 * operand is untouched: its length already bounds n. */
static void clamp_lanes(uint8_t *p, size_t len, int prog_run)
{
    uint64_t n;
    if (len < 24)
        return;
    if (cftr_get32(p + (prog_run ? 4 : 12)) != 0)     /* operand mask */
        return;
    n = get64(p + 16);
    if (n > 4096u)
        put64(p + 16, n & 4095u);
}

static void one_request(uint16_t op, uint8_t *p, size_t len)
{
    answer A;
    memset(&A, 0, sizeof A);
    A.status = CFT_ERR_INTERNAL;
    g_c.requests++;
    if (op < 256)
        g_c.op_count[op]++;

    switch (op) {
    case CFTR_OP_HELLO:
    case CFTR_OP_CAPS:
        if (len == 0 && g_c.dev) {
            A.resp = (uint8_t *)malloc(CFTR_CAPS_BYTES);
            if (A.resp) {
                caps_block(&g_c, A.resp);
                A.resp_len = CFTR_CAPS_BYTES;
                A.status = CFT_OK;
                g_c.hello_done = 1;
            }
        }
        break;
    case CFTR_OP_STATS:      h_stats(&g_c, &A); break;
    case CFTR_OP_RUN:
        clamp_lanes(p, len, 0);
        h_run(&g_c, p, len, &A, 0);
        break;
    case CFTR_OP_REDUCE:
        clamp_lanes(p, len, 0);
        h_run(&g_c, p, len, &A, 1);
        break;
    case CFTR_OP_PROG_LOAD:
        clamp_repeats(p, len);
        h_prog_load(&g_c, p, len, &A);
        break;
    case CFTR_OP_PROG_RUN:
        clamp_lanes(p, len, 1);
        h_prog_run(&g_c, p, len, &A, 0);
        break;
    case CFTR_OP_PROG_RUN_BANK:
        /* The same clamp: the lane count is in the same fixed word,
         * and the bank's length is the one that was zero on PROG_RUN
         * - which h_prog_run holds to the payload's own length before
         * it reads a byte of it. */
        clamp_lanes(p, len, 1);
        h_prog_run(&g_c, p, len, &A, 1);
        break;
    case CFTR_OP_PROG_FREE:  h_prog_free(&g_c, p, len, &A); break;
    case CFTR_OP_BUF_ALLOC:  h_buf_alloc(&g_c, p, len, &A); break;
    case CFTR_OP_BUF_FREE:   h_buf_free(&g_c, p, len, &A); break;
    case CFTR_OP_BUF_WRITE:  h_buf_write(&g_c, p, len, &A); break;
    case CFTR_OP_BUF_READ:   h_buf_read(&g_c, p, len, &A); break;
    case CFTR_OP_FLAGS_LOWER:
    case CFTR_OP_FLAGS_RAISE:
    case CFTR_OP_FLAGS_TEST:
    case CFTR_OP_FLAGS_SAVE:
    case CFTR_OP_FLAGS_RESTORE:
    case CFTR_OP_FLAGS_TEST_SAVED:
        h_flags(&g_c, op, p, len, &A);
        break;
    default:
        break;
    }
    /* The reply the server would serialise, touched the way
     * send_reply would touch it. */
    if (A.status == CFT_OK && A.resp && A.resp_len) {
        volatile uint32_t sink = 0;
        size_t i;
        for (i = 0; i < A.resp_len; i++)
            sink ^= A.resp[i];
        (void)sink;
    }
    free(A.resp);
}

static void run(const uint8_t *data, size_t len)
{
    size_t off = 0;
    int nreq = 0;

    while (off + 6 <= len && nreq < MAX_REQUESTS) {
        uint16_t op = cftr_get16(data + off);
        uint32_t plen = cftr_get32(data + off + 2);
        uint8_t *copy;
        off += 6;
        if (plen > len - off)
            plen = (uint32_t)(len - off);
        /* A private copy: h_buf_write and h_prog_load are handed
         * bytes the frame layer malloc'd, and clamp_repeats writes to
         * them. */
        copy = (uint8_t *)malloc(plen ? plen : 1);
        if (!copy)
            return;
        memcpy(copy, data + off, plen);
        one_request(op, copy, plen);
        free(copy);
        off += plen;
        nreq++;
    }
    reset();
}

/* Most of a random input names an opcode that does not exist. Steer
 * the first two bytes of each record onto the sixteen that do, most of
 * the time. */
static const uint16_t OPS[] = {
    CFTR_OP_HELLO, CFTR_OP_CAPS, CFTR_OP_STATS, CFTR_OP_RUN,
    CFTR_OP_REDUCE, CFTR_OP_PROG_LOAD, CFTR_OP_PROG_RUN,
    CFTR_OP_PROG_FREE, CFTR_OP_BUF_ALLOC, CFTR_OP_BUF_FREE,
    CFTR_OP_BUF_WRITE, CFTR_OP_BUF_READ, CFTR_OP_FLAGS_LOWER,
    CFTR_OP_FLAGS_RAISE, CFTR_OP_FLAGS_TEST, CFTR_OP_FLAGS_SAVE,
    CFTR_OP_FLAGS_RESTORE, CFTR_OP_FLAGS_TEST_SAVED, CFTR_OP_BYE
};

static size_t fixup(uint8_t *d, size_t len, size_t cap, uint64_t *st)
{
    size_t off = 0;
    int nreq = 0;
    (void)cap;
    *st += 0x9E3779B97F4A7C15ull;
    if ((*st >> 61) == 0)
        return len;                       /* sometimes, leave it wrong */
    while (off + 6 <= len && nreq < MAX_REQUESTS) {
        uint32_t plen;
        uint64_t r;
        *st += 0x9E3779B97F4A7C15ull;
        r = *st ^ (*st >> 31);
        if ((r & 15u) != 0)
            cftr_put16(d + off, OPS[r % (sizeof OPS / sizeof OPS[0])]);
        plen = cftr_get32(d + off + 2);
        if (plen > len - off - 6)
            cftr_put32(d + off + 2, (uint32_t)(len - off - 6));
        plen = cftr_get32(d + off + 2);
        off += 6 + plen;
        nreq++;
    }
    return len;
}

static const cft_fuzz_target target = {
    "serve", init, run, fixup, 16384
};

int main(int argc, char **argv)
{
    return cft_fuzz_main(argc, argv, &target);
}
