# The four format sites: binary32.com, binary64.com, binary128.com, binary256.com

A layout plan, written 2026-09-14, before anything was built. **Built
the same day**: the sites live in
[loganw234/binary-sites](https://github.com/loganw234/binary-sites), one
tree that generates all four, with the module pinned by hash to this
repository's committed conformance page. What is built follows this
plan; where the two differ, the repository is the record and this file
is the argument. The four
domains are the names of the IEEE 754 binary interchange formats, and
the brief is that each site teaches its format first, points at the
software that serves that format best, and carries this project as one
thread across all four: the same operation gives the same bits at every
rung, wherever it runs. The project is never the hero. The format is.

What follows is the shape the sites should share, what each of the four
carries that the others do not, which pieces of this repository they can
reuse without writing new arithmetic, how the project appears on a page
that is deliberately not about it, and how four custom domains are
served from GitHub Pages. Every number quoted has a run behind it in
docs/VALIDATION.md, docs/BENCHMARKS.md or cft-rebound's own record.

---

## The brief, restated as rules

1. **A reader who searched the format's name gets the format.** The
   first screen of binary64.com explains binary64. The project's name
   does not appear above the fold, in the `<title>`, or as the site's
   colour.
2. **Every site is the same page with a different filling.** Same nine
   sections, same order, same widgets. A reader who has read one knows
   where everything is on the others, which is what makes the four a
   family rather than four sites that link to each other.
3. **The software table is honest by construction.** At binary32 and
   binary64 the row for this project says a CPU wins on throughput and
   the row exists for the contract. The README already says this; the
   sites say it in the same words.
4. **The determinism thread is one section, in the same place on every
   site, with format-specific evidence.** Not a banner, not a sidebar
   that follows the reader.
5. **Interactive parts compute, they do not illustrate.** Every widget
   runs the real library in the tab - the wasm module the conformance
   page already embeds - so a number a reader sees is the contract's
   number, not a JavaScript approximation of it. That is the one
   advantage these sites have over every other floating-point explainer,
   and it costs nothing: the module exists, is committed, and is
   byte-reproducible.

---

## One template, four fillings

The page every site follows, top to bottom. The left column is the
section; the right is the widget that runs there and the wasm export
it calls, so the shared component library is sized before anything is
written.

| # | section | what it says | widget (shared) |
|---|---|---|---|
| 1 | **The format** | the name and its aliases (`float`, `f32`, `REAL*4`, `np.float32` ...), one sentence of identity, the bit bar drawn to scale with a live number in it | `bitbar`: sign, exponent, fraction fields at true bit widths; the ladder nav is four of these |
| 2 | **Anatomy** | fields, bias, p, emax, subnormals, the two zeros, the infinities, quiet and signaling NaN; the parameter row from docs/DETERMINISM.md | `inspector`: type a decimal or hex, or click bits; shows the exact decimal value to every digit (`cftw_to_decimal_char`, unbounded H), the class (`cftw_class`), nextUp and nextDown, the ulp |
| 3 | **What it can hold** | decimal digits, the exact-integer cliff, the range, the smallest subnormal, and a spacing chart: ulp against magnitude, log-log | `ruler`: a number line you drag along, spacing drawn to scale; the integer cliff marked |
| 4 | **Where it lives** | hardware: which processors have it natively, at what rate; languages: how each spells it, and which lack it | a static table per site; the one part with no shared widget, because it is the part that differs most |
| 5 | **Where it breaks** | the format's own failure gallery, each case runnable | `case`: a fixed expression evaluated live under the contract, with the flags it raised, beside the reader's own browser's answer where the browser has the format |
| 6 | **Rounding and flags** | the five attributes and the five flags, on one operation | `attrs`: one op, five rows, one per attribute (`cftw_run` with the mode), flags decoded per row |
| 7 | **Tools and libraries** | the curated list: what to reach for at this format, ranked, with the reason | static; one row is this project, honest per rule 3 |
| 8 | **Same bits everywhere** | what legally differs between implementations at this format, and the contract that removes the difference; the live replay | `replay`: `cftw_conformance` over the embedded sample filtered to this format, with the drop zone for the full sets; the format's canonical checksum from docs/COMPATIBILITY.md |
| 9 | **Up and down the ladder** | when to step wider, when narrower, with the measured evidence, linking the neighbours; the reading list | the ladder nav again, and `travel` (below) |

Sections 1, 2, 3, 6 and 8 are the same code on all four sites,
parameterised by format. Sections 4, 5, 7 and 9 are where the writing
lives. Section 5's cases and section 9's evidence are the two places a
site earns its domain.

### The ladder nav, and the value that travels with the reader

The strip across the top of every page is the four bit bars at their
true proportions - 32 : 64 : 128 : 256 - with the current site's bar
highlighted. That is the cross-link, and it doubles as the family's
identity: no logo, no wordmark, the ladder itself.

It carries one thing across sites: the number the reader has in the
inspector. The link to a neighbour appends the current encoding as a URL
fragment (`#x=3fb999999999999a`), and the destination's inspector opens
on that value converted to its own format - widening exact, narrowing by
one rounding, which is `cftw_convert` and the standard's 5.4.2, on the
destination page's own module. Arriving on binary128.com from
binary64.com with 0.1 shows the reader that their binary64 0.1 is
exactly

    0.1000000000000000055511151231257827021181583404541015625

and that binary128's nearest 0.1 is a different number, to 34 digits.
That is the whole family's thesis in one page load, and it is only
possible because the character conversions are exact at every digit
count.

---

## The four fillings

What differs, site by site. Each gets a hue of its own (the ladder nav
shows all four), a signature interactive that the other three do not
have, and its own answer to the two questions a reader brings: *where
does this format go wrong* and *what should I use for it*.

### binary32.com - the format of the GPU

| | |
|---|---|
| aliases | single precision, `float`, `f32`, `REAL*4`, `np.float32`, `Float32Array` (JavaScript has no scalar binary32) |
| parameters | w 8, t 23, p 24, emax 127; 7.22 decimal digits; every integer to 2^24 = 16,777,216; largest 3.40e38; smallest subnormal 2^-149 |
| where it lives | every CPU since the 1980s, every GPU at full rate, every shader language, most DSPs; on the tile, 8 lanes per beat - and the tile **loses**: one tile is 1.6x behind an x86-64 workstation and 7.2x behind an M2 Pro, four tiles pass the workstation and still lose to the laptop (docs/BENCHMARKS.md) |
| where it breaks | 16,777,217 does not exist; 0.1 + 0.2; catastrophic cancellation in the textbook quadratic formula; the floating-origin problem in games (a position 10 km from the origin has a resolution of about a millimetre); accumulating 0.1 ten million times; FMA contraction changing a result between two compilers of the same source; two GPU vendors disagreeing in the last bit and then diverging |
| signature interactive | the **exactness census**: the Collatz workload at binary32, where the inexact flag is a per-element certificate and the format loses 87 of 100,000 trajectories to exactness while binary64 loses none (docs/COLLATZ.md, already ported to the browser in `demos_core.js`). A cliff you can watch the numbers fall off |
| tools and libraries | the compiler's own switches, and what each costs: `-ffp-contract`, `-ffast-math`, `/fp:strict`; SIMD intrinsics; the GPU APIs; CORE-MATH's correctly rounded binary32 functions, several of which have since been merged into glibc; Herbie for rewriting an expression to lose less; this library, for the contract |
| same bits everywhere | this is the format where cross-vendor divergence is famous, and the format where the project's proven case lives: atlas-engine's geometry library producing **one hash across NVIDIA, AMD and Intel GPUs**. The contract's answer is one exact result per operation, scored on 8 lanes per beat on the tile and on a **16 MHz ATmega328P** with 2 KB of RAM (`CFT_TINY`, docs/EMBEDDED.md): the same library, compiled small, replays the published binary32 and binary64 families - 508,000 cases on the ESP32 - and disagrees on none. "Runs on an Arduino Uno" is the sentence this site gets to say |
| up the ladder | past seven digits, past 16.7 million as an integer, or when a sum runs long: binary64, one click right |

### binary64.com - the format of science, and of JavaScript

| | |
|---|---|
| aliases | double precision, `double`, `f64`, `REAL*8`, JavaScript's `Number`, Python's `float`, `np.float64`, the default of MATLAB, R and Julia |
| parameters | w 11, t 52, p 53, emax 1023; 15.95 digits; every integer to 2^53 = 9,007,199,254,740,992 (`Number.MAX_SAFE_INTEGER`); largest 1.80e308; smallest subnormal 2^-1074 |
| where it lives | every CPU natively; GPUs at anywhere from one half to one sixty-fourth of their binary32 rate depending on the part; on the tile, 4 lanes per beat, one tile 1.1x behind the workstation |
| where it breaks | the 2^53 cliff in JavaScript identifiers; summation order - a parallel reduction that answers differently on a different core count; x87 excess precision and double rounding; `-ffast-math`; the libm lottery - `sin` differing in the last bit between glibc, musl and macOS, all of them legal because 754 recommends and does not require correct rounding for clause 9; Excel showing 15 digits of a 17-digit value; round-off as a random walk - Brouwer's law, energy error growing as t^0.5 and phase as t^1.5, measured over a 64-member ensemble in cft-rebound's docs/HORIZON.md |
| signature interactive | **your browser's `Math.sin` against the correctly rounded value**: type x, see the browser's answer, the contract's answer (`cftw_sin`), and whether the last bit moved; then a sweep of a thousand inputs over all thirty-nine functions, counting the disagreements. Different browsers produce different counts on the same page, which is the whole argument made in the reader's own tab. The second visual is the round-off random walk: the ensemble's phase-error percentiles against orbits, from the horizon data |
| tools and libraries | the platform libm, and CORE-MATH or CRlibm when the last bit has to be the same everywhere; compensated and exact summation - Kahan, ReproBLAS, and 9.5's `augmentedAddition`, which this library provides; Herbie; MPFR or `BigFloat` for checking an answer at more digits; `printf("%a")` for writing a double down exactly; this library for the contract, and for the 39 functions correctly rounded |
| same bits everywhere | clause 9 is where binary64 diverges, and the contract's 39 correctly rounded functions are the answer to it. The evidence this site carries is the REBOUND port: a fifteenth-order integrator used in orbital-dynamics research, every floating-point operation routed through this library, and **at binary64 the result is REBOUND's own IAS15 bit for bit** - 1,264 recorded values identical, across rejected steps and iteration caps. A library that reproduces a real scientific code's bits is a library whose binary64 is IEEE binary64. Beside it, the one program in nine languages printing the checksum `0x04110a4c30c6df4d` on every platform in docs/COMPATIBILITY.md |
| up the ladder | the honest bridge is cft-rebound's horizon: binary64 is entirely sufficient for regular systems under a million orbits at 1e-6 of an orbit, for chaotic systems past their horizon where the science is statistical, and for anything limited by its physics. The niche for wider is phases of a regular system past a few million orbits, close encounters, and results demanded exact rather than close. That paragraph, and the table it comes from, is the link to binary128.com |

### binary128.com - the format that is in the standard and almost not in the silicon

| | |
|---|---|
| aliases | quadruple precision, quad, `__float128`, C23's `_Float128`, `real128` / `REAL(16)`, Boost `float128`, and `long double` **on some platforms only** |
| parameters | w 15, t 112, p 113, emax 16383; 34.02 digits; integers to 2^113 ~ 1.04e34; largest 1.19e4932; smallest subnormal 2^-16494 |
| where it lives | in hardware: IBM POWER9 and later, IBM z, the RISC-V Q extension on paper, and this tile at 2 lanes per beat - **the first rung where the card beats the best software**: one tile 4.5x over gcc's `__float128`, four tiles 17.5x, crossing MPFR at about 2,700 elements (docs/BENCHMARKS.md, `tipping-points.json`). In software everywhere else, and **not at all on Apple Silicon**, where `__float128` does not exist and `long double` is 64 bits, so MPFR is not the best alternative there but the only one |
| where it breaks | `long double` is three formats behind one keyword: 80-bit x87 on x86-64 Linux, binary128 on AArch64 Linux and SPARC, plain binary64 on MSVC and macOS - a determinism story in one identifier; `np.longdouble` inherits that; `fmaq` is a soft routine, so `__float128` multiplies in 20.8 ns and fuses in 817 ns, a 39x cliff inside one library; printing needs `quadmath_snprintf`; Python has no native quad, so it is mpmath or gmpy2 at 113 bits, which is the pattern `bindings/python/cftmpfr` is a drop-in for; Rust's `f128` is unstable, Go, Java, .NET and JavaScript have nothing |
| signature interactive | **Burrau's Pythagorean three-body problem at binary64 and binary128 on the same steps**: the binary64 solution is lost by t = 66 and the binary128 solution runs eighteen decades under it, the two divergence curves being one curve 2^60 apart (cft-rebound, docs/HORIZON.md). The chart from the recorded runs, and beside it the live quad calculator with the 34-digit exact expansion |
| tools and libraries | libquadmath and the compiler's `_Float128`; gfortran's `real128`; Boost.Multiprecision; MPFR at 113 bits with the manual's binary-format recipe (exponent range narrowed, `mpfr_check_range`, `mpfr_subnormalize` on every result - and what that still does not buy: encodings, payloads, signaling NaNs, this contract's flags); Julia's Quadmath.jl; mpmath; this library, in software or on the tile |
| same bits everywhere | the implementations a reader can reach disagree with each other in the transcendentals and in the cost of a fused multiply-add; the contract's every operation is correctly rounded, and GNU MPFR - the only external oracle that reaches this format - arbitrates 739,234 transcendental cases and 999,000 divide and square-root cases with zero value and zero flag mismatches. Checksum `0xb815aa4a3a3eb024` |
| the ladder, both ways | down: most of the time binary64 is enough, and the horizon table says exactly when. Up: **binary256 changes nothing for this integrator at any step a user would choose** - identical to binary128 to every digit at every setting of the sweep - except the outer solar system at 10 to 20 day steps, where it is worth one to six orders more. A measured negative result, kept, is the most credible link a site can offer to its neighbour |

