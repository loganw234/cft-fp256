# Study ACC-A: how well a certificate's two estimates indicate

STATUS: a measurement study, 2026-09-30. Parcel S2 of the round planned
in docs/ROADMAP.md, "Steps 5 and 6: accuracy in C, and cft-orbits' runs
certified". What it changed in the tree:
- `programs/check.py`: its 300-digit arm's reference became two
  functions, `scheme_exact` and `scheme_run`, which `check_ode` calls.
  check.py's output is unchanged apart from two lines, both explained in
  section 1.3;
- `programs/estimates.py`, new: the instrument;
- `docs/studies/acc-a/`: the instrument's two captured runs;
- this file, and its row in docs/README.md.

No C, and no certificate, image or program, was changed. **Nothing here
is a bound.** docs/CERTIFICATES.md says an estimate "indicates an error
without bounding it". This measures how well it indicates, on the runs
the corpus certifies, and says where the measurement stops.

Every number below is one of three kinds and says which:

- **RUN**: printed by `programs/estimates.py`. Its two captured runs are
  `docs/studies/acc-a/certified.out.txt` and `sweep.out.txt`, so any
  figure here can be diffed against a re-run; only lines beginning
  `time` should move (section 9).
- **READ**: out of the tree, with the file it came from.
- **BELIEVED**: reasoned, or taken from the literature, and not
  measured here. Each one says so.

## 0. The short answers

1. **Step-halving is a steady fraction of the method error, near
   Richardson's.** At the certified horizon it is:
   - 0.9525 of the method error on Lorenz-63 (RK4);
   - 0.9367 on Lorenz-96 (RK4);
   - 0.750002 on Henon-Heiles (Stormer-Verlet).
   Each is RUN, with an uncertainty of at most 3.6e-7.

   Richardson's factor 1 - 2^-p is 15/16 = 0.9375 for RK4 and 3/4 for
   Stormer-Verlet. So Henon-Heiles meets it to 2e-6 and Lorenz-96 to
   0.0009. Lorenz-63 is 0.015 above it: at h = 0.01 its error is not yet
   in RK4's h^4 regime. The excess halves with each halving of h
   (section 5).
2. **Wider is the rounding error of the certified arithmetic.** W/rho -
   1 is at most 1e-17 in every lane of every fp64 case, and at every
   level of the sweep. That holds because the fp128 run's own rounding
   is 2^60 times smaller. RUN.
3. **There is an error neither estimate sees.** RK4's bank carries h/6
   ROUNDED. So the fp64 scheme converges to the ODE's solution at a
   shifted time, y((1 + delta) t), with delta = 4.34e-17.
   - On Lorenz-63 lane 0 the shift is 3.5e-15: twice that lane's whole
     fp64 rounding error. RUN.
   - The half-step run halves h/6 exactly and the wider run widens it
     exactly, so neither sees it.
   - At fp256 the shift is exactly 0: that format's h has a significand
     divisible by 3, so h/6 is exact. RUN.
4. **As h shrinks, fp64 rounding takes over.** Past that point the
   step-halving estimate measures rounding, not method error.
   - Lorenz-63: the estimate goes from 0.95 of the method error to 274
     times it by h/512.
   - Lorenz-96: from 0.94 to 2,769 times it by h/128.
   - Throughout, it stays within a factor of 3 of the TOTAL error.
   - Near the crossover it also carries the half-step run's rounding,
     which no entry estimates.
   - Stormer-Verlet is still method-dominated at h/1024.
   All RUN.
5. **Read with that in mind, a certificate on these programs says the
   following.**
   - Where W/E is small (here 2e-7 or less at h = 0.01), the true method
     error is E/0.95 to E/0.75. Richardson's correction recovers it to
     1.6% on these programs.
   - Where W is not small against E, E is not a method error at all.
   - Neither estimate covers the rounding of the bank's derived
     constants.

## 1. What was measured, and how

### 1.1 The two estimates (READ: docs/CERTIFICATES.md, "Accuracy entries")

**Step-halving E** is the largest absolute difference, over the state's
slots, between the main run's final state F0 and a half-step run's F1:
- the half-step run uses the same image;
- its bank's h-slots are exactly halved;
- it runs twice the segments, from the same start.

**Wider W** is the same difference against a run one format wider:
- the same instructions;
- the constants, streams and start exactly widened.

