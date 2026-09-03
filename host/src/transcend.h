/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The transcendental set, internal surface. The public entry
 * points are in cft.h; what is here is the dispatch by index that the
 * conformance replay and the check harnesses use, plus the
 * instrumentation counters that make docs/TRANSCENDENTALS.md's
 * escalation numbers measurements rather than beliefs.
 *
 * Nothing here is CFT_API: the symbols exist for statically-linked
 * tools inside this repository and are not part of the ABI.
 */

#ifndef CFT_TRANSCEND_H
#define CFT_TRANSCEND_H

#include <stdint.h>

#include "../include/cft.h"

/* The canonical order: the ABI's, the vector sets', the model's
 * TRANSCEND_FNS, and cft_tr_name's. Phase 1's nine first, phase 2's
 * eleven after and phase 3's nine after those, and it never changes - a
 * name inserted rather than appended silently renumbers every committed
 * vector set. */
enum {
    CFT_TR_EXP = 0,
    CFT_TR_EXPM1,
    CFT_TR_EXP2,
    CFT_TR_LOG,
    CFT_TR_LOG1P,
    CFT_TR_LOG2,
    CFT_TR_LOG10,
    CFT_TR_POW,
    CFT_TR_HYPOT,
    /* phase 2 (ABI 0.4): the trigonometric functions whose argument
     * reduction is exact - x mod 2 on a dyadic operand for the forward
     * Pi-variants, and nothing at all for the inverses. */
    CFT_TR_SINPI,
    CFT_TR_COSPI,
    CFT_TR_TANPI,
    CFT_TR_ASIN,
    CFT_TR_ACOS,
    CFT_TR_ATAN,
    CFT_TR_ATAN2,
    CFT_TR_ASINPI,
    CFT_TR_ACOSPI,
    CFT_TR_ATANPI,
    CFT_TR_ATAN2PI,
    /* phase 3 (ABI 0.5): the radian trigonometry, whose argument
     * reduction against pi is the thing phase 2 was defined to exclude,
     * and the hyperbolics, which need no reduction and no new
     * constant at all. */
    CFT_TR_SIN,
    CFT_TR_COS,
    CFT_TR_TAN,
    CFT_TR_SINH,
    CFT_TR_COSH,
    CFT_TR_TANH,
    CFT_TR_ASINH,
    CFT_TR_ACOSH,
    CFT_TR_ATANH,
    CFT_TR_COUNT
};

/* The escalation cap's ceiling, shared with the model
 * (python/cft_golden/transcend.py PREC_CAP_CEILING). Both
 * implementations must give up in the same place, or they disagree
 * about which inputs are answerable. */
#define CFT_TR_PREC_CAP_CEILING 832

/* ---- the phase-3 argument reduction ------------------------------- *
 *
 * The widest window of 2/pi one reduction may read, in bits. It is the
 * cancellation allowance, and it is the number the reduction REFUSES
 * past: a window of W bits delivers a reduced argument to the working
 * precision as long as
 *
 *     W >= p + 2 + (bits of cancellation) + Wi + 10
 *
 * so 8192 provides for 7,006 bits of cancellation at fp256 and 7,478 at
 * fp64 (host/src/transcend.c derives both, docs/TRANSCENDENTALS.md
 * prints them). The measured worst case over every fp32 and fp64 binade
 * is 29 and 61 bits, and the counting argument puts fp256's near 256,
 * so the allowance is more than an order of magnitude clear of anything
 * expected - and a call that needed more would get CFT_ERR_INTERNAL
 * rather than a plausible sine.
 *
 * host/tools/gen_2opi.py reads this number: the stored constant is
 * (fp256's deepest window start) + this, so raising it here without
 * regenerating mp_2opi.h would read off the end of the array.
 * python/tests/test_mp_consts.py fails if the two disagree. */
#define CFT_TR_PH_WINDOW_MAX 8192

const char *cft_tr_name(int fn);
int         cft_tr_from_name(const char *s);
int         cft_tr_arity(int fn);

/* The same twenty operations by index, so a replayer does not need a
 * twenty-way switch of its own. */
cft_status cft_tr_apply(cft_device *dev, int fn, cft_format fmt,
                        cft_round rnd, const void *a, const void *b,
                        void *d, size_t n, uint32_t *flags_out);

extern uint64_t cft_tr_calls;        /* elements evaluated */
extern uint64_t cft_tr_ziv_calls;    /* elements that reached the loop */
extern uint64_t cft_tr_escalations;  /* precision raises inside it */
extern uint64_t cft_tr_max_prec;     /* deepest working precision used */
extern uint64_t cft_tr_exact;        /* elements decided exactly */
extern uint64_t cft_tr_neighbour;    /* elements decided by side */

/* Phase 3's reduction, instrumented the same way and for the same
 * reason: "how wide a window did it ever need" is a measurement in
 * docs/TRANSCENDENTALS.md rather than a belief. */
extern uint64_t cft_tr_reduce_calls;   /* arguments reduced mod pi/2 */
extern uint64_t cft_tr_reduce_widen;   /* window widenings inside them */
extern uint64_t cft_tr_max_window;     /* widest window used, in bits */
extern uint64_t cft_tr_max_cancel;     /* deepest cancellation seen, bits */

void cft_tr_reset_stats(void);

#endif /* CFT_TRANSCEND_H */
