/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * RFC 6455 for cft-serve. ws.h says what this is and why the envelope
 * changes nothing about the frame inside it.
 *
 * Everything here is written against the cftr_sock_* shim in
 * src/remote.h - recv-all, send-all, the receive timeout the server
 * already sets - so there is no platform branch and no new link flag,
 * on any platform. The handshake reads byte by byte because it is the
 * one place on the wire whose length is not known in advance; it
 * happens once per connection and is capped, so the syscall count is
 * not worth a buffer that would then have to be pushed back into the
 * frame reader.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../include/cft.h"
#include "ws.h"

/* RFC 6455 section 1.3. Not a secret and not a nonce: a constant that
 * makes an accept value impossible to produce by echoing. */
#define WS_GUID "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

/* The opening handshake's request, capped. A browser sends a few
 * hundred bytes; anything past this is not a handshake. */
#define WS_REQ_MAX 8192

/* opcodes */
#define WS_CONT   0x0
#define WS_TEXT   0x1
#define WS_BIN    0x2
#define WS_CLOSE  0x8
#define WS_PING   0x9
#define WS_PONG   0xA

/* ---- SHA-1 ---------------------------------------------------------- */

static uint32_t rol32(uint32_t v, unsigned n)
{
    return (uint32_t)((v << n) | (v >> (32 - n)));
}

