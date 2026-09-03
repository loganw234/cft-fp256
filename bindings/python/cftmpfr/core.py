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
        # Specials are lexed here, not by gmpy2. to_str emits "nan",
        # "inf", "-inf" and the two zeros without a library, so the
        # parse has to read them back without one - and gmpy2 2.1.2
        # refuses every spelling of inf and nan ("invalid digits")
        # where 2.2 accepts them. Recognising a token is not rounding;
        # what follows the token still goes through MPFR. Whitespace
        # is stripped for the same reason: 2.1.2 rejects it trailing,
        # 2.2 accepts it either side, and a parse should not depend on
        # which one is installed.
        t = s.strip()
        neg = t.startswith("-")
        body = t[1:] if t[:1] in "+-" else t
        low = body.lower()
        if low == "nan":
            self.last_flags = 0
            return self.nan()
        if low in ("inf", "infinity"):
            self.last_flags = 0
            return self.inf(1 if neg else 0)
        # A leading plus carries no information and gmpy2 2.1.2 refuses
        # "+0" with "invalid digits", so it is dropped here. A leading
        # MINUS is not: under a directed attribute the rounding of -x is
        # not the negation of the rounding of x, so the sign must reach
        # MPFR with the digits.
        if t.startswith("+"):
            t = t[1:]
        result = self._rounded_via_gmpy2(
            lambda: gmpy2.mpfr(t), f"decimal string {s!r}")
        # The sign of a zero comes from the DECIMAL, not from gmpy2.
        # gmpy2 2.1.2 (MPFR 4.1.0) parses "-0" inside the ieee() context
        # this method rounds in to a zero with no sign at all, and
        # from_mpfr takes the sign from is_signed, so every zero parsed
        # from a negative decimal lost its sign on that version (2.2.1
        # is correct). 754 settles what the answer is: rounding never
        # changes a sign, so a negative decimal that is zero, or that
        # underflows to zero in this format, is -0 in every attribute.
        # The parse flags stand; only the sign bit is restored.
        if result.is_zero and neg:
            flags = self.last_flags
            result = self.zero(1)
            self.last_flags = flags
        return result

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

    # ---- the phase-1 transcendentals (ABI 0.3) -------------------
    #
    # Correctly rounded at this context's precision under this
    # context's attribute, with the 754-2019 clause 9.2.1 special
    # values and exact flags - so gmpy2's exp/log/pow at a matching
    # IEEE context return the same bits, and this package's whole
    # claim extends to them. The exact cases raise nothing: exp only
    # at zero, log only at one, exp2 at an integer, log2 at a power of
    # two, log10 at a representable power of ten, pow at a dyadic
    # result, hypot at a perfect square.

    def _transcend1(self, name, x):
        x = self._coerce(x)
        out, fl = _lib.transcend(self._dev, name, self._fi.code, self._rnd,
                                 x.to_bytes(), None, 1, self._fi.esz)
        return self._finish(out, fl)

    def _transcend2(self, name, x, y):
        x, y = self._coerce(x), self._coerce(y)
        out, fl = _lib.transcend(self._dev, name, self._fi.code, self._rnd,
                                 x.to_bytes(), y.to_bytes(), 1,
                                 self._fi.esz)
        return self._finish(out, fl)

    def _transcend_int(self, name, x, n):
        """One of the three whose second operand is an INTEGER. n is
        taken as a Python int and passed as int64, so the whole range
        is available and nothing is asked whether it is integral."""
        x = self._coerce(x)
        out, fl = _lib.transcend(self._dev, name, self._fi.code, self._rnd,
                                 x.to_bytes(), None, 1, self._fi.esz,
                                 ns=(int(n),))
        return self._finish(out, fl)

    def exp(self, x):
        """e ** x, correctly rounded."""
        return self._transcend1("exp", x)

    def expm1(self, x):
        """exp(x) - 1, correctly rounded; expm1(-0) is -0."""
        return self._transcend1("expm1", x)

    def exp2(self, x):
        """2 ** x, exact for an integer argument."""
        return self._transcend1("exp2", x)

    def log(self, x):
        """The natural logarithm. log(+-0) is -inf with divideByZero,
        a negative operand is invalid."""
        return self._transcend1("log", x)

    def log1p(self, x):
        """log(1 + x), correctly rounded; log1p(-0) is -0 and
        log1p(-1) is -inf with divideByZero."""
        return self._transcend1("log1p", x)

    def log2(self, x):
        """Base-two logarithm, exact at the powers of two."""
        return self._transcend1("log2", x)

    def log10(self, x):
        """Base-ten logarithm, exact at the powers of ten the format
        represents."""
        return self._transcend1("log10", x)

    def pow(self, x, y):
        """x ** y - 754-2019's `pow`, so pow(x, +-0) is 1 for any x
        including a quiet NaN and pow(1, y) is 1 for any y."""
        return self._transcend2("pow", x, y)

    def hypot(self, x, y):
        """sqrt(x^2 + y^2) computed as if with unbounded range and
        rounded once; an infinite operand gives +inf even against a
        quiet NaN."""
        return self._transcend2("hypot", x, y)

    # ---- the phase-2 trigonometrics (ABI 0.4) --------------------
    #
    # The eleven whose argument reduction is exact, so they need no pi
    # to hundreds of thousands of bits: sinPi reduces by x mod 2 on a
    # dyadic operand, and the inverses have nothing to reduce. Their
    # exact cases are a much larger table than the exponentials' -
    # sinPi and cosPi at every half-integer, tanPi at every
    # quarter-integer, asinPi(+-1) = +-1/2, acosPi(0) = 1/2,
    # atanPi(+-1) = +-1/4 and atan2Pi on every axis and diagonal - and
    # every one of them raises nothing at all.

    def sinpi(self, x):
        """sin(pi x). Exact at the half-integers: sinPi(n) is a zero
        with the sign of n, sinPi(n + 1/2) is +-1."""
        return self._transcend1("sinpi", x)

    def cospi(self, x):
        """cos(pi x). cosPi(n) is (-1)^n and cosPi(n + 1/2) is +0."""
        return self._transcend1("cospi", x)

    def tanpi(self, x):
        """tan(pi x), which is sinPi/cosPi in every respect including
        the signs - tanPi(1) is -0. The half-integers are poles:
        +-infinity with divideByZero. It cannot overflow."""
        return self._transcend1("tanpi", x)

    def asin(self, x):
        """asin(x) in radians; |x| > 1 is invalid. Exact only at +-0."""
        return self._transcend1("asin", x)

    def acos(self, x):
        """acos(x) in radians, in [0, pi]; exact only at acos(1)."""
        return self._transcend1("acos", x)

    def atan(self, x):
        """atan(x) in radians; atan(+-inf) is +-pi/2."""
        return self._transcend1("atan", x)

    def asinpi(self, x):
        """asin(x)/pi. Exact at +-0 and at +-1, where it is +-1/2."""
        return self._transcend1("asinpi", x)

    def acospi(self, x):
        """acos(x)/pi. Exact at 1 (+0), at +-0 (1/2) and at -1 (1)."""
        return self._transcend1("acospi", x)

    def atanpi(self, x):
        """atan(x)/pi. Exact at +-0, +-1 (+-1/4) and +-inf (+-1/2)."""
        return self._transcend1("atanpi", x)

    def atan2(self, y, x):
        """atan2(y, x) in radians, y first as C has it. atan2(+-0, -0)
        is +-pi, which is the row of that table most often missed."""
        return self._transcend2("atan2", y, x)

    def atan2pi(self, y, x):
        """atan2(y, x)/pi. Exact on every axis and diagonal - 0, +-1/4,
        +-1/2, +-3/4, +-1 - where the radian form is an inexact
        rounding of a multiple of pi."""
        return self._transcend2("atan2pi", y, x)

    # ---- the phase-3 radian trigonometry and the hyperbolics (ABI 0.5)
    #
    # sin, cos and tan take a RADIAN argument and are reduced against pi
    # inside the library, at any magnitude the format holds; the six
    # hyperbolics need no reduction. Every one is correctly rounded like
    # the rest, and their exact cases are the zeros: sin, tan, sinh, tanh,
    # asinh and atanh at +-0, cos and cosh at 0 (giving 1), acosh at 1
    # (giving +0). That is a theorem (Hermite-Lindemann), so every other
    # result raises inexact.

    def sin(self, x):
        """sin(x), x in radians. Exact only at +-0; sin(+-inf) is
        invalid."""
        return self._transcend1("sin", x)

    def cos(self, x):
        """cos(x) in radians. cos(+-0) = 1 is the only exact case;
        cos(+-inf) is invalid."""
        return self._transcend1("cos", x)

    def tan(self, x):
        """tan(x) in radians. Exact only at +-0. No representable
        argument is a pole (an odd multiple of pi/2 is irrational), so it
        never signals divideByZero - but it can overflow."""
        return self._transcend1("tan", x)

    def sinh(self, x):
        """sinh(x). Odd, exact only at +-0, sinh(+-inf) = +-inf, and it
        overflows for a large argument like any exponential."""
        return self._transcend1("sinh", x)

    def cosh(self, x):
        """cosh(x). Even, never below 1, exact only at cosh(+-0) = 1."""
        return self._transcend1("cosh", x)

    def tanh(self, x):
        """tanh(x). Odd, exact at +-0, and tanh(+-inf) = +-1 EXACTLY - a
        limit that happens to be representable, raising nothing."""
        return self._transcend1("tanh", x)

    def asinh(self, x):
        """asinh(x). Odd, exact only at +-0; asinh(+-inf) = +-inf."""
        return self._transcend1("asinh", x)

    def acosh(self, x):
        """acosh(x) on [1, +inf). acosh(1) = +0 exactly; every x below 1
        is invalid, zeros, negatives and -inf included."""
        return self._transcend1("acosh", x)


    # ---- the rest of table 9.1 (part of the 0.6 step) ------------
    #
    # With these ten the drop-in reaches every operation 754-2019 table
    # 9.1 lists for the binary formats, and every one of them is
    # correctly rounded. Three rows follow the STANDARD where MPFR does
    # not, so a caller who swapped this context for gmpy2's would see
    # them move: rSqrt(-0) is -infinity here and +infinity there;
    # powr(1, qNaN) is a quiet NaN here and 1 there; and compound(x, 0)
    # for x below -1 is invalid rather than 1. cft.h and
    # docs/TRANSCENDENTALS.md carry the readings.

    def exp2m1(self, x):
        """2**x - 1. Exact at EVERY integer argument, which is the widest
        exact table in the set; expm1's cancellation-free form in
        another base, so it is not exp2(x) - 1."""
        return self._transcend1("exp2m1", x)

    def exp10(self, x):
        """10**x. Exact at the non-negative integers whose 5^n fits the
        format; a negative power of ten is not a dyadic rational."""
        return self._transcend1("exp10", x)

    def exp10m1(self, x):
        """10**x - 1, exact where 10^n - 1 fits; exp10m1(-0) is -0."""
        return self._transcend1("exp10m1", x)

    def log2p1(self, x):
        """log2(1 + x). Exact where 1 + x is a power of two, and 1 + x
        is formed exactly on the encoding rather than in the format -
        which is the whole reason this is not log2(1 + x)."""
        return self._transcend1("log2p1", x)

    def log10p1(self, x):
        """log10(1 + x), exact where 1 + x is a power of ten."""
        return self._transcend1("log10p1", x)

    def rsqrt(self, x):
        """1/sqrt(x). Exact at the even powers of two; rSqrt(+-0) is
        +-infinity with divideByZero - the sign SURVIVES, which is
        9.2.1's row and not MPFR's."""
        return self._transcend1("rsqrt", x)

    def powr(self, x, y):
        """x**y as exp(y log x), so a negative base is invalid for every
        exponent and powr(qNaN, 0) is a NaN where pow(qNaN, 0) is 1."""
        return self._transcend2("powr", x, y)

    def pown(self, x, n):
        """x**n for an INTEGER n. pown(x, 0) is 1 for any x that is not
        a signaling NaN, and the zero and infinity rows split on the
        parity of n."""
        return self._transcend_int("pown", x, n)

    def compound(self, x, n):
        """(1 + x)**n for an integer n, on [-1, +inf]. compound(x, 0) is
        1 for x >= -1 or a quiet NaN - and INVALID below -1."""
        return self._transcend_int("compound", x, n)

    def rootn(self, x, n):
        """x**(1/n) for a nonzero integer n. rootn(x, 1) is x exactly and
        rootn(x, 2) is sqrt(x) on every input but -0, where 9.2.1's own
        NOTE says they differ: rootn(-0, 2) is +0."""
        return self._transcend_int("rootn", x, n)

    def atanh(self, x):
        """atanh(x) on (-1, 1). Exact only at +-0; atanh(+-1) is +-inf
        with divideByZero; |x| > 1 is invalid, infinities included."""
        return self._transcend1("atanh", x)

    # ---- the augmented arithmetic operations (754-2019 9.5) ------
    #
    # The only members here that return a PAIR, and the only ones that
    # ignore this context's rounding attribute - 9.5 fixes the rounding
    # to roundTiesTowardZero, which is not one of the five and which no
    # other operation in this package can be asked for.
    #
    # What they are for: r is the operation rounded and e is the error
    # rounding made, so r + e is the exact result the format cannot
    # hold. That is the primitive under compensated summation, exact
    # dot products and double-double arithmetic - written by hand as
    # TwoSum and Dekker splitting everywhere else, correct only under
    # assumptions a compiler is free to break, and here a library call
    # with the standard behind it.
    #
    # gmpy2 has no equivalent: MPFR has no roundTiesTowardZero, so this
    # is one of the few places where this package is not a drop-in for
    # something that already exists but an addition to it.

    def _augmented(self, name, x, y):
        x, y = self._coerce(x), self._coerce(y)
        r, e, fl = _lib.augmented(self._dev, name, self._fi.code,
                                  x.to_bytes(), y.to_bytes(), 1,
                                  self._fi.esz)
        self.last_flags = fl
        self.flags |= fl
        return Float(self, r), Float(self, e)

    def augmented_add(self, x, y):
        """(r, e) with r = x + y rounded ties-toward-zero and e the
        exact residual. e is always representable here; it is a zero
        with r's SIGN when the sum is exact, and a subnormal e raises
        underflow with no inexact."""
        return self._augmented("add", x, y)

    def augmented_sub(self, x, y):
        """(r, e) for x - y, on every term of augmentedAddition."""
        return self._augmented("sub", x, y)

    def augmented_mul(self, x, y):
        """(r, e) with r = x * y rounded ties-toward-zero. The one case
        where r + e is not exact is a residual below the subnormal grid,
        which arrives rounded with underflow AND inexact raised."""
        return self._augmented("mul", x, y)

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
