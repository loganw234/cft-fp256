# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The sequencer header's `flags` word: one bit, one name, one place.

Identity needs one definition, and this word did not have one. On
2026-09-11 the list of defined flags was written out by hand in seven
places, and they had drifted to three different revisions at once:

    revision 4, three flags   python/cft_golden/seq.py
    revision 3, two flags     python/cft_golden/asm.py
                              host/src/program.c
                              host/tools/cft-asm.c (twice)
                              host/tools/positive-run.c
    revision 2, one flag      docs/HOSTAPI.md ("flags[31:1]", and it
                              called itself the list "in full")

Two of those are in this package, so the golden model contradicted
itself about which flags exist. That is the failure this module ends.

WHAT IS SHARED AND WHAT IS NOT. The bit NUMBERING is canonical - a flag
means the same bit everywhere or images do not interchange, which is the
product. The SUBSET a layer accepts is not: the model implements R8 and
the assembler cannot yet emit it, and that difference is real. So each
consumer declares its own `FLAGS_KNOWN` from the names below and renders
its refusal with `names()`, which is why a message can no longer name a
flag list its own mask disagrees with.

host/include/cft_seq_flags.h is generated from this file by
python/gen_seq_flags.py, so the C library and the tools read the same
numbering rather than a fourth copy of it.
"""

FLAG_BANK_EXT = 1 << 0
FLAG_SCRATCH_IO = 1 << 1
FLAG_SCRATCH_STRICT = 1 << 2

# Bit -> name -> the C macro that must carry the same number. The C
# column is here rather than in the generator so that adding a flag is
# one edit in one file, which is the whole point.
FLAG_TABLE = (
    (FLAG_BANK_EXT,       "BANK_EXT",       "CFT_PROG_FLAG_BANK_EXT"),
    (FLAG_SCRATCH_IO,     "SCRATCH_IO",     "CFT_PROG_FLAG_SCRATCH_IO"),
    (FLAG_SCRATCH_STRICT, "SCRATCH_STRICT", "CFT_PROG_FLAG_SCRATCH_STRICT"),
)

FLAG_NAMES = {bit: name for bit, name, _c in FLAG_TABLE}

# Every bit this project has ever defined. NOT what any one layer
# accepts - see the note above, and do not reach for this as a mask.
FLAGS_DEFINED = 0
for _bit in FLAG_NAMES:
    FLAGS_DEFINED |= _bit


def names(mask):
    """The flag names in `mask`, low bit first, as English.

    For a refusal that has to say which flags it does know. Derived from
    the caller's own mask, so a layer that accepts two flags cannot
    print the names of three.
    """
    have = [FLAG_NAMES[bit] for bit, _n, _c in FLAG_TABLE if mask & bit]
    if not have:
        return "none"
    if len(have) == 1:
        return have[0]
    return ", ".join(have[:-1]) + " and " + have[-1]
