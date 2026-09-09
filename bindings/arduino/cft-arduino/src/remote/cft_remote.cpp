/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The frame codec of docs/REMOTE.md, streamed.
 *
 * Read host/src/backend_remote.c beside this file: it is the same
 * codec and it is the reference. The differences are all one
 * difference - that client holds a payload and this one does not - and
 * they are these three:
 *
 *   1. THE CHECKSUM IS COMPUTED IN A SEPARATE PASS. CRC-32 covers the
 *      header (with its own crc field zero) and then the payload, and
 *      the header goes out first, so the whole payload must have been
 *      seen before the first byte of the frame can be sent. The C
 *      client has the payload in memory and walks it twice for free.
 *      Here the payload does not exist yet, so the caller's Operands
 *      object is asked for every element TWICE: once for the checksum
 *      pass and once for the send pass. The frame's LENGTH is
 *      arithmetic, not a walk, which is why two passes suffice and not
 *      three.
 *
 *   2. A RESPONSE IS DELIVERED BEFORE IT IS CHECKED. The crc is in the
 *      header, which arrived first, so an element handed to a Results
 *      object has not yet been vouched for. run() says so in its
 *      contract; runOne() and reduce() hold their single element back
 *      until the frame checks out, because one element fits.
 *
 *   3. NOTHING IS ALLOCATED. A payload this client does not understand
 *      - a longer caps block from a newer server, a refusal longer
 *      than the message store - is read straight into the checksum and
 *      dropped, thirty-two bytes at a time. That is what makes a 1 GiB
 *      frame cap survivable on a board with 2 kB of SRAM: the cap
 *      bounds reading, never memory.
 */

#include "cft_remote.h"

#include <string.h>

namespace cftr {

/* ---- formats -------------------------------------------------------- */

uint8_t formatSize(uint8_t fmt)
{
    switch (fmt) {
    case FP32:  return 4;
    case FP64:  return 8;
    case FP128: return 16;
    case FP256: return 32;
    default:    return 0;
    }
}

/* ---- little-endian fields ------------------------------------------- */

void put16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
}

void put32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16);
    p[3] = (uint8_t)(v >> 24);
}

void put64(uint8_t *p, uint64_t v)
{
    put32(p, (uint32_t)v);
    put32(p + 4, (uint32_t)(v >> 32));
}

uint16_t get16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

uint32_t get32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

/* ---- CRC-32 ---------------------------------------------------------
 *
 * The reflected polynomial is the one constant here that is
 * transcribed, in the base its definition uses, and crcSelfcheck()
 * holds the result against the standard's own check value before any
 * frame is sent. Bitwise: no table, no PROGMEM, no initialisation, and
 * the same eight lines on every board.
 */

uint32_t crcBegin(void) { return 0xFFFFFFFFul; }

uint32_t crcUpdate(uint32_t c, const uint8_t *p, uint16_t n)
{
    uint16_t i;
    uint8_t  b;
    for (i = 0; i < n; i++) {
        c ^= (uint32_t)p[i];
        for (b = 0; b < 8; b++)
            c = (c & 1u) ? (0xEDB88320ul ^ (c >> 1)) : (c >> 1);
    }
    return c;
}

uint32_t crcFinal(uint32_t c) { return ~c; }

uint32_t crc32(const uint8_t *p, uint16_t n)
{
    return crcFinal(crcUpdate(crcBegin(), p, n));
}

int crcSelfcheck(void)
{
    static const char digits[] = "123456789";
    return crc32((const uint8_t *)digits, 9) == 0xCBF43926ul ? 0 : -1;
}

/* ---- operands and results out of RAM --------------------------------- */

RamOperands::RamOperands(uint8_t fmt, const void *a, const void *b,
                         const void *c)
{
    esz_     = formatSize(fmt);
    p_[0]    = (const uint8_t *)a;
    p_[1]    = (const uint8_t *)b;
    p_[2]    = (const uint8_t *)c;
    present_ = (uint8_t)((a ? 1u : 0u) | (b ? 2u : 0u) | (c ? 4u : 0u));
}

