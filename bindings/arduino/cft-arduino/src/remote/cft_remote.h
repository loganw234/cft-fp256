/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The frame protocol of docs/REMOTE.md, spoken from an Arduino-class
 * board.
 *
 *     #include <cft_remote.h>       // the umbrella at the root of src/
 *
 *     cftr::StreamTransport io(Serial);
 *     cftr::Client dev;
 *     dev.begin(io, CFT_REMOTE_ABI);          // one HELLO
 *     dev.runOne(cftr::OP_FMA, cftr::FP64, cftr::RNE, a, b, c, d);
 *
 * This is the same protocol host/src/backend_remote.c speaks and the
 * same protocol bindings/wasm/remote.mjs speaks, byte for byte: the
 * same 32-byte header, the same little-endian fields, the same CRC-32
 * over the same bytes, the same opcodes and the same payload layouts.
 * Nothing here is an embedded dialect of it. The bytes an Uno puts on
 * the wire for a given call are the bytes the C client puts on the
 * wire for that call, which is the only reason the server can serve
 * both without knowing which is which - and it is the whole point:
 * the answer that comes back is the SAME ANSWER, not a near one.
 *
 * WHAT IS DIFFERENT, AND IT IS NOT THE WIRE
 *
 * The C client holds the whole payload in malloc'd memory, checksums
 * it, and sends it. A Nano has 2048 bytes of SRAM and cannot hold a
 * payload at all. So this client STREAMS: it asks the caller for one
 * element at a time, twice - once to checksum the frame and once to
 * send it - and hands results back one element at a time. Nothing here
 * ever allocates, and the largest object it has in hand at any moment
 * is one element, 32 bytes at binary256. See cft_remote_config.h for
 * the budget and every knob that moves it.
 *
 * The price of streaming is stated once, here, because it is the one
 * thing a caller must honour: an Operands object is asked for the same
 * element TWICE and MUST answer with the same bytes both times. A
 * generator that reads a sensor between the two passes will checksum
 * one number and send another, and the server will refuse the frame.
 * That is a detected failure rather than a wrong answer, which is the
 * property this whole repository is for - but it is still a bug, and
 * it is the caller's.
 *
 * THE ABI IS NOT TRANSCRIBED HERE
 *
 * Every frame carries the SENDER's cft_abi_version() and the server
 * refuses a mismatch rather than warning about one, so a client must
 * SAY which ABI it is claiming. A number copied into this file would
 * be a number that goes stale against a server nobody rebuilt, so
 * there is none: begin() takes it. Its value for a given server is one
 * command away -
 *
 *     python host/tools/cft-serial-bridge.py --probe-abi HOST:PORT
 *
 * - which reads it out of the header of the refusal the server sends
 * to a deliberately wrong HELLO. A wrong value is not a silent hazard:
 * it is a refusal at HELLO with both versions in the message.
 *
 * WHAT THIS CLIENT DOES NOT DO
 *
 * PROG_LOAD, PROG_RUN and the three run-with-data opcodes, the buffer
 * operations, and STATS are not implemented. The program opcodes are
 * out for a structural reason and not for want of room: an image must
 * be held to be checksummed, and holding a buffer is the one thing the
 * budget forbids. RUN and REDUCE and the status-word operations are
 * here, at every format, and they are what a board is for.
 */

#ifndef CFT_REMOTE_H_
#define CFT_REMOTE_H_

#include <stddef.h>
#include <stdint.h>

#include "cft_remote_config.h"

/* F("...") keeps a literal in flash on AVR and is a plain literal
 * everywhere else; off a board there is no such macro, so the text
 * this client returns for a local failure is typed once and reads
 * correctly on all four. */
#if defined(ARDUINO)
#  include <Arduino.h>
typedef const __FlashStringHelper *cftr_text;
#  define CFTR_TEXT(s) F(s)
#else
typedef const char *cftr_text;
#  define CFTR_TEXT(s) (s)
#endif

