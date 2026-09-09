/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * An Uno computes in binary256.
 *
 * It cannot represent a binary256 number, or a binary64 one - an AVR's
 * `double` is thirty-two bits - and it does not need to. It sends the
 * ENCODINGS to a cft device and gets the encoding of the answer back,
 * and the answer is the answer: the same bits a desktop gets, the same
 * bits the card gets, because they are all the same device on the
 * other end of the same protocol.
 *
 * WIRING IT UP
 *
 *   1. on the host, start a server:
 *        make -C host cft-serve
 *        host/cft-serve --port 7754
 *   2. find out which libcft it is, once:
 *        python host/tools/cft-serial-bridge.py --probe-abi 127.0.0.1:7754
 *      and put the number it prints in CFT_REMOTE_ABI below.
 *   3. flash this sketch, then close every serial monitor - the bridge
 *      needs the port to itself - and run:
 *        python host/tools/cft-serial-bridge.py --serial COM5 \
 *               --server 127.0.0.1:7754 --framed --forever
 *
 *   --framed is what lets this sketch PRINT on the same wire it speaks
 *   the protocol on, which on an Uno or a Nano is the only wire there
 *   is: the bridge follows the framing, forwards the frames, and shows
 *   everything between them as the log below. On a Mega, an ESP32 or a
 *   Pico you can instead point CFT_PORT at Serial1 and keep Serial for
 *   the monitor, and then the bridge is a plain pipe.
 *
 * WHAT IT CHECKS
 *
 *   fma(1 + ulp, 1 + ulp, -1) at binary64 and at binary256. One
 *   rounding, an exact product, and an answer that is NOT what a chain
 *   of separate operations would give: the product is 1 + 2*ulp +
 *   ulp^2, the ulp^2 term is below the format's last bit, and the fused
 *   operation keeps it until the single rounding at the end. The
 *   expected encodings are compiled in below; they came out of libcft
 *   itself and the sketch compares byte for byte.
 */

/* One include: it is at the root of src/, which is what makes
 * arduino-cli resolve the library at all, and it names everything in
 * src/remote/ that a sketch uses. */
#include <cft_remote.h>

/* ---- what to edit -------------------------------------------------- */

/* The ABI word this client CLAIMS. Every frame carries it and the
 * server refuses a mismatch rather than warning about one, so it has
 * to be right - and it is one command away:
 *
 *   python host/tools/cft-serial-bridge.py --probe-abi HOST:PORT
 *
 * A wrong value is not a silent hazard: HELLO comes back refused, with
 * both versions in the message, and this sketch prints it. */
#define CFT_REMOTE_ABI 0x0000000BUL      /* libcft 0.11 */

#define CFT_PORT Serial                  /* the protocol's port */
#define CFT_LOG  Serial                  /* where this sketch talks */
#define CFT_BAUD 115200

/* ---- the case, and the answer libcft gives for it ------------------ *
 *
 * Little-endian interchange encodings, least significant byte first,
 * exactly as they sit in a cft_run buffer and exactly as they cross the
 * wire. Generated from libcft, not typed: a = 1 + one ulp, c = -1.
 *
 *   binary64   fma(0x3ff0000000000001, same, 0xbff0000000000000)
 *                = 0x3cc0000000000000, which is 2^-51, inexact
 *   binary256  fma(1+ulp, 1+ulp, -1) = 2^-235, inexact
 */
static const uint8_t A64[8] PROGMEM = {
    0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0xF0, 0x3F
};
static const uint8_t C64[8] PROGMEM = {
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xF0, 0xBF
};
static const uint8_t D64[8] PROGMEM = {
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xC0, 0x3C
};
static const uint8_t A256[32] PROGMEM = {
    0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0xF0, 0xFF, 0x3F
};
static const uint8_t C256[32] PROGMEM = {
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0xF0, 0xFF, 0xBF
};
static const uint8_t D256[32] PROGMEM = {
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x40, 0xF1, 0x3F
};

/* ---- the client ---------------------------------------------------- */

static cftr::StreamTransport io(CFT_PORT);
static cftr::Client dev;

static void say(const __FlashStringHelper *s) { CFT_LOG.println(s); }