### binary256.com - the format no one ships

| | |
|---|---|
| aliases | octuple precision. No language has a keyword for it. The standard defines it by formula - Table 3.5's binary{k} - and names it as its own example: "binary256 would have p = 237 and emax = 262143" |
| parameters | w 19, t 236, p 237, emax 262143; 71.34 digits; integers to 2^237 ~ 2.21e71; largest 1.61e78913; smallest subnormal 2^-262378 |
| where it lives | no commercial processor implements it; this tile does, 1 element per beat with a 237-bit significand, 107 million elements a second on one tile and 427 million on four at about 35 watts, 5.5x over MPFR on one tile and 21.1x on four; in software, MPFR at 237 bits, mpmath, Julia's `BigFloat`, and this library on anything with a C compiler, a browser, a Raspberry Pi Pico or an ESP32 (docs/EMBEDDED.md) |
| where it breaks | there is no second implementation to disagree with, which is the format's own problem: an MPFR result at 237 bits and a 754 binary256 result are not the same thing until the exponent range, the subnormals, the NaN encodings and the flags are pinned, and MPFR's manual recipe pins the first two. What binary256 does not buy is the other honest entry: IAS15 at ordinary steps, where the method's own truncation error sits far above the binary128 floor |
| what it is for, measured | a deep-zoom reference orbit where one pixel is 3.1e-61 wide: binary256 holds the centre to zero pixels of error, and the binary64 reference is 9.4e30 pixels off, wrong from iteration 1, **raising no flag** (docs/ZOOM.md); exact integers below 2^237 - Collatz trajectories with the inexact flag as the certificate, and Lucas-Lehmer on 59-bit limbs through 2^19937 - 1 (docs/MERSENNE.md); rigorous enclosures where 14 of 15 ill-conditioned binary64 enclosures straddle zero and 0 of 15 at binary256 (docs/ENCLOSE.md); checking a binary64 libm, which wants more than twice the bits; angular-momentum drift of 9.0e-69 against binary64's 1.4e-13 on the same orbit, 2^184 apart (docs/ORBITS.md) |
| signature interactive | **the deep-zoom explorer**: the binary256 reference orbit with binary64 perturbation, rendered in the tab, and the binary64 reference beside it, different at every one of 4,096 pixels with every flag clear (`demos_core.js` already runs it, checksum-matched to the C tool). Second: the 71-digit exact expansion of any number the reader types |
| tools and libraries | MPFR and GMP; mpmath; Julia `BigFloat`; Boost `cpp_bin_float`, which is not bit-exact 754; Arb (now in FLINT) for ball arithmetic when rigour is the point; this library, which is the only one of these that is a binary256 *implementation* rather than a multiprecision library set to 237 bits |
| same bits everywhere | at this format the contract is not one implementation among several; it is the definition, published as 1,068,915 conformance cases anyone can score against, with MPFR as the one external arbiter. The replay in section 8 runs the reference implementation in the reader's tab. Checksum `0x0eea048c14040a4e` |
| down the ladder | the negative result again, stated first: if the method's error is above the binary128 floor, binary128 is the answer and it is one click left. This is the one site where the tile can be described fully - the beat, the lanes, the card - and still in section 8, not the hero |

