# The remote backend: a tile behind a socket

Step 1 of docs/ROADMAP.md's "After card day: the third tier". A third
backend for libcft, beside the software one and the XRT one: a device
reached over a TCP connection, served by a small program that holds a
library device of its own - the software backend by default, or an
artifact on a machine that has the card. The client is the same
`libcft` every caller already links; the only new thing a caller sees
is one more spelling of the argument to `cft_open`:

    cft_open("cft://host:port", 0, &dev);

Everything else - `cft_run`, `cft_reduce`, the programs, the buffers,
the status word, the clause-5 and clause-9 host operations - is the
API it always was, on a device whose arithmetic happens somewhere
else. The contract does not move: the server computes with the
library, the library is the contract, and a remote replay that
disagrees with a local one is a fault in the transport until proven
otherwise.

This file is the protocol, written before the code that implements it,
and then the measurements the code was held to. It is also
docs/PLATFORMS.md section 6's Windows answer: XRT is Linux-only, so a
Windows host talks to the card through a Linux box that has it, and
the Windows client needs no driver, no XRT, and no shell - a socket is
all it needs, and Windows has had one of those since 1993.

## Scope, stated first

- **No authentication and no encryption.** The server answers anyone
  who can reach its port, and the bytes are plain. It binds to
  `127.0.0.1` unless told otherwise (`--bind`), which keeps it off the
  network by default; exposing it on a LAN is a deliberate act and a
  trust decision about that LAN. A first step should say what it is,
  and this one is a transport, not a security boundary. The two safe
  ways to reach a server on another machine - an SSH tunnel, or a LAN
  you already trust with the machine - and what a WebSocket port adds
  to that, are in "What no authentication means, said again for a
  browser" below.
- **One request at a time, many connections.** The server multiplexes
  its connections with `select()` rather than threads: it opens a
  library device for each connection when it is accepted, and then
  serves requests from every open connection one at a time, in arrival
  order, each to completion. Two clients, or one client holding two
  handles, interleave at request granularity and neither waits for the
  other to close - which is what makes `device-test`'s two handles, or
  a process with a handle per thread, safe. Up to 32 connections at
  once; the listen backlog holds the rest. On any one connection the
  wire is a strict request/response sequence, so a request id is a
  check rather than a scheduler. A connection that starts a frame and
  then falls silent for a minute is dropped, so it cannot hold the
  others up; a slow link that keeps delivering bytes is never cut.
- **The socket API is the operating system's, not a dependency.**
  BSD sockets on POSIX, Winsock on Windows, both C99 plus the system
  headers; there is nothing to install. On Windows the library loads
  `ws2_32.dll` at first use rather than at link time, so `libcft.a`'s
  link set is what it was and every existing consumer - the Fortran,
  Go and Rust examples, the soak tools, the DLL's loaders - builds and
  runs unchanged. An emscripten build compiles the backend to a stub
  that reports `CFT_ERR_NO_DEVICE`, because a browser has no socket to
  offer it.
- **Localhost forwarding is what makes the cross-OS case free.** WSL2
  forwards ports a Linux service listens on to the Windows host's
  `localhost`, so a server built in the desktop's `cft2204` distro is
  reached by a Windows client with the same URL a loopback test uses.

## What crosses the wire, and what does not

The rule is the one `host/src/device.c` already draws for the XRT
backend: only the calls that touch a device cross. Everything the
library does on the host stays on the client's host, computed by the
client's own copy of the library, which is bit-identical by contract.

| operation | where it runs | on the wire |
|---|---|---|
| `cft_run` | server | one `RUN` request per chunk of the call |
| `cft_reduce` for `CFT_SUM`, `CFT_DOT` | server | one `REDUCE` request |
| `cft_reduce` for `CFT_SUMSQ`, `CFT_SUMABS` | the composition on the client, its two passes on the server | `REDUCE` (dot), or `RUN` (abs) then `REDUCE` (sum) |
| `cft_program_load` | validated on the client, then loaded on the server | `PROG_LOAD` once per distinct image |
| `cft_program_run` | server | one `PROG_RUN` per chunk of lanes |
| `cft_program_free` | both | `PROG_FREE` |
| `cft_get_caps`, `cft_supports` | client, from the capabilities the handshake returned | nothing after `HELLO` |
| `cft_alloc` and the buffer calls | client: host memory, as on the software backend | nothing (see below) |
| the six status-word operations (5.7.4) | client | nothing (see below) |
| `cft_div`, `cft_sqrt`, `cft_rint`, `cft_scaleb`, `cft_cmp_sig`, the formatOf widening route | the composition on the client, each pass on the server | one request per pass, or one `PROG_RUN` per chunk on the program route |
| the clause-5 host operations, the transcendentals, the character conversions, the augmented operations, the scaled products, the magnitude forms, `cft_convert` | client | nothing |

