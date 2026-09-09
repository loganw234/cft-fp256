/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Hello - what this board is, and one fused multiply-add whose answer
 * is known in advance.
 *
 * The first thing to flash. It prints the library's ABI, the backend,
 * the formats this build carries and how much RAM is left, then
 * computes
 *
 *     fma(1 + 2^-52, 1 + 2^-52, -1)  =  0x3cc0000000000000, inexact
 *
 * in binary64 and says whether the encoding and the flags are the
 * ones the golden model gives. That single case is not a conformance
 * run - VectorReplay is - but it is exact, it exercises the wide
 * intermediate the format's fused multiply-add needs, and if it is
 * right then the build, the profile and the toolchain are all sound
 * enough to be worth replaying a million cases through.
 *
 * 1 + 2^-52 squared is 1 + 2^-51 + 2^-104. Subtracting 1 leaves
 * 2^-51 + 2^-104 exactly, which binary64 cannot hold; rounded to
 * nearest it is 2^-51 = 0x3cc0000000000000, and inexact is raised.
 * A library that computed the multiply and the add as two roundings
 * would answer 2^-51 with no flag, or 0 - which is why this is the
 * case to print.
 */

#include <string.h>

#include <cft.h>

static cft_device *dev;

/* Little-endian interchange encodings, which is what the API takes at
 * every format: byte 0 is the least significant. */
static const uint8_t ONE_PLUS_ULP[8] =
    { 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf0, 0x3f };
static const uint8_t MINUS_ONE[8] =
    { 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf0, 0xbf };
static const uint8_t EXPECT[8] =
    { 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xc0, 0x3c };

static void print_hex(const uint8_t *e, int n)
{
    static const char D[] = "0123456789abcdef";
    Serial.print("0x");
    for (int i = n - 1; i >= 0; i--) {
        Serial.print(D[e[i] >> 4]);
        Serial.print(D[e[i] & 0xf]);
    }
}

/* How much room is left between the heap and this frame. The linker
 * reports static RAM at build time; this is the other half of the
 * question - what a call has to work in - and it is the number that
 * decides whether an fp256 fused multiply-add fits on a part. */
#if defined(__AVR__)
extern "C" char *__brkval;
extern "C" char __heap_start;
static long free_ram(void)
{
    char here;
    return (long)(&here - (__brkval ? __brkval : &__heap_start));
}
#define HAVE_FREE_RAM 1
#elif defined(ARDUINO_ARCH_ESP32)
static long free_ram(void) { return (long)ESP.getFreeHeap(); }
#define HAVE_FREE_RAM 1
#elif defined(ARDUINO_ARCH_RP2040)
static long free_ram(void) { return (long)rp2040.getFreeHeap(); }
#define HAVE_FREE_RAM 1
#endif

void setup()
{
    Serial.begin(115200);
    while (!Serial && millis() < 3000)
        ;

    uint32_t abi = cft_abi_version();
    Serial.print(F("libcft ABI "));
    Serial.print(abi >> 16);
    Serial.print('.');
    Serial.println(abi & 0xffffu);

    if (cft_open(NULL, 0, &dev) != CFT_OK) {
        Serial.println(F("cft_open failed"));
        return;
    }

    cft_caps caps;
    memset(&caps, 0, sizeof caps);
    caps.struct_size = sizeof caps;
    if (cft_get_caps(dev, &caps) == CFT_OK) {
        Serial.print(F("backend        "));
        Serial.println(caps.backend);
        Serial.print(F("formats        "));
        for (int i = 0; i < 4; i++)
            if (caps.format_mask & (1u << i)) {
                Serial.print(cft_format_name((cft_format)i));
                Serial.print(' ');
            }
        Serial.println();
        Serial.print(F("flags readable "));
        Serial.println(caps.flags_readable ? F("yes") : F("no"));
    }
#ifdef HAVE_FREE_RAM
    Serial.print(F("free RAM       "));
    Serial.print(free_ram());
    Serial.println(F(" bytes"));
#endif

    uint8_t d[8];
    uint32_t flags = 0;
    cft_status st = cft_run(dev, CFT_FMA, CFT_FP64, CFT_RNE,
                            ONE_PLUS_ULP, ONE_PLUS_ULP, MINUS_ONE,
                            d, 1, &flags, NULL);
    Serial.print(F("fma(1+ulp, 1+ulp, -1) = "));
    if (st != CFT_OK) {
        Serial.println(cft_strerror(st));
        return;
    }
    print_hex(d, 8);
    Serial.print(F("  flags 0x"));
    Serial.println(flags, HEX);
    Serial.print(F("expected              "));
    print_hex(EXPECT, 8);
    Serial.println(F("  flags 0x10"));
    Serial.println(memcmp(d, EXPECT, 8) == 0 && flags == CFT_FLAG_INEXACT
                   ? F("MATCH - the same bits the golden model gives")
                   : F("MISMATCH"));
}

void loop()
{
    delay(1000);
}
