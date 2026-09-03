/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The tile's arithmetic, in C. Internal to libcft.
 *
 * This is a port of python/cft_golden/softfloat.py, which remains the
 * definition of correct. "Port" is the operative word: the control
 * flow, the order of the special cases and the names are deliberately
 * the same, so the two can be read side by side and a divergence shows
 * up as a structural difference rather than as a subtle one.
 *
 * The one place the two genuinely differ is operand alignment - Python
 * shifts exactly in unbounded integers, this bounds the shift and
 * carries a sticky bit. That reduction is argued in softfloat.c, and
 * it is checked rather than trusted: host/tests/diff_check.py replays
 * both implementations over the whole interesting input space, and
 * cft_conformance() replays the published vectors through this one.
 */

#ifndef CFT_SOFTFLOAT_H
#define CFT_SOFTFLOAT_H

#include <stddef.h>     /* size_t, for the reduction tree's index range */

#include "bigint.h"

typedef struct {
    const char *name;
    int      exp_w;      /* exponent field width */
    int      man_w;      /* trailing significand field width */
    int      width;      /* 1 + exp_w + man_w */
    int      prec;       /* man_w + 1, the hidden bit included */
    int      bias;
    int      emax;
    int      emin;
    uint32_t exp_mask;
} cft_fmt_desc;

/* Indexed by the precision code that MODE[11:8] carries and that
 * cft_format uses: 0 fp32, 1 fp64, 2 fp128, 3 fp256. */
extern const cft_fmt_desc cft_sf_formats[4];

/* Flags, matching rtl/cft_fpfma.sv, the FLAGS CSR and cft_exception. */
#define CFT_SF_INVALID    (1u << 0)
#define CFT_SF_DIVZERO    (1u << 1)
#define CFT_SF_OVERFLOW   (1u << 2)
#define CFT_SF_UNDERFLOW  (1u << 3)
#define CFT_SF_INEXACT    (1u << 4)

/* Rounding attributes: RISC-V frm, as the contract specifies. */
#define CFT_SF_RNE 0
#define CFT_SF_RTZ 1
#define CFT_SF_RDN 2
#define CFT_SF_RUP 3
#define CFT_SF_RMM 4

/* The SIXTH rounding DIRECTION, which is not an attribute:
 * roundTiesTowardZero, defined by IEEE 754-2019 9.5 for the augmented
 * arithmetic operations and for nothing else. Nearest, and an exact tie
 * takes "the one with smaller magnitude"; overflow still goes to an
 * infinity, which 9.5 states explicitly.
 *
 * cft_sf_round_pack accepts it; nothing that takes a cft_round does.
 * The value is deliberately outside the 3-bit MODE[14:12] field the
 * five attributes encode into, so it cannot be mistaken for one on a
 * wire, in a CSR, or in a vector set - and the API layer's own
 * range check (0..4) rejects it before it can be passed as one.
 * augmented.c is the only caller. */
#define CFT_SF_RTTZ 16

/* Opcodes. 15 and 28..255 are unassigned and answer with the canonical
 * quiet NaN and invalid - a defined result, because a host issuing an
 * opcode its device predates should see that in the flags rather than
 * receive a plausible number. */
#define CFT_SF_FMA       0
#define CFT_SF_ADD       1
#define CFT_SF_SUB       2
#define CFT_SF_MUL       3
#define CFT_SF_ABS       4
#define CFT_SF_NEG       5
#define CFT_SF_COPYSIGN  6
#define CFT_SF_MIN       7
#define CFT_SF_MAX       8
#define CFT_SF_MINNUM    9
#define CFT_SF_MAXNUM   10
#define CFT_SF_SELECT   11
#define CFT_SF_CMPLT    12
#define CFT_SF_CMPLE    13
#define CFT_SF_CMPEQ    14
#define CFT_SF_IAND     16
#define CFT_SF_IOR      17
#define CFT_SF_IXOR     18
#define CFT_SF_IADD     19
#define CFT_SF_ISUB     20
#define CFT_SF_ISHL     21
#define CFT_SF_ISHR     22
#define CFT_SF_ICMPLT   23

/* Reductions. n inputs, one output - a different calling convention
 * from everything above, which is why the API exposes them through
 * cft_reduce() rather than cft_run(). They share the opcode space so
 * the device's opcode field stays one field. */
#define CFT_SF_SUM      24
#define CFT_SF_DOT      25

/* Divide/sqrt seeds: quiet unary table lookups, mirrors of the
 * model's recip_seed/rsqrt_seed including the flush-at-input rule for
 * subnormal operands. divsqrt.c refines them to full precision. */
#define CFT_SF_RECIP_SEED 26
#define CFT_SF_RSQRT_SEED 27

/* Is `op` one of the assigned opcodes? Unassigned ones still compute -
 * see above - but cft_supports() answers with this. */
