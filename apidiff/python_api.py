"""Public Python API surface from source or ``.pyi`` stubs, via the stdlib ``ast`` (no import, no execution).

Public = not underscore-prefixed, and listed in ``__all__`` when the module defines one.
"""

from __future__ import annotations

import ast
from pathlib import Path

from apidiff.model import ApiSurface, ApiSymbol, Param, SymbolKind


def _ann(node: ast.AST | None) -> str | None:
    return ast.unparse(node) if node is not None else None


def _is_deprecated(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> bool:
    for d in node.decorator_list:
        text = ast.unparse(d)
        if "deprecated" in text.lower():
            return True
    doc = ast.get_docstring(node) or ""
    return ".. deprecated" in doc or doc.lower().startswith("deprecated")


def _params(fn: ast.FunctionDef | ast.AsyncFunctionDef, *, method: bool) -> list[Param]:
    a = fn.args
    positional = [*a.posonlyargs, *a.args]
    if method and positional and positional[0].arg in ("self", "cls"):
        positional = positional[1:]
    n_defaults = len(a.defaults)
    out: list[Param] = []
    for i, arg in enumerate(positional):
        has_default = i >= len(positional) - n_defaults
        out.append(Param(arg.arg, not has_default, _ann(arg.annotation)))
    for arg, default in zip(a.kwonlyargs, a.kw_defaults, strict=True):
        out.append(Param(arg.arg, default is None, _ann(arg.annotation), "keyword"))
    if a.vararg:
        out.append(Param("*" + a.vararg.arg, False, _ann(a.vararg.annotation)))
    if a.kwarg:
        out.append(Param("**" + a.kwarg.arg, False, _ann(a.kwarg.annotation)))
    return out


def _sig(name: str, params: list[Param], returns: str | None) -> str:
    ps = ", ".join(f"{p.name}{': ' + p.type if p.type else ''}{'' if p.required else '=...'}" for p in params)
    return f"{name}({ps})" + (f" -> {returns}" if returns else "")


def _module_all(tree: ast.Module) -> set[str] | None:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            try:
                return set(ast.literal_eval(node.value))
            except (ValueError, SyntaxError):
                return None
    return None


def extract_python_module(source: str, module: str, surface: ApiSurface | None = None) -> ApiSurface:
    surface = surface or ApiSurface("python")
    tree = ast.parse(source)
    exported = _module_all(tree)

    def public(name: str) -> bool:
        return not name.startswith("_") and (exported is None or name in exported)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and public(node.name):
            ps, ret = _params(node, method=False), _ann(node.returns)
            surface.add(ApiSymbol(f"{module}.{node.name}", SymbolKind.FUNCTION, node.name, ps, ret,
                                  _is_deprecated(node), _sig(f"{module}.{node.name}", ps, ret)))
        elif isinstance(node, ast.ClassDef) and public(node.name):
            cid = f"{module}.{node.name}"
            fields: dict[str, str] = {}
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    is_init = item.name == "__init__"
                    if item.name.startswith("_") and not is_init:
                        continue
                    ps, ret = _params(item, method=True), _ann(item.returns)
                    mid = f"{cid}.{item.name}"
                    surface.add(ApiSymbol(mid, SymbolKind.METHOD, item.name, ps, ret, _is_deprecated(item),
                                          _sig(mid, ps, ret)))
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    if not item.target.id.startswith("_"):
                        fields[item.target.id] = _ann(item.annotation) or "any"
            surface.add(ApiSymbol(cid, SymbolKind.CLASS, node.name, deprecated=_is_deprecated(node),
                                  signature=f"class {cid}", fields=fields))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and public(node.target.id):
            surface.add(ApiSymbol(f"{module}.{node.target.id}", SymbolKind.CONSTANT, node.target.id,
                                  returns=_ann(node.annotation), signature=f"{module}.{node.target.id}"))
    return surface


def extract_python_package(root: str | Path, package: str | None = None) -> ApiSurface:
    """Walk a package directory; ``.pyi`` stubs win over ``.py`` for the same module."""
    root = Path(root)
    package = package or root.name
    surface = ApiSurface("python")
    files: dict[str, Path] = {}
    for f in sorted(root.rglob("*.py*")):
        if f.suffix not in (".py", ".pyi") or any(p.startswith(("_", ".")) and p != "__init__.py" and
                                                  p != "__init__.pyi" for p in f.relative_to(root).parts):
            continue
        rel = f.relative_to(root).with_suffix("")
        parts = [package, *rel.parts]
        if parts[-1] == "__init__":
            parts = parts[:-1]
        mod = ".".join(parts)
        if mod not in files or f.suffix == ".pyi":
            files[mod] = f
    for mod, f in files.items():
        try:
            extract_python_module(f.read_text(encoding="utf-8"), mod, surface)
        except SyntaxError:
            continue
    return surface