void RamOperands::element(uint8_t role, uint32_t index, uint8_t *out)
{
    const uint8_t *p = (role < 3) ? p_[role] : 0;
    if (p)
        memcpy(out, p + (uint32_t)index * esz_, esz_);
    else
        memset(out, 0, esz_);
}

RamResults::RamResults(uint8_t fmt, void *d)
{
    esz_ = formatSize(fmt);
    p_   = (uint8_t *)d;
}

void RamResults::element(uint32_t index, const uint8_t *in)
{
    if (p_)
        memcpy(p_ + (uint32_t)index * esz_, in, esz_);
}

/* ---- why ------------------------------------------------------------- */

cftr_text reasonText(uint8_t reason)
{
    switch (reason) {
    case R_NONE:      return CFTR_TEXT("no failure");
    case R_LOCAL:     return CFTR_TEXT("refused here, before a frame was sent");
    case R_SERVER:    return CFTR_TEXT("the operation failed on the server");
    case R_REFUSED:   return CFTR_TEXT("the server refused the frame and closed");
    case R_MAGIC:     return CFTR_TEXT("not a cft frame: the magic is wrong");
    case R_PROTO:     return CFTR_TEXT("a protocol version this client does not speak");
    case R_RESERVED:  return CFTR_TEXT("the reserved header word is not zero");
    case R_ABI:       return CFTR_TEXT("ABI mismatch: the server is a different libcft");
    case R_LENGTH:    return CFTR_TEXT("a payload longer than this board will read");
    case R_CRC:       return CFTR_TEXT("the frame does not match the checksum it carries");
    case R_SHORT:     return CFTR_TEXT("the payload is not the length the opcode requires");
    case R_ID:        return CFTR_TEXT("a response for a request that was not asked");
    case R_KIND:      return CFTR_TEXT("a frame that is neither a response nor a refusal");
    case R_TIMEOUT:   return CFTR_TEXT("the connection stopped moving");
    case R_TRANSPORT: return CFTR_TEXT("the connection failed");
    case R_POISONED:  return CFTR_TEXT("an earlier fault finished this handle; open it again");
    default:          return CFTR_TEXT("unknown");
    }
}

/* ---- the client ------------------------------------------------------ */

Client::Client()
{
    io_ = 0;
    abi_ = 0;
    nextId_ = 0;
    crc_ = 0;
    want_ = 0;
    left_ = 0;
    rkind_ = 0;
    rstatus_ = 0;
    formatMask_ = 0;
    opGroups_ = 0;
    tiles_ = 0;
    deviceVersion_ = 0;
    serverAbi_ = 0;
#if CFT_REMOTE_KEEP_SEQ_CAPS
    maxDeposits_ = 0;
    maxInsns_ = 0;
    maxConsts_ = 0;
    seqFeatures_ = 0;
    maxScratch_ = 0;
#endif
    flagsReadable_ = 0;
    capsBytes_ = 0;
    status_ = OK;
    reason_ = R_NONE;
    poisoned_ = 0;
#if CFT_REMOTE_BACKEND_NAME_BYTES > 0
    backend_[0] = '\0';
#endif
#if CFT_REMOTE_ERR_BYTES > 0
    err_[0] = '\0';
#endif
    memset(elem_, 0, sizeof elem_);
}

const char *Client::backend() const
{
#if CFT_REMOTE_BACKEND_NAME_BYTES > 0
    return backend_;
#else
    return "";
#endif
}

const char *Client::message() const
{
#if CFT_REMOTE_ERR_BYTES > 0
    return err_;
#else
    return "";
#endif
}

bool Client::supportsFormat(uint8_t fmt) const
{
    return fmt < 4 && (formatMask_ & (1ul << fmt)) != 0;
}

/* A failure that leaves the connection usable: a local refusal, or the
 * operation's own answer. */
int Client::fail(int status, uint8_t reason)
{
    status_ = (int8_t)status;
    reason_ = reason;
    return status;
}

/* A failure that does not: after a framing error the byte stream is
 * unsynchronised, and pretending to resume it is how a later request
 * gets answered with an earlier response. */
int Client::poison(int status, uint8_t reason)
{
    poisoned_ = 1;
    return fail(status, reason);
}

