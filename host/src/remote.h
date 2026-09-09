/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The remote backend's wire protocol and its socket shim. Internal.
 *
 * docs/REMOTE.md is the normative description and was written before
 * this header; the two must move together. Three things include it:
 * src/backend_remote.c (the client backend, the only thing device.c
 * dispatches to), tools/cft-serve.c (the server, which links libcft.a
 * and speaks the same frames from the other side) and
 * tests/remote_test.c (which speaks them badly on purpose).
 *
 * Nothing here is exported from the shared library: the cftr_ symbols
 * are plain internal functions, reachable from the static archive the
 * tools link, and the public surface of libcft is still exactly
 * include/cft.h.
 */

#ifndef CFT_REMOTE_H
#define CFT_REMOTE_H

#include <stddef.h>
#include <stdint.h>

#include "backend.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ---- the frame ---------------------------------------------------- */

/* 'C' 'F' 'T' 'R' as they appear on the wire, first byte first; as a
 * little-endian uint32_t that is 0x52544643, and it is DERIVED here
 * rather than typed so that the four bytes and the number cannot
 * disagree. */
#define CFTR_MAGIC  ((uint32_t)'C' | ((uint32_t)'F' << 8) | \
                     ((uint32_t)'T' << 16) | ((uint32_t)'R' << 24))
#define CFTR_PROTO_VERSION  1u
#define CFTR_HDR_BYTES      32u

/* header.kind */
#define CFTR_KIND_REQUEST   0u
#define CFTR_KIND_RESPONSE  1u
#define CFTR_KIND_REFUSAL   2u

/* A payload longer than this is refused before any of it is read:
 * a corrupted length field must not become an allocation. 1 GiB. */
#define CFTR_MAX_PAYLOAD    ((uint32_t)1u << 30)

/* The client splits RUN and PROG_RUN so that no frame carries more
 * than this much operand and result data. 16 MiB. */
#define CFTR_CHUNK_BYTES    ((size_t)16u << 20)

/* opcodes */
#define CFTR_OP_HELLO            0x0001u
#define CFTR_OP_CAPS             0x0002u
#define CFTR_OP_STATS            0x0003u
#define CFTR_OP_RUN              0x0010u
#define CFTR_OP_REDUCE           0x0011u
#define CFTR_OP_PROG_LOAD        0x0020u
#define CFTR_OP_PROG_RUN         0x0021u
#define CFTR_OP_PROG_FREE        0x0022u
/* PROG_RUN with the constant bank as data (ABI 0.9, docs/SEQUENCER.md
 * revision 2 R3). A NEW OPCODE rather than a longer PROG_RUN, which is
 * what makes it versioned in both directions without a protocol step:
 *
 *  - an older SERVER refuses it by name. Its dispatch has no case for
 *    0x0023 and its default arm answers CFT_ERR_UNSUPPORTED with
 *    "opcode 0x0023 is not one this server serves", on a connection
 *    that stays open - an operation's own failure, not a broken
 *    stream. Widening PROG_RUN's payload instead would have reached
 *    that server's length check and been a REFUSAL, which ends the
 *    connection over a feature the caller could have asked about.
 *  - an older CLIENT never sends it, because it does not have the
 *    constant. A current client never sends it to a server whose
 *    device lacks CFT_SEQ_FEAT_BANK_PTR either, because a BANK_EXT
 *    program does not LOAD against such a device - the HELLO caps
 *    block carries seq_features and cft_program_load refuses the image
 *    there, one round trip earlier and with a message that names the
 *    feature.
 *
 * CFTR_PROTO_VERSION does not move: it is compared for equality at
 * both ends, so stepping it would turn "an older server refuses one
 * operation" into "an older server refuses the connection". */
#define CFTR_OP_PROG_RUN_BANK    0x0023u
/* PROG_RUN with everything a run can carry (ABI 0.10,
 * docs/SEQUENCER.md revision 3 R5): the bank, and the per-run scratch
 * block in and out. A THIRD opcode for exactly the reasons the second
 * one was a second - an older server has no case for 0x0024 and
 * answers CFT_ERR_UNSUPPORTED by name on a connection that stays open,
 * where a longer PROG_RUN_BANK would have failed that server's length
 * check and ended the connection.
 *
 * WHICH of the three a run becomes is the IMAGE's decision, read from
 * its header - SCRATCH_IO (flags bit 1) first, then BANK_EXT (bit 0) -
 * and never from the buffers' lengths. A BANK_EXT program whose
 * n_consts is zero has a legitimately empty bank and still needs the
 * bank opcode, and a SCRATCH_IO program whose two counts are zero has
 * two legitimately empty blocks and still needs this one, because the
 * server's cft_program_run and cft_program_run_bank both refuse it and
 * only cft_program_run_ex takes it. That corner was found by the
 * JavaScript client on 2026-09-08 and is the reason the rule is
 * written down here rather than inferred at each call site. */