Both are computed here by `cert.derive`, the page's own function, on the
certified states. The two estimates the corpus certificates carry equal
it: RUN, "the certificate's entry ... holds its derived value".
- lorenz63-rk4-fp64's step-halving is 0x81e790cdd/2^48 = 1.2388664e-4;
- `example`'s is 6.1097814e-6.

### 1.2 The cases (READ: certificates/MANIFEST)

Every ODE case of the golden corpus that has an auxiliary run, every
lane. host/tests/segrun_check.py certifies the same runs: the same
ensembles, lanes, segments and banks.

| case | lanes | main: segments x steps | T | estimates |
|---|---|---|---|---|
| lorenz63-rk4-fp64 | 3 | 3 x 100 | 300 H | step-halving, wider |
| lorenz63-rk4-fp256 | 3 | 3 x 100 | 300 H | step-halving |
| lorenz96-rk4-fp64 | 2 | 2 x 20 | 40 H | step-halving, wider |
| lorenz96-rk4-fp256 | 2 | 2 x 20 | 40 H | step-halving |
| henonheiles-lf-fp64 | 4 | 4 x 100 | 400 H | step-halving, wider |
| henonheiles-lf-fp256 | 4 | 4 x 100 | 400 H | step-halving |
| example (keyed) | 2 | 2 x 100 | 200 H | step-halving |

**H is each format's rounded 0.01.** At fp64 it is 0.01 + 2.082e-19, so
300 H = 3 + 6.2e-17. At fp256 it is 0.01 - 5.66e-75. Every reference
below integrates to exactly N x H, not to the decimal time: RUN, each
case's `T =` line.

**How the states are held.** Before use, every state file is held to its
manifest SHA-256 and to its certificate's hash.

**`example`** is Henon-Heiles fp64, lanes 0 and 1, over half the
horizon. Its rows equal henonheiles-lf-fp64's at the same boundaries, as
they must.

**Not scored, by name** (RUN, the `not scored` lines):
- lorenz63-rk4-fp64-half-init: it states a relation that is false on
  purpose, which the audit refuses `aux-start`. Its half-step run starts
  elsewhere, so its difference estimates nothing;
- deepwrap-fp64-256 and -2048: not an ODE program; its half-step run
  halves a slot that steps no equation;
- flagstep-fp64 and augsum-fp64: not ODE programs, and no auxiliary run.

**A wider run at fp256 does not exist.** The golden audit, handed each
fp256 case's own certificate with its main run attached again as a
wider run, refuses it `aux-format`, exit 5: "the main run is fp256, the
top of the ladder". RUN, for all three cases.

### 1.3 The rounding reference: check.py's 300-digit arm, callable

**What the arm computes.** check.py's `scheme` arm runs `ode_step`,
check.py's mirror of the program's rounding order, through `_MpOps`: the
five operations in mpmath at 300 digits. It starts from the bank's and
the state's exact values. That is the program's own scheme with its
roundings taken out.

**The refactor** (commit e8cea9b):
- `scheme_exact(fmt, bits)` gives an encoding's exact value;
- `scheme_run(base, Km, lanes, steps)` runs the scheme;
- `check_ode` calls both and keeps its verdict and its 300-digit
  context.

**The proof** is check.py's whole output before and after, both 341
passed and 0 failed. Two lines differ:
- the time;
- the independence census's count of names check.py binds at module
  level, 150 then 153. The census's own set difference is exactly
  `SCHEME_DPS`, `scheme_exact` and `scheme_run`.
All 161 ODE-row lines are identical, byte for byte.

**R_0** is `scheme_run` over the whole certified run, from boundary 0:
the ROUNDING REFERENCE of the main run. The main run's rounding error is
rho = max |F0 - R_0|.

**R_0's own arithmetic** was checked against the same computation at 400
digits. The largest difference in any case is 2.3e-299: RUN, the `400
digits` line of each case.

### 1.4 The converged reference: the scheme at h/2^k

**Level k** (R_k) is R_0's computation with three changes:
- the bank's h-slots exactly halved k times. These are slots 0 to 2 in
  every bank here (H, H2, H6 or H, H2, MH), held to the certificate's
  own h-slot list;
- 2^k times the steps;
- the state kept at every boundary of the certified run.
It is the certificate's half-step construction applied k times: R_1 is
the half-step run's rounding reference.

