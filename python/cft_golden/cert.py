# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Certificates, version 1: the golden implementation.

docs/CERTIFICATES.md is the specification; this file is its executable
form, as seq.py is SEQUENCER.md's. A certificate says what ran - the
program image, its bank, the streams, the lanes - how it was cut into
segments, which state each segment started and ended on (as hashes),
and how accurate the result is, of which kind. An audit checks
the statement by re-running segments with `seq.run` from their certified
start states.

A certificate is KEYED or OPEN, its owner's choice (Logan, 2026-09-28):
keyed, its state and stream hashes are HMAC-SHA-256 under a 32-byte
salt the owner keeps, and a reader of it cannot confirm a guessed
state; open, they are plain SHA-256, and anyone holding the states can
audit it.

What is here:
  * encode()        a Certificate -> the bytes, hash line included
  * parse()         the bytes -> a Certificate, STRICT: every departure
                    from the one spelling is refused by name
  * salt_commitment(), state_hash(), stream_hash()  the hashes, keyed
                    under a salt or open without one
  * run_chain(), certify_run()  a run cut into segments by seq.run, and
                    its chain of state hashes - the golden writer
  * derive()        each accuracy value as the stated function of
                    certified runs
  * sample()        the auditor's segment sample, PRNG fixed exactly
  * audit()         every check, in the specification's order

Every refusal is a `Refusal` whose `.name` is one of REFUSALS and whose
`.exit_code` is the one the specification's table gives. Nothing here
approximates: a value past the width rule, a NaN where a number is
needed, a run the format cannot describe - each is refused by name.
"""

import hashlib
import hmac
import math
import os
import re
from dataclasses import dataclass
from fractions import Fraction

from . import chars
from . import seq
from . import softfloat as sf
from .formats import FORMATS

MAGIC = "cft-certificate"
VERSION = 1

# The width rule (docs/CERTIFICATES.md, "The width rule"). Every exact
# rational the format carries, and every one an audit computes on the
# way to a value, has a numerator of at most WIDTH bits in magnitude and
# a denominator of at most WIDTH bits, in reduced form. 1,023 because one
# exact step on two such values - a/b + c/d = (ad + cb) / bd - needs
# 2 * 1023 + 1 = 2,047 bits of magnitude, which libcft's default unsigned
# bigint (2,048 bits, host/src/bigint.h) holds with one bit to spare:
# 1,024 would need 2,049, which it does not.
WIDTH = 1023

SALT_BYTES = 32
SEED_BYTES = 32

# The lanes an audit re-runs at once (run_segment): libcft's BLOCK_LANES
# (host/src/program.c), so that each auditor holds one block's scratch
# at the certified depth - a constant the page fixes, where the dense
# seq.run holds every lane's (the lead's decision, 2026-09-29).
BLOCK_LANES = 64

# The domain-separation tags. No tag is a prefix of another - they part
# at "salt" / "state" / "stream" - so no message in one domain is a
# message in another. The salt's is fixed by the plan of record; the
# others end in a NUL so that the payload that follows cannot extend
# the tag into another one.
TAG_SALT = b"cft-certificate 1 salt"
TAG_STATE = b"cft-certificate 1 state\x00"
TAG_STREAM = {n: b"cft-certificate 1 stream " + n.encode() + b"\x00"
              for n in "abc"}
TAG_SAMPLE = b"cft-certificate 1 sample\x00"

LADDER = ("fp32", "fp64", "fp128", "fp256")
RND = {"rne": sf.RND_RNE, "rtz": sf.RND_RTZ, "rdn": sf.RND_RDN,
       "rup": sf.RND_RUP, "rmm": sf.RND_RMM}

# What each method is. Version 1 has no method with a rigorous
# remainder, so no entry can be a bound: the kind word exists for the
# versions that will.
METHOD_KIND = {"drift": "measurement", "step-halving": "estimate",
               "wider": "estimate"}
# The auxiliary run each estimate compares run 0 with.
METHOD_RUN = {"step-halving": "half-step", "wider": "wider"}
KINDS = ("bound", "estimate", "measurement")
MAX_TERMS = 64
MAX_FACTORS = 8

# The one parameter the audit READS (the lead's decision, 2026-09-29): a
# run's scratch depth, where `device-caps` gives none - so that a software
# handle opened deeper (cft_open_ex, cft-segrun --scratch-depth) can say
# the depth it ran at. Every other parameter is stated and not checked.
DEPTH_PARAMETER = "scratch-depth"


def _is_depth(v):
    """A scratch depth a certificate may state: a power of two in
    1..32,768, the four bits of CAPS2[3:0] (seq.SCRATCH_D_MAX)."""
    return _is_int(v) and 1 <= v <= seq.SCRATCH_D_MAX and not v & (v - 1)

# Refusal name -> exit code, one table (the specification prints the
# same one, and test_cert.py holds the two equal). Codes are families
# in the order the audit reaches them; the NAME is the report.
REFUSALS = {
    # 1: integrity - the hash line
    "hash-line": 1, "body-hash": 1,
    # 2: form - the strict reader
    "magic": 2, "version": 2, "mode-unknown": 2, "commitment-missing": 2,
    "commitment-unexpected": 2, "unknown-line": 2, "line-missing": 2,
    "line-order": 2, "line-unexpected": 2, "count": 2, "malformed": 2,
    "decimal": 2, "accuracy-kind": 2,
    # 3: the width rule, wherever it is met
    "width": 3,
    # 4: an input handed to the audit is not the one certified
    "salt-missing": 4, "salt-unexpected": 4, "salt-length": 4,
    "salt-commitment": 4, "image-digest": 4,
    "program-digest": 4, "program-image": 4, "program-format": 4,
    "program-shape": 4, "stream": 4, "state-shape": 4, "state-hash": 4,
    "state-missing": 4,
    # 5: the chain and the auxiliary runs' relation to the main run
    "continuity": 5, "aux-format": 5, "aux-lanes": 5, "aux-image": 5,
    "aux-segments": 5, "aux-h-slots": 5, "aux-bank": 5, "aux-streams": 5,
    "aux-start": 5,
    # 6: a re-run disagrees with its certified segment
    "segment-end": 6, "segment-flags": 6, "segment-status": 6,
    # 7: an accuracy value is not the function it names
    "accuracy-run": 7, "accuracy-scope": 7, "accuracy-slot": 7,
    "accuracy-finite": 7, "accuracy-value": 7,
    # 64: the auditor was asked for something the certificate lacks
    "choice": 64,
}


class Refusal(ValueError):
    """A refusal by name. `name` is a key of REFUSALS. Its location is in
    fields, each None where it does not apply: `line` for the reader's
    refusals; for the audit's, `run` where it concerns one run, `segment`
    where it concerns one segment or boundary of it, and `entry` where it
    concerns one accuracy entry."""

    def __init__(self, name, message, *, line=None, run=None, segment=None,
                 entry=None):
        if name not in REFUSALS:
            raise AssertionError(f"unnamed refusal {name!r}")
        self.name = name
        self.message = message
        self.line = line
        self.run = run
        self.segment = segment
        self.entry = entry
        self.exit_code = REFUSALS[name]
        super().__init__(f"{name}: {message}")


def _is_int(v):
    """An integer that is not a bool (True is an int in Python)."""
    return isinstance(v, int) and not isinstance(v, bool)


# ---- the structure ----------------------------------------------------

@dataclass(frozen=True)
class Identity:
    """What the producer says it ran on. Recorded for reproduction and
    reported; never checked (docs/CERTIFICATES.md, "Identity")."""
    # libcft's cft_build_id() string, verbatim (parcel P2, 2026-09-28):
    # "commit=<40 or 64 lowercase hex> tracked=<clean|modified>
    # untracked=<none|present>", or "unknown" whole
    build_id: str = "unknown"
    backend: str = "unknown"            # software, xrt, remote or unknown
    device_xclbin: str = "unknown"      # 64 hex, none or unknown
    device_version: str = "unknown"     # 8 hex, none or unknown
    # cft_image_id's raw words: (CAPS,) below VERSION 0x800 and
    # (CAPS, CAPS2) from it, each 8 hex; or none or unknown
    device_caps: object = "unknown"
    device_tiles: object = "unknown"    # an integer >= 1, or unknown


@dataclass(frozen=True)
class Segment:
    start: str          # HMAC of the state it began on
    end: str            # HMAC of the state it ended on
    flags: int          # the run's sticky IEEE flags
    status: int         # the run's STATUS word


@dataclass(frozen=True)
class Run:
    kind: str           # main, half-step or wider
    fmt: str
    image: str          # SHA-256 of the image bytes
    digest: str         # SHA-256 of image then bank: cft_program_digest
    lanes: int
    steps: int          # steps a segment - stated, not checked
    streams: tuple      # HMACs of a, b, c
    parameters: tuple   # ((name, integer), ...), names increasing
    chain: tuple        # (Segment, ...)
    output: str         # HMAC of the final state
    h_slots: tuple = ()  # half-step only: the bank slots that carry h


@dataclass(frozen=True)
class Value:
    form: str           # exact, rounded or enclosed
    exact: Fraction = None
    fmt: str = None
    rnd: str = None
    bits: int = None
    lo: int = None
    hi: int = None


@dataclass(frozen=True)
class Entry:
    method: str         # drift, step-halving or wider
    kind: str
    uses: int           # the run it is a function of (with run 0 for an
                        # estimate)
    lane: object        # a lane index, or None for the maximum over lanes
    value: Value
    label: str = None   # drift only
    terms: tuple = ()   # drift only: ((coefficient, (slot, ...)), ...)


@dataclass(frozen=True)
class Certificate:
    mode: str               # keyed or open (Logan, 2026-09-28)
    salt_commitment: str    # keyed: HMAC(salt, TAG_SALT); open: None
    identity: Identity
    runs: tuple
    accuracy: tuple


MODES = ("keyed", "open")


# ---- the hashes of states and streams -------------------------------------
#
# A certificate is KEYED or OPEN, the owner's choice (Logan, 2026-09-28).
# Keyed, every state and stream hash is HMAC-SHA-256 under the owner's
# 32-byte salt; open, it is plain SHA-256 of the same tag and bytes.
# Here `salt` None means open.

def _mac(salt, message):
    if salt is None:
        return hashlib.sha256(message).hexdigest()
    _check_salt_length(salt)
    return hmac.new(bytes(salt), message, hashlib.sha256).hexdigest()


def salt_commitment(salt):
    """HMAC(salt, "cft-certificate 1 salt"): binds a keyed certificate
    to its salt without publishing anything that is the key. A bare
    SHA-256(salt) would BE the HMAC key of any salt longer than 64
    bytes (RFC 2104 hashes such keys; verifier-C1 measured it), which
    is also why the salt is exactly 32 bytes."""
    if salt is None:
        raise Refusal("salt-missing", "a salt commitment needs a salt")
    return _mac(salt, TAG_SALT)


def state_hash(salt, data):
    """The hash of a state: the scratch block's bytes as the library
    stores them - lane-major, each element format-width and
    little-endian (state_bytes) - behind TAG_STATE. Keyed under `salt`,
    or open when `salt` is None."""
    return _mac(salt, TAG_STATE + bytes(data))


def stream_hash(salt, name, data):
    """The hash of input stream `name` (a, b or c): its n elements,
    format-width, little-endian, lane order, behind its own tag. Keyed
    under `salt`, or open when `salt` is None."""
    return _mac(salt, TAG_STREAM[name] + bytes(data))


def _check_salt_length(salt):
    if not isinstance(salt, (bytes, bytearray)) or len(salt) != SALT_BYTES:
        got = len(salt) if isinstance(salt, (bytes, bytearray)) else None
        raise Refusal("salt-length",
                      f"a version-1 salt is exactly {SALT_BYTES} bytes; "
                      f"this one is "
                      f"{'not bytes' if got is None else f'{got} bytes'}")


def state_bytes(fmt, values):
    """Elements -> the bytes the library stores: format-width,
    little-endian, in order."""
    fmt = FORMATS[fmt] if isinstance(fmt, str) else fmt
    esz = fmt.width // 8
    return b"".join(int(v).to_bytes(esz, "little") for v in values)


def state_values(fmt, data):
    """The inverse of state_bytes."""
    fmt = FORMATS[fmt] if isinstance(fmt, str) else fmt
    esz = fmt.width // 8
    if len(data) % esz:
        raise ValueError(f"{len(data)} bytes is not a whole number of "
                         f"{fmt.name} elements")
    return [int.from_bytes(data[i:i + esz], "little")
            for i in range(0, len(data), esz)]


def sha256(data):
    return hashlib.sha256(bytes(data)).hexdigest()


# ---- exact values ---------------------------------------------------------

def _checked(q, what):
    """The width rule, applied to one exact value."""
    if (abs(q.numerator).bit_length() > WIDTH
            or q.denominator.bit_length() > WIDTH):
        raise Refusal("width",
                      f"{what} needs a {abs(q.numerator).bit_length()}-bit "
                      f"numerator and a {q.denominator.bit_length()}-bit "
                      f"denominator; version 1 allows {WIDTH} bits each")
    return q


def element_fraction(fmt, bits):
    """(kind, exact value) of an encoding: kind is 'finite' (zero
    included), 'inf', '-inf' or 'nan'. No width rule here - callers
    apply it where the specification says it applies."""
    fmt = FORMATS[fmt] if isinstance(fmt, str) else fmt
    kind, sign, m, e, _, _ = chars._decode(fmt, bits)
    if kind == "zero":
        return "finite", Fraction(0)
    if kind == "inf":
        return ("-inf" if sign else "inf"), None
    if kind == "nan":
        return "nan", None
    v = Fraction(m) * (Fraction(2) ** e)
    return "finite", (-v if sign else v)


def _exact(fmt, bits, what):
    """An element's exact value, under the width rule; a non-finite one
    has none, refused by name."""
    kind, v = element_fraction(fmt, bits)
    if kind != "finite":
        raise Refusal("accuracy-finite",
                      f"{what} is {kind}; an exact value needs a finite "
                      f"element")
    return _checked(v, what)


def round_rational(fmt, q, rnd):
    """The exact rational q correctly rounded into `fmt` under the
    attribute named `rnd` (rne, rtz, rdn, rup, rmm). An exact zero is
    +0 under every attribute."""
    fmt = FORMATS[fmt] if isinstance(fmt, str) else fmt
    if q == 0:
        return sf.zero_bits(fmt, 0)
    bits, _ = chars._round_rational(fmt, 1 if q < 0 else 0,
                                    abs(q.numerator), q.denominator,
                                    RND[rnd])
    return bits


def exact_decimal(fmt, bits):
    """The canonical exact decimal of an encoding (chars.to_decimal's
    exact mode): what the reader holds each element's decimal to."""
    fmt = FORMATS[fmt] if isinstance(fmt, str) else fmt
    return chars.to_decimal(fmt, bits, 0)[0]


