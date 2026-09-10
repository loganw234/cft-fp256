/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The remote backend: a device behind a socket.
 *
 * docs/REMOTE.md is the protocol, written before this file. What this
 * file adds to it is the division of labour with device.c, which is
 * the one the XRT backend already has: device.c checks arguments and
 * owns the status word, and the backend moves bytes. Only the calls
 * that touch a device cross the wire - cft_run, cft_reduce and the
 * program runs - and everything the library computes on the host is
 * computed on THIS host by this copy of the library, which is
 * bit-identical to the server's by contract.
 *
 * ---------------------------------------------------------------
 * Why the socket API is loaded, not linked, on Windows
 * ---------------------------------------------------------------
 *
 * libcft.a is linked by the Fortran, Go and Rust examples, the soak
 * tools and the C++ tests, none of which name ws2_32 - and Go's cgo
 * link would fail on an unresolved WSAStartup with no way to fix it
 * outside the example. So on Windows the fifteen Winsock entry points
 * this file uses are looked up in ws2_32.dll at first use, through a
 * table below, and the archive's link set is exactly what it was. On
 * POSIX the BSD calls are in libc and there is nothing to arrange.
 * That is what "an OS API, not a dependency" means in practice.
 *
 * ---------------------------------------------------------------
 * Failure is a poisoned handle
 * ---------------------------------------------------------------
 *
 * After a framing fault - a bad magic, a crc that does not match, a
 * truncated payload, a response carrying the wrong id - the byte
 * stream is unsynchronised, and reading on from it is how a later
 * request gets answered with an earlier response. So a transport
 * fault poisons the handle: every later call refuses until it is
 * closed and reopened, exactly as backend_xrt.cpp treats a handle
 * whose compute units may still be running. An operation that FAILED
 * on the server - an unsupported format, a bus fault - is not a
 * transport fault, comes back as an ordinary status, and leaves the
 * handle usable.
 */

#if !defined(_WIN32)
#  define _POSIX_C_SOURCE 200809L
#  define _DEFAULT_SOURCE 1
#endif

/* This module is optional: the cft:// device of docs/REMOTE.md,
 * removed entirely by -DCFT_NO_REMOTE. Removed rather than left for
 * the linker to garbage-collect, because what does not fit on a part
 * with 32 KB of flash is as often a constant table as it is code, and
 * a table reachable from one live function is not collected. */
#include "../include/cft_config.h"
#ifndef CFT_NO_REMOTE

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../include/cft.h"
#include "remote.h"

#if defined(__EMSCRIPTEN__)
/* ================================================================
 * A browser has no socket to offer, so the wasm build carries a stub
 * that says so. cft_open("cft://...") is CFT_ERR_NO_DEVICE there, the
 * same answer a build without XRT gives an xclbin path.
 * ================================================================ */
int cftr_is_url(const char *artifact)
{
    return artifact && strncmp(artifact, "cft://", 6) == 0;
}
int cftr_open(const char *url, int index, void **out,
              uint32_t *format_mask, uint32_t *op_groups,
              uint32_t *tiles, uint32_t *version, int *flags_readable,
              cft_seq_caps *seq)
{
    (void)url; (void)index; (void)format_mask; (void)op_groups;
    (void)tiles; (void)version; (void)flags_readable; (void)seq;
    if (out) *out = NULL;
    return CFT_ERR_NO_DEVICE;
}
void cftr_close(void *hw) { (void)hw; }
int cftr_run(void *hw, int op, int fmt, int rnd,
             const void *a, const void *b, const void *c, void *d,
             size_t n, uint32_t *flags, uint32_t *bus)
{
    (void)hw; (void)op; (void)fmt; (void)rnd; (void)a; (void)b; (void)c;
    (void)d; (void)n; (void)flags; (void)bus;
    return CFT_ERR_INTERNAL;
}
int cftr_reduce(void *hw, int op, int fmt, int rnd,
                const void *a, const void *b, void *d, size_t n,
                uint32_t *flags, uint32_t *bus)
{
    (void)hw; (void)op; (void)fmt; (void)rnd; (void)a; (void)b; (void)d;
    (void)n; (void)flags; (void)bus;
    return CFT_ERR_INTERNAL;
}
int cftr_program_run(void *hw, int fmt, const void *image,
                     size_t image_bytes, const cft_seq_run_io *io,
                     uint32_t max_deposits,
                     const void *a, const void *b, const void *c,
                     void *deposits, uint32_t *counts, size_t n,
                     uint32_t *flags, uint32_t *bus)
{
    (void)hw; (void)fmt; (void)image; (void)image_bytes; (void)max_deposits;
    (void)io;
    (void)a; (void)b; (void)c; (void)deposits; (void)counts; (void)n;
    (void)flags; (void)bus;
    return CFT_ERR_INTERNAL;
}
const char *cftr_last_error(void) { return ""; }

#else  /* the real thing */

#if defined(_WIN32)
#  ifndef WIN32_LEAN_AND_MEAN
#    define WIN32_LEAN_AND_MEAN
#  endif
#  include <winsock2.h>
#  include <ws2tcpip.h>
#  include <windows.h>
#else
#  include <errno.h>
#  include <netdb.h>
#  include <netinet/in.h>
#  include <netinet/tcp.h>
#  include <sys/select.h>
#  include <sys/socket.h>
#  include <sys/time.h>
#  include <sys/types.h>
#  include <unistd.h>
#  ifndef MSG_NOSIGNAL
#    define MSG_NOSIGNAL 0
#  endif
#endif

/* ---- error text ---------------------------------------------------- */

static char g_sock_err[256];
static int  g_sock_timed_out;
static char g_err[512];

static void set_err(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(g_err, sizeof g_err, fmt, ap);
    va_end(ap);
}

const char *cftr_last_error(void)
{
    return g_err;
}

const char *cftr_sock_error(void)
{
    return g_sock_err;
}

int cftr_sock_timed_out(void)
{
    return g_sock_timed_out;
}

/* ---- little-endian fields ------------------------------------------ */

void cftr_put16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
}

void cftr_put32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16);
    p[3] = (uint8_t)(v >> 24);
}

void cftr_put64(uint8_t *p, uint64_t v)
{
    cftr_put32(p, (uint32_t)v);
    cftr_put32(p + 4, (uint32_t)(v >> 32));
}

uint16_t cftr_get16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

uint32_t cftr_get32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

uint64_t cftr_get64(const uint8_t *p)
{
    return (uint64_t)cftr_get32(p) | ((uint64_t)cftr_get32(p + 4) << 32);
}

/* ---- CRC-32 -------------------------------------------------------- *
 *
 * The reflected polynomial is the one constant here that is
 * transcribed, in the base its definition uses; the table is derived
 * from it, and cftr_crc32_selfcheck() holds the result against the
 * standard's own check value before any frame is sent. Two things
 * that share no code agreeing on a value is the only evidence a typed
 * constant ever gets.
 */
static uint32_t g_crc_table[256];
static int      g_crc_ready;

static void crc_init(void)
{
    uint32_t i, j;
    if (g_crc_ready)
        return;
    for (i = 0; i < 256; i++) {
        uint32_t c = i;
        for (j = 0; j < 8; j++)
            c = (c & 1u) ? (0xEDB88320u ^ (c >> 1)) : (c >> 1);
        g_crc_table[i] = c;
    }
    g_crc_ready = 1;
}

uint32_t cftr_crc32(uint32_t seed, const void *data, size_t len)
{
    const uint8_t *p = (const uint8_t *)data;
    uint32_t c = ~seed;
    size_t i;
    crc_init();
    for (i = 0; i < len; i++)
        c = g_crc_table[(c ^ p[i]) & 0xFFu] ^ (c >> 8);
    return ~c;
}

int cftr_crc32_selfcheck(void)
{
    return cftr_crc32(0, "123456789", 9) == 0xCBF43926u ? 0 : -1;
}

