# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The ctypes binding of libcft's run/div/sqrt/reduce surface.

This module is deliberately the only place that knows libcft is a C
library. Everything above it deals in Python ints, bytes and
exceptions; everything below it is the header's contract. There is no
build step and no generated code - the C ABI is the whole point, and
this file is what it costs to reach it from Python: one CDLL and a
page of argtypes.

Library discovery
-----------------
Candidates are tried in a fixed, documented order; the search stops at
the first path that EXISTS (not the first that loads - a library that
exists but fails to load is an error worth seeing, not a reason to
quietly try somewhere else):

1. ``CFT_LIB`` - an explicit override wins outright. Same variable the
   repo's own test harnesses honour.
2. The in-repo build: ``<repo>/host/cft.dll`` (or ``libcft.so``,
   ``libcft.dylib``), located relative to this file. This is what
   makes a fresh checkout plus ``make -C host`` work with no
   configuration.
3. Next to this package: a vendored copy of the library dropped into
   the ``cftmpfr/`` directory itself, for when the package is copied
   out of the repo.
4. ``ctypes.util.find_library("cft")`` - the system loader's opinion,
   for an installed library.

Each step names exactly one file per platform rather than trying every
platform's name in turn: a tree built from two platforms holds both
libraries, and a tolerant fallback then loads the foreign one and
fails with "invalid ELF header" instead of "build it first".