**Precision.** 300 digits (1,000 bits) at both formats. That is 947 bits
below fp64's unit roundoff and 763 below fp256's.
- Going lower costs almost nothing less: 50 digits were at most 15%
  cheaper, measured before the build.
- The deepest level any case reached is Henon-Heiles at K = 11: 819,200
  steps. BELIEVED: its accumulated rounding stays below 1e-290 relative,
  from the step count and the 400-digit check of level 0.

**Converged**, in this study, means the first K >= 3 at which BOTH of
these hold in every lane, at every boundary:
- two successive levels agree to TAU = 1e-6 of the method error:
  max |R_K - R_(K-1)| <= 1e-6 max |R_0 - R_K|;
- their differences are shrinking at the scheme's order: the last
  successive ratio is within 10% of 2^p.
The caps are K = 10 for RK4 and 13 for Stormer-Verlet. A case that
reaches its cap first is named NOT CONVERGED and not scored. **None
did.**
- K = 6 for all four RK4 cases;
- K = 11 for the three Henon-Heiles cases, `example` among them.

**The stated error of R_K** is u = |R_K - R_(K-1)| / (2^p - 1). Every
ratio below carries 2u as its uncertainty.
- The largest u is 4.2e-12 (Lorenz-63), 1.0e-14 (Lorenz-96) and 2.6e-12
  (Henon-Heiles);
- those are 3.2e-8, 6.1e-8 and 2.4e-7 of each method error.

**What converged cannot mean.** It is a statement about THIS horizon.
Section 7 gives the long-horizon limits.

### 1.5 The limit, and the time shift

**Where the scheme converges.** RK4's bank carries H6 = h/6 rounded to
the format, and the half-step construction halves it exactly. So the
scheme at h/2^k is consistent with y' = (1 + delta) f(y), where delta =
6 H6/H - 1, and converges to y((1 + delta) t). That is the solution of
the ODE, with the bank's parameter values (BETA as rounded, for
example), at a SHIFTED time.
- That limit is what the step-halving estimate estimates the distance
  to, and R_K converges to it.
- delta = 4.3368e-17 at fp64, and exactly 0 at fp256: RUN.
- Stormer-Verlet's bank has no rounded derived constant: its H2 and MH
  are exact.

**How the shift is measured** (section 4): odefun evaluates y at both
times, and the difference is the shift.

**Definitions used from here on.** The method error is M = max |R_0 -
R_K|. The certified run's total error, against the same limit, is
max |F0 - R_K|.

### 1.6 An independent cross-check: odefun

**What it is.** mpmath's own Taylor-series integrator, run from the same
exact start with the bank's parameter values, at 30 and 40 digits. It
shares no code with the program, gen_odes.py or `ode_step`: its vector
fields are written again, in textbook form, in `programs/estimates.py`.

**What it gave.** At every lane and every boundary of every case:
- its 30- and 40-digit answers agree to 3e-30 or better;
- its value at (1 + delta) t is 0.98 to 1.04 u from R_K.
RUN, the `odefun at 30 and 40 digits` tables.

**What that shows.** R_K's stated error is its real distance from the
limit, measured by a method that shares nothing with the scheme. It
also shows that the limit IS the ODE's solution at the shifted time, so
a mistake shared by gen_odes.py and `ode_step` would show here.

### 1.7 The sweep, and which reference scored which run

**The runs.** For lane 0 of each system, at levels j = 0..J, cft-segrun
certifies three runs in a scratch directory:
- a main run with the bank halved j times and S x 2^j segments;
- its half-step run;
- at fp64, its wider run.

**How they are held:**
- the golden audit accepts a sample of each certificate;
- level 0 equals lane 0 of the corpus's runs, bit for bit;
- each level's half-step run equals the next level's main run, bit for
  bit.
RUN, every `ok` line of sweep.out.txt.

**The rounding reference** at level j is R_j.

**The method error** at level j is measured against one of two
references:
- **R_L**, lane 0's deepest level (L is 10, 8, 11 and 8 for the four
  sweeps), where 2u_L is at most 0.1% of the level's method error. So
  R_L's own error biases a ratio by no more than 0.1%;
- otherwise **odefun**, where its stated agreement with the scheme's
  limit is at most 1% of it.