def widen(fmt, bits):
    """One rung up the ladder, exactly: the contract's convertFormat,
    which is exact for every finite and infinite value and maps a NaN
    to the wider format's canonical quiet NaN."""
    src = FORMATS[fmt]
    dst = FORMATS[LADDER[LADDER.index(fmt) + 1]]
    out, _ = sf.convert(src, dst, bits)
    return out


# ---- encodings (text) -------------------------------------------------------

_HEX = {n: re.compile(r"[0-9a-f]{%d}" % n) for n in (8, 40, 64)}
_DEC = re.compile(r"0|[1-9][0-9]*")
_NAME = re.compile(r"[a-z][a-z0-9-]{0,63}")
_RAT = re.compile(r"(0|-?[1-9a-f][0-9a-f]*)/([1-9a-f][0-9a-f]*)")
_SLOT = re.compile(r"s(0|[1-9][0-9]*)")
# cft_build_id's commit field: 40 lowercase hex digits, or 64 in a
# repository that names objects by SHA-256 (P2's generator writes either)
_BUILD_COMMIT = re.compile(r"commit=(?:[0-9a-f]{40}|[0-9a-f]{64})")
DEC_MAX = (1 << 63) - 1


def _index(tok):
    """A decimal token's value when it is in its one spelling and at
    most 2^63 - 1, else None. The length is bounded BEFORE int() is
    called: Python refuses to convert a decimal string of more than
    4,300 digits (a ValueError, not a refusal), and a reader must refuse
    such a token by name rather than fall over on it."""
    if not _DEC.fullmatch(tok) or len(tok) > 19:
        return None
    v = int(tok)
    return v if v <= DEC_MAX else None


def _hex_bits(digits):
    """The bit length of a magnitude spelt in hex with no leading zero
    (`0` for zero), from its digits alone: four bits a digit past the
    first, and the first digit's own."""
    return 4 * (len(digits) - 1) + int(digits[0], 16).bit_length()


def rational_text(q):
    """The one spelling of a rational: hex numerator (the sign on it,
    no leading zeros), a slash, hex denominator (positive, no leading
    zeros), in lowest terms. Zero is 0/1."""
    n, d = q.numerator, q.denominator
    return f"{'-' if n < 0 else ''}{abs(n):x}/{d:x}"


def element_hex(fmt, bits):
    fmt = FORMATS[fmt] if isinstance(fmt, str) else fmt
    return f"{bits:0{fmt.width // 4}x}"


def _value_text(v):
    if v.form == "exact":
        return f"value exact {rational_text(v.exact)}"
    if v.form == "rounded":
        return (f"value rounded {v.fmt} {v.rnd} {element_hex(v.fmt, v.bits)} "
                f"{exact_decimal(v.fmt, v.bits)}")
    return (f"value enclosed {v.fmt} {element_hex(v.fmt, v.lo)} "
            f"{exact_decimal(v.fmt, v.lo)} {element_hex(v.fmt, v.hi)} "
            f"{exact_decimal(v.fmt, v.hi)}")


def _body_lines(cert):
    idn = cert.identity
    caps = (" ".join(idn.device_caps) if isinstance(idn.device_caps, tuple)
            else idn.device_caps)
    L = [f"{MAGIC} {VERSION}", f"mode {cert.mode}"]
    if cert.mode == "keyed":
        L.append(f"salt-commitment {cert.salt_commitment}")
    L += [f"build-id {idn.build_id}",
         f"backend {idn.backend}",
         f"device-xclbin {idn.device_xclbin}",
         f"device-version {idn.device_version}",
         f"device-caps {caps}",
         f"device-tiles {idn.device_tiles}",
         f"runs {len(cert.runs)}"]
    for i, run in enumerate(cert.runs):
        if run.kind == "half-step":
            L.append(f"run {i} half-step h-slots {len(run.h_slots)} "
                     + " ".join(str(s) for s in run.h_slots))
        else:
            L.append(f"run {i} {run.kind}")
        L += [f"program-format {run.fmt}",
              f"program-image {run.image}",
              f"program-digest {run.digest}",
              f"lanes {run.lanes}",
              f"steps {run.steps}",
              f"stream-a {run.streams[0]}",
              f"stream-b {run.streams[1]}",
              f"stream-c {run.streams[2]}",
              f"parameters {len(run.parameters)}"]
        L += [f"parameter {n} {v}" for n, v in run.parameters]
        L.append(f"segments {len(run.chain)}")
        L += [f"segment {k} start {s.start} end {s.end} flags {s.flags} "
              f"status {s.status}" for k, s in enumerate(run.chain)]
        L.append(f"output {run.output}")
    L.append(f"accuracy {len(cert.accuracy)}")
    for j, e in enumerate(cert.accuracy):
        L += [f"entry {j} {e.method}",
              f"kind {e.kind}",
              f"uses {e.uses}",
              "scope max-lanes" if e.lane is None else f"scope lane {e.lane}"]
        if e.method == "drift":
            L.append(f"quantity {e.label} terms {len(e.terms)}")
            for c, slots in e.terms:
                L.append(" ".join(["term", rational_text(c)]
                                  + [f"s{s}" for s in slots]))
        L.append(_value_text(e.value))
    L.append("end")
    return L


def _normalized(cert):
    """The same certificate with every sequence a tuple, which is what
    parse() returns - so that a writer's lists compare equal."""
    runs = tuple(Run(r.kind, r.fmt, r.image, r.digest, r.lanes, r.steps,
                     tuple(r.streams),
                     tuple((n, v) for n, v in r.parameters),
                     tuple(Segment(*s) if not isinstance(s, Segment) else s
                           for s in r.chain),
                     r.output, tuple(r.h_slots)) for r in cert.runs)
    acc = tuple(Entry(e.method, e.kind, e.uses, e.lane, e.value, e.label,
                      tuple((c, tuple(sl)) for c, sl in e.terms))
                for e in cert.accuracy)
    idn = cert.identity
    if isinstance(idn.device_caps, list):
        idn = Identity(idn.build_id, idn.backend, idn.device_xclbin,
                       idn.device_version, tuple(idn.device_caps),
                       idn.device_tiles)
    return Certificate(cert.mode, cert.salt_commitment, idn, runs, acc)


def encode(cert):
    """The certificate's bytes, hash line included.

    The writer applies the reader's rules: the text is read back with
    parse() before it is returned, so a value past the width rule, a
    non-canonical spelling or a bound in version 1 is refused here by
    the name the reader would use - and the read-back must equal the
    object, so nothing the encoder wrote can mean something else."""
    try:
        cert = _normalized(cert)
        body = ("\n".join(_body_lines(cert)) + "\n").encode("ascii")
    except (AttributeError, IndexError, KeyError, TypeError,
            UnicodeEncodeError, ValueError) as e:
        raise Refusal("malformed",
                      f"the writer was handed a certificate object it cannot "
                      f"spell ({type(e).__name__}: {e})") from None
    data = body + f"hash {sha256(body)}\n".encode("ascii")
    back = parse(data)
    if back != cert:
        where = _first_difference(cert, back) or "the certificate"
        raise Refusal("malformed",
                      f"the writer was handed {where}, which reads back as "
                      f"something else: a value of the wrong type or "
                      f"spelling (device_caps a bare string where a tuple of "
                      f"words belongs, a count or index that is not an "
                      f"integer)")
    return data


