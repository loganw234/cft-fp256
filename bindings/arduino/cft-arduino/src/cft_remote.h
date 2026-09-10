/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The one line a sketch needs to reach a cft device over the wire:
 *
 *     #include <cft_remote.h>
 *
 * Everything it names lives in src/remote/ - the codec, the two
 * transports, the flash-operand helpers - and this file is four
 * #includes.
 *
 * IT HAS TO BE AT THE ROOT OF src/, and that is the whole reason it
 * exists rather than being one more header in src/remote/.
 * arduino-cli's library resolver indexes a library by the headers that
 * sit DIRECTLY in src/ and by nothing deeper, so a sketch whose first
 * include is <remote/cft_remote.h> resolves no library at all and the
 * compile ends there. Once ANY root header has pulled the library in,
 * src/ is on the include path and every subdirectory include works -
 * which is why this is the only file of the remote half outside
 * src/remote/, and why it is named after that half and not after the
 * library. The on-chip half's own root header is a different file with
 * a different name and the two do not meet.
 */

#ifndef CFT_REMOTE_ROOT_H_
#define CFT_REMOTE_ROOT_H_

#include "remote/cft_remote.h"        /* the frame codec and the client */
#include "remote/cft_remote_stream.h" /* over an Arduino Stream: Serial */
#include "remote/cft_remote_net.h"    /* over a socket: WiFiClient, ... */
#include "remote/cft_remote_flash.h"  /* operands out of program memory */

#endif /* CFT_REMOTE_ROOT_H_ */