- Where neither qualifies, the level is printed unresolved. None was.

**odefun's agreement is shown** on lane 0, level by level (RUN, the
`|R_k - od|` tables):
- |R_k - odefun| / u_k lies within [0.5, 2] at every level from k = 3;
  it tends to 1, as it must if odefun sits at the scheme's limit;
- the deepest level, extrapolated as R_L + (R_L - R_(L-1))/(2^p - 1),
  lands within 2.95e-19 (Lorenz-63), 9.7e-21 (Lorenz-96) and 2.3e-23
  (Henon-Heiles) of odefun.

**The stated agreement** is the largest of three: that distance, how far
the extrapolation moved from level L - 1, and odefun's own 30- against
40-digit difference. It is 4.0e-18, 3.1e-19, 3.5e-22 and 3.9e-15 for
the four sweeps.

**Which reference scored which level** (the `ref` column):

| sweep | R_L | odefun |
|---|---|---|
| lorenz63 fp64 | j = 0..7 | j = 8, 9 |
| lorenz96 fp64 | j = 0..5 | j = 6, 7 |
| henonheiles fp64 | j = 0..5 | j = 6..10 |
| lorenz63 fp256 | j = 0..4 | - |

## 2. Step-halving, scored

At the certified horizon, which is the boundary a certificate states.
E/M is the estimate over the method error, with 2u as its uncertainty
(RUN):

| case | lane | E | M | E/M | E/M - (1 - 2^-p) |
|---|---|---|---|---|---|
| lorenz63-rk4-fp64 | 0 | 1.23887e-4 | 1.30064e-4 | 0.9525064 +- 6.0e-8 | +0.0150 |
| | 1 | 1.23451e-4 | 1.29630e-4 | 0.9523265 +- 6.1e-8 | +0.0148 |
| | 2 | 1.23014e-4 | 1.29196e-4 | 0.9521473 +- 6.1e-8 | +0.0146 |
| | max | 1.23887e-4 | 1.30064e-4 | 0.9525064 +- 6.1e-8 | +0.0150 |
| lorenz63-rk4-fp256 | 0-2, max | the same to 7 digits | | 0.9525064 +- 6.1e-8 | +0.0150 |
| lorenz96-rk4-fp64 | 0 | 7.79955e-8 | 8.32706e-8 | 0.9366516 +- 1.1e-7 | -0.00085 |
| | 1 | 1.55965e-7 | 1.66514e-7 | 0.9366503 +- 1.1e-7 | -0.00085 |
| | max | 1.55965e-7 | 1.66514e-7 | 0.9366503 +- 1.1e-7 | -0.00085 |
| lorenz96-rk4-fp256 | max | 1.55966e-7 | 1.66514e-7 | 0.9366505 +- 1.1e-7 | -0.00085 |
| henonheiles-lf-fp64 | 0-2 | 8.03e-6 to 8.04e-6 | 1.07e-5 | 0.750002 +- 3.6e-7 | +2.0e-6 |
| | 3 | 8.05280e-6 | 1.07370e-5 | 0.7500019 +- 3.6e-7 | +1.95e-6 |
| | max | 8.05280e-6 | 1.07370e-5 | 0.7500019 +- 3.6e-7 | +1.95e-6 |
| henonheiles-lf-fp256 | max | 8.05280e-6 | 1.07370e-5 | 0.7500019 +- 3.6e-7 | +1.95e-6 |
| example | 0, 1, max | 6.10978e-6 (max) | 8.14636e-6 | 0.7500016 +- 3.6e-7 | +1.6e-6 |

**Against the total error** max |F0 - R_K|, the ratios agree with E/M to
6 digits in every case (RUN, the `E/total` column). At h = 0.01
rounding is far below the method error: W/E is at most 2.1e-10
(Lorenz-63), 1.9e-7 (Lorenz-96) and 1.6e-10 (Henon-Heiles). Lorenz-96's
shows in the 7th digit.

**fp64 and fp256 agree** to 6 digits, since the scheme and its method
error are the same. They agree to 7 digits except on Lorenz-96, where
fp64's rounding moves the 7th.
- Lorenz-63's starts 1 + i/64 are dyadic, so the two formats start
  identically.
- Their h differ by 2e-19, which moves nothing at 7 digits.

**At the earlier boundaries** (RUN, the `b` column):

