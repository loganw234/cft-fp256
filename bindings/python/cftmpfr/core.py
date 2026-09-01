# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Context and Float: MPFR-shaped scalar arithmetic on libcft bits.

A ``Context`` is a precision, a rounding attribute and an open libcft
device; a ``Float`` is an IEEE interchange encoding (the bytes) tied
to a context. Every arithmetic result comes out of libcft - nothing
numeric is computed in Python. The only Python-side bit manipulation
in this file is the interchange CODEC (field packing between integer
significands and encodings), which is representation, not arithmetic:
it either reproduces a value exactly or refuses.

Conversions follow one rule, applied uniformly: exact when exactness
is possible, correctly rounded through gmpy2's own arithmetic when a
rounding is required and gmpy2 is present, and a loud refusal
otherwise. There is no third path - this package does not reimplement
rounding, because a second implementation of the semantics is exactly
how "identical bits" stops being true.

Rounding names are MPFR's: RNDN, RNDZ, RNDD, RNDU - plus RNDNA
(roundTiesToAway), which MPFR itself does not have: MPFR_RNDA rounds
EVERY inexact value away from zero, not just ties, so it is not the
same attribute. libcft implements true ties-to-away (the contract's
RMM), and this package exposes it; the one consequence is that
conversions that would have to ROUND under RNDNA (an over-long decimal
string, an int with too many bits) are refused, since gmpy2 cannot
perform them and this package will not guess. Rounding is accepted by
NAME only: the CFT and MPFR enumerations assign different numbers to
the same directions (CFT 2 is down, MPFR 2 is up), and accepting raw
integers would turn that difference into silent wrong answers.
"""

import math
import struct

from . import _lib

try:
    import gmpy2
except ImportError:  # optional, and its absence is a documented state
    gmpy2 = None


# ---------------------------------------------------------------------
# Formats. Geometry only - width, field sizes, exponent range. The
# names and codes are cft.h's; the precisions are the four the tile
# implements, and the only four this package accepts.
# ---------------------------------------------------------------------

class _FormatInfo:
    __slots__ = ("code", "name", "ieee_name", "width", "esz", "exp_w",
                 "man_w", "prec", "bias", "emin", "emax")

    def __init__(self, code, name, ieee_name, width, exp_w, man_w):
        self.code = code
        self.name = name                  # cft_format_name()'s answer
        self.ieee_name = ieee_name        # 754's name, and gmpy2.ieee()'s
        self.width = width
        self.esz = width // 8
        self.exp_w = exp_w
        self.man_w = man_w
        self.prec = man_w + 1
        self.bias = (1 << (exp_w - 1)) - 1
        self.emax = self.bias             # largest unbiased normal exponent
        self.emin = 1 - self.bias         # smallest unbiased normal exponent


_FP32 = _FormatInfo(_lib.FP32, "fp32", "binary32", 32, 8, 23)
_FP64 = _FormatInfo(_lib.FP64, "fp64", "binary64", 64, 11, 52)
_FP128 = _FormatInfo(_lib.FP128, "fp128", "binary128", 128, 15, 112)
_FP256 = _FormatInfo(_lib.FP256, "fp256", "binary256", 256, 19, 236)

_BY_PRECISION = {24: _FP32, 53: _FP64, 113: _FP128, 237: _FP256}
_BY_ALIAS = {f.ieee_name: f for f in _BY_PRECISION.values()}

SUPPORTED_PRECISIONS = tuple(sorted(_BY_PRECISION))

_ROUNDING = {"RNDN": _lib.RNE, "RNDZ": _lib.RTZ,
             "RNDD": _lib.RDN, "RNDU": _lib.RUP, "RNDNA": _lib.RMM}
_ROUNDING_NAME = {v: k for k, v in _ROUNDING.items()}

RNDN, RNDZ, RNDD, RNDU, RNDNA = "RNDN", "RNDZ", "RNDD", "RNDU", "RNDNA"


def _format_for(precision):
    if isinstance(precision, str):
        f = _BY_ALIAS.get(precision.lower())
        if f is not None:
            return f
    elif precision in _BY_PRECISION:
        return _BY_PRECISION[precision]
    raise ValueError(
        f"unsupported precision {precision!r}: this package drives IEEE "
        f"interchange formats only - precision 24 (binary32), 53 "
        f"(binary64), 113 (binary128) or 237 (binary256)")


def _round_for(rounding):
    if isinstance(rounding, str):
        code = _ROUNDING.get(rounding.upper())
        if code is not None:
            return code
    raise ValueError(
        f"unknown rounding {rounding!r}: use one of RNDN, RNDZ, RNDD, "
        f"RNDU, RNDNA (names, not numbers - the CFT and MPFR enums "
        f"number the directions differently)")


def _require_gmpy2(what):
    if gmpy2 is None:
        raise RuntimeError(
            f"{what} requires gmpy2, which is not installed. This package "
            f"refuses to reimplement rounding in Python - a second "
            f"implementation of the semantics is how bit-identity dies. "
            f"Either `pip install gmpy2`, or supply the value in a form "
            f"that needs no rounding (from_bits / an exactly "
            f"representable int or float).")


# ---------------------------------------------------------------------
# The interchange codec: encoding bits <-> (class, sign, m, 2^e).
# Pure field packing. Exact both ways or a refusal - never a rounding.
# ---------------------------------------------------------------------

def _decode(fi, bits):
    """-> (kind, sign, m, e) with value == (-1)^sign * m * 2^e for
    kind == 'finite' (m > 0); m, e are 0 for the other kinds."""
    sign = (bits >> (fi.width - 1)) & 1
    biased = (bits >> fi.man_w) & ((1 << fi.exp_w) - 1)
    frac = bits & ((1 << fi.man_w) - 1)
    if biased == (1 << fi.exp_w) - 1:
        return ("nan" if frac else "inf"), sign, 0, 0
    if biased == 0:
        if frac == 0:
            return "zero", sign, 0, 0
        return "finite", sign, frac, fi.emin - fi.man_w
    return "finite", sign, frac | (1 << fi.man_w), biased - fi.bias - fi.man_w


def _encode_exact(fi, sign, m, e):
    """Bits for (-1)^sign * m * 2^e (m > 0), or ValueError if that value
    is not representable exactly. The refusal carries the reason: the
    caller turns it into either a rounded gmpy2 route or a loud stop."""
    L = m.bit_length()
    E = e + L - 1                       # unbiased exponent of the leading bit
    if E > fi.emax:
        raise ValueError(f"exponent {E} above {fi.ieee_name}'s emax {fi.emax}")
    if E >= fi.emin:
        shift = fi.prec - L
        if shift >= 0:
            sig = m << shift
        else:
            if m & ((1 << -shift) - 1):
                raise ValueError(
                    f"needs {L} significand bits; {fi.ieee_name} has {fi.prec}")
            sig = m >> -shift
        return ((sign << (fi.width - 1))
                | ((E + fi.bias) << fi.man_w)
                | (sig & ((1 << fi.man_w) - 1)))
    # subnormal: the value must sit on the fixed grid 2^(emin - man_w)
    shift = e - (fi.emin - fi.man_w)
    if shift >= 0:
        k = m << shift
    else:
        if m & ((1 << -shift) - 1):
            raise ValueError(
                f"below {fi.ieee_name}'s subnormal grid 2^"
                f"{fi.emin - fi.man_w}")
        k = m >> -shift
    return (sign << (fi.width - 1)) | k


# ---------------------------------------------------------------------
# Float
# ---------------------------------------------------------------------

class Float:
    """One IEEE interchange encoding, tied to the Context that made it.

    The value IS the bytes: construction and conversion either
    preserve them exactly or say so. Arithmetic operators route
    through the owning context's device, so ``x + y`` is a cft_run
    and its flags land in ``x.context.last_flags`` like any other
    call's. Ordering and equality are the QUIET 754 predicates
    (unordered compares false, +0 == -0), which is why Float is
    deliberately unhashable: a thing where x != x cannot keep a
    dictionary's promises.
    """

    __slots__ = ("_ctx", "_enc")

    def __init__(self, ctx, enc):
        if len(enc) != ctx._fi.esz:
            raise ValueError(
                f"{ctx._fi.ieee_name} encoding is {ctx._fi.esz} bytes, "
                f"got {len(enc)}")
        self._ctx = ctx
        self._enc = bytes(enc)

    # -- representation access ---------------------------------------
    @property
    def context(self):
        return self._ctx

    def to_bytes(self):
        """The little-endian interchange encoding, verbatim."""
        return self._enc

    def to_bits(self):
        """The encoding as an unsigned integer."""
        return int.from_bytes(self._enc, "little")

    # -- classification (bit inspection, signals nothing) ------------
    def _kso(self):
        return _decode(self._ctx._fi, self.to_bits())

    @property
    def is_nan(self):
        return self._kso()[0] == "nan"

    @property
    def is_inf(self):
        return self._kso()[0] == "inf"

    @property
    def is_zero(self):
        return self._kso()[0] == "zero"

    @property
    def sign(self):
        """The sign BIT - 1 for anything negative, including -0."""
        return self._kso()[1]

    # -- conversions out ---------------------------------------------
    def to_int(self):
        """Truncate toward zero, exactly. NaN and infinity refuse."""
        kind, sign, m, e = self._kso()
        if kind in ("nan", "inf"):
            raise ValueError(f"cannot convert {kind} to int")
        if kind == "zero":
            return 0
        mag = m << e if e >= 0 else m >> -e
        return -mag if sign else mag

    def to_float(self):
        """A Python float. Exact whenever the value is representable in
        binary64 (always, for binary32/64 sources); otherwise rounded
        per the context's attribute through gmpy2, or refused."""
        kind, sign, m, e = self._kso()
        if kind == "nan":
            return math.nan
        if kind == "inf":
            return -math.inf if sign else math.inf
        if kind == "zero":
            return -0.0 if sign else 0.0
        try:
            b64 = _encode_exact(_FP64, sign, m, e)
        except ValueError:
            return self._ctx._narrow_via_gmpy2(self, _FP64, "to_float")
        return struct.unpack("<d", b64.to_bytes(8, "little"))[0]

    def to_str(self):
        """A decimal string that reads back to these exact bits at the
        same precision under RNDN (mpfr_get_str's n=0 guarantee). The
        digits come from the exact value via gmpy2; specials need no
        library at all."""
        kind, sign, _, _ = self._kso()
        neg = "-" if sign else ""
        if kind == "nan":
            return "nan"
        if kind == "inf":
            return neg + "inf"
        if kind == "zero":
            return neg + "0"
        _require_gmpy2("decimal-string conversion")
        digits, exp, _ = self.to_mpfr().digits(10)
        digits = digits.lstrip("-").rstrip("0") or "0"
        mant = digits[0] if len(digits) == 1 else digits[0] + "." + digits[1:]
        return f"{neg}{mant}e{exp - 1:+d}"

    def to_mpfr(self):
        """The same value as a gmpy2.mpfr, bit-exact, built from the
        integer significand - never through a decimal representation.
        The one lossy corner is spelled out rather than hidden: MPFR
        keeps neither NaN payloads nor a NaN sign, so any NaN becomes
        MPFR's one NaN. That matches how libcft's arithmetic treats
        NaNs (any NaN in, the canonical quiet NaN out), so values that
        came out of arithmetic round-trip; a hand-built payload does
        not survive MPFR because nothing survives MPFR's NaN."""
        _require_gmpy2("Float.to_mpfr")
        kind, sign, m, e = self._kso()
        if kind == "nan":
            return gmpy2.mpfr("nan")
        if kind == "inf":
            return gmpy2.mpfr("-inf" if sign else "inf")
        if kind == "zero":
            return gmpy2.mpfr("-0" if sign else "0")
        save = gmpy2.get_context()
        gmpy2.set_context(gmpy2.context(precision=self._ctx._fi.prec))
        try:
            x = gmpy2.mpfr(m)                       # <= prec bits: exact
            x = (gmpy2.mul_2exp(x, e) if e >= 0     # 2^e scaling: exact
                 else gmpy2.div_2exp(x, -e))
            return -x if sign else x
        finally:
            gmpy2.set_context(save)

    # -- printing ----------------------------------------------------
    def __repr__(self):
        fi = self._ctx._fi
        s = f"Float({fi.ieee_name}, 0x{self.to_bits():0{fi.esz * 2}x}"
        if gmpy2 is not None:
            s += f" ~ {self.to_str()}"
        return s + ")"

    # -- arithmetic operators (each one is a libcft call) ------------
    def _binop(self, other, method):
        try:
            other = self._ctx._coerce(other)
        except TypeError:
            return NotImplemented
        return method(self, other)

    def __add__(self, other):
        return self._binop(other, self._ctx.add)

    def __radd__(self, other):
        return self._binop(other, lambda a, b: self._ctx.add(b, a))

    def __sub__(self, other):
        return self._binop(other, self._ctx.sub)

    def __rsub__(self, other):
        return self._binop(other, lambda a, b: self._ctx.sub(b, a))

    def __mul__(self, other):
        return self._binop(other, self._ctx.mul)

    def __rmul__(self, other):
        return self._binop(other, lambda a, b: self._ctx.mul(b, a))

    def __truediv__(self, other):
        return self._binop(other, self._ctx.div)

    def __rtruediv__(self, other):
        return self._binop(other, lambda a, b: self._ctx.div(b, a))

    def __neg__(self):
        return self._ctx.neg(self)

    def __abs__(self):
        return self._ctx.abs(self)

    # -- comparison: the quiet 754 predicates, via the device --------
    def _pred(self, other, op, swap=False):
        try:
            other = self._ctx._coerce(other)
        except TypeError:
            return NotImplemented
        a, b = (other, self) if swap else (self, other)
        r = self._ctx._run2(op, a.to_bytes(), b.to_bytes())
        return not r.is_zero

    def __eq__(self, other):
        return self._pred(other, _lib.OP_CMPEQ)

    def __ne__(self, other):
        eq = self._pred(other, _lib.OP_CMPEQ)
        return NotImplemented if eq is NotImplemented else not eq

    def __lt__(self, other):
        return self._pred(other, _lib.OP_CMPLT)

    def __le__(self, other):
        return self._pred(other, _lib.OP_CMPLE)

    def __gt__(self, other):
        # the header is explicit: a > b IS cmplt with the operands
        # swapped, and no separate opcode exists or is needed
        return self._pred(other, _lib.OP_CMPLT, swap=True)

    def __ge__(self, other):
        return self._pred(other, _lib.OP_CMPLE, swap=True)

    __hash__ = None  # x != x for NaN; see the class docstring

    def same_bits(self, other):
        """Encoding identity - the comparison the tests and the parity
        claims are actually about. Distinct from ==, which is 754
        equality and calls -0 equal to +0 and NaN equal to nothing."""
        return isinstance(other, Float) and self._enc == other._enc