def _first_difference(a, b, path="certificate"):
    """Where two certificate objects first differ, as 'path = a (read back
    as b)', or None. For the writer's refusal message only."""
    if type(a) is not type(b) and not (isinstance(a, (tuple, list))
                                       and isinstance(b, (tuple, list))):
        return f"{path} = {a!r} (read back as {b!r})"
    if hasattr(a, "__dataclass_fields__"):
        for f in a.__dataclass_fields__:
            d = _first_difference(getattr(a, f), getattr(b, f),
                                  f"{path}.{f}")
            if d:
                return d
        return None
    if isinstance(a, (tuple, list)):
        if len(a) != len(b):
            return f"{path} = {a!r} (read back as {b!r})"
        for i, (x, y) in enumerate(zip(a, b)):
            d = _first_difference(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    return None if a == b else f"{path} = {a!r} (read back as {b!r})"


def rehash(body_text):
    """A body (magic line to `end` and its newline) with a valid hash
    line appended. For the negative controls, which must reach the check
    they exist for rather than stop at the hash (docs/CERTIFICATES.md,
    "The controls")."""
    body = body_text.encode("ascii") if isinstance(body_text, str) \
        else bytes(body_text)
    return body + f"hash {sha256(body)}\n".encode("ascii")


def body_of(data):
    """The body of a certificate's bytes: everything before its last
    line."""
    data = bytes(data)
    cut = data.rfind(b"\n", 0, len(data) - 1)
    return data[:cut + 1]


# ---- the strict reader -----------------------------------------------------

# Every line's key is its first token, and every key has one place: a
# rank in the order the specification lists them. The four STARTERS
# open a block.
_ORDER = ("cft-certificate", "mode", "salt-commitment", "build-id",
          "backend", "device-xclbin",
          "device-version", "device-caps", "device-tiles", "runs",
          "run", "program-format", "program-image", "program-digest",
          "lanes", "steps", "stream-a", "stream-b", "stream-c",
          "parameters", "parameter", "segments", "segment", "output",
          "accuracy", "entry", "kind", "uses", "scope", "quantity",
          "term", "value", "end", "hash")
RANK = {k: i for i, k in enumerate(_ORDER)}
STARTERS = ("run", "accuracy", "entry", "end")
# The blocks, in order: the header (0), a run (1), the accuracy count
# (2), an entry (3), the end (4). Runs and entries repeat. BLOCK_TYPE
# gives every key its block; `hash` belongs after the body.
BLOCK_OF = {"run": 1, "accuracy": 2, "entry": 3, "end": 4}
REPEATING = ("run", "entry")
BLOCK_TYPE = {k: (0 if RANK[k] < RANK["run"] else
                  1 if RANK[k] < RANK["accuracy"] else
                  2 if k == "accuracy" else
                  3 if RANK[k] < RANK["end"] else
                  4 if k == "end" else 5) for k in RANK}


def _split_hash(data):
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("a certificate is bytes")
    data = bytes(data)
    if not data.endswith(b"\n"):
        raise Refusal("hash-line", "the file does not end with a newline, "
                                   "so its last line is not a hash line")
    cut = data.rfind(b"\n", 0, len(data) - 1)
    last = data[cut + 1:-1]
    m = re.fullmatch(rb"hash ([0-9a-f]{64})", last)
    if not m:
        shown = last[:80].decode("ascii", "replace")
        raise Refusal("hash-line",
                      f"the last line must be 'hash' and 64 lowercase hex "
                      f"digits; it is {shown!r}")
    return data[:cut + 1], m.group(1).decode("ascii")


def _split_lines(body):
    lines = []
    for n, raw in enumerate(body.split(b"\n")[:-1], 1):
        bad = [b for b in raw if not 0x20 <= b <= 0x7E]
        if bad:
            raise Refusal("malformed", f"line {n} holds byte {bad[0]:#04x}; "
                                       f"a certificate is printable ASCII "
                                       f"and LF", line=n)
        if not raw:
            raise Refusal("malformed", f"line {n} is empty", line=n)
        if raw.startswith(b" ") or raw.endswith(b" ") or b"  " in raw:
            raise Refusal("malformed", f"line {n}: tokens are separated by "
                                       f"exactly one space, with none at "
                                       f"either end", line=n)
        lines.append(raw.decode("ascii").split(" "))
    return lines


class _Reader:
    """One pass over the body's lines against the specification's line
    order, refusing at the first departure by the name its
    classification gives (docs/CERTIFICATES.md, "The strict reader")."""

    def __init__(self, lines):
        self.lines = lines
        self.pos = 0
        self.block = 0          # BLOCK_OF's numbering; 0 is the header

    # -- where we are ---------------------------------------------------

    def key(self, i=None):
        i = self.pos if i is None else i
        return self.lines[i][0] if i < len(self.lines) else None

    def ln(self, i=None):
        return (self.pos if i is None else i) + 1

    def fail(self, name, message, i=None):
        return Refusal(name, f"line {self.ln(i)}: {message}", line=self.ln(i))

    def malformed(self, message, i=None):
        return self.fail("malformed", message, i)

    def _block_rest(self):
        """The keys from here to the end of the current block."""
        out = []
        for i in range(self.pos, len(self.lines)):
            k = self.lines[i][0]
            if i > self.pos and k in STARTERS:
                break
            out.append(k)
        return out

    def classify(self, expected):
        """The name for 'expected a line with key `expected`, found
        something else': a key that starts a later block (so `expected`
        is missing); a key whose place is earlier (a line with no place
        here); `expected` present further on in this block (out of
        order); or else `expected` missing. (Every key here is a known
        one: the certificate's key scan refused any other before this
        can be asked.)"""
        k = self.key()
        if k is None:
            return Refusal("line-missing",
                           f"'{expected}' is missing: the body ends first",
                           line=self.ln())
        t = BLOCK_TYPE[k]
        if k in STARTERS:
            if t > self.block or (t == self.block and k in REPEATING):
                return self.fail("line-missing",
                                 f"'{expected}' is missing: '{k}' begins a "
                                 f"later block here")
            return self.fail("line-unexpected",
                             f"'{k}' has no place here: its block is "
                             f"already read, and '{expected}' belongs here")
        # A line of a block already read, or of this block but placed
        # before what is expected, has no place here. When a STARTER is
        # expected, the current block is finished, so every line of its
        # type is behind us.
        if t < self.block or (t == self.block and (
                expected in STARTERS or RANK[k] < RANK[expected])):
            return self.fail("line-unexpected",
                             f"'{k}' has no place here: its place is "
                             f"earlier, and '{expected}' belongs here")
        if expected in self._block_rest():
            return self.fail("line-order",
                             f"'{k}' comes before '{expected}', which "
                             f"belongs first")
        return self.fail("line-missing", f"'{expected}' is missing; "
                                         f"'{k}' is here instead")

    def expect(self, key, ntok=None):
        if self.key() != key:
            raise self.classify(key)
        toks = self.lines[self.pos]
        if ntok is not None and len(toks) != ntok:
            raise self.malformed(f"'{key}' takes {ntok - 1} value"
                                 f"{'s' if ntok != 2 else ''}, not "
                                 f"{len(toks) - 1}")
        self.pos += 1
        return toks

    # -- tokens -------------------------------------------------------------

    def dec(self, tok, what, lo=0, hi=DEC_MAX, i=None):
        if not _DEC.fullmatch(tok):
            raise self.malformed(f"{what} {tok[:80]!r} is not a decimal "
                                 f"integer in its one spelling (digits, no "
                                 f"sign, no leading zero)", i)
        v = _index(tok)
        if v is None:
            raise self.malformed(f"{what} {tok[:40]}... is past 2^63 - 1"
                                 if len(tok) > 40 else
                                 f"{what} {tok} is past 2^63 - 1", i)
        if not lo <= v <= hi:
            raise self.malformed(f"{what} is {v}; it must be in {lo}..{hi}",
                                 i)
        return v

    def hexn(self, tok, n, what, i=None):
        if not _HEX[n].fullmatch(tok):
            raise self.malformed(f"{what} {tok[:80]!r} is not {n} lowercase "
                                 f"hex digits", i)
        return tok

    def word(self, tok, words, what):
        """A fixed word, read from the line just taken by expect()."""
        if tok not in words:
            raise self.malformed(f"{what} {tok[:80]!r} is not one of "
                                 f"{', '.join(words)}", self.pos - 1)
        return tok

    def rational(self, tok, what, i=None):
        """A rational in its one spelling, under the width rule: its
        spelling first; then each part's DIGITS against the rule, before
        anything is converted or reduced; then zero's one spelling, 0/1;
        last, lowest terms (the lead's decision, 2026-09-29). So a long
        token that is not in lowest terms is `width`, a short one
        `malformed`: an auditor whose exact arithmetic is 2,048 bits wide
        cannot hold a longer token, let alone reduce it, and the golden
        reader's gcd of one would cost the square of its length. In lowest
        terms a token's parts ARE its value's, so its digits decide the
        rule for its value too."""
        m = _RAT.fullmatch(tok)
        if not m:
            if re.fullmatch(r"-?[0-9a-f]+/0+", tok):
                why = "a zero denominator"
            else:
                why = ("not hex numerator/denominator in their one "
                       "spelling (lowercase, no leading zeros, the sign "
                       "on the numerator, no '+')")
            raise self.malformed(f"{what} {tok[:80]!r}: {why}", i)
        nb, db = _hex_bits(m.group(1).lstrip("-")), _hex_bits(m.group(2))
        if nb > WIDTH or db > WIDTH:
            raise self.fail("width", f"{what} {tok[:40]!r}... is a {nb}-bit "
                                     f"numerator over a {db}-bit denominator "
                                     f"by its digits; version 1 allows "
                                     f"{WIDTH} bits each", i)
        n, d = int(m.group(1), 16), int(m.group(2), 16)
        if n == 0 and d != 1:
            raise self.malformed(f"{what} {tok[:80]!r}: zero is spelled 0/1",
                                 i)
        if math.gcd(abs(n), d) != 1:
            raise self.malformed(f"{what} {tok[:80]!r} is not in lowest "
                                 f"terms", i)
        return Fraction(n, d)

    def element(self, fmt, htok, dtok, what):
        """An element, read from the line just taken by expect(): exactly
        width/4 hex digits of its bits, then its exact decimal, which
        must be THE exact decimal of those bits."""
        at = self.pos - 1
        f = FORMATS[fmt]
        if not re.fullmatch(r"[0-9a-f]{%d}" % (f.width // 4), htok):
            raise self.malformed(f"{what} {htok[:80]!r} is not "
                                 f"{f.width // 4} lowercase hex digits "
                                 f"(an {fmt} element's bits)", at)
        bits = int(htok, 16)
        if element_fraction(f, bits)[0] == "nan":
            raise self.malformed(f"{what} is a NaN, and an accuracy value "
                                 f"is a number", at)
        want = exact_decimal(f, bits)
        if dtok != want:
            raise self.fail("decimal",
                            f"{what}: the decimal {dtok[:60]!r} is not the "
                            f"exact decimal of {htok}, which is "
                            f"{want[:60]!r}"
                            f"{'...' if len(want) > 60 else ''}", at)
        return bits

    # -- counted groups -------------------------------------------------

    def count_line(self, key, member, minimum, consecutive, stop=()):
        """`key N`, then its N members, counted BEFORE they are read:
        a count that disagrees with the lines present is `count`,
        whatever else is wrong with them."""
        i = self.pos
        toks = self.expect(key, 2)
        n = self.dec(toks[1], key, lo=minimum, i=i)
        have = 0
        for j in range(self.pos, len(self.lines)):
            k = self.lines[j][0]
            if consecutive and k != member:
                break
            if k in stop:
                break
            if k == member:
                have += 1
        if have != n:
            raise self.fail("count", f"'{key}' says {n} and {have} "
                                     f"'{member}' line"
                                     f"{'s' if have != 1 else ''} follow",
                            i)
        return n

    def member_index(self, key, want, stop=(), consecutive=True):
        """The group member here must carry index `want`."""
        if self.key() != key:
            raise self.classify(key)
        toks = self.lines[self.pos]
        got = _index(toks[1]) if len(toks) > 1 else None
        if got is None:
            raise self.malformed(f"'{key}' needs its index first: a decimal "
                                 f"integer in its one spelling, at most "
                                 f"2^63 - 1")
        if got == want:
            return
        later = []
        for j in range(self.pos + 1, len(self.lines)):
            k = self.lines[j][0]
            if (consecutive and k != key) or k in stop:
                break
            if k == key and len(self.lines[j]) > 1 \
                    and _index(self.lines[j][1]) is not None:
                later.append(_index(self.lines[j][1]))
        if got < want:
            raise self.fail("line-unexpected",
                            f"'{key} {got}' again, where '{key} {want}' "
                            f"belongs")
        if want in later:
            raise self.fail("line-order",
                            f"'{key} {got}' comes before '{key} {want}', "
                            f"which belongs first")
        raise self.fail("line-missing", f"'{key} {want}' is missing; "
                                        f"'{key} {got}' is here instead")

    # -- the certificate ------------------------------------------------------

    def certificate(self):
        if not self.lines:
            raise Refusal("magic", "the body is empty; its first line must "
                                   "be 'cft-certificate 1'", line=1)
        first = self.lines[0]
        if first[0] != MAGIC:
            raise Refusal("magic", f"line 1 is {' '.join(first)[:80]!r}; a "
                                   f"certificate begins 'cft-certificate 1'",
                          line=1)
        if first != [MAGIC, "1"]:
            if len(first) == 2 and _DEC.fullmatch(first[1]):
                raise Refusal("version", f"this is 'cft-certificate "
                                         f"{first[1]}', and this reader "
                                         f"speaks version 1 only", line=1)
            raise Refusal("malformed", "line 1 must be exactly "
                                       "'cft-certificate 1'", line=1)
        # Every key is known before any structure is read, so that an
        # unknown line is named for what it is wherever it stands -
        # inside a counted group too, where a count would otherwise
        # see it first.
        for i, toks in enumerate(self.lines):
            if toks[0] not in RANK:
                raise self.fail("unknown-line",
                                f"'{toks[0][:80]}' is not a line of "
                                f"version 1", i)
        self.pos = 1
        mode = self.expect("mode", 2)[1]
        if mode not in MODES:
            raise self.fail("mode-unknown",
                            f"mode {mode[:40]!r}: this reader knows 'keyed' "
                            f"and 'open'", self.pos - 1)
        # The commitment line is there exactly when the certificate is
        # keyed - wherever it stands, which is why this is decided from
        # the whole body before its place is.
        at = [i for i, t in enumerate(self.lines) if t[0] == "salt-commitment"]
        if mode == "open" and at:
            raise self.fail("commitment-unexpected",
                            "an open certificate has no salt and so no "
                            "salt commitment", at[0])
        if mode == "keyed" and not at:
            raise self.fail("commitment-missing",
                            "a keyed certificate commits to its salt on the "
                            "line after its mode, and this one has no "
                            "salt-commitment line")
        sc = None
        if mode == "keyed":
            sc = self.hexn(self.expect("salt-commitment", 2)[1], 64,
                           "the salt commitment", self.pos - 1)
        idn = self.identity()
        R = self.count_line("runs", "run", 1, False, stop=("accuracy", "end"))
        runs = tuple(self.run(i) for i in range(R))
        A = self.count_line("accuracy", "entry", 0, False, stop=("end",))
        self.block = BLOCK_OF["accuracy"]
        acc = tuple(self.entry(j) for j in range(A))
        self.expect("end", 1)
        self.block = BLOCK_OF["end"]
        if self.pos != len(self.lines):
            # (a key there is a known one: the scan above refused any
            # other, wherever it stood)
            raise self.fail("line-unexpected",
                            f"'{self.key()}' after 'end'; the body ends at "
                            f"'end'")
        return Certificate(mode, sc, idn, runs, acc)

    def identity(self):
        def one(key, words=(), hexn=None, dec=False):
            toks = self.expect(key, 2)
            v = toks[1]
            if v in words:
                return v
            if hexn and _HEX[hexn].fullmatch(v):
                return v
            if dec and _DEC.fullmatch(v):
                return self.dec(v, key, lo=1, i=self.pos - 1)
            raise self.malformed(f"'{key}' {v[:80]!r} is not "
                                 + " or ".join(
                                     ([f"{hexn} lowercase hex digits"]
                                      if hexn else [])
                                     + (["a decimal integer"] if dec else [])
                                     + [repr(w) for w in words]),
                                 self.pos - 1)

        # cft_build_id()'s string, verbatim, in its own grammar:
        # `unknown` whole, or its three fields in their order, each
        # spelt as the library spells it.
        toks = self.expect("build-id")
        if toks[1:] == ["unknown"]:
            build = "unknown"
        elif (len(toks) == 4 and _BUILD_COMMIT.fullmatch(toks[1])
              and toks[2] in ("tracked=clean", "tracked=modified")
              and toks[3] in ("untracked=none", "untracked=present")):
            build = " ".join(toks[1:])
        else:
            raise self.malformed("'build-id' is cft_build_id()'s string "
                                 "verbatim: 'commit=<40 or 64 lowercase "
                                 "hex> tracked=<clean|modified> "
                                 "untracked=<none|present>', or 'unknown'",
                                 self.pos - 1)
        backend = one("backend", ("software", "xrt", "remote", "unknown"))
        xclbin = one("device-xclbin", ("none", "unknown"), hexn=64)
        version = one("device-version", ("none", "unknown"), hexn=8)
        toks = self.expect("device-caps")
        if toks[1:] in (["none"], ["unknown"]):
            caps = toks[1]
        elif len(toks) in (2, 3) and all(_HEX[8].fullmatch(t)
                                         for t in toks[1:]):
            caps = tuple(toks[1:])
        else:
            raise self.malformed("'device-caps' is the raw words "
                                 "cft_get_image_id gives - CAPS alone, or "
                                 "CAPS then CAPS2, each 8 lowercase hex "
                                 "digits - or 'none' or 'unknown'",
                                 self.pos - 1)
        tiles = one("device-tiles", ("unknown",), dec=True)
        return Identity(build, backend, xclbin, version, caps, tiles)

    def run(self, i):
        self.member_index("run", i, stop=("accuracy", "end"),
                          consecutive=False)
        toks = self.expect("run")
        self.block = BLOCK_OF["run"]
        at = self.pos - 1
        h_slots = ()
        if len(toks) < 3:
            raise self.malformed("'run' is 'run <index> main', "
                                 "'run <index> half-step h-slots <n> ...' "
                                 "or 'run <index> wider'", at)
        kind = toks[2]
        if kind == "main":
            if i != 0 or len(toks) != 3:
                raise self.malformed("run 0, and only run 0, is 'run 0 "
                                     "main'", at)
        elif kind == "wider":
            if i == 0 or len(toks) != 3:
                raise self.malformed("'run <index> wider' is an auxiliary "
                                     "run, never run 0, and takes nothing "
                                     "more", at)
        elif kind == "half-step":
            if i == 0:
                raise self.malformed("run 0 is the main run; a half-step "
                                     "run is auxiliary", at)
            if len(toks) < 5 or toks[3] != "h-slots":
                raise self.malformed("'run <index> half-step h-slots <n> "
                                     "<slot> ...'", at)
            n = self.dec(toks[4], "the h-slot count", lo=1,
                         hi=seq.KADDR_KX, i=at)
            have = len(toks) - 5
            if have != n:
                raise self.fail("count", f"'h-slots {n}' and {have} slot "
                                         f"index{'es' if have != 1 else ''} "
                                         f"follow", at)
            h = [self.dec(t, "an h-slot", hi=seq.KADDR_KX - 1, i=at)
                 for t in toks[5:]]
            for a, b in zip(h, h[1:]):
                if b <= a:
                    raise self.malformed("h-slot indices are strictly "
                                         "increasing", at)
            h_slots = tuple(h)
        else:
            raise self.malformed(f"run kind {kind[:40]!r} is not main, "
                                 f"half-step or wider", at)

        fmt = self.word(self.expect("program-format", 2)[1], LADDER,
                        "the program format")
        image = self.hexn(self.expect("program-image", 2)[1], 64,
                          "the image digest", self.pos - 1)
        digest = self.hexn(self.expect("program-digest", 2)[1], 64,
                           "the program digest", self.pos - 1)
        lanes = self.dec(self.expect("lanes", 2)[1], "lanes", lo=1,
                         i=self.pos - 1)
        steps = self.dec(self.expect("steps", 2)[1], "steps", lo=1,
                         i=self.pos - 1)
        streams = tuple(self.hexn(self.expect(f"stream-{s}", 2)[1], 64,
                                  f"stream {s}'s hash", self.pos - 1)
                        for s in "abc")
        P = self.count_line("parameters", "parameter", 0, True)
        params = []
        for _ in range(P):
            toks = self.expect("parameter", 3)
            at = self.pos - 1
            if not _NAME.fullmatch(toks[1]):
                raise self.malformed(f"parameter name {toks[1][:80]!r} is "
                                     f"not [a-z][a-z0-9-]*, at most 64", at)
            if params and toks[1] <= params[-1][0]:
                if toks[1] == params[-1][0]:
                    raise self.fail("line-unexpected",
                                    f"parameter {toks[1]!r} again", at)
                raise self.fail("line-order",
                                f"parameter {toks[1]!r} comes after "
                                f"{params[-1][0]!r}; names are in "
                                f"increasing order", at)
            v = self.dec(toks[2], "a parameter", i=at)
            if toks[1] == DEPTH_PARAMETER and not _is_depth(v):
                raise self.malformed(f"parameter {DEPTH_PARAMETER} {v}: a "
                                     f"run's scratch depth is a power of two "
                                     f"in 1..{seq.SCRATCH_D_MAX}", at)
            params.append((toks[1], v))
        S = self.count_line("segments", "segment", 1, True)
        chain = []
        for k in range(S):
            self.member_index("segment", k)
            toks = self.expect("segment", 10)
            at = self.pos - 1
            if (toks[2], toks[4], toks[6], toks[8]) != ("start", "end",
                                                        "flags", "status"):
                raise self.malformed("'segment <k> start <hash> end <hash> "
                                     "flags <n> status <n>'", at)
            chain.append(Segment(
                self.hexn(toks[3], 64, "a start hash", at),
                self.hexn(toks[5], 64, "an end hash", at),
                self.dec(toks[7], "flags", hi=31, i=at),
                self.dec(toks[9], "status", hi=(1 << 32) - 1, i=at)))
        output = self.hexn(self.expect("output", 2)[1], 64, "the output hash",
                           self.pos - 1)
        return Run(kind, fmt, image, digest, lanes, steps, streams,
                   tuple(params), tuple(chain), output, h_slots)

    def entry(self, j):
        self.member_index("entry", j, stop=("end",), consecutive=False)
        toks = self.expect("entry", 3)
        self.block = BLOCK_OF["entry"]
        method = self.word(toks[2], tuple(METHOD_KIND), "the method")
        kind = self.word(self.expect("kind", 2)[1], KINDS, "the kind")
        if kind != METHOD_KIND[method]:
            raise self.fail(
                "accuracy-kind",
                f"entry {j}: the kind of {method} is "
                f"{METHOD_KIND[method]}, not {kind}"
                + ("; a bound needs a rigorous remainder, and no version-1 "
                   "method has one" if kind == "bound" else ""),
                self.pos - 1)
        uses = self.dec(self.expect("uses", 2)[1], "the run used",
                        i=self.pos - 1)
        toks = self.expect("scope")
        if toks == ["scope", "max-lanes"]:
            lane = None
        elif len(toks) == 3 and toks[1] == "lane":
            lane = self.dec(toks[2], "the lane", i=self.pos - 1)
        else:
            raise self.malformed("'scope lane <i>' or 'scope max-lanes'",
                                 self.pos - 1)
        label, terms = None, ()
        if method == "drift":
            i = self.pos
            toks = self.expect("quantity")
            if len(toks) != 4 or toks[2] != "terms":
                raise self.malformed("'quantity <label> terms <n>'", i)
            if not _NAME.fullmatch(toks[1]):
                raise self.malformed(f"label {toks[1][:80]!r} is not "
                                     f"[a-z][a-z0-9-]*, at most 64", i)
            label = toks[1]
            t = self.dec(toks[3], "the term count", lo=1, hi=MAX_TERMS, i=i)
            have = 0
            for q in range(self.pos, len(self.lines)):
                if self.lines[q][0] != "term":
                    break
                have += 1
            if have != t:
                raise self.fail("count", f"'terms {t}' and {have} 'term' "
                                         f"line{'s' if have != 1 else ''} "
                                         f"follow", i)
            out = []
            for _ in range(t):
                toks = self.expect("term")
                at = self.pos - 1
                if len(toks) < 2:
                    raise self.malformed("'term <coefficient> [s<slot> ...]'",
                                         at)
                c = self.rational(toks[1], "a coefficient", at)
                slots = []
                for f in toks[2:]:
                    m = _SLOT.fullmatch(f)
                    if not m:
                        raise self.malformed(f"factor {f[:40]!r} is not "
                                             f"s<slot>", at)
                    slots.append(self.dec(m.group(1), "a slot", hi=0xFFFF,
                                          i=at))
                if len(slots) > MAX_FACTORS:
                    raise self.malformed(f"a term has at most {MAX_FACTORS} "
                                         f"factors", at)
                if slots != sorted(slots):
                    raise self.malformed("a term's factors are in "
                                         "non-decreasing slot order", at)
                out.append((c, tuple(slots)))
            terms = tuple(out)
        value = self.value()
        return Entry(method, kind, uses, lane, value, label, terms)

    def value(self):
        toks = self.expect("value")
        at = self.pos - 1
        form = toks[1] if len(toks) > 1 else None
        if form == "exact" and len(toks) == 3:
            return Value("exact", exact=self.rational(toks[2], "the value",
                                                      at))
        if form == "rounded" and len(toks) == 6:
            fmt = self.word(toks[2], LADDER, "the value's format")
            rnd = self.word(toks[3], tuple(RND), "the rounding direction")
            bits = self.element(fmt, toks[4], toks[5], "the value")
            return Value("rounded", fmt=fmt, rnd=rnd, bits=bits)
        if form == "enclosed" and len(toks) == 7:
            fmt = self.word(toks[2], LADDER, "the value's format")
            lo = self.element(fmt, toks[3], toks[4], "the lower end")
            hi = self.element(fmt, toks[5], toks[6], "the upper end")
            # The audit compares each end with the exact value, an exact
            # step like any other, so a finite end is held to the width
            # rule; an infinite end compares by its sign alone. (A
            # rounded value's element is not: the audit rounds the exact
            # value and compares BITS, which needs no exact comparison.)
            for end, what in ((lo, "the lower end"), (hi, "the upper end")):
                kind, v = element_fraction(fmt, end)
                if kind == "finite":
                    try:
                        _checked(v, f"{what}'s exact value")
                    except Refusal as r:
                        raise self.fail("width", r.message, at)
            if _order_key(fmt, lo) > _order_key(fmt, hi):
                raise self.malformed("an enclosure's lower end is above its "
                                     "upper end", at)
            return Value("enclosed", fmt=fmt, lo=lo, hi=hi)
        raise self.malformed("'value exact <rational>', 'value rounded <fmt> "
                             "<rnd> <hex> <decimal>' or 'value enclosed <fmt> "
                             "<hex> <decimal> <hex> <decimal>'", at)


def _order_key(fmt, bits):
    """A non-NaN element as a comparable key (-inf < finite < inf)."""
    kind, v = element_fraction(fmt, bits)
    if kind == "-inf":
        return (0, 0)
    if kind == "inf":
        return (2, 0)
    return (1, v)


def parse(data, salt=None):
    """The bytes -> a Certificate, or a Refusal by name.

    The order is the specification's: the hash line, the body's hash,
    then the body line by line. With `salt`, the salt is checked too
    (after the body has been read): against the commitment of a keyed
    certificate, and refused outright for an open one."""
    body, digest = _split_hash(data)
    if sha256(body) != digest:
        raise Refusal("body-hash",
                      "the hash line is not the SHA-256 of the body: the "
                      "bytes are not the ones it was written over")
    cert = _Reader(_split_lines(body)).certificate()
    if salt is not None:
        check_salt(cert, salt)
    return cert


def check_salt(cert, salt):
    """The salt handed to an auditor (None for none), against the
    certificate's mode and commitment."""
    if cert.mode == "open":
        if salt is not None:
            raise Refusal("salt-unexpected",
                          "this certificate is open: its hashes are not "
                          "keyed, and a salt handed to its audit would be "
                          "believed to mean something it does not")
        return
    if salt is None:
        raise Refusal("salt-missing",
                      "this certificate is keyed: its state and stream "
                      "hashes can be checked only with the owner's salt, "
                      "and none was handed")
    _check_salt_length(salt)
    if not hmac.compare_digest(salt_commitment(salt), cert.salt_commitment):
        raise Refusal("salt-commitment",
                      "HMAC(salt, 'cft-certificate 1 salt') is not the "
                      "certificate's salt-commitment: this is not its salt")


# ---- the golden writer: a run, segment by segment ------------------------

def _bank_values(prog, bank):
    """A bank's bytes -> its values, with the refusals the executor
    would make: a BANK_EXT program's bank is exactly n_consts elements,
    and a program with its own constants takes none."""
    bank = bytes(bank or b"")
    esz = prog.fmt.width // 8
    if not prog.bank_ext:
        if bank:
            raise Refusal("program-image",
                          "this image carries its own constants, so the "
                          "bank must be empty")
        return None
    if len(bank) != prog.n_consts * esz:
        raise Refusal("program-image",
                      f"the bank is {len(bank)} bytes; the image addresses "
                      f"{prog.n_consts} constants of {esz} bytes")
    return state_values(prog.fmt, bank)


def _segment_shape(prog):
    """A program is a segment when its whole state enters through the
    scratch block and leaves through a block of the same shape, and
    nothing else comes out: version 1 certifies the state, so a program
    that deposits would be half certified, and is refused."""
    if not prog.scratch_io:
        return "it declares no scratch block (flags.SCRATCH_IO clear)"
    if prog.n_scratch_in != prog.n_scratch_out or prog.n_scratch_in < 1:
        return (f"its scratch block goes in as {prog.n_scratch_in} and out "
                f"as {prog.n_scratch_out} slots a lane; a segment's end "
                f"state must be the next one's start")
    if prog.max_deposits:
        return (f"it deposits ({prog.max_deposits} slots a lane); version 1 "
                f"certifies the scratch state only, and a deposit would go "
                f"uncertified")
    return None


def scratch_depth_of(identity, run=None):
    """The scratch depth a run had, which the audit re-runs it at
    (revision 7): 1 << CAPS2[3:0] where `device-caps` carries CAPS2 with
    CAPS2[4] set, which every tile from revision 3 does - 256 on the
    round-2 images, 2,048 on the U50's revision-7 ones - and then for
    every run, since a certificate names one device. Otherwise the run's
    `scratch-depth` parameter, where it states one (the audit round,
    2026-09-29): a software handle opened deeper says its depth so, and
    the reader has held it to a power of two in 1..32,768. Otherwise the
    model's default of 256: the software backend's opened plainly, and
    every tile's before revision 7. A REMOTE handle's certificate records
    `unknown` and is re-run at 256 unless its runs state a depth,
    whatever its server's - the protocol carries no CAPS2 (a known limit,
    docs/CERTIFICATES.md). With no `run`, the answer the device lines
    alone give: CAPS2's depth, or 256.

    Reading the word is not checking it. The identity is still stated and
    never checked; a certificate that misstates its device's depth simply
    fails its own re-run, as one that misstates any number the arithmetic
    reads does."""
    caps = identity.device_caps
    if isinstance(caps, tuple) and len(caps) == 2:
        word = int(caps[1], 16)
        if word & 0x10:
            return 1 << (word & 0xF)
    if run is not None:
        for name, v in run.parameters:
            if name == DEPTH_PARAMETER:
                return v
    return seq.SCRATCH_D


def run_chain(image, bank, initial, segments, streams=None,
              scratch_depth=seq.SCRATCH_D):
    """Run `image` as `segments` consecutive segments from `initial`
    (the lane-major scratch block), each starting where the last ended.
    Returns (states, results): the S + 1 boundary states and each
    segment's (flags, status). The golden writer's arithmetic, by
    seq.run and nothing else, on a tile of `scratch_depth` slots
    (revision 7; 256 by default)."""
    prog = seq.Program.from_bytes(bytes(image), scratch_depth=scratch_depth)
    why = _segment_shape(prog)
    if why:
        raise Refusal("program-shape", f"this program is not a segment: "
                                       f"{why}")
    bankv = _bank_values(prog, bank)
    nslots = prog.n_scratch_in
    if len(initial) % nslots:
        raise Refusal("state-shape", f"{len(initial)} values is not a whole "
                                     f"number of lanes of {nslots} slots")
    n = len(initial) // nslots
    a, b, c = _streams_or_zero(prog.fmt, n, streams)
    states = [list(initial)]
    results = []
    for _ in range(segments):
        res = seq.run(prog, a, b, c, bank=bankv, scratch_in=states[-1],
                      scratch_depth=scratch_depth)
        states.append(list(res.scratch_out))
        results.append((res.flags, res.status))
    return states, results


def _streams_or_zero(fmt, n, streams):
    zero = sf.zero_bits(fmt, 0)
    if streams is None:
        return [zero] * n, [zero] * n, [zero] * n
    out = tuple(list(s) if s is not None else [zero] * n for s in streams)
    for name, s in zip("abc", out):
        if len(s) != n:
            raise Refusal("stream", f"stream {name} holds {len(s)} values; "
                                    f"the run has {n} lanes")
    return out


def certify_run(kind, image, bank, salt, states, results, *, steps,
                streams=None, parameters=(), h_slots=(),
                scratch_depth=seq.SCRATCH_D):
    """A Run from a chain of boundary states and segment results (from
    run_chain, or a producer's own): the hashes of every boundary, the
    image and program digests, the streams' hashes - keyed under `salt`,
    or open when `salt` is None. The image is read as written for
    `scratch_depth` slots, the depth its chain ran at."""
    prog = seq.Program.from_bytes(bytes(image), scratch_depth=scratch_depth)
    why = _segment_shape(prog)
    if why:
        raise Refusal("program-shape", f"this program is not a segment: "
                                       f"{why}")
    if not results:
        raise Refusal("malformed", "a run has at least one segment, and this "
                                   "one has none: the format has no "
                                   "spelling for an empty run")
    if len(states) != len(results) + 1:
        raise Refusal("state-shape",
                      f"{len(results)} segments have {len(results) + 1} "
                      f"boundary states, and {len(states)} were given")
    fmt = prog.fmt
    nslots = prog.n_scratch_in
    n = len(states[0]) // nslots
    a, b, c = _streams_or_zero(fmt, n, streams)
    hs = [state_hash(salt, state_bytes(fmt, s)) for s in states]
    chain = tuple(Segment(hs[k], hs[k + 1], fl, st)
                  for k, (fl, st) in enumerate(results))
    return Run(kind, fmt.name, sha256(image), sha256(bytes(image)
                                                     + bytes(bank or b"")),
               n, steps,
               tuple(stream_hash(salt, nm, state_bytes(fmt, s))
                     for nm, s in zip("abc", (a, b, c))),
               tuple((nm, int(v)) for nm, v in parameters), chain, hs[-1],
               tuple(h_slots))


# ---- accuracy: each value as the stated function of certified runs ------

def derive(entry, runs, shapes, states):
    """The exact value `entry` names, computed from certified states.

    `runs` are the certificate's runs; `shapes[r]` is (format, slots a
    lane) of run r's program; `states[(r, b)]` is run r's boundary-b
    state (boundary 0 the initial state, boundary S the output), each
    already held to its certified hash. The width rule applies to every
    value computed, in the order the specification fixes."""
    r = entry.uses
    if not 0 <= r < len(runs):
        raise Refusal("accuracy-run", f"entry uses run {r}, and the "
                                      f"certificate has {len(runs)}")
    if entry.method != "drift":
        want = METHOD_RUN[entry.method]
        if r == 0 or runs[r].kind != want:
            raise Refusal("accuracy-run",
                          f"a {entry.method} estimate compares run 0 with a "
                          f"{want} run; run {r} is "
                          f"{'the main run' if r == 0 else runs[r].kind}")
        # An estimate compares the two final states lane by lane and slot
        # by slot, so it is defined only where run r has run 0's lanes and
        # slots a lane (the lead's decision, 2026-09-30: it was an
        # IndexError here, or run 0's state read by run r's shape). An
        # audit never meets it: step 8 refuses such a run first, aux-lanes
        # or aux-image. A writer, which checks no relation, meets it here.
        if runs[r].lanes != runs[0].lanes or shapes[r][1] != shapes[0][1]:
            raise Refusal("accuracy-run",
                          f"a {entry.method} estimate compares run 0's final "
                          f"state with run {r}'s, lane by lane and slot by "
                          f"slot; run {r} is {runs[r].lanes} lanes of "
                          f"{shapes[r][1]} slots and run 0 is "
                          f"{runs[0].lanes} lanes of {shapes[0][1]}")
    # A lane and a slot are indices from 0, as the run is: each is bounded
    # from below too (the lead's decision, 2026-09-30: a negative one was
    # read by Python's index from the end - another lane's value, or an
    # IndexError; verifier-W1b). An audit never meets one: the reader
    # refuses a certificate that spells one. A writer meets it here.
    lanes = runs[r].lanes
    if entry.lane is not None and not 0 <= entry.lane < lanes:
        raise Refusal("accuracy-scope", f"lane {entry.lane} of a run of "
                                        f"{lanes} lanes")
    fmt, nslots = shapes[r]

    def need(rr, b):
        s = states.get((rr, b))
        if s is None:
            raise Refusal("state-missing",
                          f"run {rr} boundary {b}: the accuracy entry needs "
                          f"this state, and it was neither handed nor "
                          f"re-run into", run=rr, segment=b)
        return s

    pick = range(lanes) if entry.lane is None else (entry.lane,)
    if entry.method == "drift":
        for _, slots in entry.terms:
            for s in slots:
                if not 0 <= s < nslots:
                    raise Refusal("accuracy-slot",
                                  f"a term names slot {s}; run {r}'s state "
                                  f"has {nslots} slots a lane")
        first, last = need(r, 0), need(r, len(runs[r].chain))

        def q_of(state, i, which):
            q = Fraction(0)
            for t, (c, slots) in enumerate(entry.terms):
                p = c
                for s in slots:
                    v = _exact(fmt, state[i * nslots + s],
                               f"lane {i} slot {s} of the {which} state")
                    p = _checked(p * v, f"term {t}'s product, lane {i}")
                q = _checked(q + p, f"the quantity's sum at term {t}, lane "
                                    f"{i}")
            return q

        vals = [(_checked(q_of(last, i, "final") - q_of(first, i, "initial"),
                          f"the drift of lane {i}")) for i in pick]
    else:
        fmt0, _ = shapes[0]
        f0, fr = need(0, len(runs[0].chain)), need(r, len(runs[r].chain))
        vals = []
        for i in pick:
            e = Fraction(0)
            for s in range(nslots):
                a = _exact(fmt0, f0[i * nslots + s],
                           f"run 0 lane {i} slot {s}")
                b = _exact(fmt, fr[i * nslots + s],
                           f"run {r} lane {i} slot {s}")
                d = _checked(abs(a - b), f"the difference at lane {i} slot "
                                         f"{s}")
                e = max(e, d)
            vals.append(e)
    if entry.lane is not None:
        return vals[0]
    return max(abs(v) for v in vals)


def make_value(q, form="exact", fmt=None, rnd=None):
    """The Value a writer records for the exact value q: exact, rounded
    in `fmt` under `rnd`, or enclosed in `fmt` by its two directed
    roundings (the tightest enclosure that format holds). An end of that
    pair can be past the width rule when q is not: encode() then refuses
    it `width`, and the pair is never widened (verifier-C2).

    The exact value is held to the width rule whatever the form: a
    rounded or enclosed value is still a statement about q, which an
    auditor must compute exactly to check, so a value past the rule is
    refused here rather than rounded into something that looks
    checkable (the page: "nothing past it is ever approximated").

    What it cannot spell - a value that is not a rational, a form, a
    format or a direction the page does not name - is refused
    `malformed`, by name, like everything else the writer is handed."""
    if not isinstance(q, (Fraction, int)) or isinstance(q, bool):
        raise Refusal("malformed", f"a value is an exact rational (a "
                                   f"Fraction or an int), not a "
                                   f"{type(q).__name__}")
    _checked(q, "the value")
    if form == "exact":
        return Value("exact", exact=q)
    if form not in ("rounded", "enclosed"):
        raise Refusal("malformed", f"a value's form is exact, rounded or "
                                   f"enclosed, not {form!r}")
    if fmt not in LADDER:
        raise Refusal("malformed", f"a {form} value's format is one of "
                                   f"{', '.join(LADDER)}, not {fmt!r}")
    if form == "rounded":
        if not isinstance(rnd, str) or rnd not in RND:
            raise Refusal("malformed", f"a rounded value's direction is one "
                                       f"of {', '.join(RND)}, not {rnd!r}")
        return Value("rounded", fmt=fmt, rnd=rnd,
                     bits=round_rational(fmt, q, rnd))
    return Value("enclosed", fmt=fmt, lo=round_rational(fmt, q, "rdn"),
                 hi=round_rational(fmt, q, "rup"))


def value_holds(value, q):
    """Does the recorded value state the exact value q?"""
    if value.form == "exact":
        return value.exact == q
    if value.form == "rounded":
        return value.bits == round_rational(value.fmt, q, value.rnd)
    return (_order_key(value.fmt, value.lo) <= (1, q)
            <= _order_key(value.fmt, value.hi))


# ---- sampling ---------------------------------------------------------------

def _words(seed, run):
    """The sampling PRNG's 64-bit words for run `run`: SHA-256 blocks of
    TAG_SAMPLE || seed || run (4 bytes BE) || counter (8 bytes BE),
    each block read as four big-endian 64-bit words in order."""
    block = 0
    while True:
        h = hashlib.sha256(TAG_SAMPLE + seed + run.to_bytes(4, "big")
                           + block.to_bytes(8, "big")).digest()
        for i in range(4):
            yield int.from_bytes(h[8 * i:8 * i + 8], "big")
        block += 1


def _uniform(words, m):
    """A uniform integer in [0, m) by rejection: no modulo bias."""
    limit = (1 << 64) - ((1 << 64) % m)
    while True:
        w = next(words)
        if w < limit:
            return w % m


def sample(seed, run, S, k):
    """The k segments of S the auditor re-runs for run `run`: a partial
    Fisher-Yates shuffle of 0..S-1 driven by the PRNG, the first k
    taken and sorted. The seed is the AUDITOR's, chosen after the
    certificate is fixed - never derived from it."""
    if not isinstance(seed, (bytes, bytearray)) or len(seed) != SEED_BYTES:
        raise Refusal("choice", f"a sampling seed is exactly {SEED_BYTES} "
                                f"bytes")
    if not _is_int(run) or not 0 <= run < (1 << 32):
        raise Refusal("choice", f"run {run!r}: a run index is an integer in "
                                f"0..2^32 - 1, the PRNG's four bytes")
    if not _is_int(S) or not _is_int(k) or not 1 <= k <= S:
        raise Refusal("choice", f"a sample of {k!r} from {S!r} segments; "
                                f"both are integers, 1 <= k <= S")
    words = _words(bytes(seed), run)
    idx = list(range(S))
    for j in range(k):
        r = j + _uniform(words, S - j)
        idx[j], idx[r] = idx[r], idx[j]
    return sorted(idx[:k])


def escape_probability(S, k, f):
    """C(S - f, k) / C(S, k): the chance that a sample of k from S
    segments misses all of f wrong ones. For f = 1, the value the verdict
    prints, it is (S - k)/S and is computed so: equal to the binomials'
    ratio, and linear in the digits of S where two binomials of S and
    their gcd are not (the lead's decision, 2026-09-29)."""
    if f == 1:
        return Fraction(S - k, S)
    return Fraction(math.comb(S - f, k), math.comb(S, k))


# ---- the audit --------------------------------------------------------------

@dataclass
class Verdict:
    """What an audit found. `runs[r]` says which segments were re-run
    and how they were chosen; `accuracy[j]` is entry j's re-derived
    exact value; `identity` is the producer's statement, reported."""
    runs: list
    accuracy: list
    identity: list
    mode: str = "keyed"
    exit_code: int = 0

    def lines(self):
        out = ["cft-certificate 1: ACCEPTED - every check passed",
               "keyed: the salt handed is the one committed to"
               if self.mode == "keyed" else
               "open: no salt - its hashes are plain SHA-256, and anyone "
               "holding the states can audit it"]
        for r in self.runs:
            head = (f"run {r['run']} {r['kind']} {r['format']}, "
                    f"{r['lanes']} lanes, {r['segments']} segments: re-ran "
                    f"{len(r['rerun'])} of {r['segments']}")
            if r["how"] == "sample":
                S, k = r["segments"], len(r["rerun"])
                p1 = escape_probability(S, k, 1)
                head += (f", a sample drawn with the auditor's seed "
                         f"{r['seed']}: a producer who made f of these {S} "
                         f"segments wrong escapes it with probability "
                         f"C({S}-f,{k})/C({S},{k}); for f = 1 that is "
                         f"{p1.numerator}/{p1.denominator}; the segments "
                         f"sampled: {_segment_list(r['rerun'])}")
            elif r["how"] == "named":
                head += f", the segments named: {_segment_list(r['rerun'])}"
            else:
                head += ", every segment"
            out.append(head)
        for j, q in enumerate(self.accuracy):
            out.append(f"accuracy entry {j}: re-derived as {rational_text(q)}"
                       f" - the value is the stated function of the "
                       f"certified runs; that an estimate estimates well is "
                       f"not shown")
        out += self.identity
        return out


def _segment_list(segments):
    """Segment indices as the verdict spells them, a sample's and a named
    choice's alike: in decimal, a comma and one space between them, in
    square brackets - `[1, 3]` - in the order they were re-run, which the
    plan makes ascending. P1's C auditor prints the same bytes (the audit
    round's ledger, P3.md, 2026-09-29)."""
    return "[" + ", ".join(str(k) for k in segments) + "]"


def identity_report(cert):
    idn = cert.identity
    rows = [("build-id", idn.build_id),
            ("backend", idn.backend), ("device-xclbin", idn.device_xclbin),
            ("device-version", idn.device_version),
            ("device-caps", " ".join(idn.device_caps)
             if isinstance(idn.device_caps, tuple) else idn.device_caps),
            ("device-tiles", str(idn.device_tiles))]
    return [f"{k}: unknown - the producer did not record it" if v == "unknown"
            else f"{k}: {v} - stated, not checked" for k, v in rows]


def _as_values(fmt, s, name, where, run=None, segment=None):
    """A state or stream handed as values or as the bytes the library
    stores. Anything else, and bytes that are not whole elements, are
    refused by `name` (state-shape or stream), located by `run` and
    `segment`, not left to raise."""
    if isinstance(s, (bytes, bytearray)):
        esz = fmt.width // 8
        if len(s) % esz:
            raise Refusal(name, f"{where}: {len(s)} bytes is not a whole "
                                f"number of {fmt.name} elements ({esz} "
                                f"bytes each)", run=run, segment=segment)
        return state_values(fmt, s)
    if not isinstance(s, (tuple, list)) or not all(_is_int(v) for v in s):
        raise Refusal(name, f"{where}: handed as a {type(s).__name__}; it "
                            f"is the elements' bits as integers, or the "
                            f"bytes the library stores", run=run,
                      segment=segment)
    return list(s)


def audit(data, salt, programs, states=None, streams=None, choose=None,
          seed=None):
    """Audit a certificate. Returns a Verdict, or raises the first
    Refusal in the specification's order:

      1 integrity   the hash line, the body's hash
      2 form        the strict reader
        choice      the auditor's own choice of segments, against the
                    certificate's shape (a usage error, exit 64)
      3 salt        keyed: handed, 32 bytes, its commitment; open:
                    none handed
      4 programs    per run: image digest, program digest, the image
                    decodes, its format, its shape as a segment
      5 streams     per run: each handed one's length; then, for a
                    BOUNDED run, a, b and c against their hashes
      6 continuity  per run: each start is the last end; the output
      7 states      every state handed, against its boundary's hash
      8 relations   per auxiliary run, to the main run
      9 re-runs     per run, the chosen segments in ascending order,
                    each in blocks of BLOCK_LANES lanes (run_segment)
     10 accuracy    per entry, re-derived and held to its value

    What it spends is bounded by what it is handed, never by a number the
    certificate states (docs/CERTIFICATES.md, "What an audit spends"): a
    run's `lanes` is read against a stream or a state handed for that run
    before anything of its size is built or hashed, and a run with none
    such - BOUNDED by nothing handed - costs nothing and cannot be
    accepted. The scratch depth is at most 32,768 slots by the page, and
    a re-run holds one block of lanes at it.

    programs  {run: (image bytes, bank bytes)}
    states    {run: {boundary: values or bytes}}; boundary 0 is the
              initial state and boundary S the output. A segment whose
              start was not handed may start from the previous
              segment's re-run, when that re-run matched.
    streams   {run: (a, b, c)}, each `lanes` values; absent means +0
    choose    {run: "all" | [segment, ...] | ("sample", k)}; absent
              means every segment of every run
    seed      32 bytes for a sample - the auditor's own. Drawn from the
              operating system when None and a sample is asked for.
    """
    cert = parse(data)                                          # 1, 2
    plan = _plan(cert, choose, seed)                            # choice
    check_salt(cert, salt)                                      # 3
    progs = _check_programs(cert, programs)                     # 4
    strm = _check_streams(cert, salt, progs, streams, states)   # 5
    _check_continuity(cert)                                     # 6
    known = _check_states(cert, salt, progs, states)            # 7
    _check_relations(cert, salt, progs, strm, known)            # 8
    _rerun(cert, salt, progs, strm, known, plan)                # 9
    shapes = [(p["prog"].fmt, p["nslots"]) for p in progs]
    values = []
    for j, e in enumerate(cert.accuracy):                       # 10
        try:
            q = derive(e, cert.runs, shapes, known)
        except Refusal as r:
            raise Refusal(r.name, f"entry {j}: {r.message}", run=r.run,
                          segment=r.segment, entry=j)
        if not value_holds(e.value, q):
            raise Refusal("accuracy-value",
                          f"entry {j}: the value recorded is not the "
                          f"{e.method} of the certified runs, which is "
                          f"{rational_text(q)}", entry=j)
        values.append(q)
    return Verdict(plan, values, identity_report(cert), cert.mode)


def _run_mapping(cert, arg, what, name):
    """An argument that maps run indices to something - programs,
    streams, states, the choice - held to that shape before it is read:
    a dict whose every key is a run of this certificate. None is the
    empty mapping. Refused by the argument's own name."""
    if arg is None:
        return {}
    if not isinstance(arg, dict):
        raise Refusal(name, f"{what} is handed as a {type(arg).__name__}; it "
                            f"is a mapping from run index to its value")
    for r in arg:
        if not _is_int(r) or not 0 <= r < len(cert.runs):
            raise Refusal(name, f"{what} names run {r!r}, and the "
                                f"certificate's runs are 0.."
                                f"{len(cert.runs) - 1}")
    return arg


def _is_bytes(v):
    return isinstance(v, (bytes, bytearray))


def _check_programs(cert, programs):
    programs = _run_mapping(cert, programs, "programs", "program-image")
    out = []
    for r, run in enumerate(cert.runs):
        # The depth this run is re-run at (scratch_depth_of): the
        # certificate's device's, which is every run's, or else the run's
        # own scratch-depth parameter, or 256.
        depth = scratch_depth_of(cert.identity, run)
        if r not in programs:
            raise Refusal("program-image", f"run {r}: no program image was "
                                           f"handed to the audit", run=r)
        pair = programs[r]
        if not (isinstance(pair, (tuple, list)) and len(pair) == 2
                and _is_bytes(pair[0])
                and (pair[1] is None or _is_bytes(pair[1]))):
            raise Refusal("program-image",
                          f"run {r}: a program is handed as (image, bank), "
                          f"the image bytes and the bank bytes or None; this "
                          f"is a {type(pair).__name__}", run=r)
        image, bank = bytes(pair[0]), bytes(pair[1] or b"")
        if sha256(image) != run.image:
            raise Refusal("image-digest",
                          f"run {r}: the image handed is not the one "
                          f"certified (its SHA-256 differs)", run=r)
        if sha256(image + bank) != run.digest:
            raise Refusal("program-digest",
                          f"run {r}: the image and bank handed are not the "
                          f"ones certified (SHA-256 of image then bank "
                          f"differs)", run=r)
        try:
            prog = seq.Program.from_bytes(image, scratch_depth=depth)
        except seq.ProgramError as e:
            raise Refusal("program-image", f"run {r}: the image does not "
                                           f"load: {e}", run=r)
        if prog.fmt.name != run.fmt:
            raise Refusal("program-format",
                          f"run {r}: the image is {prog.fmt.name} and the "
                          f"certificate says {run.fmt}", run=r)
        why = _segment_shape(prog)
        if why:
            raise Refusal("program-shape",
                          f"run {r}: this program is not a segment: {why}",
                          run=r)
        try:
            bankv = _bank_values(prog, bank)
        except Refusal as e:
            raise Refusal(e.name, f"run {r}: {e.message}", run=r)
        out.append({"prog": prog, "bank": bank, "bankv": bankv,
                    "nslots": prog.n_scratch_in, "depth": depth})
    return out


def _state_bounds(states, r, S, lanes, esz):
    """Is run r BOUNDED by a state handed for it (docs/CERTIFICATES.md,
    "What an audit spends"): one for a boundary 0..S that holds at least
    `lanes` elements - a list or tuple of that many items, or bytes of at
    least lanes x esz, found by dividing the size handed, never by
    multiplying `lanes`? Reads the argument as it was handed and refuses
    nothing: a state in a shape step 7 refuses bounds nothing, and step 7
    refuses it by its own name."""
    if not isinstance(states, dict):
        return False
    for key, per in states.items():
        if not (_is_int(key) and key == r and isinstance(per, dict)):
            continue
        for b, s in per.items():
            if not (_is_int(b) and 0 <= b <= S):
                continue
            if isinstance(s, (bytes, bytearray)) and len(s) // esz >= lanes:
                return True
            if isinstance(s, (tuple, list)) and len(s) >= lanes:
                return True
    return False


def _check_streams(cert, salt, progs, streams, states):
    """Step 5, run by run. Each stream handed is held to the run's lanes
    by its length first, before anything is built beside it. Then, for a
    BOUNDED run only - one handed a stream, or a state of at least its
    lanes (_state_bounds) - the +0 streams are built and every stream is
    held to its certified hash. An unbounded run's are neither built nor
    checked, which costs nothing whatever its `lanes` says; it cannot be
    accepted, since its re-runs have no state of its size to start from
    (step 7's `state-shape`, or `state-missing` at step 8 or 9). Its
    entry is None."""
    streams = _run_mapping(cert, streams, "streams", "stream")
    out = []
    for r, run in enumerate(cert.runs):
        fmt = progs[r]["prog"].fmt
        given = streams.get(r)
        if given is not None:
            if not isinstance(given, (tuple, list)) or len(given) != 3:
                raise Refusal("stream",
                              f"run {r}: its streams are handed as (a, b, "
                              f"c), three, each None for +0; this is "
                              + (f"{len(given)} of them"
                                 if isinstance(given, (tuple, list))
                                 else f"a {type(given).__name__}"), run=r)
            given = tuple(None if s is None else
                          _as_values(fmt, s, "stream",
                                     f"run {r} stream {nm}", run=r)
                          for nm, s in zip("abc", given))
            for nm, s in zip("abc", given):
                if s is not None and len(s) != run.lanes:
                    raise Refusal("stream", f"run {r}: stream {nm} holds "
                                            f"{len(s)} values; the run has "
                                            f"{run.lanes} lanes", run=r)
        handed = given is not None and any(s is not None for s in given)
        if not handed and not _state_bounds(states, r, len(run.chain),
                                            run.lanes, fmt.width // 8):
            out.append(None)
            continue
        abc = _streams_or_zero(fmt, run.lanes, given)
        for i, (nm, s) in enumerate(zip("abc", abc)):
            if not all(0 <= v < (1 << fmt.width) for v in s):
                raise Refusal("stream", f"run {r}: stream {nm} holds a value "
                                        f"that is not the bits of a "
                                        f"{fmt.name} element (an integer in "
                                        f"0..2^{fmt.width} - 1)", run=r)
            if stream_hash(salt, nm, state_bytes(fmt, s)) != run.streams[i]:
                raise Refusal("stream", f"run {r}: stream {nm} is not the "
                                        f"one certified", run=r)
        out.append(abc)
    return out


def _check_continuity(cert):
    for r, run in enumerate(cert.runs):
        for k in range(1, len(run.chain)):
            if run.chain[k].start != run.chain[k - 1].end:
                raise Refusal("continuity",
                              f"run {r} segment {k} starts on a state that "
                              f"is not segment {k - 1}'s end", run=r,
                              segment=k)
        if run.output != run.chain[-1].end:
            raise Refusal("continuity", f"run {r}: the output is not the "
                                        f"last segment's end", run=r,
                          segment=len(run.chain) - 1)


def _boundary_hash(run, b):
    return run.chain[b].start if b < len(run.chain) else run.output


def _check_states(cert, salt, progs, states):
    states = _run_mapping(cert, states, "states", "state-shape")
    known = {}
    for r in sorted(states):
        run = cert.runs[r]
        fmt = progs[r]["prog"].fmt
        want = run.lanes * progs[r]["nslots"]
        per = states[r]
        if not isinstance(per, dict):
            raise Refusal("state-shape",
                          f"run {r}: its states are handed as a "
                          f"{type(per).__name__}; they are a mapping from "
                          f"boundary to state", run=r)
        for b in per:
            if not _is_int(b) or not 0 <= b <= len(run.chain):
                raise Refusal("state-shape",
                              f"run {r} has boundaries 0..{len(run.chain)}; "
                              f"a state was handed for {b!r}", run=r)
        for b in sorted(per):
            vals = _as_values(fmt, per[b], "state-shape",
                              f"run {r} boundary {b}", run=r, segment=b)
            if len(vals) != want:
                raise Refusal("state-shape",
                              f"run {r} boundary {b}: {len(vals)} values; "
                              f"the state is {run.lanes} lanes of "
                              f"{progs[r]['nslots']} {fmt.name} slots",
                              run=r, segment=b)
            if not all(0 <= v < (1 << fmt.width) for v in vals):
                raise Refusal("state-shape",
                              f"run {r} boundary {b}: a value is not the "
                              f"bits of a {fmt.name} element (an integer "
                              f"in 0..2^{fmt.width} - 1)", run=r, segment=b)
            if state_hash(salt, state_bytes(fmt, vals)) \
                    != _boundary_hash(run, b):
                raise Refusal("state-hash",
                              f"run {r} boundary {b}: the state handed is "
                              f"not the one certified", run=r, segment=b)
            known[(r, b)] = vals
    return known


def _check_relations(cert, salt, progs, strm, known):
    main, P0 = cert.runs[0], progs[0]
    for r in range(1, len(cert.runs)):
        A, PA = cert.runs[r], progs[r]
        half = A.kind == "half-step"
        where = f"run {r} ({A.kind})"
        # format
        if half and A.fmt != main.fmt:
            raise Refusal("aux-format", f"{where} is {A.fmt}; a half-step run "
                                        f"is at the main run's {main.fmt}",
                          run=r)
        if not half:
            if main.fmt == LADDER[-1]:
                raise Refusal("aux-format",
                              f"{where}: the main run is {main.fmt}, the top "
                              f"of the ladder - a program image is at most "
                              f"fp256, so no wider run exists and a rounding "
                              f"estimate by one is refused", run=r)
            nxt = LADDER[LADDER.index(main.fmt) + 1]
            if A.fmt != nxt:
                raise Refusal("aux-format", f"{where} is {A.fmt}; one format "
                                            f"wider than {main.fmt} is "
                                            f"{nxt}", run=r)
        # lanes
        if A.lanes != main.lanes:
            raise Refusal("aux-lanes", f"{where} has {A.lanes} lanes and the "
                                       f"main run {main.lanes}", run=r)
        # image
        if A.steps != main.steps:
            raise Refusal("aux-image", f"{where} states {A.steps} steps a "
                                       f"segment and the main run "
                                       f"{main.steps}; the same instructions "
                                       f"take the same steps", run=r)
        if half:
            if A.image != main.image:
                raise Refusal("aux-image", f"{where}: its image digest is not "
                                           f"the main run's - a half-step run "
                                           f"is the same image", run=r)
        else:
            why = _wider_image(P0["prog"], PA["prog"])
            if why:
                raise Refusal("aux-image", f"{where} is not the main image "
                                           f"one format wider: {why}", run=r)
        # the same instructions on the same machine: a run at another
        # scratch depth reduces a non-strict STX/LDX by another modulus
        # (the lead's decision, 2026-09-29). Under CAPS2 the runs cannot
        # differ; under the scratch-depth parameter they can.
        if PA["depth"] != P0["depth"]:
            raise Refusal("aux-image", f"{where} is re-run at a scratch depth "
                                       f"of {PA['depth']} and the main run at "
                                       f"{P0['depth']}: the same instructions "
                                       f"on another machine", run=r)
        # segments
        want = 2 * len(main.chain) if half else len(main.chain)
        if len(A.chain) != want:
            raise Refusal("aux-segments",
                          f"{where} has {len(A.chain)} segments; "
                          + (f"a half-step run has twice the main run's "
                             f"{len(main.chain)}" if half else
                             f"a wider run has the main run's "
                             f"{len(main.chain)}"), run=r)
        # h-slots and the bank
        b0, bA = P0["bankv"], PA["bankv"]
        fmt0 = P0["prog"].fmt
        if half:
            if b0 is None:
                raise Refusal("aux-h-slots", f"{where}: the main image "
                                             f"carries its constants, so no "
                                             f"bank slot can be halved",
                              run=r)
            for s in A.h_slots:
                if s >= len(b0):
                    raise Refusal("aux-h-slots", f"{where}: h-slot {s} is "
                                                 f"past the {len(b0)}-slot "
                                                 f"bank", run=r)
                kind, v = element_fraction(fmt0, b0[s])
                if kind != "finite" or v == 0:
                    raise Refusal("aux-h-slots",
                                  f"{where}: h-slot {s} holds "
                                  f"{'zero' if kind == 'finite' else kind} "
                                  f"in the main bank, which halving leaves "
                                  f"unchanged or undefined", run=r)
            for s in range(len(b0)):
                if s in A.h_slots:
                    # b0[s] is finite and not zero (above), so its half is
                    # a Fraction; a NaN or an infinity in bA[s] has none
                    # (None), and differs from it like any wrong value
                    if element_fraction(fmt0, bA[s])[1] != \
                            element_fraction(fmt0, b0[s])[1] / 2:
                        raise Refusal("aux-bank",
                                      f"{where}: bank slot {s} is not the "
                                      f"main bank's exactly halved", run=r)
                elif bA[s] != b0[s]:
                    raise Refusal("aux-bank",
                                  f"{where}: bank slot {s} differs from the "
                                  f"main bank's, and it is not a named "
                                  f"h-slot", run=r)
        else:
            # The two banks have one shape here: the images' flags
            # (BANK_EXT among them) and n_consts were held equal above,
            # and step 4 held each bank to its image's n_consts.
            if b0 is not None and any(widen(main.fmt, x) != y
                                      for x, y in zip(b0, bA)):
                raise Refusal("aux-bank", f"{where}: the bank is not the main "
                                          f"bank exactly widened", run=r)
        # streams
        if half:
            if A.streams != main.streams:
                raise Refusal("aux-streams", f"{where}: its streams are not "
                                             f"the main run's", run=r)
        elif strm[0] is not None:
            # The main run's streams exactly widened, hashed only when the
            # main run is bounded (step 5 built them). When it is not, no
            # state of it was handed - step 7 refused any too short to be
            # one - and `aux-start` below refuses `state-missing`.
            fmtA = PA["prog"].fmt
            for i, nm in enumerate("abc"):
                w = [widen(main.fmt, x) for x in strm[0][i]]
                if stream_hash(salt, nm, state_bytes(fmtA, w)) \
                        != A.streams[i]:
                    raise Refusal("aux-streams",
                                  f"{where}: stream {nm} is not the main "
                                  f"run's exactly widened", run=r)
        # start
        if half:
            if A.chain[0].start != main.chain[0].start:
                raise Refusal("aux-start", f"{where} does not start on the "
                                           f"main run's initial state",
                              run=r)
        else:
            s0 = known.get((0, 0))
            if s0 is None:
                raise Refusal("state-missing",
                              f"{where}: holding a wider run to the main "
                              f"run's initial state exactly widened needs "
                              f"that state (run 0 boundary 0), and it was "
                              f"not handed", run=0, segment=0)
            w = [widen(main.fmt, x) for x in s0]
            if state_hash(salt, state_bytes(PA["prog"].fmt, w)) \
                    != A.chain[0].start:
                raise Refusal("aux-start",
                              f"{where} does not start on the main run's "
                              f"initial state exactly widened", run=r)


def _wider_image(p0, pa):
    """Why `pa` is not `p0` one format wider, or None: the same
    instruction words and header fields, and any constants the image
    carries exactly widened. (Not the same image digest: the header
    carries the format's precision code, so an image one format wider
    cannot be the same bytes. The formats themselves are one rung apart
    already: step 4 held each image to its run's format, and the
    relation's format check, first in its order, held the runs'.)"""
    if pa.insns != p0.insns:
        return "its instruction words differ"
    for f in ("max_deposits", "flags", "n_consts", "scratch_io_word"):
        if getattr(pa, f) != getattr(p0, f):
            return f"its header's {f} differs"
    if [widen(p0.fmt.name, x) for x in p0.consts] != list(pa.consts):
        return "its constants are not the main image's exactly widened"
    return None


def _plan(cert, choose, seed):
    # A seed handed is the auditor's statement of its sample, so it is
    # held to its size whether or not this audit draws one.
    if seed is not None and (not isinstance(seed, (bytes, bytearray))
                             or len(seed) != SEED_BYTES):
        raise Refusal("choice", f"a sampling seed is exactly {SEED_BYTES} "
                                f"bytes")
    choose = _run_mapping(cert, choose, "the choice", "choice")
    plan = []
    drew = None
    for r, run in enumerate(cert.runs):
        S = len(run.chain)
        c = choose.get(r, "all")
        entry = {"run": r, "kind": run.kind, "format": run.fmt,
                 "lanes": run.lanes, "segments": S}
        if c == "all":
            entry.update(how="all", rerun=list(range(S)))
        elif isinstance(c, tuple) and len(c) == 2 and c[0] == "sample":
            if not _is_int(c[1]) or not 1 <= c[1] <= S:
                raise Refusal("choice", f"run {r}: a sample of {c[1]!r} from "
                                        f"{S} segments; a sample's size is "
                                        f"an integer in 1..{S}", run=r)
            if seed is None:
                drew = drew or os.urandom(SEED_BYTES)
                use = drew
            else:
                use = seed
            entry.update(how="sample", rerun=sample(use, r, S, c[1]),
                         seed=bytes(use).hex())
        elif isinstance(c, (list, tuple)):
            segs = list(c)
            if not segs or any(not _is_int(k) or not 0 <= k < S
                               for k in segs) or len(set(segs)) != len(segs):
                raise Refusal("choice", f"run {r}: segments {segs!r} are not "
                                        f"distinct indices in 0..{S - 1}, "
                                        f"at least one", run=r)
            entry.update(how="named", rerun=sorted(segs))
        else:
            raise Refusal("choice", f"run {r}: {c!r} is not 'all', a list of "
                                    f"segments or ('sample', k)", run=r)
        plan.append(entry)
    return plan


def run_segment(prog, a, b, c, start, *, bank=None,
                scratch_depth=seq.SCRATCH_D):
    """One segment, as the audit re-runs it: `seq.run` over the lanes
    BLOCK_LANES at a time - each block its own lanes' streams and start
    state - with the end state the blocks' in lane order, and the flag
    word and STATUS the OR of the blocks'. -> (end state, flags, status).

    This is the dense `seq.run` over every lane, exactly: every write and
    every flag is masked by the lane's active bit, and the early exit, the
    one thing lanes share, is invisible (docs/SEQUENCER.md, P3) - the
    property that lets lanes be split across tiles, and what libcft's
    software backend and the tile compute, block by block. What it buys:
    a re-run holds one block's scratch at the certified depth, at most
    64 x 32,768 slots, where the dense run holds every lane's (the lead's
    decision, 2026-09-29; docs/CERTIFICATES.md, "What an audit
    spends")."""
    n = len(a)
    per = prog.n_scratch_in
    out, flags, status = [], 0, 0
    for lo in range(0, n, BLOCK_LANES):
        hi = min(n, lo + BLOCK_LANES)
        res = seq.run(prog, a[lo:hi], b[lo:hi], c[lo:hi], bank=bank,
                      scratch_depth=scratch_depth,
                      scratch_in=start[lo * per:hi * per])
        out += res.scratch_out
        flags |= res.flags
        status |= res.status
        # let this block's scratch go before the next block takes its own
        del res
    return out, flags, status


def _rerun(cert, salt, progs, strm, known, plan):
    for r, run in enumerate(cert.runs):
        p = progs[r]
        fmt = p["prog"].fmt
        for k in plan[r]["rerun"]:
            s = known.get((r, k))
            if s is None:
                raise Refusal("state-missing",
                              f"run {r} segment {k}: its start state "
                              f"(boundary {k}) was not handed"
                              + (", and it is the initial state" if k == 0
                                 else f", and segment {k - 1} was not re-run "
                                      f"to give it"), run=r, segment=k)
            # A run with a state known is bounded, so step 5 built its
            # streams: a state held to `lanes` x slots at step 7 holds at
            # least `lanes` elements.
            a, b, c = strm[r]
            try:
                out, fl, st = run_segment(p["prog"], a, b, c, s,
                                          bank=p["bankv"],
                                          scratch_depth=p["depth"])
            except seq.ProgramError as e:
                raise Refusal("program-image", f"run {r} segment {k}: the "
                                               f"executor refuses it: {e}",
                              run=r, segment=k)
            seg = run.chain[k]
            if state_hash(salt, state_bytes(fmt, out)) != seg.end:
                raise Refusal("segment-end",
                              f"run {r} segment {k}: re-run from its "
                              f"certified start state, it does not end on "
                              f"its certified end state", run=r, segment=k)
            if fl != seg.flags:
                raise Refusal("segment-flags",
                              f"run {r} segment {k}: the re-run raises flags "
                              f"{fl} and the certificate says "
                              f"{seg.flags}", run=r, segment=k)
            if st != seg.status:
                raise Refusal("segment-status",
                              f"run {r} segment {k}: the re-run's STATUS is "
                              f"{st} and the certificate says "
                              f"{seg.status}", run=r, segment=k)
            known.setdefault((r, k + 1), out)
