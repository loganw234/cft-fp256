# The language

A small text language for dynamical systems - ordinary differential
equations and maps - whose every rounding is fixed by the text. A
system file declares a format and a rounding attribute, its state,
constants and parameters, its equations, and an integrator from a
library of three; the step it denotes is checked into a **step graph**,
and the step graph is what a run computes, bit for bit. A system may
also ask for its **variational equations** - the derivative of its step
along tangent vectors, stepped beside the state, every rounding fixed
by rules written in the language (see "The variational equations").

This document is the language's definition. Its executable form is
`python/cft_golden/lang/`, in the golden model, which is the authority:
a parser, a checker, the exact constants, the step graph, and a
reference interpreter that is the definition of correct for every
compiled image. The compiler that turns a step graph into a tile image
is `python/cftc`, the step-3 plan's parcel L2, held to this definition
by the runner's `lang` stage (docs/VERIFICATION.md); ROADMAP.md's
"Step 3: the language and its compiler (plan of record, 2026-10-01)" is
the plan, and this document is its parcel L1.

Files are `*.cftl` (a working name). The three references are written in
it, at fp64 and fp256, in `programs/systems/`, each beside the image
`programs/gen_odes.py` wrote by hand for the same system; the reference
interpreter reproduces each image's run on seq.py bit for bit, FLAGS
included (`python/tests/test_lang_refs.py`).

## A system, by example

`programs/systems/lorenz63-rk4-fp64.cftl`:

```
system lorenz63
format fp64
round  rne
state  x, y, z
param  sigma = 10, rho = 28, beta = 8/3
d/dt x = sigma * (y - x)
d/dt y = fma(x, rho - z, -y)
d/dt z = fma(x, y, -(beta * z))
step   rk4, h = 1/100
```

`programs/systems/lorenz96-rk4-fp64.cftl`:

```
system lorenz96
format fp64
round  rne
state  x[40] cyclic
param  F = 8
d/dt x[i] = fma(x[i+1] - x[i-2], x[i-1], F - x[i])
step   rk4, h = 1/100
```

`programs/systems/henonheiles-lf-fp64.cftl`:

```
system henonheiles
format fp64
round  rne
state  x, y, px, py
d/dt x  = px
d/dt y  = py
d/dt px = -(x * fma(2, y, 1))
d/dt py = fma(y, y - 1, -(x * x))
step   stormer-verlet, h = 1/100, q = (x, y), p = (px, py)
```

Each fp256 file differs from its fp64 one in the `format` line only, and
the gate holds that.

## The text

- One statement a line. `;` starts a comment that runs to the end of
  the line, as in `.cfta`. A newline inside `( )` or `[ ]` continues
  the statement.
- **The characters** follow `.cfta`'s rule (`docs/PROGRAMS.md`, "The
  text form's characters"), and `python/cft_golden/lang/syntax.py`
  holds it in `asm.py`'s words, so that no reader (the parser, cft-asm,
  an LF-only tool, `str.splitlines()`) sees a line another does not:
  - a source is UTF-8;
  - a line ends at LF, and a CR immediately before the LF is part of
    that end, so a CRLF file reads as its LF twin;
  - every other line boundary `str.splitlines()` knows (a CR that ends
    no line, VT, FF, 0x1c to 0x1e, NEL, U+2028, U+2029), and NUL and
    Ctrl-Z, are refused anywhere, comments included, naming the
    character and its line (`character`);
  - outside a comment a line holds only printable ASCII, spaces and
    tabs, and a comment may hold any other character. A byte-order
    mark is no exception: at the start of a file it is a character
    outside a comment, and refused.

  The whole source is held to the rule before a line of it is parsed,
  UTF-8 first, so of several faults the first is named. A caller with a
  file passes its bytes (`lang.load` does): a text-mode read would turn
  a lone CR into a line end before the rule could refuse it. Until
  2026-10-01 a lone CR ended a line here and in no LF-only reader, so
  `; rounding: the default`, a CR and `round rdn` compiled as rdn while
  grep showed one comment; a form feed or U+2028 in a comment hid a line
  from the parser that `splitlines()` showed; and `lang.load` dropped a
  byte-order mark (verifier-VL1).
- Parentheses and brackets nest at most 100 deep (`too-deep`).
- **Chains may be any length, with the same verdict on every machine and
  every Python.** A chain such as `a + b + c`, an index such as
  `x[i + 1 + 1 ...]`, a run of minuses, and a chain of lets, labels or
  consts, each reading the next, have no bound:
  - the checker and the renderers walk chains and runs in loops;
  - the checker evaluates a definition where it is first read, and one
    read with Python's stack already a fixed budget deep is set aside,
    evaluated first from the top with the path that led to it kept, and
    the expression that read it evaluated again. What it evaluates again
    is only a prefix it had evaluated without fault, whose effects repeat
    nothing, so the graph's operations are the recursion's, in its order,
    the first refusal is the recursion's, and a cycle is named at the same
    reference. `python/tests/test_lang_readback.py` holds it to the
    recursion run with no limit in reach, and parcel D2 measured the two
    equal on Python 3.10, 3.12 and 3.13.

  Until 2026-10-01 a chain of lets was held to Python's own recursion
  limit, so the verdict hung on the Python version and on the caller's
  stack: a chain of 150 lets through a call was accepted on Python 3.12
  and refused on 3.10, a 230-let map accepted from the command line and
  refused 100 frames down, and rk4 with 81 to 246 lets accepted while
  its canonical form, whose expansion block chains the stages through
  labels, did not read back (verifier-VD2). What is left to recurse is
  nesting, which the 100 bounds: only a caller whose own stack is
  already hundreds of frames deep can meet Python's recursion limit,
  which the package keeps rather than raises, and the refusal there is
  `too-deep` too.
- **The canonical form is held to the same 100**, so that, with chains of
  any length, it always reads back ("The intention-out"). It writes its
  own parentheses - around every operation nested in another but a left
  operand of its kind, around a compound constant used as an operand,
  `x * (1/3)`, and around a negation used as an operand of a binary
  operation, `(-a) * b` - and writes out what the source need not: the
  expansion block, the tangent's lines. So it can nest deeper than its
  source: for example, `-(-(x) * y) * y` is written `(-((-x) * y)) * y`,
  two levels a level, and the tangent of an unnamed product of n terms
  nests n - 1 deep from a source 0 deep. A source whose canonical form
  would nest past 100 is refused `too-deep` at the line of the equation
  or let whose line would be too deep - primal or tangent, a written
  tangent equation or tangent let at its own line - and the sentence
  names that line and its depth. The depth is the canonical form's own,
  measured as the parser counts nesting:
  `python/cft_golden/lang/nesting.py` follows the renderer's rules
  without writing the text, and `python/tests/test_lang_readback.py`
  holds it to the lexer's own count of the renderer's text, line by
  line, so nothing is refused whose canonical form reads back. Lets
  bound the depth: the canonical form writes a let by its name. Until
  2026-10-01 such a source was accepted, and the compiler stopped at its
  own check of the canonical form, exit 70, "a defect in the compiler"
  (verifier-VL3; parcel D2).
- A name is a letter or `_` followed by letters, digits and `_`, and
  names are case-sensitive: `Y` and `y` are two names.
- A dotted name such as `k1.x` or `Y2.x[3]` is a **label**: it names a
  node of an expanded step, and is defined only inside an `expansion`
  block (see "The step"). A dotted name whose first part is a tangent
  vector, such as `v.x` or `v.k1.x`, names a tangent's component, let or
  label (see "The variational equations").
- Keywords: `system format round state cyclic tangent const param lane
  let next step for in expansion end`, and `d/dt`, which is one token
  where a statement starts.
- Reserved: no value may be named after one of these, and the check is
  `reserved-name`.
  - the keywords;
  - the built-ins `fma abs min max minnum maxnum copysign select`;
  - `sqrt` and the transcendental names (`exp`, `log`, `sin`, `pow`,
    `hypot` and the rest of the list in `python/cft_golden/lang/check.py`);
  - `h`, the step's own name;
  - `inf infinity nan snan`.
- `tangent` became a keyword with the variational equations (part
  two, 2026-10-02). A source written before them that names a value
  `tangent` is refused now: `syntax` wherever it reads it, since the
  parser meets the read first, and `reserved-name` where it only
  declares it (verifier-VI2).
- `t` is not reserved: a source names a value `t` to carry time in its
  state ("Time").

### Statements

```
file       = { [ statement ] [ ";" comment ] NEWLINE }
statement  = "system" NAME
           | "format" ( "fp32" | "fp64" | "fp128" | "fp256" )
           | "round" ( "rne" | "rtz" | "rdn" | "rup" | "rmm" )      ; absent: rne
           | "state" svar { "," svar }
           | "tangent" NAME { "," NAME }                     ; the variational equations
           | "const" NAME "=" expr { "," NAME "=" expr }
           | "param" NAME "=" expr { "," NAME "=" expr }
           | "lane" "param" NAME [ "=" expr ] { "," NAME [ "=" expr ] }
           | "let" target "=" expr [ range ]
           | ( "d/dt" | "next" ) target "=" expr [ range ]
           | "step" integrator { "," option }
           | "expansion" NEWLINE { stepline NEWLINE } "end"
svar       = NAME [ "[" INTEGER "]" [ "cyclic" ] ]
target     = NAME [ "[" index "]" ]
range      = "for" NAME "in" index ".." index             ; inclusive at both ends
integrator = "rk4" | "euler" | "stormer-verlet" | "map"
option     = "h" "=" expr
           | ( "q" | "p" ) "=" "(" NAME { "," NAME } ")"   ; stormer-verlet only
stepline   = "let" LABEL [ "[" INTEGER "]" ] "=" expr | "next" target "=" expr
```

With tangent vectors declared, a `target` or a `LABEL` may be one of a
vector's - `d/dt v.x`, `next v.x`, `let v.r`, and in an expansion block
`let v.k1.x` and `next v.x` - which writes out the derivation the
language makes anyway, and is held to it ("The variational equations",
"Writing them out").

- Statements may come in any order, and a name may be used above its
  definition. A definition that reaches itself is `cycle`.
- A system is a **flow** (every equation `d/dt`) or a **map** (every
  equation `next`), never both (`mixed-equations`).
- Every state component has exactly one equation: `missing-equation` if
  it has none, `duplicate-equation` if it has two.

### Literals

A literal is an exact rational, and carries no sign: minus is an
operator.

- **integer:** `0`, or digits without a leading zero. `05` is refused,
  as `syntax`, because in C it is octal.
- **decimal:** IEEE 754-2019 5.12.2's syntax, exactly as `chars.lex_decimal`
  reads it: digits with an optional point, at least one digit, and an
  optional `e` exponent. `0.01`, `1e-2`, `.5` and `2.` are all decimals,
  and each is exactly D x 10^k. A decimal may lead with zeros, as
  lex_decimal reads it and as C does: `05.5` is 5.5 and `007e-3` is
  0.007. Only an integer, digits alone, may not.
- **hexadecimal significand:** 5.12.3's syntax, as `chars.lex_hex` reads
  it, with the binary exponent required: `0x1.8p+1` is 3. `0x10` with no
  `p` is refused, as `syntax`, because an encoding is not a literal.
- **a/b** is not a separate token. It is a constant division, and
  constant arithmetic is exact, so `8/3` is the rational 8/3.
- **The bound.** A literal, or a constant expression's exact value,
  beyond 2^+-1048576 is `constant-range`. It lies outside every format by
  far, and the evaluator refuses it rather than build the integer.
  - Inside that bound a constant is held exactly at any size.
  - The step graph and the canonical form write a constant of thousands
    of digits in full, reading it back the same, and Python's own
    4,300-digit limit on printing an integer is no bound here. Writing
    one out takes time linear in its size: `1e-78900` is written in
    0.2 s, where finding a decimal's powers of 2 and 5 a factor at a
    time took about a minute (verifier-VL1).
  - A refusal's sentence names a long constant by its canonical
    spelling when that is at most forty characters (`-1e5000 overflows
    binary64 under rne`), and otherwise by its value to five
    significant digits (`3.3333e+4999 (to five digits)`).

### Arrays and indices

- Arrays are one-dimensional: `state x[40]`. An array's length is written
  as a whole number (`x[4]`, not `x[4.0]`), from 1 to 32,768
  (`array-length`).
- A lane holds its state, its tangent vectors and its lane params, at
  most 32,768 values in all (`lane-capacity`). A range covers at most
  32,768 indices
  (`index-range`). No tile publishes a deeper scratch than that (seq.py's
  `SCRATCH_D_MAX`), and the bound keeps a source like `state x[1000000000]`
  from taking the machine's memory before it is refused.
- `cyclic` makes an index wrap modulo the length, so `x[-1]` is `x[39]`.
  On any other array an index outside 0..N-1 is `index-range`.
- `d/dt x[i] = ...`, where `i` is bound by nothing else, runs over the
  whole array; `... for i in 1..38` runs over that range. The range
  includes both ends.
