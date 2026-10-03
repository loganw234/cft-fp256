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
ENDREP and HALT - so a tile can run every image, unless the step divides
or takes a root (C4). Then each routine inlined is written

    quiet                     ; div(x, r3): divfull's routine, run quiet
      iand     r12, r3, b17   ; div(x, r3) [1/186]
      ...
    endquiet
    raise    r14              ; div(x, r3)'s flags

- its own opcodes (the integer group, select, the compares, a seed)
with its own attributes as suffixes (its one truncating fma `fma.rtz`),
revision 8's QUIET, ENDQUIET and RAISE around it, and its words as
`.const` lines naming them - so that image needs revision 8's flag
control (R24). The program's attribute is the suffix on the language's
four rounded operations; a quiet operation's rounding field, which it
does not read, is zero.

A step past the call loop's constant (callloop.py) writes each looped
batch as an inner `repeat K` ... `endrep`, its body indented one more,
with revision 7's `ldx`, `stx` and `iadd` for the record index and the
loop's words (LOOP_STEP, each loop's LOOP_BASE) as `.const` lines; a
header line names each loop, its calls and its records' slots.
"""

from cft_golden import asm
from cft_golden.lang import constants as K

from . import callloop

COMMENT_COL = 36
COMMENT_MAX = 200


def bank_name(low, k):
    """A bank slot's name: h, h/2, 2, 8/3, sigma, flip(h), or a routine's
    word by divfull's name for it (K_SIGN)."""
    s = low.slots[k]
    if s.kind == "param":
        return low.graph.param[s.index][0]
    if s.kind == "word":
        return s.names[0][1]
    exact, factor = low.graph.const[s.index][:2]
    base = K.h_form(factor) if factor is not None else K.literal(exact)
    return f"flip({base})" if s.kind == "flip" else base


def bank_role(low, k):
    s = low.slots[k]
    if s.kind == "param":
        return "param" + ("" if s.default else ", a run value")
    if s.kind == "word":
        ops = []
        for op, _n in s.names:
            name = "the call loop" if op == "loop" else op
            if name not in ops:
                ops.append(name)
        also = sorted({n for _o, n in s.names} - {s.names[0][1]})
        return f"a word of {' and '.join(ops)}" + \
            (f", also {', '.join(also)}" if also else "")
    if s.factor is not None and s.factor != 0:
        return f"h-scaled x {K.literal(s.factor)}"
    return "const"


class Namer:
    """Readable names for the values of a lowered step - or of its
    expansion, where the step has routines (inline.py): a routine's
    instructions and raise are named by the routine node they come from,
    as the lowered step names it."""

    def __init__(self, low, x=None):
        self.low = low
        self.x = low if x is None else x
        g = low.graph
        self.g = g
        self.out_name = {}
        for i, o in enumerate(self.x.outs):
            if o[0] == "n" and o[1] not in self.out_name:
                self.out_name[o[1]] = f"next {g.components[i]}"
        self.low_names = None if x is None else Namer(low)

    def kind(self, j):
        return getattr(self.x.nodes[j], "kind", "lang")

    def routine(self, j):
        """The routine node an expanded node comes from: its label, or
        its expression in the lowered step's names; a call loop, by its
        operation and its place among the step's loops."""
        nd = self.x.nodes[j]
        if self.kind(j) == "loop":
            return f"{nd.op} loop {nd.block + 1}"
        low_nd = self.low.nodes[nd.routine]
        return low_nd.label or self.low_names.expr(nd.routine)

    def node(self, j):
        if self.kind(j) != "lang":
            return self.routine(j)
        nd = self.x.nodes[j]
        return nd.label or self.out_name.get(j) or f"n{nd.origin[0]}"

    def ref(self, r):
        kind, i = r
        if kind == "n":
            return self.node(i)
        if kind in "sl":
            return self.g.ref_name(r)
        return bank_name(self.low, self.low.slot_of[r])

    def key(self, key):
        if key[0] in "pcfw":
            return bank_name(self.low, self.low.slot_of[key])
        return self.ref(key)

    def expr(self, j):
        nd = self.x.nodes[j]
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


ROUTINE_SOURCE = {"div": "divfull's", "sqrt": "sqrtfull's"}


def routine_fragment(low, op):
    from cft_golden import routines as R
    return R.fragment(op, low.graph.fmt, low.graph.rnd)


def _loop_text(low, namer, ins, pad):
    """A call loop's own instructions (callloop.py)."""
    nd = namer.x.nodes[ins.node]
    name = namer.routine(ins.node)
    if ins.kind == "repeat":
        recs = nd.stride * len(nd.calls)
        fixed = "".join(f", its {n} b{low.slot_of[r]} for every call"
                        for n, r in nd.fixed.items())
        return _line(f"{pad}repeat {ins.slot}",
                     f"{name}: {len(nd.calls)} calls of "
                     f"{ROUTINE_SOURCE[nd.op]} routine, one a record, "
                     f"slots {nd.base}..{nd.base + recs - 1}{fixed}")
    if ins.kind == "endrep":
        return _line(f"{pad}endrep", f"{name}: the next call")
    if ins.kind == "index":
        if ins.op == "ior":
            return _line(f"{pad}{'ior':<8} r{ins.rd}, {_src(ins.srcs[0])}, "
                         f"{_src(ins.srcs[1])}",
                         f"{name}: the record index, slot {nd.base}")
        return _line(f"{pad}{'iadd':<8} r{ins.rd}, {_src(ins.srcs[0])}, "
                     f"{_src(ins.srcs[1])}", f"{name}: the next slot")
    if ins.kind == "ldx":
        return _line(f"{pad}{'ldx':<8} r{ins.rd}, r{ins.srcs[0][1]}",
                     f"{name}: the call's operand, from its record")
    return _line(f"{pad}{'stx':<8} r{ins.srcs[0][1]}, r{ins.srcs[1][1]}",
                 f"{name}: the call's result, into its record")


