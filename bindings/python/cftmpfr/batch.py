# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Whole-array operations: one libcft call per op, zero Python per element.

This module is where the acceleration lives. The scalar path in
core.py crosses the ctypes boundary once per operation per value; a
pure-gmpy2 loop crosses the interpreter's dispatch machinery the same
way. Here the interpreter is crossed ONCE and libcft's C loop does the
elements - and on the device backend the same single call is a DMA and
a kernel launch. Batch semantics are the header's: element i of the
output depends on element i of the inputs, the returned flag word is
the OR over every element (padding never contributes), and the tests
prove batch output is bit-identical to a loop of scalar calls.

Operands may be, in any mix:

* a ``list``/``tuple`` of Float (or of ints/floats, coerced through
  the context's exact-or-refuse constructors),
* ``bytes``/``bytearray``/``memoryview`` holding packed little-endian
  encodings (length a multiple of the element size),
* a numpy ndarray, when numpy is installed: any dtype whose itemsize
  equals the element size (float32/float64 for those formats, or a
  void/structured dtype such as ``V32`` for binary256), or a uint8
  array of packed encodings,
* a single ``Float``, which broadcasts - the Horner-step coefficient
  case. Only a Float broadcasts: a one-element bytes object is a
  sequence of one, because a rule you have to guess is a bug factory.

The result mirrors the container of the first sequence operand (list
in, list out; bytes in, bytes out; ndarray in, ndarray of the same
dtype and shape out) and arrives with the call's flag word:

    out, flags = batch.fma(ctx, xs, ys, zs)

``tree_sum`` and ``tree_dot`` are the contract's REDUCTIONS: the fixed
index-shaped binary tree of docs/DETERMINISM.md, identical bits on
one tile or four. They are deliberately not called "sum": MPFR's
mpfr_sum is a single correctly-rounded operation with different
results, and a name that invited the confusion would cost somebody a
week.
"""

from . import _lib
from .core import Float

try:
    import numpy as _np
except ImportError:  # optional; arrays simply cannot arrive without it
    _np = None


def _as_operand(ctx, x):
    """-> (payload, n_or_None, mirror) where payload is packed bytes
    (or a bytes-like buffer), n is the element count (None for a
    broadcast scalar), and mirror is a callable rebuilding this
    operand's container style from result bytes (None if this operand
    should not shape the output)."""
    esz = ctx._fi.esz

    if isinstance(x, Float):
        if x._ctx._fi.prec != ctx._fi.prec:
            raise ValueError(
                f"mixed precisions: {x._ctx._fi.ieee_name} Float in a "
                f"{ctx._fi.ieee_name} batch")
        return x.to_bytes(), None, None

    if isinstance(x, (bytes, bytearray, memoryview)):
        buf = bytes(x)
        if len(buf) % esz:
            raise ValueError(
                f"{len(buf)} bytes is not a whole number of "
                f"{ctx._fi.ieee_name} encodings ({esz} bytes each)")
        return buf, len(buf) // esz, lambda out: out

    if isinstance(x, (list, tuple)):
        encs = [ctx._coerce(v).to_bytes() for v in x]
        return (b"".join(encs), len(encs),
                lambda out: [Float(ctx, out[i * esz:(i + 1) * esz])
                             for i in range(len(out) // esz)])

    if _np is not None and isinstance(x, _np.ndarray):
        if x.dtype.itemsize == esz:
            n = x.size
            mirror = (lambda out, dt=x.dtype, sh=x.shape:
                      _np.frombuffer(out, dtype=dt).reshape(sh).copy())
        elif x.dtype.itemsize == 1:
            if x.size % esz:
                raise ValueError(
                    f"uint8 array of {x.size} bytes is not a whole number "
                    f"of {esz}-byte {ctx._fi.ieee_name} encodings")
            n = x.size // esz
            mirror = (lambda out, dt=x.dtype:
                      _np.frombuffer(out, dtype=dt).copy())
        else:
            raise ValueError(
                f"dtype {x.dtype} has {x.dtype.itemsize}-byte elements; a "
                f"{ctx._fi.ieee_name} batch needs {esz}-byte elements "
                f"(e.g. dtype 'V{esz}'), or uint8 holding packed "
                f"encodings. A different float width is a different "
                f"format - convert explicitly.")
        # tobytes() copies (and linearises any non-contiguous view).
        # The copy runs at memory bandwidth and the arithmetic does
        # not; measuring before optimising said leave it alone.
        return x.tobytes(), n, mirror

    raise TypeError(f"cannot use {type(x).__name__} as a batch operand")


def _normalise(ctx, operands):
    """Resolve counts and broadcasts across one call's operands.
    Returns (payload list, n, mirror-of-first-sequence-operand)."""
    parts = [_as_operand(ctx, x) for x in operands]
    counts = {n for _, n, _ in parts if n is not None}
    if not counts:
        raise TypeError(
            "every operand is a broadcast scalar; batch needs at least "
            "one sequence to set the element count (for scalars, the "
            "Context methods are the right call)")
    if len(counts) != 1:
        raise ValueError(f"operand lengths disagree: {sorted(counts)}")
    n = counts.pop()
    payloads = []
    mirror = None
    for buf, cnt, mk in parts:
        if cnt is None:
            buf = buf * n          # broadcast: replicate the encoding
        payloads.append(buf)
        if mirror is None and mk is not None:
            mirror = mk
    return payloads, n, mirror


def _finish(ctx, out, fl, mirror):
    ctx.last_flags = fl
    ctx.flags |= fl
    return mirror(out), fl


# ---------------------------------------------------------------------
# Elementwise. Operand slots follow cft.h exactly: ADD/SUB read a and
# c (b unused), MUL reads a and b (c unused), FMA reads all three.
# ---------------------------------------------------------------------

def add(ctx, x, y):
    """out[i] = x[i] + y[i]. Returns (results, flag word)."""
    (bx, by), n, mirror = _normalise(ctx, (x, y))
    out, fl = _lib.run(ctx._dev, _lib.OP_ADD, ctx._fi.code, ctx._rnd,
                       bx, None, by, n, ctx._fi.esz)
    return _finish(ctx, out, fl, mirror)


def sub(ctx, x, y):
    """out[i] = x[i] - y[i]."""
    (bx, by), n, mirror = _normalise(ctx, (x, y))
    out, fl = _lib.run(ctx._dev, _lib.OP_SUB, ctx._fi.code, ctx._rnd,
                       bx, None, by, n, ctx._fi.esz)
    return _finish(ctx, out, fl, mirror)


def mul(ctx, x, y):
    """out[i] = x[i] * y[i]."""
    (bx, by), n, mirror = _normalise(ctx, (x, y))
    out, fl = _lib.run(ctx._dev, _lib.OP_MUL, ctx._fi.code, ctx._rnd,
                       bx, by, None, n, ctx._fi.esz)
    return _finish(ctx, out, fl, mirror)


def fma(ctx, x, y, z):
    """out[i] = x[i]*y[i] + z[i], one rounding (the exact product is
    never rounded on its own) - mpfr_fma element by element."""
    (bx, by, bz), n, mirror = _normalise(ctx, (x, y, z))
    out, fl = _lib.run(ctx._dev, _lib.OP_FMA, ctx._fi.code, ctx._rnd,
                       bx, by, bz, n, ctx._fi.esz)
    return _finish(ctx, out, fl, mirror)


def div(ctx, x, y):
    """out[i] = x[i] / y[i], correctly rounded via libcft's fixed
    seed/Newton/residual sequence - some 25-30 elementwise passes per
    call, the honest price of correct rounding built from an FMA. On
    the software backend that price is real; on the tile the passes
    run at hardware speed."""
    (bx, by), n, mirror = _normalise(ctx, (x, y))
    out, fl = _lib.div(ctx._dev, ctx._fi.code, ctx._rnd, bx, by,
                       n, ctx._fi.esz)
    return _finish(ctx, out, fl, mirror)


def sqrt(ctx, x):
    """out[i] = squareRoot(x[i]), correctly rounded; same sequence
    story as div."""
    (bx,), n, mirror = _normalise(ctx, (x,))
    out, fl = _lib.sqrt(ctx._dev, ctx._fi.code, ctx._rnd, bx,
                        n, ctx._fi.esz)
    return _finish(ctx, out, fl, mirror)


# ---------------------------------------------------------------------
# The transcendentals, one C call for the whole array. Every
# one is correctly rounded, so the array answer is the scalar answer
# element by element - there is no vectorised approximation here to
# differ from a scalar path, which is a property worth having and one
# most math libraries cannot offer.
# ---------------------------------------------------------------------

def _t1(ctx, name, x):
    (bx,), n, mirror = _normalise(ctx, (x,))
    out, fl = _lib.transcend(ctx._dev, name, ctx._fi.code, ctx._rnd, bx,
                             None, n, ctx._fi.esz)
    return _finish(ctx, out, fl, mirror)


def _t2(ctx, name, x, y):
    (bx, by), n, mirror = _normalise(ctx, (x, y))
    out, fl = _lib.transcend(ctx._dev, name, ctx._fi.code, ctx._rnd, bx, by,
                             n, ctx._fi.esz)
    return _finish(ctx, out, fl, mirror)


def exp(ctx, x):
    """out[i] = exp(x[i]), correctly rounded."""
    return _t1(ctx, "exp", x)


def expm1(ctx, x):
    """out[i] = exp(x[i]) - 1."""
    return _t1(ctx, "expm1", x)


def exp2(ctx, x):
    """out[i] = 2 ** x[i]."""
    return _t1(ctx, "exp2", x)


def log(ctx, x):
    """out[i] = log(x[i])."""
    return _t1(ctx, "log", x)


def log1p(ctx, x):
    """out[i] = log(1 + x[i])."""
    return _t1(ctx, "log1p", x)


def log2(ctx, x):
    """out[i] = log2(x[i])."""
    return _t1(ctx, "log2", x)


def log10(ctx, x):
    """out[i] = log10(x[i])."""
    return _t1(ctx, "log10", x)


def pow(ctx, x, y):
    """out[i] = x[i] ** y[i]."""
    return _t2(ctx, "pow", x, y)


def hypot(ctx, x, y):
    """out[i] = sqrt(x[i]^2 + y[i]^2)."""
    return _t2(ctx, "hypot", x, y)


# The phase-2 trigonometrics, on the same footing: one C call for the
# array, and the array answer IS the scalar answer element by element,
# because correct rounding leaves no vectorised approximation to drift.

def sinpi(ctx, x):
    """out[i] = sin(pi * x[i])."""
    return _t1(ctx, "sinpi", x)


def cospi(ctx, x):
    """out[i] = cos(pi * x[i])."""
    return _t1(ctx, "cospi", x)


def tanpi(ctx, x):
    """out[i] = tan(pi * x[i])."""
    return _t1(ctx, "tanpi", x)


def asin(ctx, x):
    """out[i] = asin(x[i]), in radians."""
    return _t1(ctx, "asin", x)


def acos(ctx, x):
    """out[i] = acos(x[i]), in radians."""
    return _t1(ctx, "acos", x)


def atan(ctx, x):
    """out[i] = atan(x[i]), in radians."""
    return _t1(ctx, "atan", x)


def asinpi(ctx, x):
    """out[i] = asin(x[i]) / pi."""
    return _t1(ctx, "asinpi", x)


def acospi(ctx, x):
    """out[i] = acos(x[i]) / pi."""
    return _t1(ctx, "acospi", x)


def atanpi(ctx, x):
    """out[i] = atan(x[i]) / pi."""
    return _t1(ctx, "atanpi", x)


def atan2(ctx, y, x):
    """out[i] = atan2(y[i], x[i]), in radians - y first, as C has it."""
    return _t2(ctx, "atan2", y, x)


def atan2pi(ctx, y, x):
    """out[i] = atan2(y[i], x[i]) / pi."""
    return _t2(ctx, "atan2pi", y, x)


# The phase-3 radian trigonometry and the hyperbolics (ABI 0.5), on
# the same footing again.

def sin(ctx, x):
    """out[i] = sin(x[i]), x in radians."""
    return _t1(ctx, "sin", x)


def cos(ctx, x):
    """out[i] = cos(x[i]), x in radians."""
    return _t1(ctx, "cos", x)


def tan(ctx, x):
    """out[i] = tan(x[i]), x in radians."""
    return _t1(ctx, "tan", x)


def sinh(ctx, x):
    """out[i] = sinh(x[i])."""
    return _t1(ctx, "sinh", x)


def cosh(ctx, x):
    """out[i] = cosh(x[i])."""
    return _t1(ctx, "cosh", x)


def tanh(ctx, x):
    """out[i] = tanh(x[i])."""
    return _t1(ctx, "tanh", x)


def asinh(ctx, x):
    """out[i] = asinh(x[i])."""
    return _t1(ctx, "asinh", x)


def acosh(ctx, x):
    """out[i] = acosh(x[i])."""
    return _t1(ctx, "acosh", x)


def atanh(ctx, x):
    """out[i] = atanh(x[i])."""
    return _t1(ctx, "atanh", x)


# The rest of table 9.1 (part of the 0.6 step), on the same footing -
# except for the three whose second operand is an INTEGER per element,
# which take a sequence rather than an array of encodings.

def exp2m1(ctx, x):
    """out[i] = 2**x[i] - 1."""
    return _t1(ctx, "exp2m1", x)


def exp10(ctx, x):
    """out[i] = 10**x[i]."""
    return _t1(ctx, "exp10", x)


def exp10m1(ctx, x):
    """out[i] = 10**x[i] - 1."""
    return _t1(ctx, "exp10m1", x)


def log2p1(ctx, x):
    """out[i] = log2(1 + x[i])."""
    return _t1(ctx, "log2p1", x)


def log10p1(ctx, x):
    """out[i] = log10(1 + x[i])."""
    return _t1(ctx, "log10p1", x)



# ---------------------------------------------------------------------
# Character sequences (5.12) and NaN payloads (9.7). Part of the 0.6
# step.
#
# Only one direction of 5.12 belongs here, and that is cft.h's shape
# rather than this module's preference: reading sequences IN is a
# genuine batch - an array of strings, one C call, a dense array of
# encodings out - while writing one OUT is per element, because an
# output sequence's length is not known until the conversion has run
# and runs from three characters to 183,000. Float.to_decimal() is
# where that direction lives, and a caller writing a whole array ORs
# the flag words itself, which is all this module does with them.
# ---------------------------------------------------------------------

def _from_char(ctx, seqs, hex_form):
    if isinstance(seqs, str):
        raise TypeError(
            "batch wants a sequence of strings; one string is "
            "Context.from_decimal / Context.from_hex")
    seqs = list(seqs)
    for s in seqs:
        if not isinstance(s, str):
            raise TypeError(f"every element must be a str, got "
                            f"{type(s).__name__}")
    esz = ctx._fi.esz
    out, fl = _lib.from_char(ctx._dev, ctx._fi.code, ctx._rnd, seqs, esz,
                             hex_form=hex_form)
    ctx.last_flags = fl
    ctx.flags |= fl
    return ([Float(ctx, out[i * esz:(i + 1) * esz])
             for i in range(len(seqs))], fl)


def from_decimal(ctx, seqs):
    """A list of decimal character sequences to Floats, one libcft call
    for the array, each correctly rounded in ctx's attribute. Returns
    (list of Float, flag word) - the flag word being the OR across the
    batch, as everywhere else here. A sequence outside 5.12's syntax
    refuses the whole call and names which one."""
    return _from_char(ctx, seqs, False)


def from_hex(ctx, seqs):
    """The same for hexadecimal-significand sequences (5.12.3)."""
    return _from_char(ctx, seqs, True)


def _payload(ctx, name, x):
    payloads, n, mirror = _normalise(ctx, (x,))
    out = _lib.payload_op(ctx._dev, name, ctx._fi.code, payloads[0], n,
                          ctx._fi.esz)
    # 9.7: "These operations signal no exceptions." No flag word is
    # recorded and none is returned, so ctx.last_flags is left alone.
    return mirror(out)


def get_payload(ctx, x):
    """9.7 getPayload elementwise: each NaN's payload as a
    floating-point integer, -1 for anything that is not a NaN."""
    return _payload(ctx, "get_payload", x)


def set_payload(ctx, x):
    """9.7 setPayload elementwise: a quiet NaN carrying x[i] when that
    value is an admissible payload, and +0 otherwise."""
    return _payload(ctx, "set_payload", x)


def set_payload_signaling(ctx, x):
    """9.7 setPayloadSignaling elementwise. Payload 0 is not admissible,
    so +-0 answers +0."""
    return _payload(ctx, "set_payload_signaling", x)

def rsqrt(ctx, x):
    """out[i] = 1/sqrt(x[i])."""
    return _t1(ctx, "rsqrt", x)


def powr(ctx, x, y):
    """out[i] = x[i]**y[i] as exp(y log x): a negative base is invalid."""
    return _t2(ctx, "powr", x, y)


def _tint(ctx, name, x, ns):
    (bx,), n, mirror = _normalise(ctx, (x,))
    ns = [int(v) for v in ns]
    if len(ns) == 1 and n != 1:
        ns = ns * n
    if len(ns) != n:
        raise ValueError(f"{name}: {len(ns)} exponents for {n} elements")
    out, fl = _lib.transcend(ctx._dev, name, ctx._fi.code, ctx._rnd, bx,
                             None, n, ctx._fi.esz, ns=ns)
    return _finish(ctx, out, fl, mirror)


def pown(ctx, x, n):
    """out[i] = x[i]**n[i], n integral. A scalar n applies to every
    element; a sequence must be as long as the operand."""
    return _tint(ctx, "pown", x, n if hasattr(n, "__len__") else (n,))


def compound(ctx, x, n):
    """out[i] = (1 + x[i])**n[i], n integral."""
    return _tint(ctx, "compound", x, n if hasattr(n, "__len__") else (n,))


def rootn(ctx, x, n):
    """out[i] = x[i]**(1/n[i]), n a nonzero integer."""
    return _tint(ctx, "rootn", x, n if hasattr(n, "__len__") else (n,))


# ---------------------------------------------------------------------
# The augmented arithmetic operations (754-2019 clause 9.5).
#
# The only calls here that return TWO arrays - the operation rounded,
# and the error rounding made - and the only ones that ignore the
# context's rounding attribute, because 9.5 fixes the rounding to
# roundTiesTowardZero. Both arrays mirror the container of the first
# sequence operand, exactly as one-output calls do:
#
#     r, e, flags = batch.augmented_add(ctx, xs, ys)
#
# and r[i] + e[i] is the exact sum, elementwise, which is the whole
# reason to want them over an array rather than one at a time.
# ---------------------------------------------------------------------

def _aug(ctx, name, x, y):
    (bx, by), n, mirror = _normalise(ctx, (x, y))
    br, be, fl = _lib.augmented(ctx._dev, name, ctx._fi.code, bx, by, n,
                                ctx._fi.esz)
    ctx.last_flags = fl
    ctx.flags |= fl
    return mirror(br), mirror(be), fl


def augmented_add(ctx, x, y):
    """(r, e, flags) with r[i] + e[i] the exact x[i] + y[i]."""
    return _aug(ctx, "add", x, y)


def augmented_sub(ctx, x, y):
    """(r, e, flags) with r[i] + e[i] the exact x[i] - y[i]."""
    return _aug(ctx, "sub", x, y)


def augmented_mul(ctx, x, y):
    """(r, e, flags) with r[i] + e[i] the exact x[i] * y[i], except
    where the residual falls below the subnormal grid - 9.5's one
    non-representable case, which arrives rounded and flagged."""
    return _aug(ctx, "mul", x, y)


# ---------------------------------------------------------------------
# Reductions: n in, ONE out, over the contract's fixed tree.
# ---------------------------------------------------------------------

def tree_sum(ctx, x):
    """The contract reduction: sum over the fixed index-shaped binary
    tree, rounded at every node in the context's attribute. NOT
    mpfr_sum (a single correctly-rounded sum) - same inputs, different
    and equally deterministic bits. n=0 yields +0 and raises nothing;
    n=1 yields the element verbatim. Returns (Float, flag word)."""
    (bx,), n, _ = _normalise(ctx, (x,))
    out, fl = _lib.reduce(ctx._dev, _lib.OP_SUM, ctx._fi.code, ctx._rnd,
                          bx, None, n, ctx._fi.esz)
    ctx.last_flags = fl
    ctx.flags |= fl
    return Float(ctx, out), fl


def tree_dot(ctx, x, y):
    """sum over the fixed tree of round(x[i]*y[i]): each product is
    rounded once, then summed like tree_sum. Same non-mpfr_sum caveat.
    Returns (Float, flag word)."""
    (bx, by), n, _ = _normalise(ctx, (x, y))
    out, fl = _lib.reduce(ctx._dev, _lib.OP_DOT, ctx._fi.code, ctx._rnd,
                          bx, by, n, ctx._fi.esz)
    ctx.last_flags = fl
    ctx.flags |= fl
    return Float(ctx, out), fl


# ---------------------------------------------------------------------
# The rest of clause 9.4 (the 0.6 step)
#
# The other five reductions 754-2019 9.4 asks a language to define.
# Named tree_* like the two above, and for the same reason: nothing
# here is mpfr_sum, mpfr_dot or any other single correctly-rounded
# reduction, and a name that invited that reading would cost somebody a
# week. What these are is the contract's fixed index-shaped tree,
# rounded at every node in the context's attribute.
# ---------------------------------------------------------------------

def tree_sumsq(ctx, x):
    """sum over the fixed tree of round(x[i]*x[i]) - 9.4's sumSquare.

    Bit-identical to tree_dot(ctx, x, x), because the library issues
    exactly that; the one exception is 9.4's own, where a vector
    holding an infinity AND a NaN gives +inf rather than the quiet NaN
    the tree would give. Returns (Float, flag word)."""
    (bx,), n, _ = _normalise(ctx, (x,))
    out, fl = _lib.reduce(ctx._dev, _lib.OP_SUMSQ, ctx._fi.code, ctx._rnd,
                          bx, None, n, ctx._fi.esz)
    ctx.last_flags = fl
    ctx.flags |= fl
    return Float(ctx, out), fl


def tree_sumabs(ctx, x):
    """sum over the fixed tree of |x[i]| - 9.4's sumAbs.

    Bit-identical to an abs pass followed by tree_sum, with the same
    single exception tree_sumsq carries. Returns (Float, flag word)."""
    (bx,), n, _ = _normalise(ctx, (x,))
    out, fl = _lib.reduce(ctx._dev, _lib.OP_SUMABS, ctx._fi.code, ctx._rnd,
                          bx, None, n, ctx._fi.esz)
    ctx.last_flags = fl
    ctx.flags |= fl
    return Float(ctx, out), fl


def _scaled(ctx, kind, x, y=None):
    if y is None:
        (bx,), n, _ = _normalise(ctx, (x,))
        by = None
    else:
        (bx, by), n, _ = _normalise(ctx, (x, y))
    out, scale, fl = _lib.scaled_prod(ctx._dev, kind, ctx._fi.code,
                                      ctx._rnd, bx, by, n, ctx._fi.esz)
    ctx.last_flags = fl
    ctx.flags |= fl
    return Float(ctx, out), scale, fl


def scaled_prod(ctx, x):
    """9.4's scaledProd: the product of the elements as a PAIR.

    Returns (Float pr, int scale, flag word), where ldexp(pr, scale) is
    the product and pr is always in +-[1, 2). The operation cannot
    overflow or underflow whatever the true product is - both operands
    of every node's multiply are in +-[1, 2) by construction - which is
    the reason 754 defines it at all. n = 0 gives (1, 0) silently, the
    multiplicative identity."""
    return _scaled(ctx, 0, x)


def scaled_prod_sum(ctx, x, y):
    """9.4's scaledProdSum: the product of (x[i] + y[i]) as a pair.

    ONE contract rounding per leaf sum, then the same scaled tree. That
    leaf addition is the only place this can signal overflow or
    underflow; the product tree never does. Returns (Float, int, flag
    word)."""
    return _scaled(ctx, 1, x, y)


def scaled_prod_diff(ctx, x, y):
    """9.4's scaledProdDiff: the product of (x[i] - y[i]) as a pair.

    scaled_prod_sum with a subtraction at the leaf, in every respect.
    Returns (Float, int, flag word)."""
    return _scaled(ctx, 2, x, y)


# ---------------------------------------------------------------------
# The formatOf arithmetic, 754-2019 clause 5.4.1
#
# The one family here whose operands and results are DIFFERENT SIZES,
# which is why it does not reuse _normalise's mirror: that mirror was
# built from the operand's context and would rebuild the container at
# the source's element size. So the operands are normalised against the
# SOURCE context and the container is rebuilt against the DESTINATION's,
# by the same three rules - list in, list of destination Floats out;
# bytes in, packed destination encodings out; ndarray in, an array of
# the destination's natural dtype out.
#
# `src` is the operands' context and `dst` the result's. Both are real
# Contexts because both formats' machinery is needed: the source's to
# coerce an int or a float exactly, the destination's to carry the
# attribute, the flag word and the result Floats.
# ---------------------------------------------------------------------

def _dest_dtype(dst):
    """The numpy dtype an array of `dst` encodings comes back as:
    float32 and float64 where numpy has the format, and a void dtype of
    the right width where it does not."""
    esz = dst._fi.esz
    if esz == 4:
        return _np.dtype("float32")
    if esz == 8:
        return _np.dtype("float64")
    return _np.dtype("V%d" % esz)


def _dest_mirror(dst, operands):
    """A callable rebuilding the destination container from result
    bytes, chosen from the first SEQUENCE operand's style."""
    esz = dst._fi.esz
    for x in operands:
        if isinstance(x, Float):
            continue
        if isinstance(x, (bytes, bytearray, memoryview)):
            return lambda out: out
        if isinstance(x, (list, tuple)):
            return lambda out: [Float(dst, out[i * esz:(i + 1) * esz])
                                for i in range(len(out) // esz)]
        if _np is not None and isinstance(x, _np.ndarray):
            return (lambda out, dt=_dest_dtype(dst):
                    _np.frombuffer(out, dtype=dt).copy())
    return None


def _formatof(dst, src, name, operands):
    """The shared tail: normalise against the source, call, rebuild
    against the destination."""
    for x in operands:
        if isinstance(x, Float) and x._ctx._fi.prec != src._fi.prec:
            raise ValueError(
                f"{x._ctx._fi.ieee_name} Float among {src._fi.ieee_name} "
                f"operands: `src` names the ONE source format 5.4.1 "
                f"takes, and a mixed operand is refused rather than "
                f"silently widened.")
    payloads, n, _ = _normalise(src, operands)
    mirror = _dest_mirror(dst, operands)
    if mirror is None:
        raise TypeError(
            "every operand is a broadcast scalar; batch needs at least "
            "one sequence to set the element count (for scalars, the "
            "Context methods are the right call)")
    out, fl = _lib.formatof(dst._dev, name, src._fi.code, dst._fi.code,
                            dst._rnd, tuple(payloads), n, dst._fi.esz)
    return _finish(dst, out, fl, mirror)


def formatof_add(dst, src, x, y):
    """out[i] = x[i] + y[i] in `src`'s format, rounded ONCE into
    `dst`'s.

    `src` is passed rather than inferred, and that is not ceremony: a
    bytes operand or a numpy array carries no format of its own, so the
    element size a buffer is cut into has to be stated. Getting it wrong
    would read the wrong number of bytes per element rather than give a
    wrong answer, which is a failure worth making impossible to reach by
    accident.

    Every exception belongs to the destination. Returns (results, flag
    word), with the results in the container style the first sequence
    operand used."""
    return _formatof(dst, src, "add", (x, y))


def formatof_sub(dst, src, x, y):
    """out[i] = x[i] - y[i] in `src`'s format, rounded once into
    `dst`'s."""
    return _formatof(dst, src, "sub", (x, y))


def formatof_mul(dst, src, x, y):
    """out[i] = x[i] * y[i] in `src`'s format, rounded once into
    `dst`'s."""
    return _formatof(dst, src, "mul", (x, y))


def formatof_div(dst, src, x, y):
    """out[i] = x[i] / y[i], correctly rounded once into `dst`'s
    format - not the source-format quotient converted down, which is a
    different answer near the destination's midpoints."""
    return _formatof(dst, src, "div", (x, y))


def formatof_sqrt(dst, src, x):
    """out[i] = squareRoot(x[i]), correctly rounded once into `dst`'s
    format, with the destination's overflow and underflow."""
    return _formatof(dst, src, "sqrt", (x,))


def formatof_fma(dst, src, x, y, z):
    """out[i] = x[i]*y[i] + z[i] with ONE rounding into `dst`'s format -
    the operation no double-rounding scheme imitates at any width."""
    return _formatof(dst, src, "fma", (x, y, z))