namespace cftr {

/* ---- the wire ------------------------------------------------------
 *
 * Every constant in this block is host/src/remote.h's or cft.h's, and
 * every one of them is held to it: src/remote/test/host_check.cc
 * includes both this header and those two and static_asserts the pairs
 * equal, so a value that drifts is a compile error in the gate rather
 * than a refusal on a board. That check is the only reason these may
 * be written down at all.
 */

/* 'C' 'F' 'T' 'R' as they appear on the wire, first byte first;
 * DERIVED from the four characters rather than typed as a number, so
 * that the bytes and the word cannot disagree. */
#define CFT_REMOTE_MAGIC ((uint32_t)'C' | ((uint32_t)'F' << 8) | \
                          ((uint32_t)'T' << 16) | ((uint32_t)'R' << 24))

enum {
    PROTO_VERSION = 1,
    HDR_BYTES     = 32,
    DEFAULT_PORT  = 7754,
    BACKEND_NAME  = 32,   /* the caps block's field, not our store */
    CAPS_BYTES_V1 = 56,   /* the least a caps block has ever been */
    CAPS_BYTES_V2 = 72,   /* + the four sequencer capacities */
    CAPS_BYTES_V3 = 76    /* + max_scratch */
};

enum { KIND_REQUEST = 0, KIND_RESPONSE = 1, KIND_REFUSAL = 2 };

enum {
    OP_HELLO            = 0x0001,
    OP_CAPS             = 0x0002,
    OP_STATS            = 0x0003,
    OP_RUN              = 0x0010,
    OP_REDUCE           = 0x0011,
    OP_PROG_LOAD        = 0x0020,
    OP_PROG_RUN         = 0x0021,
    OP_PROG_FREE        = 0x0022,
    OP_PROG_RUN_BANK    = 0x0023,
    OP_PROG_RUN_EX      = 0x0024,
    OP_BUF_ALLOC        = 0x0030,
    OP_BUF_FREE         = 0x0031,
    OP_BUF_WRITE        = 0x0032,
    OP_BUF_READ         = 0x0033,
    OP_FLAGS_LOWER      = 0x0040,
    OP_FLAGS_RAISE      = 0x0041,
    OP_FLAGS_TEST       = 0x0042,
    OP_FLAGS_SAVE       = 0x0043,
    OP_FLAGS_RESTORE    = 0x0044,
    OP_FLAGS_TEST_SAVED = 0x0045,
    OP_BYE              = 0x00FF
};

/* cft_status, in cft.h's order. */
enum {
    OK = 0,
    ERR_INVALID_ARGUMENT = 1,
    ERR_UNSUPPORTED      = 2,
    ERR_NO_DEVICE        = 3,
    ERR_ARTIFACT         = 4,
    ERR_BUS_FAULT        = 5,
    ERR_OUT_OF_MEMORY    = 6,
    ERR_TIMEOUT          = 7,
    ERR_INTERNAL         = 8
};

/* cft_format. The value is normative for callers (cft.h says so) and
 * it is what the wire carries. */
enum { FP32 = 0, FP64 = 1, FP128 = 2, FP256 = 3 };

/* cft_op. Numbered, never renumbered: an opcode number is on the wire
 * and in every published vector set. */
enum {
    OP_FMA = 0, OP_ADD = 1, OP_SUB = 2, OP_MUL = 3,
    OP_ABS = 4, OP_NEG = 5, OP_COPYSIGN = 6,
    OP_MIN = 7, OP_MAX = 8, OP_MINNUM = 9, OP_MAXNUM = 10,
    OP_SELECT = 11, OP_CMPLT = 12, OP_CMPLE = 13, OP_CMPEQ = 14,
    OP_IAND = 16, OP_IOR = 17, OP_IXOR = 18, OP_IADD = 19,
    OP_ISUB = 20, OP_ISHL = 21, OP_ISHR = 22, OP_ICMPLT = 23,
    OP_SUM = 24, OP_DOT = 25,
    OP_RECIP_SEED = 26, OP_RSQRT_SEED = 27,
    OP_SUMSQ = 28, OP_SUMABS = 29,
    OP_IMUL = 30
};