Thread safety
-------------
Per cft.h: a ``cft_device`` is NOT thread-safe, and neither is the
static buffer behind ``cft_last_error()``. The CDLL handle itself (the
module-level singleton here) is safe to share - binding argtypes once
at import is exactly why - but every thread must open its own device.
``core.Context`` owns one device apiece, so the rule callers actually
follow is: one Context per thread. Contexts are cheap; the software
backend's open is an allocation, not a negotiation.
"""

import ctypes
import ctypes.util
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------
# Constants transcribed from cft.h. The header is normative; these are
# the names, not a reinterpretation. cft_format_name()/cft_op_name()
# exist so that a mistranscription here shows up as a name mismatch
# rather than as a wrong answer - which is the audit the header
# designed for, and _audit() below is where it is actually performed,
# once, against whatever shared library this process loaded. The
# expected name is not written out anywhere: it is the Python
# constant's own name, lowercased, so there is one transcription here
# and not two.
#
# The rounding attributes and the exception flags get no such audit
# because the header publishes no accessor for them - the ABI major
# check is all that stands behind those five and those five bits.
# ---------------------------------------------------------------------

ABI_MAJOR = 0        # cft.h CFT_ABI_VERSION_MAJOR; a different major
                     # breaks source or binary compatibility outright

FP32, FP64, FP128, FP256 = 0, 1, 2, 3

OP_FMA, OP_ADD, OP_SUB, OP_MUL = 0, 1, 2, 3
OP_ABS, OP_NEG, OP_COPYSIGN = 4, 5, 6
OP_MIN, OP_MAX, OP_MINNUM, OP_MAXNUM = 7, 8, 9, 10
OP_SELECT, OP_CMPLT, OP_CMPLE, OP_CMPEQ = 11, 12, 13, 14
OP_SUM, OP_DOT = 24, 25
OP_RECIP_SEED, OP_RSQRT_SEED = 26, 27
OP_SUMSQ, OP_SUMABS = 28, 29        # the other two of clause 9.4

RNE, RTZ, RDN, RUP, RMM = 0, 1, 2, 3, 4

FLAG_INVALID = 1 << 0
FLAG_DIVBYZERO = 1 << 1
FLAG_OVERFLOW = 1 << 2
FLAG_UNDERFLOW = 1 << 3
FLAG_INEXACT = 1 << 4

_FLAG_NAMES = (
    (FLAG_INVALID, "invalid"),
    (FLAG_DIVBYZERO, "divbyzero"),
    (FLAG_OVERFLOW, "overflow"),
    (FLAG_UNDERFLOW, "underflow"),
    (FLAG_INEXACT, "inexact"),
)


def flag_names(flags):
    """The IEEE exception names set in a flag word, as a tuple.

    An unexpected high bit is reported rather than dropped: a flag
    word this library cannot name is a disagreement with the header,
    and hiding it would be the one wrong response."""
    names = [n for bit, n in _FLAG_NAMES if flags & bit]
    extra = flags & ~sum(bit for bit, _ in _FLAG_NAMES)
    if extra:
        names.append(f"unknown(0x{extra:x})")
    return tuple(names)


class CftError(RuntimeError):
    """A libcft call returned a non-OK status.

    Carries the numeric status, the header's name for it, and whatever
    detail cft_last_error() had to add - which on a device backend is
    often the only explanation anybody gets."""

    def __init__(self, status, where, strerror, detail):
        self.status = status
        self.where = where
        msg = f"{where}: {strerror} (status {status})"
        if detail:
            msg += f" - {detail}"
        super().__init__(msg)


# ---------------------------------------------------------------------
# Discovery and binding
# ---------------------------------------------------------------------

_LIB = None  # the bound CDLL, created once on first use


def _platform_name():
    return {"win32": "cft.dll", "cygwin": "cft.dll",
            "darwin": "libcft.dylib"}.get(sys.platform, "libcft.so")


def _candidates():
    override = os.environ.get("CFT_LIB")
    if override:
        yield Path(override)
        return  # an explicit override that is wrong should fail, not fall back
    name = _platform_name()
    here = Path(__file__).resolve()
    # bindings/python/cftmpfr/_lib.py -> repo root is parents[3]
    if len(here.parents) > 3:
        yield here.parents[3] / "host" / name
    yield here.parent / name
    found = ctypes.util.find_library("cft")
    if found:
        yield Path(found)


def _find():
    tried = []
    for path in _candidates():
        if path.exists():
            return path
        tried.append(str(path))
    lines = "\n".join(f"    {t}" for t in tried)
    raise OSError(
        "libcft not found. Tried:\n" + lines + "\n"
        "Build it first:\n"
        "    make -C host\n"
        "or point CFT_LIB at the shared library.")


def _bind(lib):
    """Declare every prototype this package uses. ctypes defaults every
    undeclared function to int(...) and silently truncates pointers on
    64-bit Windows, so an argtype missing here is not a style problem,
    it is a wrong answer waiting for a large address."""
    c_int, c_uint32, c_size_t = ctypes.c_int, ctypes.c_uint32, ctypes.c_size_t
    c_void_p, c_char_p = ctypes.c_void_p, ctypes.c_char_p
    u32p = ctypes.POINTER(c_uint32)

    lib.cft_abi_version.argtypes = []
    lib.cft_abi_version.restype = c_uint32
    lib.cft_strerror.argtypes = [c_int]
    lib.cft_strerror.restype = c_char_p
    lib.cft_last_error.argtypes = []
    lib.cft_last_error.restype = c_char_p
    lib.cft_format_size.argtypes = [c_int]
    lib.cft_format_size.restype = c_size_t
    lib.cft_format_name.argtypes = [c_int]
    lib.cft_format_name.restype = c_char_p
    lib.cft_op_name.argtypes = [c_int]
    lib.cft_op_name.restype = c_char_p

    lib.cft_open.argtypes = [c_char_p, c_int, ctypes.POINTER(c_void_p)]
    lib.cft_open.restype = c_int
    lib.cft_close.argtypes = [c_void_p]
    lib.cft_close.restype = None
    lib.cft_get_caps.argtypes = [c_void_p, ctypes.POINTER(Caps)]
    lib.cft_get_caps.restype = c_int
    lib.cft_supports.argtypes = [c_void_p, c_int, c_int]
    lib.cft_supports.restype = c_int

    lib.cft_run.argtypes = [c_void_p, c_int, c_int, c_int,
                            c_void_p, c_void_p, c_void_p, c_void_p,
                            c_size_t, u32p, u32p]
    lib.cft_run.restype = c_int
    lib.cft_reduce.argtypes = [c_void_p, c_int, c_int, c_int,
                               c_void_p, c_void_p, c_void_p,
                               c_size_t, u32p, u32p]
    lib.cft_reduce.restype = c_int
    lib.cft_div.argtypes = [c_void_p, c_int, c_int,
                            c_void_p, c_void_p, c_void_p,
                            c_size_t, u32p, u32p]
    lib.cft_div.restype = c_int
    lib.cft_sqrt.argtypes = [c_void_p, c_int, c_int,
                             c_void_p, c_void_p,
                             c_size_t, u32p, u32p]
    lib.cft_sqrt.restype = c_int

    # The transcendentals (ABI 0.3, 0.4 and 0.5). Host operations, so
    # no bus word: the argument list ends at the flags pointer.
    for _name in ("cft_exp", "cft_expm1", "cft_exp2", "cft_log",
                  "cft_log1p", "cft_log2", "cft_log10",
                  "cft_sinpi", "cft_cospi", "cft_tanpi", "cft_asin",
                  "cft_acos", "cft_atan", "cft_asinpi", "cft_acospi",
                  "cft_atanpi",
                  "cft_sin", "cft_cos", "cft_tan", "cft_sinh", "cft_cosh",
                  "cft_tanh", "cft_asinh", "cft_acosh", "cft_atanh",
                  "cft_exp2m1", "cft_exp10", "cft_exp10m1", "cft_log2p1",
                  "cft_log10p1", "cft_rsqrt"):
        _fn = getattr(lib, _name)
        _fn.argtypes = [c_void_p, c_int, c_int, c_void_p, c_void_p,
                        c_size_t, ctypes.POINTER(c_uint32)]
        _fn.restype = c_int
    for _name in ("cft_pow", "cft_hypot", "cft_atan2", "cft_atan2pi",
                  "cft_powr"):
        _fn = getattr(lib, _name)
        _fn.argtypes = [c_void_p, c_int, c_int, c_void_p, c_void_p,
                        c_void_p, c_size_t, ctypes.POINTER(c_uint32)]
        _fn.restype = c_int
    # pown, compound and rootn read an INTEGER exponent array beside the
    # encodings, which is what 754-2019 9.2.1 asks for - so their
    # prototype is a different one, and getting it wrong here would be a
    # pointer-sized lie ctypes would happily tell.
    for _name in ("cft_pown", "cft_compound", "cft_rootn"):
        _fn = getattr(lib, _name)
        _fn.argtypes = [c_void_p, c_int, c_int, c_void_p,
                        ctypes.POINTER(ctypes.c_int64), c_void_p,
                        c_size_t, ctypes.POINTER(c_uint32)]
        _fn.restype = c_int
    # The augmented arithmetic operations (754-2019 9.5). Two outputs
    # and NO rounding argument - the shortest possible summary of why
    # they get their own loop: the standard fixes the rounding, so
    # there is no c_int for an attribute between the format and the
    # operands.
    for _name in ("cft_augmented_add", "cft_augmented_sub",
                  "cft_augmented_mul"):
        _fn = getattr(lib, _name)
        _fn.argtypes = [c_void_p, c_int, c_void_p, c_void_p, c_void_p,
                        c_void_p, c_size_t, ctypes.POINTER(c_uint32)]
        _fn.restype = c_int

    # The scaled product reductions (clause 9.4). Host operations like
    # the transcendentals - no bus word - but they return a PAIR, so
    # the argument list carries an int64 out-parameter for the scale
    # before the length. Three named entry points rather than one with
    # a kind argument, for the reason cft.h gives.
    _i64p = ctypes.POINTER(ctypes.c_int64)
    lib.cft_scaled_prod.argtypes = [c_void_p, c_int, c_int, c_void_p,
                                    c_void_p, _i64p, c_size_t,
                                    ctypes.POINTER(c_uint32)]
    lib.cft_scaled_prod.restype = c_int
    for _name in ("cft_scaled_prod_sum", "cft_scaled_prod_diff"):
        _fn = getattr(lib, _name)
        _fn.argtypes = [c_void_p, c_int, c_int, c_void_p, c_void_p,
                        c_void_p, _i64p, c_size_t,
                        ctypes.POINTER(c_uint32)]
        _fn.restype = c_int

    # The formatOf arithmetic of 754-2019 5.4.1: TWO formats per call,
    # the operands read in the first and the result rounded once into
    # the second. Written out rather than looped over the same-format
    # list, because the extra c_int is exactly the kind of difference a
    # shared loop hides.
    for _name in ("cft_formatof_add", "cft_formatof_sub",
                  "cft_formatof_mul", "cft_formatof_div"):
        _fn = getattr(lib, _name)
        _fn.argtypes = [c_void_p, c_int, c_int, c_int, c_void_p, c_void_p,
                        c_void_p, c_size_t, ctypes.POINTER(c_uint32),
                        ctypes.POINTER(c_uint32)]
        _fn.restype = c_int
    lib.cft_formatof_sqrt.argtypes = [c_void_p, c_int, c_int, c_int,
                                      c_void_p, c_void_p, c_size_t,
                                      ctypes.POINTER(c_uint32),
                                      ctypes.POINTER(c_uint32)]
    lib.cft_formatof_sqrt.restype = c_int
    lib.cft_formatof_fma.argtypes = [c_void_p, c_int, c_int, c_int,
                                     c_void_p, c_void_p, c_void_p,
                                     c_void_p, c_size_t,
                                     ctypes.POINTER(c_uint32),
                                     ctypes.POINTER(c_uint32)]
    lib.cft_formatof_fma.restype = c_int

    # The clause-5.12 character conversions and the clause-9.7 payload
    # operations (part of the 0.6 step). Host operations, so no bus
    # word; the payload three signal nothing, so no flag word either.
    szp = ctypes.POINTER(c_size_t)
    cpp = ctypes.POINTER(c_char_p)
    lib.cft_format_decimal_digits.argtypes = [c_int]
    lib.cft_format_decimal_digits.restype = c_size_t
    lib.cft_from_decimal_char.argtypes = [c_void_p, c_int, c_int, cpp,
                                          c_void_p, c_size_t, szp, u32p]
    lib.cft_from_hex_char.argtypes = [c_void_p, c_int, c_int, cpp, c_void_p,
                                      c_size_t, szp, u32p]
    lib.cft_to_decimal_char.argtypes = [c_void_p, c_int, c_int, c_void_p,
                                        c_size_t, c_char_p, c_size_t, szp,
                                        u32p]
    lib.cft_to_hex_char.argtypes = [c_void_p, c_int, c_void_p, c_char_p,
                                    c_size_t, szp]
    for _name in ("cft_get_payload", "cft_set_payload",
                  "cft_set_payload_signaling"):
        _fn = getattr(lib, _name)
        _fn.argtypes = [c_void_p, c_int, c_void_p, c_void_p, c_size_t]
        _fn.restype = c_int
    for _name in ("cft_from_decimal_char", "cft_from_hex_char",
                  "cft_to_decimal_char", "cft_to_hex_char"):
        getattr(lib, _name).restype = c_int

    _audit(lib)
    return lib


def _audit(lib):
    """Ask the loaded library whether the constants above mean what
    their names say, and refuse to run if they do not.

    cft.h says to check the ABI at run time rather than trust the
    header you compiled against, "because a binding loaded against a
    different shared library is the normal case, not the exceptional
    one" - and it publishes cft_format_name()/cft_op_name() so that a
    mistranscribed number is visible as a name. Both of those are only
    worth anything if something performs the comparison, so this does,
    once, at bind time. It costs one call per constant, each returning
    a pointer to static storage.

    A mismatch is not something to work around: every number below
    travels into an opcode field, so the failure it prevents is a
    plausible-looking wrong answer rather than a crash."""
    abi = lib.cft_abi_version()
    if (abi >> 16) != ABI_MAJOR:
        raise RuntimeError(
            f"libcft reports ABI {abi >> 16}.{abi & 0xffff}; this package "
            f"is written against major {ABI_MAJOR}. A major change breaks "
            f"source or binary compatibility (cft.h), so the opcode and "
            f"format numbers below cannot be assumed to still mean what "
            f"they say. Update cftmpfr, or point CFT_LIB at a matching "
            f"library.")

    wrong = []
    for name in sorted(globals()):
        value = globals()[name]
        if name.startswith("OP_"):
            want, got = name[3:].lower(), lib.cft_op_name(value)
        elif name in ("FP32", "FP64", "FP128", "FP256"):
            want, got = name.lower(), lib.cft_format_name(value)
        else:
            continue
        got = got.decode("ascii", "replace")
        if got != want:
            wrong.append(f"{name} = {value}, but the library calls "
                         f"{value} {got!r}")
    if wrong:
        detail = "\n".join(f"    {w}" for w in wrong)
        raise RuntimeError(
            "cftmpfr's transcription of cft.h disagrees with the library "
            "it loaded:\n" + detail + "\nThese numbers go into opcode and "
            "format fields, so continuing would compute the wrong "
            "operation and say nothing about it.")


class Caps(ctypes.Structure):
    """cft_caps, with the struct_size handshake the header requires."""
    _fields_ = [("struct_size", ctypes.c_size_t),
                ("format_mask", ctypes.c_uint32),
                ("tiles", ctypes.c_uint32),
                ("abi_version", ctypes.c_uint32),
                ("device_version", ctypes.c_uint32),
                ("flags_readable", ctypes.c_int),
                ("backend", ctypes.c_char * 32)]


def lib():
    """The process-wide bound CDLL. Bound exactly once; see the module
    docstring for what is and is not safe to share."""
    global _LIB
    if _LIB is None:
        _LIB = _bind(ctypes.CDLL(str(_find())))
    return _LIB


def check(status, where):
    """Raise CftError for a non-OK status, with the library's own words."""
    if status != 0:
        L = lib()
        raise CftError(status, where,
                       L.cft_strerror(status).decode("ascii", "replace"),
                       L.cft_last_error().decode("ascii", "replace"))


