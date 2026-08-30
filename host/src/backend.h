/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * What a hardware backend owes the rest of libcft. Internal.
 *
 * The public API takes host pointers and an arbitrary element count.
 * Everything between that and a compute unit - buffer staging, beat
 * padding, splitting the work across tiles, OR-ing four sets of sticky
 * registers back into one answer - lives behind this interface, so
 * device.c never learns that tiles exist and neither does a caller.
 *
 * Status values are cft_status passed as int, which keeps this header
 * independent of the public one and lets the C++ side include it
 * without dragging in anything else.
 */

#ifndef CFT_BACKEND_H
#define CFT_BACKEND_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Open an artifact. On success fills every out-parameter:
 *
 *   format_mask     CAPS[3:0]  - precisions this bitstream carries
 *   op_groups       CAPS[15:8] - opcode groups it implements
 *   tiles           compute units found
 *   version         the VERSION register, the hardware contract level
 *   flags_readable  0 if the runtime cannot read the status registers,
 *                   in which case exception flags from this device are
 *                   not to be trusted and cft_get_caps says so
 */
int  cftx_open(const char *artifact, int index, void **out,
               uint32_t *format_mask, uint32_t *op_groups,
               uint32_t *tiles, uint32_t *version, int *flags_readable);

void cftx_close(void *hw);

/* Elementwise over n elements, partitioned across every tile. flags is
 * the OR of all tiles' sticky words; bus is the OR of their fault
 * registers and is only meaningful when the return is
 * CFT_ERR_BUS_FAULT. */
int  cftx_run(void *hw, int op, int fmt, int rnd,
              const void *a, const void *b, const void *c, void *d,
              size_t n, uint32_t *flags, uint32_t *bus);

/* Reduce index ranges of `a`, writing ONE element per range into
 * `partials`.
 *
 * `nranges` MAY EXCEED THE TILE COUNT, and routinely does - the tree's
 * canonical cut of [0, n) into at most `parts` nodes needs one extra
 * range whenever n is a power of two plus a remainder, so four tiles
 * get five ranges at n = 5, 9, 17, 33, 65 and so on. The backend runs
 * them in waves and must re-stage a tile's operands before each wave
 * rather than staging every range up front, or a later range silently
 * overwrites an earlier one's data before it has been computed.
 *
 * The caller folds the partials with the reduction tree, and the ranges
 * must be canonical NODES of that tree for the fold to be valid - which
 * is why the caller computes them (cft_sf_canonical_ranges) rather than
 * this function inventing a split. The division of labour is the same
 * one the rest of this header draws: the tree lives in C where the
 * contract is defined, and the backend only knows how to make tiles
 * run.
 *
 * A range's SHAPE depends only on its length, so a tile handed
 * [lo, hi) computes exactly the subtree the whole-array reduction would
 * have, without being told where the range sits.
 *
 * flags is the OR across every tile used; bus likewise, and only
 * meaningful on CFT_ERR_BUS_FAULT. */
int  cftx_reduce(void *hw, int op, int fmt, int rnd, const void *a,
                 const size_t *lo, const size_t *hi, size_t nranges,
                 void *partials, uint32_t *flags, uint32_t *bus);

/* The message from the most recent failure, or "". Static storage,
 * overwritten by the next one. XRT's exceptions carry the only
 * explanation of most device failures that anybody will ever get, and
 * throwing that away to return a bare enum would make a bad night on
 * the bench considerably worse. */
const char *cftx_last_error(void);

#ifdef __cplusplus
}  /* extern "C" */
#endif

#endif /* CFT_BACKEND_H */
