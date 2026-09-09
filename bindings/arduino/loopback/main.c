/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cft-replay-loopback - the CSRP/1 responder, on stdin and stdout.
 *
 * WHY THIS EXISTS. host/tools/serial_replay.py is the thing that will
 * say whether a board computes the published vectors correctly, and a
 * checker that has never been seen to work - or, worse, never been
 * seen to FAIL - proves nothing about the board it passes. So the same
 * responder the sketch runs is built here as a host process speaking
 * the same protocol over pipes, and the harness is driven against it
 * over the whole census before any board is plugged in. Two things
 * come out of that:
 *
 *   the harness is exercised end to end, every verb and every set,
 *   at a rate no UART could reach; and
 *
 *   the reduced build profiles are exercised too. This links the
 *   VENDORED copy of libcft under bindings/arduino/cft-arduino/src/cft
 *   - the bytes that go on the part, whose hashes vendor.json records
 *   - so `--profile tiny` replaying the fp32 and fp64 sets is the AVR
 *   core's arithmetic being held to the golden model on a machine
 *   where the whole census takes minutes.
 *
 * AND WHY IT CAN LIE ON PURPOSE. --corrupt damages exactly one answer,
 * in one of six ways, and the harness is required to notice. A negative
 * control is the only evidence that a green report is not a report of
 * a checker that always says green; the six modes are chosen to hit
 * six different parts of the host's checking - the encoding compare,
 * the flag compare, the frame's CRC, the sequence number, the timeout,
 * and the character-sequence compare that goes through `get`.
 *
 *   cft-replay-loopback [--line N] [--stage N] [--out N]
 *                       [--corrupt MODE] [--corrupt-at N]
 *
 * Reads one request line per line of stdin, writes one response line
 * per line of stdout, and exits 0 at end of input.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cft.h"
#include "cft_replay.h"

/* The corruption modes. See the banner. */
enum {
    CO_NONE = 0,
    CO_BITS,     /* flip a digit of the first result field           */
    CO_FLAGS,    /* flip a digit of the last field before the CRC    */
    CO_CRC,      /* leave the answer right and the checksum wrong    */
    CO_SEQ,      /* answer the wrong sequence number                 */
    CO_DROP,     /* answer nothing at all                            */
    CO_TEXT      /* damage a character sequence coming back from get */
};

static const struct { const char *name; int mode; } CO_NAMES[] = {
    { "bits",  CO_BITS  },
    { "flags", CO_FLAGS },
    { "crc",   CO_CRC   },
    { "seq",   CO_SEQ   },
    { "drop",  CO_DROP  },
    { "text",  CO_TEXT  },
    { NULL, 0 }
};

static const char HEXD[] = "0123456789abcdef";

static int hexval(int c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;
}

/* Recompute the trailing " *CCCC" so a damaged answer is a WELL-FORMED
 * damaged answer. Anything less would be caught by the frame check
 * rather than by the comparison the mode is aimed at, and a control
 * that trips the wrong alarm has not tested the right one. */
static void refresh_crc(char *line)
{
    size_t n = strlen(line);
    uint16_t crc;
    if (n < 6)
        return;
    crc = cft_replay_crc16(line, n - 6);
    line[n - 4] = HEXD[(crc >> 12) & 0xf];
    line[n - 3] = HEXD[(crc >> 8) & 0xf];
    line[n - 2] = HEXD[(crc >> 4) & 0xf];
    line[n - 1] = HEXD[crc & 0xf];
}

/* Flip one hex digit of field `idx` (0 = the status word `ok`). */
static int flip_field(char *line, int idx)
{
    char *p = line, *end = line + strlen(line);
    int f = -1;
    while (p < end) {
        while (p < end && *p == ' ')
            p++;
        f++;
        if (f == idx + 1) {          /* +1: field 0 is "<SS" */
            char *q = p;
            while (q < end && *q != ' ')
                q++;
            while (q > p) {
                int v = hexval((unsigned char)q[-1]);
                if (v >= 0) {
                    q[-1] = HEXD[(v + 1) & 0xf];
                    return 1;
                }
                q--;
            }
            return 0;
        }
        while (p < end && *p != ' ')
            p++;
    }
    return 0;
}

/* Flip one hex digit of the last field before " *CCCC". */
static int flip_last(char *line)
{
    size_t n = strlen(line);
    char *p;
    if (n < 8)
        return 0;
    p = line + n - 6;                /* at the ' ' before '*' */
    while (p > line && p[-1] != ' ') {
        int v = hexval((unsigned char)p[-1]);
        if (v >= 0) {
            p[-1] = HEXD[(v + 1) & 0xf];
            return 1;
        }
        p--;
    }
    return 0;
}

/* The request's verb, copied out before the responder tokenises the
 * line in place. NULL if the line is not a request at all. */
static const char *verb_of(const char *line, char *buf, size_t cap)
{
    size_t i = 0;
    if (line[0] != '>' || !line[1] || !line[2] || line[3] != ' ')
        return NULL;
    line += 4;
    while (line[i] && line[i] != ' ' && i + 1 < cap) {
        buf[i] = line[i];
        i++;
    }
    buf[i] = '\0';
    return buf;
}

/* Which answers --corrupt-at counts.
 *
 * Not "every answer": the first line of any session is the harness
 * asking `id`, and damaging that tests nothing about the case
 * comparison - it tests whether the harness minds being told the
 * device speaks a different protocol version, which it does, for the
 * wrong reason. The default is every verb that returns a COMPUTED
 * value, and --corrupt-verb narrows it to one when a mode needs a
 * particular shape of answer (the `text` mode needs a `get`). */
