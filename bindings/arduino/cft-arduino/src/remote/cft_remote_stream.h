/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The frames of docs/REMOTE.md over an Arduino Stream: Serial on any
 * board, Serial1 on a Mega or a Pico, a SoftwareSerial where that is
 * what there is.
 *
 * A Stream is a byte pipe with no notion of a message, which is
 * exactly what this protocol wants - a frame's boundary is its own
 * length field and nothing else - so the transport is thirty lines and
 * the codec above it does not change at all. What sits on the far end
 * of the pipe is host/tools/cft-serial-bridge.py, which copies bytes
 * between the port and a cft-serve TCP socket and understands nothing
 * about them.
 *
 * ONE PORT, TWO PURPOSES. On an Uno or a Nano there is one UART and it
 * is the one the sketch prints to. Print to it while a conversation is
 * open and those bytes go to the server, which reads them as a frame
 * header, does not find the magic, refuses and closes. Either keep the
 * port for the protocol and say nothing on it, or run the bridge with
 * --framed, which follows the framing on the board-to-host direction
 * and prints anything BETWEEN frames as the board's log instead of
 * forwarding it. A Mega, an ESP32 or a Pico has a second port and the
 * question does not arise.
 */

#ifndef CFT_REMOTE_STREAM_H_
#define CFT_REMOTE_STREAM_H_

#include "cft_remote.h"

#if defined(ARDUINO)

#include <Stream.h>

namespace cftr {

class StreamTransport : public Transport {
public:
    explicit StreamTransport(Stream &s) : s_(&s) {}

    virtual int writeBytes(const uint8_t *p, uint16_t n)
    {
        /* HardwareSerial::write blocks when its ring is full and
         * returns what it wrote; a short write is a failed one. */
        return s_->write(p, (size_t)n) == (size_t)n ? 0 : -1;
    }

    virtual int readBytes(uint8_t *p, uint16_t n, uint32_t timeoutMs)
    {
        uint32_t last = millis();
        uint16_t got = 0;
        while (got < n) {
            int c = s_->read();
            if (c < 0) {
                if ((uint32_t)(millis() - last) > timeoutMs)
                    return -1;
                continue;
            }
            p[got++] = (uint8_t)c;
            last = millis();     /* the stall is per byte, not per call */
        }
        return 0;
    }

    virtual int flushOut()
    {
        /* Stream::flush waits for the transmit ring to drain. It costs
         * nothing to ask and it is what makes a frame one message as
         * far as the far end's read loop is concerned. */
        s_->flush();
        return 0;
    }

    /* Discard whatever is already in the receive ring. Worth calling
     * once before begin() on a board whose bootloader or whose last
     * run left bytes on the line: the protocol would refuse them, and
     * a refusal closes the connection. */
    void drain()
    {
        while (s_->read() >= 0)
            ;
    }

private:
    Stream *s_;
};

}  /* namespace cftr */

#endif /* ARDUINO */
#endif /* CFT_REMOTE_STREAM_H_ */
