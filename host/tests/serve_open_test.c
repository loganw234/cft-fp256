/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cft-serve answers a request on a connection whose device would not
 * open with THAT OPEN'S reason, whatever the other connections did in
 * between (KL-490, 2026-10-22).
 *
 * The reason is cft_last_error() as the failed cft_open left it, and
 * that slot belongs to the most recent status-returning call in the
 * process (cft.h). The server runs every connection's calls in one
 * thread, in turn, so by the time a later request on connection A says
 * "no device", connection B has made a call of its own: a failing one
 * leaves its own sentence, and since cft_last_error() became the last
 * call's, a succeeding one leaves none. Either way A's request, which
 * read the slot at answer time, said B's reason or no reason. The server
 * now copies the sentence into the connection when the open fails.
 *
 * This file includes the server whole with its main() renamed, as
 * fuzz/fuzz_serve.c does, and calls the handlers the dispatcher calls, so
 * what it holds is the answer a client would receive (answer.msg), not a
 * helper's. It needs no socket and no second process. The test takes the
 * open's sentence itself, straight after the open, which is what a client
 * of the library does; it names no field of the server's, so it builds
 * against a server that keeps no copy, and is red there.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define main cft_serve_main_unused
#include "../tools/cft-serve.c"
#undef main

static int failures;

#define CHECK(cond, ...)                                                 \
    do {                                                                 \
        if (!(cond)) {                                                   \
            printf("FAIL %s:%d: ", __FILE__, __LINE__);                  \
            printf(__VA_ARGS__);                                         \
            printf("\n");                                                \
            failures++;                                                  \
        }                                                                \
    } while (0)

static void put32(uint8_t *p, uint32_t v) { cftr_put32(p, v); }

/* RUN or REDUCE with no operands and no elements: 24 bytes, the shape
 * h_run's length check admits for n = 0 */
static void run_req(uint8_t *p, uint32_t op, uint32_t fmt)
{
    memset(p, 0, 24);
    put32(p + 0, op);
    put32(p + 4, fmt);
}

/* One request on A, whose device did not open: the handler must answer
 * with A's open status and the open's own words, and nothing of B's. */
static int legs;

static void on_a(const char *what, int rc, const answer *ans,
                 cft_status open_status, const char *open_said,
                 const char *b_said)
{
    legs++;
    CHECK(rc == 0, "%s: the handler refused the frame (rc %d), so it never "
          "reached the device check: %s", what, rc, ans->why);
    CHECK(ans->status == (int)open_status,
          "%s: status %d, wanted the open's %d", what, ans->status,
          (int)open_status);
    CHECK(strstr(ans->msg, open_said) != NULL,
          "%s: the answer does not carry the open's sentence \"%s\": "
          "\"%s\"", what, open_said, ans->msg);
    if (b_said && *b_said)
        CHECK(strstr(ans->msg, b_said) == NULL,
              "%s: the answer carries the OTHER connection's sentence "
              "\"%s\": \"%s\"", what, b_said, ans->msg);
}

/* A's five handlers that stop at no_device(), each on a frame well
 * formed enough to reach it */
