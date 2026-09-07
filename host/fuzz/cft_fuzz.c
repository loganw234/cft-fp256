/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * A small coverage-guided mutation fuzzer.
 *
 * Why this and not libFuzzer: there is no clang on either machine this
 * repository is built on (checked: no clang on PATH, none in
 * /c/msys64/clang64 or /c/msys64/mingw64, none in the cft-sim image),
 * and the cft-sim image carries no AFL++ either. What both toolchains
 * DO carry is gcc with -fsanitize=address,undefined and gcc's
 * -fsanitize-coverage=trace-pc, which is enough to build the part of
 * libFuzzer that matters here: an edge map, a corpus that grows when
 * an input reaches an edge nothing else reached, and havoc mutation on
 * top of it. host/fuzz/README.md says what that costs in practice.
 *
 * This file is the one translation unit compiled WITHOUT the coverage
 * flag, because __sanitizer_cov_trace_pc calling itself is a stack
 * overflow rather than a measurement.
 */

#if !defined(_WIN32)
#  define _POSIX_C_SOURCE 200809L
#  define _DEFAULT_SOURCE 1
#endif

#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#if defined(_WIN32)
#  include <direct.h>
#  include <io.h>
#  define MKDIR(p) _mkdir(p)
#else
#  include <dirent.h>
#  include <sys/stat.h>
#  include <sys/time.h>
#  include <sys/types.h>
#  include <unistd.h>
#  define MKDIR(p) mkdir((p), 0755)
#endif

#include "cft_fuzz.h"

/* ---- the coverage map ------------------------------------------- */

uint8_t cft_fuzz_map[CFT_FUZZ_MAP_SIZE];
static uint8_t  virgin[CFT_FUZZ_MAP_SIZE];   /* every bucket ever hit */
static unsigned prev_loc;

/* AFL's edge hash, with the previous location shifted so that A->B and
 * B->A are different edges. The block identity is the return address
 * of the call gcc inserts, shifted past the alignment bits that carry
 * no information. */
void __sanitizer_cov_trace_pc(void)
{
    uintptr_t pc = (uintptr_t)__builtin_return_address(0);
    unsigned cur = (unsigned)((pc >> 4) ^ (pc >> 11)) & (CFT_FUZZ_MAP_SIZE - 1);
    cft_fuzz_map[cur ^ prev_loc]++;
    prev_loc = cur >> 1;
}

/* ---- the state a crash handler has to be able to reach ----------- */

#define FUZZ_MAX_INPUT (1u << 20)

static uint8_t  cur_input[FUZZ_MAX_INPUT];
static size_t   cur_len;
static char     crash_dir[512];
static volatile sig_atomic_t exec_tick;      /* bumped every execution */
static unsigned long long execs;

static void write_all(int fd, const void *p, size_t n);

#if defined(_WIN32)
static void write_all(int fd, const void *p, size_t n)
{
    (void)_write(fd, p, (unsigned)n);
}
#else
static void write_all(int fd, const void *p, size_t n)
{
    const char *q = (const char *)p;
    while (n) {
        ssize_t w = write(fd, q, n);
        if (w <= 0)
            return;
        q += w;
        n -= (size_t)w;
    }
}
#endif

/* Async-signal-safe enough to run from a crash handler: no malloc, no
 * stdio, a name built by hand. */
static void save_input(const char *kind, unsigned long long tag)
{
    char path[600];
    size_t i = 0, j;
    int fd;
    const char *hex = "0123456789abcdef";

    for (j = 0; crash_dir[j] && i + 1 < sizeof path; j++)
        path[i++] = crash_dir[j];
    if (i + 1 < sizeof path)
        path[i++] = '/';
    for (j = 0; kind[j] && i + 1 < sizeof path; j++)
        path[i++] = kind[j];
    if (i + 1 < sizeof path)
        path[i++] = '-';
    for (j = 16; j-- > 0;)
        if (i + 1 < sizeof path)
            path[i++] = hex[(tag >> (j * 4)) & 0xF];
    path[i] = '\0';

#if defined(_WIN32)
    fd = _open(path, _O_WRONLY | _O_CREAT | _O_TRUNC | _O_BINARY, 0644);
#else
    fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
#endif
    if (fd < 0)
        return;
    write_all(fd, cur_input, cur_len);
#if defined(_WIN32)
    _close(fd);
#else
    close(fd);
#endif
}

static void on_fatal(int sig)
{
    save_input("crash", (unsigned long long)sig * 0x100000000ull + execs);
    _exit(86);
}

#if !defined(_WIN32)

/* One repeating timer for the whole run rather than an alarm() per
 * execution: a hang is an execution the counter stopped moving in, and
 * that is cheaper to notice than to arm three thousand times a second. */
