# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Assemble bindings/wasm/conformance.html from its three ingredients.

    page_template.html   the page, with three @CFT_*@ tokens open
    cft_runtime.js       emcc -sSINGLE_FILE output (wasm embedded as
                         base64), spliced in verbatim
    a vectors directory  the 20 regenerated .jsonl sets, sampled here

Run by build.sh inside the pinned container; pure stdlib, so it also
runs anywhere a Python 3.10+ exists (the negative-control build below
does not need the toolchain, only the build/ products).

THE SAMPLING RULE - stated here, in build.sh and on the page, because
a sample nobody can regenerate is a sample nobody can audit:

    From each of the 20 sets (4 formats x 5 rounding attributes,
    11,800 lines each), take every 59th line - 0-based line numbers
    0, 59, 118, ... - which is exactly 200 lines per set since
    11,800 = 59 * 200. Then, for any opcode name present in the set
    but missing from that stride, add the set's FIRST line carrying
    it, so every opcode class is embedded per set by construction
    rather than by luck: arithmetic, sign, min/max, predicates,
    integer, the divide/sqrt seeds (26/27), and the unassigned
    reserved15/30/255 whose defined qNaN+invalid answer is contract
    surface too. Lines keep file order.

ONLY THE OPCODE SETS ARE SAMPLED, and that is unchanged at ABI 0.6.
The generator now writes five families - opcode, transcendental,
augmented, reduction and character - but the embedded sample exists to
give a page that has just loaded something to replay before anyone
drops a file, and the opcode sets are the ones whose schema this rule
can sample line by line and whose 28 opcode classes it can prove
covered. The other four families are droppable in section 3, where
they are replayed whole; embedding a sample of them would grow the
committed page for a weaker version of the check the drop zone already
makes. cft_conformance reads all five either way, so nothing here
decides what the library will replay.

The numbers 11,800 / 59 / 200 assume the generator arguments the repo
publishes (`make vectors`); the asserts below pin that, so changing
the generator without changing this file and the page prose fails the
build instead of quietly shipping stale text. The reserved list has
now shed a member three times - 24 became CFT_SUM, 26 CFT_RECIP_SEED
and 28 CFT_SUMSQ at ABI 0.6 - which is why the opcode names above are
worth keeping current rather than approximately right.

--corrupt builds the NEGATIVE CONTROL page: identical except that one
expected "d" value in the embedded sample has its low hex digit
flipped, and a banner says so. That page MUST report a conformance
failure; it exists to prove the checker can fail, and is never the
page you ship.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

STRIDE = 59
LINES_PER_SET = 11800
EXPECTED_OPS = 28          # 4 arithmetic + 19 simple + 2 seeds + 3 reserved

FORMATS = ("fp32", "fp64", "fp128", "fp256")
ROUNDINGS = ("rne", "rtz", "rdn", "rup", "rmm")


def canonical_names():
    return [f"{f}.jsonl" if r == "rne" else f"{f}-{r}.jsonl"
            for f in FORMATS for r in ROUNDINGS]


def die(msg):
    print(f"make_page.py: {msg}", file=sys.stderr)
    sys.exit(1)


