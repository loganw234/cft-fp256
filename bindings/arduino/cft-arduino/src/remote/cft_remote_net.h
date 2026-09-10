/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The frames of docs/REMOTE.md over a socket, from the board: on an
 * ESP32 that is a WiFiClient talking straight to cft-serve's TCP port,
 * with no bridge and no host in between.
 *
 *     WiFiClient sock;
 *     cftr::NetTransport io(sock);
 *     io.connect("192.168.1.20", 7754);
 *     dev.begin(io, CFT_REMOTE_ABI);
 *
 * THE TYPE IS `Client`, THE ARDUINO ONE, not WiFiClient: WiFiClient is
 * a Client, and so is WiFiClientSecure, and so is an Ethernet shield's
 * EthernetClient, and this transport does not need to know which. The
 * ESP32 example passes a WiFiClient because that is the board the
 * examples are for.
 *
 * (Arduino's Client and this library's cftr::Client are two different
 * classes with the same name in different namespaces. Inside this
 * header the global one is written ::Client, which is why.)
 *
 * WHY THERE IS A STAGING BUFFER HERE AND NOT IN THE STREAM TRANSPORT.
 * A HardwareSerial has a transmit ring and coalesces for free. The
 * ESP32's WiFiClient::write() is one lwIP send() per call, so a frame
 * written as a header and then thirty-two-byte elements would be
 * thirty-odd packets and thirty-odd round trips' worth of latency with
 * TCP_NODELAY set - and NODELAY has to be set, because without it
 * Nagle adds a delay to every request instead. Staging the frame and
 * flushing it once is what makes the two settings agree.
 */

#ifndef CFT_REMOTE_NET_H_
#define CFT_REMOTE_NET_H_

#include "cft_remote.h"

#if defined(ARDUINO)

#include <Client.h>
#include <string.h>

namespace cftr {

class NetTransport : public Transport {
public:
    explicit NetTransport(::Client &c) : c_(&c), n_(0) {}

    /* Open the connection. True on success.
     *
     * TCP_NODELAY is the SKETCH's to set, on the concrete client and
     * after this returns - `sock.setNoDelay(true)` on an ESP32 - and
     * it should: without it Nagle holds a small request back for the
     * previous response's acknowledgement, which is a delay on every
     * round trip. It is not set here because the Arduino `Client` base
     * class has no such method and this transport is deliberately
     * written against the base. */
    bool connect(const char *host, uint16_t port)
    {
        n_ = 0;
        return c_->connect(host, port) != 0;
    }

    void stop() { n_ = 0; c_->stop(); }

    virtual int writeBytes(const uint8_t *p, uint16_t n)
    {
#if CFT_REMOTE_NET_TX_BUFFER > 0
        while (n) {
            uint16_t room = (uint16_t)(CFT_REMOTE_NET_TX_BUFFER - n_);
            uint16_t k = n < room ? n : room;
            memcpy(buf_ + n_, p, k);
            n_ = (uint16_t)(n_ + k);
            p += k;
            n = (uint16_t)(n - k);
            if (n_ == CFT_REMOTE_NET_TX_BUFFER && push())
                return -1;
        }
        return 0;
#else
        return c_->write(p, (size_t)n) == (size_t)n ? 0 : -1;
#endif
    }

    virtual int readBytes(uint8_t *p, uint16_t n, uint32_t timeoutMs)
    {
        uint32_t last = millis();
        uint16_t got = 0;
        while (got < n) {
            int k = c_->read(p + got, (size_t)(n - got));
            if (k > 0) {
                got = (uint16_t)(got + k);
                last = millis();
                continue;
            }
            /* read() answers 0 or -1 for "nothing yet"; only a closed
             * connection with nothing buffered is fatal. */
            if (!c_->connected() && !c_->available())
                return -1;
            if ((uint32_t)(millis() - last) > timeoutMs)
                return -1;
        }
        return 0;
    }

    virtual int flushOut()
    {
#if CFT_REMOTE_NET_TX_BUFFER > 0
        if (push())
            return -1;
#endif
        c_->flush();
        return 0;
    }

    virtual bool alive() { return c_->connected() != 0; }

private:
#if CFT_REMOTE_NET_TX_BUFFER > 0
    int push()
    {
        uint16_t n = n_;
        n_ = 0;
        if (!n)
            return 0;
        return c_->write(buf_, (size_t)n) == (size_t)n ? 0 : -1;
    }
    uint8_t buf_[CFT_REMOTE_NET_TX_BUFFER];
#endif
    ::Client *c_;
    uint16_t  n_;
};

}  /* namespace cftr */

#endif /* ARDUINO */
#endif /* CFT_REMOTE_NET_H_ */
