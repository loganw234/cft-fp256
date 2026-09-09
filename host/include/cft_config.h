/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * libcft build profile - what a translation unit of this library
 * contains, decided at compile time.
 *
 * The library exists to put the same bits everywhere, and "everywhere"
 * came to include parts with 32 KB of flash and 2 KB of RAM. The
 * arithmetic already runs there unchanged: it is integer code over
 * 32-bit limbs with no floating-point dependence and no platform
 * conditional. What does not fit is the SURROUNDING library - a 117 KB
 * table of 2/pi for the trigonometric argument reduction, a sequencer,
 * a file-reading conformance replay, a socket backend - and the
 * intermediate width the widest format demands.
 *
 * So this header names those pieces, one macro each, and one profile
 * macro (CFT_TINY) that turns on the set an 8-bit part needs. Nothing
 * here has any effect on the DEFAULT build: with no macro defined the
 * values below are exactly what the library had before this file
 * existed, and every existing gate compiles the same code it did.
 *
 * These are BUILD-TIME choices about what is present, never run-time
 * choices about what an operation computes. An operation that is
 * present computes what the golden model says and what the vector sets
 * record, at every profile; one that is absent is absent at link time,
 * which is a message a caller can act on. There is no configuration in
 * this file that changes one bit of one answer - and
 * bindings/arduino/loopback replays the published vectors through the
 * reduced profiles to keep that honest rather than merely intended.
 *
 * The profiles this repository builds and checks (docs/EMBEDDED.md):
 *
 *   default            everything. Hosts, and the 32-bit boards
 *                      (RP2040, ESP32) which have the flash for it.
 *   CFT_TINY           fp32 and fp64, the elementwise opcodes, the
 *                      reductions, div/sqrt, clause 5, 9.5 and 9.6.
 *                      No transcendentals, no sequencer, no character
 *                      conversions, no formatOf, no sockets, no
 *                      file-based conformance replay. ATmega328P and
 *                      ATmega2560.
 *   CFT_TINY +         the same, plus fp128. Measured on the Mega,
 *   CFT_MAX_FORMAT=2   where the 8 KB of RAM is the binding limit.
 */

#ifndef CFT_CONFIG_H
#define CFT_CONFIG_H

/* ---------------------------------------------------------------
 * The profile a target picks for itself
 *
 * An Arduino build compiles a library with the core's own flags and
 * gives the library no way to add one per board. So the two things
 * that are true of EVERY Arduino target are decided here rather than
 * on a command line nobody can reach: there is no Berkeley socket
 * layer to put the cft:// backend on, and no directory of vector sets
 * for cft_conformance() to open (the sets reach a board over the wire
 * instead - host/tools/serial_replay.py). And on an 8-bit AVR, where
 * the whole of RAM is smaller than one fp256 reduction vector, the
 * profile is CFT_TINY.
 *
 * ARDUINO is defined by every Arduino core; __AVR__ by avr-gcc. A
 * caller who wants something else defines CFT_NO_AUTO_PROFILE and
 * says what they want - and then owns the question of whether it fits,
 * which is a question docs/EMBEDDED.md answers with numbers for the
 * profiles that are actually built here.
 * --------------------------------------------------------------- */
#if defined(ARDUINO) && !defined(CFT_NO_AUTO_PROFILE)
#  ifndef CFT_NO_REMOTE
#    define CFT_NO_REMOTE 1
#  endif
#  ifndef CFT_NO_CONFORMANCE
#    define CFT_NO_CONFORMANCE 1
#  endif
#  if defined(__AVR__) && !defined(CFT_TINY)
#    define CFT_TINY 1
#  endif
#endif

/* ---------------------------------------------------------------
 * CFT_TINY - the small-target profile
 *
 * A single macro, because a caller on an 8-bit part should not have to
 * know which six things do not fit. Each member can still be set (or
 * left unset) on its own: the block below only supplies a default, so
 * -DCFT_TINY -UCFT_NO_CHARS is a profile with the decimal conversions
 * back in, and it is the caller's job to check that it links.
 * --------------------------------------------------------------- */
#ifdef CFT_TINY
#  ifndef CFT_NO_REMOTE
#    define CFT_NO_REMOTE 1
#  endif
#  ifndef CFT_NO_CONFORMANCE
#    define CFT_NO_CONFORMANCE 1
#  endif
#  ifndef CFT_NO_TRANSCEND
#    define CFT_NO_TRANSCEND 1
#  endif
#  ifndef CFT_NO_PROGRAM
#    define CFT_NO_PROGRAM 1
#  endif
#  ifndef CFT_NO_CHARS
#    define CFT_NO_CHARS 1
#  endif
#  ifndef CFT_NO_FORMATOF
#    define CFT_NO_FORMATOF 1
#  endif
#  ifndef CFT_NO_GETENV
#    define CFT_NO_GETENV 1
#  endif
#  ifndef CFT_MAX_FORMAT
#    define CFT_MAX_FORMAT 1
#  endif
#endif