static void a_requests(conn *A, const char *tag, cft_status open_status,
                       const char *open_said, const char *b_said)
{
    uint8_t req[28];
    answer ans;
    char what[80];
    int rc;

    run_req(req, CFT_ADD, CFT_FP64);
    memset(&ans, 0, sizeof ans);
    rc = h_run(A, req, 24, &ans, 0);
    snprintf(what, sizeof what, "%s, RUN", tag);
    on_a(what, rc, &ans, open_status, open_said, b_said);

    memset(&ans, 0, sizeof ans);
    rc = h_run(A, req, 24, &ans, 1);
    snprintf(what, sizeof what, "%s, REDUCE", tag);
    on_a(what, rc, &ans, open_status, open_said, b_said);

    memset(req, 0, sizeof req);
    put32(req + 0, CFT_SUM);
    put32(req + 4, CFT_FP64);
    put32(req + 24, 1);                         /* seg 1, n 0 */
    memset(&ans, 0, sizeof ans);
    rc = h_reduce_seg(A, req, 28, &ans);
    snprintf(what, sizeof what, "%s, REDUCE_SEG", tag);
    on_a(what, rc, &ans, open_status, open_said, b_said);

    memset(&ans, 0, sizeof ans);
    rc = h_prog_load(A, req, 1, &ans);
    snprintf(what, sizeof what, "%s, PROG_LOAD", tag);
    on_a(what, rc, &ans, open_status, open_said, b_said);

    memset(req, 0, 8);
    put32(req, 64);                             /* a 64-byte buffer */
    memset(&ans, 0, sizeof ans);
    rc = h_buf_alloc(A, req, 8, &ans);
    snprintf(what, sizeof what, "%s, BUF_ALLOC", tag);
    on_a(what, rc, &ans, open_status, open_said, b_said);
}

int main(void)
{
    conn A, B;
    answer ans;
    uint8_t req[24];
    char open_said[512], b_said[512];
    int rc;

    memset(&A, 0, sizeof A);
    A.open = 1; A.s = CFTR_BAD_SOCK; A.id = 1;
    A.artifact = "p2b-no-such-image.xclbin";
    memset(&B, 0, sizeof B);
    B.open = 1; B.s = CFTR_BAD_SOCK; B.id = 2;
    B.artifact = NULL;                          /* the software device */

    /* A's device would not open, and the library said why. */
    CHECK(conn_device(&A) == NULL && A.dev == NULL && A.open_status != CFT_OK,
          "connection A opened %s: status %d", A.artifact,
          (int)A.open_status);
    snprintf(open_said, sizeof open_said, "%s", cft_last_error());
    CHECK(*open_said != '\0', "the failed open left no sentence, so the "
          "legs below would prove nothing");

    /* B's device opens, and B makes a FAILING call of its own: a format
     * that is no format, which the library refuses with its own sentence. */
    CHECK(conn_device(&B) != NULL && B.dev != NULL,
          "connection B's software device did not open: status %d",
          (int)B.open_status);
    run_req(req, CFT_ADD, 9);
    memset(&ans, 0, sizeof ans);
    rc = h_run(&B, req, 24, &ans, 0);
    CHECK(rc == 0 && ans.status == CFT_ERR_INVALID_ARGUMENT,
          "B's failing call: rc %d, status %d", rc, ans.status);
    snprintf(b_said, sizeof b_said, "%s", cft_last_error());
    CHECK(*b_said != '\0' && strcmp(b_said, open_said) != 0,
          "B's failing call left \"%s\", which must be a sentence of its "
          "own and not A's \"%s\"", b_said, open_said);
    a_requests(&A, "after B's failing call", A.open_status, open_said,
               b_said);

    /* B makes a call that SUCCEEDS, which empties the slot. */
    run_req(req, CFT_ADD, CFT_FP64);
    memset(&ans, 0, sizeof ans);
    rc = h_run(&B, req, 24, &ans, 0);
    CHECK(rc == 0 && ans.status == CFT_OK, "B's good call: rc %d, status %d",
          rc, ans.status);
    CHECK(*cft_last_error() == '\0', "a call that succeeded left \"%s\"",
          cft_last_error());
    a_requests(&A, "after B's good call", A.open_status, open_said, NULL);

    cft_close(B.dev);
    printf("serve-open-test: %d requests on a connection whose device did not "
           "open, each after another connection's failing call and after "
           "its good one%s\n", legs,
           failures ? "" : " - every answer carries the open's own sentence");
    if (failures)
        printf("serve-open-test: %d FAILED\n", failures);
    else
        printf("serve-open-test: all checks passed\n");
    return failures ? 1 : 0;
}