def sample_set(path: Path):
    """Apply the sampling rule to one set; returns (text, n, ops)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if len(lines) != LINES_PER_SET:
        die(f"{path.name}: {len(lines)} lines, expected {LINES_PER_SET} - "
            "the generator arguments changed; update this file and the "
            "page prose together, or regenerate the sets")

    ops = [json.loads(ln)["op"] for ln in lines]
    all_ops = set(ops)
    if len(all_ops) != EXPECTED_OPS:
        die(f"{path.name}: {len(all_ops)} distinct opcodes, expected "
            f"{EXPECTED_OPS}")

    take = set(range(0, len(lines), STRIDE))
    sampled_ops = {ops[i] for i in take}
    for missing in all_ops - sampled_ops:
        take.add(ops.index(missing))          # the set's first line of it

    idx = sorted(take)
    if {ops[i] for i in idx} != all_ops:      # by construction; assert anyway
        die(f"{path.name}: sampling failed to cover every opcode")
    return "\n".join(lines[i] for i in idx) + "\n", len(idx), all_ops


def corrupt_one(sample: dict):
    """Flip the low hex digit of one expected value, deterministically:
    the first sampled fp64.jsonl line whose op is fma. Returns a
    human-readable description of what was done."""
    name = "fp64.jsonl"
    lines = sample[name].splitlines()
    for i, ln in enumerate(lines):
        case = json.loads(ln)
        if case["op"] != "fma":
            continue
        old = case["d"]
        flipped = format(int(old[-1], 16) ^ 0x1, "x")
        new = old[:-1] + flipped
        needle = f'"d": "{old}"'
        if needle not in ln:
            die("negative control: could not locate the d field verbatim")
        lines[i] = ln.replace(needle, f'"d": "{new}"', 1)
        sample[name] = "\n".join(lines) + "\n"
        return (f"{name}, sampled line {i} (op fma): "
                f"expected value {old} corrupted to {new}")
    die("negative control: no fma case in the fp64.jsonl sample")


def splice(page: str, token: str, payload: str) -> str:
    if page.count(token) != 1:
        die(f"template token {token!r} found {page.count(token)} times, "
            "expected exactly once")
    return page.replace(token, payload, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vectors", required=True)
    ap.add_argument("--runtime", required=True)
    ap.add_argument("--wasm", required=True,
                    help="the split-build .wasm, for the honest size line")
    ap.add_argument("--template", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--emcc-version", required=True)
    ap.add_argument("--gen-command", required=True)
    ap.add_argument("--corrupt", action="store_true")
    args = ap.parse_args()

    vdir = Path(args.vectors)
    names = canonical_names()
    missing = [n for n in names if not (vdir / n).exists()]
    if missing:
        die(f"{vdir} is missing {len(missing)} set(s): {' '.join(missing)} - "
            "an incomplete embedding would be a quieter claim than the page "
            "makes, so it is refused")

    sample, per_set, digests = {}, {}, []
    total_sampled = 0
    for n in names:
        text, count, _ = sample_set(vdir / n)
        sample[n] = text
        per_set[n] = count
        total_sampled += count
        digests.append(hashlib.sha256((vdir / n).read_bytes()).hexdigest())

    # One digest over the 20 per-file digests, in canonical name order:
    # enough to pin exactly which vectors were sampled.
    vectors_digest = hashlib.sha256(
        "".join(digests).encode("ascii")).hexdigest()

    negctl_html = ""
    if args.corrupt:
        what = corrupt_one(sample)
        negctl_html = (
            '<div class="negctl-banner">NEGATIVE CONTROL BUILD - not the '
            'shipping page. ' + what + '. The replay below MUST fail; a '
            'green verdict on this page would mean the checker cannot '
            'fail, which is worse than any red one.</div>')

    runtime = Path(args.runtime).read_text(encoding="utf-8")
    for bad in ("</script", "<!--"):
        if bad in runtime:
            die(f"the emcc runtime contains {bad!r}, which an inline "
                "<script> cannot carry verbatim - splice refused; teach "
                "this script to escape it before shipping anything")
    sample_json = json.dumps(sample)
    if "</script" in sample_json:
        die("the sample contains '</script' - splice refused")

    wasm_bytes = Path(args.wasm).stat().st_size
    js_bytes = Path(args.runtime).stat().st_size
    build_info = {
        "image": args.image,
        "emcc_version": args.emcc_version,
        "gen_command": args.gen_command,
        "vectors_digest": vectors_digest,
        "sample_rule": (f"every {STRIDE}th line of each set (0-based), "
                        "plus the set's first line of any opcode the "
                        "stride missed"),
        "sample_cases": f"{total_sampled:,}",
        "total_cases": f"{LINES_PER_SET * len(names):,}",
        "wasm_note": (f"wasm module {wasm_bytes:,} bytes, embedded as "
                      f"base64 in this page; modularized runtime js "
                      f"{js_bytes:,} bytes"),
    }

    page = Path(args.template).read_text(encoding="utf-8")
    page = splice(page, "<!--@CFT_NEGCTL@-->", negctl_html)
    page = splice(page, "/*@CFT_RUNTIME_JS@*/", runtime)
    page = splice(page, "/*@CFT_SAMPLE_JSON@*/ null", sample_json)
    page = splice(page, "/*@CFT_BUILD_JSON@*/ null", json.dumps(build_info))

    out = Path(args.out)
    out.write_text(page, encoding="utf-8", newline="\n")

    kind = "NEGATIVE CONTROL page" if args.corrupt else "page"
    print(f"{out}: {kind}, {out.stat().st_size:,} bytes")
    print(f"  sample: {total_sampled:,} cases over {len(names)} sets "
          f"(per set: {min(per_set.values())}..{max(per_set.values())})")
    print(f"  wasm {wasm_bytes:,} bytes / runtime js {js_bytes:,} bytes")
    print(f"  vectors digest {vectors_digest}")
    if args.corrupt:
        print("  " + what)


if __name__ == "__main__":
    main()
