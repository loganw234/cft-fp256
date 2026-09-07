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

**The caps block** (72 bytes): `u32 format_mask, u32 op_groups,
u32 tiles, u32 device_version, u32 flags_readable, u32 abi,
char backend[32]`, then `u32 max_deposits, u32 max_insns,
u32 max_consts, u32 seq_features` - the server's device as
`cft_get_caps` reports it, with `op_groups` derived by asking
`cft_supports` one representative opcode per group, and `backend` the
NAME OF THE SERVER'S BACKEND (`software`, `xrt`), NUL-padded. The
client reports its own backend as `remote` and keeps the server's name
for the message a failure carries.

**The block grows by appending, and a client reads what it
recognises.** It was 56 bytes until 2026-09-07, when the sequencer's
on-chip capacities were added (docs/HOSTAPI.md, docs/SEQUENCER.md);
the client accepts any block of at least the original 56 and leaves
the fields a shorter one does not carry at zero, which `cft_caps`
documents as UNKNOWN and against which nothing is enforced. A block
shorter than 56 is not an older version, it is a stream that is not a
caps block, and the connection ends.

**`CFTR_PROTO_VERSION` does not move for this**, and that is
deliberate. The `proto` field is compared for EQUALITY at both ends,
so bumping it would turn "an older server answers with a shorter
block" into "an older server refuses the connection" - the opposite of
the tolerance the length rule buys. What the length rule cannot do is
make an older CLIENT read a longer block: it checks for exactly 56 and
calls anything else a protocol fault. That pairing is already refused
one field earlier, by the ABI equality check every frame carries -
appending to `cft_caps` is an ABI minor step, and two libraries whose
ABI differs have never been allowed to talk. So the tolerance is
insurance for the next growth rather than a live compatibility path
today, and no old-server pairing has been built or simulated here.

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
the caps block and the client's `cft_get_caps` says so. The same is
true of the sequencer capacities: a server fronting a tile reports the
tile's 64 deposit slots a lane, a server fronting the software backend
reports 2^20, and in both cases it is the CLIENT's
`cft_program_load` that refuses an image past them - before a frame is
sent, with the cap named.

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