# ---------------------------------------------------------------------
# Devices - thin, explicit wrappers. Ownership lives in core.Context;
# these exist so core.py never touches ctypes.
# ---------------------------------------------------------------------

def open_device(artifact=None, index=0):
    """cft_open. artifact=None is the software backend; a path is the
    tile's xclbin. Returns an opaque handle for the calls below."""
    handle = ctypes.c_void_p()
    art = os.fsencode(artifact) if artifact is not None else None
    check(lib().cft_open(art, index, ctypes.byref(handle)), "cft_open")
    return handle


def close_device(handle):
    if handle:
        lib().cft_close(handle)


def get_caps(handle):
    caps = Caps()
    caps.struct_size = ctypes.sizeof(Caps)
    check(lib().cft_get_caps(handle, ctypes.byref(caps)), "cft_get_caps")
    return caps


def supports(handle, op, fmt):
    return bool(lib().cft_supports(handle, op, fmt))


def run(handle, op, fmt, rnd, a, b, c, n, esz):
    """cft_run over n elements. a/b/c are bytes-like or None (for the
    operands the op ignores - b for ADD/SUB, c for MUL). Returns
    (result bytes, flag word).

    bytes objects pass through ctypes as borrowed pointers - no copy on
    the way in. The output is a fresh buffer each call; d-aliases-a
    tricks are the C caller's option, not something a binding should
    spring on anybody."""
    d = ctypes.create_string_buffer(n * esz)
    flags = ctypes.c_uint32(0)
    check(lib().cft_run(handle, op, fmt, rnd, a, b, c, d, n,
                        ctypes.byref(flags), None), "cft_run")
    return d.raw, flags.value