---

## What the repository already supplies

None of the arithmetic on the sites is new. The inventory, so the sites
are scoped as writing and layout rather than as a second implementation:

| piece | where it is | what the sites do with it |
|---|---|---|
| the wasm module | `bindings/node/cft_node.wasm` (226,393 bytes) and its loader `cft_node.js`; 138 `cftw_*` exports at ABI 0.11, byte-identical to the module the conformance page embeds | every widget in the template. Pin it by commit and sha256 the way cft-rebound pins its upstreams and docs/DEMOS.md records its build, so each site's footer can name the module it loaded |
| exact decimal and hex conversion | `cftw_to_decimal_char`, `cftw_from_decimal_char`, `cftw_to_hex_char`, `cftw_from_hex_char` | the inspector's every-digit expansion; the fragment that travels between sites |
| the ladder | `cftw_convert` over all sixteen ordered pairs | `travel`: widen exact, narrow once |
| classification, next, order | `cftw_class`, `cftw_next_up`, `cftw_next_down`, `cftw_total_order` | the inspector and the ruler |
| the operations with attributes and flags | `cftw_run` with the mode word; `cftw_div`, `cftw_sqrt`, `cftw_rint`, `cftw_augmented_add` | sections 5 and 6 |
| the thirty-nine functions | `cftw_sin` ... `cftw_compound` | binary64's signature interactive |
| the replay | `cftw_conformance`, the embedded 4,015-case sample spanning all formats, the 168 set names the drop zone accepts | section 8, filtered to the site's format |
| the workloads | `bindings/wasm/demos_core.js` and `demos_worker.js`: zoom, orbits, Collatz, enclose, Mersenne, each with the C tool's checksum chain in `demos_chains.json` | binary32's Collatz census, binary256's zoom explorer, enclose on both wide sites |
| the charts | `docs/img/bench/when-hardware-pays-{light,dark}.svg` and `cost-by-size-*.svg`, regenerated by `python/readme_charts.py` | section 4's throughput panel on the two wide sites; the losses on the two narrow ones |
| the horizon data | cft-rebound `results/` and `results/horizon/`: the ensembles, the Pythagorean divergence, the floors, `energy_vs_orbits.png` | binary64's random walk, binary128's divergence chart, both ladder sections. Export the plotted series to JSON once, in cft-rebound, rather than shipping CSVs |
| the parameter and evidence tables | docs/DETERMINISM.md (formats), docs/COMPLIANCE.md (clause by clause), docs/COMPATIBILITY.md (the checksums, the languages), docs/BENCHMARKS.md (every rate), CAPABILITIES.md | section 2, 4, 7 and 8 copy |
| the page idiom | `bindings/wasm/make_page.py` and `page_template.html`: a Python generator producing a committed, self-contained page, built in a pinned container | the generator the sites should reuse the shape of |