| case | t = 1 | t = 2 | t = 3 | t = 4 |
|---|---|---|---|---|
| lorenz63, max | 0.9909093 | 0.9784676 | 0.9525064 | |
| lorenz96, max (t = 0.2, 0.4) | 0.9345577 | 0.9366503 | | |
| henonheiles, max | 0.750003 | 0.7500016 | 0.7500055 | 0.7500019 |

### 2.1 How near Richardson, and why not nearer

**The argument.** Richardson's argument is asymptotic. If the error at
step h is C h^p, a FIXED vector times h^p, then E = e(h) - e(h/2) =
(1 - 2^-p) e(h). The measurements show where that holds.

**Henon-Heiles meets it to 2e-6.** Stormer-Verlet is symmetric, so its
global error has only even powers: h^2, h^4, and so on. The next term
is h^2 smaller than the first. So the ratio of successive level
differences is 4.00004, then 4.00001, then 4.0000 at every level after
(RUN, the level table), the effective order is 2.0, and the ratio is 3/4 to
the next term. The deviation, +1.6e-6 to +5.5e-6 across the boundaries,
is measured: it is larger than the 3.6e-7 uncertainty.

**Lorenz-96 meets it to 0.0009.** Its start is the equilibrium x_i = F
with one member displaced by (i+1)/1024, so over 0.4 time units it moves
slowly.
- The first level ratio is 15.78, and they climb to 15.99. The
  effective order at h is 3.98, and 1 - 2^-3.98 = 0.9366 is the
  measured ratio.
- The deficit roughly halves with each halving of h, as the next term,
  in h^5, predicts. In exact arithmetic it is -0.00085, -0.00035, -0.00015 and
  -0.00007 at j = 0..3 (section 5).

**Lorenz-63 misses it by 0.015 at the certified horizon.** At h = 0.01
the error is still pre-asymptotic, and the level table measures it: the
successive ratios are 21.15, 19.06, 17.71, 16.90 and 16.47, not 16.
- **Size.** Halving h cuts the error by 21, not 16: an effective order
  of 4.40 at t = 3. RK4's next term, in h^5, is not small against the
  h^4 term at this h.
  - BELIEVED, from a two-term model e(h) = C h^4 (1 + a h) fitted to
    the ratio 21: a h is about 0.9 at h = 0.01.
  - The step-halving ratio is still within 0.015 of 15/16, because
    e(h/2)/e(h) enters E/M = 1 - e(h/2)/e(h) as 1/21 in place of 1/16.
- **Direction.** At t = 1 the effective order is 5.24, yet the ratio is
  0.991, not 1 - 2^-5.24 = 0.973. There, e(h/2) does not point where
  e(h) points, so |e(h) - e(h/2)| is nearly |e(h)|. At t = 2 and 3,
  1 - 2^-p_eff (0.9786 and 0.9525) matches the ratio to 2e-4 and 1e-5.
- **As h shrinks.** The excess over 15/16 in exact arithmetic is 0.0150,
  0.0101, 0.0061, 0.0034, 0.0018, 0.0009 and 0.0005 at j = 0..6. It
  falls by 0.67, then 0.60, 0.56, 0.53, 0.52 and 0.52 a level: towards
  halving, the signature of a first correction in h^5 (section 5).

**In a sentence.** The step-halving estimate on RK4 at h = 0.01 is
within 1.5 points of 15/16 of the method error on these programs. Its
sign relative to 15/16 is not fixed: above on Lorenz-63, below on
Lorenz-96.

## 3. Wider, scored

At the certified horizon: W, rho = max |F0 - R_0|, and the wider run's
own rounding max |F2 - R_0|, which bounds |W - rho| by the triangle
inequality (RUN):

| case | lane | W | W/rho - 1 | max abs(F2 - R_0) |
|---|---|---|---|---|
| lorenz63-rk4-fp64 | 0 | 1.75873e-15 | -9.5e-18 | 1.7e-32 |
| | 1 | 8.98220e-15 | -8.4e-19 | 1.7e-32 |
| | 2 | 2.60033e-14 | -5.3e-19 | 1.4e-32 |
| lorenz96-rk4-fp64 | 0 | 1.56272e-14 | +8.6e-19 | 2.2e-32 |
| | 1 | 3.00529e-14 | +2.9e-19 | 2.4e-32 |
| henonheiles-lf-fp64 | 0 | 1.30932e-15 | -1.0e-19 | 3.3e-34 |
| | 1 | 6.90971e-16 | -3.4e-21 | 6.2e-34 |
| | 2 | 4.32851e-16 | +1.0e-18 | 9.7e-34 |
| | 3 | 4.12454e-16 | +6.1e-19 | 2.5e-34 |

