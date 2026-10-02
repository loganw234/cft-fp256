"""Independent finite binary32/64/128/256 oracle, using integers/Fractions.

This is a test-data generator, not a replacement for cft_golden. Special-value
probes carry explicit expected bits instead. No Python float enters an oracle.
Tininess is detected after rounding. Flags: invalid=1, overflow=4,
underflow=8, inexact=16. binary256 uses 19 exponent and 236 fraction bits;
the workload runner checks that layout against the actual implementation.
"""
from fractions import Fraction
from functools import lru_cache

FORMATS = {"fp32": (32, 8, 23), "fp64": (64, 11, 52),
           "fp128": (128, 15, 112), "fp256": (256, 19, 236)}
MODES = ("rne", "rtz", "rdn", "rup", "rmm")


def power2(e):
    return Fraction(1 << e) if e >= 0 else Fraction(1, 1 << -e)


def floor_log2(v):
    n, d = v.numerator, v.denominator
    e = n.bit_length() - d.bit_length()
    if (n < d << e) if e >= 0 else (n << -e < d):
        e -= 1
    return e


def spelling(bits, fmt="fp64"):
    return "0x" + format(bits, "0%dx" % (FORMATS[fmt][0] // 4))


@lru_cache(maxsize=32768)
def decode(bits, fmt="fp64"):
    width, eb, fb = FORMATS[fmt]
    sign = bits >> (width - 1)
    exp = (bits >> fb) & ((1 << eb) - 1)
    mant = bits & ((1 << fb) - 1)
    if exp == (1 << eb) - 1:
        raise ValueError("finite oracle cannot decode infinity or NaN")
    bias = (1 << (eb - 1)) - 1
    v = mant * power2(1 - bias - fb) if exp == 0 else ((1 << fb) + mant) * power2(exp - bias - fb)
    return -v if sign else v


def round_exact(value, fmt="fp64", mode="rne", zero_sign=0):
    value = Fraction(value)
    width, eb, fb = FORMATS[fmt]
    bias = (1 << (eb - 1)) - 1
    emin, emax = 1 - bias, bias
    sign = int(value < 0) if value else zero_sign
    sign_bit = sign << (width - 1)
    if not value:
        return sign_bit, 0
    value = abs(value)
    e = floor_log2(value)
    quantum = max(e - fb, emin - fb)
    scaled = value / power2(quantum)
    q, rem = divmod(scaled.numerator, scaled.denominator)
    inexact = bool(rem)
    up = False
    if rem:
        if mode == "rne":
            up = 2 * rem > scaled.denominator or (2 * rem == scaled.denominator and q % 2 == 1)
        elif mode == "rmm":
            up = 2 * rem >= scaled.denominator
        elif mode == "rup":
            up = not sign
        elif mode == "rdn":
            up = bool(sign)
        elif mode != "rtz":
            raise ValueError(mode)
    q += int(up)
    if q:
        result_e = q.bit_length() - 1 + quantum
        if result_e > emax:
            inf = mode in ("rne", "rmm") or (mode == "rup" and not sign) or (mode == "rdn" and sign)
            mag = ((1 << eb) - 1) << fb if inf else (((1 << eb) - 2) << fb) | ((1 << fb) - 1)
            return sign_bit | mag, 4 | 16
        if result_e >= emin:
            sig = q << (fb - (q.bit_length() - 1)) if q.bit_length() <= fb + 1 else q >> (q.bit_length() - 1 - fb)
            mag = ((result_e + bias) << fb) | (sig - (1 << fb))
        else:
            mag = q
    else:
        mag = 0
    tiny = (mag >> fb) == 0
    flags = (16 if inexact else 0) | (8 if inexact and tiny else 0)
    return sign_bit | mag, flags


class FiniteOracle:
    def __init__(self, fmt="fp64", mode="rne"):
        self.fmt, self.mode, self.flags = fmt, mode, 0
        self.sign_mask = 1 << (FORMATS[fmt][0] - 1)

    def constant(self, value):
        # Constants' flags deliberately do not enter run FLAGS.
        return round_exact(value, self.fmt, self.mode)[0]

    def neg(self, a):
        return a ^ self.sign_mask

    def abs(self, a):
        return a & ~self.sign_mask

    def emit(self, value, zero_sign=0):
        bits, flags = round_exact(value, self.fmt, self.mode, zero_sign)
        self.flags |= flags
        return bits

    def add(self, a, b):
        x, y = decode(a, self.fmt), decode(b, self.fmt)
        sa, sb = bool(a & self.sign_mask), bool(b & self.sign_mask)
        zero_sign = sa if not x and not y and sa == sb else self.mode == "rdn"
        return self.emit(x + y, int(zero_sign))

    def sub(self, a, b):
        return self.add(a, self.neg(b))

    def mul(self, a, b):
        return self.emit(decode(a, self.fmt) * decode(b, self.fmt), int(bool((a ^ b) & self.sign_mask)))

    def fma(self, a, b, c):
        x, y, z = decode(a, self.fmt), decode(b, self.fmt), decode(c, self.fmt)
        product_sign = bool((a ^ b) & self.sign_mask)
        sc = bool(c & self.sign_mask)
        zero_sign = product_sign if not x * y and not z and product_sign == sc else self.mode == "rdn"
        return self.emit(x * y + z, int(zero_sign))

    def integrate(self, state, field, integrator, h):
        h1, h2, h6 = (self.constant(h / d) for d in (1, 2, 6))
        if integrator == "euler":
            return [self.fma(h1, f, y) for f, y in zip(field(state), state)]
        if integrator != "rk4":
            raise ValueError(integrator)
        two = self.constant(2)
        k1 = field(state)
        k2 = field([self.fma(h2, f, y) for f, y in zip(k1, state)])
        k3 = field([self.fma(h2, f, y) for f, y in zip(k2, state)])
        k4 = field([self.fma(h1, f, y) for f, y in zip(k3, state)])
        sums = [self.add(self.fma(two, c, self.fma(two, b, a)), d) for a, b, c, d in zip(k1, k2, k3, k4)]
        return [self.fma(h6, f, y) for f, y in zip(sums, state)]