---

## How the project appears, and where it does not

- **Never** in the hero, the `<title>`, the meta description or the
  site's colour. Never a "buy", "contact" or newsletter. Links go to
  the repositories.
- **The footer, on every page:** one line - the interactive parts run
  libcft, the software of cft-fp256, compiled to WebAssembly, Apache-2.0,
  module named by hash - and the maintainer's name. A site that
  computes needs to say what computed.
- **Section 7, one row**, ranked where it belongs. On binary32.com and
  binary64.com that row says "a CPU wins; this is here so one contract
  covers the ladder", in those words, with the measured numbers. On
  binary128.com and binary256.com the row says what the card measured
  and where software still wins - below a few thousand elements, and at
  binary256 over PCIe rather than resident.
- **Section 8, one section**, in the same place on all four, and the
  only place the tile is described. Its evidence is format-specific
  (above), so the section reads differently on each site while sitting
  in the same slot.
- **cft-rebound appears as evidence, not as a product**: on
  binary64.com as the bit-identity gate, on binary128.com as the
  horizon, on binary256.com as the negative result. A reader who wants
  the integrator follows one link.
- **The library's own softfloat is the reference, not the racer**, and
  the sites say so where it comes up: MPFR beats it by 6 to 19 times on
  add, multiply and fused multiply-add and by 94 to 316 times on divide
  and square root. Charting the card against it would be the accelerator
  number nobody believes, and the README refuses to; the sites inherit
  the refusal.

