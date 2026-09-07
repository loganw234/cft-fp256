/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cft-serve - the tile behind a socket (docs/REMOTE.md).
 *
 *     cft-serve [--port N] [--bind ADDR] [--artifact PATH]
 *               [--max-conns N] [--pid-file PATH] [--port-file PATH]
 *               [--ws N] [--ws-port-file PATH] [--verbose]
 *
 * Holds one libcft device per connection - the software backend by
 * default, or the artifact named on the command line, so that the
 * same program fronts the U50C from a Linux box that has it - and
 * serves the device-touching operations over the frame protocol:
 * capabilities, cft_run, cft_reduce, the program load/run/free, the
 * buffer allocate/free/write/read, and the six status-word operations
 * of 754-2019 5.7.4. Everything the library computes on a host is not
 * here, because the client computes it on its own host with its own
 * copy of the library; only what touches a device crosses.
 *
 * Connections are multiplexed with select(), not threads: requests
 * from every open connection are served one at a time, in arrival
 * order, each to completion, so two clients - or one client holding
 * two handles - interleave at request granularity and neither waits
 * for the other to close. Up to MAX_CONNS at once; the listen backlog
 * holds the rest. A connection that starts a frame and then stalls
 * for a minute is dropped, so it cannot hold the others up.
 *
 * --ws N adds a SECOND listener that speaks the same frames inside
 * RFC 6455 WebSocket messages - one message per frame, unchanged - so
 * a browser reaches the tile. It is a second port and not a second
 * protocol on the first, for three reasons, which docs/REMOTE.md
 * states at length: the frame path here is not touched at all and
 * keeps the behaviour its negative control recorded; detecting "GET "
 * on the first bytes would need a peek the socket shim does not
 * expose and a platform branch this file has not got; and a browser
 * will open a WebSocket to a loopback port from any page the person
 * is looking at, so a transport that is reachable from the web is one
 * an operator should have to ask for. Off unless --ws is given.
 *
 * Scope: no authentication, no encryption, 127.0.0.1 unless --bind
 * says otherwise. A transport, not a security boundary; docs/REMOTE.md
 * says so at more length. C99 plus the operating system's socket API,
 * through the shim in libcft.a, so this file has no platform branch of
 * its own except the one that asks the process id - and neither has
 * tools/ws.c, which is written against the same shim.
 *
 * Stopping it: by its PID, which it prints on startup and writes to
 * --pid-file. Never by image name on a shared host.
 */

#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if defined(_WIN32)
#  include <process.h>
#  define SERVE_PID() ((unsigned long)_getpid())
#else
#  include <unistd.h>
#  define SERVE_PID() ((unsigned long)getpid())
#endif

#include "cft.h"
#include "remote.h"
#include "ws.h"

#define MAX_CONNS 32

/* How long a connection may stall in the middle of a frame before it
 * is dropped. Per recv, so a slow link that keeps delivering bytes is
 * never cut; only silence is. */
#define STALL_MS  60000L

/* ---- per-connection state ------------------------------------------ */

typedef struct {
    int           open;
    cftr_sock     s;
    unsigned long id;
    int           ws;               /* frames arrive in WebSocket messages */
    int           ws_pending;       /* its opening handshake is still due */
    ws_conn       w;
    cft_device   *dev;
    cft_status    open_status;      /* why dev is NULL, if it is */
    cft_program **progs;
    uint32_t      nprogs;
    cft_buffer  **bufs;
    uint64_t     *buf_bytes;
    uint32_t      nbufs;
    uint64_t      requests, bytes_in, bytes_out;
    uint64_t      op_count[256];
    int           hello_done;
} conn;

static conn g_conns[MAX_CONNS];
static int  g_verbose;

static void logline(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stdout, fmt, ap);
    va_end(ap);
    fputc('\n', stdout);
    fflush(stdout);
}

/* A growable table of handles: index + 1 is the handle, NULL is a
 * free slot. Small, because a client holds a few programs and a few
 * buffers, not thousands. */
static uint32_t slot_add(void ***table, uint32_t *count, void *item)
{
    uint32_t i;
    void **t = *table;
    for (i = 0; i < *count; i++)
        if (!t[i]) {
            t[i] = item;
            return i + 1;
        }
    t = (void **)realloc(t, (size_t)(*count + 1) * sizeof *t);
    if (!t)
        return 0;
    t[*count] = item;
    *table = t;
    (*count)++;
    return *count;
}

static void *slot_get(void **table, uint32_t count, uint32_t handle)
{
    if (handle == 0 || handle > count)
        return NULL;
    return table[handle - 1];
}

static size_t elem_bytes(uint32_t fmt)
{
    return fmt <= 3 ? cft_format_size((cft_format)fmt) : 0;
}

static unsigned popcount3(uint32_t m)
{
    return (m & 1u) + ((m >> 1) & 1u) + ((m >> 2) & 1u);
}

/* ---- the caps block ------------------------------------------------- */

/* CAPS[15:8] is not in cft_caps, so the opcode groups are derived by
 * asking cft_supports() one representative opcode per group, on a
 * format the device carries - the same question every caller asks. */
static uint32_t derive_op_groups(cft_device *dev, uint32_t format_mask)
{
    static const int rep[7] = { CFT_FMA, CFT_ABS, CFT_MIN, CFT_SELECT,
                                CFT_IAND, CFT_SUM, CFT_RECIP_SEED };
    uint32_t groups = 0;
    int f, g;
    for (f = 0; f < 4; f++)
        if (format_mask & (1u << f))
            break;
    if (f == 4)
        return 0;
    for (g = 0; g < 7; g++)
        if (cft_supports(dev, (cft_op)rep[g], (cft_format)f))
            groups |= 1u << g;
    return groups;
}