# ---------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------

class Context:
    """A precision, a rounding attribute, and an open libcft device.

    ``Context(237)`` (or ``Context("binary256")``) with no artifact is
    the software backend: no card, no driver, same bits. Passing
    ``artifact="path/to/tile.xclbin"`` opens the FPGA tile through the
    identical calls - that is cft_open's contract, and it is the whole
    adoption story: nothing above this line changes when the hardware
    arrives.

    Sticky flags accumulate in ``flags`` (OR of every call's flags,
    like MPFR's own flag model); ``last_flags`` is the word from the
    most recent call alone. ``clear_flags()`` resets the sticky word.

    NOT thread-safe, because a cft_device is not (cft.h is explicit).
    One Context per thread; they are cheap.
    """

    def __init__(self, precision, rounding="RNDN", artifact=None, index=0):
        self._fi = _format_for(precision)
        self._rnd = _round_for(rounding)
        self._dev = _lib.open_device(artifact, index)
        self.flags = 0
        self.last_flags = 0

    # -- lifecycle ---------------------------------------------------
    def close(self):
        dev, self._dev = self._dev, None
        _lib.close_device(dev)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass  # interpreter teardown: the OS reclaims the handle

    # -- introspection -----------------------------------------------
    @property
    def precision(self):
        return self._fi.prec

    @property
    def format(self):
        """cft.h's name for the format: 'fp32' ... 'fp256'."""
        return self._fi.name

    @property
    def rounding(self):
        return _ROUNDING_NAME[self._rnd]

    @property
    def backend(self):
        """'software' or the device runtime's name, from cft_get_caps."""
        return _lib.get_caps(self._dev).backend.decode("ascii", "replace")

    def __repr__(self):
        return (f"Context({self._fi.ieee_name}, precision={self._fi.prec}, "
                f"rounding={self.rounding}, backend={self.backend})")

    # -- construction ------------------------------------------------
    def __call__(self, value):
        """The ergonomic constructor, dispatching on type: int, float,
        str, Float (same precision), or gmpy2.mpfr. Each route is one
        of the explicit from_* constructors; this adds nothing but
        dispatch."""
        if isinstance(value, Float):
            return self._coerce(value)
        if isinstance(value, bool):
            raise TypeError("refusing bool: say 0 or 1 if you mean a number")
        if isinstance(value, int):
            return self.from_int(value)
        if isinstance(value, float):
            return self.from_float(value)
        if isinstance(value, str):
            return self.from_str(value)
        if gmpy2 is not None and isinstance(value, gmpy2.mpfr):
            return self.from_mpfr(value)
        raise TypeError(f"cannot make a Float from {type(value).__name__}")

    def from_bytes(self, enc):
        """Adopt an encoding verbatim. No validation beyond length -
        every bit pattern means something in 754."""
        return Float(self, enc)

    def from_bits(self, bits):
        fi = self._fi
        if not 0 <= bits < (1 << fi.width):
            raise ValueError(f"bits outside {fi.width}-bit range")
        return Float(self, bits.to_bytes(fi.esz, "little"))

    def zero(self, sign=0):
        return self.from_bits((1 << (self._fi.width - 1)) if sign else 0)

    def inf(self, sign=0):
        fi = self._fi
        bits = ((1 << fi.exp_w) - 1) << fi.man_w
        return self.from_bits(bits | (sign << (fi.width - 1)))

    def nan(self):
        """The contract's canonical quiet NaN: sign 0, quiet bit set,
        payload zero - the one NaN libcft arithmetic ever produces."""
        fi = self._fi
        return self.from_bits((((1 << fi.exp_w) - 1) << fi.man_w)
                              | (1 << (fi.man_w - 1)))

    def from_int(self, n):
        """Exact when n fits the significand; otherwise rounded per
        this context's attribute through gmpy2 (RNDNA refuses - MPFR
        cannot round ties-to-away, and this package will not). Like
        every conversion that is an operation in 754's sense, it sets
        last_flags - to 0 on the exact path. from_bits/from_bytes are
        the exceptions: adopting an encoding is not an operation, and
        they leave the flag state alone."""
        if not isinstance(n, int) or isinstance(n, bool):
            raise TypeError(f"from_int wants an int, got {type(n).__name__}")
        self.last_flags = 0            # the gmpy2 route overwrites this
        if n == 0:
            return self.zero(0)
        sign, m = (1, -n) if n < 0 else (0, n)
        try:
            return self.from_bits(_encode_exact(self._fi, sign, m, 0))
        except ValueError:
            return self._rounded_via_gmpy2(
                lambda: gmpy2.mpfr(n), f"int with {m.bit_length()} bits",
                known_inexact=True)

    def from_float(self, x):
        """Exact for binary64 and wider targets (53 bits always fit in
        113 or 237); binary32 narrows, so it rounds via gmpy2 or
        refuses. NaN becomes the canonical NaN - Python floats do not
        expose their payloads and the contract would canonicalise them
        at the first operation anyway."""
        if not isinstance(x, float):
            raise TypeError(f"from_float wants a float, got {type(x).__name__}")
        self.last_flags = 0            # the gmpy2 route overwrites this
        bits64 = struct.unpack("<Q", struct.pack("<d", x))[0]
        kind, sign, m, e = _decode(_FP64, bits64)
        if kind == "nan":
            return self.nan()
        if kind == "inf":
            return self.inf(sign)
        if kind == "zero":
            return self.zero(sign)
        try:
            return self.from_bits(_encode_exact(self._fi, sign, m, e))
        except ValueError:
            return self._rounded_via_gmpy2(
                lambda: gmpy2.mpfr(x), "this float into binary32",
                known_inexact=True)

    def from_str(self, s):
        """A decimal string, correctly rounded to this format in this
        context's attribute - by gmpy2/MPFR in the matching IEEE
        emulation context, never by a Python reimplementation. The
        flags of the PARSE (inexact, and over/underflow if the decimal
        lands outside the format) are surfaced in last_flags with
        MPFR's own flag definitions, which for a decimal parse are not
        in dispute the way tininess is."""
        if not isinstance(s, str):
            raise TypeError(f"from_str wants a str, got {type(s).__name__}")
        return self._rounded_via_gmpy2(
            lambda: gmpy2.mpfr(s), f"decimal string {s!r}")

    def from_mpfr(self, x):
        """A gmpy2.mpfr, adopted EXACTLY - integer significand and
        exponent, never a decimal detour. An mpfr whose value does not
        fit this format exactly is refused with instructions, because
        a conversion that silently rounded would make 'bit-exact
        interop' a lie precisely where it matters."""
        _require_gmpy2("Context.from_mpfr")
        if not isinstance(x, gmpy2.mpfr):
            raise TypeError(f"from_mpfr wants gmpy2.mpfr, "
                            f"got {type(x).__name__}")
        self.last_flags = 0            # exact or refused: never a flag
        if gmpy2.is_nan(x):
            return self.nan()
        sign = 1 if gmpy2.is_signed(x) else 0
        if gmpy2.is_infinite(x):
            return self.inf(sign)
        if gmpy2.is_zero(x):
            return self.zero(sign)
        m, e = x.as_mantissa_exp()                  # exact: x == m * 2^e
        m, e = int(m), int(e)
        if m < 0:
            m = -m
        try:
            return self.from_bits(_encode_exact(self._fi, sign, m, e))
        except ValueError as err:
            raise ValueError(
                f"mpfr value does not fit {self._fi.ieee_name} exactly "
                f"({err}). from_mpfr never rounds; round it in gmpy2 "
                f"first - e.g. compute it inside gmpy2.ieee"
                f"({self._fi.width}) - and convert the result.") from None

    # -- the gmpy2 rounded route (shared by every inexact conversion) --
    _GMPY2_ROUND = {_lib.RNE: "RoundToNearest", _lib.RTZ: "RoundToZero",
                    _lib.RDN: "RoundDown", _lib.RUP: "RoundUp"}

    def _rmm_refusal(self, what):
        return ValueError(
            f"{what} is inexact and this context rounds RNDNA "
            f"(ties-to-away), which MPFR does not implement - MPFR_RNDA "
            f"rounds every inexact value away, not just ties, and this "
            f"package will not substitute its own rounding. Convert under "
            f"an RNDN context of the same precision (Floats of equal "
            f"precision mix freely), or supply the value exactly "
            f"(from_bits, or an int/float that fits).")

    def _rounded_via_gmpy2(self, build, what, known_inexact=False):
        """Round a conversion through gmpy2's IEEE emulation of this
        format, in this context's attribute. Under RNDNA the value is
        parsed truncated instead, and adopted only if that changed
        nothing - an EXACT decimal is fine under any attribute; one
        that needs rounding refuses, because MPFR cannot round
        ties-to-away and a substitute rounding would be a second
        implementation of the semantics. Callers that already KNOW the
        conversion is inexact say so, which puts the RNDNA refusal
        ahead of the gmpy2-missing complaint: installing gmpy2 would
        not have helped, and an error message should not imply it
        would."""
        rmm = self._rnd == _lib.RMM
        if rmm and known_inexact:
            raise self._rmm_refusal(what)
        _require_gmpy2(f"rounding {what}")
        save = gmpy2.get_context()
        ctx = gmpy2.ieee(self._fi.width)
        ctx.round = (gmpy2.RoundToZero if rmm
                     else getattr(gmpy2, self._GMPY2_ROUND[self._rnd]))
        gmpy2.set_context(ctx)
        try:
            y = build()
            fl = 0
            if ctx.inexact:
                fl |= _lib.FLAG_INEXACT
            if ctx.overflow:
                fl |= _lib.FLAG_OVERFLOW
            if ctx.underflow:
                fl |= _lib.FLAG_UNDERFLOW
        finally:
            gmpy2.set_context(save)
        if rmm and fl:
            raise self._rmm_refusal(what)
        result = self.from_mpfr(y)     # exact by construction; zeroes flags
        self.last_flags = fl           # ... so the parse's word goes last
        self.flags |= fl
        return result

    def _narrow_via_gmpy2(self, x, target_fi, what):
        """Round Float x down to a NARROWER binary format via gmpy2 and
        hand back a Python float (only binary64 is ever asked for).
        The caller established the value is inexact in the target, so
        under RNDNA this refuses outright."""
        _require_gmpy2(what)
        if self._rnd == _lib.RMM:
            raise self._rmm_refusal(what)
        save = gmpy2.get_context()
        ctx = gmpy2.ieee(target_fi.width)
        ctx.round = getattr(gmpy2, self._GMPY2_ROUND[self._rnd])
        gmpy2.set_context(ctx)
        try:
            y = gmpy2.mpfr(x.to_mpfr())
        finally:
            gmpy2.set_context(save)
        return float(y)

    # -- flags -------------------------------------------------------
    def clear_flags(self):
        self.flags = 0

    def flag_names(self, flags=None):
        """Names for a flag word; defaults to the sticky word."""
        return _lib.flag_names(self.flags if flags is None else flags)

    # -- scalar arithmetic (each method is one libcft call) ----------
    def _coerce(self, v):
        if isinstance(v, Float):
            if v._ctx._fi.prec != self._fi.prec:
                raise ValueError(
                    f"mixed precisions: {v._ctx._fi.ieee_name} operand in "
                    f"a {self._fi.ieee_name} context. Convert explicitly - "
                    f"implicit widening would have to choose semantics "
                    f"for you.")
            return v
        if isinstance(v, bool):
            raise TypeError("refusing bool as a number")
        if isinstance(v, int):
            return self.from_int(v)
        if isinstance(v, float):
            return self.from_float(v)
        if gmpy2 is not None and isinstance(v, gmpy2.mpfr):
            return self.from_mpfr(v)
        raise TypeError(f"cannot use {type(v).__name__} as an operand")

    def _finish(self, out, fl):
        self.last_flags = fl
        self.flags |= fl
        return Float(self, out)

    def _run2(self, op, a_enc, b_enc):
        """A two-operand opcode in the a,b slots (the comparison
        predicates). Flags are recorded like any other call's: the
        quiet predicates signal nothing except invalid on a signaling
        NaN (754 5.11), and swallowing that one signal would hide the
        only thing they ever say."""
        fi = self._fi
        out, fl = _lib.run(self._dev, op, fi.code, self._rnd,
                           a_enc, b_enc, None, 1, fi.esz)
        return self._finish(out, fl)

    def add(self, x, y):
        """x + y. Note the operand slots: cft.h's ADD reads a and c."""
        x, y = self._coerce(x), self._coerce(y)
        out, fl = _lib.run(self._dev, _lib.OP_ADD, self._fi.code, self._rnd,
                           x.to_bytes(), None, y.to_bytes(), 1, self._fi.esz)
        return self._finish(out, fl)

    def sub(self, x, y):
        x, y = self._coerce(x), self._coerce(y)
        out, fl = _lib.run(self._dev, _lib.OP_SUB, self._fi.code, self._rnd,
                           x.to_bytes(), None, y.to_bytes(), 1, self._fi.esz)
        return self._finish(out, fl)

    def mul(self, x, y):
        x, y = self._coerce(x), self._coerce(y)
        out, fl = _lib.run(self._dev, _lib.OP_MUL, self._fi.code, self._rnd,
                           x.to_bytes(), y.to_bytes(), None, 1, self._fi.esz)
        return self._finish(out, fl)

    def fma(self, x, y, z):
        """x*y + z, one rounding - the operation the tile is built
        around, and MPFR's fma semantics exactly."""
        x, y, z = self._coerce(x), self._coerce(y), self._coerce(z)
        out, fl = _lib.run(self._dev, _lib.OP_FMA, self._fi.code, self._rnd,
                           x.to_bytes(), y.to_bytes(), z.to_bytes(), 1,
                           self._fi.esz)
        return self._finish(out, fl)

    def div(self, x, y):
        """x / y, correctly rounded - libcft's seed + Newton + exact
        residual sequence, not a shortcut."""
        x, y = self._coerce(x), self._coerce(y)
        out, fl = _lib.div(self._dev, self._fi.code, self._rnd,
                           x.to_bytes(), y.to_bytes(), 1, self._fi.esz)
        return self._finish(out, fl)

    def sqrt(self, x):
        x = self._coerce(x)
        out, fl = _lib.sqrt(self._dev, self._fi.code, self._rnd,
                            x.to_bytes(), 1, self._fi.esz)
        return self._finish(out, fl)

    def neg(self, x):
        """Sign flip, 754 5.5.1: quiet even on signaling NaNs, payload
        preserved - deliberately NOT 0 - x."""
        x = self._coerce(x)
        out, fl = _lib.run(self._dev, _lib.OP_NEG, self._fi.code, self._rnd,
                           x.to_bytes(), None, None, 1, self._fi.esz)
        return self._finish(out, fl)

    def abs(self, x):
        x = self._coerce(x)
        out, fl = _lib.run(self._dev, _lib.OP_ABS, self._fi.code, self._rnd,
                           x.to_bytes(), None, None, 1, self._fi.esz)
        return self._finish(out, fl)
