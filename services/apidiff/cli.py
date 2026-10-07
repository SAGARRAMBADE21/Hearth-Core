"""``hearth-apidiff OLD NEW [--lang openapi|python|typescript] [--json]``"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from services.apidiff.engine import diff_surfaces, extract_surface


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="hearth-apidiff", description="Diff two API surfaces.")
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--lang", choices=["openapi", "python", "typescript"])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--breaking-only", action="store_true")
    args = ap.parse_args(argv)

    changes = diff_surfaces(extract_surface(args.old, args.lang), extract_surface(args.new, args.lang))
    if args.breaking_only:
        changes = [c for c in changes if c.breaking]
    if args.json:
        json.dump([{**asdict(c), "breaking": c.breaking} for c in changes], sys.stdout, indent=2, default=str)
        print()
    else:
        for c in changes:
            print(f"{'BREAKING' if c.breaking else 'info    '}  {c.describe()}")
    return 1 if any(c.breaking for c in changes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
