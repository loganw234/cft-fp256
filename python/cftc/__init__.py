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

Known limit: compile time grows faster than the step does, roughly with
its square for a wide step - the list schedulers scan their ready set at
every pick, and six candidate orders are scheduled and allocated.
Measured on the desktop, niced and in use (2026-10-01), for rings of
the Lorenz-96 kind: 0.3 s at 760 nodes, 3.6 s at 3,800, 14 s at 7,980
and 58 s at 16,796 (verifier-VL2 measured about 100 s for 16,800 before
the homed stores were indexed by position).
"""

import hashlib
from pathlib import Path

from cft_golden import asm, seq
from cft_golden import lang
from cft_golden.lang import constants as K

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

VERSION = 1
MAX_STEPS = (1 << 32) - 1
MAX_WORST = 1 << 40

__all__ = ["BUILTIN", "Compilation", "InternalError", "MAX_STEPS", "NAMES",
           "Target", "VERSION", "compile_file", "compile_graph",
           "compile_text", "get_target", "lang"]


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

    def scratch_block(self, states, lane_params=None):
        """The lane-major block a run takes: each lane's state, then its
        lane params (their defaults where none are given)."""
        g = self.ir
        out = []
        for k, st in enumerate(states):
            if lane_params is None:
                lp = [b for _n, _d, b in g.lane]
                if any(b is None for b in lp):
                    raise ValueError("a lane param without a default needs "
                                     "lane_params")
            else:
                lp = lane_params[k]
            out += list(st) + list(lp)
        return out

    def run(self, states, lane_params=None, bank=None, scratch_depth=None,
            streams=None):
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
                       scratch_in=self.scratch_block(states, lane_params),
                       scratch_depth=scratch_depth or self.depth)


def _param_bits(graph, params, source):
    """{index: (bits, flags, exact)} for run values given by name. Each is
    read by the language itself, as the default of a param of a one-line
    system, so it is exactly what the same text written as a default
    would be - a decimal read exactly, a/b a constant division, never
    binary64 - and refused by the same names."""
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
        text = (f"system runvalue\nformat {graph.fmt.name}\n"
                f"round {graph.round_name}\nstate x\n"
                f"param v = {value}\nnext x = x * v\nstep map\n")
        try:
            g1 = lang.compile_text(text, f"--param {name}").graph
        except lang.Refusal as e:
            raise lang.Refusal(e.name, f"--param {name}={value}: "
                               f"{e.sentence}", source=source) from None
        _n, exact, bits, flags = g1.param[0]
        out[names.index(name)] = (bits, flags, exact)
    return out


def compile_graph(graph, steps, target="sw", stem="system", source=None,
                  source_bytes=None, params=None):
    """Compile a checked step graph (lang.StepGraph) into its outputs."""
    src = source or "<graph>"
    t = get_target(target)
    if isinstance(steps, bool) or not isinstance(steps, int) \
            or not 1 <= steps <= MAX_STEPS:
        refuse("segment-steps", f"a segment is one REPEAT of 1 to "
               f"{MAX_STEPS:,} steps, and {steps!r} was given", source=src)
    if graph.fmt.name not in t.formats:
        refuse("target-format", f"{graph.fmt.name} is not carried by "
               f"{t.name}, which carries {', '.join(t.formats)}",
               source=src)
    c = Compilation()
    c.stem, c.source, c.steps, c.target = stem, src, steps, t
    c.graph = graph
    c.graph_bytes = graph.to_bytes()
    c.source_sha256 = (hashlib.sha256(source_bytes).hexdigest()
                       if source_bytes is not None else None)
    g = Graph(c.graph_bytes)
    c.ir = g
    c.lowered = low = lower(g, _param_bits(graph, params, src))
    half = halve(low, src) if low.h_slots else None
    c.program = prog = best_program(low)
    c.worst_case = (len(prog.prologue) + 1 + steps * (len(prog.body) + 1)
                    + len(prog.epilogue) + 1)
    if c.worst_case > MAX_WORST:
        refuse("loader-bound", f"{steps:,} steps of {len(prog.body) + 1:,} "
               f"instructions is {c.worst_case:,} instructions at worst, and "
               f"the loader's bound is 2^40 on every device", source=src)
    c.depth = scratch_declared(prog.slots_used)
    meta = {"stem": stem, "source": src, "target": t.name,
            "source_sha256": c.source_sha256 or "(none: a graph)"}
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
        refuse("target-feature", f"the image needs "
               f"{', '.join(f'{f} ({T.CAPS_PLACE[f]})' for f in missing)}, "
               f"which {t.name} does not publish", source=src)
    if len(c.image_obj.insns) > t.max_insns:
        refuse("program-capacity", f"the image is "
               f"{len(c.image_obj.insns):,} instructions and {t.name} holds "
               f"{t.max_insns:,}", source=src)
    if prog.slots_used > t.scratch_depth:
        refuse("scratch-capacity", f"this program needs {prog.slots_used:,} "
               f"scratch slots a lane ({g.n_state} state, {len(g.lane)} lane "
               f"params, {prog.spill_slots} spills) and {t.name} has "
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
                 params=None):
    system = lang.compile_text(text, source)
    return compile_graph(system.graph, steps, target,
                         stem=stem or "system", source=source,
                         source_bytes=text.encode("utf-8"), params=params)


def compile_file(path, steps, target="sw", stem=None, params=None,
                 source=None):
    p = Path(path)
    data = p.read_bytes()
    system = lang.load(p)
    name = stem or (p.name[:-5] if p.name.endswith(".cftl") else p.stem)
    return compile_graph(system.graph, steps, target, stem=name,
                         source=source or p.as_posix(), source_bytes=data,
                         params=params)
