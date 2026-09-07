/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * RFC 6455 for cft-serve: the browser's way in (docs/REMOTE.md).
 *
 * ONE WEBSOCKET MESSAGE CARRIES EXACTLY ONE FRAME OF docs/REMOTE.md,
 * UNCHANGED - the same 32-byte header, the same little-endian fields,
 * the same CRC over the same bytes. Nothing about the protocol is
 * different over this transport; a WebSocket message is an envelope
 * around the frame the TCP path sends bare, so the server's handlers,
 * its STATS counters and its refusals are the ones the TCP path
 * already had, and a client that speaks the frames can speak them
 * over either.
 *
 * What this file adds is the envelope and the way in: the opening
 * handshake (with SHA-1 and base64 implemented here - a handshake
 * that pulled in a crypto library would be a dependency for four
 * lines of hashing), client-to-server unmasking, fragment reassembly,
 * ping/pong and close.
 *
 * It is written against the cftr_sock_* shim in src/remote.h and
 * nothing else, so it has no platform branch and adds no link flag on
 * any platform - the same property the rest of the server has, for
 * the same reason.
 */

#ifndef CFT_WS_H
#define CFT_WS_H

#include <stddef.h>
#include <stdint.h>

#include "remote.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ---- the two primitives the handshake needs ------------------------ */

/* SHA-1 of `len` bytes, FIPS 180-4 / RFC 3174. Here because
 * Sec-WebSocket-Accept is defined in terms of it and for no other
 * reason: it is not a security primitive in this protocol, it is a
 * fixed function of a fixed string that proves the peer read the
 * request. */
void ws_sha1(const void *data, size_t len, uint8_t out[20]);

/* Standard base64 with padding (RFC 4648). Writes a NUL. Returns the
 * number of characters written, or 0 if `out_size` is too small. */
size_t ws_base64(const uint8_t *in, size_t len, char *out, size_t out_size);

/* 0 when SHA-1 and base64 give the published values: FIPS 180-4's
 * SHA-1("abc"), RFC 4648's base64 vectors, and RFC 6455 section 1.3's
 * own worked example of the whole accept computation - the key
 * "dGhlIHNhbXBsZSBub25jZQ==" answered with
 * "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=". Checked before the server listens,
 * as the CRC-32 is, because an implementation that has never been
 * held against its own published vector is a guess. */
int ws_selfcheck(void);

/* ---- a WebSocket connection ---------------------------------------- */

/* The receive state that has to live between calls: the buffer a
 * fragmented message is reassembled into, and whether a message is
 * open. `origin` is the Origin header the browser sent, kept for the
 * connection's log line - see the security note in docs/REMOTE.md,
 * because any page in a browser may open a WebSocket to a loopback
 * port and this server has no authentication. */
typedef struct ws_conn {
    cftr_sock s;
    uint8_t  *msg;                /* the message being reassembled */
    size_t    msg_len, msg_cap;
    int       in_message;         /* a fragmented message is open */
    int       peer_closed;
    char      origin[192];
} ws_conn;

/* The server side of the opening handshake, on a socket that has just
 * been accepted. Returns 0 on success; nonzero with `why` set after
 * writing a short HTTP error response, in which case the caller
 * closes the socket. */
int ws_handshake(ws_conn *W, cftr_sock s, char *why, size_t why_size);

/* Release the reassembly buffer. Does not close the socket - the
 * server's conn_close() owns that, as it does for a TCP connection. */
void ws_conn_free(ws_conn *W);

/* Send a close frame (best effort) before the socket goes away. */
void ws_send_close(ws_conn *W, uint16_t code);

/* ---- frames over a WebSocket ---------------------------------------- *
 *
 * The same contract as cftr_send_frame / cftr_recv_frame in
 * src/remote.h, so that cft-serve's serve_one() differs between the
 * two transports by which of the two it calls and by nothing else.
 */

/* Send one frame as one unfragmented binary message. */
int ws_send_frame(ws_conn *W, const cftr_hdr *h, const void *payload,
                  size_t len);

/* Receive one frame. Returns:
 *
 *   0   a frame arrived; *payload is malloc'd (NULL when length is 0)
 *   1   the peer closed - a close frame or a clean EOF
 *  -1   a control frame was handled (a ping answered, a pong dropped)
 *       and no protocol frame arrived; the caller should go back to
 *       waiting rather than block here, so one connection's keepalive
 *       cannot hold up the others
 *  else the cft_status a refusal should carry, with `why` set
 *
 * NEGATIVE for the control case and not 2, because 2 is
 * CFT_ERR_UNSUPPORTED - which is exactly what an ABI or protocol
 * version mismatch returns - and 1 is CFT_ERR_INVALID_ARGUMENT. A
 * sentinel that collides with a status is a refusal that gets read as
 * something else, which is a client waiting for an answer that was
 * never sent. cftr_recv_frame has the same shape and avoids the
 * collision the same way: it never refuses with 1.
 *
 * The checks on the frame inside the message are the ones
 * cftr_recv_frame makes on the frame inside the stream, with the same
 * words: magic, protocol version, the reserved word, the sender's
 * ABI, the length cap and the CRC. */
int ws_recv_frame(ws_conn *W, cftr_hdr *h, uint8_t **payload,
                  uint32_t my_abi, char *why, size_t why_size);

#ifdef __cplusplus
}
#endif

#endif /* CFT_WS_H */
