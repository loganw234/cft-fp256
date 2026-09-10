/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * CSRP/1 - the cft serial replay protocol.
 *
 * WHAT THIS IS FOR. The published conformance vectors (vectors/out,
 * 168 set files, 1,071,635 cases) are what every implementation of
 * this contract is held to, and host/src/conformance.c replays them by
 * opening the files. A microcontroller has no files and no room for
 * 194 MB of them, so the sets stay on the host and the CASES travel:
 * the host reads a line of JSONL exactly as cft_selftest.c's reader
 * does, sends the operands, and compares what comes back - the result
 * encoding and the five exception flags - against what the file
 * records. Bit for bit, one case at a time. The same replay, over a
 * wire.
 *
 * This file is the DEVICE half, and it is deliberately transport-free:
 * it takes a complete request line and writes a complete response
 * line. examples/VectorReplay/VectorReplay.ino carries the lines over
 * a UART; bindings/arduino/loopback carries them over stdin and stdout
 * from a host process built from the same sources, which is how the
 * harness gets exercised against the whole census before any board
 * exists. host/tools/serial_replay.py is the host half of both.
 *
 * ---------------------------------------------------------------
 * THE PROTOCOL
 *
 * ASCII lines terminated by \n. A \r before the \n is ignored, so a
 * host that opens the port in text mode does no damage. Nothing here
 * is binary and nothing is framed by length alone: a line that gets
 * cut in half by a reset, a baud mismatch or a full buffer must be
 * recognisable as damaged rather than replayed as a shorter case.
 *
 *   request    >SS VERB [field ...] *CCCC
 *   response   <SS ok [field ...] *CCCC
 *              <SS err REASON [text] *CCCC
 *
 *   SS     the request's sequence number, two lowercase hex digits,
 *          incrementing mod 256. The response echoes it. A response
 *          whose SS is not the one just sent is a lost or duplicated
 *          line, not a wrong answer, and the host resynchronises
 *          rather than scoring it.
 *   CCCC   CRC-16/CCITT-FALSE (poly 0x1021, init 0xffff, no reflection,
 *          no final xor) over every byte of the line from the leading
 *          '>' or '<' up to but NOT including the space before the '*'.
 *          Four lowercase hex digits.
 *
 * A request whose CRC does not check is answered `err crc`, and a
 * request whose sequence number the responder cannot read is answered
 * with sequence `00` and `err frame`. Neither ever produces an answer
 * that could be mistaken for a computed one.
 *
 * FIELD KINDS
 *
 *   <fmt>    fp32 | fp64 | fp128 | fp256 - the format's name, the same
 *            spelling cft_format_name() and the set files use.
 *   <rnd>    rne | rtz | rdn | rup | rmm.
 *   <op>     an opcode NAME - add, fma, imul, reserved15 ... - not a
 *            number. Names travel because the host reads them out of
 *            the JSONL and the device resolves them through
 *            cft_op_name(), so there is no third table to drift.
 *   <elem>   an element encoding: exactly 2*bytes hex digits, most
 *            significant FIRST, which is the `"a": "0x00000001"` of a
 *            set file with the 0x removed. Not little-endian byte
 *            order: the set file's spelling is the wire's, so an
 *            expected value can be compared as the string it already
 *            is and no byte order exists to get wrong twice.
 *            `-` where an operand is not read.
 *   <text>   `h` followed by an even number of hex digits, the bytes
 *            of a character sequence. `h` alone is the empty string.
 *            Hex because a 5.12 sequence may legally contain spaces
 *            (the refusal cases " 1" and "1 " do) and may be empty,
 *            and a whitespace-delimited token cannot carry either.
 *   <flags>  two hex digits: invalid 1, divideByZero 2, overflow 4,
 *            underflow 8, inexact 16, exactly cft_exception's bits.
 *   <int>    signed decimal.
 *
 * VERBS
 *
 *   id
 *     ok <proto> <abi> <backend> <fmtmask> <line> <stage> <out> <verbs>
 *     What this responder is and what it can hold. <proto> is
 *     CFT_REPLAY_PROTOCOL, so a host that speaks a different version
 *     finds out before it sends a case. <line> is the longest request
 *     it will accept and the longest chunk it will hand back to a
 *     `get`; <stage> is each staging buffer; <out> is the character
 *     buffer a to_decimal writes into. The host uses all three to
 *     decide which cases this device can be asked at all - a case
 *     whose exact decimal is 183,476 characters cannot be replayed on
 *     a part with 2 KB of RAM, and the honest thing is to skip it BY
 *     NAME and say so, not to shorten it. <verbs> is a comma-separated
 *     list of the verbs below that this build actually carries.
 *
 *   run <fmt> <rnd> <op> <a> <b> <c>          -> ok <d> <flags>
 *     One cft_run element. The elementwise sets (fp32.jsonl and its
 *     four attribute siblings, per format).
 *
 *   trn <fmt> <rnd> <fn> <a> <b|-> <n|->      -> ok <d> <flags>
 *     One transcendental, by the name the set file uses. <b> for the
 *     binary ones (pow, hypot, atan2, powr, atan2pi); <n> for the
 *     three that take an integer exponent (pown, compound, rootn).
 *
 *   aug <fmt> <fn> <a> <b>                    -> ok <r> <e> <flags>
 *     One 9.5 augmented operation; two outputs, no attribute.
 *
 *   mmg <fmt> <fn> <a> <b>                    -> ok <d> <flags>
 *     One 9.6 magnitude min/max; no attribute.
 *
 *   fof <sfmt> <dfmt> <rnd> <fn> <a> <b|-> <c|-> -> ok <d> <flags>
 *     One 5.4.1 formatOf operation. The operands are <sfmt>-wide and
 *     the answer is <dfmt>-wide, so the two hex lengths on the line
 *     differ; that is the schema, not an error.
 *
 *   red <fmt> <rnd> <fn> <n>                  -> ok <d> <flags>
 *                                             -> ok <pr> <sf> <flags>
 *     One reduction over the n elements already in the staging
 *     buffers: buffer 0 is `a`, buffer 1 is `b` (dot and the two
 *     two-operand scaled products). The second response shape is the
 *     scaled products', which return a pair.
 *
 *   chs <fmt> <rnd> <fn> <text|@>             -> ok <d> <flags>
 *     from_decimal or from_hex of one sequence. `@` reads the sequence
 *     from staging buffer 0 instead, for one too long to inline. A
 *     sequence outside 5.12's syntax is answered `err refused`, which
 *     is not a failure: the sets asserting a refusal are as much a
 *     part of the contract as the ones asserting a value.
 *
 *   chw <fmt> <rnd> <fn> <digits> <a>         -> ok <len> <flags>
 *     to_decimal or to_hex. The sequence goes into the out buffer and
 *     its LENGTH comes back; the host reads it with `get`. Answered
 *     `err toobig <need>` when it does not fit, which is the answer
 *     that lets the host skip that case by name and count it.
 *
 *   pay <fmt> <fn> <a>                        -> ok <d>
 *     One 9.7 payload operation. No attribute and no flags, which is
 *     what its rows in the character sets carry.
 *
 *   put <0|1> <off> <text>                    -> ok <used>
 *   get <off> <len>                           -> ok <text>
 *   clr                                       -> ok
 *     The staging buffers and the out buffer. `put` writes raw bytes
 *     at a byte offset (for a reduction vector these are packed
 *     little-endian elements, which is exactly what cft_reduce reads,
 *     so the device converts nothing); `get` reads the out buffer.
 *     `clr` empties all three.
 *
 *   env                                       -> ok <lines> <ok> <err> [k=v ...]
 *     The responder's own counters - requests seen, answered and
 *     refused since reset - and after them whatever the embedder's
 *     hook adds: key=value tokens the protocol does not interpret.
 *     The reference sketch reports temp= (die temperature, degrees
 *     C, where the part has a sensor), heap= (free bytes) and up=
 *     (milliseconds), so a long run can be read against the board's
 *     thermals and memory: an ESP32-S3's throughput decayed steadily
 *     from 62,000 cases on (2026-09-09), and whether that is heat or
 *     a leak is a question only a number from the board answers.
 *
 * ERROR REASONS: crc, frame, verb, field, unsupported, refused,
 * toobig, range, internal. Every one of them is a refusal to answer,
 * never a computed value - so a harness can treat "not ok" as "this
 * case was not checked" and say which, which is the distinction
 * cft_conformance() makes when it skips a format a device lacks.
 *
 * WHAT THE VERBS DO NOT COVER: the ARRAY pass. cft_conformance()
 * replays every set twice, once an element at a time and once as whole
 * arrays, and the second pass exists to exercise a DEVICE backend's
 * partitioning across tiles. There are no tiles here - this is the
 * software backend on one core - and a part with 2 KB of RAM cannot
 * hold a set. So this replay is the first pass, the one that pins each
 * case's exception flags exactly, and the harness says so in its
 * report rather than letting a smaller claim read as the larger one.
 */

