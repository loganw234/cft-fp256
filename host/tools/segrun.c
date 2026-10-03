/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cft-segrun - run a program as consecutive segments, keep the state at
 * every boundary, and write the certificate (docs/CERTIFICATES.md,
 * versions 1 and 2). Step 3 of the plan of record (docs/ROADMAP.md,
 * "Segments, certificates and the audit tool"); the page's section "The
 * segment runner" is this tool's manual.
 *
 *   cft-segrun --out CERT --states DIR (--salt SALT | --open)
 *              [--format-version 1|2]
 *              [--device sw|<xclbin>|cft://host:port | --scratch-depth N]
 *              [--certificate-id ID] [--issuer ISSUER] [--issuer-key KEY]
 *              [--initial INITIAL] [--supersedes DIGEST]
 *              [--compiler-build BUILD]
 *              [--publish device-serial|host-os-version ...]
 *              --run main --image IMG [--bank BANK] --init INIT
 *                         --segments S --steps K [--param NAME=N ...]
 *                         [--lane-flags]
 *                         [--source SRC --manifest M [--compiler none]]
 *                         [--replay-image IMG [--replay-bank BANK]]
 *              [--run half-step --h-slots I,J,... --image IMG ...]
 *              [--run wider --image IMG ...]
 *              [--run wider-source --image IMG ...]
 *              [--entry drift|step-halving|wider|wider-source --uses R
 *                       --scope max-lanes|lane:I
 *                       [--quantity LABEL --term C[,sI...] ...]
 *                       --value exact|rounded:FMT:RND|enclosed:FMT] ...
 *   cft-segrun --hash state|stream-a|stream-b|stream-c FILE
 *              (--salt SALT | --open)
 *   cft-segrun --hash commitment --salt SALT
 *   cft-segrun --build-id
 *
 * ---------------------------------------------------------------
 * Version 2 (certificate format version 2's C half, parcel CV2CW,
 * 2026-10-02)
 * ---------------------------------------------------------------
 *
 * The tool writes version 2 by default, and version 1 with
 * `--format-version 1`: the old code, byte for byte what it wrote before
 * (the corpus's version-1 cases and segrun_check's sections 1 to 13 hold
 * it). Every option version 1 has no line for, given beside it, is
 * `usage`, naming it. Version 2 adds, as docs/CERTIFICATES.md's "Version
 * 2" says and the golden writer, python/cft_golden/cert2.py, writes:
 *   - the header's new lines (put_v2_header): the definition, from cft.h's
 *     CFT_PROFILE_* and CFT_LANGUAGE_* (a fallback block below until
 *     CV2CA's merge); the device lines through cft_image_id at ABI 0.18
 *     (cert_write.h's cw_identify); the writer and its build; the
 *     compiler's build; each run's replay method; the header's statements,
 *     each option taking its line's own value as the certificate spells
 *     it (check_statements), the issuer and the device serial withheld
 *     unless given or published; the host's OS and architecture, the
 *     times and the writer's list's environment, measured - the
 *     environment's values, like a source's file name, as the process
 *     has them, which on Windows is the wide APIs' text and not the ANSI
 *     code page's ("the process's own text", below);
 *   - a run's per-lane block (--lane-flags, and wherever its image holds
 *     flag control), each segment's written beside the boundaries;
 *   - its source (--source SRC --manifest M, check_source): the source
 *     lines from cftc's manifest, held to the files the run runs;
 *   - a marked lane replayed (replay_segment) by an image of the run's
 *     source (--replay-image, --replay-bank), the corrected segment
 *     certified and the raw one on a replay line and in -raw files;
 *   - `run <i> wider-source` and `entry <j> wider-source`.
 * Its refusals are the page's names (the table below gains them) and its
 * gate is segrun_check's section 14 (host/tests/segrun_check_v2.py).
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
 * and a fifth writes what would be refused, for the audit's control:
 *   wider-routine      a wider run whose main image holds a routine is
 *                      written as stated instead of refused `aux-image`
 *                      (C4, main() after check_run), so that the gate can
 *                      hand cft-audit the certificate it must refuse
 *                      (programs/lang_check.py, leg E)
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

#include "cft.h"
/* An accuracy entry's exact arithmetic, cft-audit's, shared (the plan's
 * step 5): the functions exactly, the width rule, the rounding and the
 * enclosure, each returning a status this file refuses by name. With it
 * come the formats (FMT, ESZ), the directions (RND_NAME), the run kinds
 * (K_MAIN, K_HALF, K_WIDER, KIND_NAME) and the methods' words. */
#include "cert_exact.h"
/* The certificate's encoding, shared with cft-orbits' certified runs
 * (the steps-5-and-6 round's parcel S3, 2026-09-30): the tagged hashes
 * and the salt's commitment, the identity lines, the text and the lines,
 * an entry's lines, and a file created new (cw_create_new: O_EXCL, so no
 * file the tool writes is one it did not create). Each returns the name
 * this file refuses by; the words and the exits stay here. */
#include "cert_write.h"
/* An Ed25519 public key's decoding, cft-audit's (parcel CV2CA's
 * host/tools/ed25519.h, with SHA-512 in sha512.h; header-only, every
 * definition static and marked unused): this file calls only
 * ed25519_key_check, on an --issuer-key, so the tree keeps one Ed25519 in
 * C (the lead's decision at the merge of the two halves, 2026-10-03). */
#include "ed25519.h"

/* Version 2's measurements: the times, and the host's OS and architecture
 * (docs/CERTIFICATES.md, "Provenance"). */
#include <time.h>
#if !defined(_WIN32)
#  include <sys/utsname.h>
#endif

/* ---- the process's own text --------------------------------------------
 * A certificate records the values the tool reads as the process has them
 * (docs/CERTIFICATES.md, "Encodings": a text is UTF-8): an environment
 * variable's value, and a source's file name. Windows hands main its
 * arguments, and getenv its values, converted to the ANSI code page, which
 * cannot carry most of Unicode - U+0141 arrives as L by best fit, and
 * U+00E9 and a, U+20AC, b as bytes that are not UTF-8 (verifier-VCV2CW,
 * 2026-10-03). So on Windows the arguments are the wide command line's
 * (CommandLineToArgvW), each environment value GetEnvironmentVariableW's,
 * each in UTF-8, and every path is opened through its wide form; elsewhere
 * the bytes the process was handed are its text, as Python's are the
 * golden writer's. The header's statements stay in their own
 * percent-encoded spelling (the lead's decision, 2026-10-02): an option
 * the user spells, not a value the tool reads.
 *
 * The path functions here run from cleanup(), so they never refuse: each
 * answers as the C library's would, NULL or -1 with errno set (EILSEQ for
 * a path that is not UTF-8, which no argument read here can be). */
#if defined(_WIN32)
#  include <shellapi.h>             /* CommandLineToArgvW */
#  include <wchar.h>
#  if defined(_MSC_VER)
#    pragma comment(lib, "shell32.lib")
#  endif
#  ifndef WC_ERR_INVALID_CHARS
#    define WC_ERR_INVALID_CHARS 0x80
#  endif

/* UTF-16 to UTF-8, malloc'd: NULL with errno EILSEQ where the string has
 * no UTF-8 spelling (an unpaired surrogate), ENOMEM where memory fails */
static char *u8_of_wide(const wchar_t *w)
{
    int n = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, w, -1, NULL,
                                0, NULL, NULL);
    char *s;
    if (n <= 0) {
        errno = EILSEQ;
        return NULL;
    }
    s = (char *)malloc((size_t)n);
    if (!s) {
        errno = ENOMEM;
        return NULL;
    }
    if (WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, w, -1, s, n, NULL,
                            NULL) != n) {
        free(s);
        errno = EILSEQ;
        return NULL;
    }
    return s;
}

/* UTF-8 to UTF-16, malloc'd: NULL with errno EILSEQ where the bytes are
 * not UTF-8, ENOMEM where memory fails */
static wchar_t *wide_of_u8(const char *s)
{
    int n = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s, -1, NULL,
                                0);
    wchar_t *w;
    if (n <= 0) {
        errno = EILSEQ;
        return NULL;
    }
    w = (wchar_t *)malloc((size_t)n * sizeof *w);
    if (!w) {
        errno = ENOMEM;
        return NULL;
    }
    if (MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s, -1, w, n) !=
        n) {
        free(w);
        errno = EILSEQ;
        return NULL;
    }
    return w;
}

static FILE *u8_fopen(const char *path, const char *mode)
{
    wchar_t *w = wide_of_u8(path), *m = w ? wide_of_u8(mode) : NULL;
    FILE *f = w && m ? _wfopen(w, m) : NULL;
    int e = errno;
    free(w);
    free(m);
    errno = e;
    return f;
}

/* cert_write.h's cw_create_new through the path's wide form: O_EXCL, and
 * a path that is there called so whatever it is (Windows answers O_EXCL
 * on a directory with EACCES) */
static FILE *u8_create_new(const char *path)
{
    struct _stat sb;
    wchar_t *w = wide_of_u8(path);
    FILE *f = NULL;
    int fd, e;
    if (!w)
        return NULL;
    fd = _wopen(w, _O_WRONLY | _O_CREAT | _O_EXCL | _O_BINARY,
                _S_IREAD | _S_IWRITE);
    if (fd < 0) {
        e = errno;
        if (e == EACCES && _wstat(w, &sb) == 0)
            e = EEXIST;
    } else {
        f = _fdopen(fd, "wb");
        e = errno;
        if (!f) {
            _close(fd);
            _wremove(w);
        }
    }
    free(w);
    errno = e;
    return f;
}

static int u8_mkdir(const char *path)
{
    wchar_t *w = wide_of_u8(path);
    int r = w ? _wmkdir(w) : -1, e = errno;
    free(w);
    errno = e;
    return r;
}

static int u8_rmdir(const char *path)
{
    wchar_t *w = wide_of_u8(path);
    int r = w ? _wrmdir(w) : -1, e = errno;
    free(w);
    errno = e;
    return r;
}

static int u8_remove(const char *path)
{
    wchar_t *w = wide_of_u8(path);
    int r = w ? _wremove(w) : -1, e = errno;
    free(w);
    errno = e;
    return r;
}
#else
#  define u8_fopen(p, m)    fopen((p), (m))
#  define u8_create_new(p)  cw_create_new(p)
#  define u8_mkdir(p)       MKDIR(p)
#  define u8_rmdir(p)       RMDIR(p)
#  define u8_remove(p)      remove(p)
#endif

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

/* The domain tags (docs/CERTIFICATES.md, "Hashes") are cert_write.h's,
 * CW_TAG_*: each length stated, not left to a terminator, since a state's
 * and a stream's tag END IN a NUL byte, the separator the page puts
 * before the bytes, and the salt's has none. */

static const char *const FORMAT_NAME[4] = { "fp32", "fp64", "fp128", "fp256" };

/* ---- refusals ---------------------------------------------------------- */

