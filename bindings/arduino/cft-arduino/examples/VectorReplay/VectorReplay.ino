/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * VectorReplay - answer the published conformance vectors over the UART.
 *
 * Flash this, then on the host:
 *
 *     python host/tools/serial_replay.py --port COM7 --sets 'fp32*'
 *     python host/tools/serial_replay.py --port COM7          (all of it)
 *
 * The host reads vectors/out - the same 168 set files
 * host/tools/cft_selftest.c replays, 1,068,915 cases - sends each case
 * over the wire, and compares the encoding and the five exception
 * flags this board answers with, bit for bit, against what the file
 * records. This sketch is the device half: a line in, a line out, and
 * no state between them except the staging buffers a reduction needs.
 *
 * The protocol is CSRP/1 and it is documented in src/cft_replay.h,
 * which is also where the answering lives. Everything here is the
 * transport: read a line, hand it over, write the answer.
 *
 * THE BUFFERS ARE THE INTERESTING PART. They are static, sized per
 * part below, and they are what decides which cases this board can be
 * asked at all. The `id` verb reports all three, the host reads them,
 * and a case that will not fit is SKIPPED BY NAME and counted rather
 * than truncated into a smaller case that would pass. On an ATmega328P
 * with 2 KB of RAM that is most of the reduction sets and all of the
 * character sets; on a Pico it is nothing at all. docs/EMBEDDED.md has
 * the measured numbers per board.
 */

#include <stdio.h>
#include <string.h>

#include <cft.h>
#include <cft_replay.h>

/* ---- sizing ------------------------------------------------------
 *
 * line   the longest request accepted. A `run` at fp64 is about 80
 *        characters (three 16-digit operands plus the frame); at
 *        fp256 about 220.
 * resp   the longest answer produced. `line` is what `id` publishes
 *        and the host sizes both directions from, so `resp` may only
 *        be smaller where nothing large comes back - the check below
 *        enforces that. A `run` answers in about 32 characters and the
 *        longest answer a part with no character buffer gives is
 *        `id`'s 60, so 72 is enough on an ATmega328P and 24 bytes of
 *        RAM saved. A bigger pair is fewer round trips on the
 *        character sets and nothing else.
 * stage  each of the two reduction vectors, in BYTES. A reduction case
 *        of n elements needs n * sizeof(element) here - the sets go to
 *        n = 129, so 1032 bytes at fp64 - and a device with less
 *        answers `err toobig` for the long ones, which the host
 *        counts and names.
 * out    the character-conversion output. The exact decimal of the
 *        smallest binary256 subnormal is 183,476 characters, so no
 *        part here holds every case; what a board can hold, it does.
 */
#if defined(__AVR_ATmega328P__) || defined(__AVR_ATmega168__)
/* 2 KB of RAM, and the arithmetic wants a third of it for its stack:
 * an fp64 case takes 944 bytes of it end to end, measured
 * with avr-gcc -fstack-usage: docs/EMBEDDED.md names every frame in
 * the chain and the margin that is left.
 *
 * Both staging buffers are ZERO here, and that is not a compromise:
 * this part's responder is CFT_REPLAY_MIN (cft_replay.h), which
 * carries no verb that reads a staging buffer. A `red` that cannot be
 * answered and a buffer for it that could not hold one would be RAM
 * spent on nothing. `id` reports 0 and the host skips those sets by
 * name.
 *
 * 96 characters of request is an fp64 `run` (79) with 17 spare;
 * 72 of answer is a `run` reply (32) with twice that again. */
#  define VR_LINE    96
#  define VR_RESP    72
#  define VR_STAGE  0
#  define VR_OUT    0
#elif defined(__AVR_ATmega2560__)
/* 8 KB. Room for every reduction case at fp64 (129 * 8 = 1032) with
 * the two buffers, and still under a fifth of RAM. */
#  define VR_LINE   256
#  define VR_STAGE  1088
#  define VR_OUT    0
#elif defined(ARDUINO_ARCH_RP2040)
/* 264 KB. Enough for every reduction case at fp256 (129 * 32 = 4128)
 * and for every character sequence up to 32 KB - which is every fp32,
 * fp64 and fp128 case in the sets and all but 25 of fp256's 2,145.
 * Those 25 run to 183,476 characters and are not a buffer-size
 * problem: producing one needs the arbitrary-precision natural behind
 * it as well (docs/EMBEDDED.md). */