/* cft_round. */
enum { RNE = 0, RTZ = 1, RDN = 2, RUP = 3, RMM = 4 };

/* cft_exception, the sticky flag bits a run ORs together. */
enum {
    FLAG_INVALID   = 1u << 0,
    FLAG_DIVBYZERO = 1u << 1,
    FLAG_OVERFLOW  = 1u << 2,
    FLAG_UNDERFLOW = 1u << 3,
    FLAG_INEXACT   = 1u << 4
};

/* Bytes per element, 0 for a format this client does not know. */
uint8_t formatSize(uint8_t fmt);

/* ---- CRC-32 --------------------------------------------------------
 *
 * IEEE 802.3 / zlib / PNG: reflected polynomial 0xEDB88320, initial
 * value all ones, final complement, check value 0xCBF43926 for the
 * nine ASCII digits "123456789". BITWISE, with no table: 1 kB of table
 * is half an Uno's SRAM and a quarter of its flash if it is not in
 * PROGMEM, and eight shifts a byte is nothing beside a serial line
 * that moves eleven kilobytes a second. The value is the same value.
 *
 * Streaming, because the payload is never in one place: begin, update
 * as the bytes go past, final. crc32() is the one-shot form the
 * self-check uses. */
uint32_t crcBegin(void);
uint32_t crcUpdate(uint32_t running, const uint8_t *p, uint16_t n);
uint32_t crcFinal(uint32_t running);
uint32_t crc32(const uint8_t *p, uint16_t n);
/* 0 when this implementation gives the standard check value. Called by
 * begin() before the first frame is sent, exactly as the C client
 * calls cftr_crc32_selfcheck(). */
int crcSelfcheck(void);

/* Little-endian field access, so no struct layout and no host byte
 * order is ever on the wire. */
void     put16(uint8_t *p, uint16_t v);
void     put32(uint8_t *p, uint32_t v);
void     put64(uint8_t *p, uint64_t v);
uint16_t get16(const uint8_t *p);
uint32_t get32(const uint8_t *p);

/* ---- the transport -------------------------------------------------
 *
 * A byte pipe, all-or-nothing in both directions, and nothing else.
 * The protocol does not care which one it is: a USB serial port with a
 * bridge on the far end and a TCP socket to the same server carry the
 * same bytes and get the same answers, which is what
 * docs/REMOTE.md's serial section is about.
 */
class Transport {
public:
    /* Hand n bytes to the pipe. 0 on success, nonzero on any failure.
     * May stage them; flushOut() is what promises they have gone. */
    virtual int writeBytes(const uint8_t *p, uint16_t n) = 0;
    /* Fill p with exactly n bytes. 0 on success; nonzero if the pipe
     * made no progress for timeoutMs milliseconds or failed. */
    virtual int readBytes(uint8_t *p, uint16_t n, uint32_t timeoutMs) = 0;
    /* Push whatever writeBytes staged. 0 on success. */
    virtual int flushOut() { return 0; }
    /* False once the pipe is known to be finished. A serial port has
     * no such notion and always answers true. */
    virtual bool alive() { return true; }
protected:
    /* Not virtual, and protected: a transport is never destroyed
     * through this pointer, and a virtual destructor on AVR would drag
     * in operator delete for nothing. */
    ~Transport() {}
};

/* ---- operands and results ------------------------------------------
 *
 * The two callbacks that make an operand array unnecessary. Both are
 * indexed by the element's position in the WHOLE run, not in the
 * chunk: the client splits a run into frames and the index it passes
 * is the global one, so a generator never learns that chunking exists.
 */
class Operands {
public:
    /* Write element `index` of operand `role` - 0 for a, 1 for b, 2
     * for c - into `out`, as formatSize(fmt) bytes of the format's
     * interchange encoding, little-endian.
     *
     * CALLED TWICE FOR EVERY ELEMENT OF EVERY FRAME: once while the
     * frame is checksummed and once while it is sent. It MUST write
     * the same bytes both times. */
    virtual void element(uint8_t role, uint32_t index, uint8_t *out) = 0;
protected:
    ~Operands() {}
};