/* ---- sending --------------------------------------------------------- */

int Client::sendHeader(uint16_t op, uint32_t id, uint32_t length, uint32_t crc)
{
    uint8_t h[HDR_BYTES];
    memset(h, 0, sizeof h);
    put32(h + 0, CFT_REMOTE_MAGIC);
    put16(h + 4, PROTO_VERSION);
    put16(h + 6, KIND_REQUEST);
    put32(h + 8, abi_);
    put32(h + 12, id);
    put16(h + 16, op);
    put16(h + 18, 0);
    put32(h + 20, length);
    put32(h + 24, crc);
    put32(h + 28, 0);
    return io_->writeBytes(h, HDR_BYTES);
}

/* The header as it is checksummed: the same bytes, with the crc field
 * zero. Returned as the running crc so the payload can follow it. */
int Client::beginRequest(uint16_t op, uint32_t length, uint32_t *crc)
{
    uint8_t h[HDR_BYTES];
    memset(h, 0, sizeof h);
    put32(h + 0, CFT_REMOTE_MAGIC);
    put16(h + 4, PROTO_VERSION);
    put16(h + 6, KIND_REQUEST);
    put32(h + 8, abi_);
    put32(h + 12, nextId_ + 1);
    put16(h + 16, op);
    put16(h + 18, 0);
    put32(h + 20, length);
    put32(h + 24, 0);
    put32(h + 28, 0);
    *crc = crcUpdate(crcBegin(), h, HDR_BYTES);
    return 0;
}

/* One RUN or REDUCE frame: the 24-byte fixed prefix
 * (op, fmt, rnd, present as u32, then n as u64) and then, for each
 * operand the present mask names, `count` elements starting at global
 * index `base`. Two passes over the caller's generator - checksum,
 * then send - and never a byte of it stored. */
int Client::sendRunLike(uint16_t wireOp, uint8_t op, uint8_t fmt, uint8_t rnd,
                        uint8_t present, uint32_t base, uint32_t count,
                        Operands &in)
{
    uint8_t  pre[24];
    uint8_t  esz = formatSize(fmt);
    uint8_t  npresent = (uint8_t)(((present & 1u) ? 1 : 0) +
                                  ((present & 2u) ? 1 : 0) +
                                  ((present & 4u) ? 1 : 0));
    uint32_t length = 24ul + (uint32_t)npresent * count * esz;
    uint32_t crc;
    uint8_t  role, pass;
    uint32_t i;

    put32(pre + 0, (uint32_t)op);
    put32(pre + 4, (uint32_t)fmt);
    put32(pre + 8, (uint32_t)rnd);
    put32(pre + 12, (uint32_t)present);
    put64(pre + 16, (uint64_t)count);

    beginRequest(wireOp, length, &crc);
    crc = crcUpdate(crc, pre, sizeof pre);

    /* pass 0 checksums the operands, pass 1 sends the frame */
    for (pass = 0; pass < 2; pass++) {
        if (pass == 1) {
            if (sendHeader(wireOp, nextId_ + 1, length, crcFinal(crc)))
                return poison(ERR_INTERNAL, R_TRANSPORT);
            if (io_->writeBytes(pre, sizeof pre))
                return poison(ERR_INTERNAL, R_TRANSPORT);
        }
        for (role = 0; role < 3; role++) {
            if (!(present & (1u << role)))
                continue;
            for (i = 0; i < count; i++) {
                in.element(role, base + i, elem_);
                if (pass == 0)
                    crc = crcUpdate(crc, elem_, esz);
                else if (io_->writeBytes(elem_, esz))
                    return poison(ERR_INTERNAL, R_TRANSPORT);
            }
        }
    }
    if (io_->flushOut())
        return poison(ERR_INTERNAL, R_TRANSPORT);
    nextId_++;
    return OK;
}

/* ---- receiving -------------------------------------------------------- */

