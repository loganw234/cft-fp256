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