**Why the status word stays on the client.** 7.1's word is the
caller's record of what the caller's calls raised, and the client's
`cft_device` already owns one: every entry point in the library ends
with `cft_flags_emit(dev, acc, flags_out)`, which ORs the call's flags
into the handle's word and writes `flags_out` from the same value. A
remote `cft_run` returns its flag word in the response; the client ORs
it in through exactly that hook, as the XRT backend does with the word
it reads from the tile's `FLAGS` register. So the word is correct by
the same argument on all three backends, the composition discipline
(`cft_flags_mute` around a composed operation's internal passes) works
unchanged because it is the client's own passes being muted, and the
six operations of 5.7.4 - lower, raise, test, save, restore, test-saved
- never need a round trip. Putting the word on the server would make
`cft_test_flags` a network call, make `cft_lower_flags(NULL, ...)`'s
tolerated-NULL semantics meaningless, and leave the composition
discipline to a second implementation on the far end. The server's own
device has a word too, since it is a library device; nothing reads it,
and it dies with the connection. The protocol still serves the six
operations (`FLAGS_*` below) because the server's word is observable
state and a client that is not libcft - a test, a thin binding - may
want it; libcft's client never issues them.

**Why the buffers stay on the client.** `cft_alloc` on the software
backend is a host allocation and the sync calls are no-ops, and
`cft_run` copies from whatever pointers it is given on every backend
today - the "recognises its own buffers and skips staging" of cft.h is
a design intention the XRT backend has not yet built either. A remote
handle therefore treats buffers exactly as the software backend does.
The protocol serves buffer allocate, free, write and read (`BUF_*`
below) so that a later step which adds by-handle operands to `RUN` can
do so without a protocol version bump, and so that the server's buffer
path is exercised now rather than discovered later; libcft's client
does not use them.

## The frame

Every message on the wire is one frame: a fixed 32-byte header, then a
payload of the length the header states. All integers are
little-endian, unpadded, at the offsets given. There is no text on the
wire except a refusal's message and a backend's name, and no number is
ever sent in a parsed form: an encoding travels as the bytes of its
interchange format, exactly as it sits in a `cft_run` buffer, and a
flag word travels as the `uint32_t` the library returns.

    offset  size  field      meaning
    0       4     magic      the bytes 'C' 'F' 'T' 'R', in that order
    4       2     proto      protocol version; this document is 1
    6       2     kind       0 request, 1 response, 2 refusal
    8       4     abi        the SENDER's cft_abi_version(): (major << 16) | minor
    12      4     id         request id; a response or refusal echoes the request's
    16      2     op         opcode (below); echoed in the response
    18      2     status     cft_status of the operation (response, refusal); 0 in a request
    20      4     length     payload bytes that follow the header
    24      4     crc        CRC-32 of the header with this field zero, then the payload
    28      4     reserved   0

**Magic.** Four bytes, so that a connection which is not speaking this
protocol at all - a browser, a stray telnet, a different service on a
reused port - is refused on its first four bytes and not parsed.

**Both ends' ABI, on every frame.** The client puts its
`cft_abi_version()` in every request and the server puts its own in
every response. Each side compares the other's with its own and
REFUSES a mismatch: the two libraries would agree on the arithmetic
(that is the contract) but not necessarily on which operations exist,
which opcode numbers are assigned, or what the status word's bits are,
and a warning is a disagreement nobody reads. The mismatch is reported
as `CFT_ERR_UNSUPPORTED` with both versions in the message. This is
also why the ABI version is in the header rather than only in `HELLO`:
a server that is upgraded under a long-lived client fails on the next
frame, not the next session.

**The CRC.** CRC-32 as IEEE 802.3, zlib and PNG define it: reflected
polynomial `0xEDB88320`, initial value all ones, final complement,
check value `0xCBF43926` for the nine ASCII digits `123456789`. The
table is derived from the polynomial at first use and the
implementation checks itself against that check value before the first
frame is sent; `host/tests/remote_test.c` also checks a frame's CRC
against Python's `zlib.crc32`, so two implementations that share no
code agree on it. It covers the header (with the crc field as zero) and
the whole payload, so a flipped byte anywhere in a frame is a refusal.
This is a corruption check for a transport that is already
TCP-checksummed; its job is to make a wrong length, a truncated
payload, a bug in either end's serialiser, or a deliberately corrupted
byte (the negative control below) a REFUSAL rather than a plausible
number.

**The length discipline.** A receiver reads exactly 32 bytes, checks
magic, version, reserved and ABI, then reads exactly `length` bytes.
A payload longer than the frame cap (1 GiB, `CFTR_MAX_PAYLOAD`) is
refused before any of it is read or allocated, because a corrupted
length field must not become an allocation. A connection that closes
before `length` bytes arrive is a truncated frame and is refused; so
is one that stalls mid-frame for the server's stall timeout (a
minute), which is how a header claiming one byte more than its sender
holds ends - the server waits for the byte, gives up, refuses the
frame as truncated with `CFT_ERR_TIMEOUT`, and closes. A payload whose
length does not match what its opcode requires - a `RUN` whose operand
bytes are not `n` elements of the format's width - is refused by the
operation's decoder.

**Refusal.** A frame that fails any check above is answered with kind
2, `status` naming the reason (`CFT_ERR_INTERNAL` for a transport
fault, `CFT_ERR_UNSUPPORTED` for an ABI or protocol-version mismatch,
`CFT_ERR_INVALID_ARGUMENT` for a payload an operation cannot decode)
and a NUL-terminated message as payload, and then the sender of the
refusal CLOSES THE CONNECTION. After a framing error the byte stream
is unsynchronised, and pretending to resume it is how a later request
gets answered with an earlier response. A client that receives a
refusal, or that fails any check on a response, marks its handle
POISONED: every later call on that handle returns `CFT_ERR_INTERNAL`
with "close and reopen" in `cft_last_error()`, the same discipline the
XRT backend applies to a handle whose compute units may still be
running. A kind-1 response whose `status` is not `CFT_OK` is not a
refusal: it is the operation's own answer (`CFT_ERR_UNSUPPORTED` for a
format the server's device lacks, `CFT_ERR_BUS_FAULT` from a tile), the
connection continues, and the payload is the message for
`cft_last_error()`.