static volatile sig_atomic_t last_tick;
static int stall_ticks;
static long hang_secs = 10;

static void on_tick(int sig)
{
    (void)sig;
    if (exec_tick == last_tick) {
        if (++stall_ticks >= hang_secs) {
            save_input("hang", execs);
            _exit(87);
        }
    } else {
        last_tick = exec_tick;
        stall_ticks = 0;
    }
}
#endif

/* ---- the corpus -------------------------------------------------- */

typedef struct { uint8_t *buf; size_t len; } entry;

static entry  *queue;
static size_t  nqueue, cqueue;
static char    corpus_dir[512];
static size_t  max_len = 65536;

static void queue_push(const uint8_t *d, size_t n)
{
    if (nqueue == cqueue) {
        size_t c = cqueue ? cqueue * 2 : 64;
        entry *q = (entry *)realloc(queue, c * sizeof *q);
        if (!q)
            return;
        queue = q;
        cqueue = c;
    }
    queue[nqueue].buf = (uint8_t *)malloc(n ? n : 1);
    if (!queue[nqueue].buf)
        return;
    memcpy(queue[nqueue].buf, d, n);
    queue[nqueue].len = n;
    nqueue++;
}

/* ---- a deterministic PRNG ---------------------------------------- */

static uint64_t rng_state;

static uint64_t rnd(void)
{
    uint64_t z = (rng_state += 0x9E3779B97F4A7C15ull);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
    return z ^ (z >> 31);
}

static size_t rnd_below(size_t n)
{
    return n ? (size_t)(rnd() % n) : 0;
}

/* ---- mutation ---------------------------------------------------- */

static const uint64_t interesting[] = {
    0, 1, 2, 3, 4, 7, 8, 15, 16, 31, 32, 63, 64, 127, 128, 255, 256,
    511, 512, 1023, 1024, 4095, 4096, 65535, 65536, 0x7FFFFFFFu,
    0x80000000u, 0xFFFFFFFFu, 0x100000000ull, 0x7FFFFFFFFFFFFFFFull,
    0x8000000000000000ull, 0xFFFFFFFFFFFFFFFFull, 24, 32, 56, 0x40000000u
};
#define N_INTERESTING (sizeof interesting / sizeof interesting[0])

static void put_le(uint8_t *p, uint64_t v, int width)
{
    int i;
    for (i = 0; i < width; i++)
        p[i] = (uint8_t)(v >> (8 * i));
}

static size_t mutate(uint8_t *buf, size_t len, size_t cap)
{
    int rounds = 1 + (int)rnd_below(8);
    while (rounds--) {
        switch (rnd() % 12u) {
        case 0:                                  /* flip one bit */
            if (len) buf[rnd_below(len)] ^= (uint8_t)(1u << (rnd() & 7u));
            break;
        case 1:                                  /* set one byte */
            if (len) buf[rnd_below(len)] = (uint8_t)rnd();
            break;
        case 2:                                  /* small arithmetic */
            if (len) {
                size_t i = rnd_below(len);
                buf[i] = (uint8_t)(buf[i] + (int)(rnd() % 35u) - 17);
            }
            break;
        case 3: case 4: {                        /* an interesting word */
            int w = 1 << (rnd() % 4u);           /* 1, 2, 4 or 8 bytes */
            if (len >= (size_t)w) {
                size_t i = rnd_below(len - (size_t)w + 1);
                put_le(buf + i, interesting[rnd_below(N_INTERESTING)], w);
            }
            break;
        }
        case 5:                                  /* delete a run */
            if (len > 1) {
                size_t n = 1 + rnd_below(len > 32 ? 32 : len - 1);
                size_t i = rnd_below(len - n + 1);
                memmove(buf + i, buf + i + n, len - i - n);
                len -= n;
            }
            break;
        case 6:                                  /* insert a run */
            if (len < cap) {
                size_t n = 1 + rnd_below(cap - len > 32 ? 32 : cap - len);
                size_t i = rnd_below(len + 1);
                size_t k;
                memmove(buf + i + n, buf + i, len - i);
                for (k = 0; k < n; k++)
                    buf[i + k] = (uint8_t)rnd();
                len += n;
            }
            break;
        case 7:                                  /* repeat a run */
            if (len > 1 && len < cap) {
                size_t n = 1 + rnd_below(len > 32 ? 32 : len - 1);
                size_t src = rnd_below(len - n + 1);
                size_t dst = rnd_below(len + 1);
                if (len + n > cap)
                    n = cap - len;
                memmove(buf + dst + n, buf + dst, len - dst);
                memmove(buf + dst, buf + src + (src >= dst ? n : 0), n);
                len += n;
            }
            break;
        case 8:                                  /* splice from the queue */
            if (nqueue) {
                entry *e = &queue[rnd_below(nqueue)];
                size_t n = e->len < cap ? e->len : cap;
                size_t i = n ? rnd_below(n) : 0;
                if (i < n) {
                    size_t take = n - i;
                    if (take > cap) take = cap;
                    memcpy(buf, e->buf + i, take);
                    if (take > len) len = take;
                }
            }
            break;
        case 9:                                  /* truncate */
            if (len > 1)
                len = 1 + rnd_below(len - 1);
            break;
        case 10:                                 /* extend with zeros */
            if (len < cap) {
                size_t n = 1 + rnd_below(cap - len > 64 ? 64 : cap - len);
                memset(buf + len, 0, n);
                len += n;
            }
            break;
        default:                                 /* swap two bytes */
            if (len > 1) {
                size_t i = rnd_below(len), j = rnd_below(len);
                uint8_t t = buf[i]; buf[i] = buf[j]; buf[j] = t;
            }
            break;
        }
    }
    return len;
}

