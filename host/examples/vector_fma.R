# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# The same program as vector_fma.c, in R.
#
#     Rscript host/examples/vector_fma.R [artifact.xclbin]
#
# It must print exactly what the C program prints - every line, every
# digit. Base R only: no CRAN package, no binding generator, nothing
# to install beyond R itself on the machine that built the library.
#
# R is the row of the table in docs/HOSTAPI.md that says "a thin
# shim", and this file is that row paid out - shim included, at the
# bottom, all of a page. The shim exists because base R's foreign
# interfaces prescribe the callee's shape instead of adapting to it:
# .C hands the callee a pointer for every argument and returns
# nothing, .Call hands it R's own boxed values, and neither can pass
# cft_run the plain by-value ints it asks for, the way ctypes and
# ccall assemble a foreign call frame at run time. So R compiles the
# shim itself on each run - R CMD SHLIB, into tempdir(), about a
# second - and the shim does calling-convention work only: arguments
# out of boxes, results into boxes. No arithmetic, no defaults, no
# policy - nothing in it that can drift. The pitch's letter ("no
# build step") bends for R; the part that keeps checksums equal - no
# second implementation - does not.
#
# Of the two interfaces the shim could present, .Call, for two
# load-bearing reasons:
#
#  * The device handle is a pointer that must survive between calls.
#    .Call carries it as an external pointer - a pointer-shaped value
#    in a pointer-shaped box. Under .C it would have to ride bit-cast
#    through a double, which works until the day a pointer does not
#    round-trip, and lies about what it is every day before that.
#
#  * The operand streams are raw vectors, and .Call passes the vector
#    itself - RAW() is its storage, read in place, written in place.
#    .C's contract is to copy every argument in and back out on every
#    call; nothing in that copying can go right, it can only go wrong
#    or go slowly.
#
# The other thing R lacks is a 64-bit integer, and the checksum needs
# one. Doubles hold integers exactly to 2^53 and no further - the FNV
# offset basis would not even survive being typed in whole. So the
# FNV-1a below runs on 32-bit halves held in doubles, and it is exact
# rather than close: with h = hi*2^32 + lo and the prime split the
# same way, h*prime mod 2^64 is lo*PRM_LO for the low word and
# hi*PRM_LO + lo*PRM_HI + carry for the high, and every term stays
# below 2^42 - comfortably inside the range where a double is still
# an integer. Divisions are by powers of two only. No step ever
# rounds, so the hash is FNV, not something FNV-shaped. The
# xorshift32 state gets the same discipline one word down: shifts as
# exact scalings, xor sixteen bits at a time, because R's own
# integers stop at 2^31.
#
# Verified 2026-09-01: R 4.1.2 on Linux (the cft2204 WSL distro),
# byte-identical to the C example on the same machine, all four
# checksums matching the published set - and the error paths diffed
# along with the happy one: a missing artifact produces the C
# example's stderr byte for byte, a missing library the ctypes
# port's. Two demands the other ports do not make: a C toolchain at
# run time (for the shim build; a machine that built the library has
# one by definition), and R 4.0 or later, for the raw string the
# shim's source sits in.

# cft_op and cft_round - the values are normative (cft.h), so a
# caller writes the names and never the register layout behind them.
FMA <- 0L
RNE <- 0L

N <- 4096L

# width, exp_w, man_w, bias - the geometry table vector_fma.c
# carries. Operand-stream machinery, not format knowledge the caller
# should own: element sizes and names below still come from the
# library, because a size the caller guesses is a size that goes
# stale.
GEOM <- list(
  c(width =  32L, exp_w =  8L, man_w =  23L, bias =    127L),
  c(width =  64L, exp_w = 11L, man_w =  52L, bias =   1023L),
  c(width = 128L, exp_w = 15L, man_w = 112L, bias =  16383L),
  c(width = 256L, exp_w = 19L, man_w = 236L, bias = 262143L)
)

# Rscript gives a script no equivalent of __file__ or @__DIR__; the
# path is recovered from the --file= argument the front end passes.
script_path <- function() {
  arg <- grep("^--file=", commandArgs(trailingOnly = FALSE), value = TRUE)
  normalizePath(sub("^--file=", "", arg[1]))
}