- An index is integer arithmetic (`+ - *`, unary minus, parentheses) on
  literals and the statement's index variable. Anything else is
  `index-not-integer`, and a free name is `unbound-index`.
- An index variable used as a value is that integer, a constant.
- A let may be indexed the same way: `let d[i] = x[i+1] - x[i-2] for i
  in 0..39`. A let array has the components it defines and no others.
- An equation's arrays are unrolled into the step graph, one component
  at a time.

## Expressions and operations

Precedence, lowest first:

1. one comparison: `<`, `<=`, `>`, `>=`, `==`. `a < b < c` is
   `chained-comparison`; `!=` is `not-equal`, since there is no such
   operation (`select(a == b, 0, 1)` is one).
2. `+` and `-`, binary, associating left.
3. `*` and `/`, associating left; `/` only between constants.
4. unary `-`, which binds tighter than `*`, as in C and Python.
5. a literal, a name, `name[index]`, a label, a call, or `( expr )`.

**Unary minus and the attribute.** `-a*b` is `(-a)*b`. Under rdn and rup
that rounding differs from `-(a*b)`:
- rdn rounds the negative product down, away from zero;
- the negation of a product rounded down is the positive product rounded
  toward zero, negated.

Under rne, rtz and rmm the two agree, since those attributes are
symmetric in sign. The difference also shows in the sign of a NaN. The
canonical form therefore always prints the parentheses, `(-x) * y` or
`-(x * y)`, so the intention-out shows which was meant. The gate holds
one such pair under rdn and rup, and the same pair under the other
three.

**Literal evaluation** (754-2019 10.4). Every operator or built-in
written is one node of the step graph and one operation of the run, so
the language takes 754's clauses 4.1, 10 and 11 at their strictest:
- `a + b + c` is `(a + b) + c`, two roundings, and parentheses are kept.
- `a*b + c` is a mul and an add. Nothing is contracted.
- `fma(a, b, c)` is one rounding.
- `x + 0` is an add: under every attribute but rdn it turns -0 into +0.
- Nothing is reassociated, distributed, folded as an identity or
  widened.
- A value defined and never used is `unused`. Every operation written is
  performed, so no dead-code elimination ever has to decide whether a
  dropped operation's flags were part of the answer. h is used where a
  constant of the step scales with it ("The step's constants"): every
  flow's template has one, and a map that names its step but reads h
  only where it folds to a constant that does not scale - `h - h`,
  `h/h`, `copysign(1, h)` - is `unused` at the step line, its sentence
  naming the uses that folded, by line, each with its value - the first
  three, and how many more: `h - h at line 5 is 0`.

The compiler (L2) may commute the operands of `+` and `*`, share
identical subexpressions, schedule and allocate freely. None of these
changes a value or the run's FLAGS: verifier-P1 measured the
commutations bit for bit, NaN payloads included, and FLAGS is a sticky
OR.

### The operations

Every node of a step graph is one of these. Its name is softfloat.py's
OP_NAMES spelling, and its operands are in the golden function's order,
which is asm.py's OP_FIELDS order.

| written | node | golden function | 754-2019 | rounds | flags it can raise |
|---|---|---|---|---|---|
| `a + b` | `add(a, b)` | `sf.add` | 5.4.1 addition | once | all but divideByZero |
| `a - b` | `sub(a, b)` | `sf.sub` | 5.4.1 subtraction | once | the same |
| `a * b` | `mul(a, b)` | `sf.mul` | 5.4.1 multiplication | once | the same |
| `fma(a, b, c)` | `fma(a, b, c)`, a*b + c | `sf.fma` | 5.4.1 fusedMultiplyAdd | once | the same |
| `-a` | `neg(a)` | `sf.neg` | 5.5.1 negate | no: exact | none, not even on a signaling NaN |
| `abs(a)` | `abs(a)` | `sf.fabs` | 5.5.1 abs | no | none |
| `copysign(a, b)` | `copysign(a, b)` | `sf.copysign` | 5.5.1 copySign | no | none |
| `min(a, b)` | `min(a, b)` | `sf.fmin` | 9.6 minimum | no | invalid on a signaling NaN |
| `max(a, b)` | `max(a, b)` | `sf.fmax` | 9.6 maximum | no | the same |
| `minnum(a, b)` | `minnum(a, b)` | `sf.fminnum` | 9.6 minimumNumber | no | the same |
| `maxnum(a, b)` | `maxnum(a, b)` | `sf.fmaxnum` | 9.6 maximumNumber | no | the same |
| `a < b` | `cmplt(a, b)` | `sf.cmplt`: 1.0 or +0.0 | 5.6.1 compareQuietLess | no | the same |
| `a <= b` | `cmple(a, b)` | `sf.cmple` | 5.6.1 compareQuietLessEqual | no | the same |
| `a > b` | `cmplt(b, a)` | `sf.cmplt`, swapped | 5.6.1 compareQuietGreater (5.11: Less, swapped) | no | the same |
| `a >= b` | `cmple(b, a)` | `sf.cmple`, swapped | 5.6.1 compareQuietGreaterEqual | no | the same |
| `a == b` | `cmpeq(a, b)` | `sf.cmpeq` | 5.6.1 compareQuietEqual | no | the same |
| `select(c, a, b)` | `select(a, b, c)` | `sf.select`: a if c's magnitude is not zero, else b | none: the tile's SELECT; quiet like 5.5.1 | no | none |

- The four that round take the program's one attribute; the rest ignore
  it, as `softfloat.compute` does.
- `select` takes its arguments in C's conditional order, `c ? a : b`,
  not OpenCL's select. Both arms are operands, so both are computed:
  there is no branch.
- A comparison's value is 1.0 or +0.0, and may be used arithmetically.

### Refused in v1

| written | refusal | why |
|---|---|---|
| a division with a non-constant operand | `runtime-division` | v1 has none; `x * (1/3)` is one rounding of 1/3, then one of the product |
| `sqrt(...)` | `runtime-sqrt` at run time, `irrational-constant` on a constant | v1 has no square root; inlining divfull or sqrtfull is a later parcel |
| a transcendental | `transcendental` at run time, `irrational-constant` on a constant | the correctly rounded math library is a later step |
| `^` or `**` | `power` | write `x * x`, and a longer product in the order meant |
| `t`, declared nowhere | `time-dependence` | carry time in the state, `state t` and `d/dt t = 1`, or count steps ("Time") |
| `h` in a flow's equations | `h-scope` | a step-halving run halves h; the right-hand side must not move with it |

## Constants

**A constant is an exact rational.**
- A literal, a `const`, `h`, and any operator or built-in whose operands
  are all constants make a constant. It is evaluated exactly, as a
  Fraction, and is not an operation.
- So `x * 2 * 3` is `(x * 2) * 3`, two multiplies, while `x * (2 * 3)`
  is `x * 6`, one.
- The same holds inside the integrators' templates.

**Rounded once.** A constant is rounded ONCE, under the program's
attribute, where it meets a run-time operation or the bank:
- through `chars._round_rational`, one integer division and one
  `softfloat.round_pack`;
- never through binary64, and never twice: `h/6` is RN(1/600), not
  RN(RN(1/100)/6). No float can reach a constant at all: every constant
  path is Fractions and integers, and the code that holds a constant
  refuses a float outright (the gate sweeps abs and copysign over every
  power of h from -3 to 3, both signs of h, to hold it).

Its rounding's flags are the compiler's report, written into the
intention-out, and not the run's FLAGS.

**Zero is +0.** A constant whose exact value is zero is +0 under every
attribute. That covers `0`, `1 - 1` and `-1 * 0`, and a negated zero
the text did not write as one: `-(1 - 1)`, and `-i` where an index
variable i is 0. This is a choice: the exact rational has no sign of
zero, so the language does not invent one.

**What a rational cannot carry is refused.** In v1 a constant cannot be
any of these:
- `-0`, a minus written on a zero literal (`-0`, `-0.0`, `-(0)`,
  `- -0`, `-0x0p+0`): the writer asked for a sign the rational cannot
  keep, `constant-negative-zero`;
- `inf` or `infinity`: `constant-infinity`;
- `nan` or `snan`: `constant-nan`;
- a constant divided by a constant zero: `constant-division-by-zero`.

All of them can still arise at run time. A lane may start at -0, an
infinity or a NaN, and the operations make them.

**Rounding refusals.** A constant whose one rounding overflows is
`constant-overflow`, under every attribute, rtz included. A nonzero
constant that rounds to zero is `constant-rounds-to-zero`. A subnormal
constant is allowed and reported with its flags.

### const, param, lane param

- **`const NAME = expr`** is a name for a constant expression. Every use
  is the constant itself, folded into whatever constant expression
  contains it. A const cannot change per run: one value, one image.
- **`param NAME = expr`** is a bank slot that belongs to the run.
  - Its default is the expression's exact value rounded once. The
    expression must be constant (`not-constant`), and may not read h
    (`h-scope`).
  - Every use is a run-time leaf: `-beta` is a run-time neg of the
    bank's value.
  - A run may give another value (BANK_EXT), so one image serves every
    value.
- **`lane param NAME [= expr]`** is one value per lane, held after the
  state in the lane's scratch. It is a run-time leaf, and its optional
  default is what a run uses when it gives none.

Under rdn and rup the negation of a const is the attribute's rounding of
the negated exact value, so RN(-8/3) is not -RN(8/3). The negation of a
param is a run-time neg of its rounded value. For an exact constant
(`2`, `1/2`) the two agree. The gate holds 8/3, where they differ, and
2, where they agree, under both attributes.

### The step's constants

- **h** is the step's constant, declared by the `step` line.
- **h-scaled constants** are a template's multiples of h (h/2, h/6),
  each a constant expression evaluated exactly and rounded once. The
  step graph records each one's factor, so the compiler's manifest can
  list them and write the halved bank. Halving RN(c h) is exact for
  these magnitudes; the gate holds that, and verifier-P1 measured it.
- A constant is either independent of h or a rational multiple of it.
  `h*h`, `1/h` and `h + 1` do not halve with h, and are `h-nonlinear`.
  - The rule holds a constant's value, not the products and quotients
    that make it: the checker carries every constant as c x h^d,
    exactly, so `(h*h)/h` is h, and `(h*h)/(h*h)` is 1 - in a map, a
    use of h that folds away (below).
  - Folding constants, a sum of different powers of h, and a min, max,
    minnum, maxnum, comparison or select whose operands are all
    constants, one of them changing with h's size, are refused where they
    are folded, whatever surrounds them: `(h + 1) - 1` at its sum
    although its value is h, and `min(h, 2*h)` although at h's sign it is
    a multiple of h. h's sign enters a constant only through copysign and
    abs. A run-time operation on an h-scaled constant is an operation like
    any other: `min(x, h)` in a map is a min of the state and the
    constant h.
- A flow's equations and their lets cannot read h, whatever it folds to,
  nor a const whose value changes with h's size (`h-scope`): a
  step-halving run halves h, and a right-hand side must not move with
  it. The rule refuses h read directly even where the value would not
  move, `(h/h) * x`, and a const that changes with h's size even where
  it is read so that it would not, `c/c`. A const whose value does not
  change with h's size is a plain rational wherever it is used, however
  it was written: `const c = h/h` is 1, and `copysign(1, h)` and
  `abs(h)/h` are h's sign, 1 or -1.
