/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The phase-1 transcendental set, internal surface. The public entry
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
 * TRANSCEND_FNS, and cft_tr_name's. */
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
    CFT_TR_COUNT
};

/* The escalation cap's ceiling, shared with the model
 * (python/cft_golden/transcend.py PREC_CAP_CEILING). Both
 * implementations must give up in the same place, or they disagree
 * about which inputs are answerable. */
#define CFT_TR_PREC_CAP_CEILING 832

const char *cft_tr_name(int fn);
int         cft_tr_from_name(const char *s);
int         cft_tr_arity(int fn);

/* The same nine operations by index, so a replayer does not need a
 * nine-way switch of its own. */
cft_status cft_tr_apply(cft_device *dev, int fn, cft_format fmt,
                        cft_round rnd, const void *a, const void *b,
                        void *d, size_t n, uint32_t *flags_out);

extern uint64_t cft_tr_calls;        /* elements evaluated */
extern uint64_t cft_tr_ziv_calls;    /* elements that reached the loop */
extern uint64_t cft_tr_escalations;  /* precision raises inside it */
extern uint64_t cft_tr_max_prec;     /* deepest working precision used */
extern uint64_t cft_tr_exact;        /* elements decided exactly */
extern uint64_t cft_tr_neighbour;    /* elements decided by side */

void cft_tr_reset_stats(void);

#endif /* CFT_TRANSCEND_H */