#ifndef CFT_REPLAY_H
#define CFT_REPLAY_H

#include <stddef.h>
#include <stdint.h>

#include "cft.h"

#ifdef __cplusplus
extern "C" {
#endif

/* The protocol version this responder speaks, reported by `id`. */
#define CFT_REPLAY_PROTOCOL "csrp/1"

/* ---------------------------------------------------------------
 * CFT_REPLAY_MIN - the verb set a 32 KB part can carry
 *
 * Which verbs this responder answers otherwise follows the LIBRARY's
 * profile: there is no `trn` where there are no transcendentals. On an
 * ATmega328P that leaves id, clr, put, get, run, aug, mmg and red -
 * which the library HAS, and which together do not fit in 32 KB of
 * flash beside the Arduino core. Measured: 38 KB against 32,256 bytes
 * available (docs/EMBEDDED.md).
 *
 * So on a part with under 64 KB of flash the responder carries the
 * elementwise verb and the staging, and nothing else. That is a choice
 * about the REPLAY TOOL and not about the library: cft_reduce,
 * cft_augmented_add and the magnitude operations are all still there,
 * still correct, and a sketch that calls one and not the others gets
 * it - the linker's --gc-sections keeps what a sketch uses. What does
 * not fit is all of them at once plus a serial protocol.
 *
 * What the Uno and the Nano therefore replay is the elementwise sets:
 * fp32 and fp64, every opcode, all five rounding attributes, all five
 * exception flags, 120,000 cases. What they cannot be asked, the
 * harness skips by name and counts.
 *
 * -DCFT_REPLAY_FULL overrides this and -DCFT_REPLAY_MIN forces it, for
 * a part in between or a build that has traded something else away.
 * --------------------------------------------------------------- */
#ifdef __AVR__
#include <avr/io.h>                  /* FLASHEND */
#endif

#if !defined(CFT_REPLAY_MIN) && !defined(CFT_REPLAY_FULL) && \
    defined(FLASHEND) && (FLASHEND < 0xFFFFL)
#define CFT_REPLAY_MIN 1
#endif

/* Everything the responder needs, supplied by the embedder: the
 * sketch hands it static arrays, the loopback hands it malloc'd ones.
 * The responder itself allocates nothing, which is what lets it run on
 * a part whose whole heap is smaller than one fp256 reduction vector.
 */
typedef struct {
    cft_device *dev;

    uint8_t    *stage[2];       /* reduction vectors, staged sequences */
    size_t      stage_cap;      /* bytes in EACH of the two            */
    size_t      stage_used[2];

    char       *out;            /* character-conversion output         */
    size_t      out_cap;
    size_t      out_len;

    size_t      line_cap;       /* longest line this side will handle  */

    uint32_t    n_lines;        /* requests seen, answers given, and   */
    uint32_t    n_ok;           /* refusals - what `id` cannot say and */
    uint32_t    n_err;          /* a long run wants to know afterwards */

    /* Optional: what the board can say that the library cannot. `env`
     * appends this hook's text to its answer. Set it AFTER
     * cft_replay_init, which zeroes the struct; NULL means the answer
     * ends at the counters. The hook writes key=value tokens separated
     * by spaces into `out`, at most `cap` bytes including the NUL, and
     * returns the length - snprintf's convention, so a sketch can
     * return snprintf itself: a negative value or a length of `cap` or
     * more means "nothing to add", and the answer ends at the counters. */
    int       (*env)(void *ctx, char *out, size_t cap);
    void       *env_ctx;
} cft_replay;

/* Wire it up. Returns 0, or -1 if a required pointer is missing.
 * `dev` must already be open; the responder never opens or closes it,
 * because a sketch wants the device open for its whole life and a
 * failure to open is something the sketch must report on its own. */
int cft_replay_init(cft_replay *r, cft_device *dev,
                    uint8_t *stage0, uint8_t *stage1, size_t stage_cap,
                    char *outbuf, size_t out_cap, size_t line_cap);

/* Answer one request.
 *
 * `line` is a complete request line WITHOUT its newline; it is
 * modified in place (the parse tokenises it). `resp` receives a
 * complete response line without a newline, NUL-terminated.
 *
 * Returns the response length, or -1 if the response did not fit in
 * `resp_cap` - which cannot happen for a host that respected the
 * `line` capacity `id` reported, and is a caller bug rather than a
 * protocol event if it does.
 *
 * Never returns without writing a response: a request this responder
 * cannot parse is answered `err`, so a harness waiting on a line never
 * waits forever for a case the device silently dropped. */
int cft_replay_line(cft_replay *r, char *line, char *resp, size_t resp_cap);

/* CRC-16/CCITT-FALSE over `n` bytes. Exposed because the host half
 * computes the same value and a second implementation of a checksum is
 * a second place for it to be wrong; the loopback's tests check this
 * one against host/tools/serial_replay.py's. */
uint16_t cft_replay_crc16(const void *data, size_t n);

#ifdef __cplusplus
}
#endif

#endif /* CFT_REPLAY_H */
