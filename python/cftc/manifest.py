# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The manifest: what an image is, where everything lives in it, and what
it cost - JSON, ASCII, one-space indent, keys in a fixed order, a final
newline, the same bytes for the same source on every machine.

Every exact value, encoding, flag and relative error is spelt by the
language's own constants code (cft_golden.lang.constants), so the
manifest and the canonical form say the same numbers - an exact value as
the step graph writes it, p or p/q, through frac_text, at any size
(str() of a Fraction stops at Python's 4,300-digit limit).
"""

import json
from fractions import Fraction

from cft_golden import softfloat as sf
from cft_golden.lang import constants as K

from .emit import bank_name, scratch_declared
from .targets import BUILTIN

FLAG_WORDS = ((sf.FLAG_INVALID, "invalid"), (sf.FLAG_DIVZERO, "divideByZero"),
              (sf.FLAG_OVERFLOW, "overflow"),
              (sf.FLAG_UNDERFLOW, "underflow"), (sf.FLAG_INEXACT, "inexact"))

# What each template's step advances the independent variable by, over
# RN(h): k times the h-scaled constant of factor f. rk4's update is
# RN(h/6) (k1 + 2 k2 + 2 k3 + k4), six times RN(h/6); stormer-verlet's
# positions move by RN(h/2) twice and its momenta by RN(h) once; euler's
# by RN(h).
SHIFTS = {
    "rk4": [("6 RN(h/6) / RN(h) - 1", 6, Fraction(1, 6))],
    "stormer-verlet": [("2 RN(h/2) / RN(h) - 1", 2, Fraction(1, 2)),
                       ("RN(h) / RN(h) - 1", 1, Fraction(1))],
    "euler": [("RN(h) / RN(h) - 1", 1, Fraction(1))],
}


def flag_words(flags):
    return [w for b, w in FLAG_WORDS if flags & b]


def _call_loop_above():
    """The call loop's constant, as the manifest states it: read when the
    manifest is built, so that a test lowering it is seen."""
    from . import callloop
    return callloop.CALL_LOOP_ABOVE


def _hex(fmt, bits):
    return K.bits_hex(fmt, bits)


def _value_text(fmt, bits):
    """The encoding's exact value as a hexadecimal significand, or what it
    is when it is not finite."""
    u = sf.unpack(fmt, bits)
    if u.kind == sf.INF:
        return "-inf" if u.sign else "inf"
    if u.kind == sf.NAN:
        return "nan"
    return K.literal(K.value_of(fmt, bits))


def time_shift(g):
    integ, h, _opts = g.integrator
    if integ not in SHIFTS or h is None:
        return None
    fmt, rnd = g.fmt, g.rnd
    rn_h, _ = K.round_once(fmt, rnd, h)
    vh = K.value_of(fmt, rn_h)
    out = []
    for text, k, factor in SHIFTS[integ]:
        bits, _ = K.round_once(fmt, rnd, factor * h)
        shift = k * K.value_of(fmt, bits) / vh - 1
        out.append({"expression": text, "exact": K.frac_text(shift),
                    "value": K.sig(shift)})
    return out


def build(c):
    """The manifest of a Compilation, as an ordered dict."""
    low, prog, g = c.lowered, c.program, c.ir
    fmt = g.fmt
    counts = prog.step_counts()
    by_op = {}
    for ins in prog.body:
        if ins.kind == "alu":
            by_op[ins.op] = by_op.get(ins.op, 0) + 1
    regs = prog.registers()
    layout = []
    for i, name in enumerate(g.components):
        entry = {"slot": i, "name": name, "kind": "state"}
        if i >= g.n_primal:
            # a tangent vector's component: the vector, and the state
            # component it is the tangent of
            vk, comp = divmod(i - g.n_primal, g.n_primal)
            entry = {"slot": i, "name": name, "kind": "tangent",
                     "vector": g.tangent[vk],
                     "of": g.primal_components[comp]}
        r = prog.pinned.get(("s", i))
        entry["pinned"] = None if r is None else f"r{r}"
        layout.append(entry)
    for j, (name, default, bits) in enumerate(g.lane):
        r = prog.pinned.get(("l", j))
        layout.append({"slot": g.n_state + j, "name": name,
                       "kind": "lane param",
                       "default": None if default is None
                       else K.frac_text(default),
                       "default_encoding": None if bits is None
                       else _hex(fmt, bits),
                       "pinned": None if r is None else f"r{r}"})
    bank = []
    for k, s in enumerate(low.slots):
        e = {"slot": k, "name": bank_name(low, k), "kind": s.kind}
        if s.kind == "word":
            # a routine's word (C4): raw bits at the format, no rational's
            # rounding - so no exact value, flags or error - and never
            # h-scaled; every (routine, divfull name) it stands for
            e["words"] = [f"{op} {name}" for op, name in s.names]
            e["exact"] = None
            e["h_factor"] = None
            e["encoding"] = _hex(fmt, s.bits)
            e["value"] = _value_text(fmt, s.bits)
            e["flags"] = []
            e["relative_error"] = None
            bank.append(e)
            continue
        if s.kind == "flip":
            e["flips"] = low.slot_of.get(("c", s.index))
            e["const"] = K.literal(g.const[s.index][0])
        if s.kind == "param":
            e["default"] = s.default
        e["exact"] = K.frac_text(s.exact)
        e["h_factor"] = None if s.factor is None else K.frac_text(s.factor)
        e["encoding"] = _hex(fmt, s.bits)
        e["value"] = _value_text(fmt, s.bits)
        e["flags"] = flag_words(s.flags)
        e["relative_error"] = K.sig(K.relative_error(fmt, s.bits, s.exact))
        if low.half_bits is not None and k in low.h_slots:
            e["halved"] = _hex(fmt, low.half_bits[k])
        bank.append(e)
    overrides = [{"name": g.param[s.index][0], "value": K.frac_text(s.exact),
                  "encoding": _hex(fmt, s.bits),
                  "default": K.frac_text(g.param[s.index][1])}
                 for s in low.slots if s.kind == "param" and not s.default]
    integ, h, opts = g.integrator
    source = {"path": c.source, "sha256": c.source_sha256}
    over = getattr(c, "format_override", None)
    if over:
        # only where a format override changed the format, so that every
        # other manifest is what it was (C4)
        source["format_override"] = {"source": over[0], "compiled": over[1]}
    m = {
        "cftc_manifest": 1,
        "compiler": {"name": "cftc", "version": c.version},
        "source": source,
        "graph": {"cftl_graph": g.version, "file": f"{c.stem}.graph.json",
                  "sha256": g.sha256},
        "system": g.system,
        "format": g.fmt_name,
        "round": g.rnd_name,
        "integrator": {"name": integ,
                       "h": None if h is None else K.frac_text(h),
                       "options": opts},
        "steps": c.steps,
        "target": c.target.describe(),
        "accepted_by": c.accepted_by,
        "uses": {
            "instructions": len(c.image_obj.insns),
            "registers": len(regs),
            "register_list": regs,
            "scratch_slots": prog.slots_used,
            "scratch_declared": scratch_declared(prog.slots_used),
            "bank_slots": len(low.slots),
            "worst_case_instructions": c.worst_case,
            "features": c.features,
        },
        "per_step": {
            "instructions": len(prog.body) + 1,
            "alu": counts["alu"],
            "loads": counts["loads"],
            "stores": counts["stores"],
            "copies": counts["copies"],
            "endrep": 1,
            "by_op": by_op,
        },
        "per_segment": {
            "prologue_loads": len(prog.prologue),
            "epilogue_stores": len(prog.epilogue),
            "repeat": 1,
            "halt": 1,
        },
        "lowering": {
            "graph_step_nodes": len(g.nodes),
            "graph_by_op": g.op_counts(),
            "shared": low.shared,
            "folded": len(low.folds),
            "folds": [{"neg": f"n{f['neg_origin']}",
                       "labels": f["labels"], "uses": f["uses"],
                       "flip_slots": f["slots"]} for f in low.folds],
            "order": prog.candidate[0] + (f" {prog.candidate[1]}"
                                          if prog.candidate[1] else ""),
            "pinning": prog.pinning,
        },
        "scratch": {
            "in": g.m,
            "out": g.m,
            "spill_slots": prog.spill_slots,
            "strict": True,
            "layout": layout,
        },
        "bank": bank,
        "param_overrides": overrides,
        "h_slots": list(low.h_slots),
        "time_shift": time_shift(g),
    }
    if g.T:
        # the variational equations' own entries, only where the graph
        # has them, so a manifest without tangents is what it was
        m["tangent"] = {
            "vectors": list(g.tangent),
            "components": g.n_primal,
            "slots": [g.n_primal * (k + 1) for k in range(g.T)],
        }
        m["lowering"]["graph_step_nodes"] = g.primal_step_nodes
        m["lowering"]["graph_by_op"] = g.primal_counts
        m["lowering"]["graph_tangent_step_nodes"] = g.tangent_step_nodes
        m["lowering"]["graph_tangent_by_op"] = g.tangent_counts
    x = getattr(prog, "x", None)
    blocks = getattr(x, "blocks", None)
    loops = getattr(x, "loops", None)
    if blocks or loops:
        # the routines' own entries (C4), only where the step has them, so
        # a manifest without them is what it was
        from cft_golden import routines as R
        calls = {}
        for _j, op, _f, _r in blocks:
            calls[op] = calls.get(op, 0) + 1
        for li in loops or ():
            nd = x.nodes[li]
            calls[nd.op] = calls.get(nd.op, 0) + len(nd.calls)
        m["routines"] = {
            "calls": calls,
            "per_call": {op: len(R.fragment(op, fmt, g.rnd))
                         for op in calls},
            "words": sum(1 for s in low.slots if s.kind == "word"),
            "instructions_quiet": prog.routine_alu(),
            "raises": counts["raises"],
            "brackets": counts["brackets"],
            "source": "cft_golden/routines.py: divfull's and sqrtfull's "
                      "instructions, relocated and specialised at the "
                      "program's attribute",
            "flags": "each runs in a quiet region and raises exactly its "
                     "operation's flags: revision 8's flag control, "
                     "QUIET, ENDQUIET and RAISE (docs/SEQUENCER.md R24)",
        }
        if loops:
            # only where the step, its routines inlined, would pass the
            # call loop's constant (callloop.py)
            m["routines"]["call_loops"] = {
                "above": _call_loop_above(),
                "loops": [{"op": x.nodes[li].op,
                           "depth": x.nodes[li].depth,
                           "calls": len(x.nodes[li].calls),
                           "records": [x.nodes[li].base,
                                       x.nodes[li].base + x.nodes[li].stride
                                       * len(x.nodes[li].calls) - 1],
                           "fixed": {name: low.slot_of[ref] for name, ref
                                     in x.nodes[li].fixed.items()}}
                          for li in loops],
                "executed_per_step": prog.executed(),
            }
    cost = {
        "assumes": "revision 7, a single-pass tile (docs/SEQUENCER.md "
                   "R12-R19); measured on revision 7's quad on the U50, "
                   "where ten compiled programs ran 2.2% to 5.8% slower "
                   "than this model (docs/VALIDATION.md, 2026-10-02)",
    }
    if blocks or loops:
        cost["routines"] = ("QUIET and ENDQUIET a cycle each, RAISE a beat "
                            "a cycle once its register has landed: believed, "
                            "from R18's prices for the control codes it "
                            "built, since no tile has revision 8's R24")
    if loops:
        cost["call_loops"] = ("a call loop runs as unrolled, its REPEAT and "
                              "each ENDREP a cycle; an LDX waits for its "
                              "index to have landed, fires two steps later "
                              "than an LDL and holds the next instruction "
                              "that is not one two cycles; an STX waits for "
                              "its index landed: R18's rules, believed, since "
                              "no compiled image has run them on a card")
    cost["cycles_per_step_one_beat"] = c.cycles_one_beat
    cost["cycles_per_step_sixteen_beats"] = c.cycles_sixteen_beats
    m.update({
        "cost_model": cost,
        "files": c.file_digests(),
    })
    return m


def dumps(m):
    return (json.dumps(m, indent=1, ensure_ascii=True) + "\n").encode("ascii")


def accepted_by(fmt_name, features, insns, slots):
    out = []
    for name, t in BUILTIN.items():
        if fmt_name not in t.formats:
            continue
        if any(f not in t.features() for f in features):
            continue
        if insns > t.max_insns or slots > t.scratch_depth:
            continue
        out.append(name)
    return out