static void caps_block(conn *C, uint8_t out[CFTR_CAPS_BYTES])
{
    cft_caps caps;
    memset(out, 0, CFTR_CAPS_BYTES);
    memset(&caps, 0, sizeof caps);
    caps.struct_size = sizeof caps;
    if (!C->dev || cft_get_caps(C->dev, &caps) != CFT_OK)
        return;
    cftr_put32(out + 0, caps.format_mask);
    cftr_put32(out + 4, derive_op_groups(C->dev, caps.format_mask));
    cftr_put32(out + 8, caps.tiles);
    cftr_put32(out + 12, caps.device_version);
    cftr_put32(out + 16, caps.flags_readable ? 1u : 0u);
    cftr_put32(out + 20, caps.abi_version);
    /* NUL-padded, never NUL-less: the block reserves 32 bytes and the
     * name is at most 31 plus its terminator. */
    {
        size_t n = strlen(caps.backend);
        if (n > CFTR_BACKEND_NAME - 1)
            n = CFTR_BACKEND_NAME - 1;
        memcpy(out + 24, caps.backend, n);
    }
}

/* ---- the handlers ------------------------------------------------------ *
 *
 * Each fills *status and, when the status is CFT_OK, *resp with
 * *resp_len (malloc'd); when it is not, the message for the client's
 * cft_last_error(). Returns 0 to answer, or -1 with `why` set to
 * REFUSE: the payload could not be decoded, which is a protocol
 * fault, and the connection ends after the refusal.
 */

typedef struct {
    int      status;
    uint8_t *resp;
    size_t   resp_len;
    char     msg[512];
    char     why[512];
} answer;

static void fail(answer *A, cft_status st, const char *what)
{
    const char *detail = cft_last_error();
    A->status = (int)st;
    snprintf(A->msg, sizeof A->msg, "%s: %s%s%s", what, cft_strerror(st),
             *detail ? " - " : "", *detail ? detail : "");
}

static int no_device(conn *C, answer *A, const char *what)
{
    if (C->dev)
        return 0;
    fail(A, C->open_status, what);
    return 1;
}

static int h_run(conn *C, const uint8_t *p, size_t len, answer *A, int reduce)
{
    uint32_t op, fmt, rnd, present;
    uint64_t n;
    size_t esz, opnd, expect, out_bytes;
    const uint8_t *a = NULL, *b = NULL, *c = NULL, *q;
    uint8_t *d;
    uint32_t flags = 0, bus = 0;
    cft_status st;

    /* four u32 and a u64 before the operands: 24 bytes, as
     * docs/REMOTE.md lays RUN and REDUCE out */
    if (len < 24) {
        snprintf(A->why, sizeof A->why, "%s payload of %lu bytes is shorter "
                 "than its fixed fields", reduce ? "REDUCE" : "RUN",
                 (unsigned long)len);
        return -1;
    }
    op      = cftr_get32(p + 0);
    fmt     = cftr_get32(p + 4);
    rnd     = cftr_get32(p + 8);
    present = cftr_get32(p + 12);
    n       = cftr_get64(p + 16);
    esz     = elem_bytes(fmt);
    if (present & ~7u || (reduce && (present & 4u))) {
        snprintf(A->why, sizeof A->why, "operand mask 0x%x names an operand "
                 "this operation has not got", (unsigned)present);
        return -1;
    }
    if (esz && n > (uint64_t)(CFTR_MAX_PAYLOAD / esz)) {
        snprintf(A->why, sizeof A->why, "n = %llu elements cannot fit a "
                 "frame", (unsigned long long)n);
        return -1;
    }
    opnd   = (size_t)n * esz;
    expect = 24u + (size_t)popcount3(present) * opnd;
    if (len != expect) {
        snprintf(A->why, sizeof A->why, "%s over %llu %s elements with "
                 "operand mask 0x%x should carry %lu bytes, not %lu",
                 reduce ? "REDUCE" : "RUN", (unsigned long long)n,
                 fmt <= 3 ? cft_format_name((cft_format)fmt) : "invalid",
                 (unsigned)present, (unsigned long)expect,
                 (unsigned long)len);
        return -1;
    }
    if (no_device(C, A, reduce ? "cft_reduce" : "cft_run"))
        return 0;
    q = p + 24;
    if (present & 1u) { a = q; q += opnd; }
    if (present & 2u) { b = q; q += opnd; }
    if (present & 4u) { c = q; }

    out_bytes = reduce ? esz : opnd;
    d = (uint8_t *)malloc(8u + (out_bytes ? out_bytes : 1u));
    if (!d) {
        fail(A, CFT_ERR_OUT_OF_MEMORY, "allocating the result");
        return 0;
    }
    if (reduce)
        st = cft_reduce(C->dev, (cft_op)op, (cft_format)fmt, (cft_round)rnd,
                        a, b, d + 8, (size_t)n, &flags, &bus);
    else
        st = cft_run(C->dev, (cft_op)op, (cft_format)fmt, (cft_round)rnd,
                     a, b, c, d + 8, (size_t)n, &flags, &bus);
    if (st != CFT_OK) {
        free(d);
        fail(A, st, reduce ? "cft_reduce" : "cft_run");
        return 0;
    }
    cftr_put32(d + 0, flags);
    cftr_put32(d + 4, bus);
    A->status   = CFT_OK;
    A->resp     = d;
    A->resp_len = 8u + out_bytes;
    return 0;
}