**Request ids.** The client numbers requests from 1 and the server
echoes the number; a response carrying any other id is refused by the
client. With one request in flight at a time the id can only be wrong
if the stream is, which is exactly when the check matters.

## The operations

Payload layouts, request then response. `u32`/`u64` are little-endian
integers; `elem[n]` is `n` dense elements of `cft_format_size(fmt)`
bytes each; `present` is a bit mask, bit 0 for `a`, bit 1 for `b`,
bit 2 for `c`, and an operand that is absent is simply not in the
payload (the server passes NULL for it, as the caller did).

| op | name | request | response |
|---|---|---|---|
| `0x0001` | `HELLO` | - | the caps block |
| `0x0002` | `CAPS` | - | the caps block |
| `0x0003` | `STATS` | - | `u64 requests, u64 bytes_in, u64 bytes_out, u32 entries, u32 0, then entries x (u32 op, u32 0, u64 count)` |
| `0x0010` | `RUN` | `u32 op, u32 fmt, u32 rnd, u32 present, u64 n, elem[n] per present operand` | `u32 flags, u32 bus, elem[n]` |
| `0x0011` | `REDUCE` | `u32 op, u32 fmt, u32 rnd, u32 present, u64 n, elem[n] per present operand` | `u32 flags, u32 bus, elem[1]` |
| `0x0020` | `PROG_LOAD` | the program image, byte for byte | `u32 handle, u32 fmt, u32 max_deposits, u32 0` |
| `0x0021` | `PROG_RUN` | `u32 handle, u32 present, u32 want_counts, u32 0, u64 n, elem[n] per present operand` | `u32 flags, u32 bus, elem[n * max_deposits], then u32[n] counts if wanted` |
| `0x0022` | `PROG_FREE` | `u32 handle` | - |
| `0x0030` | `BUF_ALLOC` | `u64 bytes` | `u32 handle` |
| `0x0031` | `BUF_FREE` | `u32 handle` | - |
| `0x0032` | `BUF_WRITE` | `u32 handle, u32 0, u64 offset, bytes` | - |
| `0x0033` | `BUF_READ` | `u32 handle, u32 0, u64 offset, u64 bytes` | bytes |
| `0x0040` | `FLAGS_LOWER` | `u32 mask` | - |
| `0x0041` | `FLAGS_RAISE` | `u32 mask` | - |
| `0x0042` | `FLAGS_TEST` | `u32 mask` | `u32 result` |
| `0x0043` | `FLAGS_SAVE` | - | `u32 word` |
| `0x0044` | `FLAGS_RESTORE` | `u32 saved, u32 mask` | - |
| `0x0045` | `FLAGS_TEST_SAVED` | `u32 saved, u32 mask` | `u32 result` |
| `0x00FF` | `BYE` | - | -, and both sides close |

**The caps block** (56 bytes): `u32 format_mask, u32 op_groups,
u32 tiles, u32 device_version, u32 flags_readable, u32 abi,
char backend[32]` - the server's device as `cft_get_caps` reports it,
with `op_groups` derived by asking `cft_supports` one representative
opcode per group, and `backend` the NAME OF THE SERVER'S BACKEND
(`software`, `xrt`), NUL-padded. The client reports its own backend as
`remote` and keeps the server's name for the message a failure carries.

`HELLO` must be the first request on a connection; anything else
before it is refused. `CAPS` is the same block again on demand.
`STATS` is the server's count of what this connection has asked of it,
by opcode, which is how the round-trip measurements below are taken
rather than inferred: the count of `RUN` frames a `cft_div` issued is
the number of `RUN` frames the server received.

**Programs.** `cft_program_load` validates the image on the client
first, as it always has, so an image a device could execute
ambiguously never crosses. The remote backend then loads it on the
server when it is first RUN, keeps the server's handle beside the
image bytes, and reuses it for every later run of the same bytes -
`cft_div` loads one program per call and runs it over every chunk, so
after the first chunk a run is one round trip. A different image
frees the cached handle and loads the new one. The server validates
the image again with the same library and reports the format and
deposit budget it read, which the client checks against its own; a
disagreement is a refusal, because the two libraries have the same
ABI and could only differ if one of them were not the library.

**Chunking.** `RUN` and `PROG_RUN` requests are split by the client
so that no frame carries more than `CFTR_CHUNK_BYTES` (16 MiB) of
operand and result data. That is safe for exactly the reason the XRT
backend's multi-tile partitioning is: an element of an elementwise
result depends on its own index alone, and a sequencer lane on its
own lane alone, with the early exit changing only how long a run
takes (docs/SEQUENCER.md P2, P3). The flag and bus words are ORs over
the chunks, which is the same union one frame would carry. `REDUCE`
is not chunked - a partial sum is only reusable if its range is a
node of the tree, and cutting the tree is the XRT backend's job with
its own tiles, not the transport's - so a reduction whose operands
exceed the frame cap is `CFT_ERR_INVALID_ARGUMENT`. At fp256 that is
sixteen million elements per operand, and a first step may have a
ceiling if it says where it is.

**Timeouts.** A client waits for a response for `CFT_TIMEOUT_MS`
milliseconds if that is set in the environment, else twenty minutes -
the XRT backend's cap, and deliberately not its sixty-second default,
because a remote server may be a software backend and a program of
ten million steps over four thousand lanes is a legitimate minute of
its time. A timeout poisons the handle and returns `CFT_ERR_TIMEOUT`.

