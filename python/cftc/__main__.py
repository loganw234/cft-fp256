# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""cftc's command line.

    python -m cftc SOURCE.cftl --steps S [--target NAME] [--out DIR]
                   [--stem NAME] [--param NAME=VALUE ...] [--format FMT]
    python -m cftc --targets
    python -m cftc --compiler-id

(run from python/, or with python/ on PYTHONPATH; `python python/cftc
...` works from the repository's root as well.)

`--format FMT` compiles the source at FMT, one of fp32, fp64, fp128 and
fp256, in place of the format its `format` statement declares (the
package's docstring; a format that is none of the four is refused
`unknown-format`). `--compiler-id` prints the build id of the
repository cftc runs from, in libcft's grammar, or `unknown` with the
reason on stderr, and exits 0 (cftc.compiler_id).

Exit 0: every file written. A refusal prints
`cftc: refused <name>: <source>[:<line>]: <sentence>` on stderr and exits
3, writing nothing; a command line it does not take exits 64, `usage`;
an internal error - a defect in the compiler, never a property of the
source - prints `cftc: internal error (a defect in the compiler): ...`
and exits 70, writing nothing.
"""

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    # `python python/cftc ...`: the package's parent is not on the path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "cftc"
    import cftc  # noqa: F401,E402

from cftc import InternalError, compile_file, compiler_id_detail, lang  # noqa: E402,E501
from cftc import targets as T  # noqa: E402

EXIT_REFUSED = 3
EXIT_USAGE = 64
EXIT_INTERNAL = 70


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"cftc: usage: {message}", file=sys.stderr)
        sys.exit(EXIT_USAGE)


def main(argv=None):
    ap = _Parser(prog="cftc", description="compile a .cftl system to a "
                 "sequencer segment image")
    ap.add_argument("source", nargs="?", help="the system, a .cftl file")
    ap.add_argument("--steps", type=int, help="S: the steps a segment runs "
                    "(the image's one REPEAT count)")
    ap.add_argument("--target", default="sw", help="the device it is for "
                    "(default sw; --targets lists them)")
    ap.add_argument("--out", default=".", help="where the files go")
    ap.add_argument("--stem", help="the files' name (default: the source's)")
    ap.add_argument("--param", action="append", default=[],
                    metavar="NAME=VALUE", help="a param's run value, read "
                    "exactly as the language reads a default")
    ap.add_argument("--format", dest="fmt", metavar="FMT",
                    help="compile at FMT (fp32, fp64, fp128 or fp256) in "
                    "place of the format the source declares")
    ap.add_argument("--targets", action="store_true",
                    help="list the built-in targets and exit")
    ap.add_argument("--compiler-id", action="store_true",
                    help="print the build id of the repository cftc runs "
                    "from, or unknown, and exit")
    a = ap.parse_args(argv)
    if a.compiler_id:
        ident, why = compiler_id_detail()
        print(ident)
        if why:
            print(f"cftc: compiler id unknown: {why}", file=sys.stderr)
        return 0
    if a.targets:
        for name, t in T.BUILTIN.items():
            print(f"{name:14s} {','.join(t.formats):23s} "
                  f"insns {t.max_insns:>10,}  consts {t.max_consts}  "
                  f"scratch {t.scratch_depth:>5,}  features "
                  f"0x{t.seq_features:x}  ({t.where})")
        print("sw:N           the software backend at N scratch slots a "
              "lane, N a power of two to 32,768")
        return 0
    if a.source is None or a.steps is None:
        ap.error("a source and --steps are required")
    if T.get(a.target) is None:
        ap.error(f"{a.target!r} is not a target: {', '.join(T.names())}, "
                 f"or sw:N")
    params = {}
    for p in a.param:
        name, eq, value = p.partition("=")
        if not eq or not name or not value:
            ap.error(f"--param takes NAME=VALUE, not {p!r}")
        if name in params:
            ap.error(f"--param {name} is given twice")
        params[name] = value
    if not Path(a.source).is_file():
        ap.error(f"{a.source} is not a file")
    try:
        c = compile_file(a.source, a.steps, a.target, stem=a.stem,
                         params=params or None, fmt=a.fmt)
    except lang.Refusal as e:
        where = e.source or a.source
        if e.line is not None:
            where = f"{where}:{e.line}"
        print(f"cftc: refused {e.name}: {where}: {e.sentence}",
              file=sys.stderr)
        return EXIT_REFUSED
    except InternalError as e:
        print(f"cftc: internal error (a defect in the compiler): {e}",
              file=sys.stderr)
        return EXIT_INTERNAL
    for path in c.write(a.out):
        print(path.as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