static int h_prog_load(conn *C, const uint8_t *p, size_t len, answer *A)
{
    cft_program *prog = NULL;
    cft_program_info info;
    uint32_t handle;
    cft_status st;

    if (no_device(C, A, "cft_program_load"))
        return 0;
    st = cft_program_load(C->dev, p, len, &prog);
    if (st != CFT_OK) {
        fail(A, st, "cft_program_load");
        return 0;
    }
    memset(&info, 0, sizeof info);
    info.struct_size = sizeof info;
    cft_program_get_info(prog, &info);
    handle = slot_add((void ***)&C->progs, &C->nprogs, prog);
    if (!handle) {
        cft_program_free(prog);
        fail(A, CFT_ERR_OUT_OF_MEMORY, "keeping the program");
        return 0;
    }
    A->resp = (uint8_t *)malloc(16);
    if (!A->resp) {
        fail(A, CFT_ERR_OUT_OF_MEMORY, "answering");
        return 0;
    }
    cftr_put32(A->resp + 0, handle);
    cftr_put32(A->resp + 4, (uint32_t)info.format);
    cftr_put32(A->resp + 8, info.max_deposits);
    cftr_put32(A->resp + 12, 0);
    A->resp_len = 16;
    A->status = CFT_OK;
    return 0;
}

static int h_prog_run(conn *C, const uint8_t *p, size_t len, answer *A)
{
    uint32_t handle, present, want_counts;
    uint64_t n;
    cft_program *prog;
    cft_program_info info;
    size_t esz, opnd, expect, dep_bytes, cnt_bytes, i;
    const uint8_t *a = NULL, *b = NULL, *c = NULL, *q;
    uint8_t *out;
    uint32_t *counts = NULL;
    uint32_t flags = 0, bus = 0;
    cft_status st;

    if (len < 24) {
        snprintf(A->why, sizeof A->why, "PROG_RUN payload of %lu bytes is "
                 "shorter than its fixed fields", (unsigned long)len);
        return -1;
    }
    handle      = cftr_get32(p + 0);
    present     = cftr_get32(p + 4);
    want_counts = cftr_get32(p + 8);
    n           = cftr_get64(p + 16);
    if (present & ~7u) {
        snprintf(A->why, sizeof A->why, "operand mask 0x%x", (unsigned)present);
        return -1;
    }
    prog = (cft_program *)slot_get((void **)C->progs, C->nprogs, handle);
    if (!prog) {
        /* An argument error rather than a protocol one: the frame is
         * well formed, it names a program this connection does not
         * hold. The connection continues. But the length check below
         * needs the program's format, so this answers first. */
        A->status = CFT_ERR_INVALID_ARGUMENT;
        snprintf(A->msg, sizeof A->msg, "no program is held under handle %lu",
                 (unsigned long)handle);
        return 0;
    }
    memset(&info, 0, sizeof info);
    info.struct_size = sizeof info;
    cft_program_get_info(prog, &info);
    esz = elem_bytes((uint32_t)info.format);
    if (n > (uint64_t)(CFTR_MAX_PAYLOAD / esz) ||
        (info.max_deposits &&
         n > (uint64_t)(CFTR_MAX_PAYLOAD / esz / info.max_deposits))) {
        snprintf(A->why, sizeof A->why, "n = %llu lanes cannot fit a frame",
                 (unsigned long long)n);
        return -1;
    }
    opnd   = (size_t)n * esz;
    expect = 24u + (size_t)popcount3(present) * opnd;
    if (len != expect) {
        snprintf(A->why, sizeof A->why, "PROG_RUN over %llu lanes with "
                 "operand mask 0x%x should carry %lu bytes, not %lu",
                 (unsigned long long)n, (unsigned)present,
                 (unsigned long)expect, (unsigned long)len);
        return -1;
    }
    q = p + 24;
    if (present & 1u) { a = q; q += opnd; }
    if (present & 2u) { b = q; q += opnd; }
    if (present & 4u) { c = q; }

    dep_bytes = (size_t)n * info.max_deposits * esz;
    cnt_bytes = want_counts ? (size_t)n * 4u : 0u;
    out = (uint8_t *)malloc(8u + dep_bytes + cnt_bytes + 1u);
    if (!out) {
        fail(A, CFT_ERR_OUT_OF_MEMORY, "allocating the deposits");
        return 0;
    }
    if (want_counts && n) {
        counts = (uint32_t *)malloc((size_t)n * sizeof *counts);
        if (!counts) {
            free(out);
            fail(A, CFT_ERR_OUT_OF_MEMORY, "allocating the counts");
            return 0;
        }
    }
    st = cft_program_run(prog, a, b, c, dep_bytes ? out + 8 : NULL, counts,
                         (size_t)n, &flags, &bus);
    if (st != CFT_OK) {
        free(out);
        free(counts);
        fail(A, st, "cft_program_run");
        return 0;
    }
    cftr_put32(out + 0, flags);
    cftr_put32(out + 4, bus);
    for (i = 0; i < (size_t)(want_counts ? n : 0); i++)
        cftr_put32(out + 8 + dep_bytes + i * 4u, counts[i]);
    free(counts);
    A->status   = CFT_OK;
    A->resp     = out;
    A->resp_len = 8u + dep_bytes + cnt_bytes;
    return 0;
}

static int h_prog_free(conn *C, const uint8_t *p, size_t len, answer *A)
{
    uint32_t handle;
    cft_program *prog;
    if (len != 4) {
        snprintf(A->why, sizeof A->why, "PROG_FREE carries a u32 handle");
        return -1;
    }
    handle = cftr_get32(p);
    prog = (cft_program *)slot_get((void **)C->progs, C->nprogs, handle);
    if (!prog) {
        A->status = CFT_ERR_INVALID_ARGUMENT;
        snprintf(A->msg, sizeof A->msg, "no program is held under handle %lu",
                 (unsigned long)handle);
        return 0;
    }
    cft_program_free(prog);
    C->progs[handle - 1] = NULL;
    A->status = CFT_OK;
    return 0;
}