class Results {
public:
    /* Element `index` of the result, formatSize(fmt) bytes.
     *
     * ARRIVES BEFORE THE FRAME'S CRC HAS BEEN CHECKED, because the crc
     * is in the header and the header came first. Accumulate it, store
     * it, count it - but do not ACT on it until run() has returned OK,
     * because a frame that fails its checksum has already delivered
     * every element it carried. runOne() and reduce() have no such
     * rule: they hold their single element back until the frame
     * checks out. */
    virtual void element(uint32_t index, const uint8_t *in) = 0;
protected:
    ~Results() {}
};

/* Operands read straight out of RAM, for the small case where the
 * arrays do fit: up to three dense, contiguous buffers of n elements.
 * A null pointer is an absent operand and its `present` bit is clear. */
class RamOperands : public Operands {
public:
    RamOperands(uint8_t fmt, const void *a, const void *b = 0,
                const void *c = 0);
    virtual void element(uint8_t role, uint32_t index, uint8_t *out);
    uint8_t present() const { return present_; }
private:
    const uint8_t *p_[3];
    uint8_t esz_, present_;
};

/* Results written straight into RAM, the mirror of the above. It obeys
 * the rule in Results by construction: it stores, it does not act. */
class RamResults : public Results {
public:
    RamResults(uint8_t fmt, void *d);
    virtual void element(uint32_t index, const uint8_t *in);
private:
    uint8_t *p_;
    uint8_t esz_;
};

/* ---- why a call failed ---------------------------------------------
 *
 * status() is the operation's cft_status and is what a caller checks.
 * reason() says which of the protocol's own checks failed, when one
 * did, and reasonText() puts it in words without spending a byte of
 * SRAM to do it.
 */
enum Reason {
    R_NONE = 0,
    R_LOCAL,          /* refused here, before a frame was sent */
    R_SERVER,         /* the operation's own failure; the connection lives */
    R_REFUSED,        /* the server refused the frame and closed */
    R_MAGIC,          /* the four bytes were not 'C' 'F' 'T' 'R' */
    R_PROTO,          /* a protocol version this client does not speak */
    R_RESERVED,       /* the reserved header word was not zero */
    R_ABI,            /* the other end is a different libcft */
    R_LENGTH,         /* a payload longer than this board will read */
    R_CRC,            /* the frame does not match the checksum it carries */
    R_SHORT,          /* the payload was not the length the opcode requires */
    R_ID,             /* a response for a request that was not asked */
    R_KIND,           /* neither a response nor a refusal */
    R_TIMEOUT,        /* the pipe stopped moving */
    R_TRANSPORT,      /* the pipe failed or closed */
    R_POISONED        /* an earlier fault finished this handle */
};

cftr_text reasonText(uint8_t reason);

/* ---- the client ----------------------------------------------------- */

class Client {
public:
    Client();

    /* Open the conversation: check the CRC implementation against its
     * own check value, send HELLO, read the caps block. `abi` is the
     * ABI WORD THIS CLIENT CLAIMS - (major << 16) | minor, 0x0000000B
     * for libcft 0.11 - and the server refuses a mismatch. Returns a
     * cft_status; OK means the device on the far end is open and its
     * caps are readable below. */
    int begin(Transport &io, uint32_t abi);

    /* Ask for the caps block again on an open connection. Same fields,
     * same accessors. */
    int refreshCaps();

    /* Say goodbye so the server can log a clean close. Best effort:
     * the pipe closes either way. */
    void end();