/* ---- header ----------------------------------------------------------- */

void cftr_hdr_pack(const cftr_hdr *h, uint8_t out[32])
{
    memset(out, 0, 32);
    cftr_put32(out + 0, CFTR_MAGIC);
    cftr_put16(out + 4, h->proto);
    cftr_put16(out + 6, h->kind);
    cftr_put32(out + 8, h->abi);
    cftr_put32(out + 12, h->id);
    cftr_put16(out + 16, h->op);
    cftr_put16(out + 18, h->status);
    cftr_put32(out + 20, h->length);
    cftr_put32(out + 24, 0);            /* crc, filled by the sender */
    cftr_put32(out + 28, 0);            /* reserved */
}

/* 0 on a header that is at least well-formed enough to read; -1 for a
 * wrong magic, -2 for a wrong protocol version, -3 for a nonzero
 * reserved word. The crc is returned for the caller to check once the
 * payload is in hand. */
int cftr_hdr_unpack(const uint8_t in[32], cftr_hdr *h, uint32_t *crc)
{
    if (cftr_get32(in + 0) != CFTR_MAGIC)
        return -1;
    h->proto  = cftr_get16(in + 4);
    h->kind   = cftr_get16(in + 6);
    h->abi    = cftr_get32(in + 8);
    h->id     = cftr_get32(in + 12);
    h->op     = cftr_get16(in + 16);
    h->status = cftr_get16(in + 18);
    h->length = cftr_get32(in + 20);
    *crc      = cftr_get32(in + 24);
    if (h->proto != CFTR_PROTO_VERSION)
        return -2;
    if (cftr_get32(in + 28) != 0)
        return -3;
    return 0;
}

/* ---- the socket shim --------------------------------------------------- */

#if defined(_WIN32)

/* The Winsock entry points, resolved from ws2_32.dll at first use. The
 * names carry a trailing underscore because <winsock2.h> is included
 * for its types and constants, and its declarations of the real
 * functions would otherwise collide. */
static struct {
    HMODULE lib;
    int    (WSAAPI *WSAStartup_)(WORD, LPWSADATA);
    int    (WSAAPI *WSAGetLastError_)(void);
    SOCKET (WSAAPI *socket_)(int, int, int);
    int    (WSAAPI *connect_)(SOCKET, const struct sockaddr *, int);
    int    (WSAAPI *bind_)(SOCKET, const struct sockaddr *, int);
    int    (WSAAPI *listen_)(SOCKET, int);
    SOCKET (WSAAPI *accept_)(SOCKET, struct sockaddr *, int *);
    int    (WSAAPI *send_)(SOCKET, const char *, int, int);
    int    (WSAAPI *recv_)(SOCKET, char *, int, int);
    int    (WSAAPI *setsockopt_)(SOCKET, int, int, const char *, int);
    int    (WSAAPI *closesocket_)(SOCKET);
    int    (WSAAPI *getaddrinfo_)(const char *, const char *,
                                  const struct addrinfo *,
                                  struct addrinfo **);
    void   (WSAAPI *freeaddrinfo_)(struct addrinfo *);
    int    (WSAAPI *getsockname_)(SOCKET, struct sockaddr *, int *);
    int    (WSAAPI *select_)(int, fd_set *, fd_set *, fd_set *,
                             const struct timeval *);
    int    ready;
} W;

static void *w_sym(const char *name)
{
    /* FARPROC to an object pointer is the documented GetProcAddress
     * idiom on Windows, where the two have the same size; the
     * intermediate cast keeps a pedantic compiler quiet about it. */
    FARPROC f = GetProcAddress(W.lib, name);
    return f ? *(void **)(void *)&f : NULL;
}

static void w_fail(const char *what)
{
    int code = W.WSAGetLastError_ ? W.WSAGetLastError_() : 0;
    g_sock_timed_out = (code == WSAETIMEDOUT);
    snprintf(g_sock_err, sizeof g_sock_err, "%s: winsock error %d", what,
             code);
}

int cftr_sock_init(void)
{
    WSADATA wsd;
    if (W.ready)
        return 0;
    g_sock_timed_out = 0;
    W.lib = LoadLibraryA("ws2_32.dll");
    if (!W.lib) {
        snprintf(g_sock_err, sizeof g_sock_err,
                 "ws2_32.dll could not be loaded (error %lu)",
                 (unsigned long)GetLastError());
        return -1;
    }
#define W_SYM(name) do { \
        *(void **)(void *)&W.name##_ = w_sym(#name); \
        if (!W.name##_) { \
            snprintf(g_sock_err, sizeof g_sock_err, \
                     "ws2_32.dll has no %s", #name); \
            return -1; \
        } } while (0)
    W_SYM(WSAStartup);
    W_SYM(WSAGetLastError);
    W_SYM(socket);
    W_SYM(connect);
    W_SYM(bind);
    W_SYM(listen);
    W_SYM(accept);
    W_SYM(send);
    W_SYM(recv);
    W_SYM(setsockopt);
    W_SYM(closesocket);
    W_SYM(getaddrinfo);
    W_SYM(freeaddrinfo);
    W_SYM(getsockname);
    W_SYM(select);
#undef W_SYM
    if (W.WSAStartup_(MAKEWORD(2, 2), &wsd) != 0) {
        w_fail("WSAStartup");
        return -1;
    }
    W.ready = 1;
    return 0;
}

static int set_nodelay(cftr_sock s)
{
    BOOL on = TRUE;
    return W.setsockopt_((SOCKET)s, IPPROTO_TCP, TCP_NODELAY,
                         (const char *)&on, (int)sizeof on);
}

/* A client that vanished without closing - a laptop that lost its
 * route mid-run - would otherwise hold this connection's device until
 * the server exits, because a socket nobody writes to never becomes
 * readable. Keepalive probes turn that silence into a close. Windows
 * starts probing after its default two hours of idle: long, but
 * bounded; the Linux path tunes it to about a minute. */
static int set_keepalive(cftr_sock s)
{
    BOOL on = TRUE;
    return W.setsockopt_((SOCKET)s, SOL_SOCKET, SO_KEEPALIVE,
                         (const char *)&on, (int)sizeof on);
}

int cftr_sock_timeout(cftr_sock s, long ms)
{
    DWORD v = (DWORD)(ms < 0 ? 0 : ms);
    if (W.setsockopt_((SOCKET)s, SOL_SOCKET, SO_RCVTIMEO,
                      (const char *)&v, (int)sizeof v) != 0) {
        w_fail("setsockopt(SO_RCVTIMEO)");
        return -1;
    }
    return 0;
}

cftr_sock cftr_sock_connect(const char *host, const char *port)
{
    struct addrinfo hints, *res = NULL, *ai;
    SOCKET s = INVALID_SOCKET;
    int rc;

    if (cftr_sock_init())
        return CFTR_BAD_SOCK;
    g_sock_timed_out = 0;
    memset(&hints, 0, sizeof hints);
    hints.ai_family   = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_protocol = IPPROTO_TCP;
    rc = W.getaddrinfo_(host, port, &hints, &res);
    if (rc != 0 || !res) {
        snprintf(g_sock_err, sizeof g_sock_err,
                 "resolving %s:%s: getaddrinfo error %d", host, port, rc);
        return CFTR_BAD_SOCK;
    }
    for (ai = res; ai; ai = ai->ai_next) {
        s = W.socket_(ai->ai_family, ai->ai_socktype, ai->ai_protocol);
        if (s == INVALID_SOCKET)
            continue;
        if (W.connect_(s, ai->ai_addr, (int)ai->ai_addrlen) == 0)
            break;
        w_fail("connect");
        W.closesocket_(s);
        s = INVALID_SOCKET;
    }
    W.freeaddrinfo_(res);
    if (s == INVALID_SOCKET) {
        if (!g_sock_err[0])
            snprintf(g_sock_err, sizeof g_sock_err, "no address for %s:%s",
                     host, port);
        return CFTR_BAD_SOCK;
    }
    set_nodelay((cftr_sock)s);
    return (cftr_sock)s;
}

