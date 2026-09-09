/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * A few hundred cases a board can check without being sent a single
 * one of them.
 *
 * The obvious way to replay a vector set on a microcontroller is to
 * feed it the cases, and the obvious way is wrong twice over: an Uno
 * cannot hold them, and the feeding is a second protocol nobody has
 * held to anything. So the cases are not sent. They are GENERATED, by
 * a function of the case index that the board and the host both run,
 * and the board sends back ONE 32-bit number: a CRC-32 over every
 * result encoding in index order.
 *
 * That number is the whole verdict. It is not a tolerance, it is not a
 * sample, and it does not depend on the board being able to represent
 * any of the values it is checking: a Nano with no 64-bit floating
 * type at all can prove that four thousand bytes of binary256 results
 * are exactly the bytes libcft computes, because a CRC over the
 * encodings needs no arithmetic on them.
 *
 * The generator is the lowbias32 finaliser (docs/ATLAS.md), which is
 * here for the same reason it is there: a 32-bit hash whose value is
 * the same on every machine that computes it, with no floating point
 * anywhere in the derivation. One exponent bit is cleared so the
 * pattern is a finite number rather than mostly-NaN - the NaN paths
 * have their own vector sets and this is not one of them.
 *
 * Both users of this header are in this repository: RemoteReplay.ino
 * runs it on the board and test/host_check.cc runs it on the desktop
 * against libcft, so the digest below is derived and then held rather
 * than typed and hoped for.
 */

#ifndef CFT_REMOTE_REPLAY_H_
#define CFT_REMOTE_REPLAY_H_

#include "cft_remote.h"

namespace cftr {
namespace replay {

/* The sweep this digest names: fma at binary256, over this many cases,
 * from this seed, round to nearest even. */
enum { SEED = 0x43465432ul, CASES = 256, FMT = FP256, OP = OP_FMA,
       RND = RNE };

/* The CRC-32 of the CASES result encodings, in index order, as libcft
 * computes them. DERIVED, not chosen: test/host_check.py prints it and
 * checks it on every run, so a change in the arithmetic or in the
 * generator fails there rather than on a bench. */
#define CFT_REMOTE_REPLAY_DIGEST 0x9F924345ul

/* lowbias32, bit for bit. */
inline uint32_t mix(uint32_t x)
{
    x ^= x >> 16; x *= 0x7feb352dul;
    x ^= x >> 15; x *= 0x846ca68bul;
    x ^= x >> 16;
    return x;
}

/* Element `index` of operand `role`, as `esz` bytes. A pure function of
 * its three arguments and nothing else - which is what lets the
 * streaming client ask for it twice and lets a host on the other side
 * of the world produce the same bytes. */
inline void operand(uint8_t role, uint32_t index, uint8_t esz, uint8_t *out)
{
    uint32_t s = mix((uint32_t)SEED ^ (index * 0x9E3779B9ul) ^
                     ((uint32_t)role << 29));
    for (uint8_t i = 0; i < esz; i += 4) {
        s = mix(s + 1u);
        out[i + 0] = (uint8_t)s;
        out[i + 1] = (uint8_t)(s >> 8);
        out[i + 2] = (uint8_t)(s >> 16);
        out[i + 3] = (uint8_t)(s >> 24);
    }
    out[esz - 1] &= 0xBFu;      /* one exponent bit down: a finite number */
}

/* The operands of the sweep, for the client to stream. */
class Operands : public cftr::Operands {
public:
    explicit Operands(uint8_t fmt) : esz_(formatSize(fmt)) {}
    virtual void element(uint8_t role, uint32_t index, uint8_t *out)
    {
        operand(role, index, esz_, out);
    }
    static uint8_t present() { return 7u; }   /* a, b and c */
private:
    uint8_t esz_;
};

/* The results, folded into a digest as they arrive and never stored.
 * Results::element's rule - an element arrives before its frame has
 * been checksummed - is honoured by construction: nothing here ACTS on
 * an element, and the digest is only read after run() has returned. */
class Digest : public Results {
public:
    explicit Digest(uint8_t fmt) : esz_(formatSize(fmt)), c_(crcBegin()),
                                   n_(0) {}
    virtual void element(uint32_t index, const uint8_t *in)
    {
        (void)index;
        c_ = crcUpdate(c_, in, esz_);
        n_++;
    }
    uint32_t value() const { return crcFinal(c_); }
    uint32_t count() const { return n_; }
private:
    uint8_t  esz_;
    uint32_t c_;
    uint32_t n_;
};

}  /* namespace replay */
}  /* namespace cftr */

#endif /* CFT_REMOTE_REPLAY_H_ */