    /* d[i] = op(a[i], b[i], c[i]) for i in [0, n), at `fmt` and `rnd`.
     * The operands present are the ones RamOperands or the caller's own
     * Operands object answers for, named by `present`: bit 0 a, bit 1
     * b, bit 2 c, exactly as the wire names them.
     *
     * Split into frames of at most CFT_REMOTE_CHUNK_BYTES of operand
     * and result data. The flag and bus words come back ORed over
     * every frame, which is the same union one frame would have
     * carried. */
    int run(uint8_t op, uint8_t fmt, uint8_t rnd, uint8_t present,
            uint32_t n, Operands &in, Results &out,
            uint32_t *flags = 0, uint32_t *bus = 0);

    /* One element in, one element out, from and to plain buffers: the
     * shape almost every sketch wants. a, b and c may be null for an
     * operand the opcode does not read. The result is written to d
     * ONLY if the frame checked out. */
    int runOne(uint8_t op, uint8_t fmt, uint8_t rnd,
               const void *a, const void *b, const void *c, void *d,
               uint32_t *flags = 0, uint32_t *bus = 0);

    /* n elements in, ONE element out: CFT_SUM, CFT_DOT, CFT_SUMSQ,
     * CFT_SUMABS. Not chunked, and it does not need to be - the
     * request streams out of the caller's generator and the response
     * is eight bytes and one element - so a board may reduce over far
     * more elements than it could ever store. d receives the single
     * result, and only if the frame checked out. */
    int reduce(uint8_t op, uint8_t fmt, uint8_t rnd, uint8_t present,
               uint32_t n, Operands &in, void *d,
               uint32_t *flags = 0, uint32_t *bus = 0);

    /* The device's sticky exception flags: the five status-word
     * operations of docs/REMOTE.md, which the C client never issues
     * because libcft keeps that word on the host. Over the wire the
     * word lives on the server, so a board can read it. */
    int flagsLower(uint32_t mask);
    int flagsRaise(uint32_t mask);
    int flagsTest(uint32_t mask, uint32_t *result);
    int flagsSave(uint32_t *word);
    int flagsRestore(uint32_t saved, uint32_t mask);
    int flagsTestSaved(uint32_t saved, uint32_t mask, uint32_t *result);

    /* The caps block, as HELLO reported it. */
    uint32_t formatMask()    const { return formatMask_; }
    uint32_t opGroups()      const { return opGroups_; }
    uint32_t tiles()         const { return tiles_; }
    uint32_t deviceVersion() const { return deviceVersion_; }
    bool     flagsReadable() const { return flagsReadable_ != 0; }
    uint32_t serverAbi()     const { return serverAbi_; }
    /* "software", "xrt", or "" when CFT_REMOTE_BACKEND_NAME_BYTES is
     * 0. Never null. */
    const char *backend() const;
    /* True when the server's device carries this format. Checked
     * locally before a frame is sent, so an unsupported format costs
     * no round trip. */
    bool supportsFormat(uint8_t fmt) const;
#if CFT_REMOTE_KEEP_SEQ_CAPS
    uint32_t maxDeposits()   const { return maxDeposits_; }
    uint32_t maxInsns()      const { return maxInsns_; }
    uint32_t maxConsts()     const { return maxConsts_; }
    uint32_t seqFeatures()   const { return seqFeatures_; }
    uint32_t maxScratch()    const { return maxScratch_; }
#endif
    /* How many bytes of caps block the server sent. A server that
     * predates a field answers short and the field reads zero, which
     * cft_caps documents as unknown. */
    uint8_t capsBytes() const { return capsBytes_; }

    /* Why the last call failed. status() is its cft_status, reason()
     * names the check that failed, message() is the SERVER's own words
     * when it sent any ("" otherwise, never null). */
    int         status()  const { return status_; }
    uint8_t     reason()  const { return reason_; }
    const char *message() const;

    /* True once a framing fault has finished this handle: every later
     * call answers ERR_INTERNAL without touching the pipe. The same
     * discipline the C client applies, and for the same reason - after
     * a framing error the byte stream is unsynchronised, and
     * pretending to resume it is how a later request gets answered
     * with an earlier response. */
    bool poisoned() const { return poisoned_ != 0; }