static int corruptible(const char *verb, const char *only)
{
    if (!verb)
        return 0;
    if (only)
        return strcmp(verb, only) == 0;
    return strcmp(verb, "run") == 0 || strcmp(verb, "trn") == 0 ||
           strcmp(verb, "aug") == 0 || strcmp(verb, "mmg") == 0 ||
           strcmp(verb, "fof") == 0 || strcmp(verb, "red") == 0 ||
           strcmp(verb, "chs") == 0 || strcmp(verb, "chw") == 0 ||
           strcmp(verb, "pay") == 0 || strcmp(verb, "get") == 0;
}

static void usage(void)
{
    fputs("cft-replay-loopback [--line N] [--stage N] [--out N]\n"
          "                    [--corrupt bits|flags|crc|seq|drop|text]\n"
          "                    [--corrupt-at N] [--corrupt-verb VERB]\n",
          stderr);
}

int main(int argc, char **argv)
{
    size_t line_cap = 1024, stage_cap = 262144, out_cap = 262144;
    const char *corrupt_verb = NULL;
    long corrupt_at = 1;
    int corrupt = CO_NONE;
    cft_device *dev = NULL;
    cft_replay R;
    char *in = NULL, *resp = NULL;
    uint8_t *st0 = NULL, *st1 = NULL;
    char *outbuf = NULL;
    size_t in_cap;
    long answered = 0;
    int i, rc = 0;

    for (i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--line") && i + 1 < argc)
            line_cap = (size_t)strtoul(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--stage") && i + 1 < argc)
            stage_cap = (size_t)strtoul(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--out") && i + 1 < argc)
            out_cap = (size_t)strtoul(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--corrupt-at") && i + 1 < argc)
            corrupt_at = strtol(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--corrupt-verb") && i + 1 < argc)
            corrupt_verb = argv[++i];
        else if (!strcmp(argv[i], "--corrupt") && i + 1 < argc) {
            int k;
            const char *want = argv[++i];
            corrupt = -1;
            for (k = 0; CO_NAMES[k].name; k++)
                if (!strcmp(CO_NAMES[k].name, want))
                    corrupt = CO_NAMES[k].mode;
            if (corrupt < 0) {
                fprintf(stderr, "unknown corruption mode: %s\n", want);
                usage();
                return 2;
            }
        } else {
            usage();
            return 2;
        }
    }
    if (line_cap < 64)
        line_cap = 64;

    /* The response buffer has to hold the longest line this responder
     * will emit, which is a `get` of a full line's worth of hex plus
     * the frame. Generous rather than exact: this is a host process,
     * and an off-by-one here would show up as a refusal on a case that
     * the board would have answered. */
    in_cap = 2 * line_cap + 4096;
    in = (char *)malloc(in_cap);
    resp = (char *)malloc(in_cap);
    st0 = (uint8_t *)malloc(stage_cap ? stage_cap : 1);
    st1 = (uint8_t *)malloc(stage_cap ? stage_cap : 1);
    outbuf = (char *)malloc(out_cap ? out_cap : 1);
    if (!in || !resp || !st0 || !st1 || !outbuf) {
        fputs("out of memory\n", stderr);
        return 2;
    }

    if (cft_open(NULL, 0, &dev) != CFT_OK) {
        fprintf(stderr, "cft_open: %s\n", cft_last_error());
        return 2;
    }
    if (cft_replay_init(&R, dev, st0, st1, stage_cap, outbuf, out_cap,
                        line_cap)) {
        fputs("cft_replay_init failed\n", stderr);
        cft_close(dev);
        return 2;
    }

    while (fgets(in, (int)in_cap, stdin)) {
        size_t n = strlen(in);
        char vbuf[16];
        const char *verb;
        int len, damage;
        while (n && (in[n - 1] == '\n' || in[n - 1] == '\r'))
            in[--n] = '\0';
        if (n == 0)
            continue;
        verb = verb_of(in, vbuf, sizeof vbuf);
        damage = corruptible(verb, corrupt_verb);
        len = cft_replay_line(&R, in, resp, in_cap);
        if (len < 0) {
            fputs("response did not fit\n", stderr);
            rc = 2;
            break;
        }
        if (damage)
            answered++;

        if (corrupt != CO_NONE && damage && answered == corrupt_at) {
            switch (corrupt) {
            case CO_BITS:  flip_field(resp, 1); refresh_crc(resp); break;
            case CO_FLAGS: flip_last(resp);     refresh_crc(resp); break;
            case CO_TEXT:  flip_field(resp, 1); refresh_crc(resp); break;
            case CO_SEQ:   resp[1] = HEXD[(hexval((unsigned char)resp[1])
                                           + 1) & 0xf];
                           refresh_crc(resp); break;
            case CO_CRC:   {
                size_t rn = strlen(resp);
                if (rn >= 4)
                    resp[rn - 1] = HEXD[(hexval((unsigned char)resp[rn - 1])
                                         + 1) & 0xf];
                break;
            }
            case CO_DROP:  continue;
            default: break;
            }
        }

        fputs(resp, stdout);
        fputc('\n', stdout);
        fflush(stdout);
    }

    cft_close(dev);
    fprintf(stderr, "loopback: %lu requests, %lu ok, %lu err\n",
            (unsigned long)R.n_lines, (unsigned long)R.n_ok,
            (unsigned long)R.n_err);
    free(in); free(resp); free(st0); free(st1); free(outbuf);
    return rc;
}
