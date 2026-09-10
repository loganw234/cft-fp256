/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Operands read out of program memory rather than SRAM.
 *
 * On an AVR a `const uint8_t x[] PROGMEM` lives in flash and an
 * ordinary pointer dereference does not reach it - that is the split
 * address space, and it is why an Uno with 2 kB of SRAM can carry
 * kilobytes of constants. memcpy_P is the read that does reach it, and
 * every Arduino core provides it (on the 32-bit cores flash is in the
 * same address space and it is a plain memcpy, so the same source
 * compiles everywhere).
 *
 * This matters here more than it usually does. A binary256 constant is
 * thirty-two bytes; three operands of it are ninety-six, which is five
 * per cent of a Nano's whole memory for ONE element. Kept in flash they
 * cost nothing at run time, and the streaming client never needs them
 * anywhere else: it asks for one element, checksums it, asks again,
 * sends it.
 */

#ifndef CFT_REMOTE_FLASH_H_
#define CFT_REMOTE_FLASH_H_

#include "cft_remote.h"

#if defined(ARDUINO)

namespace cftr {

/* Up to three dense arrays of n elements each, in program memory. A
 * null pointer is an absent operand, exactly as with RamOperands. */
class FlashOperands : public Operands {
public:
    FlashOperands(uint8_t fmt, const void *a, const void *b = 0,
                  const void *c = 0)
    {
        esz_     = formatSize(fmt);
        p_[0]    = (const uint8_t *)a;
        p_[1]    = (const uint8_t *)b;
        p_[2]    = (const uint8_t *)c;
        present_ = (uint8_t)((a ? 1u : 0u) | (b ? 2u : 0u) | (c ? 4u : 0u));
    }
    virtual void element(uint8_t role, uint32_t index, uint8_t *out)
    {
        const uint8_t *p = (role < 3) ? p_[role] : 0;
        if (p)
            memcpy_P(out, p + (uint32_t)index * esz_, esz_);
        else
            memset(out, 0, esz_);
    }
    uint8_t present() const { return present_; }
private:
    const uint8_t *p_[3];
    uint8_t esz_, present_;
};

/* One element from flash, repeated: the operand a whole run shares.
 * `count` elements of the same thirty-two bytes cost thirty-two bytes
 * of flash and nothing at all of SRAM. */
class FlashScalar : public Operands {
public:
    FlashScalar(uint8_t fmt, const void *a, const void *b = 0,
                const void *c = 0)
    {
        esz_     = formatSize(fmt);
        p_[0]    = (const uint8_t *)a;
        p_[1]    = (const uint8_t *)b;
        p_[2]    = (const uint8_t *)c;
        present_ = (uint8_t)((a ? 1u : 0u) | (b ? 2u : 0u) | (c ? 4u : 0u));
    }
    virtual void element(uint8_t role, uint32_t index, uint8_t *out)
    {
        const uint8_t *p = (role < 3) ? p_[role] : 0;
        (void)index;
        if (p)
            memcpy_P(out, p, esz_);
        else
            memset(out, 0, esz_);
    }
    uint8_t present() const { return present_; }
private:
    const uint8_t *p_[3];
    uint8_t esz_, present_;
};

}  /* namespace cftr */

#endif /* ARDUINO */
#endif /* CFT_REMOTE_FLASH_H_ */
