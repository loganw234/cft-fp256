# The language

A small text language for dynamical systems - ordinary differential
equations and maps - whose every rounding is fixed by the text. A
system file declares a format and a rounding attribute, its state,
constants and parameters, its equations, and an integrator from a
library of three; the step it denotes is checked into a **step graph**,
and the step graph is what a run computes, bit for bit.

This document is the language's definition. Its executable form is
`python/cft_golden/lang/`, in the golden model, which is the authority:
a parser, a checker, the exact constants, the step graph, and a
reference interpreter that is the definition of correct for every
compiled image. The compiler that turns a step graph into a tile image
is the step-3 plan's parcel L2 and does not exist yet; ROADMAP.md's
"Step 3: the language and its compiler (plan of record, 2026-10-01)" is
the plan, and this is its parcel L1.

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
- Parentheses and brackets nest at most 100 deep (`too-deep`). A chain
  such as `a + b + c`, an index such as `x[i + 1 + 1 ...]`, and a run of
  minuses may be any length: the checker and the renderers walk them in
  loops. What is left to recurse, deep nesting and long chains of lets,
  is held to Python's own recursion limit, which the package keeps
  rather than raises, and past it the refusal is `too-deep` too.
- A name is a letter or `_` followed by letters, digits and `_`, and
  names are case-sensitive: `Y` and `y` are two names.
- A dotted name such as `k1.x` or `Y2.x[3]` is a **label**: it names a
  node of an expanded step, and is defined only inside an `expansion`
  block (see "The step").
- Keywords: `system format round state cyclic const param lane let next
  step for in expansion end`, and `d/dt`, which is one token where a
  statement starts.
- Reserved: no value may be named after one of these, and the check is
  `reserved-name`.
  - the keywords;
  - the built-ins `fma abs min max minnum maxnum copysign select`;
  - `sqrt` and the transcendental names (`exp`, `log`, `sin`, `pow`,
    `hypot` and the rest of the list in `python/cft_golden/lang/check.py`);
  - `h`, the step's own name;
  - `inf infinity nan snan`.

### Statements

```
file       = { [ statement ] [ ";" comment ] NEWLINE }
statement  = "system" NAME
           | "format" ( "fp32" | "fp64" | "fp128" | "fp256" )
           | "round" ( "rne" | "rtz" | "rdn" | "rup" | "rmm" )      ; absent: rne
           | "state" svar { "," svar }
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
- A lane holds its state and its lane params, at most 32,768 values in
  all (`lane-capacity`). A range covers at most 32,768 indices
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
  dropped operation's flags were part of the answer.

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
| `t`, declared nowhere | `time-dependence` | carry time in the state: `state t`, `d/dt t = 1` |
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
- A flow's equations and their lets cannot read h, nor a const whose
  value changes with h's size (`h-scope`): a step-halving run halves h,
  and such a right-hand side would move with it. A const whose value
  does not change with h's size is a plain rational wherever it is
  used, however it was written: `const c = h/h` is 1, and
  `copysign(1, h)` and `abs(h)/h` are h's sign, 1 or -1.
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
it needs.

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

## The step graph

The checked form of one step. The checker builds it; the interpreter,
the renderers and the compiler read it. `python/cft_golden/lang/graph.py`
holds it, as canonical JSON, version 1.

| key | content |
|---|---|
| `cftl_graph` | 1 |
| `system`, `format`, `round` | the name, the format, the one attribute |
| `state` | [[name, length or null]], declaration order. The flat component order s0, s1, ... is this order with an array's components by index: the lane layout |
| `lane` | [[name, default exact or null, encoding or null]] |
| `param` | [[name, default exact, encoding, flags]] |
| `integrator` | [name, h exact or null, options or null]; options are {"q": [...], "p": [...]} for stormer-verlet |
| `const` | [[exact, h-factor or null, encoding, flags]]: one entry per distinct (exact value, h-factor). The h-scaled come first by factor descending, then the rest by value ascending |
| `field` | a flow's right-hand sides once, over the state inputs: {"out": [ref], "nodes": [node]}. null for a map |
| `step` | one step with the template expanded: {"out", "nodes"}. What the interpreter runs and the compiler compiles |

**Nodes and refs.**
- A node is `[op, [ref, ...], label or null]`.
- A ref is `sN` (a state input), `lN` (a lane param), `pN` (a param),
  `cN` (a const) or `nN` (an earlier node of the same section).
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
               at=())              # step counts at which to record (states, FLAGS)
run.states    # one list a lane: the state's encodings after `steps` steps
run.flags     # the five IEEE flags, a sticky OR over every node, lane and step
run.at        # {s: (states, flags)}
```

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
   expect fails, so nothing printed goes unread. The test's tables are
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
     held against Unicode's own Greek letters. The expressions, and the
     scheme's own lines, are the second check's, which holds them at the
     points it samples: a select's arm, or the operand a min or max
     discards, only at points that take it.
   - The check is held itself: a test plants a wrong sha256 digit,
     attribute, format, title, h-scaled list, lane default and its
     encoding, a comment on an equation, a lane param's and a let's
     glyph and the integrator's name, and each must be caught. Before
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
| `too-deep` | parentheses nested more than 100 deep, or an expression or a chain of lets deeper than the checker evaluates |
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
| `lane-capacity` | a lane of more than 32,768 values (its state and lane params), the deepest scratch any tile publishes |
| `unused` | a const, param, lane param, let or h that nothing uses |
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
| `graph-format` | bytes that are not a version-1 step graph |

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

Both files run in the golden stage (`pytest python/tests`) and under
`make golden`, with no change to either.

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
- the intention-out's three checks;
- this document's refusal tables, template text and Lorenz-63 blocks
  against the code.

## What v1 does not do

- **The compiler** is L2's: lowering, allocation and spilling,
  scheduling, emission, the manifest, the halved-bank file, and the
  target-dependent refusals above.
- **The variational equations** are L3's.
- **Run-time division and square root.** Inlining divfull or sqrtfull
  means spilling the registers around it, which is a later parcel.
- **Run-time transcendentals.** The correctly rounded math library is a
  later step.
- **Explicit time, adaptive steps and events.**
- **Per-operation attributes.** v1 has one attribute a program.
- **User-defined integrators**, beyond rk4, euler, stormer-verlet and
  map.
- **Two-dimensional arrays.**
- **A Python front end.** If one follows, it refuses a Python float as a
  constant by name, since Python's 0.01 is binary64 already.
- **A LaTeX rendering of the intention-out.**