int Client::recvHeader(uint16_t wantOp)
{
    uint8_t  h[HDR_BYTES];
    uint32_t length, id, peerAbi;
    uint16_t op;

    if (io_->readBytes(h, HDR_BYTES, CFT_REMOTE_TIMEOUT_MS))
        return poison(ERR_TIMEOUT, R_TIMEOUT);
    if (get32(h + 0) != CFT_REMOTE_MAGIC)
        return poison(ERR_INTERNAL, R_MAGIC);
    if (get16(h + 4) != PROTO_VERSION)
        return poison(ERR_UNSUPPORTED, R_PROTO);
    if (get32(h + 28) != 0)
        return poison(ERR_INTERNAL, R_RESERVED);
    peerAbi = get32(h + 8);
    /* Kept even when it is the thing that failed, so a sketch can
     * print what the server said it was against what it claimed. */
    serverAbi_ = peerAbi;
    if (peerAbi != abi_)
        return poison(ERR_UNSUPPORTED, R_ABI);
    id     = get32(h + 12);
    op     = get16(h + 16);
    length = get32(h + 20);
    if (length > (uint32_t)CFT_REMOTE_MAX_RECV_BYTES)
        return poison(ERR_INTERNAL, R_LENGTH);
    if (id != nextId_ || op != wantOp)
        return poison(ERR_INTERNAL, R_ID);
    rkind_   = get16(h + 6);
    rstatus_ = get16(h + 18);
    want_    = get32(h + 24);
    left_    = length;
    put32(h + 24, 0);
    crc_     = crcUpdate(crcBegin(), h, HDR_BYTES);
    return OK;
}

/* n payload bytes into dst, or into the checksum and out of existence
 * when dst is null. */
int Client::recvPayload(uint8_t *dst, uint32_t n)
{
    uint8_t tmp[32];
    while (n) {
        uint16_t k = (uint16_t)(n > sizeof tmp ? sizeof tmp : n);
        uint8_t *p = dst ? dst : tmp;
        if (left_ < k)
            return poison(ERR_INTERNAL, R_SHORT);
        if (io_->readBytes(p, k, CFT_REMOTE_TIMEOUT_MS))
            return poison(ERR_TIMEOUT, R_TIMEOUT);
        crc_ = crcUpdate(crc_, p, k);
        left_ -= k;
        n -= k;
        if (dst)
            dst += k;
    }
    return OK;
}

/* Read whatever is left of the payload, then hold the frame to the
 * checksum it carried. */
int Client::endFrame(void)
{
    if (left_ && recvPayload(0, left_) != OK)
        return status_;
    if (crcFinal(crc_) != want_)
        return poison(ERR_INTERNAL, R_CRC);
    return OK;
}

/* The server's own words out of a refusal or a failed response: as
 * much as the message store holds, and the rest into the checksum. */
int Client::takeMessage(void)
{
#if CFT_REMOTE_ERR_BYTES > 0
    uint32_t k = left_ < (uint32_t)CFT_REMOTE_ERR_BYTES
                     ? left_ : (uint32_t)CFT_REMOTE_ERR_BYTES;
    err_[0] = '\0';
    if (k && recvPayload((uint8_t *)err_, k) != OK)
        return status_;
    err_[k] = '\0';
    /* the server NUL-terminates; a truncated copy might not */
    err_[CFT_REMOTE_ERR_BYTES] = '\0';
#endif
    return endFrame();
}

/* A request whose payload is a handful of fixed bytes and whose
 * response is too: the status-word operations, and BYE. */