#define CFTR_OP_PROG_RUN_EX      0x0024u
#define CFTR_OP_BUF_ALLOC        0x0030u
#define CFTR_OP_BUF_FREE         0x0031u
#define CFTR_OP_BUF_WRITE        0x0032u
#define CFTR_OP_BUF_READ         0x0033u
#define CFTR_OP_FLAGS_LOWER      0x0040u
#define CFTR_OP_FLAGS_RAISE      0x0041u
#define CFTR_OP_FLAGS_TEST       0x0042u
#define CFTR_OP_FLAGS_SAVE       0x0043u
#define CFTR_OP_FLAGS_RESTORE    0x0044u
#define CFTR_OP_FLAGS_TEST_SAVED 0x0045u
#define CFTR_OP_BYE              0x00FFu

/* The caps block a HELLO or CAPS response carries.
 *
 * IT GROWS BY APPENDING, and a client reads what it recognises out of
 * whatever length arrived: a block SHORTER than this one is a server
 * that predates the missing fields, and they read as zero, which
 * cft_caps documents as "unknown" and nothing enforces anything
 * against. That is a property of the block, not of the frame, so
 * CFTR_PROTO_VERSION does NOT move for it - the proto field is
 * compared for equality at both ends, so bumping it would turn "an
 * older server answers with a shorter block" into "an older server
 * refuses the connection", which is the outcome the tolerance exists
 * to avoid. What it cannot do is make an OLDER client read a longer
 * block; that pairing is already refused one field earlier, by the
 * ABI equality check in cftr_recv_frame, since appending to cft_caps
 * is an ABI minor step.
 *
 * V1 (56 bytes, protocol 1 as first shipped): format_mask, op_groups,
 * tiles, device_version, flags_readable, abi, backend[32].
 * V2 (72): + max_deposits, max_insns, max_consts, seq_features - the
 * sequencer capacities of cft_caps, in the same units.
 * V3 (76): + max_scratch, the per-lane scratch depth of revision 3.
 * seq_features carries the two new feature bits in the field it
 * already had, so only the capacity needed a word. */
#define CFTR_CAPS_BYTES_V1  56u
#define CFTR_CAPS_BYTES_V2  72u
#define CFTR_CAPS_BYTES     76u
#define CFTR_BACKEND_NAME   32u

/* The default port the server listens on. A choice, not a derivation:
 * above the privileged range, and nothing else on the boxes this was
 * built on uses it. */
#define CFTR_DEFAULT_PORT   7754

typedef struct cftr_hdr {
    uint16_t proto;
    uint16_t kind;
    uint32_t abi;
    uint32_t id;
    uint16_t op;
    uint16_t status;
    uint32_t length;
} cftr_hdr;

/* CRC-32 as IEEE 802.3 / zlib / PNG define it: reflected polynomial
 * 0xEDB88320, initial value all ones, final complement. The table is
 * derived from the polynomial on first use. cftr_crc32_selfcheck()
 * returns 0 when the implementation gives the standard check value
 * 0xCBF43926 for the nine ASCII digits "123456789". */
uint32_t cftr_crc32(uint32_t seed, const void *data, size_t len);
int      cftr_crc32_selfcheck(void);

/* Little-endian field access, so that no struct layout or host byte
 * order is ever on the wire. */
void     cftr_put16(uint8_t *p, uint16_t v);
void     cftr_put32(uint8_t *p, uint32_t v);
void     cftr_put64(uint8_t *p, uint64_t v);
uint16_t cftr_get16(const uint8_t *p);
uint32_t cftr_get32(const uint8_t *p);
uint64_t cftr_get64(const uint8_t *p);

/* Serialise a header (crc field zero) into 32 bytes, and back. */
void cftr_hdr_pack(const cftr_hdr *h, uint8_t out[32]);
int  cftr_hdr_unpack(const uint8_t in[32], cftr_hdr *h, uint32_t *crc);

/* ---- the socket shim ---------------------------------------------- *
 *
 * The same eight verbs on both platforms. On Windows the functions
 * behind them are looked up in ws2_32.dll at first use, which is why
 * linking libcft.a needs no -lws2_32 and no existing consumer of the
 * archive changed; on POSIX they are the BSD calls. A socket is an
 * intptr_t so that both SOCKET (UINT_PTR) and int fit; -1 is invalid.
 */
typedef intptr_t cftr_sock;
#define CFTR_BAD_SOCK ((cftr_sock)-1)

/* One-time initialisation (WSAStartup on Windows; nothing elsewhere).
 * 0 on success; the message from cftr_sock_error() otherwise. Safe to
 * call more than once. */
int         cftr_sock_init(void);

