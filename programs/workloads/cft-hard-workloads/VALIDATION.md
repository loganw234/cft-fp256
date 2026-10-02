# What was checked

No cftc or cft_golden checkout is available in this workspace. The programs
have not been compiled here, and no physical device was run.

The following independent checks were completed:

* All 21 generated sources regenerate byte for byte, use ASCII/LF, stay
  below the specified source nesting limit, define every state equation,
  use every generated let/parameter, and have conservative bank estimates
  below 512. Larger lane layouts stay below 32,768 values.
* A small separate parser checks precisely the CFT subset emitted by this
  generator. It builds every runtime operation without algebraic folding
  or FMA contraction. It is not a substitute for the actual CFT checker.
* Equations in all three lanes of every source agree with separately written
  vectorized NumPy equations: 63 checks, including correct 2D wrap, matrix
  multiplication, and all tangent equations.
* Integer/Fraction arithmetic produces exact one-step state bits and FLAGS
  for all 21 programs and all three lanes. No host float enters these
  expectations. Constants meet runtime arithmetic after one rounding.
* Normal rounding interval and sign-symmetry checks cover 300 samples in
  each of fp32, fp64, fp128 and fp256. The fp32/fp64 samples also match
  host encodings. The runtime checks the actual checker's encoding of 1 to
  verify exponent/fraction layout before using any format's vectors.
* Centered differences independently check all four main Lorenz tangent
  columns against the primal field's directional derivative.
* Numerical energy gradients check both Hamiltonian force fields.
  Short energy and endpoint probes show second-order Stormer-Verlet
  behavior; RK4 endpoint probes show approximately fourth-order behavior.
* All seven main models were simulated independently for their long profile,
  using the perturbed second lane. They stayed finite and developed
  nontrivial dynamics or a dense steady covariance.
* Synthetic backends confirm that the runtime harness rejects altered
  one-step bits, altered FLAGS, a bad multi-step segment, a bad monolithic
  image result, and a bad halved-step result. A small tangent fixture checks
  exact external rescaling, signed zero preservation and growth-rate
  checkpoints. These are harness tests, not CFT execution.

Machine-readable evidence:

* [Model validation](evidence/model-validation.json)
* [Exact-vector construction and operation counts](evidence/reference-build.json)
* [Runner fault-injection checks](evidence/runner-validation.json)

## Independent calibration results

These numbers are from NumPy doubles, using the stated mathematical
discretizations. They establish reasonable workloads and diagnostics; they
are not expected compiler bits or acceptance results.

| Model | Steps | Observed result |
|---|---:|---|
| Gray-Scott | 4,096 | Nonuniform V; final spatial standard deviation about 0.117 |
| Lorenz with tangent vectors | 8,192 | Finite primal and rescaled tangent evolution |
| FPUT | 8,192 | Relative energy drift about 1.14e-5; momentum change about 8.9e-16 |
| Double-well lattice | 8,192 | Relative energy drift about 7.17e-6 |
| Kuramoto-Sivashinsky | 8,192 | Final RMS about 1.31; mean change about -2.8e-16 |
| Recurrent reservoir | 16,384 | State spans nearly [-1,1]; spatial standard deviation about 0.597 |
| Riccati | 1,024 | Positive symmetric covariance; minimum symmetric eigenvalue about 1.562 |

The FPUT and double-well short energy-error ratios at h versus h/2 are
approximately 4.001. The RK4 short endpoint ratios range from about 15.9
to 19.4. Momentum reversal returns the independent double states within
roughly 1.2e-15 in the short lattice checks.

The actual harness reports such quantities as measurements and preserves
the underlying bit encodings. It checks compiler correctness against the
integer oracle/interpreter, not against these rounded calibration numbers.

## Important distinctions in returned results

* COMPILED means CLI exports were produced; it does not mean image execution
  was checked.
* PASS on the one-step gate means agreement with an independent finite
  IEEE arithmetic evaluator.
* Exact differential segments mean the compiled seq.py image and golden
  interpreter agreed on every state encoding and aggregate FLAGS.
* Later long-run segments without --compare-all execute only the compiled
  image. The logs mark this explicitly.
* TARGET-LIMIT records a published selected-target capacity refusal;
  it does not score that source as successfully executed.
* MEASURED marks scientific step-halving/reversal results. These do not
  decide compiler correctness.
* No wide-format vector or long run is described as measured hardware
  behavior. Physical serialized-image/card checks remain separate work.