cftr_sock cftr_sock_listen(const char *addr, const char *port, int backlog,
                           int *bound_port)
{
    struct addrinfo hints, *res = NULL, *ai;
    SOCKET s = INVALID_SOCKET;
    int rc;

    if (cftr_sock_init())
        return CFTR_BAD_SOCK;
    memset(&hints, 0, sizeof hints);
    hints.ai_family   = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_protocol = IPPROTO_TCP;
    hints.ai_flags    = addr ? 0 : AI_PASSIVE;
    rc = W.getaddrinfo_(addr, port, &hints, &res);
    if (rc != 0 || !res) {
        snprintf(g_sock_err, sizeof g_sock_err,
                 "resolving %s:%s: getaddrinfo error %d",
                 addr ? addr : "*", port, rc);
        return CFTR_BAD_SOCK;
    }
    for (ai = res; ai; ai = ai->ai_next) {
        s = W.socket_(ai->ai_family, ai->ai_socktype, ai->ai_protocol);
        if (s == INVALID_SOCKET)
            continue;
        if (W.bind_(s, ai->ai_addr, (int)ai->ai_addrlen) == 0 &&
            W.listen_(s, backlog) == 0)
            break;
        w_fail("bind/listen");
        W.closesocket_(s);
        s = INVALID_SOCKET;
    }
    W.freeaddrinfo_(res);
    if (s == INVALID_SOCKET)
        return CFTR_BAD_SOCK;
    if (bound_port) {
        struct sockaddr_storage ss;
        int len = (int)sizeof ss;
        *bound_port = 0;
        if (W.getsockname_(s, (struct sockaddr *)&ss, &len) == 0) {
            if (ss.ss_family == AF_INET)
                *bound_port = (int)((((struct sockaddr_in *)&ss)->sin_port >> 8) |
                                    ((((struct sockaddr_in *)&ss)->sin_port & 0xFFu) << 8));
            else if (ss.ss_family == AF_INET6)
                *bound_port = (int)((((struct sockaddr_in6 *)&ss)->sin6_port >> 8) |
                                    ((((struct sockaddr_in6 *)&ss)->sin6_port & 0xFFu) << 8));
        }
    }
    return (cftr_sock)s;
}

cftr_sock cftr_sock_accept(cftr_sock listener)
{
    SOCKET c = W.accept_((SOCKET)listener, NULL, NULL);
    if (c == INVALID_SOCKET) {
        w_fail("accept");
        return CFTR_BAD_SOCK;
    }
    set_nodelay((cftr_sock)c);
    set_keepalive((cftr_sock)c);
    return (cftr_sock)c;
}

int cftr_sock_send_all(cftr_sock s, const void *buf, size_t len)
{
    const char *p = (const char *)buf;
    while (len) {
        int chunk = len > 0x40000000u ? 0x40000000 : (int)len;
        int n = W.send_((SOCKET)s, p, chunk, 0);
        if (n <= 0) {
            w_fail("send");
            return -1;
        }
        p += n;
        len -= (size_t)n;
    }
    return 0;
}

int cftr_sock_recv_all(cftr_sock s, void *buf, size_t len)
{
    char *p = (char *)buf;
    size_t got = 0;
    g_sock_timed_out = 0;
    while (got < len) {
        int chunk = (len - got) > 0x40000000u ? 0x40000000 : (int)(len - got);
        int n = W.recv_((SOCKET)s, p + got, chunk, 0);
        if (n == 0) {
            if (got == 0)
                return 1;               /* clean EOF */
            snprintf(g_sock_err, sizeof g_sock_err,
                     "connection closed after %lu of %lu bytes",
                     (unsigned long)got, (unsigned long)len);
            return -1;
        }
        if (n < 0) {
            w_fail("recv");
            return -1;
        }
        got += (size_t)n;
    }
    return 0;
}

void cftr_sock_close(cftr_sock s)
{
    if (s != CFTR_BAD_SOCK && W.closesocket_)
        W.closesocket_((SOCKET)s);
}

/* Winsock's fd_set is a counted array of SOCKETs, and FD_ISSET on it
 * is a call into ws2_32 (__WSAFDIsSet) - so the set is built and read
 * by hand here, which keeps the archive free of that import too. */
int cftr_sock_select(const cftr_sock *socks, int n, int *ready,
                     long timeout_ms)
{
    fd_set rfds;
    struct timeval tv, *ptv = NULL;
    int i, rc, count = 0;

    rfds.fd_count = 0;
    for (i = 0; i < n && rfds.fd_count < FD_SETSIZE; i++)
        rfds.fd_array[rfds.fd_count++] = (SOCKET)socks[i];
    if (timeout_ms >= 0) {
        tv.tv_sec  = (long)(timeout_ms / 1000);
        tv.tv_usec = (long)((timeout_ms % 1000) * 1000);
        ptv = &tv;
    }
    rc = W.select_(0, &rfds, NULL, NULL, ptv);
    if (rc < 0) {
        w_fail("select");
        return -1;
    }
    for (i = 0; i < n; i++) {
        unsigned j;
        ready[i] = 0;
        for (j = 0; j < rfds.fd_count; j++)
            if (rfds.fd_array[j] == (SOCKET)socks[i]) {
                ready[i] = 1;
                count++;
                break;
            }
    }
    return count;
}

#else  /* POSIX */

static void p_fail(const char *what)
{
    g_sock_timed_out = (errno == EAGAIN || errno == EWOULDBLOCK);
    snprintf(g_sock_err, sizeof g_sock_err, "%s: %s", what, strerror(errno));
}

int cftr_sock_init(void)
{
    g_sock_timed_out = 0;
    return 0;
}

static int set_nodelay(cftr_sock s)
{
    int on = 1;
    return setsockopt((int)s, IPPROTO_TCP, TCP_NODELAY, &on, sizeof on);
}

/* See the Windows twin above. Where the knobs exist (Linux), the
 * probes start after 30 s of silence, repeat every 10 s and give up
 * after three, so a dead client releases its tile in about a minute;
 * elsewhere the OS defaults apply, long but bounded. */
static int set_keepalive(cftr_sock s)
{
    int on = 1;
    int rc = setsockopt((int)s, SOL_SOCKET, SO_KEEPALIVE, &on, sizeof on);
#if defined(TCP_KEEPIDLE) && defined(TCP_KEEPINTVL) && defined(TCP_KEEPCNT)
    if (rc == 0) {
        int idle = 30, intvl = 10, cnt = 3;
        setsockopt((int)s, IPPROTO_TCP, TCP_KEEPIDLE, &idle, sizeof idle);
        setsockopt((int)s, IPPROTO_TCP, TCP_KEEPINTVL, &intvl, sizeof intvl);
        setsockopt((int)s, IPPROTO_TCP, TCP_KEEPCNT, &cnt, sizeof cnt);
    }
#endif
    return rc;
}

int cftr_sock_timeout(cftr_sock s, long ms)
{
    struct timeval tv;
    tv.tv_sec  = ms / 1000;
    tv.tv_usec = (ms % 1000) * 1000;
    if (setsockopt((int)s, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv) != 0) {
        p_fail("setsockopt(SO_RCVTIMEO)");
        return -1;
    }
    return 0;
}

