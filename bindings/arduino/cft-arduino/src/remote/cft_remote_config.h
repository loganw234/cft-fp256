/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The remote client's compile-time budget.
 *
 * Every number here is a knob a sketch may lower BEFORE including
 * <remote/cft_remote.h> (or with a -D on the command line). Nothing
 * here is on the wire: the wire's constants live in cft_remote.h and
 * are held to host/src/remote.h by a static_assert in the host check.
 *
 * The defaults split on __AVR__ for one reason: an Uno or a Nano has
 * 2048 bytes of SRAM in total, of which the core's two 64-byte serial
 * rings and the sketch's own variables are already spent. The client
 * is sized so that its object, its stack and its transport together
 * stay under about a tenth of that, and so that a sketch which needs
 * less can say so.
 *
 * What the client NEVER does, on any board, and what makes the budget
 * a budget rather than an estimate: it does not allocate, it does not
 * hold an operand array, and it does not hold a result array. Operands
 * are produced one element at a time by the caller's Operands object
 * and results are handed back one element at a time to the caller's
 * Results object. The largest single object the client ever has in
 * hand is ONE element - 32 bytes at binary256.
 */

#ifndef CFT_REMOTE_CONFIG_H_
#define CFT_REMOTE_CONFIG_H_

/* The most operand-and-result data one RUN frame carries. The client
 * splits a run of n elements into ceil(n / k) frames, where k is this
 * budget divided by what one element costs on the wire (its operands
 * plus its result), at least 1. The same discipline as the C client's
 * CFTR_CHUNK_BYTES, four to five orders of magnitude smaller: the
 * reason there is a 16 MiB memcpy, the reason here is that a serial
 * line at 115200 baud moves 11.5 kB a second and a sketch wants to see
 * progress.
 *
 * It does NOT cap a REDUCE: a reduction streams n elements out and
 * gets ONE element back, so an 8-bit board can reduce over more
 * elements than it could ever store. It is not a receive cap either -
 * see CFT_REMOTE_MAX_RECV_BYTES. */
#ifndef CFT_REMOTE_CHUNK_BYTES
#  if defined(__AVR__)
#    define CFT_REMOTE_CHUNK_BYTES 256u
#  else
#    define CFT_REMOTE_CHUNK_BYTES 4096u
#  endif
#endif

/* A frame whose header declares more payload than this is a protocol
 * fault: the connection is finished and the handle is poisoned. It is
 * NOT an allocation limit - this client allocates nothing and reads a
 * payload it does not understand straight into the checksum and out of
 * existence - it is the bound on how long a corrupted length field can
 * make the client read. The protocol's own cap is 1 GiB
 * (CFTR_MAX_PAYLOAD); this one is the board's opinion of it. */
#ifndef CFT_REMOTE_MAX_RECV_BYTES
#  if defined(__AVR__)
#    define CFT_REMOTE_MAX_RECV_BYTES 1048576ul
#  else
#    define CFT_REMOTE_MAX_RECV_BYTES 16777216ul
#  endif
#endif

/* Bytes of the server's own message kept for message(). The text
 * arrives at run time in a refusal's or a failed response's payload;
 * anything past this is checksummed and dropped, and the message is
 * always NUL-terminated. Set to 0 to keep none - reason() and
 * status() still say what happened, in numbers. */
#ifndef CFT_REMOTE_ERR_BYTES
#  if defined(__AVR__)
#    define CFT_REMOTE_ERR_BYTES 64u
#  else
#    define CFT_REMOTE_ERR_BYTES 192u
#  endif
#endif

/* Bytes of the caps block's backend name kept ("software", "xrt").
 * 0 keeps none and backend() answers "". The wire field is 32 bytes
 * (CFTR_BACKEND_NAME) and a shorter store truncates. */
#ifndef CFT_REMOTE_BACKEND_NAME_BYTES
#  if defined(__AVR__)
#    define CFT_REMOTE_BACKEND_NAME_BYTES 0u
#  else
#    define CFT_REMOTE_BACKEND_NAME_BYTES 32u
#  endif
#endif

/* Keep the four sequencer capacities and the scratch depth out of the
 * caps block (20 bytes). Off on AVR because this client does not issue
 * PROG_LOAD or PROG_RUN at all - a program image would have to be held
 * to be checksummed, and holding it is the one thing the budget above
 * forbids. */
#ifndef CFT_REMOTE_KEEP_SEQ_CAPS
#  if defined(__AVR__)
#    define CFT_REMOTE_KEEP_SEQ_CAPS 0
#  else
#    define CFT_REMOTE_KEEP_SEQ_CAPS 1
#  endif
#endif

/* The widest element the client will handle, in bytes: 32 for
 * binary256, 16 for binary128, 8 for binary64, 4 for binary32. It
 * sizes one member (the single-element result of runOne and reduce)
 * and one stack buffer, so a sketch that only ever asks for binary64
 * saves 24 bytes of each by setting it to 8. A format wider than this
 * is refused locally, before a frame is sent. */
#ifndef CFT_REMOTE_MAX_ELEM_BYTES
#  define CFT_REMOTE_MAX_ELEM_BYTES 32u
#endif

/* How long a single read may make no progress before the client calls
 * the connection dead, in milliseconds. The C client waits twenty
 * MINUTES because a remote server may be running a ten-million-step
 * program; a board wants to know it is stuck. This is a per-read
 * stall, not a per-frame budget, so a long transfer that keeps moving
 * never trips it. */
#ifndef CFT_REMOTE_TIMEOUT_MS
#  define CFT_REMOTE_TIMEOUT_MS 10000ul
#endif

/* Bytes the NetTransport stages before it hands them to the Client.
 * The ESP32's WiFiClient::write() is one send() per call, and a frame
 * written in 32-byte elements would be a packet per element; staging
 * makes it one segment per frame for anything that fits. 0 disables
 * staging (every write goes straight through), which is what a
 * HardwareSerial wants - it has its own ring. */
#ifndef CFT_REMOTE_NET_TX_BUFFER
#  if defined(__AVR__)
#    define CFT_REMOTE_NET_TX_BUFFER 64u
#  else
#    define CFT_REMOTE_NET_TX_BUFFER 536u
#  endif
#endif

#endif /* CFT_REMOTE_CONFIG_H_ */
