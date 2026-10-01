# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The `.cfta` text, which asm.py assembles into the image.

What the text holds (docs/PROGRAMS.md is the form's specification):
* a header comment naming the source, both SHA-256s, the target and S;
* `.format`, `.deposits 0`, `.bank external`, `.scratch strict`,
  `.scratch in m`, `.scratch out m`, and `.scratch D` where D is the
  smallest power of two at least 256 covering every slot used -
  asm.infer_scratch_depth's own rule, so a disassembly writes it back;
* `.const b0` ... in slot order, bare names under `.bank external`, each
  with a comment giving its name, kind, exact value and encoding;
* the prologue, `repeat S`, the step, `endrep`, the epilogue, `halt`.

Registers are written rN and slots as numbers: the language's names are
case-sensitive and `.cfta`'s are not, so no language name becomes a
`.cfta` name. Each instruction's comment names its node's label and
expression, as the step graph has them.

Only revision-7 instructions are written - the ALU opcodes the
language's built-ins name, `ior` for a copy, and STL, LDL, REPEAT,
ENDREP and HALT - so a tile can run every image. The program's
attribute is the suffix on the four rounded operations only; a quiet
operation's rounding field, which it does not read, is zero.
"""

from cft_golden import asm
from cft_golden.lang import constants as K

COMMENT_COL = 36
COMMENT_MAX = 200


def bank_name(low, k):
    """A bank slot's name: h, h/2, 2, 8/3, sigma, or flip(h)."""
    s = low.slots[k]
    if s.kind == "param":
        return low.graph.param[s.index][0]
    exact, factor = low.graph.const[s.index][:2]
    base = K.h_form(factor) if factor is not None else K.literal(exact)
    return f"flip({base})" if s.kind == "flip" else base


def bank_role(low, k):
    s = low.slots[k]
    if s.kind == "param":
        return "param" + ("" if s.default else ", a run value")
    if s.factor is not None and s.factor != 0:
        return f"h-scaled x {K.literal(s.factor)}"
    return "const"


class Namer:
    """Readable names for the values of a lowered step."""

    def __init__(self, low):
        self.low = low
        g = low.graph
        self.g = g
        self.out_name = {}
        for i, o in enumerate(low.outs):
            if o[0] == "n" and o[1] not in self.out_name:
                self.out_name[o[1]] = f"next {g.components[i]}"

    def node(self, j):
        nd = self.low.nodes[j]
        return nd.label or self.out_name.get(j) or f"n{nd.origin[0]}"

    def ref(self, r):
        kind, i = r
        if kind == "n":
            return self.node(i)
        if kind in "sl":
            return self.g.ref_name(r)
        return bank_name(self.low, self.low.slot_of[r])

    def key(self, key):
        if key[0] in "pcf":
            return bank_name(self.low, self.low.slot_of[key])
        return self.ref(key)

    def expr(self, j):
        nd = self.low.nodes[j]
        return f"{nd.op}({', '.join(self.ref(a) for a in nd.args)})"


def _line(code, comment):
    if not comment:
        return code
    text = code.ljust(COMMENT_COL - 1) + " ; " + comment
    if len(text) > COMMENT_MAX:
        text = text[:COMMENT_MAX - 3] + "..."
    return text


def _src(s):
    return f"r{s[1]}" if s[0] == "r" else f"b{s[1]}"


def _ins_text(low, namer, ins, indent, out_of):
    pad = "  " * indent
    if ins.kind == "alu":
        mnem = ins.op
        if ins.op in ("fma", "add", "sub", "mul") and ins.rnd != 0:
            mnem += "." + asm.RND_NAMES[ins.rnd]
        code = f"{pad}{mnem:<8} r{ins.rd}, " + ", ".join(_src(s)
                                                         for s in ins.srcs)
        return _line(code, f"{namer.node(ins.node)} = {namer.expr(ins.node)}")
    if ins.kind == "copy":
        code = f"{pad}{'ior':<8} r{ins.rd}, {_src(ins.srcs[0])}, " \
               f"{_src(ins.srcs[1])}"
        return _line(code, f"{namer.key(ins.key)}, copied")
    if ins.kind == "ldl":
        code = f"{pad}{'ldl':<8} r{ins.rd}, {ins.slot}"
        n = low.graph.n_state
        own = ((ins.key[0] == "s" and ins.key[1] == ins.slot) or
               (ins.key[0] == "l" and ins.key[1] + n == ins.slot))
        where = "its home" if own else f"slot {ins.slot}"
        return _line(code, f"{namer.key(ins.key)}, from {where}")
    code = f"{pad}{'stl':<8} r{ins.srcs[0][1]}, {ins.slot}"
    if ins.slot < low.graph.n_state and ins.key in out_of.get(ins.slot, ()):
        what = f"next {low.graph.components[ins.slot]}"
    elif ins.slot < low.graph.n_state and ins.key == ("s", ins.slot):
        what = f"{low.graph.components[ins.slot]}, the segment's last state"
    else:
        what = f"{namer.key(ins.key)}, spilled"
    return _line(code, what)


def scratch_declared(slots_used):
    d = 256
    while d < slots_used:
        d *= 2
    return d


def cfta(low, prog, steps, meta):
    """The program's text. `meta`: stem, source, source_sha256, target."""
    g = low.graph
    namer = Namer(low)
    counts = prog.step_counts()
    regs = prog.registers()
    out_of = {}
    for i, o in enumerate(low.outs):
        out_of.setdefault(i, set()).add(o)
    integ, h, _opts = g.integrator
    lines = [
        f"; {meta['stem']} - written by cftc from {meta['source']};",
        "; edit that, not this file.",
        f"; source  sha256 {meta['source_sha256']}",
        f"; graph   sha256 {g.sha256}",
        f"; system  {g.system}: {g.fmt_name}, {g.rnd_name}, {integ}"
        + (f", h = {K.literal(h)}" if h is not None else ""),
        f"; target  {meta['target']}; {steps} steps a segment",
        f"; a step  {counts['alu']} ALU, {counts['loads']} loads, "
        f"{counts['stores']} stores, {counts['copies']} copies, and the "
        f"endrep",
        f"; registers {len(regs)}"
        + (f" (r{regs[0]}..r{regs[-1]})" if regs else ""),
        "",
        f".format   {g.fmt_name}",
        ".deposits 0",
        ".bank     external",
        ".scratch  strict",
        f".scratch  in {g.m}",
        f".scratch  out {g.m}",
    ]
    depth = scratch_declared(prog.slots_used)
    if depth != 256:
        lines.append(f".scratch  {depth}")
    lines.append("")
    esz = g.fmt.width // 4
    for k, s in enumerate(low.slots):
        name, value = bank_name(low, k), K.literal(s.exact)
        said = name if name == value else f"{name} = {value}"
        lines.append(_line(f".const    b{k}",
                           f"{said} ({bank_role(low, k)}): "
                           f"0x{s.bits:0{esz}x}"))
    lines.append("")
    if prog.prologue:
        lines.append("; the pinned values into their registers")
        for ins in prog.prologue:
            lines.append(_ins_text(low, namer, ins, 0, out_of))
    lines.append(f"repeat {steps}")
    for ins in prog.body:
        lines.append(_ins_text(low, namer, ins, 1, out_of))
    lines.append("endrep")
    if prog.epilogue:
        lines.append("; the pinned state back to its homes")
        for ins in prog.epilogue:
            lines.append(_ins_text(low, namer, ins, 0, out_of))
    lines.append("halt")
    return "\n".join(lines) + "\n"


def assemble(text, stem):
    """asm.py's image of the text: the bytes a .cftp file holds."""
    return asm.assemble_image(text, f"{stem}.cfta")
