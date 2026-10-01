# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The manifest: what an image is, where everything lives in it, and what
it cost - JSON, ASCII, one-space indent, keys in a fixed order, a final
newline, the same bytes for the same source on every machine.

Every exact value, encoding, flag and relative error is spelt by the
language's own constants code (cft_golden.lang.constants), so the
manifest and the canonical form say the same numbers.
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
        out.append({"expression": text, "exact": str(shift),
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
        r = prog.pinned.get(("s", i))
        entry["pinned"] = None if r is None else f"r{r}"
        layout.append(entry)
    for j, (name, default, bits) in enumerate(g.lane):
        r = prog.pinned.get(("l", j))
        layout.append({"slot": g.n_state + j, "name": name,
                       "kind": "lane param",
                       "default": None if default is None else str(default),
                       "default_encoding": None if bits is None
                       else _hex(fmt, bits),
                       "pinned": None if r is None else f"r{r}"})
    bank = []
    for k, s in enumerate(low.slots):
        e = {"slot": k, "name": bank_name(low, k), "kind": s.kind}
        if s.kind == "flip":
            e["flips"] = low.slot_of.get(("c", s.index))
            e["const"] = K.literal(g.const[s.index][0])
        if s.kind == "param":
            e["default"] = s.default
        e["exact"] = str(s.exact)
        e["h_factor"] = None if s.factor is None else str(s.factor)
        e["encoding"] = _hex(fmt, s.bits)
        e["value"] = _value_text(fmt, s.bits)
        e["flags"] = flag_words(s.flags)
        e["relative_error"] = K.sig(K.relative_error(fmt, s.bits, s.exact))
        if low.half_bits is not None and k in low.h_slots:
            e["halved"] = _hex(fmt, low.half_bits[k])
        bank.append(e)
    overrides = [{"name": g.param[s.index][0], "value": str(s.exact),
                  "encoding": _hex(fmt, s.bits),
                  "default": str(g.param[s.index][1])}
                 for s in low.slots if s.kind == "param" and not s.default]
    integ, h, opts = g.integrator
    m = {
        "cftc_manifest": 1,
        "compiler": {"name": "cftc", "version": c.version},
        "source": {"path": c.source, "sha256": c.source_sha256},
        "graph": {"cftl_graph": 1, "file": f"{c.stem}.graph.json",
                  "sha256": g.sha256},
        "system": g.system,
        "format": g.fmt_name,
        "round": g.rnd_name,
        "integrator": {"name": integ,
                       "h": None if h is None else str(h),
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
        "cost_model": {
            "assumes": "revision 7, a single-pass tile; believed from "
                       "docs/SEQUENCER.md R12-R19, not measured; the card's "
                       "measurement is the lead's",
            "cycles_per_step_one_beat": c.cycles_one_beat,
            "cycles_per_step_sixteen_beats": c.cycles_sixteen_beats,
        },
        "files": c.file_digests(),
    }
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
