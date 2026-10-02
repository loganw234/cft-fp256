# programs/workloads/ - programs written elsewhere, kept as delivered

## The hard workloads, `cft-hard-workloads/`

**These programs were written by an OpenAI model that was given only the
language brief and some example files, as a test of the language's
portability.** That is why they exist, and why, on close inspection, they
read differently from the rest of this tree. They keep their own
conventions (snake_case names, a `catalog.json`, inputs as exact rationals
in JSON, a compact Python style), their own independent oracle and runner,
and their own documents. Logan, on 2026-10-02, verbatim:

> "The workloads can be tracked in the repo, make a note where they are
> held that they were written by an OpenAI model who was only given the
> language brief and some example files as a test of the language
> portability. I think thats the cleanest way to state why they exist and
> why they could be 'different' from the rest on close inspection"

### What the model was given

On 2026-10-01 Logan gave another model (GPT-6.1 Sol Max) these, and
nothing more:

- the language document, docs/LANGUAGE.md as it was at 80abee5. The pack
  carries it unchanged as
  [its LANGUAGE.md](cft-hard-workloads/LANGUAGE.md): git blob 29c1b66,
  whose SHA-256 is the catalog's `language_spec_sha256`;
- the six reference sources, the `.cftl` files of programs/systems/ at
  80abee5: Lorenz-63 and Lorenz-96 under rk4 and Henon-Heiles under
  Stormer-Verlet, each at fp64 and fp256;
- one compiled bundle, lorenz63-rk4-fp64's.

It had no compiler and no golden model where it worked; the pack's own
[VALIDATION.md](cft-hard-workloads/VALIDATION.md) says so.

### What it wrote

Twenty-one programs ([its PROGRAMS.md](cft-hard-workloads/PROGRAMS.md),
the equations in [its MODELS.md](cft-hard-workloads/MODELS.md)):

- seven families: Gray-Scott, a two-scale Lorenz-96 with tangent vectors
  written out as state, an FPUT chain, a phi⁴ double-well lattice,
  Kuramoto-Sivashinsky, a dense recurrent reservoir map and a matrix
  Riccati flow;
- each "hard" at fp64, "extended" (a larger geometry) at fp64, and "wide"
  (the hard geometry) at fp256;
- three lanes of exact rational initial conditions each, in `inputs/`;
- a one-step vector each, in `reference/`: the states and FLAGS after one
  step from those lanes, made by an evaluator of its own - a parser of the
  subset of the language it writes, rounding with integers and Fractions,
  importing nothing of this repository's (`tools/subset_oracle.py`,
  `tools/exact_oracle.py`);
- its own runner, `tools/run_workloads.py`, which compiles with
  python/cftc and holds the compiled image on seq.py and the golden
  interpreter to those vectors and to each other, and its own NumPy model
  checks and fault-injection tests of that runner (`evidence/`).

[Its README](cft-hard-workloads/README.md) says how to run it.

### What they showed

Measured on amd-arc-box against main at 80abee5, 2026-10-01 and 02. The
figures and the tables are docs/VALIDATION.md's, in the entry "the
language round, part two" (2026-10-02), under "The hard workloads on the
card"; the run records are in Data/runs/2026-10-01-hard-workloads/, which
is outside the tree.

- **All 21 compile**, on the pack's own runner. It verified 20 against its
  vectors by 05:34 on 2026-10-02, none failing; the last, Lorenz-tangent
  extended, had passed every segment and was building its 8-step image.
- **Ten fit the card** (`u50-rev7-quad`): FPUT, phi⁴, Kuramoto-Sivashinsky,
  the reservoir and Riccati, each hard and wide. Gray-Scott is past the
  tile's 32,768 instructions, Lorenz-tangent past those and its 2,048
  scratch slots a lane, and every extended one past one or the other: the
  compiler does not split a program across tiles.
- **Those ten are bit for bit** with libcft's software backend on
  revision 7's quad, on every lane.
- **The speeds:** 98,000 to 433,000 fp64 lane-steps a second (1.2 to 1.6
  G operations a second) and 25,000 to 110,000 at fp256 (310 to 415 M),
  about 23 to 25 times the box's whole idle 18-core Xeon at fp64 and 9 to
  10 times at fp256 (FPUT 10 and 3.2 times). The card is 2 to 6% slower
  than the compiler's cost model on every program.

### The one change

`tools/run_workloads.py` asked for python/cftc to be a file,
`(Path(args.repo)/"python"/"cftc").is_file()`, and cftc is a package
directory, which `python <checkout>/python/cftc` runs exactly as the
pack's own README invokes it. So it refused every checkout ("checkout has
no python/cftc") before doing anything. The check now asks that the path
exist, `.exists()`, in that one line; it is the change the pack ran with
on the box, and the commit after the pack's own in this tree's history.

So the pack's own SHA256SUMS fails for that one file, its SHA-256 now
f5ad6a73... where the list records 947dc42e..., and holds for the other
85:

    cd programs/workloads/cft-hard-workloads && sha256sum -c SHA256SUMS

### Kept as delivered

Every other file is byte for byte what the model delivered (the zip's
SHA-256 is 0761b7eb...d485), its SHA256SUMS included, so that list stays
the other model's record of what it sent. Nothing in the pack is restyled,
corrected or brought to this tree's conventions. A file it would have
written differently is its business; a defect it finds in this tree is
ours. The docs check (`python/check_docs_index.py`) exempts the pack's
five documents from its link and quoted-path checks, by name, for exactly
as long as each is the bytes the pack's SHA256SUMS records for it.

About 11 MB, which Logan accepted.
