"""vectors.py with every list append tagged by its source line.

Imported by audit_table.py.  It re-executes python/cft_golden/vectors.py
with every list append tagged by the source line that built it, so that the
operands the vector generator directs at a function can be grouped by the
line of the generator that directs them (the random ones are neutralised).
"""
import ast, collections, sys, types
import os  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "python"))
import cft_golden
from cft_golden import vectors as V0
from cft_golden import softfloat as sf

TAG = collections.defaultdict(set)

def _tag_append(lst, e, ln):
    lst.append(e)
    if e is not None:
        TAG[e].add(ln)

def _tag_extend(lst, vals, ln):
    for v in vals:
        lst.append(v)
        if v is not None:
            TAG[v].add(ln)

class Tr(ast.NodeTransformer):
    NAMES = ("pairs", "out", "ops", "cases")
    def visit_Expr(self, node):
        self.generic_visit(node)
        c = node.value
        if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                and c.func.attr == "append"
                and isinstance(c.func.value, ast.Name)
                and c.func.value.id in self.NAMES and len(c.args) == 1):
            new = ast.Call(func=ast.Name("_tag_append", ast.Load()),
                           args=[c.func.value, c.args[0], ast.Constant(node.lineno)],
                           keywords=[])
            return ast.copy_location(ast.Expr(new), node)
        return node
    def visit_AugAssign(self, node):
        self.generic_visit(node)
        if (isinstance(node.op, ast.Add) and isinstance(node.target, ast.Name)
                and node.target.id in self.NAMES):
            new = ast.Call(func=ast.Name("_tag_extend", ast.Load()),
                           args=[ast.Name(node.target.id, ast.Load()), node.value,
                                 ast.Constant(node.lineno)], keywords=[])
            return ast.copy_location(ast.Expr(new), node)
        return node

def load():
    src = open(V0.__file__).read()
    tree = Tr().visit(ast.parse(src))
    ast.fix_missing_locations(tree)
    m = types.ModuleType("cft_golden.vectors_t")
    m.__package__ = "cft_golden"
    m.__file__ = V0.__file__
    m._tag_append = _tag_append
    m._tag_extend = _tag_extend
    exec(compile(tree, V0.__file__, "exec"), m.__dict__)
    def tagged_extend(out, *values):
        ln = sys._getframe(1).f_lineno
        for v in values:
            if v is not None:
                out.append(v)
                TAG[v].add(ln)
    m._extend = tagged_extend
    m._rand_bits = lambda rng, fmt: sf.one_bits(fmt)   # randoms are not directed
    return m
