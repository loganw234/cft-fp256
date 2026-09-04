# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Assemble bindings/wasm/demos.html from its five ingredients.

    demos_template.html   the page, with six @CFT_*@ tokens open
    cft_demos_runtime.js  emcc -sSINGLE_FILE output, spliced verbatim
    demos_core.js         the compute core, shared with node
    demos_worker.js       the driver the Worker (or the fallback) runs
    demos_chains.json     the chains the NATIVE tools produced

Run by build_demos.sh inside the pinned container; pure stdlib plus
make_page.py's own splice(), so it also runs anywhere a Python 3.10+
exists.

THE ONE THING THIS SCRIPT REFUSES TO DO is ship a page whose module is
not bindings/node/cft_node.wasm. The demos page exists to run the
conformance page's own bits: its chains are a claim about THAT module,
whose sha256 the conformance page and three documents quote. So the
module is checked twice here - against the split .wasm the same emcc
run produced, and by walking the bytes back out of the assembled HTML
- on top of the check build_demos.sh already made. Three checks of one
fact is not paranoia when the fact is the whole argument.

--corrupt builds the NEGATIVE CONTROL page: identical except that one
opcode in one panel's step is changed, and a banner says so. Every
chain that panel computes MUST then differ from the recorded native
chain. It exists to prove the comparison can fail, and is never the
page you ship.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_page import die, splice          # noqa: E402  (same directory)