def reduce(handle, op, fmt, rnd, a, b, n, esz):
    """cft_reduce: n elements in, ONE element out, over the contract's
    fixed index tree. Returns (one-element bytes, flag word)."""
    d = ctypes.create_string_buffer(esz)
    flags = ctypes.c_uint32(0)
    check(lib().cft_reduce(handle, op, fmt, rnd, a, b, d, n,
                           ctypes.byref(flags), None), "cft_reduce")
    return d.raw, flags.value


def scaled_prod(handle, kind, fmt, rnd, a, b, n, esz):
    """cft_scaled_prod / _sum / _diff: n elements in, a PAIR out.

    kind is 0, 1 or 2 for the product of the elements, of their
    pairwise sums, and of their pairwise differences. Returns
    (one-element bytes, int scale, flag word); scaleB(pr, scale) is the
    product, and pr is always in +-[1, 2) so the operation cannot
    overflow or underflow.
    """
    d = ctypes.create_string_buffer(esz)
    scale = ctypes.c_int64(0)
    flags = ctypes.c_uint32(0)
    name = ("cft_scaled_prod", "cft_scaled_prod_sum",
            "cft_scaled_prod_diff")[kind]
    fn = getattr(lib(), name)
    if kind == 0:
        st = fn(handle, fmt, rnd, a, d, ctypes.byref(scale), n,
                ctypes.byref(flags))
    else:
        st = fn(handle, fmt, rnd, a, b, d, ctypes.byref(scale), n,
                ctypes.byref(flags))
    check(st, name)
    return d.raw, scale.value, flags.value