    /* How many elements one RUN frame will carry at this format and
     * this many present operands - the chunk size, exposed so a sketch
     * can report it and so a test can check the arithmetic. */
    static uint32_t chunkElements(uint8_t fmt, uint8_t npresent);

private:
    int  fail(int status, uint8_t reason);
    int  poison(int status, uint8_t reason);
    int  sendHeader(uint16_t op, uint32_t id, uint32_t length, uint32_t crc);
    int  beginRequest(uint16_t op, uint32_t length, uint32_t *crc);
    int  sendRunLike(uint16_t wireOp, uint8_t op, uint8_t fmt, uint8_t rnd,
                     uint8_t present, uint32_t base, uint32_t count,
                     Operands &in);
    int  recvHeader(uint16_t wantOp);
    int  recvPayload(uint8_t *dst, uint32_t n);
    int  endFrame(void);
    int  takeMessage(void);
    int  simpleRequest(uint16_t op, const uint8_t *req, uint8_t reqLen,
                       uint8_t *resp, uint8_t respLen);
    int  readCaps(void);

    Transport *io_;
    uint32_t   abi_;
    uint32_t   nextId_;
    /* the frame being received */
    uint32_t   crc_;        /* running, over the header then the payload */
    uint32_t   want_;       /* the crc the header carried */
    uint32_t   left_;       /* payload bytes not yet read */
    uint16_t   rkind_;
    uint16_t   rstatus_;
    /* the caps block */
    uint32_t   formatMask_, opGroups_, tiles_, deviceVersion_, serverAbi_;
#if CFT_REMOTE_KEEP_SEQ_CAPS
    uint32_t   maxDeposits_, maxInsns_, maxConsts_, seqFeatures_, maxScratch_;
#endif
    uint8_t    flagsReadable_;
    uint8_t    capsBytes_;
    /* the verdict */
    int8_t     status_;
    uint8_t    reason_;
    uint8_t    poisoned_;
#if CFT_REMOTE_BACKEND_NAME_BYTES > 0
    char       backend_[CFT_REMOTE_BACKEND_NAME_BYTES + 1];
#endif
#if CFT_REMOTE_ERR_BYTES > 0
    char       err_[CFT_REMOTE_ERR_BYTES + 1];
#endif
    uint8_t    elem_[CFT_REMOTE_MAX_ELEM_BYTES];
};

/* ---- encodings ------------------------------------------------------
 *
 * A float is four bytes of binary32 on every board here, so packF32
 * and unpackF32 are honest everywhere.
 *
 * A double is NOT eight bytes everywhere: on the AVR cores an Arduino
 * `double` IS a `float`, 32 bits, and there is no 64-bit floating type
 * to make a binary64 encoding out of. That is why packF64 exists only
 * where the compiler has one, guarded below, and why the examples that
 * run on a Nano carry their binary64, binary128 and binary256 operands
 * as BYTES. It is not a limitation of the protocol - a board that
 * cannot represent binary256 can still send it, receive it and compare
 * it, and the device does the arithmetic. Couriering an encoding needs
 * no arithmetic type for it.
 */
void  packF32(uint8_t *out, float v);
float unpackF32(const uint8_t *in);

#if !defined(__AVR__) && (!defined(__SIZEOF_DOUBLE__) || __SIZEOF_DOUBLE__ == 8)
#  define CFT_REMOTE_HAVE_F64 1
void   packF64(uint8_t *out, double v);
double unpackF64(const uint8_t *in);
#else
#  define CFT_REMOTE_HAVE_F64 0
#endif

/* Hex, for printing an encoding a board cannot otherwise say out loud:
 * `bytes` bytes, MOST significant first, so that the text reads the
 * way the number is written. out must hold 2 * bytes + 1 chars. */
void toHex(char *out, const uint8_t *in, uint8_t bytes);
/* The inverse, for a constant carried as text. Returns 0 on success. */
int  fromHex(uint8_t *out, const char *in, uint8_t bytes);

}  /* namespace cftr */

#endif /* CFT_REMOTE_H_ */
