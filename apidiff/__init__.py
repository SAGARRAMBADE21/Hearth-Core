"""API diff engine: extract a surface from two versions, diff it, fold it into a Change Record."""

from apidiff.engine import diff_surfaces, extract_surface, to_change_record
from apidiff.model import ApiChange, ApiSurface, ApiSymbol, ChangeType, Param, SymbolKind
from apidiff.openapi import extract_openapi
from apidiff.python_api import extract_python_module, extract_python_package
from apidiff.typescript_api import extract_typescript, extract_typescript_dir

__all__ = [
    "ApiChange",
    "ApiSurface",
    "ApiSymbol",
    "ChangeType",
    "Param",
    "SymbolKind",
    "diff_surfaces",
    "extract_openapi",
    "extract_python_module",
    "extract_python_package",
    "extract_surface",
    "extract_typescript",
    "extract_typescript_dir",
    "to_change_record",
]