#  define VR_LINE   4096
#  define VR_STAGE  8192
#  define VR_OUT    32768
#elif defined(ARDUINO_ARCH_ESP32)
/* 520 KB of SRAM, but not 520 KB of STATIC data: the linker's
 * dram0_0_seg is the segment .data and .bss go in, and it is about
 * 160 KB after the IDF's own statics. 104 KB of buffers here
 * overflowed it by 3,088 bytes (measured); 56 KB does not, and 32 KB
 * of character output still covers every fp32, fp64 and fp128 sequence
 * the sets contain and all but 25 of fp256's 2,145. */
#  define VR_LINE   4096
#  define VR_STAGE  8192
#  define VR_OUT    32768
#else
#  define VR_LINE   1024
#  define VR_STAGE  4096
#  define VR_OUT    8192
#endif

/* Where the two are not sized apart, they are the same. */
#ifndef VR_RESP
#define VR_RESP VR_LINE
#endif

/* VR_LINE is what `id` publishes, and the host sizes BOTH directions
 * from it: the request it builds and the `get` chunk it asks back. So
 * a smaller response buffer is only safe where nothing comes back
 * through `get`, which means where there is no character-conversion
 * output at all. Say so at compile time rather than discovering it as
 * a truncated answer on a board.
 *
 * The ATmega328P is exactly that case: no `out` buffer, and 24 bytes
 * of RAM saved by not carrying a response buffer as long as the
 * longest request. */
#if VR_OUT && (VR_RESP < VR_LINE)
#error "VR_RESP < VR_LINE with a character-conversion buffer: the host \
sizes its `get` chunks from the line budget `id` reports, so the answer \
would not fit. Raise VR_RESP to VR_LINE, or set VR_OUT to 0."
#endif

#ifndef VR_BAUD
#define VR_BAUD 115200
#endif

static cft_device *dev;
static cft_replay  R;

static char    line[VR_LINE];
static char    resp[VR_RESP];
#if VR_STAGE
static uint8_t stage0[VR_STAGE];
static uint8_t stage1[VR_STAGE];
#endif
#if VR_OUT
static char    outbuf[VR_OUT];
#endif

static size_t used;
static char   seqdig[4];

/* A well-formed `err` frame for a request whose ANSWER did not fit the
 * response buffer.
 *
 * It cannot happen to a host that respected the capacity `id`
 * published, and the reply still has to be a real frame: an
 * unreadable one would cost the host a protocol abort, and silence
 * would cost it a timeout per case for the rest of the run. Both would
 * report a transport problem where the truth is "this board told you
 * it could not hold that".
 *
 * The sequence number is copied from the request, so the host matches
 * it to the case it asked. */
static void send_toobig(const char *req)
{
    static const char D[] = "0123456789abcdef";
    char f[24];
    uint16_t crc;
    int n = 0;
    f[n++] = '<';
    f[n++] = (req[0] == '>') ? req[1] : '0';
    f[n++] = (req[0] == '>') ? req[2] : '0';
    f[n++] = ' ';
    memcpy(f + n, "err toobig", 10);
    n += 10;
    crc = cft_replay_crc16(f, (size_t)n);
    f[n++] = ' ';
    f[n++] = '*';
    f[n++] = D[(crc >> 12) & 0xf];
    f[n++] = D[(crc >> 8) & 0xf];
    f[n++] = D[(crc >> 4) & 0xf];
    f[n++] = D[crc & 0xf];
    f[n] = '\0';
    Serial.println(f);
}

/* A line whose device could not be opened is not a line to answer:
 * every reply would be a refusal, and a harness would score 1,068,915
 * skips as a successful run of nothing. Say it once a second, forever,
 * in a shape the host's resync counter will notice. */
static bool ready;

/* The ESP32 Arduino core runs loop() on an 8 KB stack, and the
 * correctly-rounded transcendentals want far more than that - the first
 * `trn` on an ESP32-S3 overflowed it and the board reset without
 * answering (2026-09-09, the first board this ran on). The core's own
 * hook raises it; 96 KB is a tenth of the S3's RAM and covers the
 * deepest path with room. The RP2040 core gives loop() the main stack,
 * and the AVRs have no transcendentals to run. */
#if defined(ARDUINO_ARCH_ESP32)
SET_LOOP_TASK_STACK_SIZE(96 * 1024);
#endif