## The server

    cft-serve [--port N] [--bind ADDR] [--artifact PATH] [--max-conns N]
              [--ws PORT] [--ws-port-file PATH] [--verbose]

Listens on `127.0.0.1:7754` by default (the port is a choice, not a
derivation; anything above 1024 that nothing else on the box uses).
`--bind 0.0.0.0` exposes it on every interface, with the scope
statement above in force. `--artifact` names an xclbin, so that the
same program fronts the U50C from a Linux box; without it every
connection gets the software backend. `--max-conns N` exits after N
connections, which is what a test harness wants; otherwise it serves
until it is stopped - BY ITS PID, which it prints on startup and
writes to `--pid-file PATH` if asked. `--verbose` logs every request
with its opcode, length and status; the default is one line per
connection.

One library device per connection, opened at accept and closed at
disconnect, so a client's status word, buffers and programs are its
own and a client that exits mid-run leaves nothing behind. The
device's exception flags are read the way every backend reads them
and returned in every `RUN`, `REDUCE` and `PROG_RUN` response, so a
server fronting a tile whose `flags_readable` is 0 reports that in
the caps block and the client's `cft_get_caps` says so.

## The browser reaches the tile: the same frames over WebSocket

`cft-serve --ws PORT` opens a second listener that speaks RFC 6455.
**One WebSocket message carries exactly one frame of the section
above, unchanged** - the same 32-byte header, the same little-endian
fields, the same CRC-32 over the same bytes, the same opcodes and the
same payload layouts. A WebSocket message is an envelope around the
frame the TCP path sends bare, so the server's handlers, its `STATS`
counters and its refusals are the ones the TCP path already had, and
the protocol version does not move: a transport is not a protocol
change.

The envelope lives in `host/tools/ws.c` and `ws.h`, written against
the same `cftr_sock_*` shim as the rest of the server, so it has no
platform branch and adds no link flag on any platform. SHA-1 and
base64 are implemented there because `Sec-WebSocket-Accept` is defined
in terms of them and for no other reason; a handshake that pulled in a
crypto library would be a dependency for forty lines of hashing.

### A second port, not a second protocol on the first

The alternative was one listener that reads the first bytes and treats
`GET ` as a WebSocket. It was not taken, for three reasons:

1. **The frame path is not touched.** A separate listener means
   `serve_one()` reads a TCP frame with exactly the call it read it
   with before, so the stall timeout, the truncation behaviour and the
   refusals that "The negative control" below recorded are the ones
   that were measured, not ones that were re-derived. Detection would
   have meant reading the first four bytes and then handing them back
   to a reader that takes a socket, which is a second frame reader on
   the same connection.
2. **Detection needs a peek the socket shim does not offer.**
   `cftr_sock_recv_all` consumes what it reads; `MSG_PEEK` would be a
   direct `recv` call, which on Windows means linking `ws2_32` into a
   tool whose library deliberately loads it at run time
   (`src/backend_remote.c` says why), and a platform branch in a file
   that has none.
3. **A browser will open a WebSocket to a loopback port from any page
   the person is looking at.** A cross-origin `WebSocket` needs no
   preflight and no permission from the server; the only thing that
   decides is whether the server answers. The frame port is not
   reachable that way at all - a browser cannot be made to send
   `CFTR`, and a `GET ` on the frame port dies on the magic check. So
   the WebSocket listener is the one transport a web page can use, and
   it is **off unless `--ws` is given**. `--ws` and `--port` refuse to
   be the same port.

The handshake is read on the connection's first readable event and not
at accept, because the loop is one thread: a client that connects to
the WebSocket port and then says nothing would otherwise hold every
other connection for the stall minute.

### The envelope, in detail

- The opening handshake is `GET`, `Upgrade: websocket`, `Connection:
  upgrade`, `Sec-WebSocket-Version: 13` and a `Sec-WebSocket-Key`;
  the answer is `101` with `Sec-WebSocket-Accept =
  base64(SHA-1(key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"))`.
  Anything else gets a short HTTP status (`400`, `426`, `431`) and the
  connection closes. The request head is capped at 8 KiB.
- The SHA-1 and base64 are checked against their published vectors
  before the server listens, exactly as the CRC-32 is: FIPS 180-4's
  `SHA-1("abc")`, RFC 4648 section 10's seven base64 vectors, and RFC
  6455 section 1.3's own worked example of the whole accept
  computation. An implementation never held against its own published
  vector is a guess.
- Binary messages only. A text message is refused: this protocol is
  bytes, and a text frame would have been through a UTF-8 round trip.
- A client frame must be masked, as RFC 6455 5.1 requires; an unmasked
  one is refused. Server frames are unmasked, as 5.1 also requires.
- **Fragmentation is tolerated on receive**: a message split across a
  binary frame and any number of continuations is reassembled and then
  read as one frame. The server never fragments what it sends.
- A ping is answered with a pong carrying the same bytes; a pong is
  dropped; a close is answered with a close. **A control frame is not
  a request**: nothing is counted, and the server goes back to waiting
  rather than blocking for a data frame that may not be coming, so one
  connection's keepalive cannot hold up the others.
- Reserved bits, a 64-bit length with its top bit set, a fragmented or
  oversize control frame, and a message longer than the frame cap are
  each refused before anything is allocated.

**One thing the message boundary changes, and only one.** A header
that claims one byte more than its payload holds - the second sabotage
of "The negative control" below - is caught immediately here, because
the message ended, where the TCP path waits out its stall minute for a
byte that never comes. Same verdict, sooner: the refusal says
`truncated frame`, and it carries `CFT_ERR_INTERNAL` where the TCP
path reports `CFT_ERR_TIMEOUT`. No frame with a wrong length is
computed on either way.