/* Connect to host:port (a name, a dotted quad, or a bracketed IPv6
 * literal; port as a decimal string). Every address the resolver
 * returns is tried in order. Sets TCP_NODELAY. */
cftr_sock   cftr_sock_connect(const char *host, const char *port);

/* Bind and listen on addr:port. addr may be NULL for the wildcard. On
 * return *bound_port is the port actually bound, which matters when 0
 * was asked for. */
cftr_sock   cftr_sock_listen(const char *addr, const char *port,
                             int backlog, int *bound_port);
cftr_sock   cftr_sock_accept(cftr_sock listener);

/* Receive timeout in milliseconds; 0 means none. */
int         cftr_sock_timeout(cftr_sock s, long ms);

/* Wait until at least one of `socks` is readable (a listener with a
 * connection to accept counts), or until timeout_ms passes; -1 waits
 * forever. Sets ready[i] to 1 for each readable socket and returns how
 * many, 0 on a timeout, -1 on failure. How the server multiplexes its
 * connections without a thread. */
int         cftr_sock_select(const cftr_sock *socks, int n, int *ready,
                             long timeout_ms);

/* All-or-nothing. 0 on success, -1 on any failure (a short transfer
 * followed by EOF counts). cftr_sock_recv_all reports EOF-before-any-
 * byte as 1, so a server can tell a clean disconnect from a truncated
 * frame. */
int         cftr_sock_send_all(cftr_sock s, const void *buf, size_t len);
int         cftr_sock_recv_all(cftr_sock s, void *buf, size_t len);
void        cftr_sock_close(cftr_sock s);

/* The most recent socket failure, as text. Static storage. */
const char *cftr_sock_error(void);

/* Nonzero if the most recent socket failure was the receive timeout
 * expiring rather than a fault, so a client can report
 * CFT_ERR_TIMEOUT instead of CFT_ERR_INTERNAL. */
int         cftr_sock_timed_out(void);

/* ---- frames over a socket ------------------------------------------ */

/* Send one frame: header with the crc filled in, then the payload. */
int cftr_send_frame(cftr_sock s, const cftr_hdr *h, const void *payload,
                    size_t len);

/* Receive one frame. Checks magic, protocol version, reserved word,
 * the length cap, the crc, and that the sender's abi equals my_abi.
 * On success *payload is a malloc'd copy of the payload (NULL when the
 * length is zero), the caller frees it, and the return is 0. On a
 * clean EOF before any byte the return is 1. Any other outcome is a
 * refusal: the return is the cft_status the refusal should carry
 * (CFT_ERR_INTERNAL for a transport fault, CFT_ERR_UNSUPPORTED for a
 * version mismatch) and `why` holds the message. */
int cftr_recv_frame(cftr_sock s, cftr_hdr *h, uint8_t **payload,
                    uint32_t my_abi, char *why, size_t why_size);

/* ---- the client backend, as device.c sees it ------------------------ *
 *
 * The same shapes as the cftx_ functions in backend.h, so that
 * device.c's dispatch to the two device backends reads alike - which
 * is why this header includes that one rather than restating
 * cft_seq_caps. `url` is the whole "cft://host:port" string. */
int  cftr_is_url(const char *artifact);
int  cftr_open(const char *url, int index, void **out,
               uint32_t *format_mask, uint32_t *op_groups,
               uint32_t *tiles, uint32_t *version, int *flags_readable,
               cft_seq_caps *seq);
void cftr_close(void *hw);
int  cftr_run(void *hw, int op, int fmt, int rnd,
              const void *a, const void *b, const void *c, void *d,
              size_t n, uint32_t *flags, uint32_t *bus);
int  cftr_reduce(void *hw, int op, int fmt, int rnd,
                 const void *a, const void *b, void *d, size_t n,
                 uint32_t *flags, uint32_t *bus);
int  cftr_program_run(void *hw, int fmt, const void *image,
                      size_t image_bytes,
                      const cft_seq_run_io *io,
                      uint32_t max_deposits,
                      const void *a, const void *b, const void *c,
                      void *deposits, uint32_t *counts, size_t n,
                      uint32_t *flags, uint32_t *bus);
const char *cftr_last_error(void);

/* One raw request on an open remote handle, for the tests and for the
 * operations libcft's own client never issues (the buffer and status-
 * word operations, STATS). Returns the transport verdict: 0 when a
 * response arrived, in which case *status is the operation's
 * cft_status and *resp with *resp_len its payload (malloc'd, or NULL);
 * nonzero when the handle is poisoned, with the message in
 * cftr_last_error(). */
int cftr_request(void *hw, uint16_t op, const void *payload, size_t len,
                 int *status, uint8_t **resp, size_t *resp_len);

/* The server's name for its own backend, as HELLO reported it. */
const char *cftr_server_backend(void *hw);

#ifdef __cplusplus
}
#endif

#endif /* CFT_REMOTE_H */