# Exactly one candidate, chosen by platform - the same policy as
# vector_fma_ctypes.py, for the same reason: listing every name and
# taking the first that exists looks tolerant and is not. A tree
# built from two platforms holds both libraries, and the fallback
# then loads the foreign one and fails with a loader error instead
# of "build it first".
library_path <- function() {
  override <- Sys.getenv("CFT_LIB")
  if (nzchar(override)) return(override)
  name <- if (.Platform$OS.type == "windows") "cft.dll"
          else if (Sys.info()[["sysname"]] == "Darwin") "libcft.dylib"
          else "libcft.so"
  root <- dirname(dirname(dirname(script_path())))
  file.path(root, "host", name)
}

# ---- the shim ---------------------------------------------------- #
#
# Seven entry points, transcribed from cft.h - the R analogue of the
# Rust example's extern block, plus the unboxing that block does not
# need. The library is linked by the absolute path library_path()
# chose: libcft.so carries no SONAME, so the linker records the path
# itself and the loader reopens exactly that file - a CFT_LIB
# override included - with no search path to get wrong.
SHIM <- r"---(
#include <stddef.h>
#include <stdint.h>
#include <Rinternals.h>

typedef struct cft_device cft_device;

extern int         cft_open(const char *artifact, int index,
                            cft_device **out);
extern void        cft_close(cft_device *dev);
extern int         cft_supports(cft_device *dev, int op, int fmt);
extern size_t      cft_format_size(int fmt);
extern const char *cft_format_name(int fmt);
extern const char *cft_strerror(int status);
extern int         cft_run(cft_device *dev, int op, int fmt, int rnd,
                           const void *a, const void *b, const void *c,
                           void *d, size_t n,
                           uint32_t *flags_out, uint32_t *bus_out);

SEXP r_open(SEXP artifact)
{
    cft_device *dev = NULL;
    const char *path = Rf_isNull(artifact) ? NULL
                                           : CHAR(STRING_ELT(artifact, 0));
    int st = cft_open(path, 0, &dev);
    SEXP out = PROTECT(Rf_allocVector(VECSXP, 2));
    SET_VECTOR_ELT(out, 0, Rf_ScalarInteger(st));
    SET_VECTOR_ELT(out, 1, R_MakeExternalPtr(dev, R_NilValue, R_NilValue));
    UNPROTECT(1);
    return out;
}

SEXP r_close(SEXP dev)
{
    cft_close((cft_device *)R_ExternalPtrAddr(dev));
    return R_NilValue;
}

SEXP r_supports(SEXP dev, SEXP op, SEXP fmt)
{
    return Rf_ScalarInteger(
        cft_supports((cft_device *)R_ExternalPtrAddr(dev),
                     Rf_asInteger(op), Rf_asInteger(fmt)));
}

SEXP r_format_size(SEXP fmt)
{
    return Rf_ScalarInteger((int)cft_format_size(Rf_asInteger(fmt)));
}

SEXP r_format_name(SEXP fmt)
{
    return Rf_mkString(cft_format_name(Rf_asInteger(fmt)));
}

SEXP r_strerror(SEXP st)
{
    return Rf_mkString(cft_strerror(Rf_asInteger(st)));
}

SEXP r_run(SEXP dev, SEXP op, SEXP fmt, SEXP rnd,
           SEXP a, SEXP b, SEXP c, SEXP n)
{
    uint32_t flags = 0;
    SEXP d = PROTECT(Rf_allocVector(RAWSXP, XLENGTH(a)));
    int st = cft_run((cft_device *)R_ExternalPtrAddr(dev),
                     Rf_asInteger(op), Rf_asInteger(fmt), Rf_asInteger(rnd),
                     RAW(a), RAW(b), RAW(c), RAW(d),
                     (size_t)Rf_asInteger(n), &flags, NULL);
    SEXP out = PROTECT(Rf_allocVector(VECSXP, 3));
    SET_VECTOR_ELT(out, 0, Rf_ScalarInteger(st));
    SET_VECTOR_ELT(out, 1, d);
    SET_VECTOR_ELT(out, 2, Rf_ScalarInteger((int)flags));
    UNPROTECT(2);
    return out;
}
)---"

