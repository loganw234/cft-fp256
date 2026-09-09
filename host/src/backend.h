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

/* The sequencer capacities a backend publishes AND enforces.
 *
 * One struct rather than four more out-parameters, because both
 * backends fill all four from one place (a CAPS register read, a HELLO
 * caps block) and device.c copies them straight into cft_caps.
 *
 * The units are the program header's, so a comparison against a
 * header field needs no conversion; CAPS carries log2 of the first
 * three and the decode happens in the XRT backend, at the register.
 *
 * ZERO IS UNKNOWN in every field, and program.c enforces nothing
 * against an unknown - see cft_caps in the public header. */
typedef struct cft_seq_caps {
    uint32_t max_deposits;
    uint32_t max_insns;
    uint32_t max_consts;   /* addressable, not the header's n_consts */
    uint32_t features;     /* CAPS[7:4] in bits 3:0, CAPS[31:28] in 7:4,
                            * CAPS2[7:4] in 11:8 */
    uint32_t max_scratch;  /* scratch slots a lane, CAPS2[3:0] as log2
                            * (revision 3, R4). Zero is unknown here as
                            * everywhere else in this struct */
} cft_seq_caps;

/* Open an artifact. On success fills every out-parameter:
 *
 *   format_mask     CAPS[3:0]  - precisions this bitstream carries
 *   op_groups       CAPS[15:8] - opcode groups it implements
 *   tiles           compute units found
 *   version         the VERSION register, the hardware contract level
 *   flags_readable  0 if the runtime cannot read the status registers,
 *                   in which case exception flags from this device are
 *                   not to be trusted and cft_get_caps says so
 *   seq             CAPS[7:4] and CAPS[27:16] decoded - the sequencer
 *                   capacities this device will accept a program
 *                   against, which the loader then holds it to
 */
int  cftx_open(const char *artifact, int index, void **out,
               uint32_t *format_mask, uint32_t *op_groups,
               uint32_t *tiles, uint32_t *version, int *flags_readable,
               cft_seq_caps *seq);

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

/* The per-run DATA a sequencer program carries beside its operands.
 *
 * One struct rather than six more positional arguments, for the reason
 * cft_run_args exists in the public header: revision 2 added two of
 * them, revision 3 added four, and a backend signature that grows by
 * an argument a round is one every backend has to be edited to ignore.
 * Everything here has already been held to the program's own header by
 * program.c, so a backend may take the byte counts as given.
 *
 * bank         NULL for a program that carries its own constants, and
 *              the caller's dense array of `n_consts` format-width
 *              values for a BANK_EXT one (revision 2, R3) whose image
 *              has no constant section at all
 * scratch_in   NULL, or n * n_scratch_in format-width values,
 *              LANE-MAJOR and dense - lane i's slot s is element
 *              i * n_scratch_in + s (revision 3, R5) - preloaded into
 *              the first slots of each lane's scratch before its first
 *              instruction
 * scratch_out  NULL, or n * n_scratch_out likewise, written after each
 *              lane's last deposit
 * n_scratch_*  the per-lane slot counts the two blocks are shaped by,
 *              which a backend that CHUNKS the run needs: a chunk of k
 *              lanes starting at lane `off` carries the elements
 *              [off * n_scratch_in, (off + k) * n_scratch_in), and a
 *              transport that sliced the block by bytes alone would
 *              hand every chunk the first lanes' slots
 */
typedef struct cft_seq_run_io {
    const void *bank;        size_t bank_bytes;
    const void *scratch_in;  size_t scratch_in_bytes;
    void       *scratch_out; size_t scratch_out_bytes;
    uint32_t    n_scratch_in, n_scratch_out;
} cft_seq_run_io;

/* Run a sequencer program (docs/SEQUENCER.md) on ONE compute unit.
 *
 * `image` is the exact byte image cft_program_load validated, DMA'd
 * into the tile whole rather than reassembled from the parsed form -
 * so what executes is what was loaded, and a readback can attest it.
 * `io` is the per-run data above.
 * `max_deposits` comes from the image's header and shapes `deposits`
 * at n * max_deposits elements; `counts` may be NULL, though the tile
 * writes the counts regardless and the backend supplies a buffer for
 * them either way.
 *
 * flags is the run's sticky IEEE word. bus carries STATUS: bits 0..2
 * only on CFT_ERR_BUS_FAULT, as everywhere else in this header, and
 * CFT_STATUS_DEPOSIT_OVERFLOW (bit 4) on success - which is a report
 * rather than an error, because what fit is correct.
 *
 * ONE compute unit, deliberately. See the note in the implementation
 * beside cftx_run's partitioning: an elementwise element depends on
 * its own index alone, and a sequencer lane does too - but the early
 * exit is a CROSS-LANE condition, so splitting lanes across tiles is
 * a claim about P3 that wants its own fuzz before it ships. */
