# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""cftc: the compiler from the language's systems to segment images.

The language (docs/LANGUAGE.md; cft_golden.lang) is defined golden-first,
and its reference interpreter, lang.run, is the definition of correct.
This package compiles a system's step graph to a sequencer image that a
tile can run - and is held to that interpreter on seq.py, bit for bit,
FLAGS included, the way program.c is held to seq.py.

    import cftc
    c = cftc.compile_file("programs/systems/lorenz63-rk4-fp64.cftl",
                          steps=100)
    c.files()       # {name: bytes}: .cfta, .cftp, .bank, .half.bank,
                    # .manifest.json, .graph.json, and the intention-out
    c.write("out")

What it writes, for a stem (the source's name without .cftl):

  <stem>.cfta            the program as text; asm.py assembles it
  <stem>.cftp            the image: asm.assemble of the .cfta
  <stem>.bank            every param's default and every const an
                         instruction addresses, each rounded once, and the
                         sign-flipped slots of the one fold (lower.py)
  <stem>.half.bank       every h-scaled slot exactly halved, every other
                         the same - for a step-halving estimate; only
                         when some slot scales with h
  <stem>.manifest.json   names to slots, the h-slots, each constant's
                         exact value, encoding, flags and relative error,
                         the time shift, the capacities used, the counts
  <stem>.graph.json      the step graph's canonical bytes
  <stem>.canonical.cftl  the intention-out: the canonical form
  <stem>.math.txt        the intention-out: the mathematical form

Every refusal is the language's Refusal (cft_golden.lang), by name. An
InternalError is a defect in the compiler, never a property of a source.

VERSION is cftc's OUTPUT version (C4, 2026-10-02): bumped with any change
to the bytes cftc writes for some source, and recorded, version by
version, with the SHA-256 of every committed compiled file
(programs/systems/cftc-outputs.txt; outputs.py; the lang stage's leg F).
1 is every cftc from L2 (2026-10-01) until the record began, never
bumped; 2 is the manifest's cost note restated as measured (C4); 3 is
the routines: a source that divides or takes a root at run time, which
2 refused, compiles (C4); 4 is the call loop: a step whose routines,
inlined, would pass 32,768 instructions, which 3 inlined whole, runs
batches of them in loops (C4).

A format override: compile_text and compile_file take `fmt`, a format's
name, which replaces the value of the source's `format` statement
(lang.compile_text's `fmt`; `--format` on the command line). The system
is compiled at that format; the manifest's "source" says so, and an
override equal to the declared format changes no byte. Certificate
version 2's wider-source run compiles a source one format up with it
(docs/studies/CERT-V2.md, 8.4).

compiler_id() - `--compiler-id` on the command line - is the build id of
the repository cftc runs from, in libcft's grammar (cft_build_id(),
docs/HOSTAPI.md): host/tools/gen_build_id.sh's own answer, run on that
repository, or `unknown`. It is provenance, which varies with the
checkout, so no file cftc writes carries it.

A run-time division or square root - the language's div and sqrt (L4) -
is a ROUTINE (C4): a tile has no such instruction, so each node is
inlined where it stands as divfull's or sqrtfull's own instructions,
relocated and specialised at the program's attribute
(cft_golden/routines.py), run in a quiet region, then a RAISE of a word
holding exactly the operation's flags (revision 8's flag control,
docs/SEQUENCER.md R24). inline.py expands them for the allocator, which
gives their registers and spills around them; their raw words are bank
slots of their own (lower.py); the internal check holds each to its
fragment, taken from the golden model (check.py). Such an image needs
FLAG_CONTROL, CAPS2[14], so revision 7's targets refuse it
`target-feature` and the software targets compile and run it; a bank the
routines' words would take past 512 is `bank-capacity`. Until C4 such a
system was refused `runtime-routine`, a name that went with it.

A step whose routines, inlined, would pass 32,768 instructions - the
largest instruction memory a tile has, a constant of the compiler's that
no target is read for (callloop.CALL_LOOP_ABOVE; Logan's rule,
2026-10-02) - runs batches of them in CALL LOOPS instead: one copy of a
routine in a REPEAT over records in the scratch, the largest batch first,
until the step fits or none is left (callloop.py). Measured on planar N
bodies under rk4 at fp64 (C4's ledger, 2026-10-02): at N = 8 the step,
40,477 instructions inlined, loops the first two stages' 56 divisions
and is 31,342 written and 41,957 run (+3.7%), 3.5% more of the model's
cycles a step at sixteen beats, in 243 scratch slots for 220. Where
inlining fits too (N = 6 and 7, the loop forced), one loop adds 3.5% to
the cycles (3.6% to the instructions run), two 6.4% to 6.6% (6.7% to
6.9%) and all four 7.8% to 8.2% (8.4% to 8.7%), while the image shrinks
by 22%, 45% and 89% to 90%.

A system with tangent vectors (docs/LANGUAGE.md, "The variational
equations") compiles the same way: its step graph is version 2, read by
ir.py into an extended state - the state, then each vector's components,
which is the lane block [state | v | w | lane params] - so the image
carries the tangent's operations beside the step's, every value homed or
pinned like a state component. The manifest names the vectors and their
slots; Compilation.scratch_block and run take `tangents`. The schedulers
gain one candidate for such a graph only, the interleaved walk
(schedule.py), which keeps the stage values a tangent reads in registers.

Known limit: the choice between candidates reads no capacity - fewest
instructions a step first, then one-beat cycles - so for Lorenz-96 at
N = 40 with two, three or four tangent vectors the older orders' fewer
instructions win at more scratch (450 slots at T = 2, which no 256-slot
target holds; 5,288 instructions and 490 slots at T = 3, where the
interleaved walk takes 6,286 and 300). Choosing by the
target's capacity would make the image depend on the target, which this
design rules out: one image, the same bytes, serves every target that
accepts it.

Known limit: compile time grows faster than the step does, roughly with
its square for a wide step - the list schedulers scan their ready set at
every pick, and six candidate orders are scheduled and allocated - and
it depends on the step's shape as well as its size. Measured on the
desktop, niced and in use (2026-10-01): rings of the Lorenz-96 kind
took 0.3 s at 760 nodes, 3.6 s at 3,800, 13.8 s at 7,980 and 58.2 s at
16,796 (verifier-VL2: 15.1 s and 60.5 s for the last two). Another shape
of about the same size, verifier-VL2's 8-component map of 1,050-term
sums, which spills 3,063 values, took about 100 s before the homed
stores were indexed by position and 97.4 s after (verifier-VL2's
figures): the index did not change it.
"""

import hashlib
import re
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

from cft_golden import asm, seq
from cft_golden import lang
from cft_golden.lang import constants as K

from . import callloop
from . import manifest as M
from . import targets as T
from .check import verify
from .emit import assemble, cfta, scratch_declared
from .ir import Graph
from .lower import halve, lower
from .refusals import NAMES, InternalError, refuse
from .regalloc import best_program
from .schedule import cycles
from .targets import BUILTIN, Target

VERSION = 4               # the output version: the module docstring, outputs.py
MAX_STEPS = (1 << 32) - 1
MAX_WORST = 1 << 40

__all__ = ["BUILTIN", "Compilation", "InternalError", "MAX_STEPS", "NAMES",
           "Target", "VERSION", "compile_file", "compile_graph",
           "compile_text", "compiler_id", "get_target", "lang"]

ROOT = Path(__file__).resolve().parents[2]
_ID = re.compile(r"commit=([0-9a-f]{40}|[0-9a-f]{64}) "
                 r"tracked=(clean|modified) untracked=(none|present)")


def compiler_id_detail():
    """(id, why): the repository cftc runs from, in cft_build_id()'s
    grammar, from host/tools/gen_build_id.sh --print - the one generator,
    run, not restated - or ("unknown", the reason). The repository is
    python/cftc's grandparent; the script says `unknown` itself where
    that is not the top of a work tree, where git is missing or warns."""
    script = ROOT / "host" / "tools" / "gen_build_id.sh"
    if not script.is_file():
        return "unknown", f"no {script.as_posix()} beside python/cftc"
    sh = shutil.which("sh")
    if sh is None:
        return ("unknown", "no POSIX shell (sh) on PATH to run "
                "host/tools/gen_build_id.sh")
    try:
        r = subprocess.run([sh, script.as_posix(), "--print", ROOT.as_posix()],
                           capture_output=True, text=True, timeout=120,
                           cwd=str(ROOT / "host"))
    except (OSError, subprocess.SubprocessError) as e:
        return "unknown", f"gen_build_id.sh did not run: {e}"
    lines = r.stdout.splitlines()
    line = lines[0].strip() if len(lines) == 1 else None
    if r.returncode != 0 or line is None:
        return ("unknown", f"gen_build_id.sh exited {r.returncode}, "
                f"answering {len(lines)} lines: "
                f"{(r.stderr or r.stdout).strip()[:200]}")
    if line == "unknown":
        return ("unknown", "gen_build_id.sh says unknown: `make -C host "
                "print-build-id`, or the header it writes, says why")
    if not _ID.fullmatch(line):
        return ("unknown", f"gen_build_id.sh answered out of grammar: "
                f"{line[:120]!r}")
    return line, None


def compiler_id():
    """The build id of the repository cftc runs from, or `unknown`."""
    return compiler_id_detail()[0]


def get_target(name):
    t = T.get(name)
    if t is None:
        raise ValueError(f"{name!r} is not a target here: "
                         f"{', '.join(T.names())}, or sw:N")
    return t


class Compilation:
    """One system compiled: every output, and what the gate asks of it."""

    version = VERSION

    def file_names(self):
        st = self.stem
        names = [("cfta", f"{st}.cfta"), ("image", f"{st}.cftp"),
                 ("bank", f"{st}.bank")]
        if self.half_bank is not None:
            names.append(("half_bank", f"{st}.half.bank"))
        names += [("manifest", f"{st}.manifest.json"),
                  ("graph", f"{st}.graph.json"),
                  ("canonical", f"{st}.canonical.cftl"),
                  ("math", f"{st}.math.txt")]
        return names

    _TEXT = {"cfta": ("cfta", "ascii"), "canonical": ("canonical", "utf-8"),
             "math": ("mathematical", "utf-8")}
    _DATA = {"image": "image", "bank": "bank", "half_bank": "half_bank",
             "manifest": "manifest_bytes", "graph": "graph_bytes"}

    def _bytes(self, what):
        if what in self._TEXT:
            attr, encoding = self._TEXT[what]
            return getattr(self, attr).encode(encoding)
        return getattr(self, self._DATA[what])

    def file_digests(self):
        return {what: {"name": name,
                       "sha256": hashlib.sha256(self._bytes(what))
                       .hexdigest()}
                for what, name in self.file_names() if what != "manifest"}

    def files(self):
        return {name: self._bytes(what) for what, name in self.file_names()}

    def write(self, out_dir):
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        written = []
        for name, data in self.files().items():
            (out / name).write_bytes(data)
            written.append(out / name)
        return written

    def scratch_block(self, states, lane_params=None, tangents=None):
        """The lane-major block a run takes: each lane's state, then its
        tangent vectors' values in declaration order (a system with
        tangent vectors: `tangents` as lang.run takes them, one list a
        lane of one list a vector), then its lane params (their defaults
        where none are given)."""
        g = self.ir
        if g.T and tangents is None:
            raise ValueError(f"a system with tangent vectors "
                             f"({', '.join(g.tangent)}) needs tangents")
        if not g.T and tangents is not None:
            raise ValueError("this system has no tangent vectors")
        out = []
        for k, st in enumerate(states):
            if lane_params is None:
                lp = [b for _n, _d, b in g.lane]
                if any(b is None for b in lp):
                    raise ValueError("a lane param without a default needs "
                                     "lane_params")
            else:
                lp = lane_params[k]
            tv = []
            if g.T:
                if len(tangents[k]) != g.T or \
                        any(len(t) != g.n_primal for t in tangents[k]):
                    raise ValueError(f"lane {k}'s tangents are not {g.T} "
                                     f"vectors of {g.n_primal} values")
                for t in tangents[k]:
                    tv += list(t)
            out += list(st) + tv + list(lp)
        return out

    def run(self, states, lane_params=None, bank=None, scratch_depth=None,
            streams=None, tangents=None):
        """The image on seq.py: streams +0 unless given, every lane
        active, its own bank unless one is given, at its declared depth
        unless another is given. -> seq.Result."""
        prog = seq.Program.from_bytes(
            self.image, scratch_depth=scratch_depth or self.depth)
        nlanes = len(states)
        a = b = c = [0] * nlanes
        if streams is not None:
            a, b, c = streams
        vals = self.lowered.bank_values() if bank is None else list(bank)
        return seq.run(prog, a, b, c, bank=vals,
                       scratch_in=self.scratch_block(states, lane_params,
                                                     tangents),
                       scratch_depth=scratch_depth or self.depth)


def _param_bits(graph, params, source):
    """{index: (bits, flags, exact)} for run values given by name. Each is
    read by the language itself, as the default of a param of a one-line
    system, so it is exactly what the same text written as a default
    would be - a decimal read exactly, a/b a constant division, never
    binary64 - and refused by the same names. A Python int or Fraction
    is written out exactly first, at any size; a float is refused, being
    binary64 already, and so is text of more than one line."""
    if not params:
        return None
    names = [p[0] for p in graph.param]
    out = {}
    for name, value in params.items():
        if name not in names:
            raise lang.Refusal("unknown-param", f"{name} is not a param of "
                               f"{graph.system}", source=source)
        if isinstance(value, float):
            raise lang.Refusal("param-value", f"{name}'s run value is a "
                               f"Python float, which is binary64 already: "
                               f"give it as text", source=source)
        if isinstance(value, (int, Fraction)) and \
                not isinstance(value, bool):
            value = K.frac_text(value)      # exact, at any size: str() is not
        if not isinstance(value, str):
            raise lang.Refusal("param-value", f"{name}'s run value is a "
                               f"{type(value).__name__}: give it as text",
                               source=source)
        if "\n" in value or "\r" in value:
            raise lang.Refusal("param-value", f"{name}'s run value is more "
                               f"than one line: give a constant",
                               source=source)
        # The one-line system names the param itself, so that a refusal's
        # sentence names it too (it said "v's default" once); its state is
        # a name the value does not use, so that a value naming one is
        # refused as naming something undeclared, not as naming the state
        # of a system the writer never wrote.
        taken = set(re.findall(r"[A-Za-z_]\w*", value)) | {name}
        state = next(s for s in ["x", "y", "z"] +
                     [f"x{k}" for k in range(len(taken) + 1)]
                     if s not in taken)
        system = "runvalue" if name != "runvalue" else "runvalues"
        text = (f"system {system}\nformat {graph.fmt.name}\n"
                f"round {graph.round_name}\nstate {state}\n"
                f"param {name} = {value}\nnext {state} = {state} * {name}\n"
                f"step map\n")
        try:
            g1 = lang.compile_text(text, f"--param {name}").graph
        except lang.Refusal as e:
            shown = value if len(value) <= 48 else \
                f"{value[:24]}...{value[-12:]} ({len(value):,} characters)"
            raise lang.Refusal(e.name, f"--param {name}={shown}: "
                               f"{e.sentence}", source=source) from None
        _n, exact, bits, flags = g1.param[0]
        out[names.index(name)] = (bits, flags, exact)
    return out


def _call_loops(g, pb, src, low0, prog0):
    """-> (lowered, program, looped batches): the step's batches looped,
    the largest first, until it fits CALL_LOOP_ABOVE or none is left
    (callloop.py), lowered again with the loop's step word and, once the
    allocation is chosen, its record bases (callloop.finish). A batch is
    known by its operation and depth, which the fold - the one thing the
    words' room can change - leaves alone. A step with no batch of two
    calls or more has nothing a loop shortens, and stays inlined."""
    sizes = {b.key(): b for b in callloop.batches(low0)}
    keys = [b.key() for b in callloop.by_size(low0)]
    if not keys:
        return low0, prog0, []
    low = lower(g, pb, source=src, loop_words=callloop.WORDS)
    for k in range(1, len(keys) + 1):
        looped = callloop.select(low, keys[:k], sizes)
        prog = best_program(low, looped=looped)
        if len(prog.body) + 1 <= callloop.CALL_LOOP_ABOVE:
            break
    callloop.finish(low, prog, src)
    return low, prog, looped


def compile_graph(graph, steps, target="sw", stem="system", source=None,
                  source_bytes=None, params=None):
    """Compile a checked step graph (lang.StepGraph) into its outputs."""
    src = source or "<graph>"
    t = get_target(target)
    if isinstance(steps, bool) or not isinstance(steps, int) \
            or not 1 <= steps <= MAX_STEPS:
        refuse("segment-steps", f"a segment is one REPEAT of 1 to "
               f"{MAX_STEPS:,} steps, and {K.shown(steps)} was given",
               source=src)
    if graph.fmt.name not in t.formats:
        refuse("target-format", f"{graph.fmt.name} is not carried by "
               f"{t.name}, which carries {', '.join(t.formats)}",
               source=src)
    c = Compilation()
    c.stem, c.source, c.steps, c.target = stem, src, steps, t
    c.graph = graph
    # a format override, where the source declares another format: the
    # graph is at the override (lang.compile_text's fmt); the manifest and
    # the .cfta say so. One equal to the declared format is no override.
    own = getattr(graph, "source_format", None)
    c.format_override = (own, graph.fmt.name) \
        if own is not None and own != graph.fmt.name else None
    c.graph_bytes = graph.to_bytes()
    c.source_sha256 = (hashlib.sha256(source_bytes).hexdigest()
                       if source_bytes is not None else None)
    g = Graph(c.graph_bytes)
    c.ir = g
    pb = _param_bits(graph, params, src)
    low = lower(g, pb, source=src)
    half = halve(low, src) if low.h_slots else None
    prog = best_program(low)
    c.looped = []
    if low.routines and len(prog.body) + 1 > callloop.CALL_LOOP_ABOVE:
        low, prog, c.looped = _call_loops(g, pb, src, low, prog)
        half = halve(low, src) if low.h_slots else None
    c.lowered, c.program = low, prog
    # a step's instructions as it runs them: its call loops' bodies once a
    # call (equal to the step's length where it has none), as the loader
    # counts the worst case
    run_step = prog.executed()
    c.worst_case = (len(prog.prologue) + 1 + steps * run_step
                    + len(prog.epilogue) + 1)
    if c.worst_case > MAX_WORST:
        refuse("loader-bound", f"{steps:,} steps of {run_step:,} "
               f"instructions is {c.worst_case:,} instructions at worst, and "
               f"the loader's bound is 2^40 on every device", source=src)
    c.depth = scratch_declared(prog.slots_used)
    meta = {"stem": stem, "source": src, "target": t.name,
            "source_sha256": c.source_sha256 or "(none: a graph)",
            "format_override": c.format_override}
    c.cfta = cfta(low, prog, steps, meta)
    c.image_obj = assemble(c.cfta, stem)
    c.image = c.image_obj.to_bytes()
    c.bank = low.bank_bytes()
    c.half_bank = low.half_bank_bytes()
    feats = [T.ASM_FEATURE.get(f, f) for f in c.image_obj.features()]
    feats.append("SCRATCH_STRICT")
    c.features = [f for f in T.FEATURE_BITS if f in feats]
    missing = [f for f in c.features if f not in t.features()]
    if missing:
        why = ""
        if "FLAG_CONTROL" in missing:
            why = (f": it raises its routines' flags ("
                   f"{' and '.join(low.routines)}) through revision 8's "
                   f"flag control, QUIET, ENDQUIET and RAISE, which no "
                   f"tile has yet; the software targets run it")
        refuse("target-feature", f"the image needs "
               f"{', '.join(f'{f} ({T.CAPS_PLACE[f]})' for f in missing)}, "
               f"which {t.name} does not publish{why}", source=src)
    if len(c.image_obj.insns) > t.max_insns:
        refuse("program-capacity", f"the image is "
               f"{len(c.image_obj.insns):,} instructions and {t.name} holds "
               f"{t.max_insns:,}", source=src)
    if prog.slots_used > t.scratch_depth:
        held = f"{g.n_primal} state"
        if g.T:
            held += (f", {g.T * g.n_primal} for {g.T} tangent "
                     f"vector{'s' if g.T > 1 else ''}")
        refuse("scratch-capacity", f"this program needs {prog.slots_used:,} "
               f"scratch slots a lane ({held}, {len(g.lane)} lane params, "
               f"{prog.spill_slots} spills) and {t.name} has "
               f"{t.scratch_depth:,}", source=src)
    verify(low, prog, c.image, steps, half)
    seq.Program.from_bytes(c.image, scratch_depth=c.depth)
    c.cycles_one_beat = cycles(prog.body, 1)
    c.cycles_sixteen_beats = cycles(prog.body, 16)
    c.accepted_by = M.accepted_by(g.fmt_name, c.features,
                                  len(c.image_obj.insns), prog.slots_used)
    # The intention-out, and its first check. A failure here is a defect -
    # in L1's renderers or in what the compiler handed them - and never a
    # property of the source the writer gave: so it is an InternalError,
    # even where reading the canonical form back raises the language's
    # Refusal (verifier-VL2 planted a renderer fault; it stopped the
    # compilation as a refusal, exit 3, until this was so).
    try:
        c.canonical = lang.render_canonical(graph)
        c.mathematical = lang.render_math(graph)
        back = lang.compile_text(c.canonical, f"{stem}.canonical.cftl")
    except Exception as e:                       # noqa: BLE001
        raise InternalError(f"the intention-out failed, rendering it or "
                            f"reading the canonical form back "
                            f"({type(e).__name__}: {e})") from None
    if back.graph.to_bytes() != c.graph_bytes:
        raise InternalError("the canonical form, read back, is not the same "
                            "step graph")
    c.manifest = M.build(c)
    c.manifest_bytes = M.dumps(c.manifest)
    return c


def compile_text(text, steps, target="sw", source="<text>", stem=None,
                 params=None, fmt=None):
    """Compile a system's text: a str, or a file's bytes - which is how a
    caller holding a file should pass it, as lang.compile_text takes it.
    A text-mode read turns a lone CR into a line end before the
    language's character rule could refuse it (D1's finding, the rule
    L1 adopted); bytes reach the rule whole, and the source's SHA-256 is
    of those bytes. `fmt`, a format's name, overrides the source's
    `format` statement (the module docstring)."""
    system = lang.compile_text(text, source, fmt)
    raw = bytes(text) if isinstance(text, (bytes, bytearray)) \
        else text.encode("utf-8")
    return compile_graph(system.graph, steps, target,
                         stem=stem or "system", source=source,
                         source_bytes=raw, params=params)


def compile_file(path, steps, target="sw", stem=None, params=None,
                 source=None, fmt=None):
    p = Path(path)
    data = p.read_bytes()
    system = lang.load(p, fmt)
    name = stem or (p.name[:-5] if p.name.endswith(".cftl") else p.stem)
    return compile_graph(system.graph, steps, target, stem=name,
                         source=source or p.as_posix(), source_bytes=data,
                         params=params)