static int h_buf_alloc(conn *C, const uint8_t *p, size_t len, answer *A)
{
    uint64_t bytes;
    cft_buffer *buf = NULL;
    uint32_t handle;
    cft_status st;
    if (len != 8) {
        snprintf(A->why, sizeof A->why, "BUF_ALLOC carries a u64 size");
        return -1;
    }
    if (no_device(C, A, "cft_alloc"))
        return 0;
    bytes = cftr_get64(p);
    if (bytes > (uint64_t)(size_t)-1 / 2) {
        A->status = CFT_ERR_INVALID_ARGUMENT;
        snprintf(A->msg, sizeof A->msg, "a %llu-byte buffer",
                 (unsigned long long)bytes);
        return 0;
    }
    st = cft_alloc(C->dev, (size_t)bytes, &buf);
    if (st != CFT_OK) {
        fail(A, st, "cft_alloc");
        return 0;
    }
    handle = slot_add((void ***)&C->bufs, &C->nbufs, buf);
    if (!handle) {
        cft_buffer_free(buf);
        fail(A, CFT_ERR_OUT_OF_MEMORY, "keeping the buffer");
        return 0;
    }
    C->buf_bytes = (uint64_t *)realloc(C->buf_bytes,
                                       (size_t)C->nbufs * sizeof(uint64_t));
    if (!C->buf_bytes) {
        fail(A, CFT_ERR_OUT_OF_MEMORY, "keeping the buffer");
        return 0;
    }
    C->buf_bytes[handle - 1] = bytes;
    A->resp = (uint8_t *)malloc(4);
    if (!A->resp) {
        fail(A, CFT_ERR_OUT_OF_MEMORY, "answering");
        return 0;
    }
    cftr_put32(A->resp, handle);
    A->resp_len = 4;
    A->status = CFT_OK;
    return 0;
}

static cft_buffer *buf_lookup(conn *C, uint32_t handle, answer *A)
{
    cft_buffer *buf = (cft_buffer *)slot_get((void **)C->bufs, C->nbufs,
                                             handle);
    if (!buf) {
        A->status = CFT_ERR_INVALID_ARGUMENT;
        snprintf(A->msg, sizeof A->msg, "no buffer is held under handle %lu",
                 (unsigned long)handle);
    }
    return buf;
}

static int h_buf_free(conn *C, const uint8_t *p, size_t len, answer *A)
{
    uint32_t handle;
    cft_buffer *buf;
    if (len != 4) {
        snprintf(A->why, sizeof A->why, "BUF_FREE carries a u32 handle");
        return -1;
    }
    handle = cftr_get32(p);
    buf = buf_lookup(C, handle, A);
    if (!buf)
        return 0;
    cft_buffer_free(buf);
    C->bufs[handle - 1] = NULL;
    A->status = CFT_OK;
    return 0;
}

static int h_buf_write(conn *C, const uint8_t *p, size_t len, answer *A)
{
    uint32_t handle;
    uint64_t offset, bytes;
    cft_buffer *buf;
    if (len < 16) {
        snprintf(A->why, sizeof A->why, "BUF_WRITE is shorter than its "
                 "fixed fields");
        return -1;
    }
    handle = cftr_get32(p);
    offset = cftr_get64(p + 8);
    bytes  = (uint64_t)(len - 16);
    buf = buf_lookup(C, handle, A);
    if (!buf)
        return 0;
    if (offset > C->buf_bytes[handle - 1] ||
        bytes > C->buf_bytes[handle - 1] - offset) {
        A->status = CFT_ERR_INVALID_ARGUMENT;
        snprintf(A->msg, sizeof A->msg, "%llu bytes at offset %llu do not "
                 "fit a %llu-byte buffer", (unsigned long long)bytes,
                 (unsigned long long)offset,
                 (unsigned long long)C->buf_bytes[handle - 1]);
        return 0;
    }
    memcpy((uint8_t *)cft_buffer_data(buf) + offset, p + 16, (size_t)bytes);
    A->status = (int)cft_buffer_to_device(buf);
    if (A->status != CFT_OK)
        fail(A, (cft_status)A->status, "cft_buffer_to_device");
    return 0;
}

static int h_buf_read(conn *C, const uint8_t *p, size_t len, answer *A)
{
    uint32_t handle;
    uint64_t offset, bytes;
    cft_buffer *buf;
    cft_status st;
    if (len != 24) {
        snprintf(A->why, sizeof A->why, "BUF_READ carries handle, offset "
                 "and length");
        return -1;
    }
    handle = cftr_get32(p);
    offset = cftr_get64(p + 8);
    bytes  = cftr_get64(p + 16);
    buf = buf_lookup(C, handle, A);
    if (!buf)
        return 0;
    if (offset > C->buf_bytes[handle - 1] ||
        bytes > C->buf_bytes[handle - 1] - offset ||
        bytes > CFTR_MAX_PAYLOAD) {
        A->status = CFT_ERR_INVALID_ARGUMENT;
        snprintf(A->msg, sizeof A->msg, "%llu bytes at offset %llu do not "
                 "fit a %llu-byte buffer or a frame",
                 (unsigned long long)bytes, (unsigned long long)offset,
                 (unsigned long long)C->buf_bytes[handle - 1]);
        return 0;
    }
    st = cft_buffer_from_device(buf);
    if (st != CFT_OK) {
        fail(A, st, "cft_buffer_from_device");
        return 0;
    }
    A->resp = (uint8_t *)malloc((size_t)bytes + 1u);
    if (!A->resp) {
        fail(A, CFT_ERR_OUT_OF_MEMORY, "answering");
        return 0;
    }
    memcpy(A->resp, (const uint8_t *)cft_buffer_data(buf) + offset,
           (size_t)bytes);
    A->resp_len = (size_t)bytes;
    A->status = CFT_OK;
    return 0;
}

