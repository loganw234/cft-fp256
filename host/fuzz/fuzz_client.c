/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The client side of docs/REMOTE.md against a server that lies.
 *
 * backend_remote.c's response parsing is reached through a socket, so
 * this harness gives it one: a socketpair whose far end has already
 * been filled with the fuzzer's bytes and then half-closed, so every
 * recv either returns those bytes or EOF and nothing ever blocks. The
 * client's own requests go the other way into a buffer nobody reads,
 * which is what a socket buffer is for.
 *
 * The file is included rather than linked for the same reason
 * fuzz_serve.c includes the server: `rdev` and `do_request` are
 * static, and a handle the fuzzer can point at a socket of its own is
 * the whole harness. No diff to the file under test.
 *
 * Four modes, chosen by the input's first byte:
 *   0  cftr_recv_frame alone - magic, version, reserved word, ABI,
 *      the length cap, the crc. The server reads frames with the same
 *      function, so this covers both ends' framing.
 *   1  cft_run's chunked reply: the length the client demands back
 *   2  cft_reduce's reply
 *   3  a program: PROG_LOAD's 16-byte answer, then PROG_RUN's
 *
 * The second byte says how much of the staged stream to repair - magic,
 * version and ABI, the length field, the id and opcode, the crc - so
 * the fuzzer can reach both the frames a client accepts and every
 * reason it has for refusing one.
 */

#include "../src/backend_remote.c"

#include <sys/socket.h>
#include <unistd.h>

#include "cft_fuzz.h"

/* A program of one instruction: halt. Built once, so ensure_program
 * has something real to send. */
static uint8_t g_image[40];
static size_t  g_image_bytes;

static void init(void)
{
    uint8_t *p = g_image;
    memset(g_image, 0, sizeof g_image);
    cftr_put32(p + 0, 0x50544643u);           /* "CFTP" */
    cftr_put32(p + 4, 1u);                    /* version */
    cftr_put32(p + 8, 1u);                    /* one instruction */
    cftr_put32(p + 12, 0u);                   /* no constants */
    cftr_put32(p + 16, 1u);                   /* one deposit slot */
    cftr_put32(p + 20, 0u);                   /* fp32 */
    cftr_put64(p + 32, (uint64_t)1u << 31);   /* ctrl | halt */
    g_image_bytes = 40;
}

/* Walk the staged byte stream as frames and put each one into a shape
 * the client will read. */
static void stage(uint8_t *s, size_t len, const uint16_t *ops, int nops,
                  unsigned patch, uint32_t abi)
{
    size_t off = 0;
    int k = 0;
    while (off + CFTR_HDR_BYTES <= len && k <= 8) {
        uint8_t *h = s + off;
        uint32_t plen, crc;
        size_t avail = len - off - CFTR_HDR_BYTES;

        if (patch & 1u)
            cftr_put32(h + 0, CFTR_MAGIC);
        if (patch & 2u) {
            cftr_put16(h + 4, CFTR_PROTO_VERSION);
            cftr_put32(h + 28, 0);
            cftr_put32(h + 8, abi);
        }
        plen = cftr_get32(h + 20);
        if (plen > avail || (patch & 4u)) {
            plen = (uint32_t)(plen % (avail + 1u));
            cftr_put32(h + 20, plen);
        }
        if (patch & 8u) {
            cftr_put32(h + 12, (uint32_t)k + 1u);          /* id */
            cftr_put16(h + 16, ops[k < nops ? k : nops - 1]);
            if (cftr_get16(h + 6) > CFTR_KIND_REFUSAL)
                cftr_put16(h + 6, CFTR_KIND_RESPONSE);
        }
        if (patch & 16u) {
            cftr_put32(h + 24, 0);
            crc = cftr_crc32(0, h, CFTR_HDR_BYTES);
            if (plen)
                crc = cftr_crc32(crc, h + CFTR_HDR_BYTES, plen);
            cftr_put32(h + 24, crc);
        }
        off += CFTR_HDR_BYTES + plen;
        k++;
    }
}

static void run(const uint8_t *data, size_t len)
{
    static const uint16_t ops_run[]  = { CFTR_OP_RUN, CFTR_OP_RUN,
                                         CFTR_OP_RUN, CFTR_OP_RUN };
    static const uint16_t ops_red[]  = { CFTR_OP_REDUCE };
    static const uint16_t ops_prog[] = { CFTR_OP_PROG_LOAD,
                                         CFTR_OP_PROG_RUN,
                                         CFTR_OP_PROG_RUN };
    const uint16_t *ops;
    int nops;
    uint8_t *s;
    int sv[2], mode;
    unsigned patch;
    rdev R;
    uint32_t flags = 0, bus = 0;

    if (len < 4)
        return;
    mode  = data[0] & 3;
    patch = data[1] & 31u;

    memset(&R, 0, sizeof R);
    R.abi = cft_abi_version();
    R.next_id = 0;
    snprintf(R.url, sizeof R.url, "cft://fuzz:1");

    switch (mode) {
    case 2:  ops = ops_red;  nops = 1; break;
    case 3:  ops = ops_prog; nops = 3; break;
    default: ops = ops_run;  nops = 4; break;
    }

    s = (uint8_t *)malloc(len);
    if (!s)
        return;
    memcpy(s, data, len);
    stage(s + 2, len - 2, ops, nops, patch, R.abi);

    if (socketpair(AF_UNIX, SOCK_STREAM, 0, sv) != 0) {
        free(s);
        return;
    }
    if (write(sv[1], s + 2, len - 2) < 0) {
        /* longer than the socket buffer: test what did fit */
    }
    shutdown(sv[1], SHUT_WR);
    R.s = (cftr_sock)sv[0];

    switch (mode) {
    case 1: {
        uint8_t a[16], d[16];
        memset(a, 0, sizeof a);
        cftr_run(&R, CFT_ADD, CFT_FP32, CFT_RNE, a, a, NULL, d, 4,
                 &flags, &bus);
        break;
    }
    case 2: {
        uint8_t a[16], d[4];
        memset(a, 0, sizeof a);
        cftr_reduce(&R, CFT_SUM, CFT_FP32, CFT_RNE, a, NULL, d, 4,
                    &flags, &bus);
        break;
    }
    case 3: {
        uint8_t a[16], dep[16];
        uint32_t counts[4];
        memset(a, 0, sizeof a);
        /* No bank: the seed image carries its own constants. The
         * banked path (PROG_RUN_BANK, ABI 0.9) is exercised by
         * fuzz_serve's corpus from the other side of the wire, which
         * is where a malformed one can do damage. */
        cftr_program_run(&R, CFT_FP32, g_image, g_image_bytes, NULL, 0, 1,
                         a, NULL, NULL, dep, counts, 4, &flags, &bus);
        break;
    }
    default: {
        int i;
        for (i = 0; i < 8; i++) {
            cftr_hdr h;
            uint8_t *payload = NULL;
            char why[384];
            int rc = cftr_recv_frame(R.s, &h, &payload, R.abi, why,
                                     sizeof why);
            free(payload);
            if (rc)
                break;
        }
        break;
    }
    }

    free(R.pimg);
    close(sv[0]);
    close(sv[1]);
    free(s);
}

static const cft_fuzz_target target = {
    "client", init, run, NULL, 16384
};

int main(int argc, char **argv)
{
    return cft_fuzz_main(argc, argv, &target);
}
