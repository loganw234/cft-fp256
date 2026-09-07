# host/fuzz - the parsers that face untrusted bytes

Four places in this repository read bytes somebody else wrote:

| what | where | what it reads |
| --- | --- | --- |
| the server | `host/tools/cft-serve.c` | frames off a socket (docs/REMOTE.md) |
| the client | `host/src/backend_remote.c` | a server's replies, off the same socket |
| the loader | `host/src/program.c` | a program image (docs/SEQUENCER.md) |
| five workloads | `host/tools/{collatz,enclose,mersenne,orbits,zoom}.c` | a checkpoint they wrote, and something else may have rewritten |

Nothing else in libcft parses a blob: every other entry point takes
arguments, and an argument that is wrong is the caller's mistake.
These four are different, and until 2026-09-07 none of them had been
fuzzed.

Everything here is **opt-in**. No target is a prerequisite of `all`,
nothing is added to `TOOLS`, and a default build of libcft still needs
one C99 compiler and nothing else.

    make -C host fuzz          build the three in-process harnesses
    make -C host fuzz-run      run each for FUZZ_SECONDS (default 60)
    make -C host fuzz-ckpt     the five workload tools' --resume readers
    make -C host fuzz-repro    replay every checked-in reproducer

## Which engine, and why not libFuzzer

libFuzzer needs clang. There is no clang on either machine this
repository is built on - not on `PATH`, not in `/c/msys64/clang64`, not
in `/c/msys64/mingw64`, and not in the `cft-sim` image - and the image
carries no AFL++ either. Installing one would have made the fuzz lane
depend on a toolchain the rest of the repository is careful not to
need.

What both toolchains do carry is gcc with
`-fsanitize=address,undefined` and gcc's `-fsanitize-coverage=trace-pc`.
That is enough for the part of libFuzzer that matters here, and
`cft_fuzz.c` is it: an AFL-style edge map hashed from the return
address of the instrumentation call, hit counts bucketed 1/2/3/4-7/…,
a corpus that grows whenever an input reaches a bucket nothing else
reached, and havoc mutation over that corpus. Roughly 6,000 to 8,500
executions a second per target on this desktop, which is a tenth of
what libFuzzer manages and about six orders of magnitude more than the
protocol had seen before.

`cft_fuzz.c` is the one translation unit built WITHOUT the coverage
flag: an instrumented `__sanitizer_cov_trace_pc` calls itself until
the stack ends.

The Windows toolchain (MSYS2 mingw64 gcc) has neither sanitiser, so the
fuzz lane runs inside the `cft-sim` image (gcc 13, Linux). The
harnesses compile on Windows too, without sanitisers, which is worth
much less; say so rather than implying otherwise.

### What the coverage feedback does not cover

`fuzz_ckpt.py` drives the workload tools as PROCESSES, because each
tool's `ckpt_read` is static inside its own main file and a resume is a
whole-process act anyway. There is no coverage feedback there - it is
black-box mutation at about three resumes a second. The mutation is
structure-aware instead: a checkpoint is one key per line with counted
blocks after `batchrecords` and `inflight`, and the mutator works on
keys, tokens and counts rather than on bytes.

## The targets

**`fuzz_serve.c`** includes `tools/cft-serve.c` whole, with its
`main()` renamed out of the way, and calls the request handlers
directly. Including it rather than refactoring it is deliberate: the
handlers are static, and a harness that needs no diff cannot conflict
with anybody editing that file. An input is a sequence of

    u16 op | u32 length | length bytes of payload

against ONE connection, so state a single frame cannot reach -
BUF_WRITE into a buffer BUF_ALLOC made, PROG_RUN against a handle
PROG_LOAD returned - is reachable.

