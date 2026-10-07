"""TypeScript declaration (``.d.ts``) surface extraction.

This is a lightweight, dependency-free scanner for the declaration shapes SDKs ship most often:
``export (declare) function``, ``export (declare) class`` with method/property members,
``export interface``, ``export type`` and ``export (declare) const``. It tracks brace depth instead of
parsing fully, so exotic declarations (overload-heavy generics, declaration merging across files) can be
missed; every symbol it emits is tagged ``confidence`` < 1 by the engine. Swap in tree-sitter-typescript
behind the same ``extract_typescript`` signature when precision matters (TDD §2: tree-sitter).
"""

from __future__ import annotations

import re
from pathlib import Path

from apidiff.model import ApiSurface, ApiSymbol, Param, SymbolKind

_COMMENT_RE = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
_DEPRECATED_RE = re.compile(r"/\*\*(?:(?!\*/).)*@deprecated(?:(?!\*/).)*\*/\s*$", re.S)

_FN_RE = re.compile(r"export\s+(?:declare\s+)?(?:async\s+)?function\s+(\w+)\s*(<[^>]*>)?\s*\(")
_CLASS_RE = re.compile(r"export\s+(?:declare\s+)?(?:abstract\s+)?class\s+(\w+)[^{]*\{")
_IFACE_RE = re.compile(r"export\s+(?:declare\s+)?interface\s+(\w+)[^{]*\{")
_TYPE_RE = re.compile(r"export\s+(?:declare\s+)?type\s+(\w+)(?:<[^=]*>)?\s*=\s*")
_CONST_RE = re.compile(r"export\s+(?:declare\s+)?(?:const|let|var)\s+(\w+)\s*:\s*([^;=]+)")
_MEMBER_METHOD_RE = re.compile(r"^\s*(?:public\s+|static\s+|readonly\s+|abstract\s+)*(\w+)\s*(\??)\s*(<[^>]*>)?\s*\(")
_MEMBER_PROP_RE = re.compile(r"^\s*(?:public\s+|static\s+|readonly\s+)*(\w+)\s*(\??)\s*:\s*(.+?);?\s*$")


def _match_close(text: str, start: int, open_ch: str, close_ch: str) -> int:
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i
    return len(text) - 1


def _split_top(s: str, sep: str = ",") -> list[str]:
    out, depth, cur = [], 0, []
    for c in s:
        if c in "<({[":
            depth += 1
        elif c in ">)}]":
            depth -= 1
        if c == sep and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(c)
    if "".join(cur).strip():
        out.append("".join(cur))
    return out


def _parse_params(s: str) -> list[Param]:
    params = []
    for raw in _split_top(s):
        raw = raw.strip()
        if not raw:
            continue
        name, _, typ = raw.partition(":")
        name = name.strip()
        optional = name.endswith("?") or "=" in name
        name = name.rstrip("?").split("=")[0].strip()
        if name.startswith("..."):
            optional = True
        params.append(Param(name, not optional, typ.strip() or None))
    return params


def _deprecated_before(text: str, pos: int) -> bool:
    return bool(_DEPRECATED_RE.search(text[max(0, pos - 600):pos]))


def _members(body: str) -> list[tuple[str, str]]:
    """Split a class/interface body into top-level member declarations."""
    out, depth, cur = [], 0, []
    for c in body:
        if c in "{(<[":
            depth += 1
        elif c in "})>]":
            depth -= 1
        if c in ";\n" and depth == 0:
            line = "".join(cur).strip()
            if line:
                out.append(line)
            cur = []
        else:
            cur.append(c)
    if "".join(cur).strip():
        out.append("".join(cur).strip())
    return [(m, m) for m in out]


def extract_typescript(source: str, module: str = "", surface: ApiSurface | None = None) -> ApiSurface:
    surface = surface or ApiSurface("typescript")
    prefix = f"{module}." if module else ""
    raw = source
    code = _COMMENT_RE.sub(lambda m: " " * len(m.group(0)), source)  # keep offsets stable

    for m in _FN_RE.finditer(code):
        open_paren = m.end() - 1
        close = _match_close(code, open_paren, "(", ")")
        params = _parse_params(code[open_paren + 1:close])
        rest = code[close + 1:close + 300]
        ret = rest.split(";", 1)[0].lstrip(": ").strip() if rest.lstrip().startswith(":") else None
        sid = prefix + m.group(1)
        sym = surface.symbols.get(sid)
        if sym:  # overload: union of params, a param is required only if required in every overload
            names = {p.name for p in params}
            sym.params = [p if p.name in names else Param(p.name, False, p.type) for p in sym.params]
            continue
        surface.add(ApiSymbol(sid, SymbolKind.FUNCTION, m.group(1), params, ret, _deprecated_before(raw, m.start()),
                              f"function {sid}({code[open_paren + 1:close].strip()})"))

    for regex, kind in ((_CLASS_RE, SymbolKind.CLASS), (_IFACE_RE, SymbolKind.TYPE)):
        for m in regex.finditer(code):
            name = m.group(1)
            brace = m.end() - 1
            close = _match_close(code, brace, "{", "}")
            body = code[brace + 1:close]
            fields: dict[str, str] = {}
            required: set[str] = set()
            cid = prefix + name
            for member, _ in _members(body):
                mm = _MEMBER_METHOD_RE.match(member)
                if mm and not member.lstrip().startswith(("private", "protected", "#")):
                    mname = mm.group(1)
                    open_paren = member.index("(", mm.start(1))
                    mclose = _match_close(member, open_paren, "(", ")")
                    params = _parse_params(member[open_paren + 1:mclose])
                    after = member[mclose + 1:].strip()
                    ret = after.lstrip(":").strip().rstrip(";") if after.startswith(":") else None
                    mid = f"{cid}.{mname}"
                    pos = code.find(member, brace)
                    surface.add(ApiSymbol(mid, SymbolKind.METHOD, mname, params, ret,
                                          _deprecated_before(raw, pos) if pos >= 0 else False, f"{mid}(...)"))
                    continue
                pm = _MEMBER_PROP_RE.match(member)
                if pm and not member.lstrip().startswith(("private", "protected", "#")):
                    fields[pm.group(1)] = pm.group(3).strip()
                    if not pm.group(2):
                        required.add(pm.group(1))
            surface.add(ApiSymbol(cid, kind, name, deprecated=_deprecated_before(raw, m.start()),
                                  signature=f"{'class' if kind == SymbolKind.CLASS else 'interface'} {cid}",
                                  fields=fields, required_fields=required))

    for m in _TYPE_RE.finditer(code):
        end = code.find(";", m.end())
        rhs = code[m.end(): end if end > 0 else None].strip()
        surface.add(ApiSymbol(prefix + m.group(1), SymbolKind.TYPE, m.group(1), returns=" ".join(rhs.split()),
                              deprecated=_deprecated_before(raw, m.start()), signature=f"type {prefix}{m.group(1)}"))

    for m in _CONST_RE.finditer(code):
        surface.add(ApiSymbol(prefix + m.group(1), SymbolKind.CONSTANT, m.group(1), returns=m.group(2).strip(),
                              deprecated=_deprecated_before(raw, m.start()), signature=f"const {prefix}{m.group(1)}"))
    return surface


def extract_typescript_dir(root: str | Path) -> ApiSurface:
    root = Path(root)
    surface = ApiSurface("typescript")
    for f in sorted(root.rglob("*.d.ts")):
        if "node_modules" in f.parts:
            continue
        extract_typescript(f.read_text(encoding="utf-8", errors="replace"), "", surface)
    return surface
