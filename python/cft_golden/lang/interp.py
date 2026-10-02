# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The reference interpreter: the definition of correct for the language.

It steps a system's step graph through the golden softfloat, one
operation per node, on any number of lanes, for S steps, and returns
each lane's state and the run's FLAGS - the five IEEE flags, a sticky OR
over every node of every lane and step, exactly as seq.py ORs every ALU
instruction's over its active lanes (seq.py run(), the ALU branch).
A compiled image is correct when its run equals this one, FLAGS
included.

The lane layout is seq.py's scratch block: lane k's values are its
state components in declaration order (an array's by index), then its
lane params in declaration order - so lane k is
scratch_in[k*m:(k+1)*m] with m = n_state + n_lane, and after S steps its
state is Result.scratch_out[k*m : k*m + n_state].
"""

from fractions import Fraction

from .. import softfloat as sf
from . import constants as C
from .check import constant_of
from .refusals import Refusal


class Run:
    __slots__ = ("states", "flags", "at", "tangents", "primal_flags",
                 "at_tangents")

    def __init__(self, states, flags, at, tangents=None, primal_flags=None,
                 at_tangents=None):
        self.states = states        # [[bits] a lane]
        self.flags = flags          # the run's sticky FLAGS: every node's
        self.at = at                # {s: (states, flags)}
        self.tangents = tangents    # [[[bits] a vector] a lane], or None
        # the primal nodes' FLAGS alone - a run of the system without its
        # tangent vectors gives these, bit for bit
        self.primal_flags = flags if primal_flags is None else primal_flags
        self.at_tangents = at_tangents or {}    # {s: tangents}


def _ops(fmt, rnd):
    """The golden function for each node operation. The six that round
    take the program's attribute - division and the square root among
    them, sf.div and sf.sqrt, correctly rounded with their exact flags
    (L4) - and the rest are called as softfloat.compute calls them, and
    ignore it."""
    return {
        "fma": lambda a, b, c: sf.fma(fmt, a, b, c, rnd),
        "add": lambda a, b: sf.add(fmt, a, b, rnd),
        "sub": lambda a, b: sf.sub(fmt, a, b, rnd),
        "mul": lambda a, b: sf.mul(fmt, a, b, rnd),
        "div": lambda a, b: sf.div(fmt, a, b, rnd),
        "sqrt": lambda a: sf.sqrt(fmt, a, rnd),
        "neg": lambda a: sf.neg(fmt, a),
        "abs": lambda a: sf.fabs(fmt, a),
        "copysign": lambda a, b: sf.copysign(fmt, a, b),
        "min": lambda a, b: sf.fmin(fmt, a, b),
        "max": lambda a, b: sf.fmax(fmt, a, b),
        "minnum": lambda a, b: sf.fminnum(fmt, a, b),
        "maxnum": lambda a, b: sf.fmaxnum(fmt, a, b),
        "cmplt": lambda a, b: sf.cmplt(fmt, a, b),
        "cmple": lambda a, b: sf.cmple(fmt, a, b),
        "cmpeq": lambda a, b: sf.cmpeq(fmt, a, b),
        "select": lambda a, b, c: sf.select(fmt, a, b, c),
    }


def _whole(n):
    return isinstance(n, int) and not isinstance(n, bool) and n >= 0


def _exact_run_value(name, value):
    """A run value as an exact rational: an int, a Fraction, or text
    read by the language's own rules for a constant (constant_of)."""
    if isinstance(value, float):
        raise Refusal("param-value", f"{name}'s run value is a Python float, "
                      f"which is binary64 already: give an int, a Fraction "
                      f"or the literal as text")
    if isinstance(value, bool):
        raise Refusal("param-value", f"{name}'s run value is a bool")
    if isinstance(value, str):
        try:
            v = constant_of(value)
        except Refusal as r:
            if r.name.startswith("constant-") or r.name == "too-deep":
                raise
            raise Refusal("param-value", f"{name}'s run value {value!r} is "
                          f"not a constant: {r.sentence}") from None
    elif isinstance(value, (int, Fraction)):
        v = Fraction(value)
    else:
        raise Refusal("param-value", f"{name}'s run value {value!r} is not "
                      f"an exact rational (an int, a Fraction or text such "
                      f"as 8/3, 0.01 or 0x1p-3)")
    if not C.in_range(v):
        raise Refusal("constant-range", f"{name}'s run value lies beyond "
                      f"2^+-{C.LIMIT_LOG2}, outside every format by far")
    return v


def _round_run(graph, name, value):
    fmt, rnd = graph.fmt, graph.rnd
    bits, flags = C.round_once(fmt, rnd, value)
    over = C.overflowed(flags)
    if over or C.rounded_to_zero(fmt, value, bits):
        where = f"{C.FORMAT_754[fmt.name]} under {sf.RND_NAMES[rnd]}"
        if over:
            raise Refusal("constant-overflow", f"{name} = {C.brief(value)} "
                          f"overflows {where}")
        raise Refusal("constant-rounds-to-zero", f"{name} = "
                      f"{C.brief(value)} is not zero and rounds to zero in "
                      f"{where}")
    return bits


def run(graph, states, steps, lane_params=None, params=None,
        param_bits=None, h=None, at=(), tangents=None):
    """Step `graph` S = `steps` times on every lane.

    states       one list a lane: the state's encodings, flat order
    lane_params  one list a lane: the lane params' encodings, in
                 declaration order; None takes each one's default
    params       {name: exact value - an int, a Fraction or text such as
                 8/3}: run values, each rounded once under the
                 program's attribute
    param_bits   {name: encoding}: run values as a bank carries them
    h            an exact step in place of the graph's h, of the graph's
                 h's sign: every h-scaled constant is recomputed from it
                 and rounded once, which is the graph compiled at that h
    at           step counts at which to record (states, FLAGS)
    tangents     for a graph with tangent vectors, and only then: one
                 list a lane, holding one list a vector (declaration
                 order) of the state's n encodings, flat order

    Returns a Run: .states, .flags, and .at = {s: (states, flags)}; for
    a graph with tangent vectors also .tangents (as given), .primal_flags
    (the primal nodes' alone) and .at_tangents = {s: tangents}. Each step
    evaluates the primal nodes first, then each vector's tangent nodes,
    which only read them: the states and the primal flags are the run of
    the same system without its tangents, bit for bit.
    """
    fmt, rnd = graph.fmt, graph.rnd
    top = 1 << fmt.width
    if not _whole(steps):
        raise Refusal("step-count", f"steps is a whole number, at least 0; "
                      f"{C.shown(steps)} is not")
    marks = []
    for s in at:
        if not _whole(s) or s > steps:
            raise Refusal("step-count", f"a checkpoint is a whole number "
                          f"from 0 to the run's {C.shown(steps)} steps; "
                          f"{C.shown(s)} is not")
        marks.append(s)
    n, m = graph.n_state, len(graph.lane)
    states = [list(st) for st in states]
    for k, st in enumerate(states):
        if len(st) != n:
            raise Refusal("lane-shape", f"lane {k} holds {len(st)} state "
                          f"values; a lane of {graph.system} has {n}")
        for v in st:
            if not isinstance(v, int) or isinstance(v, bool) \
                    or not 0 <= v < top:
                raise Refusal("lane-value", f"lane {k}'s value {C.shown(v)} "
                              f"is not a {C.FORMAT_754[fmt.name]} encoding")
    if lane_params is None:
        missing = [nm for nm, d, _b in graph.lane if d is None]
        if missing:
            raise Refusal("lane-shape", f"lane param {missing[0]} has no "
                          f"default, so each lane gives it: lane_params")
        lane_params = [[b for _n, _d, b in graph.lane] for _ in states]
    lane_params = [list(lp) for lp in lane_params]
    if len(lane_params) != len(states):
        raise Refusal("lane-shape", f"{len(lane_params)} lanes of lane "
                      f"params for {len(states)} lanes of state")
    for k, lp in enumerate(lane_params):
        if len(lp) != m:
            raise Refusal("lane-shape", f"lane {k} holds {len(lp)} lane "
                          f"param values; {graph.system} has {m}")
        for v in lp:
            if not isinstance(v, int) or isinstance(v, bool) \
                    or not 0 <= v < top:
                raise Refusal("lane-value", f"lane {k}'s lane param value "
                              f"{C.shown(v)} is not a "
                              f"{C.FORMAT_754[fmt.name]} encoding")
    T = len(graph.tangent)
    if T == 0 and tangents is not None:
        raise Refusal("lane-shape", f"{graph.system} carries no tangent "
                      f"vectors, and tangents were given")
    if T:
        vecs = ", ".join(graph.tangent)
        if tangents is None:
            raise Refusal("lane-shape", f"{graph.system} carries the tangent "
                          f"vector{'s' if T > 1 else ''} {vecs}, so each "
                          f"lane gives {'them' if T > 1 else 'it'}: tangents")
        tangents = [[list(t) for t in lt] for lt in tangents]
        if len(tangents) != len(states):
            raise Refusal("lane-shape", f"{len(tangents)} lanes of tangents "
                          f"for {len(states)} lanes of state")
        for k, lt in enumerate(tangents):
            if len(lt) != T:
                raise Refusal("lane-shape", f"lane {k} holds {len(lt)} "
                              f"tangent vectors; {graph.system} has {T} "
                              f"({vecs})")
            for vec, t in zip(graph.tangent, lt):
                if len(t) != n:
                    raise Refusal("lane-shape", f"lane {k}'s tangent {vec} "
                                  f"holds {len(t)} values; the state has {n}")
                for v in t:
                    if not isinstance(v, int) or isinstance(v, bool) \
                            or not 0 <= v < top:
                        raise Refusal("lane-value", f"lane {k}'s tangent "
                                      f"value {C.shown(v)} is not a "
                                      f"{C.FORMAT_754[fmt.name]} encoding")
    names = [p[0] for p in graph.param]
    pbits = [p[2] for p in graph.param]
    both = sorted(set(params or {}) & set(param_bits or {}))
    if both:
        raise Refusal("param-value", f"{both[0]} is given both as a value "
                      f"and as an encoding; a run gives each param once")
    for name, value in (params or {}).items():
        if name not in names:
            raise Refusal("unknown-param", f"{name} is not a param of "
                          f"{graph.system}")
        pbits[names.index(name)] = _round_run(graph, name,
                                              _exact_run_value(name, value))
    for name, value in (param_bits or {}).items():
        if name not in names:
            raise Refusal("unknown-param", f"{name} is not a param of "
                          f"{graph.system}")
        if not isinstance(value, int) or isinstance(value, bool) \
                or not 0 <= value < top:
            raise Refusal("param-value", f"{name}'s encoding "
                          f"{C.shown(value)} does not fit "
                          f"{C.FORMAT_754[fmt.name]}")
        pbits[names.index(name)] = value
    cbits = [c[2] for c in graph.const]
    if h is not None:
        if graph.integrator[1] is None:
            raise Refusal("unknown-param", f"{graph.system} declares no h to "
                          f"replace")
        hv = _exact_run_value("h", h)
        if hv == 0:
            raise Refusal("step-size-zero", "h is exactly zero")
        h0 = graph.integrator[1]
        if (hv < 0) != (h0 < 0):
            # Every constant is c x h^d with c fixed by h's sign alone,
            # so a run at an h of the graph's sign is the graph compiled
            # at that h, with its h-scaled constants recomputed. Across
            # the sign it is not: copysign(1, h), abs(h)/h and abs(h)
            # were folded at the graph's h (verifier-VL1: 0.875 here
            # where compiling at -1/8 gave 1.125).
            raise Refusal("step-size-sign", f"h = {C.brief(hv)} and the "
                          f"graph was compiled at h = {C.brief(h0)}: a run "
                          f"may give h another value of the same sign, and "
                          f"not of the other, since a constant may hold h's "
                          f"sign (copysign(1, h), abs(h)) as it was when "
                          f"compiled; compile the system at this h")
        for k, (_v, factor, _b, _f) in enumerate(graph.const):
            if factor is not None:
                cbits[k] = _round_run(graph, f"{C.h_form(factor)}",
                                      factor * hv)

    # the program: every node's function and the slots it reads. The
    # tangent's, after the primal's nodes: its inputs, then its nodes;
    # its nN reads the primal node N of this step, its tN the vector's
    # component N, its dN its own node N.
    fns = _ops(fmt, rnd)
    base = {"s": 0, "l": n, "p": n + m, "c": n + m + len(pbits)}
    nbase = base["c"] + len(cbits)
    tbase = nbase + len(graph.step.nodes)
    dbase = tbase + n

    def slot(ref):
        kind, i = ref[0], int(ref[1:])
        return nbase + i if kind == "n" else base[kind] + i

    def tslot(ref):
        kind, i = ref[0], int(ref[1:])
        if kind == "t":
            return tbase + i
        if kind == "d":
            return dbase + i
        return slot(ref)
    prog = [(fns[op], tuple(slot(a) for a in args))
            for op, args, _label in graph.step.nodes]
    outs = [slot(o) for o in graph.step.out]
    tprog, touts = [], []
    if T:
        tprog = [(fns[op], tuple(tslot(a) for a in args))
                 for op, args, _label in graph.tangent_step.nodes]
        touts = [tslot(o) for o in graph.tangent_step.out]
    size = dbase + len(tprog)

    def execute(code, v, k):
        fl_all = 0
        for fn, args in code:
            if len(args) == 2:
                res, fl = fn(v[args[0]], v[args[1]])
            elif len(args) == 3:
                res, fl = fn(v[args[0]], v[args[1]], v[args[2]])
            else:
                res, fl = fn(v[args[0]])
            v[k] = res
            fl_all |= fl
            k += 1
        return fl_all

    flags = pflags = 0
    final, final_t = [], []
    at_states = {s: [] for s in marks}
    at_flags = {s: 0 for s in marks}
    at_t = {s: [] for s in marks}
    for li, st in enumerate(states):
        v = [0] * size
        v[0:n] = st
        v[n:n + m] = lane_params[li]
        v[n + m:n + m + len(pbits)] = pbits
        v[base["c"]:nbase] = cbits
        cur = [list(t) for t in tangents[li]] if T else []
        lane_flags = lane_pflags = 0
        if 0 in at_states:
            at_states[0].append(list(st))
            at_t[0].append([list(t) for t in cur])
        for step in range(1, steps + 1):
            lane_pflags |= execute(prog, v, nbase)
            nxt = [v[o] for o in outs]
            # each vector's tangent reads this step's primal values - the
            # state the step began from and its nodes - so the state moves
            # only once every vector is through
            for k in range(T):
                v[tbase:tbase + n] = cur[k]
                lane_flags |= execute(tprog, v, dbase)
                cur[k] = [v[o] for o in touts]
            v[0:n] = nxt
            if step in at_states:
                at_states[step].append(v[0:n])
                at_flags[step] |= lane_flags | lane_pflags
                at_t[step].append([list(t) for t in cur])
        final.append(v[0:n])
        final_t.append(cur)
        flags |= lane_flags | lane_pflags
        pflags |= lane_pflags
    at_all = {s: (at_states[s], at_flags[s]) for s in marks}
    if not T:
        return Run(final, flags, at_all)
    return Run(final, flags, at_all, final_t, pflags,
               {s: at_t[s] for s in marks})