build_shim <- function(lib) {
  dir <- file.path(tempdir(), "cft-shim")
  dir.create(dir, showWarnings = FALSE)
  writeLines(SHIM, file.path(dir, "cft_shim.c"))
  old <- setwd(dir)
  on.exit(setwd(old))
  log <- suppressWarnings(
    system2(file.path(R.home("bin"), "R"),
            c("CMD", "SHLIB", "cft_shim.c", shQuote(lib)),
            stdout = TRUE, stderr = TRUE))
  so <- file.path(dir, paste0("cft_shim", .Platform$dynlib.ext))
  if (!file.exists(so)) {
    cat(log, sep = "\n", file = stderr())
    cat("shim build failed - R CMD SHLIB needs the C toolchain",
        "that built the library\n", file = stderr())
    quit(save = "no", status = 1)
  }
  so
}

load_library <- function() {
  path <- library_path()
  if (!file.exists(path)) {
    cat(path, " not found - run `make -C host` first\n",
        sep = "", file = stderr())
    quit(save = "no", status = 1)
  }
  # The library first, by full path, so a Windows loader can satisfy
  # the shim's dependency from the module already in the process; on
  # ELF the shim's recorded absolute path does the work and this is a
  # reference count.
  dyn.load(path)
  dll <- dyn.load(build_shim(path))
  sym <- function(name) getNativeSymbolInfo(name, PACKAGE = dll)
  list(open        = sym("r_open"),
       close       = sym("r_close"),
       supports    = sym("r_supports"),
       format_size = sym("r_format_size"),
       format_name = sym("r_format_name"),
       strerror    = sym("r_strerror"),
       run         = sym("r_run"))
}

# ---- the operand stream ------------------------------------------ #

# xorshift32, stepped once per byte - the stream vector_fma.c
# generates, which is what lets the two checksums be compared at all.
# The state is a whole number below 2^32 in a double. Shifting left
# is multiplying by 2^k and reducing mod 2^32; shifting right is
# integer division by 2^k; nothing exceeds 2^45 on the way, so every
# step is exact. xor has no such trick and goes through bitwXor
# sixteen bits at a time, each half small enough for R's integers.
xor32 <- function(a, b) {
  bitwXor(a %/% 2^16, b %/% 2^16) * 2^16 + bitwXor(a %% 2^16, b %% 2^16)
}

rng_new <- function(seed) {
  r <- new.env(parent = emptyenv())
  r$s <- if (seed == 0) 1 else seed
  r
}

rng_byte <- function(r) {
  s <- r$s
  s <- xor32(s, (s * 2^13) %% 2^32)
  s <- xor32(s, s %/% 2^17)
  s <- xor32(s, (s * 2^5) %% 2^32)
  r$s <- s
  s %% 256
}

# One element, as nb byte values 0..255: a normal with a fraction
# from the stream and an exponent within 32 of 1.0, so that products
# stay in range and the run exercises rounding rather than overflow.
# vector_fma.c line for line, shifted to 1-based indexing - the same
# hazard the Julia port walks, caught by the same diff.
make_element <- function(r, width, exp_w, man_w, bias) {
  nb <- width %/% 8
  kb <- man_w %/% 8
  rb <- man_w %% 8

  e <- numeric(nb)
  for (j in 1:nb)
    e[j] <- rng_byte(r)
  ef <- bias - 32 + bitwAnd(rng_byte(r), 63)

  e[kb + 1] <- bitwAnd(e[kb + 1], 2^rb - 1)
  if (kb + 2 <= nb)               # `:` counts down when its range is
    for (j in (kb + 2):nb)        # empty, so it gets a guard, not trust
      e[j] <- 0
  for (j in 0:(exp_w - 1)) {
    if (bitwAnd(ef %/% 2^j, 1) != 0) {
      k <- (man_w + j) %/% 8 + 1
      e[k] <- bitwOr(e[k], 2^((man_w + j) %% 8))
    }
  }
  if (bitwAnd(rng_byte(r), 1) != 0)
    e[nb] <- bitwOr(e[nb], 128)
  e
}