---

## Hosting: four custom domains on GitHub Pages

GitHub Pages serves **one custom domain per site**, so four domains are
four Pages sites, each with its own `CNAME` file. Two ways to organise
that, and the recommendation:

**One source repository, four deploy targets (recommended).** A repo
such as `binary-sites` holds `common/` (the CSS, the ladder nav, the
widgets, the module loader, the pinned wasm) and `sites/32`, `sites/64`,
`sites/128`, `sites/256` (the writing, as Markdown or as the generator's
template fragments). One generator, in the shape of `make_page.py`,
builds four output trees. One workflow deploys each tree to its own
Pages repository - `binary32.com`, `binary64.com`, `binary128.com`,
`binary256.com` - over a deploy key, which is what the
`peaceiris/actions-gh-pages` action's `external_repository` input is
for. One place to edit; a change to a shared widget reaches all four in
one push; the four target repos hold nothing but built output and a
`CNAME`.

**Four repositories with a shared submodule** works too and needs no
deploy keys, at the cost of four places to bump the submodule and four
workflows to keep identical. Take it only if the deploy-key path is
refused by the account's policy.

Practicalities, in the order they bite:

- **DNS.** Apex `A`/`AAAA` records to GitHub's four Pages addresses and
  a `CNAME` from `www` to the account's `github.io` host; set the apex
  as the custom domain and GitHub redirects `www` to it. Enforce HTTPS
  once the certificate issues, which takes up to a day after DNS
  resolves.
