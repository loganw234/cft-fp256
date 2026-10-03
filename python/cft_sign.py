#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""cft-sign: the key tool for certificates' detached signatures
(docs/CERTIFICATES.md, version 2, "The detached signature").

    python python/cft_sign.py keygen --out KEY
    python python/cft_sign.py public --key KEY
    python python/cft_sign.py sign   --key KEY --cert CERT [--out SIG]
    python python/cft_sign.py verify --cert CERT [--sig SIG] [--keyring RING]

keygen   draws a 32-byte Ed25519 secret from the operating system's secure
         randomness (`secrets`), writes it to KEY - a file it creates new,
         never over an existing one, owner-only where the system honours
         the mode (Windows does not, by chmod) - and prints the public key,
         64 hex digits: the certificate's `issuer-key` and a keyring's key.
         The secret is never printed.
public   prints KEY's public key.
sign     writes CERT's signature, `<CERT>.sig` unless --out names another
         new file: five lines, the key, the certificate's body hash, and
         Ed25519 (RFC 8032) over `cft-signature 1`, a NUL and the 32 bytes
         of that hash. It signs a certificate of either version that the
         strict reader reads, and refuses anything else by the reader's
         name - bytes with a good hash line that are no certificate
         among them.
verify   checks SIG (`<CERT>.sig` by default) against CERT: its form, that
         it names this certificate and verifies, and for version 2 that its
         key is the certificate's `issuer-key` where it names one, and a
         keyring's holder its `issuer` - step 2a of version 2's audit. It
         prints the key, and its holder where a keyring names it.

A key file is text: `cft-signing-key 1`, `scheme ed25519`, `seed <64
hex>`, `key <64 hex>` (the seed's public key, held to it on reading). On
a POSIX system a key file its group or others may read or write is
refused (`usage`), as ssh refuses one; on Windows, whose permissions are
ACLs that a mode does not show, it is not checked.

Exit 0 on success. A refusal prints `cft-sign: refused <name>: <why>` and
exits with the name's code (the certificate's table: 1, 2 or 4), `usage`
(64) for a command line or a key file it does not take, `output` (73) for
an output that is there already.
"""

import argparse
import os
import re
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cft_golden import cert, cert2, ed25519  # noqa: E402

KEY_MAGIC = "cft-signing-key 1"
EXIT_USAGE, EXIT_OUTPUT = 64, 73
# a key file's mode is checked where the mode is the permission
_POSIX = os.name != "nt"


class Stop(Exception):
    def __init__(self, name, why, code):
        super().__init__(why)
        self.name, self.why, self.code = name, why, code


def _usage(why):
    return Stop("usage", why, EXIT_USAGE)


def key_text(seed):
    return (f"{KEY_MAGIC}\nscheme ed25519\nseed {seed.hex()}\n"
            f"key {ed25519.public_key(seed).hex()}\n")


def read_key(path):
    """A key file -> its 32-byte seed, read strictly: owner-only on a
    POSIX system."""
    try:
        data = Path(path).read_bytes()
        mode = os.stat(path).st_mode
    except OSError as e:
        raise _usage(f"{path}: cannot be read ({e.strerror})") from None
    if _POSIX and mode & 0o077:
        raise _usage(f"{path}: its group or others may read or write it "
                     f"(mode {mode & 0o777:03o}); a key file is its "
                     f"owner's alone - chmod 600")
    pat = (re.escape(KEY_MAGIC), r"scheme ed25519", r"seed [0-9a-f]{64}",
           r"key [0-9a-f]{64}")
    try:
        lines = data.decode("ascii").split("\n")
    except UnicodeDecodeError:
        lines = []
    if len(lines) != 5 or lines[4] != "" or \
            not all(re.fullmatch(p, ln) for p, ln in zip(pat, lines)):
        raise _usage(f"{path} is not a key file: four lines, "
                     f"'{KEY_MAGIC}', 'scheme ed25519', 'seed <64 hex>' and "
                     f"'key <64 hex>', each ending in LF")
    seed = bytes.fromhex(lines[2].split(" ")[1])
    if ed25519.public_key(seed).hex() != lines[3].split(" ")[1]:
        raise _usage(f"{path}: its key line is not its seed's public key")
    return seed


def create_new(path, data):
    """Write `data` to a file that must not exist, owner-only where the
    system honours the mode."""
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL
                     | getattr(os, "O_BINARY", 0), 0o600)
    except FileExistsError:
        raise Stop("output", f"{path} is there already; it is never "
                             f"overwritten", EXIT_OUTPUT) from None
    except OSError as e:
        raise Stop("output", f"{path} cannot be created ({e.strerror})",
                   EXIT_OUTPUT) from None
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def _read(path, what):
    try:
        return Path(path).read_bytes()
    except OSError as e:
        raise _usage(f"{what} {path} cannot be read ({e.strerror})") \
            from None


def cmd_keygen(a):
    seed = secrets.token_bytes(ed25519.SECRET_BYTES)
    create_new(a.out, key_text(seed).encode("ascii"))
    print(ed25519.public_key(seed).hex())


def cmd_public(a):
    print(ed25519.public_key(read_key(a.key)).hex())


def cmd_sign(a):
    seed = read_key(a.key)
    data = _read(a.cert, "the certificate")
    cert.parse(data)            # a certificate, by the strict reader's word
    sig = cert2.signature_file(seed, data)
    out = a.out or (str(a.cert) + ".sig")
    create_new(out, sig)
    print(out)


def cmd_verify(a):
    data = _read(a.cert, "the certificate")
    sig = _read(a.sig or (str(a.cert) + ".sig"), "the signature")
    ring = _read(a.keyring, "the keyring") if a.keyring else None
    c = cert.parse(data)
    if isinstance(c, cert2.Certificate):
        line = cert2._check_signature(c, data, sig, ring)
    else:
        key = cert2.check_signature_file(data, sig)
        holder = cert2.read_keyring(ring).get(key) if ring else None
        line = (f"signature: by key {key}, verified"
                + (f", held by {cert2.text_token(holder)} by the keyring "
                   f"handed" if holder else
                   ", which no keyring handed names" if ring is None else
                   ", which the keyring handed does not name"))
    print(line)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cft-sign", description=__doc__
                                 .split("\n\n")[0])
    sub = ap.add_subparsers(dest="what")
    k = sub.add_parser("keygen")
    k.add_argument("--out", required=True)
    p = sub.add_parser("public")
    p.add_argument("--key", required=True)
    s = sub.add_parser("sign")
    s.add_argument("--key", required=True)
    s.add_argument("--cert", required=True)
    s.add_argument("--out")
    v = sub.add_parser("verify")
    v.add_argument("--cert", required=True)
    v.add_argument("--sig")
    v.add_argument("--keyring")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return EXIT_USAGE if e.code else 0
    if a.what is None:
        ap.print_usage(sys.stderr)
        return EXIT_USAGE
    try:
        {"keygen": cmd_keygen, "public": cmd_public, "sign": cmd_sign,
         "verify": cmd_verify}[a.what](a)
    except Stop as e:
        print(f"cft-sign: refused {e.name}: {e.why}", file=sys.stderr)
        return e.code
    except cert.Refusal as e:
        print(f"cft-sign: refused {e.name}: {e.message}", file=sys.stderr)
        return e.exit_code
    return 0


if __name__ == "__main__":
    sys.exit(main())