### What "no authentication" means, said again for a browser

The scope statement at the top of this file holds without change: the
server answers anyone who can reach its port, the bytes are plain, and
it binds to `127.0.0.1` unless `--bind` says otherwise. The WebSocket
port makes one thing sharper and it is worth saying plainly.

**Anyone who can reach the port can compute on the device, read its
`STATS`, load programs on it and allocate memory on it.** There is no
credential to get wrong. So there are exactly two safe ways to run it:

- **On loopback**, which is the default, reached by clients on the
  same machine - or through an SSH tunnel from another one:
  `ssh -N -L 7755:127.0.0.1:7755 user@host` puts the remote server on
  the client's own `127.0.0.1`, authenticated and encrypted by SSH,
  with nothing listening on the network at either end. That is the
  supported way to reach a server on another machine.
- **On a LAN you already trust with the machine**, by an explicit
  `--bind`. That is a decision about the LAN, not about this program:
  binding to `0.0.0.0` offers the device to every host that can route
  to it.

And for the WebSocket port specifically: **any page in a browser on a
machine that can reach the port can open a WebSocket to it.**
Cross-origin WebSocket connections need no preflight and no
cooperation from the server, so a page the operator happens to visit
can drive the tile. The server logs the `Origin` header of every
handshake - it is recorded, not judged, because a server with no
authentication should not pretend an `Origin` check is one - and
`--ws` is off unless asked for. If the machine is running `cft-serve`
for a C client, it is not offering a WebSocket unless someone typed
`--ws`.

### The clients

- `bindings/wasm/remote.mjs` - the frames, in JavaScript. The same
  bytes `src/backend_remote.c` builds: the same header, the same CRC
  (whose table is derived from the polynomial here too), the same
  chunking at `CFTR_CHUNK_BYTES`, the same refusal-poisons-the-handle
  discipline. Two transports behind one codec: `ws://` (browser and
  Node 22, which has a global `WebSocket`) and `tcp://` (Node, through
  `node:net`, imported lazily so a browser bundle never sees it) -
  `cft://host:port` is accepted as a spelling of the second. The two
  differ in where a frame's boundary comes from and in nothing else,
  which is what makes them comparable. There is no transcribed ABI
  number: `abi` is a required option whose natural value is the wasm
  module's own `cftw_abi_version()`, because every frame carries the
  sender's and the server refuses a mismatch. The caps block is read
  by offset and not by total length - the 56 bytes this document
  defines, and whatever a later server appends kept as `extra` - so a
  server that grows its `HELLO` stays readable by a client that has
  not been rebuilt.
- `bindings/wasm/remote.html` - a page that connects, prints the caps
  block the server answered `HELLO` with, and then runs a check twice
  for the same inputs: once on the server, once in the wasm module
  loaded beside it, compared byte for byte. It also replays a dropped
  `vectors/out` set through the server and compares each case with
  both the local module and the golden model's published result. It
  needs `build/cft_runtime.js` (`bash bindings/wasm/build.sh`) and to
  be served over HTTP rather than opened from `file://`, because a
  browser will not load an ES module from a `file:` URL.
- `bindings/node/remote_test.mjs` - the same checks headless, plus a
  raw RFC 6455 client written in the file itself for the branches a
  client library will not exercise on request (fragmentation, ping).
  It starts its own `cft-serve` on two free loopback ports, records
  its PID and stops it by that PID. `make -C host wstest` runs it.

### What this was held to

Measured 2026-09-07 on DESKTOP-T33SK86 (Windows 11, MINGW64, gcc -O2,
Node v22.19.0), server and clients all on `127.0.0.1`.

**The TCP path first, unchanged.** `make -C host remotetest`, with the
WebSocket code compiled in: `remote_check: every check passed` -
`remote-test`'s protocol suite **245 checks, 0 failures** on both
div/sqrt routes, `device-test` against a remote handle **2,248 checks,
0 failed**, a bounded 28-set replay of **184,496 cases** giving the
same report local and remote, and the Collatz sweep chain
`3d16b9d7ac66234495c47d202358df24aeeb0aaffc32e5babb0072f2d9e159b7`
both ways. That run is what the second-listener decision above was
for: the frame path here is the one that was measured, not one
re-derived around a detection.

**Then the WebSocket path.** `node bindings/node/remote_test.mjs
--sets 20 --cases 11800`: **46 checks, 0 failures**.

| comparison | cases | differing |
|---|---|---|
| WebSocket against the local wasm module | 392,000 | 0 |
| WebSocket against the model's published `d` | 392,000 | 0 |
| WebSocket against the published flag word | 392,000 | 0 |
| WebSocket against TCP | 392,000 | 0 |
| `sum` and `dot`, as `REDUCE` frames | 2,560 | 0 |

392,000 cases is all twenty opcode sets of `vectors/out`, every line,
in 75.4 s. Each was run on the server over WebSocket, on the server
over TCP and in the local wasm module, interleaved and compared as it
went - so the server was multiplexing a WebSocket client and a TCP
client throughout, and nothing was accumulated to compare later.

`make -C host wstest` runs the same test against whatever
`vectors/out` holds. In a tree where the vectors have not been
generated the golden legs say NOT RUN and the replay falls back to
LCG inputs, which still compare the server with the local module and
the two transports with each other: **42 checks, 0 failures**.