**What this shows.** The wider estimate is the main run's rounding error
to 17 digits or better, lane by lane. The same holds at every level of
the sweep: W/rho - 1 is at most 3.4e-18 down to h/1024 (section 5).
That is because the fp128 run is the same scheme on the same constants,
with rounding 2^60 times smaller.

**A consequence.** At fp64, the wider estimate is as good as an estimate
of rounding can be. What it leaves out is section 4.

## 4. The time shift: an error neither estimate sees

The shift is max |y((1 + delta) t) - y(t)|, from odefun at 40 digits
(RUN):

| case | lane | t = 1 | t = 2 | t = 3 | shift / rho at t = 3 |
|---|---|---|---|---|---|
| lorenz63-rk4-fp64 | 0 | 9.165e-16 | 1.566e-15 | 3.5146e-15 | 2.00 |
| | 1 | 9.159e-16 | 1.562e-15 | 3.5182e-15 | 0.392 |
| | 2 | 9.152e-16 | 1.559e-15 | 3.5216e-15 | 0.135 |

- **lorenz96-rk4-fp64:** 1.1e-18 and 2.2e-18 at t = 0.4, which is 7e-5
  of each lane's rounding.
- **Every fp256 case, and Henon-Heiles:** 0.

**Where it comes from.** The shift is a displacement along the flow, of
about delta t f(y(t)). That is why it barely differs between lanes whose
arithmetic rounding differs fifteenfold, and why it grows with t
(BELIEVED; the table agrees).

**What it means.**
- At fp64, on RK4 programs whose bank carries a rounded h/6, the
  certified state carries an error that no version-1 entry estimates:
  3.5e-15 on Lorenz-63 and 2e-18 on Lorenz-96 here. It is:
  - comparable to the arithmetic's own rounding on Lorenz-63: twice it
    on lane 0;
  - negligible beside the method error at h = 0.01 (3e-11 of it);
  - not negligible where rounding is what is being read.
- Its size is computable from the bank and the final state (delta t
  |f(y(t))|). Neither estimate computes it, since each carries the same
  rounded h/6.
- At fp256 it is 0 for these banks, by a property of the rounded h: 6 H6
  = H exactly. BELIEVED: another h need not have that property.

## 5. As h shrinks

Lane 0, a certified run at every level. E, M and the total error are as
in section 2, at level j. rho = max |F_j - R_j|. The last column is the
step-halving ratio in exact arithmetic, |R_j - R_(j+1)| / M (RUN,
sweep.out.txt).

**Lorenz-63, fp64.**

| j | h | E/M | E / total | rho | exact |
|---|---|---|---|---|---|
| 0 | H | 0.952506 | 0.952506 | 1.8e-15 | 0.952506 |
| 2 | H/4 | 0.943584 | 0.943585 | 2.3e-14 | 0.943584 |
| 4 | H/16 | 0.939168 | 0.9393 | 1.5e-13 | 0.93929 |
| 5 | H/32 | 0.937497 | 0.937777 | 4.0e-14 | 0.938423 |
| 6 | H/64 | 0.950116 | 0.940533 | 1.3e-13 | 0.937982 |
| 7 | H/128 | 1.81385 | 1.83643 | 1.3e-14 | 0.937965 |
| 8 | H/256 | 38.99 | 2.704 | 2.2e-13 | 0.93763 |
| 9 | H/512 | 274.2 | 0.696 | 3.8e-13 | 0.93767 |

**Lorenz-96, fp64.**

| j | E/M | E / total | rho | exact |
|---|---|---|---|---|
| 0 | 0.936652 | 0.936652 | 1.6e-14 | 0.936652 |
| 3 | 0.937671 | 0.937031 | 6.2e-14 | 0.937429 |
| 4 | 0.884329 | 0.878141 | 1.3e-13 | 0.93748 |
| 5 | 3.2137 | 1.20015 | 1.9e-13 | 0.93771 |
| 6 | 65.73 | 0.956 | 3.5e-13 | 0.93749 |
| 7 | 2768.6 | 1.287 | 6.8e-13 | 0.93750 |