def div(handle, fmt, rnd, a, b, n, esz):
    d = ctypes.create_string_buffer(n * esz)
    flags = ctypes.c_uint32(0)
    check(lib().cft_div(handle, fmt, rnd, a, b, d, n,
                        ctypes.byref(flags), None), "cft_div")
    return d.raw, flags.value


def sqrt(handle, fmt, rnd, a, n, esz):
    d = ctypes.create_string_buffer(n * esz)
    flags = ctypes.c_uint32(0)
    check(lib().cft_sqrt(handle, fmt, rnd, a, d, n,
                         ctypes.byref(flags), None), "cft_sqrt")
    return d.raw, flags.value


# ---------------------------------------------------------------------
# The transcendentals. Correctly rounded, which is the whole reason they
# are worth calling from here: MPFR's own are too, so the two agree bit
# for bit, and nothing else in a Python numerics stack does.
#
# ABI 0.4's eleven are on the same footing. The Pi-variants are the ones
# a numerics stack most often has to fake - Python's own math module has
# no sinpi at all - and they are the ones whose exact cases are largest.
#
# ABI 0.5's nine complete the elementary set: sin, cos and tan of a
# RADIAN argument, reduced against pi inside the library at any
# magnitude, and the six hyperbolics.


# ---- character sequences (5.12) and NaN payloads (9.7) ---------------
#
# Part of the 0.6 step. The from_ conversions are batches like every
# other call here; the to_ conversions are per element and use the
# library's two-call sizing protocol, which these helpers absorb -
# Python has a growable string, so a caller should never see it.