cftr_sock cftr_sock_connect(const char *host, const char *port)
{
    struct addrinfo hints, *res = NULL, *ai;
    int s = -1, rc;

    g_sock_timed_out = 0;
    memset(&hints, 0, sizeof hints);
    hints.ai_family   = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    rc = getaddrinfo(host, port, &hints, &res);
    if (rc != 0 || !res) {
        snprintf(g_sock_err, sizeof g_sock_err, "resolving %s:%s: %s",
                 host, port, gai_strerror(rc));
        return CFTR_BAD_SOCK;
    }
    for (ai = res; ai; ai = ai->ai_next) {
        s = socket(ai->ai_family, ai->ai_socktype, ai->ai_protocol);
        if (s < 0)
            continue;
        if (connect(s, ai->ai_addr, ai->ai_addrlen) == 0)
            break;
        p_fail("connect");
        close(s);
        s = -1;
    }
    freeaddrinfo(res);
    if (s < 0) {
        if (!g_sock_err[0])
            snprintf(g_sock_err, sizeof g_sock_err, "no address for %s:%s",
                     host, port);
        return CFTR_BAD_SOCK;
    }
    set_nodelay(s);
    return s;
}

cftr_sock cftr_sock_listen(const char *addr, const char *port, int backlog,
                           int *bound_port)
{
    struct addrinfo hints, *res = NULL, *ai;
    int s = -1, rc;

    memset(&hints, 0, sizeof hints);
    hints.ai_family   = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_flags    = addr ? 0 : AI_PASSIVE;
    rc = getaddrinfo(addr, port, &hints, &res);
    if (rc != 0 || !res) {
        snprintf(g_sock_err, sizeof g_sock_err, "resolving %s:%s: %s",
                 addr ? addr : "*", port, gai_strerror(rc));
        return CFTR_BAD_SOCK;
    }
    for (ai = res; ai; ai = ai->ai_next) {
        int on = 1;
        s = socket(ai->ai_family, ai->ai_socktype, ai->ai_protocol);
        if (s < 0)
            continue;
        /* A restarted server should not wait out TIME_WAIT on the
         * port its last incarnation used. */
        setsockopt(s, SOL_SOCKET, SO_REUSEADDR, &on, sizeof on);
        if (bind(s, ai->ai_addr, ai->ai_addrlen) == 0 &&
            listen(s, backlog) == 0)
            break;
        p_fail("bind/listen");
        close(s);
        s = -1;
    }
    freeaddrinfo(res);
    if (s < 0)
        return CFTR_BAD_SOCK;
    if (bound_port) {
        struct sockaddr_storage ss;
        socklen_t len = sizeof ss;
        *bound_port = 0;
        if (getsockname(s, (struct sockaddr *)&ss, &len) == 0) {
            if (ss.ss_family == AF_INET)
                *bound_port = (int)ntohs(((struct sockaddr_in *)&ss)->sin_port);
            else if (ss.ss_family == AF_INET6)
                *bound_port = (int)ntohs(((struct sockaddr_in6 *)&ss)->sin6_port);
        }
    }
    return s;
}

cftr_sock cftr_sock_accept(cftr_sock listener)
{
    int c = accept((int)listener, NULL, NULL);
    if (c < 0) {
        p_fail("accept");
        return CFTR_BAD_SOCK;
    }
    set_nodelay(c);
    set_keepalive(c);
    return c;
}

int cftr_sock_send_all(cftr_sock s, const void *buf, size_t len)
{
    const char *p = (const char *)buf;
    while (len) {
        ssize_t n = send((int)s, p, len, MSG_NOSIGNAL);
        if (n <= 0) {
            if (n < 0 && errno == EINTR)
                continue;
            p_fail("send");
            return -1;
        }
        p += n;
        len -= (size_t)n;
    }
    return 0;
}

int cftr_sock_recv_all(cftr_sock s, void *buf, size_t len)
{
    char *p = (char *)buf;
    size_t got = 0;
    g_sock_timed_out = 0;
    while (got < len) {
        ssize_t n = recv((int)s, p + got, len - got, 0);
        if (n == 0) {
            if (got == 0)
                return 1;               /* clean EOF */
            snprintf(g_sock_err, sizeof g_sock_err,
                     "connection closed after %lu of %lu bytes",
                     (unsigned long)got, (unsigned long)len);
            return -1;
        }
        if (n < 0) {
            if (errno == EINTR)
                continue;
            p_fail("recv");
            return -1;
        }
        got += (size_t)n;
    }
    return 0;
}

void cftr_sock_close(cftr_sock s)
{
    if (s != CFTR_BAD_SOCK)
        close((int)s);
}

int cftr_sock_select(const cftr_sock *socks, int n, int *ready,
                     long timeout_ms)
{
    fd_set rfds;
    struct timeval tv, *ptv = NULL;
    int i, rc, maxfd = -1, count = 0;

    FD_ZERO(&rfds);
    for (i = 0; i < n; i++) {
        int fd = (int)socks[i];
        if (fd < 0 || fd >= FD_SETSIZE) {
            snprintf(g_sock_err, sizeof g_sock_err,
                     "descriptor %d is beyond FD_SETSIZE", fd);
            return -1;
        }
        FD_SET(fd, &rfds);
        if (fd > maxfd)
            maxfd = fd;
    }
    if (timeout_ms >= 0) {
        tv.tv_sec  = timeout_ms / 1000;
        tv.tv_usec = (timeout_ms % 1000) * 1000;
        ptv = &tv;
    }
    rc = select(maxfd + 1, &rfds, NULL, NULL, ptv);
    if (rc < 0) {
        if (errno == EINTR)
            return 0;
        p_fail("select");
        return -1;
    }
    for (i = 0; i < n; i++) {
        ready[i] = FD_ISSET((int)socks[i], &rfds) ? 1 : 0;
        count += ready[i];
    }
    return count;
}

#endif /* platform shim */

/* ---- frames --------------------------------------------------------- */

int cftr_send_frame(cftr_sock s, const cftr_hdr *h, const void *payload,
                    size_t len)
{
    uint8_t hdr[CFTR_HDR_BYTES];
    uint32_t crc;
    cftr_hdr hh = *h;

    if (len > CFTR_MAX_PAYLOAD) {
        snprintf(g_sock_err, sizeof g_sock_err,
                 "frame payload of %lu bytes exceeds the cap",
                 (unsigned long)len);
        return -1;
    }
    hh.length = (uint32_t)len;
    cftr_hdr_pack(&hh, hdr);
    crc = cftr_crc32(0, hdr, CFTR_HDR_BYTES);
    if (len)
        crc = cftr_crc32(crc, payload, len);
    cftr_put32(hdr + 24, crc);

    /* One send for a small frame, so header and payload share a
     * segment; two for a large one, so the payload is not copied. */
    if (len <= 65536) {
        uint8_t small[CFTR_HDR_BYTES + 65536];
        memcpy(small, hdr, CFTR_HDR_BYTES);
        if (len)
            memcpy(small + CFTR_HDR_BYTES, payload, len);
        return cftr_sock_send_all(s, small, CFTR_HDR_BYTES + len);
    }
    if (cftr_sock_send_all(s, hdr, CFTR_HDR_BYTES))
        return -1;
    return cftr_sock_send_all(s, payload, len);
}

