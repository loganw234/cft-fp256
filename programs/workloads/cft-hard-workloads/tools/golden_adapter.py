"""The hard-workload adapter for the golden reference interpreter.

Based on the working adapter in the user's returned result archive. This
backend is cft_golden.lang: lang.load reads the source's bytes whole (the
character rule sees a lone CR), lang.run is the reference interpreter, and
StepGraph.from_bytes / to_bytes are the graph's byte reader and writer.

The checkout is the one named by CFT_REPO (its python/ is put on the path).
Request values pass through as the suite gives them, except hex strings,
which become the integers they spell; the interpreter does every check, so
a float, a wrong shape or an out-of-width encoding reaches it as written.
"""
import os
import sys
from pathlib import Path

REPO = Path(os.environ["CFT_REPO"]).resolve()
sys.path.insert(0, str(REPO / "python"))

from cft_golden import lang  # noqa: E402

BACKEND = "golden interpreter (cft_golden.lang.run)"


def _bits(v):
    """A hex spelling to its integer; anything else exactly as given."""
    if isinstance(v, str) and v.lower().startswith("0x"):
        return int(v, 16)
    return v


def _lanes(rows):
    return None if rows is None else [[_bits(x) for x in lane] for lane in rows]


def _hex(v, width):
    return "0x" + format(v, "0%dx" % (width // 4))


def load_source(path):
    return lang.load(Path(path)).graph


def run(graph, request):
    bits = request.get("param_bits")
    r = lang.run(graph, _lanes(request["states"]), request["steps"],
                 lane_params=_lanes(request.get("lane_params")),
                 params=request.get("params"),
                 param_bits=None if bits is None else
                 {k: _bits(v) for k, v in bits.items()},
                 h=request.get("h"))
    w = graph.fmt.width
    return {"states": [[_hex(v, w) for v in lane] for lane in r.states],
            "flags": r.flags}


def read_graph(data):
    return lang.StepGraph.from_bytes(data)


def graph_bytes(graph):
    return graph.to_bytes()


def refusal_name(exc):
    return exc.name if isinstance(exc, lang.Refusal) else None