def from_char(handle, fmt, rnd, seqs, esz, hex_form=False):
    """cft_from_decimal_char / cft_from_hex_char over a list of str.
    Returns (encoding bytes, flag word). A sequence outside 5.12's
    syntax raises CftError naming which one it was, because a caller
    reading a file of numbers needs the line and not just the
    verdict."""
    n = len(seqs)
    arr = (ctypes.c_char_p * max(n, 1))(*[s.encode("ascii") for s in seqs])
    d = ctypes.create_string_buffer(max(n, 1) * esz)
    flags = ctypes.c_uint32(0)
    bad = ctypes.c_size_t(0)
    fn = (lib().cft_from_hex_char if hex_form
          else lib().cft_from_decimal_char)
    st = fn(handle, fmt, rnd, arr, d, n, ctypes.byref(bad),
            ctypes.byref(flags))
    if st != 0:
        where = ("cft_from_hex_char" if hex_form
                 else "cft_from_decimal_char")
        if bad.value < n:
            s = seqs[bad.value]
            where += (" on sequence %d %r"
                      % (bad.value, s if len(s) <= 60 else s[:60] + "..."))
        check(st, where)
    return d.raw[:n * esz], flags.value


def to_char(handle, fmt, rnd, enc, digits=0, hex_form=False):
    """cft_to_decimal_char / cft_to_hex_char for ONE encoding, sized by
    the library. Returns (str, flag word)."""
    need = ctypes.c_size_t(0)
    flags = ctypes.c_uint32(0)
    L = lib()
    if hex_form:
        st = L.cft_to_hex_char(handle, fmt, enc, None, 0,
                               ctypes.byref(need))
    else:
        st = L.cft_to_decimal_char(handle, fmt, rnd, enc, digits, None, 0,
                                   ctypes.byref(need), ctypes.byref(flags))
    if need.value == 0:                  # a real argument error, not a size
        check(st, "cft_to_hex_char" if hex_form else "cft_to_decimal_char")
    buf = ctypes.create_string_buffer(need.value)
    if hex_form:
        st = L.cft_to_hex_char(handle, fmt, enc, buf, need.value,
                               ctypes.byref(need))
    else:
        st = L.cft_to_decimal_char(handle, fmt, rnd, enc, digits, buf,
                                   need.value, ctypes.byref(need),
                                   ctypes.byref(flags))
    check(st, "cft_to_hex_char" if hex_form else "cft_to_decimal_char")
    return buf.value.decode("ascii"), flags.value