/* ---------------------------------------------------------------
 * CFT_MAX_FORMAT - the widest format this build carries
 *
 * 0 fp32, 1 fp64, 2 fp128, 3 fp256; the same numbering cft_format
 * uses, so the value IS the highest cft_format the library accepts.
 * Default 3, which is every format and what the library has always
 * built.
 *
 * The arithmetic itself is width-generic - one code path serves all
 * four formats - so narrowing this saves almost no FLASH. What it
 * saves is RAM: CFT_BN_LIMBS below is sized from it, and cft_bn is the
 * struct every intermediate is held in.
 *
 * A format above the ceiling is refused with CFT_ERR_UNSUPPORTED and
 * is absent from cft_caps.format_mask, so a caller finds out by
 * asking rather than by getting a wrong answer.
 * --------------------------------------------------------------- */
#ifndef CFT_MAX_FORMAT
#define CFT_MAX_FORMAT 3
#endif

#if CFT_MAX_FORMAT < 0 || CFT_MAX_FORMAT > 3
#error "CFT_MAX_FORMAT must be 0 (fp32), 1 (fp64), 2 (fp128) or 3 (fp256)"
#endif

/* ---------------------------------------------------------------
 * How wide an `int` the chosen ceiling needs
 *
 * softfloat.c holds exponents in `int`, and `int` is SIXTEEN bits on
 * an 8-bit AVR. That is fine for two of the four formats and fatal for
 * the other two, and the difference is arithmetic rather than opinion.
 *
 * An unpacked significand is an integer whose least significant bit
 * has weight 2^e, so sf_unpack gives e in [emin - (p-1), emax - (p-1)].
 * The fused multiply-add adds two of them - `ep = ua.e + ub.e` - which
 * is the widest exponent quantity in the library:
 *
 *              emin - (p-1)   2 * that     fits int16?
 *   fp32            -149          -298     yes, 100x over
 *   fp64          -1,074        -2,148     yes, 15x over
 *   fp128        -16,494       -32,988     NO, and by 220
 *   fp256       -262,378      -524,756     no, by a factor of 16
 *
 * So binary128 on a 16-bit int is not a tight fit that might work: the
 * very first line of a subnormal-times-subnormal multiply wraps.
 * Widening every exponent local to int32_t would fix it and would cost
 * an 8-bit part two extra bytes and two extra instructions on each of
 * them, for a format that would take an ATmega most of a second an
 * element - so the ceiling is refused here instead, by the compiler,
 * with the number that refuses it. docs/EMBEDDED.md carries the same
 * table.
 *
 * The check asks for TWICE the span, because `ep` is not the end of
 * it: VEp - VEc and be - k are built from it and reach about 1.5x.
 * The preprocessor evaluates this at full width whatever the target's
 * int is, which is exactly what makes it able to answer the question.
 * --------------------------------------------------------------- */
#include <limits.h>

#if   CFT_MAX_FORMAT == 0
#define CFT_EXP_SPAN 298L
#elif CFT_MAX_FORMAT == 1
#define CFT_EXP_SPAN 2148L
#elif CFT_MAX_FORMAT == 2
#define CFT_EXP_SPAN 32988L
#else
#define CFT_EXP_SPAN 524756L
#endif

#if INT_MAX < 2 * CFT_EXP_SPAN
#error "this target's int is too narrow for CFT_MAX_FORMAT: binary128 \
needs an int that holds +-32988 and binary256 one that holds +-524756, \
which a 16-bit int does not. Lower CFT_MAX_FORMAT (1 is fp32 and fp64, \
which fit a 16-bit int fifteen times over) - see cft_config.h."
#endif

/* The format mask a device of this build publishes: every format up to
 * and including the ceiling. */
#define CFT_FORMAT_MASK_BUILD ((uint32_t)((1u << (CFT_MAX_FORMAT + 1)) - 1u))

/* The two things that can be wrong with a cft_format argument, and
 * they are not the same thing.
 *
 * OUT_OF_RANGE is "that is not one of the four interchange formats",
 * which is a caller error and always has been: CFT_ERR_INVALID_ARGUMENT.
 * It does not move with the profile - cft_format_size(CFT_FP256) is 32
 * bytes on every build, because that is a fact about binary256 and not
 * about this library.
 *
 * ABSENT is "that IS a format, and this build does not carry it":
 * CFT_ERR_UNSUPPORTED, the same answer a device whose bitstream lacks
 * a format gives through cft_caps.format_mask. At the default profile
 * the test is `(f) > 3 && (f) <= 3`, which is false for every value, so
 * a default build compiles exactly the code it compiled before this
 * file existed. */
