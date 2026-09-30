/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cft-orbits - symplectic few-body integration where the roundoff
 * floor and the method's truncation error are two SEPARATELY
 * MEASURABLE numbers.
 *
 *   ./cft-orbits --problem kepler --periods 64
 *   ./cft-orbits --problem outer --years 300 --format fp64
 *   ./cft-orbits --scheme yoshida4 --engine program --rsqrt newton
 *   ./cft-orbits --checkpoint run.ckpt --resume
 *
 * ---------------------------------------------------------------
 * Why this workload, on this contract
 * ---------------------------------------------------------------
 *
 * A symplectic integrator has two error sources and they behave
 * completely differently:
 *
 *   TRUNCATION is a property of the METHOD. Stormer-Verlet is second
 *   order, so its energy error is O(h^2) and - because the scheme is
 *   symplectic - it OSCILLATES with the orbit rather than growing. It
 *   is the same number in every arithmetic; it does not care how many
 *   bits you have.
 *
 *   ROUNDOFF is a property of the ARITHMETIC. It has no reason to
 *   cancel, so it accumulates: the energy random-walks and the phase
 *   drifts secularly. In binary64 that drift buries the method's own
 *   error after a few million steps, and from then on a long
 *   integration is measuring the floating-point format rather than
 *   the physics.
 *
 * Split them and each becomes a number:
 *
 *   truncation  =  ||(300-digit run of THIS scheme)  -  exact orbit||
 *   roundoff    =  ||(this format's run)  -  (300-digit run of the
 *                    same scheme from the same starting bits)||
 *
 * The second line is what this tool exists to measure, and it is why
 * binary256 is interesting here: at p = 237 the roundoff term is
 * 2^184 times smaller than binary64's, which puts it far below the
 * truncation error for any integration a person would actually run.
 * The method's error becomes the ONLY error, which is the condition
 * under which a step-size study means what it says.
 *
 * host/tests/orbits_check.py is the oracle: mpmath at 300 digits,
 * running the identical discrete scheme from the identical starting
 * ENCODINGS, plus - for the Kepler problem - the closed form through
 * Kepler's equation, so both terms above are measured rather than
 * assumed.
 *
 * ---------------------------------------------------------------
 * The two problems
 * ---------------------------------------------------------------
 *
 * --problem kepler   A test particle around a unit point mass at the
 *   origin, in the plane. mu = 1, semi-major axis a = 1, eccentricity
 *   e = 3/4 - a dyadic rational, so 1-e and 1+e are exact in every
 *   format and only the initial speed needs rounding. The initial
 *   condition is Hairer, Lubich and Wanner's (Geometric Numerical
 *   Integration, 2nd ed., section I.2.2), which starts the particle
 *   at PERIapsis with the velocity perpendicular to the radius:
 *
 *       q = (1-e, 0)        v = (0, sqrt((1+e)/(1-e)))
 *
 *   which gives H = -1/2 and L = sqrt(1-e^2) exactly, and period
 *   T = 2*pi. With e = 3/4 the speed is sqrt(7), the one initial
 *   value that is not exact - and it is delivered by cft_sqrt,
 *   correctly rounded.
 *
 *   The two zeros in that initial condition are not a convenience:
 *   they are what lets the sequencer run this problem at all. See
 *   "Where the step runs" below.
 *
 * --problem outer    The outer solar system: Sun (carrying the inner
 *   planets' mass), Jupiter, Saturn, Uranus, Neptune, in heliocentric
 *   coordinates, AU and days, from the same book's section I.2.3.
 *   The gravitational constant is NOT transcribed: it is k^2, the
 *   square of the IAU 1976 Gaussian gravitational constant
 *   k = 0.01720209895, computed here by one multiply. The positions,
 *   velocities and masses ARE transcribed - they are measurements,
 *   not derivable - so orbits_check.py validates them physically,
 *   recovering each planet's osculating semi-major axis and period
 *   from its own (r, v) and comparing against the published sidereal
 *   periods. A typo in the table moves a period by percent.
 *
 * ---------------------------------------------------------------
 * The scheme
 * ---------------------------------------------------------------
 *
 * --scheme leapfrog is Stormer-Verlet in its drift-kick-drift form,
 * one force evaluation per step:
 *
 *       q += (h/2) v ;  v += h a(q) ;  q += (h/2) v
 *
 * --scheme yoshida4 is Yoshida's fourth-order composition of it,
 *
 *       S4(h) = S2(w1 h) . S2(w0 h) . S2(w1 h)
 *       w1 = 1/(2 - 2^(1/3))      w0 = -2^(1/3)/(2 - 2^(1/3))
 *
 * with 2^(1/3) delivered by cft_rootn (754-2019 9.2's rootn,
 * correctly rounded) and w0, w1 composed from it by cft_div and
 * cft_run - derived, never typed. The adjacent drifts of two
 * neighbouring substeps are deliberately NOT merged: merging is a
 * different sequence of roundings, and the point of the exercise is
 * that the sequence of roundings is the contract.
 *
 * Two schemes over one arithmetic is the whole argument: the same
 * roundoff floor sits under two different truncation errors, so a
 * plot of one against the other separates them by construction.
 *
 * ---------------------------------------------------------------
 * 1/r^3, and where the rounding goes
 * ---------------------------------------------------------------
 *
 * Every kick needs G m / r^3 for every pair. r^2 comes from one
 * multiply and (ndim-1) fused multiply-adds; what happens next is
 * --rsqrt:
 *
 *   --rsqrt exact (the default)      s = cft_sqrt(r2)
 *                                    w = r2 * s          (= r^3)
 *                                    g = cft_div(K, w)
 *     Two CORRECTLY ROUNDED composed operations and one multiply:
 *     three roundings for the whole factor. cft_sqrt and cft_div are
 *     the library's own compositions of the tile's seed opcodes and
 *     its FMA (docs/HOSTAPI.md, python/cft_golden/sequences.py), so
 *     every rounding in them is the contract's.
 *
 *   --rsqrt newton                   y = CFT_RSQRT_SEED(r2)
 *                                    n x { y = y + (y/2)(1 - r2 y^2) }
 *                                    g = K * y^3
 *     A fixed, published Newton refinement from the tile's own seed
 *     opcode. NOT correctly rounded - it is a documented composition
 *     with a few ulps of its own - but every instruction in it is an
 *     ALU opcode, which is what makes it expressible on-chip. The
 *     iteration count is DERIVED from the format's p by iterating the
 *     seed's stated relative error bound 2^-8.5 through the Newton
 *     error recurrence e -> 1.5 e^2 until it passes 2^-(p+2); it is
 *     never tabulated.
 *
 * Measured on the software backend, --rsqrt exact costs about 2.2x
 * what --rsqrt newton costs at binary256 (docs/ORBITS.md), and it is
 * still the default: correct rounding is the contract's product, the
 * factor is a factor and not an order, and the exact route is the one
 * whose error the reader can bound from the standard rather than from
 * this file.
 *
 * ---------------------------------------------------------------
 * Where the step runs: three engines, one arithmetic
 * ---------------------------------------------------------------
 *
 * --engine loop issues every operation as a cft_run / cft_sqrt /
 * cft_div pass over the ensemble. It runs both problems, both
 * schemes, both routes, and it is the reference the two program
 * engines are held to.
 *
 * --engine program compiles the whole integration into ONE orbit
 * sequencer program (docs/SEQUENCER.md) per batch: the ensemble is
 * loaded into lane registers once, every step executes from the
 * instruction memory, and the sampled states come back through the
 * deposit stream. It is restricted to `--problem kepler --rsqrt
 * newton` without --resume, and it stays that way on purpose: its
 * image is the one the browser demos rebuild instruction for
 * instruction and whose digest bindings/wasm/verify_demos.mjs records
 * as taken from this tool (docs/DEMOS.md), so it is kept exactly as
 * it was written (2026-09-04).
 *
 * --engine segments (2026-09-25) is the program engine rebuilt on
 * revision 3's per-lane scratch block (cft_program_run_ex's
 * scratch_in and scratch_out, docs/SEQUENCER.md R5): the ensemble
 * STATE enters every run through the scratch block and leaves the
 * same way, so a run is a SEGMENT of steps from any state this tool
 * can hold. That answers (1) below, and it is what lets a program
 * engine run the outer solar system, resume from a checkpoint either
 * engine wrote, stop at any step, run any sample interval, and record
 * any number of samples: a segment deposits nothing, so the tile's
 * deposit budget no longer bounds a run. Segments are driven by the
 * loop engine's own control loop - the same checkpoints, the same
 * records, the same chain - and their arithmetic is the loop engine's
 * instruction for instruction ("The integration as resumable
 * segments", below).
 *
 * The two facts that restricted the program engine when it was
 * written (2026-09-04), and where each stands:
 *
 *   (1) THREE INPUT STREAMS. cft_program_run initialises r0, r1 and
 *       r2 from a, b and c; r3..r31 start at +0, normatively (r3..r15
 *       before the sequencer's revision 2 doubled the file). A
 *       Hamiltonian system with d degrees of freedom has 2d state
 *       values per lane, and 2d > 3 for everything here: 4 for the
 *       planar Kepler problem, 30 for the outer solar system. So a
 *       program can be ENTERED only at a state with at most three
 *       non-zero components. The Kepler initial condition has exactly
 *       two - q = (1-e, 0), v = (0, v0) - and the registers that must
 *       hold the zeros are the ones that start at +0, so step 0 is
 *       reachable and no later step is. That is why the program
 *       engine runs the whole integration in one call and cannot
 *       resume into the middle of one, and it is why the outer solar
 *       system has no program engine at all. Revision 3's scratch
 *       block (cft_program_run_ex's scratch_in; docs/SEQUENCER.md,
 *       "What the workloads asked of the program model") lets a
 *       program be entered at any state it can spell. --engine
 *       program still calls cft_program_run, for the reason above;
 *       --engine segments is the engine that uses the block.
 *
 *   (2) CORRECTLY ROUNDED DIVIDE AND SQUARE ROOT WERE NOT PROGRAMS.
 *       python/cft_golden/seqprogs.py - which is the library's own
 *       in-program cft_div/cft_sqrt - partitions the route as HOST
 *       prep (operand classification and the prenormalise/centre
 *       surgery), PROGRAM core, HOST finish (round_pack, the
 *       contract's single rounding authority). The core alone uses
 *       r0..r12 of the thirty-two registers a lane owns. So that
 *       route cannot be inlined inside a larger program's loop body:
 *       it needs the host between its halves. Since 2026-09-14
 *       python/cft_golden/divfull.py (in libcft, divsqrt.c's
 *       full_via_program over divfull_images.h, opt-in by
 *       CFT_DIVSQRT_FULL=1) computes each as ONE program, prep and
 *       round_pack in the instruction stream, no host between. It
 *       uses r0..r31, and revision 3's scratch is where a live set
 *       larger than the register file spills, so room for the orbit
 *       state beside it is not a model limit either. What is missing
 *       is the splice: those two are WHOLE programs - operands from
 *       the streams, results and flags as deposits, all thirty-two
 *       registers and their own constants - and putting one inside
 *       another program's loop body needs a fragment inliner that
 *       relocates their registers and constants and turns their
 *       deposits into moves. That does not exist yet, in this tool or
 *       anywhere in the tree, so --rsqrt exact is still a loop-engine
 *       route and both program engines refuse it by name. --rsqrt
 *       newton exists so that all three engines have a step they can
 *       run - which they must run bit for bit.
 *
 * Under --rsqrt newton the three engines produce byte-identical
 * records, byte-identical checkpoints and the same chain wherever each
 * can run. host/tests/orbits_check.py holds segments against the loop
 * engine at all four formats, and the program engine against it at
 * binary256, on the problems, schemes, batch sizes, segment lengths,
 * stop points, relays and interruptions it names - evidence for the
 * claim, not every configuration there is.
 *
 * ---------------------------------------------------------------
 * Flags: which are expected, which are certificates
 * ---------------------------------------------------------------
 *
 * NOTHING HERE IS EXACT. Every drift, every kick, every step of the
 * refinement rounds, so CFT_FLAG_INEXACT is EXPECTED on essentially
 * every call and carries no information. Saying so is the point: a
 * tool that treated inexact as a fault here would be lying about its
 * own workload, and one that never mentioned flags would be hiding
 * the four that DO mean something.
 *
 * The certificates are the other four. Over this workload
 *
 *   INVALID      would mean a NaN reached the arithmetic;
 *   DIVBYZERO    would mean r reached zero - a collision;
 *   OVERFLOW     would mean the integration went unstable;
 *   UNDERFLOW    would mean a value fell into the subnormals, which
 *                for state of order 1 (Kepler) or 1e-3..1e2 (outer)
 *                cannot happen while the integration is sane.
 *
 * so every one of them is checked on every call and any of them stops
 * the run. They are the workload's exception-flag gate, and they are
 * cheap because the library computes them anyway.
 *
 * Beside them sit the three certificates that are NOT flags, and they
 * are the ones that carry the result:
 *
 *   - the two invariants, energy and angular momentum, whose drift is
 *     reported per period at every format;
 *   - agreement with the 300-digit run of the same scheme, in ulps,
 *     which is what orbits_check.py scores;
 *   - bit identity between engines and across batch sizes.
 *
 * ---------------------------------------------------------------
 * Determinism
 * ---------------------------------------------------------------
 *
 * The ensemble advances in LOCKSTEP: one library call per operation
 * per step per batch chunk, so --batch is purely how many ensemble
 * members ride in one call and can never reach a result. Nothing
 * reduces across ensemble members. Records are chained in
 * (sample, member) order, which is fixed by construction and not by
 * the schedule. The checkpoint carries results and nothing about the
 * machine, so two runs at different batch sizes end on byte-identical
 * files - which `make -C host orbitstest` checks rather than asserts.
 *
 * No constant below is transcribed except the published initial
 * conditions, which are measurements and are cited. p is measured
 * from the library, pi comes from cft_acos(-1), 2^(1/3) from
 * cft_rootn, the Gaussian constant is squared rather than copied, the
 * Newton iteration count is derived from p, and SHA-256's round
 * constants are computed from the cube roots of the primes by
 * host/src/sha256.c, the one copy this tool shares with collatz.c.
 *
 * ---------------------------------------------------------------
 * Certified runs (2026-09-30)
 * ---------------------------------------------------------------
 *
 * --cert CERT --cert-states DIR (--cert-salt SALT | --cert-open), on
 * --engine segments --rsqrt newton, writes a version-1 certificate
 * (docs/CERTIFICATES.md) when the run completes: one run, `main`, whose
 * image is the one seg_build makes for the STRIDE and whose segments
 * are the sample intervals, each with its start and end state's hash,
 * its flag word and its STATUS. The engine may run an interval as
 * several shorter segments (the loader's limit, the checkpoint clock)
 * and in batch chunks; the interval's word is the OR of every run's
 * and chunk's, and an audit re-runs it whole, as one run of the stride
 * image over every lane. That the two agree is the claim the gate
 * holds (orbits_check.py [8]): a step hands the next nothing but the
 * scratch block and the q registers, which the image loads and stores
 * without rounding, and an image for k steps differs from the stride's
 * in its trip count alone (docs/ORBITS.md, "Certified runs").
 *
 * What a certified run does beyond an ordinary one:
 *   - stream a is +0, an explicit zero buffer (cft_run_args' `a` may
 *     not be NULL), where an ordinary run hands q_0 - which LDL
 *     overwrites before anything reads it, so nothing it computes
 *     differs, and the certificate's stream hashes are what ran;
 *   - DIR holds the image, run-0.cftp, and each boundary's state,
 *     run-0-boundary-<b>.bin, written as it is reached - the files
 *     cft-audit --states and cert.audit read;
 *   - its checkpoint is version 3: version 2's lines, then the
 *     certificate so far (the `cert` block), then a `sum` line over the
 *     whole file, which a resume requires;
 *   - the certificate is written only when the run completes, into
 *     CERT.tmp and then moved to CERT without replacing anything, by
 *     whichever process completes it - so a stop or a kill writes none,
 *     and a resumed run writes the uninterrupted run's bytes.
 * Every refusal of the certified path prints "cft-orbits: refused
 * <name>: <why>" and exits with the name's code (CERT_REFUSAL, below).
 */
#if !defined(_WIN32)
#  define _POSIX_C_SOURCE 200112L   /* 199309L hid snprintf on Darwin (2026-09-09) */
#endif

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdarg.h>
#include <inttypes.h>
#include <errno.h>

#include "cft.h"
#include "../src/sha256.h"
#include "cert_write.h"

/* The system's own words for the last failure, kept for a refusal that
 * names its cause: strerror() here, FormatMessage on Windows (below). */
static char SYS_ERR[320];

static void note_errno(int e)
{
    snprintf(SYS_ERR, sizeof SYS_ERR, "%s",
             e ? strerror(e) : "no reason given");
}

/* CFT_ORBITS_SHARE_FIFO (the test instruments, below): the records file
 * is taken to be what the WSL share makes of a Linux FIFO. */
static int SHARE_FIFO = 0;

/* The clock, and what the checkpoint and the records file need from
 * the system: how long an open file is, whether a path names a regular
 * file, which file a path or a stream is, opening a file for writing
 * without cutting it and then cutting it to nothing, cutting a file
 * back to a length (--resume, "The checkpoint format" in
 * docs/ORBITS.md), renaming a file over another, and ending the
 * process as a kill would. A length of -1 means "not a regular file" -
 * a pipe or a device, which has none to check.
 *
 * path_kind is 1 for a regular file, 0 for anything else that is there
 * (a pipe, a FIFO, a device, a directory) and -1 when nothing can be
 * asked of the path (it does not exist, or may not be opened). It
 * never reads: POSIX asks stat(), which does not open a FIFO. Windows'
 * _stat64 calls NUL, CON and a named pipe regular files, so the path is
 * opened and GetFileType asked - which, for a named pipe, connects to
 * an instance and hangs up (a server sees a client come and go). */
#if defined(_WIN32)
#  include <windows.h>
#  include <sys/stat.h>
#  include <io.h>
static double now_s(void)
{
    LARGE_INTEGER f, t;
    QueryPerformanceFrequency(&f);
    QueryPerformanceCounter(&t);
    return (double)t.QuadPart / (double)f.QuadPart;
}

static int64_t file_length(FILE *f)
{
    struct _stat64 st;
    if (_fstat64(_fileno(f), &st) != 0 ||
        (st.st_mode & _S_IFMT) != _S_IFREG)
        return -1;
    return (int64_t)st.st_size;
}

static int path_kind(const char *path)
{
    const DWORD share = FILE_SHARE_READ | FILE_SHARE_WRITE |
                        FILE_SHARE_DELETE;
    BY_HANDLE_FILE_INFORMATION bi;
    HANDLE h;
    int regular;

    /* attributes alone first; a console will not open without access */
    h = CreateFileA(path, FILE_READ_ATTRIBUTES, share, NULL, OPEN_EXISTING,
                    FILE_FLAG_BACKUP_SEMANTICS, NULL);
    if (h == INVALID_HANDLE_VALUE &&
        GetLastError() == ERROR_INVALID_PARAMETER)
        h = CreateFileA(path, GENERIC_READ, share, NULL, OPEN_EXISTING,
                        FILE_FLAG_BACKUP_SEMANTICS, NULL);
    if (h == INVALID_HANDLE_VALUE)
        return GetLastError() == ERROR_PIPE_BUSY ? 0 : -1;
    regular = GetFileType(h) == FILE_TYPE_DISK &&
              GetFileInformationByHandle(h, &bi) &&
              !(bi.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY);
    CloseHandle(h);
    return regular;
}

/* Which file a path or an open stream is - the volume and the file's
 * index on it - so two spellings of one file are seen to be one.
 * `path` is only opened for its attributes, and only a path that must
 * be a regular file or nothing is handed here (never a pipe's name). */
static int handle_id(HANDLE h, uint64_t id[2])
{
    BY_HANDLE_FILE_INFORMATION bi;
    if (h == INVALID_HANDLE_VALUE || !GetFileInformationByHandle(h, &bi))
        return 0;
    id[0] = bi.dwVolumeSerialNumber;
    id[1] = ((uint64_t)bi.nFileIndexHigh << 32) | bi.nFileIndexLow;
    return 1;
}

static int file_id(const char *path, FILE *open_file, uint64_t id[2])
{
    HANDLE h;
    int ok;
    if (open_file)
        return handle_id((HANDLE)_get_osfhandle(_fileno(open_file)), id);
    h = CreateFileA(path, FILE_READ_ATTRIBUTES, FILE_SHARE_READ |
                    FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL,
                    OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, NULL);
    ok = handle_id(h, id);
    if (h != INVALID_HANDLE_VALUE)
        CloseHandle(h);
    return ok;
}

static void note_win_error(DWORD e)
{
    char text[256];
    DWORD n = FormatMessageA(FORMAT_MESSAGE_FROM_SYSTEM |
                             FORMAT_MESSAGE_IGNORE_INSERTS, NULL, e, 0,
                             text, sizeof text, NULL);
    while (n && (text[n - 1] == '\r' || text[n - 1] == '\n' ||
                 text[n - 1] == ' ' || text[n - 1] == '.'))
        text[--n] = 0;
    snprintf(SYS_ERR, sizeof SYS_ERR, "%s, Windows error %lu",
             n ? text : "no text for it", (unsigned long)e);
}

/* A file opened for writing WITHOUT being cut, and created if it is not
 * there, so that which file it is can be asked of the open handle
 * before a byte of it is lost (main, where --records is opened). The
 * access and the sharing are fopen's "wb"; OPEN_ALWAYS, not
 * CREATE_ALWAYS, is the only difference - and a named pipe or a device
 * is opened as "wb" opened it, once. One more: CREATE_ALWAYS refuses a
 * hidden file, which "wb" therefore could not write; this writes it. */
static FILE *open_uncut(const char *path)
{
    HANDLE h = CreateFileA(path, GENERIC_WRITE,
                           FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
                           OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    FILE *f;
    int fd;
    if (h == INVALID_HANDLE_VALUE) {
        note_win_error(GetLastError());
        return NULL;
    }
    fd = _open_osfhandle((intptr_t)h, 0);
    if (fd < 0) {
        note_errno(errno);
        CloseHandle(h);
        return NULL;
    }
    f = _fdopen(fd, "wb");
    if (!f) {
        note_errno(errno);
        _close(fd);
    }
    return f;
}

/* A regular file cut to nothing, as "wb" would have cut it. A pipe or a
 * device has nothing to cut, and neither has a file that says it is
 * empty - which is not a formality: Windows is told a Linux FIFO seen
 * through the WSL share is an empty regular file, and the share refuses
 * to cut it ("the parameter is incorrect", measured 2026-09-27), so
 * bc00d8d, which cut it all the same, refused a fresh run into it that
 * had streamed until then (verifier-V6, 2026-09-26). Under
 * CFT_ORBITS_SHARE_FIFO the file says 0 bytes and the cut is refused
 * with that same error. */
static int file_empty(FILE *f)
{
    HANDLE h = (HANDLE)_get_osfhandle(_fileno(f));
    LARGE_INTEGER zero, size;
    if (GetFileType(h) != FILE_TYPE_DISK)
        return 0;
    if (SHARE_FIFO)
        size.QuadPart = 0;
    else if (!GetFileSizeEx(h, &size))
        size.QuadPart = -1;             /* not known: cut it */
    if (size.QuadPart == 0)
        return 0;
    if (SHARE_FIFO) {
        note_win_error(ERROR_INVALID_PARAMETER);
        return -1;
    }
    zero.QuadPart = 0;
    if (!SetFilePointerEx(h, zero, NULL, FILE_BEGIN) || !SetEndOfFile(h)) {
        note_win_error(GetLastError());
        return -1;
    }
    return 0;
}

static int file_cut(const char *path, uint64_t len)
{
    HANDLE h = CreateFileA(path, GENERIC_WRITE, 0, NULL, OPEN_EXISTING,
                           FILE_ATTRIBUTE_NORMAL, NULL);
    LARGE_INTEGER at;
    int ok;
    if (h == INVALID_HANDLE_VALUE)
        return -1;
    at.QuadPart = (LONGLONG)len;
    ok = SetFilePointerEx(h, at, NULL, FILE_BEGIN) && SetEndOfFile(h);
    return CloseHandle(h) && ok ? 0 : -1;
}

/* Another process that holds the target open for a moment - a virus
 * scanner, a sync agent, anything that stat()s it - fails the rename.
 * What MoveFileEx returns then is ERROR_ACCESS_DENIED (measured, for a
 * stat()-style open and for readers, delete-sharing or not);
 * ERROR_SHARING_VIOLATION is retried too. Verifier-V6, 2026-09-25: 8
 * runs of 8 killed so under a tight os.stat poll. The rename is tried
 * again - ten times at once, then twenty milliseconds apart - until
 * RENAME_RETRY_S seconds have passed on the clock since it first
 * failed, and then the run gives up by name. A deadline, not a count:
 * d56ecbe's sixty tries lasted as long as the scheduler made each
 * sleep - 1.55 s on a quiet desktop, up to 4.88 s with a game holding
 * the CPU at 100%, and once past a 5 s hold (verifier-V6, 2026-09-25).
 * Past the deadline the retry costs one more sleep - however long a
 * busy scheduler makes that one - and one more try, not sixty of each.
 * now_s() is the wall's clock under every test instrument. */
#define RENAME_RETRY_S 1.5
static int file_replace(const char *tmp, const char *path)
{
    double until = 0;
    int tries;
    for (tries = 0;; tries++) {
        DWORD e;
        if (MoveFileExA(tmp, path, MOVEFILE_REPLACE_EXISTING))
            return 0;
        e = GetLastError();
        if (e != ERROR_SHARING_VIOLATION && e != ERROR_ACCESS_DENIED)
            return -1;
        if (!tries)
            until = now_s() + RENAME_RETRY_S;
        else if (now_s() >= until)
            return -1;
        Sleep(tries < 10 ? 0 : 20);
    }
}
#else
#  include <time.h>
#  include <sys/stat.h>
#  include <fcntl.h>
#  include <unistd.h>
static double now_s(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

static int64_t file_length(FILE *f)
{
    struct stat st;
    if (fstat(fileno(f), &st) != 0 || !S_ISREG(st.st_mode))
        return -1;
    return (int64_t)st.st_size;
}

static int path_kind(const char *path)
{
    struct stat st;
    if (stat(path, &st) != 0)
        return -1;
    return S_ISREG(st.st_mode) ? 1 : 0;
}

static int file_id(const char *path, FILE *open_file, uint64_t id[2])
{
    struct stat st;
    if (open_file ? fstat(fileno(open_file), &st) != 0
                  : stat(path, &st) != 0)
        return 0;
    id[0] = (uint64_t)st.st_dev;
    id[1] = (uint64_t)st.st_ino;
    return 1;
}

/* fopen's "wb" without O_TRUNC: which file it is can be asked before a
 * byte is lost (main, where --records is opened). A FIFO blocks here
 * until it has a reader, as "wb" did. */
static FILE *open_uncut(const char *path)
{
    int fd = open(path, O_WRONLY | O_CREAT, 0666);
    FILE *f;
    if (fd < 0) {
        note_errno(errno);
        return NULL;
    }
    f = fdopen(fd, "wb");
    if (!f) {
        note_errno(errno);
        close(fd);
    }
    return f;
}

/* As on Windows: a regular file that says it is empty is not cut, and
 * CFT_ORBITS_SHARE_FIFO makes the file say 0 bytes and refuse the cut
 * (EINVAL, which is what ftruncate() gives for a file it cannot cut). */
static int file_empty(FILE *f)
{
    struct stat st;
    if (fstat(fileno(f), &st) != 0) {
        note_errno(errno);
        return -1;
    }
    if (!S_ISREG(st.st_mode))
        return 0;
    if ((SHARE_FIFO ? 0 : st.st_size) == 0)
        return 0;
    if (SHARE_FIFO) {
        note_errno(EINVAL);
        return -1;
    }
    if (ftruncate(fileno(f), 0) != 0) {
        note_errno(errno);
        return -1;
    }
    return 0;
}

static int file_cut(const char *path, uint64_t len)
{
    FILE *f = fopen(path, "r+b");
    int rc;
    if (!f)
        return -1;
    rc = (uint64_t)(off_t)len == len ? ftruncate(fileno(f), (off_t)len)
                                     : -1;
    if (fclose(f) != 0)
        rc = -1;
    return rc;
}

/* rename() over a file other processes hold open succeeds here */
static int file_replace(const char *tmp, const char *path)
{
    return rename(tmp, path);
}
#endif

/* The process ends at once, as a kill would leave it: no buffered
 * output flushed, no exit handler run. Only CFT_ORBITS_DIE_AFTER_
 * CHECKPOINT (below) asks for it. Not _exit() on Windows: it goes
 * through ExitProcess, and msvcrt flushes every stream as it unloads -
 * which a kill does not do (measured: the records reached the file).
 * TerminateProcess is what taskkill and Python's kill() call. */
static void end_as_killed(void)
{
#if defined(_WIN32)
    TerminateProcess(GetCurrentProcess(), 9);
#endif
    _exit(9);
}

#define MAX_ESZ    32     /* bytes in the widest element, binary256 */
#define MAX_BODIES  8
#define MAX_DIM     3
#define MAX_COMP    (MAX_BODIES * MAX_DIM)
#define DECMAX   2048     /* one exact decimal, generously */

static void die(const char *what)
{
    fprintf(stderr, "cft-orbits: %s\n", what);
    exit(2);
}

static void die_st(const char *what, cft_status st)
{
    const char *d = cft_last_error();
    fprintf(stderr, "cft-orbits: %s: %s%s%s\n", what, cft_strerror(st),
            (d && *d) ? " - " : "", (d && *d) ? d : "");
    exit(2);
}

static void *xcalloc(size_t n, size_t sz)
{
    void *p = calloc(n ? n : 1, sz ? sz : 1);
    if (!p)
        die("out of memory");
    return p;
}

/* ===================================================================
 * The certified path's refusals (the header's "Certified runs")
 *
 * The page's name where the page names the defect (docs/CERTIFICATES.md,
 * "Refusals"), and cft-segrun's own name and code where it has one for
 * the same condition ("The segment runner"); the rest are this tool's.
 * Each prints "cft-orbits: refused <name>: <why>" and exits with the
 * name's code. `width` has the page's 3, which the flag certificate's
 * exit shares; the name tells them apart. None has 9, the kill
 * instrument's. A checkpoint that does not describe this run is the
 * checkpoint reader's to refuse, as it always was: a sentence, and exit 2
 * (ckpt_read).
 * =================================================================== */
#if defined(__GNUC__)
#  define ORB_NORETURN __attribute__((noreturn))
#else
#  define ORB_NORETURN
#endif

static const struct { const char *name; int code; } CERT_REFUSAL[] = {
    /* the page's */
    { "malformed", 2 }, { "width", 3 },
    { "salt-length", 4 }, { "salt-missing", 4 }, { "salt-unexpected", 4 },
    { "salt-commitment", 4 }, { "image-digest", 4 },
    { "program-digest", 4 }, { "program-image", 4 }, { "state-shape", 4 },
    { "state-hash", 4 }, { "state-missing", 4 },
    { "accuracy-run", 7 }, { "accuracy-scope", 7 }, { "accuracy-slot", 7 },
    { "accuracy-finite", 7 },
    /* what this tool cannot certify, and why is in the sentence */
    { "rsqrt-exact", 64 }, { "engine", 64 }, { "step-halving", 64 },
    { "wider", 64 }, { "energy-drift", 64 },
    /* the tool's own: cft-segrun's usage, device, memory, output and
     * build-width */
    { "usage", 64 }, { "device", 69 }, { "memory", 71 }, { "output", 73 },
    { "build-width", 78 },
    /* a resume on another build or device than the certificate names */
    { "identity", 78 },
};

/* CERT.tmp, which a certified run creates before anything else and moves
 * to CERT when the run completes; a process that ends otherwise removes
 * it (atexit), and one killed leaves it, empty, for the next to cut. */
static char  *CERT_TMP = NULL;
static FILE  *CERT_TMP_FP = NULL;

static void cert_cleanup(void)
{
    if (CERT_TMP_FP) {
        fclose(CERT_TMP_FP);
        CERT_TMP_FP = NULL;
        remove(CERT_TMP);
    }
}

static void refuse(const char *name, const char *fmt, ...)
    ORB_NORETURN CW_PRINTF_LIKE(2, 3);

static void refuse(const char *name, const char *fmt, ...)
{
    va_list ap;
    size_t i;
    int code = -1;
    for (i = 0; i < sizeof CERT_REFUSAL / sizeof CERT_REFUSAL[0]; i++)
        if (!strcmp(CERT_REFUSAL[i].name, name))
            code = CERT_REFUSAL[i].code;
    if (code < 0) {
        fprintf(stderr, "cft-orbits: internal error: unnamed refusal '%s'\n",
                name);
        exit(70);
    }
    fprintf(stderr, "cft-orbits: refused %s: ", name);
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fputc('\n', stderr);
    exit(code);
}

/* A library call of the certified path that failed, with its sentence. */
static void refuse_st(const char *name, const char *what, cft_status st)
    ORB_NORETURN;

static void refuse_st(const char *name, const char *what, cft_status st)
{
    const char *d = cft_last_error();
    refuse(name, "%s: %s%s%s", what, cft_strerror(st), (d && *d) ? " - " : "",
           (d && *d) ? d : "");
}

/* A cert_write.h function that returned a name: refused by it. */
static void cert_ok(const char *why, const char *what)
{
    if (why)
        refuse(why, "%s", what);
}

/* ===================================================================
 * SHA-256, from the library
 *
 * There were four copies of this hash in host/tools, one per workload
 * tool and all byte-identical, plus the one cft_program_digest wanted.
 * They are now one, in host/src/sha256.c, together with the constant
 * derivation the standing rule asks for - SHA-256's eight initial
 * words and sixty-four round constants are SPECIFIED as the fractional
 * parts of the square and cube roots of the first primes, so that is
 * how they are computed, by integer search with no floating point and
 * nothing to mistype.
 *
 * Below is the whole adaptation: this file's own three names, bound to
 * the library's. Not one byte of the chain this tool prints changed in
 * the move, and host/tests/orbits_check.py recomputes every line of it
 * with Python's hashlib, which is what proves that.
 * =================================================================== */
typedef cft_sha256_ctx sha256;
#define sha256_start(s)       cft_sha256_init(s)
#define sha256_push(s, d, n)  cft_sha256_update((s), (d), (n))
#define sha256_end(s, o)      cft_sha256_final((s), (o))


static void hex32(const uint8_t in[32], char out[65])
{
    static const char D[] = "0123456789abcdef";
    int i;
    for (i = 0; i < 32; i++) {
        out[2 * i]     = D[in[i] >> 4];
        out[2 * i + 1] = D[in[i] & 15];
    }
    out[64] = 0;
}

static int unhex32(const char *in, uint8_t out[32])
{
    int i;
    for (i = 0; i < 64; i++) {
        int c = (unsigned char)in[i], v;
        if (c >= '0' && c <= '9')      v = c - '0';
        else if (c >= 'a' && c <= 'f') v = c - 'a' + 10;
        else if (c >= 'A' && c <= 'F') v = c - 'A' + 10;
        else return 0;
        if (i & 1) out[i / 2] = (uint8_t)(out[i / 2] | v);
        else       out[i / 2] = (uint8_t)(v << 4);
    }
    return in[64] == 0;
}

/* ===================================================================
 * Format parameters, measured rather than tabulated
 * =================================================================== */
typedef struct {
    cft_format fmt;
    size_t     esz;
    int        width;
    int        prec;     /* p, significand bits, hidden one included */
    int        newton;   /* refinement passes, derived from p */
} fmt_info;

static cft_device *DEV;
static uint32_t    FLAGS_SEEN = 0;
static int         FLAGS_TRUSTED = 1;
static uint64_t    N_CALLS = 0;      /* library calls issued */
static uint64_t    N_ELEMOPS = 0;    /* elementwise opcode issues */
static uint64_t    N_COMPOSED = 0;   /* cft_div / cft_sqrt element calls */
static uint64_t    STEPS_DONE = 0;   /* steps taken in this process - the
                                        test clock's time (VCLOCK below) */

/* Every arithmetic instruction in this workload rounds, so INEXACT is
 * EXPECTED and says nothing. The other four are certificates: none of
 * them can arise from a sane integration of either problem, so any of
 * them stops the run rather than being folded into a summary. */
#define EXPECTED_FLAGS  ((uint32_t)CFT_FLAG_INEXACT)
#define CERT_FLAGS      ((uint32_t)(CFT_FLAG_INVALID | CFT_FLAG_DIVBYZERO | \
                                    CFT_FLAG_OVERFLOW | CFT_FLAG_UNDERFLOW))

static void note_flags(uint32_t f, const char *what)
{
    FLAGS_SEEN |= f;
    if (FLAGS_TRUSTED && (f & CERT_FLAGS)) {
        fprintf(stderr,
                "cft-orbits: %s raised 0x%02x - this workload can only ever "
                "raise inexact, so invalid, divide-by-zero, overflow or "
                "underflow means the integration or the tool is wrong "
                "(docs/ORBITS.md, \"Flags\")\n", what, (unsigned)f);
        exit(3);
    }
}

static void measure_format(fmt_info *fi, cft_format fmt)
{
    uint8_t one[MAX_ESZ], pow[MAX_ESZ], sum[MAX_ESZ];
    int64_t i1 = 1;
    int k;
    cft_status st;

    memset(fi, 0, sizeof *fi);
    fi->fmt = fmt;
    fi->esz = cft_format_size(fmt);
    if (!fi->esz || fi->esz > MAX_ESZ)
        die("unknown format");
    fi->width = (int)fi->esz * 8;

    st = cft_cvt_from_i64(DEV, fmt, CFT_RNE, &i1, one, 1, NULL);
    if (st != CFT_OK)
        die_st("cft_cvt_from_i64", st);

    /* p is the smallest k for which 2^k + 1 is not representable, and
     * the library answers that question itself, in the flag it raises. */
    fi->prec = 0;
    for (k = 1; k < fi->width; k++) {
        uint32_t fl = 0;
        st = cft_scaleb(DEV, fmt, CFT_RNE, one, k, pow, 1, NULL, NULL);
        if (st != CFT_OK)
            die_st("cft_scaleb", st);
        st = cft_run(DEV, CFT_ADD, fmt, CFT_RNE, pow, NULL, one, sum, 1,
                     &fl, NULL);
        if (st != CFT_OK)
            die_st("cft_run", st);
        if (fl & CFT_FLAG_INEXACT) {
            fi->prec = k;
            break;
        }
    }
    if (!fi->prec)
        die("could not measure the format's precision");

    /* The Newton refinement count, derived, in integers, and
     * conservative at every step.
     *
     * CFT_RSQRT_SEED's stated relative error is below 2^-8.5
     * (host/include/cft.h), so the seed is good to at least EIGHT
     * bits - the weaker integer bound, deliberately, so that nothing
     * here needs an irrational constant. The Newton-Raphson step for
     * 1/sqrt takes a relative error e to 1.5 e^2 + O(e^3), and
     * 1.5 * (2^-b)^2 < 2^-(2b-1), so a step at least DOUBLES the
     * correct bits and loses at most one. Iterating b -> 2b - 1 from
     * 8 until it passes p + 2 is therefore an upper bound on the
     * passes needed and never a lower one, and it is what the format
     * asked for rather than what somebody remembered. */
    {
        int bits = 8;
        fi->newton = 0;
        while (bits < fi->prec + 2) {
            bits = 2 * bits - 1;
            fi->newton++;
            if (fi->newton > 32)
                die("the Newton refinement did not converge - impossible");
        }
    }
}

/* ===================================================================
 * Values
 * =================================================================== */
static void run1(cft_op op, const fmt_info *fi, const void *a, const void *b,
                 const void *c, void *d)
{
    uint32_t fl = 0;
    cft_status st = cft_run(DEV, op, fi->fmt, CFT_RNE, a, b, c, d, 1, &fl,
                            NULL);
    if (st != CFT_OK)
        die_st("cft_run", st);
    FLAGS_SEEN |= fl;
}

static void val_from_i64(const fmt_info *fi, int64_t v, uint8_t *out)
{
    uint32_t fl = 0;
    cft_status st = cft_cvt_from_i64(DEV, fi->fmt, CFT_RNE, &v, out, 1, &fl);
    if (st != CFT_OK)
        die_st("cft_cvt_from_i64", st);
    if (fl & CFT_FLAG_INEXACT)
        die("an integer constant was not exact in this format");
}

static void val_pow2(const fmt_info *fi, int e, uint8_t *out)
{
    uint8_t one[MAX_ESZ];
    cft_status st;
    val_from_i64(fi, 1, one);
    st = cft_scaleb(DEV, fi->fmt, CFT_RNE, one, e, out, 1, NULL, NULL);
    if (st != CFT_OK)
        die_st("cft_scaleb", st);
}

/* The exact decimal of one value, 5.12.2's digits = 0 conversion.
 * Every binary float is a finite decimal, so this is the value
 * itself and not a rendering of it - which is what makes a
 * checkpoint round trip lossless and a record comparable against a
 * 300-digit oracle. */
static void val_to_dec(const fmt_info *fi, const void *v, char *out,
                       size_t cap)
{
    size_t len = 0;
    cft_status st = cft_to_decimal_char(DEV, fi->fmt, CFT_RNE, v, 0, out,
                                        cap, &len, NULL);
    if (st != CFT_OK)
        die_st("cft_to_decimal_char", st);
}

/* A short decimal, for human-readable summary lines only. Never used
 * for a record, a chain or a checkpoint. */
static void val_to_dec_short(const fmt_info *fi, const void *v, char *out,
                             size_t cap, size_t digits)
{
    size_t len = 0;
    cft_status st = cft_to_decimal_char(DEV, fi->fmt, CFT_RNE, v, digits,
                                        out, cap, &len, NULL);
    if (st != CFT_OK)
        die_st("cft_to_decimal_char", st);
}

static int val_from_dec_ok(const fmt_info *fi, const char *s, void *out,
                           int require_exact)
{
    const char *arr[1];
    uint32_t fl = 0;
    cft_status st;
    arr[0] = s;
    st = cft_from_decimal_char(DEV, fi->fmt, CFT_RNE, arr, out, 1, NULL, &fl);
    if (st != CFT_OK)
        return 0;
    if (require_exact && (fl & (CFT_FLAG_INEXACT | CFT_FLAG_OVERFLOW)))
        return 0;
    return 1;
}

/* An initial condition is a decimal literal from a published table.
 * It is converted once, correctly rounded, and the rounding is
 * expected - the table is a measurement, not a binary value. */
static void val_from_dec(const fmt_info *fi, const char *s, void *out)
{
    if (!val_from_dec_ok(fi, s, out, 0))
        die("an initial-condition literal could not be converted");
}

static int val_lt(const fmt_info *fi, const void *a, const void *b)
{
    uint8_t r[MAX_ESZ], zero[MAX_ESZ];
    run1(CFT_CMPLT, fi, a, b, NULL, r);
    memset(zero, 0, fi->esz);
    return memcmp(r, zero, fi->esz) != 0;
}

/* ===================================================================
 * The problems
 *
 * The Kepler initial condition is derived from the eccentricity, a
 * dyadic rational, so only the speed needs rounding. The outer solar
 * system's table is TRANSCRIBED, with its source, and validated
 * physically by host/tests/orbits_check.py: a mistyped digit moves an
 * osculating period by percent, and the check compares against the
 * published sidereal periods.
 *
 * Hairer, Lubich and Wanner, "Geometric Numerical Integration:
 * Structure-Preserving Algorithms for Ordinary Differential
 * Equations", 2nd edition (Springer, 2006), sections I.2.2 (Kepler)
 * and I.2.3 (the outer solar system). Masses are in solar masses,
 * lengths in AU, times in days; the Sun's mass carries the inner
 * planets.
 * =================================================================== */
enum { PROB_KEPLER = 0, PROB_OUTER = 1 };

#define ECC_NUM  3        /* eccentricity 3/4: dyadic, so 1-e and 1+e */
#define ECC_DEN  4        /* are exact in every format */

typedef struct {
    const char *name;
    const char *mass;     /* solar masses, decimal literal */
    const char *q[3];
    const char *v[3];
} body_row;

/* HLW section I.2.3. The Sun starts at rest at the origin, so the
 * barycentre drifts - that is the published setup, and the total
 * energy and total angular momentum are conserved regardless. */
static const body_row OUTER[] = {
    { "Sun",     "1.00000597682",
      { "0", "0", "0" },
      { "0", "0", "0" } },
    { "Jupiter", "0.000954786104043",
      { "-3.5023653", "-3.8169847", "-1.5507963" },
      { "0.00565429", "-0.00412490", "-0.00190589" } },
    { "Saturn",  "0.000285583733151",
      { "9.0755314", "-3.0458353", "-1.6483708" },
      { "0.00168318", "0.00483525", "0.00192462" } },
    { "Uranus",  "0.0000437273164546",
      { "8.3101420", "-16.2901086", "-7.2521278" },
      { "0.00354178", "0.00137102", "0.00055029" } },
    { "Neptune", "0.0000517759138449",
      { "11.4707666", "-25.7294829", "-10.8169456" },
      { "0.00288930", "0.00114527", "0.00039677" } }
};
#define N_OUTER ((int)(sizeof OUTER / sizeof OUTER[0]))

/* The IAU 1976 Gaussian gravitational constant. G in AU^3 day^-2
 * Msun^-1 is k^2, so this is squared rather than the square being
 * transcribed. */
#define GAUSS_K  "0.01720209895"

/* ===================================================================
 * The run
 * =================================================================== */
enum { SCHEME_LEAPFROG = 0, SCHEME_YOSHIDA4 = 1 };
enum { RSQRT_EXACT = 0, RSQRT_NEWTON = 1 };
enum { ENG_LOOP = 0, ENG_PROGRAM = 1, ENG_SEGMENTS = 2 };
#define MAX_SUB 3

typedef struct {
    int         problem, scheme, rsqrt, engine;
    cft_format  fmt;
    size_t      members, batch;
    uint64_t    spread;
    uint64_t    steps_per_period, periods;   /* kepler */
    uint64_t    days, years;                 /* outer */
    uint64_t    sample_every;
    uint64_t    steps_opt;                   /* --steps override */
    const char *ckpt;
    double      ckpt_interval;
    int         resume;
    long        stop_after_samples, stop_after_steps;
    const char *records_path;
    const char *artifact;
    const char *segment_dump;                /* --segment-dump DIR */
    int         csv, quiet, dump_setup;
    /* a certified run (the header's "Certified runs") */
    const char *cert_path;                   /* --cert CERT */
    const char *cert_states;                 /* --cert-states DIR */
    const char *cert_salt_path;              /* --cert-salt SALT */
    int         cert_open;                   /* --cert-open */
    const char *cert_accuracy;               /* --cert-accuracy METHOD */
} options;

typedef struct {
    const fmt_info *fi;
    options        *O;

    int      nb, nd, ncomp;     /* bodies, dims, components = nb*nd */
    int      nsub;              /* composition substeps */
    int      nL;                /* angular-momentum components */

    uint64_t nsteps, nsamples, stride;

    /* ensemble state, SoA: comp c of member m at (c*M + m) */
    uint8_t *q, *v;
    /* scratch, all M-wide */
    uint8_t *d[MAX_DIM], *x, *y, *w, *e, *z, *g, *t1, *t2, *acc;

    /* broadcast constants, M-wide */
    uint8_t *c_hd[MAX_SUB];     /* w_i * h / 2   (drift) */
    uint8_t *c_mg[MAX_SUB];     /* -(w_i * h * mu)                kepler */
    uint8_t *c_hm[MAX_SUB][MAX_BODIES];   /*  w_i*h*m_b           outer */
    uint8_t *c_mhm[MAX_SUB][MAX_BODIES];  /* -(w_i*h*m_b)         outer */
    uint8_t *c_G, *c_mu, *c_half, *c_mone, *c_mhalf;
    uint8_t *c_m[MAX_BODIES], *c_halfm[MAX_BODIES];
    uint8_t *c_gmm[MAX_BODIES][MAX_BODIES];

    /* scalar copies (1 element) of the things the summary prints */
    uint8_t  s_h[MAX_ESZ];      /* the step size */

    /* per-member invariants and their extremes */
    uint8_t *H0, *L0[3], *Hd, *Ld[3], *dHmax, *dLmax[3];
    uint8_t *q0, *v0;           /* the initial ensemble, for separations */

    /* progress */
    uint64_t step, sample;
    uint8_t  chain[32];
    uint64_t rec_bytes;         /* the record stream so far, in bytes -
                                   what --records holds, or would */
    FILE    *recf;

    /* the program engine */
    cft_program *prog;
    uint8_t     *dep;
    uint32_t    *depcount;
    uint32_t     n_insns, max_deposits;
    uint64_t     alu_per_step;   /* ALU issues one step costs a lane */

    /* the segments engine: the loaded images, one per segment length
     * a run has needed lately (SEG_CACHE of them, the least recently
     * used replaced), so a length is built and loaded once however
     * often it recurs. What the census reports is read off an image
     * itself (seg_census), not counted while building it. */
#define SEG_CACHE 8
    cft_program *sprog[SEG_CACHE];
    uint64_t     sprog_k[SEG_CACHE], sprog_used[SEG_CACHE];
    uint8_t     *sin, *sout;          /* one batch of scratch blocks */
    uint32_t     s_insns, s_consts, s_slots, s_regs;
    uint64_t     s_alu_step, s_ctl_step;   /* inside the REPEAT body */
    uint64_t     s_runs;              /* cft_program_run_ex calls */
    uint64_t     s_loads;             /* images built and loaded */
    uint64_t     s_segments;          /* segments run, the cache's clock */
    int          s_dumped;            /* --segment-dump written */
    uint64_t     s_kmax;              /* longest segment the loader takes */
    double       s_sec_per_step;      /* the last segment's, 0 untimed */

    /* a certified run: the certificate so far (the header's "Certified
     * runs"). Segment k is sample interval k: it starts on boundary k
     * and ends on boundary k + 1, and its word and STATUS are the OR of
     * every run and chunk the engine ran inside it. */
    int          cert;                /* --cert given */
    uint8_t     *salt;                /* 32 bytes, or NULL: open */
    char         commitment[CW_HEX];  /* keyed: HMAC(salt, TAG_SALT) */
    uint8_t     *c_image;             /* the stride's image, and its size */
    size_t       c_image_bytes;
    cw_identity  c_id;
    cw_text      c_ident;             /* `mode` .. `device-tiles` */
    cw_text      c_runhead;           /* `program-format` .. `segments S` */
    char       (*c_bhash)[CW_HEX];    /* boundary 0 .. nsamples, as reached */
    uint32_t    *c_flags, *c_status;  /* each closed interval's */
    uint32_t     c_iflags, c_istatus; /* the interval in progress, so far */
    uint64_t     c_replace_from;      /* a resumed run replaces boundary
                                         files past its checkpoint's */
    uint8_t     *c_zero;              /* stream a, +0, one chunk long */
    uint8_t     *c_state;             /* one boundary, lane-major */
    size_t       c_state_bytes;
    int          c_written;           /* the certificate is at CERT */
    /* --cert-accuracy angular-momentum-drift: a drift entry for each
     * component of the angular momentum, over run 0, the maximum over its
     * lanes, exact (cert_entries) */
    int          c_angmom;
    unsigned     c_n_entries;
#if CX_EXACT
    entry_t      c_entries[3];
    term_t      *c_terms;             /* each entry's, 2 a body */
    rat          c_q[3];              /* each entry's value, derived */
#endif
    const char  *c_labels[3];
} runstate;

/* ---- chunked library calls ---------------------------------------
 * Every elementwise operation goes through here, and it is the only
 * place --batch appears. n is always the ensemble size; the chunking
 * is the library-call boundary and nothing else, which is what makes
 * batch-size independence a property of every operation rather than
 * of the tool's outer loop. */
static void opN(runstate *R, cft_op op, const void *a, const void *b,
                const void *c, void *dst)
{
    const fmt_info *fi = R->fi;
    size_t esz = fi->esz, M = R->O->members, B = R->O->batch, i;
    for (i = 0; i < M; i += B) {
        size_t n = M - i < B ? M - i : B;
        uint32_t fl = 0;
        cft_status st = cft_run(DEV, op, fi->fmt, CFT_RNE,
                                a ? (const uint8_t *)a + i * esz : NULL,
                                b ? (const uint8_t *)b + i * esz : NULL,
                                c ? (const uint8_t *)c + i * esz : NULL,
                                (uint8_t *)dst + i * esz, n, &fl, NULL);
        if (st != CFT_OK)
            die_st("cft_run", st);
        note_flags(fl, cft_op_name(op));
        N_CALLS++;
        N_ELEMOPS += n;
    }
}

static void sqrtN(runstate *R, const void *a, void *dst)
{
    const fmt_info *fi = R->fi;
    size_t esz = fi->esz, M = R->O->members, B = R->O->batch, i;
    for (i = 0; i < M; i += B) {
        size_t n = M - i < B ? M - i : B;
        uint32_t fl = 0;
        cft_status st = cft_sqrt(DEV, fi->fmt, CFT_RNE,
                                 (const uint8_t *)a + i * esz,
                                 (uint8_t *)dst + i * esz, n, &fl, NULL);
        if (st != CFT_OK)
            die_st("cft_sqrt", st);
        note_flags(fl, "cft_sqrt");
        N_CALLS++;
        N_COMPOSED += n;
    }
}

static void divN(runstate *R, const void *a, const void *b, void *dst)
{
    const fmt_info *fi = R->fi;
    size_t esz = fi->esz, M = R->O->members, B = R->O->batch, i;
    for (i = 0; i < M; i += B) {
        size_t n = M - i < B ? M - i : B;
        uint32_t fl = 0;
        cft_status st = cft_div(DEV, fi->fmt, CFT_RNE,
                                (const uint8_t *)a + i * esz,
                                (const uint8_t *)b + i * esz,
                                (uint8_t *)dst + i * esz, n, &fl, NULL);
        if (st != CFT_OK)
            die_st("cft_div", st);
        note_flags(fl, "cft_div");
        N_CALLS++;
        N_COMPOSED += n;
    }
}

static uint8_t *alloc_m(runstate *R)
{
    return (uint8_t *)xcalloc(R->O->members, R->fi->esz);
}

static void bcast(runstate *R, uint8_t *dst, const uint8_t *v)
{
    size_t i, esz = R->fi->esz;
    for (i = 0; i < R->O->members; i++)
        memcpy(dst + i * esz, v, esz);
}

static uint8_t *alloc_bcast(runstate *R, const uint8_t *v)
{
    uint8_t *p = alloc_m(R);
    bcast(R, p, v);
    return p;
}

#define CQ(R, c)  ((R)->q + (size_t)(c) * (R)->O->members * (R)->fi->esz)
#define CV(R, c)  ((R)->v + (size_t)(c) * (R)->O->members * (R)->fi->esz)
#define COMP(R, b, k)  ((b) * (R)->nd + (k))

/* ===================================================================
 * 1/r^3, both routes
 *
 * On entry R->x holds r^2 for every member; on exit `dst` holds
 * scale / r^3, where `scale` is a broadcast constant. The two routes
 * are different arithmetic and are not expected to agree - which is
 * why --rsqrt is a run parameter that the checkpoint records.
 * =================================================================== */
static void inv_r3_scaled(runstate *R, const uint8_t *scale, uint8_t *dst)
{
    int k;
    if (R->O->rsqrt == RSQRT_EXACT) {
        sqrtN(R, R->x, R->y);                       /* s   = sqrt(r^2)  */
        opN(R, CFT_MUL, R->x, R->y, NULL, R->w);    /* w   = r^2 * s    */
        divN(R, scale, R->w, dst);                  /* dst = scale / r^3 */
        return;
    }
    /* y0 = seed, then the derived number of Newton passes:
     *      y <- y + (y/2)(1 - x y^2)
     * written as the four ALU opcodes a sequencer program carries. */
    opN(R, CFT_RSQRT_SEED, R->x, NULL, NULL, R->y);
    for (k = 0; k < R->fi->newton; k++) {
        opN(R, CFT_MUL, R->x, R->y, NULL, R->w);            /* w = x*y      */
        opN(R, CFT_FMA, R->w, R->y, R->c_mone, R->e);       /* e = x y^2 -1 */
        opN(R, CFT_MUL, R->y, R->c_mhalf, NULL, R->z);      /* z = -y/2     */
        opN(R, CFT_FMA, R->z, R->e, R->y, R->y);            /* y = y - ye/2 */
    }
    opN(R, CFT_MUL, R->y, R->y, NULL, R->w);                /* w = y^2      */
    opN(R, CFT_MUL, R->w, R->y, NULL, R->w);                /* w = y^3      */
    opN(R, CFT_MUL, R->w, scale, NULL, dst);
}

/* ===================================================================
 * The force, and the substep
 * =================================================================== */
static void kepler_r2(runstate *R)
{
    /* r^2 = q0^2 + q1^2, one multiply and one FMA, in a fixed order */
    opN(R, CFT_MUL, CQ(R, 1), CQ(R, 1), NULL, R->w);
    opN(R, CFT_FMA, CQ(R, 0), CQ(R, 0), R->w, R->x);
}

static void drift(runstate *R, int sub)
{
    int c;
    for (c = 0; c < R->ncomp; c++)
        opN(R, CFT_FMA, R->c_hd[sub], CV(R, c), CQ(R, c), CQ(R, c));
}

static void kick_kepler(runstate *R, int sub)
{
    kepler_r2(R);
    inv_r3_scaled(R, R->c_mg[sub], R->g);   /* g = -(w h mu)/r^3 */
    opN(R, CFT_FMA, R->g, CQ(R, 0), CV(R, 0), CV(R, 0));
    opN(R, CFT_FMA, R->g, CQ(R, 1), CV(R, 1), CV(R, 1));
}

/* Pairs in lexicographic (i, j) order with i < j, and the kick
 * accumulated straight into v as each pair is computed. Both are part
 * of the arithmetic, not of the implementation: a different pair
 * order is a different sequence of roundings and therefore a
 * different (equally valid, equally reproducible) result. */
static void kick_outer(runstate *R, int sub)
{
    int i, j, k;
    for (i = 0; i < R->nb; i++) {
        for (j = i + 1; j < R->nb; j++) {
            for (k = 0; k < R->nd; k++)
                opN(R, CFT_SUB, CQ(R, COMP(R, j, k)), NULL,
                    CQ(R, COMP(R, i, k)), R->d[k]);
            opN(R, CFT_MUL, R->d[R->nd - 1], R->d[R->nd - 1], NULL, R->w);
            for (k = R->nd - 2; k > 0; k--)
                opN(R, CFT_FMA, R->d[k], R->d[k], R->w, R->w);
            opN(R, CFT_FMA, R->d[0], R->d[0], R->w, R->x);
            inv_r3_scaled(R, R->c_G, R->t1);          /* t1 = G / r^3 */
            opN(R, CFT_MUL, R->t1, R->c_hm[sub][j], NULL, R->g);
            for (k = 0; k < R->nd; k++)
                opN(R, CFT_FMA, R->g, R->d[k], CV(R, COMP(R, i, k)),
                    CV(R, COMP(R, i, k)));
            opN(R, CFT_MUL, R->t1, R->c_mhm[sub][i], NULL, R->g);
            for (k = 0; k < R->nd; k++)
                opN(R, CFT_FMA, R->g, R->d[k], CV(R, COMP(R, j, k)),
                    CV(R, COMP(R, j, k)));
        }
    }
}

static void substep(runstate *R, int sub)
{
    drift(R, sub);
    if (R->O->problem == PROB_KEPLER)
        kick_kepler(R, sub);
    else
        kick_outer(R, sub);
    drift(R, sub);
}

static void one_step(runstate *R)
{
    int s;
    for (s = 0; s < R->nsub; s++)
        substep(R, s);
    STEPS_DONE++;
}

/* ===================================================================
 * The invariants
 *
 * Summed in a fixed index order with elementwise adds - never through
 * cft_reduce, whose reduction runs over ELEMENTS, and an element here
 * is an ensemble member.
 * =================================================================== */
static void invariants(runstate *R, const uint8_t *qq, const uint8_t *vv,
                       uint8_t *H, uint8_t *L[3])
{
    const fmt_info *fi = R->fi;
    size_t esz = fi->esz, M = R->O->members;
    int i, j, k;
    const uint8_t *Q, *V;
#define QC(c) (qq + (size_t)(c) * M * esz)
#define VC(c) (vv + (size_t)(c) * M * esz)

    if (R->O->problem == PROB_KEPLER) {
        /* H = (v0^2 + v1^2)/2 - mu/r */
        opN(R, CFT_MUL, VC(1), VC(1), NULL, R->w);
        opN(R, CFT_FMA, VC(0), VC(0), R->w, R->t1);
        opN(R, CFT_MUL, R->t1, R->c_half, NULL, R->t1);
        opN(R, CFT_MUL, QC(1), QC(1), NULL, R->w);
        opN(R, CFT_FMA, QC(0), QC(0), R->w, R->x);
        sqrtN(R, R->x, R->y);
        divN(R, R->c_mu, R->y, R->t2);
        opN(R, CFT_SUB, R->t1, NULL, R->t2, H);
        /* L = q0 v1 - q1 v0 */
        opN(R, CFT_MUL, QC(1), VC(0), NULL, R->w);
        opN(R, CFT_NEG, R->w, NULL, NULL, R->w);
        opN(R, CFT_FMA, QC(0), VC(1), R->w, L[0]);
        return;
    }

    /* KE = sum_b (m_b/2) |v_b|^2, bodies in index order */
    for (i = 0; i < R->nb; i++) {
        opN(R, CFT_MUL, VC(COMP(R, i, R->nd - 1)),
            VC(COMP(R, i, R->nd - 1)), NULL, R->w);
        for (k = R->nd - 2; k >= 0; k--)
            opN(R, CFT_FMA, VC(COMP(R, i, k)), VC(COMP(R, i, k)), R->w,
                R->w);
        opN(R, CFT_MUL, R->w, R->c_halfm[i], NULL, R->t1);
        if (i == 0)
            memcpy(R->acc, R->t1, M * esz);
        else
            opN(R, CFT_ADD, R->acc, NULL, R->t1, R->acc);
    }
    memcpy(H, R->acc, M * esz);
    /* PE = -sum_{i<j} G m_i m_j / r_ij, pairs in the kick's own order */
    for (i = 0; i < R->nb; i++) {
        for (j = i + 1; j < R->nb; j++) {
            for (k = 0; k < R->nd; k++)
                opN(R, CFT_SUB, QC(COMP(R, j, k)), NULL, QC(COMP(R, i, k)),
                    R->d[k]);
            opN(R, CFT_MUL, R->d[R->nd - 1], R->d[R->nd - 1], NULL, R->w);
            for (k = R->nd - 2; k > 0; k--)
                opN(R, CFT_FMA, R->d[k], R->d[k], R->w, R->w);
            opN(R, CFT_FMA, R->d[0], R->d[0], R->w, R->x);
            sqrtN(R, R->x, R->y);
            divN(R, R->c_gmm[i][j], R->y, R->t1);
            opN(R, CFT_SUB, H, NULL, R->t1, H);
        }
    }
    /* L = sum_b m_b (q_b x v_b), components in x, y, z order */
    for (k = 0; k < 3; k++) {
        int k1 = (k + 1) % 3, k2 = (k + 2) % 3;
        for (i = 0; i < R->nb; i++) {
            Q = QC(COMP(R, i, k2));
            V = VC(COMP(R, i, k1));
            opN(R, CFT_MUL, Q, V, NULL, R->w);
            opN(R, CFT_NEG, R->w, NULL, NULL, R->w);
            opN(R, CFT_FMA, QC(COMP(R, i, k1)), VC(COMP(R, i, k2)), R->w,
                R->t1);
            opN(R, CFT_MUL, R->t1, R->c_m[i], NULL, R->t1);
            if (i == 0)
                memcpy(L[k], R->t1, M * esz);
            else
                opN(R, CFT_ADD, L[k], NULL, R->t1, L[k]);
        }
    }
#undef QC
#undef VC
}

/* ===================================================================
 * Records and the hash chain
 *
 *   chain_0     = 32 zero bytes
 *   chain_(i+1) = SHA-256( chain_i || record_i || "\n" )
 *
 * over records in (sample, member) order. That order is fixed by
 * construction and never by the schedule, which is what makes the
 * chain independent of the batch size, of the engine and of where a
 * run was interrupted.
 * =================================================================== */
static void chain_absorb(runstate *R, const char *line)
{
    sha256 h;
    sha256_start(&h);
    sha256_push(&h, R->chain, sizeof R->chain);
    sha256_push(&h, line, strlen(line));
    sha256_push(&h, "\n", 1);
    sha256_end(&h, R->chain);
}

/* Build one record line: sample, step, member, then every state
 * component and every invariant as an EXACT decimal. */
static void record_line(runstate *R, uint64_t sample, uint64_t step,
                        size_t m, const uint8_t *qq, const uint8_t *vv,
                        const uint8_t *H, uint8_t *const L[3],
                        char *out, size_t cap)
{
    const fmt_info *fi = R->fi;
    size_t esz = fi->esz, M = R->O->members, used;
    char dec[DECMAX];
    int c, k, n;

    n = snprintf(out, cap, "%" PRIu64 " %" PRIu64 " %" PRIu64,
                 sample, step, (uint64_t)m);
    if (n <= 0 || (size_t)n >= cap)
        die("record line too long");
    used = (size_t)n;
#define PUT(ptr) do {                                                    \
        val_to_dec(fi, (ptr), dec, sizeof dec);                          \
        if (used + strlen(dec) + 2 >= cap) die("record line too long");   \
        out[used++] = ' ';                                               \
        memcpy(out + used, dec, strlen(dec));                            \
        used += strlen(dec);                                             \
        out[used] = 0;                                                   \
    } while (0)
    for (c = 0; c < R->ncomp; c++)
        PUT(qq + ((size_t)c * M + m) * esz);
    for (c = 0; c < R->ncomp; c++)
        PUT(vv + ((size_t)c * M + m) * esz);
    PUT(H + m * esz);
    for (k = 0; k < R->nL; k++)
        PUT(L[k] + m * esz);
#undef PUT
}

/* ===================================================================
 * One sample: invariants, extremes, records, chain
 * =================================================================== */
static void emit_sample(runstate *R, uint64_t sample, uint64_t step,
                        const uint8_t *qq, const uint8_t *vv)
{
    const fmt_info *fi = R->fi;
    size_t esz = fi->esz, M = R->O->members, m;
    char *line;
    int k;

    invariants(R, qq, vv, R->Hd, R->Ld);

    if (sample == 0) {
        memcpy(R->H0, R->Hd, M * esz);
        for (k = 0; k < R->nL; k++)
            memcpy(R->L0[k], R->Ld[k], M * esz);
    } else {
        opN(R, CFT_SUB, R->Hd, NULL, R->H0, R->t1);
        opN(R, CFT_ABS, R->t1, NULL, NULL, R->t1);
        opN(R, CFT_MAX, R->dHmax, R->t1, NULL, R->dHmax);
        for (k = 0; k < R->nL; k++) {
            opN(R, CFT_SUB, R->Ld[k], NULL, R->L0[k], R->t1);
            opN(R, CFT_ABS, R->t1, NULL, NULL, R->t1);
            opN(R, CFT_MAX, R->dLmax[k], R->t1, NULL, R->dLmax[k]);
        }
    }

    line = (char *)xcalloc(1, (size_t)(2 * R->ncomp + 8) * DECMAX);
    for (m = 0; m < M; m++) {
        record_line(R, sample, step, m, qq, vv, R->Hd, R->Ld, line,
                    (size_t)(2 * R->ncomp + 8) * DECMAX);
        chain_absorb(R, line);
        /* counted whether or not --records is open, so a checkpoint is
         * the same file either way (docs/ORBITS.md, "recbytes") */
        R->rec_bytes += (uint64_t)strlen(line) + 1;
        if (R->recf)
            fprintf(R->recf, "%s\n", line);
    }
    free(line);
}

/* ===================================================================
 * The step as an orbit-sequencer program (Kepler, --rsqrt newton)
 *
 * docs/SEQUENCER.md's encoding. Registers:
 *
 *   r0 = q0   (the a stream)          r4 = r^2
 *   r1 = v1   (the b stream)          r5 = y, the rsqrt iterate
 *   r2 = q1   (the c stream: +0)      r6 = w
 *   r3 = v0   (starts at +0)          r7 = e
 *                                     r8 = z
 *                                     r9 = g
 *
 * The mapping is forced. cft_program_run can initialise only r0, r1
 * and r2, and the Kepler initial condition has exactly two non-zero
 * components, so the two that must be zero are put in registers that
 * start at +0 - r2 by passing c = NULL, r3 because r3..r31 always do.
 * =================================================================== */
enum { R_Q0 = 0, R_V1 = 1, R_Q1 = 2, R_V0 = 3,
       R_X = 4, R_Y = 5, R_W = 6, R_E = 7, R_Z = 8, R_G = 9 };
enum { C_HALT = 0, C_REPEAT, C_ENDREP, C_DEPOSIT, C_SETACT, C_ACTALL };
#define DEPOSITS_PER_SAMPLE 4
/* The deposit ceiling is not a literal here any more. It was 64 -
 * MAXD, copied out of rtl/cft_krnl.sv - which is a number that stops
 * being true the day a tile ships with a different one, and which no
 * tool could check. cft_get_caps publishes it (cft_caps.max_deposits)
 * and this asks. */

static uint64_t alu(int op, int rd, int ra, int rb, int rc,
                    int ka, int kb, int kc)
{
    return (uint64_t)(uint32_t)op |
           ((uint64_t)(uint32_t)rd << 8) |
           ((uint64_t)(uint32_t)ra << 12) |
           ((uint64_t)(uint32_t)rb << 16) |
           ((uint64_t)(uint32_t)rc << 20) |
           ((uint64_t)(uint32_t)(ka ? 1 : 0) << 27) |
           ((uint64_t)(uint32_t)(kb ? 1 : 0) << 28) |
           ((uint64_t)(uint32_t)(kc ? 1 : 0) << 29);
}

static uint64_t ctl(int code, int ra, uint32_t imm)
{
    return (uint64_t)(uint32_t)code |
           ((uint64_t)(uint32_t)ra << 12) |
           ((uint64_t)1 << 31) |
           ((uint64_t)imm << 32);
}

static void put_le32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}

static void put_le64(uint8_t *p, uint64_t v)
{
    put_le32(p, (uint32_t)v);
    put_le32(p + 4, (uint32_t)(v >> 32));
}

/* Constant-bank indices. c_hd[s] and c_mg[s] are per substep, so the
 * bank grows with the composition. */
#define KB_MONE   0
#define KB_MHALF  1
#define KB_HD(s)  (2 + 2 * (s))
#define KB_MG(s)  (3 + 2 * (s))

static uint8_t *build_program(runstate *R, size_t *bytes_out)
{
    const fmt_info *fi = R->fi;
    size_t esz = fi->esz, i, off, nk;
    uint64_t *ins;
    uint32_t n = 0, cap;
    uint8_t *img;
    int s, k;

    nk = (size_t)(2 + 2 * R->nsub);
    cap = (uint32_t)(16 + R->nsub * (16 + 4 * R->fi->newton) + 16);
    ins = (uint64_t *)xcalloc(cap, sizeof(uint64_t));

    /* sample 0: the initial state, before a single step */
    ins[n++] = ctl(C_DEPOSIT, R_Q0, 0);
    ins[n++] = ctl(C_DEPOSIT, R_Q1, 0);
    ins[n++] = ctl(C_DEPOSIT, R_V0, 0);
    ins[n++] = ctl(C_DEPOSIT, R_V1, 0);

    ins[n++] = ctl(C_REPEAT, 0, (uint32_t)R->nsamples);
    ins[n++] = ctl(C_REPEAT, 0, (uint32_t)R->stride);
    for (s = 0; s < R->nsub; s++) {
        ins[n++] = alu(CFT_FMA, R_Q0, KB_HD(s), R_V0, R_Q0, 1, 0, 0);
        ins[n++] = alu(CFT_FMA, R_Q1, KB_HD(s), R_V1, R_Q1, 1, 0, 0);
        ins[n++] = alu(CFT_MUL, R_W, R_Q1, R_Q1, 0, 0, 0, 0);
        ins[n++] = alu(CFT_FMA, R_X, R_Q0, R_Q0, R_W, 0, 0, 0);
        ins[n++] = alu(CFT_RSQRT_SEED, R_Y, R_X, 0, 0, 0, 0, 0);
        for (k = 0; k < fi->newton; k++) {
            ins[n++] = alu(CFT_MUL, R_W, R_X, R_Y, 0, 0, 0, 0);
            ins[n++] = alu(CFT_FMA, R_E, R_W, R_Y, KB_MONE, 0, 0, 1);
            ins[n++] = alu(CFT_MUL, R_Z, R_Y, KB_MHALF, 0, 0, 1, 0);
            ins[n++] = alu(CFT_FMA, R_Y, R_Z, R_E, R_Y, 0, 0, 0);
        }
        ins[n++] = alu(CFT_MUL, R_W, R_Y, R_Y, 0, 0, 0, 0);
        ins[n++] = alu(CFT_MUL, R_W, R_W, R_Y, 0, 0, 0, 0);
        ins[n++] = alu(CFT_MUL, R_G, R_W, KB_MG(s), 0, 0, 1, 0);
        ins[n++] = alu(CFT_FMA, R_V0, R_G, R_Q0, R_V0, 0, 0, 0);
        ins[n++] = alu(CFT_FMA, R_V1, R_G, R_Q1, R_V1, 0, 0, 0);
        ins[n++] = alu(CFT_FMA, R_Q0, KB_HD(s), R_V0, R_Q0, 1, 0, 0);
        ins[n++] = alu(CFT_FMA, R_Q1, KB_HD(s), R_V1, R_Q1, 1, 0, 0);
    }
    ins[n++] = ctl(C_ENDREP, 0, 0);
    ins[n++] = ctl(C_DEPOSIT, R_Q0, 0);
    ins[n++] = ctl(C_DEPOSIT, R_Q1, 0);
    ins[n++] = ctl(C_DEPOSIT, R_V0, 0);
    ins[n++] = ctl(C_DEPOSIT, R_V1, 0);
    ins[n++] = ctl(C_ENDREP, 0, 0);
    ins[n++] = ctl(C_HALT, 0, 0);
    if (n > cap)
        die("the program image outgrew its buffer");

    R->n_insns = n;
    R->max_deposits = (uint32_t)((R->nsamples + 1) * DEPOSITS_PER_SAMPLE);
    R->alu_per_step = (uint64_t)R->nsub * (12 + 4 * (uint64_t)fi->newton);

    *bytes_out = 32 + nk * esz + (size_t)n * 8;
    img = (uint8_t *)xcalloc(*bytes_out, 1);
    img[0] = 'C'; img[1] = 'F'; img[2] = 'T'; img[3] = 'P';
    put_le32(img + 4, 1);
    put_le32(img + 8, n);
    put_le32(img + 12, (uint32_t)nk);
    put_le32(img + 16, R->max_deposits);
    put_le32(img + 20, (uint32_t)fi->fmt);
    off = 32;
    memcpy(img + off + (size_t)KB_MONE * esz, R->c_mone, esz);
    memcpy(img + off + (size_t)KB_MHALF * esz, R->c_mhalf, esz);
    for (s = 0; s < R->nsub; s++) {
        memcpy(img + off + (size_t)KB_HD(s) * esz, R->c_hd[s], esz);
        memcpy(img + off + (size_t)KB_MG(s) * esz, R->c_mg[s], esz);
    }
    off += nk * esz;
    for (i = 0; i < n; i++) {
        put_le64(img + off, ins[i]);
        off += 8;
    }
    free(ins);
    return img;
}

/* ===================================================================
 * The integration as resumable segments (--engine segments)
 *
 * One lane is one ensemble member. Its scratch holds the member's
 * whole state in 2 * ncomp slots - slot c is q_c and slot ncomp + c is
 * v_c, the order the checkpoint writes them - and that block is the
 * run's input and its output (R5), so a run advances the ensemble by
 * k steps from wherever it stands and hands the state back. Nothing is
 * deposited.
 *
 * The program loads every q_c into register c on entry and stores it
 * back on exit. The velocities stay in their slots and are loaded,
 * updated and stored where the arithmetic touches them, because the
 * outer solar system's thirty values and the kick's temporaries do not
 * fit thirty-two registers together:
 *
 *   r0 .. r(ncomp-1)   q, one register per component (at most 15)
 *   r16, r17, r18      d, a pair's separation (outer)
 *   r19 x = r^2   r20 y   r21 w   r22 e   r23 z   r24 g   r25 t1
 *   r26                the velocity component being updated
 *
 * The arithmetic is the loop engine's, instruction for instruction and
 * operand for operand - drift, kick_kepler, kick_outer and the Newton
 * route of inv_r3_scaled - so the engines produce the same bits, and
 * host/tests/orbits_check.py compares them byte for byte. The loads
 * and stores are not arithmetic (docs/SEQUENCER.md R4: no rounding, no
 * flags), so where a value lives cannot reach a result.
 *
 * The constants ride in the image: this tool builds its images per
 * run, so there is nothing a per-run bank (BANK_EXT) would save.
 *
 * How long a segment is - to the sample boundary or the stop point,
 * and no longer than the loader takes or, while checkpoints are
 * written, than fits the time left before the next one is due at the
 * last segment's rate - is decided in main()'s run loop; seg_limits
 * and seg_time_cap carry the two limits, and no result depends on
 * where a segment ends.
 * =================================================================== */

/* Revision 3's scratch pair, beside the six codes above. docs/
 * SEQUENCER.md's numbering, which host/src/program.c keeps in a
 * private enum and this tool copies, as cft-zoom copies the six. What
 * holds a copied number to the contract is the gate, not this comment:
 * orbits_check.py hands the image this engine writes (--segment-dump)
 * to python/cft_golden's assembler, which must read it back to the
 * same bytes, and to its executor, which must compute the same scratch
 * block the library did. */
enum { C_STL = 6, C_LDL = 7 };

#define KOP        0x10000            /* an operand naming a constant */
#define KONST(i)   (KOP | (i))
#define SEG_RQ(c)  (c)                /* q_c's register */
#define SEG_RD(k)  (16 + (k))         /* d_k's register */
enum { SR_X = 19, SR_Y, SR_W, SR_E, SR_Z, SR_G, SR_T1, SR_V };
#define SEG_REGS   (SR_V + 1)
#define SEG_SQ(c)     ((uint32_t)(c))                 /* q_c's slot */
#define SEG_SV(R, c)  ((uint32_t)((R)->ncomp + (c)))  /* v_c's slot */

/* The negative controls this tool carries, read once in main() from
 * CFT_ORBITS_NEGATIVE_CONTROL. Each makes the tool wrong in one named
 * way; orbits_check.py runs each and requires the check it exists for
 * to FAIL. Each prints a warning on stderr whenever it is set, and
 * nothing but that test sets them. The first five sabotage --engine
 * segments and are refused on the other two engines; `append` and
 * `flush-late` sabotage the records beside the checkpoint, which the
 * loop and segments engines share, and are refused on --engine program.
 *
 *   transpose  the host packs v_0 into v_1's slot and v_1 into v_0's -
 *              and unpacks the same way, so its own arrays stay
 *              consistent - the lane-major transposition bug the engine
 *              comparisons exist to catch;
 *   zero-r2    every r^2 the image forms becomes r^2 - r^2 = +0, so the
 *              reciprocal square root meets a zero and the step goes to
 *              NaN: a fault only the flag certificate can see, which is
 *              what shows a segment's flags reach note_flags();
 *   uncapped   segments ignore --checkpoint-interval and run to the
 *              sample boundary, as this engine did before 2026-09-25,
 *              which the interruption tests must see as a lost interval;
 *   late-stop  a segment runs one step past --stop-after-steps, so a
 *              stopped run is a step late wherever a segment, rather
 *              than a sample boundary, ends it;
 *   overlong   the longest segment is taken one step past what the
 *              loader accepts (seg_limits), so the first segment of an
 *              interval that long must be refused;
 *   append     --resume appends to --records without checking it or
 *              cutting it back to the checkpoint, as this tool did
 *              before 2026-09-25, so after a kill the resumed records
 *              are not the run's;
 *   flush-late the records are handed to the system just AFTER the
 *              checkpoint that counts them is renamed into place rather
 *              than before, so a process that ends between the two leaves
 *              the file behind the checkpoint on disk;
 *   drop-flags a certified run's resume takes the interval in progress
 *              as having raised nothing so far, as a checkpoint that did
 *              not carry its flags would, so the interval's word in the
 *              certificate is the resumed runs' alone - which a stop at
 *              an interval's last step makes 0 where the run raised 16,
 *              and the audit refuses (segment-flags). Certified runs only.
 *
 * And one TEST INSTRUMENT of the certified path, CFT_ORBITS_CERT_PLANT,
 * which makes what no backend in this tree does reachable, as
 * CFT_SEGRUN_PLANT does for cft-segrun: `flags-unreadable`, the device
 * taken to be one that cannot read the sticky flags (refused `device`
 * before anything is made); `flags-unwritten`, each segment's flag word
 * taken to be left unwritten by the library (refused `device`);
 * `flags-wide`, each word gaining bit 5, past the five sticky flags
 * (refused `malformed`); and `width`, the first angular-momentum term's
 * coefficient taken times 2^-1000, so that its first product is past the
 * width rule (refused `width`, as the golden writer refuses the same
 * entry). Announced on stderr; refused where there is no --cert, and
 * `width` where there is no --cert-accuracy. */
static int NEGCTL_TRANSPOSE = 0, NEGCTL_ZERO_R2 = 0, NEGCTL_UNCAPPED = 0;
static int NEGCTL_LATE_STOP = 0, NEGCTL_OVERLONG = 0, NEGCTL_APPEND = 0;
static int NEGCTL_FLUSH_LATE = 0, NEGCTL_DROP_FLAGS = 0;
static int PLANT_UNREADABLE = 0, PLANT_UNWRITTEN = 0, PLANT_WIDE = 0;

/* The test instruments, read once in main() from the environment. A
 * negative control makes the tool wrong; an instrument changes only
 * what the tool meets - which the checks that use one hold it right
 * against - and makes something reachable in a test that otherwise is
 * not. Each is off unless set, refused by name when malformed or set
 * where it does not apply, and announced on stderr.
 *
 *   CFT_ORBITS_SEGMENT_LIMIT=N   (--engine segments) the loader is
 *       taken to accept at most N steps a segment, so an interval
 *       longer than N is split where the real limit would split it -
 *       and the real one (seg_limits: 2^32-1 steps, or 2^40
 *       instructions) is hours of work away;
 *   CFT_ORBITS_VIRTUAL_CLOCK=S   (--engine loop and segments) the
 *       clock this tool reads advances S seconds for every step the
 *       ensemble takes and for nothing else, and each checkpoint is
 *       logged on stderr as it is written - a perfectly steady rate,
 *       so where checkpoints fall is a fact a test can predict rather
 *       than a measurement of this machine's load. The run's own report
 *       then gives that clock's time and throughput, not the wall's;
 *   CFT_ORBITS_DIE_AFTER_CHECKPOINT=N   (--engine loop and segments)
 *       the process ends as a kill would - exit 9, no buffered output
 *       flushed - the moment its N-th checkpoint is renamed into place:
 *       one line to stderr saying so, and nothing else the run does
 *       comes after the rename. A kill lands there by chance once in
 *       thousands of tries; this lands there every time, so what a
 *       checkpoint promises about the records beside it at the instant
 *       it appears is a fact a test can check;
 *   CFT_ORBITS_SHARE_FIFO=1   (any engine, with --records) the records
 *       file is taken to be what the WSL share makes of a Linux FIFO
 *       seen from Windows: a regular file that says it holds 0 bytes,
 *       however much is written to it, and that refuses to be cut
 *       (Windows error 87; EINVAL on POSIX). The records still go into
 *       the real file. The share's own FIFO cannot be a gate's: an open
 *       of one that finds no peer leaves a thread of the distro's 9P
 *       server blocked, and enough of them hung the share on
 *       2026-09-25 - so what a fresh run does with such a file (bc00d8d
 *       refused it) is reachable here without it. SHARE_FIFO is
 *       declared above, where file_empty() reads it. */
static uint64_t SEG_LIMIT = 0;
static double   VCLOCK = 0;
static uint64_t DIE_AFTER = 0;

static double clock_s(void)
{
    return VCLOCK > 0 ? (double)STEPS_DONE * VCLOCK : now_s();
}

static int seg_vperm(int c)
{
    return NEGCTL_TRANSPOSE && c < 2 ? c ^ 1 : c;
}

/* One 64-bit instruction word, revision 3: python/cft_golden/asm.py's
 * encode(), which is the reference this is held to. f[] are the rd,
 * ra, rb, rc fields; isk[] says which of them name a constant. A
 * register's fifth bit rides in imm[27:24]; under kx a constant's index
 * rides in imm's bytes and the field is zero. */
static uint64_t seq_word(int op, const int f[4], const int isk[4],
                         int ctrl, uint32_t imm, int kx)
{
    static const int shift[4] = { 8, 12, 16, 20 };     /* rd ra rb rc */
    static const int hibit[4] = { 24, 25, 26, 27 };    /* R1 */
    uint64_t w;
    int i;

    if (op < 0 || op > 255)
        die("internal: an opcode outside a byte");
    w = (uint64_t)(uint32_t)op;
    w |= (uint64_t)(isk[1] ? 1u : 0u) << 27;
    w |= (uint64_t)(isk[2] ? 1u : 0u) << 28;
    w |= (uint64_t)(isk[3] ? 1u : 0u) << 29;
    w |= (uint64_t)(kx ? 1u : 0u) << 30;
    w |= (uint64_t)(ctrl ? 1u : 0u) << 31;
    for (i = 0; i < 4; i++) {
        if (f[i] < 0 || f[i] > (isk[i] ? 511 : 31))
            die("internal: an operand field out of range");
        if (isk[i] && kx)
            continue;
        w |= (uint64_t)(uint32_t)(f[i] & 0xf) << shift[i];
        if (f[i] >> 4) {
            if (isk[i])
                die("internal: a constant index past 15 without kx");
            imm |= 1u << hibit[i];
        }
    }
    return w | ((uint64_t)imm << 32);
}

/* An ALU instruction. An operand is a register number or KONST(i); kx
 * is chosen the way the assembler chooses it (docs/PROGRAMS.md):
 * indexed when any constant index is 16 or more. An operand the opcode
 * does not read is passed as 0, register r0, and the field is zero. */
static uint64_t seg_alu(int op, int rd, int a, int b, int c)
{
    static const int kxs[3] = { 0, 8, 16 };     /* KX_SHIFT */
    static const int kx9[3] = { 28, 29, 30 };   /* KX9_SHIFT, R7 */
    int f[4], isk[4], x[3], i, kx = 0;
    uint32_t imm = 0;

    x[0] = a; x[1] = b; x[2] = c;
    f[0] = rd;
    isk[0] = 0;
    for (i = 0; i < 3; i++) {
        isk[i + 1] = (x[i] & KOP) != 0;
        f[i + 1] = x[i] & ~KOP;
        if (isk[i + 1] && f[i + 1] >= 16)
            kx = 1;
    }
    if (kx)
        for (i = 0; i < 3; i++)
            if (isk[i + 1]) {
                imm |= (uint32_t)(f[i + 1] & 0xff) << kxs[i];
                imm |= (uint32_t)(f[i + 1] >> 8) << kx9[i];
            }
    return seq_word(op, f, isk, 0, imm, kx);
}

/* A control code: HALT, REPEAT, ENDREP (rd = ra = 0), LDL (rd, slot),
 * STL (ra, slot). */
static uint64_t seg_ctl(int code, int rd, int ra, uint32_t imm)
{
    int f[4], isk[4] = { 0, 0, 0, 0 };
    f[0] = rd; f[1] = ra; f[2] = 0; f[3] = 0;
    return seq_word(code, f, isk, 1, imm, 0);
}

typedef struct { uint64_t *w; size_t n, cap; } seg_ibuf;

static void seg_put(seg_ibuf *B, uint64_t w)
{
    if (B->n == B->cap) {
        size_t cap = B->cap ? 2 * B->cap : 256;
        uint64_t *nw = (uint64_t *)realloc(B->w, cap * sizeof *nw);
        if (!nw)
            die("out of memory building a segment");
        B->w = nw;
        B->cap = cap;
    }
    B->w[B->n++] = w;
}

typedef struct { const uint8_t *v[512]; int n; } seg_bank;

static int seg_k(seg_bank *K, const uint8_t *v)
{
    if (K->n >= 512)
        die("a segment needs more than 512 constants");
    K->v[K->n] = v;
    return K->n++;
}

/* inv_r3_scaled's Newton route, the loop engine's four opcodes a pass */
static void seg_inv_r3(seg_ibuf *B, const fmt_info *fi, int kmone,
                       int kmhalf, int kscale, int dst)
{
    int k;
    if (NEGCTL_ZERO_R2)
        seg_put(B, seg_alu(CFT_SUB, SR_X, SR_X, 0, SR_X));
    seg_put(B, seg_alu(CFT_RSQRT_SEED, SR_Y, SR_X, 0, 0));
    for (k = 0; k < fi->newton; k++) {
        seg_put(B, seg_alu(CFT_MUL, SR_W, SR_X, SR_Y, 0));
        seg_put(B, seg_alu(CFT_FMA, SR_E, SR_W, SR_Y, KONST(kmone)));
        seg_put(B, seg_alu(CFT_MUL, SR_Z, SR_Y, KONST(kmhalf), 0));
        seg_put(B, seg_alu(CFT_FMA, SR_Y, SR_Z, SR_E, SR_Y));
    }
    seg_put(B, seg_alu(CFT_MUL, SR_W, SR_Y, SR_Y, 0));
    seg_put(B, seg_alu(CFT_MUL, SR_W, SR_W, SR_Y, 0));
    seg_put(B, seg_alu(CFT_MUL, dst, SR_W, KONST(kscale), 0));
}

/* drift(): q_c += hd * v_c, every component in index order */
static void seg_drift(seg_ibuf *B, runstate *R, int khd)
{
    int c;
    for (c = 0; c < R->ncomp; c++) {
        seg_put(B, seg_ctl(C_LDL, SR_V, 0, SEG_SV(R, c)));
        seg_put(B, seg_alu(CFT_FMA, SEG_RQ(c), KONST(khd), SR_V,
                           SEG_RQ(c)));
    }
}

/* v_c += g * x_c, one velocity component through the scratch */
static void seg_kick_one(seg_ibuf *B, runstate *R, int c, int g, int x)
{
    seg_put(B, seg_ctl(C_LDL, SR_V, 0, SEG_SV(R, c)));
    seg_put(B, seg_alu(CFT_FMA, SR_V, g, x, SR_V));
    seg_put(B, seg_ctl(C_STL, 0, SR_V, SEG_SV(R, c)));
}

static uint8_t *seg_build(runstate *R, uint64_t k, size_t *bytes_out)
{
    const fmt_info *fi = R->fi;
    seg_ibuf B;
    seg_bank *KB;
    int kmone, kmhalf, kG = -1, s, c, i, j, kk;
    int khd[MAX_SUB], kmg[MAX_SUB];
    int khm[MAX_SUB][MAX_BODIES], kmhm[MAX_SUB][MAX_BODIES];
    uint32_t nslots = (uint32_t)(2 * R->ncomp);
    size_t esz = fi->esz, off, n;
    uint8_t *img;

    if (R->ncomp > 16 || SEG_REGS > 32)
        die("internal: the segment register map does not fit");
    if (k == 0 || k > 0xffffffffull)
        die("internal: a segment's trip count must be 1..2^32-1");
    memset(&B, 0, sizeof B);
    KB = (seg_bank *)xcalloc(1, sizeof *KB);

    /* the bank, in a fixed order */
    kmone = seg_k(KB, R->c_mone);
    kmhalf = seg_k(KB, R->c_mhalf);
    for (s = 0; s < R->nsub; s++)
        khd[s] = seg_k(KB, R->c_hd[s]);
    if (R->O->problem == PROB_KEPLER) {
        for (s = 0; s < R->nsub; s++)
            kmg[s] = seg_k(KB, R->c_mg[s]);
    } else {
        kG = seg_k(KB, R->c_G);
        for (s = 0; s < R->nsub; s++)
            for (i = 0; i < R->nb; i++) {
                khm[s][i] = seg_k(KB, R->c_hm[s][i]);
                kmhm[s][i] = seg_k(KB, R->c_mhm[s][i]);
            }
    }

    for (c = 0; c < R->ncomp; c++)
        seg_put(&B, seg_ctl(C_LDL, SEG_RQ(c), 0, SEG_SQ(c)));
    seg_put(&B, seg_ctl(C_REPEAT, 0, 0, (uint32_t)k));
    for (s = 0; s < R->nsub; s++) {
        seg_drift(&B, R, khd[s]);
        if (R->O->problem == PROB_KEPLER) {
            /* kick_kepler: r^2 = q1*q1 then q0*q0 + that */
            seg_put(&B, seg_alu(CFT_MUL, SR_W, SEG_RQ(1), SEG_RQ(1), 0));
            seg_put(&B, seg_alu(CFT_FMA, SR_X, SEG_RQ(0), SEG_RQ(0), SR_W));
            seg_inv_r3(&B, fi, kmone, kmhalf, kmg[s], SR_G);
            seg_kick_one(&B, R, 0, SR_G, SEG_RQ(0));
            seg_kick_one(&B, R, 1, SR_G, SEG_RQ(1));
        } else {
            /* kick_outer: pairs in lexicographic (i, j) order */
            for (i = 0; i < R->nb; i++) {
                for (j = i + 1; j < R->nb; j++) {
                    for (kk = 0; kk < R->nd; kk++)
                        seg_put(&B, seg_alu(CFT_SUB, SEG_RD(kk),
                                            SEG_RQ(COMP(R, j, kk)), 0,
                                            SEG_RQ(COMP(R, i, kk))));
                    seg_put(&B, seg_alu(CFT_MUL, SR_W, SEG_RD(R->nd - 1),
                                        SEG_RD(R->nd - 1), 0));
                    for (kk = R->nd - 2; kk > 0; kk--)
                        seg_put(&B, seg_alu(CFT_FMA, SR_W, SEG_RD(kk),
                                            SEG_RD(kk), SR_W));
                    seg_put(&B, seg_alu(CFT_FMA, SR_X, SEG_RD(0), SEG_RD(0),
                                        SR_W));
                    seg_inv_r3(&B, fi, kmone, kmhalf, kG, SR_T1);
                    seg_put(&B, seg_alu(CFT_MUL, SR_G, SR_T1,
                                        KONST(khm[s][j]), 0));
                    for (kk = 0; kk < R->nd; kk++)
                        seg_kick_one(&B, R, COMP(R, i, kk), SR_G,
                                     SEG_RD(kk));
                    seg_put(&B, seg_alu(CFT_MUL, SR_G, SR_T1,
                                        KONST(kmhm[s][i]), 0));
                    for (kk = 0; kk < R->nd; kk++)
                        seg_kick_one(&B, R, COMP(R, j, kk), SR_G,
                                     SEG_RD(kk));
                }
            }
        }
        seg_drift(&B, R, khd[s]);
    }
    seg_put(&B, seg_ctl(C_ENDREP, 0, 0, 0));
    for (c = 0; c < R->ncomp; c++)
        seg_put(&B, seg_ctl(C_STL, 0, SEG_RQ(c), SEG_SQ(c)));
    seg_put(&B, seg_ctl(C_HALT, 0, 0, 0));

    n = B.n;
    *bytes_out = 32 + (size_t)KB->n * esz + n * 8;
    img = (uint8_t *)xcalloc(*bytes_out, 1);
    img[0] = 'C'; img[1] = 'F'; img[2] = 'T'; img[3] = 'P';
    put_le32(img + 4, 1);
    put_le32(img + 8, (uint32_t)n);
    put_le32(img + 12, (uint32_t)KB->n);
    put_le32(img + 16, 0);                        /* max_deposits */
    put_le32(img + 20, (uint32_t)fi->fmt);
    put_le32(img + 24, CFT_PROG_FLAG_SCRATCH_IO);
    put_le32(img + 28, nslots | (nslots << 16));  /* scratch in, out */
    off = 32;
    for (i = 0; i < KB->n; i++) {
        memcpy(img + off, KB->v[i], esz);
        off += esz;
    }
    for (i = 0; (size_t)i < n; i++) {
        put_le64(img + off, B.w[i]);
        off += 8;
    }
    free(B.w);
    free(KB);
    return img;
}

/* The census, read off an image rather than counted while building it:
 * instructions, constants, and the ALU and control codes a lane issues
 * per step - the REPEAT body. */
static void seg_census(runstate *R, const uint8_t *img, size_t bytes)
{
    const uint8_t *p;
    uint32_t n, nk, i;
    int depth = 0;
    uint64_t alu = 0, ctl = 0;

    n = (uint32_t)img[8] | ((uint32_t)img[9] << 8) |
        ((uint32_t)img[10] << 16) | ((uint32_t)img[11] << 24);
    nk = (uint32_t)img[12] | ((uint32_t)img[13] << 8) |
         ((uint32_t)img[14] << 16) | ((uint32_t)img[15] << 24);
    if (32 + (size_t)nk * R->fi->esz + (size_t)n * 8 != bytes)
        die("internal: a segment image's size does not match its header");
    p = img + 32 + (size_t)nk * R->fi->esz;
    for (i = 0; i < n; i++, p += 8) {
        uint64_t w = 0;
        int b, is_ctl, op;
        for (b = 7; b >= 0; b--)
            w = (w << 8) | p[b];
        is_ctl = (int)((w >> 31) & 1);
        op = (int)(w & 0xff);
        if (is_ctl && op == C_REPEAT) { depth++; continue; }
        if (is_ctl && op == C_ENDREP) { depth--; continue; }
        if (depth > 0) {
            if (is_ctl)
                ctl++;
            else
                alu++;
        }
    }
    R->s_insns = n;
    R->s_consts = nk;
    R->s_slots = (uint32_t)(2 * R->ncomp);
    R->s_regs = SEG_REGS;
    R->s_alu_step = alu;
    R->s_ctl_step = ctl;
}

static const char *problem_name(int p);

static void seg_write(const char *dir, const char *name, const void *p,
                      size_t bytes)
{
    char path[1024];
    FILE *f;
    if ((size_t)snprintf(path, sizeof path, "%s/%s", dir, name) >=
        sizeof path)
        die("--segment-dump path too long");
    f = fopen(path, "wb");
    if (!f || fwrite(p, 1, bytes, f) != bytes || fclose(f) != 0)
        die("--segment-dump could not write a file");
}

/* Advance every member by k steps: one cft_program_run_ex per batch
 * chunk, the state through the scratch block in and out. */
static void seg_run(runstate *R, uint64_t k)
{
    const fmt_info *fi = R->fi;
    options *O = R->O;
    size_t esz = fi->esz, M = O->members, ns = (size_t)(2 * R->ncomp);
    size_t chunk, i;
    int c, slot = -1;
    cft_status st;
    cft_program *prog;

    /* The image for k steps: cached, or built and loaded into the slot
     * that is free or least recently used. A program handle holds its
     * own image and every run takes it from there - the software
     * backend runs it, the XRT backend stages it whole on every run,
     * and the remote backend sends it, reloading the one image its
     * server keeps when the image changes - so several may be live at
     * once. What the cache saves is this process's build and load; on
     * a remote device the server still reloads when lengths alternate. */
    R->s_segments++;
    for (c = 0; c < SEG_CACHE; c++)
        if (R->sprog[c] && R->sprog_k[c] == k) {
            slot = c;
            break;
        }
    if (slot < 0) {
        size_t bytes = 0;
        uint8_t *img;
        slot = 0;
        for (c = 0; c < SEG_CACHE; c++) {
            if (!R->sprog[c]) {
                slot = c;
                break;
            }
            if (R->sprog_used[c] < R->sprog_used[slot])
                slot = c;
        }
        if (R->sprog[slot]) {
            cft_program_free(R->sprog[slot]);
            R->sprog[slot] = NULL;
        }
        img = seg_build(R, k, &bytes);
        seg_census(R, img, bytes);
        st = cft_program_load(DEV, img, bytes, &R->sprog[slot]);
        if (st != CFT_OK) {
            free(img);
            die_st("cft_program_load (a segment)", st);
        }
        if (O->segment_dump && !R->s_dumped)
            seg_write(O->segment_dump, "segment.cftp", img, bytes);
        free(img);
        R->sprog_k[slot] = k;
        R->s_loads++;
    }
    R->sprog_used[slot] = R->s_segments;
    prog = R->sprog[slot];
    if (!R->sin) {
        /* one chunk's worth: --batch past --members is legal and means
         * one chunk of all of them, so it must not size the buffers */
        size_t lanes = O->batch < M ? O->batch : M;
        R->sin = (uint8_t *)xcalloc(lanes * ns, esz);
        R->sout = (uint8_t *)xcalloc(lanes * ns, esz);
    }

    for (chunk = 0; chunk < M; chunk += O->batch) {
        size_t n = M - chunk < O->batch ? M - chunk : O->batch;
        /* A certified run records the word the library wrote, so it is
         * preset to what no library writes and held to having been
         * written (as cft-segrun holds it) - no value is assumed. */
        uint32_t fl = R->cert ? 0xFFFFFFFFu : 0, bus = 0;
        cft_run_args A;

        for (i = 0; i < n; i++)
            for (c = 0; c < R->ncomp; c++) {
                memcpy(R->sin + (i * ns + SEG_SQ(c)) * esz,
                       CQ(R, c) + (chunk + i) * esz, esz);
                memcpy(R->sin + (i * ns + SEG_SV(R, seg_vperm(c))) * esz,
                       CV(R, c) + (chunk + i) * esz, esz);
            }
        memset(&A, 0, sizeof A);
        A.struct_size = sizeof A;
        /* r0 is overwritten by LDL before anything reads it, and b and c
         * leave r1 and r2 to LDL or to nothing, so no stream reaches a
         * result (docs/ORBITS.md, "Certified runs"). `a` may not be
         * NULL (cft.h): an ordinary run hands q_0, which it has; a
         * certified one hands +0, which its certificate's stream lines
         * then state truly. */
        A.a = R->cert ? R->c_zero : CQ(R, 0) + chunk * esz;
        A.n = n;
        A.scratch_in = R->sin;
        A.scratch_in_bytes = n * ns * esz;
        A.scratch_out = R->sout;
        A.scratch_out_bytes = n * ns * esz;
        A.flags_out = &fl;
        A.bus_out = &bus;
        st = cft_program_run_ex(prog, &A);
        if (st != CFT_OK)
            die_st("cft_program_run_ex (a segment)", st);
        if (R->cert) {
            if (PLANT_UNWRITTEN)
                fl = 0xFFFFFFFFu;
            if (PLANT_WIDE)
                fl |= 0x20u;
            if (fl == 0xFFFFFFFFu)
                refuse("device", "a segment's run at step %" PRIu64 ": the "
                       "library did not write the flag word, and a "
                       "certificate records it%s", R->step,
                       PLANT_UNWRITTEN ? " (planted: CFT_ORBITS_CERT_PLANT="
                                         "flags-unwritten)" : "");
            if (fl > 31u)
                refuse("malformed", "a segment's run at step %" PRIu64 ": "
                       "the library reported flags 0x%08x, and a "
                       "certificate's flag word is the five sticky IEEE "
                       "flags, 0 to 31%s", R->step, (unsigned)fl,
                       PLANT_WIDE ? " (planted: CFT_ORBITS_CERT_PLANT="
                                    "flags-wide)" : "");
        }
        if (bus) {
            char msg[200];
            snprintf(msg, sizeof msg,
                     "a segment returned STATUS 0x%02x - it deposits nothing "
                     "and names only static scratch slots, so any status "
                     "bit means the tool or the device is wrong",
                     (unsigned)bus);
            die(msg);
        }
        if (O->segment_dump && !R->s_dumped && chunk == 0) {
            char meta[512];
            seg_write(O->segment_dump, "segment.in.bin", R->sin,
                      n * ns * esz);
            seg_write(O->segment_dump, "segment.out.bin", R->sout,
                      n * ns * esz);
            seg_write(O->segment_dump, "segment.a.bin", A.a, n * esz);
            snprintf(meta, sizeof meta,
                     "format %s\nlanes %lu\nsteps %llu\nslots %lu\n"
                     "ncomp %d\nproblem %s\n",
                     cft_format_name(fi->fmt), (unsigned long)n,
                     (unsigned long long)k, (unsigned long)ns, R->ncomp,
                     problem_name(O->problem));
            seg_write(O->segment_dump, "segment.txt", meta, strlen(meta));
            R->s_dumped = 1;
        }
        for (i = 0; i < n; i++)
            for (c = 0; c < R->ncomp; c++) {
                memcpy(CQ(R, c) + (chunk + i) * esz,
                       R->sout + (i * ns + SEG_SQ(c)) * esz, esz);
                memcpy(CV(R, c) + (chunk + i) * esz,
                       R->sout + (i * ns + SEG_SV(R, seg_vperm(c))) * esz,
                       esz);
            }
        note_flags(fl, "a sequencer-program segment");
        /* The interval's own word and STATUS, apart from FLAGS_SEEN,
         * which the invariants' host calls reach too: the OR over every
         * run and chunk inside it, as an audit's blocks are OR'd. */
        R->c_iflags |= fl;
        R->c_istatus |= bus;
        N_CALLS++;
        N_ELEMOPS += (uint64_t)n * k * R->s_alu_step;
        R->s_runs++;
    }
    STEPS_DONE += k;
}

/* The loader refuses an image whose worst case could execute more than
 * 2^40 instructions (docs/SEQUENCER.md, "What the loader refuses"), and
 * a REPEAT's trip count is 32 bits. It multiplies the nest out as
 * src/program.c's seq_validate does: the REPEAT, the loads before it
 * and the stores and HALT after it once each, and the body with its
 * ENDREP - which the census does not count - once a pass. So the
 * longest segment is read off a one-step image's census, exactly: one
 * step more and the loader would refuse it. A sample interval longer
 * than that is run as several segments - this engine resumes between
 * any two steps, so nothing is refused that the loop engine runs. */
#define SEG_MAX_EXEC (1ull << 40)

static void seg_limits(runstate *R)
{
    size_t bytes = 0;
    uint8_t *img = seg_build(R, 1, &bytes);
    uint64_t body, outside, k;

    seg_census(R, img, bytes);
    free(img);
    body = R->s_alu_step + R->s_ctl_step + 1;      /* ENDREP included */
    outside = R->s_insns - body;
    k = (SEG_MAX_EXEC - outside) / body;
    R->s_kmax = k < 0xffffffffull ? k : 0xffffffffull;
    if (!R->s_kmax)
        die("internal: a one-step segment exceeds the loader's ceiling");
    if (NEGCTL_OVERLONG)
        R->s_kmax++;
    if (SEG_LIMIT && R->s_kmax > SEG_LIMIT)
        R->s_kmax = SEG_LIMIT;
}

/* How many steps fit in `secs` at the rate the last segment ran: the
 * largest power of two that does; 1 when nothing does, or when `secs`
 * is not positive; and 1 before any segment has been timed, which is
 * how the rate is first measured. main() hands it the time LEFT before
 * the next checkpoint is due, so a segment ends at or just short of
 * that moment and the run is between segments when it comes - which
 * cuts each checkpoint interval into a binary decomposition of its
 * steps, a few powers of two, recurring from one interval to the next.
 * Powers of two keep those lengths few; seg_run's cache keeps each one
 * built and loaded once rather than for every segment. */
static uint64_t seg_time_cap(const runstate *R, double secs)
{
    uint64_t cap = 1;
    double fit;

    if (R->s_sec_per_step <= 0)
        return 1;
    fit = secs / R->s_sec_per_step;
    while (cap < (1ull << 62) && (double)(cap * 2) <= fit)
        cap *= 2;
    return cap;
}

/* ===================================================================
 * The certificate (the header's "Certified runs"; docs/ORBITS.md)
 *
 * One run, `main`: the stride's image, `lanes` the members, `steps` the
 * stride, +0 streams, no parameters, and a segment for each sample
 * interval. Its states are the lane-major scratch blocks the image
 * reads, each boundary's written to DIR as it is reached; the image is
 * DIR/run-0.cftp. The certificate is written when the run completes.
 * =================================================================== */
#if defined(_WIN32)
#  include <direct.h>
#  define ORB_MKDIR(p) _mkdir(p)
#else
#  define ORB_MKDIR(p) mkdir((p), 0777)
#endif

static int path_there(const char *path, int *is_dir)
{
#if defined(_WIN32)
    struct _stat64 st;
    if (_stat64(path, &st) != 0)
        return 0;
    if (is_dir)
        *is_dir = (st.st_mode & _S_IFMT) == _S_IFDIR;
#else
    struct stat st;
    if (stat(path, &st) != 0)
        return 0;
    if (is_dir)
        *is_dir = S_ISDIR(st.st_mode);
#endif
    return 1;
}

static char *cert_path_in(const char *dir, const char *name)
{
    size_t n = strlen(dir) + strlen(name) + 2;
    char *p = (char *)calloc(n, 1);
    if (!p)
        refuse("memory", "a path in %s could not be allocated", dir);
    snprintf(p, n, "%s/%s", dir, name);
    return p;
}

/* The whole of a file the run wrote, or NULL with errno set; *n is its
 * size. A file that says it holds more than `most` bytes is not read:
 * *n is set and NULL returned with errno 0. */
static uint8_t *cert_slurp(const char *path, size_t most, size_t *n)
{
    FILE *f = fopen(path, "rb");
    int64_t len;
    uint8_t *buf;
    if (!f)
        return NULL;
    len = file_length(f);
    if (len < 0) {
        fclose(f);
        errno = EINVAL;
        return NULL;
    }
    *n = (size_t)len;
    if ((uint64_t)len > (uint64_t)most) {
        fclose(f);
        errno = 0;
        return NULL;
    }
    buf = (uint8_t *)calloc(*n ? *n : 1, 1);
    if (!buf) {
        fclose(f);
        refuse("memory", "%s (%lu bytes) could not be read into memory", path,
               (unsigned long)*n);
    }
    if (fread(buf, 1, *n, f) != *n) {
        int e = errno;
        fclose(f);
        free(buf);
        errno = e ? e : EIO;
        return NULL;
    }
    fclose(f);
    return buf;
}

/* The ensemble as a certificate's state: member m's slots in order, slot
 * c = q_c and slot ncomp + c = v_c, each element format-width and
 * little-endian - the scratch block seg_run hands the image. The
 * transpose control's permutation is NOT applied: the certified state is
 * the layout the image reads, so a run made under that control is
 * refused by its own audit (segment-end). */
static void cert_pack(const runstate *R, uint8_t *out)
{
    size_t esz = R->fi->esz, M = R->O->members, m;
    size_t ns = (size_t)(2 * R->ncomp);
    int c;
    for (m = 0; m < M; m++)
        for (c = 0; c < R->ncomp; c++) {
            memcpy(out + (m * ns + SEG_SQ(c)) * esz, CQ(R, c) + m * esz, esz);
            memcpy(out + (m * ns + SEG_SV(R, c)) * esz, CV(R, c) + m * esz,
                   esz);
        }
}

/* Boundary b's state, written to DIR as it is reached and hashed. A fresh
 * run's DIR is its own and new, so each file is created new, and one
 * there already is one this run did not make (`output`). A resumed run
 * REPLACES a file past its checkpoint's last boundary: the process before
 * it wrote that file and was stopped before a checkpoint counted it, and
 * the resumed run computes the same state again, bit for bit. */
static void cert_boundary(runstate *R, uint64_t b)
{
    char name[64];
    char *path;
    FILE *f;
    snprintf(name, sizeof name, "run-0-boundary-%" PRIu64 ".bin", b);
    path = cert_path_in(R->O->cert_states, name);
    cert_pack(R, R->c_state);
    errno = 0;
    f = b > R->c_replace_from ? fopen(path, "wb") : cw_create_new(path);
    if (!f)
        refuse("output", "%s cannot be created (%s); the boundary files "
               "written so far are left in %s", path,
               errno == EEXIST ? "a file this run did not make is there "
                                 "already" : strerror(errno),
               R->O->cert_states);
    if (fwrite(R->c_state, 1, R->c_state_bytes, f) != R->c_state_bytes) {
        fclose(f);
        refuse("output", "a short write to %s", path);
    }
    if (fclose(f) != 0)
        refuse("output", "%s could not be closed (%s)", path, strerror(errno));
    free(path);
    cert_ok(cw_state_hash(R->salt, R->c_state, R->c_state_bytes,
                          R->c_bhash[b]), "a boundary state's hash");
}

/* Interval sample - 1 has just closed: its word and STATUS are recorded,
 * its end state is boundary `sample`, and the next interval's word begins
 * at nothing. */
static void cert_close(runstate *R)
{
    uint64_t k = R->sample - 1;
    R->c_flags[k] = R->c_iflags;
    R->c_status[k] = R->c_istatus;
    R->c_iflags = R->c_istatus = 0;
    cert_boundary(R, R->sample);
}

/* ---- the accuracy entries: the angular momentum's drift ----------------
 *
 * L = sum over bodies b of m_b (q_b x v_b) is a polynomial in the state,
 * so version 1 carries its drift exactly (docs/CERTIFICATES.md, "Accuracy
 * entries"): one `drift` entry for each component - x, y and z for the
 * outer system, z alone for the planar Kepler problem - over run 0, the
 * maximum over its lanes of |L(final) - L(initial)|, exact, labelled
 * angular-momentum-<component>. Component k's terms, body by body:
 * m_b q_(k+1) v_(k+2), then -m_b q_(k+2) v_(k+1), the indices mod 3; each
 * coefficient is the exact value of the mass the run computed with, and 1
 * for Kepler's test particle, whose L the tool reports as q0 v1 - q1 v0.
 * So the quantity is the one invariants() sums, in exact arithmetic. Its
 * drift is docs/ORBITS.md's "angular-momentum certificate": both schemes
 * conserve L exactly, so what moves it is the arithmetic alone. Every
 * value is cert_exact.h's, as cft-segrun and cft-audit compute every
 * entry, held to the width rule at each step and refused `width` by name
 * past it (the lead's conditions, 2026-09-30). */
#if CX_EXACT
static int PLANT_WIDTH = 0;           /* CFT_ORBITS_CERT_PLANT=width */

/* A cert_exact.h status, refused by its name, the page's; one that is no
 * verdict is an internal error, as cft-segrun's is. */
static void cert_cx(int st, const char *why)
{
    const char *name = cx_name(st);
    if (st == CX_OK)
        return;
    if (st == CX_LIBRARY)
        refuse("device", "the library failed an accuracy value's rounding: "
               "%s", why);
    if (!name) {
        fprintf(stderr, "cft-orbits: internal error: %s\n", why);
        exit(70);
    }
    refuse(name, "%s", why);
}

/* The entries' definitions, before anything runs: their terms, and
 * cert.derive's checks of them against the run (cx_entry_check). */
static void cert_entries(runstate *R)
{
    static const char *const LABEL[3] = {
        "angular-momentum-x", "angular-momentum-y", "angular-momentum-z"
    };
    const fmt_info *fi = R->fi;
    int f = (int)fi->fmt, nb = R->nb, k, b;
    unsigned n = 0, j;
    char why[512];
    cx_run m;

    R->c_terms = (term_t *)calloc((size_t)(3 * 2 * nb), sizeof(term_t));
    if (!R->c_terms)
        refuse("memory", "the accuracy entries' terms could not be "
               "allocated");
    for (k = R->nd == 2 ? 2 : 0; k < 3; k++) {
        int k1 = (k + 1) % 3, k2 = (k + 2) % 3;
        entry_t *E = &R->c_entries[n];
        term_t *T = R->c_terms + (size_t)n * 2 * nb;
        memset(E, 0, sizeof *E);
        E->method = M_DRIFT;
        E->uses = 0;
        E->has_lane = 0;
        E->n_terms = (unsigned)(2 * nb);
        E->terms = T;
        E->value.form = V_EXACT;
        for (b = 0; b < nb; b++) {
            uint8_t one[MAX_ESZ];
            const uint8_t *mass = R->c_m[b];     /* its first element */
            char what[64];
            if (R->O->problem == PROB_KEPLER) {
                val_from_i64(fi, 1, one);
                mass = one;
            }
            snprintf(what, sizeof what, "body %d's mass", b);
            cert_cx(cx_exact(&T[2 * b].coef, f, mass, what, why, sizeof why),
                    why);
            T[2 * b].n = 2;
            T[2 * b].slot[0] = (uint64_t)COMP(R, b, k1);
            T[2 * b].slot[1] = (uint64_t)(R->ncomp + COMP(R, b, k2));
            T[2 * b + 1] = T[2 * b];
            T[2 * b + 1].coef.neg = !T[2 * b].coef.neg;
            T[2 * b + 1].slot[0] = (uint64_t)COMP(R, b, k2);
            T[2 * b + 1].slot[1] = (uint64_t)(R->ncomp + COMP(R, b, k1));
        }
        R->c_labels[n++] = LABEL[k];
    }
    R->c_n_entries = n;
    if (PLANT_WIDTH) {
        /* the first term's coefficient times 2^-1000: within the rule for
         * Kepler's 1, and its first product with a state value past it */
        rat p;
        memset(&p, 0, sizeof p);
        cft_bn_set_u32(&p.n, 1);
        cft_bn_zero(&p.d);
        cft_bn_setbit(&p.d, 1000);
        if (rat_mul(&R->c_terms[0].coef, &R->c_terms[0].coef, &p))
            refuse("width", "the planted coefficient is past the bigint");
    }
    m.kind = K_MAIN;
    m.fmt = f;
    m.lanes = R->O->members;
    m.S = R->nsamples;
    m.nslots = (uint32_t)(2 * R->ncomp);
    for (j = 0; j < n; j++)
        cert_cx(cx_entry_check(&R->c_entries[j], 1, &m, &m, why, sizeof why),
                why);
}

/* Boundary b's state, read back from DIR and held to the hash the
 * certificate carries for it, as cft-segrun reads its states back: a file
 * another process changed is refused `output`. */
static uint8_t *cert_read_back(runstate *R, uint64_t b)
{
    char name[64], h[CW_HEX];
    char *path;
    uint8_t *buf;
    size_t n = 0;
    snprintf(name, sizeof name, "run-0-boundary-%" PRIu64 ".bin", b);
    path = cert_path_in(R->O->cert_states, name);
    errno = 0;
    buf = cert_slurp(path, R->c_state_bytes, &n);
    if (!buf || n != R->c_state_bytes)
        refuse("output", "%s cannot be read back as the %lu bytes this run "
               "wrote there (%s): another process changed %s", path,
               (unsigned long)R->c_state_bytes,
               errno ? strerror(errno) : "its size", R->O->cert_states);
    cert_ok(cw_state_hash(R->salt, buf, n, h), "a state read back");
    if (strcmp(h, R->c_bhash[b]) != 0)
        refuse("output", "%s is not the state this run wrote there - its "
               "hash is not the one the certificate carries at boundary %"
               PRIu64 ": another process changed %s", path, b,
               R->O->cert_states);
    free(path);
    return buf;
}

/* Every entry's value, in the golden writer's order: each derived from
 * the initial state and the final one, read back (cert.derive), and only
 * then each made in its form (cert.make_value). */
static void cert_derive(runstate *R)
{
    uint8_t *first = cert_read_back(R, 0);
    uint8_t *last = cert_read_back(R, R->nsamples);
    char why[512];
    cx_run m;
    unsigned j;
    m.kind = K_MAIN;
    m.fmt = (int)R->fi->fmt;
    m.lanes = R->O->members;
    m.S = R->nsamples;
    m.nslots = (uint32_t)(2 * R->ncomp);
    for (j = 0; j < R->c_n_entries; j++)
        cert_cx(cx_entry_value(&R->c_entries[j], &m, &m, first, last,
                               &R->c_q[j], why, sizeof why), why);
    free(first);
    free(last);
    for (j = 0; j < R->c_n_entries; j++)
        cert_cx(cx_value_make(DEV, &R->c_q[j], V_EXACT, 0, 0,
                              &R->c_entries[j].value, why, sizeof why), why);
}
#endif /* CX_EXACT */

/* What the certificate says before any segment runs: the stride's image
 * and its digests (the loader must take it: a stride past its limits is
 * refused here, with the library's sentence), the identity, the +0
 * streams, and the lines through `segments S` - which the checkpoint
 * carries too, and a resume holds to its own. */
static void cert_setup(runstate *R, const cft_caps *caps)
{
    const options *O = R->O;
    const fmt_info *fi = R->fi;
    size_t M = O->members, esz = fi->esz;
    char img_hex[CW_HEX], dig_hex[CW_HEX], strm[3][CW_HEX];
    cft_program *p = NULL;
    cft_status st;
    uint8_t d[32];
    int s;

    if (R->stride > 0xffffffffull)
        refuse("program-image", "the stride is %" PRIu64 " steps, and a "
               "REPEAT's trip count is 32 bits: no image runs one interval "
               "whole, so no loader could take the certificate's image "
               "(docs/SEQUENCER.md, \"What the loader refuses\")", R->stride);
    R->c_image = seg_build(R, R->stride, &R->c_image_bytes);
    st = cft_program_load(DEV, R->c_image, R->c_image_bytes, &p);
    if (st != CFT_OK) {
        char what[200];
        snprintf(what, sizeof what, "the image of one %" PRIu64 "-step "
                 "interval, the certificate's: cft_program_load", R->stride);
        refuse_st("program-image", what, st);
    }
    cert_ok(cw_sha256(R->c_image, R->c_image_bytes, d), "the image's digest");
    cw_hex(d, 32, img_hex);
    st = cft_program_digest(p, NULL, 0, d);
    if (st != CFT_OK)
        refuse_st("device", "cft_program_digest", st);
    cw_hex(d, 32, dig_hex);
    cft_program_free(p);

    if (cw_identify(DEV, caps, &R->c_id))
        refuse("malformed", "cft_build_id() returned '%s', which is not the "
               "page's grammar; the build-id line is that string verbatim, "
               "so no certificate can be written from it",
               R->c_id.build_id ? R->c_id.build_id : "(null)");

    if (M > ((size_t)-1) / esz)
        refuse("memory", "%lu members' streams cannot be addressed",
               (unsigned long)M);
    R->c_zero = (uint8_t *)calloc(M, esz);
    if (!R->c_zero)
        refuse("memory", "the +0 streams (%lu elements) could not be "
               "allocated", (unsigned long)M);
    for (s = 0; s < 3; s++)
        cert_ok(cw_stream_hash(R->salt, s, R->c_zero, M * esz, strm[s]),
                "a stream's hash");
    if (R->salt)
        cert_ok(cw_salt_commitment(R->salt, R->commitment),
                "the salt's commitment");

    cert_ok(cw_identity_lines(&R->c_ident, R->salt ? R->commitment : NULL,
                              &R->c_id), "the certificate's header");
    cert_ok(cw_run_head(&R->c_runhead, cft_format_name(fi->fmt), img_hex,
                        dig_hex, (uint64_t)M, R->stride, strm[0], strm[1],
                        strm[2]), "the certificate's run");
    cert_ok(cw_put(&R->c_runhead, "parameters 0\nsegments %" PRIu64 "\n",
                   R->nsamples), "the certificate's run");

    /* the certificate's own memory, sized by the run and taken now, so
     * a run the process cannot hold is refused before anything is made */
    if (R->nsamples >= ((size_t)-1) / CW_HEX ||
        (size_t)(2 * R->ncomp) > ((size_t)-1) / esz / M)
        refuse("memory", "%" PRIu64 " intervals of %lu members cannot be "
               "addressed", R->nsamples, (unsigned long)M);
    R->c_bhash = (char (*)[CW_HEX])calloc((size_t)R->nsamples + 1, CW_HEX);
    R->c_flags = (uint32_t *)calloc((size_t)R->nsamples, sizeof(uint32_t));
    R->c_status = (uint32_t *)calloc((size_t)R->nsamples, sizeof(uint32_t));
    R->c_state_bytes = M * (size_t)(2 * R->ncomp) * esz;
    R->c_state = (uint8_t *)calloc(R->c_state_bytes, 1);
    if (!R->c_bhash || !R->c_flags || !R->c_status || !R->c_state)
        refuse("memory", "the certificate's hashes and words for %" PRIu64
               " intervals, and a state of %lu bytes, could not be "
               "allocated", R->nsamples, (unsigned long)R->c_state_bytes);
    R->c_replace_from = UINT64_MAX;
#if CX_EXACT
    if (R->c_angmom)
        cert_entries(R);
#endif
}

/* A fresh certified run's files: DIR, made new, and in it the image and
 * boundary 0, the initial state - setup_state's ensemble, the records'
 * sample 0. */
static void cert_fresh_files(runstate *R)
{
    const char *dir = R->O->cert_states;
    char *img;
    FILE *f;
    if (ORB_MKDIR(dir) != 0)
        refuse("output", "--cert-states %s cannot be created (%s); a certified "
               "run's states directory is made new, so that no two runs' "
               "states mix", dir,
               errno == EEXIST ? "it is there already" : strerror(errno));
    img = cert_path_in(dir, "run-0.cftp");
    f = cw_create_new(img);
    if (!f || fwrite(R->c_image, 1, R->c_image_bytes, f) != R->c_image_bytes ||
        fclose(f) != 0)
        refuse("output", "%s cannot be written (%s)", img, strerror(errno));
    free(img);
    cert_boundary(R, 0);
}

/* A resumed certified run's files, held to its checkpoint: DIR is there,
 * its image is the one this process builds, and every boundary the
 * checkpoint has passed is there, the size of a state, and hashes to the
 * checkpoint's hash for it. */
static void cert_resumed_files(runstate *R)
{
    const char *dir = R->O->cert_states;
    int is_dir = 0;
    char *path;
    uint8_t *buf;
    size_t n = 0;
    uint64_t b;
    char h[CW_HEX];

    if (!path_there(dir, &is_dir) || !is_dir)
        refuse("output", "--cert-states %s is not a directory there: a "
               "resumed certified run's states are in the directory its "
               "first process made", dir);
    path = cert_path_in(dir, "run-0.cftp");
    buf = cert_slurp(path, R->c_image_bytes, &n);
    if (!buf || n != R->c_image_bytes ||
        memcmp(buf, R->c_image, R->c_image_bytes) != 0)
        refuse("image-digest", "%s is %s: the image of this run's stride, "
               "which the certificate names, is %lu bytes this process "
               "builds", path,
               !buf && errno ? "not there, or cannot be read"
                             : "not that image",
               (unsigned long)R->c_image_bytes);
    free(buf);
    free(path);
    for (b = 0; b <= R->sample; b++) {
        char name[64];
        snprintf(name, sizeof name, "run-0-boundary-%" PRIu64 ".bin", b);
        path = cert_path_in(dir, name);
        errno = 0;
        buf = cert_slurp(path, R->c_state_bytes, &n);
        if (!buf && errno)
            refuse("state-missing", "%s, boundary %" PRIu64 " of this run, "
                   "is not there, or cannot be read (%s); the checkpoint has "
                   "passed it", path, b, strerror(errno));
        if (!buf || n != R->c_state_bytes)
            refuse("state-shape", "%s is %lu bytes, and a state of %lu "
                   "members is %lu", path, (unsigned long)n,
                   (unsigned long)R->O->members,
                   (unsigned long)R->c_state_bytes);
        cert_ok(cw_state_hash(R->salt, buf, n, h), "a boundary state's hash");
        if (strcmp(h, R->c_bhash[b]) != 0)
            refuse("state-hash", "%s does not hash to the checkpoint's "
                   "boundary %" PRIu64 ": it is not the state this run "
                   "certified there", path, b);
        free(buf);
        free(path);
    }
}

/* Before anything is read back or made: CERT is not there; DIR is not
 * there for a fresh run, and is for a resumed one; and CERT.tmp is
 * created now - before DIR, as cft-segrun creates its certificate before
 * its states directory, so a CERT inside a DIR not made yet cannot be
 * created at all. */
static void cert_outputs(runstate *R)
{
    const options *O = R->O;
    int is_dir = 0;
    size_t n;
    if (path_there(O->cert_path, NULL))
        refuse("output", "--cert %s is there already: a certificate is never "
               "written over a file", O->cert_path);
    if (O->resume && !(path_there(O->cert_states, &is_dir) && is_dir))
        refuse("output", "--cert-states %s is not a directory there: a "
               "resumed certified run's states are in the directory its "
               "first process made", O->cert_states);
    if (!O->resume && path_there(O->cert_states, NULL))
        refuse("output", "--cert-states %s is there already: a certified "
               "run's states directory is made new, so that no two runs' "
               "states mix", O->cert_states);
    n = strlen(O->cert_path) + 5;
    CERT_TMP = (char *)calloc(n, 1);
    if (!CERT_TMP)
        refuse("memory", "a path could not be allocated");
    snprintf(CERT_TMP, n, "%s.tmp", O->cert_path);
    CERT_TMP_FP = fopen(CERT_TMP, "wb");
    if (!CERT_TMP_FP)
        refuse("output", "%s cannot be created (%s): the certificate is "
               "written there when the run completes, then moved to %s",
               CERT_TMP, strerror(errno), O->cert_path);
}

/* The certificate, whole, once the run has completed: into CERT.tmp,
 * then moved to CERT without replacing anything. */
static void cert_finish(runstate *R)
{
    const char *cert = R->O->cert_path;
    cw_text t;
    uint64_t k, S = R->nsamples;
    const char *why;
    int moved;

#if CX_EXACT
    if (R->c_n_entries)
        cert_derive(R);             /* before a byte of the text */
#endif
    memset(&t, 0, sizeof t);
    why = cw_put(&t, "cft-certificate 1\n%sruns 1\nrun 0 main\n%s",
                 R->c_ident.p, R->c_runhead.p);
    for (k = 0; !why && k < S; k++)
        why = cw_segment_line(&t, k, R->c_bhash[k], R->c_bhash[k + 1],
                              R->c_flags[k], R->c_status[k]);
    if (!why)
        why = cw_put(&t, "output %s\naccuracy %u\n", R->c_bhash[S],
                     R->c_n_entries);
    cert_ok(why, "the certificate's text");
#if CX_EXACT
    {
        char ewhy[512];
        unsigned j;
        for (j = 0; j < R->c_n_entries; j++) {
            why = cw_entry_lines(&t, j, &R->c_entries[j], R->c_labels[j], DEV,
                                 ewhy, sizeof ewhy);
            if (why)
                refuse(why, "%s could not be written", ewhy);
        }
    }
#endif
    cert_ok(cw_finish(&t), "the certificate's text");

    if (fwrite(t.p, 1, t.n, CERT_TMP_FP) != t.n ||
        fflush(CERT_TMP_FP) != 0)
        refuse("output", "a short write to %s", CERT_TMP);
    if (fclose(CERT_TMP_FP) != 0) {
        CERT_TMP_FP = NULL;
        remove(CERT_TMP);
        refuse("output", "%s could not be closed", CERT_TMP);
    }
    CERT_TMP_FP = NULL;
    cw_text_free(&t);
#if defined(_WIN32)
    /* no MOVEFILE_REPLACE_EXISTING: a CERT that is there stays */
    moved = MoveFileExA(CERT_TMP, cert, 0) != 0;
    if (!moved) {
        DWORD e = GetLastError();
        remove(CERT_TMP);
        note_win_error(e);
        refuse("output", "%s could not be moved to %s (%s)%s", CERT_TMP, cert,
               SYS_ERR, (e == ERROR_ALREADY_EXISTS || e == ERROR_FILE_EXISTS)
                        ? ": a certificate is never written over a file"
                        : "");
    }
#else
    /* link() refuses a name that is taken, where rename() would replace
     * it; a filesystem without hard links is asked first instead */
    moved = link(CERT_TMP, cert) == 0;
    if (!moved && errno != EEXIST && !path_there(cert, NULL))
        moved = rename(CERT_TMP, cert) == 0;
    else if (moved)
        unlink(CERT_TMP);
    if (!moved) {
        int e = errno;
        unlink(CERT_TMP);
        refuse("output", "%s could not be moved to %s (%s)%s", CERT_TMP, cert,
               strerror(e), e == EEXIST ? ": a certificate is never "
                                          "written over a file" : "");
    }
#endif
}

/* ===================================================================
 * The checkpoint
 *
 * A line-oriented ASCII file, written to <path>.tmp, flushed, closed
 * and then RENAMED over the target, so a reader never sees a
 * half-written one. It carries every number that describes a RESULT
 * and nothing that describes the MACHINE - no batch size, no engine,
 * no timing - which is what lets two runs with different batch sizes
 * end on byte-identical files.
 *
 * Version 2 (2026-09-25) added `recbytes`, the length of the record
 * stream the checkpoint's chain covers - the bytes --records has
 * written by then, counted whether or not it is open, so the file is
 * the same either way. A version-1 file does not say it, and is
 * refused by the magic line like any other version.
 *
 * Version 3 (2026-09-30) is a CERTIFIED run's, and only a certified run
 * writes it, so every other run's checkpoint is version 2 byte for byte
 * as it was. It is version 2's lines, then the certificate so far - the
 * `cert` block: each certificate line from `mode` to `segments S`,
 * prefixed `cert `; `cert boundary 0 <hash>`; a `cert segment` line for
 * each interval closed, the certificate's own line; and `cert interval
 * flags <n> status <n>`, what the interval in progress has raised so far
 * - then `end`, then `sum <hex>`, SHA-256 of every byte before it. Its
 * reader is strict (ckpt_read3): the sum first, then every line once, in
 * this order, each value in its one spelling; a resume with --cert
 * requires version 3, and one without refuses it. Version 2's reader is
 * as lenient as it was.
 * =================================================================== */
#define CKPT_MAGIC  "cft-orbits-checkpoint 2"   /* an ordinary run's */
#define CKPT_MAGIC3 "cft-orbits-checkpoint 3"   /* a certified run's */

/* The rename that makes a checkpoint the one on disk (file_replace,
 * above, retries it on Windows while another process holds the file).
 * Under CFT_ORBITS_DIE_AFTER_CHECKPOINT the process ends here, the
 * instant the N-th checkpoint is in place: whatever the checkpoint
 * promises about the records file must already be true on disk,
 * because after the one line to stderr nothing of the run is done. */
static int ckpt_replace(const char *tmp, const char *path)
{
    static uint64_t renamed = 0;
    if (file_replace(tmp, path) != 0)
        return -1;
    if (DIE_AFTER && ++renamed == DIE_AFTER) {
        fprintf(stderr, "cft-orbits: ending as a kill would, after "
                "checkpoint %" PRIu64 " (CFT_ORBITS_DIE_AFTER_CHECKPOINT)\n",
                renamed);
        end_as_killed();
    }
    return 0;
}

static const char *problem_name(int p)
{
    return p == PROB_KEPLER ? "kepler" : "outer";
}

static const char *scheme_name(int s)
{
    return s == SCHEME_LEAPFROG ? "leapfrog" : "yoshida4";
}

static const char *rsqrt_name(int r)
{
    return r == RSQRT_EXACT ? "exact" : "newton";
}

/* Hand every record so far to the system, and check the file holds
 * exactly the stream the next checkpoint will account for. Called
 * BEFORE that checkpoint is written: it promises the file holds at
 * least `recbytes` bytes, so a kill between the two leaves the file
 * ahead of the checkpoint on disk and never behind it - and --resume
 * cuts it back (records_resume). A failed write is ferror()'s to
 * catch. The length check catches a flush left out or a record
 * miscounted. Of two processes writing the same file it stops only the
 * one that LAGS - the file is as long as the leader has written - and
 * the one ahead finishes unaware (verifier-V6, 2026-09-25: 3 of 3). A
 * file another process cuts short is not caught at all: the next flush
 * writes past the cut and leaves a hole of zeros exactly as long as the
 * count says. A pipe or a device has no length and is not checked. A
 * pipe the system presents as a regular file has one - 0, whatever is
 * written to it: the WSL share presents a Linux FIFO so (measured,
 * 2026-09-27). This cannot tell such a pipe from a file something else
 * cut, so a file that says it holds nothing after this run wrote to it
 * is refused with both named, and neither claimed. */
static void records_sync(runstate *R)
{
    int64_t have;
    char msg[640];

    if (fflush(R->recf) != 0 || ferror(R->recf))
        die("the records file could not be written");
    if (NEGCTL_APPEND)
        return;                 /* the old resume: nothing to hold it to */
    have = SHARE_FIFO ? 0 : file_length(R->recf);
    if (have == 0 && R->rec_bytes > 0) {
        snprintf(msg, sizeof msg,
                 "the records file says it holds 0 bytes, where %" PRIu64
                 " have been written to it: something else cut it, or it is "
                 "a pipe the system presents as an empty file (the WSL share "
                 "presents a Linux FIFO so), which has no length to hold a "
                 "checkpoint to - with --checkpoint, --records must name a "
                 "file", R->rec_bytes);
        die(msg);
    }
    if (have >= 0 && (uint64_t)have != R->rec_bytes) {
        snprintf(msg, sizeof msg,
                 "the records file holds %" PRId64 " bytes and the records "
                 "so far are %" PRIu64 " - something else wrote to it or "
                 "cut it",
                 have, R->rec_bytes);
        die(msg);
    }
}

/* Where a checkpoint's text goes: the file, and for version 3 the running
 * SHA-256 its `sum` line states. Each piece is formatted once and written
 * as formatted, so version 2's bytes are what its fprintf calls wrote. */
typedef struct {
    FILE  *f;
    int    summed, bad;
    sha256 h;
} ck_sink;

static void ck_put(ck_sink *o, const char *fmt, ...) CW_PRINTF_LIKE(2, 3);

static void ck_put(ck_sink *o, const char *fmt, ...)
{
    char small[256], *buf = small;
    va_list ap;
    int n;
    va_start(ap, fmt);
    n = vsnprintf(small, sizeof small, fmt, ap);
    va_end(ap);
    if (n < 0) {
        o->bad = 1;
        return;
    }
    if ((size_t)n >= sizeof small) {
        buf = (char *)xcalloc((size_t)n + 1, 1);
        va_start(ap, fmt);
        vsnprintf(buf, (size_t)n + 1, fmt, ap);
        va_end(ap);
    }
    if (fwrite(buf, 1, (size_t)n, o->f) != (size_t)n)
        o->bad = 1;
    if (o->summed)
        sha256_push(&o->h, buf, (size_t)n);
    if (buf != small)
        free(buf);
}

/* A cw_text's lines, each written again with `prefix` before it. */
static void ck_lines(ck_sink *o, const char *prefix, const cw_text *t)
{
    const char *p = t->p, *nl;
    while (p && *p && (nl = strchr(p, '\n')) != NULL) {
        ck_put(o, "%s%.*s\n", prefix, (int)(nl - p), p);
        p = nl + 1;
    }
}

static void ckpt_write(runstate *R)
{
    const fmt_info *fi = R->fi;
    options *O = R->O;
    char tmp[1024], dec[DECMAX], chain[65];
    ck_sink o;
    size_t m, esz = fi->esz, M = O->members;
    int c, k;

    if (!O->ckpt)
        return;
    if (R->recf && !NEGCTL_FLUSH_LATE)
        records_sync(R);
    if ((size_t)snprintf(tmp, sizeof tmp, "%s.tmp", O->ckpt) >= sizeof tmp)
        die("checkpoint path too long");
    memset(&o, 0, sizeof o);
    o.f = fopen(tmp, "wb");
    if (!o.f)
        die("cannot write the checkpoint");
    o.summed = R->cert;
    if (o.summed)
        sha256_start(&o.h);

    hex32(R->chain, chain);
    ck_put(&o, "%s\n", R->cert ? CKPT_MAGIC3 : CKPT_MAGIC);
    ck_put(&o, "format %s\n", cft_format_name(fi->fmt));
    ck_put(&o, "problem %s\n", problem_name(O->problem));
    ck_put(&o, "scheme %s\n", scheme_name(O->scheme));
    ck_put(&o, "rsqrt %s\n", rsqrt_name(O->rsqrt));
    ck_put(&o, "members %" PRIu64 "\n", (uint64_t)M);
    ck_put(&o, "spread %" PRIu64 "\n", O->spread);
    ck_put(&o, "bodies %d\n", R->nb);
    ck_put(&o, "dims %d\n", R->nd);
    val_to_dec(fi, R->s_h, dec, sizeof dec);
    ck_put(&o, "h %s\n", dec);
    ck_put(&o, "steps %" PRIu64 "\n", R->nsteps);
    ck_put(&o, "stride %" PRIu64 "\n", R->stride);
    ck_put(&o, "samples %" PRIu64 "\n", R->nsamples);
    ck_put(&o, "at %" PRIu64 " %" PRIu64 "\n", R->step, R->sample);
    ck_put(&o, "chain %s\n", chain);
    ck_put(&o, "recbytes %" PRIu64 "\n", R->rec_bytes);
    for (m = 0; m < M; m++) {
        ck_put(&o, "state %" PRIu64, (uint64_t)m);
        for (c = 0; c < R->ncomp; c++) {
            val_to_dec(fi, CQ(R, c) + m * esz, dec, sizeof dec);
            ck_put(&o, " %s", dec);
        }
        for (c = 0; c < R->ncomp; c++) {
            val_to_dec(fi, CV(R, c) + m * esz, dec, sizeof dec);
            ck_put(&o, " %s", dec);
        }
        ck_put(&o, "\n");
    }
    for (m = 0; m < M; m++) {
        ck_put(&o, "inv %" PRIu64, (uint64_t)m);
        val_to_dec(fi, R->H0 + m * esz, dec, sizeof dec);
        ck_put(&o, " %s", dec);
        val_to_dec(fi, R->dHmax + m * esz, dec, sizeof dec);
        ck_put(&o, " %s", dec);
        for (k = 0; k < R->nL; k++) {
            val_to_dec(fi, R->L0[k] + m * esz, dec, sizeof dec);
            ck_put(&o, " %s", dec);
            val_to_dec(fi, R->dLmax[k] + m * esz, dec, sizeof dec);
            ck_put(&o, " %s", dec);
        }
        ck_put(&o, "\n");
    }
    if (R->cert) {
        /* the certificate so far: its lines through `segments S`, the
         * initial state's hash, every closed interval's segment line, and
         * the interval in progress's word and STATUS so far */
        uint64_t j;
        uint8_t d[32];
        char sum[65];
        ck_lines(&o, "cert ", &R->c_ident);
        ck_lines(&o, "cert ", &R->c_runhead);
        ck_put(&o, "cert entries %s\n", R->c_angmom ? "angular-momentum-drift"
                                                    : "none");
        ck_put(&o, "cert boundary 0 %s\n", R->c_bhash[0]);
        for (j = 0; j < R->sample; j++)
            ck_put(&o, "cert segment %" PRIu64 " start %s end %s flags %u "
                   "status %u\n", j, R->c_bhash[j], R->c_bhash[j + 1],
                   (unsigned)R->c_flags[j], (unsigned)R->c_status[j]);
        ck_put(&o, "cert interval flags %u status %u\n",
               (unsigned)R->c_iflags, (unsigned)R->c_istatus);
        ck_put(&o, "end\n");
        sha256_end(&o.h, d);
        hex32(d, sum);
        o.summed = 0;
        ck_put(&o, "sum %s\n", sum);
    } else {
        ck_put(&o, "end\n");
    }
    if (o.bad || fflush(o.f) != 0 || fclose(o.f) != 0)
        die("the checkpoint did not write cleanly");
    if (ckpt_replace(tmp, O->ckpt) != 0)
        die("the checkpoint could not be renamed into place (on Windows, "
            "another process held it or its temporary through 1.5 s of "
            "retries; or the directory refused the rename)");
    if (R->recf && NEGCTL_FLUSH_LATE)
        records_sync(R);
    if (VCLOCK > 0)
        fprintf(stderr, "cft-orbits: checkpoint at step %" PRIu64
                ", sample %" PRIu64 "\n", R->step, R->sample);
}

static char *trim_nl(char *s)
{
    size_t n = strlen(s);
    while (n && (s[n - 1] == '\n' || s[n - 1] == '\r'))
        s[--n] = 0;
    return s;
}

/* Read one whitespace-delimited token out of *pp, advancing it. */
static int next_tok(char **pp, char *out, size_t cap)
{
    char *p = *pp;
    size_t n = 0;
    while (*p == ' ' || *p == '\t')
        p++;
    if (!*p)
        return 0;
    while (*p && *p != ' ' && *p != '\t') {
        if (n + 1 >= cap)
            return 0;
        out[n++] = *p++;
    }
    out[n] = 0;
    *pp = p;
    return 1;
}

/* A whole decimal number, digits only, at most `max`: 1 if `s` is one. */
static int dec_u64(const char *s, uint64_t max, uint64_t *out)
{
    uint64_t v = 0;
    if (!*s)
        return 0;
    for (; *s; s++) {
        unsigned d = (unsigned)(unsigned char)*s - '0';
        if (d > 9 || v > (max - d) / 10)
            return 0;
        v = v * 10 + d;
    }
    *out = v;
    return 1;
}

/* ---- version 3: a certified run's checkpoint, read strictly -----------
 *
 * The sum first: the last line is `sum` and 64 lowercase hex digits, the
 * SHA-256 of every byte before it - so a file cut, or changed anywhere,
 * is refused before a line of it is read. Then every line once, in the
 * order ckpt_write writes them, each value in its one spelling and range:
 * version 2's lines held to this run as version 2's reader holds them,
 * and to what it only skipped (spread, bodies, dims, samples); then the
 * `cert` block. Its lines through `segments` must be the ones this
 * process writes - the salt's by the page's names, the build and device
 * by `identity` with both named, the image by `image-digest` and
 * `program-digest` - and every other departure is a sentence, exit 2, as
 * every checkpoint refusal before it was. A sum proves the bytes are the
 * writer's, not who the writer was: a file written to pass it could hand
 * a resume a state the run never reached mid-interval, and the audit is
 * what refuses the certificate that follows (segment-end); at a sample
 * boundary the state is held to the boundary's hash here. */
static const char *CK3_FILE;
static unsigned long CK3_LINE;

static void ck3_die(const char *fmt, ...) ORB_NORETURN CW_PRINTF_LIKE(1, 2);

static void ck3_die(const char *fmt, ...)
{
    char msg[1200];
    int n = snprintf(msg, sizeof msg, "the checkpoint %s, line %lu: ",
                     CK3_FILE, CK3_LINE);
    va_list ap;
    if (n < 0 || (size_t)n >= sizeof msg)
        n = 0;
    va_start(ap, fmt);
    vsnprintf(msg + n, sizeof msg - (size_t)n, fmt, ap);
    va_end(ap);
    fprintf(stderr, "cft-orbits: %s\n", msg);    /* die()'s words and exit */
    exit(2);
}

/* The next line of the body, NUL-terminated in place; NULL past `end`. */
static char *ck3_line(char **cur, char *stop)
{
    char *p = *cur, *nl;
    if (p >= stop)
        return NULL;
    nl = (char *)memchr(p, '\n', (size_t)(stop - p));
    if (!nl)
        return NULL;
    *nl = 0;
    *cur = nl + 1;
    CK3_LINE++;
    return p;
}

/* The next line, which must be `key` and one space and its values, or
 * `key` alone when `bare`: the values, or "" when bare. */
static char *ck3_key(char **cur, char *stop, const char *key, int bare)
{
    char *ln = ck3_line(cur, stop);
    size_t n = strlen(key);
    if (!ln)
        ck3_die("the file ends where `%s` belongs", key);
    if (strncmp(ln, key, n) != 0 || (bare ? ln[n] != 0 : ln[n] != ' ' ||
                                     !ln[n + 1]))
        ck3_die("`%.80s` where `%s` belongs", ln, key);
    return ln + n + (bare ? 0 : 1);
}

/* One space-separated token of *p, in place; NULL when there is none. */
static char *ck3_tok(char **p)
{
    char *s = *p, *e;
    if (!*s)
        return NULL;
    e = strchr(s, ' ');
    if (e) {
        if (e == s || !e[1])
            return NULL;            /* two spaces, or one at the end */
        *e = 0;
        *p = e + 1;
    } else {
        *p = s + strlen(s);
    }
    return s;
}

/* A decimal in its one spelling, 0 or a nonzero digit and digits. */
static int ck3_dec(const char *s, uint64_t max, uint64_t *out)
{
    if (!*s || (s[0] == '0' && s[1]))
        return 0;
    return dec_u64(s, max, out);
}

static int ck3_hex64(const char *s)
{
    int i;
    for (i = 0; i < 64; i++)
        if (!((s[i] >= '0' && s[i] <= '9') || (s[i] >= 'a' && s[i] <= 'f')))
            return 0;
    return s[64] == 0;
}

/* `key <decimal>`, which must be `want`: else the sentence `why`. */
static void ck3_want(char **cur, char *stop, const char *key, uint64_t want,
                     const char *why)
{
    uint64_t v;
    char *val = ck3_key(cur, stop, key, 0);
    if (!ck3_dec(val, UINT64_MAX, &v))
        ck3_die("`%s %.40s` is not a decimal in its one spelling", key, val);
    if (v != want)
        die(why);
}

/* A `cert` line that must be `want`, one of this process's own lines. */
static void ck3_cert_line(runstate *R, char **cur, char *stop,
                          const char *want, size_t wn)
{
    char *ln = ck3_line(cur, stop);
    const char *key_end = memchr(want, ' ', wn);
    size_t kn = key_end ? (size_t)(key_end - want) : wn;
    char key[32];
    if (!ln)
        ck3_die("the file ends where `cert %.*s` belongs", (int)wn, want);
    if (strncmp(ln, "cert ", 5) != 0)
        ck3_die("`%.80s` where the certificate's `cert %.*s` belongs", ln,
                (int)kn, want);
    ln += 5;
    if (strlen(ln) == wn && memcmp(ln, want, wn) == 0)
        return;
    snprintf(key, sizeof key, "%.*s", (int)(kn < sizeof key - 1 ? kn
                                             : sizeof key - 1), want);
    if (!strcmp(key, "mode") && !strncmp(ln, "mode ", 5)) {
        if (!strcmp(ln + 5, "keyed") && !R->salt)
            refuse("salt-missing", "the run was certified keyed, and this "
                   "resume was handed --cert-open: resume it with the "
                   "--cert-salt it was started with");
        if (!strcmp(ln + 5, "open") && R->salt)
            refuse("salt-unexpected", "the run was certified open, and this "
                   "resume was handed --cert-salt: resume it with "
                   "--cert-open");
    }
    if (!strcmp(key, "salt-commitment") &&
        !strncmp(ln, "salt-commitment ", 16))
        refuse("salt-commitment", "HMAC(salt, 'cft-certificate 1 salt') "
               "of the --cert-salt handed is not the commitment the run was "
               "certified under: this is not its salt");
    if (!strcmp(key, "program-image") && !strncmp(ln, "program-image ", 14))
        refuse("image-digest", "the image this process builds for the "
               "stride, program-image %s, is not the one the run was "
               "certified with, %s: resume it with the build that started "
               "it, or start again", want + 14, ln + 14);
    if (!strcmp(key, "program-digest") &&
        !strncmp(ln, "program-digest ", 15))
        refuse("program-digest", "this process's program digest, %s, is "
               "not the one the run was certified with, %s", want + 15,
               ln + 15);
    ck3_die("`cert %.80s` where this run's certificate has `%.*s`", ln,
            (int)wn, want);
}

/* The identity lines: all six read, then compared, so a refusal names the
 * whole of both identities (the lead's decision, 2026-09-30). */
static void ck3_identity(char **cur, char *stop, const char **want,
                         const size_t *wn)
{
    static const char *const KEYS[6] = {
        "build-id", "backend", "device-xclbin", "device-version",
        "device-caps", "device-tiles"
    };
    char *got[6];
    int i, differ = 0;
    for (i = 0; i < 6; i++) {
        size_t kn = strlen(KEYS[i]);
        got[i] = ck3_line(cur, stop);
        if (!got[i])
            ck3_die("the file ends where `cert %s` belongs", KEYS[i]);
        if (strncmp(got[i], "cert ", 5) != 0 ||
            strncmp(got[i] + 5, KEYS[i], kn) != 0 || got[i][5 + kn] != ' ')
            ck3_die("`%.80s` where `cert %s` belongs", got[i], KEYS[i]);
        got[i] += 5 + kn + 1;                /* the value */
        if (strlen(got[i]) != wn[i] || memcmp(got[i], want[i], wn[i]) != 0)
            differ = 1;
    }
    if (differ)
        refuse("identity", "the run was certified on build-id %s, backend "
               "%s, device-xclbin %s, device-version %s, device-caps %s, "
               "device-tiles %s; this process is build-id %.*s, backend %.*s, "
               "device-xclbin %.*s, device-version %.*s, device-caps %.*s, "
               "device-tiles %.*s. A certificate names one build and one "
               "device: resume the run on those, or start it again", got[0],
               got[1], got[2], got[3], got[4], got[5], (int)wn[0], want[0],
               (int)wn[1], want[1], (int)wn[2], want[2], (int)wn[3], want[3],
               (int)wn[4], want[4], (int)wn[5], want[5]);
}

/* A flag word and STATUS this tool could have written for interval k: a
 * run stops at any flag but inexact (exit 3, note_flags) and at any
 * STATUS bit (seg_run), so no checkpoint of a certified run holds one. A
 * word outside that is refused, not carried into a certificate. */
static void ck3_possible(uint64_t fl, uint64_t st, uint64_t k)
{
    if (fl & CERT_FLAGS)
        ck3_die("interval %" PRIu64 " says flags %" PRIu64 ", and this tool "
                "stops a run at any flag but inexact (exit 3), so no "
                "checkpoint of its holds one", k, fl);
    if (st)
        ck3_die("interval %" PRIu64 " says STATUS %" PRIu64 ", and this tool "
                "stops a run at any STATUS bit, so no checkpoint of its holds "
                "one", k, st);
}

/* A cw_text's lines, one at a time: the next line and its length. */
static const char *ck3_next_of(const char **p, size_t *n)
{
    const char *s = *p, *nl;
    if (!s || !*s)
        return NULL;
    nl = strchr(s, '\n');
    if (!nl)
        return NULL;
    *n = (size_t)(nl - s);
    *p = nl + 1;
    return s;
}

static void ckpt_read3(runstate *R)
{
    const fmt_info *fi = R->fi;
    options *O = R->O;
    size_t esz = fi->esz, M = O->members, n = 0, m, wn[6];
    uint8_t *file, d[32];
    char *body, *stop, *cur, *val, *t, sum[65];
    const char *w, *want[6];
    uint64_t v, step, sample, j, fl, st;
    int c, k, i;

    CK3_FILE = O->ckpt;
    CK3_LINE = 0;
    errno = 0;
    file = cert_slurp(O->ckpt, (size_t)-1 / 2, &n);
    if (!file)
        die("cannot read the checkpoint named by --resume");
    /* the sum: the last line, over every byte before it */
    if (n < 70 || file[n - 1] != '\n')
        die("the checkpoint does not end in a `sum` line and a newline "
            "(version 3): it was cut, or it is not the file this tool wrote");
    body = (char *)file;
    stop = body + n - 1;                     /* the sum line's newline */
    t = stop;
    while (t > body && t[-1] != '\n')
        t--;
    if (stop - t != 68 || strncmp(t, "sum ", 4) != 0)
        die("the checkpoint's last line is not `sum` and 64 hex digits "
            "(version 3): it was cut, or it is not the file this tool wrote");
    *stop = 0;
    if (!ck3_hex64(t + 4))
        die("the checkpoint's `sum` is not 64 lowercase hex digits");
    {
        sha256 h;
        sha256_start(&h);
        sha256_push(&h, body, (size_t)(t - body));
        sha256_end(&h, d);
        hex32(d, sum);
    }
    if (strcmp(sum, t + 4) != 0)
        die("the checkpoint's `sum` is not the SHA-256 of what it follows: "
            "it is not the file this tool wrote, byte for byte - it was cut, "
            "or something else changed it (version 3)");
    stop = t;                                /* the body ends here */
    for (cur = body; cur < stop; cur++)
        if (*cur != '\n' && (*cur < 0x20 || *cur > 0x7e))
            die("the checkpoint holds a byte that is not printable ASCII");
    cur = body;

    /* version 2's lines */
    if (strcmp(ck3_key(&cur, stop, CKPT_MAGIC3, 1), "") != 0)
        ck3_die("not the version-3 magic line");
    val = ck3_key(&cur, stop, "format", 0);
    if (strcmp(val, cft_format_name(fi->fmt)))
        die("the checkpoint was written for a different format");
    val = ck3_key(&cur, stop, "problem", 0);
    if (strcmp(val, problem_name(O->problem)))
        die("the checkpoint was written for a different problem");
    val = ck3_key(&cur, stop, "scheme", 0);
    if (strcmp(val, scheme_name(O->scheme)))
        die("the checkpoint was written for a different scheme");
    val = ck3_key(&cur, stop, "rsqrt", 0);
    if (strcmp(val, rsqrt_name(O->rsqrt)))
        die("the checkpoint was written for a different 1/r^3 route");
    ck3_want(&cur, stop, "members", (uint64_t)M,
             "the checkpoint has a different ensemble size");
    ck3_want(&cur, stop, "spread", O->spread,
             "the checkpoint was written for a different --spread");
    ck3_want(&cur, stop, "bodies", (uint64_t)R->nb,
             "the checkpoint was written for a different problem");
    ck3_want(&cur, stop, "dims", (uint64_t)R->nd,
             "the checkpoint was written for a different problem");
    {
        uint8_t got[MAX_ESZ];
        val = ck3_key(&cur, stop, "h", 0);
        if (!val_from_dec_ok(fi, val, got, 1) || memcmp(got, R->s_h, esz))
            die("the checkpoint was written for a different step size");
    }
    ck3_want(&cur, stop, "steps", R->nsteps,
             "the checkpoint was written for a different step count");
    ck3_want(&cur, stop, "stride", R->stride,
             "the checkpoint was written for a different sample interval");
    ck3_want(&cur, stop, "samples", R->nsamples,
             "the checkpoint was written for a different sample count");
    val = ck3_key(&cur, stop, "at", 0);
    if (!(t = ck3_tok(&val)) || !ck3_dec(t, UINT64_MAX, &step) ||
        !(t = ck3_tok(&val)) || !ck3_dec(t, UINT64_MAX, &sample) || *val)
        ck3_die("bad checkpoint at-line");
    if (step > R->nsteps || sample > R->nsamples ||
        step < sample * R->stride || step - sample * R->stride > R->stride ||
        (sample == R->nsamples && step != R->nsteps))
        ck3_die("at %" PRIu64 " %" PRIu64 " is no place a run of %" PRIu64
                " steps sampled every %" PRIu64 " can be", step, sample,
                R->nsteps, R->stride);
    val = ck3_key(&cur, stop, "chain", 0);
    if (!ck3_hex64(val) || !unhex32(val, R->chain))
        ck3_die("bad checkpoint chain");
    val = ck3_key(&cur, stop, "recbytes", 0);
    if (!ck3_dec(val, UINT64_MAX, &R->rec_bytes))
        ck3_die("bad checkpoint recbytes line");
    for (m = 0; m < M; m++) {
        val = ck3_key(&cur, stop, "state", 0);
        if (!(t = ck3_tok(&val)) || !ck3_dec(t, UINT64_MAX, &v) || v != m)
            ck3_die("a state line out of its place: member %lu's belongs "
                    "here", (unsigned long)m);
        for (c = 0; c < 2 * R->ncomp; c++) {
            uint8_t *dst = c < R->ncomp ? CQ(R, c) + m * esz
                                        : CV(R, c - R->ncomp) + m * esz;
            if (!(t = ck3_tok(&val)) || !val_from_dec_ok(fi, t, dst, 1))
                ck3_die("bad checkpoint state value");
        }
        if (*val)
            ck3_die("a state line longer than a member's state");
    }
    for (m = 0; m < M; m++) {
        uint8_t *dst[8];
        int nd = 0;
        val = ck3_key(&cur, stop, "inv", 0);
        if (!(t = ck3_tok(&val)) || !ck3_dec(t, UINT64_MAX, &v) || v != m)
            ck3_die("an inv line out of its place: member %lu's belongs "
                    "here", (unsigned long)m);
        dst[nd++] = R->H0 + m * esz;
        dst[nd++] = R->dHmax + m * esz;
        for (k = 0; k < R->nL; k++) {
            dst[nd++] = R->L0[k] + m * esz;
            dst[nd++] = R->dLmax[k] + m * esz;
        }
        for (i = 0; i < nd; i++)
            if (!(t = ck3_tok(&val)) || !val_from_dec_ok(fi, t, dst[i], 1))
                ck3_die("bad checkpoint invariant");
        if (*val)
            ck3_die("an inv line longer than a member's invariants");
    }

    /* the certificate so far: its lines through `segments`, this
     * process's own - the identity's six read whole, then compared */
    {
        const char *ln[32];
        size_t lnn[32];
        int nl = 0, x;
        for (x = 0; x < 2; x++) {
            w = x ? R->c_runhead.p : R->c_ident.p;
            while (nl < 32 && (ln[nl] = ck3_next_of(&w, &lnn[nl])) != NULL)
                nl++;
        }
        for (x = 0; x < nl; x++) {
            if (!strncmp(ln[x], "build-id ", 9) && x + 6 <= nl) {
                for (i = 0; i < 6; i++) {
                    const char *sp = memchr(ln[x + i], ' ', lnn[x + i]);
                    want[i] = sp + 1;
                    wn[i] = lnn[x + i] - (size_t)(sp + 1 - ln[x + i]);
                }
                ck3_identity(&cur, stop, want, wn);
                x += 5;
                continue;
            }
            ck3_cert_line(R, &cur, stop, ln[x], lnn[x]);
        }
    }
    /* the entries the run was started to write: a certificate states one
     * set, so a resume asks for the same */
    val = ck3_key(&cur, stop, "cert entries", 0);
    if (strcmp(val, "none") && strcmp(val, "angular-momentum-drift"))
        ck3_die("`cert entries` is none or angular-momentum-drift, not "
                "`%.40s`", val);
    if (strcmp(val, R->c_angmom ? "angular-momentum-drift" : "none"))
        die(R->c_angmom
            ? "the run was certified without accuracy entries, and this "
              "resume asks for --cert-accuracy angular-momentum-drift: a "
              "certificate states one set of entries - resume the run as it "
              "was started, or start it again"
            : "the run was certified with --cert-accuracy "
              "angular-momentum-drift, and this resume asks for none: a "
              "certificate states one set of entries - resume the run as it "
              "was started, or start it again");
    val = ck3_key(&cur, stop, "cert boundary", 0);
    if (!(t = ck3_tok(&val)) || strcmp(t, "0") || !ck3_hex64(val))
        ck3_die("`cert boundary 0` and the initial state's hash belong here");
    memcpy(R->c_bhash[0], val, CW_HEX);
    for (j = 0; j < sample; j++) {
        val = ck3_key(&cur, stop, "cert segment", 0);
        if (!(t = ck3_tok(&val)) || !ck3_dec(t, UINT64_MAX, &v) || v != j)
            ck3_die("segment %" PRIu64 "'s line belongs here: the "
                    "checkpoint is %" PRIu64 " intervals in", j, sample);
        if (!(t = ck3_tok(&val)) || strcmp(t, "start") ||
            !(t = ck3_tok(&val)) || !ck3_hex64(t))
            ck3_die("a segment line's start hash");
        if (strcmp(t, R->c_bhash[j]) != 0)
            ck3_die("segment %" PRIu64 " does not start where %s", j,
                    j ? "the segment before it ended"
                      : "boundary 0, the initial state, is");
        if (!(t = ck3_tok(&val)) || strcmp(t, "end") ||
            !(t = ck3_tok(&val)) || !ck3_hex64(t))
            ck3_die("a segment line's end hash");
        memcpy(R->c_bhash[j + 1], t, CW_HEX);
        if (!(t = ck3_tok(&val)) || strcmp(t, "flags") ||
            !(t = ck3_tok(&val)) || !ck3_dec(t, 31, &fl) ||
            !(t = ck3_tok(&val)) || strcmp(t, "status") ||
            !(t = ck3_tok(&val)) || !ck3_dec(t, 0xffffffffull, &st) || *val)
            ck3_die("a segment line's flag word (0 to 31) and STATUS");
        ck3_possible(fl, st, j);
        R->c_flags[j] = (uint32_t)fl;
        R->c_status[j] = (uint32_t)st;
    }
    val = ck3_key(&cur, stop, "cert interval", 0);
    if (!(t = ck3_tok(&val)) || strcmp(t, "flags") ||
        !(t = ck3_tok(&val)) || !ck3_dec(t, 31, &fl) ||
        !(t = ck3_tok(&val)) || strcmp(t, "status") ||
        !(t = ck3_tok(&val)) || !ck3_dec(t, 0xffffffffull, &st) || *val)
        ck3_die("`cert interval flags <0..31> status <n>` belongs here");
    ck3_possible(fl, st, sample);
    if (step == sample * R->stride && (fl || st))
        ck3_die("the interval in progress has run no step, and says it "
                "raised flags %" PRIu64 " and STATUS %" PRIu64, fl, st);
    R->c_iflags = (uint32_t)fl;
    R->c_istatus = (uint32_t)st;
    if (NEGCTL_DROP_FLAGS)
        R->c_iflags = R->c_istatus = 0;      /* the planted defect */
    (void)ck3_key(&cur, stop, "end", 1);
    if (cur != stop)
        ck3_die("a line after `end`, before the sum");
    free(file);

    R->step = step;
    R->sample = sample;
    /* at a sample boundary the state IS that boundary */
    if (step == sample * R->stride) {
        char h[CW_HEX];
        cert_pack(R, R->c_state);
        cert_ok(cw_state_hash(R->salt, R->c_state, R->c_state_bytes, h),
                "the checkpoint's state's hash");
        if (strcmp(h, R->c_bhash[sample]) != 0)
            die("the checkpoint's state is not boundary the run certified "
                "where the checkpoint says it is");
    }
    R->c_replace_from = sample;
}

static void ckpt_read(runstate *R)
{
    const fmt_info *fi = R->fi;
    options *O = R->O;
    FILE *f = fopen(O->ckpt, "rb");
    size_t esz = fi->esz, linecap = (size_t)(2 * R->ncomp + 8) * DECMAX;
    char *line = (char *)xcalloc(1, linecap);
    char tok[DECMAX];
    int c, k, have_recbytes = 0;

    if (!f)
        die("cannot read the checkpoint named by --resume");
    if (!fgets(line, (int)linecap, f))
        die("that file is not a cft-orbits checkpoint of this version");
    trim_nl(line);
    if (!strcmp(line, CKPT_MAGIC3)) {
        fclose(f);
        free(line);
        if (!R->cert)
            die("the checkpoint is version 3, a certified run's: resume it "
                "with --cert, --cert-states and the salt choice it was "
                "started with (docs/ORBITS.md, \"Certified runs\")");
        ckpt_read3(R);
        return;
    }
    if (strcmp(line, CKPT_MAGIC) != 0)
        die("that file is not a cft-orbits checkpoint of this version");
    if (R->cert)
        die("the checkpoint is version 2, a run that was not certified: no "
            "interval before its step has a hash or a flag word, so --cert "
            "cannot resume it - resume it without --cert, or start the "
            "certified run again (a certified run's checkpoint is version 3)");

    while (fgets(line, (int)linecap, f)) {
        char *p = line;
        trim_nl(line);
        if (!next_tok(&p, tok, sizeof tok))
            continue;
        if (!strcmp(tok, "format")) {
            if (!next_tok(&p, tok, sizeof tok) ||
                strcmp(tok, cft_format_name(fi->fmt)))
                die("the checkpoint was written for a different format");
        } else if (!strcmp(tok, "problem")) {
            if (!next_tok(&p, tok, sizeof tok) ||
                strcmp(tok, problem_name(O->problem)))
                die("the checkpoint was written for a different problem");
        } else if (!strcmp(tok, "scheme")) {
            if (!next_tok(&p, tok, sizeof tok) ||
                strcmp(tok, scheme_name(O->scheme)))
                die("the checkpoint was written for a different scheme");
        } else if (!strcmp(tok, "rsqrt")) {
            if (!next_tok(&p, tok, sizeof tok) ||
                strcmp(tok, rsqrt_name(O->rsqrt)))
                die("the checkpoint was written for a different 1/r^3 route");
        } else if (!strcmp(tok, "members")) {
            if (!next_tok(&p, tok, sizeof tok) ||
                strtoull(tok, NULL, 10) != (unsigned long long)O->members)
                die("the checkpoint has a different ensemble size");
        } else if (!strcmp(tok, "steps")) {
            if (!next_tok(&p, tok, sizeof tok) ||
                strtoull(tok, NULL, 10) != R->nsteps)
                die("the checkpoint was written for a different step count");
        } else if (!strcmp(tok, "stride")) {
            if (!next_tok(&p, tok, sizeof tok) ||
                strtoull(tok, NULL, 10) != R->stride)
                die("the checkpoint was written for a different sample "
                    "interval");
        } else if (!strcmp(tok, "h")) {
            uint8_t got[MAX_ESZ];
            if (!next_tok(&p, tok, sizeof tok) ||
                !val_from_dec_ok(fi, tok, got, 1) ||
                memcmp(got, R->s_h, esz) != 0)
                die("the checkpoint was written for a different step size");
        } else if (!strcmp(tok, "at")) {
            if (!next_tok(&p, tok, sizeof tok))
                die("bad checkpoint at-line");
            R->step = strtoull(tok, NULL, 10);
            if (!next_tok(&p, tok, sizeof tok))
                die("bad checkpoint at-line");
            R->sample = strtoull(tok, NULL, 10);
        } else if (!strcmp(tok, "chain")) {
            if (!next_tok(&p, tok, sizeof tok) || !unhex32(tok, R->chain))
                die("bad checkpoint chain");
        } else if (!strcmp(tok, "recbytes")) {
            if (!next_tok(&p, tok, sizeof tok) ||
                !dec_u64(tok, UINT64_MAX, &R->rec_bytes))
                die("bad checkpoint recbytes line");
            have_recbytes = 1;
        } else if (!strcmp(tok, "state")) {
            size_t m;
            if (!next_tok(&p, tok, sizeof tok))
                die("bad checkpoint state line");
            m = (size_t)strtoull(tok, NULL, 10);
            if (m >= O->members)
                die("a checkpoint state line names a member out of range");
            for (c = 0; c < R->ncomp; c++)
                if (!next_tok(&p, tok, sizeof tok) ||
                    !val_from_dec_ok(fi, tok, CQ(R, c) + m * esz, 1))
                    die("bad checkpoint position");
            for (c = 0; c < R->ncomp; c++)
                if (!next_tok(&p, tok, sizeof tok) ||
                    !val_from_dec_ok(fi, tok, CV(R, c) + m * esz, 1))
                    die("bad checkpoint velocity");
        } else if (!strcmp(tok, "inv")) {
            size_t m;
            if (!next_tok(&p, tok, sizeof tok))
                die("bad checkpoint inv line");
            m = (size_t)strtoull(tok, NULL, 10);
            if (m >= O->members)
                die("a checkpoint inv line names a member out of range");
            if (!next_tok(&p, tok, sizeof tok) ||
                !val_from_dec_ok(fi, tok, R->H0 + m * esz, 1) ||
                !next_tok(&p, tok, sizeof tok) ||
                !val_from_dec_ok(fi, tok, R->dHmax + m * esz, 1))
                die("bad checkpoint invariant");
            for (k = 0; k < R->nL; k++)
                if (!next_tok(&p, tok, sizeof tok) ||
                    !val_from_dec_ok(fi, tok, R->L0[k] + m * esz, 1) ||
                    !next_tok(&p, tok, sizeof tok) ||
                    !val_from_dec_ok(fi, tok, R->dLmax[k] + m * esz, 1))
                    die("bad checkpoint invariant");
        } else if (!strcmp(tok, "end")) {
            break;
        }
    }
    fclose(f);
    free(line);
    if (!have_recbytes)
        die("the checkpoint does not say how long its records are (no "
            "recbytes line)");
}

/* --records that could not be opened for writing, or not emptied for a
 * fresh run: refused with the step, the path and the system's own words
 * for why (SYS_ERR, noted where the call failed). */
static void records_refused(const char *step, const char *path,
                            const char *after)
{
    char msg[1800];
    snprintf(msg, sizeof msg, "could not %s the records file %s (%s)%s",
             step, path, SYS_ERR, after);
    die(msg);
}

/* --records and --checkpoint naming one file: the checkpoint is written
 * to <path>.tmp and renamed over <path> at every interval, so on POSIX
 * the records go on into an unlinked file and are lost with exit 0,
 * and on Windows the rename is refused while the records hold the file
 * and the run dies blaming another process (verifier-V6, 2026-09-25,
 * both measured). Refused by name, and before a byte of either file is
 * cut: as the paths are written, before anything is opened; and as
 * files - two spellings of one file - on --resume once the records
 * path is known to be a regular file, and on a fresh run on the records
 * file opened but not yet cut (open_uncut). A records path that may be
 * a named pipe is never opened a second time to ask, since opening one
 * connects to it. */
static void records_apart(const options *O, FILE *open_records,
                          int by_path)
{
    char tmp[1100], msg[2400];
    uint64_t r[2], c[2];
    const char *how = NULL;

    snprintf(tmp, sizeof tmp, "%s.tmp", O->ckpt);
    if (!strcmp(O->records_path, O->ckpt) || !strcmp(O->records_path, tmp))
        how = "the same path";
    else if ((open_records || by_path) &&
             file_id(O->records_path, open_records, r) &&
             ((file_id(O->ckpt, NULL, c) && c[0] == r[0] && c[1] == r[1]) ||
              (file_id(tmp, NULL, c) && c[0] == r[0] && c[1] == r[1])))
        how = "one file under two names";
    if (how) {
        snprintf(msg, sizeof msg,
                 "--records %s and --checkpoint %s are %s - the checkpoint "
                 "is written beside its path and renamed over it at every "
                 "interval, which would lose the records; give each its "
                 "own file", O->records_path, O->ckpt, how);
        die(msg);
    }
}

/* --resume with --records. The checkpoint says how long the record
 * stream was when it was written (recbytes) and what those records hash
 * to (chain). The file must hold at least that many bytes, and those
 * bytes must hash to that chain; otherwise it is not this run's records
 * - cut short, another run's, or edited - and the resume is refused by
 * name, with nothing touched. Whatever lies past them was written after
 * the checkpoint: records the resumed run writes again, and usually a
 * line a kill cut in half. It is cut away before a byte is appended, so
 * a killed and resumed run's records are the uninterrupted run's, byte
 * for byte, and still hash to its chain. */
static void records_resume(runstate *R)
{
    const char *path = R->O->records_path;
    const size_t chunk = (size_t)1 << 16;
    unsigned char *buf;
    uint8_t chain[32];
    uint64_t have = 0;
    int64_t size;
    int in_line = 0;
    sha256 h;
    char msg[1400];
    FILE *f;

    /* Only a regular file can be read back and cut. A pipe or a FIFO
     * would be read by a process that holds its write end, or that no
     * one writes - and wait for ever (c8a7d97 did, verifier-V6) - and a
     * device or a directory holds no records; so each is refused here,
     * before anything is read or written. */
    if (path_kind(path) == 0) {
        snprintf(msg, sizeof msg,
                 "--resume: --records names %s, which is not a regular file "
                 "(a pipe, a FIFO, a device or a directory) - a resume "
                 "reads the records back and cuts them to the checkpoint, "
                 "which only a regular file allows; resume into a file and "
                 "pass it on from there, or resume without --records", path);
        die(msg);
    }
    if (R->O->ckpt)
        records_apart(R->O, NULL, 1);
    /* The file must open, and say how long it is, before a byte is read:
     * a file that cannot be opened is named for that - locked or held by
     * another process, say - not for being short (c8a7d97 called it
     * "0 bytes ... cut short"), and nothing is read past the length the
     * file itself gives. That bound is what keeps a Linux FIFO seen
     * through the WSL share, which Windows takes for an empty regular
     * file, from being read and waited on (verifier-V6). */
    errno = 0;
    f = fopen(path, "rb");
    if (!f) {
        int e = errno;
        if (e == ENOENT)
            snprintf(msg, sizeof msg,
                     "--resume: there is no records file %s, and the "
                     "checkpoint's records run to %" PRIu64 " bytes - resume "
                     "with the file the run wrote, or without --records",
                     path, R->rec_bytes);
        else
            snprintf(msg, sizeof msg,
                     "--resume: the records file %s could not be opened to "
                     "be read back (%s) - another process may hold it open "
                     "or locked, or this one may not read it; nothing was "
                     "changed: resume once it can be read, or without "
                     "--records", path, e ? strerror(e) : "no reason given");
        die(msg);
    }
    size = file_length(f);
    if (size < 0 || (uint64_t)size < R->rec_bytes) {
        fclose(f);
        snprintf(msg, sizeof msg,
                 "--resume: the records file %s holds %" PRId64 " bytes and "
                 "the checkpoint's records run to %" PRIu64 " - it was cut "
                 "short, or it is not this run's; resume with the file the "
                 "run wrote, or without --records", path,
                 size < 0 ? (int64_t)0 : size, R->rec_bytes);
        die(msg);
    }
    buf = (unsigned char *)xcalloc(1, chunk);
    memset(chain, 0, sizeof chain);
    sha256_start(&h);
    while (have < R->rec_bytes) {
        uint64_t left = R->rec_bytes - have;
        size_t got = fread(buf, 1, left < chunk ? (size_t)left : chunk, f);
        size_t i, from = 0;
        if (!got) {
            if (ferror(f)) {
                int e = errno;
                fclose(f);
                free(buf);
                snprintf(msg, sizeof msg,
                         "--resume: the records file %s could not be read "
                         "back (%s) after %" PRIu64 " bytes - another "
                         "process may hold part of it locked; nothing was "
                         "changed", path, e ? strerror(e) : "a read error",
                         have);
                die(msg);
            }
            break;
        }
        for (i = 0; i < got; i++) {
            if (buf[i] != '\n')
                continue;
            if (!in_line) {
                sha256_start(&h);
                sha256_push(&h, chain, sizeof chain);
            }
            sha256_push(&h, buf + from, i - from);
            sha256_push(&h, "\n", 1);
            sha256_end(&h, chain);
            in_line = 0;
            from = i + 1;
        }
        if (from < got) {
            if (!in_line) {
                sha256_start(&h);
                sha256_push(&h, chain, sizeof chain);
                in_line = 1;
            }
            sha256_push(&h, buf + from, got - from);
        }
        have += got;
    }
    fclose(f);
    free(buf);
    if (have < R->rec_bytes) {           /* it shrank while being read */
        snprintf(msg, sizeof msg,
                 "--resume: the records file %s holds %" PRIu64 " bytes and "
                 "the checkpoint's records run to %" PRIu64 " - it was cut "
                 "short, or it is not this run's; resume with the file the "
                 "run wrote, or without --records", path, have,
                 R->rec_bytes);
        die(msg);
    }
    if (in_line || memcmp(chain, R->chain, sizeof chain) != 0) {
        snprintf(msg, sizeof msg,
                 "--resume: the first %" PRIu64 " bytes of the records file "
                 "%s do not hash to the checkpoint's chain - it is not the "
                 "records this run wrote", R->rec_bytes, path);
        die(msg);
    }
    if (file_cut(path, R->rec_bytes) != 0)
        die("--resume could not cut the records file back to the "
            "checkpoint");
}

/* ===================================================================
 * Setting the ensemble up
 * =================================================================== */

/* nextUp applied `n` times to a positive finite value, as one integer
 * add on the encoding - the tile's own CFT_IADD, no rounding, no
 * flag. The perturbation ladder is therefore exact and identical on
 * every backend. */
static void bump_ulps(runstate *R, uint8_t *val, uint64_t n)
{
    const fmt_info *fi = R->fi;
    uint8_t bits[MAX_ESZ], zero[MAX_ESZ];
    size_t i;
    if (!n)
        return;
    memset(bits, 0, fi->esz);
    for (i = 0; i < 8 && i < fi->esz; i++)
        bits[i] = (uint8_t)(n >> (8 * i));
    memset(zero, 0, fi->esz);
    if (!val_lt(fi, zero, val))
        die("the perturbation ladder only steps positive values");
    run1(CFT_IADD, fi, val, bits, NULL, val);
}

static void setup_state(runstate *R)
{
    const fmt_info *fi = R->fi;
    options *O = R->O;
    size_t esz = fi->esz, M = O->members, m;
    uint8_t tmp[MAX_ESZ];
    int b, k;

    if (O->problem == PROB_KEPLER) {
        uint8_t num[MAX_ESZ], den[MAX_ESZ], q0[MAX_ESZ], v1[MAX_ESZ];
        /* q0 = 1 - e = (DEN-NUM)/DEN, exact for a dyadic denominator */
        val_from_i64(fi, ECC_DEN - ECC_NUM, num);
        val_from_i64(fi, ECC_DEN, den);
        {
            uint32_t fl = 0;
            cft_status st = cft_div(DEV, fi->fmt, CFT_RNE, num, den, q0, 1,
                                    &fl, NULL);
            if (st != CFT_OK)
                die_st("cft_div", st);
            if (fl & CFT_FLAG_INEXACT)
                die("1 - e is not exact: choose a dyadic eccentricity");
            /* v1 = sqrt((1+e)/(1-e)) */
            val_from_i64(fi, ECC_DEN + ECC_NUM, num);
            val_from_i64(fi, ECC_DEN - ECC_NUM, den);
            st = cft_div(DEV, fi->fmt, CFT_RNE, num, den, tmp, 1, &fl, NULL);
            if (st != CFT_OK)
                die_st("cft_div", st);
            st = cft_sqrt(DEV, fi->fmt, CFT_RNE, tmp, v1, 1, NULL, NULL);
            if (st != CFT_OK)
                die_st("cft_sqrt", st);
        }
        for (m = 0; m < M; m++) {
            memcpy(CQ(R, 0) + m * esz, q0, esz);
            memset(CQ(R, 1) + m * esz, 0, esz);
            memset(CV(R, 0) + m * esz, 0, esz);
            memcpy(CV(R, 1) + m * esz, v1, esz);
            /* the ladder: member 0 unperturbed, then alternate q0 and
             * v1 with a rung of --spread ulps each time round */
            if (m) {
                uint64_t rung = (uint64_t)((m + 1) / 2) * O->spread;
                if (m & 1)
                    bump_ulps(R, CQ(R, 0) + m * esz, rung);
                else
                    bump_ulps(R, CV(R, 1) + m * esz, rung);
            }
        }
        return;
    }

    for (b = 0; b < R->nb; b++) {
        for (k = 0; k < R->nd; k++) {
            val_from_dec(fi, OUTER[b].q[k], tmp);
            for (m = 0; m < M; m++)
                memcpy(CQ(R, COMP(R, b, k)) + m * esz, tmp, esz);
            val_from_dec(fi, OUTER[b].v[k], tmp);
            for (m = 0; m < M; m++)
                memcpy(CV(R, COMP(R, b, k)) + m * esz, tmp, esz);
        }
    }
    /* the ladder, on Jupiter's x, alternating position and velocity.
     * Both are positive-signed? They are not - Jupiter's x is
     * negative - so the ladder steps the MAGNITUDE by working on
     * |x| and putting the sign back, which is still an exact
     * integer step on the encoding. */
    for (m = 1; m < M; m++) {
        uint64_t rung = (uint64_t)((m + 1) / 2) * O->spread;
        uint8_t *slot = (m & 1) ? CQ(R, COMP(R, 1, 0)) + m * esz
                                : CV(R, COMP(R, 1, 0)) + m * esz;
        uint8_t mag[MAX_ESZ], sgn[MAX_ESZ];
        memcpy(sgn, slot, esz);
        run1(CFT_ABS, fi, slot, NULL, NULL, mag);
        bump_ulps(R, mag, rung);
        run1(CFT_COPYSIGN, fi, mag, sgn, NULL, slot);
    }
}

/* ===================================================================
 * Constants: the step size, the composition weights, the masses
 * =================================================================== */
static void setup_constants(runstate *R)
{
    const fmt_info *fi = R->fi;
    options *O = R->O;
    uint8_t one[MAX_ESZ], mone[MAX_ESZ], two[MAX_ESZ], tmp[MAX_ESZ];
    uint8_t half[MAX_ESZ], mhalf[MAX_ESZ], h[MAX_ESZ];
    uint8_t wgt[MAX_SUB][MAX_ESZ];
    uint8_t mass[MAX_BODIES][MAX_ESZ], gconst[MAX_ESZ];
    cft_status st;
    int s, b, j;

    val_from_i64(fi, 1, one);
    val_from_i64(fi, -1, mone);
    val_from_i64(fi, 2, two);
    val_pow2(fi, -1, half);
    run1(CFT_NEG, fi, half, NULL, NULL, mhalf);

    R->c_mone  = alloc_bcast(R, mone);
    R->c_half  = alloc_bcast(R, half);
    R->c_mhalf = alloc_bcast(R, mhalf);

    /* --- the step size --- */
    if (O->problem == PROB_KEPLER) {
        /* h = 2 pi / steps_per_period, with pi from the library:
         * acos(-1) is correctly rounded, so pi is the format's pi and
         * not a transcription of anybody's digits. */
        uint8_t pi[MAX_ESZ], twopi[MAX_ESZ], nsp[MAX_ESZ];
        st = cft_acos(DEV, fi->fmt, CFT_RNE, mone, pi, 1, NULL);
        if (st != CFT_OK)
            die_st("cft_acos", st);
        run1(CFT_MUL, fi, pi, two, NULL, twopi);
        val_from_i64(fi, (int64_t)O->steps_per_period, nsp);
        st = cft_div(DEV, fi->fmt, CFT_RNE, twopi, nsp, h, 1, NULL, NULL);
        if (st != CFT_OK)
            die_st("cft_div", st);
    } else {
        val_from_i64(fi, (int64_t)O->days, h);
    }
    memcpy(R->s_h, h, fi->esz);

    /* --- the composition weights --- */
    if (O->scheme == SCHEME_LEAPFROG) {
        R->nsub = 1;
        memcpy(wgt[0], one, fi->esz);
    } else {
        /* w1 = 1/(2 - 2^(1/3)),  w0 = -2^(1/3) * w1, derived from
         * rootn(2, 3) - 754-2019 9.2's correctly rounded root. */
        uint8_t cbrt2[MAX_ESZ], den[MAX_ESZ], w1[MAX_ESZ], w0[MAX_ESZ];
        int64_t three = 3;
        st = cft_rootn(DEV, fi->fmt, CFT_RNE, two, &three, cbrt2, 1, NULL);
        if (st != CFT_OK)
            die_st("cft_rootn", st);
        run1(CFT_SUB, fi, two, NULL, cbrt2, den);
        st = cft_div(DEV, fi->fmt, CFT_RNE, one, den, w1, 1, NULL, NULL);
        if (st != CFT_OK)
            die_st("cft_div", st);
        run1(CFT_MUL, fi, cbrt2, w1, NULL, tmp);
        run1(CFT_NEG, fi, tmp, NULL, NULL, w0);
        R->nsub = 3;
        memcpy(wgt[0], w1, fi->esz);
        memcpy(wgt[1], w0, fi->esz);
        memcpy(wgt[2], w1, fi->esz);
    }

    /* --- masses and G --- */
    if (O->problem == PROB_KEPLER) {
        val_from_i64(fi, 1, mass[0]);              /* mu = 1 */
        R->c_mu = alloc_bcast(R, mass[0]);
    } else {
        uint8_t k[MAX_ESZ];
        val_from_dec(fi, GAUSS_K, k);
        run1(CFT_MUL, fi, k, k, NULL, gconst);     /* G = k^2 */
        R->c_G = alloc_bcast(R, gconst);
        for (b = 0; b < R->nb; b++) {
            val_from_dec(fi, OUTER[b].mass, mass[b]);
            R->c_m[b] = alloc_bcast(R, mass[b]);
            run1(CFT_MUL, fi, mass[b], half, NULL, tmp);
            R->c_halfm[b] = alloc_bcast(R, tmp);
        }
        for (b = 0; b < R->nb; b++)
            for (j = b + 1; j < R->nb; j++) {
                run1(CFT_MUL, fi, gconst, mass[b], NULL, tmp);
                run1(CFT_MUL, fi, tmp, mass[j], NULL, tmp);
                R->c_gmm[b][j] = alloc_bcast(R, tmp);
            }
    }

    /* --- the per-substep drift and kick scales --- */
    for (s = 0; s < R->nsub; s++) {
        uint8_t hs[MAX_ESZ], hd[MAX_ESZ];
        run1(CFT_MUL, fi, wgt[s], h, NULL, hs);        /* w_s h        */
        run1(CFT_MUL, fi, hs, half, NULL, hd);         /* w_s h / 2    */
        R->c_hd[s] = alloc_bcast(R, hd);
        if (O->problem == PROB_KEPLER) {
            run1(CFT_MUL, fi, hs, mass[0], NULL, tmp); /* w_s h mu     */
            run1(CFT_NEG, fi, tmp, NULL, NULL, tmp);
            R->c_mg[s] = alloc_bcast(R, tmp);
        } else {
            for (b = 0; b < R->nb; b++) {
                run1(CFT_MUL, fi, hs, mass[b], NULL, tmp);
                R->c_hm[s][b] = alloc_bcast(R, tmp);
                run1(CFT_NEG, fi, tmp, NULL, NULL, tmp);
                R->c_mhm[s][b] = alloc_bcast(R, tmp);
            }
        }
    }
}

/* ===================================================================
 * Reporting
 * =================================================================== */
static void max_over_members(runstate *R, const uint8_t *a, uint8_t *out)
{
    const fmt_info *fi = R->fi;
    size_t esz = fi->esz, m;
    memcpy(out, a, esz);
    for (m = 1; m < R->O->members; m++)
        if (val_lt(fi, out, a + m * esz))
            memcpy(out, a + m * esz, esz);
}

/* The separation of each member from member 0, as a Euclidean norm
 * over the whole state vector. One-element library calls: the
 * ensemble is the element axis, so a cross-member quantity cannot be
 * an elementwise op and is assembled member by member instead. */
static void separations(runstate *R, const uint8_t *qq, const uint8_t *vv,
                        uint8_t *out)
{
    const fmt_info *fi = R->fi;
    size_t esz = fi->esz, M = R->O->members, m;
    uint8_t acc[MAX_ESZ], t[MAX_ESZ], u[MAX_ESZ];
    int c;
    for (m = 0; m < M; m++) {
        memset(acc, 0, esz);
        for (c = 0; c < R->ncomp; c++) {
            run1(CFT_SUB, fi, qq + ((size_t)c * M + m) * esz, NULL,
                 qq + (size_t)c * M * esz, t);
            run1(CFT_FMA, fi, t, t, acc, acc);
            run1(CFT_SUB, fi, vv + ((size_t)c * M + m) * esz, NULL,
                 vv + (size_t)c * M * esz, u);
            run1(CFT_FMA, fi, u, u, acc, acc);
        }
        if (cft_sqrt(DEV, fi->fmt, CFT_RNE, acc, out + m * esz, 1, NULL,
                     NULL) != CFT_OK)
            die("cft_sqrt failed computing a separation");
    }
}

/* Every derived constant the integration will use, as an EXACT
 * decimal - the step size, the composition weights folded into the
 * drift and kick scales, G, the masses, the pairwise products.
 *
 * This is not a debugging aid. The 300-digit oracle has to run the
 * SAME discrete scheme the tool ran, and "the same" includes the
 * constants: h is fl(2*pi/S), the drift scale is fl(fl(w*h)*0.5), and
 * an oracle that used the exact real numbers instead would be
 * measuring the constants' rounding as though it were the
 * integration's. So the tool states what it is about to compute with,
 * the same way a program image can be read back to attest what
 * executed. */
static void dump_setup(runstate *R)
{
    const fmt_info *fi = R->fi;
    options *O = R->O;
    char dec[DECMAX];
    int s, b, j;

    printf("setup format %s\n", cft_format_name(fi->fmt));
    printf("setup precision %d\n", fi->prec);
    printf("setup newton %d\n", fi->newton);
    printf("setup problem %s\n", problem_name(O->problem));
    printf("setup scheme %s\n", scheme_name(O->scheme));
    printf("setup rsqrt %s\n", rsqrt_name(O->rsqrt));
    printf("setup bodies %d\n", R->nb);
    printf("setup dims %d\n", R->nd);
    printf("setup nsub %d\n", R->nsub);
    printf("setup members %" PRIu64 "\n", (uint64_t)O->members);
    printf("setup steps %" PRIu64 "\n", R->nsteps);
    printf("setup stride %" PRIu64 "\n", R->stride);
    printf("setup samples %" PRIu64 "\n", R->nsamples);
    val_to_dec(fi, R->s_h, dec, sizeof dec);
    printf("setup h %s\n", dec);
    for (s = 0; s < R->nsub; s++) {
        val_to_dec(fi, R->c_hd[s], dec, sizeof dec);
        printf("setup hd %d %s\n", s, dec);
        if (O->problem == PROB_KEPLER) {
            val_to_dec(fi, R->c_mg[s], dec, sizeof dec);
            printf("setup mg %d %s\n", s, dec);
        } else {
            for (b = 0; b < R->nb; b++) {
                val_to_dec(fi, R->c_hm[s][b], dec, sizeof dec);
                printf("setup hm %d %d %s\n", s, b, dec);
                val_to_dec(fi, R->c_mhm[s][b], dec, sizeof dec);
                printf("setup mhm %d %d %s\n", s, b, dec);
            }
        }
    }
    if (O->problem == PROB_KEPLER) {
        val_to_dec(fi, R->c_mu, dec, sizeof dec);
        printf("setup mu %s\n", dec);
    } else {
        val_to_dec(fi, R->c_G, dec, sizeof dec);
        printf("setup G %s\n", dec);
        for (b = 0; b < R->nb; b++) {
            val_to_dec(fi, R->c_m[b], dec, sizeof dec);
            printf("setup mass %d %s\n", b, dec);
            val_to_dec(fi, R->c_halfm[b], dec, sizeof dec);
            printf("setup halfm %d %s\n", b, dec);
        }
        for (b = 0; b < R->nb; b++)
            for (j = b + 1; j < R->nb; j++) {
                val_to_dec(fi, R->c_gmm[b][j], dec, sizeof dec);
                printf("setup gmm %d %d %s\n", b, j, dec);
            }
    }
    val_to_dec(fi, R->c_half, dec, sizeof dec);
    printf("setup half %s\n", dec);
    printf("setup end\n");
}

static void report(runstate *R, double elapsed, const char *backend)
{
    const fmt_info *fi = R->fi;
    options *O = R->O;
    size_t esz = fi->esz, M = O->members, m;
    uint8_t worstH[MAX_ESZ], worstL[MAX_ESZ], rel[MAX_ESZ], tmp[MAX_ESZ];
    uint8_t *sep0, *sep1;
    char chain[65], sh[64], sdh[64], sdl[64], ssep[64], sgrow[64];
    /* Snapshot before this function does any arithmetic of its own:
     * what is reported is what the INTEGRATION raised. */
    uint32_t flags_run = FLAGS_SEEN, status_run = cft_save_all_flags(DEV);
    double steps_s = elapsed > 0 ? (double)R->step / elapsed : 0.0;
    double elem_s = elapsed > 0 ?
        (double)R->step * (double)M / elapsed : 0.0;
    double ops_s = elapsed > 0 ?
        (double)(N_ELEMOPS + N_COMPOSED) / elapsed : 0.0;
    int k;

    hex32(R->chain, chain);
    val_to_dec_short(fi, R->s_h, sh, sizeof sh, 12);

    /* the worst relative energy drift over the ensemble */
    max_over_members(R, R->dHmax, worstH);
    run1(CFT_ABS, fi, R->H0, NULL, NULL, tmp);
    if (cft_div(DEV, fi->fmt, CFT_RNE, worstH, tmp, rel, 1, NULL, NULL)
        != CFT_OK)
        die("cft_div failed computing the energy drift");
    val_to_dec_short(fi, rel, sdh, sizeof sdh, 6);

    memset(worstL, 0, esz);
    for (k = 0; k < R->nL; k++) {
        max_over_members(R, R->dLmax[k], tmp);
        if (val_lt(fi, worstL, tmp))
            memcpy(worstL, tmp, esz);
    }
    {
        uint8_t l0[MAX_ESZ], best[MAX_ESZ];
        memset(best, 0, esz);
        for (k = 0; k < R->nL; k++) {
            run1(CFT_ABS, fi, R->L0[k], NULL, NULL, l0);
            if (val_lt(fi, best, l0))
                memcpy(best, l0, esz);
        }
        if (cft_div(DEV, fi->fmt, CFT_RNE, worstL, best, rel, 1, NULL, NULL)
            != CFT_OK)
            die("cft_div failed computing the angular-momentum drift");
        val_to_dec_short(fi, rel, sdl, sizeof sdl, 6);
    }

    sep0 = alloc_m(R);
    sep1 = alloc_m(R);
    separations(R, R->q0, R->v0, sep0);
    separations(R, R->q, R->v, sep1);

    if (O->csv) {
        /* The last seven columns are the segments engine's census and
         * are zero on the other two; they are APPENDED, so a reader that
         * takes columns by name (host/tests/orbits_check.py) or reads
         * the human report (bindings/wasm/verify_demos.mjs) is
         * untouched. seg_loads, the images built and loaded, came last
         * (2026-09-25). */
        printf("backend,format,problem,scheme,rsqrt,engine,members,batch,"
               "spread,h,steps,samples,seconds,steps_per_s,elem_steps_per_s,"
               "libops_per_s,calls,elemops,composed,energy_drift,"
               "angmom_drift,flags,chain,seg_insns,seg_consts,seg_alu_step,"
               "seg_ctl_step,seg_slots,seg_runs,seg_loads\n");
        printf("%s,%s,%s,%s,%s,%s,%" PRIu64 ",%" PRIu64 ",%" PRIu64
               ",%s,%" PRIu64 ",%" PRIu64 ",%.6f,%.1f,%.1f,%.1f,%" PRIu64
               ",%" PRIu64 ",%" PRIu64 ",%s,%s,0x%02x,%s,%u,%u,%" PRIu64
               ",%" PRIu64 ",%u,%" PRIu64 ",%" PRIu64 "\n",
               backend, cft_format_name(fi->fmt), problem_name(O->problem),
               scheme_name(O->scheme), rsqrt_name(O->rsqrt),
               O->engine == ENG_PROGRAM ? "program" :
               O->engine == ENG_SEGMENTS ? "segments" : "loop",
               (uint64_t)M, (uint64_t)O->batch, O->spread, sh,
               R->step, R->sample, elapsed, steps_s, elem_s, ops_s,
               N_CALLS, N_ELEMOPS, N_COMPOSED, sdh, sdl,
               (unsigned)flags_run, chain, (unsigned)R->s_insns,
               (unsigned)R->s_consts, R->s_alu_step, R->s_ctl_step,
               (unsigned)R->s_slots, R->s_runs, R->s_loads);
        free(sep0); free(sep1);
        return;
    }

    printf("\n");
    printf("  backend       %s\n", backend);
    printf("  format        %s, p = %d, %d Newton passes for rsqrt\n",
           cft_format_name(fi->fmt), fi->prec, fi->newton);
    printf("  problem       %s, %d bod%s in %dD, %" PRIu64 " ensemble "
           "members\n", problem_name(O->problem), R->nb,
           R->nb == 1 ? "y" : "ies", R->nd, (uint64_t)M);
    printf("  scheme        %s (%d substep%s), 1/r^3 route %s\n",
           scheme_name(O->scheme), R->nsub, R->nsub == 1 ? "" : "s",
           rsqrt_name(O->rsqrt));
    printf("  engine        %s, batch %" PRIu64 "\n",
           O->engine == ENG_PROGRAM ? "sequencer program" :
           O->engine == ENG_SEGMENTS ? "sequencer-program segments" :
           "host cft_run loop",
           (uint64_t)O->batch);
    if (O->engine == ENG_PROGRAM)
        printf("  program       %u instructions, %u deposit slots per lane\n",
               R->n_insns, R->max_deposits);
    if (O->engine == ENG_SEGMENTS)
        printf("  segments      %u instructions, %u constants; a lane-step is "
               "%" PRIu64 " ALU and %" PRIu64 " control codes; %u scratch "
               "slots, %u registers; %" PRIu64 " runs of %" PRIu64
               " image%s\n",
               (unsigned)R->s_insns, (unsigned)R->s_consts, R->s_alu_step,
               R->s_ctl_step, (unsigned)R->s_slots, (unsigned)R->s_regs,
               R->s_runs, R->s_loads, R->s_loads == 1 ? "" : "s");
    printf("  step size     %s\n", sh);
    printf("  steps done    %" PRIu64 " of %" PRIu64 ", %" PRIu64
           " samples of %" PRIu64 "\n",
           R->step, R->nsteps, R->sample, R->nsamples);
    printf("  energy drift  %s   max over samples and members of "
           "|H-H0|, over member 0's |H0|\n", sdh);
    printf("  angmom drift  %s   the same for L, whose drift is "
           "ROUNDOFF ALONE\n", sdl);
    printf("  separations   member: initial -> final, growth\n");
    for (m = 1; m < M && m < 5; m++) {
        uint8_t growth[MAX_ESZ];
        char si[64];
        val_to_dec_short(fi, sep0 + m * esz, si, sizeof si, 4);
        val_to_dec_short(fi, sep1 + m * esz, ssep, sizeof ssep, 4);
        if (cft_div(DEV, fi->fmt, CFT_RNE, sep1 + m * esz, sep0 + m * esz,
                    growth, 1, NULL, NULL) != CFT_OK)
            die("cft_div failed computing a separation growth");
        val_to_dec_short(fi, growth, sgrow, sizeof sgrow, 4);
        printf("                %2" PRIu64 ": %s -> %s, x%s\n",
               (uint64_t)m, si, ssep, sgrow);
    }
    if (M > 5)
        printf("                (%" PRIu64 " more; --records has them all)\n",
               (uint64_t)(M - 5));
    printf("  library calls %" PRIu64 "\n", N_CALLS);
    printf("  elementwise   %" PRIu64 " opcode issues, plus %" PRIu64
           " composed div/sqrt\n", N_ELEMOPS, N_COMPOSED);
    printf("  flags seen    0x%02x  (inexact is EXPECTED here and means "
           "nothing;\n", (unsigned)FLAGS_SEEN);
    printf("                 the other four are certificates and are "
           "checked on every call)%s\n",
           FLAGS_TRUSTED ? "" : " - NOT readable on this backend");
    printf("  status word   0x%02x%s\n", (unsigned)status_run,
           status_run == flags_run ? " (agrees with the union above)"
                                   : "  DISAGREES WITH THE UNION ABOVE");
    printf("  time          %.3f s\n", elapsed);
    printf("  throughput    %.0f steps/s, %.0f element-steps/s, "
           "%.0f library element-ops/s\n", steps_s, elem_s, ops_s);
    printf("  chain         %s\n", chain);
    if (R->cert && R->c_written) {
        printf("  certificate   %s (%s, %" PRIu64 " segments of %" PRIu64
               " steps; the image and %" PRIu64 " states in %s)\n",
               O->cert_path, R->salt ? "keyed" : "open", R->nsamples,
               R->stride, R->nsamples + 1, O->cert_states);
#if CX_EXACT
        {
            unsigned j;
            for (j = 0; j < R->c_n_entries; j++) {
                char buf[CX_RAT_TEXT];
                rat_text(&R->c_q[j], buf);
                printf("  accuracy %u    %s drift, the most over the members, "
                       "exact: %.60s%s\n", j, R->c_labels[j], buf,
                       strlen(buf) > 60 ? "..." : "");
            }
        }
#endif
    }
    else if (R->cert)
        printf("  certificate   not written yet: the run stopped at step %"
               PRIu64 " of %" PRIu64 ", and a certificate is written when "
               "its run completes - --resume it\n", R->step, R->nsteps);
    printf("\n");
    free(sep0);
    free(sep1);
}

/* =================================================================== */
static void usage(void)
{
    printf(
"cft-orbits - symplectic few-body integration on libcft\n"
"\n"
"  --problem kepler|outer   Kepler two-body (default), or the outer\n"
"                           solar system: Sun, Jupiter, Saturn, Uranus,\n"
"                           Neptune\n"
"  --scheme leapfrog|yoshida4   Stormer-Verlet (default), or Yoshida's\n"
"                           fourth-order composition of it\n"
"  --format fp32|fp64|fp128|fp256   default fp256\n"
"  --engine loop|program|segments\n"
"                           host cft_run loop (default); the whole\n"
"                           integration as one sequencer program\n"
"                           (kepler + --rsqrt newton only, no resume);\n"
"                           or resumable sequencer-program segments with\n"
"                           the state in the scratch block (both\n"
"                           problems, --rsqrt newton; see the header)\n"
"  --segment-dump DIR       write the first segment's image and scratch\n"
"                           blocks to DIR (the golden model's cross-check)\n"
"  --rsqrt exact|newton     1/r^3 from cft_sqrt and cft_div, correctly\n"
"                           rounded (default), or from the tile's seed\n"
"                           opcode and a derived Newton refinement\n"
"  --members N              ensemble size (default 16)\n"
"  --spread N               ulps per rung of the perturbation ladder\n"
"                           (default 1)\n"
"  --periods P              kepler: orbits to integrate (default 16)\n"
"  --steps-per-period N     kepler: steps per orbit (default 1024)\n"
"  --years Y                outer: years to integrate (default 100)\n"
"  --days D                 outer: step size in days (default 10)\n"
"  --steps N                override the step count directly\n"
"  --sample-every N         steps between recorded samples (a tile holds\n"
"                           cft_caps.max_deposits a lane: at most\n"
"                           max_deposits/4 - 1 samples a run under\n"
"                           --engine program there - 15 at 64, 255 at the\n"
"                           U50's 1,024; segments deposit nothing and are\n"
"                           not bounded by it)\n"
"  --batch N                ensemble members per library call\n"
"  --checkpoint PATH        write a resumable checkpoint\n"
"  --checkpoint-interval S  seconds between checkpoints (default 10); 0\n"
"                           writes one after every step, and under\n"
"                           --engine segments makes every segment one\n"
"                           step - about the loop engine's own speed\n"
"  --resume                 continue from --checkpoint; with --records,\n"
"                           a regular file holding the records the\n"
"                           checkpoint accounts for, cut back to them\n"
"                           (a pipe or a device is refused)\n"
"  --stop-after-samples N   stop cleanly after N samples this run\n"
"  --stop-after-steps N     stop cleanly after N steps this run\n"
"  --records PATH           one line per (sample, member), exact decimal\n"
"  --cert CERT              certify the run (--engine segments, --rsqrt\n"
"                           newton): a version-1 certificate, written when\n"
"                           the run completes, a segment a sample interval\n"
"                           (docs/ORBITS.md, \"Certified runs\")\n"
"  --cert-states DIR        with --cert: a new directory for the image and\n"
"                           every boundary state, the files an audit takes\n"
"  --cert-salt SALT         with --cert: keyed under a file of 32 random\n"
"                           bytes\n"
"  --cert-open              with --cert: open, plain SHA-256 hashes\n"
"  --cert-accuracy METHOD   step-halving, wider or energy-drift: each\n"
"                           refused by its name, with the reason\n"
"  --artifact PATH          an .xclbin; omit for the software backend\n"
"  --csv                    machine-readable summary\n"
"  --quiet                  summary only\n"
"\n"
"Inexact is EXPECTED on every call here; docs/ORBITS.md is the argument\n"
"and host/tests/orbits_check.py is the 300-digit oracle.\n");
}

static const char *need(int argc, char **argv, int *i)
{
    if (*i + 1 >= argc)
        die("that option needs a value");
    return argv[++(*i)];
}

/* A certified run's option, given once. */
static void cert_once(const char **slot, const char *opt, const char *v)
{
    if (*slot)
        refuse("usage", "%s is given twice", opt);
    *slot = v;
}

/* What a certified run refuses before anything is opened or made, in this
 * order: the options' shape; the engine, the route and the accuracy it
 * cannot certify, each by its own name; a stop it could never finish; and
 * the salt. The engine and the route are asked before the tool's own
 * checks of them, so that a certified run is refused by name. */
static void cert_options(const options *O, uint8_t **salt)
{
    size_t n = 0;
    if (!O->cert_path) {
        if (O->cert_states || O->cert_salt_path || O->cert_open ||
            O->cert_accuracy)
            refuse("usage", "--cert-states, --cert-salt, --cert-open and "
                   "--cert-accuracy describe a certified run, and there is "
                   "no --cert");
        return;
    }
    if (!O->cert_states)
        refuse("usage", "--cert needs --cert-states DIR, the directory its "
               "image and states are written to");
    if (!!O->cert_salt_path == !!O->cert_open)
        refuse("usage", "--cert needs one of --cert-salt SALT (keyed) and "
               "--cert-open (open)");
    if (O->engine != ENG_SEGMENTS)
        refuse("engine", "--engine %s: a certified interval is one image run "
               "over every lane, which --engine segments runs; the loop "
               "engine runs host calls, and --engine program runs the whole "
               "integration as one program that deposits",
               O->engine == ENG_LOOP ? "loop (the default)" : "program");
    if (O->rsqrt != RSQRT_NEWTON)
        refuse("rsqrt-exact", "--rsqrt exact (the default) computes 1/r^3 "
               "with cft_sqrt and cft_div, host calls between program runs, "
               "so an interval is no image; certify --rsqrt newton, whose "
               "every interval is one (the exact route needs an orbit "
               "integrator in the golden model, docs/ROADMAP.md)");
    if (O->cert_accuracy &&
        strcmp(O->cert_accuracy, "angular-momentum-drift") != 0) {
        if (!strcmp(O->cert_accuracy, "step-halving"))
            refuse("step-halving", "a step-halving estimate needs a "
                   "half-step run on a bank whose h-slots are halved, and "
                   "this run's image carries its constants and takes no bank "
                   "(the page's aux-h-slots)");
        if (!strcmp(O->cert_accuracy, "wider"))
            refuse("wider", "a wider re-run must be this image's "
                   "instructions one format wider, its constants exactly "
                   "widened; this tool derives its constants in each format "
                   "and its Newton passes change with the format (the page's "
                   "aux-image)");
        if (!strcmp(O->cert_accuracy, "energy-drift"))
            refuse("energy-drift", "the energy goes through 1/r, which is "
                   "not a polynomial in the state, and version 1 carries a "
                   "drift only of a polynomial (docs/CERTIFICATES.md, "
                   "\"What version 1 does not do\")");
        refuse("usage", "--cert-accuracy takes angular-momentum-drift, and "
               "refuses step-halving, wider and energy-drift, each by its "
               "name");
    }
#if !CX_EXACT
    if (O->cert_accuracy)
        refuse("build-width", "this build's bigint is %d bits, and an exact "
               "value needs %d (docs/CERTIFICATES.md, \"The width rule\"): "
               "it writes no accuracy entry rather than one computed "
               "narrower", (int)CFT_BN_BITS, 2 * CX_WIDTH_BITS + 1);
#endif
    if ((O->stop_after_steps >= 0 || O->stop_after_samples >= 0) && !O->ckpt)
        refuse("usage", "--stop-after-steps and --stop-after-samples stop a "
               "certified run before its end, and it writes its certificate "
               "only at its end: without --checkpoint it could never be "
               "resumed to write one");
    if (O->cert_salt_path) {
        uint8_t *s;
        errno = 0;
        s = cert_slurp(O->cert_salt_path, 4096, &n);
        if (!s && errno)
            refuse("usage", "--cert-salt %s cannot be read (%s)",
                   O->cert_salt_path, strerror(errno));
        if (!s || n != CW_SALT_BYTES)
            refuse("salt-length", "--cert-salt %s is %lu bytes; a salt is "
                   "exactly %d random bytes", O->cert_salt_path,
                   (unsigned long)n, CW_SALT_BYTES);
        *salt = s;
    }
}

int main(int argc, char **argv)
{
    options O;
    fmt_info fi;
    runstate R;
    cft_caps caps;
    cft_status st;
    double t0, tckpt, elapsed;
    long emitted = 0;
    uint64_t steps_this_run = 0;
    int stopping = 0;
    int i, c, k;
    size_t esz;
    uint8_t *salt = NULL;       /* --cert-salt's 32 bytes, read by cert_options */

    memset(&O, 0, sizeof O);
    O.problem = PROB_KEPLER;
    O.scheme = SCHEME_LEAPFROG;
    O.rsqrt = RSQRT_EXACT;
    O.engine = ENG_LOOP;
    O.fmt = CFT_FP256;
    O.members = 16;
    O.batch = 0;
    O.spread = 1;
    O.steps_per_period = 1024;
    O.periods = 16;
    O.days = 10;
    O.years = 100;
    O.ckpt_interval = 10.0;
    O.stop_after_samples = -1;
    O.stop_after_steps = -1;

    for (i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (!strcmp(a, "-h") || !strcmp(a, "--help")) { usage(); return 0; }
        else if (!strcmp(a, "--problem")) {
            const char *val = need(argc, argv, &i);
            if (!strcmp(val, "kepler")) O.problem = PROB_KEPLER;
            else if (!strcmp(val, "outer")) O.problem = PROB_OUTER;
            else die("--problem takes kepler or outer");
        } else if (!strcmp(a, "--scheme")) {
            const char *val = need(argc, argv, &i);
            if (!strcmp(val, "leapfrog")) O.scheme = SCHEME_LEAPFROG;
            else if (!strcmp(val, "yoshida4")) O.scheme = SCHEME_YOSHIDA4;
            else die("--scheme takes leapfrog or yoshida4");
        } else if (!strcmp(a, "--rsqrt")) {
            const char *val = need(argc, argv, &i);
            if (!strcmp(val, "exact")) O.rsqrt = RSQRT_EXACT;
            else if (!strcmp(val, "newton")) O.rsqrt = RSQRT_NEWTON;
            else die("--rsqrt takes exact or newton");
        } else if (!strcmp(a, "--engine")) {
            const char *val = need(argc, argv, &i);
            if (!strcmp(val, "loop")) O.engine = ENG_LOOP;
            else if (!strcmp(val, "program")) O.engine = ENG_PROGRAM;
            else if (!strcmp(val, "segments")) O.engine = ENG_SEGMENTS;
            else die("--engine takes loop, program or segments");
        } else if (!strcmp(a, "--format")) {
            const char *val = need(argc, argv, &i);
            if (!strcmp(val, "fp32")) O.fmt = CFT_FP32;
            else if (!strcmp(val, "fp64")) O.fmt = CFT_FP64;
            else if (!strcmp(val, "fp128")) O.fmt = CFT_FP128;
            else if (!strcmp(val, "fp256")) O.fmt = CFT_FP256;
            else die("--format takes fp32, fp64, fp128 or fp256");
        }
        else if (!strcmp(a, "--members"))
            O.members = (size_t)strtoull(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--batch"))
            O.batch = (size_t)strtoull(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--spread"))
            O.spread = strtoull(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--periods"))
            O.periods = strtoull(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--steps-per-period"))
            O.steps_per_period = strtoull(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--years"))
            O.years = strtoull(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--days"))
            O.days = strtoull(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--steps"))
            O.steps_opt = strtoull(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--sample-every"))
            O.sample_every = strtoull(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--checkpoint")) O.ckpt = need(argc, argv, &i);
        else if (!strcmp(a, "--checkpoint-interval")) {
            /* A number of seconds and nothing else. strtod alone read
             * "nan" as a clock that never came due - one-step segments
             * and no checkpoint until the end, on both engines - "abc"
             * as 0, a checkpoint every step, and "1s" as 1. */
            const char *val = need(argc, argv, &i);
            char *end = NULL;
            double s = (*val >= '0' && *val <= '9') || *val == '.'
                       ? strtod(val, &end) : -1;
            if (!end || *end || !(s >= 0) || s > 1e15)
                die("--checkpoint-interval takes a number of seconds, 0 or "
                    "more (0 writes a checkpoint after every step)");
            O.ckpt_interval = s;
        }
        else if (!strcmp(a, "--resume")) O.resume = 1;
        else if (!strcmp(a, "--stop-after-samples"))
            O.stop_after_samples = strtol(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--stop-after-steps"))
            O.stop_after_steps = strtol(need(argc, argv, &i), NULL, 10);
        else if (!strcmp(a, "--records"))
            O.records_path = need(argc, argv, &i);
        else if (!strcmp(a, "--artifact")) O.artifact = need(argc, argv, &i);
        else if (!strcmp(a, "--segment-dump"))
            O.segment_dump = need(argc, argv, &i);
        else if (!strcmp(a, "--cert"))
            cert_once(&O.cert_path, a, need(argc, argv, &i));
        else if (!strcmp(a, "--cert-states"))
            cert_once(&O.cert_states, a, need(argc, argv, &i));
        else if (!strcmp(a, "--cert-salt"))
            cert_once(&O.cert_salt_path, a, need(argc, argv, &i));
        else if (!strcmp(a, "--cert-accuracy"))
            cert_once(&O.cert_accuracy, a, need(argc, argv, &i));
        else if (!strcmp(a, "--cert-open")) {
            if (O.cert_open)
                refuse("usage", "--cert-open is given twice");
            O.cert_open = 1;
        }
        else if (!strcmp(a, "--dump-setup")) O.dump_setup = 1;
        else if (!strcmp(a, "--csv")) O.csv = 1;
        else if (!strcmp(a, "--quiet")) O.quiet = 1;
        else {
            fprintf(stderr, "cft-orbits: unknown option %s\n", a);
            return 2;
        }
    }
    atexit(cert_cleanup);
    cert_options(&O, &salt);
    if (!O.members)
        die("--members must be positive");
    if (!O.batch)
        O.batch = O.members;
    if (O.segment_dump && O.engine != ENG_SEGMENTS)
        die("--segment-dump writes a segment, so it needs --engine segments");
    {
        const char *nc = getenv("CFT_ORBITS_NEGATIVE_CONTROL");
        if (nc && *nc) {
            const char *what;
            if (!strcmp(nc, "transpose")) {
                NEGCTL_TRANSPOSE = 1;
                what = "v_0 and v_1 are packed into each other's scratch "
                       "slots - every result of this run is deliberately "
                       "wrong";
            } else if (!strcmp(nc, "zero-r2")) {
                NEGCTL_ZERO_R2 = 1;
                what = "every r^2 in the segment image is zeroed - the run "
                       "must end on the flag certificate";
            } else if (!strcmp(nc, "uncapped")) {
                NEGCTL_UNCAPPED = 1;
                what = "segments ignore --checkpoint-interval - an "
                       "interruption loses up to a whole sample interval";
            } else if (!strcmp(nc, "late-stop")) {
                NEGCTL_LATE_STOP = 1;
                what = "segments run one step past --stop-after-steps - a "
                       "stopped run is deliberately a step late";
            } else if (!strcmp(nc, "overlong")) {
                NEGCTL_OVERLONG = 1;
                what = "the longest segment is one step past what the "
                       "loader accepts - the first one that long must be "
                       "refused";
            } else if (!strcmp(nc, "append")) {
                NEGCTL_APPEND = 1;
                what = "--resume appends to --records without checking it "
                       "or cutting it back to the checkpoint - after a kill "
                       "the resumed records are deliberately wrong";
            } else if (!strcmp(nc, "flush-late")) {
                NEGCTL_FLUSH_LATE = 1;
                what = "the records are handed to the system after the "
                       "checkpoint that counts them is in place - a process "
                       "ending between the two leaves them behind it";
            } else if (!strcmp(nc, "drop-flags")) {
                NEGCTL_DROP_FLAGS = 1;
                what = "a certified run's resume takes the interval in "
                       "progress as having raised nothing so far - its "
                       "certificate is deliberately wrong there";
            } else {
                die("CFT_ORBITS_NEGATIVE_CONTROL takes transpose, zero-r2, "
                    "uncapped, late-stop, overlong, append, flush-late or "
                    "drop-flags");
            }
            if (NEGCTL_DROP_FLAGS && !O.cert_path)
                die("CFT_ORBITS_NEGATIVE_CONTROL=drop-flags sabotages a "
                    "certified run's resume, and there is no --cert");
            if (NEGCTL_APPEND || NEGCTL_FLUSH_LATE
                ? O.engine == ENG_PROGRAM : O.engine != ENG_SEGMENTS)
                die(NEGCTL_APPEND || NEGCTL_FLUSH_LATE
                    ? "CFT_ORBITS_NEGATIVE_CONTROL=append and =flush-late "
                      "sabotage the records beside a resumable run's "
                      "checkpoints, and --engine program cannot resume"
                    : "CFT_ORBITS_NEGATIVE_CONTROL sabotages --engine "
                      "segments and nothing else");
            fprintf(stderr, "cft-orbits: NEGATIVE CONTROL ACTIVE "
                    "(CFT_ORBITS_NEGATIVE_CONTROL=%s): %s\n", nc, what);
        }
    }
    {
        const char *lim = getenv("CFT_ORBITS_SEGMENT_LIMIT");
        const char *vc = getenv("CFT_ORBITS_VIRTUAL_CLOCK");
        if (lim && *lim) {
            if (!dec_u64(lim, 0xffffffffull, &SEG_LIMIT) || !SEG_LIMIT)
                die("CFT_ORBITS_SEGMENT_LIMIT takes a whole number of "
                    "steps, 1 to 4294967295");
            if (O.engine != ENG_SEGMENTS)
                die("CFT_ORBITS_SEGMENT_LIMIT instruments --engine "
                    "segments and nothing else");
            fprintf(stderr, "cft-orbits: TEST INSTRUMENT ACTIVE "
                    "(CFT_ORBITS_SEGMENT_LIMIT=%s): the loader is taken to "
                    "accept at most %s steps a segment, so longer intervals "
                    "are split where its real limit would split them - no "
                    "result may change\n", lim, lim);
        }
        if (vc && *vc) {
            char *end = NULL;
            double s = (*vc >= '0' && *vc <= '9') || *vc == '.'
                       ? strtod(vc, &end) : 0;
            if (!end || *end || !(s > 0) || s > 1e6)
                die("CFT_ORBITS_VIRTUAL_CLOCK takes a positive number of "
                    "seconds a step, at most 1e6");
            if (O.engine == ENG_PROGRAM)
                die("CFT_ORBITS_VIRTUAL_CLOCK instruments the loop and "
                    "segments engines' checkpoints, and --engine program "
                    "writes one, at the end");
            VCLOCK = s;
            fprintf(stderr, "cft-orbits: TEST INSTRUMENT ACTIVE "
                    "(CFT_ORBITS_VIRTUAL_CLOCK=%s): the clock advances %s s "
                    "a step and nothing else moves it, and each checkpoint "
                    "is logged here - no result may change\n", vc, vc);
        }
        {
            const char *da = getenv("CFT_ORBITS_DIE_AFTER_CHECKPOINT");
            if (da && *da) {
                if (!dec_u64(da, 0xffffffffull, &DIE_AFTER) || !DIE_AFTER)
                    die("CFT_ORBITS_DIE_AFTER_CHECKPOINT takes a whole "
                        "number of checkpoints, 1 to 4294967295");
                if (O.engine == ENG_PROGRAM)
                    die("CFT_ORBITS_DIE_AFTER_CHECKPOINT instruments a "
                        "resumable run, and --engine program cannot resume");
                fprintf(stderr, "cft-orbits: TEST INSTRUMENT ACTIVE "
                        "(CFT_ORBITS_DIE_AFTER_CHECKPOINT=%s): the process "
                        "ends as a kill would, exit 9, the moment checkpoint "
                        "%s is in place\n", da, da);
            }
        }
        {
            const char *cp = getenv("CFT_ORBITS_CERT_PLANT");
            if (cp && *cp) {
                int width = 0;
                if (!strcmp(cp, "flags-unreadable"))
                    PLANT_UNREADABLE = 1;
                else if (!strcmp(cp, "flags-unwritten"))
                    PLANT_UNWRITTEN = 1;
                else if (!strcmp(cp, "flags-wide"))
                    PLANT_WIDE = 1;
                else if (!strcmp(cp, "width"))
                    width = 1;
                else
                    die("CFT_ORBITS_CERT_PLANT takes flags-unreadable, "
                        "flags-unwritten, flags-wide or width");
                if (!O.cert_path)
                    die("CFT_ORBITS_CERT_PLANT instruments a certified run, "
                        "and there is no --cert");
                if (width && !O.cert_accuracy)
                    die("CFT_ORBITS_CERT_PLANT=width instruments an accuracy "
                        "entry, and there is no --cert-accuracy");
#if CX_EXACT
                PLANT_WIDTH = width;
#endif
                fprintf(stderr, "cft-orbits: TEST INSTRUMENT ACTIVE "
                        "(CFT_ORBITS_CERT_PLANT=%s): %s\n", cp,
                        PLANT_UNREADABLE ? "the device is taken to be one "
                        "that cannot read the sticky flags" :
                        PLANT_UNWRITTEN ? "each segment's flag word is taken "
                        "to be left unwritten by the library" :
                        PLANT_WIDE ? "each segment's flag word gains bit 5, "
                        "past the five sticky flags" :
                        "the first term's coefficient is taken times "
                        "2^-1000, so its first product is past the width "
                        "rule");
            }
        }
        {
            const char *sf = getenv("CFT_ORBITS_SHARE_FIFO");
            if (sf && *sf) {
                if (strcmp(sf, "1"))
                    die("CFT_ORBITS_SHARE_FIFO takes 1");
                if (!O.records_path)
                    die("CFT_ORBITS_SHARE_FIFO instruments the records "
                        "file, and there is no --records");
                SHARE_FIFO = 1;
                fprintf(stderr, "cft-orbits: TEST INSTRUMENT ACTIVE "
                        "(CFT_ORBITS_SHARE_FIFO=1): the records file is "
                        "taken to be what the WSL share makes of a Linux "
                        "FIFO - it says it holds 0 bytes, whatever is "
                        "written to it, and refuses to be cut; the records "
                        "still go into it\n");
            }
        }
    }

    st = cft_open(O.artifact, 0, &DEV);
    if (st != CFT_OK)
        die_st("cft_open", st);
    memset(&caps, 0, sizeof caps);
    caps.struct_size = sizeof caps;
    if (cft_get_caps(DEV, &caps) != CFT_OK)
        die("cft_get_caps failed");
    if (!(caps.format_mask & (1u << (unsigned)O.fmt)))
        die("this backend does not carry that format");
    FLAGS_TRUSTED = caps.flags_readable != 0;
    if (O.cert_path && (PLANT_UNREADABLE || !caps.flags_readable))
        refuse("device", "this %s device cannot read the sticky flags, and a "
               "certificate records each segment's flag word%s",
               caps.backend, PLANT_UNREADABLE ? " (planted: "
               "CFT_ORBITS_CERT_PLANT=flags-unreadable)" : "");

    measure_format(&fi, O.fmt);

    memset(&R, 0, sizeof R);
    R.fi = &fi;
    R.O = &O;
    R.cert = O.cert_path != NULL;
    R.salt = salt;
    R.c_angmom = O.cert_accuracy != NULL;   /* the one method not refused */
    esz = fi.esz;
    R.nb = O.problem == PROB_KEPLER ? 1 : N_OUTER;
    R.nd = O.problem == PROB_KEPLER ? 2 : 3;
    R.ncomp = R.nb * R.nd;
    R.nL = O.problem == PROB_KEPLER ? 1 : 3;

    /* --- the schedule --- */
    if (O.steps_opt)
        R.nsteps = O.steps_opt;
    else if (O.problem == PROB_KEPLER)
        R.nsteps = O.periods * O.steps_per_period;
    else
        R.nsteps = (O.years * 36525ull) / (100ull * O.days);
    if (!R.nsteps)
        die("that is a run of zero steps");
    R.stride = O.sample_every;
    if (!R.stride)
        R.stride = O.problem == PROB_KEPLER ? O.steps_per_period
                                            : (36525ull / (100ull * O.days)
                                               ? 36525ull / (100ull * O.days)
                                               : 1);
    if (!R.stride)
        R.stride = 1;
    if (R.stride > R.nsteps)
        R.stride = R.nsteps;
    R.nsamples = R.nsteps / R.stride;
    if (!R.nsamples)
        die("--sample-every is larger than the run");
    R.nsteps = R.nsamples * R.stride;   /* an exact number of samples */

    if (O.engine == ENG_SEGMENTS) {
        if (O.rsqrt != RSQRT_NEWTON)
            die("--engine segments needs --rsqrt newton: the correctly "
                "rounded divide and square root exist as WHOLE programs "
                "(programs/divfull-*, sqrtfull-*), and splicing one into "
                "this program's loop body needs a fragment inliner that "
                "does not exist yet (docs/ORBITS.md, \"The step, and "
                "where it runs\")");
    }
    if (O.engine == ENG_PROGRAM) {
        if (O.problem != PROB_KEPLER)
            die("--engine program cannot run --problem outer: a lane's "
                "state is 30 values and cft_program_run initialises three "
                "registers (docs/ORBITS.md, \"The step, and where it "
                "runs\"); "
                "--engine segments runs it");
        if (O.rsqrt != RSQRT_NEWTON)
            die("--engine program needs --rsqrt newton: the correctly "
                "rounded route is host-prep, program core, host finish "
                "(python/cft_golden/seqprogs.py) and cannot sit inside "
                "another program's loop body");
        if (O.resume)
            die("--engine program cannot resume into the middle of a run: "
                "a restart state has four non-zero components and only "
                "three registers can be loaded; --engine segments can");
        if (R.nsamples > 0xffffffffull || R.stride > 0xffffffffull)
            die("that run does not fit the sequencer's 32-bit trip counts");
        /* This program deposits four values a sample plus four at the
         * start, for a whole run in ONE call, so the sample count is
         * bounded by the device's deposit budget: 64 slots a lane on
         * the round-2 tile is fifteen samples, 1,024 on the U50's
         * revision-7 tile 255, 2^20 in this library's software backend
         * a quarter of a million.
         *
         * Unlike the zoom's trip count, the sample count is part of
         * WHAT IS COMPUTED - fewer samples is a different record - so
         * there is nothing to resize and this refuses, naming the two
         * flags that set it. A cap of zero means the device did not
         * say (an older remote server; docs/REMOTE.md), and an unknown
         * cap constrains nothing; cft_program_load is the backstop. */
        if (caps.max_deposits &&
            (R.nsamples + 1) * DEPOSITS_PER_SAMPLE > caps.max_deposits) {
            char msg[280];
            snprintf(msg, sizeof msg,
                     "%llu samples deposit %llu values a lane and the %s "
                     "backend holds %u (cft_caps.max_deposits): record at "
                     "most %u samples a run - raise --sample-every or lower "
                     "--periods",
                     (unsigned long long)R.nsamples,
                     (unsigned long long)((R.nsamples + 1) * DEPOSITS_PER_SAMPLE),
                     caps.backend, (unsigned)caps.max_deposits,
                     (unsigned)(caps.max_deposits / DEPOSITS_PER_SAMPLE - 1));
            die(msg);
        }
    }

    /* --- allocation --- */
    R.q = (uint8_t *)xcalloc((size_t)R.ncomp * O.members, esz);
    R.v = (uint8_t *)xcalloc((size_t)R.ncomp * O.members, esz);
    R.q0 = (uint8_t *)xcalloc((size_t)R.ncomp * O.members, esz);
    R.v0 = (uint8_t *)xcalloc((size_t)R.ncomp * O.members, esz);
    for (k = 0; k < MAX_DIM; k++)
        R.d[k] = alloc_m(&R);
    R.x = alloc_m(&R); R.y = alloc_m(&R); R.w = alloc_m(&R);
    R.e = alloc_m(&R); R.z = alloc_m(&R); R.g = alloc_m(&R);
    R.t1 = alloc_m(&R); R.t2 = alloc_m(&R); R.acc = alloc_m(&R);
    R.H0 = alloc_m(&R); R.Hd = alloc_m(&R); R.dHmax = alloc_m(&R);
    for (k = 0; k < 3; k++) {
        R.L0[k] = alloc_m(&R);
        R.Ld[k] = alloc_m(&R);
        R.dLmax[k] = alloc_m(&R);
    }

    setup_constants(&R);
    setup_state(&R);
    memcpy(R.q0, R.q, (size_t)R.ncomp * O.members * esz);
    memcpy(R.v0, R.v, (size_t)R.ncomp * O.members * esz);

    /* Building the constants and the initial condition deliberately
     * rounds; 754-2019 7.1 says a status flag is lowered only at the
     * user's request, and this is that request. From here the word
     * holds what the INTEGRATION raised, which the report
     * cross-checks against the union of the calls' flags_out. */
    cft_lower_flags(DEV, CFT_FLAGS_ALL);
    FLAGS_SEEN = 0;

    if (O.dump_setup) {
        dump_setup(&R);
        cft_close(DEV);
        return 0;
    }

    /* A certified run's image, digests, identity and streams, then its
     * outputs' places - all before a checkpoint is read or a file made */
    if (R.cert) {
        cert_setup(&R, &caps);
        cert_outputs(&R);
    }
    if (O.resume) {
        if (!O.ckpt)
            die("--resume needs --checkpoint");
        ckpt_read(&R);
        if (R.cert)
            cert_resumed_files(&R);     /* read, never changed */
    }
    if (O.records_path) {
        if (O.ckpt)
            records_apart(&O, NULL, 0);     /* the paths as written */
        if (O.resume && !NEGCTL_APPEND)
            records_resume(&R);
        /* A fresh run's file is opened uncut, asked which file it is,
         * and only then cut to nothing: a refusal loses no byte. */
        R.recf = O.resume ? fopen(O.records_path, "ab")
                          : open_uncut(O.records_path);
        if (!R.recf) {
            if (O.resume)
                note_errno(errno);
            records_refused("open", O.records_path, "");
        }
        if (O.ckpt)
            records_apart(&O, R.recf, 0);   /* the files, now one is open */
        if (!O.resume && file_empty(R.recf) != 0)
            records_refused("empty", O.records_path,
                            " - it was left as it was, and nothing written "
                            "to it");
    }
    /* the last thing before the run: a fresh certified run's DIR, its
     * image and boundary 0 */
    if (R.cert && !O.resume)
        cert_fresh_files(&R);

    if (!O.quiet && !O.csv)
        printf("cft-orbits: %s backend, %s, p = %d, %s, %s, %s engine\n",
               caps.backend, cft_format_name(fi.fmt), fi.prec,
               problem_name(O.problem), scheme_name(O.scheme),
               O.engine == ENG_PROGRAM ? "sequencer-program" :
               O.engine == ENG_SEGMENTS ? "sequencer-segments" : "host-loop");

    t0 = clock_s();
    tckpt = t0;

    if (O.engine == ENG_PROGRAM) {
        size_t bytes = 0, M = O.members, m, chunk;
        uint8_t *img = build_program(&R, &bytes);
        uint8_t *qs, *vs;
        uint64_t s;
        st = cft_program_load(DEV, img, bytes, &R.prog);
        free(img);
        if (st != CFT_OK)
            die_st("cft_program_load", st);
        R.dep = (uint8_t *)xcalloc(M * R.max_deposits, esz);
        R.depcount = (uint32_t *)xcalloc(M, sizeof(uint32_t));
        for (chunk = 0; chunk < M; chunk += O.batch) {
            size_t n = M - chunk < O.batch ? M - chunk : O.batch;
            uint32_t fl = 0, bus = 0;
            st = cft_program_run(R.prog, CQ(&R, 0) + chunk * esz,
                                 CV(&R, 1) + chunk * esz, NULL,
                                 R.dep + (size_t)chunk * R.max_deposits * esz,
                                 R.depcount + chunk, n, &fl, &bus);
            if (st != CFT_OK)
                die_st("cft_program_run", st);
            if (bus & CFT_STATUS_DEPOSIT_OVERFLOW)
                die("the deposit buffer overflowed - the program is wrong");
            note_flags(fl, "the sequencer program");
            N_CALLS++;
            /* the ALU issues a lane actually performed - the same
             * count the host loop makes for the same step, which is
             * what lets the two throughputs be compared */
            N_ELEMOPS += (uint64_t)n * R.nsteps * R.alu_per_step;
        }
        for (m = 0; m < M; m++)
            if (R.depcount[m] != R.max_deposits)
                die("a lane deposited the wrong number of values");
        /* Replay the deposits in (sample, member) order, computing the
         * invariants with the same host routine the loop engine uses,
         * so the two engines' records are the same bytes. */
        qs = (uint8_t *)xcalloc((size_t)R.ncomp * M, esz);
        vs = (uint8_t *)xcalloc((size_t)R.ncomp * M, esz);
        for (s = 0; s <= R.nsamples; s++) {
            for (m = 0; m < M; m++) {
                const uint8_t *d = R.dep +
                    ((size_t)m * R.max_deposits +
                     (size_t)s * DEPOSITS_PER_SAMPLE) * esz;
                memcpy(qs + (0 * M + m) * esz, d + 0 * esz, esz);
                memcpy(qs + (1 * M + m) * esz, d + 1 * esz, esz);
                memcpy(vs + (0 * M + m) * esz, d + 2 * esz, esz);
                memcpy(vs + (1 * M + m) * esz, d + 3 * esz, esz);
            }
            emit_sample(&R, s, s * R.stride, qs, vs);
            R.sample = s;
            R.step = s * R.stride;
        }
        memcpy(R.q, qs, (size_t)R.ncomp * M * esz);
        memcpy(R.v, vs, (size_t)R.ncomp * M * esz);
        free(qs);
        free(vs);
    } else {
        /* Sample 0 is the initial state. A checkpoint is only ever
         * written after it has been emitted, so a resume must not
         * emit it again. */
        if (!O.resume)
            emit_sample(&R, 0, 0, R.q, R.v);
        while (R.sample < R.nsamples && !stopping) {
            /* The checkpoint is STEP-granular, not sample-granular:
             * the ensemble state is complete after every step, so a
             * checkpoint may be taken between any two of them and a
             * resume picks up part way through a sample interval.
             * That is what makes an interruption cost about one
             * --checkpoint-interval of work however coarse the
             * sampling is: the loop engine reads the clock after every
             * step, and a segment is sized to END when the next
             * checkpoint is due, so both write one as soon as an
             * interval has passed - the interval plus at most a step,
             * at a steady rate. It is what the resume and interruption
             * tests in host/tests/orbits_check.py exercise. */
            uint64_t upto = (R.sample + 1) * R.stride;
            while (R.step < upto) {
                if (O.engine == ENG_SEGMENTS) {
                    /* One segment to the sample boundary, or to the stop
                     * point if that comes first - the same step at
                     * which the loop below would stop - and no longer
                     * than the loader takes (seg_limits) or, while
                     * checkpoints are written, than fits the time left
                     * before the next one is due, at the last segment's
                     * rate (seg_time_cap). Sized to one whole interval
                     * instead, a segment ran half to all of one and the
                     * checkpoint came after the second - two intervals
                     * apart (verifier-V1, 2026-09-25). The results do
                     * not depend on where segments end; orbits_check.py
                     * holds that at every batch, stop, segment length
                     * and relay it runs. */
                    uint64_t kseg = upto - R.step;
                    double tseg, dt;
                    if (O.stop_after_steps >= 0) {
                        uint64_t want = (uint64_t)O.stop_after_steps;
                        uint64_t left = want > steps_this_run
                                        ? want - steps_this_run : 1;
                        if (NEGCTL_LATE_STOP)
                            left++;
                        if (kseg > left)
                            kseg = left;
                    }
                    if (!R.s_kmax)
                        seg_limits(&R);
                    if (kseg > R.s_kmax)
                        kseg = R.s_kmax;
                    if (O.ckpt && !NEGCTL_UNCAPPED) {
                        uint64_t cap = seg_time_cap(&R, O.ckpt_interval -
                                                   (clock_s() - tckpt));
                        if (kseg > cap)
                            kseg = cap;
                    }
                    tseg = clock_s();
                    seg_run(&R, kseg);
                    dt = clock_s() - tseg;
                    if (dt > 0)     /* a clock that did not move measured
                                       nothing; keep the last rate */
                        R.s_sec_per_step = dt / (double)kseg;
                    R.step += kseg;
                    steps_this_run += kseg;
                } else {
                    one_step(&R);
                    R.step++;
                    steps_this_run++;
                }
                if (O.ckpt && clock_s() - tckpt >= O.ckpt_interval) {
                    ckpt_write(&R);
                    tckpt = clock_s();
                }
                if (O.stop_after_steps >= 0 &&
                    steps_this_run >= (uint64_t)O.stop_after_steps) {
                    stopping = 1;
                    break;
                }
            }
            if (stopping)
                break;
            R.sample++;
            emit_sample(&R, R.sample, R.step, R.q, R.v);
            if (R.cert)
                cert_close(&R);         /* before any checkpoint counts it */
            emitted++;
            if (O.ckpt && clock_s() - tckpt >= O.ckpt_interval) {
                ckpt_write(&R);
                tckpt = clock_s();
            }
            if (O.stop_after_samples >= 0 && emitted >= O.stop_after_samples)
                break;
        }
    }
    elapsed = clock_s() - t0;
    if (O.ckpt)
        ckpt_write(&R);
    if (R.recf && fclose(R.recf) != 0)
        die("the records file could not be written");
    /* A certificate exists only for a run that completed, every interval
     * a whole stride; the final checkpoint is on disk first, so a failure
     * here leaves a run that --resume completes again. */
    if (R.cert && R.sample == R.nsamples) {
        cert_finish(&R);
        R.c_written = 1;
    }

    report(&R, elapsed, caps.backend);

    for (c = 0; c < MAX_DIM; c++)
        free(R.d[c]);
    free(R.q); free(R.v); free(R.q0); free(R.v0);
    free(R.x); free(R.y); free(R.w); free(R.e); free(R.z); free(R.g);
    free(R.t1); free(R.t2); free(R.acc);
    free(R.H0); free(R.Hd); free(R.dHmax);
    for (k = 0; k < 3; k++) { free(R.L0[k]); free(R.Ld[k]); free(R.dLmax[k]); }
    free(R.dep);
    free(R.depcount);
    free(R.sin);
    free(R.sout);
    if (R.prog)
        cft_program_free(R.prog);
    for (k = 0; k < SEG_CACHE; k++)
        if (R.sprog[k])
            cft_program_free(R.sprog[k]);
    free(R.salt);
    free(R.c_image);
    free(R.c_bhash);
    free(R.c_flags);
    free(R.c_status);
    free(R.c_zero);
    free(R.c_state);
    cw_text_free(&R.c_ident);
    cw_text_free(&R.c_runhead);
    cft_close(DEV);
    return 0;
}