int Client::simpleRequest(uint16_t op, const uint8_t *req, uint8_t reqLen,
                          uint8_t *resp, uint8_t respLen)
{
    uint32_t crc;

    if (poisoned_)
        return fail(ERR_INTERNAL, R_POISONED);
    beginRequest(op, reqLen, &crc);
    if (reqLen)
        crc = crcUpdate(crc, req, reqLen);
    if (sendHeader(op, nextId_ + 1, reqLen, crcFinal(crc)))
        return poison(ERR_INTERNAL, R_TRANSPORT);
    if (reqLen && io_->writeBytes(req, reqLen))
        return poison(ERR_INTERNAL, R_TRANSPORT);
    if (io_->flushOut())
        return poison(ERR_INTERNAL, R_TRANSPORT);
    nextId_++;

    if (recvHeader(op) != OK)
        return status_;
    if (rkind_ == KIND_REFUSAL) {
        takeMessage();
        poisoned_ = 1;
        return fail(rstatus_ ? (int)rstatus_ : ERR_INTERNAL, R_REFUSED);
    }
    if (rkind_ != KIND_RESPONSE)
        return poison(ERR_INTERNAL, R_KIND);
    if (rstatus_ != OK) {
        /* The operation's own failure, on a connection that lives. Its
         * message is the payload - unless reading the payload was
         * itself a fault, in which case THAT is the verdict. */
        if (takeMessage() != OK)
            return status_;
        return fail((int)rstatus_, R_SERVER);
    }
    if (left_ != (uint32_t)respLen) {
        endFrame();
        return poison(ERR_INTERNAL, R_SHORT);
    }
    if (respLen && recvPayload(resp, respLen) != OK)
        return status_;
    if (endFrame() != OK)
        return status_;
    return fail(OK, R_NONE);
}

/* ---- HELLO and the caps block ------------------------------------------ */

int Client::readCaps(void)
{
    uint8_t w[24];   /* the first six u32 and the start of the name */
    uint8_t i;

    if (rkind_ == KIND_REFUSAL) {
        takeMessage();
        poisoned_ = 1;
        return fail(rstatus_ ? (int)rstatus_ : ERR_INTERNAL, R_REFUSED);
    }
    if (rkind_ != KIND_RESPONSE)
        return poison(ERR_INTERNAL, R_KIND);
    if (rstatus_ != OK) {
        /* The server could not open ITS device. Its words, its
         * connection - this is not a framing failure. */
        if (takeMessage() != OK)
            return status_;
        return fail((int)rstatus_, R_SERVER);
    }
    /* A block SHORTER than the 56 bytes this protocol has always
     * carried is not an older version, it is a stream that is not a
     * caps block. A LONGER one is a newer server, and a client reads
     * what it recognises out of whatever length arrived. */
    if (left_ < (uint32_t)CAPS_BYTES_V1) {
        endFrame();
        return poison(ERR_INTERNAL, R_SHORT);
    }
    capsBytes_ = (uint8_t)(left_ > 255 ? 255 : left_);

    if (recvPayload(w, sizeof w) != OK)
        return status_;
    formatMask_    = get32(w + 0);
    opGroups_      = get32(w + 4);
    tiles_         = get32(w + 8);
    deviceVersion_ = get32(w + 12);
    flagsReadable_ = get32(w + 16) ? 1 : 0;
    serverAbi_     = get32(w + 20);

    /* the 32-byte backend name, NUL-padded */
#if CFT_REMOTE_BACKEND_NAME_BYTES > 0
    {
        uint8_t keep = CFT_REMOTE_BACKEND_NAME_BYTES < BACKEND_NAME
                           ? (uint8_t)CFT_REMOTE_BACKEND_NAME_BYTES
                           : (uint8_t)BACKEND_NAME;
        if (recvPayload((uint8_t *)backend_, keep) != OK)
            return status_;
        backend_[keep] = '\0';
        for (i = 0; i < keep; i++)
            if (backend_[i] == '\0')
                break;
        backend_[i] = '\0';
        if (keep < BACKEND_NAME &&
            recvPayload(0, (uint32_t)(BACKEND_NAME - keep)) != OK)
            return status_;
    }
#else
    (void)i;
    if (recvPayload(0, BACKEND_NAME) != OK)
        return status_;
#endif

#if CFT_REMOTE_KEEP_SEQ_CAPS
    maxDeposits_ = maxInsns_ = maxConsts_ = seqFeatures_ = maxScratch_ = 0;
    if (left_ >= (uint32_t)(CAPS_BYTES_V2 - CAPS_BYTES_V1)) {
        uint8_t s[16];
        if (recvPayload(s, sizeof s) != OK)
            return status_;
        maxDeposits_ = get32(s + 0);
        maxInsns_    = get32(s + 4);
        maxConsts_   = get32(s + 8);
        seqFeatures_ = get32(s + 12);
        if (left_ >= 4) {
            if (recvPayload(s, 4) != OK)
                return status_;
            maxScratch_ = get32(s);
        }
    }
#endif
    /* Anything the server appended past what this client knows is
     * checksummed and dropped: the block grows by appending, and a
     * client reads what it recognises. */
    if (endFrame() != OK)
        return status_;
    return fail(OK, R_NONE);
}

