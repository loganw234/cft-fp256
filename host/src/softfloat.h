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

/* Opcodes. 15 and 24..255 are unassigned and answer with the canonical
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

/* Is `op` one of the assigned opcodes? Unassigned ones still compute -
 * see above - but cft_supports() answers with this. */
int cft_sf_op_assigned(int op);

/* Which of a, b, c the opcode reads, as bits 1, 2, 4. The steering
 * makes ADD ignore b and MUL ignore c, so a caller may legitimately
 * pass NULL for those; anything an opcode does read must be there. */
unsigned cft_sf_op_operands(int op);

/* One element. Returns 0, or 1 on an internal invariant failure -
 * never on a caller error, which the API layer rejects first. */
int cft_sf_compute(const cft_fmt_desc *f, int op, int rnd,
                   const cft_bn *a, const cft_bn *b, const cft_bn *c,
                   cft_bn *out, uint32_t *flags);

#endif /* CFT_SOFTFLOAT_H */