# ---- the checksum ------------------------------------------------ #

# FNV-1a's two constants, copied from the specification in the base
# the specification uses - hex - and split at bit 32 because no R
# literal can hold 64 bits. Retyping them whole, in decimal, silently
# rounded, is how you get a checksum that is stable, plausible, and
# not FNV.
FNV_HI <- 0xcbf29ce4   # offset basis 0xcbf29ce484222325, bits 63..32
FNV_LO <- 0x84222325   #                                  bits 31..0
PRM_HI <- 0x100        # prime        0x00000100000001b3, bits 63..32
PRM_LO <- 0x1b3        #                                  bits 31..0

# Returns the 16 hex digits directly: the halves are what this file
# has, and %016llx is not a thing R's sprintf can be asked for.
fnv1a <- function(bytes) {
  v  <- as.integer(bytes)
  hi <- FNV_HI
  lo <- FNV_LO
  for (x in v) {
    l8 <- lo %% 256                   # h ^= byte: only the low eight
    lo <- lo - l8 + bitwXor(l8, x)    # bits can change
    t  <- lo * PRM_LO                 # h *= prime, in halves; every
    hi <- (hi * PRM_LO + lo * PRM_HI + t %/% 2^32) %% 2^32   # term
    lo <- t %% 2^32                   # below 2^42, so exact
  }
  sprintf("%04x%04x%04x%04x",
          as.integer(hi %/% 2^16), as.integer(hi %% 2^16),
          as.integer(lo %/% 2^16), as.integer(lo %% 2^16))
}

# ---- the program ------------------------------------------------- #

main <- function() {
  args <- commandArgs(trailingOnly = TRUE)
  artifact <- if (length(args) > 0) args[1] else NULL
  backend <- if (is.null(artifact)) "software" else artifact

  cft <- load_library()

  opened <- .Call(cft$open, artifact)
  st <- opened[[1]]
  dev <- opened[[2]]
  if (st != 0L) {
    cat(sprintf("cft_open(%s): %s\n", backend, .Call(cft$strerror, st)),
        file = stderr())
    quit(save = "no", status = 1)
  }
  cat(sprintf("cft-fp256 vector fma, %s backend\n", backend))

  for (f in 0:3) {
    g <- GEOM[[f + 1]]
    fmt <- as.integer(f)

    # The name comes from the library, not a local table - cft.h
    # provides cft_format_name precisely so a binding, a log line
    # and a conformance report all say the same thing.
    name <- .Call(cft$format_name, fmt)

    if (.Call(cft$supports, dev, FMA, fmt) == 0L) {
      cat(sprintf("%-6s not available on this device\n", name))
      next
    }
    esz <- .Call(cft$format_size, fmt)

    a <- numeric(N * esz)
    b <- numeric(N * esz)
    c <- numeric(N * esz)

    # Seeded per format, so each line is independent of the ones
    # before it and can be reproduced on its own.
    r <- rng_new(0x1234567 + f)
    for (i in 0:(N - 1)) {
      off <- i * esz
      a[off + (1:esz)] <- make_element(r, g[["width"]], g[["exp_w"]],
                                       g[["man_w"]], g[["bias"]])
      b[off + (1:esz)] <- make_element(r, g[["width"]], g[["exp_w"]],
                                       g[["man_w"]], g[["bias"]])
      c[off + (1:esz)] <- make_element(r, g[["width"]], g[["exp_w"]],
                                       g[["man_w"]], g[["bias"]])
    }

    run <- .Call(cft$run, dev, FMA, fmt, RNE,
                 as.raw(a), as.raw(b), as.raw(c), N)
    if (run[[1]] != 0L) {
      cat(sprintf("cft_run %s: %s\n", name, .Call(cft$strerror, run[[1]])),
          file = stderr())
      .Call(cft$close, dev)
      quit(save = "no", status = 1)
    }

    cat(sprintf("%-6s n=%d rne  checksum 0x%s  flags 0x%02x\n",
                name, N, fnv1a(run[[2]]), run[[3]]))
  }

  .Call(cft$close, dev)
  invisible(0)
}

main()