int  cftx_program_run(void *hw, int fmt, const void *image,
                      size_t image_bytes,
                      const cft_seq_run_io *io,
                      uint32_t max_deposits,
                      const void *a, const void *b, const void *c,
                      void *deposits, uint32_t *counts, size_t n,
                      uint32_t *flags, uint32_t *bus);

/* The backend handle behind a device, or NULL if it was opened without
 * an artifact and is therefore the software one.
 *
 * The other direction to everything above: device.c owns struct
 * cft_device, and program.c has to ask it which executor a program
 * belongs to. Declared here because here is where the two sides
 * already meet, and a bare extern in a .c file is how a signature
 * drifts out of step with its definition. */
struct cft_device;
void *cft_device_backend(const struct cft_device *dev);

/* The same seam again, for the capacities rather than the handle.
 *
 * device.c owns struct cft_device and fills these at open - from the
 * CAPS register, from the HELLO caps block, or from cft_sw_seq_caps()
 * below for a software handle. program.c reads them back to hold a
 * program image to the device it was loaded for, so that the caps a
 * backend REPORTS and the caps it ENFORCES are the same four numbers
 * by construction and not by agreement.
 *
 * cft_sw_seq_caps lives in program.c, which is where the software
 * backend's limits are enforced. */
void cft_device_seq_caps(const struct cft_device *dev, cft_seq_caps *out);
void cft_sw_seq_caps(cft_seq_caps *out);

/* This library's own last-error slot, behind cft_last_error(). For
 * refusals libcft makes WITHOUT reaching a device backend - the only
 * one today is a program past a device's published capacity - so that
 * a caller is told which cap and by how much rather than only that
 * something was unsupported. Cleared the moment anything reaches a
 * backend, so it never explains someone else's failure.
 *
 * cft_seq_cap_refusal formats one of those and returns the status to
 * return (CFT_ERR_UNSUPPORTED as int, since this header stays
 * independent of the public one): `field` is the program's, `units`
 * says what the device's number counts, and `caps_field` is the
 * cft_caps member that would have answered in advance. */
void cft_set_error(const char *fmt, ...);
int  cft_seq_cap_refusal(const char *field, unsigned long asked,
                         unsigned long cap, const char *units,
                         const char *caps_field);

/* The message from the most recent failure, or "". Static storage,
 * overwritten by the next one. XRT's exceptions carry the only
 * explanation of most device failures that anybody will ever get, and
 * throwing that away to return a bare enum would make a bad night on
 * the bench considerably worse. */
const char *cftx_last_error(void);

/* ====================================================================
 * The remote backend (docs/REMOTE.md), beside the XRT one.
 *
 * Its cftr_ functions have the same shapes as the cftx_ ones above and
 * are declared in remote.h, together with the wire protocol they
 * speak. What this block adds is the two questions the rest of the
 * library asks of "the backend" without caring which one it is:
 * program.c needs to hand a program run to whichever device backend
 * the handle has, and divsqrt.c needs to know whether there is one.
 * cft_device_backend() above answers the second for both; this
 * dispatcher answers the first, so that neither file names a backend.
 *
 * Returns the backend's status, or CFT_ERR_INTERNAL (as int) for a
 * handle that has no device backend - which program.c never asks
 * about, since it checks cft_device_backend() first.
 * ==================================================================== */
int cft_backend_program_run(struct cft_device *dev, int fmt,
                            const void *image, size_t image_bytes,
                            const cft_seq_run_io *io,
                            uint32_t max_deposits,
                            const void *a, const void *b, const void *c,
                            void *deposits, uint32_t *counts, size_t n,
                            uint32_t *flags, uint32_t *bus);
/* ============================ end of the remote block ============== */

#ifdef __cplusplus
}  /* extern "C" */
#endif

#endif /* CFT_BACKEND_H */
