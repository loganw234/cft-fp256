/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cft-segrun - run a program as consecutive segments, keep the state at
 * every boundary, and write the certificate (docs/CERTIFICATES.md,
 * version 1). Step 3 of the plan of record (docs/ROADMAP.md, "Segments,
 * certificates and the audit tool"); the page's section "The segment
 * runner" is this tool's manual.
 *
 *   cft-segrun --out CERT --states DIR (--salt SALT | --open)
 *              [--device sw|<xclbin>|cft://host:port | --scratch-depth N]
 *              --run main --image IMG [--bank BANK] --init INIT
 *                         --segments S --steps K [--param NAME=N ...]
 *              [--run half-step --h-slots I,J,... --image IMG ...]
 *              [--run wider --image IMG ...]
 *              [--entry drift|step-halving|wider --uses R
 *                       --scope max-lanes|lane:I
 *                       [--quantity LABEL --term C[,sI...] ...]
 *                       --value exact|rounded:FMT:RND|enclosed:FMT] ...
 *   cft-segrun --hash state|stream-a|stream-b|stream-c FILE
 *              (--salt SALT | --open)
 *   cft-segrun --hash commitment --salt SALT
 *   cft-segrun --build-id
 *
 * ---------------------------------------------------------------
 * What it does
 * ---------------------------------------------------------------
 *
 * Each `--run` opens a run block; the options after it, up to the next
 * `--run`, are that run's. Run 0 is `main`; each later run is an
 * auxiliary run, `half-step` (the same image on a bank whose named
 * h-slots are halved, for twice the segments) or `wider` (the image one
 * format wider). For each run the tool takes an image, its bank when the
 * image takes one (`flags.BANK_EXT`), an initial state and a segment
 * count, and runs the image S times on one device handle, each segment
 * entered with the last one's scratch-out: `cft_program_run_ex` with
 * every lane active, no index table and no lane mask, the streams a, b
 * and c all +0 (the tool takes no streams, and the certificate's stream
 * hashes are of the +0 streams it ran).
 *
 * A STATE is the lane-major scratch block exactly as the library stores
 * it, as positive-run's --scratch-in: lane i's slot s is element
 * i * n_scratch_in + s, each element format-width and little-endian.
 * --init is run r's boundary 0; its size fixes the lanes. Every
 * boundary is written to the states directory as it is reached:
 *
 *   DIR/run-<r>-boundary-<b>.bin     b = 0 (the initial state) .. S
 *
 * decimal indices, no leading zeros, the numbering the certificate uses.
 * DIR is created by this run and must not exist before it, so two runs'
 * states never share a directory. It is what an auditor is handed, with
 * the certificate, the images and banks, and a keyed certificate's salt.
 *
 * The certificate is written last, once every segment of every run has
 * run: the lines in the page's order, the accuracy block, `end`, and the
 * hash line. `steps` and every `--param` are stated, not checked, as the
 * page says.
 *
 * ACCURACY ENTRIES (the plan's step 5, 2026-09-30). Each `--entry`, after
 * the runs, is one entry of the accuracy block, in the order given: its
 * method, the run it uses, its scope, a drift's quantity and terms, and
 * its value's form (the page's "Accuracy entries"). The kind is the
 * method's. Every value is computed as "The functions, exactly" says, in
 * its order, each value held to the width rule, by cert_exact.h -
 * cft-audit's own arithmetic, moved there so that the two tools compute
 * with one code - from the states the runs wrote to DIR, read back once
 * every run has run, one entry's two states at a time, each held to the
 * hash the certificate carries at its boundary. Every value first, then
 * every value's form: the golden writer's order (cert.derive, then
 * make_value and encode's reader). With no --entry the block is
 * `accuracy 0`, byte for byte what the tool wrote before step 5.
 *
 * `--scratch-depth N` (the golden-certificate round, 2026-09-29) opens
 * the SOFTWARE backend at N scratch slots a lane through cft_open_ex, as
 * positive-run's option does: the depth is part of what an image
 * computes, since a non-strict STX/LDX reduces its index modulo it. The
 * certificate says so in every run block, `parameter scratch-depth N`,
 * in byte order among the run's parameters - the one parameter the page
 * READS: an audit re-runs a run at it where the device lines carry no
 * CAPS2 depth, as a software certificate's never do ("The chain"). It
 * is written only when the option is given, so every certificate made
 * without it is byte for byte what it always was. Refused `usage`
 * before anything is made: beside a --device other than sw (a device's
 * depth is its image's, and cft_open_ex refuses it too); N not a
 * decimal in its one spelling, or not a power of two in 1..32,768
 * (CAPS2[3:0] is a four-bit log2, cft_open_ex's range and the reader's);
 * and a `--param scratch-depth=...`, since the name is the option's.
 *
 * Every file the tool writes is one it creates new (O_EXCL), and a
 * regular file: --out must not exist either, and no run overwrites a
 * file, so a refusal that removes what it made never removes anything
 * else. --out is created BEFORE DIR, so an --out inside DIR cannot be
 * created at all - DIR does not exist yet - and a certificate can never
 * be one of the boundary files. And what the runs need in memory is
 * tried before either is created (try_runs): taken and let go in the
 * order the runs will take it, so a run the process cannot hold is
 * refused then, by name, while the runs themselves hold no more at once
 * than 99f1b43's did - one run's states at a time - and the accuracy
 * entries after them one entry's two states at a time, which is never
 * more than the largest run held. (Where memory is overcommitted, an
 * allocation the machine cannot back still succeeds, and only what the
 * address space cannot hold is refused.)
 *
 * ---------------------------------------------------------------
 * Hashes
 * ---------------------------------------------------------------
 *
 * Keyed (`--salt`, a file of exactly 32 bytes) or open (`--open`), the
 * owner's choice per certificate. A state's hash is over
 * "cft-certificate 1 state" 0x00 and the state's bytes, a stream's over
 * "cft-certificate 1 stream a" (b, c) 0x00 and its bytes: HMAC-SHA-256
 * under the salt (RFC 2104, SHA-256's 64-byte block) when keyed, plain
 * SHA-256 when open. The commitment is HMAC(salt, "cft-certificate 1
 * salt"), with no NUL. libcft's cft_sha256 is one-shot, so each HMAC
 * pass hashes one buffer: the padded key block, the tag and the bytes.
 * `--hash` prints one of these for a file, which is how the gate holds
 * this code to the page's test vectors.
 *
 * ---------------------------------------------------------------
 * Identity, from the library and nowhere else
 * ---------------------------------------------------------------
 *
 *   build-id        cft_build_id(), verbatim - this binary's library,
 *                   which is libcft.a as it was when this was linked
 *   backend         cft_caps.backend: software, xrt or remote; any other
 *                   answer is written `unknown`
 *   device-xclbin   cft_get_image_id(): the SHA-256 of the bytes loaded
 *   device-version  cft_get_image_id(): VERSION
 *   device-caps     cft_get_image_id(): CAPS alone, or CAPS then CAPS2
 *   device-tiles    cft_caps.tiles, or `unknown` for zero
 *
 * Where cft_get_image_id refuses, the three image lines are `none` on
 * the software backend (no xclbin, no registers), and `unknown`
 * elsewhere, with one exception the page makes: through a remote handle
 * the SERVER's VERSION is written where the protocol carries a nonzero
 * one (cft_caps.device_version, from its HELLO), since the page takes
 * the server's device fields where the protocol carries them. The
 * protocol carries no xclbin digest and no raw CAPS word, so those two
 * are `unknown` there, and device-tiles is the server's.
 *
 * ---------------------------------------------------------------
 * Refusals
 * ---------------------------------------------------------------
 *
 * Every refusal is a name and an exit code, printed as
 * "cft-segrun: refused <name>: <why>" on stderr. The page's names, for
 * the inputs a writer refuses before anything runs:
 *   salt-length (4)    a salt file that is not exactly 32 bytes
 *   program-image (4)  an image whose header does not load, a bank that
 *                      is not the size the image addresses (or any bank
 *                      for an image that carries its constants), or an
 *                      image the library's loader refuses
 *   program-shape (4)  a program that is not a segment: no SCRATCH_IO,
 *                      scratch in and out not equal and at least 1, or
 *                      max_deposits not 0
 *   state-shape (4)    an initial state that is not a whole number of
 *                      lanes, at least one, of the image's slots
 *   malformed (2)      a count or index not in the page's decimal
 *                      spelling or its range (segments and steps at
 *                      least 1; h-slots 1 to 512 of them, each below 512,
 *                      strictly increasing; a parameter name or value);
 *                      run 0 not main, or a later run that is; no run
 *   line-unexpected (2), line-order (2)
 *                      a parameter name repeated, or smaller than the
 *                      one before it (names in byte order)
 * and for an accuracy entry, before anything runs:
 *   malformed (2)      a method, label, run, lane or slot not in its
 *                      spelling (a run, lane or slot given negative, -1,
 *                      is spelt, and names none: accuracy-run, -scope,
 *                      -slot); a drift with no quantity, no term or more
 *                      than 64; an estimate given a quantity or a term; a
 *                      coefficient not in its one spelling; a factor not
 *                      s<slot>, more than 8, or out of order; a value
 *                      that is not exact, rounded:FMT:RND or enclosed:FMT
 *   width (3)          a coefficient past the width rule by its digits
 *   accuracy-run (7)   a run that does not exist, a negative one among
 *                      them; an estimate on run 0,
 *                      on a run of the other kind, or on one whose lanes
 *                      or slots a lane are not run 0's
 *   accuracy-scope (7) a lane the run does not have, a negative one too
 *   accuracy-slot (7)  a slot the run's state does not have, a negative
 *                      one too
 * and after the runs, from the states read back:
 *   accuracy-finite (7) an element a value needs that is not finite
 *   width (3)          a value computed past the rule, in the page's
 *                      order, or an enclosure's finite end past it
 * - the same names, for the same defects, as the golden writer's
 *   (cert.run_chain, certify_run, derive, make_value, encode). And the
 *   tool's own, which the golden writer - an API, not a command - has no
 *   use for:
 *   usage (64)         a command line this tool does not take (among
 *                      them a --scratch-depth it cannot open, above, and
 *                      an entry's options out of place, twice, or
 *                      without --uses, --scope or --value), or a file it
 *                      names that cannot be read
 *   device (69)        the device cannot make or report the run: it does
 *                      not open, it cannot read the sticky flags a
 *                      certificate records (cft_caps.flags_readable), or
 *                      a digest or a segment's run fails; or the software
 *                      handle an accuracy value is rounded and spelt
 *                      through does not open, or a conversion fails
 *   memory (71)        the process cannot have what the runs need, more
 *                      than it can address or more than it is given -
 *                      found before anything is created or run - or
 *                      another of this tool's own allocations fails. The
 *                      LIBRARY's allocations are not this tool's: a
 *                      library out of memory is refused as what failed,
 *                      `program-image` (cft_program_load) or `device`
 *                      (a segment's run); a stdio buffer that cannot be
 *                      had, as `usage` (reading) or `output` (writing)
 *   output (73)        the certificate or the states cannot be created
 *                      or written: --out or DIR already exists, --out is
 *                      not a regular file (Windows' NUL), or --out lies
 *                      inside DIR, which is not there yet; or a boundary
 *                      file read back for an entry is not the state this
 *                      run wrote there (its size or hash): another
 *                      process changed DIR
 *   build-width (78)   a build whose bigint is narrower than the width
 *                      rule's steps need (2,047 bits), given an --entry:
 *                      it has no exact arithmetic (cft-audit's name)
 *   build-format (78)  a value rounded or enclosed in a format above the
 *                      build's CFT_MAX_FORMAT (cft-audit's name)
 * A refusal writes no certificate, and removes only what the run itself
 * created. One made before the first segment leaves nothing behind; a
 * run that fails part way, or an entry refused after the runs, leaves
 * the boundary files it had written, and says so. An exact step past the
 * bigint, which the width rule makes impossible, is no refusal: it prints
 * "cft-segrun: internal error" and exits 70, as cft-audit's does.
 *
 * The read-back refusal has a plant build, not an instrument: compiled
 * with -DCFT_SEGRUN_PLANT_STATE_CHANGED (by the gate, never by the
 * Makefile), the first state read back has a bit flipped, and the run is
 * refused `output`. The tool the Makefile builds has no such path (the
 * lead's condition, 2026-09-30).
 *
 * Two refusals guard against a LIBRARY that misreports a segment's flag
 * word: one it left unwritten (the word preset to all ones is still all
 * ones: `device`), and one past the five sticky flags (`malformed`, as
 * the golden writer's encode would refuse a flag word the reader cannot
 * read). No backend in this tree does either, and none reports
 * flags_readable 0, so CFT_SEGRUN_PLANT is an instrument for the gate
 * that holds those three refusals:
 *   flags-unreadable   the device is treated as one that cannot read its
 *                      flags (refused before anything runs)
 *   flags-unwritten    each segment's flag word is treated as left
 *                      unwritten by the library
 *   flags-wide         each segment's flag word gains bit 5
 * Each says so on stderr, and makes a certificate's run refuse by that
 * name; with --build-id or --hash, which run nothing, it only prints its
 * note and the run exits 0 with the right output. A fourth refuses
 * nothing:
 *   trial-skipped      the trial's allocations are skipped, its size
 *                      checks kept (try_runs), so that the gate can hold
 *                      the trial to costing the runs nothing
 * Any other value is refused as `usage`.
 *
 * ---------------------------------------------------------------
 * What it certifies, and what it does not
 * ---------------------------------------------------------------
 *
 * It certifies what ran: which bits each segment started and ended on
 * (as hashes), with its flags and STATUS, on which library and device;
 * and each accuracy entry's value as the stated function of the states
 * it certifies. It checks nothing about an auxiliary run's relation to
 * the main run - a half-step bank that is not the main bank halved is
 * written as stated and refused by the audit (`aux-bank`), and an
 * estimate against it computed as stated - and nothing about how well an
 * estimate estimates. It signs nothing: the hash line catches
 * corruption, not forgery. The gate is host/tests/segrun_check.py: the
 * golden writer, handed this certificate's identity lines, the same salt,
 * the same initial states and the same entries, runs every segment
 * itself and must write the same bytes.
 */
#if !defined(_WIN32)
#  define _POSIX_C_SOURCE 200112L   /* 199309L hid snprintf on Darwin (2026-09-09) */
#  define _DEFAULT_SOURCE           /* glibc: MAP_ANONYMOUS beside POSIX */
#  define _DARWIN_C_SOURCE          /* Darwin: MAP_ANON beside POSIX */
#endif

#include <errno.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if defined(_WIN32)
#  ifndef WIN32_LEAN_AND_MEAN
#    define WIN32_LEAN_AND_MEAN
#  endif
#  include <windows.h>              /* VirtualAlloc, for try_runs */
#  include <direct.h>
#  include <fcntl.h>
#  include <io.h>
#  include <sys/stat.h>
#  define MKDIR(p) _mkdir(p)
#  define RMDIR(p) _rmdir(p)
#else
#  include <fcntl.h>
#  include <sys/mman.h>             /* mmap, for try_runs */
#  include <sys/stat.h>
#  include <sys/types.h>
#  include <unistd.h>
#  define MKDIR(p) mkdir((p), 0777)
#  define RMDIR(p) rmdir(p)
#  if defined(MAP_ANONYMOUS)
#    define SEG_MAP_ANON MAP_ANONYMOUS
#  elif defined(MAP_ANON)
#    define SEG_MAP_ANON MAP_ANON
#  endif
#endif
/* stat, fstat and fileno under their Windows names, which -std=c99
 * leaves declared there, and the POSIX ones elsewhere */
#if defined(_WIN32)
typedef struct _stat stat_t;
#  define STAT(p, b)   _stat((p), (b))
#  define FSTAT(d, b)  _fstat((d), (b))
#  define FILENO(f)    _fileno(f)
#  define IS_FILE(m)   (((m) & _S_IFMT) == _S_IFREG)
#else
typedef struct stat stat_t;
#  define STAT(p, b)   stat((p), (b))
#  define FSTAT(d, b)  fstat((d), (b))
#  define FILENO(f)    fileno(f)
#  define IS_FILE(m)   S_ISREG(m)
#endif

/* A file this run creates NEW, or NULL with errno set (EEXIST when the
 * path is taken): O_EXCL, so no file the tool writes is one it did not
 * create, and a refusal that removes what the run made removes nothing
 * else. Windows answers O_EXCL on a directory that is there with EACCES,
 * not EEXIST, so a path that is there is called so whatever it is. */
static FILE *create_new(const char *path)
{
    FILE *f;
    int e;
    stat_t sb;
#if defined(_WIN32)
    int fd = _open(path, _O_WRONLY | _O_CREAT | _O_EXCL | _O_BINARY,
                   _S_IREAD | _S_IWRITE);
#else
    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL, 0666);
#endif
    if (fd < 0) {
        e = errno;
        if (e == EACCES && STAT(path, &sb) == 0)
            e = EEXIST;
        errno = e;
        return NULL;
    }
#if defined(_WIN32)
    f = _fdopen(fd, "wb");
    if (!f) {
        e = errno;
        _close(fd);
        remove(path);
        errno = e;
    }
#else
    f = fdopen(fd, "wb");
    if (!f) {
        e = errno;
        close(fd);
        remove(path);
        errno = e;
    }
#endif
    return f;
}

#include "cft.h"
/* An accuracy entry's exact arithmetic, cft-audit's, shared (the plan's
 * step 5): the functions exactly, the width rule, the rounding and the
 * enclosure, each returning a status this file refuses by name. With it
 * come the formats (FMT, ESZ), the directions (RND_NAME), the run kinds
 * (K_MAIN, K_HALF, K_WIDER, KIND_NAME) and the methods' words. */
#include "cert_exact.h"

/* refuse() never returns, and its message is a printf format. mingw-w64
 * names the archetype its stdio really is; elsewhere it is printf. */
#if defined(__GNUC__)
#  define NORETURN __attribute__((noreturn))
#  if defined(__MINGW_PRINTF_FORMAT)
#    define PRINTF_LIKE(f, a) \
         __attribute__((format(__MINGW_PRINTF_FORMAT, f, a)))
#  else
#    define PRINTF_LIKE(f, a) __attribute__((format(printf, f, a)))
#  endif
#else
#  define NORETURN
#  define PRINTF_LIKE(f, a)
#endif

#define HEADER_BYTES  32
#define SALT_BYTES    32
#define MAX_HSLOTS    512      /* h-slots at most, and each below it */
#define MAX_NAME      64       /* a parameter's name, at most */
/* --scratch-depth: a power of two in 1..DEPTH_MAX, since CAPS2[3:0] is a
 * four-bit log2 (cft_open_ex's range, and the reader's for the one
 * parameter the page reads, which carries it) */
#define DEPTH_MAX     32768u
static const char DEPTH_PARAM[] = "scratch-depth";
#define DEPTH_PARAM_LEN (sizeof DEPTH_PARAM - 1)
#define FLAGS_KNOWN   (CFT_PROG_FLAG_BANK_EXT | CFT_PROG_FLAG_SCRATCH_IO | \
                       CFT_PROG_FLAG_SCRATCH_STRICT)

/* The domain tags (docs/CERTIFICATES.md, "Hashes"). Each length is
 * stated, not left to a terminator: a state's and a stream's tag END IN
 * a NUL byte, which is the separator the page puts before the bytes,
 * and the salt's has none. */
static const char TAG_SALT[]     = "cft-certificate 1 salt";
#define TAG_SALT_LEN   (sizeof TAG_SALT - 1)        /* 22, no NUL */
static const char TAG_STATE[]    = "cft-certificate 1 state";
#define TAG_STATE_LEN  (sizeof TAG_STATE)           /* 24, the NUL included */
static const char TAG_STREAM_A[] = "cft-certificate 1 stream a";
static const char TAG_STREAM_B[] = "cft-certificate 1 stream b";
static const char TAG_STREAM_C[] = "cft-certificate 1 stream c";
#define TAG_STREAM_LEN (sizeof TAG_STREAM_A)        /* 27, the NUL included */

static const char *const FORMAT_NAME[4] = { "fp32", "fp64", "fp128", "fp256" };

/* ---- refusals ---------------------------------------------------------- */

static const struct { const char *name; int code; } REFUSAL[] = {
    /* the page's names: the inputs a writer refuses */
    { "malformed", 2 }, { "line-order", 2 }, { "line-unexpected", 2 },
    { "width", 3 },
    { "salt-length", 4 }, { "program-image", 4 }, { "program-shape", 4 },
    { "state-shape", 4 },
    { "accuracy-run", 7 }, { "accuracy-scope", 7 }, { "accuracy-slot", 7 },
    { "accuracy-finite", 7 },
    /* the tool's own (docs/CERTIFICATES.md, "The segment runner") */
    { "usage", 64 }, { "device", 69 }, { "memory", 71 }, { "output", 73 },
    { "build-width", 78 }, { "build-format", 78 },
};

/* What a refusal must undo: the certificate this run created is
 * removed, and the states directory this run created is removed while
 * it is still empty. Both were created new (create_new, mkdir), so
 * nothing here is ever a file the run did not make. */
static const char *CERT_PATH = NULL;
static FILE *CERT_FP = NULL;
static const char *STATES_DIR = NULL;
static int STATES_CREATED = 0;
static unsigned long long STATE_FILES = 0;

/* CFT_SEGRUN_PLANT, the instrument (the header comment). */
static int PLANT_UNREADABLE = 0, PLANT_UNWRITTEN = 0, PLANT_WIDE = 0;
static int PLANT_NO_TRIAL = 0;

/* --scratch-depth N, or 0 where it was not given: the software backend
 * is then opened plainly, at its own 256, and no run block states it */
static uint32_t SCRATCH_DEPTH = 0;

static void cleanup(void)
{
    if (CERT_FP) {
        fclose(CERT_FP);
        CERT_FP = NULL;
        remove(CERT_PATH);
    }
    if (STATES_CREATED && STATE_FILES == 0) {
        RMDIR(STATES_DIR);
        STATES_CREATED = 0;
    } else if (STATES_CREATED) {
        fprintf(stderr, "cft-segrun: no certificate was written; the %llu "
                "boundary state file%s written so far %s left in %s\n",
                STATE_FILES, STATE_FILES == 1 ? "" : "s",
                STATE_FILES == 1 ? "is" : "are", STATES_DIR);
    }
}

static void refuse(const char *name, const char *fmt, ...)
    NORETURN PRINTF_LIKE(2, 3);
static void refuse_st(const char *name, const char *what, cft_status st)
    NORETURN;
#if CX_EXACT
static void internal(const char *what) NORETURN;
#endif

static void refuse(const char *name, const char *fmt, ...)
{
    va_list ap;
    size_t i;
    int code = -1;
    for (i = 0; i < sizeof REFUSAL / sizeof REFUSAL[0]; i++)
        if (!strcmp(REFUSAL[i].name, name))
            code = REFUSAL[i].code;
    if (code < 0) {
        fprintf(stderr, "cft-segrun: internal error: unnamed refusal '%s'\n",
                name);
        cleanup();
        exit(70);
    }
    fprintf(stderr, "cft-segrun: refused %s: ", name);
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fputc('\n', stderr);
    cleanup();
    exit(code);
}

/* What no refusal names and the width rule makes impossible: an exact step
 * past the bigint. Not a verdict on the input, so no name of the page's:
 * exit 70, as cft-audit's internal error (the lead's decision,
 * 2026-09-30). Only the exact arithmetic can reach it. */
#if CX_EXACT
static void internal(const char *what)
{
    fprintf(stderr, "cft-segrun: internal error: %s\n", what);
    cleanup();
    exit(70);
}
#endif

/* cft_last_error() before the calls refuse_st reports on, once a call
 * whose failure the tool expects has left its sentence there (identify's
 * cft_get_image_id, on the software backend and through a remote one). A
 * sentence can outlive its call (cft.h): the one a failure reports must
 * be one it wrote, so the same sentence as before is not shown. */
static char LAST_BEFORE[512];

static void refuse_st(const char *name, const char *what, cft_status st)
{
    const char *detail = cft_last_error();
    int fresh = detail && *detail &&
                strncmp(detail, LAST_BEFORE, sizeof LAST_BEFORE - 1) != 0;
    refuse(name, "%s: %s%s%s", what, cft_strerror(st), fresh ? " - " : "",
           fresh ? detail : "");
}

/* Every allocation of the tool's that fails is refused by name, `memory`.
 * What a run's size decides is tried before anything is made (try_runs)
 * and taken again as the run reaches it (run_take); this is the rest:
 * the inputs as they are read, the command line's lists, a hash's
 * buffer, a boundary file's path, and the certificate's text. */
static void *xcalloc(size_t n, size_t sz)
{
    void *p;
    if (sz && n > (size_t)-1 / sz)
        p = NULL;
    else
        p = calloc(n ? n : 1, sz ? sz : 1);
    if (!p)
        refuse("memory", "%llu x %llu bytes could not be allocated",
               (unsigned long long)n, (unsigned long long)sz);
    return p;
}

/* ---- files ------------------------------------------------------------- */

/* The whole file, or NULL with errno set. */
static uint8_t *read_file(const char *path, size_t *n_out)
{
    FILE *f = fopen(path, "rb");
    uint8_t *buf;
    size_t cap = 1 << 16, have = 0;
    if (!f)
        return NULL;
    buf = (uint8_t *)xcalloc(cap, 1);
    for (;;) {
        size_t got;
        if (have == cap) {
            uint8_t *bigger = (uint8_t *)xcalloc(cap, 2);
            memcpy(bigger, buf, have);
            free(buf);
            buf = bigger;
            cap *= 2;
        }
        got = fread(buf + have, 1, cap - have, f);
        have += got;
        if (got == 0)
            break;
    }
    if (ferror(f)) {
        int e = errno;
        fclose(f);
        free(buf);
        errno = e ? e : EIO;
        return NULL;
    }
    fclose(f);
    *n_out = have;
    return buf;
}

static uint8_t *read_named(const char *what, const char *path, size_t *n)
{
    uint8_t *p = read_file(path, n);
    if (!p)
        refuse("usage", "%s %s cannot be read (%s)", what, path,
               strerror(errno));
    return p;
}

static uint32_t get_le32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

/* ---- the page's spellings ---------------------------------------------- */

/* A decimal integer in its one spelling - 0, or a nonzero digit and
 * digits - at most 2^63 - 1. Nineteen digits cannot wrap a uint64. */
static int dec_ok(const char *s, uint64_t *out)
{
    size_t i, n = strlen(s);
    uint64_t v = 0;
    if (n == 0 || n > 19 || (s[0] == '0' && n > 1))
        return 0;
    for (i = 0; i < n; i++) {
        if (s[i] < '0' || s[i] > '9')
            return 0;
        v = v * 10u + (uint64_t)(s[i] - '0');
    }
    if (v > (uint64_t)INT64_MAX)
        return 0;
    *out = v;
    return 1;
}

/* A name: a lowercase letter, then lowercase letters, digits and '-',
 * at most 64 characters. */
static int name_ok(const char *s, size_t n)
{
    size_t i;
    if (n == 0 || n > MAX_NAME || s[0] < 'a' || s[0] > 'z')
        return 0;
    for (i = 1; i < n; i++)
        if (!((s[i] >= 'a' && s[i] <= 'z') || (s[i] >= '0' && s[i] <= '9') ||
              s[i] == '-'))
            return 0;
    return 1;
}

/* Two names in the reader's byte order - ASCII's, a name before every
 * longer one it begins: <0, 0 or >0 as a comes before, is, or comes
 * after b. */
static int name_cmp(const char *a, size_t an, const char *b, size_t bn)
{
    int c = memcmp(a, b, an < bn ? an : bn);
    if (c == 0)
        c = an < bn ? -1 : an > bn ? 1 : 0;
    return c;
}

/* cft_build_id()'s grammar, as the page's reader holds the build-id line
 * to it: `unknown` whole, or its three fields in their order. */
static int build_id_ok(const char *s)
{
    size_t n = 0;
    const char *p;
    if (!strcmp(s, "unknown"))
        return 1;
    if (strncmp(s, "commit=", 7) != 0)
        return 0;
    p = s + 7;
    while ((p[n] >= '0' && p[n] <= '9') || (p[n] >= 'a' && p[n] <= 'f'))
        n++;
    if (n != 40 && n != 64)
        return 0;
    p += n;
    if (!strncmp(p, " tracked=clean", 14))
        p += 14;
    else if (!strncmp(p, " tracked=modified", 17))
        p += 17;
    else
        return 0;
    return !strcmp(p, " untracked=none") || !strcmp(p, " untracked=present");
}

static void hex_of(const uint8_t *in, size_t n, char *out)
{
    static const char D[] = "0123456789abcdef";
    size_t i;
    for (i = 0; i < n; i++) {
        out[2 * i]     = D[in[i] >> 4];
        out[2 * i + 1] = D[in[i] & 15];
    }
    out[2 * n] = 0;
}

/* ---- the hashes ---------------------------------------------------------- */

static void sha256_of(const void *data, size_t n, uint8_t out[32])
{
    cft_status st = cft_sha256(data, n, out);
    if (st != CFT_OK)
        refuse_st("device", "cft_sha256", st);
}

/* HMAC-SHA-256 (RFC 2104, B = 64) of tag || msg under a 32-byte key.
 * The key is shorter than the block, so it is its own K0, zero-padded;
 * cft_sha256 is one-shot, so each pass hashes one buffer, taken for the
 * hash and let go after it - never held while the library runs a
 * segment, which has buffers of its own. */
static void hmac_sha256(const uint8_t key[SALT_BYTES],
                        const void *tag, size_t tag_len,
                        const void *msg, size_t msg_len, uint8_t out[32])
{
    uint8_t *inner = (uint8_t *)xcalloc(64 + tag_len + msg_len, 1);
    uint8_t outer[64 + 32], ih[32];
    size_t i;
    for (i = 0; i < 64; i++) {
        uint8_t k = i < SALT_BYTES ? key[i] : 0;
        inner[i] = (uint8_t)(k ^ 0x36);
        outer[i] = (uint8_t)(k ^ 0x5c);
    }
    if (tag_len)
        memcpy(inner + 64, tag, tag_len);
    if (msg_len)
        memcpy(inner + 64 + tag_len, msg, msg_len);
    sha256_of(inner, 64 + tag_len + msg_len, ih);
    free(inner);
    memcpy(outer + 64, ih, 32);
    sha256_of(outer, sizeof outer, out);
}

/* The hash of tag || bytes: keyed under `salt`, or open (plain SHA-256)
 * when `salt` is NULL. */
static void tagged_hash(const uint8_t *salt, const char *tag, size_t tag_len,
                        const void *bytes, size_t n, char hex[65])
{
    uint8_t d[32];
    if (salt) {
        hmac_sha256(salt, tag, tag_len, bytes, n, d);
    } else {
        uint8_t *buf = (uint8_t *)xcalloc(tag_len + n, 1);
        memcpy(buf, tag, tag_len);
        if (n)
            memcpy(buf + tag_len, bytes, n);
        sha256_of(buf, tag_len + n, d);
        free(buf);
    }
    hex_of(d, 32, hex);
}

static void state_hash(const uint8_t *salt, const void *bytes, size_t n,
                       char hex[65])
{
    tagged_hash(salt, TAG_STATE, TAG_STATE_LEN, bytes, n, hex);
}

static const char *stream_tag(int which)
{
    return which == 0 ? TAG_STREAM_A : which == 1 ? TAG_STREAM_B
                                                   : TAG_STREAM_C;
}

static void salt_commitment(const uint8_t *salt, char hex[65])
{
    uint8_t d[32];
    hmac_sha256(salt, TAG_SALT, TAG_SALT_LEN, NULL, 0, d);
    hex_of(d, 32, hex);
}

/* ---- the image header, read before the library sees the bytes --------- */

typedef struct {
    uint32_t n_insns, n_consts, max_deposits, prec, flags;
    uint32_t n_in, n_out;
} header;

/* NULL when the header describes these bytes, else why not. */
static const char *parse_header(const uint8_t *img, size_t n, header *H,
                                char *why, size_t cap)
{
    uint32_t scratch_io;
    uint64_t want, esz;
    if (n < HEADER_BYTES) {
        snprintf(why, cap, "it is %lu bytes, shorter than a %d-byte header",
                 (unsigned long)n, HEADER_BYTES);
        return why;
    }
    if (get_le32(img) != 0x50544643u)
        return "it does not begin with CFTP";
    if (get_le32(img + 4) != 1u) {
        snprintf(why, cap, "program version %u; version 1 is the one there is",
                 (unsigned)get_le32(img + 4));
        return why;
    }
    H->n_insns      = get_le32(img + 8);
    H->n_consts     = get_le32(img + 12);
    H->max_deposits = get_le32(img + 16);
    H->prec         = get_le32(img + 20);
    H->flags        = get_le32(img + 24);
    scratch_io      = get_le32(img + 28);
    if (H->prec > 3) {
        snprintf(why, cap, "precision code %u is not on the ladder",
                 (unsigned)H->prec);
        return why;
    }
    if (H->flags & ~(uint32_t)FLAGS_KNOWN) {
        snprintf(why, cap, "header flags 0x%08x set a bit no revision assigns",
                 (unsigned)H->flags);
        return why;
    }
    if (!(H->flags & CFT_PROG_FLAG_SCRATCH_IO) && scratch_io)
        return "header word 7 is not zero, and flags.SCRATCH_IO does not say "
               "it is scratch_io";
    H->n_in  = scratch_io & 0xFFFFu;
    H->n_out = (scratch_io >> 16) & 0xFFFFu;
    esz = cft_format_size((cft_format)H->prec);
    want = HEADER_BYTES + (uint64_t)H->n_insns * 8u +
           ((H->flags & CFT_PROG_FLAG_BANK_EXT) ? 0u
                                                : (uint64_t)H->n_consts * esz);
    if (want != (uint64_t)n) {
        snprintf(why, cap, "it is %lu bytes, and its header describes %llu",
                 (unsigned long)n, (unsigned long long)want);
        return why;
    }
    return NULL;
}

/* NULL when the program is a segment (the page's "A program is a
 * segment"), else why not - the golden writer's words. */
static const char *segment_shape(const header *H, char *why, size_t cap)
{
    if (!(H->flags & CFT_PROG_FLAG_SCRATCH_IO))
        return "it declares no scratch block (flags.SCRATCH_IO clear)";
    if (H->n_in != H->n_out || H->n_in < 1) {
        snprintf(why, cap, "its scratch block goes in as %u and out as %u "
                 "slots a lane; a segment's end state must be the next one's "
                 "start", (unsigned)H->n_in, (unsigned)H->n_out);
        return why;
    }
    if (H->max_deposits) {
        snprintf(why, cap, "it deposits (%u slots a lane); version 1 "
                 "certifies the scratch state only, and a deposit would go "
                 "uncertified", (unsigned)H->max_deposits);
        return why;
    }
    return NULL;
}

/* ---- one run --------------------------------------------------------- */

/* (the kinds, K_MAIN, K_HALF and K_WIDER, and their words, KIND_NAME, are
 * cert_exact.h's) */

typedef struct {
    int kind;
    const char *image_path, *bank_path, *init_path;
    const char *segments_s, *steps_s, *hslots_s;
    const char **param_s;
    size_t n_param_s;

    /* read and checked */
    uint8_t *img, *bank, *init;
    size_t img_bytes, bank_bytes, init_bytes;
    header H;
    size_t esz, lanes, state_bytes;
    uint64_t segments, steps;
    unsigned hslots[MAX_HSLOTS];
    size_t n_hslots;

    /* made */
    cft_program *prog;
    char image_digest[65], program_digest[65];
    char stream_hash[3][65];
    char (*hash)[65];           /* boundaries 0..S */
    uint32_t *flags, *status;   /* segments 0..S-1 */
} run_spec;

static void add_param(run_spec *r, const char *s)
{
    const char **grown = (const char **)xcalloc(r->n_param_s + 1,
                                                sizeof *grown);
    if (r->n_param_s)
        memcpy(grown, r->param_s, r->n_param_s * sizeof *grown);
    free(r->param_s);
    grown[r->n_param_s++] = s;
    r->param_s = grown;
}

/* ---- one accuracy entry (docs/CERTIFICATES.md, "Accuracy entries") ----- */

typedef struct {
    /* as given: --entry, --uses, --scope, --quantity, each --term, --value */
    const char *method_s, *uses_s, *scope_s, *label_s, *value_s;
    const char **term_s;
    size_t n_term_s;

    /* checked before anything is made: the bytes of the two states it
     * reads, and of its lines in the certificate, at least and at most */
    size_t need_bytes[2];
    size_t text_least, text_most;
#if CX_EXACT
    entry_t E;          /* its definition; E.value is made after the runs */
    rat q;              /* its value, derived after the runs */
#endif
} entry_spec;

static void add_term(entry_spec *X, const char *s)
{
    const char **grown = (const char **)xcalloc(X->n_term_s + 1,
                                                sizeof *grown);
    if (X->n_term_s)
        memcpy(grown, X->term_s, X->n_term_s * sizeof *grown);
    free(X->term_s);
    grown[X->n_term_s++] = s;
    X->term_s = grown;
}

/* Everything about run `idx` that can be refused before a device is
 * opened, in the golden writer's order: the image loads, it is a
 * segment, its bank, its initial state; then the counts and the
 * parameters the reader would refuse. */
static void check_run(run_spec *r, size_t idx)
{
    char why[256];
    const char *bad;
    uint64_t v;

    if (idx == 0 && r->kind != K_MAIN)
        refuse("malformed", "run 0 is 'run 0 main'; this certificate's first "
               "run is %s", KIND_NAME[r->kind]);
    if (idx > 0 && r->kind == K_MAIN)
        refuse("malformed", "run 0, and only run 0, is 'run 0 main'; run %lu "
               "is main too", (unsigned long)idx);
    if (!r->image_path || !r->init_path || !r->segments_s || !r->steps_s)
        refuse("usage", "run %lu (%s) needs --image, --init, --segments and "
               "--steps", (unsigned long)idx, KIND_NAME[r->kind]);
    if (r->hslots_s && r->kind != K_HALF)
        refuse("usage", "run %lu is %s: --h-slots belongs to a half-step run",
               (unsigned long)idx, KIND_NAME[r->kind]);

    /* the image */
    r->img = read_named("the image", r->image_path, &r->img_bytes);
    bad = parse_header(r->img, r->img_bytes, &r->H, why, sizeof why);
    if (bad)
        refuse("program-image", "run %lu: %s does not load: %s",
               (unsigned long)idx, r->image_path, bad);
    r->esz = cft_format_size((cft_format)r->H.prec);
    bad = segment_shape(&r->H, why, sizeof why);
    if (bad)
        refuse("program-shape", "run %lu: %s is not a segment: %s",
               (unsigned long)idx, r->image_path, bad);

    /* its bank */
    if (r->bank_path)
        r->bank = read_named("the bank", r->bank_path, &r->bank_bytes);
    if (r->H.flags & CFT_PROG_FLAG_BANK_EXT) {
        uint64_t want = (uint64_t)r->H.n_consts * r->esz;
        if ((uint64_t)r->bank_bytes != want)
            refuse("program-image", "run %lu: the bank is %lu bytes; the "
                   "image addresses %u constants of %lu bytes, %llu in all",
                   (unsigned long)idx, (unsigned long)r->bank_bytes,
                   (unsigned)r->H.n_consts, (unsigned long)r->esz,
                   (unsigned long long)want);
    } else if (r->bank_bytes) {
        refuse("program-image", "run %lu: this image carries its own "
               "constants, so the bank must be empty; %s is %lu bytes",
               (unsigned long)idx, r->bank_path, (unsigned long)r->bank_bytes);
    }

    /* its initial state */
    r->init = read_named("the initial state", r->init_path, &r->init_bytes);
    {
        size_t lane = (size_t)r->H.n_in * r->esz;
        /* Empty is a state of no lanes, and `lanes` is at least 1: the
         * wrong size, like a part of a lane. (The golden writer has no
         * name for the empty case: cert.run_chain hands seq.run an empty
         * block and it raises seq.ProgramError.) */
        if (r->init_bytes == 0 || r->init_bytes % lane)
            refuse("state-shape", "run %lu: %s is %lu bytes, not a whole "
                   "number of lanes, at least one, of %u %s slots (%lu "
                   "bytes a lane, lane-major)", (unsigned long)idx,
                   r->init_path, (unsigned long)r->init_bytes,
                   (unsigned)r->H.n_in, FORMAT_NAME[r->H.prec],
                   (unsigned long)lane);
        r->lanes = r->init_bytes / lane;
        r->state_bytes = r->init_bytes;
    }

    /* the counts */
    if (!dec_ok(r->segments_s, &v) || v < 1)
        refuse("malformed", "run %lu: segments '%s' is not a decimal "
               "integer from 1 to 2^63 - 1 in its one spelling",
               (unsigned long)idx, r->segments_s);
    r->segments = v;
    if (!dec_ok(r->steps_s, &v) || v < 1)
        refuse("malformed", "run %lu: steps '%s' is not a decimal integer "
               "from 1 to 2^63 - 1 in its one spelling", (unsigned long)idx,
               r->steps_s);
    r->steps = v;

    /* the h-slots */
    if (r->kind == K_HALF) {
        const char *p = r->hslots_s;
        if (!p)
            refuse("malformed", "run %lu is half-step, and a half-step run "
                   "names 1 to %d h-slots (--h-slots I,J,...)",
                   (unsigned long)idx, MAX_HSLOTS);
        for (;;) {
            char tok[24];
            size_t n = strcspn(p, ",");
            if (n == 0 || n >= sizeof tok)
                refuse("malformed", "run %lu: --h-slots '%s' is not a list "
                       "of decimal slot indices separated by commas",
                       (unsigned long)idx, r->hslots_s);
            memcpy(tok, p, n);
            tok[n] = 0;
            if (!dec_ok(tok, &v) || v >= MAX_HSLOTS)
                refuse("malformed", "run %lu: h-slot '%s' is not a decimal "
                       "index below %d in its one spelling",
                       (unsigned long)idx, tok, MAX_HSLOTS);
            if (r->n_hslots == MAX_HSLOTS)
                refuse("malformed", "run %lu: more than %d h-slots",
                       (unsigned long)idx, MAX_HSLOTS);
            if (r->n_hslots && v <= r->hslots[r->n_hslots - 1])
                refuse("malformed", "run %lu: h-slot indices are strictly "
                       "increasing, and %s follows %u", (unsigned long)idx,
                       tok, r->hslots[r->n_hslots - 1]);
            r->hslots[r->n_hslots++] = (unsigned)v;
            if (!p[n])
                break;
            p += n + 1;
        }
    }

    /* the parameters, as the reader takes each line: the name's spelling,
     * then its place in byte order, then the value */
    {
        size_t k;
        const char *prev = NULL;
        size_t prev_n = 0;
        for (k = 0; k < r->n_param_s; k++) {
            const char *s = r->param_s[k];
            const char *eq = strchr(s, '=');
            size_t n = eq ? (size_t)(eq - s) : strlen(s);
            int c;
            if (!eq || !name_ok(s, n))
                refuse("malformed", "run %lu: --param '%s' is not NAME=N with "
                       "NAME a lowercase letter, then lowercase letters, "
                       "digits and '-', at most %d", (unsigned long)idx, s,
                       MAX_NAME);
            if (prev) {
                c = name_cmp(prev, prev_n, s, n);
                if (c == 0)
                    refuse("line-unexpected", "run %lu: parameter '%.*s' "
                           "again", (unsigned long)idx, (int)n, s);
                if (c > 0)
                    refuse("line-order", "run %lu: parameter '%.*s' comes "
                           "after '%.*s'; names are in increasing byte order",
                           (unsigned long)idx, (int)n, s, (int)prev_n, prev);
            }
            if (!dec_ok(eq + 1, &v))
                refuse("malformed", "run %lu: parameter '%.*s' = '%s' is not "
                       "a decimal integer from 0 to 2^63 - 1 in its one "
                       "spelling", (unsigned long)idx, (int)n, s, eq + 1);
            prev = s;
            prev_n = n;
        }
    }
}

/* ---- the certificate's text --------------------------------------------- */

typedef struct {
    char  *p;
    size_t n, cap;
} text;

static void put(text *t, const char *fmt, ...) PRINTF_LIKE(2, 3);

static void put(text *t, const char *fmt, ...)
{
    va_list ap;
    int len;
    va_start(ap, fmt);
    len = vsnprintf(NULL, 0, fmt, ap);
    va_end(ap);
    if (len < 0)
        refuse("output", "a certificate line could not be formatted");
    if (t->n + (size_t)len + 1 > t->cap) {
        size_t cap = t->cap ? t->cap : 4096;
        char *grown;
        while (t->n + (size_t)len + 1 > cap)
            cap *= 2;
        grown = (char *)xcalloc(cap, 1);
        if (t->n)
            memcpy(grown, t->p, t->n);
        free(t->p);
        t->p = grown;
        t->cap = cap;
    }
    va_start(ap, fmt);
    vsnprintf(t->p + t->n, (size_t)len + 1, fmt, ap);
    va_end(ap);
    t->n += (size_t)len;
}

/* ---- identity ------------------------------------------------------------ */

typedef struct {
    const char *build_id;
    const char *backend;        /* one of the page's four words */
    char xclbin[72], version[16], caps[24], tiles[24];
} identity;

static void identify(cft_device *dev, const cft_caps *caps, identity *id)
{
    cft_image_id im;
    cft_status st;
    int sw = !strcmp(caps->backend, "software");
    int remote = !strcmp(caps->backend, "remote");

    id->build_id = cft_build_id();
    if (!id->build_id || !build_id_ok(id->build_id))
        refuse("malformed", "cft_build_id() returned '%s', which is not the "
               "page's grammar; the build-id line is that string verbatim, "
               "so no certificate can be written from it",
               id->build_id ? id->build_id : "(null)");

    id->backend = sw ? "software" : remote ? "remote"
                : !strcmp(caps->backend, "xrt") ? "xrt" : "unknown";

    memset(&im, 0, sizeof im);
    im.struct_size = sizeof im;
    st = cft_get_image_id(dev, &im);
    if (st == CFT_OK && im.struct_size >= offsetof(cft_image_id, caps) +
                                            2 * sizeof im.caps[0]) {
        hex_of(im.sha256, 32, id->xclbin);
        snprintf(id->version, sizeof id->version, "%08x", (unsigned)im.version);
        if (im.n_caps == 1)
            snprintf(id->caps, sizeof id->caps, "%08x", (unsigned)im.caps[0]);
        else if (im.n_caps == 2)
            snprintf(id->caps, sizeof id->caps, "%08x %08x",
                     (unsigned)im.caps[0], (unsigned)im.caps[1]);
        else
            snprintf(id->caps, sizeof id->caps, "unknown");
    } else if (sw) {
        /* no xclbin and no registers: the fields do not exist here */
        snprintf(id->xclbin, sizeof id->xclbin, "none");
        snprintf(id->version, sizeof id->version, "none");
        snprintf(id->caps, sizeof id->caps, "none");
    } else {
        snprintf(id->xclbin, sizeof id->xclbin, "unknown");
        snprintf(id->caps, sizeof id->caps, "unknown");
        if (remote && caps->device_version)
            snprintf(id->version, sizeof id->version, "%08x",
                     (unsigned)caps->device_version);
        else
            snprintf(id->version, sizeof id->version, "unknown");
    }
    if (caps->tiles >= 1)
        snprintf(id->tiles, sizeof id->tiles, "%u", (unsigned)caps->tiles);
    else
        snprintf(id->tiles, sizeof id->tiles, "unknown");
}

/* ---- the states directory ---------------------------------------------- */

/* A boundary file's path: the directory's name, "/run-", 20 digits,
 * "-boundary-", 20, ".bin". */
#define PATH_TAIL 64

static void write_boundary(size_t r, uint64_t b, const void *state, size_t n)
{
    size_t cap = strlen(STATES_DIR) + PATH_TAIL;
    char *path = (char *)xcalloc(cap, 1);
    FILE *f;
    snprintf(path, cap, "%s/run-%lu-boundary-%llu.bin", STATES_DIR,
             (unsigned long)r, (unsigned long long)b);
    /* created new: the directory is the run's own, so a file already
     * there is one this run did not make, and it is left as it is */
    f = create_new(path);
    if (!f)
        refuse("output", "%s cannot be created (%s)", path,
               errno == EEXIST ? "a file this run did not make is there "
                                 "already" : strerror(errno));
    STATE_FILES++;
    if (fwrite(state, 1, n, f) != n) {
        fclose(f);
        refuse("output", "a short write to %s", path);
    }
    if (fclose(f) != 0)
        refuse("output", "%s could not be closed (%s)", path, strerror(errno));
    free(path);
}

/* ---- what every run needs, tried before anything is created or run --- */

/* The certificate's text. At most, for the count against what the
 * process can address: a segment's line is 195 bytes ("segment " and 19
 * digits, " start " and 64, " end " and 64, " flags " and 2, " status "
 * and 10, and its LF); a run block's other lines are under 1 KiB beside
 * its h-slots (4 bytes each) and parameters (under 100 each); the
 * header, `accuracy`, `end` and the hash line under 1 KiB. At the least,
 * for the trial: the segment lines alone, each at least 167 bytes (one
 * digit where the most is 19, 2 and 10). */
#define SEGMENT_TEXT     200
#define SEGMENT_TEXT_MIN 167
#define RUN_TEXT         4096
#define HSLOT_TEXT       4
#define PARAM_TEXT       100
#define HEAD_TEXT        2048

static int mul_ok(size_t a, size_t b, size_t *out)
{
    if (b && a > (size_t)-1 / b)
        return 0;
    *out = a * b;
    return 1;
}

static int add_ok(size_t *acc, size_t v)
{
    if (*acc > (size_t)-1 - v)
        return 0;
    *acc += v;
    return 1;
}

/* ---- the trial ------------------------------------------------------------
 *
 * The runs allocate as 99f1b43's tool did, and hold no more at once: a
 * run's boundary hashes, flag words and STATUS when it starts, kept for
 * the certificate; its two states and its +0 streams, let go when it
 * ends; a hash's buffer and a boundary file's path for as long as each
 * takes; the certificate's text last, grown as it is written. So a run
 * beside the main run costs its own inputs and hashes, never a second
 * working set (verifier-C7, 2026-09-28: 4eed552 held every run's states
 * at once, and refused under a limit a certificate 99f1b43 writes). They
 * hold a little less than 99f1b43's did: each image is let go once the
 * library has loaded and digested it, each initial state once it is
 * copied into the run's first state.
 *
 * The accuracy entries come after the last run has let its states go:
 * each reads its two states back from DIR into buffers of their exact
 * size and lets both go before the next entry reads its own (the plan's
 * step 5). The pair is one run's (a drift) or run 0's final state beside
 * a run of run 0's lanes and slots (an estimate), so the entries hold no
 * more at once than the largest run did: its two states, its streams
 * and a hash's copy. Measured with segrun_check's section 10
 * (2026-09-30): beside flagstep's three runs of 65,535 lanes, two
 * entries reading four states back cost no more peak commit than the
 * runs alone, to within the noise of identical runs, so they hold no
 * state beside the runs'; and beside slotstep's one run of 8 MiB states,
 * where the entries' phase is the peak, two drifts cost the run alone's
 * peak to within a quarter of a state - from 476 KiB less to 116 KiB
 * more (S1 and verifier-W1b) - where a state more at once would cost 7.5
 * MiB (the first shape cannot see that: verifier-W1).
 *
 * Before anything is made, try_runs counts all of it against what the
 * process can address, and then tries, in the runs' own order, the
 * pieces their size decides: each run's hashes, flag words and STATUS,
 * kept; its two states and its streams, taken and let go; then each
 * entry's two states, taken and let go; the certificate's text last, at
 * the least it can be, its entries' lines among it. A run the process
 * cannot have is refused `memory` then, with nothing made.
 *
 * The trial takes nothing from the C library's heap. Every piece comes
 * from the operating system, rounded down to whole pages (a piece under
 * a page is not tried), and so does the trial's own list of what it
 * holds; all of it is given back before the outputs are made. So the
 * runs allocate from the heap they would have had without the trial,
 * and the trial costs them nothing - which the gate holds to the page on
 * Linux (verifier-C7, 2026-09-29: at eb2d1ae the pieces under 64 KiB
 * came from calloc, left the heap up to 40 KiB bigger, and 99f1b43 wrote
 * certificates under limits eb2d1ae refused).
 *
 * The trial holds no hash's buffer and no library, device or program -
 * at each run, less than 99f1b43's tool held there. But it holds every
 * run's initial state throughout, as 99f1b43's runs did, where the runs
 * now let each go once it is copied: so the trial can need more than the
 * runs themselves (verifier-C7's `up` shape, about 10 MB), and refuse a
 * certificate they alone could have written, which 99f1b43 could not
 * write either.
 *
 * What the trial cannot promise: a hash's buffer and a boundary file's
 * path; a piece under a page; the library's own memory, which fails as
 * `program-image` or `device`; and memory the machine gives others
 * between the trial and the run. A piece of the tool's that cannot be
 * had after the trial had it is still refused `memory`, part way. Where
 * the operating system has no anonymous mapping, the trial is its size
 * checks alone. */

typedef struct {
    void *p;
    size_t n;
} trial;

#if defined(_WIN32) || defined(SEG_MAP_ANON)
#  define TRIAL_OS 1

static size_t page_size(void)
{
#  if defined(_WIN32)
    SYSTEM_INFO si;
    GetSystemInfo(&si);
    return si.dwPageSize ? (size_t)si.dwPageSize : 4096;
#  else
    long p = sysconf(_SC_PAGESIZE);
    return p > 0 ? (size_t)p : 4096;
#  endif
}

/* `n` bytes, a whole number of pages, from the operating system, or
 * NULL: never from the C library's heap. */
static void *os_take(size_t n)
{
#  if defined(_WIN32)
    return VirtualAlloc(NULL, n, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
#  else
    void *p = mmap(NULL, n, PROT_READ | PROT_WRITE,
                   MAP_PRIVATE | SEG_MAP_ANON, -1, 0);
    return p == MAP_FAILED ? NULL : p;
#  endif
}

static void os_give(void *p, size_t n)
{
#  if defined(_WIN32)
    (void)n;
    VirtualFree(p, 0, MEM_RELEASE);
#  else
    munmap(p, n);
#  endif
}

/* `bytes` tried: rounded down to whole pages and taken from the operating
 * system - the runs' own allocation of it, the C library's with its
 * header, can only be larger - or, under a page, not tried at all. 0
 * only if the operating system refuses it. */
static int trial_take(trial *t, size_t bytes)
{
    size_t pg = page_size();
    t->p = NULL;
    t->n = bytes / pg * pg;
    if (t->n == 0)
        return 1;
    t->p = os_take(t->n);
    return t->p != NULL;
}

static void trial_give(trial *t)
{
    if (t->p)
        os_give(t->p, t->n);
    t->p = NULL;
    t->n = 0;
}

/* One piece of the trial: `n` x `sz` bytes for `what`, of run `r` (or of
 * the certificate, for r = -1), or the refusal. */
static void trial_or_refuse(trial *t, size_t n, size_t sz, long r,
                            const char *what)
{
    size_t bytes;
    char who[32] = "";
    if (r >= 0)
        snprintf(who, sizeof who, "run %ld: ", r);
    if (!mul_ok(n, sz, &bytes) || !trial_take(t, bytes))
        refuse("memory", "%s%llu x %llu bytes for %s could not be had; what "
               "the runs need is tried, in the order they need it, before "
               "anything is made, so nothing was", who,
               (unsigned long long)n, (unsigned long long)sz, what);
}

/* One of accuracy entry j's two states, taken and let go as the entry
 * takes it when it reads the state back. */
static void trial_entry_or_refuse(trial *t, size_t bytes, size_t j)
{
    if (!trial_take(t, bytes))
        refuse("memory", "entry %lu: %llu bytes for a state read back could "
               "not be had; what the runs and the entries need is tried, in "
               "the order they need it, before anything is made, so nothing "
               "was", (unsigned long)j, (unsigned long long)bytes);
}
#else
#  define TRIAL_OS 0
#endif

static void try_runs(const run_spec *runs, size_t n_runs,
                     const entry_spec *entries, size_t n_entries,
                     const char *states, int keyed)
{
    size_t r, text_max = HEAD_TEXT, text_min = 0, cap = 4096;
    size_t path = strlen(states) + PATH_TAIL;
    size_t lead = keyed ? 64 : 0;      /* the HMAC's key block */

    /* every size, against what the process can address */
    for (r = 0; r < n_runs; r++) {
        const run_spec *R = &runs[r];
        size_t S = (size_t)R->segments, h, a, tmax, tmin, b;
        size_t params = R->n_param_s + (SCRATCH_DEPTH ? 1u : 0u);
        int ok = (uint64_t)S == R->segments && S < (size_t)-1 &&
                 mul_ok(S + 1, sizeof *R->hash, &h) &&
                 mul_ok(S, 2 * sizeof(uint32_t), &a) && add_ok(&h, a) &&
                 mul_ok(S, SEGMENT_TEXT, &tmax) && add_ok(&tmax, RUN_TEXT) &&
                 add_ok(&tmax, R->n_hslots * HSLOT_TEXT) &&
                 add_ok(&tmax, params * PARAM_TEXT) &&
                 add_ok(&text_max, tmax) &&
                 mul_ok(S, SEGMENT_TEXT_MIN, &tmin) &&
                 add_ok(&text_min, tmin);
        if (!ok)
            refuse("memory", "run %lu: %llu segments need more memory than "
                   "this process can address - the boundary hashes, flag "
                   "words and STATUS, or the certificate's text", (unsigned
                   long)r, (unsigned long long)R->segments);
        b = R->state_bytes > R->lanes * R->esz ? R->state_bytes
                                               : R->lanes * R->esz;
        if (!add_ok(&b, lead + TAG_STREAM_LEN) || !add_ok(&b, path))
            refuse("memory", "run %lu: its state is past what this process "
                   "can address", (unsigned long)r);
    }
    /* each accuracy entry's lines; the states it reads are the runs' own,
     * each counted above */
    for (r = 0; r < n_entries; r++)
        if (!add_ok(&text_max, entries[r].text_most) ||
            !add_ok(&text_min, entries[r].text_least))
            refuse("memory", "entry %lu: the certificate's text is more "
                   "than this process can address", (unsigned long)r);
    while (cap - 1 < text_min) {
        if (cap > (size_t)-1 / 2)
            refuse("memory", "the certificate's text, at least %llu bytes, "
                   "is more than this process can address",
                   (unsigned long long)text_min);
        cap *= 2;
    }
    if (PLANT_NO_TRIAL)
        return;

#if TRIAL_OS
    {
        /* tried in the order the runs need it: each run's hashes, flag
         * words and STATUS kept, as the certificate keeps them; its two
         * states and its streams taken and let go, as the run lets them
         * go. The list of what is kept is the operating system's too. */
        size_t pg = page_size(), list, i;
        trial *kept, now[3];
        if (!mul_ok(3 * sizeof *kept, n_runs, &list) ||
            !add_ok(&list, pg - 1))
            refuse("memory", "the trial's list of %lu runs is more than "
                   "this process can address", (unsigned long)n_runs);
        list = list / pg * pg;
        kept = (trial *)os_take(list);
        if (!kept)
            refuse("memory", "%llu bytes for the trial's own list could not "
                   "be had; nothing was made", (unsigned long long)list);
        for (r = 0; r < n_runs; r++) {
            const run_spec *R = &runs[r];
            size_t S = (size_t)R->segments;
            long ri = (long)r;
            trial_or_refuse(&kept[3 * r], S + 1, sizeof *R->hash, ri,
                            "the boundary hashes");
            trial_or_refuse(&kept[3 * r + 1], S, sizeof(uint32_t), ri,
                            "the flag words");
            trial_or_refuse(&kept[3 * r + 2], S, sizeof(uint32_t), ri,
                            "STATUS");
            trial_or_refuse(&now[0], R->state_bytes, 1, ri, "a state");
            trial_or_refuse(&now[1], R->state_bytes, 1, ri, "a state");
            trial_or_refuse(&now[2], R->lanes, R->esz, ri, "the streams");
            for (i = 0; i < 3; i++)
                trial_give(&now[i]);
        }
        /* each accuracy entry's two states, read back once the runs have
         * run, beside every run's hashes: taken and let go in the entries'
         * order, as each entry lets its pair go before the next reads */
        for (r = 0; r < n_entries; r++) {
            trial_entry_or_refuse(&now[0], entries[r].need_bytes[0], r);
            trial_entry_or_refuse(&now[1], entries[r].need_bytes[1], r);
            trial_give(&now[0]);
            trial_give(&now[1]);
        }
        /* the certificate's text, beside every run's hashes, at the least
         * it can be and grown as put() grows it: 4096 doubled, the old
         * buffer and the new held together at the last doubling */
        now[0].p = NULL;
        now[0].n = 0;
        if (cap > 4096)
            trial_or_refuse(&now[0], cap / 2, 1, -1,
                            "the certificate's text");
        trial_or_refuse(&now[1], cap, 1, -1, "the certificate's text");
        trial_give(&now[0]);
        trial_give(&now[1]);
        for (i = 0; i < 3 * n_runs; i++)
            trial_give(&kept[i]);
        os_give(kept, list);
    }
#endif
}

/* A run's own allocation, as the trial took it: one that fails now is
 * refused by the same name, part way. */
static void *run_take(size_t n, size_t sz, size_t r, const char *what)
{
    void *p = (sz && n > (size_t)-1 / sz) ? NULL
            : calloc(n ? n : 1, sz ? sz : 1);
    if (!p)
        refuse("memory", "run %lu: %llu x %llu bytes for %s could not be "
               "had, although they could when tried before anything was "
               "made", (unsigned long)r, (unsigned long long)n,
               (unsigned long long)sz, what);
    return p;
}

/* ---- accuracy entries -------------------------------------------------------
 *
 * Each --entry is one entry of the certificate's accuracy block, in the
 * order given, after the runs (docs/CERTIFICATES.md, "Accuracy entries";
 * the plan's step 5). Its value is computed by cert_exact.h, cft-audit's
 * own arithmetic, from the states the runs wrote to DIR, read back once
 * every run has run - one entry's two states at a time - each held to the
 * hash the certificate carries at its boundary. Every refusal takes the
 * golden writer's name for the same defect (cert.derive, make_value and
 * encode's reader).
 *
 * The bytes of an entry's lines, at least (for the trial: each line's
 * fixed words, one digit a number, and an exact 0/1) and at most (for the
 * count against what the process can address: a value's line is under
 * 4 KiB - an exact value is two parts of at most 256 hex digits, and an
 * element's exact decimal, for a value within the width rule, under 1,400
 * characters - and a term's under 1 KiB). */
#define ENTRY_TEXT_LEAST     64
#define ENTRY_TEXT_MOST      8192
#define QUANTITY_TEXT_LEAST  19
#define TERM_TEXT_LEAST      9
#define TERM_TEXT_MOST       1024

#if CX_EXACT
/* An entry's run, lane or slot: a decimal in its one spelling, of any
 * length, saturated at 2^64 - 1. Past 2^63 - 1 it is no index a
 * certificate can hold, and names no run, lane or slot, so the check
 * against the runs refuses it (accuracy-run, -scope, -slot), as
 * cert.derive does before encode's reader could call it malformed. */
static int dec_sat(const char *s, uint64_t *out)
{
    size_t i, n = strlen(s);
    uint64_t v = 0;
    if (n == 0 || (s[0] == '0' && n > 1))
        return 0;
    for (i = 0; i < n; i++) {
        unsigned d;
        if (s[i] < '0' || s[i] > '9')
            return 0;
        d = (unsigned)(s[i] - '0');
        v = v > (UINT64_MAX - d) / 10u ? UINT64_MAX : v * 10u + d;
    }
    *out = v;
    return 1;
}

/* A negative run, lane or slot: a minus and a nonzero decimal in its one
 * spelling (-0 and -01 spell no index, and stay malformed). It names no
 * run, lane or slot, and cert.derive bounds each from below as from
 * above (`not 0 <= i < n`; verifier-W1 and W1b, 2026-09-30), so it is
 * held to the runs as an index past them is, and refused accuracy-run,
 * -scope or -slot there. Its caller stores UINT64_MAX, which names none,
 * and gives the index as given in the sentence. */
static int dec_neg(const char *s)
{
    uint64_t v;
    return s[0] == '-' && dec_sat(s + 1, &v) && v != 0;
}

/* A run as an entry reads it (cert_exact.h's cx_run). */
static void run_shape_of(const run_spec *R, cx_run *s)
{
    s->kind = R->kind;
    s->fmt = (int)R->H.prec;
    s->lanes = R->lanes;
    s->S = R->segments;
    s->nslots = R->H.n_in;
}

/* A status of cert_exact.h's for entry j, refused by the page's name; a
 * library call that failed, `device`; the rest, an internal error. */
static void refuse_cx(int st, size_t j, const char *why)
{
    const char *name = cx_name(st);
    if (st == CX_OK)
        return;
    if (st == CX_LIBRARY)
        refuse_st("device", "an accuracy value's rounding "
                  "(cft_from_hex_char)", CFT_ERR_INTERNAL);
    if (!name)
        internal(why);
    refuse(name, "entry %lu: %s", (unsigned long)j, why);
}

/* A --term: the coefficient in its one spelling (the reader's order:
 * malformed, then width by its digits), then its factors, s<slot> each,
 * at most eight, in non-decreasing order. A slot is any decimal index:
 * one past the state is accuracy-slot, as cert.derive refuses it, and so
 * is a negative one (dec_neg), stored as UINT64_MAX; the order is the
 * slots' as the golden writer is handed them, -1 before 0. */
static void parse_term(const char *s, term_t *T, size_t j, size_t t)
{
    size_t n = strlen(s);
    char *buf = (char *)xcalloc(n + 1, 1), *p, *comma, why[256];
    int st, neg[MAX_FACTORS] = { 0 };
    uint64_t v, mag[MAX_FACTORS] = { 0 };
    memcpy(buf, s, n);
    p = buf;
    comma = strchr(p, ',');
    if (comma)
        *comma = 0;
    st = cx_rat_parse(p, &T->coef, "a coefficient", why, sizeof why);
    if (st == CX_MALFORMED)
        refuse("malformed", "entry %lu term %lu: %s", (unsigned long)j,
               (unsigned long)t, why);
    if (st == CX_WIDTH)
        refuse("width", "entry %lu term %lu: %s", (unsigned long)j,
               (unsigned long)t, why);
    if (st)
        internal(why);
    T->n = 0;
    while (comma) {
        p = comma + 1;
        comma = strchr(p, ',');
        if (comma)
            *comma = 0;
        if (p[0] == 's' && dec_neg(p + 1)) {
            dec_sat(p + 2, &v);
            if (T->n < MAX_FACTORS) {
                T->slot[T->n] = UINT64_MAX;     /* names no slot */
                neg[T->n] = 1;
                mag[T->n] = v;
            }
        } else if (p[0] != 's' || !dec_sat(p + 1, &v)) {
            refuse("malformed", "entry %lu term %lu: factor '%.40s' is not "
                   "s<slot>, the slot a decimal integer in its one spelling",
                   (unsigned long)j, (unsigned long)t, p);
        } else if (T->n < MAX_FACTORS) {
            T->slot[T->n] = v;
            neg[T->n] = 0;
            mag[T->n] = v;
        }
        T->n++;
    }
    if (T->n > MAX_FACTORS)
        refuse("malformed", "entry %lu term %lu: a term has at most %d "
               "factors, and this one has %u", (unsigned long)j,
               (unsigned long)t, MAX_FACTORS, T->n);
    /* the slots as integers: -5 before -1, -1 before 0 */
    for (n = 1; n < T->n; n++)
        if (neg[n] != neg[n - 1] ? neg[n]
                                 : (neg[n] ? mag[n] > mag[n - 1]
                                           : mag[n] < mag[n - 1]))
            refuse("malformed", "entry %lu term %lu: a term's factors are in "
                   "non-decreasing slot order", (unsigned long)j,
                   (unsigned long)t);
    free(buf);
}

/* A --value: exact, rounded:FMT:RND or enclosed:FMT, each word the
 * page's (make_value's malformed); a format this build's library does
 * not carry is refused by the build's name at its word, as cft-audit's
 * reader does, before the rest (its decimals and rounding are the
 * library's). */
static void parse_value(const char *s, value_t *v, size_t j)
{
    size_t n = strlen(s), k, parts = 1;
    char *buf = (char *)xcalloc(n + 1, 1), *part[3] = { NULL, NULL, NULL };
    int f = -1, d = -1;
    memcpy(buf, s, n);
    part[0] = buf;
    for (k = 0; k < n; k++)
        if (buf[k] == ':') {
            buf[k] = 0;
            if (parts < 3)
                part[parts] = buf + k + 1;
            parts++;
        }
    if (!strcmp(part[0], "exact"))
        v->form = V_EXACT;
    else if (!strcmp(part[0], "rounded"))
        v->form = V_ROUNDED;
    else if (!strcmp(part[0], "enclosed"))
        v->form = V_ENCLOSED;
    else
        refuse("malformed", "entry %lu: --value '%.60s': a value's form is "
               "exact, rounded or enclosed", (unsigned long)j, s);
    if (parts != (v->form == V_EXACT ? 1u : v->form == V_ROUNDED ? 3u : 2u))
        refuse("malformed", "entry %lu: --value '%.60s' is not exact, "
               "rounded:FMT:RND or enclosed:FMT", (unsigned long)j, s);
    if (v->form != V_EXACT) {
        for (k = 0; k < 4; k++)
            if (!strcmp(part[1], FMT[k].name))
                f = (int)k;
        if (f < 0)
            refuse("malformed", "entry %lu: %s %s value's format is one of "
                   "fp32, fp64, fp128, fp256, not '%.40s'", (unsigned long)j,
                   v->form == V_ENCLOSED ? "an" : "a", part[0], part[1]);
        /* the format by its word as given, which the loop above matched to
         * FMT[f].name: never FMT[f] here, where f is past the build's
         * ceiling (gcc 13 flags that subscript in the default build, where
         * the branch cannot be taken; parcel S3, 2026-09-30) */
        if (f > CFT_MAX_FORMAT)
            refuse("build-format", "entry %lu: its value is stated in %s, and "
                   "this build's library carries formats up to %s "
                   "(CFT_MAX_FORMAT=%d); its decimals and its rounding are the "
                   "library's, so it refuses rather than write it differently",
                   (unsigned long)j, part[1], FMT[CFT_MAX_FORMAT].name,
                   CFT_MAX_FORMAT);
        v->fmt = f;
    }
    if (v->form == V_ROUNDED) {
        for (k = 0; k < 5; k++)
            if (!strcmp(part[2], RND_NAME[k]))
                d = (int)k;
        if (d < 0)
            refuse("malformed", "entry %lu: a rounded value's direction is "
                   "one of rne, rtz, rdn, rup, rmm, not '%.40s'",
                   (unsigned long)j, part[2]);
        v->rnd = d;
    }
    free(buf);
}

/* cx_entry_check refuses the first slot past the state, terms in order
 * and each term's factors in order, as cert.derive does; where that slot
 * was given negative (stored as UINT64_MAX), the sentence names it as
 * given, as cert.derive's does, from the --term it came in. */
static void slot_as_given(const entry_spec *X, const cx_run *u, char *why,
                          size_t cap)
{
    const entry_t *E = &X->E;
    unsigned t, k, i;
    for (t = 0; t < E->n_terms; t++)
        for (k = 0; k < E->terms[t].n && k < MAX_FACTORS; k++) {
            const char *f = X->term_s[t];
            size_t len;
            if (E->terms[t].slot[k] < u->nslots)
                continue;
            for (i = 0; i <= k && f; i++) {     /* factor k: after comma k+1 */
                f = strchr(f, ',');
                if (f)
                    f++;
            }
            if (f && f[0] == 's' && f[1] == '-') {
                len = strcspn(f + 1, ",");
                snprintf(why, cap, "a term names slot %.*s%s; run %llu's "
                         "state has %lu slots a lane",
                         (int)(len > 40 ? 40 : len), f + 1,
                         len > 40 ? "..." : "",
                         (unsigned long long)E->uses,
                         (unsigned long)u->nslots);
            }
            return;
        }
}

/* Entry j, checked before anything is made: its words and spellings as
 * the reader holds them, then against the runs in cert.derive's order
 * (the run it uses, that run's kind and shape, the lane, the slots). And
 * what it will need: the bytes of the two states it reads, and of its
 * lines. */
static void check_entry(entry_spec *X, size_t j, const run_spec *runs,
                        size_t n_runs)
{
    entry_t *E = &X->E;
    char why[512];
    uint64_t v, need[2][2];
    cx_run m, u;
    size_t t;
    int k, st, negative, neg_lane;

    for (k = 0; k < 3 && strcmp(X->method_s, METHOD_NAME[k]) != 0; k++)
        ;
    if (k == 3)
        refuse("malformed", "entry %lu: method '%.40s' is not drift, "
               "step-halving or wider", (unsigned long)j, X->method_s);
    E->method = k;
    if (!X->uses_s || !X->scope_s || !X->value_s)
        refuse("usage", "entry %lu (%s) needs --uses, --scope and --value",
               (unsigned long)j, METHOD_NAME[k]);
    /* The run and the lane: a decimal in its one spelling, or a negative
     * one (dec_neg), which names none. The golden writer handed one
     * refuses it at cert.derive's check of that index (accuracy-run,
     * accuracy-scope), before encode's reader could call it malformed: so
     * it is held to the runs below, as an index past them is (verifier-W1
     * and W1b, 2026-09-30: both were refused malformed). -0 and -01 spell
     * no index: malformed. */
    negative = dec_neg(X->uses_s);
    if (!negative && !dec_sat(X->uses_s, &v))
        refuse("malformed", "entry %lu: --uses '%.40s' is not a run index, a "
               "decimal integer in its one spelling", (unsigned long)j,
               X->uses_s);
    E->uses = negative ? UINT64_MAX : v;
    neg_lane = !strncmp(X->scope_s, "lane:", 5) && dec_neg(X->scope_s + 5);
    if (!strcmp(X->scope_s, "max-lanes")) {
        E->has_lane = 0;
    } else if (neg_lane || (!strncmp(X->scope_s, "lane:", 5) &&
                            dec_sat(X->scope_s + 5, &v))) {
        E->has_lane = 1;
        E->lane = neg_lane ? UINT64_MAX : v;
    } else {
        refuse("malformed", "entry %lu: --scope '%.40s' is max-lanes, or "
               "lane:I with I a lane index, a decimal integer in its one "
               "spelling", (unsigned long)j, X->scope_s);
    }
    if (E->method == M_DRIFT) {
        if (!X->label_s)
            refuse("malformed", "entry %lu: a drift states its quantity: "
                   "--quantity LABEL and its terms, --term", (unsigned long)j);
        if (!name_ok(X->label_s, strlen(X->label_s)))
            refuse("malformed", "entry %lu: label '%.80s' is not a lowercase "
                   "letter, then lowercase letters, digits and '-', at most "
                   "%d", (unsigned long)j, X->label_s, MAX_NAME);
        if (X->n_term_s < 1 || X->n_term_s > MAX_TERMS)
            refuse("malformed", "entry %lu: a drift's quantity has 1 to %d "
                   "terms (--term), and this one has %lu", (unsigned long)j,
                   MAX_TERMS, (unsigned long)X->n_term_s);
        E->terms = (term_t *)xcalloc(X->n_term_s, sizeof *E->terms);
        E->n_terms = (unsigned)X->n_term_s;
        for (t = 0; t < X->n_term_s; t++)
            parse_term(X->term_s[t], &E->terms[t], j, t);
    } else if (X->label_s || X->n_term_s) {
        refuse("malformed", "entry %lu: a %s estimate states no quantity; "
               "--quantity and --term are a drift's", (unsigned long)j,
               METHOD_NAME[E->method]);
    }
    parse_value(X->value_s, &E->value, j);

    memset(&u, 0, sizeof u);
    run_shape_of(&runs[0], &m);
    if (E->uses < n_runs)
        run_shape_of(&runs[E->uses], &u);
    st = cx_entry_check(E, n_runs, &m, E->uses < n_runs ? &u : NULL, why,
                        sizeof why);
    /* a negative index as given, not as stored */
    if (st == CX_RUN && negative)
        snprintf(why, sizeof why, "entry uses run %.40s%s, and the "
                 "certificate has %llu", X->uses_s,
                 strlen(X->uses_s) > 40 ? "..." : "",
                 (unsigned long long)n_runs);
    if (st == CX_SCOPE && neg_lane)
        snprintf(why, sizeof why, "lane %.40s%s of a run of %llu lanes",
                 X->scope_s + 5, strlen(X->scope_s + 5) > 40 ? "..." : "",
                 (unsigned long long)u.lanes);
    if (st == CX_SLOT)
        slot_as_given(X, &u, why, sizeof why);
    refuse_cx(st, j, why);

    cx_entry_needs(E, &m, &u, need);
    X->need_bytes[0] = runs[need[0][0]].state_bytes;
    X->need_bytes[1] = runs[need[1][0]].state_bytes;
    X->text_least = ENTRY_TEXT_LEAST;
    X->text_most = ENTRY_TEXT_MOST;
    if (E->method == M_DRIFT) {
        X->text_least += QUANTITY_TEXT_LEAST + E->n_terms * TERM_TEXT_LEAST;
        X->text_most += E->n_terms * (size_t)TERM_TEXT_MOST;
    }
}

#if defined(CFT_SEGRUN_PLANT_STATE_CHANGED)
/* A PLANT BUILD, compiled only by the gate (host/tests/segrun_check.py),
 * never by the Makefile: the first state read back has its first bit
 * flipped, as if another process had changed the file, so that the gate
 * holds the refusal that follows (`output`). The shipped tool has no such
 * path (the lead's condition, 2026-09-30). */
static int PLANTED_STATE = 0;
#endif

/* Run r's boundary-b state, read back from the file this run wrote: into
 * a buffer of exactly its size, and held to the hash the certificate
 * carries at that boundary, which the run computed as it wrote the file.
 * A file that is not that state, or cannot be read, is refused `output`:
 * another process changed DIR. */
static uint8_t *read_back(const run_spec *runs, const uint8_t *salt,
                          uint64_t r, uint64_t b, size_t j)
{
    const run_spec *R = &runs[r];
    size_t n = R->state_bytes, got, cap = strlen(STATES_DIR) + PATH_TAIL;
    char *path = (char *)xcalloc(cap, 1);
    uint8_t *buf = (uint8_t *)run_take(n, 1, (size_t)r, "a state read back");
    char hex[65];
    FILE *f;
    int more;
    snprintf(path, cap, "%s/run-%lu-boundary-%llu.bin", STATES_DIR,
             (unsigned long)r, (unsigned long long)b);
    f = fopen(path, "rb");
    if (!f)
        refuse("output", "entry %lu: %s cannot be read back (%s)",
               (unsigned long)j, path, strerror(errno));
    got = fread(buf, 1, n, f);
    more = fgetc(f);
    if (ferror(f)) {
        fclose(f);
        refuse("output", "entry %lu: %s cannot be read back", (unsigned long)j,
               path);
    }
    fclose(f);
    if (got != n || more != EOF)
        refuse("output", "entry %lu: %s is not the %lu bytes this run wrote "
               "there: another process changed %s", (unsigned long)j, path,
               (unsigned long)n, STATES_DIR);
#if defined(CFT_SEGRUN_PLANT_STATE_CHANGED)
    if (!PLANTED_STATE) {
        PLANTED_STATE = 1;
        buf[0] ^= 1u;
        fprintf(stderr, "cft-segrun: CFT_SEGRUN_PLANT_STATE_CHANGED - a plant "
                "build: the first state read back, %s, has its first bit "
                "flipped\n", path);
    }
#endif
    state_hash(salt, buf, n, hex);
    if (strcmp(hex, R->hash[b]) != 0)
        refuse("output", "entry %lu: %s is not the state this run wrote there "
               "- its hash is not the one the certificate carries at run %lu "
               "boundary %llu: another process changed %s", (unsigned long)j,
               path, (unsigned long)r, (unsigned long long)b, STATES_DIR);
    free(path);
    return buf;
}

/* Entry j's value, once every run has run: its two states read back, in
 * cert.derive's order, and "The functions, exactly" on them; then both
 * let go, before the next entry reads its own. */
static void derive_entry(entry_spec *X, size_t j, const run_spec *runs,
                         const uint8_t *salt)
{
    cx_run m, u;
    uint64_t need[2][2];
    uint8_t *s[2];
    char why[512];
    int st;
    run_shape_of(&runs[0], &m);
    run_shape_of(&runs[X->E.uses], &u);
    cx_entry_needs(&X->E, &m, &u, need);
    s[0] = read_back(runs, salt, need[0][0], need[0][1], j);
    s[1] = read_back(runs, salt, need[1][0], need[1][1], j);
    st = cx_entry_value(&X->E, &m, &u, s[0], s[1], &X->q, why, sizeof why);
    free(s[0]);
    free(s[1]);
    refuse_cx(st, j, why);
}

/* Entry j's value in its form (cert.make_value, and encode's width at an
 * enclosure's finite end), after every entry's value is derived: the
 * golden writer's order. */
static void make_value(entry_spec *X, size_t j, cft_device *arith)
{
    char why[512];
    value_t *v = &X->E.value;
    refuse_cx(cx_value_make(arith, &X->q, v->form, v->fmt, v->rnd, v, why,
                            sizeof why), j, why);
}

/* An element as the certificate spells one: its bits in width/4 hex
 * digits, a space, and its exact decimal (cft_to_decimal_char at 0
 * digits, as cft-audit holds it). */
static void put_element(text *t, int f, const uint8_t *le, cft_device *arith)
{
    size_t i, len = 0;
    uint32_t fl = 0;
    char *dec;
    cft_status st;
    for (i = ESZ(f); i-- > 0;)
        put(t, "%02x", le[i]);
    st = cft_to_decimal_char(arith, (cft_format)f, CFT_RNE, le, 0, NULL, 0,
                             &len, &fl);
    if (st != CFT_ERR_INVALID_ARGUMENT || len == 0)
        refuse_st("device", "cft_to_decimal_char, sizing an accuracy value's "
                  "decimal", st);
    dec = (char *)xcalloc(len, 1);
    st = cft_to_decimal_char(arith, (cft_format)f, CFT_RNE, le, 0, dec, len,
                             &len, &fl);
    if (st != CFT_OK)
        refuse_st("device", "cft_to_decimal_char, an accuracy value's decimal",
                  st);
    put(t, " %s", dec);
    free(dec);
}
#endif /* CX_EXACT */

/* The accuracy block, in the page's order and spellings (cert._body_lines):
 * `accuracy <A>`, then each entry's lines. With no --entry it is
 * `accuracy 0`, byte for byte what the tool wrote before step 5. One
 * function, beside the run blocks' code, so that another writer of the
 * same certificates can take it whole. */
static void put_accuracy(text *t, const entry_spec *entries, size_t n,
                         cft_device *arith)
{
    put(t, "accuracy %llu\n", (unsigned long long)n);
#if CX_EXACT
    {
        size_t j;
        for (j = 0; j < n; j++) {
            const entry_t *E = &entries[j].E;
            const value_t *v = &E->value;
            char buf[CX_RAT_TEXT];
            unsigned k, s;
            put(t, "entry %llu %s\n", (unsigned long long)j,
                METHOD_NAME[E->method]);
            put(t, "kind %s\n", KINDS[METHOD_KIND[E->method]]);
            put(t, "uses %llu\n", (unsigned long long)E->uses);
            if (E->has_lane)
                put(t, "scope lane %llu\n", (unsigned long long)E->lane);
            else
                put(t, "scope max-lanes\n");
            if (E->method == M_DRIFT) {
                put(t, "quantity %s terms %u\n", entries[j].label_s,
                    E->n_terms);
                for (k = 0; k < E->n_terms; k++) {
                    rat_text(&E->terms[k].coef, buf);
                    put(t, "term %s", buf);
                    for (s = 0; s < E->terms[k].n; s++)
                        put(t, " s%llu",
                            (unsigned long long)E->terms[k].slot[s]);
                    put(t, "\n");
                }
            }
            if (v->form == V_EXACT) {
                rat_text(&v->exact, buf);
                put(t, "value exact %s\n", buf);
            } else if (v->form == V_ROUNDED) {
                put(t, "value rounded %s %s ", FMT[v->fmt].name,
                    RND_NAME[v->rnd]);
                put_element(t, v->fmt, v->bits, arith);
                put(t, "\n");
            } else {
                put(t, "value enclosed %s ", FMT[v->fmt].name);
                put_element(t, v->fmt, v->lo, arith);
                put(t, " ");
                put_element(t, v->fmt, v->hi, arith);
                put(t, "\n");
            }
        }
    }
#else
    (void)entries;
    (void)arith;
#endif
}

/* ---- usage --------------------------------------------------------------- */

static void usage_text(FILE *f)
{
    fputs(
"cft-segrun - run a program as consecutive segments and write the certificate\n"
"(docs/CERTIFICATES.md, version 1; \"The segment runner\" is the manual)\n"
"\n"
"  cft-segrun --out CERT --states DIR (--salt SALT | --open)\n"
"             [--device sw|<xclbin>|cft://host:port | --scratch-depth N]\n"
"             --run main --image IMG [--bank BANK] --init INIT\n"
"                        --segments S --steps K [--param NAME=N ...]\n"
"             [--run half-step --h-slots I,J,... --image IMG ...]\n"
"             [--run wider --image IMG ...]\n"
"             [--entry drift|step-halving|wider --uses R\n"
"                      --scope max-lanes|lane:I\n"
"                      [--quantity LABEL --term C[,sI...] ...]\n"
"                      --value exact|rounded:FMT:RND|enclosed:FMT] ...\n"
"  cft-segrun --hash state|stream-a|stream-b|stream-c FILE\n"
"             (--salt SALT | --open)\n"
"  cft-segrun --hash commitment --salt SALT\n"
"  cft-segrun --build-id\n"
"\n"
"  --out CERT      the certificate, written once every segment has run\n"
"  --states DIR    a NEW directory: DIR/run-<r>-boundary-<b>.bin, each the\n"
"                  lane-major scratch block at boundary b (0 = --init)\n"
"  --salt SALT     keyed: SALT is exactly 32 random bytes the owner keeps\n"
"  --open          open: plain SHA-256, no salt\n"
"  --device        the software backend (sw, the default), an .xclbin, or\n"
"                  a cft-serve at cft://host:port\n"
"  --scratch-depth N  the software backend at N scratch slots a lane (a\n"
"                  power of two, 1 to 32768), as a tile of that depth; every\n"
"                  run block then says `parameter scratch-depth N`\n"
"  --run KIND      main first; then half-step or wider auxiliary runs\n"
"  --image IMG     the program image (.cftp), a segment: SCRATCH_IO, in = out\n"
"  --bank BANK     a BANK_EXT image's constants, n_consts values, raw\n"
"  --init INIT     the initial state: lanes x n_scratch_in elements, raw,\n"
"                  format-width, little-endian, lane-major\n"
"  --segments S    how many consecutive segments; each enters with the last\n"
"                  one's scratch-out\n"
"  --steps K       steps a segment: stated, not checked\n"
"  --param NAME=N  a non-negative integer parameter: stated, not checked;\n"
"                  names in increasing byte order\n"
"  --h-slots LIST  a half-step run's bank slots that carry the step\n"
"  --entry METHOD  an accuracy entry, after the runs: drift (a measurement),\n"
"                  step-halving or wider (estimates against run 0)\n"
"  --uses R        the run the entry is a function of\n"
"  --scope S       max-lanes, or lane:I\n"
"  --quantity L    a drift's quantity, named L, with its terms in order:\n"
"  --term C,sI...  the coefficient C (hex N/D in lowest terms, 1/1 for one)\n"
"                  and its factors, the state's slots, non-decreasing\n"
"  --value FORM    exact, rounded:FMT:RND (rne rtz rdn rup rmm) or\n"
"                  enclosed:FMT; each value is computed from the states the\n"
"                  runs wrote to DIR, read back once they have run\n"
"  --hash KIND     print one of the page's hashes of FILE, and exit\n"
"  --build-id      print cft_build_id(), which the build-id line carries\n"
"\n"
"The streams a, b and c are +0. Refusals are named on stderr as\n"
"\"cft-segrun: refused <name>: <why>\"; the exit code is the name's.\n", f);
}

static const char *need(int argc, char **argv, int *i)
{
    if (*i + 1 >= argc)
        refuse("usage", "%s needs a value", argv[*i]);
    return argv[++(*i)];
}

static void once(const char **slot, const char *opt, const char *v)
{
    if (*slot)
        refuse("usage", "%s is given twice", opt);
    *slot = v;
}

/* ---- --hash ------------------------------------------------------------ */

static int do_hash(const char *kind, const char *file, const uint8_t *salt)
{
    char hex[65];
    if (!strcmp(kind, "commitment")) {
        if (file)
            refuse("usage", "--hash commitment takes no file");
        if (!salt)
            refuse("usage", "--hash commitment needs --salt");
        salt_commitment(salt, hex);
    } else {
        uint8_t *bytes;
        size_t n = 0;
        int which = -1;
        if (!strcmp(kind, "state"))
            which = 3;
        else if (!strcmp(kind, "stream-a"))
            which = 0;
        else if (!strcmp(kind, "stream-b"))
            which = 1;
        else if (!strcmp(kind, "stream-c"))
            which = 2;
        else
            refuse("usage", "--hash %s: the kinds are state, stream-a, "
                   "stream-b, stream-c and commitment", kind);
        if (!file)
            refuse("usage", "--hash %s needs a file", kind);
        bytes = read_named("the file", file, &n);
        if (which == 3)
            state_hash(salt, bytes, n, hex);
        else
            tagged_hash(salt, stream_tag(which), TAG_STREAM_LEN, bytes, n,
                        hex);
        free(bytes);
    }
    printf("%s\n", hex);
    return 0;
}

/* ---- main -------------------------------------------------------------- */

int main(int argc, char **argv)
{
    const char *out_path = NULL, *states_path = NULL, *salt_path = NULL;
    const char *device = NULL, *hash_kind = NULL, *hash_file = NULL;
    const char *depth_s = NULL;
    const char *plant = getenv("CFT_SEGRUN_PLANT");
    int open_mode = 0, want_build_id = 0, i;
    run_spec *runs = NULL;
    size_t n_runs = 0, r;
    entry_spec *entries = NULL;
    size_t n_entries = 0, j;
    uint8_t *salt = NULL;
    size_t salt_bytes = 0;
    cft_device *dev = NULL, *arith = NULL;
    cft_caps caps;
    cft_status st;
    identity id;
    text body;
    char commitment[65], hex[65];
    uint8_t digest[32];

    memset(&body, 0, sizeof body);
    if (plant && *plant) {
        if (!strcmp(plant, "flags-unreadable"))
            PLANT_UNREADABLE = 1;
        else if (!strcmp(plant, "flags-unwritten"))
            PLANT_UNWRITTEN = 1;
        else if (!strcmp(plant, "flags-wide"))
            PLANT_WIDE = 1;
        else if (!strcmp(plant, "trial-skipped"))
            PLANT_NO_TRIAL = 1;
        else
            refuse("usage", "CFT_SEGRUN_PLANT=%s is not an instrument this "
                   "tool has (flags-unreadable, flags-unwritten, "
                   "flags-wide, trial-skipped)", plant);
        fprintf(stderr, "cft-segrun: CFT_SEGRUN_PLANT=%s - an instrument: "
                "%s\n", plant, PLANT_NO_TRIAL ? "the trial's allocations "
                "are skipped, its size checks kept" : "this run is to be "
                "refused");
    }

    if (argc < 2) {
        usage_text(stderr);
        refuse("usage", "nothing to do");
    }
    for (i = 1; i < argc; i++) {
        const char *a = argv[i];
        run_spec *cur = n_runs ? &runs[n_runs - 1] : NULL;
        if (!strcmp(a, "-h") || !strcmp(a, "--help")) {
            usage_text(stdout);
            return 0;
        } else if (!strcmp(a, "--build-id")) {
            want_build_id = 1;
        } else if (!strcmp(a, "--hash")) {
            once(&hash_kind, a, need(argc, argv, &i));
            if (strcmp(hash_kind, "commitment") != 0)
                hash_file = need(argc, argv, &i);
        } else if (!strcmp(a, "--out")) {
            once(&out_path, a, need(argc, argv, &i));
        } else if (!strcmp(a, "--states")) {
            once(&states_path, a, need(argc, argv, &i));
        } else if (!strcmp(a, "--salt")) {
            once(&salt_path, a, need(argc, argv, &i));
        } else if (!strcmp(a, "--open")) {
            if (open_mode)
                refuse("usage", "--open is given twice");
            open_mode = 1;
        } else if (!strcmp(a, "--device")) {
            once(&device, a, need(argc, argv, &i));
        } else if (!strcmp(a, "--scratch-depth")) {
            once(&depth_s, a, need(argc, argv, &i));
        } else if (!strcmp(a, "--run")) {
            const char *k = need(argc, argv, &i);
            run_spec *grown;
            int kind;
            if (n_entries)
                refuse("usage", "--run %s after --entry: the runs come first, "
                       "and the accuracy entries after them", k);
            if (!strcmp(k, "main"))
                kind = K_MAIN;
            else if (!strcmp(k, "half-step"))
                kind = K_HALF;
            else if (!strcmp(k, "wider"))
                kind = K_WIDER;
            else
                refuse("usage", "--run %s: a run is main, half-step or wider",
                       k);
            grown = (run_spec *)xcalloc(n_runs + 1, sizeof *grown);
            if (n_runs)
                memcpy(grown, runs, n_runs * sizeof *grown);
            free(runs);
            runs = grown;
            memset(&runs[n_runs], 0, sizeof runs[n_runs]);
            runs[n_runs].kind = kind;
            n_runs++;
        } else if (!strcmp(a, "--image") || !strcmp(a, "--bank") ||
                   !strcmp(a, "--init") || !strcmp(a, "--segments") ||
                   !strcmp(a, "--steps") || !strcmp(a, "--h-slots") ||
                   !strcmp(a, "--param")) {
            const char *v = need(argc, argv, &i);
            if (!cur)
                refuse("usage", "%s belongs to a run: give it after --run",
                       a);
            if (n_entries)
                refuse("usage", "%s belongs to a run, and the runs come "
                       "before the accuracy entries (--entry)", a);
            if (!strcmp(a, "--image"))         once(&cur->image_path, a, v);
            else if (!strcmp(a, "--bank"))     once(&cur->bank_path, a, v);
            else if (!strcmp(a, "--init"))     once(&cur->init_path, a, v);
            else if (!strcmp(a, "--segments")) once(&cur->segments_s, a, v);
            else if (!strcmp(a, "--steps"))    once(&cur->steps_s, a, v);
            else if (!strcmp(a, "--h-slots"))  once(&cur->hslots_s, a, v);
            else {
                /* the one name the page reads is the option's to write,
                 * from the depth the backend was opened at */
                if (!strncmp(v, DEPTH_PARAM, DEPTH_PARAM_LEN) &&
                    v[DEPTH_PARAM_LEN] == '=')
                    refuse("usage", "--param %s: %s is the parameter "
                           "--scratch-depth writes, from the depth the "
                           "software backend is opened at; give "
                           "--scratch-depth N instead", v, DEPTH_PARAM);
                add_param(cur, v);
            }
        } else if (!strcmp(a, "--entry")) {
            const char *m = need(argc, argv, &i);
            entry_spec *grown = (entry_spec *)xcalloc(n_entries + 1,
                                                      sizeof *grown);
            if (n_entries)
                memcpy(grown, entries, n_entries * sizeof *grown);
            free(entries);
            entries = grown;
            entries[n_entries].method_s = m;
            n_entries++;
        } else if (!strcmp(a, "--uses") || !strcmp(a, "--scope") ||
                   !strcmp(a, "--quantity") || !strcmp(a, "--term") ||
                   !strcmp(a, "--value")) {
            const char *v = need(argc, argv, &i);
            entry_spec *X = n_entries ? &entries[n_entries - 1] : NULL;
            if (!X)
                refuse("usage", "%s belongs to an accuracy entry: give it "
                       "after --entry", a);
            if (!strcmp(a, "--uses"))          once(&X->uses_s, a, v);
            else if (!strcmp(a, "--scope"))    once(&X->scope_s, a, v);
            else if (!strcmp(a, "--quantity")) once(&X->label_s, a, v);
            else if (!strcmp(a, "--value"))    once(&X->value_s, a, v);
            else                               add_term(X, v);
        } else {
            refuse("usage", "unknown argument '%s' (--help lists them)", a);
        }
    }

    /* ---- the two small modes ---------------------------------------- */
    if (want_build_id) {
        if (argc != 2)
            refuse("usage", "--build-id takes nothing else");
        printf("%s\n", cft_build_id());
        return 0;
    }
    if (salt_path && open_mode)
        refuse("usage", "--salt and --open: a certificate is keyed or open, "
               "not both");
    if (salt_path) {
        salt = read_named("the salt", salt_path, &salt_bytes);
        if (salt_bytes != SALT_BYTES)
            refuse("salt-length", "a version-1 salt is exactly %d bytes; %s "
                   "is %lu", SALT_BYTES, salt_path,
                   (unsigned long)salt_bytes);
    }
    if (hash_kind) {
        if (out_path || states_path || device || depth_s || n_runs ||
            n_entries)
            refuse("usage", "--hash takes a kind, a file and --salt or "
                   "--open, and nothing else");
        if (!salt && !open_mode && strcmp(hash_kind, "commitment") != 0)
            refuse("usage", "--hash %s needs --salt or --open", hash_kind);
        return do_hash(hash_kind, hash_file, salt);
    }

    /* ---- a certificate: the command line, then every input --------- */
    if (!out_path || !states_path)
        refuse("usage", "--out and --states are required");
    if (!salt_path && !open_mode)
        refuse("usage", "say --salt SALT (keyed) or --open");
    if (depth_s) {
        uint64_t v;
        if (device && strcmp(device, "sw") != 0)
            refuse("usage", "--scratch-depth %s beside --device %s: it opens "
                   "the SOFTWARE backend at a tile's depth, and a device's "
                   "depth is its image's (CAPS2[3:0]); cft_open_ex refuses "
                   "the two together too", depth_s, device);
        if (!dec_ok(depth_s, &v) || v < 1 || v > DEPTH_MAX || (v & (v - 1)))
            refuse("usage", "--scratch-depth %s is not a power of two from 1 "
                   "to %u in its one decimal spelling: a tile publishes its "
                   "depth as a four-bit log2 (CAPS2[3:0]), and the reader "
                   "holds a certificate's scratch-depth to the same range",
                   depth_s, DEPTH_MAX);
        SCRATCH_DEPTH = (uint32_t)v;
    }
    if (n_runs == 0)
        refuse("malformed", "a certificate has at least one run, and run 0 "
               "is main (--run main ...)");
    for (r = 0; r < n_runs; r++)
        check_run(&runs[r], r);

    /* ---- the accuracy entries, before anything is made ----------------- */
#if CX_EXACT
    for (j = 0; j < n_entries; j++)
        check_entry(&entries[j], j, runs, n_runs);
#else
    /* no exact arithmetic in this build: the entries' values are exact
     * rationals, which a bigint narrower than the width rule's steps
     * cannot compute, so it refuses rather than write them differently
     * (cft-audit's build-width) */
    if (n_entries)
        refuse("build-width", "this command line has %lu accuracy entr%s, "
               "whose values are exact, and this build's bigint is %d bits, "
               "narrower than the %d an exact step needs; it refuses rather "
               "than write them differently", (unsigned long)n_entries,
               n_entries == 1 ? "y" : "ies", CFT_BN_LIMBS * 32,
               2 * CX_WIDTH_BITS + 1);
#endif

    /* ---- what every run needs, tried before anything is made ------------ */
    try_runs(runs, n_runs, entries, n_entries, states_path, salt != NULL);

    /* ---- the outputs, before any device work ----------------------------
     * Both created new, the certificate first: a file already at --out is
     * refused, never overwritten, and an --out inside --states cannot be
     * created at all, since --states must not exist yet - so the
     * certificate can never be one of the boundary files. */
    CERT_PATH = out_path;
    CERT_FP = create_new(out_path);
    if (!CERT_FP) {
        if (errno == EEXIST)
            refuse("output", "--out %s is there already; the certificate is "
                   "a new file, so that no run overwrites, and no refusal "
                   "removes, a file the run did not make", out_path);
        refuse("output", "--out %s cannot be created (%s)%s", out_path,
               strerror(errno), errno == ENOENT ? "; an --out inside "
               "--states, which this run creates and which must not exist "
               "yet, is refused this way" : "");
    }
    {
        /* a device opens "new" too (Windows' NUL): what was opened must be
         * a file, and a device is not this run's to remove */
        stat_t sb;
        if (FSTAT(FILENO(CERT_FP), &sb) != 0 || !IS_FILE(sb.st_mode)) {
            FILE *f = CERT_FP;
            CERT_FP = NULL;
            fclose(f);
            refuse("output", "--out %s is not a file, and the certificate is "
                   "one; a device or other special file there is left as it "
                   "is", out_path);
        }
    }
    STATES_DIR = states_path;
    if (MKDIR(states_path) != 0)
        refuse("output", "--states %s cannot be created (%s); it must be a "
               "new directory, so that no two runs' states mix",
               states_path, strerror(errno));
    STATES_CREATED = 1;

    /* ---- the device ----------------------------------------------------- */
    if (SCRATCH_DEPTH) {
        /* the software backend at a tile's depth; the option was held to
         * cft_open_ex's range above, and beside a device it was refused */
        cft_open_args oa;
        memset(&oa, 0, sizeof oa);
        oa.struct_size   = sizeof oa;
        oa.artifact      = NULL;
        oa.index         = 0;
        oa.scratch_depth = SCRATCH_DEPTH;
        st = cft_open_ex(&oa, &dev);
        if (st != CFT_OK)
            refuse_st("device", "cft_open_ex", st);
    } else {
        st = cft_open((device && strcmp(device, "sw") != 0) ? device : NULL,
                      0, &dev);
        if (st != CFT_OK)
            refuse_st("device", "cft_open", st);
    }
    memset(&caps, 0, sizeof caps);
    caps.struct_size = sizeof caps;
    st = cft_get_caps(dev, &caps);
    if (st != CFT_OK)
        refuse_st("device", "cft_get_caps", st);
    if (PLANT_UNREADABLE)
        caps.flags_readable = 0;
    if (!caps.flags_readable)
        refuse("device", "this %s device cannot read the sticky flags, and a "
               "certificate records each segment's flag word%s",
               caps.backend, PLANT_UNREADABLE ? " (planted: "
               "CFT_SEGRUN_PLANT=flags-unreadable)" : "");
#if CX_EXACT
    /* A rounded or enclosed value is rounded and spelt through the
     * library, on a software handle of its own, as cft-audit's are: the
     * arithmetic is the host's whatever --device ran the segments. */
    for (j = 0; j < n_entries; j++)
        if (entries[j].E.value.form != V_EXACT) {
            st = cft_open(NULL, 0, &arith);
            if (st != CFT_OK)
                refuse_st("device", "cft_open, the software backend an "
                          "accuracy value is rounded and spelt through", st);
            break;
        }
#endif

    for (r = 0; r < n_runs; r++) {
        run_spec *R = &runs[r];
        cft_program_info info;
        const void *bank = R->bank_bytes ? R->bank : NULL;
        char where[64];
        snprintf(where, sizeof where, "run %lu: cft_program_load",
                 (unsigned long)r);
        st = cft_program_load(dev, R->img, R->img_bytes, &R->prog);
        if (st != CFT_OK)
            refuse_st("program-image", where, st);
        memset(&info, 0, sizeof info);
        info.struct_size = sizeof info;
        st = cft_program_get_info(R->prog, &info);
        if (st != CFT_OK)
            refuse_st("device", "cft_program_get_info", st);
        if ((uint32_t)info.format != R->H.prec ||
            info.n_scratch_in != R->H.n_in ||
            info.n_scratch_out != R->H.n_out ||
            info.max_deposits != R->H.max_deposits)
            refuse("program-image", "run %lu: the library reads %s's header "
                   "differently from this tool", (unsigned long)r,
                   R->image_path);
        sha256_of(R->img, R->img_bytes, digest);
        hex_of(digest, 32, R->image_digest);
        /* the library holds its own copy of the image (cft_program_load),
         * and the certificate needs only its digest */
        free(R->img);
        R->img = NULL;
        st = cft_program_digest(R->prog, bank, R->bank_bytes, digest);
        if (st != CFT_OK)
            refuse_st("device", "cft_program_digest", st);
        hex_of(digest, 32, R->program_digest);
    }
    identify(dev, &caps, &id);
    snprintf(LAST_BEFORE, sizeof LAST_BEFORE, "%s", cft_last_error());

    /* ---- the runs, segment by segment ------------------------------------ */
    for (r = 0; r < n_runs; r++) {
        run_spec *R = &runs[r];
        const void *bank = R->bank_bytes ? R->bank : NULL;
        uint8_t *cur, *next, *zero;
        uint64_t k;
        int s;

        /* as the trial took them: this run's hashes, flag words and STATUS,
         * kept for the certificate; its two states and its streams, let go
         * when it ends, so no run holds another's */
        R->hash = (char (*)[65])run_take((size_t)R->segments + 1,
                                         sizeof *R->hash, r,
                                         "the boundary hashes");
        R->flags = (uint32_t *)run_take((size_t)R->segments,
                                        sizeof(uint32_t), r, "the flag words");
        R->status = (uint32_t *)run_take((size_t)R->segments,
                                         sizeof(uint32_t), r, "STATUS");
        cur = (uint8_t *)run_take(R->state_bytes, 1, r, "a state");
        next = (uint8_t *)run_take(R->state_bytes, 1, r, "a state");
        zero = (uint8_t *)run_take(R->lanes, R->esz, r, "the streams");
        memcpy(cur, R->init, R->state_bytes);
        /* boundary 0 is written and hashed from cur: the initial state is
         * not needed again */
        free(R->init);
        R->init = NULL;

        for (s = 0; s < 3; s++)
            tagged_hash(salt, stream_tag(s), TAG_STREAM_LEN, zero,
                        R->lanes * R->esz, R->stream_hash[s]);
        write_boundary(r, 0, cur, R->state_bytes);
        state_hash(salt, cur, R->state_bytes, R->hash[0]);

        for (k = 0; k < R->segments; k++) {
            cft_run_args ra;
            uint32_t fl = 0xFFFFFFFFu, bus = 0;
            uint8_t *t;
            memset(&ra, 0, sizeof ra);
            ra.struct_size = sizeof ra;
            ra.a = zero;
            ra.b = zero;
            ra.c = zero;
            ra.n = R->lanes;
            ra.bank = bank;
            ra.bank_bytes = R->bank_bytes;
            ra.scratch_in = cur;
            ra.scratch_in_bytes = R->state_bytes;
            ra.scratch_out = next;
            ra.scratch_out_bytes = R->state_bytes;
            ra.flags_out = &fl;
            ra.bus_out = &bus;
            st = cft_program_run_ex(R->prog, &ra);
            if (st != CFT_OK) {
                char what[96];
                snprintf(what, sizeof what, "run %lu segment %llu: "
                         "cft_program_run_ex", (unsigned long)r,
                         (unsigned long long)k);
                refuse_st("device", what, st);
            }
            if (PLANT_UNWRITTEN)
                fl = 0xFFFFFFFFu;
            if (PLANT_WIDE)
                fl |= 0x20u;
            if (fl == 0xFFFFFFFFu)
                refuse("device", "run %lu segment %llu: the library did not "
                       "write the flag word%s", (unsigned long)r,
                       (unsigned long long)k, PLANT_UNWRITTEN ? " (planted: "
                       "CFT_SEGRUN_PLANT=flags-unwritten)" : "");
            if (fl > 31u)
                refuse("malformed", "run %lu segment %llu: the library "
                       "reported flags 0x%08x, and a certificate's flag word "
                       "is the five sticky IEEE flags, 0 to 31%s",
                       (unsigned long)r, (unsigned long long)k, (unsigned)fl,
                       PLANT_WIDE ? " (planted: CFT_SEGRUN_PLANT=flags-wide)"
                                  : "");
            R->flags[k] = fl;
            R->status[k] = bus;
            write_boundary(r, k + 1, next, R->state_bytes);
            state_hash(salt, next, R->state_bytes, R->hash[k + 1]);
            t = cur;
            cur = next;
            next = t;
        }
        free(cur);
        free(next);
        free(zero);
    }

    /* ---- the accuracy entries, from the states the runs wrote ----------
     * Every value first, each entry's two states read back and let go
     * before the next entry's; then every value's form. That is the golden
     * writer's order: cert.derive for each entry, then encode's reader
     * (an enclosure's ends against the width rule). */
#if CX_EXACT
    for (j = 0; j < n_entries; j++)
        derive_entry(&entries[j], j, runs, salt);
    for (j = 0; j < n_entries; j++)
        make_value(&entries[j], j, arith);
#endif

    /* ---- the certificate ------------------------------------------------- */
    put(&body, "cft-certificate 1\n");
    put(&body, "mode %s\n", salt ? "keyed" : "open");
    if (salt) {
        salt_commitment(salt, commitment);
        put(&body, "salt-commitment %s\n", commitment);
    }
    put(&body, "build-id %s\n", id.build_id);
    put(&body, "backend %s\n", id.backend);
    put(&body, "device-xclbin %s\n", id.xclbin);
    put(&body, "device-version %s\n", id.version);
    put(&body, "device-caps %s\n", id.caps);
    put(&body, "device-tiles %s\n", id.tiles);
    put(&body, "runs %llu\n", (unsigned long long)n_runs);
    for (r = 0; r < n_runs; r++) {
        run_spec *R = &runs[r];
        uint64_t k;
        if (R->kind == K_HALF) {
            put(&body, "run %llu half-step h-slots %llu",
                (unsigned long long)r, (unsigned long long)R->n_hslots);
            for (j = 0; j < R->n_hslots; j++)
                put(&body, " %u", R->hslots[j]);
            put(&body, "\n");
        } else {
            put(&body, "run %llu %s\n", (unsigned long long)r,
                KIND_NAME[R->kind]);
        }
        put(&body, "program-format %s\n", FORMAT_NAME[R->H.prec]);
        put(&body, "program-image %s\n", R->image_digest);
        put(&body, "program-digest %s\n", R->program_digest);
        put(&body, "lanes %llu\n", (unsigned long long)R->lanes);
        put(&body, "steps %llu\n", (unsigned long long)R->steps);
        put(&body, "stream-a %s\n", R->stream_hash[0]);
        put(&body, "stream-b %s\n", R->stream_hash[1]);
        put(&body, "stream-c %s\n", R->stream_hash[2]);
        put(&body, "parameters %llu\n", (unsigned long long)R->n_param_s +
            (SCRATCH_DEPTH ? 1u : 0u));
        {
            /* --scratch-depth's parameter in its place in byte order among
             * the run's own, which are in that order already (check_run),
             * and none of which is named as it is (refused as usage) */
            int depth_put = SCRATCH_DEPTH == 0;
            for (j = 0; j < R->n_param_s; j++) {
                const char *s = R->param_s[j];
                const char *eq = strchr(s, '=');
                if (!depth_put && name_cmp(DEPTH_PARAM, DEPTH_PARAM_LEN, s,
                                           (size_t)(eq - s)) < 0) {
                    put(&body, "parameter %s %lu\n", DEPTH_PARAM,
                        (unsigned long)SCRATCH_DEPTH);
                    depth_put = 1;
                }
                put(&body, "parameter %.*s %s\n", (int)(eq - s), s, eq + 1);
            }
            if (!depth_put)
                put(&body, "parameter %s %lu\n", DEPTH_PARAM,
                    (unsigned long)SCRATCH_DEPTH);
        }
        put(&body, "segments %llu\n", (unsigned long long)R->segments);
        for (k = 0; k < R->segments; k++)
            put(&body, "segment %llu start %s end %s flags %u status %u\n",
                (unsigned long long)k, R->hash[k], R->hash[k + 1],
                (unsigned)R->flags[k], (unsigned)R->status[k]);
        put(&body, "output %s\n", R->hash[R->segments]);
    }
    put_accuracy(&body, entries, n_entries, arith);
    put(&body, "end\n");
    sha256_of(body.p, body.n, digest);
    hex_of(digest, 32, hex);
    put(&body, "hash %s\n", hex);

    if (fwrite(body.p, 1, body.n, CERT_FP) != body.n)
        refuse("output", "a short write to %s", out_path);
    if (fclose(CERT_FP) != 0) {
        CERT_FP = NULL;
        remove(out_path);
        refuse("output", "%s could not be closed", out_path);
    }
    CERT_FP = NULL;

    /* ---- the report ------------------------------------------------------ */
    printf("certificate   %s (%s, %lu run%s)\n", out_path,
           salt ? "keyed" : "open", (unsigned long)n_runs,
           n_runs == 1 ? "" : "s");
    printf("states        %s (%llu files: run-<r>-boundary-<b>.bin)\n",
           states_path, STATE_FILES);
    printf("build-id      %s\n", id.build_id);
    printf("device        %s: xclbin %s, version %s, caps %s, tiles %s\n",
           id.backend, id.xclbin, id.version, id.caps, id.tiles);
    if (SCRATCH_DEPTH)
        printf("scratch-depth %lu slots a lane (cft_open_ex), stated in "
               "every run block\n", (unsigned long)SCRATCH_DEPTH);
    for (r = 0; r < n_runs; r++) {
        run_spec *R = &runs[r];
        uint64_t k;
        uint32_t orf = 0, ors = 0;
        for (k = 0; k < R->segments; k++) {
            orf |= R->flags[k];
            ors |= R->status[k];
        }
        printf("run %-10llu%s %s, %llu lane%s, %llu segment%s, flags seen "
               "0x%02x, STATUS seen 0x%08x\n", (unsigned long long)r,
               KIND_NAME[R->kind], FORMAT_NAME[R->H.prec],
               (unsigned long long)R->lanes, R->lanes == 1 ? "" : "s",
               (unsigned long long)R->segments, R->segments == 1 ? "" : "s",
               (unsigned)orf, (unsigned)ors);
        printf("  output      %s\n", R->hash[R->segments]);
    }
#if CX_EXACT
    for (j = 0; j < n_entries; j++) {
        const entry_t *E = &entries[j].E;
        char buf[CX_RAT_TEXT];
        rat_text(&entries[j].q, buf);
        printf("entry %-8lu%s, %s of run %llu, %s%s: %.60s%s (%s)\n",
               (unsigned long)j, METHOD_NAME[E->method],
               KINDS[METHOD_KIND[E->method]], (unsigned long long)E->uses,
               E->has_lane ? "lane " : "max-lanes",
               E->has_lane ? entries[j].scope_s + 5 : "", buf,
               strlen(buf) > 60 ? "..." : "",
               E->value.form == V_EXACT ? "exact" :
               E->value.form == V_ROUNDED ? "rounded" : "enclosed");
    }
#endif
    printf("hash          %s\n", hex);

    for (r = 0; r < n_runs; r++) {
        cft_program_free(runs[r].prog);
        free(runs[r].img);
        free(runs[r].bank);
        free(runs[r].init);
        free(runs[r].hash);
        free(runs[r].flags);
        free(runs[r].status);
        free((void *)runs[r].param_s);
    }
    free(runs);
    for (j = 0; j < n_entries; j++) {
#if CX_EXACT
        free(entries[j].E.terms);
#endif
        free((void *)entries[j].term_s);
    }
    free(entries);
    free(salt);
    free(body.p);
    if (arith)
        cft_close(arith);
    cft_close(dev);
    return 0;
}