static void sayHex(const __FlashStringHelper *label, const uint8_t *p,
                   uint8_t n)
{
    char hex[2 * 32 + 1];
    cftr::toHex(hex, p, n);
    CFT_LOG.print(label);
    CFT_LOG.print(F(" 0x"));
    CFT_LOG.println(hex);
}

static void sayWhy(void)
{
    CFT_LOG.print(F("cft: status "));
    CFT_LOG.print(dev.status());
    CFT_LOG.print(F(" - "));
    CFT_LOG.println(cftr::reasonText(dev.reason()));
    if (dev.message()[0]) {
        CFT_LOG.print(F("cft: the server said: "));
        CFT_LOG.println(dev.message());
    }
    if (dev.reason() == cftr::R_ABI) {
        CFT_LOG.print(F("cft: it is libcft 0x"));
        CFT_LOG.print(dev.serverAbi(), HEX);
        CFT_LOG.println(F("; edit CFT_REMOTE_ABI to match"));
    }
}

/* One fma, from operands in flash, compared with the answer in flash.
 * The result is streamed into a local buffer by RamResults and only
 * LOOKED AT after run() has returned OK - which is the rule
 * cftr::Results states, and the only rule this API asks a caller to
 * keep. */
static bool fmaCase(uint8_t fmt, const uint8_t *a, const uint8_t *c,
                    const uint8_t *want, const __FlashStringHelper *name)
{
    uint8_t esz = cftr::formatSize(fmt);
    uint8_t got[32], expect[32];
    uint32_t flags = 0, bus = 0;

    /* b is a again: one array, two operands, no copy of either. */
    cftr::FlashOperands in(fmt, a, a, c);
    cftr::RamResults out(fmt, got);

    unsigned long t0 = millis();
    int st = dev.run(cftr::OP_FMA, fmt, cftr::RNE, in.present(), 1, in, out,
                     &flags, &bus);
    unsigned long ms = millis() - t0;
    if (st != cftr::OK) {
        CFT_LOG.print(F("cft: "));
        CFT_LOG.print(name);
        CFT_LOG.println(F(" failed"));
        sayWhy();
        return false;
    }
    memcpy_P(expect, want, esz);
    sayHex(name, got, esz);
    CFT_LOG.print(F("cft:      flags 0x"));
    CFT_LOG.print(flags, HEX);
    CFT_LOG.print(F("  bus 0x"));
    CFT_LOG.print(bus, HEX);
    CFT_LOG.print(F("  round trip "));
    CFT_LOG.print(ms);
    CFT_LOG.println(F(" ms"));
    if (memcmp(got, expect, esz) != 0) {
        sayHex(F("cft: EXPECTED"), expect, esz);
        return false;
    }
    return true;
}

void setup()
{
    CFT_PORT.begin(CFT_BAUD);
    while (!CFT_PORT)
        ;                       /* boards with native USB */
    delay(200);
    io.drain();                 /* whatever the last run or the
                                 * bootloader left on the line */

    say(F("cft: hello - the frame protocol of docs/REMOTE.md over a UART"));
    if (dev.begin(io, CFT_REMOTE_ABI) != cftr::OK) {
        say(F("cft: HELLO failed"));
        sayWhy();
        return;
    }
    CFT_LOG.print(F("cft: server backend \""));
    CFT_LOG.print(dev.backend());
    CFT_LOG.print(F("\", "));
    CFT_LOG.print(dev.tiles());
    CFT_LOG.print(F(" tile(s), formats 0x"));
    CFT_LOG.print(dev.formatMask(), HEX);
    CFT_LOG.print(F(", abi 0x"));
    CFT_LOG.println(dev.serverAbi(), HEX);

    bool ok = true;
    ok &= fmaCase(cftr::FP64, A64, C64, D64, F("cft: binary64  d ="));
    ok &= fmaCase(cftr::FP256, A256, C256, D256, F("cft: binary256 d ="));

    say(ok ? F("cft: PASS - every bit is the bit libcft computes")
           : F("cft: FAIL - see above"));
    dev.end();
}

void loop()
{
    delay(1000);
}