def payload_op(handle, name, fmt, enc, n, esz):
    """One of the three 9.7 operations. They signal no exceptions, so
    there is no flag word to return and none is invented."""
    d = ctypes.create_string_buffer(n * esz)
    check(getattr(lib(), "cft_" + name)(handle, fmt, enc, d, n),
          "cft_" + name)
    return d.raw[:n * esz]


def decimal_digits(fmt):
    """Pmin(fmt) from 5.12.2 - the digit count at which the decimal
    round trip is guaranteed. The LIBRARY's answer, not a table here."""
    return lib().cft_format_decimal_digits(fmt)
# ---------------------------------------------------------------------

TRANSCEND_UNARY = ("exp", "expm1", "exp2", "log", "log1p", "log2", "log10",
                   "sinpi", "cospi", "tanpi", "asin", "acos", "atan",
                   "asinpi", "acospi", "atanpi",
                   "sin", "cos", "tan", "sinh", "cosh", "tanh",
                   "asinh", "acosh", "atanh",
                   "exp2m1", "exp10", "exp10m1", "log2p1", "log10p1",
                   "rsqrt")
TRANSCEND_BINARY = ("pow", "hypot", "atan2", "atan2pi", "powr")
#: The three that read an INTEGER exponent per element rather than a
#: second encoding - 9.2.1's "finite integral value in integralFormat".
TRANSCEND_INT = ("pown", "compound", "rootn")
TRANSCEND = TRANSCEND_UNARY + TRANSCEND_BINARY + TRANSCEND_INT