int Client::begin(Transport &io, uint32_t abi)
{
    uint32_t crc;

    io_ = &io;
    abi_ = abi;
    nextId_ = 0;
    poisoned_ = 0;
    capsBytes_ = 0;
    status_ = OK;
    reason_ = R_NONE;
#if CFT_REMOTE_ERR_BYTES > 0
    err_[0] = '\0';
#endif
    if (crcSelfcheck())
        return fail(ERR_INTERNAL, R_LOCAL);

    beginRequest(OP_HELLO, 0, &crc);
    if (sendHeader(OP_HELLO, 1, 0, crcFinal(crc)))
        return poison(ERR_INTERNAL, R_TRANSPORT);
    if (io_->flushOut())
        return poison(ERR_INTERNAL, R_TRANSPORT);
    nextId_ = 1;
    if (recvHeader(OP_HELLO) != OK)
        return status_;
    return readCaps();
}

int Client::refreshCaps()
{
    uint32_t crc;
    if (poisoned_)
        return fail(ERR_INTERNAL, R_POISONED);
    beginRequest(OP_CAPS, 0, &crc);
    if (sendHeader(OP_CAPS, nextId_ + 1, 0, crcFinal(crc)))
        return poison(ERR_INTERNAL, R_TRANSPORT);
    if (io_->flushOut())
        return poison(ERR_INTERNAL, R_TRANSPORT);
    nextId_++;
    if (recvHeader(OP_CAPS) != OK)
        return status_;
    return readCaps();
}

void Client::end()
{
    if (io_ && !poisoned_)
        (void)simpleRequest(OP_BYE, 0, 0, 0, 0);
    io_ = 0;
}

/* ---- RUN --------------------------------------------------------------- */

uint32_t Client::chunkElements(uint8_t fmt, uint8_t npresent)
{
    uint8_t  esz = formatSize(fmt);
    uint32_t per, k;
    if (!esz)
        return 1;
    per = (uint32_t)(npresent + 1u) * esz;    /* operands in, result out */
    k = (uint32_t)CFT_REMOTE_CHUNK_BYTES / per;
    return k ? k : 1;
}

int Client::run(uint8_t op, uint8_t fmt, uint8_t rnd, uint8_t present,
                uint32_t n, Operands &in, Results &out,
                uint32_t *flags, uint32_t *bus)
{
    uint8_t  esz = formatSize(fmt);
    uint8_t  npresent;
    uint32_t epc, off, flagAcc = 0, busAcc = 0;

    if (flags) *flags = 0;
    if (bus)   *bus = 0;
    if (poisoned_)
        return fail(ERR_INTERNAL, R_POISONED);
    if (!io_ || !esz || esz > CFT_REMOTE_MAX_ELEM_BYTES || present > 7u)
        return fail(ERR_INVALID_ARGUMENT, R_LOCAL);
    if (!supportsFormat(fmt))
        return fail(ERR_UNSUPPORTED, R_LOCAL);
    if (n == 0)
        return fail(OK, R_NONE);

    npresent = (uint8_t)(((present & 1u) ? 1 : 0) + ((present & 2u) ? 1 : 0) +
                         ((present & 4u) ? 1 : 0));
    epc = chunkElements(fmt, npresent);

    for (off = 0; off < n; off += epc) {
        uint32_t k = (n - off < epc) ? (n - off) : epc;
        uint32_t i;
        uint8_t  fb[8];

        if (sendRunLike(OP_RUN, op, fmt, rnd, present, off, k, in) != OK)
            return status_;
        if (recvHeader(OP_RUN) != OK)
            return status_;
        if (rkind_ == KIND_REFUSAL) {
            takeMessage();
            poisoned_ = 1;
            return fail(rstatus_ ? (int)rstatus_ : ERR_INTERNAL, R_REFUSED);
        }
        if (rkind_ != KIND_RESPONSE)
            return poison(ERR_INTERNAL, R_KIND);
        if (rstatus_ != OK) {
            if (takeMessage() != OK)
                return status_;
            return fail((int)rstatus_, R_SERVER);
        }
        if (left_ != 8ul + (uint32_t)k * esz) {
            endFrame();
            return poison(ERR_INTERNAL, R_SHORT);
        }
        if (recvPayload(fb, 8) != OK)
            return status_;
        flagAcc |= get32(fb + 0);
        busAcc  |= get32(fb + 4);
        for (i = 0; i < k; i++) {
            if (recvPayload(elem_, esz) != OK)
                return status_;
            out.element(off + i, elem_);
        }
        if (endFrame() != OK)
            return status_;
    }
    if (flags) *flags = flagAcc;
    if (bus)   *bus = busAcc;
    return fail(OK, R_NONE);
}

