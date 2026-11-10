"""Import direction of the jarvis package (docs/ARCHITECTURE.md): app -> commands -> core <- adapters."""
import ast
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parent.parent / "src" / "jarvis"
FORBIDDEN = {
    "core": {"adapters", "commands", "app"},
    "adapters": {"commands", "app"},
    "commands": {"adapters", "app"},
    "app": set(),
}


def jarvis_imports(path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
        for n in names:
            if n.startswith("jarvis."): yield n.split(".")[1]


@pytest.mark.parametrize("layer", sorted(FORBIDDEN))
def test_layer_imports_point_inward(layer):
    bad = {(p.name, dep) for p in (PKG / layer).glob("*.py") for dep in jarvis_imports(p) if dep in FORBIDDEN[layer]}
    assert bad == set()


def test_no_module_level_mutable_singletons_in_app():
    """The composition root owns instances; app modules hold classes, functions and constants only."""
    for p in (PKG / "app").glob("*.py"):
        for node in ast.parse(p.read_text(encoding="utf-8")).body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Call):
                fn = node.value.func
                name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
                assert name in {"getLogger", "frozenset", "dict"}, f"{p.name}: module-level {name}()"


def test_architecture_lists_every_module():
    doc = (PKG.parent.parent / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    flat = {f"`{p.name}`" for p in PKG.parent.glob("*.py")}
    pkg = {f"`jarvis/{p.parent.name}/{p.name}`" for p in PKG.glob("*/*.py") if p.name != "__init__.py"}
    assert {m for m in flat | pkg if m not in doc} == set()


def test_no_global_statements_in_the_package():
    """State lives in objects the composition root builds, never in rebound module globals."""
    bad = [(p.relative_to(PKG).as_posix(), n.lineno) for p in PKG.rglob("*.py")
           for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))) if isinstance(n, ast.Global)]
    assert bad == []


def test_src_keeps_only_the_entry_points():
    """Everything else lives in the layered package; these three are called by name from outside."""
    assert sorted(p.name for p in PKG.parent.glob("*.py")) == ["fatsecret_call.py", "jarvis_supervisor.py", "jarvis_voice.py"]
