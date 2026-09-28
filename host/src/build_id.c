/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cft_build_id(): which source tree this library was compiled from
 * (cft.h says what the id means and what it does not).
 *
 * A file of its own so that a new id recompiles this and nothing else.
 * host/Makefile computes the id on every make that builds the library
 * (tools/gen_build_id.sh), writes it to a header OUTSIDE src/ and
 * include/ - both of which
 * bindings/arduino/sync.py vendors whole, so a generated file in either
 * would fail `sync.py --check` on every commit - and compiles THIS file,
 * and only this one, with CFT_BUILD_ID_H naming that header.
 *
 * Every other build of this file sees no CFT_BUILD_ID_H and compiles
 * "unknown": the Arduino library's vendored copy, the WebAssembly
 * module, the fuzz harnesses, profiles-check, and anything compiled
 * outside host/Makefile. None of them ran the generator, so none of
 * them knows which tree it came from, and "unknown" is the answer that
 * is true of all of them. A header is included only when the build that
 * names it also wrote it, which is what keeps a stale one from being
 * picked up by accident.
 */

#include "../include/cft.h"

#ifdef CFT_BUILD_ID_H
#include CFT_BUILD_ID_H
#endif

#ifndef CFT_BUILD_ID_STRING
#define CFT_BUILD_ID_STRING "unknown"
#endif

CFT_API const char *cft_build_id(void)
{
    return CFT_BUILD_ID_STRING;
}
