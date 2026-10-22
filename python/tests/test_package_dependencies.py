# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The package declares what it imports (KL-611).

python/pyproject.toml said `dependencies = []` and named mpmath only in
the test extra, though cft_golden/mathlib.py imports mpmath at module
level and the model's exact evaluation needs it: `pip install python/`
gave a package whose math library could not be imported.

This reads every import of the packaged directories (the
`[tool.setuptools.packages.find]` include list, so a package added there
is read too), at any depth - a function's lazy `import mpmath` is an
import - and holds each module that is neither the standard library nor
the package itself to the `dependencies` list, with a version floor.
It reads pyproject.toml without tomllib, which is 3.11 and later where
the package supports 3.10; the file is simple, and a layout the reader
cannot parse fails the test rather than passing it.
"""

import ast
import re
import sys
from pathlib import Path

import pytest

PYTHON = Path(__file__).resolve().parents[1]
ROOT = PYTHON.parent
PYPROJECT = PYTHON / "pyproject.toml"

# An import name that is not its distribution's name. Empty today: mpmath
# and gmpy2 are both. A package that is named differently goes here, once,
# with the reason, rather than being waved through by the test.
DISTRIBUTION = {}

# An import that is no distribution at all but a script of this tree, which
# the importing function puts on sys.path itself from the source checkout
# (cft_golden/vectors.py, _reduction_worst_cases). It is not installed with
# the package, so a non-editable install cannot make those vectors; that is
# the tree's layout and not a dependency to declare. Named here with its
# file, and the file must exist.
IN_TREE = {"pi_worstcase": "host/tools/pi_worstcase.py"}


def _table(text, header):
    """The text of the [header] table: from its line to the next table's."""
    m = re.search(r"^\[%s\]\s*$(.*?)(?=^\[|\Z)" % re.escape(header), text,
                  re.S | re.M)
    assert m, f"pyproject.toml has no [{header}] table"
    return m.group(1)


def _strings(text, key):
    """The strings of `key = [ ... ]` in a table's text."""
    m = re.search(r"^%s\s*=\s*\[(.*?)\]" % re.escape(key), text, re.S | re.M)
    assert m, f"no `{key} = [...]` in the table"
    body = re.sub(r"#[^\n]*", "", m.group(1))          # a comment in the array
    return re.findall(r'"([^"]*)"', body)


def _name(requirement):
    """A requirement's distribution name, normalised (PEP 503)."""
    return re.sub(r"[-_.]+", "-",
                  re.split(r"[<>=!~;\[ ]", requirement.strip(),
                           maxsplit=1)[0]).lower()


@pytest.fixture(scope="module")
def pyproject():
    return PYPROJECT.read_text(encoding="utf-8")


def _packaged(pyproject_text):
    include = _strings(_table(pyproject_text, "tool.setuptools.packages.find"),
                       "include")
    assert include, "no package is included"
    return sorted(i.rstrip("*") for i in include)


def _third_party_imports(packages):
    """{import name: [path:line, ...]} over every .py of the packages."""
    own = set(packages)
    found = {}
    for pkg in packages:
        for path in sorted((PYTHON / pkg).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module]
                else:
                    continue
                for dotted in names:
                    top = dotted.split(".")[0]
                    if top not in sys.stdlib_module_names and top not in own:
                        where = f"{path.relative_to(PYTHON).as_posix()}:{node.lineno}"
                        found.setdefault(top, []).append(where)
    return found


def test_the_reader_finds_what_it_reads(pyproject):
    """A reader that found nothing would let every test below pass."""
    assert _packaged(pyproject) == ["cft_golden", "cftc"]
    assert _strings(_table(pyproject, "project"), "dependencies")
    assert _strings(_table(pyproject, "project.optional-dependencies"), "test")


def test_every_third_party_import_of_the_package_is_a_declared_dependency(
        pyproject):
    deps = {_name(d) for d in
            _strings(_table(pyproject, "project"), "dependencies")}
    found = _third_party_imports(_packaged(pyproject))
    assert "mpmath" in found, "the scan did not see mathlib.py's import"
    undeclared = {
        mod: where for mod, where in found.items()
        if mod not in IN_TREE
        and _name(DISTRIBUTION.get(mod, mod)) not in deps}
    assert not undeclared, (
        "imported by the package and not in pyproject.toml's `dependencies` "
        "(declare it with a floor, or name its distribution in DISTRIBUTION): "
        + "; ".join(f"{m} at {w[0]}" + (f" and {len(w) - 1} more" if len(w) > 1
                                          else "")
                    for m, w in sorted(undeclared.items())))


def test_an_in_tree_import_is_a_script_of_the_tree_that_is_there(pyproject):
    found = _third_party_imports(_packaged(pyproject))
    for mod, path in IN_TREE.items():
        assert mod in found, f"{mod} is no longer imported: drop it from IN_TREE"
        assert (ROOT / path).is_file(), path


def test_every_dependency_carries_a_version_floor(pyproject):
    for req in _strings(_table(pyproject, "project"), "dependencies"):
        assert re.fullmatch(r"[A-Za-z0-9_.\-]+\s*>=\s*\d+(\.\d+)*", req), (
            f"{req!r}: a dependency is declared with a floor, name>=X.Y, "
            f"that the tree's records support")


def test_mpmath_has_the_same_floor_in_the_testbench_requirements(pyproject):
    """tb/requirements.txt declares mpmath too, for the testbenches; two
    floors for one library that disagree would be two claims."""
    def floor(requirements):
        for r in requirements:
            if _name(r) == "mpmath":
                return re.search(r">=\s*([\d.]+)", r).group(1)
    ours = floor(_strings(_table(pyproject, "project"), "dependencies"))
    tb = floor(line.strip() for line in
               (ROOT / "tb" / "requirements.txt")
               .read_text(encoding="utf-8").splitlines()
               if line.strip() and not line.lstrip().startswith("#"))
    assert ours and ours == tb, (ours, tb)
