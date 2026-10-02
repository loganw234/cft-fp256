# CFT hard numerical workloads

This pack contains 21 substantial, fully specified programs: seven main
fp64 workloads, seven larger fp64 workloads, and the seven main geometries
again at fp256. Each has three lanes of exact rational initial conditions.
The programs use coupled equations, dense algebra, or nonlinear spatial
dynamics. They are intended to be accepted as ordinary CFT programs.

Start with [PROGRAMS.md](PROGRAMS.md) for the source files and
[MODELS.md](MODELS.md) for the equations. [VALIDATION.md](VALIDATION.md)
explains the evidence included in this pack.
The supplied [language definition](LANGUAGE.md) is included unchanged.

| Family | Main state values/lane | Larger state values/lane | Main arithmetic operations/step/lane |
|---|---:|---:|---:|
| Gray-Scott, 16x16 and 32x32 | 512 | 2,048 | 22,024 |
| Two-scale Lorenz-96 and tangent vectors | 1,080 | 5,712 | 35,980 |
| FPUT chain, 512 and 2,048 particles | 1,024 | 4,096 | 4,608 |
| Double-well lattice, 16x16 and 32x32 | 512 | 2,048 | 3,072 |
| Kuramoto-Sivashinsky, 256 and 1,024 sites | 256 | 1,024 | 15,104 |
| Dense two-layer recurrent reservoir | 106 | 202 | 14,614 |
| Matrix Riccati flow, 12x12 and 32x32 | 144 | 1,024 | 12,532 |

Counts come from an independent source evaluator, including the expanded
step. Compiler sharing can reduce arithmetic; scheduling adds loads/stores.
The larger Lorenz case has approximately 193,972 arithmetic operations per
step, and the larger Riccati case 179,204.

## Run first

Use the same Python environment that ran your previous CFT tests.
The checkout must provide python/cftc and python/cft_golden. These commands
are issued from this unpacked directory.

On PowerShell:

~~~powershell
$env:CFT_REPO = 'C:\path\to\cft-checkout'
python tools/run_workloads.py --only lorenz_tangent_hard_fp64 --profile verify
~~~

On bash:

~~~bash
export CFT_REPO=/path/to/cft-checkout
python tools/run_workloads.py --only lorenz_tangent_hard_fp64 --profile verify
~~~

The default target is sw:32768, the largest software scratch target described
in your returned results. Specify --target u50:rev7 to measure that target's
actual capacity limits. A TARGET-LIMIT is logged distinctly from a failure.
The plain sw target has only 256 scratch slots and is too small for many
of these programs.

Then run the seven main cases:

~~~bash
python tools/run_workloads.py --profile verify --step-halving --reversal --compare-all
~~~

Verification performs CLI compilation, keeps all emitted artifacts, checks
canonical readback, compares both backends to the independent one-step
vectors, compares both backends at 1, 2, 4 and 8 steps, and checks that a
single eight-step image agrees with the segmented run. The optional probes
measure short step-halving differences and momentum reversal.

Both adapters were based on the working interfaces in your returned archive.
The compiled adapter uses cftc.compile_graph and executes the live image on
seq.py. It keeps at most two compiled segment lengths cached per source.
It does not reload the CLI's .cftp from disk and does not execute a physical
card. CLI exports remain in the results for independent artifact review.

## Run substantial trajectories

~~~bash
python tools/run_workloads.py --profile long --step-halving --reversal
python tools/run_workloads.py --profile long --only gray_scott_hard_fp64 --compare-all
python tools/run_workloads.py --tier wide --profile verify
python tools/run_workloads.py --tier extended --profile verify
~~~

The long profile runs 1,024 to 16,384 steps depending on the system.
The endurance profile runs 65,536 steps, except Riccati at 16,384.
Use --steps N to choose an endpoint and --chunk N to change the maximum
segment length (128 by default).

Long and endurance runs always pass the independent one-step gate and the
early eight-step differential checks. Later segments execute the compiled
image alone unless --compare-all is present. Results explicitly record which
segments had a golden comparison. A PASS for such a run does not certify all
later segments against the interpreter.

These can consume substantial CPU time on Python interpreters. For example,
the larger Lorenz long run contains roughly 4.77 billion arithmetic
operations over its three lanes, before scratch accesses. Choose a specific
case before starting a full extended or fp256 long run.

Lorenz tangent vectors are rescaled by exact powers of two between long-run
segments, beginning at step 8. The scaling powers, input digests and finite
time growth rates are logged separately. This prevents the tangent columns
from overflowing while leaving the primal dynamics alone. There is no QR
orthogonalization: these runs measure growth of selected directions, not a
complete Lyapunov spectrum. Verify runs have no external rescaling.

All scientific diagnostics are measurements, rather than hard-coded compiler
pass/fail thresholds. Chaotic trajectories at h and h/2 can diverge over long
times even when both implementations are correct. A short probe provides
more useful convergence evidence.

## Compile without running the images

~~~bash
python tools/run_workloads.py --compile-only
python tools/run_workloads.py --tier all --compile-only
~~~

There is also the previous suite's command-template interface, updated for
this catalog. It does not import CFT itself. For example, on PowerShell:

~~~powershell
$argv = @('python', "$env:CFT_REPO/python/cftc", '{source}', '--steps', '{steps}', '--target', 'sw:32768', '--out', '{out}')
python tools/compile_cases.py --command-json (ConvertTo-Json -Compress -InputObject $argv) --results compiler-results.jsonl
~~~

Or bash:

~~~bash
python tools/compile_cases.py --command "python $CFT_REPO/python/cftc {source} --steps {steps} --target sw:32768 --out {out}" --results compiler-results.jsonl
~~~

Use --command-json when a path contains spaces or uses Windows backslashes.
Add --include-stress for the larger and wide cases. Add --hash-seeds 1,7,123
for deterministic compilation checks. The name stress is inherited from
the earlier harness: here it selects larger valid models, rather than
malformed source probes. Compilation defaults to a 600-second timeout,
which can be changed with --timeout.

Each source is standalone; you can also invoke your compiler directly on any
file in programs/. The input JSON states follow its declaration order.

## Return results as a ZIP

Every run creates a new directory under hard-results/ and prints its path.
It contains the environment/revision, compiler stdout and stderr, exports,
checked source/graph, input encodings, state snapshots, diagnostics, and a
line-buffered runtime-results.jsonl. Full state snapshots are retained at
powers of two and at the final step; every segment records a digest and
diagnostics.

~~~bash
python tools/collect_results.py hard-results/run-YYYYMMDD-HHMMSS-NNN
~~~

Attach the printed ZIP. For command-template compile runs, ZIP the JSONL and
its matching compiler-results-outputs-* directory together.

## Reproduce or change the workload pack

~~~bash
python tools/generate_workloads.py
python tools/build_reference.py
python tools/validate_models.py
python tools/validate_runner.py
~~~

Generation, exact reference construction and runtime execution use Python's
standard library. Only validate_models.py needs NumPy. Its simulations check
the equations and run choices with doubles; they do not produce compiler
results. The reference builder uses integers/Fractions for every rounding.
The runtime checks the actual format layout before trusting wide vectors.

If you edit an equation, parameter default, initial condition or geometry,
regenerate the matching vectors. Sources and inputs are hashed so a changed
program cannot silently use stale expectations.

No CFT compiler is installed in the workspace where this pack was made.
Actual language acceptance, lowering and image execution are awaiting your
compiler run. The included evidence is independent model validation and
runner fault-injection evidence, clearly marked as such.