def _ins_text(low, namer, ins, indent, out_of, block=None):
    pad = "  " * indent
    if ins.kind in ("repeat", "endrep", "index", "ldx", "stx"):
        return _loop_text(low, namer, ins, pad)
    if ins.kind == "quiet":
        return _line(f"{pad}quiet", f"{block[0]}: {ROUTINE_SOURCE[block[1]]} "
                                    f"routine, run quiet")
    if ins.kind == "endquiet":
        return f"{pad}endquiet"
    if ins.kind == "raise":
        if namer.kind(ins.node) == "loop":
            return _line(f"{pad}{'raise':<8} r{ins.srcs[0][1]}",
                         f"{namer.routine(ins.node)}: the call's flags")
        return _line(f"{pad}{'raise':<8} r{ins.srcs[0][1]}",
                     f"{namer.routine(ins.node)}'s flags")
    if ins.kind == "alu":
        mnem = ins.op
        if ins.op in ("fma", "add", "sub", "mul") and ins.rnd != 0:
            mnem += "." + asm.RND_NAMES[ins.rnd]
        code = f"{pad}{mnem:<8} r{ins.rd}, " + ", ".join(_src(s)
                                                         for s in ins.srcs)
        if namer.kind(ins.node) == "loop":
            nd = namer.x.nodes[ins.node]
            f_len = len(routine_fragment(low, nd.op))
            return _line(code, f"{namer.routine(ins.node)} "
                               f"[{ins.key[1] + 1}/{f_len}]")
        if namer.kind(ins.node) == "quiet":
            at = namer.x.nodes[ins.node].at
            return _line(code, f"{namer.routine(ins.node)} [{at[0]}/{at[1]}]")
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
    if ins.node is not None and namer.kind(ins.node) == "loop":
        return _line(code, f"{namer.key(ins.key)}, into its record for "
                           f"{namer.routine(ins.node)}")
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
    x = prog.x if getattr(prog, "x", None) is not None else low
    namer = Namer(low, None if x is low else x)
    counts = prog.step_counts()
    regs = prog.registers()
    out_of = {}
    for i, o in enumerate(x.outs):
        out_of.setdefault(i, set()).add(o)
    integ, h, _opts = g.integrator
    lines = [
        f"; {meta['stem']} - written by cftc from {meta['source']};",
        "; edit that, not this file.",
        f"; source  sha256 {meta['source_sha256']}",
        f"; graph   sha256 {g.sha256}",
        f"; system  {g.system}: {g.fmt_name}, {g.rnd_name}, {integ}"
        + (f", h = {K.literal(h)}" if h is not None else ""),
    ]
    over = meta.get("format_override")
    if over:
        lines.append(f"; format  {over[1]} by a format override; the source "
                     f"declares {over[0]}")
    if g.T:
        n = g.n_primal
        lines.append("; tangent " + ", ".join(
            f"{vec} (slots {n * (k + 1)}..{n * (k + 2) - 1})"
            for k, vec in enumerate(g.tangent)))
    lines += [
        f"; target  {meta['target']}; {steps} steps a segment",
        f"; a step  {counts['alu']} ALU, {counts['loads']} loads, "
        f"{counts['stores']} stores, {counts['copies']} copies, and the "
        f"endrep",
        f"; registers {len(regs)}"
        + (f" (r{regs[0]}..r{regs[-1]})" if regs else ""),
    ]
    blocks = getattr(x, "blocks", None)
    loops = getattr(x, "loops", None)
    if blocks or loops:
        calls = {}
        for _j, op, _f, _r in blocks:
            calls[op] = calls.get(op, 0) + 1
        for li in loops or ():
            nd = x.nodes[li]
            calls[nd.op] = calls.get(nd.op, 0) + len(nd.calls)
        made = ", ".join(f"{op} {k}" for op, k in calls.items())
        raises = counts["raises"]
        lines.append(f"; routines {made} a step: {prog.routine_alu()} of the "
                     f"ALU instructions in quiet regions, {raises} "
                     f"raise{'' if raises == 1 else 's'}, "
                     f"{counts['brackets']} brackets (revision 8's flag "
                     f"control)")
    if loops:
        lines.append(f"; call loops {len(loops)}, the step past "
                     f"{callloop.CALL_LOOP_ABOVE:,} instructions inlined: "
                     + "; ".join(
                         f"{x.nodes[li].op} x {len(x.nodes[li].calls)} at "
                         f"depth {x.nodes[li].depth}, records from slot "
                         f"{x.nodes[li].base}" for li in loops)
                     + f"; {counts['indexed']} ldx and stx, "
                       f"{counts['index']} index instructions, "
                       f"{counts['loops']} repeats and endreps; "
                       f"{prog.executed():,} instructions run a step")
    lines += [
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
        if s.kind == "word":
            said = bank_name(low, k)
        else:
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
    depth = 1
    for k, ins in enumerate(prog.body):
        if ins.kind in ("endquiet", "endrep"):
            depth -= 1
        block = None
        if ins.kind == "quiet":
            # the block the region opens: its first ALU instruction's
            nxt = next(b for b in prog.body[k + 1:] if b.kind == "alu")
            xn = x.nodes[nxt.node]
            block = (namer.routine(nxt.node),
                     xn.op if namer.kind(nxt.node) == "loop"
                     else low.nodes[xn.routine].op)
        lines.append(_ins_text(low, namer, ins, depth, out_of, block))
        if ins.kind in ("quiet", "repeat"):
            depth += 1
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