static int h_flags(conn *C, uint16_t op, const uint8_t *p, size_t len,
                   answer *A)
{
    uint32_t v = 0, mask = 0, saved = 0;
    size_t want = (op == CFTR_OP_FLAGS_SAVE) ? 0u
                : (op == CFTR_OP_FLAGS_RESTORE ||
                   op == CFTR_OP_FLAGS_TEST_SAVED) ? 8u : 4u;
    if (len != want) {
        snprintf(A->why, sizeof A->why, "FLAGS op 0x%04x carries %lu bytes, "
                 "not %lu", (unsigned)op, (unsigned long)want,
                 (unsigned long)len);
        return -1;
    }
    if (want == 4)
        mask = cftr_get32(p);
    if (want == 8) {
        saved = cftr_get32(p);
        mask  = cftr_get32(p + 4);
    }
    /* A NULL device is tolerated by all six, by cft.h's own promise,
     * so a connection whose device failed to open still answers. */
    switch (op) {
    case CFTR_OP_FLAGS_LOWER:      cft_lower_flags(C->dev, mask); break;
    case CFTR_OP_FLAGS_RAISE:      cft_raise_flags(C->dev, mask); break;
    case CFTR_OP_FLAGS_TEST:       v = (uint32_t)cft_test_flags(C->dev, mask); break;
    case CFTR_OP_FLAGS_SAVE:       v = cft_save_all_flags(C->dev); break;
    case CFTR_OP_FLAGS_RESTORE:    cft_restore_flags(C->dev, saved, mask); break;
    default:                       v = (uint32_t)cft_test_saved_flags(saved, mask); break;
    }
    if (op == CFTR_OP_FLAGS_TEST || op == CFTR_OP_FLAGS_SAVE ||
        op == CFTR_OP_FLAGS_TEST_SAVED) {
        A->resp = (uint8_t *)malloc(4);
        if (!A->resp) {
            fail(A, CFT_ERR_OUT_OF_MEMORY, "answering");
            return 0;
        }
        cftr_put32(A->resp, v);
        A->resp_len = 4;
    }
    A->status = CFT_OK;
    return 0;
}

static int h_stats(conn *C, answer *A)
{
    uint32_t entries = 0, i;
    uint8_t *q;
    for (i = 0; i < 256; i++)
        if (C->op_count[i])
            entries++;
    A->resp = (uint8_t *)malloc(32u + (size_t)entries * 16u);
    if (!A->resp) {
        fail(A, CFT_ERR_OUT_OF_MEMORY, "answering");
        return 0;
    }
    cftr_put64(A->resp + 0, C->requests);
    cftr_put64(A->resp + 8, C->bytes_in);
    cftr_put64(A->resp + 16, C->bytes_out);
    cftr_put32(A->resp + 24, entries);
    cftr_put32(A->resp + 28, 0);
    q = A->resp + 32;
    for (i = 0; i < 256; i++) {
        if (!C->op_count[i])
            continue;
        cftr_put32(q + 0, i);
        cftr_put32(q + 4, 0);
        cftr_put64(q + 8, C->op_count[i]);
        q += 16;
    }
    A->resp_len = 32u + (size_t)entries * 16u;
    A->status = CFT_OK;
    return 0;
}

/* ---- connections ------------------------------------------------------ */

/* Take a connection into a slot. A WebSocket connection's opening
 * handshake is NOT read here - see below. */
static void conn_open(conn *C, cftr_sock s, unsigned long id,
                      const char *artifact, int is_ws)
{
    cft_caps caps;
    memset(C, 0, sizeof *C);
    C->open = 1;
    C->s = s;
    C->id = id;
    C->ws = is_ws;
    /* The handshake is NOT read here. Reading it would hold this
     * accept until the request head arrives or the stall timeout
     * expires - and every other connection with it, because the loop
     * is one thread. So the connection joins the select set with its
     * handshake still due, and is read when it has something to say,
     * exactly as a frame is. */
    C->ws_pending = is_ws;
    cftr_sock_timeout(s, STALL_MS);
    C->open_status = cft_open(artifact, 0, &C->dev);
    memset(&caps, 0, sizeof caps);
    caps.struct_size = sizeof caps;
    if (C->dev) {
        cft_get_caps(C->dev, &caps);
        logline("connection %lu: opened, device backend %s", id, caps.backend);
    } else {
        logline("connection %lu: opened, but its device did not: %s (%s)",
                id, cft_strerror(C->open_status), cft_last_error());
    }
}

static void conn_close(conn *C)
{
    uint32_t i;
    if (C->ws) {
        ws_send_close(&C->w, 1000);
        ws_conn_free(&C->w);
    }
    for (i = 0; i < C->nprogs; i++)
        cft_program_free(C->progs[i]);
    for (i = 0; i < C->nbufs; i++)
        cft_buffer_free(C->bufs[i]);
    free(C->progs);
    free(C->bufs);
    free(C->buf_bytes);
    cft_close(C->dev);
    cftr_sock_close(C->s);
    memset(C, 0, sizeof *C);
}