/* What `env` adds after the responder's counters: the die temperature
 * where the part has a sensor, the free heap, and the uptime, as
 * key=value tokens. A long run can then be read against the board's
 * thermals and memory. The ESP32-S3's throughput decayed steadily
 * from 62,000 cases on (2026-09-09); its package is bare plastic on
 * the PCB with no heatsink, and whether the decay is heat or a leak
 * is a question these two numbers answer between them. */
static int board_env(void *ctx, char *out, size_t cap)
{
    (void)ctx;
#if defined(ARDUINO_ARCH_ESP32)
    return snprintf(out, cap, "temp=%.1f heap=%lu up=%lu",
                    (double)temperatureRead(),
                    (unsigned long)ESP.getFreeHeap(),
                    (unsigned long)millis());
#elif defined(ARDUINO_ARCH_RP2040)
    return snprintf(out, cap, "temp=%.1f heap=%lu up=%lu",
                    (double)analogReadTemp(),
                    (unsigned long)rp2040.getFreeHeap(),
                    (unsigned long)millis());
#elif defined(__AVR__)
    /* No die sensor on an ATmega. Free RAM is the gap between the
     * heap's end and the stack pointer - the classic measurement,
     * and the one number a 2 KB part most wants watched. */
    extern int __heap_start, *__brkval;
    int v;
    int free_ram = (int)&v - (__brkval == 0 ? (int)&__heap_start
                                             : (int)__brkval);
    return snprintf(out, cap, "heap=%d up=%lu", free_ram,
                    (unsigned long)millis());
#else
    return snprintf(out, cap, "up=%lu", (unsigned long)millis());
#endif
}

void setup()
{
#if defined(ARDUINO_ARCH_ESP32)
    /* The receive ring has to hold a whole request, and the core's
     * default for USB CDC is 256 bytes (HWCDC.cpp), while VR_LINE
     * publishes 4,096. That gap is invisible until something sends a
     * long line: an S3 answered a 275-character `put` and never
     * answered a 403-character one, which is where a census died at
     * 222,000 cases (2026-09-09). The reduction sets are the first to
     * send one, so every set before them passes and the board looks
     * healthy. Must precede begin(); costs RAM the S3 has.
     *
     * All three of the ESP32's serial classes - HWCDC, USBCDC and the
     * UART - carry this method, so it does not matter which `Serial`
     * the board's variant binds. */
    Serial.setRxBufferSize(VR_LINE * 2);
#endif
    Serial.begin(VR_BAUD);
    while (!Serial && millis() < 3000)
        ;                                  /* native USB: wait, briefly */

    ready = (cft_open(NULL, 0, &dev) == CFT_OK) &&
            (cft_replay_init(&R, dev,
#if VR_STAGE
                             stage0, stage1, VR_STAGE,
#else
                             NULL, NULL, 0,
#endif
#if VR_OUT
                             outbuf, VR_OUT,
#else
                             NULL, 0,
#endif
                             VR_LINE) == 0);
    if (ready)
        R.env = board_env;         /* after init, which zeroes R */
    if (ready)
        Serial.println(F("# cft VectorReplay ready - csrp/1"));
    else
        Serial.println(F("# cft VectorReplay FAILED to open a device"));
}

void loop()
{
    if (!ready) {
        Serial.println(F("# cft VectorReplay FAILED to open a device"));
        delay(1000);
        return;
    }

    while (Serial.available() > 0) {
        int c = Serial.read();
        if (c < 0)
            break;
        if (c == '\r')
            continue;
        if (c == '\n') {
            if (used == 0)
                continue;
            line[used] = '\0';
            used = 0;
            /* The sequence digits before the parse, which tokenises
             * `line` in place: send_toobig needs them and cannot read
             * them afterwards. */
            seqdig[0] = line[0];
            seqdig[1] = line[1];
            seqdig[2] = line[2];
            if (cft_replay_line(&R, line, resp, sizeof resp) > 0)
                Serial.println(resp);
            else
                send_toobig(seqdig);
            continue;
        }
        if (used + 1 < sizeof line) {
            line[used++] = (char)c;
        } else {
            /* Overlong: drop the rest of it and let the frame check
             * fail on what arrived. A truncated request must never be
             * answered as a shorter valid one. */
            used = sizeof line - 1;
        }
    }
}