static void sha1_block(uint32_t h[5], const uint8_t p[64])
{
    uint32_t w[80], a, b, c, d, e, f, k, t;
    int i;

    for (i = 0; i < 16; i++)
        w[i] = ((uint32_t)p[i * 4] << 24) | ((uint32_t)p[i * 4 + 1] << 16) |
               ((uint32_t)p[i * 4 + 2] << 8) | (uint32_t)p[i * 4 + 3];
    for (i = 16; i < 80; i++)
        w[i] = rol32(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);

    a = h[0]; b = h[1]; c = h[2]; d = h[3]; e = h[4];
    for (i = 0; i < 80; i++) {
        if (i < 20)       { f = (b & c) | (~b & d);          k = 0x5A827999u; }
        else if (i < 40)  { f = b ^ c ^ d;                   k = 0x6ED9EBA1u; }
        else if (i < 60)  { f = (b & c) | (b & d) | (c & d); k = 0x8F1BBCDCu; }
        else              { f = b ^ c ^ d;                   k = 0xCA62C1D6u; }
        t = rol32(a, 5) + f + e + k + w[i];
        e = d; d = c; c = rol32(b, 30); b = a; a = t;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e;
}

void ws_sha1(const void *data, size_t len, uint8_t out[20])
{
    uint32_t h[5];
    uint8_t tail[128];
    const uint8_t *p = (const uint8_t *)data;
    size_t whole = len / 64, rest = len % 64, tail_len;
    uint64_t bits = (uint64_t)len * 8u;
    size_t i;

    h[0] = 0x67452301u; h[1] = 0xEFCDAB89u; h[2] = 0x98BADCFEu;
    h[3] = 0x10325476u; h[4] = 0xC3D2E1F0u;
    for (i = 0; i < whole; i++)
        sha1_block(h, p + i * 64);

    memset(tail, 0, sizeof tail);
    memcpy(tail, p + whole * 64, rest);
    tail[rest] = 0x80;
    tail_len = (rest < 56) ? 64u : 128u;
    for (i = 0; i < 8; i++)
        tail[tail_len - 1 - i] = (uint8_t)(bits >> (8 * i));
    sha1_block(h, tail);
    if (tail_len == 128)
        sha1_block(h, tail + 64);

    for (i = 0; i < 5; i++) {
        out[i * 4 + 0] = (uint8_t)(h[i] >> 24);
        out[i * 4 + 1] = (uint8_t)(h[i] >> 16);
        out[i * 4 + 2] = (uint8_t)(h[i] >> 8);
        out[i * 4 + 3] = (uint8_t)h[i];
    }
}

/* ---- base64 ---------------------------------------------------------- */

size_t ws_base64(const uint8_t *in, size_t len, char *out, size_t out_size)
{
    static const char A[] =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    size_t need = ((len + 2) / 3) * 4, i, j = 0;
    if (out_size < need + 1)
        return 0;
    for (i = 0; i < len; i += 3) {
        uint32_t v = (uint32_t)in[i] << 16;
        if (i + 1 < len) v |= (uint32_t)in[i + 1] << 8;
        if (i + 2 < len) v |= (uint32_t)in[i + 2];
        out[j++] = A[(v >> 18) & 0x3F];
        out[j++] = A[(v >> 12) & 0x3F];
        out[j++] = (i + 1 < len) ? A[(v >> 6) & 0x3F] : '=';
        out[j++] = (i + 2 < len) ? A[v & 0x3F] : '=';
    }
    out[j] = '\0';
    return j;
}

/* The accept value: base64(SHA-1(key + GUID)). One function, used by
 * the handshake and by the self-check, so the thing checked is the
 * thing that runs. */
static int ws_accept_of(const char *key, char *out, size_t out_size)
{
    char joined[192];
    uint8_t digest[20];
    if (strlen(key) + sizeof WS_GUID > sizeof joined)
        return -1;
    snprintf(joined, sizeof joined, "%s%s", key, WS_GUID);
    ws_sha1(joined, strlen(joined), digest);
    return ws_base64(digest, sizeof digest, out, out_size) ? 0 : -1;
}

int ws_selfcheck(void)
{
    static const struct { const char *in, *out; } b64[] = {
        { "",       ""         },
        { "f",      "Zg=="     },
        { "fo",     "Zm8="     },
        { "foo",    "Zm9v"     },
        { "foob",   "Zm9vYg==" },
        { "fooba",  "Zm9vYmE=" },
        { "foobar", "Zm9vYmFy" }
    };
    uint8_t digest[20];
    char text[64];
    size_t i;

    /* FIPS 180-4 / RFC 3174: SHA-1("abc") */
    ws_sha1("abc", 3, digest);
    for (i = 0; i < 20; i++)
        snprintf(text + i * 2, 3, "%02x", digest[i]);
    if (strcmp(text, "a9993e364706816aba3e25717850c26c9cd0d89d") != 0)
        return -1;

    /* RFC 4648 section 10 */
    for (i = 0; i < sizeof b64 / sizeof b64[0]; i++) {
        text[0] = '\0';
        ws_base64((const uint8_t *)b64[i].in, strlen(b64[i].in), text,
                  sizeof text);
        if (strcmp(text, b64[i].out) != 0)
            return -2;
    }

    /* RFC 6455 section 1.3, the whole accept computation */
    if (ws_accept_of("dGhlIHNhbXBsZSBub25jZQ==", text, sizeof text))
        return -3;
    if (strcmp(text, "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=") != 0)
        return -3;
    return 0;
}

/* ---- the opening handshake ------------------------------------------ */

static int ci_equal(const char *a, const char *b)
{
    for (; *a && *b; a++, b++) {
        int x = (*a >= 'A' && *a <= 'Z') ? *a + 32 : *a;
        int y = (*b >= 'A' && *b <= 'Z') ? *b + 32 : *b;
        if (x != y)
            return 0;
    }
    return *a == *b;
}

static int ci_contains(const char *hay, const char *needle)
{
    size_t n = strlen(needle);
    const char *p;
    for (p = hay; *p; p++) {
        size_t i;
        for (i = 0; i < n; i++) {
            int x = p[i], y = needle[i];
            if (x >= 'A' && x <= 'Z') x += 32;
            if (y >= 'A' && y <= 'Z') y += 32;
            if (x != y)
                break;
        }
        if (i == n)
            return 1;
    }
    return 0;
}

static void trim(char *s)
{
    size_t n;
    char *p = s;
    while (*p == ' ' || *p == '\t')
        p++;
    if (p != s)
        memmove(s, p, strlen(p) + 1);
    n = strlen(s);
    while (n && (s[n - 1] == ' ' || s[n - 1] == '\t' || s[n - 1] == '\r'))
        s[--n] = '\0';
}

static void http_error(cftr_sock s, const char *status, const char *body)
{
    char out[512];
    int n = snprintf(out, sizeof out,
                     "HTTP/1.1 %s\r\n"
                     "Content-Type: text/plain; charset=utf-8\r\n"
                     "Content-Length: %u\r\n"
                     "Connection: close\r\n"
                     "\r\n%s",
                     status, (unsigned)strlen(body), body);
    if (n > 0)
        (void)cftr_sock_send_all(s, out, (size_t)n);
}

int ws_handshake(ws_conn *W, cftr_sock s, char *why, size_t why_size)
{
    char req[WS_REQ_MAX + 1];
    char key[128], accept[64], reply[320];
    int have_upgrade = 0, have_connection = 0, version_ok = 0;
    size_t n = 0;
    char *line, *next = NULL;
    int rc, first = 1;

    memset(W, 0, sizeof *W);
    W->s = s;
    key[0] = '\0';

    /* Read the request head, byte by byte, up to CRLF CRLF. */
    for (;;) {
        rc = cftr_sock_recv_all(s, req + n, 1);
        if (rc) {
            snprintf(why, why_size, "reading the WebSocket handshake: %s",
                     rc == 1 ? "the client closed before sending one"
                             : cftr_sock_error());
            return -1;
        }
        n++;
        if (n >= 4 && memcmp(req + n - 4, "\r\n\r\n", 4) == 0)
            break;
        if (n == WS_REQ_MAX) {
            snprintf(why, why_size, "a handshake request longer than %d "
                     "bytes is not one", WS_REQ_MAX);
            http_error(s, "431 Request Header Fields Too Large",
                       "cft-serve: that is not a WebSocket handshake.\n");
            return -1;
        }
    }
    req[n] = '\0';

    for (line = req; line && *line; line = next) {
        char *eol = strstr(line, "\r\n");
        char *colon;
        if (!eol)
            break;
        *eol = '\0';
        next = eol + 2;
        if (first) {
            first = 0;
            if (strncmp(line, "GET ", 4) != 0) {
                snprintf(why, why_size, "the WebSocket port was given "
                         "\"%.32s\", which is not a GET", line);
                http_error(s, "400 Bad Request",
                           "cft-serve: this port speaks WebSocket "
                           "(docs/REMOTE.md); the binary frame protocol is "
                           "on the other one.\n");
                return -1;
            }
            continue;
        }
        colon = strchr(line, ':');
        if (!colon)
            continue;
        *colon = '\0';
        trim(line);
        trim(colon + 1);
        if (ci_equal(line, "Sec-WebSocket-Key"))
            snprintf(key, sizeof key, "%s", colon + 1);
        else if (ci_equal(line, "Sec-WebSocket-Version"))
            version_ok = (strcmp(colon + 1, "13") == 0);
        else if (ci_equal(line, "Upgrade"))
            have_upgrade = ci_contains(colon + 1, "websocket");
        else if (ci_equal(line, "Connection"))
            have_connection = ci_contains(colon + 1, "upgrade");
        else if (ci_equal(line, "Origin"))
            snprintf(W->origin, sizeof W->origin, "%s", colon + 1);
    }

    if (!have_upgrade || !have_connection) {
        snprintf(why, why_size, "a GET without Upgrade: websocket");
        http_error(s, "400 Bad Request",
                   "cft-serve: this port serves the frame protocol of "
                   "docs/REMOTE.md over WebSocket only.\n");
        return -1;
    }
    if (!version_ok) {
        snprintf(why, why_size, "Sec-WebSocket-Version is not 13");
        http_error(s, "426 Upgrade Required",
                   "cft-serve: RFC 6455 version 13 only.\n");
        return -1;
    }
    if (!key[0] || ws_accept_of(key, accept, sizeof accept)) {
        snprintf(why, why_size, "no usable Sec-WebSocket-Key");
        http_error(s, "400 Bad Request",
                   "cft-serve: the handshake carried no Sec-WebSocket-Key.\n");
        return -1;
    }

    rc = snprintf(reply, sizeof reply,
                  "HTTP/1.1 101 Switching Protocols\r\n"
                  "Upgrade: websocket\r\n"
                  "Connection: Upgrade\r\n"
                  "Sec-WebSocket-Accept: %s\r\n"
                  "\r\n", accept);
    if (rc <= 0 || cftr_sock_send_all(s, reply, (size_t)rc)) {
        snprintf(why, why_size, "sending the handshake response: %s",
                 cftr_sock_error());
        return -1;
    }
    return 0;
}

void ws_conn_free(ws_conn *W)
{
    free(W->msg);
    W->msg = NULL;
    W->msg_len = W->msg_cap = 0;
    W->in_message = 0;
}

/* ---- the envelope ---------------------------------------------------- */

static int ws_send_control(ws_conn *W, unsigned opcode, const void *payload,
                           size_t len)
{
    uint8_t out[2 + 125];
    if (len > 125)
        len = 125;
    out[0] = (uint8_t)(0x80u | opcode);
    out[1] = (uint8_t)len;                    /* server frames are unmasked */
    if (len)
        memcpy(out + 2, payload, len);
    return cftr_sock_send_all(W->s, out, 2 + len);
}

void ws_send_close(ws_conn *W, uint16_t code)
{
    uint8_t body[2];
    if (W->peer_closed > 1)
        return;
    body[0] = (uint8_t)(code >> 8);
    body[1] = (uint8_t)code;
    (void)ws_send_control(W, WS_CLOSE, body, 2);
    W->peer_closed = 2;
}

int ws_send_frame(ws_conn *W, const cftr_hdr *h, const void *payload,
                  size_t len)
{
    uint8_t hdr[CFTR_HDR_BYTES];
    uint8_t env[10];
    uint32_t crc;
    cftr_hdr hh = *h;
    size_t total, env_len;

    if (len > CFTR_MAX_PAYLOAD)
        return -1;
    /* The frame, byte for byte as the TCP path builds it: pack the
     * header with a zero crc, run cftr_crc32 over it and the payload,
     * write the crc at offset 24. The same three calls
     * cftr_send_frame makes, over the same bytes. */
    hh.length = (uint32_t)len;
    cftr_hdr_pack(&hh, hdr);
    crc = cftr_crc32(0, hdr, CFTR_HDR_BYTES);
    if (len)
        crc = cftr_crc32(crc, payload, len);
    cftr_put32(hdr + 24, crc);

    total = CFTR_HDR_BYTES + len;
    env[0] = (uint8_t)(0x80u | WS_BIN);       /* FIN, one binary message */
    if (total <= 125) {
        env[1] = (uint8_t)total;
        env_len = 2;
    } else if (total <= 0xFFFFu) {
        env[1] = 126;
        env[2] = (uint8_t)(total >> 8);
        env[3] = (uint8_t)total;
        env_len = 4;
    } else {
        int i;
        env[1] = 127;
        for (i = 0; i < 8; i++)
            env[2 + i] = (uint8_t)((uint64_t)total >> (8 * (7 - i)));
        env_len = 10;
    }

    /* One send for a small message, so the envelope, the header and
     * the payload share a segment; three for a large one, so the
     * payload is not copied. The same trade cftr_send_frame makes. */
    if (total <= 65536) {
        uint8_t small[10 + CFTR_HDR_BYTES + 65536];
        memcpy(small, env, env_len);
        memcpy(small + env_len, hdr, CFTR_HDR_BYTES);
        if (len)
            memcpy(small + env_len + CFTR_HDR_BYTES, payload, len);
        return cftr_sock_send_all(W->s, small, env_len + total);
    }
    if (cftr_sock_send_all(W->s, env, env_len))
        return -1;
    if (cftr_sock_send_all(W->s, hdr, CFTR_HDR_BYTES))
        return -1;
    return cftr_sock_send_all(W->s, payload, len);
}

/* Read one WebSocket frame. Returns 0 with the frame's fields set, 1
 * on a clean EOF, or a cft_status with `why` set - never 1 for a
 * refusal, so that a status can never be read as a close. A control
 * frame is handled here and reported through *control. */
static int ws_read_one(ws_conn *W, int *fin, unsigned *opcode,
                       uint8_t **data, size_t *data_len, int *control,
                       char *why, size_t why_size)
{
    uint8_t b[8], mask[4];
    uint64_t len;
    uint8_t *p = NULL;
    int rc;

    *data = NULL;
    *data_len = 0;
    *control = 0;
    rc = cftr_sock_recv_all(W->s, b, 2);
    if (rc == 1)
        return 1;
    if (rc) {
        snprintf(why, why_size, "reading a WebSocket frame header: %s",
                 cftr_sock_error());
        return cftr_sock_timed_out() ? CFT_ERR_TIMEOUT : CFT_ERR_INTERNAL;
    }
    *fin    = (b[0] & 0x80u) ? 1 : 0;
    *opcode = (unsigned)(b[0] & 0x0Fu);
    if (b[0] & 0x70u) {
        snprintf(why, why_size, "a WebSocket frame with reserved bits set, "
                 "and no extension was negotiated");
        return CFT_ERR_INTERNAL;
    }
    if (!(b[1] & 0x80u)) {
        /* RFC 6455 5.1: a client MUST mask. An unmasked frame from a
         * client is a broken client or something that is not one. */
        snprintf(why, why_size, "an unmasked frame from a client, which "
                 "RFC 6455 5.1 forbids");
        return CFT_ERR_INTERNAL;
    }
    len = (uint64_t)(b[1] & 0x7Fu);
    if (len == 126) {
        if (cftr_sock_recv_all(W->s, b, 2)) {
            snprintf(why, why_size, "reading a WebSocket length: %s",
                     cftr_sock_error());
            return CFT_ERR_INTERNAL;
        }
        len = ((uint64_t)b[0] << 8) | b[1];
    } else if (len == 127) {
        int i;
        if (cftr_sock_recv_all(W->s, b, 8)) {
            snprintf(why, why_size, "reading a WebSocket length: %s",
                     cftr_sock_error());
            return CFT_ERR_INTERNAL;
        }
        len = 0;
        for (i = 0; i < 8; i++)
            len = (len << 8) | b[i];
        if (len >> 63) {
            snprintf(why, why_size, "a WebSocket length with its top bit "
                     "set, which RFC 6455 5.2 forbids");
            return CFT_ERR_INTERNAL;
        }
    }
    if (len > (uint64_t)CFTR_HDR_BYTES + CFTR_MAX_PAYLOAD) {
        snprintf(why, why_size,
                 "WebSocket frame length %llu exceeds the %lu-byte cap; "
                 "refused before any of it is read",
                 (unsigned long long)len,
                 (unsigned long)(CFTR_HDR_BYTES + CFTR_MAX_PAYLOAD));
        return CFT_ERR_INTERNAL;
    }
    if ((*opcode & 0x8u) && (len > 125 || !*fin)) {
        snprintf(why, why_size, "a control frame that is fragmented or "
                 "longer than 125 bytes, which RFC 6455 5.5 forbids");
        return CFT_ERR_INTERNAL;
    }
    if (cftr_sock_recv_all(W->s, mask, 4)) {
        snprintf(why, why_size, "reading a WebSocket mask: %s",
                 cftr_sock_error());
        return CFT_ERR_INTERNAL;
    }
    if (len) {
        size_t i;
        p = (uint8_t *)malloc((size_t)len);
        if (!p) {
            snprintf(why, why_size, "out of memory for a %llu-byte "
                     "WebSocket frame", (unsigned long long)len);
            return CFT_ERR_OUT_OF_MEMORY;
        }
        if (cftr_sock_recv_all(W->s, p, (size_t)len)) {
            free(p);
            snprintf(why, why_size, "truncated WebSocket frame: %s",
                     cftr_sock_error());
            return cftr_sock_timed_out() ? CFT_ERR_TIMEOUT : CFT_ERR_INTERNAL;
        }
        for (i = 0; i < (size_t)len; i++)
            p[i] ^= mask[i & 3u];
    }

    switch (*opcode) {
    case WS_CLOSE:
        W->peer_closed = 1;
        ws_send_close(W, 1000);
        free(p);
        *control = 1;
        return 1;
    case WS_PING:
        rc = ws_send_control(W, WS_PONG, p, (size_t)len);
        free(p);
        *control = 1;
        if (rc) {
            snprintf(why, why_size, "answering a ping: %s",
                     cftr_sock_error());
            return CFT_ERR_INTERNAL;
        }
        return 0;
    case WS_PONG:
        free(p);
        *control = 1;
        return 0;
    case WS_CONT:
    case WS_BIN:
        *data = p;
        *data_len = (size_t)len;
        return 0;
    case WS_TEXT:
        free(p);
        /* CFT_ERR_INTERNAL, the status docs/REMOTE.md gives a transport
         * fault - and not CFT_ERR_INVALID_ARGUMENT, which is 1 and
         * would be read as a clean close by the caller. */
        snprintf(why, why_size, "a text message where a frame of "
                 "docs/REMOTE.md was due: this protocol is bytes, and a "
                 "text frame would have been through a UTF-8 round trip");
        return CFT_ERR_INTERNAL;
    default:
        free(p);
        snprintf(why, why_size, "WebSocket opcode 0x%x is not one RFC 6455 "
                 "assigns", *opcode);
        return CFT_ERR_INTERNAL;
    }
}

static int msg_append(ws_conn *W, const uint8_t *p, size_t len, char *why,
                      size_t why_size)
{
    if (W->msg_len + len > (size_t)CFTR_HDR_BYTES + CFTR_MAX_PAYLOAD) {
        snprintf(why, why_size, "a reassembled WebSocket message longer "
                 "than the %lu-byte cap",
                 (unsigned long)(CFTR_HDR_BYTES + CFTR_MAX_PAYLOAD));
        return CFT_ERR_INTERNAL;
    }
    if (W->msg_len + len > W->msg_cap) {
        size_t want = W->msg_cap ? W->msg_cap * 2 : 4096;
        uint8_t *q;
        while (want < W->msg_len + len)
            want *= 2;
        q = (uint8_t *)realloc(W->msg, want);
        if (!q) {
            snprintf(why, why_size, "out of memory reassembling a "
                     "WebSocket message");
            return CFT_ERR_OUT_OF_MEMORY;
        }
        W->msg = q;
        W->msg_cap = want;
    }
    if (len)
        memcpy(W->msg + W->msg_len, p, len);
    W->msg_len += len;
    return 0;
}

/* The checks a frame gets once it is whole. These are the checks
 * cftr_recv_frame makes in src/backend_remote.c, in the same order and
 * with the same words, over a message instead of a stream - the same
 * cftr_hdr_unpack and the same cftr_crc32 over the same bytes. They
 * are restated rather than shared because cftr_recv_frame reads from a
 * socket itself; factoring its checks into a cftr_check_frame() that
 * both callers use would remove this copy, and that belongs in
 * src/remote.h, which this step does not touch. */
static int check_message(const uint8_t *m, size_t mlen, cftr_hdr *h,
                         uint8_t **payload, uint32_t my_abi, char *why,
                         size_t why_size)
{
    uint8_t hdr[CFTR_HDR_BYTES];
    uint32_t want_crc, crc;
    uint8_t *p = NULL;
    int rc;

    *payload = NULL;
    if (mlen < CFTR_HDR_BYTES) {
        snprintf(why, why_size,
                 "a WebSocket message of %lu bytes cannot hold a %u-byte "
                 "frame header", (unsigned long)mlen,
                 (unsigned)CFTR_HDR_BYTES);
        return CFT_ERR_INTERNAL;
    }
    memcpy(hdr, m, CFTR_HDR_BYTES);
    rc = cftr_hdr_unpack(hdr, h, &want_crc);
    if (rc == -1) {
        snprintf(why, why_size,
                 "not a cft frame: magic %02x %02x %02x %02x, expected "
                 "'C' 'F' 'T' 'R'", hdr[0], hdr[1], hdr[2], hdr[3]);
        return CFT_ERR_INTERNAL;
    }
    if (rc == -2) {
        snprintf(why, why_size, "protocol version %u, this library speaks %u",
                 (unsigned)h->proto, (unsigned)CFTR_PROTO_VERSION);
        return CFT_ERR_UNSUPPORTED;
    }
    if (rc == -3) {
        snprintf(why, why_size, "reserved header word is not zero");
        return CFT_ERR_INTERNAL;
    }
    if (h->abi != my_abi) {
        snprintf(why, why_size,
                 "ABI mismatch: the other end is libcft %u.%u, this end is "
                 "%u.%u - the two libraries may not agree on which "
                 "operations exist, so this is refused rather than warned",
                 (unsigned)(h->abi >> 16), (unsigned)(h->abi & 0xFFFFu),
                 (unsigned)(my_abi >> 16), (unsigned)(my_abi & 0xFFFFu));
        return CFT_ERR_UNSUPPORTED;
    }
    if (h->length > CFTR_MAX_PAYLOAD) {
        snprintf(why, why_size,
                 "frame length %lu exceeds the %lu-byte cap; refused before "
                 "any of it is read", (unsigned long)h->length,
                 (unsigned long)CFTR_MAX_PAYLOAD);
        return CFT_ERR_INTERNAL;
    }
    /* A message boundary is what a stream has not got: a header whose
     * length does not match the bytes that came with it is caught here
     * and now, where the TCP path waits out its stall timeout for a
     * byte that never arrives and then refuses the same frame. Same
     * verdict, sooner. */
    if (h->length != mlen - CFTR_HDR_BYTES) {
        snprintf(why, why_size,
                 "truncated frame: the header claims %lu payload bytes and "
                 "the WebSocket message carries %lu",
                 (unsigned long)h->length,
                 (unsigned long)(mlen - CFTR_HDR_BYTES));
        return CFT_ERR_INTERNAL;
    }
    if (h->length) {
        p = (uint8_t *)malloc(h->length);
        if (!p) {
            snprintf(why, why_size, "out of memory for a %lu-byte payload",
                     (unsigned long)h->length);
            return CFT_ERR_OUT_OF_MEMORY;
        }
        memcpy(p, m + CFTR_HDR_BYTES, h->length);
    }
    cftr_put32(hdr + 24, 0);
    crc = cftr_crc32(0, hdr, CFTR_HDR_BYTES);
    if (h->length)
        crc = cftr_crc32(crc, p, h->length);
    if (crc != want_crc) {
        free(p);
        snprintf(why, why_size,
                 "frame crc %08x does not match the %08x it carries: a "
                 "corrupted frame, refused", (unsigned)crc,
                 (unsigned)want_crc);
        return CFT_ERR_INTERNAL;
    }
    *payload = p;
    return 0;
}

int ws_recv_frame(ws_conn *W, cftr_hdr *h, uint8_t **payload,
                  uint32_t my_abi, char *why, size_t why_size)
{
    *payload = NULL;
    for (;;) {
        uint8_t *data = NULL;
        size_t data_len = 0;
        unsigned opcode = 0;
        int fin = 0, control = 0, rc;

        rc = ws_read_one(W, &fin, &opcode, &data, &data_len, &control, why,
                         why_size);
        if (rc)
            return rc;
        if (control)
            return -1;                /* answered; nothing to serve */

        if (opcode == WS_BIN) {
            if (W->in_message) {
                free(data);
                snprintf(why, why_size, "a new message began while one was "
                         "still fragmented");
                return CFT_ERR_INTERNAL;
            }
            W->msg_len = 0;
        } else if (!W->in_message) {
            free(data);
            snprintf(why, why_size, "a continuation frame with no message "
                     "to continue");
            return CFT_ERR_INTERNAL;
        }
        rc = msg_append(W, data, data_len, why, why_size);
        free(data);
        if (rc) {
            W->in_message = 0;
            return rc;
        }
        if (!fin) {
            W->in_message = 1;
            continue;                 /* wait for the rest of it */
        }
        W->in_message = 0;
        return check_message(W->msg, W->msg_len, h, payload, my_abi, why,
                             why_size);
    }
}