static int send_reply(conn *C, const cftr_hdr *req, int kind, int status,
                      const void *payload, size_t len, uint32_t my_abi)
{
    cftr_hdr h;
    memset(&h, 0, sizeof h);
    h.proto  = CFTR_PROTO_VERSION;
    h.kind   = (uint16_t)kind;
    h.abi    = my_abi;
    h.id     = req->id;
    h.op     = req->op;
    h.status = (uint16_t)status;
    /* The frame is the frame either way; the transport is only which
     * of the two sends it. The byte count is the PROTOCOL's, so the
     * counters STATS reports do not move between transports. */
    C->bytes_out += CFTR_HDR_BYTES + len;
    return C->ws ? ws_send_frame(&C->w, &h, payload, len)
                 : cftr_send_frame(C->s, &h, payload, len);
}

/* Read and answer ONE request on a connection select() reported
 * readable. Returns 0 to keep the connection, 1 to close it. */
static int serve_one(conn *C, uint32_t my_abi)
{
    cftr_hdr h;
    uint8_t *p = NULL;
    char why[512];
    answer A;
    int rc;

    if (C->ws_pending) {
        /* The first thing a WebSocket connection has to say is its
         * opening handshake. A failure has already been answered with
         * an HTTP status by ws_handshake, so there is no close frame
         * to send after it. */
        C->ws_pending = 0;
        if (ws_handshake(&C->w, C->s, why, sizeof why)) {
            C->w.peer_closed = 2;
            logline("connection %lu: not a WebSocket handshake, refused: %s",
                    C->id, why);
            return 1;
        }
        /* The Origin is logged and not judged. This server has no
         * authentication, and a browser will open a WebSocket to a
         * loopback port from ANY page the person is looking at, so
         * the log is where that becomes visible. docs/REMOTE.md says
         * what running with --ws means. */
        logline("connection %lu: WebSocket handshake accepted, origin %s",
                C->id, C->w.origin[0] ? C->w.origin : "(none)");
        return 0;
    }
    memset(&h, 0, sizeof h);
    rc = C->ws ? ws_recv_frame(&C->w, &h, &p, my_abi, why, sizeof why)
               : cftr_recv_frame(C->s, &h, &p, my_abi, why, sizeof why);
    if (rc < 0) {
        /* A WebSocket control frame: a ping answered, a pong dropped.
         * No request arrived, so nothing is counted and the loop goes
         * back to waiting rather than blocking here - one connection's
         * keepalive must not hold up the others. */
        return 0;
    }
    if (rc == 1) {
        logline("connection %lu: closed by the client after %llu requests",
                C->id, (unsigned long long)C->requests);
        return 1;
    }
    if (rc) {
        /* A refusal, then the connection ends: the stream is not to be
         * trusted past a frame that failed its checks. A stall is the
         * same outcome with a different reason in the log. */
        logline("connection %lu: REFUSED a frame: %s", C->id, why);
        send_reply(C, &h, CFTR_KIND_REFUSAL, rc, why, strlen(why) + 1, my_abi);
        return 1;
    }
    C->requests++;
    C->bytes_in += CFTR_HDR_BYTES + h.length;
    if (h.op < 256)
        C->op_count[h.op]++;

    memset(&A, 0, sizeof A);
    A.status = CFT_ERR_INTERNAL;
    if (h.kind != CFTR_KIND_REQUEST) {
        snprintf(A.why, sizeof A.why, "a frame of kind %u where a request "
                 "was due", (unsigned)h.kind);
    } else if (!C->hello_done && h.op != CFTR_OP_HELLO) {
        snprintf(A.why, sizeof A.why, "op 0x%04x before HELLO", (unsigned)h.op);
    } else {
        switch (h.op) {
        case CFTR_OP_HELLO:
        case CFTR_OP_CAPS:
            if (h.length) {
                snprintf(A.why, sizeof A.why, "HELLO/CAPS carry no payload");
                break;
            }
            if (!C->dev) {
                fail(&A, C->open_status, "opening this connection's device");
                break;
            }
            A.resp = (uint8_t *)malloc(CFTR_CAPS_BYTES);
            if (!A.resp) {
                fail(&A, CFT_ERR_OUT_OF_MEMORY, "answering");
                break;
            }
            caps_block(C, A.resp);
            A.resp_len = CFTR_CAPS_BYTES;
            A.status = CFT_OK;
            C->hello_done = 1;
            break;
        case CFTR_OP_STATS:      h_stats(C, &A); break;
        case CFTR_OP_RUN:        h_run(C, p, h.length, &A, 0); break;
        case CFTR_OP_REDUCE:     h_run(C, p, h.length, &A, 1); break;
        case CFTR_OP_PROG_LOAD:  h_prog_load(C, p, h.length, &A); break;
        case CFTR_OP_PROG_RUN:   h_prog_run(C, p, h.length, &A); break;
        case CFTR_OP_PROG_FREE:  h_prog_free(C, p, h.length, &A); break;
        case CFTR_OP_BUF_ALLOC:  h_buf_alloc(C, p, h.length, &A); break;
        case CFTR_OP_BUF_FREE:   h_buf_free(C, p, h.length, &A); break;
        case CFTR_OP_BUF_WRITE:  h_buf_write(C, p, h.length, &A); break;
        case CFTR_OP_BUF_READ:   h_buf_read(C, p, h.length, &A); break;
        case CFTR_OP_FLAGS_LOWER:
        case CFTR_OP_FLAGS_RAISE:
        case CFTR_OP_FLAGS_TEST:
        case CFTR_OP_FLAGS_SAVE:
        case CFTR_OP_FLAGS_RESTORE:
        case CFTR_OP_FLAGS_TEST_SAVED:
            h_flags(C, h.op, p, h.length, &A);
            break;
        case CFTR_OP_BYE:
            A.status = CFT_OK;
            break;
        default:
            /* An operation this server does not have is the operation's
             * own failure, not a broken stream. */
            A.status = CFT_ERR_UNSUPPORTED;
            snprintf(A.msg, sizeof A.msg, "opcode 0x%04x is not one this "
                     "server serves", (unsigned)h.op);
            break;
        }
    }
    free(p);

    if (A.why[0]) {
        logline("connection %lu: REFUSED request %lu (op 0x%04x): %s", C->id,
                (unsigned long)h.id, (unsigned)h.op, A.why);
        send_reply(C, &h, CFTR_KIND_REFUSAL, CFT_ERR_INVALID_ARGUMENT, A.why,
                   strlen(A.why) + 1, my_abi);
        free(A.resp);
        return 1;
    }
    if (g_verbose)
        logline("connection %lu: request %lu op 0x%04x in %lu bytes -> %s, "
                "%lu bytes", C->id, (unsigned long)h.id, (unsigned)h.op,
                (unsigned long)h.length, cft_strerror((cft_status)A.status),
                (unsigned long)(A.status == CFT_OK ? A.resp_len
                                                   : strlen(A.msg) + 1));
    if (A.status == CFT_OK)
        rc = send_reply(C, &h, CFTR_KIND_RESPONSE, CFT_OK, A.resp, A.resp_len,
                        my_abi);
    else
        rc = send_reply(C, &h, CFTR_KIND_RESPONSE, A.status, A.msg,
                        strlen(A.msg) + 1, my_abi);
    free(A.resp);
    if (rc) {
        logline("connection %lu: sending a reply failed: %s", C->id,
                cftr_sock_error());
        return 1;
    }
    if (h.op == CFTR_OP_BYE) {
        logline("connection %lu: BYE after %llu requests", C->id,
                (unsigned long long)C->requests);
        return 1;
    }
    return 0;
}