int Client::runOne(uint8_t op, uint8_t fmt, uint8_t rnd,
                   const void *a, const void *b, const void *c, void *d,
                   uint32_t *flags, uint32_t *bus)
{
    uint8_t hold[CFT_REMOTE_MAX_ELEM_BYTES];
    RamOperands in(fmt, a, b, c);
    RamResults out(fmt, hold);
    uint8_t esz = formatSize(fmt);
    int st;

    if (!d || !esz || esz > CFT_REMOTE_MAX_ELEM_BYTES)
        return fail(ERR_INVALID_ARGUMENT, R_LOCAL);
    st = run(op, fmt, rnd, in.present(), 1, in, out, flags, bus);
    /* Held back until the frame checked out: one element fits, so
     * runOne need not pass the caller anything unvouched-for. */
    if (st == OK)
        memcpy(d, hold, esz);
    return st;
}

/* ---- REDUCE ------------------------------------------------------------- */

int Client::reduce(uint8_t op, uint8_t fmt, uint8_t rnd, uint8_t present,
                   uint32_t n, Operands &in, void *d,
                   uint32_t *flags, uint32_t *bus)
{
    uint8_t  esz = formatSize(fmt);
    uint8_t  fb[8];

    if (flags) *flags = 0;
    if (bus)   *bus = 0;
    if (poisoned_)
        return fail(ERR_INTERNAL, R_POISONED);
    if (!io_ || !d || !esz || esz > CFT_REMOTE_MAX_ELEM_BYTES ||
        present > 3u || !(present & 1u) || n == 0)
        return fail(ERR_INVALID_ARGUMENT, R_LOCAL);
    if (!supportsFormat(fmt))
        return fail(ERR_UNSUPPORTED, R_LOCAL);

    /* Not chunked - a partial sum is only reusable if its range is a
     * node of the tree - so the whole request is one frame. It streams
     * out of the generator, so its size is the protocol's business and
     * not this board's; only the eight bytes and one element that come
     * back are. */
    if (sendRunLike(OP_REDUCE, op, fmt, rnd, present, 0, n, in) != OK)
        return status_;
    if (recvHeader(OP_REDUCE) != OK)
        return status_;
    if (rkind_ == KIND_REFUSAL) {
        takeMessage();
        poisoned_ = 1;
        return fail(rstatus_ ? (int)rstatus_ : ERR_INTERNAL, R_REFUSED);
    }
    if (rkind_ != KIND_RESPONSE)
        return poison(ERR_INTERNAL, R_KIND);
    if (rstatus_ != OK) {
        if (takeMessage() != OK)
            return status_;
        return fail((int)rstatus_, R_SERVER);
    }
    if (left_ != 8ul + esz) {
        endFrame();
        return poison(ERR_INTERNAL, R_SHORT);
    }
    if (recvPayload(fb, 8) != OK)
        return status_;
    if (recvPayload(elem_, esz) != OK)
        return status_;
    if (endFrame() != OK)
        return status_;
    if (flags) *flags = get32(fb + 0);
    if (bus)   *bus = get32(fb + 4);
    memcpy(d, elem_, esz);
    return fail(OK, R_NONE);
}

/* ---- the status word ---------------------------------------------------- */