#define CFT_FMT_OUT_OF_RANGE(f) ((int)(f) < 0 || (int)(f) > 3)
#define CFT_FMT_ABSENT(f) ((int)(f) > CFT_MAX_FORMAT && (int)(f) <= 3)

/* ---------------------------------------------------------------
 * CFT_BN_LIMBS - the fixed-width integer container, in 32-bit limbs
 *
 * bigint.h states the requirement: the widest intermediate any
 * operation produces is the near-case fused multiply-add's addend
 * alignment at about 5p + 3 bits. That is
 *
 *     fp32    p=24    123 bits     4 limbs
 *     fp64    p=53    268 bits     9 limbs
 *     fp128   p=113   568 bits    18 limbs
 *     fp256   p=237  1188 bits    38 limbs
 *
 * and fp256's 64 limbs are 1.7x its requirement, which is the margin
 * the library has always carried.
 *
 * On a part with two kilobytes of RAM that margin is not affordable,
 * and it is not free: cft_bn is the struct every intermediate is held
 * in, so a call's stack is roughly linear in it. Measured on an
 * ATmega328P (avr-gcc -Os -fstack-usage; cft_run plus cft_sf_compute,
 * which is where sf_fma inlines):
 *
 *    limbs   sizeof(cft_bn)   bits   fp64 cft_run + compute
 *        8              34     256      630 bytes
 *        9              38     288      686
 *       10              42     320      742
 *       12              50     384      854
 *       16              66     512    1,072
 *
 * So the narrow profiles take the REQUIREMENT rounded up to a whole
 * limb and no more: 9 at fp64, 18 at fp128. That is a deliberate
 * asymmetry with fp256's 64, and the reason is which failure each
 * shortage produces. Too few limbs is loud - bigint.c returns 1 from
 * every operation that would not fit, softfloat.c turns that into
 * CFT_ERR_INTERNAL, and a replay reports it as a refusal on the first
 * case that needs the width. Too little STACK is silent: it writes
 * through the top of RAM and the part carries on. Given one number to
 * spend, it goes on the stack.
 *
 * Note that 8 limbs - 256 bits, BELOW the bound - also replays every
 * published fp32 and fp64 case without a refusal. It is not the value
 * here, and that is the point of having a bound: the sets are a sample
 * of the input space and 269 bits is a statement about all of it.
 *
 * Checked rather than argued, either way: bindings/arduino/loopback
 * replays the fp32 and fp64 sets through the CFT_TINY profile at 9,
 * and the fp128 sets through the fp128 profile at 18.
 * --------------------------------------------------------------- */
#ifndef CFT_BN_LIMBS
#  if CFT_MAX_FORMAT >= 3
#    define CFT_BN_LIMBS 64
#  elif CFT_MAX_FORMAT == 2
#    define CFT_BN_LIMBS 18
#  else
#    define CFT_BN_LIMBS 9
#  endif
#endif

/* ---------------------------------------------------------------
 * CFT_CHUNK - how many elements a composed operation works on at once
 *
 * divsqrt.c and clause5.c reach their answers by issuing passes over
 * the caller's array, and they hold scratch for those passes: twelve
 * lane buffers plus six small arrays in divsqrt's case. The size is
 * deliberately FIXED rather than proportional to n - that is what
 * keeps cft_div of a million elements from allocating a million
 * elements of scratch - and 4096 is the number it has always been.
 *
 * 4096 is also 393 KB of scratch at binary64 and a megabyte and a half
 * at binary256, which is more RAM than any part here has: on a Pico
 * every cft_div would answer CFT_ERR_OUT_OF_MEMORY, and on an ATmega
 * every one would. So it is a build choice, and the profiles pick a
 * value their part can hold. It changes no answer: a chunk boundary is
 * where the loop reloads its slice, and the arithmetic inside is per
 * element. The published vectors are replayed at CFT_CHUNK 8 through
 * bindings/arduino/loopback to keep that a measurement rather than an
 * argument.
 *
 * Bytes of scratch, at the worst case (divsqrt, twelve buffers plus
 * about 12 bytes an element of bookkeeping):
 *
 *   CFT_CHUNK   fp32    fp64    fp128   fp256
 *          8     432     624    1,008   1,776
 *         32   1,728   2,496    4,032   7,104
 *         64   3,456   4,992    8,064  14,208
 *       4096  221,184 319,488  516,096 917,504
 * --------------------------------------------------------------- */
#ifndef CFT_CHUNK
#  ifdef CFT_TINY
#    define CFT_CHUNK 8
#  elif defined(ARDUINO)
#    define CFT_CHUNK 32
#  else
#    define CFT_CHUNK 4096
#  endif
#endif

