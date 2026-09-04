// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// bindings/node - libcft in Node, through the wasm module the browser
// conformance page runs.
//
//     import { Context } from "./index.mjs";
//     const ctx = await Context.open(256);        // binary256
//     const y = ctx.sqrt(ctx.from("2"));
//     console.log(y.toString(), ctx.flagNames(ctx.lastFlags));
//
// Two layers, and both are on purpose:
//
//   raw   lib.mjs exposes the module's cftw_* exports one to one, so
//         anything cft.h documents is reachable without asking this
//         package's permission.
//   shaped core.mjs adds Context and Float - a precision, an
//         attribute, sticky flags - the same shape as the Python
//         drop-in, because that shape is what people already write
//         numerics in.
//
// What this package is NOT is a drop-in for a named JavaScript
// library, and the README says why: nothing mainstream in JS models
// binary128 or binary256, and the decimal packages model a different
// radix. Being a "drop-in" for one of those would mean claiming
// semantics this library does not implement.

export { Context, Float, NotExact, formatFor } from "./core.mjs";
export {
  ABI_MAJOR, AUGMENTED, CHARACTER_FNS, CLASS_NAMES, FLAGS_ALL,
  FLAG_DIVBYZERO,
  FLAG_INEXACT, FLAG_INVALID, FLAG_OVERFLOW, FLAG_UNDERFLOW,
  FORMATOF_ARITY, FORMATOF_FNS, FORMATOF_METHOD,
  MINMAG_METHOD, MINMAX_MAG, OPS_BY_NAME,
  SCALED_PRODUCTS, TRANSCEND_BINARY, TRANSCEND_INTARG, TRANSCEND_UNARY,
  flagNames, is754version1985, is754version2008, is754version2019,
  loadModule,
} from "./lib.mjs";