/* ---- the loop ---------------------------------------------------- */

static int has_new_coverage(void)
{
    size_t i;
    int fresh = 0;
    for (i = 0; i < CFT_FUZZ_MAP_SIZE; i++) {
        if (!cft_fuzz_map[i])
            continue;
        /* Bucketed hit counts, as AFL does it: 1, 2, 3, 4-7, 8-15,
         * 16-31, 32-127, 128+. A loop that ran eleven times instead of
         * ten is not news; one that ran a hundred is. */
        {
            uint8_t c = cft_fuzz_map[i];
            uint8_t b = c <= 3 ? c
                      : c <= 7 ? 4 : c <= 15 ? 5 : c <= 31 ? 6
                      : c <= 127 ? 7 : 8;
            if ((virgin[i] & (uint8_t)(1u << (b - 1))) == 0) {
                virgin[i] |= (uint8_t)(1u << (b - 1));
                fresh = 1;
            }
        }
    }
    return fresh;
}

static double now_s(void)
{
#if defined(_WIN32)
    return (double)clock() / CLOCKS_PER_SEC;
#else
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (double)tv.tv_sec + (double)tv.tv_usec * 1e-6;
#endif
}

static int read_file(const char *path, uint8_t *buf, size_t cap, size_t *len)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return -1;
    *len = fread(buf, 1, cap, f);
    fclose(f);
    return 0;
}

static void load_corpus(const char *dir)
{
#if !defined(_WIN32)
    DIR *d = opendir(dir);
    struct dirent *e;
    if (!d)
        return;
    while ((e = readdir(d))) {
        char path[1024];
        uint8_t buf[FUZZ_MAX_INPUT];
        size_t n;
        struct stat st;
        snprintf(path, sizeof path, "%s/%s", dir, e->d_name);
        if (stat(path, &st) != 0 || !S_ISREG(st.st_mode))
            continue;
        if (read_file(path, buf, sizeof buf, &n) == 0)
            queue_push(buf, n > max_len ? max_len : n);
    }
    closedir(d);
#else
    (void)dir;
#endif
}

static void save_queue_entry(const uint8_t *d, size_t n, unsigned long long id)
{
    char path[1024];
    FILE *f;
    snprintf(path, sizeof path, "%s/q%08llx", corpus_dir, id);
    f = fopen(path, "wb");
    if (!f)
        return;
    fwrite(d, 1, n, f);
    fclose(f);
}