#if CFT_CHUNK < 1
#error "CFT_CHUNK must be at least 1 element"
#endif

/* ---------------------------------------------------------------
 * CFT_ERRMSG_MAX - the library's own last-error slot, in bytes
 *
 * cft_last_error() returns this buffer. Its one producer in a build
 * with no device backend is cft_program_load's capacity refusal, which
 * CFT_NO_PROGRAM removes - so the tiny profile keeps the empty string
 * the function must still return and drops both the 320-byte buffer
 * and the vsnprintf that fills it.
 * --------------------------------------------------------------- */
#ifndef CFT_ERRMSG_MAX
#  ifdef CFT_TINY
#    define CFT_ERRMSG_MAX 1
#  else
#    define CFT_ERRMSG_MAX 320
#  endif
#endif

#if CFT_ERRMSG_MAX < 1
#error "CFT_ERRMSG_MAX must be at least 1 - cft_last_error() returns a string"
#endif

/* ---------------------------------------------------------------
 * The module switches
 *
 * Each names one translation unit (two, where a module and its table
 * are separate files) and removes it entirely: the file compiles to
 * nothing, so its code, its constant tables and its dependencies are
 * all gone rather than left to the linker's garbage collector to
 * find. The public entry points that module defines are then absent at
 * LINK time, which is deliberate - a caller that needs cft_exp on a
 * part with no room for it should be told so by the linker and not by
 * a run-time refusal it might not check.
 *
 *   CFT_NO_REMOTE       backend_remote.c - the cft:// device of
 *                       docs/REMOTE.md. Sockets. Pre-dates this file;
 *                       device.c has honoured it since ABI 0.7.
 *   CFT_NO_CONFORMANCE  conformance.c - cft_conformance(), which reads
 *                       vector sets from a DIRECTORY. There is no
 *                       filesystem on these parts; the same sets reach
 *                       them over the wire instead
 *                       (host/tools/serial_replay.py).
 *   CFT_NO_TRANSCEND    transcend.c and mpfloat.c - the 39 correctly
 *                       rounded transcendentals, their multiprecision
 *                       evaluator, and mp_2opi.h, which is a 117 KB
 *                       table of 2/pi. Much the largest single thing
 *                       in the library.
 *   CFT_NO_PROGRAM      program.c and sha256.c - the sequencer, its
 *                       image loader and cft_sha256().
 *   CFT_NO_CHARS        chars.c - the clause-5.12 character
 *                       conversions and 9.7's payload operations.
 *                       Carries its own arbitrary-precision natural
 *                       for the exact decimal, and a malloc with it.
 *   CFT_NO_FORMATOF     formatof.c - the 5.4.1 mixed-format
 *                       arithmetic. Needs clause5.c and divsqrt.c.
 *   CFT_NO_DIVSQRT      divsqrt.c - cft_div and cft_sqrt. Implies
 *                       CFT_NO_FORMATOF, which calls both.
 *   CFT_NO_CLAUSE5      clause5.c - conversions, cft_rint, cft_scaleb,
 *                       the predicates, cft_rem. Implies
 *                       CFT_NO_FORMATOF, which calls cft_convert.
 *   CFT_NO_AUGMENTED    augmented.c - the 9.5 augmented arithmetic.
 *   CFT_NO_REDUCE       reduce.c - cft_reduce() and the 9.4 scaled
 *                       products. The reduction TREE is in
 *                       softfloat.c and stays either way.
 *   CFT_NO_GETENV       the two getenv() route overrides
 *                       (CFT_DIVSQRT_SEQ, CFT_TRANSCEND_MINPREC).
 *                       avr-libc has no environment; a freestanding
 *                       build has nothing for one to mean.
 *
 * Implications are applied here rather than left to the linker, so a
 * caller who asks for one gets a build that links.
 * --------------------------------------------------------------- */
#if defined(CFT_NO_DIVSQRT) || defined(CFT_NO_CLAUSE5)
#  ifndef CFT_NO_FORMATOF
#    define CFT_NO_FORMATOF 1
#  endif
#endif

/* ---------------------------------------------------------------
 * What no profile removes: the heap
 *
 * There is no CFT_NO_HEAP here, because the library does not have one
 * to offer and a macro that promised otherwise would be worse than no
 * macro at all. cft_open() allocates its device handle; divsqrt.c,
 * clause5.c and reduce.c each allocate a scratch vector proportional
 * to the element count of the call they are serving. Every one of
 * those is a malloc, every one is checked, and every one is freed
 * before its call returns - so a build's steady-state heap is one
 * device handle, and its peak is one call's scratch.
 *
 * docs/EMBEDDED.md measures both on the parts this is built for.
 * --------------------------------------------------------------- */

#endif /* CFT_CONFIG_H */
