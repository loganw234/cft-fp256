/* timer for the 21 (function, n) slices of parcel M3XN: raw_tfn and ieee_tfn_oracle at 24 bits over COUNT uniformly random 32-bit x (the slice's own population: every pattern of the free operand), n fixed; build from docs/studies/m3: gcc -O2 -o timer pw32n_oracle_timer.c -lmpfr -lgmp (mingw64, MPFR 4.2.2); run: timer [COUNT, default 2^20]; TIME is the process's CPU time (clock_gettime CLOCK_PROCESS_CPUTIME_ID); the first version used clock(), which on Windows is WALL-CLOCK time since the process began, not CPU time (send-back 1); a C long is 32 bits there, so n = -2^63 is not timed */
#include <time.h>
static double now(void){ struct timespec ts; clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &ts); return ts.tv_sec + 1e-9 * ts.tv_nsec; }
#include "../../../host/tools/mpfr_tfn.h"
static const fdesc F32 = { "fp32", CFT_FP32, 8, 23, 24, 127, -126, 4 };
static uint64_t s = 88172645463325252ULL;
static uint32_t rnd32(void){ s ^= s << 13; s ^= s >> 7; s ^= s << 17; return (uint32_t)(s >> 16); }
int main(int argc, char **argv)
{
    int cnt = argc > 1 ? atoi(argv[1]) : (1 << 20);
    int fns[3] = { TF_POWN, TF_ROOTN, TF_COMPOUND };
    long ns[7] = { 2, -2, 3, -3, 17, 2147483647L, 0 };
    mpfr_t a, b, r, o;
    uint32_t *xs = malloc(sizeof(uint32_t) * cnt);
    int i, fi, ni;
    static const mpfr_rnd_t RN[5] = { MPFR_RNDN, MPFR_RNDZ, MPFR_RNDD, MPFR_RNDU, MPFR_RNDN };
    mpfr_init2(a, 24); mpfr_init2(b, 24); mpfr_init2(r, 24); mpfr_init2(o, 24);
    mpfr_set_ui(b, 0, MPFR_RNDN);
    for (i = 0; i < cnt; i++) xs[i] = rnd32();
    volatile long sink = 0;
    for (fi = 0; fi < 3; fi++) for (ni = 0; ni < 7; ni++) {
        long n = ns[ni]; double t0, t1, t2, t3; uint32_t fl; uint8_t ba[4], bb[4] = {0,0,0,0};
        int k;
        if (ni == 6) { printf("%s n=-9223372036854775808 rand N=NOFIT: not timed, a C long here is 32 bits\n", TFN_NAME[fns[fi]]); continue; }
        t0 = now();
        for (i = 0; i < cnt; i++) {
            ba[0] = xs[i]; ba[1] = xs[i] >> 8; ba[2] = xs[i] >> 16; ba[3] = xs[i] >> 24;
            enc_to_mpfr(&F32, ba, a);
            sink += 1;
        }
        t1 = now();
        for (i = 0; i < cnt; i++) {
            ba[0] = xs[i]; ba[1] = xs[i] >> 8; ba[2] = xs[i] >> 16; ba[3] = xs[i] >> 24;
            enc_to_mpfr(&F32, ba, a);
            raw_tfn(r, fns[fi], a, b, n, MPFR_RNDN);
            sink += mpfr_zero_p(r);
        }
        t2 = now();
        for (i = 0; i < cnt; i++) {
            ba[0] = xs[i]; ba[1] = xs[i] >> 8; ba[2] = xs[i] >> 16; ba[3] = xs[i] >> 24;
            ieee_tfn_oracle(&F32, fns[fi], MPFR_RNDN, 0, ba, bb, n, o, &fl);
            sink += fl;
        }
        t3 = now();
        {
            double t4, t5 = 0;
            t4 = now();
            for (i = 0; i < cnt; i++) {
                ba[0] = xs[i]; ba[1] = xs[i] >> 8; ba[2] = xs[i] >> 16; ba[3] = xs[i] >> 24;
                for (k = 0; k < 5; k++) {
                    ieee_tfn_oracle(&F32, fns[fi], RN[k], k == 4, ba, bb, n, o, &fl);
                    sink += fl;
                }
            }
            t5 = now();
            printf("%s n=%ld rand N=%ld: raw_tfn %.3f us, oracle x1 %.3f us, oracle x5 %.3f us a lane (sink %ld, mpfr %s)\n",
                   TFN_NAME[fns[fi]], n, n,
                   1e6 * (t2 - t1) / cnt,
                   1e6 * (t3 - t2) / cnt,
                   1e6 * (t5 - t4) / cnt, (long)sink, MPFR_VERSION_STRING);
            fflush(stdout);
        }
    }
    return 0;
}
