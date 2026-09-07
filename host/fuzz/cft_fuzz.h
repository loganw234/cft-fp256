/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The interface a fuzz target implements, and the loop that drives it.
 * host/fuzz/README.md says why this engine exists rather than
 * libFuzzer's.
 */

#ifndef CFT_FUZZ_H
#define CFT_FUZZ_H

#include <stddef.h>
#include <stdint.h>

typedef struct {
    /* The target's name; the corpus and the crash directory default
     * to host/fuzz/corpus/<name> and host/fuzz/crashes/<name>. */
    const char *name;

    /* Called once before the loop. May be NULL. */
    void (*init)(void);

    /* One execution over one input. The input is read-only; anything
     * the target allocates it must free, because the loop runs in one
     * process and a leak is a fuzzer that dies of memory rather than
     * of a finding. */
    void (*run)(const uint8_t *data, size_t len);

    /* Structure-aware repair, called on a mutated input before `run`.
     * A protocol with a length field and a checksum rejects essentially
     * every random mutation at its first check, and then the fuzzer is
     * only ever testing that check; this hook puts the input back in
     * shape - most of the time, not always, because the reject paths
     * are worth reaching too. Returns the (possibly changed) length.
     * May be NULL. */
    size_t (*fixup)(uint8_t *data, size_t len, size_t cap, uint64_t *rng);

    /* Inputs longer than this are trimmed. 0 means the engine's
     * default of 65536. */
    size_t max_len;
} cft_fuzz_target;

int cft_fuzz_main(int argc, char **argv, const cft_fuzz_target *t);

/* The coverage map, so a target that wants to can look at it. Written
 * by __sanitizer_cov_trace_pc in cft_fuzz.c, which is the ONE
 * translation unit built without -fsanitize-coverage - instrumenting
 * the callback recurses until the stack ends. */
#define CFT_FUZZ_MAP_BITS 15
#define CFT_FUZZ_MAP_SIZE (1u << CFT_FUZZ_MAP_BITS)
extern uint8_t cft_fuzz_map[CFT_FUZZ_MAP_SIZE];

#endif /* CFT_FUZZ_H */