**The counters.** After that work the two connections' `STATS` say the
same thing to the byte: **394,562 requests each, `RUN` x392,000 each,
40,958,524 bytes in and 21,700,888 out each**. The counters count
PROTOCOL bytes - `CFTR_HDR_BYTES + length`, on both paths - so the
same sequence of calls leaves the same numbers whichever transport
carried them. That is the measurement that says the envelope is only
an envelope.

**The envelope's own branches**, driven by a raw RFC 6455 client
written inside the test, because a client library will not fragment a
message or send a ping because a test asked it to: a `HELLO` split
across three fragments is answered with its caps block; a ping comes
back as a pong carrying the same fourteen bytes; the connection serves
a request afterwards; a close is answered with a close.
`Sec-WebSocket-Accept` was recomputed with `node:crypto`'s SHA-1 and
matched, which is a second implementation of what `tools/ws.c` does.

### The negative control, over WebSocket

The two sabotages of "The negative control" below, applied to the
JavaScript client instead of the C one (`--sabotage` in
`bindings/wasm/remote.mjs`), against a loopback server:

- **One bit of one returned encoding**, flipped after the CRC has
  passed and the frame has been accepted: nothing about the transport
  notices, because the CRC was correct and the frame was well formed,
  and the comparison catches it at once - the local answer
  `0000000000000000000000000080ff7f` against the sabotaged
  `0100000000000000000000000080ff7f`. Which is the point: the bit
  identity is checked by the replay, not by the wire.
- **A `RUN` header claiming one byte more than its payload holds**:
  `the server refused the request: truncated frame: the header claims 73
  payload bytes and the WebSocket message carries 72`, and every later
  call on the handle refuses with `this remote handle was poisoned by an
  earlier transport fault; close it and open it again`. No frame with a
  wrong length was computed on.

And the refusals the protocol already had, over the new transport: a
wrong magic, a corrupted CRC and a length past the cap refused with
status `8` (CFT_ERR_INTERNAL), a wrong ABI with `2`
(CFT_ERR_UNSUPPORTED), a request before `HELLO` with `1`
(CFT_ERR_INVALID_ARGUMENT), and the connection closed after each. Plus
the ones the envelope adds: a text message is refused as a frame, and
a `GET` without `Upgrade` or a binary frame sent to the WebSocket port
each get `HTTP/1.1 400 Bad Request` before any upgrade happens.

### The round trip

One element per call and 4,096 per call, sequential, from the same
Node client over each transport on loopback, so the difference is the
envelope and nothing else:

| call | TCP | WebSocket | the envelope |
|---|---|---|---|
| 1 fp64 element | 57.5 / 69.8 / 58.7 us | 81.7 / 70.4 / 77.4 us | within the spread |
| 4,096 fp64 elements | 2.656 / 2.793 / 2.693 ms | 3.62 / 3.44 / 3.75 ms | 0.65 to 1.06 ms |

Three runs of 5,000 one-element calls and 500 batched ones, on a box
carrying other work; the spread is the box's. On a one-element call the
envelope is two to fourteen bytes and disappears into the run-to-run
noise. On a 4,096-element call it is 0.65 to 1.06 ms over the 131,136
bytes that cross - **about 5 to 8 nanoseconds a byte** - which is the
client-to-server masking RFC 6455 5.1 requires, and the server's
unmasking of it. The envelope's cost is per byte, not per call.

These are a JavaScript client's numbers and they are not the C
client's: this document's own measurement of `src/backend_remote.c` on
this box, below, is 22.5 us for a one-element call and 1.40 ms for a
4,096-element one, and the difference is a promise and an event-loop
turn per call where the C has a blocking `recv`. The comparable number
here is TCP against WebSocket from the SAME client, which is the table
above.

In a browser the number is the browser's: measured from
`bindings/wasm/remote.html` in a Chrome tab on the same machine,
**264 us** for a one-element fp64 `RUN` over 1,000 sequential calls with
the tab visible, and 5.1 ms with it hidden - a background tab is
throttled by two orders, which is the browser's scheduling and not the
transport. The page's own dropped-set replay ran 300 cases of
`fp64.jsonl` at 2,227 cases/s with 0 differing against the tab's module,
0 against the published `d` and 0 against the published flags.

### What was not run

- **Nothing crossed a network.** Every run above was `127.0.0.1` on
  one machine. The cross-OS run of "How it is held to the contract"
  (c) below - a Linux server in the WSL distro, a Windows client -
  was not repeated over WebSocket.
- **`host/tools/ws.c` was not built or run on Linux.** It is C99
  over the same `cftr_sock_*` shim as the rest of the server, with no
  platform branch of its own, so there is nothing in it that is
  Windows'; but that is an argument, not a measurement.
- **No TLS.** The server does not terminate it. The client accepts a
  `wss://` URL for a proxy that does, and that path was not
  exercised; an SSH tunnel is the answer this document gives for
  crossing a network.
- **The seven-family conformance replay was not driven over
  WebSocket.** The JavaScript client replays what a frame expresses:
  the opcode sets as `RUN` and the reduction sets' `sum` and `dot` as
  `REDUCE`. The transcendental, character, augmented, formatOf and
  scaled-product families are host compositions that never cross the
  wire (see "What crosses the wire, and what does not"), so
  replaying them through a client that is not libcft would be
  replaying the client. `cft_conformance` replays all seven through
  the TCP path and did, above.