**Henon-Heiles, fp64.**
- E/M runs 0.750002, 0.750001, 0.750003 ... 0.750183 through j = 5.
  Scored by R_11, whose 2u is 0.05% at j = 5.
- From j = 6, scored by odefun: 0.750002, 0.749999, 0.749978, 0.749733
  and 0.750685 at j = 10.
- The exact ratio from j = 6 on is 0.75 within its uncertainty: 1e-13 at
  j = 6, and 2.6e-11 at j = 10.
- rho grows from 1.3e-15 to 5.7e-14.
- The method error falls from 1.1e-5 to 1.0e-11. So at h/1024 rounding
  is still 1/180 of it.

**Lorenz-63, fp256** (j = 0..4): 0.952506, 0.947615, 0.943584, 0.940882
and 0.939303. rho is at most 2.8e-69, so these are the exact-arithmetic
values.

**Wider at every level:** W/rho - 1 is at most 3.4e-18 in all three
fp64 sweeps.

**What the sweep shows.**
- **In exact arithmetic** the step-halving ratio goes to 1 - 2^-p as h
  shrinks: Lorenz-63's excess and Lorenz-96's deficit both roughly halve
  at each level. It is a pre-asymptotic effect, below 0.001 by h/32. At fp256 the
  certified runs follow the exact-arithmetic ratio at every level
  measured.
- **At fp64, rounding takes over** where it meets the method error:
  - j = 6-7 for Lorenz-63;
  - j = 4-5 for Lorenz-96;
  - not by j = 10 for Stormer-Verlet. BELIEVED: near j = 13, from the
    measured growth of the two.
  Past the crossover E/M means nothing (274, 2,769): the estimate is
  measuring the two runs' rounding. It still sits within a factor of 3
  of the TOTAL error, in either direction (0.70 to 2.70).
- **The half-step run's rounding is in E, and no entry estimates it.**
  At Lorenz-63 j = 7, the main run's rounding happens to be small: W =
  1.3e-14, so W/E is 0.028. But the half-step run's rounding is 2.2e-13,
  17 times the main run's, and E is 1.8 times the method error. So near
  the crossover a small W/E does not make E a method error.

## 6. What the scores mean for a reader of a certificate

For the three programs here, at the certified h:

1. **A step-halving estimate E is 93% to 99% of the method error**
   (0.75 of it for Stormer-Verlet), when rounding is far below it:
   - here W/E is 2e-7 or less, and at fp256 there is no rounding to
     speak of;
   - the method error is then E x 1.050 (Lorenz-63, T = 3), E x 1.068
     (Lorenz-96) or E x 1.33333 (Henon-Heiles);
   - Richardson's correction E x 2^p/(2^p - 1) recovers it to 1.6%
     (Lorenz-63), 0.09% (Lorenz-96) or 3e-6 (Henon-Heiles);
   - E itself UNDER-states the method error: by 0.9% to 6.5% for RK4
     here, and by 25% for Stormer-Verlet.
2. **A wider estimate W is the rounding error of the certified
   arithmetic,** to 17 digits here. W and E together say which kind of
   error dominates.
3. **Where W is not far below E, E is not a method error.**
   - Past the crossover it measures rounding.
   - Near it, E carries the half-step run's rounding too, which can
     exceed W many times over. Lorenz-63 j = 7 is the measured example:
     W/E = 0.028 and E = 1.8 M.
   - What E still indicates there is the size of the total error, within
     a factor of 3 on these runs.
4. **The rounding of the bank's derived constants is outside both
   estimates.** For RK4 with h/6 rounded at fp64 it is 3.5e-15 on
   Lorenz-63 here, and 2e-18 on Lorenz-96. A
   reader who sums "method error about E" and "rounding about W" into a
   total is short by that much, which on Lorenz-63 lane 0 is twice W.
5. **fp256 has no wider estimate, and needs none at these h.** The
   step-halving estimate is the whole story there, because rounding is
   of order 1e-69: at most 2.8e-69 in the fp256 sweep.

## 7. What the scores do not show