Two harness-side policies, stated because they change what is tested:
REPEAT immediates inside a PROG_LOAD image are clamped to 1..8, and a
RUN/REDUCE/PROG_RUN that names no operand has its lane count trimmed to
4096. Both keep the budget in the decoders rather than in arithmetic
the decoders were right to start. Neither changes what the server
ACCEPTS, and the second one hides a real property of the protocol that
is written up in docs/VALIDATION.md instead.

**`fuzz_client.c`** includes `src/backend_remote.c` for the same
reason - `rdev` and `do_request` are static - and gives the client a
socketpair whose far end is filled with the fuzzer's bytes and then
half-closed, so every `recv` returns those bytes or EOF and nothing
blocks. Four modes, chosen by the input's first byte: `cftr_recv_frame`
alone (the framing BOTH ends use), `cft_run`'s chunked reply,
`cft_reduce`'s, and a program's PROG_LOAD-then-PROG_RUN pair. The
second byte says how much of the stream to repair - magic, version and
ABI, the length field, the id and opcode, the crc - so both the frames
a client accepts and every reason it has for refusing one are reachable.

**`fuzz_program.c`** loads whole images through `cft_program_load`. It
does not RUN them: a validated program may legally describe 2^40
instructions, so "it did not finish" would be evidence of nothing.
`--verdict FILE...` prints one line per file saying whether the C
loader took it.

**`program_differential.py`** is the differential arm. The oracle is
`python/cft_golden/seq.py`, which is the definition of what a program
is; an image one loader accepts and the other refuses is a device
executing something the host believed it had rejected.
`host/tests/seq_check.py` already asks that question about valid
programs and nine named corruptions of them; this asks it about mutated
bytes, repaired only far enough to get past the header. That is how the
multiplication in `seq_validate`'s worst-case bound was found to wrap.

**`fuzz_ckpt.py`** mutates each tool's own checkpoint and resumes from
it. The contract being tested is the one the tools state: a malformed
checkpoint must produce a NAMED REFUSAL - the tool's `die()` message
and exit 2 - never a crash, never a hang, and never a silent resume
from a state the file did not describe.

## Layout

    cft_fuzz.[ch]              the engine (uninstrumented)
    fuzz_serve.c               cft-serve's request handlers
    fuzz_client.c              backend_remote.c's response parsing
    fuzz_program.c             cft_program_load
    program_differential.py    the C loader against the golden model
    fuzz_ckpt.py               the five tools' --resume readers
    make_seeds.py              writes corpus/{program,serve,client}
    run.sh run_ckpt.sh repro.sh leaks.sh   (run through `sh`, as
                                            verify/run.sh is: this
                                            repository does not carry
                                            the executable bit)
    corpus/<target>/           seeds, plus whatever the engine kept
    crashes/<target>/          reproducers, checked in when small
    bin/                       the sanitised workload tools (built, not checked in)

`crashes/` holds the reproducer for every finding in
docs/VALIDATION.md's 2026-09-07 entry. `make -C host fuzz-repro`
replays them; a fix that is reverted makes it print a sanitiser report
and exit nonzero.

## Running one target by hand

    cd host/fuzz
    ./fuzz-program --seconds 300 --seed 7 --corpus corpus/program \
                   --crashes crashes/program
    ./fuzz-program --run crashes/program/crash-0000000b00001234
    sh run.sh 300 serve             # one target, restarting on a crash
    sh repro.sh                     # the regression gate
    sh leaks.sh                     # the corpus once, with LSan on

`run.sh` restarts a harness that a crash ended, so the rest of the
budget is still spent fuzzing; the corpus persists across restarts.
It sets `allocator_may_return_null=1` on purpose - a BUF_ALLOC of two
exabytes is a request `cft_alloc` is right to refuse with
CFT_ERR_OUT_OF_MEMORY, and without that ASan aborts on the size and the
fuzzer spends its budget re-finding a policy. `detect_leaks=0` for the
same kind of reason: the engine's corpus is deliberately never freed,
so LeakSanitizer at exit would be reporting the fuzzer rather than the
target.