- **The module as a file, not a base64 blob.** The conformance page is
  one self-contained file because it is meant to run from `file://`.
  A site with several pages should serve one `cft.wasm` and let the
  browser cache it; Pages serves `application/wasm` correctly, so
  `WebAssembly.instantiateStreaming` works and the 226 KB is fetched
  once per visitor, not once per page.
- **Everything static, nothing tracked.** No cookies, no analytics
  beyond the Pages defaults, so no banner. A `corrections` link to the
  source repository's issues on every page.
- **Provenance the way the repository does it.** The generator records
  the module hash, the ABI and the commit of cft-fp256 it was built
  from into the footer, and the build fails if the pinned hash does not
  match the file - the DEMOS.md pattern, not a new one.
- **Search.** Descriptive `<title>` and description per page, a
  `sitemap.xml` per site, and the four sites linking each other through
  the ladder nav - which is real cross-linking about a real
  relationship, and the only kind worth having. Nothing else.

---

## Sequence

What to build first, so each step is usable on its own:

1. **`common/`**: the ladder nav and bit bars, the module loader, and
   the inspector. The inspector alone - exact digits, class, next, ulp -
   is the widget every other floating-point explainer approximates, and
   it is the one that needs the module most.
2. **binary64.com.** The largest audience, the site whose neutral tone
   sets the family's, and the `Math.sin` sweep as its hook.
3. **binary256.com.** The flagship; the zoom explorer already exists in
   `demos_core.js` and needs a frame around it, not a port.
4. **binary128.com.** Needs the horizon series exported from cft-rebound
   to JSON first; otherwise all writing.
5. **binary32.com.** The Collatz census exists; the spacing ruler is
   shared; the embedded story is written in docs/EMBEDDED.md.
6. **`travel`**, last, because it needs all four live to mean anything.

---

## Open questions for the owner

- **A name for the family?** The recommendation is none: the ladder nav
  is the identity, and a wordmark would be the first step toward the
  self-promotion the brief rules out. If one is wanted, it belongs in
  the footer only.
- **The maintainer line.** A site that computes should say who runs it;
  a footer "maintained by" with a link to the account is the credible
  minimum and is not promotion.
- **Where the writing lives.** In the sites repository, or beside the
  documents it quotes here? Here keeps the numbers next to their runs;
  there keeps the sites buildable without a clone of this repository.
  The recommendation is there, quoting here by commit.