int Client::flagsLower(uint32_t mask)
{
    uint8_t req[4];
    put32(req, mask);
    return simpleRequest(OP_FLAGS_LOWER, req, 4, 0, 0);
}

int Client::flagsRaise(uint32_t mask)
{
    uint8_t req[4];
    put32(req, mask);
    return simpleRequest(OP_FLAGS_RAISE, req, 4, 0, 0);
}

int Client::flagsTest(uint32_t mask, uint32_t *result)
{
    uint8_t req[4], resp[4];
    int st;
    put32(req, mask);
    st = simpleRequest(OP_FLAGS_TEST, req, 4, resp, 4);
    if (st == OK && result)
        *result = get32(resp);
    return st;
}

int Client::flagsSave(uint32_t *word)
{
    uint8_t resp[4];
    int st = simpleRequest(OP_FLAGS_SAVE, 0, 0, resp, 4);
    if (st == OK && word)
        *word = get32(resp);
    return st;
}

int Client::flagsRestore(uint32_t saved, uint32_t mask)
{
    uint8_t req[8];
    put32(req + 0, saved);
    put32(req + 4, mask);
    return simpleRequest(OP_FLAGS_RESTORE, req, 8, 0, 0);
}

int Client::flagsTestSaved(uint32_t saved, uint32_t mask, uint32_t *result)
{
    uint8_t req[8], resp[4];
    int st;
    put32(req + 0, saved);
    put32(req + 4, mask);
    st = simpleRequest(OP_FLAGS_TEST_SAVED, req, 8, resp, 4);
    if (st == OK && result)
        *result = get32(resp);
    return st;
}

/* ---- encodings ----------------------------------------------------------- */

void packF32(uint8_t *out, float v)
{
    uint32_t u;
    memcpy(&u, &v, 4);
    put32(out, u);
}

float unpackF32(const uint8_t *in)
{
    uint32_t u = get32(in);
    float v;
    memcpy(&v, &u, 4);
    return v;
}

#if CFT_REMOTE_HAVE_F64
void packF64(uint8_t *out, double v)
{
    uint8_t b[8];
    memcpy(b, &v, 8);
    /* every board here is little-endian, and the check is one line */
    {
        uint16_t probe = 1;
        if (*(const uint8_t *)&probe) {
            memcpy(out, b, 8);
        } else {
            uint8_t i;
            for (i = 0; i < 8; i++)
                out[i] = b[7 - i];
        }
    }
}

double unpackF64(const uint8_t *in)
{
    uint8_t b[8];
    uint16_t probe = 1;
    double v;
    if (*(const uint8_t *)&probe) {
        memcpy(b, in, 8);
    } else {
        uint8_t i;
        for (i = 0; i < 8; i++)
            b[i] = in[7 - i];
    }
    memcpy(&v, b, 8);
    return v;
}
#endif

static char hexDigit(uint8_t v)
{
    return (char)(v < 10 ? ('0' + v) : ('a' + (v - 10)));
}

void toHex(char *out, const uint8_t *in, uint8_t bytes)
{
    uint8_t i;
    for (i = 0; i < bytes; i++) {
        uint8_t b = in[bytes - 1 - i];      /* most significant first */
        out[2 * i]     = hexDigit((uint8_t)(b >> 4));
        out[2 * i + 1] = hexDigit((uint8_t)(b & 0x0Fu));
    }
    out[2 * bytes] = '\0';
}

int fromHex(uint8_t *out, const char *in, uint8_t bytes)
{
    uint8_t i;
    for (i = 0; i < bytes; i++) {
        uint8_t v = 0, j;
        for (j = 0; j < 2; j++) {
            char ch = in[2 * i + j];
            uint8_t d;
            if (ch >= '0' && ch <= '9')      d = (uint8_t)(ch - '0');
            else if (ch >= 'a' && ch <= 'f') d = (uint8_t)(ch - 'a' + 10);
            else if (ch >= 'A' && ch <= 'F') d = (uint8_t)(ch - 'A' + 10);
            else return -1;
            v = (uint8_t)((v << 4) | d);
        }
        out[bytes - 1 - i] = v;
    }
    return in[2 * bytes] == '\0' ? 0 : -1;
}

}  /* namespace cftr */