- **A bound.** Every ratio is measured on these states, at these
  horizons, at these h. The page's own words stand: an estimate
  indicates, and a version-1 certificate never says "method error <= X".
- **Another program.** There is one program per system:
  - one RK4 scheme, as gen_odes.py writes it for both Lorenz systems,
    and one Stormer-Verlet;
  - one bank layout, 0.01 as h, and one rounding of h/6.
  Another scheme, order, constant set or rounding of h would have its
  own ratios and its own shift. Where delta = 0 (fp256 here), the shift
  is absent by luck, not by design.
- **A population.** The lanes are 3, 2 and 4 near-copies of one start:
  displaced by 1/64, (i+1)/1024 and 1/1024. Their spread (0.95215 to
  0.95251 on Lorenz-63) is not a sample of anything wider.
- **Long horizons of a chaotic system.** The certified horizons are
  short: 3, 0.4, 4 and 2 time units.
  - On Lorenz-63 the ratio already moves with the horizon: 0.991, 0.978
    and 0.953 at t = 1, 2 and 3.
  - Its error constant grows like e^(lambda t). BELIEVED: lambda is
    about 0.9 for these parameters, from the literature. So the K a
    reference needs grows linearly with T.
  - Once the method error at h reaches the attractor's size, E and M
    both saturate and their ratio says nothing.
  - "Converged" here means converged at the certified horizon. It says
    nothing about a horizon the reference was not run to.
  - It is also y for the bank's rounded parameters, not the Lorenz
    system with beta = 8/3: the difference is a model's, not a method's.
- **Stormer-Verlet's crossover.** It was not reached cheaply.
- **The card.** Nothing here ran on the card. The certified states are
  the corpus's, which the software backend and the golden writer agree
  on byte for byte (certificates/corpus.py's check).
- **The reference's independence.** R_k is check.py's mirror: the
  program's own scheme, by construction (check.py's identity arm). Two
  things stand apart from it:
  - check.py's textbook arm holds that scheme to the textbook's over two
    steps;
  - odefun holds its limit to the ODE's solution over every horizon
    here.

## 8. Found along the way

- **fp256's rounded 0.01 has a significand divisible by 3.** So h/6 is
  exact in the fp256 banks, and delta is 0. RUN.
- **check.py's independence census counts its own module-level names**,
  so any function added to check.py moves one line of its output. That
  line is the census's count, not a result: 150 to 153 in e8cea9b.
- **Windows Python writes CRLF** when its output is redirected.
  `.gitattributes` normalizes the committed text, and
  `programs/estimates.py` now writes LF itself, so a re-run diffs
  against the committed run line for line.

## 9. Reproduction

From the repository root. The sweep needs cft-segrun, and both need
mpmath:

    python programs/estimates.py certified > docs/studies/acc-a/certified.out.txt
    python programs/estimates.py sweep --tool host/cft-segrun > docs/studies/acc-a/sweep.out.txt
    python programs/estimates.py all --tool host/cft-segrun

**Time.** 355 s for `certified` and 206 s for `sweep`, run one at a time
and niced, on a desktop in use: 3% busy with other work when the first
began, and not measured again before the second. That is about 9
minutes for `all`.
- Henon-Heiles' K = 11 is 270 s of the first.
- `--cases A,B` limits either mode to named corpus cases.
- `--tau` sets the tolerance.
- The script exits 0 only if every check passed and every case
  converged.

**The environment.** Run on 2026-09-30 at the tree of e8cea9b plus the
script (744c094): Python 3.12.9, mpmath 1.3.0 on gmpy2 2.2.1, Windows 11,
and cft-segrun built from the same tree with MSYS2's mingw64 gcc.

**Checking a re-run.** Each captured run is the whole output, and only
`time` lines differ between runs. A re-run of lorenz96-rk4-fp64 alone
(`--cases`) reproduced its section of certified.out.txt exactly, apart
from those lines. `--against FILE` makes that comparison itself. It
holds every section a run prints to the committed section with the same
first line, and names the first line that differs.

**Two runner stages hold it** (the lead's decision, 2026-09-30):
- `estimates`, in the gate budget: `certified --cases
  lorenz63-rk4-fp64,lorenz96-rk4-fp64` against certified.out.txt, 47 s;
- `estimates-full`, in the full census only: `all` against both runs.
Both are in docs/VERIFICATION.md.
