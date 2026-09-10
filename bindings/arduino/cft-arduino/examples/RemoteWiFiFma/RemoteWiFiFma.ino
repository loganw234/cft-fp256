/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The same arithmetic as RemoteSerialFma, over Wi-Fi, with no bridge
 * and no host process in the middle: an ESP32 opens a TCP connection
 * straight to cft-serve's frame port and speaks the protocol of
 * docs/REMOTE.md down it.
 *
 * Nothing in the client changes to make this work. The frames are the
 * frames; only the byte pipe under them is different, which is the
 * point of writing the transport as an interface and the reason the
 * serial route and this one cannot disagree about an answer.
 *
 * WIRING IT UP
 *
 *   1. start a server that listens on something other than loopback -
 *      the board is not on this machine:
 *
 *        host/cft-serve --port 7754 --bind 0.0.0.0
 *
 *      READ THAT FLAG BEFORE YOU USE IT. --bind 0.0.0.0 puts an
 *      unauthenticated, unencrypted arithmetic service on every
 *      interface this machine has; docs/REMOTE.md says what that does
 *      and does not mean. On a home network behind a router it is a
 *      device on your desk. On anything else, think first.
 *
 *   2. copy arduino_secrets_example.h to arduino_secrets.h in this
 *      folder and put your network in it. That file is NOT committed -
 *      the .gitignore beside this sketch keeps it out - and this sketch
 *      compiles without it, with placeholders that will not connect.
 *
 *   3. set CFT_SERVER_HOST below to the machine running cft-serve.
 *
 *   4. flash it and open the serial monitor at 115200. Serial is only
 *      the log here: the protocol is on the socket, so there is no
 *      sharing of a port and no need for the bridge's --framed.
 */

#include <cft_remote.h>
#include <WiFi.h>

/* ---- what to edit -------------------------------------------------- */

/* The ABI word this client CLAIMS; the server refuses a mismatch.
 *   python host/tools/cft-serial-bridge.py --probe-abi HOST:PORT  */
#define CFT_REMOTE_ABI 0x0000000BUL      /* libcft 0.11 */

#define CFT_SERVER_HOST "192.168.1.20"
#define CFT_SERVER_PORT 7754

/* Your network, out of a file this repository never sees. Without it
 * the sketch still compiles - which is what the compile gate needs -
 * and will not associate, which is what an unconfigured board should
 * do rather than silently join something. */
#if defined(__has_include)
#  if __has_include("arduino_secrets.h")
#    include "arduino_secrets.h"
#  endif
#endif
#ifndef SECRET_SSID
#  define SECRET_SSID "set-me-in-arduino_secrets.h"
#  define SECRET_PASS ""
#endif

/* ---- the case, and the answer libcft gives for it ------------------ *
 * fma(1 + ulp, 1 + ulp, -1) at binary256: 2^-235, inexact. The
 * encodings are little-endian, least significant byte first, straight
 * out of libcft. */
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

static WiFiClient sock;
static cftr::NetTransport io(sock);
static cftr::Client dev;

static void sayWhy(void)
{
    Serial.print(F("cft: status "));
    Serial.print(dev.status());
    Serial.print(F(" - "));
    Serial.println(cftr::reasonText(dev.reason()));
    if (dev.message()[0]) {
        Serial.print(F("cft: the server said: "));
        Serial.println(dev.message());
    }
    if (dev.reason() == cftr::R_ABI) {
        Serial.print(F("cft: it is libcft 0x"));
        Serial.print(dev.serverAbi(), HEX);
        Serial.println(F("; edit CFT_REMOTE_ABI to match"));
    }
}

void setup()
{
    char hex[65];
    uint8_t got[32], expect[32];
    uint32_t flags = 0, bus = 0;

    Serial.begin(115200);
    delay(300);
    Serial.println();
    Serial.print(F("cft: joining "));
    Serial.println(F(SECRET_SSID));
    WiFi.mode(WIFI_STA);
    WiFi.begin(SECRET_SSID, SECRET_PASS);
    for (int i = 0; i < 60 && WiFi.status() != WL_CONNECTED; i++) {
        delay(500);
        Serial.print('.');
    }
    Serial.println();
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println(F("cft: no network - check arduino_secrets.h"));
        return;
    }
    Serial.print(F("cft: "));
    Serial.print(WiFi.localIP());
    Serial.print(F(" -> "));
    Serial.print(F(CFT_SERVER_HOST));
    Serial.print(':');
    Serial.println(CFT_SERVER_PORT);

    if (!io.connect(CFT_SERVER_HOST, CFT_SERVER_PORT)) {
        Serial.println(F("cft: the server did not answer"));
        return;
    }
    /* TCP_NODELAY, on the concrete client and after the connect. The
     * transport is written against the Arduino Client base class,
     * which has no such method - and without it Nagle holds a small
     * request back waiting for the previous response's ack, which is a
     * delay on every single round trip. */
    sock.setNoDelay(true);

    if (dev.begin(io, CFT_REMOTE_ABI) != cftr::OK) {
        Serial.println(F("cft: HELLO failed"));
        sayWhy();
        return;
    }
    Serial.print(F("cft: server backend \""));
    Serial.print(dev.backend());
    Serial.print(F("\", "));
    Serial.print(dev.tiles());
    Serial.print(F(" tile(s), formats 0x"));
    Serial.print(dev.formatMask(), HEX);
    Serial.print(F(", caps block "));
    Serial.print(dev.capsBytes());
    Serial.println(F(" bytes"));

    cftr::FlashOperands in(cftr::FP256, A256, A256, C256);
    cftr::RamResults out(cftr::FP256, got);
    unsigned long t0 = micros();
    int st = dev.run(cftr::OP_FMA, cftr::FP256, cftr::RNE, in.present(), 1,
                     in, out, &flags, &bus);
    unsigned long us = micros() - t0;
    if (st != cftr::OK) {
        Serial.println(F("cft: the fma failed"));
        sayWhy();
        return;
    }
    cftr::toHex(hex, got, 32);
    Serial.print(F("cft: binary256 d = 0x"));
    Serial.println(hex);
    Serial.print(F("cft:      flags 0x"));
    Serial.print(flags, HEX);
    Serial.print(F("  bus 0x"));
    Serial.print(bus, HEX);
    Serial.print(F("  round trip "));
    Serial.print(us);
    Serial.println(F(" us"));

    memcpy_P(expect, D256, 32);
    if (memcmp(got, expect, 32) == 0) {
        Serial.println(F("cft: PASS - every bit is the bit libcft computes"));
    } else {
        cftr::toHex(hex, expect, 32);
        Serial.print(F("cft: FAIL - expected 0x"));
        Serial.println(hex);
    }

    /* What a round trip costs over this network, once the connection is
     * warm: the same one-element fma, a hundred times. */
    t0 = micros();
    for (int i = 0; i < 100 && st == cftr::OK; i++)
        st = dev.run(cftr::OP_FMA, cftr::FP256, cftr::RNE, in.present(), 1,
                     in, out, 0, 0);
    us = micros() - t0;
    if (st == cftr::OK) {
        Serial.print(F("cft: 100 more round trips, "));
        Serial.print(us / 100);
        Serial.println(F(" us each"));
    }

    dev.end();
    io.stop();
}

void loop()
{
    delay(1000);
}
