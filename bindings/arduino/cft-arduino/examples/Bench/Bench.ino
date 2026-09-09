/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Bench - how fast this part computes, per format and per operation.
 *
 * Prints elements a second for add, multiply and fused multiply-add at
 * every format the build carries, over the UART, once, and then
 * repeats every ten seconds so a board left plugged in keeps a record.
 *
 * WHAT IT TIMES, AND WHAT IT DOES NOT. cft_run over an array of
 * elements, wall clock, with the operands already in RAM: the
 * arithmetic and the library's per-element dispatch, and nothing else.
 * Not the serial link, not the staging a replay does, not cft_open.
 * The array is small on purpose - a few dozen elements - because the
 * point is the per-element cost and a part with 2 KB of RAM cannot
 * hold more; the batch is repeated until at least half a second has
 * passed, so the timer's resolution is not the measurement.
 *
 * The operands are chosen to be ORDINARY: normal numbers of similar
 * magnitude with full significands, which is the near case in the
 * addend alignment and the one an average costs anything to compute.
 * Timing zeros or infinities would time the special-case ladder and
 * report a number four times too good.
 *
 * These are software-backend numbers on one core with no
 * floating-point hardware in the loop - the same integer code the host
 * and the FPGA's model run. They are meant to answer "can this part do
 * the work at all", not to be compared with a native double.
 */

#include <string.h>

#include <cft.h>

static cft_device *dev;

/* Sized for the smallest part: 8 fp64 elements is 64 bytes per
 * operand array, four of them 256 bytes - which leaves an ATmega328P
 * the 944 bytes of stack an fp64 case needs (docs/EMBEDDED.md).
 * A bigger array would not measure anything different; the work is
 * per element. */
#if defined(__AVR_ATmega328P__) || defined(__AVR_ATmega168__)
#  define BN 8
#elif defined(__AVR__)
#  define BN 48
#else
#  define BN 256
#endif

/* One buffer per role, at the widest format the build carries. */
#define EW (4 << CFT_MAX_FORMAT)

static uint8_t A[BN * EW], B[BN * EW], C[BN * EW], D[BN * EW];

/* A normal number with a full significand, built from the format's own
 * description so the same code serves all four: exponent = bias, so
 * the value is in [1, 2), with every trailing significand bit set and
 * the low bits varied per element so no two are identical.
 *
 * Written straight into the little-endian encoding, because that is
 * the interchange format and the library takes nothing else. */
static void fill(uint8_t *buf, cft_format fmt, unsigned n, uint32_t salt)
{
    const size_t esz = cft_format_size(fmt);
    /* exponent field width and trailing significand width, by format */
    static const uint8_t EXPW[4] = { 8, 11, 15, 19 };
    const unsigned expw = EXPW[(int)fmt];
    const unsigned manw = (unsigned)(esz * 8u - 1u - expw);
    const uint32_t bias = (1uL << (expw - 1)) - 1uL;

    for (unsigned k = 0; k < n; k++) {
        uint8_t *e = buf + k * esz;
        memset(e, 0xff, esz);                     /* significand all ones */
        /* Clear the sign and exponent fields, then write the exponent. */
        for (unsigned bit = manw; bit < esz * 8u; bit++)
            e[bit >> 3] &= (uint8_t)~(1u << (bit & 7u));
        uint32_t x = bias;
        for (unsigned bit = 0; bit < expw; bit++) {
            if (x & (1uL << bit))
                e[(manw + bit) >> 3] |= (uint8_t)(1u << ((manw + bit) & 7u));
        }
        /* Vary the low bits so the batch is not one value repeated. */
        e[0] ^= (uint8_t)(k * 31u + salt);
        e[1] ^= (uint8_t)(k * 7u + (salt >> 8));
    }
}

static const char *op_name(cft_op op)
{
    return cft_op_name(op);
}

static void bench_one(cft_format fmt, cft_op op)
{
    const size_t esz = cft_format_size(fmt);
    if (esz == 0 || esz > EW)
        return;
    if (!cft_supports(dev, op, fmt))
        return;

    fill(A, fmt, BN, 1);
    fill(B, fmt, BN, 2);
    fill(C, fmt, BN, 3);

    /* Grow the repetition count until the run is long enough that
     * millis()'s one-millisecond tick is noise rather than the
     * measurement. */
    unsigned long reps = 1, ms = 0;
    for (;;) {
        unsigned long t0 = millis();
        for (unsigned long r = 0; r < reps; r++)
            if (cft_run(dev, op, fmt, CFT_RNE, A, B, C, D, BN,
                        NULL, NULL) != CFT_OK) {
                Serial.println(F("  cft_run refused"));
                return;
            }
        ms = millis() - t0;
        if (ms >= 500 || reps > 1000000UL)
            break;
        reps = ms < 10 ? reps * 8 : (reps * 600) / (ms ? ms : 1) + 1;
    }

    const unsigned long elems = reps * (unsigned long)BN;
    /* elements a second, without floating point: the whole point of
     * this library is that a part with no FPU is not disadvantaged,
     * and a benchmark that needed one to print its own result would
     * be a strange advertisement for that. */
    const unsigned long per_s = ms ? (elems * 1000UL) / ms : 0;

    Serial.print(F("  "));
    Serial.print(cft_format_name(fmt));
    Serial.print(F("\t"));
    Serial.print(op_name(op));
    Serial.print(F("\t"));
    Serial.print(elems);
    Serial.print(F(" elements in "));
    Serial.print(ms);
    Serial.print(F(" ms\t"));
    Serial.print(per_s);
    Serial.println(F(" /s"));
}

void setup()
{
    Serial.begin(115200);
    while (!Serial && millis() < 3000)
        ;
    if (cft_open(NULL, 0, &dev) != CFT_OK) {
        Serial.println(F("cft_open failed"));
        return;
    }
    Serial.print(F("# cft Bench, batch of "));
    Serial.print(BN);
    Serial.println(F(" elements per cft_run call"));
}

void loop()
{
    if (!dev) {
        delay(10000);
        return;
    }
    Serial.println(F("format\top\telements\tms\trate"));
    for (int f = 0; f <= CFT_MAX_FORMAT; f++) {
        bench_one((cft_format)f, CFT_ADD);
        bench_one((cft_format)f, CFT_MUL);
        bench_one((cft_format)f, CFT_FMA);
    }
    Serial.println();
    delay(10000);
}
