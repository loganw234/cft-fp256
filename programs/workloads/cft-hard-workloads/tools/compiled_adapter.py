"""The hard-workload adapter: compiled images run on seq.py.

Based on the working adapter in the user's returned result archive.
Two compiled segment lengths are cached per graph; each execution starts
from the states and bank supplied in its request.

- load_source, read_graph, graph_bytes and refusal_name are the golden
  adapter's: the compiler reads no source or graph bytes of its own; it
  takes the language's checked step graph (cftc.compile_graph).
- run(graph, request):
  - it compiles the graph with cftc.compile_graph at S = the request's
    steps, on CFT_TARGET (default sw);
  - the request's params go in through the compiler's own run-value path
    (`--param`'s);
  - its param_bits and h are written into the bank the image runs with.
    A param's slot takes the raw encoding. An h-scaled slot takes
    RN(factor x h), and its flip slot takes the sign-flipped value, which
    is the bank of the graph compiled at that h;
  - the image runs once, on seq.py, with every lane active, one segment of
    S steps;
  - each lane's state is read back from scratch-out, and FLAGS are
    seq.py's sticky OR;
  - a nonzero sequencer status, or a lane param changed by the run, is
    raised as an error.
- The run's input checks are lang.run's, at zero steps, before anything is
  compiled. The image has no run-input API of its own in Python, so the
  suite's run-refusal vectors test the interpreter's front here, not the
  image.

The checkout is the one named by CFT_REPO (its python/ is put on the path).
"""
import os
import sys
from collections import OrderedDict
from pathlib import Path

REPO = Path(os.environ["CFT_REPO"]).resolve()
sys.path.insert(0, str(REPO / "python"))

import cftc  # noqa: E402
from cft_golden import lang  # noqa: E402
from cft_golden.lang import constants as K  # noqa: E402
from cft_golden.lang.check import constant_of  # noqa: E402

TARGET = os.environ.get("CFT_TARGET", "sw")
BACKEND = f"compiled image on seq.py (cftc.compile_graph, target {TARGET})"
_cache_graph = None
_cache = OrderedDict()


def clear_cache():
    global _cache_graph
    _cache_graph = None
    _cache.clear()


def _compile(graph, steps, params):
    """Two segment lengths at most; reuse lowering for repeated long chunks."""
    global _cache_graph
    if graph is not _cache_graph:
        clear_cache()
        _cache_graph = graph
    key = (steps, tuple(sorted((k, repr(v)) for k,v in (params or {}).items())))
    if key not in _cache:
        _cache[key] = cftc.compile_graph(graph, steps, TARGET, stem=graph.system, params=params)
        if len(_cache) > 2:
            _cache.popitem(last=False)
    _cache.move_to_end(key)
    return _cache[key]


def _bits(v):
    if isinstance(v, str) and v.lower().startswith("0x"):
        return int(v, 16)
    return v


def _lanes(rows):
    return None if rows is None else [[_bits(x) for x in lane] for lane in rows]


def _hex(v, width):
    return "0x" + format(v, "0%dx" % (width // 4))


def _whole(n):
    return isinstance(n, int) and not isinstance(n, bool) and n >= 0


def load_source(path):
    return lang.load(Path(path)).graph


def run(graph, request):
    states = _lanes(request["states"])
    lanes = _lanes(request.get("lane_params"))
    params = request.get("params")
    raw = request.get("param_bits")
    pbits = None if raw is None else {k: _bits(v) for k, v in raw.items()}
    h = request.get("h")
    steps = request["steps"]
    # The interpreter's input checks, with no step taken.
    lang.run(graph, states, 0 if _whole(steps) else steps, lane_params=lanes,
             params=params, param_bits=pbits, h=h)
    w = graph.fmt.width
    if steps == 0:
        return {"states": [[_hex(v, w) for v in lane] for lane in states],
                "flags": 0}
    c = _compile(graph, steps, params)
    low = c.lowered
    vals = list(low.bank_values())
    sign = 1 << (w - 1)
    for name, b in (pbits or {}).items():
        k = next(k for k, s in enumerate(low.slots) if s.kind == "param"
                 and c.ir.param[s.index][0] == name)
        vals[k] = b
    if h is not None:
        hv = constant_of(h)
        for k, s in enumerate(low.slots):
            if s.kind not in ("const", "flip"):
                continue
            factor = c.ir.const[s.index][1]
            if factor is None:
                continue
            b = K.round_once(graph.fmt, graph.rnd, factor * hv)[0]
            vals[k] = b ^ sign if s.kind == "flip" else b
    r = c.run(states, lanes, bank=vals)
    if r.status != 0:
        raise RuntimeError(f"seq.py status {r.status:#x}")
    n, m = graph.n_state, graph.n_state + len(graph.lane)
    lp = lanes if lanes is not None else \
        [[b for _n, _d, b in graph.lane] for _ in states]
    out = []
    for k in range(len(states)):
        block = r.scratch_out[k * m:(k + 1) * m]
        if block[n:] != list(lp[k]):
            raise RuntimeError(f"lane {k}'s lane params changed in the run")
        out.append([_hex(v, w) for v in block[:n]])
    return {"states": out, "flags": r.flags}


def read_graph(data):
    return lang.StepGraph.from_bytes(data)


def graph_bytes(graph):
    return graph.to_bytes()


def refusal_name(exc):
    return exc.name if isinstance(exc, lang.Refusal) else None