int cft_fuzz_main(int argc, char **argv, const cft_fuzz_target *t)
{
    double seconds = 60.0, t0;
    int i, replay = 0;
    unsigned long long report_at = 0;

    snprintf(corpus_dir, sizeof corpus_dir, "corpus/%s", t->name);
    snprintf(crash_dir, sizeof crash_dir, "crashes/%s", t->name);
    if (t->max_len)
        max_len = t->max_len < FUZZ_MAX_INPUT ? t->max_len : FUZZ_MAX_INPUT;
    rng_state = 0x243F6A8885A308D3ull;

    for (i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--seconds") && i + 1 < argc)
            seconds = atof(argv[++i]);
        else if (!strcmp(argv[i], "--seed") && i + 1 < argc)
            rng_state ^= strtoull(argv[++i], NULL, 10) * 0x9E3779B97F4A7C15ull;
        else if (!strcmp(argv[i], "--corpus") && i + 1 < argc)
            snprintf(corpus_dir, sizeof corpus_dir, "%s", argv[++i]);
        else if (!strcmp(argv[i], "--crashes") && i + 1 < argc)
            snprintf(crash_dir, sizeof crash_dir, "%s", argv[++i]);
        else if (!strcmp(argv[i], "--max-len") && i + 1 < argc)
            max_len = (size_t)strtoull(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--run"))
            replay = i + 1;
        else if (!strcmp(argv[i], "--help")) {
            printf("%s [--seconds S] [--seed N] [--corpus DIR] "
                   "[--crashes DIR] [--max-len N] [--run FILE...]\n", t->name);
            return 0;
        }
    }
    if (max_len > FUZZ_MAX_INPUT)
        max_len = FUZZ_MAX_INPUT;

    if (t->init)
        t->init();

    /* --run: replay named inputs and exit. This is how a reproducer in
     * host/fuzz/crashes is checked, and how the regression tests in
     * the suites call the harness. */
    if (replay) {
        for (i = replay; i < argc; i++) {
            size_t n = 0;
            if (read_file(argv[i], cur_input, max_len, &n) != 0) {
                fprintf(stderr, "cannot read %s\n", argv[i]);
                return 2;
            }
            cur_len = n;
            printf("replay %s (%lu bytes)\n", argv[i], (unsigned long)n);
            fflush(stdout);
            t->run(cur_input, cur_len);
        }
        printf("%d input(s) replayed without a crash\n", argc - replay);
        return 0;
    }

    MKDIR("crashes");
    MKDIR(crash_dir);
    MKDIR("corpus");
    MKDIR(corpus_dir);

    signal(SIGSEGV, on_fatal);
    signal(SIGABRT, on_fatal);
    signal(SIGILL,  on_fatal);
    signal(SIGFPE,  on_fatal);
#if !defined(_WIN32)
    signal(SIGBUS,  on_fatal);
#endif

    load_corpus(corpus_dir);
    if (!nqueue) {
        static const uint8_t seed[32] = { 0 };
        queue_push(seed, sizeof seed);
    }

    /* The stall timer is armed HERE and not before load_corpus: the
     * corpus lives on a bind-mounted volume, a few hundred small reads
     * across it can take longer than the stall budget, and a fuzzer
     * that reports its own directory listing as a hang is a fuzzer
     * whose findings nobody trusts. */
#if !defined(_WIN32)
    {
        struct itimerval it;
        signal(SIGALRM, on_tick);
        it.it_interval.tv_sec = 1;
        it.it_interval.tv_usec = 0;
        it.it_value = it.it_interval;
        setitimer(ITIMER_REAL, &it, NULL);
    }
#endif

    /* Every seed once, so the corpus's own coverage is in `virgin`
     * before the first mutation and a seed that crashes is found
     * without waiting for luck. */
    for (i = 0; i < (int)nqueue; i++) {
        memset(cft_fuzz_map, 0, sizeof cft_fuzz_map);
        prev_loc = 0;
        cur_len = queue[i].len;
        memcpy(cur_input, queue[i].buf, cur_len);
        exec_tick++;
        t->run(cur_input, cur_len);
        execs++;
        has_new_coverage();
    }

    t0 = now_s();
    while (now_s() - t0 < seconds) {
        size_t k = rnd_below(nqueue);
        size_t n = queue[k].len;
        if (n > max_len)
            n = max_len;
        memcpy(cur_input, queue[k].buf, n);
        n = mutate(cur_input, n, max_len);
        if (t->fixup)
            n = t->fixup(cur_input, n, max_len, &rng_state);
        if (n > max_len)
            n = max_len;
        cur_len = n;

        memset(cft_fuzz_map, 0, sizeof cft_fuzz_map);
        prev_loc = 0;
        exec_tick++;
        t->run(cur_input, cur_len);
        execs++;

        if (has_new_coverage()) {
            queue_push(cur_input, cur_len);
            save_queue_entry(cur_input, cur_len, execs);
        }
        if (execs >= report_at) {
            double el = now_s() - t0;
            fprintf(stderr, "  %s: %llu execs, %.0f/s, %lu corpus, %.0fs\n",
                    t->name, execs, el > 0 ? (double)execs / el : 0.0,
                    (unsigned long)nqueue, el);
            report_at = execs + 200000;
        }
    }

    {
        double el = now_s() - t0;
        size_t used = 0;
        for (i = 0; i < (int)CFT_FUZZ_MAP_SIZE; i++)
            if (virgin[i])
                used++;
        printf("%s: %llu executions in %.1fs (%.0f/s), corpus %lu, "
               "map %lu/%u buckets\n",
               t->name, execs, el, el > 0 ? (double)execs / el : 0.0,
               (unsigned long)nqueue, (unsigned long)used,
               (unsigned)CFT_FUZZ_MAP_SIZE);
    }
    return 0;
}
