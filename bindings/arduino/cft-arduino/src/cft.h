/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * `#include <cft.h>` for a sketch.
 *
 * An Arduino build puts a library's src/ on the include path and
 * nothing below it, so the public header has to be reachable from
 * exactly here. The header itself is at src/cft/include/cft.h, beside
 * the sources that reach it as "../include/cft.h" - the layout
 * host/ has, preserved so that the vendored copy is byte-identical to
 * its source and bindings/arduino/sync.py can prove it with a hash.
 *
 * This file is the whole of the difference, and it is three lines.
 */

#ifndef CFT_ARDUINO_CFT_H
#define CFT_ARDUINO_CFT_H

#include "cft/include/cft.h"

#endif /* CFT_ARDUINO_CFT_H */
