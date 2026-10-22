# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The image registry's checks (parcel S2): config.json names an image by name, path and SHA-256 (S1 held the shape); here the
files are held to it when a job runs, for a card of kind `xrt` (a card of another kind brings its own entry in IMAGE_CHECKS).

An image has four witnesses and they must agree. The FILE's SHA-256 is computed; the REGISTRY's is config.json's; the directory's
`SHA256SUMS` has a line for the file (the driver's build step reads the same file the same way); and the MANIFEST beside it,
`<name>.manifest.txt`, which hw/rebuild-2022.sh writes, says `sha256:` of the artifact it describes. Any two that differ are
`image-digest`, naming which. The manifest also says what the image IS: `clock_cus:` lists its compute units, one a tile, and
the registry's `tiles` must equal that count (`image-tiles`); `platform:` is the platform it was built for, and the registry's
and the card's must both equal it (`image-platform`). The platform is the name the manifest carries (xilinx_u50_gen3x16_xdma_5_202210_1),
not the shell name `xbutil examine` reports (xilinx_u50_gen3x16_xdma_base_5).
"""
from __future__ import annotations

import hashlib
import os
import re

from sched_names import Refusal

SUMS_LINE = re.compile(r"([0-9a-fA-F]{64})\s+\*?(.+?)\s*$")           # the driver's own (hw/card_stress.py build_and_check)
MANIFEST_LINE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*):[ \t]+(.*?)[ \t]*$")        # a top-level `key:   value`; hdlparam lines are indented


def expand(path: str) -> str:
    return os.path.expandvars(os.path.expanduser(path))


def sha256_of(path: str) -> tuple:
    h, n = hashlib.sha256(), 0
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
            n += len(blk)
    return h.hexdigest(), n


def read_manifest(path: str) -> dict:
    """The top-level `key: value` lines of an image manifest, the first of each key (a comment after `#` is not cut: no value read
    here carries one)."""
    out: dict = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            m = MANIFEST_LINE.match(ln.rstrip("\n"))
            if m and m.group(1) not in out:
                out[m.group(1)] = m.group(2)
    return out


def manifest_path(image_path: str) -> str:
    return os.path.splitext(image_path)[0] + ".manifest.txt"


def tiles_of(manifest: dict):
    cus = [c for c in manifest.get("clock_cus", "").split(".") if c]
    return len(cus) or None


def check_xclbin(entry: dict, card: dict) -> dict:
    """The facts of an image that every witness agrees on, or the first refusal. entry is the registry's, card the card's."""
    name, path = entry["name"], expand(entry["path"])
    try:
        digest, size = sha256_of(path)
    except OSError as e:
        raise Refusal("image-digest", f"image {name}: {os.path.basename(path)} cannot be read, so its SHA-256 cannot be held to the registry's: {e.strerror or e}")
    if digest != entry["sha256"]:
        raise Refusal("image-digest", f"image {name}: the file hashes to {digest[:16]}..., the registry says {entry['sha256'][:16]}...")
    sums = os.path.join(os.path.dirname(path), "SHA256SUMS")
    if not os.path.isfile(sums):
        raise Refusal("image-digest", f"image {name}: no SHA256SUMS beside {os.path.basename(path)}")
    listed = None
    with open(sums, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            m = SUMS_LINE.match(ln)
            if m and os.path.basename(m.group(2)) == os.path.basename(path):
                listed = m.group(1).lower()
    if listed is None:
        raise Refusal("image-digest", f"image {name}: SHA256SUMS has no line for {os.path.basename(path)}")
    if listed != digest:
        raise Refusal("image-digest", f"image {name}: SHA256SUMS says {listed[:16]}..., the file hashes to {digest[:16]}...")
    mpath = manifest_path(path)
    if not os.path.isfile(mpath):
        raise Refusal("image-tiles", f"image {name}: no {os.path.basename(mpath)} beside it, so its tile count cannot be read")
    man = read_manifest(mpath)
    if man.get("sha256") != digest:
        raise Refusal("image-digest", f"image {name}: its manifest says sha256 {str(man.get('sha256'))[:16]}..., the file hashes to {digest[:16]}...")
    found, want = tiles_of(man), entry.get("tiles")
    if found is None:
        raise Refusal("image-tiles", f"image {name}: its manifest has no clock_cus line to count tiles from")
    if want is None:
        raise Refusal("image-tiles", f"image {name}: the registry gives no tile count (the manifest says {found})")
    if found != want:
        raise Refusal("image-tiles", f"image {name}: the manifest lists {found} compute unit(s); the registry says {want} tile(s)")
    plat, rplat, cplat = man.get("platform"), entry.get("platform"), card.get("platform")
    if not plat or not rplat or not cplat:
        raise Refusal("image-platform", f"image {name}: the platform is not given by the manifest ({plat!r}), the registry ({rplat!r}) and the card {card['id']} ({cplat!r}) alike")
    if not plat == rplat == cplat:
        raise Refusal("image-platform", f"image {name}: the manifest says platform {plat}, the registry {rplat}, the card {card['id']} {cplat}")
    return {"name": name, "path": path, "sha256": digest, "bytes": size, "tiles": found, "platform": plat,
            "witnesses": ["file", "registry", "SHA256SUMS", "manifest"], "manifest_commit": man.get("commit")}


IMAGE_CHECKS = {"xrt": check_xclbin}


def check_image(entry: dict, card: dict) -> dict:
    return IMAGE_CHECKS[card["kind"]](entry, card)
