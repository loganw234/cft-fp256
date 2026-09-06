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
  and this one is a transport, not a security boundary.
- **One connection at a time.** The server accepts a connection, opens
  a library device for it, serves requests until the client closes,
  closes the device, and accepts the next. A second client waits in the
  listen backlog. Every request on a connection is answered before the
  next is read, so the wire is a strict request/response sequence and
  a request id is a check rather than a scheduler.
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
before `length` bytes arrive is a truncated frame and is refused. A
payload whose length does not match what its opcode requires - a `RUN`
whose operand bytes are not `n` elements of the format's width - is
refused by the operation's decoder.

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

    cft-serve [--port N] [--bind ADDR] [--artifact PATH] [--max-conns N] [--verbose]

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

## The runner stage

`verify/run.sh`'s `remote` stage, in the quick budget: build the
server and the client tools, start a loopback server as a background
process on a port derived from the stage's own process id, record its
PID in the run directory, replay a bounded vector set through it and
locally and compare the two reports, run one workload both ways and
compare the chains, run `device-test` against it, and stop the server
by the recorded PID - never by image name, on a host where other
people's processes share the image names.