static const struct { const char *name; int code; } REFUSAL[] = {
    /* the page's names: the inputs a writer refuses */
    { "malformed", 2 }, { "line-order", 2 }, { "line-unexpected", 2 },
    { "width", 3 },
    { "salt-length", 4 }, { "program-image", 4 }, { "program-shape", 4 },
    { "state-shape", 4 },
    { "aux-image", 5 },
    { "accuracy-run", 7 }, { "accuracy-scope", 7 }, { "accuracy-slot", 7 },
    { "accuracy-finite", 7 },
    /* version 2's (docs/CERTIFICATES.md, "Version 2's refusals"): a run
     * that marks a lane it cannot replay, the times, a replay image, a
     * source and its manifest, and an issuer-key */
    { "replay-source", 2 }, { "replay-lane-flags", 2 },
    { "provenance-order", 2 },
    { "program-format", 4 }, { "source-digest", 4 }, { "source-format", 4 },
    { "source-graph", 4 }, { "source-shape", 4 }, { "source-image", 4 },
    { "signer", 4 },
    { "replay-missing", 6 }, { "replay-undecided", 78 },
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
static unsigned long long SIDE_FILES = 0;   /* version 2's, beside them */

/* CFT_SEGRUN_PLANT, the instrument (the header comment). */
static int PLANT_UNREADABLE = 0, PLANT_UNWRITTEN = 0, PLANT_WIDE = 0;
static int PLANT_NO_TRIAL = 0, PLANT_WIDER_ROUTINE = 0;

/* --scratch-depth N, or 0 where it was not given: the software backend
 * is then opened plainly, at its own 256, and no run block states it */
static uint32_t SCRATCH_DEPTH = 0;

/* --format-version: 2, the default, or 1 - version 1's certificate, byte
 * for byte what this tool wrote before version 2, for the corpus and for
 * runs that stay version 1 (docs/CERTIFICATES.md, "Version 2"). */
static int FORMAT_VERSION = 2;

/* version 2's `started` and `finished`, measured as the runs begin and
 * end (utc_now) */
static char T_STARTED[24] = "unknown", T_FINISHED[24] = "unknown";

static void cleanup(void)
{
    if (CERT_FP) {
        fclose(CERT_FP);
        CERT_FP = NULL;
        u8_remove(CERT_PATH);
    }
    if (STATES_CREATED && STATE_FILES == 0) {
        u8_rmdir(STATES_DIR);
        STATES_CREATED = 0;
    } else if (STATES_CREATED && SIDE_FILES) {
        fprintf(stderr, "cft-segrun: no certificate was written; the %llu "
                "boundary state file%s and %llu file%s of per-lane flags "
                "and replays written so far are left in %s\n", STATE_FILES,
                STATE_FILES == 1 ? "" : "s", SIDE_FILES,
                SIDE_FILES == 1 ? "" : "s", STATES_DIR);
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
    FILE *f = u8_fopen(path, "rb");
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

/* ---- version 2's spellings (docs/CERTIFICATES.md, "Version 2's
 * encodings"; a text's are cert_write.h's) ------------------------------ */

/* 64 lowercase hex digits: a digest, or a key's 32 bytes */
static int hex64_ok(const char *s)
{
    size_t i;
    if (strlen(s) != 64)
        return 0;
    for (i = 0; i < 64; i++)
        if (!((s[i] >= '0' && s[i] <= '9') || (s[i] >= 'a' && s[i] <= 'f')))
            return 0;
    return 1;
}

static unsigned hexnib(char c)
{
    return c <= '9' ? (unsigned)(c - '0') : (unsigned)(c - 'a' + 10);
}

/* ---- an issuer-key: an Ed25519 public key ---------------------------------
 *
 * The golden writer refuses an `issuer-key` that encodes no point of the
 * curve (`malformed`) or is a point of small order (`signer`, [8]A the
 * identity, under which a signature nobody made verifies for every
 * message), since every writer reads its text back with the strict reader
 * (docs/CERTIFICATES.md, "The detached signature"). This tool refuses the
 * same through ed25519_key_check (host/tools/ed25519.h, RFC 8032 section
 * 5.1.3's decoding and the small-order test, held to test_ed25519.py's
 * vectors by cft-audit's gate and here by segrun_check). Until the merge
 * of version 2's two C halves it carried a decoding-only copy of its own. */

/* ---- cftc's manifest: a small JSON reader -------------------------------
 *
 * `--source SRC --manifest M` takes a run's source lines from the manifest
 * cftc writes beside its image (python/cftc/manifest.py: JSON, ASCII,
 * keys in a fixed order). This reads JSON as RFC 8259 defines it - every
 * value, strings with their escapes and \u surrogate pairs decoded to
 * UTF-8, at most 64 deep - into a tree, and the manifest's fields are
 * taken from the tree by name. Anything it cannot read is the command
 * line's file that cannot be used: `usage`. */
enum { J_NULL, J_FALSE, J_TRUE, J_NUM, J_STR, J_ARR, J_OBJ };

typedef struct jv {
    int t;
    char *s;                    /* J_STR, decoded; J_NUM, its text */
    size_t n;                   /* J_ARR's and J_OBJ's members */
    struct jv **kid;
    char **key;                 /* J_OBJ's keys */
} jv;

typedef struct {
    const char *p, *end;
    int depth;
} jreader;

static void jfree(jv *v)
{
    size_t i;
    if (!v)
        return;
    for (i = 0; i < v->n; i++) {
        jfree(v->kid[i]);
        if (v->key)
            free(v->key[i]);
    }
    free(v->kid);
    free(v->key);
    free(v->s);
    free(v);
}

static void jws(jreader *r)
{
    while (r->p < r->end && (*r->p == ' ' || *r->p == '\t' ||
                             *r->p == '\n' || *r->p == '\r'))
        r->p++;
}

static int jhex4(const char *p, unsigned long *out)
{
    int i;
    *out = 0;
    for (i = 0; i < 4; i++) {
        char c = p[i];
        unsigned d;
        if (c >= '0' && c <= '9')
            d = (unsigned)(c - '0');
        else if (c >= 'a' && c <= 'f')
            d = (unsigned)(c - 'a' + 10);
        else if (c >= 'A' && c <= 'F')
            d = (unsigned)(c - 'A' + 10);
        else
            return 0;
        *out = *out * 16 + d;
    }
    return 1;
}

/* A string at r->p (its opening quote), decoded to UTF-8 and terminated;
 * NULL where it breaks the grammar, or decodes to a NUL. */
static char *jstring(jreader *r)
{
    size_t cap = 32, n = 0;
    char *out = (char *)xcalloc(cap, 1);
    r->p++;
    while (r->p < r->end && *r->p != '"') {
        unsigned long cp;
        unsigned char c = (unsigned char)*r->p;
        unsigned char enc[4];
        size_t k, len = 0;
        if (c < 0x20)
            goto bad;
        if (c != '\\') {
            enc[len++] = c;
            r->p++;
        } else {
            if (r->end - r->p < 2)
                goto bad;
            c = (unsigned char)r->p[1];
            r->p += 2;
            switch (c) {
            case '"': case '\\': case '/':
                enc[len++] = c;
                break;
            case 'b': enc[len++] = '\b'; break;
            case 'f': enc[len++] = '\f'; break;
            case 'n': enc[len++] = '\n'; break;
            case 'r': enc[len++] = '\r'; break;
            case 't': enc[len++] = '\t'; break;
            case 'u':
                if (r->end - r->p < 4 || !jhex4(r->p, &cp))
                    goto bad;
                r->p += 4;
                if (cp >= 0xD800 && cp <= 0xDBFF) {
                    unsigned long lo;
                    if (r->end - r->p < 6 || r->p[0] != '\\' ||
                        r->p[1] != 'u' || !jhex4(r->p + 2, &lo) ||
                        lo < 0xDC00 || lo > 0xDFFF)
                        goto bad;
                    r->p += 6;
                    cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                } else if (cp >= 0xDC00 && cp <= 0xDFFF) {
                    goto bad;
                }
                if (cp == 0)
                    goto bad;
                if (cp < 0x80) {
                    enc[len++] = (unsigned char)cp;
                } else if (cp < 0x800) {
                    enc[len++] = (unsigned char)(0xC0 | (cp >> 6));
                    enc[len++] = (unsigned char)(0x80 | (cp & 0x3F));
                } else if (cp < 0x10000) {
                    enc[len++] = (unsigned char)(0xE0 | (cp >> 12));
                    enc[len++] = (unsigned char)(0x80 | ((cp >> 6) & 0x3F));
                    enc[len++] = (unsigned char)(0x80 | (cp & 0x3F));
                } else {
                    enc[len++] = (unsigned char)(0xF0 | (cp >> 18));
                    enc[len++] = (unsigned char)(0x80 | ((cp >> 12) & 0x3F));
                    enc[len++] = (unsigned char)(0x80 | ((cp >> 6) & 0x3F));
                    enc[len++] = (unsigned char)(0x80 | (cp & 0x3F));
                }
                break;
            default:
                goto bad;
            }
        }
        if (n + len + 1 > cap) {
            char *g = (char *)xcalloc(cap, 2);
            memcpy(g, out, n);
            free(out);
            out = g;
            cap *= 2;
        }
        for (k = 0; k < len; k++)
            out[n++] = (char)enc[k];
    }
    if (r->p >= r->end)
        goto bad;
    r->p++;
    out[n] = 0;
    if (strlen(out) != n)       /* a raw NUL byte in the file */
        goto bad;
    return out;
bad:
    free(out);
    return NULL;
}

static jv *jvalue(jreader *r);

/* An object's or an array's members, grown one at a time. */
static void jadd(jv *v, jv *kid, char *key)
{
    jv **g = (jv **)xcalloc(v->n + 1, sizeof *g);
    if (v->n)
        memcpy(g, v->kid, v->n * sizeof *g);
    free(v->kid);
    v->kid = g;
    if (v->t == J_OBJ) {
        char **k = (char **)xcalloc(v->n + 1, sizeof *k);
        if (v->n)
            memcpy(k, v->key, v->n * sizeof *k);
        free(v->key);
        v->key = k;
        v->key[v->n] = key;
    }
    v->kid[v->n++] = kid;
}

static jv *jvalue(jreader *r)
{
    jv *v = (jv *)xcalloc(1, sizeof *v);
    jws(r);
    if (r->p >= r->end || ++r->depth > 64)
        goto bad;
    if (*r->p == '{' || *r->p == '[') {
        int obj = *r->p == '{';
        char close = obj ? '}' : ']';
        v->t = obj ? J_OBJ : J_ARR;
        r->p++;
        jws(r);
        if (r->p < r->end && *r->p == close) {
            r->p++;
        } else {
            for (;;) {
                char *key = NULL;
                jv *kid;
                jws(r);
                if (obj) {
                    if (r->p >= r->end || *r->p != '"' ||
                        !(key = jstring(r)))
                        goto bad;
                    jws(r);
                    if (r->p >= r->end || *r->p != ':') {
                        free(key);
                        goto bad;
                    }
                    r->p++;
                }
                kid = jvalue(r);
                if (!kid) {
                    free(key);
                    goto bad;
                }
                jadd(v, kid, key);
                jws(r);
                if (r->p < r->end && *r->p == ',') {
                    r->p++;
                    continue;
                }
                if (r->p < r->end && *r->p == close) {
                    r->p++;
                    break;
                }
                goto bad;
            }
        }
    } else if (*r->p == '"') {
        v->t = J_STR;
        if (!(v->s = jstring(r)))
            goto bad;
    } else if (r->end - r->p >= 4 && !memcmp(r->p, "true", 4)) {
        v->t = J_TRUE;
        r->p += 4;
    } else if (r->end - r->p >= 5 && !memcmp(r->p, "false", 5)) {
        v->t = J_FALSE;
        r->p += 5;
    } else if (r->end - r->p >= 4 && !memcmp(r->p, "null", 4)) {
        v->t = J_NULL;
        r->p += 4;
    } else {
        /* -?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)? */
        const char *s = r->p;
        size_t len;
        if (r->p < r->end && *r->p == '-')
            r->p++;
        if (r->p < r->end && *r->p == '0') {
            r->p++;
        } else if (r->p < r->end && *r->p >= '1' && *r->p <= '9') {
            while (r->p < r->end && *r->p >= '0' && *r->p <= '9')
                r->p++;
        } else {
            goto bad;
        }
        if (r->p < r->end && *r->p == '.') {
            r->p++;
            if (r->p >= r->end || *r->p < '0' || *r->p > '9')
                goto bad;
            while (r->p < r->end && *r->p >= '0' && *r->p <= '9')
                r->p++;
        }
        if (r->p < r->end && (*r->p == 'e' || *r->p == 'E')) {
            r->p++;
            if (r->p < r->end && (*r->p == '+' || *r->p == '-'))
                r->p++;
            if (r->p >= r->end || *r->p < '0' || *r->p > '9')
                goto bad;
            while (r->p < r->end && *r->p >= '0' && *r->p <= '9')
                r->p++;
        }
        v->t = J_NUM;
        len = (size_t)(r->p - s);
        v->s = (char *)xcalloc(len + 1, 1);
        memcpy(v->s, s, len);
    }
    r->depth--;
    return v;
bad:
    jfree(v);
    return NULL;
}

/* The member `key` of an object, or NULL. */
static const jv *jget(const jv *o, const char *key)
{
    size_t i;
    if (!o || o->t != J_OBJ)
        return NULL;
    for (i = 0; i < o->n; i++)
        if (!strcmp(o->key[i], key))
            return o->kid[i];
    return NULL;
}

static const char *jstr(const jv *v)
{
    return v && v->t == J_STR ? v->s : NULL;
}

/* A non-negative integer in its one decimal spelling, at most 2^63 - 1. */
static int juint(const jv *v, uint64_t *out)
{
    return v && v->t == J_NUM && dec_ok(v->s, out);
}

/* ---- a source param's literal: the language's canonical spelling --------
 *
 * cftc's manifest states each param run value it was given exactly, as
 * the step graph writes it, p or p/q in decimal (frac_text). A run's
 * `source-param` line spells it as the language's canonical literal
 * (docs/LANGUAGE.md, "The intention-out"; cft_golden/lang/constants.py,
 * `literal`): a decimal when it terminates within 24 significant digits,
 * positional for a leading digit between 10^-6 and 10^20 and with an
 * exponent otherwise; a hexadecimal significand when it is dyadic and
 * longer; else p or p/q in full. This is that function, on the library's
 * bigint (host/src/bigint.h, with cert_exact.h's division and gcd): a
 * value whose parts, or whose decimal, are past this build's bigint is
 * this tool's own limit, `build-width`, and never written otherwise. */
#define LIT_DIGITS 24

/* a decimal string of digits into a bigint: 0, or 1 past the bigint */
static int bn_from_dec(cft_bn *r, const char *s, size_t n)
{
    cft_bn ten, d, t;
    size_t i;
    cft_bn_zero(r);
    cft_bn_set_u32(&ten, 10);
    for (i = 0; i < n; i++) {
        if (cft_bn_mul(&t, r, &ten))
            return 1;
        cft_bn_set_u32(&d, (uint32_t)(s[i] - '0'));
        if (cft_bn_add(r, &t, &d))
            return 1;
    }
    return 0;
}

/* a bigint's decimal digits, into a buffer of the tool's (xcalloc) */
static char *bn_to_dec(const cft_bn *a)
{
    cft_bn q, rem, chunk, x;
    size_t cap = (size_t)cft_bn_bitlen(a) / 3 + 16, n = 0, i;
    char *rev = (char *)xcalloc(cap, 1), *out;
    cft_bn_copy(&x, a);
    cft_bn_set_u32(&chunk, 1000000000u);
    if (x.n == 0)
        rev[n++] = '0';
    while (x.n != 0) {
        uint32_t r9;
        int k;
        bn_divmod(&q, &rem, &x, &chunk);
        r9 = rem.n ? rem.v[0] : 0u;
        for (k = 0; k < 9 && (q.n != 0 || r9 != 0); k++) {
            rev[n++] = (char)('0' + r9 % 10u);
            r9 /= 10u;
        }
        cft_bn_copy(&x, &q);
    }
    out = (char *)xcalloc(n + 1, 1);
    for (i = 0; i < n; i++)
        out[i] = rev[n - 1 - i];
    free(rev);
    return out;
}

/* The canonical literal of the value frac_text spells - `[-]p` or
 * `[-]p/q`, lowest terms, no leading zero - into *out (the tool's): 0, 1
 * where `frac` is not frac_text's spelling, 2 past this build's bigint. */
static int literal_of(const char *frac, char **out)
{
    const char *body = frac[0] == '-' ? frac + 1 : frac;
    const char *slash = strchr(body, '/');
    size_t pn = slash ? (size_t)(slash - body) : strlen(body), i;
    size_t qn = slash ? strlen(slash + 1) : 0;
    int neg = frac[0] == '-';
    cft_bn p, q, g, five, t;
    char *ds, *res;
    int a, b = 0, k, lead;
    for (i = 0; i < pn; i++)
        if (body[i] < '0' || body[i] > '9')
            return 1;
    for (i = 0; slash && i < qn; i++)
        if (slash[1 + i] < '0' || slash[1 + i] > '9')
            return 1;
    if (pn == 0 || (pn > 1 && body[0] == '0') || (slash && (qn == 0 ||
        slash[1] == '0')) || (neg && pn == 1 && body[0] == '0'))
        return 1;
    if (bn_from_dec(&p, body, pn))
        return 2;
    if (slash) {
        if (bn_from_dec(&q, slash + 1, qn))
            return 2;
        if (bn_is_one(&q))
            return 1;                   /* p/1 is spelt p */
        if (bn_gcd(&g, &p, &q) || !bn_is_one(&g))
            return 1;                   /* not in lowest terms */
    } else {
        cft_bn_set_u32(&q, 1);
    }
    /* q = 2^a 5^b, or not: a decimal only where it is */
    a = bn_tz(&q);
    cft_bn_shr(&t, &q, a);
    cft_bn_set_u32(&five, 5);
    while (t.n != 0 && !bn_is_one(&t)) {
        cft_bn quo, rem;
        bn_divmod(&quo, &rem, &t, &five);
        if (rem.n != 0)
            break;
        cft_bn_copy(&t, &quo);
        b++;
    }
    if (bn_is_one(&t)) {
        /* |value| 10^k as an integer n, k = max(a, b): a value of at most
         * 24 significant digits never passes the bigint there (its n is
         * its digits), so one that does has more and is no decimal */
        cft_bn n, m;
        int ok = 1, e;
        size_t len, strip;
        k = a > b ? a : b;
        ok = !bn_shl(&n, &p, k - a);
        for (i = 0; ok && i < (size_t)(k - b); i++) {
            if (cft_bn_mul(&m, &n, &five))
                ok = 0;
            else
                cft_bn_copy(&n, &m);
        }
        if (ok) {
            ds = bn_to_dec(&n);
            len = strlen(ds);
            strip = len;
            while (strip > 1 && ds[strip - 1] == '0')
                strip--;
            if (strip <= LIT_DIGITS) {
                /* value = sign ds 10^e, ds without trailing zeros; its
                 * leading digit's weight is 10^lead */
                char *w;
                int point;
                ds[strip] = 0;
                e = -k + (int)(len - strip);
                lead = e + (int)strip - 1;
                res = (char *)xcalloc(strip + 48, 1);
                w = res;
                if (neg)
                    *w++ = '-';
                if (lead >= -6 && lead <= 20) {
                    if (e >= 0) {               /* ds, then e zeros */
                        memcpy(w, ds, strip);
                        w += strip;
                        for (i = 0; i < (size_t)e; i++)
                            *w++ = '0';
                    } else if ((point = (int)strip + e) > 0) {
                        memcpy(w, ds, (size_t)point);
                        w += point;
                        *w++ = '.';
                        memcpy(w, ds + point, strip - (size_t)point);
                        w += strip - (size_t)point;
                    } else {                    /* 0., zeros, ds */
                        *w++ = '0';
                        *w++ = '.';
                        for (i = 0; i < (size_t)(-point); i++)
                            *w++ = '0';
                        memcpy(w, ds, strip);
                        w += strip;
                    }
                    *w = 0;
                } else {                        /* d[.ddd]e<lead> */
                    *w++ = ds[0];
                    if (strip > 1) {
                        *w++ = '.';
                        memcpy(w, ds + 1, strip - 1);
                        w += strip - 1;
                    }
                    sprintf(w, "e%d", lead);
                }
                free(ds);
                *out = res;
                return 0;
            }
            free(ds);
        }
    }
    if (bn_is_one(&t) && b == 0 && a > 0) {
        /* dyadic and long: 0x1.<hex>p<exp>, as chars.to_hex writes an
         * encoding - the significand's bits after its leading one,
         * nibbles from the left, trailing zeros taken off */
        int bits = cft_bn_bitlen(&p), nib, exp;
        char *hx;
        size_t hl;
        lead = bits - 1;
        exp = -a + lead;
        nib = (lead + 3) / 4;
        cft_bn_copy(&t, &p);
        cft_bn_clearbit(&t, lead);
        res = (char *)xcalloc((size_t)nib + 64, 1);
        if (nib) {
            if (bn_shl(&t, &t, 4 * nib - lead))
                return 2;
            hx = (char *)xcalloc((size_t)CFT_BN_LIMBS * 8 + 2, 1);
            bn_hex(&t, hx);             /* lowercase, no leading zero */
            hl = strlen(hx);
            if (!strcmp(hx, "0"))
                hl = 0;
            /* zero-pad to nib digits, then strip the trailing zeros */
            {
                char *full = (char *)xcalloc((size_t)nib + 1, 1);
                size_t z = (size_t)nib - hl, end;
                memset(full, '0', z);
                memcpy(full + z, hx, hl);
                end = (size_t)nib;
                while (end > 0 && full[end - 1] == '0')
                    end--;
                full[end] = 0;
                sprintf(res, "%s0x1%s%sp%s%d", neg ? "-" : "",
                        end ? "." : "", full, exp >= 0 ? "+" : "-",
                        exp >= 0 ? exp : -exp);
                free(full);
            }
            free(hx);
        } else {
            sprintf(res, "%s0x1p%s%d", neg ? "-" : "", exp >= 0 ? "+" : "-",
                    exp >= 0 ? exp : -exp);
        }
        *out = res;
        return 0;
    }
    /* else p, or p/q, in full: frac_text's own spelling */
    res = (char *)xcalloc(strlen(frac) + 1, 1);
    strcpy(res, frac);
    *out = res;
    return 0;
}

/* ---- what a version-2 writer measures (docs/CERTIFICATES.md,
 * "Provenance") ---------------------------------------------------------- */

/* now, in UTC: YYYY-MM-DDTHH:MM:SSZ, or `unknown` where the clock does not
 * answer. gmtime reads POSIX time, which counts no leap second, so no
 * second is ever 60 (the reader's rule). */
static void utc_now(char out[24])
{
    time_t t = time(NULL);
    const struct tm *tm = t == (time_t)-1 ? NULL : gmtime(&t);
    if (!tm || tm->tm_sec > 59 ||
        strftime(out, 24, "%Y-%m-%dT%H:%M:%SZ", tm) != 20)
        snprintf(out, 24, "unknown");
}

/* The host's OS by name, lower case (`windows`, `linux`, or another
 * system's own name), with its version only on request: the kernel's
 * release for Linux, otherwise the system's version - as the golden
 * writer's host_os gives them (Python's platform.system, release and
 * version). Into a raw buffer, which the caller spells as a text. */
static void host_os_raw(char *out, size_t cap, int with_version)
{
#if defined(_WIN32)
    snprintf(out, cap, "windows");
    if (with_version) {
        typedef LONG (WINAPI *rtl_fn)(OSVERSIONINFOW *);
        HMODULE nt = GetModuleHandleA("ntdll.dll");
        rtl_fn rtl = NULL;
        OSVERSIONINFOW vi;
        if (nt) {
            FARPROC fp = GetProcAddress(nt, "RtlGetVersion");
            memcpy(&rtl, &fp, sizeof rtl);
        }
        memset(&vi, 0, sizeof vi);
        vi.dwOSVersionInfoSize = sizeof vi;
        if (rtl && rtl(&vi) == 0)
            snprintf(out, cap, "windows-%lu.%lu.%lu",
                     (unsigned long)vi.dwMajorVersion,
                     (unsigned long)vi.dwMinorVersion,
                     (unsigned long)vi.dwBuildNumber);
    }
#else
    struct utsname u;
    size_t i;
    if (uname(&u) != 0 || !u.sysname[0]) {
        snprintf(out, cap, "unknown");
        return;
    }
    snprintf(out, cap, "%s", u.sysname);
    for (i = 0; out[i]; i++)
        if (out[i] >= 'A' && out[i] <= 'Z')
            out[i] = (char)(out[i] - 'A' + 'a');
    if (with_version) {
        const char *rel = strcmp(out, "linux") ? u.version : u.release;
        size_t n = strlen(out);
        if (rel[0])
            snprintf(out + n, cap - n, "-%s", rel);
    }
#endif
}

/* The host's architecture, as the golden writer's host_arch names it:
 * amd64 and x86_64 as x86_64, arm64 and aarch64 as aarch64, any other
 * machine by its own name in lower case. Elsewhere that name is uname's;
 * on Windows it is the native architecture GetNativeSystemInfo reports,
 * named as Python's platform.machine names it there (CPython 3.12's
 * table: x86, MIPS, Alpha, PowerPC, ARM, ia64, AMD64, ARM64), and one that
 * table has no name for is `unknown`. */
static void host_arch_raw(char *out, size_t cap)
{
#if defined(_WIN32)
    SYSTEM_INFO si;
    const char *name;
    GetNativeSystemInfo(&si);
    switch (si.wProcessorArchitecture) {    /* PROCESSOR_ARCHITECTURE_* */
    case 0:  name = "x86";     break;       /* INTEL */
    case 1:  name = "mips";    break;
    case 2:  name = "alpha";   break;
    case 3:  name = "powerpc"; break;       /* PPC */
    case 5:  name = "arm";     break;
    case 6:  name = "ia64";    break;
    case 9:  name = "x86_64";  break;       /* AMD64 */
    case 12: name = "aarch64"; break;       /* ARM64 */
    default: name = "unknown"; break;
    }
    snprintf(out, cap, "%s", name);
#else
    struct utsname u;
    size_t i;
    if (uname(&u) != 0 || !u.machine[0]) {
        snprintf(out, cap, "unknown");
        return;
    }
    snprintf(out, cap, "%s", u.machine);
    for (i = 0; out[i]; i++)
        if (out[i] >= 'A' && out[i] <= 'Z')
            out[i] = (char)(out[i] - 'A' + 'a');
    if (!strcmp(out, "amd64"))
        snprintf(out, cap, "x86_64");
    else if (!strcmp(out, "arm64"))
        snprintf(out, cap, "aarch64");
#endif
}

/* The writer's list (docs/CERTIFICATES.md, "Provenance"): every variable
 * libcft and this tool read, the golden model's ENVIRONMENT_NAMES, in
 * byte order. segrun_check holds this table to that list, so a variable
 * joins it with the code that reads it. */
static const char *const ENV_NAMES[] = {
    "CFT_DIVSQRT_FULL", "CFT_DIVSQRT_SEQ", "CFT_SEGRUN_PLANT",
    "CFT_TIMEOUT_MS", "CFT_TRANSCEND_MINPREC", "CFT_XRT_BIND",
    "CFT_XRT_CAPS", "CFT_XRT_MASK_ADDR_OVERRIDE", "CFT_XRT_PROGRAM_CUTS",
    "CFT_XRT_REDUCE_BC", "CFT_XRT_TILES", "CFT_XRT_TILE_ORDER",
    "CFT_XRT_TRACE", "CFT_XRT_WITNESS", "XCL_EMULATION_MODE" };
#define N_ENV_NAMES (sizeof ENV_NAMES / sizeof ENV_NAMES[0])

/* ---- the hashes: cert_write.h's, refused by the name each returns ---- */

static void sha256_of(const void *data, size_t n, uint8_t out[32])
{
    cft_status st = cft_sha256(data, n, out);
    if (st != CFT_OK)
        refuse_st("device", "cft_sha256", st);
}

/* A file's SHA-256 as 64 lowercase hex digits (version 2's source, its
 * manifest's files, a replay image). */
static void sha_hex(const void *data, size_t n, char hex[65])
{
    uint8_t d[32];
    sha256_of(data, n, d);
    cw_hex(d, 32, hex);
}

/* A hash cert_write.h made, or the name it refused by: `memory` for a
 * buffer the hash needed, `device` for cft_sha256. */
static void hashed(const char *why, const char *what)
{
    if (why && !strcmp(why, "memory"))
        refuse("memory", "the buffer for %s's hash could not be allocated",
               what);
    if (why)
        refuse(why, "cft_sha256, hashing %s: %s", what, cft_last_error());
}

static void state_hash(const uint8_t *salt, const void *bytes, size_t n,
                       char hex[65])
{
    hashed(cw_state_hash(salt, bytes, n, hex), "a state");
}

static void stream_hash(const uint8_t *salt, int which, const void *bytes,
                        size_t n, char hex[65])
{
    hashed(cw_stream_hash(salt, which, bytes, n, hex), "a stream");
}

static void salt_commitment(const uint8_t *salt, char hex[65])
{
    hashed(cw_salt_commitment(salt, hex), "the salt's commitment");
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

    /* version 2 (docs/CERTIFICATES.md, "Version 2"), as given */
    int lane_flags_s;           /* --lane-flags */
    const char *replay_image_path, *replay_bank_path;
    const char *source_path, *manifest_path, *compiler_s;
    /* read and checked: whether the run asks for the per-lane block (it
     * says so, or its image needs flag control), its replay image, and
     * its source lines */
    int lane_flags, needs_fc;
    uint8_t *rimg, *rbank;
    size_t rimg_bytes, rbank_bytes;
    header RH;
    cft_program *rprog;
    char replay_digest[65];
    int has_source, compiled;   /* `source <digest>`; `compiler <name>` */
    char src_digest[65], src_name[CW_TEXT_MAX + 1], graph[65];
    char compiler_name[MAX_NAME + 1], target[CW_TEXT_MAX + 1];
    uint64_t compiler_version;
    size_t n_sparams;
    char **sparam_name, **sparam_lit;   /* names in byte order */
    /* made: each segment's block's hash, and each replay */
    char (*lanes_hash)[65];     /* segments 0..S-1, in a `yes` run */
    size_t n_replays, cap_replays;
    struct replay_rec {
        uint64_t segment, marked, changed;
        char raw_end[65], raw_lanes[65];
    } *replays;
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

/* Does a run's image hold a routine (C4): any of revision 8's QUIET,
 * ENDQUIET or RAISE (control codes 12, 13 and 14, R24)? A control word has
 * bit 31 set and its code in bits 7:0, both in the word's low half; the
 * words start after the header and, but under BANK_EXT, the constants.
 * check_run has held the header to the bytes. */
static int holds_routine(const run_spec *r)
{
    size_t off = HEADER_BYTES + ((r->H.flags & CFT_PROG_FLAG_BANK_EXT) ? 0u
                                 : (size_t)r->H.n_consts * r->esz);
    uint32_t k;
    for (k = 0; k < r->H.n_insns; k++) {
        uint32_t lo = get_le32(r->img + off + (size_t)k * 8u);
        uint32_t code = lo & 0xFFu;
        if ((lo >> 31) & 1u && (code == 12u || code == 13u || code == 14u))
            return 1;
    }
    return 0;
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

/* ---- version 2's header statements (docs/CERTIFICATES.md, "Version 2's
 * lines, in order", and "Provenance") -------------------------------------
 *
 * Each option's value is the line's own value, as the certificate spells
 * it: one of the words the line takes, or a text's one spelling - its
 * UTF-8 bytes percent-encoded, so that any value reaches the tool whole
 * through whatever made its command line (the tool reads that line as
 * Unicode, "the process's own text", above, but a shell, a script or a
 * console may spell it in a code page with no Ł for signed-fp64's
 * certificate-id); an
 * Ed25519 key or a body hash, 64 lowercase hex digits; a build in
 * build-id's grammar; or the `initial` line's tokens. The privacy
 * defaults (decisions 9 and 10): the issuer `withheld`, the device's
 * serial `withheld` where the library knows one, and host-os's name
 * without its version - each published only on request. */
static const char *ST_CERT_ID = NULL, *ST_ISSUER = NULL, *ST_KEY = NULL,
                  *ST_INITIAL = NULL, *ST_SUPERSEDES = NULL,
                  *ST_COMPILER_BUILD = NULL;
static int PUBLISH_SERIAL = 0, PUBLISH_OS_VERSION = 0;

/* A line's value: a word it takes (`words`, NULL-ended), or a text. */
static void check_word_or_text(const char *line, const char *v,
                               const char *const *words)
{
    size_t i;
    for (i = 0; words[i]; i++)
        if (!strcmp(v, words[i]))
            return;
    if (cw_is_word(v))
        refuse("malformed", "%s: the word '%s' does not stand on this line, "
               "which takes %s%s%s or a text", line, v, words[0],
               words[1] ? ", " : "", words[1] ? words[1] : "");
    if (!cw_text_ok(v))
        refuse("malformed", "%s '%.80s' is not a text in its one spelling: "
               "1 to %d characters, each byte from 0x21 to 0x7E but '%%' as "
               "itself, every other byte '%%' and two uppercase hex digits, "
               "UTF-8, and never one of the words none, unknown, withheld "
               "and given", line, v, CW_TEXT_MAX);
}

static void check_statements(void)
{
    static const char *const W_NONE[] = { "none", NULL };
    static const char *const W_ISSUER[] = { "none", "withheld", NULL };
    if (ST_CERT_ID)
        check_word_or_text("--certificate-id", ST_CERT_ID, W_NONE);
    if (ST_ISSUER)
        check_word_or_text("--issuer", ST_ISSUER, W_ISSUER);
    if (ST_KEY && strcmp(ST_KEY, "none") != 0) {
        unsigned char key[32];
        size_t i;
        if (!hex64_ok(ST_KEY))
            refuse("malformed", "--issuer-key '%.80s' is not an Ed25519 "
                   "public key - 64 lowercase hex digits - nor 'none'",
                   ST_KEY);
        for (i = 0; i < 32; i++)
            key[i] = (unsigned char)(hexnib(ST_KEY[2 * i]) << 4 |
                                     hexnib(ST_KEY[2 * i + 1]));
        switch (ed25519_key_check(key)) {
        case ED25519_KEY_NO_POINT:
            refuse("malformed", "--issuer-key %s: it encodes no point of the "
                   "curve, so it is no Ed25519 public key", ST_KEY);
            break;
        case ED25519_KEY_SMALL_ORDER:
            refuse("signer", "--issuer-key %s: a key of small order ([8]A "
                   "the identity): under it a signature nobody made "
                   "verifies for every message, so no holder vouches by it",
                   ST_KEY);
            break;
        default:
            break;
        }
    }
    if (ST_SUPERSEDES && strcmp(ST_SUPERSEDES, "none") != 0 &&
        !hex64_ok(ST_SUPERSEDES))
        refuse("malformed", "--supersedes '%.80s' is not a body hash - 64 "
               "lowercase hex digits, the superseded certificate's hash "
               "line - nor 'none'", ST_SUPERSEDES);
    if (ST_COMPILER_BUILD && strcmp(ST_COMPILER_BUILD, "none") != 0 &&
        !cw_build_id_ok(ST_COMPILER_BUILD))
        refuse("malformed", "--compiler-build '%.120s' is a build in "
               "cft_build_id()'s grammar - 'commit=<40 or 64 lowercase hex> "
               "tracked=<clean|modified> untracked=<none|present>' - or "
               "unknown or none", ST_COMPILER_BUILD);
    if (ST_INITIAL && strcmp(ST_INITIAL, "given") != 0) {
        /* `generator <name> <text> ...`: tokens separated by one space */
        const char *p = ST_INITIAL, *sp;
        char tok[CW_TEXT_MAX + 2];
        size_t n, args = 0;
        int k = 0;
        for (;;) {
            sp = strchr(p, ' ');
            n = sp ? (size_t)(sp - p) : strlen(p);
            if (n == 0 || n > CW_TEXT_MAX)
                refuse("malformed", "--initial '%.120s': 'given', or "
                       "'generator <name> <text> ...', its tokens separated "
                       "by one space, each a text of at most %d characters",
                       ST_INITIAL, CW_TEXT_MAX);
            memcpy(tok, p, n);
            tok[n] = 0;
            if (k == 0 && strcmp(tok, "generator") != 0)
                refuse("malformed", "--initial '%.120s': 'given', or "
                       "'generator <name> <text> ...'", ST_INITIAL);
            if (k == 1 && (!name_ok(tok, n) || cw_is_word(tok)))
                refuse("malformed", "--initial: generator name '%.80s' is not "
                       "[a-z][a-z0-9-]*, at most 64, or is one of the words "
                       "(none, unknown, withheld, given)", tok);
            if (k >= 2) {
                if (!cw_text_ok(tok))
                    refuse("malformed", "--initial: generator argument "
                           "'%.80s' is not a text in its one spelling", tok);
                args++;
            }
            k++;
            if (!sp)
                break;
            p = sp + 1;
        }
        if (k < 2)
            refuse("malformed", "--initial '%.120s': 'generator' needs its "
                   "name", ST_INITIAL);
        if (args > 16)
            refuse("malformed", "--initial: a generator takes at most 16 "
                   "arguments, and this one has %lu", (unsigned long)args);
    }
}

/* ---- a run's source, from cftc's manifest -------------------------------
 *
 * `--source SRC --manifest M`: the run names SRC, and its source lines come
 * from M, the manifest cftc wrote beside the image (docs/CERTIFICATES.md,
 * "Sources"). The tool has no interpreter of the language, so the graph's
 * digest and the source params' values are the manifest's, and each is
 * HELD TO THE FILES THE RUN RUNS, in this order:
 *   source-digest  SRC's SHA-256 is the manifest's source.sha256;
 *   source-graph   the manifest's format is the run's: its graph is the
 *                  step graph at the run's format, which the run's graph
 *                  line names;
 *   source-format  a main or half-step run's manifest has no format
 *                  override: the source's own format is the run's;
 *   source-shape   the manifest's scratch.in, the graph's lane - its
 *                  state, each tangent vector, its lane params - is the
 *                  image's slots a lane;
 *   source-image   compiled from (no --compiler none): the run's image is
 *                  the manifest's, and but for a half-step run, whose bank
 *                  is its relation's (aux-bank, the audit's), its bank too.
 * Then the lines' own spellings: the file name, the compiler's name and
 * target, each param's name and literal (`malformed`). A manifest this
 * tool cannot read - not JSON, not cftc's version 1, a field missing - is
 * a file the command line names that cannot be used (`usage`). */
static int cmp_names(const void *a, const void *b)
{
    const char *x = *(const char *const *)a, *y = *(const char *const *)b;
    return name_cmp(x, strlen(x), y, strlen(y));
}

static void check_source(run_spec *r, size_t idx)
{
    size_t sn, mn, i;
    uint8_t *src = read_named("the source", r->source_path, &sn);
    uint8_t *mtext = read_named("the manifest", r->manifest_path, &mn);
    const char *base, *s, *fmt_s, *image_sha, *bank_sha;
    const jv *x, *pa;
    jreader jr;
    jv *root;
    uint64_t lane_width;
    char hex[65];

    r->has_source = 1;
    r->compiled = r->compiler_s == NULL;
    sha_hex(src, sn, r->src_digest);
    free(src);

    /* the file's name, without its directories, as the system's own path
     * rules part them (the golden writer's Path.name): on Windows after
     * the last / or \ and past a drive's "X:", elsewhere after the last /
     * (a \ is a file name's character there) */
    base = r->source_path + strlen(r->source_path);
#if defined(_WIN32)
    while (base > r->source_path && base[-1] != '/' && base[-1] != '\\')
        base--;
    if (base == r->source_path && r->source_path[0] &&
        r->source_path[1] == ':' &&
        ((r->source_path[0] >= 'A' && r->source_path[0] <= 'Z') ||
         (r->source_path[0] >= 'a' && r->source_path[0] <= 'z')))
        base += 2;
#else
    while (base > r->source_path && base[-1] != '/')
        base--;
#endif
    if (cw_text_token((const unsigned char *)base, strlen(base), r->src_name))
        refuse("malformed", "run %lu: the source's file name '%.80s' cannot be "
               "spelt as a text - empty, not UTF-8, past 255 characters "
               "encoded, or one of the words", (unsigned long)idx, base);

    jr.p = (const char *)mtext;
    jr.end = (const char *)mtext + mn;
    jr.depth = 0;
    root = jvalue(&jr);
    if (root)
        jws(&jr);
    if (!root || jr.p != jr.end || root->t != J_OBJ)
        refuse("usage", "run %lu: the manifest %s is not a JSON object",
               (unsigned long)idx, r->manifest_path);
    free(mtext);
#define MAN_NEED(cond, what)                                               \
    do {                                                                    \
        if (!(cond))                                                        \
            refuse("usage", "run %lu: the manifest %s is not a manifest "   \
                   "cftc writes (version 1): %s", (unsigned long)idx,      \
                   r->manifest_path, what);                                 \
    } while (0)
    {
        uint64_t mv;
        MAN_NEED(juint(jget(root, "cftc_manifest"), &mv) && mv == 1,
                 "cftc_manifest is not 1");
    }
    s = jstr(jget(jget(root, "compiler"), "name"));
    MAN_NEED(s != NULL && juint(jget(jget(root, "compiler"), "version"),
                                &r->compiler_version),
             "compiler's name and version");
    if (strlen(s) > MAX_NAME || !name_ok(s, strlen(s)) || cw_is_word(s))
        refuse("malformed", "run %lu: the manifest's compiler '%.80s' is not "
               "a name - [a-z][a-z0-9-]*, at most 64, not one of the words - "
               "so no `compiler` line can spell it", (unsigned long)idx, s);
    strcpy(r->compiler_name, s);
    x = jget(jget(root, "source"), "sha256");
    MAN_NEED(x && (x->t == J_NULL || (x->t == J_STR && hex64_ok(x->s))),
             "source.sha256");
    s = jstr(jget(jget(root, "graph"), "sha256"));
    MAN_NEED(s && hex64_ok(s), "graph.sha256");
    strcpy(r->graph, s);
    fmt_s = jstr(jget(root, "format"));
    MAN_NEED(fmt_s && (!strcmp(fmt_s, "fp32") || !strcmp(fmt_s, "fp64") ||
                       !strcmp(fmt_s, "fp128") || !strcmp(fmt_s, "fp256")),
             "format");
    s = jstr(jget(jget(root, "target"), "name"));
    MAN_NEED(s != NULL, "target.name");
    if (cw_text_token((const unsigned char *)s, strlen(s), r->target))
        refuse("malformed", "run %lu: the manifest's target '%.80s' cannot be "
               "spelt as a text", (unsigned long)idx, s);
    image_sha = jstr(jget(jget(jget(root, "files"), "image"), "sha256"));
    MAN_NEED(image_sha && hex64_ok(image_sha), "files.image.sha256");
    bank_sha = jstr(jget(jget(jget(root, "files"), "bank"), "sha256"));
    MAN_NEED(!jget(jget(root, "files"), "bank") ||
             (bank_sha && hex64_ok(bank_sha)), "files.bank.sha256");
    MAN_NEED(juint(jget(jget(root, "scratch"), "in"), &lane_width),
             "scratch.in");
    pa = jget(root, "param_overrides");
    MAN_NEED(pa && pa->t == J_ARR, "param_overrides");
    for (i = 0; i < pa->n; i++)
        MAN_NEED(jstr(jget(pa->kid[i], "name")) &&
                 jstr(jget(pa->kid[i], "value")),
                 "a param override's name and value");

    /* the source and the files the run runs */
    if (x->t == J_NULL)
        refuse("source-digest", "run %lu: the manifest %s names no source "
               "file's SHA-256 - it was compiled from a step graph, not from "
               "a file - so nothing holds %s to it", (unsigned long)idx,
               r->manifest_path, r->source_path);
    if (strcmp(x->s, r->src_digest) != 0)
        refuse("source-digest", "run %lu: %s's SHA-256 is %.16s..., and the "
               "manifest's source is %.16s...: the manifest is another "
               "source's", (unsigned long)idx, r->source_path, r->src_digest,
               x->s);
    if (strcmp(fmt_s, FORMAT_NAME[r->H.prec]) != 0)
        refuse("source-graph", "run %lu: the manifest's step graph is at %s, "
               "and the run is %s: the run's graph line is the graph at its "
               "own format, which this manifest does not name",
               (unsigned long)idx, fmt_s, FORMAT_NAME[r->H.prec]);
    {
        const jv *ov = jget(jget(root, "source"), "format_override");
        if (ov && ov->t != J_NULL && (r->kind == K_MAIN || r->kind == K_HALF))
            refuse("source-format", "run %lu (%s): the manifest compiled the "
                   "source at %s by a format override, from its own %s, and "
                   "a %s run's format is its source's own (only a "
                   "wider-source run is the source one rung up)",
                   (unsigned long)idx, KIND_NAME[r->kind], fmt_s,
                   jstr(jget(ov, "source")) ? jstr(jget(ov, "source"))
                                            : "format",
                   KIND_NAME[r->kind]);
    }
    if (lane_width != r->H.n_in)
        refuse("source-shape", "run %lu: the image's lane is %u slots and its "
               "source's is %llu (its state, each tangent vector and its lane "
               "params: the manifest's scratch.in)", (unsigned long)idx,
               (unsigned)r->H.n_in, (unsigned long long)lane_width);
    if (r->compiled) {
        sha_hex(r->img, r->img_bytes, hex);
        if (strcmp(hex, image_sha) != 0)
            refuse("source-image", "run %lu: the image %s is not the "
                   "manifest's compile (%.16s..., the manifest %.16s...); a "
                   "run whose image is not its source's compile says "
                   "--compiler none", (unsigned long)idx, r->image_path, hex,
                   image_sha);
        if (r->kind != K_HALF) {
            int same;
            if (r->bank_bytes) {
                sha_hex(r->bank, r->bank_bytes, hex);
                same = bank_sha && !strcmp(hex, bank_sha);
            } else {
                same = bank_sha == NULL;
            }
            if (!same)
                refuse("source-image", "run %lu: the bank %s is not the "
                       "manifest's compile's bank", (unsigned long)idx,
                       r->bank_path ? r->bank_path : "(none)");
        }
    }

    /* the source params: each override's name, and its literal */
    r->n_sparams = pa->n;
    r->sparam_name = (char **)xcalloc(pa->n ? pa->n : 1, sizeof(char *));
    r->sparam_lit = (char **)xcalloc(pa->n ? pa->n : 1, sizeof(char *));
    for (i = 0; i < pa->n; i++) {
        const char *nm = jstr(jget(pa->kid[i], "name"));
        size_t k, len = strlen(nm);
        int ok = len > 0 && ((nm[0] >= 'A' && nm[0] <= 'Z') ||
                             (nm[0] >= 'a' && nm[0] <= 'z') || nm[0] == '_');
        for (k = 1; ok && k < len; k++)
            ok = (nm[k] >= 'A' && nm[k] <= 'Z') ||
                 (nm[k] >= 'a' && nm[k] <= 'z') ||
                 (nm[k] >= '0' && nm[k] <= '9') || nm[k] == '_';
        if (!ok)
            refuse("malformed", "run %lu: source param '%.80s' is not a name "
                   "of the language: a letter or '_', then letters, digits "
                   "and '_'", (unsigned long)idx, nm);
        r->sparam_name[i] = (char *)xcalloc(len + 1, 1);
        memcpy(r->sparam_name[i], nm, len);
    }
    qsort(r->sparam_name, pa->n, sizeof(char *), cmp_names);
    for (i = 0; i < pa->n; i++) {
        size_t k;
        const char *val = NULL;
        int st;
        for (k = 0; k < pa->n; k++)
            if (!strcmp(jstr(jget(pa->kid[k], "name")), r->sparam_name[i]))
                val = jstr(jget(pa->kid[k], "value"));
        if (i && !strcmp(r->sparam_name[i], r->sparam_name[i - 1]))
            refuse("usage", "run %lu: the manifest overrides param %s twice",
                   (unsigned long)idx, r->sparam_name[i]);
        st = literal_of(val, &r->sparam_lit[i]);
        if (st == 1)
            refuse("usage", "run %lu: the manifest's value for param %s, "
                   "'%.80s', is not an exact value as the step graph writes "
                   "it (p or p/q in lowest terms)", (unsigned long)idx,
                   r->sparam_name[i], val);
        if (st == 2)
            refuse("build-width", "run %lu: param %s's value, %.40s..., is "
                   "past this build's %d-bit bigint, in which its canonical "
                   "literal is computed; it refuses rather than spell it "
                   "otherwise", (unsigned long)idx, r->sparam_name[i], val,
                   CFT_BN_LIMBS * 32);
    }
    jfree(root);
#undef MAN_NEED
}

/* Everything version 2 adds to a run's checks, after check_run's: whether
 * it asks for the per-lane block, its source, and its replay image. */
static void check_run_v2(run_spec *r, size_t idx)
{
    char why[256];
    const char *bad;
    if (r->replay_bank_path && !r->replay_image_path)
        refuse("usage", "run %lu: --replay-bank is a replay image's bank; "
               "give --replay-image too", (unsigned long)idx);
    if ((r->source_path == NULL) != (r->manifest_path == NULL))
        refuse("usage", "run %lu: --source and --manifest go together: the "
               "run's source lines are the manifest's, held to the source "
               "file", (unsigned long)idx);
    if (r->compiler_s && !r->source_path)
        refuse("usage", "run %lu: --compiler none says how the run's image "
               "stands to its source, and the run names none",
               (unsigned long)idx);
    r->needs_fc = holds_routine(r);
    r->lane_flags = r->lane_flags_s || r->needs_fc;
    if (r->source_path)
        check_source(r, idx);
    if (!r->replay_image_path)
        return;
    if (!r->source_path)
        refuse("replay-source", "run %lu: --replay-image replays a marked lane "
               "by its definition, and the run names no source that gives "
               "one (--source SRC --manifest M)", (unsigned long)idx);
    r->rimg = read_named("the replay image", r->replay_image_path,
                         &r->rimg_bytes);
    bad = parse_header(r->rimg, r->rimg_bytes, &r->RH, why, sizeof why);
    if (bad)
        refuse("program-image", "run %lu: the replay image %s does not load: "
               "%s", (unsigned long)idx, r->replay_image_path, bad);
    if (r->RH.prec != r->H.prec)
        refuse("program-format", "run %lu: the replay image %s is %s, and the "
               "run is %s", (unsigned long)idx, r->replay_image_path,
               FORMAT_NAME[r->RH.prec], FORMAT_NAME[r->H.prec]);
    bad = segment_shape(&r->RH, why, sizeof why);
    if (bad)
        refuse("program-shape", "run %lu: the replay image %s is not a "
               "segment: %s", (unsigned long)idx, r->replay_image_path, bad);
    if (r->RH.n_in != r->H.n_in)
        refuse("source-shape", "run %lu: the replay image's lane is %u slots "
               "and the run's is %u: a replayed lane is the run's lane",
               (unsigned long)idx, (unsigned)r->RH.n_in, (unsigned)r->H.n_in);
    if (r->replay_bank_path)
        r->rbank = read_named("the replay bank", r->replay_bank_path,
                              &r->rbank_bytes);
    if (r->RH.flags & CFT_PROG_FLAG_BANK_EXT) {
        uint64_t want = (uint64_t)r->RH.n_consts * r->esz;
        if ((uint64_t)r->rbank_bytes != want)
            refuse("program-image", "run %lu: the replay bank is %lu bytes; "
                   "the replay image addresses %u constants of %lu bytes, %llu "
                   "in all (--replay-bank)", (unsigned long)idx,
                   (unsigned long)r->rbank_bytes, (unsigned)r->RH.n_consts,
                   (unsigned long)r->esz, (unsigned long long)want);
    } else if (r->rbank_bytes) {
        refuse("program-image", "run %lu: the replay image carries its own "
               "constants, so --replay-bank must be empty; %s is %lu bytes",
               (unsigned long)idx, r->replay_bank_path,
               (unsigned long)r->rbank_bytes);
    }
    sha_hex(r->rimg, r->rimg_bytes, r->replay_digest);
}

/* ---- the certificate's text: cert_write.h's, refused by name ----------- */

typedef cw_text text;

/* A line or a piece of one, or the refusal: `output` for a line that
 * cannot be formatted, `memory` for text that cannot grow (from 4,096
 * bytes doubled, as the trial counts it: try_runs). */
static void lines_ok(const char *why)
{
    if (why && !strcmp(why, "output"))
        refuse("output", "a certificate line could not be formatted");
    if (why)
        refuse(why, "the certificate's text could not grow");
}

static void put(text *t, const char *fmt, ...) PRINTF_LIKE(2, 3);

static void put(text *t, const char *fmt, ...)
{
    va_list ap;
    const char *why;
    va_start(ap, fmt);
    why = cw_vput(t, fmt, ap);
    va_end(ap);
    lines_ok(why);
}

/* ---- identity: cert_write.h's, from the library and nowhere else ------- */

typedef cw_identity identity;

static void identify(cft_device *dev, const cft_caps *caps, identity *id)
{
    if (cw_identify(dev, caps, id))
        refuse("malformed", "cft_build_id() returned '%s', which is not the "
               "page's grammar; the build-id line is that string verbatim, "
               "so no certificate can be written from it",
               id->build_id ? id->build_id : "(null)");
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
    f = u8_create_new(path);
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

/* Version 2's files beside the boundaries (docs/CERTIFICATES.md, "The
 * per-lane flags" and "A marked lane and its replay"):
 *   DIR/run-<r>-segment-<k>.flags        a segment's certified block
 *   DIR/run-<r>-segment-<k>-raw.bin      a replayed segment's raw end
 *   DIR/run-<r>-segment-<k>-raw.flags    and its raw block
 * each created new, as a boundary file is; `tail` is ".flags",
 * "-raw.bin" or "-raw.flags". An audit needs none of them: a re-run
 * recomputes each. */
static void write_side(size_t r, uint64_t k, const char *tail,
                       const void *bytes, size_t n)
{
    size_t cap = strlen(STATES_DIR) + PATH_TAIL + 16;
    char *path = (char *)xcalloc(cap, 1);
    FILE *f;
    snprintf(path, cap, "%s/run-%lu-segment-%llu%s", STATES_DIR,
             (unsigned long)r, (unsigned long long)k, tail);
    f = u8_create_new(path);
    if (!f)
        refuse("output", "%s cannot be created (%s)", path,
               errno == EEXIST ? "a file this run did not make is there "
                                 "already" : strerror(errno));
    SIDE_FILES++;
    if (n && fwrite(bytes, 1, n, f) != n) {
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
/* Version 2's: a segment line's " lanes " and its hash (71 bytes); a
 * replay line, at most 194 ("replay " and three 19-digit numbers, the
 * words, two hashes, the LF) - counted at most for every segment of a run
 * that can replay; the source lines, under 1 KiB beside each param's,
 * whose literal is at most a bigint's decimal; the header's lines past
 * version 1's - the texts at 255 characters, sixteen generator arguments,
 * the environment's fifteen variables - under 16 KiB. */
#define SEGMENT_LANES_TEXT 72
#define REPLAY_TEXT        200
#define SOURCE_TEXT        1024
#define SPARAM_TEXT        (64 + 16 * CFT_BN_LIMBS)
#define HEAD_TEXT_V2       16384

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
    /* version 2 keeps a fourth piece a run, its blocks' hashes */
    const size_t per = FORMAT_VERSION == 2 ? 4u : 3u;

    if (FORMAT_VERSION == 2)
        text_max += HEAD_TEXT_V2;

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
        if (!add_ok(&b, lead + CW_TAG_STREAM_LEN) || !add_ok(&b, path))
            refuse("memory", "run %lu: its state is past what this process "
                   "can address", (unsigned long)r);
        if (FORMAT_VERSION == 2) {
            /* each block's hash, kept; each segment line's lanes pair, and
             * a replay line for every segment of a run that can replay;
             * its source lines */
            size_t lh = 0, t2 = 0, t2min = 0, rp = 0;
            int ok2 = 1;
            if (R->lane_flags)
                ok2 = mul_ok(S, sizeof *R->lanes_hash, &lh) &&
                      mul_ok(S, SEGMENT_LANES_TEXT, &t2) &&
                      mul_ok(S, SEGMENT_LANES_TEXT - 1, &t2min);
            if (ok2 && R->replay_image_path)
                ok2 = mul_ok(S, REPLAY_TEXT, &rp) && add_ok(&t2, rp);
            ok2 = ok2 && mul_ok(R->n_sparams, SPARAM_TEXT, &rp) &&
                  add_ok(&t2, rp) && add_ok(&t2, SOURCE_TEXT) &&
                  add_ok(&text_max, t2) && add_ok(&text_min, t2min);
            if (!ok2)
                refuse("memory", "run %lu: %llu segments need more memory "
                       "than this process can address - their per-lane "
                       "blocks' hashes, or the certificate's text",
                       (unsigned long)r, (unsigned long long)R->segments);
        }
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
        trial *kept, now[8];
        if (!mul_ok(per * sizeof *kept, n_runs, &list) ||
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
            trial_or_refuse(&kept[per * r], S + 1, sizeof *R->hash, ri,
                            "the boundary hashes");
            trial_or_refuse(&kept[per * r + 1], S, sizeof(uint32_t), ri,
                            "the flag words");
            trial_or_refuse(&kept[per * r + 2], S, sizeof(uint32_t), ri,
                            "STATUS");
            if (per > 3)
                trial_or_refuse(&kept[per * r + 3],
                                R->lane_flags ? S : 0,
                                sizeof *R->lanes_hash, ri,
                                "the per-lane blocks' hashes");
            trial_or_refuse(&now[0], R->state_bytes, 1, ri, "a state");
            trial_or_refuse(&now[1], R->state_bytes, 1, ri, "a state");
            trial_or_refuse(&now[2], R->lanes, R->esz, ri, "the streams");
            for (i = 3; i < 8; i++) {
                now[i].p = NULL;
                now[i].n = 0;
            }
            if (FORMAT_VERSION == 2 && R->lane_flags)
                trial_or_refuse(&now[3], R->lanes, 1, ri,
                                "the per-lane block");
            if (FORMAT_VERSION == 2 && R->replay_image_path) {
                /* a replay: the raw end kept beside the corrected one, the
                 * marked lanes' start and end, and their blocks */
                trial_or_refuse(&now[4], R->state_bytes, 1, ri,
                                "a raw end state");
                trial_or_refuse(&now[5], R->state_bytes, 1, ri,
                                "the marked lanes' start");
                trial_or_refuse(&now[6], R->state_bytes, 1, ri,
                                "the marked lanes' end");
                trial_or_refuse(&now[7], 2 * R->lanes, 1, ri,
                                "the raw and replayed blocks");
            }
            for (i = 0; i < 8; i++)
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
        for (i = 0; i < per * n_runs; i++)
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

    /* version 1's three methods, and version 2's wider-source beside them
     * (an estimate on a wider-source run) */
    for (k = 0; k < (FORMAT_VERSION == 2 ? 4 : 3) &&
                strcmp(X->method_s, METHOD_NAME[k]) != 0; k++)
        ;
    if (k == (FORMAT_VERSION == 2 ? 4 : 3))
        refuse("malformed", "entry %lu: method '%.40s' is not drift, "
               "step-halving or wider%s", (unsigned long)j, X->method_s,
               FORMAT_VERSION == 2 ? ", or version 2's wider-source" : "");
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
    f = u8_fopen(path, "rb");
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

#endif /* CX_EXACT */

/* The accuracy block, in the page's order and spellings (cert._body_lines):
 * `accuracy <A>`, then each entry's lines, which are cert_write.h's
 * (cw_entry_lines, this function's own until the steps-5-and-6 round's
 * parcel S3 took it whole for cft-orbits). With no --entry it is
 * `accuracy 0`, byte for byte what the tool wrote before step 5. */
static void put_accuracy(text *t, const entry_spec *entries, size_t n,
                         cft_device *arith)
{
    put(t, "accuracy %llu\n", (unsigned long long)n);
#if CX_EXACT
    {
        size_t j;
        char why[512];
        for (j = 0; j < n; j++) {
            const char *e = cw_entry_lines(t, j, &entries[j].E,
                                           entries[j].label_s, arith, why,
                                           sizeof why);
            if (e && !strcmp(e, "output"))
                lines_ok(e);            /* a line that cannot be formatted */
            if (e)
                refuse(e, "%s could not be made", why);
        }
    }
#else
    (void)entries;
    (void)arith;
#endif
}

/* ---- a run block's own lines, both versions -------------------------------- */

/* `run <i> main`, `run <i> half-step h-slots <n> <slot> ...`, `run <i>
 * wider` and, in version 2, `run <i> wider-source`. */
static void put_run_line(text *t, size_t r, const run_spec *R)
{
    size_t j;
    if (R->kind == K_HALF) {
        put(t, "run %llu half-step h-slots %llu", (unsigned long long)r,
            (unsigned long long)R->n_hslots);
        for (j = 0; j < R->n_hslots; j++)
            put(t, " %u", R->hslots[j]);
        put(t, "\n");
    } else {
        put(t, "run %llu %s\n", (unsigned long long)r, KIND_NAME[R->kind]);
    }
}

/* `parameters <p>` and each `parameter`: --scratch-depth's parameter in
 * its place in byte order among the run's own, which are in that order
 * already (check_run), and none of which is named as it is (refused as
 * usage). */
static void put_parameters(text *t, const run_spec *R)
{
    size_t j;
    int depth_put = SCRATCH_DEPTH == 0;
    put(t, "parameters %llu\n", (unsigned long long)R->n_param_s +
        (SCRATCH_DEPTH ? 1u : 0u));
    for (j = 0; j < R->n_param_s; j++) {
        const char *s = R->param_s[j];
        const char *eq = strchr(s, '=');
        if (!depth_put && name_cmp(DEPTH_PARAM, DEPTH_PARAM_LEN, s,
                                   (size_t)(eq - s)) < 0) {
            put(t, "parameter %s %lu\n", DEPTH_PARAM,
                (unsigned long)SCRATCH_DEPTH);
            depth_put = 1;
        }
        put(t, "parameter %.*s %s\n", (int)(eq - s), s, eq + 1);
    }
    if (!depth_put)
        put(t, "parameter %s %lu\n", DEPTH_PARAM,
            (unsigned long)SCRATCH_DEPTH);
}

/* ---- version 2's header and run blocks (docs/CERTIFICATES.md, "Version
 * 2's lines, in order"; the golden writer's cert2._header_lines and
 * _run_lines) -------------------------------------------------------------- */

/* the measured lines that do not change while the tool runs, taken before
 * anything is made so that one no text can spell is refused with nothing
 * made (an environment variable's value), and the environment's lines */
static char HOST_OS[CW_TEXT_MAX + 1], HOST_ARCH[CW_TEXT_MAX + 1];
static char *ENV_TOK[sizeof ENV_NAMES / sizeof ENV_NAMES[0]];

/* An environment variable's value as the process has it ("the process's
 * own text", above), malloc'd: NULL where it is unset or set empty, and
 * then *bad set where it is set to a value with no UTF-8 spelling (on
 * Windows, an unpaired surrogate; elsewhere the bytes are handed on, and
 * the text's own check refuses bytes that are not UTF-8). */
static char *env_text(const char *name, int *bad)
{
#if defined(_WIN32)
    wchar_t wname[80], *w;
    DWORD n, m;
    char *s;
    *bad = 0;
    if (!MultiByteToWideChar(CP_UTF8, 0, name, -1, wname, 80))
        return NULL;
    for (;;) {
        n = GetEnvironmentVariableW(wname, NULL, 0);
        if (n <= 1)                     /* unset, or set empty */
            return NULL;
        w = (wchar_t *)xcalloc(n, sizeof *w);
        m = GetEnvironmentVariableW(wname, w, n);
        if (m < n)
            break;
        free(w);                        /* it grew between the two calls */
    }
    if (m == 0) {
        free(w);
        return NULL;
    }
    s = u8_of_wide(w);
    free(w);
    if (!s && errno == ENOMEM)
        refuse("memory", "the environment variable %s's value could not be "
               "held in UTF-8", name);
    *bad = s == NULL;
    return s;
#else
    const char *v = getenv(name);
    char *s;
    *bad = 0;
    if (!v || !*v)
        return NULL;
    s = (char *)xcalloc(strlen(v) + 1, 1);
    memcpy(s, v, strlen(v) + 1);
    return s;
#endif
}

static void measure_host(void)
{
    char raw[512];
    size_t i;
    host_os_raw(raw, sizeof raw, PUBLISH_OS_VERSION);
    if (!strcmp(raw, "unknown") ||
        cw_text_token((const unsigned char *)raw, strlen(raw), HOST_OS))
        snprintf(HOST_OS, sizeof HOST_OS, "unknown");
    host_arch_raw(raw, sizeof raw);
    if (!strcmp(raw, "unknown") ||
        cw_text_token((const unsigned char *)raw, strlen(raw), HOST_ARCH))
        snprintf(HOST_ARCH, sizeof HOST_ARCH, "unknown");
    /* the writer's list's variables that are set: one set to the empty
     * string counts as unset (libcft's rule, since cmd and PowerShell
     * remove a variable set empty) */
    for (i = 0; i < N_ENV_NAMES; i++) {
        int bad;
        char *v = env_text(ENV_NAMES[i], &bad);
        ENV_TOK[i] = NULL;
        if (bad)
            refuse("malformed", "the environment variable %s is set to a "
                   "value with no UTF-8 spelling (an unpaired surrogate), "
                   "which no text can spell, and a version-2 certificate "
                   "writes every variable of the writer's list that is set",
                   ENV_NAMES[i]);
        if (!v)
            continue;
        ENV_TOK[i] = (char *)xcalloc(CW_TEXT_MAX + 1, 1);
        if (cw_text_token((const unsigned char *)v, strlen(v), ENV_TOK[i]))
            refuse("malformed", "the environment variable %s is set to a "
                   "value no text can spell (empty, not UTF-8, past 255 "
                   "characters encoded, or one of the words none, unknown, "
                   "withheld and given), and a version-2 certificate writes "
                   "every variable of the writer's list that is set: %.80s",
                   ENV_NAMES[i], v);
        free(v);
    }
}

static void version_text(char out[48], int major, int minor)
{
    if (minor)
        snprintf(out, 48, "%d.%d", major, minor);
    else
        snprintf(out, 48, "%d", major);
}

static void put_v2_header(text *t, const uint8_t *salt, const identity *id,
                          const run_spec *runs, size_t n_runs)
{
    char commitment[65], v[48], issued[24];
    size_t r, i, n_env = 0, n_methods = 0;
    int any_source = 0, any_compiled = 0;
    for (r = 0; r < n_runs; r++) {
        any_source |= runs[r].has_source;
        any_compiled |= runs[r].has_source && runs[r].compiled;
        n_methods += runs[r].n_replays > 0;
    }
    put(t, "cft-certificate 2\n");
    if (salt)
        salt_commitment(salt, commitment);
    lines_ok(cw_identity_lines(t, salt ? commitment : NULL, id));
    version_text(v, CFT_PROFILE_MAJOR, CFT_PROFILE_MINOR);
    put(t, "profile %s\n", v);
    version_text(v, CFT_LANGUAGE_MAJOR, CFT_LANGUAGE_MINOR);
    put(t, "language %s\n", any_source ? v : "none");
    put(t, "device-platform %s\ndevice-xrt %s\ndevice-clock %s\n",
        id->platform, id->xrt, id->clock);
    put(t, "device-serial %s\n", id->no_card ? "none" :
        !id->serial[0] ? "unknown" : PUBLISH_SERIAL ? id->serial
                                                    : "withheld");
    put(t, "writer cft-segrun %s\n", id->build_id);
    put(t, "writer-runtime none\n");
    put(t, "compiler-build %s\n", ST_COMPILER_BUILD ? ST_COMPILER_BUILD :
        any_compiled ? "unknown" : "none");
    put(t, "replay-methods %llu\n", (unsigned long long)n_methods);
    for (r = 0; r < n_runs; r++)
        if (runs[r].n_replays)
            put(t, "replay-method %llu image %s\n", (unsigned long long)r,
                runs[r].replay_digest);
    put(t, "certificate-id %s\n", ST_CERT_ID ? ST_CERT_ID : "none");
    put(t, "issuer %s\n", ST_ISSUER ? ST_ISSUER : "withheld");
    put(t, "issuer-key %s\n", ST_KEY ? ST_KEY : "none");
    put(t, "host-os %s\nhost-arch %s\n", HOST_OS, HOST_ARCH);
    /* the times, each pair of known ones in order (started, finished,
     * issued): only a clock that went back while the tool ran breaks it,
     * and the golden writer refuses such times by the reader's name */
    utc_now(issued);
    if (strcmp(T_STARTED, "unknown") && strcmp(T_FINISHED, "unknown") &&
        strcmp(T_STARTED, T_FINISHED) > 0)
        refuse("provenance-order", "the system clock went back while the "
               "runs ran: they started at %s and finished at %s", T_STARTED,
               T_FINISHED);
    if (strcmp(issued, "unknown") &&
        ((strcmp(T_FINISHED, "unknown") && strcmp(T_FINISHED, issued) > 0) ||
         (strcmp(T_STARTED, "unknown") && strcmp(T_STARTED, issued) > 0)))
        refuse("provenance-order", "the system clock went back before the "
               "certificate was written: the runs finished at %s and it is "
               "now %s", T_FINISHED, issued);
    put(t, "started %s\nfinished %s\nissued %s\n", T_STARTED, T_FINISHED,
        issued);
    put(t, "supersedes %s\n", ST_SUPERSEDES ? ST_SUPERSEDES : "none");
    for (i = 0; i < N_ENV_NAMES; i++)
        n_env += ENV_TOK[i] != NULL;
    put(t, "environment %llu\n", (unsigned long long)n_env);
    for (i = 0; i < N_ENV_NAMES; i++)
        if (ENV_TOK[i])
            put(t, "env %s %s\n", ENV_NAMES[i], ENV_TOK[i]);
    put(t, "initial %s\n", ST_INITIAL ? ST_INITIAL : "given");
    put(t, "runs %llu\n", (unsigned long long)n_runs);
}

static void put_v2_run(text *t, size_t r, const run_spec *R)
{
    uint64_t k;
    size_t i;
    put_run_line(t, r, R);
    put(t, "program-format %s\nprogram-image %s\nprogram-digest %s\n",
        FORMAT_NAME[R->H.prec], R->image_digest, R->program_digest);
    if (!R->has_source) {
        put(t, "source none\n");
    } else {
        put(t, "source %s\nsource-name %s\ngraph %s\n", R->src_digest,
            R->src_name, R->graph);
        if (R->compiled)
            put(t, "compiler %s %llu %s\n", R->compiler_name,
                (unsigned long long)R->compiler_version, R->target);
        else
            put(t, "compiler none\n");
        put(t, "source-params %llu\n", (unsigned long long)R->n_sparams);
        for (i = 0; i < R->n_sparams; i++)
            put(t, "source-param %s %s\n", R->sparam_name[i],
                R->sparam_lit[i]);
    }
    put(t, "lanes %llu\nsteps %llu\nstream-a %s\nstream-b %s\nstream-c %s\n",
        (unsigned long long)R->lanes, (unsigned long long)R->steps,
        R->stream_hash[0], R->stream_hash[1], R->stream_hash[2]);
    put_parameters(t, R);
    put(t, "lane-flags %s\n", R->lane_flags ? "yes" : "no");
    put(t, "segments %llu\n", (unsigned long long)R->segments);
    for (k = 0; k < R->segments; k++) {
        put(t, "segment %llu start %s end %s flags %u status %u",
            (unsigned long long)k, R->hash[k], R->hash[k + 1],
            (unsigned)R->flags[k], (unsigned)R->status[k]);
        if (R->lane_flags)
            put(t, " lanes %s", R->lanes_hash[k]);
        put(t, "\n");
    }
    put(t, "replays %llu\n", (unsigned long long)R->n_replays);
    for (i = 0; i < R->n_replays; i++)
        put(t, "replay %llu marked %llu changed %llu raw-end %s raw-lanes "
            "%s\n", (unsigned long long)R->replays[i].segment,
            (unsigned long long)R->replays[i].marked,
            (unsigned long long)R->replays[i].changed,
            R->replays[i].raw_end, R->replays[i].raw_lanes);
    put(t, "output %s\n", R->hash[R->segments]);
}

/* ---- version 2: a marked lane and its replay ----------------------------
 *
 * docs/CERTIFICATES.md, "A marked lane and its replay". A segment whose
 * block marks a lane (byte [7], R24's raise with bit 7: its routine could
 * not decide that lane's last bit) is certified as the DEFINITION's
 * segment. This tool has no interpreter of the language, so it replays by
 * the producer's shortcut the contract allows, a slower image of the same
 * source (`--replay-image`, its constants in `--replay-bank`): run once
 * over the marked lanes, each from its certified start - this segment's
 * start state - with its own per-lane block. Then:
 *   - each marked lane's end values are the replay's, and its byte the
 *     replay's five IEEE flags with the raw [6:5] and [7] clear;
 *   - the flag word is the OR of the corrected bytes' [4:0], and STATUS
 *     the raw STATUS with STATUS[6] cleared;
 *   - `changed` counts the marked lanes whose values the replay moved;
 *   - the raw end state and raw block are hashed for the replay line and
 *     written beside the boundaries (run-<r>-segment-<k>-raw.bin and
 *     -raw.flags).
 * The audit holds every replayed value to the golden definition, whatever
 * replayed it, so a replay image is never handed to an auditor; its
 * answer is accepted exactly when it is the definition's. Refused:
 *   replay-source     the run names no source (the golden writer's name)
 *   replay-missing    it names one, and was handed no replay image
 *   replay-undecided  the replay image marks the lane too (exit 78, the
 *                     writer's own limit) */
static void replay_segment(run_spec *R, size_t r, uint64_t k,
                           const uint8_t *start, uint8_t *end, uint8_t *blk,
                           const uint8_t *zero, uint32_t *fl, uint32_t *bus,
                           const uint8_t *salt)
{
    size_t lane = (size_t)R->H.n_in * R->esz, m = 0, i, j;
    uint8_t *raw, *rawblk, *rin, *rout, *rblk;
    uint64_t changed = 0;
    uint32_t rfl = 0xFFFFFFFFu, rbus = 0, f;
    cft_run_args ra;
    cft_status st;
    struct replay_rec *rec;

    for (i = 0; i < R->lanes; i++)
        m += (blk[i] & CFT_LANE_MARKED) != 0;
    if (m == 0)
        return;
    if (!R->has_source)
        refuse("replay-source", "run %lu segment %llu marks %lu lane%s, and "
               "the run names no source whose definition could replay %s "
               "(--source SRC --manifest M)", (unsigned long)r,
               (unsigned long long)k, (unsigned long)m, m == 1 ? "" : "s",
               m == 1 ? "it" : "them");
    if (!R->rprog)
        refuse("replay-missing", "run %lu segment %llu marks %lu lane%s, and "
               "the run was handed no replay image (--replay-image IMG): "
               "this tool has no interpreter of the language, so it replays "
               "a marked lane by an image of its source that decides it",
               (unsigned long)r, (unsigned long long)k, (unsigned long)m,
               m == 1 ? "" : "s");
    raw = (uint8_t *)run_take(R->state_bytes, 1, r, "a raw end state");
    rawblk = (uint8_t *)run_take(R->lanes, 1, r, "a raw block");
    rin = (uint8_t *)run_take(m, lane, r, "the marked lanes' start");
    rout = (uint8_t *)run_take(m, lane, r, "the marked lanes' end");
    rblk = (uint8_t *)run_take(m, 1, r, "the replayed block");
    memcpy(raw, end, R->state_bytes);
    memcpy(rawblk, blk, R->lanes);
    for (i = 0, j = 0; i < R->lanes; i++)
        if (blk[i] & CFT_LANE_MARKED)
            memcpy(rin + lane * j++, start + lane * i, lane);

    memset(&ra, 0, sizeof ra);
    ra.struct_size = sizeof ra;
    ra.a = zero;                        /* +0 streams: m lanes of them */
    ra.b = zero;
    ra.c = zero;
    ra.n = m;
    ra.bank = R->rbank_bytes ? R->rbank : NULL;
    ra.bank_bytes = R->rbank_bytes;
    ra.scratch_in = rin;
    ra.scratch_in_bytes = m * lane;
    ra.scratch_out = rout;
    ra.scratch_out_bytes = m * lane;
    ra.flags_out = &rfl;
    ra.bus_out = &rbus;
    ra.lane_flags = rblk;
    ra.lane_flags_bytes = m;
    st = cft_program_run_ex(R->rprog, &ra);
    if (st != CFT_OK) {
        char what[112];
        snprintf(what, sizeof what, "run %lu segment %llu: the replay image's "
                 "run (cft_program_run_ex)", (unsigned long)r,
                 (unsigned long long)k);
        refuse_st("device", what, st);
    }
    for (j = 0; j < m; j++)
        if (rblk[j] & CFT_LANE_MARKED) {
            for (i = 0, f = 0; i < R->lanes; i++)
                if ((blk[i] & CFT_LANE_MARKED) && f++ == j)
                    break;
            refuse("replay-undecided", "run %lu segment %llu: the replay "
                   "image marks lane %lu too - its routine could not decide "
                   "that lane's last bit either - so this writer cannot "
                   "replay it by the definition", (unsigned long)r,
                   (unsigned long long)k, (unsigned long)i);
        }
    for (i = 0, j = 0; i < R->lanes; i++) {
        if (!(blk[i] & CFT_LANE_MARKED))
            continue;
        if (memcmp(end + lane * i, rout + lane * j, lane) != 0)
            changed++;
        memcpy(end + lane * i, rout + lane * j, lane);
        blk[i] = (uint8_t)((rblk[j] & 0x1Fu) |
                           (rawblk[i] & (CFT_LANE_DEPOSIT_OVERFLOW |
                                         CFT_LANE_SCRATCH_RANGE)));
        j++;
    }
    for (i = 0, f = 0; i < R->lanes; i++)
        f |= blk[i] & 0x1Fu;
    *fl = f;
    *bus &= ~(uint32_t)CFT_STATUS_MARKED;

    if (R->n_replays == R->cap_replays) {
        size_t cap = R->cap_replays ? 2 * R->cap_replays : 4;
        struct replay_rec *g = (struct replay_rec *)xcalloc(cap, sizeof *g);
        if (R->n_replays)
            memcpy(g, R->replays, R->n_replays * sizeof *g);
        free(R->replays);
        R->replays = g;
        R->cap_replays = cap;
    }
    rec = &R->replays[R->n_replays++];
    rec->segment = k;
    rec->marked = m;
    rec->changed = changed;
    state_hash(salt, raw, R->state_bytes, rec->raw_end);
    hashed(cw_lane_flags_hash(salt, rawblk, R->lanes, rec->raw_lanes),
           "a raw block");
    write_side(r, k, "-raw.bin", raw, R->state_bytes);
    write_side(r, k, "-raw.flags", rawblk, R->lanes);
    free(raw);
    free(rawblk);
    free(rin);
    free(rout);
    free(rblk);
}

/* ---- usage --------------------------------------------------------------- */

static void usage_text(FILE *f)
{
    fputs(
"cft-segrun - run a program as consecutive segments and write the certificate\n"
"(docs/CERTIFICATES.md, versions 1 and 2; \"The segment runner\" is the\n"
"manual)\n"
"\n"
"  cft-segrun --out CERT --states DIR (--salt SALT | --open)\n"
"             [--format-version 1|2]\n"
"             [--device sw|<xclbin>|cft://host:port | --scratch-depth N]\n"
"             [--certificate-id ID] [--issuer ISSUER] [--issuer-key KEY]\n"
"             [--initial INITIAL] [--supersedes DIGEST]\n"
"             [--compiler-build BUILD]\n"
"             [--publish device-serial|host-os-version ...]\n"
"             --run main --image IMG [--bank BANK] --init INIT\n"
"                        --segments S --steps K [--param NAME=N ...]\n"
"                        [--lane-flags]\n"
"                        [--source SRC --manifest M [--compiler none]]\n"
"                        [--replay-image IMG [--replay-bank BANK]]\n"
"             [--run half-step --h-slots I,J,... --image IMG ...]\n"
"             [--run wider --image IMG ...]\n"
"             [--run wider-source --image IMG ...]\n"
"             [--entry drift|step-halving|wider|wider-source --uses R\n"
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
"\n", f);
    /* in two pieces: one string past C99's 4,095 characters is a warning */
    fputs(
"Version 2 (the default; --format-version 1 writes version 1):\n"
"  --certificate-id, --issuer, --issuer-key, --supersedes, --initial\n"
"                  the header's statements, each its line's own value as\n"
"                  the certificate spells it: a word the line takes, or a\n"
"                  text percent-encoded (cert%200001 is \"cert 0001\");\n"
"                  --initial \"generator <name> <text> ...\" or given\n"
"  --compiler-build BUILD  the compiler's build, where a run names one\n"
"  --publish WHAT  device-serial or host-os-version, withheld by default\n"
"  --lane-flags    a run asks for the per-lane block, written beside the\n"
"                  boundaries (asked too wherever its image needs flag\n"
"                  control)\n"
"  --source SRC --manifest M  the run's source and cftc's manifest of it:\n"
"                  the source lines, held to the files the run runs;\n"
"                  --compiler none: the image is not its compile\n"
"  --replay-image IMG [--replay-bank BANK]  an image of the source that\n"
"                  replays a lane the run marks\n"
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
            stream_hash(salt, which, bytes, n, hex);
        free(bytes);
    }
    printf("%s\n", hex);
    return 0;
}

/* ---- main -------------------------------------------------------------- */

#if defined(_WIN32)
/* Whether the command line's ANSI form is exact: every character in the
 * system code page as itself, none spelt by best fit or by the default
 * character. A UTF-8 code page spells every string that has a UTF-8
 * spelling (an unpaired surrogate is refused on its own, below); a code
 * page the question cannot be put to answers no. */
static int ansi_form_exact(const wchar_t *line)
{
    UINT acp = GetACP();
    BOOL used = FALSE;
    if (acp == CP_UTF8)
        return 1;
    if (WideCharToMultiByte(acp, WC_NO_BEST_FIT_CHARS, line, -1, NULL, 0,
                            NULL, &used) == 0)
        return 0;
    return !used;
}

/* The arguments as the process has them ("the process's own text",
 * above): the wide command line's, split by CommandLineToArgvW, each in
 * UTF-8, in place of main's - and their count in place of argc. main's
 * are the C runtime's split of the line's ANSI form, which the system
 * code page makes by best fit: on cp1252 U+3000, U+2002, U+2003 and
 * U+2009 become a space, U+FF02, U+2033 and U+02BA a quote and U+FF3C a
 * backslash, so the runtime splits another string, and the Unicode split,
 * the one this tool reads, decides (verifier-VCV2CW, 2026-10-03). Only
 * where the ANSI form is exact are the two held to each other - the
 * count, and each argument that is ASCII as Unicode, which every code page
 * spells the same (argv[0] aside, which each reads its own way) - so that
 * a C runtime that splits a quoting form otherwise than CommandLineToArgvW
 * is refused by name (usage) rather than guessed at. An argument with no
 * UTF-8 spelling (an unpaired surrogate) is refused too: the tool reads
 * its command line as text. */
static char **utf8_args(int *argc, char **argv)
{
    const wchar_t *line = GetCommandLineW();
    int n = 0, i, exact;
    wchar_t **w = CommandLineToArgvW(line, &n);
    char **out;
    if (!w)
        refuse("usage", "the command line cannot be read as Unicode "
               "(CommandLineToArgvW failed, error %lu)",
               (unsigned long)GetLastError());
    exact = ansi_form_exact(line);
    if (exact && n != *argc)
        refuse("usage", "the command line splits into %d arguments as "
               "Unicode and into %d as the C runtime reads it, and the "
               "system code page spells it exactly", n, *argc);
    out = (char **)xcalloc((size_t)n + 1, sizeof *out);
    for (i = 0; i < n; i++) {
        const unsigned char *a;
        size_t k;
        int ascii = 1;
        out[i] = u8_of_wide(w[i]);
        if (!out[i] && errno == ENOMEM)
            refuse("memory", "argument %d could not be held in UTF-8", i);
        if (!out[i])
            refuse("usage", "argument %d has no UTF-8 spelling (an unpaired "
                   "surrogate), and this tool reads its command line as "
                   "text", i);
        for (a = (const unsigned char *)out[i], k = 0; a[k]; k++)
            ascii &= a[k] < 0x80;
        if (exact && i > 0 && ascii && strcmp(argv[i], out[i]) != 0)
            refuse("usage", "argument %d is '%.80s' as the C runtime reads "
                   "the command line and '%.80s' as Unicode", i, argv[i],
                   out[i]);
    }
    LocalFree(w);
    *argc = n;
    return out;
}
#endif

int main(int argc, char **argv)
{
    const char *out_path = NULL, *states_path = NULL, *salt_path = NULL;
    const char *device = NULL, *hash_kind = NULL, *hash_file = NULL;
    const char *depth_s = NULL;
    /* --format-version as given, and the first version-2 option given,
     * which version 1 has no line for */
    const char *format_s = NULL, *any_v2 = NULL;
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
        else if (!strcmp(plant, "wider-routine"))
            PLANT_WIDER_ROUTINE = 1;
        else
            refuse("usage", "CFT_SEGRUN_PLANT=%s is not an instrument this "
                   "tool has (flags-unreadable, flags-unwritten, "
                   "flags-wide, trial-skipped, wider-routine)", plant);
        fprintf(stderr, "cft-segrun: CFT_SEGRUN_PLANT=%s - an instrument: "
                "%s\n", plant, PLANT_NO_TRIAL ? "the trial's allocations "
                "are skipped, its size checks kept" : PLANT_WIDER_ROUTINE ?
                "a wider run of a routine image is written as stated, a "
                "certificate cft-audit must refuse (aux-image)" : "this run "
                "is to be refused");
    }

#if defined(_WIN32)
    argv = utf8_args(&argc, argv);
#endif
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
        } else if (!strcmp(a, "--format-version")) {
            once(&format_s, a, need(argc, argv, &i));
        } else if (!strcmp(a, "--certificate-id")) {
            once(&ST_CERT_ID, a, need(argc, argv, &i));
        } else if (!strcmp(a, "--issuer")) {
            once(&ST_ISSUER, a, need(argc, argv, &i));
        } else if (!strcmp(a, "--issuer-key")) {
            once(&ST_KEY, a, need(argc, argv, &i));
        } else if (!strcmp(a, "--initial")) {
            once(&ST_INITIAL, a, need(argc, argv, &i));
        } else if (!strcmp(a, "--supersedes")) {
            once(&ST_SUPERSEDES, a, need(argc, argv, &i));
        } else if (!strcmp(a, "--compiler-build")) {
            once(&ST_COMPILER_BUILD, a, need(argc, argv, &i));
        } else if (!strcmp(a, "--publish")) {
            const char *w = need(argc, argv, &i);
            int *slot = !strcmp(w, "device-serial") ? &PUBLISH_SERIAL
                      : !strcmp(w, "host-os-version") ? &PUBLISH_OS_VERSION
                      : NULL;
            if (!slot)
                refuse("usage", "--publish %s: what a certificate withholds "
                       "by default and publishes on request is the "
                       "device-serial and the host-os-version", w);
            if (*slot)
                refuse("usage", "--publish %s is given twice", w);
            *slot = 1;
            any_v2 = any_v2 ? any_v2 : a;
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
            else if (!strcmp(k, "wider-source"))
                kind = K_WSRC;          /* version 2's alone */
            else
                refuse("usage", "--run %s: a run is main, half-step, wider "
                       "or (version 2) wider-source", k);
            grown = (run_spec *)xcalloc(n_runs + 1, sizeof *grown);
            if (n_runs)
                memcpy(grown, runs, n_runs * sizeof *grown);
            free(runs);
            runs = grown;
            memset(&runs[n_runs], 0, sizeof runs[n_runs]);
            runs[n_runs].kind = kind;
            n_runs++;
        } else if (!strcmp(a, "--lane-flags")) {
            /* version 2: the run asks for the per-lane block */
            if (!cur)
                refuse("usage", "%s belongs to a run: give it after --run",
                       a);
            if (n_entries)
                refuse("usage", "%s belongs to a run, and the runs come "
                       "before the accuracy entries (--entry)", a);
            if (cur->lane_flags_s)
                refuse("usage", "%s is given twice", a);
            cur->lane_flags_s = 1;
            any_v2 = any_v2 ? any_v2 : a;
        } else if (!strcmp(a, "--image") || !strcmp(a, "--bank") ||
                   !strcmp(a, "--init") || !strcmp(a, "--segments") ||
                   !strcmp(a, "--steps") || !strcmp(a, "--h-slots") ||
                   !strcmp(a, "--param") || !strcmp(a, "--replay-image") ||
                   !strcmp(a, "--replay-bank") || !strcmp(a, "--source") ||
                   !strcmp(a, "--manifest") || !strcmp(a, "--compiler")) {
            const char *v = need(argc, argv, &i);
            if (!cur)
                refuse("usage", "%s belongs to a run: give it after --run",
                       a);
            if (n_entries)
                refuse("usage", "%s belongs to a run, and the runs come "
                       "before the accuracy entries (--entry)", a);
            if (!strcmp(a, "--replay-image") || !strcmp(a, "--replay-bank") ||
                !strcmp(a, "--source") || !strcmp(a, "--manifest") ||
                !strcmp(a, "--compiler"))
                any_v2 = any_v2 ? any_v2 : a;
            if (!strcmp(a, "--image"))         once(&cur->image_path, a, v);
            else if (!strcmp(a, "--replay-image"))
                once(&cur->replay_image_path, a, v);
            else if (!strcmp(a, "--replay-bank"))
                once(&cur->replay_bank_path, a, v);
            else if (!strcmp(a, "--source"))   once(&cur->source_path, a, v);
            else if (!strcmp(a, "--manifest")) once(&cur->manifest_path, a, v);
            else if (!strcmp(a, "--compiler")) {
                if (strcmp(v, "none") != 0)
                    refuse("usage", "--compiler %s: the one value it takes is "
                           "none - the run's image is not claimed to be its "
                           "source's compile, which the source defines (the "
                           "`compiler none` line); without it the compiler "
                           "is the manifest's, and the image is held to its "
                           "compile", v);
                once(&cur->compiler_s, a, v);
            }
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

    /* the format version, and the first option version 1 has no line for:
     * a header statement, a run's version-2 option, a wider-source run */
    if (format_s) {
        if (!strcmp(format_s, "1"))
            FORMAT_VERSION = 1;
        else if (strcmp(format_s, "2") != 0)
            refuse("usage", "--format-version %s: a certificate's format is "
                   "version 1 or version 2, the default", format_s);
    }
    if (!any_v2)
        any_v2 = ST_CERT_ID ? "--certificate-id" : ST_ISSUER ? "--issuer"
               : ST_KEY ? "--issuer-key" : ST_INITIAL ? "--initial"
               : ST_SUPERSEDES ? "--supersedes"
               : ST_COMPILER_BUILD ? "--compiler-build" : NULL;
    for (r = 0; r < n_runs && !any_v2; r++)
        if (runs[r].kind == K_WSRC)
            any_v2 = "--run wider-source";

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
            n_entries || format_s || any_v2)
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
    if (FORMAT_VERSION == 1 && any_v2)
        refuse("usage", "%s is version 2's: --format-version 1 writes "
               "version 1's certificate, which has no line for it", any_v2);
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
    if (FORMAT_VERSION == 2) {
        /* the header's statements, and what it measures that does not
         * change while the tool runs - each before anything is made */
        check_statements();
        measure_host();
    }
    for (r = 0; r < n_runs; r++) {
        check_run(&runs[r], r);
        if (FORMAT_VERSION == 2)
            check_run_v2(&runs[r], r);
    }
    if (FORMAT_VERSION == 2) {
        int any_compiled = 0;
        for (r = 0; r < n_runs; r++)
            any_compiled |= runs[r].has_source && runs[r].compiled;
        if (ST_COMPILER_BUILD && !any_compiled)
            refuse("usage", "--compiler-build %s: no run names a compiler "
                   "(each says source none or compiler none), so the line is "
                   "none", ST_COMPILER_BUILD);
        if (ST_COMPILER_BUILD && any_compiled &&
            !strcmp(ST_COMPILER_BUILD, "none"))
            refuse("usage", "--compiler-build none: a run names its "
                   "compiler, whose build the line states; say unknown or "
                   "its build");
    }
    /* A wider run of a routine image (C4): refused, by both writers and
     * both audits, as `aux-image`. A routine's instruction words and its
     * bank words are its format's - its Newton passes, its masks, its
     * biases - so the main image's words at the next rung, which is all
     * version 1's relation holds, compute nothing a wider estimate means.
     * QUIET, ENDQUIET or RAISE in the main image is the sign of one: the
     * language's compiler writes them around every routine and nowhere
     * else. Certificate version 2's wider-source run relates the source's
     * compile one format up instead. */
    for (r = 1; r < n_runs; r++)
        if (runs[r].kind == K_WIDER && holds_routine(&runs[0]) &&
            !PLANT_WIDER_ROUTINE)
            refuse("aux-image", "run %lu (wider): the main image holds a "
                   "routine (QUIET, ENDQUIET or RAISE), whose words are its "
                   "format's, so no image is it one format wider; "
                   "certificate version 2's wider-source run compiles its "
                   "source one format up instead", (unsigned long)r);

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
    CERT_FP = u8_create_new(out_path);
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
    if (u8_mkdir(states_path) != 0)
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
        cw_hex(digest, 32, R->image_digest);
        /* the library holds its own copy of the image (cft_program_load),
         * and the certificate needs only its digest */
        free(R->img);
        R->img = NULL;
        st = cft_program_digest(R->prog, bank, R->bank_bytes, digest);
        if (st != CFT_OK)
            refuse_st("device", "cft_program_digest", st);
        cw_hex(digest, 32, R->program_digest);
        if (R->rimg) {
            /* version 2: the replay image, on the same device, held to the
             * header check_run_v2 read (its format and its lane) */
            snprintf(where, sizeof where, "run %lu: cft_program_load of the "
                     "replay image", (unsigned long)r);
            st = cft_program_load(dev, R->rimg, R->rimg_bytes, &R->rprog);
            if (st != CFT_OK)
                refuse_st("program-image", where, st);
            memset(&info, 0, sizeof info);
            info.struct_size = sizeof info;
            st = cft_program_get_info(R->rprog, &info);
            if (st != CFT_OK)
                refuse_st("device", "cft_program_get_info", st);
            if ((uint32_t)info.format != R->RH.prec ||
                info.n_scratch_in != R->RH.n_in ||
                info.n_scratch_out != R->RH.n_out)
                refuse("program-image", "run %lu: the library reads the "
                       "replay image %s's header differently from this tool",
                       (unsigned long)r, R->replay_image_path);
            free(R->rimg);
            R->rimg = NULL;
        }
    }
    identify(dev, &caps, &id);
    snprintf(LAST_BEFORE, sizeof LAST_BEFORE, "%s", cft_last_error());

    /* ---- the runs, segment by segment ------------------------------------ */
    if (FORMAT_VERSION == 2)
        utc_now(T_STARTED);             /* when the first run began */
    for (r = 0; r < n_runs; r++) {
        run_spec *R = &runs[r];
        const void *bank = R->bank_bytes ? R->bank : NULL;
        uint8_t *cur, *next, *zero, *blk = NULL;
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
        if (FORMAT_VERSION == 2 && R->lane_flags)
            R->lanes_hash = (char (*)[65])run_take(
                (size_t)R->segments, sizeof *R->lanes_hash, r,
                "the per-lane blocks' hashes");
        cur = (uint8_t *)run_take(R->state_bytes, 1, r, "a state");
        next = (uint8_t *)run_take(R->state_bytes, 1, r, "a state");
        zero = (uint8_t *)run_take(R->lanes, R->esz, r, "the streams");
        if (FORMAT_VERSION == 2 && R->lane_flags)
            blk = (uint8_t *)run_take(R->lanes, 1, r, "the per-lane block");
        memcpy(cur, R->init, R->state_bytes);
        /* boundary 0 is written and hashed from cur: the initial state is
         * not needed again */
        free(R->init);
        R->init = NULL;

        for (s = 0; s < 3; s++)
            stream_hash(salt, s, zero, R->lanes * R->esz,
                        R->stream_hash[s]);
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
            if (blk) {
                /* version 2: R23's byte a lane (ABI 0.17) */
                ra.lane_flags = blk;
                ra.lane_flags_bytes = R->lanes;
            }
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
            if (FORMAT_VERSION == 2 && !blk && (bus & CFT_STATUS_MARKED))
                /* no image that cannot raise can mark: this run asks for
                 * the block wherever its image needs flag control, so only
                 * a library that misreports reaches this */
                refuse("replay-lane-flags", "run %lu segment %llu marks a "
                       "lane (STATUS[6]), and the run did not ask for the "
                       "per-lane block that says which", (unsigned long)r,
                       (unsigned long long)k);
            if (blk)
                replay_segment(R, r, k, cur, next, blk, zero, &fl, &bus, salt);
            R->flags[k] = fl;
            R->status[k] = bus;
            write_boundary(r, k + 1, next, R->state_bytes);
            state_hash(salt, next, R->state_bytes, R->hash[k + 1]);
            if (blk) {
                write_side(r, k, ".flags", blk, R->lanes);
                hashed(cw_lane_flags_hash(salt, blk, R->lanes,
                                          R->lanes_hash[k]),
                       "a per-lane block");
            }
            t = cur;
            cur = next;
            next = t;
        }
        free(cur);
        free(next);
        free(zero);
        free(blk);
    }
    if (FORMAT_VERSION == 2)
        utc_now(T_FINISHED);            /* when the last run ended */

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
    /* the lines are cert_write.h's (the header's identity lines, a run
     * block's head, each segment line, `end` and the hash line), shared
     * with cft-orbits; the runs' own lines between them are this tool's */
    if (FORMAT_VERSION == 1) {
        put(&body, "cft-certificate 1\n");
        if (salt)
            salt_commitment(salt, commitment);
        lines_ok(cw_identity_lines(&body, salt ? commitment : NULL, &id));
        put(&body, "runs %llu\n", (unsigned long long)n_runs);
        for (r = 0; r < n_runs; r++) {
            run_spec *R = &runs[r];
            uint64_t k;
            put_run_line(&body, r, R);
            lines_ok(cw_run_head(&body, FORMAT_NAME[R->H.prec],
                                 R->image_digest, R->program_digest,
                                 R->lanes, R->steps, R->stream_hash[0],
                                 R->stream_hash[1], R->stream_hash[2]));
            put_parameters(&body, R);
            put(&body, "segments %llu\n", (unsigned long long)R->segments);
            for (k = 0; k < R->segments; k++)
                lines_ok(cw_segment_line(&body, k, R->hash[k],
                                         R->hash[k + 1], R->flags[k],
                                         R->status[k]));
            put(&body, "output %s\n", R->hash[R->segments]);
        }
    } else {
        /* version 2: the header's new lines after version 1's identity
         * lines, and each run's source lines, lane flags and replays */
        put_v2_header(&body, salt, &id, runs, n_runs);
        for (r = 0; r < n_runs; r++)
            put_v2_run(&body, r, &runs[r]);
    }
    put_accuracy(&body, entries, n_entries, arith);
    {
        /* `end` and the hash line, SHA-256 of the body before it, whose
         * 64 digits the report prints */
        const char *why = cw_finish(&body);
        if (why && !strcmp(why, "device"))
            refuse("device", "cft_sha256, hashing the body: %s",
                   cft_last_error());
        lines_ok(why);
        memcpy(hex, body.p + body.n - 65, 64);
        hex[64] = 0;
    }

    if (fwrite(body.p, 1, body.n, CERT_FP) != body.n)
        refuse("output", "a short write to %s", out_path);
    if (fclose(CERT_FP) != 0) {
        CERT_FP = NULL;
        u8_remove(out_path);
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
    if (FORMAT_VERSION == 2)
        printf("version 2     platform %s, xrt %s, clock %s, serial %s; "
               "%llu file%s of per-lane flags and replays beside the "
               "boundaries\n", id.platform, id.xrt, id.clock,
               id.no_card ? "none" : !id.serial[0] ? "unknown"
               : PUBLISH_SERIAL ? id.serial : "withheld", SIDE_FILES,
               SIDE_FILES == 1 ? "" : "s");
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
        if (FORMAT_VERSION == 2) {
            uint64_t marked = 0, changed = 0;
            size_t q;
            for (q = 0; q < R->n_replays; q++) {
                marked += R->replays[q].marked;
                changed += R->replays[q].changed;
            }
            printf("  source      %s; lane flags %s; replays: %llu lane%s "
                   "in %llu segment%s, %llu changed\n",
                   !R->has_source ? "none" : R->compiled ? "compiled from it"
                   : "defined by it", R->lane_flags ? "yes" : "no",
                   (unsigned long long)marked, marked == 1 ? "" : "s",
                   (unsigned long long)R->n_replays,
                   R->n_replays == 1 ? "" : "s",
                   (unsigned long long)changed);
        }
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
        size_t q;
        cft_program_free(runs[r].prog);
        free(runs[r].img);
        free(runs[r].bank);
        free(runs[r].init);
        free(runs[r].hash);
        free(runs[r].flags);
        free(runs[r].status);
        free((void *)runs[r].param_s);
        /* version 2's */
        if (runs[r].rprog)
            cft_program_free(runs[r].rprog);
        free(runs[r].rimg);
        free(runs[r].rbank);
        free(runs[r].lanes_hash);
        free(runs[r].replays);
        for (q = 0; q < runs[r].n_sparams; q++) {
            free(runs[r].sparam_name[q]);
            free(runs[r].sparam_lit[q]);
        }
        free(runs[r].sparam_name);
        free(runs[r].sparam_lit);
    }
    free(runs);
    for (j = 0; j < N_ENV_NAMES; j++)
        free(ENV_TOK[j]);
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
