#!/bin/bash
# GPU-E measurements on this desktop's CPU (WSL cft-gpu), from the clone at
# /root/gpu-e/cft-rebound (cft-rebound 7a7a279, its pinned cft-fp256 922c2ad).
# One process at a time (no -j). Every run is ias15_cft on the software
# backend: REBOUND's form and the loop engine unless the label says fma,
# --max-iter 60, the default corrector tolerance (1e-16 scaled by 2^(53-p)),
# the default first step 0.01, PRS23 (REBOUND's default step criterion).
#   A: one massless ring particle on a circular orbit (G = M = r = 1, period
#      2 pi): steps per orbit and passes per step by format and epsilon
#   B: the div/sqrt call identity: 100 and 200 steps, two samples each
#   C: an ensemble of 8 such systems at r = 1.0 .. 1.7 (radial spread)
#   D: one system holding the same 8 ring particles (shared step)
#   E: one system with 16 and 32 ring particles (shared step, larger N)
set -u
exec 2>&1
BIN=/root/gpu-e/cft-rebound/build/ias15_cft
W=/root/gpu-e/work
mkdir -p "$W"; cd "$W" || exit 2
echo "== runs start $(date '+%F %T') loadavg $(cat /proc/loadavg)"
python3 - <<'PY'
import math
def body(name, m, x, y, z, vx, vy, vz):
    return "body %s %s %s %s %s %s %s %s" % (name, m.hex(), x.hex(), y.hex(), z.hex(), vx.hex(), vy.hex(), vz.hex())
def tp(r, ang):
    v = math.sqrt(1.0 / r)
    return (r * math.cos(ang), r * math.sin(ang), 0.0, -v * math.sin(ang), v * math.cos(ang), 0.0)
cen = body("planet", 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
# A/B: one ring particle at r = 1 on the x axis
with open("ring1.txt", "w") as f:
    f.write("# GPU-E: central mass 1 at rest, one massless particle on a circular orbit at r = 1, G = 1\n")
    f.write("name ring1\nG %s\nN 2\n%s\n%s\n" % ((1.0).hex(), cen, body("p0", 0.0, *tp(1.0, 0.0))))
radii = [1.0 + 0.1 * k for k in range(8)]
# C: ensemble of 8 two-body systems, one particle each, r = 1.0 .. 1.7
with open("ens8.txt", "w") as f:
    f.write("# GPU-E: 8 systems, each the central mass and one ring particle at r_k\n")
    f.write("name ens8\nG %s\nN 2\nE 8\n" % (1.0).hex())
    for k, r in enumerate(radii):
        f.write("system r%d\n%s\n%s\n" % (k, cen, body("p%d" % k, 0.0, *tp(r, 2 * math.pi * k / 8))))
# D/E: one system, the central mass and n ring particles spread over r = 1.0 .. 1.7
def shared(n, path):
    with open(path, "w") as f:
        f.write("# GPU-E: one system, the central mass and %d massless ring particles, r = 1.0 .. 1.7\n" % n)
        f.write("name ring%d\nG %s\nN %d\n%s\n" % (n, (1.0).hex(), n + 1, cen))
        for k in range(n):
            r = 1.0 + 0.7 * k / (n - 1)
            f.write(body("p%d" % k, 0.0, *tp(r, 2 * math.pi * k / n)) + "\n")
shared(8, "ring8.txt"); shared(16, "ring16.txt"); shared(32, "ring32.txt")
print("problem files written")
PY
run(){  # label format eps steps sample problem [extra args]
    local label=$1 fmt=$2 eps=$3 steps=$4 sample=$5 prob=$6; shift 6
    local t0=$(date +%s.%N)
    echo "-- $label start $(date '+%F %T') loadavg $(cat /proc/loadavg | cut -d' ' -f1-3)"
    "$BIN" --format "$fmt" --problem "$prob" --epsilon "$eps" --steps "$steps" --sample "$sample" --max-iter 60 --quiet "$@" > "$label.rec"
    local rc=$?
    local t1=$(date +%s.%N)
    echo "-- $label end rc=$rc wall=$(python3 -c "print('%.1f' % ($t1 - $t0))") s"
}
# A: steps per orbit and passes, REBOUND's form
run A_fp64_e9    fp64  1e-9  200 100 ring1.txt
run A_fp128_e9   fp128 1e-9  200 100 ring1.txt
run A_fp128_e12  fp128 1e-12 200 100 ring1.txt
run A_fp128_e16  fp128 1e-16 200 100 ring1.txt
run A_fp256_e9   fp256 1e-9  200 100 ring1.txt
run A_fp256_e12  fp256 1e-12 200 100 ring1.txt
run A_fp256_e16  fp256 1e-16 200 100 ring1.txt
run A_fp256_e20  fp256 1e-20 200 100 ring1.txt
run A_fp256_e24  fp256 1e-24 200 100 ring1.txt
# A, the FMA form at two settings (the form a GPU port would run fastest)
run A_fp128_e12_fma fp128 1e-12 200 100 ring1.txt --arith fma
run A_fp256_e16_fma fp256 1e-16 200 100 ring1.txt --arith fma
# B: the div/sqrt identity, two samples in each run
run B_fp64_e9_100     fp64  1e-9  100 100 ring1.txt
run B_fp64_e9_200     fp64  1e-9  200 200 ring1.txt
run B_fp128_e12_100   fp128 1e-12 100 100 ring1.txt
run B_fp128_e12_200   fp128 1e-12 200 200 ring1.txt
run B_fp256_e16f_100  fp256 1e-16 100 100 ring1.txt --arith fma
run B_fp256_e16f_200  fp256 1e-16 200 200 ring1.txt --arith fma
# C: the radial spread as an ensemble, each member its own step
run C_ens8_fp64_e9    fp64  1e-9  200 100 ens8.txt
run C_ens8_fp128_e12  fp128 1e-12 200 100 ens8.txt
# D: the same 8 particles in one system, one shared step
run D_ring8_fp64_e9   fp64  1e-9  200 100 ring8.txt
run D_ring8_fp128_e12 fp128 1e-12 200 100 ring8.txt
# E: more particles in one shared-step system
run E_ring16_fp64_e9  fp64  1e-9  200 100 ring16.txt
run E_ring32_fp64_e9  fp64  1e-9  100 50  ring32.txt
echo "== runs end $(date '+%F %T') loadavg $(cat /proc/loadavg)"
ls -la "$W"