- **h's sign is fixed when a graph is compiled.** Every constant is
  c x h^d with c fixed by h's sign alone: `copysign(1, h)`, `abs(h)/h`
  and, in a map, `abs(h)` (h times h's sign) are folded at the graph's
  h. So a run may give h another value of the same sign, and that run
  is the system compiled at that h, bit for bit, its h-scaled constants
  recomputed; a run at an h of the other sign is refused
  (`step-size-sign`), since compiling there gives other constants. A
  step-halving run keeps the sign. Until 2026-10-01 such a run was
  accepted: `d/dt x = s * x` with `s = copysign(1, h)`, compiled at 1/8
  and run at -1/8, stepped 1 to 0.875 where compiling at -1/8 gives
  1.125 (verifier-VL1).
- A map may name a step, `step map, h = ...`. Its equations may then use
  h, and its h-scaled constants are listed like a template's.
- **A map that names h must use it in a constant that scales with it**,
  or it is `unused`: h is used only there. `h - h`, `h/h`,
  `(h*h)/(h*h)`, `copysign(1, h)`, `abs(h)/h` and `0*h` each fold to a
  constant that does not scale, and a map that reads h only so would
  declare an h its step never reads - a param's or lane param's default
  that reads such a const (`const c = h/h`, `param p = c`) included.
  Write the constant, or leave h out of the step line. In a map `abs(h)`
  is h times its sign, a scaled constant, and `h - h + h` is h; a flow
  always uses h, in its template.
  Until 2026-10-01 such a map was accepted, and its canonical form,
  declaring h and reading it nowhere, did not read back: the compiler
  stopped with exit 70 (the challenge suite's finding 1; parcel D2).

The references' constants at fp64 under rne. At fp256 every one equals
its classic bank slot as well; the gate holds both.

| constant | exact | encoding | hex significand | relative error | h-scaled |
|---|---|---|---|---|---|
| h | 1/100 | 0x3f847ae147ae147b | 0x1.47ae147ae147bp-7 | +2.0817e-17 | x 1 |
| h/2 | 1/200 | 0x3f747ae147ae147b | 0x1.47ae147ae147bp-8 | +2.0817e-17 | x 1/2 |
| h/6 | 1/600 | 0x3f5b4e81b4e81b4f | 0x1.b4e81b4e81b4fp-10 | +6.4185e-17 | x 1/6 |
| 2, 1 | 2, 1 | 0x4000000000000000, 0x3ff0000000000000 | 0x1p+1, 0x1p+0 | 0 | no |
| sigma, rho, F (params) | 10, 28, 8 | 0x4024..., 0x403c..., 0x4020... | 0x1.4p+3, 0x1.cp+4, 0x1p+3 | 0 | - |
| beta (param) | 8/3 | 0x4005555555555555 | 0x1.5555555555555p+1 | -5.5511e-17 | - |

**fp32.** At fp32 the language's h/6 is RN(1/600) = 0x3ada740e. The
classic bank's route, RN(RN(1/100)/6), gives 0x3ada740d, one ulp below:
- the relative errors are +2.4214e-08 for the language's value and
  -4.5635e-08 for the bank's route;
- there is no fp32 image, so the gate states the value and the
  difference.

**The time shift.** The time shift a template's constants carry, for
example 6 RN(h/6) / RN(h) - 1 for rk4, is no rounding rule's to remove.
The compiler's manifest states it, and the step graph carries everything
it needs. What it does to a t carried in the state is measured in
"Time".

## The step

**Flows and maps.** A flow steps with a template from the library,
expanded into one step. A map's equations are its step: `step map`.

**Step options.**
- The flow integrators take `h`, which they require
  (`missing-step-size`).
- stormer-verlet also takes `q = (...)` and `p = (...)`, the positions
  and the momenta.
- An option an integrator does not take is `step-option`.
- `h` that is exactly zero is `step-size-zero`.

### The integrators, written in the language

`python/cft_golden/lang/templates.py` holds this text, and the
language's own parser reads it. The gate holds this copy equal to it.

```
integrator euler
  next Y = fma(h, f(Y), Y)
end

integrator rk4
  let k1 = f(Y)
  let Y2 = fma(h/2, k1, Y)
  let k2 = f(Y2)
  let Y3 = fma(h/2, k2, Y)
  let k3 = f(Y3)
  let Y4 = fma(h, k3, Y)
  let k4 = f(Y4)
  let S2 = fma(2, k2, k1)
  let S3 = fma(2, k3, S2)
  let S4 = S3 + k4
  next Y = fma(h/6, S4, Y)
end

integrator stormer-verlet
  let Q1 = fma(h/2, v(P), Q)
  let P1 = fma(h, a(Q1), P)
  next Q = fma(h/2, v(P1), Q1)
  next P = P1
end
```

**The templates' names.**
- In a template, `Y` is the whole state. `Q` and `P` are stormer-verlet's
  positions and momenta.
- `f` is the whole right-hand side. `v` is the positions' right-hand
  sides, a function of P; `a` is the momenta's, a function of Q.
- `h` is the step.
- Every operation acts component by component, and a constant
  broadcasts.

**Labels.**
- A let's components are labelled `<let>.<component>`: `k1.x`,
  `Y2.x[3]`.
- A field let evaluated inside a template call is labelled
  `<let>.<name>` when the call is bound by a let (`k1.r`), and
  `<function><ordinal>.<name>` when the call is inline (`a1.r`).

**The orders, from programs/gen_odes.py, line by line.**
- **rk4.**
  - The stage inputs are fma(H2, k1, Y) (lorenz63 :331-332, lorenz96
    :464), fma(H2, k2, Y) (:337-338, :468) and fma(H, k3, Y) (:343-344,
    :475-476).
  - The sum is fma(TWO, k2, k1) (:335-336, :471), then fma(TWO, k3, S2)
    (:341-342, :479), then S3 + k4 (:347-348, :483).
  - The update is fma(H6, S4, Y) (:349-350, :485).
  - The right-hand sides (:279-287, :456-459) are as the references
    write them.
- **stormer-verlet**, drift-kick-drift.
  - Each drift is fma(H2, p, q) (henonheiles :566-567, :577-578).
  - The kicks are fma(MH, t0, px) (:570) and fma(H, t2, py) (:576), with
    t0 = x * fma(TWO, y, ONE) (:568-569) and t2 = fma(y, y - ONE,
    -(x * x)) (:572-575).
- **euler** has no image in the tree. fma(h, f, Y) is rk4's update with
  one stage: one rounding a component.

**The kick.** The kick is `P1 = fma(h, a(Q1), P)` for every system: the
force is the writer's right-hand side, as written. Henon-Heiles's px
kick is therefore fma(h, -(x * fma(2, y, 1)), px). The image writes
fma(MH, t0, px), moving the force's sign into a -h slot. Why the
language does not:
1. **One template serves every system.** The force is the writer's
   expression, and the template does not reach into it to move a sign.
2. **The image's form needs a -h constant.** Under the constant rule
   that is RN(-h), which under rdn and rup is not -RN(h), so the two
   kicks would part under the directed attributes.
3. **The h-scaled constants stay h and h/2.**
4. **It is the image's bits.** The exact product h * (-t0) equals
   (-h) * t0, and there is one rounding. A NaN result is the canonical
   NaN, and neg raises nothing (5.5.1). So the value and the FLAGS are
   equal, and the gate holds it on states and FLAGS, its overflow,
   signaling-NaN and subnormal lanes included.

The price is one neg more a step: 13 nodes against the image's 12.
Folding that neg into a slot holding -RN(h), the sign-flipped h slot, is
the compiler's to prove, not this definition's.

**Stormer-verlet's rules.** stormer-verlet needs a separable system:
- q and p split the state, each component in exactly one
  (`verlet-partition`);
- a position's right-hand side reads no position, and a momentum's reads
  no momentum (`verlet-not-separable`).

### A written-out step

**The block.** After `step`, a flow may write its expanded step out:
```
expansion
  let LABEL = ...
  next COMPONENT = ...
end
```
**What the checker does with it.**
- It parses the block as a map over the system's names: the state,
  params, lane params, consts, h and the block's own labels, but not the
  equations' lets.
- It builds the block's step graph and requires it to be the template's
  expansion, byte for byte. Anything else is `expansion-mismatch`, named
  at the first node that differs.
- A block on a map is `integrator-mismatch`.

So a writer can pin an expansion in a source, and a later compiler that
expands differently is refused by name. The canonical form writes the
block, and that is what makes its round trip a check of the expansion.

## Time

The language has no clock and no reserved `t`. A system that reads time
carries it in its state, and one that needs it exactly counts its
steps; both are written with what the language already has. Every
figure here was measured on the reference interpreter, `lang.run` - a
stage's values read from the step graph's labelled nodes, evaluated as
it evaluates them - from t = 0 and k = 0, under rne unless an attribute
is named, and `python/tests/test_lang_time.py` holds each one (parcel
T1, 2026-10-02). An ulp count is the number of floats between t and
RN(n h), the time after n steps rounded once to nearest, signed: +3 is
three floats above it.

### t in the state

```
state t, x
d/dt t = 1
d/dt x = fma(-t, x, 1)
```

- `t` is a name like any other: a source may declare it as state, a
  const or a param. A `t` that an equation reads and nothing declares
  is refused, `time-dependence`, and its sentence gives this advice.
- **It is not reserved.** A reserved `t` would refuse every source that
  follows that advice, `reserved-name` where it declares t, as making
  `tangent` a keyword refused every value named `tangent` ("The text").
- **What the templates make of it.** `d/dt t = 1` makes t's right-hand
  side the constant 1, and the canonical form shows each template's
  step on it:
  - euler: `next t = fma(h, 1, t)`;
  - rk4: `let Y2.t = fma(h/2, 1, t)`, Y3.t the same, `let Y4.t =
    fma(h, 1, t)` and `next t = fma(h/6, 6, t)`. Each stage reads its
    own time, rounded once, and the step adds 6 RN(h/6), which is not
    RN(h): the time shift of "The step's constants";
  - stormer-verlet, t among the positions: `let Q1.t = fma(h/2, 1, t)`
    and `next t = fma(h/2, 1, Q1.t)`, and the kick's force reads Q1.t,
    the midpoint time. Among the momenta t is kicked once by RN(h), and
    no force can read it.

### A dyadic step keeps t exact

With h = 1/64, t stayed exactly n h at every step to 10^4, under every
integrator and at every format. Under the other attributes, at fp64:
- euler and stormer-verlet stayed exact under every one. Each
  increment, h or h/2, is exact, and so is each sum while n h fits the
  format;
- rk4 stayed exact under rmm only. Its increment 6 RN(h/6) is not h,
  since h/6 = 1/384 is not dyadic: the nearest attributes round each
  sum back onto n h, and a directed one does not. From the first step t
  falls behind under rtz and rdn, -57, -658 and -4,538 ulps after 10^2,
  10^3 and 10^4 steps at fp64, and runs ahead under rup, +58, +659 and
  +4,539. With h = 3/64, whose half and sixth are dyadic, rk4 keeps t
  exact under every attribute.

### Drift otherwise

With h = 1/100 every sum rounds, and t wanders from n h. Ulps after n
steps:

| format | rk4 and euler, n = 10^2 | 10^3 | 10^4 | stormer-verlet, n = 10^2 | 10^3 | 10^4 |
|---|---|---|---|---|---|---|
| fp32 | -11 | +140 | +387 | -13 | +190 | -2,007 |
| fp64 | +3 | -95 | +1,003 | +3 | +92 | -1,299 |
| fp128 | +3 | -95 | +1,003 | +3 | +92 | -1,299 |
| fp256 | +4 | +60 | -1,602 | -32 | +70 | -2,001 |

- rk4 and euler agree at these marks but not at every step between.
  rk4 adds 6 RN(h/6) where euler adds RN(h), and the two sums round
  apart at 46 of the 10^4 steps at fp32, at one (the third) at fp64 and
  fp128, and at none at fp256, meeting again each time.
- fp128's rows are fp64's, at every step. Where every quantity a step
  rounds repeats in binary with a period dividing the bits one format
  carries beyond another, each sum rounds the same way relative to an
  ulp in both (verifier-VT1's theorem). fp128 carries 60 bits beyond
  fp64; euler rounds t + RN(h), stormer-verlet t + RN(h/2) and rk4
  t + 6 RN(h/6), and 1/100, 1/200 and 1/600 all repeat every 20 bits.
  At h = 1/99, which repeats every 30, euler and stormer-verlet agree
  between fp64 and fp128 at every step, but rk4, whose h/6 = 1/594
  repeats every 90, parts at 12 steps; at h = 1/19, every 18, the two
  formats differ.
- Under a directed attribute every rounding falls one way: after 10^4
  steps at fp64, rk4 and euler are -2,999 ulps off under rtz and rdn
  and +2,735 under rup. rmm's figures at fp64 are rne's.

### The step counter

```
state k, x
const dt = 1/100
d/dt k = 100              ; h's reciprocal, written as a number
let t = k * dt            ; the time, rounded once
d/dt x = fma(-t, x, 1)
step rk4, h = 1/100
```

- **A flow's equations cannot reach h.** `d/dt k = 1/h` is refused,
  `h-scope`: "a flow's equations cannot read h, whatever it folds to".
  So is `fma(k, h, t0)`, and so is a const read there whose value
  changes with h, `const dt = h` or `const c = 1/h`. h's reciprocal is
  written as a number and the step as a const, and k counts the
  declared step. A step-halving run halves k's increment, so k counts
  halves and k dt stays the time: k = n/2 at every step of 2 x 10^4 at
  h = 1/200, under rk4, euler and stormer-verlet, at fp64. At any other
  run value of h, k is not a count of steps.
- **Exact under the nearest attributes.** k = n at every step to 10^4,
  for h = 1/100, 1/10, 1/3 and 1/64 (rates 100, 10, 3 and 64), under
  rk4, euler and stormer-verlet with k among the positions or the
  momenta, at every format, and at fp64 under rmm too. Each step adds
  the template's increment - c RN(h) under euler and as a momentum,
  c RN(h/2) twice as a position, RN(6c) RN(h/6) under rk4 - which is
  1 + e for a small fixed e, and a nearest attribute rounds k + 1 + e
  back to k + 1 while e is under half an ulp of the count.
- **Not under the directed ones.** Under rtz, rdn and rup the count was
  wrong after the first step, for each of those h under each integrator
  at every format, except h = 1/64 under euler and stormer-verlet,
  whose increments are exact: at fp64 it stayed exact at every step.
  Under rk4 a step whose sixth is dyadic counts exactly under every
  attribute at fp64: h = 3/64, rate 64/3.
- **Its limit is 2^p, or 2^(p-1) among the positions.** k + 1 must be a
  float, so the count holds to 2^p steps under euler and rk4 and with k
  among stormer-verlet's momenta: 2^24 = 16,777,216 at fp32, 2^53 at
  fp64. Among the positions the first drift makes Q1.k = k + 1/2, which
  must be a float too, so the count holds to 2^(p-1): 2^23 = 8,388,608
  at fp32, 2^52 at fp64. rk4's stage counts n + 1/2, which give a stage
  its time, hold to 2^(p-1) as well. Started two below the limit with
  h = 1/100: at fp32 euler's counter and stormer-verlet's among the
  momenta stopped at 2^24, rk4's counted by twos, and stormer-verlet's
  among the positions stopped at 2^23; at fp64 each counted by twos
  past its limit. A segment may run 2^32 - 1 steps (`segment-steps`),
  so at fp32 one segment can outrun its counter.

**t from the counter.**
- `let t = k * dt` rounds n RN(1/100) once, and `fma(k, dt, t0)`, with
  t0 a param or a lane param, rounds n RN(dt) + t0 once. Nothing
  accumulates: at fp64 t equalled RN(n h) at 8,674 of the 10,001 counts
  from 0 to 10^4 and was one ulp off at the rest (fp32 7,332 equal,
  fp128 8,674, fp256 9,105; never two off).
- **A stage's time.** The field reads each stage's own counter, and
  rk4's are exact: Y2.k = Y3.k = n + 1/2 and Y4.k = n + 1, at every
  step and format. So the same let gives each stage its own time in one
  rounding: k2.t is RN((n + 1/2) RN(1/100)). Under stormer-verlet, k
  among the positions, the kick's force reads Q1.k = n + 1/2, the
  midpoint time.
- **The correctly rounded time**, RN(n h), takes four operations: the
  exact residual and the one correction that the golden model's divide
  ends with (`python/cft_golden/sequences.py`), q = fma(r, y, q0):
  ```
  let q = k * dt
  let r = fma(-q, 100, k)   ; k - 100 q, exactly
  let t = fma(r, dt, q)
  ```
  It equalled RN(n/100) at every count from 0 to 10^4 - from the count
  of a map that counts with `next k = k + 1`, at every format under rne
  and at fp64 under rmm, and at fp64 from the flow's count under both.
  In that map, at every format, it gave rup's rounding of n/100 at
  every count; under rtz and rdn it missed at exactly the 400 counts
  n = 25j, where n/100 is itself a float, giving the float below it;
  and under rdn t at n = 0 is -0, the value right and the sign
  roundTowardNegative's for an exact zero sum.
  Past 10^4 it rests on Markstein's theorem for a quotient corrected by
  its residual, whose hypotheses hold here: dt is within 0.375 u of
  1/100 (u = 2^-p: -0.375 u at fp32, +0.1875 u at fp64 and fp128,
  -0.125 u at fp256), so q is within an ulp of n/100 at every count and
  its residual r is a float. verifier-VT1 measured it under rne and rmm
  with no miss at every count from 0 to 2^24 at fp32, and at 30,000,
  15,000 and 8,000 random counts at fp64, fp128 and fp256; the gate
  holds a seeded 4,000, 4,000, 2,000 and 1,000 counts past 10^4 through
  the language. At counts no one has run it is believed.

**What the counter cannot give:** an exact t at every count when h is
not dyadic, since n h is a float only at some counts - for h = 1/100
every 25th, where t = k * dt is exact - and at the rest t is at best
its rounding; h itself, since the rate and dt are written for the
declared step; a count under a directed attribute, unless the
template's increment is exact; a count past its limit, 2^p or 2^(p-1).
A map counts with `next k = k + 1`, exactly under every attribute, and
may read h: `let t = fma(k, h, t0)`.

### Forcing

`sin` and `cos` of t wait for the math library: today `sin(w * t)` is
refused, `transcendental` ("sin is not computed by a program in v1"),
and they are step 6's M2 (docs/ROADMAP.md). Until then a rotation
carried in the state forces a system:

```
state c, s          ; c = cos(w t), s = sin(w t), started by the host
param w = 1
d/dt c = -(w * s)
d/dt s = w * c
```

**Its own rounding.** c and s are state, stepped and rounded like any
other component: each right-hand side is one product, exact here with
w = 1, and each stage rounds. Nothing holds c^2 + s^2 to 1. Measured
exactly from the encodings, with h = 1/100, from c = 1 and s = 0, and
stormer-verlet's c a position and s a momentum; the rounding's share is
the measured value less the same step evaluated without rounding, its
constants as rounded and every operation exact:

| integrator, format | n = 10^2 | 10^3 | 10^4 | the rounding's, at 10^4 |
|---|---|---|---|---|
| rk4, fp32 | -1.1465e-07 | -2.4863e-07 | -2.2401e-06 | -2.2865e-06 |
| rk4, fp64 | -1.3880e-12 | -1.3888e-11 | -1.3889e-10 | -1.1986e-15 |
| rk4, fp256 | -1.3889e-12 | -1.3889e-11 | -1.3889e-10 | -1.9992e-70 |
| stormer-verlet, fp32 | +1.7645e-05 | +9.5304e-06 | +1.0495e-05 | +4.0936e-06 |
| stormer-verlet, fp64 and fp256 | +1.7702e-05 | +7.4001e-06 | +6.4012e-06 | +8.3061e-15 and -7.4655e-70 |

- From fp64 up the drift is the integrator's own. In exact arithmetic
  rk4's step multiplies c^2 + s^2 by 1 - (wh)^6/72 + (wh)^8/576, which
  comes to -1.3889e-10 after 10^4 steps; at fp32 the rounding's share
  is the larger. stormer-verlet keeps a nearby quadratic form, not
  c^2 + s^2, so its c^2 + s^2 oscillates without drifting. euler
  multiplies it by 1 + (wh)^2 a step: +1.7181e+00 after 10^4 steps at
  fp64.
- The phase is the integrator's too: after 10^4 steps at fp64,
  atan2(s, c) is 8.3330e-09 rad behind w t under rk4, about (wh)^5/120
  a step, and 4.1122e-04 rad ahead under stormer-verlet.
- With w = 3/10 the products round: at fp64 rk4's drift after 10^3
  steps is -1.2395e-14, of which -2.2705e-15 is the rounding's.

A forced, damped oscillator at resonance, x'' + gamma x' + x =
F cos(w t) with w = 1:

```
system forced
format fp64
round  rne
state  c, s, x, v
param  w = 1, F = 1/2, gamma = 1/10
d/dt c = -(w * s)
d/dt s = w * c
d/dt x = v
d/dt v = fma(F, c, -fma(gamma, v, x))
step   rk4, h = 1/100
```

From c = 1, s = 0 and rest, its c and s are the rotation's above, bit
for bit, and x stayed within 4.0276e-08 of the exact solution,
(F/gamma) (sin t - e^(-gamma t/2) sin(wd t)/wd) with
wd = sqrt(1 - gamma^2/4), at every step to t = 100. The rotation's lag
accounts for about 3.2e-08 of it and x's own rk4 error for about
0.8e-08: a twin of x and v forced by the exact cos t at rk4's stage
times stays within 0.8e-08 of the exact solution, and the example
within 3.2e-08 of the twin (verifier-VT1).

## The step graph

The checked form of one step. The checker builds it; the interpreter,
the renderers and the compiler read it. `python/cft_golden/lang/graph.py`
holds it, as canonical JSON, version 1 - or version 2 for a system with
tangent vectors, which adds three keys after `step` and changes nothing
before them (see "The variational equations").

| key | content |
|---|---|
| `cftl_graph` | 1, or 2 when the system declares tangent vectors |
| `system`, `format`, `round` | the name, the format, the one attribute |
| `state` | [[name, length or null]], declaration order. The flat component order s0, s1, ... is this order with an array's components by index: the lane layout |
| `lane` | [[name, default exact or null, encoding or null]] |
| `param` | [[name, default exact, encoding, flags]] |
| `integrator` | [name, h exact or null, options or null]; options are {"q": [...], "p": [...]} for stormer-verlet |
| `const` | [[exact, h-factor or null, encoding, flags]]: one entry per distinct (exact value, h-factor). The h-scaled come first by factor descending, then the rest by value ascending |
| `field` | a flow's right-hand sides once, over the state inputs: {"out": [ref], "nodes": [node]}. null for a map |
| `step` | one step with the template expanded: {"out", "nodes"}. What the interpreter runs and the compiler compiles |
| `tangent` | version 2 only: the tangent vectors' names, declaration order |
| `tangent_field` | version 2 only: the derivative of `field` along a tangent vector, {"out", "nodes"}; null for a map |
| `tangent_step` | version 2 only: the derivative of `step`, {"out", "nodes"}: what the interpreter runs once a vector, after the step |

**Nodes and refs.**
- A node is `[op, [ref, ...], label or null]`.
- A ref is `sN` (a state input), `lN` (a lane param), `pN` (a param),
  `cN` (a const) or `nN` (an earlier node of the same section). In a
  tangent section `nN` is a labelled node of the section it
  differentiates, `dN` an earlier node of the tangent section itself,
  and `tN` the tangent input N.
- Exact values are written `p/q` or `p`; encodings are `0x` and the
  format's width in hex digits.

**What makes the bytes canonical.**
- **One node per operator written**, after expansion. The graph does no
  sharing of identical subexpressions; the compiler may share. So an
  unlabelled node has exactly one use, which the builder asserts.
- **Constant subexpressions are folded exactly** as nodes are built.
- **Nodes are ordered by an iterative post-order walk** from the outputs,
  in state order, operands in order. The order of equations and lets,
  and spelling (`0.01` against `1/100`, `h/2` against `0.5*h`), do not
  reach the bytes. The order of declarations does where it is a layout:
  the state's is the lane layout, and the params' and lane params' are
  the bank's and the lane's.
- **ASCII, the key order above, no spaces, one node a line, a final
  newline.**
- **No set or hash order anywhere.** The gate builds each reference
  under two other PYTHONHASHSEEDs and compares the bytes.
- **Reading back.** `StepGraph.from_bytes` takes only the bytes the
  language would make. It refuses (`graph-format`) four kinds of input:
  - bytes not in this layout;
  - a ref that points forward;
  - an encoding that is not its exact value rounded once;
  - a graph that is not canonical.

  A graph is canonical when it is the graph of its own canonical form:
  rendered, parsed and checked again, it gives the same bytes. That
  refuses, among others, a dead node, a node order that is not the
  walk's, a shared unlabelled node, a const nothing reads, options on
  the wrong integrator, and a step that is not its field's expansion.
  JSON nested too deep is refused by name too.
- **The constants' report.** `StepGraph.constant_report()` lists every
  constant and default the step reads, as the compiler's manifest wants
  them: its spelling, exact value, h-factor, encoding, flags and exact
  relative error.

Each reference's step, against the image's ALU instructions a step
(counted from the image itself by the gate):

| system | equations | a step | the image's ALU a step | difference |
|---|---|---|---|---|
| lorenz63 | 8: 2 fma, 2 sub, 2 mul, 2 neg | 53: 26 fma, 3 add, 8 sub, 8 mul, 8 neg | 53, the same split | none |
| lorenz96 | 120: 40 fma, 80 sub | 760: 400 fma, 40 add, 320 sub | 760, the same split | none |
| henonheiles | 7: 2 fma, 1 sub, 2 mul, 2 neg | 13: 8 fma, 1 sub, 2 mul, 2 neg | 12: 8 fma, 1 sub, 2 mul, 1 neg | one neg: the kick, above |

Lorenz-96's 692 scratch accesses, and the REPEAT, ENDREP and HALT, are
the image's control codes, not nodes. Where the state lives is the
compiler's business.

## The reference interpreter

`python/cft_golden/lang/interp.py`:

```
run = lang.run(graph, states, steps,
               lane_params=None,   # one list a lane, declaration order; None takes the defaults
               params=None,        # {name: int, Fraction or a constant as text}: run values, each rounded once
               param_bits=None,    # {name: encoding}: run values as a bank carries them
               h=None,             # an exact step in place of h, of h's sign: every h-scaled constant recomputed
               at=(),              # step counts at which to record (states, FLAGS)
               tangents=None)      # with tangent vectors only: one list a lane, one list a vector of n encodings
run.states    # one list a lane: the state's encodings after `steps` steps
run.flags     # the five IEEE flags, a sticky OR over every node, lane and step
run.at        # {s: (states, flags)}
run.tangents      # with tangent vectors: one list a lane, one list a vector
run.primal_flags  # the primal nodes' FLAGS alone: the run without the tangents
run.at_tangents   # {s: tangents}
```

A system with tangent vectors is run as "The variational equations,
Running them" says: each step the primal nodes first, then each vector's
tangent nodes, which only read them.

**What a run does.** Each step, for each lane, every node of the step
section, in order, is evaluated by its golden function under the
program's attribute.
- **FLAGS** ORs every node's flags over every lane and step, exactly as
  seq.py ORs every ALU instruction's over its active lanes.
- **Constants' flags** are not FLAGS.
- **Lanes do not interact**: the language has no cross-lane condition,
  so running lane by lane is the lockstep run.

**The lane layout is seq.py's scratch block.** Lane k's values are its
state components then its lane params: m = n_state + n_lane values. That
is seq.py's `scratch_in[k*m:(k+1)*m]`, and after S steps
`Result.scratch_out[k*m : k*m + n_state]` is `run.states[k]`. For the
references m is 3, 40 and 4: exactly their images' `.scratch in` and
`.scratch out`.

**Run values.** A run value is an int, a Fraction, or a constant written
as text, which is read by the language's own rules:
- its literals, so `0x1p-3` and `8/3` are exact;
- exact arithmetic;
- a minus written on a zero refused;
- the bound of 2^+-1048576.

Each is rounded once under the program's attribute, and refused by the
same constant refusals as a source's constant.

**Refusals of a run.**
- A lane of the wrong length is `lane-shape`.
- A value that is not an encoding is `lane-value`.
- A run value for no param is `unknown-param`.
- `param-value`: a Python float as a run value (it is binary64 already),
  text that is not a constant, or one param given both as a value and as
  an encoding.
- A step count that is not a whole number is `step-count`.
- An h of the other sign from the graph's is `step-size-sign` (see "The
  step's constants"): a run at an h of the same sign is the graph
  compiled at that h, and the gate holds that on every reference at h/2
  and 3h/7.

## The intention-out

Every compilation can write the program back out as the language
understood it, regenerated from the step graph and never from the
source, two ways. `python/cft_golden/lang/render.py` writes both.

**The canonical form** is the program in the language itself, in ASCII.
- **Lets and inlining.** Every labelled node is a `let`, and every
  unlabelled node, which has one use, is written in place.
- **Parentheses.** No reading depends on precedence.
  - A binary operation inside another is parenthesised, except a left
    operand of the same kind. `a + b - c` and `a * b * c` are written
    so: they are `(a + b) - c` and `(a * b) * c` by the language's own
    rule that binary operators associate left, and a long sum written
    out stays one level deep.
  - A binary operation under a unary minus is parenthesised, and so is
    a unary minus that is an operand of a binary operation: `(-x) * y`,
    `-(x * y)`.
  - A run of minuses is written flat, one minus a negation: `- -x`,
    `- - -(x * y)`. The parser reads a run in a loop, so the canonical
    form of any run reads back, however long.
- **Constants.** A constant is written as its h-multiple (`h`, `h/2`,
  `2*h`) or as its exact value, at any size:
  - a decimal when it terminates within 24 significant digits, an
    integer among them (`2`, `0.01`, `1e4400`);
  - a hexadecimal significand when it is dyadic and longer;
  - otherwise `p` or `p/q`, in full.
- **The step.** A flow keeps its equations and writes its step out in an
  `expansion` block. The block's lets come in the template's statement
  order, components in state order.
- **Comments.** They give the graph's sha256, the attribute and the
  format, the operation counts, each constant's exact value, encoding
  and relative error, the h-scaled constants, and each param's and lane
  param's default the same way (or that a lane param has none).

**The mathematical form** gives the equations in conventional notation,
in UTF-8 plain text.
- **fma.** Each fma is shown as the a*b + c it computes. When a is a
  constant it reads c + a·b, as textbooks write a stage. A negated
  addend reads as a subtraction.
- **Parentheses** appear only where exact arithmetic needs them.
- **Constants.** Each constant is its exact value, and h-multiples print
  as `h/2` with h's value stated.
- **The step** is the template's own scheme: each let used once and not
  a call of the right-hand side is written in place.
- **Greek letters.** A name that spells a Greek letter prints as the
  letter: `sigma` as σ, `Delta` as Δ, all twenty-four, lower and capital.
  The mapping is cosmetic. The exact-evaluation check binds every value
  by its position in the step graph's own declarations, never by the
  glyph, and the third check holds every glyph printed.
- **No LaTeX.** There is no LaTeX rendering in this parcel. Every
  rendering needs its own exact-evaluation check before it can be
  trusted, and a LaTeX one would be a third renderer with its own check.

**The three checks**, held in the gate (`python/tests/test_lang.py`), on
the six references, on five written systems whose names are Greek
letters wherever a name is printed (params, lane params with and
without defaults, lets and an indexed let, state components, q and p,
each integrator, an h-scaled constant in a map), and on sixty seeded
random systems that cover every operation, constants folded, lets,
arrays, lane params, every format and attribute, and each integrator
and maps:
1. **The canonical form is itself a valid source.** Parsed again it gives
   the same step graph, byte for byte, and written out again it gives
   the same text, byte for byte, comments included. A canonical form
   that parses back to a different graph is a defect, not a style
   choice.
2. **The mathematical form, evaluated exactly at random rational points,
   gives what the step graph gives evaluated exactly.**
   - `python/tests/lang_mathform.py` is the test's own reader of the
     notation, sharing no code with the renderer.
   - For a flow it checks each right-hand side, and the whole step
     through the template's scheme. For rk4 that holds the expansion to
     the textbook scheme, exactly.
3. **What the intention-out says besides its code is read back and held
   to the graph and to the test's own arithmetic and tables.** Every
   line of both forms is read, in order, and a line the reader does not
   expect fails. The test's tables are
   its own: IEEE 754-2019's names for the attributes and the formats,
   each integrator's name, Unicode's own Greek letters.
   - The canonical form's comments: the system's name; the sha256
     line, against the test's own sha256 of the graph's bytes; the
     attribute and the format each time they are named; the operation
     counts; each constant's spelling (an h-multiple read with h as 1
     is its factor, and its value that factor times the graph's h), its
     exact value, its encoding in hex and as a hexadecimal significand,
     its flags and its relative error, and its one rounding; the
     h-scaled list, each item's factor in the table's order; each
     param's and each lane param's default the same way, or a lane
     param's "no default"; and no comment on any other line. The fixed
     sentences are held word for word. The code between them is held
     by the first check.
   - The mathematical form's lines: its title, and its header's format
     and attribute; the fixed sentences, word for word; each param's
     and lane param's name and printed default, or a lane param's
     name alone; each let's name, in the graph's order; each state
     component's name wherever it is printed (the equations, Y, Q and
     P, a map's lines); the integrator's name; h's value. Each name is
     held against Unicode's own Greek letters. The expressions are the
     second check's, which holds them at the points it samples, so only
     at points that take them: a select's arm, the operand a min or max
     discards, a comparison's threshold or its strictness (`<` against
     `<=`), an absolute value where the sampled operand is already
     non-negative. Exact arithmetic cannot tell minNum from min, or
     maxNum from max, where no NaN is sampled, so a name swapped between
     them goes unseen.
   - Each integrator's scheme lines are held word for word, against the
     test's own copy of each scheme, as the titles are; the second check
     evaluates them too. So a printed stage that no output reads is
     caught: verifier-VL1 printed an unused fifth rk4 stage,
     `k5 = f(Y + h·k4)`, and every check passed until L3 held the
     schemes word for word (2026-10-01). The gate plants that stage.
   - A system with tangent vectors prints more, each line read the same
     way, and is held by a fourth check besides ("The variational
     equations, What the gate holds").
   - The check is held itself: a test plants a wrong sha256 digit,
     attribute, format, title, h-scaled list, lane default and its
     encoding, a comment on an equation, a lane param's and a let's
     glyph, the integrator's name and an unused fifth rk4 stage, and
     each must be caught. Before
     2026-10-01 the check held params' defaults and names and the
     state's names only, and VL1's map, its lane param `rho = 1/3`
     printed as `ρ = 2/3`, passed (verifier-VL1). Of 32 such plants,
     one printed thing each, 29 passed on every system they changed,
     and none passes on any now (measured on the six references, the
     five written systems and the sixty random ones).

### Lorenz-63, as the renderers write it

The canonical form:

```
; lorenz63 - the canonical form, regenerated from the step graph
; sha256 e3153e4d526117574089681d5539012b16fc7d493015315656ceda6c5e93e80c
;
; Read back, this text gives the same step graph, byte for byte. Every
; operation is written once, in the order it is performed; each one
; that rounds rounds once, under rne (roundTiesToEven), in binary64.
;
; operations: the equations 8 (2 fma, 2 sub, 2 mul, 2 neg);
;             a step 53 (26 fma, 3 add, 8 sub, 8 mul, 8 neg)
;
; constants, exact value -> binary64 under rne:
;   h    0.01   0x3f847ae147ae147b  0x1.47ae147ae147bp-7   inexact, relative error +2.0817e-17
;   h/2  0.005  0x3f747ae147ae147b  0x1.47ae147ae147bp-8   inexact, relative error +2.0817e-17
;   h/6  1/600  0x3f5b4e81b4e81b4f  0x1.b4e81b4e81b4fp-10  inexact, relative error +6.4185e-17
;   2    2      0x4000000000000000  0x1p+1                 exact
; h-scaled, halved by a step-halving bank: h, h/2, h/6

system lorenz63
format fp64
round  rne
state  x, y, z
param  sigma = 10   ; 0x4024000000000000  0x1.4p+3  exact
param  rho = 28     ; 0x403c000000000000  0x1.cp+4  exact
param  beta = 8/3   ; 0x4005555555555555  0x1.5555555555555p+1  inexact, relative error -5.5511e-17

d/dt x = sigma * (y - x)
d/dt y = fma(x, rho - z, -y)
d/dt z = fma(x, y, -(beta * z))

step rk4, h = 0.01
expansion
  let k1.x = sigma * (y - x)
  let k1.y = fma(x, rho - z, -y)
  let k1.z = fma(x, y, -(beta * z))
  let Y2.x = fma(h/2, k1.x, x)
  let Y2.y = fma(h/2, k1.y, y)
  let Y2.z = fma(h/2, k1.z, z)
  let k2.x = sigma * (Y2.y - Y2.x)
  let k2.y = fma(Y2.x, rho - Y2.z, -Y2.y)
  let k2.z = fma(Y2.x, Y2.y, -(beta * Y2.z))
  let Y3.x = fma(h/2, k2.x, x)
  let Y3.y = fma(h/2, k2.y, y)
  let Y3.z = fma(h/2, k2.z, z)
  let k3.x = sigma * (Y3.y - Y3.x)
  let k3.y = fma(Y3.x, rho - Y3.z, -Y3.y)
  let k3.z = fma(Y3.x, Y3.y, -(beta * Y3.z))
  let Y4.x = fma(h, k3.x, x)
  let Y4.y = fma(h, k3.y, y)
  let Y4.z = fma(h, k3.z, z)
  let k4.x = sigma * (Y4.y - Y4.x)
  let k4.y = fma(Y4.x, rho - Y4.z, -Y4.y)
  let k4.z = fma(Y4.x, Y4.y, -(beta * Y4.z))
  let S2.x = fma(2, k2.x, k1.x)
  let S2.y = fma(2, k2.y, k1.y)
  let S2.z = fma(2, k2.z, k1.z)
  let S3.x = fma(2, k3.x, S2.x)
  let S3.y = fma(2, k3.y, S2.y)
  let S3.z = fma(2, k3.z, S2.z)
  let S4.x = S3.x + k4.x
  let S4.y = S3.y + k4.y
  let S4.z = S3.z + k4.z
  next x = fma(h/6, S4.x, x)
  next y = fma(h/6, S4.y, y)
  next z = fma(h/6, S4.z, z)
end
```

The mathematical form:

```
lorenz63 - the mathematical form, regenerated from the step graph
binary64 (fp64), roundTiesToEven

Each operation here is exact. The program performs the same
operations, each rounded once, in the order the canonical form
writes them.

parameters, the run's (defaults)
  σ = 10
  ρ = 28
  β = 8/3

the equations
  dx/dt = σ·(y − x)
  dy/dt = x·(ρ − z) − y
  dz/dt = x·y − β·z

one step: the classical Runge-Kutta method (rk4), with f the right-hand sides above
  h = 0.01
  Y = (x, y, z)
  k1 = f(Y)
  k2 = f(Y + (h/2)·k1)
  k3 = f(Y + (h/2)·k2)
  k4 = f(Y + h·k3)
  Y ↦ Y + (h/6)·(k1 + 2·k2 + 2·k3 + k4)
```

The gate holds both blocks to the renderers' output.

## The variational equations

A system may ask for its **variational equations**: the derivative of
its step along one or more **tangent vectors**, each a vector over the
whole state, stepped beside the state by the same program. They are
what a largest Lyapunov exponent, a sensitivity to initial conditions or
a linear stability analysis reads. What is differentiated is the step
itself, node by node, so a map has them as a flow does, and every
rounding of the tangent is fixed by rules written in the language.
`python/cft_golden/lang/tangent.py` is the derivation; the rest of this
definition carries it (the checker, the step graph, the interpreter, the
intention-out); the compiler compiles it (`python/cftc`), and the
`tangent` stage holds the compiled images to it (docs/VERIFICATION.md).

### Asking for them

`programs/systems/lorenz63-rk4-tangent-fp64.cftl`:

```
system lorenz63
format fp64
round  rne
state  x, y, z
tangent v
param  sigma = 10, rho = 28, beta = 8/3
d/dt x = sigma * (y - x)
d/dt y = fma(x, rho - z, -y)
d/dt z = fma(x, y, -(beta * z))
step   rk4, h = 1/100
```

- `tangent NAME {, NAME}` declares tangent vectors, one a name, in
  order; another `tangent` line adds more, as `state` does.
- A vector's components are `<vector>.<component>`: `v.x`, `v.x[3]` -
  the language's way to name a vector's component, as `k1.x` names one
  of a stage.
- A vector's name is a plain name. It is refused `duplicate-name` when
  it names anything else, `syntax` when dotted, and `reserved-name` when
  reserved or a label prefix of an expanded step (k1 to k4, Y2 to Y4, S2
  to S4, Q1, P1, and the call prefixes f1, v1, v2, a1): a vector named
  Y2 would make `Y2.x` both rk4's stage and a tangent.
- Nothing else is written: the tangent equations are derived. A source
  may write them out too, and they are then held to the derivation
  ("Writing them out"). Lorenz-96, its tangent equation written out:

```
system lorenz96
format fp64
round  rne
state  x[40] cyclic
tangent v
param  F = 8
d/dt x[i] = fma(x[i+1] - x[i-2], x[i-1], F - x[i])
d/dt v.x[i] = fma(v.x[i+1] - v.x[i-2], x[i-1], fma(x[i+1] - x[i-2], v.x[i-1], -v.x[i]))
step   rk4, h = 1/100
```

**A run's tangents** are given per lane, like the state: lang.run takes
`tangents=`, one list a lane holding one list a vector of the state's
n encodings in its flat order. A compiled image's lane block is the
state, then each vector's components in declaration order, then the
lane params: `[state | v | w | lane params]`, n(1 + T) + n_lane values
(`lane-capacity` holds them to 32,768).

### What is differentiated: the step

The tangent of a system is the derivative of its **step**: each node of
the step graph differentiated by its operation's rule (below), along a
tangent vector, at the values the step computes. It is the step map's
own tangent-linear model, and that is a choice between two
constructions:
- (A) differentiate the right-hand side f into the tangent field
  Df(y)·v, and apply the same integrator to the extended system (y, v);
- (B) differentiate the step the integrator makes, node by node.

**In exact arithmetic they agree.** An explicit Runge-Kutta step is
y1 = y0 + h Σ b_i k_i with k_i = f(Y_i) and Y_i = y0 + h Σ a_ij k_j; its
derivative along v is v1 = v + h Σ b_i δk_i with δk_i = Df(Y_i)·V_i and
V_i = v + h Σ a_ij δk_j - the same method on the extended system, with
the same coefficients and stages. euler is its one-stage case.
stormer-verlet's derivative is stormer-verlet on the extended system
with positions (Q, δQ) and momenta (P, δP), which stays separable,
since Dv(P)·δP reads momenta only and Da(Q)·δQ positions only. The
rounded constants (RN(h/2), RN(h/6), 2) are coefficients, the same in
both. The gate holds A and B equal, exactly, at sampled points.

**In floating point they agree node for node** wherever no tangent of
the right-hand side is identically zero: the rules give each template
operation the template's own form on the tangent (`fma(h/2, v.k1.x,
v.x)`, `fma(2, v.k2.x, v.k1.x)`), and A, as the checker expands it from
a source written with the tangent as more state, equals B node for node
after sharing (the gate holds it). They part where a component is
identically zero - a right-hand side that reads no state, such as
`d/dt t = 1`, the language's way to carry time ("Time"). There A
computes `fma(h/2, 0, v.t)`, one rounding of an exact value, which
turns -0 into +0 and a signalling NaN into the canonical NaN. B leaves
the term out: `next v.t = v.t`.

**The language's is B.**
- It is the only construction a map has: a map's step is its equations.
- It is local: one rule an operation, so the tangent's rounding order is
  fixed by the step graph's order, the rules' written forms and the
  canonical walk; no template needs a tangent version, and a later one
  gets its tangent from the rules.
- It is the derivative of what the program computes, which is what a
  Lyapunov exponent of the system the tile runs reads.
- It never rounds an exact zero.
- For v1's three templates it is A, node for node, wherever A rounds no
  zero, so the mathematical form may print the textbook scheme (the
  same method on δY), and its exact check holds it.

### The rules

`a`, `b`, `c` are an operation's operands, `da`, `db`, `dc` their
tangents and `r` its own result. A tangent is **identically zero** when
its value reads no state component - a constant, h, a param, a lane
param - or reads one only through a comparison or a select's condition.
An identically-zero tangent is never an operand: each term it would
make is left out, exactly, and where a select needs an arm it is the
constant 0. Each rule is an expression in the language, so its
roundings are fixed like any other's; every point where an operation is
not differentiable is given its fixed value in the last column.

| operation | its tangent | where a tangent is zero | where it is not differentiable |
|---|---|---|---|
| `a + b` | `da + db` | the other's tangent, as it is | - |
| `a - b` | `da - db` | `da`; or `-db` | - |
| `-a` | `-da` | zero | - |
| `a * b` | `fma(da, b, a * db)` | `da * b`; or `a * db` | - |
| `fma(a, b, c)` | `fma(da, b, fma(a, db, dc))` | each zero term left out: `fma(da, b, dc)`, `fma(a, db, dc)`, `fma(da, b, a * db)`, `da * b`, `a * db`, or `dc` | - |
| `abs(a)` | `copysign(1, a) * da` | zero | at a = +0, da; at a = -0, -da: the side the zero's sign bit names; at a NaN, its sign bit decides |
| `copysign(a, b)` | `copysign(1, b) * (copysign(1, a) * da)` | zero when da is | at a = ±0 as abs; at b = ±0 the jump in b is not differentiated: db is never read |
| `min(a, b)`, `max`, `minnum`, `maxnum` | `select(r == a, da, db)` | `0` for the zero side | at a tie, ±0 included, r == a: the first operand's tangent; where the result is a NaN, r == a is false: the second's |
| `a < b`, `<=`, `>`, `>=`, `==` | zero | | the jump at a = b is not differentiated |
| `select(c, a, b)` | `select(c, da, db)` | `0` for the zero side | the jump at c = 0 is not differentiated: c's tangent is never read |
| a constant, h, a param, a lane param | zero | | |
| a state component x | the tangent input `v.x` | | |

**Where a rule follows a published convention.**
- A product's tangent is a sum of two products, and IEEE 754-2019's
  fusedMultiplyAdd (5.4.1) rounds one of them with the sum: two
  roundings, the fewest such a sum takes.
- abs and copysign read the derivative's sign from the sign bit, as IEEE
  754-2019 reads a sign: copySign (5.5.1) takes it, and isSignMinus
  (5.7.2) counts -0 and a NaN with its sign bit set as negative. So at a
  zero the tangent is the one-sided derivative on the side the zero's
  sign names. For every tangent that is not a NaN, `copysign(1, a) * da`
  is RISC-V's FSGNJX(da, a), the F extension's sign-injection XOR (da
  with its sign bit XORed with a's, the instruction fabs is written
  with): a product by ±1 is exact and raises nothing at any format,
  subnormals included (measured at fp32, fp64 and fp256). A signalling
  NaN tangent raises invalid and gives the canonical NaN, where FSGNJX
  would keep its payload.
- min, max, minNum and maxNum are IEEE 754-2019's 9.6 operations, which
  each choose an operand; the tangent is the chosen one's, read as the
  operand the result equals, so a minNum that returns its number takes
  the number's tangent. The compare raises invalid only on a signalling
  NaN, as the primal's own operation already did. Where the operands
  tie the language takes the first operand's tangent; that is its own
  convention, no published one.
- No standard fixes a derivative's rounding; the rest are the
  language's.

**The product.** `fma(da, b, a * db)` takes two roundings: its error is
at most u|a·db| + u|d(ab)| + O(u²), against u(|da·b| + |a·db|) +
u|d(ab)| for the three of `da*b + a*db`. It reads the primal's operands
a and b, already computed, and never the primal's own product, so
Lorenz-63's image computes 53 + 61 = 114 operations a step: the
tangent's own, and nothing of the step twice. It is **not symmetric**:
`a * b` and `b * a` have the same primal and tangents rounded
differently, each fixed by the order written. The compiler may commute
the primal's multiplicands, and that never reaches the tangent, which is
derived from the graph as written.

**Reading a primal value.** A rule reads a primal value by name where it
has one - a state component, a param, a lane param, a constant, a let, a
label of the expanded step - and otherwise **writes it again**:
Lorenz-63's `rho - z` in `fma(v.x, rho - z, fma(x, -v.z, -v.y))`. A
value written again is an operation of the tangent, performed again: the
same operation on the same values, so the same bits and the same flags
(FLAGS is an OR). The compiler shares it with the primal's own, as it
shares any repeated subexpression. So the canonical form's promise holds
of the tangent too: every operation written is performed, once, in the
order written.

**Roundings, every operand's tangent nonzero** (the primal's in
brackets): `+` and `-` 1 [1]; unary minus none [none]; `*` 2 [1]; fma 2
[1]; abs one exact product by ±1 [none]; copysign two [none]; the min
family and select none, a quiet compare and a select [none].

**Nothing is refused for not being differentiable.** Every operation is
differentiable almost everywhere, and each point where one is not has
the value the table fixes; refusing abs, min or select would refuse
working systems. A run could not refuse one either: there is no branch,
and FLAGS belongs to the run, not to a lane.

### Writing them out

The canonical form writes every vector's tangent as code, and a source
may write any of it, to pin it as an expansion block pins a template:
- a flow's tangent equations, `d/dt v.x = ...`, with their lets,
  `let v.r = ...` (the tangent of the let r); a map's, `next v.x = ...`;
- in an expansion block, the tangent's lines: `let v.k1.x = ...` and
  `next v.x = ...`, after the step's own.

What is written is evaluated in that vector's own context - its
components are the tangent inputs, a name of the state or a let is the
primal's value, a primal expression written out is written again - and
held to the derivation byte for byte. A difference is `tangent-mismatch`,
named at the first label or component, in the canonical form's order,
whose definition differs. Of a vector's equations a source writes all
or none (`missing-equation`), and of its lines in a block all or none.
A name in a tangent vector - a component, a tangent let or a label -
read where it cannot be - by the state's equations, lets or constants,
or by another vector's equations - is `tangent-scope`, and so is a
vector read whole (`v` for `v.x`).

### The step graph, version 2

A graph with tangent vectors is version 2: version 1's keys byte for
byte, then `tangent`, `tangent_field` and `tangent_step` ("The step
graph"). The tangent sections are **generic**, one for every vector, and
canonical by the same walk; a tangent node is labelled with the primal
label it is the tangent of (v.k1.x is written for the node labelled
k1.x), and an unlabelled one has one use, since a primal value is read
across sections only where it has a name.
- **The primal is unchanged.** `field`, `step` and the const table are
  the primal graph's, byte for byte, unless a rule adds a constant the
  table lacks - only 0, 1 and -1 can be added (1 by abs and copysign; 0
  by a min or a select with one side zero, and by an output whose
  tangent is zero; -1 where copysign's b is a negative constant, so that
  `copysign(1, b)` folds, as any constant expression does) - and then
  only the const refs are renumbered by the table's value order. No
  reference adds one, and the gate holds both cases.
- **A graph without tangents is version 1, byte for byte**, so nothing
  written before L3 moves: the gate holds the six references' graphs
  and the 48 committed compiled files. A version-1 reader - cftc's,
  before L3 - refuses a version-2 graph rather than drop its tangents.

### Running them

Each step, for each lane: the primal nodes first, in order, as without
tangents; then, for each vector, the tangent nodes, which read the
step's primal values - the state the step began from and its nodes - and
never write them; then the state and every vector move together. So the
states, and the primal nodes' FLAGS (`run.primal_flags`), are a run of
the same system without its tangents, bit for bit; `run.flags` ORs
every node's, primal and tangent, which is what a tile's FLAGS hold.
`lane-shape` refuses tangents missing, given where the graph has none,
or of the wrong shape, and `lane-value` a value that is not an encoding.

### Lorenz-63's variational equations, as the renderers write them

The canonical form of `lorenz63-rk4-tangent-fp64.cftl` is Lorenz-63's
("Lorenz-63, as the renderers write it") with these lines more - its
operation counts:

```
; operations: the equations 8 (2 fma, 2 sub, 2 mul, 2 neg);
;             a step 53 (26 fma, 3 add, 8 sub, 8 mul, 8 neg);
;             each tangent vector's equations 11 (4 fma, 2 sub, 2 mul, 3 neg)
;             and its step 65 (34 fma, 3 add, 8 sub, 8 mul, 12 neg)
```

the tangent equations, after the state's:

```
d/dt v.x = sigma * (v.y - v.x)
d/dt v.y = fma(v.x, rho - z, fma(x, -v.z, -v.y))
d/dt v.z = fma(v.x, y, fma(x, v.y, -(beta * v.z)))
```

and, at the end of the expansion block, the tangent's step:

```
  let v.k1.x = sigma * (v.y - v.x)
  let v.k1.y = fma(v.x, rho - z, fma(x, -v.z, -v.y))
  let v.k1.z = fma(v.x, y, fma(x, v.y, -(beta * v.z)))
  let v.Y2.x = fma(h/2, v.k1.x, v.x)
  let v.Y2.y = fma(h/2, v.k1.y, v.y)
  let v.Y2.z = fma(h/2, v.k1.z, v.z)
  let v.k2.x = sigma * (v.Y2.y - v.Y2.x)
  let v.k2.y = fma(v.Y2.x, rho - Y2.z, fma(Y2.x, -v.Y2.z, -v.Y2.y))
  let v.k2.z = fma(v.Y2.x, Y2.y, fma(Y2.x, v.Y2.y, -(beta * v.Y2.z)))
  let v.Y3.x = fma(h/2, v.k2.x, v.x)
  let v.Y3.y = fma(h/2, v.k2.y, v.y)
  let v.Y3.z = fma(h/2, v.k2.z, v.z)
  let v.k3.x = sigma * (v.Y3.y - v.Y3.x)
  let v.k3.y = fma(v.Y3.x, rho - Y3.z, fma(Y3.x, -v.Y3.z, -v.Y3.y))
  let v.k3.z = fma(v.Y3.x, Y3.y, fma(Y3.x, v.Y3.y, -(beta * v.Y3.z)))
  let v.Y4.x = fma(h, v.k3.x, v.x)
  let v.Y4.y = fma(h, v.k3.y, v.y)
  let v.Y4.z = fma(h, v.k3.z, v.z)
  let v.k4.x = sigma * (v.Y4.y - v.Y4.x)
  let v.k4.y = fma(v.Y4.x, rho - Y4.z, fma(Y4.x, -v.Y4.z, -v.Y4.y))
  let v.k4.z = fma(v.Y4.x, Y4.y, fma(Y4.x, v.Y4.y, -(beta * v.Y4.z)))
  let v.S2.x = fma(2, v.k2.x, v.k1.x)
  let v.S2.y = fma(2, v.k2.y, v.k1.y)
  let v.S2.z = fma(2, v.k2.z, v.k1.z)
  let v.S3.x = fma(2, v.k3.x, v.S2.x)
  let v.S3.y = fma(2, v.k3.y, v.S2.y)
  let v.S3.z = fma(2, v.k3.z, v.S2.z)
  let v.S4.x = v.S3.x + v.k4.x
  let v.S4.y = v.S3.y + v.k4.y
  let v.S4.z = v.S3.z + v.k4.z
  next v.x = fma(h/6, v.S4.x, v.x)
  next v.y = fma(h/6, v.S4.y, v.y)
  next v.z = fma(h/6, v.S4.z, v.z)
```

A writer holds the tangent equations against the textbook's: dδx/dt =
σ(δy − δx), dδy/dt = (ρ − z)δx − xδz − δy, dδz/dt = yδx + xδy − βδz.
The mathematical form adds the variational equations after the state's:

```
the variational equations of the tangent vector v
  d(v.x)/dt = σ·(v.y − v.x)
  d(v.y)/dt = v.x·(ρ − z) + x·(−v.z) − v.y
  d(v.z)/dt = v.x·y + x·v.y − β·v.z
```

and the tangent's step after the scheme:

```
the tangent v's step: the same method on δY, with Df·δY the right-hand sides of v above
  δY = (v.x, v.y, v.z)
  δk1 = Df(Y)·δY
  δk2 = Df(Y + (h/2)·k1)·(δY + (h/2)·δk1)
  δk3 = Df(Y + (h/2)·k2)·(δY + (h/2)·δk2)
  δk4 = Df(Y + h·k3)·(δY + h·δk3)
  δY ↦ δY + (h/6)·(δk1 + 2·δk2 + 2·δk3 + δk4)
```

The gate holds each of these blocks to the renderers' output.

### What the gate holds, and what it cannot see

The intention-out's checks extend to a variational system, each line it
prints read by one of them (VL1's lesson: a printed line no check reads
is a defect in the sentence that says everything is checked):
1. **The round trip** reads the tangent's code - the declaration, the
   tangent equations and lets, the block's tangent lines - back through
   the derivation (`tangent-mismatch`), so the same graph comes back,
   and the same text: it holds the tangent's rounding order, byte for
   byte.
2. **Exact evaluation** holds the variational equations, a map's tangent
   lines and each tangent step's scheme to the tangent sections
   evaluated exactly, at random rational states and tangents
   (`python/tests/lang_mathform.py` reads `d(v.x)/dt`, `Df(Z)·W` and δ).
3. **Every line read**: the operation counts against the test's own;
   the section headers word for word; each tangent component's and
   tangent let's name against Unicode's Greek; δY, δQ and δP; each
   tangent scheme word for word against the test's own copy.
4. **The derivative is right.** The tangent sections, evaluated exactly,
   must EQUAL the test's own derivative of the primal sections: dual
   numbers in exact rationals, (value, derivative) pairs carried through
   every node, the conventions at measure-zero points written again
   from the rule table above. The points are random rationals, about
   half of them placed (one component set equal to another, or to
   zero), and the ties and zeros the conventions decide, placed with
   operands equal in value and different in tangent: min, max, minnum
   and maxnum of x and z at x = z with v.x different from v.z, alone
   and inside expressions, and abs and copysign's two sources at
   x - z. There the check also asserts that a tie given its second
   operand's tangent, or a zero's sign taken as -, gives another
   answer, so that a convention other than the table's fails it
   (measured: each, planted, red on the test and on the stage). So the
   printed variational equations are the derivative of the printed
   equations, and not merely what the graph says.

**Why exact dual numbers, not mpmath.** Every operation is piecewise
polynomial, so the exact derivative exists, and equality needs no
tolerance to argue about; a central difference in mpmath would carry
one, and a dependency besides. The plan of record said "an exact
derivative in mpmath"; exact rationals are stronger, and the stage stays
stdlib-only.

**What the fourth check cannot see**, and what holds it instead:
- **rounding order**: a rule replaced by one equal in exact arithmetic
  and rounded otherwise - `da*b + a*db` for `fma(da, b, a * db)` - is
  invisible to exact evaluation (measured: it passed every point). It is
  held by the committed compiled variational references' graph bytes
  (`programs/systems/compiled-tangent/`), by this document's rule table
  held to the code - each rule rendered on a one-operation system - and
  by the blocks above, held to the renderers;
- **special values**: NaNs, infinities and the sign of zero do not exist
  in exact arithmetic. They are held by the interpreter against seq.py
  bit for bit, with tangents holding signalling NaNs, infinities, -0 and
  subnormals, and by unit tests of each rule's specials;
- **a convention at a measure-zero point** that differs from the table:
  only at a point placed on one whose operands differ in tangent - at a
  tie of two operands with the same tangent, or a zero whose tangent is
  zero, every convention gives the same answer. The gate places such
  points for the min family's ties and for abs's and copysign's zeros
  (check 4); a tie or a zero anywhere else, such as a select whose
  comparison flips, is seen only where a placed point falls on it. The
  conventions themselves are held bit for bit by the unit tests of each
  rule's measure-zero values and specials, and by the rule table's
  text, which the rules are rendered against - all but one: copysign's
  sign source at -0 or a NaN, which no unit test places, is held by the
  rule table's text alone (verifier-VL3).

**The Lyapunov smoke test** (the `tangent` stage): Lorenz-63's largest
exponent, from `lorenz63-rk4-tangent-fp64.cftl` compiled, run on
libcft's software backend through cft-segrun one segment at a time, the
tangent scaled on the host between segments by an exact power of two.
The run length and tolerance were set from a measurement, and the stage
prints its figure each time (docs/VERIFICATION.md gives them). Such a run
is not certified as a chain: the host changes each segment's scratch-out
before the next. But an exact power-of-two scaling is invisible to the
arithmetic - every rule is linear in the tangents, and rounding commutes
with exact scaling away from overflow and underflow - so the renormalised
tangent is the unrenormalised one times 2^-K, bit for bit (measured, and
held by the stage). Within the format's range, a certified chain with
no renormalisation therefore gives the same exponent: at fp256 the
stage certifies one, both auditors accepting.

### Known limits

- **A long chain of unnamed operations** makes each one's tangent
  write its unnamed operands again wherever its rule reads an operand
  (a product, fma, abs, copysign, the min family), so the tangent
  grows with the square of the chain's length: 5,049 tangent nodes
  for an unnamed 100-term product, against 198 if read across, and
  8,099 for an unnamed min chain of 90 terms (measured, the second by
  verifier-VL3). A sum chain stays linear, and so does a chain through
  a select's condition, which takes no tangent (198 nodes at 100
  terms, verifier-VI2). Naming parts of the chain with lets keeps it
  linear, since a let is read by name. From 102 terms an unnamed
  product's tangent would print past the parser's 100 levels - from
  101 under euler and stormer-verlet, whose step writes the field one
  level deeper - and the source is refused `too-deep` (D2); lets keep
  it within reach as well.
- **The compiler's choice between its orders reads no capacity.** It
  takes the fewest instructions a step, then the fewest one-beat cycles;
  the interleaved walk, offered only for a graph with tangents, wins for
  Lorenz-96 with one vector (2,509 instructions and 139 slots, against
  2,568 and 389), but for two, three or four vectors at N = 40 the six
  older orders' fewer instructions win at more scratch (5,288
  instructions and 490 slots, against 6,286 and 300, at T = 3). At
  T = 2 the chosen order takes 450 slots (3,934 instructions a step),
  so Lorenz-96 at N = 40 with two vectors is refused `scratch-capacity`
  on every 256-slot target (verifier-VL3, measured). Choosing by the
  target's capacity would make the image depend on the target, which
  the compiler's design rules out (python/cftc).
- **Capacity.** Lorenz-96 with one tangent vector needs 2N + 59 slots a
  lane from N = 14 (measured). Just below that the count departs from
  it by a slot or a few either way: N = 9 takes 78, an older order's;
  N = 10 takes 75 and N = 12 takes 84, the interleaved walk's. The
  smallest rings take far fewer: N = 4 takes 21 (against 67) and N = 7
  takes 63 (against 73) (verifier-VI2, verifier-VL3).
  N = 40 takes 139 and fits every target;
  a 256-slot target holds it up to N = 98 (255 slots) and refuses it
  (`scratch-capacity`) from N = 99 (257); the U50's revision 7 (2,048)
  accepts N = 100 (259).

## Every refusal, by name

One exception, `lang.Refusal`, carries:
- the name;
- the source and its line (None for a refusal about the file, the run or
  the bytes as a whole);
- a sentence.

Nothing else escapes the parser or the checker, and the gate fuzzes the
references to hold that. `python/cft_golden/lang/refusals.py` is the one
list: the checker's and the interpreter's names, each made by a test in
this definition's gate, and the compiler's seven at the end, reserved
for it. The compiler raises them through the same class, and its own
gate makes each one.

The text and its declarations:

| name | what it refuses |
|---|---|
| `character` | a byte or character the text does not hold: not UTF-8; a line end other than LF or CR LF, or a NUL or Ctrl-Z, anywhere; outside a comment, anything but printable ASCII, space and tab |
| `syntax` | text that is not a statement of the language |
| `too-deep` | parentheses nested more than 100 deep, in the source or in the canonical form it would have (its own parentheses, as the parser counts them); or a system the checker cannot evaluate from a caller whose own stack is already deep (Python's recursion limit) - never a chain, which may be any length |
| `constant-range` | a constant whose exact value lies beyond 2^+-1048576 |
| `missing-system` | no `system` line |
| `missing-format` | no `format` line |
| `missing-state` | no `state` line |
| `missing-step` | no `step` line |
| `duplicate-declaration` | system, format, round, step or an expansion block declared twice |
| `unknown-format` | a format other than fp32, fp64, fp128 and fp256 |
| `unknown-rounding` | an attribute other than rne, rtz, rdn, rup and rmm |
| `unknown-integrator` | an integrator other than rk4, euler, stormer-verlet and map |
| `duplicate-name` | a name declared twice |
| `reserved-name` | a reserved word used to name a value |
| `undefined-name` | a name used and never declared |
| `array-length` | an array whose length is not written as a whole number from 1 to 32,768 |
| `lane-capacity` | a lane of more than 32,768 values (its state, its tangent vectors and its lane params), the deepest scratch any tile publishes |
| `unused` | a const, param, lane param, let or h that nothing uses; h is used only where a constant of the step scales with it, so a map whose every use of h folds away is `unused` |
| `cycle` | a definition that depends on itself |
| `not-constant` | a value needed when the program is compiled that reads the state, a param, a lane param or a let |
| `bank-capacity` | more than 512 params and constants: the bank holds 512 on every device |

Equations, indices and the step:

| name | what it refuses |
|---|---|
| `missing-equation` | a state component with no equation |
| `duplicate-equation` | a state component with two equations |
| `mixed-equations` | a system with both d/dt and next equations |
| `not-state` | an equation whose target is not a state component |
| `integrator-mismatch` | a flow's integrator on a map, map on a flow, or an expansion block on a map |
| `index-range` | an index outside a non-cyclic array, an undefined let component, or an empty range |
| `index-not-integer` | an index that is not integer arithmetic on literals and the statement's index variable |
| `array-index` | a scalar indexed, or an array named without its index |
| `unbound-index` | an index variable bound by nothing |
| `missing-step-size` | rk4, euler or stormer-verlet without h |
| `step-size-zero` | an h whose exact value is zero |
| `h-nonlinear` | a constant in which h appears other than as a rational multiple of it |
| `h-scope` | h read by a flow's equations or by a default |
| `step-option` | an option the integrator does not take |
| `verlet-partition` | q and p that do not split the state, each component in exactly one |
| `verlet-not-separable` | a position's right-hand side reading a position, or a momentum's a momentum |
| `expansion-mismatch` | a written-out step that is not the integrator's expansion |

The variational equations:

| name | what it refuses |
|---|---|
| `tangent-mismatch` | a written tangent equation, tangent let or expansion line that is not the derivation's |
| `tangent-scope` | a name in a tangent vector read by the state's equations, lets or constants, or by another tangent vector's equations; or a tangent vector read whole |

Operations v1 does not have:

| name | what it refuses |
|---|---|
| `runtime-division` | a division with an operand that is not a constant |
| `runtime-sqrt` | a square root at run time |
| `transcendental` | a transcendental function at run time |
| `irrational-constant` | a square root or transcendental of a constant |
| `power` | `^` or `**` |
| `not-equal` | `!=` |
| `chained-comparison` | a comparison of a comparison, unparenthesised |
| `time-dependence` | `t` used in an equation and declared nowhere |
| `unknown-function` | a call of a name that is not a built-in |
| `arity` | a built-in given the wrong number of arguments |

The values a rational cannot carry, and the one rounding:

| name | what it refuses |
|---|---|
| `constant-negative-zero` | a minus written on a zero literal (`-0`, `-0.0`, `-(0)`) |
| `constant-infinity` | `inf` or `infinity` |
| `constant-nan` | `nan` or `snan` |
| `constant-division-by-zero` | a constant divided by a constant zero |
| `constant-overflow` | a constant whose one rounding overflows |
| `constant-rounds-to-zero` | a nonzero constant whose one rounding is zero |

A run, and a step graph's bytes:

| name | what it refuses |
|---|---|
| `lane-shape` | a lane with the wrong number of values |
| `lane-value` | a lane value that does not fit the format |
| `unknown-param` | a run value for a name that is not a param, or an h for a system without one |
| `param-value` | a run value that is not an exact rational (a float, or text that is not a constant), an encoding that does not fit, or a param given both ways |
| `step-count` | a step count that is not a whole number of at least 0 |
| `step-size-sign` | a run's h of the other sign from the graph's: a constant may hold h's sign, fixed when the graph was compiled |
| `graph-format` | bytes that are not a step graph of version 1 (or 2, with tangent vectors) |

The compiler's, reserved for it (L2).
- The first five are a target's stated capacities (the plan's item 10).
  They depend on the lowering and on the device, so the compiler raises
  them. The bank's 512 is the same on every device, and the checker
  raises that one itself as `bank-capacity`.
- The last two are the compiled image's own.

The checker never raises any of the seven. The sentences below are their
form; the compiler words each one for the case at hand.

| name | what it refuses | its sentence |
|---|---|---|
| `scratch-capacity` | registers plus scratch past the target's: 2,048 slots on the U50's revision 7, 256 elsewhere | "this step keeps more values a lane than the target's registers and scratch slots hold" |
| `program-capacity` | more instructions than the target's image holds | "this step lowers to more instructions than the target's image holds" |
| `loader-bound` | more than 2^40 worst-case instructions, the loader's bound on every device | "this segment's worst case is past 2^40 instructions, the loader's bound on every device" |
| `target-format` | a format the target does not carry | "this format is not one the target carries" |
| `target-feature` | a feature whose CAPS bit the target does not publish | "this image needs a feature the target's CAPS bits do not publish" |
| `segment-steps` | a step count outside 1 to 2^32-1, the range of the REPEAT immediate a segment's steps are | "a segment is one REPEAT of 1 to 4,294,967,295 steps; this count is not one" |
| `halving-underflow` | an h-scaled constant whose exact halving underflows, so the step-halving bank cannot hold it exactly | "this h-scaled constant underflows when halved, so the step-halving bank would not be this bank halved exactly" |

## The gate

The five files run in the golden stage (`pytest python/tests`) and
under `make golden`, with no change to either.

**`python/tests/test_lang_refs.py`: the interpreter against seq.py.**
- **The comparison.** For each reference at fp64 and fp256:
  - the committed `.cfta` is assembled by asm.py, and its bytes are held
    to `programs/MANIFEST`;
  - its REPEAT is patched to 1, 2, 5 and its own count;
  - seq.py runs it on the committed classic bank;
  - every lane's state and the run's FLAGS must equal the interpreter's
    at every count.
- **The lanes.** Random full-significand lanes, plus one that overflows,
  one holding a signaling NaN, and one holding subnormals. Each is
  asserted to raise what it is there for. Lorenz-96 at F = 8 does not
  underflow even from all-subnormal state, measured; at F = 0 it does,
  and a run value is held to seq.py on that bank.
- **The halved step.** It is the bank with each h-scaled slot halved
  exactly.
- **Four plants.** Each is a wrong semantics built by the test as a
  modified copy of Lorenz-63's step graph, run by the shipped
  interpreter, and each must disagree with seq.py at some count the
  gate compares at (a lane can differ at one count and agree again at a
  later one, so no single count is the test):
  - a reassociated rk4 sum;
  - a contraction (a*b + c made one fma);
  - the contraction undone, verifier-P1's plant;
  - every constant rounded through a narrower format.

**`python/tests/test_lang.py`: the definition.**
- the references and their node counts against the images;
- each bank slot against the once-rounded rule;
- the fp32 statement;
- negation and unary minus under the directed attributes;
- every refusal, by name and line;
- the mutation fuzz;
- verifier-VL1's cases: constants through a power of h exact, with no
  float able to reach one; constants of thousands of digits; runs of
  minuses; non-canonical graphs refused; the bounds on arrays, ranges
  and lanes; run values as text;
- its re-check's: the character rule, each character in a comment and
  between tokens, from a str and from bytes, with every committed
  `.cftl` held to it; a run's h of the graph's sign equal to the
  system compiled at that h, and of the other sign refused; a long
  constant named in a sentence to five digits, written out in time
  linear in its size, and read back by the test's reader past 4,300
  digits;
- determinism across hash seeds;
- the intention-out's three checks, each integrator's scheme word for
  word and the unused fifth stage planted;
- this document's refusal tables, template text and Lorenz-63 blocks
  against the code.

**`python/tests/test_lang_tangent.py`: the variational equations.**
- each rule of the table above, rendered on a one-operation system for
  every pattern of zero tangents, against the table's text; the
  measure-zero values (a tie, ±0, a NaN result) and a product by ±1 at
  the specials, bit for bit;
- the fourth check - the tangent evaluated exactly against the test's
  own dual numbers - on the references with tangent vectors and on
  generated systems that cover every operation, at random points,
  about half of them placed, and at ties and zeros placed where a
  convention decides (operands equal in value, different in tangent),
  where the other conventions are asserted to give another answer;
  three plants, each red on it: a wrong product rule, a dropped tangent
  term, a tangent reading the wrong primal value; the
  rounding-order plant `da*b + a*db`, green on it and red on the
  committed bytes and the rule table;
- construction A against B: equal exactly at sampled points on every
  flow, node for node after sharing where no tangent is identically
  zero, and parting, in bits, at `d/dt t = 1`;
- the primal unchanged: the primal sections byte for byte (const refs
  mapped where a rule adds a constant), and a run's states and
  `primal_flags` the run without tangents';
- every version-1 graph unchanged: the six references' bytes are the
  committed compiled `.graph.json` files';
- the interpreter's tangents, their refusals, T = 1 and 2, maps,
  stormer-verlet, euler, lets and lane params;
- writing the tangent out: accepted where it is the derivation's,
  `tangent-mismatch` at the first difference, `tangent-scope`, all or
  none; the intention-out's four checks on references, written
  systems and random ones, and plants of the tangent's printed lines;
- determinism across hash seeds; this document's variational blocks and
  sources against the renderers and the committed files.

**`python/tests/test_lang_readback.py`: every accepted source reads
back** (parcel D2, 2026-10-01).
- a map whose every use of h folds away, in each form the challenge
  suite and D2 found, refused `unused` at the step line, the uses that
  folded named by line with their values; the controls accepted and
  read back;
- a source whose canonical form would nest past 100 - a negation
  used as a multiplicand, the tangent of an unnamed product or of a
  min chain, euler's and stormer-verlet's step around an inline
  right-hand side - refused `too-deep` at its line, naming the depth;
  each boundary's accepted neighbour read back;
- chains of lets of any length - under every integrator, with and
  without tangents, and through calls, at the old boundaries and far
  past them - accepted and read back; a cycle of any length refused
  `cycle`; the evaluation of a definition met deep held to the
  recursion itself, run with no limit in reach, and at a budget
  forced to 3 frames;
- the measure of nesting (lang/nesting.py) equal, line by line, to
  the test's own count of what render_canonical writes, and the depth
  rule refusing exactly the sources whose canonical form would not
  read back; neither rule a read-back;
- the challenge suite's four investigation sources, verbatim; the
  restated `h-nonlinear` and `h-scope` sentences on the inputs that
  made the old ones false.

**`python/tests/test_lang_time.py`: time** (parcel T1, 2026-10-02).
Every figure of "Time", computed by the interpreter through the
templates and compared, its tables parsed and its sentences matched, so
that the section and the measurement cannot part:
- t a name, `time-dependence` its refusal, and what each template makes
  of `d/dt t = 1`, from the canonical form;
- h = 1/64 exact at every step to 10^4, and at fp64 under the other
  attributes, with rk4's directed figures and h = 3/64;
- the drift table, rk4 against euler at every step, fp128 against fp64
  at every step and at h = 1/99 and 1/19, the directed attributes;
- the counter: the `h-scope` refusals, an exact count at every step,
  the directed attributes after one step, the limit for each placement
  started two below it, at fp32 and fp64, with rk4's stage counts, a
  step-halving run;
- t from the counter: one rounding, exact at every 25th count, and each
  stage's count and time inside rk4 and the midpoint under
  stormer-verlet, read from the step graph's labelled nodes by an
  evaluator held to lang.run; the exact residual in a map and in a
  flow, under each attribute, and past 10^4: dt's relative error and a
  seeded sample of counts, each a lane;
- forcing: sin refused; the rotation's table, and its rounding's share
  against the same step evaluated exactly; rk4's and euler's exact
  factors and stormer-verlet's quadratic form; the phase; w = 3/10; the
  forced oscillator against its exact solution and against a twin
  forced by the exact cos t; every source the section shows, compiled.

It takes about 50 s on one core of the desktop, nearly all of it the
interpreter's own arithmetic.

The compiled images are held to the interpreter by the `tangent` stage
(`programs/tangent_check.py`; docs/VERIFICATION.md).

## What v1 does not do

- **The compiler** is not this definition: it is `python/cftc` (L2),
  with the lowering, allocation and spilling, scheduling, emission,
  the manifest, the halved-bank file, and the target-dependent
  refusals above.
- **Of the variational equations** (L3): whole Jacobians as a construct
  (a system has the tangent vectors it declares, and nothing builds an
  n by n matrix); Lyapunov spectra beyond the largest exponent, and QR
  on the tile or the host; certified renormalisation; tangents with
  respect to params or lane params; reverse mode, second derivatives;
  a tangent the state reads.
- **Run-time division and square root.** Inlining divfull or sqrtfull
  means spilling the registers around it, which is a later parcel.
- **Run-time transcendentals.** The correctly rounded math library is a
  later step.
- **A built-in time, adaptive steps and events.** There is no reserved
  `t`: a system carries time in its state or counts its steps, and sin
  and cos of t wait for the math library ("Time").
- **Per-operation attributes.** v1 has one attribute a program.
- **User-defined integrators**, beyond rk4, euler, stormer-verlet and
  map.
- **Two-dimensional arrays.**
- **A Python front end.** If one follows, it refuses a Python float as a
  constant by name, since Python's 0.01 is binary64 already.
- **A LaTeX rendering of the intention-out.**