int cft_sf_op_assigned(int op);

/* Is `op` a reduction? Reductions are assigned, so op_assigned() says
 * yes, but they cannot be evaluated elementwise and cft_run() refuses
 * them on that basis. */
int cft_sf_is_reduction(int op);

/* The reduction tree over elements [lo, hi) of a (and b, for dot).
 *
 * The shape is the single thing this has to get right, and it is the
 * same shape python/cft_golden/reduce.py defines: split so the LEFT
 * child is the largest power of two strictly below the range length,
 * recurse, add. Not the floor midpoint - that was the first version
 * and is a different tree at every n that is not a power of two; see
 * the implementation for why it moved. Not a sequential accumulation,
 * and not a padded power-of-two tree - see that module for why padding
 * with +0.0 is not the identity it looks like.
 *
 * Recursion depth is ceil(log2(hi-lo)), so at most 64 frames for any
 * size a host can express.
 *
 * Returns 0, or 1 on an internal invariant failure. */
int cft_sf_reduce(const cft_fmt_desc *f, int op, int rnd,
                  const void *a, const void *b, size_t esz,
                  size_t lo, size_t hi,
                  cft_bn *out, uint32_t *flags);

/* The `parts` index ranges that are exact NODES of the reduction tree
 * over [0, n), for splitting a reduction across tiles.
 *
 * An arbitrary partition will not do: a partial result is only reusable
 * if its range is a node, and the even slicing used for elementwise
 * work generally is not one. Cutting the top log2(parts) levels gives
 * nodes, which is why parts must be a power of two.
 *
 * A node's SHAPE depends only on its length - the split is at the
 * largest power of two inside the range, wherever the range starts - so
 * a tile handed [lo, hi) computes the same tree the whole-array
 * reduction would have computed for that node, without being told where
 * it sits. Combining the partials with the same tree over `parts`
 * elements rebuilds the levels that were cut.
 *
 * Writes at most `cap` ranges and returns how many it produced. That
 * count is NOT bounded by `parts`: cutting the top levels of this tree
 * yields one extra range whenever n is a power of two plus a
 * remainder, so parts=4 gives five ranges at n = 5, 9, 17, 33 and so
 * on. Fewer than `parts` come back when n is too small to cut that far.
 * A caller must size its arrays from `cap`, not from `parts`, and must
 * not assume one range per tile.
 *
 * Mirrors cft_golden.reduce.canonical_ranges() EXCEPT that this one is
 * capped: it stops splitting when another pass would exceed `cap`,
 * where the model is unbounded. The two therefore differ once `parts`
 * reaches `cap` - at cap=64 and parts=64 the model returns 65 ranges
 * for n=65 and this returns 33. Both are valid canonical partitions
 * and both fold to the same answer; this one just uses fewer tiles
 * than it could. tests/reduce_parts_test.c checks the property, and
 * tests/reduce_check.py checks this function against the model. */
size_t cft_sf_canonical_ranges(size_t n, size_t parts,
                               size_t *lo_out, size_t *hi_out, size_t cap);

/* Which of a, b, c the opcode reads, as bits 1, 2, 4. The steering
 * makes ADD ignore b and MUL ignore c, so a caller may legitimately
 * pass NULL for those; anything an opcode does read must be there. */
unsigned cft_sf_op_operands(int op);

/* One element. Returns 0, or 1 on an internal invariant failure -
 * never on a caller error, which the API layer rejects first. */
int cft_sf_compute(const cft_fmt_desc *f, int op, int rnd,
                   const cft_bn *a, const cft_bn *b, const cft_bn *c,
                   cft_bn *out, uint32_t *flags);

/* ---------------------------------------------------------------
 * Pieces the library's own compositions build with (divsqrt.c).
 *
 * These exist so that composed operations round and build specials
 * through the SAME authority as everything else - a second
 * round_pack would be a second place for the contract to be wrong.
 * Still internal to libcft; nothing here is API.
 * --------------------------------------------------------------- */

/* Round the exact non-zero magnitude (m + eps) * 2^e into the format
 * under `rnd`, delivering inexact/underflow/overflow exactly as the
 * model's round_pack does. See the static sf_round_pack above its
 * definition for the m/sticky preconditions. */
int cft_sf_round_pack(const cft_fmt_desc *f, int sign, const cft_bn *m,
                      int e, int sticky, int rnd,
                      cft_bn *out, uint32_t *flags);

void cft_sf_qnan(const cft_fmt_desc *f, cft_bn *out);
void cft_sf_inf(const cft_fmt_desc *f, int sign, cft_bn *out);
void cft_sf_zero(const cft_fmt_desc *f, int sign, cft_bn *out);

#endif /* CFT_SOFTFLOAT_H */