- **No sequencer program was loaded from JavaScript.** `remote.mjs`
  implements `PROG_LOAD`, `PROG_RUN` and `PROG_FREE`, and the
  headless test drives `PROG_LOAD`'s frame path with bytes that are
  not an image (the server's library refuses them, the connection
  carries on) - but a valid image was never sent, so `PROG_RUN` over
  WebSocket is written and not exercised. The buffer and status-word
  operations ARE exercised, over WebSocket, in section I of that
  test.
- **No workload chain was computed through the WebSocket path.** The
  five workload tools are C and speak the TCP one; a chain over
  WebSocket would need the tools to take a `ws://` URL, which is a
  change to `host/src` this step did not make.

## Round trips, and what the program route saves

A composed operation issues passes through whatever backend is open,
so on a remote device each pass is a round trip. `cft_div` on the
chunk route is roughly 25 to 30 `cft_run` passes per chunk of
elements (cft.h says why: seed, Newton, an exact residual, one
rounding); on the program route the same sequence is one
`cft_program_run` per chunk, which on a remote device is one
`PROG_RUN` frame after the image has been loaded once. The remote
backend takes the program route by default, as the XRT backend does,
and `CFT_DIVSQRT_SEQ=0` in the environment forces the chunk route so
the difference can be measured rather than asserted. The measurement
is in the section below, taken from the server's `STATS` counters.

## How it is held to the contract

Four measurements, in the order the brief asked for them, each with
its result in the section that follows:

(a) `cft_conformance` replays every published set through a remote
device on loopback and the report is compared with the local replay's
- same sets, same case count, same verdict. The replay is the
library's own acceptance test for a backend, and it is the hardest
case for this one: the per-element pass is one round trip per case.

(b) The five workload tools run with `--artifact cft://...` and the
chain each prints is compared with the chain it prints locally. A
chain is a SHA-256 over every record the run produced, so one wrong
byte in one result on either side changes it.

(c) The cross-OS run: the server built in the desktop's `cft2204`
distro with a Linux `libcft`, the client on Windows, the conformance
sets and a workload replayed across the WSL2 boundary, same chains.

(d) The cost, measured honestly: cases per second for the replay,
local against loopback against WSL, and the composed operations'
round-trip counts on both routes from the server's own counters.

And two controls: `host/tests/device_test.c` holds the remote backend
against the software one the way it holds the XRT one - every
supported format, opcode and attribute, partition invariance across
the chunk boundary, the awkward reduction lengths - and the negative
control flips one byte of a returned encoding inside the client, and
separately corrupts a frame's length, to show the replay and the chain
fail and the refusal fires.

## What the four measurements said

Measured 2026-09-06 on DESKTOP-T33SK86 (Windows 11, MINGW64, gcc -O2),
the client always the Windows build, against three servers: none (the
local software backend), a Windows server on loopback, and a Linux
server in the `cft2204` WSL distro reached through WSL2's localhost
forwarding. The box was carrying other work; the seconds wobble, the
bits do not.

**(a) The full replay, three ways.** `cft-selftest` over `vectors/out`,
the runner's generator counts:

| route | sets | cases | result | seconds |
|---|---|---|---|---|
| local | 168 | 1,223,635 | all matching | 442.2 |
| Windows loopback | 168 | 1,223,635 | all matching | 450.3 |
| Linux server in WSL | 168 | 1,223,635 | all matching | 501.9 |

Every case is a round trip on this path, so the replay is the worst
case the transport has and it costs 2% on loopback and 13% across the
OS boundary. Beside it, `device-test` against the remote handle -
every format, opcode and attribute, the partition invariants, the
awkward reduction lengths - **2,248 checks, 0 failed**, and
`remote-test`'s own protocol suite **245 checks, 0 failures**.

**(b) The workload chains, local against loopback.** Each tool prints a
SHA-256 chain over its records; `matches` in the last column means the
chain also equals the one `bindings/wasm/demos_chains.json` recorded on
2026-09-04 for that configuration.

| configuration | chains | local (s) | loopback (s) | recorded | library calls |
|---|---|---|---|---|---|
| collatz trajectory | same | 0.92 | 3.91 | matches | 2,437 |
| collatz sweep | same | 0.75 | 5.76 | matches | 178 |
| zoom fp256 | same | 56.49 | 69.08 | matches | 1 for the orbit |
| zoom fp64 | same | 19.77 | 23.46 | matches | 1 for the orbit |
| orbits fp256 | same | 1.82 | 2.78 | matches | 23,627 |
| orbits fp64 | same | 1.23 | 2.03 | matches | 23,627 |
| enclose fp32 / fp64 / fp128 / fp256 | same | 0.51 / 0.26 / 0.49 / 0.36 | 0.36 / 0.42 / 0.37 / 0.33 | matches | 189 / 237 / 315 / 453 |
| mersenne to 2281 | same | 7.75 | 58.82 | matches | 1,232,076 |
| collatz sweep, program engine | same | 0.47 | 0.59 | - | 1 |
| zoom fp64, program engine | same | 11.93 | 19.18 | - | 1 for the orbit |
| orbits fp256, program engine | same | 0.63 | 0.92 | - | 1,100 |
| enclose fp256, program engine | same | 0.40 | 0.42 | - | 359 |
| mersenne, program engine | same | 6.41 | 30.27 | - | 438,262 |

The column that matters is the first: **every chain is the same over a
socket**. The column that explains the rest is the last. A tool whose
step is a program pays one frame per call and is barely slower over a
socket; a tool that issues a million library calls pays a million round
trips, and Mersenne's 7.6x is that, not the arithmetic.