# The sabotage, and the panel it lands in. Collatz's step is the
# clearest place for it: `peak` is the running maximum of the
# trajectory, it is in the record line and therefore in the chain, and
# turning the MAX into a MIN leaves everything else - the flag/witness
# agreement, the step count, the final value - working exactly as
# before. So the page still runs, still says it succeeded, and its
# chain is wrong. That is the failure a chain comparison is for.
CORRUPT_FROM = "      R(OP.max, S.peak, S.n, 0, S.peak);"
CORRUPT_TO = "      R(OP.min, S.peak, S.n, 0, S.peak);"
CORRUPT_WHAT = ("demos_core.js, the Collatz panel's engine pass: the "
                "running peak is computed with CFT_MIN instead of "
                "CFT_MAX")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_wasm(html: str) -> bytes:
    """Walk emcc's SINGLE_FILE literal back into bytes.

    findWasmBinary(){return binaryDecode('...')} - one JS string
    literal, one byte per code unit. Walked rather than evaluated,
    because this is a build product and a build product is data.
    bindings/wasm/verify.mjs and verify_demos.mjs do the same walk; if
    emscripten ever changes the encoding, all three fail loudly rather
    than one of them quietly agreeing with nothing.
    """
    anchor = "findWasmBinary(){return binaryDecode("
    at = html.find(anchor)
    if at < 0:
        die("no findWasmBinary(){return binaryDecode( in the assembled page "
            "- has the emscripten SINGLE_FILE encoding changed? Teach this "
            "script the new one rather than deleting the check")
    i = at + len(anchor)
    quote = html[i]
    i += 1
    if quote not in "'\"":
        die("binaryDecode( is not followed by a string literal")
    esc = {"n": 10, "r": 13, "t": 9, "b": 8, "f": 12, "v": 11, "0": 0}
    out = bytearray()
    while True:
        c = html[i]
        i += 1
        if c == quote:
            break
        if c != "\\":
            cc = ord(c)
            if cc > 0xFF:
                die(f"code unit {cc} > 255 in the wasm literal")
            out.append(cc)
            continue
        e = html[i]
        i += 1
        if e == "x":
            out.append(int(html[i:i + 2], 16))
            i += 2
        elif e == "u":
            cc = int(html[i:i + 4], 16)
            if cc > 0xFF:
                die(f"\\u{html[i:i + 4]} > 255 in the wasm literal")
            out.append(cc)
            i += 4
        elif e in esc:
            out.append(esc[e])
        else:
            out.append(ord(e))
    return bytes(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime", required=True,
                    help="the -sSINGLE_FILE emcc loader")
    ap.add_argument("--wasm", required=True,
                    help="the split-build .wasm from the same emcc run")
    ap.add_argument("--module", required=True,
                    help="bindings/node/cft_node.wasm, the committed module")
    ap.add_argument("--core", required=True)
    ap.add_argument("--worker", required=True)
    ap.add_argument("--chains", required=True)
    ap.add_argument("--template", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--emcc-version", required=True)
    ap.add_argument("--corrupt", action="store_true")
    args = ap.parse_args()

    module = Path(args.module)
    want_hash = sha256_file(module)
    split_hash = sha256_file(Path(args.wasm))
    if want_hash != split_hash:
        die(f"the module this build compiled ({split_hash}) is not the "
            f"committed {module} ({want_hash}). The demos page exists to run "
            "the conformance page's own bits; a page carrying a different "
            "module would make its chains a claim about some other build. "
            "Refused.")

    runtime = Path(args.runtime).read_text(encoding="utf-8")
    core = Path(args.core).read_text(encoding="utf-8")
    worker = Path(args.worker).read_text(encoding="utf-8")
    chains = json.loads(Path(args.chains).read_text(encoding="utf-8"))

    # Every one of the three sits inside a <script> element, so none of
    # them may carry a close tag or a comment opener. They do not
    # today; the build refuses rather than trusting that they never
    # will, because the failure mode is a page that half-parses.
    for name, text in (("the emcc runtime", runtime),
                       ("demos_core.js", core),
                       ("demos_worker.js", worker)):
        for banned in ("</script", "<!--"):
            if banned in text:
                die(f"{name} contains {banned!r}, which an inline <script> "
                    "cannot carry verbatim - splice refused; teach this "
                    "script to escape it before shipping anything")

    negctl_html = ""
    if args.corrupt:
        if core.count(CORRUPT_FROM) != 1:
            die("negative control: the sabotage site "
                f"{CORRUPT_FROM.strip()!r} appears "
                f"{core.count(CORRUPT_FROM)} times in demos_core.js, "
                "expected exactly once - move the sabotage rather than "
                "guessing where it landed")
        core = core.replace(CORRUPT_FROM, CORRUPT_TO, 1)
        negctl_html = (
            '<div class="negctl-banner">NEGATIVE CONTROL BUILD - not the '
            'shipping page. Sabotage: ' + CORRUPT_WHAT + '. The Collatz '
            'panel MUST report both of its chains as DIFFER; a green '
            'verdict on this page would mean the comparison cannot fail, '
            'which is worse than any red one.</div>')

    # The chain file is embedded as-is, and the two identities it
    # records are re-checked here: a chain recorded against a different
    # module or a different core is a chain about a different program.
    core_hash = hashlib.sha256(core.encode("utf-8")).hexdigest()
    if not args.corrupt:
        if chains.get("module_sha256") != want_hash:
            die(f"{args.chains} was recorded against module "
                f"{chains.get('module_sha256')}, and this page embeds "
                f"{want_hash} - re-record with "
                "`node bindings/wasm/verify_demos.mjs --record`")
        if chains.get("core_sha256") != core_hash:
            die(f"{args.chains} was recorded against compute core "
                f"{chains.get('core_sha256')}, and this page embeds "
                f"{core_hash} - re-record with "
                "`node bindings/wasm/verify_demos.mjs --record`")

    n_chains = sum(len(r["chains"]) for r in chains["runs"])
    build_info = {
        "image": args.image,
        "emcc_version": args.emcc_version,
        "module_bytes": f"{module.stat().st_size:,}",
        "module_sha256": want_hash,
        "core_sha256": core_hash,
        "page_note": (f"{len(chains['runs'])} configurations, {n_chains} "
                      "recorded chains, one embedded wasm module"),
    }

    page = Path(args.template).read_text(encoding="utf-8")
    page = splice(page, "<!--@CFT_NEGCTL@-->", negctl_html)
    page = splice(page, "/*@CFT_RUNTIME_JS@*/", runtime)
    page = splice(page, "/*@CFT_CORE_JS@*/", core)
    page = splice(page, "/*@CFT_WORKER_JS@*/", worker)
    page = splice(page, "/*@CFT_BUILD_JSON@*/ null", json.dumps(build_info))
    page = splice(page, "/*@CFT_CHAINS_JSON@*/ null", json.dumps(chains))

    # The third check of the one fact: the bytes that actually landed
    # in the page.
    embedded = extract_wasm(page)
    got = hashlib.sha256(embedded).hexdigest()
    if got != want_hash:
        die(f"the assembled page's embedded module hashes {got}, not "
            f"{want_hash} - the splice or the SINGLE_FILE encoding is wrong")

    # And that the core landed intact: the page's block must be the
    # source this script read, so verify_demos.mjs's comparison against
    # demos_core.js is a comparison of the same bytes.
    m = re.search(r'<script type="text/plain" id="cft-core-src">(.*?)'
                  r'</script>', page, re.S)
    if not m:
        die("the assembled page has no cft-core-src block")
    if m.group(1) != core:
        die("the page's compute core is not the source spliced into it")

    out = Path(args.out)
    out.write_text(page, encoding="utf-8", newline="\n")

    kind = "NEGATIVE CONTROL page" if args.corrupt else "page"
    print(f"{out}: {kind}, {out.stat().st_size:,} bytes")
    print(f"  module   {len(embedded):,} bytes, sha256 {want_hash}")
    print(f"  core     {len(core):,} chars, sha256 {core_hash}")
    print(f"  chains   {len(chains['runs'])} runs, {n_chains} chains, "
          f"recorded {chains.get('recorded')}")
    if args.corrupt:
        print(f"  sabotage {CORRUPT_WHAT}")


if __name__ == "__main__":
    main()
