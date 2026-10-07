"""OpenAPI 3.x (and Swagger 2.0, best effort) surface extraction.

Operations become OPERATION symbols keyed by ``METHOD /path`` (path params normalised to ``{}`` so a
renamed path variable is not a removal). Component schemas become TYPE symbols with their properties.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from services.apidiff.model import ApiSurface, ApiSymbol, Param, SymbolKind

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


def load_spec(source: str | Path | dict) -> dict[str, Any]:
    """Accept a parsed dict, a file path, or the spec text itself (JSON or YAML)."""
    if isinstance(source, dict):
        return source
    if isinstance(source, Path) or ("\n" not in source and Path(source).is_file()):
        text = Path(source).read_text(encoding="utf-8")
    else:
        text = source
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return yaml.safe_load(text)


def _resolve(spec: dict, node: Any, depth: int = 0) -> Any:
    if depth > 20 or not isinstance(node, dict) or "$ref" not in node:
        return node
    ref = node["$ref"]
    if not ref.startswith("#/"):
        return node  # external refs not followed
    target: Any = spec
    for part in ref[2:].split("/"):
        target = target.get(part.replace("~1", "/").replace("~0", "~"), {}) if isinstance(target, dict) else {}
    return _resolve(spec, target, depth + 1)


def _type_of(spec: dict, schema: Any) -> str:
    if not isinstance(schema, dict):
        return "any"
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    schema = _resolve(spec, schema)
    for key in ("oneOf", "anyOf", "allOf"):
        if key in schema:
            sep = " & " if key == "allOf" else " | "
            return sep.join(sorted(_type_of(spec, s) for s in schema[key]))
    t = schema.get("type", "object")
    if isinstance(t, list):
        t = "|".join(sorted(str(x) for x in t))
    if t == "array":
        return f"{_type_of(spec, schema.get('items', {}))}[]"
    if "enum" in schema:
        return f"{t}({'|'.join(sorted(map(str, schema['enum'])))})"
    return str(t)


def _norm_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def extract_openapi(source: str | Path | dict) -> ApiSurface:
    spec = load_spec(source)
    surface = ApiSurface("openapi")
    for path, item in (spec.get("paths") or {}).items():
        item = _resolve(spec, item)
        shared = item.get("parameters", [])
        for method in HTTP_METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            params: list[Param] = []
            for p in [*shared, *op.get("parameters", [])]:
                p = _resolve(spec, p)
                if not isinstance(p, dict) or "name" not in p:
                    continue
                schema = p.get("schema", p)
                params.append(Param(p["name"], bool(p.get("required") or p.get("in") == "path"),
                                    _type_of(spec, schema), p.get("in")))
            body = _resolve(spec, op.get("requestBody") or {})
            for media in (body.get("content") or {}).values():
                bschema = _resolve(spec, media.get("schema") or {})
                req = set(bschema.get("required", []))
                for name, prop in (bschema.get("properties") or {}).items():
                    params.append(Param(name, name in req, _type_of(spec, prop), "body"))
                break  # first media type is representative
            ok = next((r for code, r in (op.get("responses") or {}).items() if str(code).startswith("2")), None)
            returns = None
            if isinstance(ok, dict):
                ok = _resolve(spec, ok)
                for media in (ok.get("content") or {}).values():
                    returns = _type_of(spec, media.get("schema") or {})
                    break
            key = f"{method.upper()} {_norm_path(path)}"
            surface.add(ApiSymbol(
                id=key,
                kind=SymbolKind.OPERATION,
                name=op.get("operationId") or key,
                params=params,
                returns=returns,
                deprecated=bool(op.get("deprecated")),
                signature=f"{method.upper()} {path}" + (f" ({op['operationId']})" if op.get("operationId") else ""),
            ))
    schemas = (spec.get("components") or {}).get("schemas") or spec.get("definitions") or {}
    for name, schema in schemas.items():
        schema = _resolve(spec, schema)
        props = schema.get("properties") or {}
        surface.add(ApiSymbol(
            id=f"schema:{name}",
            kind=SymbolKind.TYPE,
            name=name,
            deprecated=bool(schema.get("deprecated")),
            signature=f"schema {name}",
            fields={k: _type_of(spec, v) for k, v in props.items()},
            required_fields=set(schema.get("required", [])),
        ))
    return surface