def transcend(handle, name, fmt, rnd, a, b, n, esz, ns=None):
    """One of the thirty-nine, over n elements. b is None for the unary
    ones; ns is the integer exponent sequence for pown, compound and
    rootn and is None for every other. Returns (bytes, flag word)."""
    if name not in TRANSCEND:
        raise ValueError(f"unknown transcendental {name!r}")
    d = ctypes.create_string_buffer(n * esz)
    flags = ctypes.c_uint32(0)
    fn = getattr(lib(), "cft_" + name)
    if name in TRANSCEND_INT:
        if ns is None:
            raise ValueError(f"{name} needs an integer exponent per element")
        arr = (ctypes.c_int64 * n)(*ns)
        st = fn(handle, fmt, rnd, a, arr, d, n, ctypes.byref(flags))
    elif name in TRANSCEND_BINARY:
        st = fn(handle, fmt, rnd, a, b, d, n, ctypes.byref(flags))
    else:
        st = fn(handle, fmt, rnd, a, d, n, ctypes.byref(flags))
    check(st, "cft_" + name)
    return d.raw, flags.value


# ---------------------------------------------------------------------
# The augmented arithmetic operations, 754-2019 clause 9.5.
#
# Two results per element - the operation rounded, and the error that
# rounding made - and no rounding attribute, because 9.5 fixes the
# rounding to roundTiesTowardZero and gives the operations no argument
# to carry one. Note the missing `rnd` parameter below: it is not an
# oversight and it is not a default, it is the standard.
# ---------------------------------------------------------------------

AUGMENTED = ("add", "sub", "mul")


def augmented(handle, name, fmt, a, b, n, esz):
    """One augmented operation over n elements. Returns
    (r bytes, e bytes, flag word)."""
    if name not in AUGMENTED:
        raise ValueError(f"unknown augmented operation {name!r}")
    r = ctypes.create_string_buffer(n * esz)
    e = ctypes.create_string_buffer(n * esz)
    flags = ctypes.c_uint32(0)
    fn = getattr(lib(), "cft_augmented_" + name)
    check(fn(handle, fmt, a, b, r, e, n, ctypes.byref(flags)),
          "cft_augmented_" + name)
    return r.raw, e.raw, flags.value


# ---------------------------------------------------------------------
# The formatOf arithmetic operations, 754-2019 clause 5.4.1.
#
# The only entry points here that take TWO formats: the operands are
# read in `sfmt` and the result is rounded once into `dfmt`. Note the
# two c_int format arguments in the prototypes above, where every other
# arithmetic call has one - a binding that bound only the first would be
# a pointer-sized lie ctypes would tell without complaint, which is why
# the argtypes for these are written out rather than looped over the
# same list the same-format calls use.
#
# The output buffer is sized from the DESTINATION's element size and the
# operand buffers from the SOURCE's; on this ladder they differ by up to
# a factor of eight, so a caller who got that backwards would read past
# the end of its own array rather than get a wrong answer.
# ---------------------------------------------------------------------

FORMATOF = ("add", "sub", "mul", "div", "sqrt", "fma")

#: How many operands each reads - 5.4.1's own arities.
FORMATOF_ARITY = {"add": 2, "sub": 2, "mul": 2, "div": 2, "sqrt": 1,
                  "fma": 3}


def formatof(handle, name, sfmt, dfmt, rnd, ops, n, desz):
    """One formatOf operation over n elements.

    `ops` is a tuple of packed source-format buffers, one per operand
    the entry point reads; the result comes back as `n * desz` bytes of
    destination-format encodings with the call's flag word.
    """
    try:
        arity = FORMATOF_ARITY[name]
    except KeyError:
        raise ValueError(f"unknown formatOf operation {name!r}") from None
    if len(ops) != arity:
        raise ValueError(
            f"formatOf-{name} reads {arity} operand(s), got {len(ops)}")
    d = ctypes.create_string_buffer(n * desz)
    flags = ctypes.c_uint32(0)
    fn = getattr(lib(), "cft_formatof_" + name)
    check(fn(handle, sfmt, dfmt, rnd, *ops, d, n, ctypes.byref(flags),
             None),
          "cft_formatof_" + name)
    return d.raw, flags.value