**(c) Across the OS boundary.** The same tools against the Linux server
in WSL, which is the case this step exists for - a Windows client
computing on a Linux-hosted device:

| configuration | chains | local (s) | WSL (s) | recorded |
|---|---|---|---|---|
| orbits fp256 | same | 1.19 | 710.79 | matches |
| enclose fp256 | same | 0.13 | 60.86 | matches |
| mersenne to 2281 | same | 3.89 | 941.45 | matches |
| zoom fp256 (32-wide), program engine | same | 1.44 | 400.19 | - |
| collatz sweep, program engine | same | 0.19 | 3.03 | - |
| enclose fp256, program engine | same | 0.11 | 2.52 | - |
| mersenne, program engine | same | 3.16 | 1859.39 | - |

Same chains, every one. The WSL2 boundary costs about 25 microseconds a
round trip where loopback costs about 3, so a call-heavy tool is two to
three orders slower there and a program-shaped one is not. This is the
measurement that says what the remote backend is for: **programs, not
per-element traffic** - which is what the sequencer was built for, and
what docs/ROADMAP.md's third tier assumes.

**(d) The round trips themselves.** From the server's own counters, one
call at a time:

| operation | elements | RUN | PROG_RUN | REDUCE | frames |
|---|---|---|---|---|---|
| run fma | any | 1 | 0 | 0 | 1 |
| div, program route | 4,096 | 0 | 1 | 0 | 3 |
| div, chunk route (`CFT_DIVSQRT_SEQ=0`) | 4,096 | 21 | 0 | 0 | 21 |
| sqrt, program route | 4,096 | 0 | 1 | 0 | 3 |
| sqrt, chunk route | 4,096 | 32 | 0 | 0 | 32 |
| rint | 4,096 | 4 | 0 | 0 | 4 |
| scaleb, cmp_sig | 4,096 | 1 | 0 | 0 | 1 |
| formatof_add | 4,096 | 128 | 0 | 0 | 128 |

So the program route is what makes a composed operation affordable
remotely: **one frame where the chunk route needs twenty-one or
thirty-two**, and it is the default here as it is on the XRT backend.
The raw costs: one fp64 element per `cft_run`, 22.5 microseconds a call
(44,444 calls/s); 4,096 elements per call, 1.40 ms (2,925,714
elements/s). A batch amortises the socket the way it amortises
everything else.

## The runner stage

`verify/run.sh`'s `remote` stage, in the quick budget: build the
server and the client tools, then hand the server's lifecycle to
`host/tests/remote_check.py`, which starts a loopback server on a free
port as its own child, records its PID in the run directory
(`remote-server.pid`), replays a bounded vector set through it and
locally and compares the two reports, runs `device-test` and
`remote-test` against it, runs one workload both ways and compares
the chains, reads the round-trip counts on both routes, and stops the
server by the recorded PID - never by image name, on a host where
other people's processes share the image names.

## The negative control

Two sabotages of the CLIENT, each applied to a scratch copy of
`host/` so the worktree's own binaries stayed honest, each built and
run against the Linux server in the `cft2204` distro (the same server
every green result below used), and then the same copy unsabotaged.
The scripts are the session's; the edits are one line each in
`host/src/backend_remote.c`.

**One bit of one returned encoding.** After `cftr_run` has copied a
`RUN` response into the caller's buffer - after the crc has passed -
flip the low bit of the first element's first byte:

    pd[off * esz] ^= 0x01;   /* SABOTAGE */

Result: `device-test cft://localhost:7755 -n 16` fails 305 of its
2,248 checks, the first at `fp32 fma 0 element 0 of 16`;
`cft-selftest` on a 14-set bounded replay fails on its FIRST case,
`expected 0xff800000 got 0xff800001`, and the replay stops there;
`cft-collatz --engine loop` refuses to finish its remote run (exit 2:
its own exactness witness no longer agrees with the flags) where the
local run prints chain `c2ccab68...`; `remote-test` fails 174 of 245
checks, every one a `BYTES DIFFER`. Nothing about the transport
noticed - the crc was correct, the frame was well formed - which is
the point: the bit identity is checked by the replay, the harness and
the chains, and a client that lies about a result is caught by
exactly those.

**A wrong frame length.** Have every `RUN` request's header claim one
byte more than its payload holds:

    hh.length = (uint32_t)len + (h->op == CFTR_OP_RUN ? 1u : 0u);

Result: the server waits its stall timeout for the byte that never
comes, refuses the frame as truncated, and closes; the client reports
`the server refused the request: truncated frame ... this remote
handle is finished; close it and open it again` with
`CFT_ERR_TIMEOUT`, and every later call on that handle refuses.
`device-test` fails 532 checks (the first `RUN` on each handle, then
everything after it on the poisoned handle), `cft-selftest` checks 0
cases and reports `CONFORMANCE FAILED: timed out`, the Collatz remote
run dies in its first `cft_scaleb`, and `remote-test` fails 174 checks
with `status 0/7` - CFT_OK locally, CFT_ERR_TIMEOUT remotely. No
frame with a wrong length was ever computed on.

**Restored.** The same scratch copy with the sabotage lines removed,
against the same server: `device-test` 2,248 checks, 0 failed; the
bounded replay 14 sets, 80,283 cases, all matching; the Collatz sweep
chain `c2ccab682e3747261561871ee0f99d3b3d43f88fa7fa4de18eff7e46a0555c51`
local and remote - which is also the chain
`bindings/wasm/demos_chains.json` recorded for that configuration on
2026-09-04; `remote-test` 245 checks, 0 failures.