/* ---- main ------------------------------------------------------------- */

static void usage(void)
{
    printf(
"cft-serve - the tile behind a socket (docs/REMOTE.md)\n"
"\n"
"  --port N          listen on this port (default %d; 0 asks the OS)\n"
"  --bind ADDR       listen on this address (default 127.0.0.1; 0.0.0.0\n"
"                    exposes the server on every interface - no\n"
"                    authentication, no encryption)\n"
"  --ws N            ALSO listen on this port for WebSocket clients\n"
"                    (RFC 6455; one message per frame, same protocol,\n"
"                    same counters). Off unless asked, because a\n"
"                    browser will open a WebSocket to a loopback port\n"
"                    from any page the person is looking at, and this\n"
"                    server has no authentication. 0 asks the OS\n"
"  --ws-port-file P  write the WebSocket port actually bound there\n"
"  --artifact PATH   the device each connection gets (default: the\n"
"                    software backend)\n"
"  --max-conns N     exit once N connections have been served\n"
"  --pid-file PATH   write the process id there\n"
"  --port-file PATH  write the port actually bound there\n"
"  --verbose         one line per request\n"
"\n"
"Stop it by its PID, which it prints - never by image name.\n",
    CFTR_DEFAULT_PORT);
}

int main(int argc, char **argv)
{
    const char *bind_addr = "127.0.0.1", *artifact = NULL;
    const char *pid_file = NULL, *port_file = NULL, *ws_port_file = NULL;
    char port_s[16];
    long port = CFTR_DEFAULT_PORT, max_conns = -1, accepted = 0;
    long ws_port = -1;                  /* -1: no WebSocket listener */
    int bound = 0, ws_bound = 0, i;
    cftr_sock listener, ws_listener = CFTR_BAD_SOCK;
    cft_device *probe = NULL;
    cft_status st;
    const uint32_t my_abi = cft_abi_version();

    for (i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (!strcmp(a, "--help") || !strcmp(a, "-h")) { usage(); return 0; }
        else if (!strcmp(a, "--verbose")) g_verbose = 1;
        else if (i + 1 >= argc) { fprintf(stderr, "%s needs a value\n", a); return 2; }
        else if (!strcmp(a, "--port")) port = strtol(argv[++i], NULL, 10);
        else if (!strcmp(a, "--ws")) ws_port = strtol(argv[++i], NULL, 10);
        else if (!strcmp(a, "--ws-port-file")) ws_port_file = argv[++i];
        else if (!strcmp(a, "--bind")) bind_addr = argv[++i];
        else if (!strcmp(a, "--artifact")) artifact = argv[++i];
        else if (!strcmp(a, "--max-conns")) max_conns = strtol(argv[++i], NULL, 10);
        else if (!strcmp(a, "--pid-file")) pid_file = argv[++i];
        else if (!strcmp(a, "--port-file")) port_file = argv[++i];
        else { fprintf(stderr, "cft-serve: unknown option %s\n", a); return 2; }
    }
    if (port < 0 || port > 65535) {
        fprintf(stderr, "cft-serve: --port %ld is not a port\n", port);
        return 2;
    }
    if (ws_port >= 0 && ws_port > 65535) {
        fprintf(stderr, "cft-serve: --ws %ld is not a port\n", ws_port);
        return 2;
    }
    if (ws_port >= 0 && ws_port == port && port != 0) {
        fprintf(stderr, "cft-serve: --ws %ld is the frame port; the two "
                        "protocols get a port each (docs/REMOTE.md says "
                        "why)\n", ws_port);
        return 2;
    }
    if (artifact && strncmp(artifact, "cft://", 6) == 0) {
        fprintf(stderr, "cft-serve: a server fronting another server is "
                        "not a thing this step builds\n");
        return 2;
    }
#ifdef SIGPIPE
    signal(SIGPIPE, SIG_IGN);
#endif
    if (cftr_crc32_selfcheck()) {
        fprintf(stderr, "cft-serve: the CRC-32 implementation failed its "
                        "check value; refusing to serve\n");
        return 2;
    }
    if (ws_port >= 0 && ws_selfcheck()) {
        fprintf(stderr, "cft-serve: the SHA-1 and base64 behind "
                        "Sec-WebSocket-Accept failed their published check "
                        "values; refusing to serve WebSocket\n");
        return 2;
    }

    /* Open the device once before listening, so a bad artifact is
     * reported to the person who started the server rather than to
     * the first client - and released again, because each connection
     * opens its own. */
    st = cft_open(artifact, 0, &probe);
    if (st != CFT_OK) {
        fprintf(stderr, "cft-serve: cft_open(%s): %s\n  %s\n",
                artifact ? artifact : "software", cft_strerror(st),
                cft_last_error());
        return 2;
    }
    cft_close(probe);

    if (cftr_sock_init()) {
        fprintf(stderr, "cft-serve: %s\n", cftr_sock_error());
        return 2;
    }
    snprintf(port_s, sizeof port_s, "%ld", port);
    listener = cftr_sock_listen(bind_addr, port_s, 16, &bound);
    if (listener == CFTR_BAD_SOCK) {
        fprintf(stderr, "cft-serve: listening on %s:%s: %s\n", bind_addr,
                port_s, cftr_sock_error());
        return 2;
    }
    if (ws_port >= 0) {
        char ws_port_s[16];
        snprintf(ws_port_s, sizeof ws_port_s, "%ld", ws_port);
        ws_listener = cftr_sock_listen(bind_addr, ws_port_s, 16, &ws_bound);
        if (ws_listener == CFTR_BAD_SOCK) {
            fprintf(stderr, "cft-serve: listening on %s:%s for WebSocket: "
                    "%s\n", bind_addr, ws_port_s, cftr_sock_error());
            cftr_sock_close(listener);
            return 2;
        }
    }
    logline("cft-serve: libcft ABI %u.%u, device %s, listening on %s:%d, "
            "pid %lu", (unsigned)(my_abi >> 16), (unsigned)(my_abi & 0xFFFFu),
            artifact ? artifact : "software", bind_addr, bound, SERVE_PID());
    if (ws_listener != CFTR_BAD_SOCK)
        logline("cft-serve: WebSocket (RFC 6455) on %s:%d - one message per "
                "frame, no authentication", bind_addr, ws_bound);
    if (pid_file) {
        FILE *f = fopen(pid_file, "w");
        if (f) { fprintf(f, "%lu\n", SERVE_PID()); fclose(f); }
    }
    if (port_file) {
        FILE *f = fopen(port_file, "w");
        if (f) { fprintf(f, "%d\n", bound); fclose(f); }
    }
    if (ws_port_file && ws_listener != CFTR_BAD_SOCK) {
        FILE *f = fopen(ws_port_file, "w");
        if (f) { fprintf(f, "%d\n", ws_bound); fclose(f); }
    }

    /* The loop: wait on the listener and every open connection, accept
     * what is waiting, serve one request on each connection that has
     * one. --max-conns stops ACCEPTING at N and exits once the last
     * of them has closed. */
    for (;;) {
        cftr_sock socks[MAX_CONNS + 2];
        int ready[MAX_CONNS + 2], map[MAX_CONNS + 2];
        int n = 0, open_count = 0, rc;

        for (i = 0; i < MAX_CONNS; i++)
            if (g_conns[i].open)
                open_count++;
        if ((max_conns < 0 || accepted < max_conns) && open_count < MAX_CONNS) {
            /* map < 0 is a listener: -1 the frame port, -2 the
             * WebSocket one. A connection is the same connection
             * either way once it is accepted. */
            socks[n] = listener;
            map[n] = -1;
            n++;
            if (ws_listener != CFTR_BAD_SOCK) {
                socks[n] = ws_listener;
                map[n] = -2;
                n++;
            }
        }
        for (i = 0; i < MAX_CONNS; i++)
            if (g_conns[i].open) {
                socks[n] = g_conns[i].s;
                map[n] = i;
                n++;
            }
        if (n == 0)
            break;                /* --max-conns reached, all closed */

        rc = cftr_sock_select(socks, n, ready, -1);
        if (rc < 0) {
            logline("cft-serve: select failed: %s", cftr_sock_error());
            break;
        }
        for (i = 0; i < n; i++) {
            if (!ready[i])
                continue;
            if (map[i] < 0) {
                const int is_ws = (map[i] == -2);
                cftr_sock c = cftr_sock_accept(is_ws ? ws_listener : listener);
                int slot;
                if (c == CFTR_BAD_SOCK) {
                    logline("cft-serve: accept failed: %s", cftr_sock_error());
                    continue;
                }
                for (slot = 0; slot < MAX_CONNS; slot++)
                    if (!g_conns[slot].open)
                        break;
                if (slot == MAX_CONNS) {      /* cannot happen: gated above */
                    cftr_sock_close(c);
                    continue;
                }
                accepted++;
                conn_open(&g_conns[slot], c, (unsigned long)accepted,
                          artifact, is_ws);
            } else if (serve_one(&g_conns[map[i]], my_abi)) {
                conn_close(&g_conns[map[i]]);
            }
        }
    }
    cftr_sock_close(listener);
    if (ws_listener != CFTR_BAD_SOCK)
        cftr_sock_close(ws_listener);
    logline("cft-serve: served %ld connection(s), exiting", accepted);
    return 0;
}
