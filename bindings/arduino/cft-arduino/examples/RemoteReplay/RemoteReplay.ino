/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * A Nano replays two hundred and fifty-six binary256 cases and reports
 * one number.
 *
 * It is not sent the cases. It could not hold them - two hundred and
 * fifty-six cases of three thirty-two-byte operands is twenty-four
 * kilobytes, twelve times a Nano's whole memory - and being sent them
 * would need a second protocol that nothing has ever held to anything.
 * So the cases are GENERATED, by a function of the case index that the
 * board and the host both run (src/remote/cft_remote_replay.h), and
 * what comes back is a CRC-32 over every result encoding in index
 * order.
 *
 * That single number is the verdict, and it is exact. It does not
 * depend on this board being able to represent any of the values it is
 * checking - an AVR has no 64-bit floating type, let alone a 256-bit
 * one - because a checksum over encodings needs no arithmetic on them.
 * If the digest matches, eight kilobytes of binary256 results are
 * exactly the bytes libcft computes, every one of them.
 *
 * WIRING IT UP
 *
 *   host/cft-serve --port 7754
 *   python host/tools/cft-serial-bridge.py --serial COM5 \
 *          --server 127.0.0.1:7754 --framed --forever
 *
 * WHAT TO EXPECT
 *
 *   At 115200 baud the sweep moves 256 * 4 * 32 bytes of operand and
 *   result, about 32 kB, in nine frames - so the wire, not the device,
 *   is the clock. The sketch prints how long it took and how many
 *   frames it was, which is CFT_REMOTE_CHUNK_BYTES doing its job: raise
 *   it and there are fewer, bigger frames; lower it and the board needs
 *   less of everything.
 */

#include <cft_remote.h>
#include <remote/cft_remote_replay.h>

/* The ABI word this client CLAIMS; the server refuses a mismatch.
 *   python host/tools/cft-serial-bridge.py --probe-abi HOST:PORT  */
#define CFT_REMOTE_ABI 0x0000000BUL      /* libcft 0.11 */

#define CFT_PORT Serial
#define CFT_LOG  Serial
#define CFT_BAUD 115200

static cftr::StreamTransport io(CFT_PORT);
static cftr::Client dev;

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

void setup()
{
    CFT_PORT.begin(CFT_BAUD);
    while (!CFT_PORT)
        ;
    delay(200);
    io.drain();

    if (dev.begin(io, CFT_REMOTE_ABI) != cftr::OK) {
        CFT_LOG.println(F("cft: HELLO failed"));
        sayWhy();
        return;
    }
    CFT_LOG.print(F("cft: server backend \""));
    CFT_LOG.print(dev.backend());
    CFT_LOG.print(F("\", replaying "));
    CFT_LOG.print((uint32_t)cftr::replay::CASES);
    CFT_LOG.print(F(" binary256 fma cases in "));
    CFT_LOG.print((uint32_t)cftr::replay::CASES /
                  cftr::Client::chunkElements(cftr::replay::FMT, 3) + 1);
    CFT_LOG.println(F(" frame(s)"));

    /* Operands out of a generator, results into a checksum. Between the
     * two there is never an array: the client asks for one element,
     * checksums it, asks for it again, sends it, and hands each result
     * straight to the digest. */
    cftr::replay::Operands in(cftr::replay::FMT);
    cftr::replay::Digest dg(cftr::replay::FMT);
    uint32_t flags = 0, bus = 0;

    unsigned long t0 = millis();
    int st = dev.run(cftr::replay::OP, cftr::replay::FMT, cftr::replay::RND,
                     cftr::replay::Operands::present(),
                     (uint32_t)cftr::replay::CASES, in, dg, &flags, &bus);
    unsigned long ms = millis() - t0;

    if (st != cftr::OK) {
        CFT_LOG.println(F("cft: the sweep failed"));
        sayWhy();
        return;
    }
    CFT_LOG.print(F("cft: "));
    CFT_LOG.print(dg.count());
    CFT_LOG.print(F(" results, digest 0x"));
    CFT_LOG.print(dg.value(), HEX);
    CFT_LOG.print(F(", flags 0x"));
    CFT_LOG.print(flags, HEX);
    CFT_LOG.print(F(", bus 0x"));
    CFT_LOG.print(bus, HEX);
    CFT_LOG.print(F(", "));
    CFT_LOG.print(ms);
    CFT_LOG.println(F(" ms"));

    if (dg.value() == (uint32_t)CFT_REMOTE_REPLAY_DIGEST &&
        dg.count() == (uint32_t)cftr::replay::CASES) {
        CFT_LOG.println(F("cft: PASS - every result is the bits libcft "
                          "computes"));
    } else {
        CFT_LOG.print(F("cft: FAIL - expected 0x"));
        CFT_LOG.println((uint32_t)CFT_REMOTE_REPLAY_DIGEST, HEX);
    }
    dev.end();
}

void loop()
{
    delay(1000);
}
