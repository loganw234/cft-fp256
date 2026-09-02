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