int cftr_recv_frame(cftr_sock s, cftr_hdr *h, uint8_t **payload,
                    uint32_t my_abi, char *why, size_t why_size)
{
    uint8_t hdr[CFTR_HDR_BYTES];
    uint32_t want_crc, crc;
    uint8_t *p = NULL;
    int rc;

    *payload = NULL;
    rc = cftr_sock_recv_all(s, hdr, CFTR_HDR_BYTES);
    if (rc == 1)
        return 1;
    if (rc) {
        snprintf(why, why_size, "reading a frame header: %s", g_sock_err);
        return g_sock_timed_out ? CFT_ERR_TIMEOUT : CFT_ERR_INTERNAL;
    }
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
    if (h->length) {
        p = (uint8_t *)malloc(h->length);
        if (!p) {
            snprintf(why, why_size, "out of memory for a %lu-byte payload",
                     (unsigned long)h->length);
            return CFT_ERR_OUT_OF_MEMORY;
        }
        rc = cftr_sock_recv_all(s, p, h->length);
        if (rc) {
            free(p);
            snprintf(why, why_size, "truncated frame: %s", g_sock_err);
            return g_sock_timed_out ? CFT_ERR_TIMEOUT : CFT_ERR_INTERNAL;
        }
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

/* ---- the client handle -------------------------------------------------- */

typedef struct rdev {
    cftr_sock s;
    uint32_t  next_id;
    uint32_t  abi;                      /* this library's */
    int       poisoned;
    int       poison_status;
    /* the caps block from HELLO */
    uint32_t  format_mask, op_groups, tiles, device_version;
    uint32_t  flags_readable, server_abi;
    /* The server device's sequencer capacities, all zero when its caps
     * block predates them. Kept here beside the rest of the block, not
     * merely forwarded, so a later CAPS request can be compared with
     * what HELLO said. */
    cft_seq_caps seq;
    char      server_backend[CFTR_BACKEND_NAME + 1];
    char      url[256];
    /* the one-entry program cache: the image bytes the server holds
     * under `phandle`, so a second run of the same program is one
     * round trip rather than three */
    uint8_t  *pimg;
    size_t    pimg_bytes;
    uint32_t  phandle, pfmt, pmaxdep;
    int       has_prog;
} rdev;

static void poison(rdev *R, int status, const char *msg)
{
    R->poisoned = 1;
    R->poison_status = status;
    set_err("%s - this remote handle is finished; close it and open it "
            "again (%s)", msg, R->url);
}

/* How long to wait for a response. Twenty minutes rather than the XRT
 * backend's sixty-second default, and for a reason: a remote server
 * may be a software backend, and a program of ten million steps over
 * four thousand lanes is a legitimate minute of its time. The cap is
 * XRT's, for XRT's reason (a value past 2^31 microseconds misbehaves
 * below some socket APIs too). */
static long timeout_ms(void)
{
    const long CAP = 20L * 60L * 1000L;
    const char *e = getenv("CFT_TIMEOUT_MS");
    long ms = CAP;
    if (e && *e)
        ms = strtol(e, NULL, 10);
    if (ms <= 0 || ms > CAP)
        ms = CAP;
    return ms;
}

/* One request, one response. Returns 0 when a response arrived and
 * *status is its verdict; -1 when the handle is (now) poisoned. */
static int do_request(rdev *R, uint16_t op, const void *req, size_t req_len,
                      int *status, uint8_t **resp, size_t *resp_len)
{
    cftr_hdr h, rh;
    uint8_t *p = NULL;
    char why[384];
    int rc;

    *resp = NULL;
    *resp_len = 0;
    *status = CFT_ERR_INTERNAL;
    if (R->poisoned) {
        set_err("this remote handle was poisoned by an earlier transport "
                "fault; close it and open it again (%s)", R->url);
        return -1;
    }
    memset(&h, 0, sizeof h);
    h.proto  = CFTR_PROTO_VERSION;
    h.kind   = CFTR_KIND_REQUEST;
    h.abi    = R->abi;
    h.id     = ++R->next_id;
    h.op     = op;
    h.status = 0;
    if (cftr_send_frame(R->s, &h, req, req_len)) {
        snprintf(why, sizeof why, "sending a request: %s", g_sock_err);
        poison(R, CFT_ERR_INTERNAL, why);
        return -1;
    }
    rc = cftr_recv_frame(R->s, &rh, &p, R->abi, why, sizeof why);
    if (rc == 1) {
        poison(R, CFT_ERR_INTERNAL, "the server closed the connection");
        return -1;
    }
    if (rc) {
        poison(R, rc, why);
        return -1;
    }
    if (rh.id != h.id || rh.op != op) {
        snprintf(why, sizeof why,
                 "response id %lu op 0x%04x for request id %lu op 0x%04x: "
                 "the stream is out of step", (unsigned long)rh.id,
                 (unsigned)rh.op, (unsigned long)h.id, (unsigned)op);
        free(p);
        poison(R, CFT_ERR_INTERNAL, why);
        return -1;
    }
    if (rh.kind == CFTR_KIND_REFUSAL) {
        snprintf(why, sizeof why, "the server refused the request: %.*s",
                 p ? (int)rh.length : 0, p ? (const char *)p : "");
        free(p);
        poison(R, rh.status ? (int)rh.status : CFT_ERR_INTERNAL, why);
        return -1;
    }
    if (rh.kind != CFTR_KIND_RESPONSE) {
        free(p);
        poison(R, CFT_ERR_INTERNAL, "a frame that is neither a response "
                                    "nor a refusal");
        return -1;
    }
    *status = (int)rh.status;
    if (rh.status != CFT_OK) {
        /* the operation's own failure: the payload is its message */
        set_err("%.*s", p ? (int)rh.length : 0, p ? (const char *)p : "");
        free(p);
        return 0;
    }
    *resp = p;
    *resp_len = rh.length;
    return 0;
}

int cftr_request(void *hw, uint16_t op, const void *payload, size_t len,
                 int *status, uint8_t **resp, size_t *resp_len)
{
    return do_request((rdev *)hw, op, payload, len, status, resp, resp_len);
}

const char *cftr_server_backend(void *hw)
{
    return hw ? ((rdev *)hw)->server_backend : "";
}

int cftr_is_url(const char *artifact)
{
    return artifact && strncmp(artifact, "cft://", 6) == 0;
}

/* "cft://host:port", "cft://[v6]:port". Host and port come back as
 * strings because getaddrinfo takes them that way, which also means no
 * byte order is ever touched here. */
static int parse_url(const char *url, char *host, size_t host_size,
                     char *port, size_t port_size)
{
    const char *p = url + 6, *h0, *h1, *q;
    size_t n;
    unsigned long v;

    if (*p == '[') {
        h0 = p + 1;
        h1 = strchr(h0, ']');
        if (!h1 || h1[1] != ':')
            return -1;
        q = h1 + 2;
    } else {
        h0 = p;
        h1 = strrchr(p, ':');
        if (!h1)
            return -1;
        q = h1 + 1;
    }
    n = (size_t)(h1 - h0);
    if (n == 0 || n + 1 > host_size)
        return -1;
    memcpy(host, h0, n);
    host[n] = '\0';
    if (!*q || strlen(q) + 1 > port_size)
        return -1;
    v = 0;
    for (p = q; *p; p++) {
        if (*p < '0' || *p > '9')
            return -1;
        v = v * 10 + (unsigned long)(*p - '0');
        if (v > 65535)
            return -1;
    }
    if (v == 0)
        return -1;
    strcpy(port, q);
    return 0;
}

static void rdev_free(rdev *R)
{
    if (!R)
        return;
    if (R->s != CFTR_BAD_SOCK)
        cftr_sock_close(R->s);
    free(R->pimg);
    free(R);
}

int cftr_open(const char *url, int index, void **out,
              uint32_t *format_mask, uint32_t *op_groups,
              uint32_t *tiles, uint32_t *version, int *flags_readable,
              cft_seq_caps *seq)
{
    char host[200], port[8];
    rdev *R;
    uint8_t *resp = NULL;
    size_t resp_len = 0;
    int status;

    if (!url || !out)
        return CFT_ERR_INVALID_ARGUMENT;
    *out = NULL;
    g_err[0] = '\0';
    if (!cftr_is_url(url))
        return CFT_ERR_INVALID_ARGUMENT;
    if (parse_url(url, host, sizeof host, port, sizeof port)) {
        set_err("\"%s\" is not of the form cft://host:port", url);
        return CFT_ERR_INVALID_ARGUMENT;
    }
    /* The URL names the device; there is no second one at this
     * address to index. The same answer the software backend gives an
     * index other than 0. */
    if (index != 0)
        return CFT_ERR_NO_DEVICE;
    if (cftr_crc32_selfcheck()) {
        set_err("the CRC-32 implementation failed its check value; "
                "refusing to speak a protocol it cannot checksum");
        return CFT_ERR_INTERNAL;
    }

    R = (rdev *)calloc(1, sizeof *R);
    if (!R)
        return CFT_ERR_OUT_OF_MEMORY;
    R->s = CFTR_BAD_SOCK;
    R->abi = cft_abi_version();
    snprintf(R->url, sizeof R->url, "%s", url);

    if (cftr_sock_init()) {
        set_err("%s", g_sock_err);
        rdev_free(R);
        return CFT_ERR_NO_DEVICE;
    }
    R->s = cftr_sock_connect(host, port);
    if (R->s == CFTR_BAD_SOCK) {
        set_err("connecting to %s: %s", url, g_sock_err);
        rdev_free(R);
        return CFT_ERR_NO_DEVICE;
    }
    cftr_sock_timeout(R->s, timeout_ms());

    if (do_request(R, CFTR_OP_HELLO, NULL, 0, &status, &resp, &resp_len)) {
        int st = R->poison_status;
        rdev_free(R);
        return st;
    }
    if (status != CFT_OK) {
        /* The server could not open ITS device - a bad artifact, no
         * card. Its message is already in g_err. */
        rdev_free(R);
        return status;
    }
    /* Short is a SERVER FROM BEFORE the block grew, and its missing
     * fields read as zero - which cft_caps documents as unknown, and
     * against which nothing is enforced. Shorter than V1 is not a
     * version, it is a stream that is not a caps block. */
    if (resp_len < CFTR_CAPS_BYTES_V1) {
        free(resp);
        set_err("HELLO answered with %lu bytes, fewer than the %u of the "
                "smallest caps block this protocol has ever carried",
                (unsigned long)resp_len, (unsigned)CFTR_CAPS_BYTES_V1);
        rdev_free(R);
        return CFT_ERR_INTERNAL;
    }
    R->format_mask    = cftr_get32(resp + 0);
    R->op_groups      = cftr_get32(resp + 4);
    R->tiles          = cftr_get32(resp + 8);
    R->device_version = cftr_get32(resp + 12);
    R->flags_readable = cftr_get32(resp + 16);
    R->server_abi     = cftr_get32(resp + 20);
    memcpy(R->server_backend, resp + 24, CFTR_BACKEND_NAME);
    R->server_backend[CFTR_BACKEND_NAME] = '\0';
    memset(&R->seq, 0, sizeof R->seq);
    if (resp_len >= CFTR_CAPS_BYTES_V2) {
        R->seq.max_deposits = cftr_get32(resp + 56);
        R->seq.max_insns    = cftr_get32(resp + 60);
        R->seq.max_consts   = cftr_get32(resp + 64);
        R->seq.features     = cftr_get32(resp + 68);
    }
    /* The block grows by appending and a client reads what it
     * recognises: a server that predates the scratch depth answers 72
     * bytes and this stays zero, which cft_caps documents as UNKNOWN
     * and nothing is enforced against. The two scratch FEATURE bits
     * need no new word - they are bits 8 and 9 of seq_features, in a
     * field the block has carried since 0.8. */
    if (resp_len >= CFTR_CAPS_BYTES)
        R->seq.max_scratch  = cftr_get32(resp + 72);
    free(resp);

    *format_mask    = R->format_mask & 0xFu;
    *op_groups      = R->op_groups & 0xFFu;
    *tiles          = R->tiles;
    *version        = R->device_version;
    *flags_readable = R->flags_readable ? 1 : 0;
    if (seq)
        *seq = R->seq;
    *out            = R;
    return CFT_OK;
}

void cftr_close(void *hw)
{
    rdev *R = (rdev *)hw;
    if (!R)
        return;
    if (!R->poisoned) {
        uint8_t *resp = NULL;
        size_t rl = 0;
        int st;
        /* Best effort: a BYE lets the server log a clean close. A
         * failure here changes nothing - the socket closes either way. */
        (void)do_request(R, CFTR_OP_BYE, NULL, 0, &st, &resp, &rl);
        free(resp);
    }
    rdev_free(R);
}

static size_t elem_bytes(int fmt)
{
    switch (fmt) {
    case 0: return 4;
    case 1: return 8;
    case 2: return 16;
    case 3: return 32;
    default: return 0;
    }
}

/* ---- cft_run --------------------------------------------------------- */

int cftr_run(void *hw, int op, int fmt, int rnd,
             const void *a, const void *b, const void *c, void *d,
             size_t n, uint32_t *flags, uint32_t *bus)
{
    rdev *R = (rdev *)hw;
    const size_t esz = elem_bytes(fmt);
    const uint8_t *pa = (const uint8_t *)a, *pb = (const uint8_t *)b;
    const uint8_t *pc = (const uint8_t *)c;
    uint8_t *pd = (uint8_t *)d;
    uint32_t present = (a ? 1u : 0u) | (b ? 2u : 0u) | (c ? 4u : 0u);
    unsigned npresent = (a ? 1u : 0u) + (b ? 1u : 0u) + (c ? 1u : 0u);
    size_t per_elem, epc, off;
    uint32_t fl_acc = 0, bus_acc = 0;
    uint8_t *req = NULL;

    g_err[0] = '\0';
    if (!R || esz == 0 || !d)
        return CFT_ERR_INVALID_ARGUMENT;
    if (n == 0) {
        if (flags) *flags = 0;
        if (bus)   *bus = 0;
        return CFT_OK;
    }
    /* Elements per request: the chunk budget over what one element
     * costs on the wire, operands in and result out. */
    per_elem = (npresent + 1u) * esz;
    epc = CFTR_CHUNK_BYTES / per_elem;
    if (epc == 0)
        epc = 1;

    for (off = 0; off < n; off += epc) {
        const size_t k = n - off < epc ? n - off : epc;
        /* four u32 and a u64 before the operands: 24 bytes, as
         * docs/REMOTE.md lays the RUN request out */
        const size_t req_len = 24u + (size_t)npresent * k * esz;
        uint8_t *q;
        uint8_t *resp = NULL;
        size_t resp_len = 0;
        int status;

        req = (uint8_t *)realloc(req, req_len);
        if (!req)
            return CFT_ERR_OUT_OF_MEMORY;
        cftr_put32(req + 0, (uint32_t)op);
        cftr_put32(req + 4, (uint32_t)fmt);
        cftr_put32(req + 8, (uint32_t)rnd);
        cftr_put32(req + 12, present);
        cftr_put64(req + 16, (uint64_t)k);
        q = req + 24;
        if (pa) { memcpy(q, pa + off * esz, k * esz); q += k * esz; }
        if (pb) { memcpy(q, pb + off * esz, k * esz); q += k * esz; }
        if (pc) { memcpy(q, pc + off * esz, k * esz); q += k * esz; }

        if (do_request(R, CFTR_OP_RUN, req, req_len, &status, &resp,
                       &resp_len)) {
            free(req);
            return R->poison_status;
        }
        if (status != CFT_OK) {
            free(req);
            return status;
        }
        if (resp_len != 8u + k * esz) {
            char why[160];
            snprintf(why, sizeof why,
                     "RUN answered with %lu bytes where %lu were due",
                     (unsigned long)resp_len, (unsigned long)(8u + k * esz));
            free(resp);
            free(req);
            poison(R, CFT_ERR_INTERNAL, why);
            return CFT_ERR_INTERNAL;
        }
        fl_acc  |= cftr_get32(resp + 0);
        bus_acc |= cftr_get32(resp + 4);
        /* d may alias an operand: this chunk's operands have already
         * been sent, and element i depends on element i alone. */
        memcpy(pd + off * esz, resp + 8, k * esz);
        free(resp);
    }
    free(req);
    if (flags) *flags = fl_acc;
    if (bus)   *bus = bus_acc;
    return CFT_OK;
}

/* ---- cft_reduce ------------------------------------------------------- */

int cftr_reduce(void *hw, int op, int fmt, int rnd,
                const void *a, const void *b, void *d, size_t n,
                uint32_t *flags, uint32_t *bus)
{
    rdev *R = (rdev *)hw;
    const size_t esz = elem_bytes(fmt);
    uint32_t present = (a ? 1u : 0u) | (b ? 2u : 0u);
    unsigned npresent = (a ? 1u : 0u) + (b ? 1u : 0u);
    size_t req_len, opnd;
    uint8_t *req, *q, *resp = NULL;
    size_t resp_len = 0;
    int status;

    g_err[0] = '\0';
    if (!R || esz == 0 || !d || !a)
        return CFT_ERR_INVALID_ARGUMENT;
    if (n > (size_t)CFTR_MAX_PAYLOAD / esz / (npresent ? npresent : 1u) ||
        (opnd = n * esz, 24u + (size_t)npresent * opnd > CFTR_MAX_PAYLOAD)) {
        set_err("a reduction over %lu elements of %lu bytes does not fit "
                "one frame (docs/REMOTE.md: reductions are not chunked, "
                "because a partial is only reusable at a node of the tree)",
                (unsigned long)n, (unsigned long)esz);
        return CFT_ERR_INVALID_ARGUMENT;
    }
    req_len = 24u + (size_t)npresent * opnd;      /* 4 x u32 + u64 first */
    req = (uint8_t *)malloc(req_len);
    if (!req)
        return CFT_ERR_OUT_OF_MEMORY;
    cftr_put32(req + 0, (uint32_t)op);
    cftr_put32(req + 4, (uint32_t)fmt);
    cftr_put32(req + 8, (uint32_t)rnd);
    cftr_put32(req + 12, present);
    cftr_put64(req + 16, (uint64_t)n);
    q = req + 24;
    memcpy(q, a, opnd);
    q += opnd;
    if (b)
        memcpy(q, b, opnd);

    if (do_request(R, CFTR_OP_REDUCE, req, req_len, &status, &resp,
                   &resp_len)) {
        free(req);
        return R->poison_status;
    }
    free(req);
    if (status != CFT_OK)
        return status;
    if (resp_len != 8u + esz) {
        char why[160];
        snprintf(why, sizeof why,
                 "REDUCE answered with %lu bytes where %lu were due",
                 (unsigned long)resp_len, (unsigned long)(8u + esz));
        free(resp);
        poison(R, CFT_ERR_INTERNAL, why);
        return CFT_ERR_INTERNAL;
    }
    if (flags) *flags = cftr_get32(resp + 0);
    if (bus)   *bus = cftr_get32(resp + 4);
    memcpy(d, resp + 8, esz);
    free(resp);
    return CFT_OK;
}

/* ---- programs ---------------------------------------------------------- */

/* Make sure the server holds `image` under R->phandle: the cache hit
 * is a memcmp, the miss is PROG_FREE of the old handle (if any) and
 * PROG_LOAD of the new bytes. */
static int ensure_program(rdev *R, int fmt, const void *image,
                          size_t image_bytes, uint32_t max_deposits)
{
    uint8_t *resp = NULL;
    size_t resp_len = 0;
    int status;

    if (R->has_prog && R->pimg_bytes == image_bytes &&
        memcmp(R->pimg, image, image_bytes) == 0)
        return CFT_OK;

    if (R->has_prog) {
        uint8_t hb[4];
        cftr_put32(hb, R->phandle);
        R->has_prog = 0;
        if (do_request(R, CFTR_OP_PROG_FREE, hb, 4, &status, &resp,
                       &resp_len))
            return R->poison_status;
        free(resp);
        /* a failure to free is the server's problem, not this run's */
    }
    if (do_request(R, CFTR_OP_PROG_LOAD, image, image_bytes, &status, &resp,
                   &resp_len))
        return R->poison_status;
    if (status != CFT_OK)
        return status;
    if (resp_len != 16) {
        free(resp);
        poison(R, CFT_ERR_INTERNAL, "PROG_LOAD answered with the wrong "
                                    "payload size");
        return CFT_ERR_INTERNAL;
    }
    R->phandle = cftr_get32(resp + 0);
    R->pfmt    = cftr_get32(resp + 4);
    R->pmaxdep = cftr_get32(resp + 8);
    free(resp);
    if (R->pfmt != (uint32_t)fmt || R->pmaxdep != max_deposits) {
        set_err("the server read this program as %s with %lu deposit slots "
                "and this library as %s with %lu: two copies of the same "
                "ABI disagreeing about an image, which means one of them "
                "is not the library",
                cft_format_name((cft_format)R->pfmt),
                (unsigned long)R->pmaxdep, cft_format_name((cft_format)fmt),
                (unsigned long)max_deposits);
        return CFT_ERR_INTERNAL;
    }
    R->pimg = (uint8_t *)realloc(R->pimg, image_bytes ? image_bytes : 1);
    if (!R->pimg)
        return CFT_ERR_OUT_OF_MEMORY;
    memcpy(R->pimg, image, image_bytes);
    R->pimg_bytes = image_bytes;
    R->has_prog = 1;
    return CFT_OK;
}

int cftr_program_run(void *hw, int fmt, const void *image,
                     size_t image_bytes, const cft_seq_run_io *io,
                     uint32_t max_deposits,
                     const void *a, const void *b, const void *c,
                     void *deposits, uint32_t *counts, size_t n,
                     uint32_t *flags, uint32_t *bus)
{
    rdev *R = (rdev *)hw;
    const size_t esz = elem_bytes(fmt);
    const uint8_t *pa = (const uint8_t *)a, *pb = (const uint8_t *)b;
    const uint8_t *pc = (const uint8_t *)c;
    uint8_t *pd = (uint8_t *)deposits;
    const void *bank        = io ? io->bank : NULL;
    size_t      bank_bytes  = io ? io->bank_bytes : 0;
    const uint8_t *psi      = io ? (const uint8_t *)io->scratch_in : NULL;
    uint8_t       *pso      = io ? (uint8_t *)io->scratch_out : NULL;
    uint32_t    n_sin       = io ? io->n_scratch_in : 0;
    uint32_t    n_sout      = io ? io->n_scratch_out : 0;
    uint32_t present = (a ? 1u : 0u) | (b ? 2u : 0u) | (c ? 4u : 0u);
    unsigned npresent = (a ? 1u : 0u) + (b ? 1u : 0u) + (c ? 1u : 0u);
    /* PROG_RUN's fixed fields, PROG_RUN_BANK's and PROG_RUN_EX's - the
     * same twenty-four bytes, with the bank appended after them and its
     * length in the word PROG_RUN leaves zero, and with two more fixed
     * words and the scratch-in block on the third opcode.
     *
     * WHICH of the three is the IMAGE's decision, read from its header
     * flags - SCRATCH_IO (bit 1) first, then BANK_EXT (bit 0) - and
     * never from the buffers' lengths. A BANK_EXT program whose
     * n_consts is zero has a legitimately empty bank and must still
     * travel as PROG_RUN_BANK, because the server's cft_program_run
     * refuses it and only cft_program_run_bank takes it (found
     * 2026-09-08 by the JavaScript client, which mirrors this file);
     * a SCRATCH_IO program whose two counts are zero is in exactly the
     * same position one call further along, and this is where that
     * lesson is applied rather than relearned. */
    const int bank_ext = image_bytes >= 32 &&
                         (((const uint8_t *)image)[24] & 1u);
    const int scratch_io = image_bytes >= 32 &&
                           (((const uint8_t *)image)[24] & 2u);
    const uint16_t op = scratch_io ? CFTR_OP_PROG_RUN_EX
                      : bank_ext   ? CFTR_OP_PROG_RUN_BANK
                                   : CFTR_OP_PROG_RUN;
    /* PROG_RUN_EX's payload carries two more fixed words - the two
     * per-lane slot counts - before the bank and the scratch-in block,
     * so the server can slice a chunk without re-reading the image. */
    const size_t fixed = scratch_io ? 32u : 24u;
    size_t per_lane, lpc, off;
    uint32_t fl_acc = 0, bus_acc = 0;
    uint8_t *req = NULL;
    int st;

    g_err[0] = '\0';
    if (!R || !image || image_bytes == 0 || esz == 0 || !a)
        return CFT_ERR_INVALID_ARGUMENT;
    if (max_deposits && !deposits)
        return CFT_ERR_INVALID_ARGUMENT;
    if (bank_bytes && !bank)
        return CFT_ERR_INVALID_ARGUMENT;
    if ((n_sin && !psi) || (n_sout && !pso))
        return CFT_ERR_INVALID_ARGUMENT;
    /* Never sent to a server that cannot serve it. The image would not
     * have LOADED against such a device - cft_program_load refuses a
     * BANK_EXT image where CAPS[6] is clear, and the HELLO caps block
     * carries the server device's seq_features - so reaching here with
     * a bank and a server without the feature means the two disagree
     * about what was published, which is worth naming rather than
     * discovering as an unsupported opcode. */
    if (bank_bytes && !(R->seq.features & CFT_SEQ_FEAT_BANK_PTR)) {
        set_err("this run supplies a constant bank and the server's device "
                "does not publish CFT_SEQ_FEAT_BANK_PTR (CAPS[6], "
                "cft_caps.seq_features bit 2), so it cannot take one");
        return CFT_ERR_UNSUPPORTED;
    }
    /* And the same for the scratch block, which is asked of the image
     * rather than of the buffers for the reason above: a program that
     * declares SCRATCH_IO needs the feature whether or not its counts
     * are zero. */
    if (scratch_io && !(R->seq.features & CFT_SEQ_FEAT_SCRATCH_IO)) {
        set_err("this program declares a per-run scratch block and the "
                "server's device does not publish CFT_SEQ_FEAT_SCRATCH_IO "
                "(CAPS2[5], cft_caps.seq_features bit 9), so it cannot "
                "take one");
        return CFT_ERR_UNSUPPORTED;
    }
    if (n == 0) {
        if (flags) *flags = 0;
        if (bus)   *bus = 0;
        return CFT_OK;
    }
    st = ensure_program(R, fmt, image, image_bytes, max_deposits);
    if (st != CFT_OK)
        return st;

    /* Lanes per request: operands and the scratch-in block in,
     * deposits, counts and the scratch-out block out. The scratch
     * blocks are PER LANE, so unlike the bank they belong in the
     * per-lane cost rather than off the budget. The bank comes off the
     * budget because it rides every chunk - a bank as large as the
     * budget would otherwise make every chunk one byte over. */
    per_lane = (size_t)npresent * esz + (size_t)max_deposits * esz + 4u +
               (size_t)n_sin * esz + (size_t)n_sout * esz;
    if (bank_bytes >= CFTR_CHUNK_BYTES) {
        set_err("this program's constant bank is %lu bytes, which does not "
                "leave room for a lane in a %lu-byte request",
                (unsigned long)bank_bytes,
                (unsigned long)CFTR_CHUNK_BYTES);
        return CFT_ERR_INVALID_ARGUMENT;
    }
    lpc = (CFTR_CHUNK_BYTES - bank_bytes) / per_lane;
    if (lpc == 0)
        lpc = 1;

    for (off = 0; off < n; off += lpc) {
        const size_t k = n - off < lpc ? n - off : lpc;
        const size_t sin_bytes = (size_t)n_sin * k * esz;
        const size_t sout_bytes = (size_t)n_sout * k * esz;
        const size_t req_len = fixed + bank_bytes + sin_bytes +
                               (size_t)npresent * k * esz;
        const size_t dep_bytes = k * (size_t)max_deposits * esz;
        const size_t want = 8u + dep_bytes + (counts ? k * 4u : 0u) +
                            sout_bytes;
        uint8_t *q, *resp = NULL;
        size_t resp_len = 0;
        int status;

        req = (uint8_t *)realloc(req, req_len);
        if (!req)
            return CFT_ERR_OUT_OF_MEMORY;
        cftr_put32(req + 0, R->phandle);
        cftr_put32(req + 4, present);
        cftr_put32(req + 8, counts ? 1u : 0u);
        /* Zero on PROG_RUN, the bank's byte length on the other two.
         * The bank rides EVERY chunk rather than being staged once,
         * because a chunk is a whole run of its own lanes on the
         * server and a program's constants are not chunk-shaped; the
         * bank is a handful of format-width values beside megabytes of
         * operands, so the repetition costs nothing measurable. */
        cftr_put32(req + 12, (uint32_t)bank_bytes);
        cftr_put64(req + 16, (uint64_t)k);
        if (scratch_io) {
            /* The two counts, so the server can shape THIS CHUNK's
             * blocks. The chunk's scratch-in is the slice of the whole
             * block belonging to its own lanes - lane-major, so lanes
             * [off, off + k) are a contiguous run of k * n_scratch_in
             * elements - which is why the counts have to cross and a
             * byte length alone would not do. */
            cftr_put32(req + 24, n_sin);
            cftr_put32(req + 28, n_sout);
        }
        q = req + fixed;
        if (bank_bytes) { memcpy(q, bank, bank_bytes); q += bank_bytes; }
        if (sin_bytes) {
            memcpy(q, psi + off * (size_t)n_sin * esz, sin_bytes);
            q += sin_bytes;
        }
        if (pa) { memcpy(q, pa + off * esz, k * esz); q += k * esz; }
        if (pb) { memcpy(q, pb + off * esz, k * esz); q += k * esz; }
        if (pc) { memcpy(q, pc + off * esz, k * esz); q += k * esz; }

        if (do_request(R, op, req, req_len, &status, &resp,
                       &resp_len)) {
            free(req);
            return R->poison_status;
        }
        if (status != CFT_OK) {
            free(req);
            return status;
        }
        if (resp_len != want) {
            char why[160];
            snprintf(why, sizeof why,
                     "op 0x%04x answered with %lu bytes where %lu were due",
                     (unsigned)op, (unsigned long)resp_len,
                     (unsigned long)want);
            free(resp);
            free(req);
            poison(R, CFT_ERR_INTERNAL, why);
            return CFT_ERR_INTERNAL;
        }
        fl_acc  |= cftr_get32(resp + 0);
        bus_acc |= cftr_get32(resp + 4);
        if (dep_bytes)
            memcpy(pd + off * (size_t)max_deposits * esz, resp + 8, dep_bytes);
        if (counts) {
            size_t i;
            for (i = 0; i < k; i++)
                counts[off + i] = cftr_get32(resp + 8 + dep_bytes + i * 4u);
        }
        /* The scratch-out block last in the response, after the
         * deposits and whatever counts were asked for, and sliced back
         * into the caller's whole-run buffer at this chunk's lanes. */
        if (sout_bytes)
            memcpy(pso + off * (size_t)n_sout * esz,
                   resp + 8 + dep_bytes + (counts ? k * 4u : 0u),
                   sout_bytes);
        free(resp);
    }
    free(req);
    if (flags) *flags = fl_acc;
    if (bus)   *bus = bus_acc;
    return CFT_OK;
}

#endif /* __EMSCRIPTEN__ */

#else  /* CFT_NO_REMOTE */

/* An empty translation unit is not strictly conforming C99 and
 * -Wpedantic says so, so leave one declaration behind. */
typedef int cft_backend_remote_module_omitted;

#endif /* CFT_NO_REMOTE */
