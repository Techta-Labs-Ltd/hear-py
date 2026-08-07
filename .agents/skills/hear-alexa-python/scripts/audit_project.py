#!/usr/bin/env python3
"""Static structural guardrails for the Hear Alexa repository."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

FALLBACKS = {"FallbackHandler", "UnmatchedIntentHandler", "UnknownRequestHandler"}


def dotted(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{dotted(node.value)}.{node.attr}".strip(".")
    return ""


def files(root: Path):
    for base in (root / "main.py", root / "config", root / "src", root / "tests"):
        if base.is_file():
            yield base
        elif base.is_dir():
            yield from sorted(base.rglob("*.py"))


def audit_module(path: Path, root: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        return [f"{path.relative_to(root)}: cannot parse: {exc}"]
    out, seen = [], {}
    for node in tree.body:
        kind = ("function" if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                else "class" if isinstance(node, ast.ClassDef) else None)
        if not kind:
            continue
        key = (kind, node.name)
        if key in seen:
            out.append(f"{path.relative_to(root)}:{node.lineno}: duplicate {kind} "
                       f"{node.name!r}; first at line {seen[key]}")
        seen[key] = node.lineno

    if "src/handlers/" in path.as_posix():
        for node in (n for n in tree.body if isinstance(n, ast.ClassDef)):
            if not node.name.endswith("Handler"):
                continue
            bases = {dotted(base).split(".")[-1] for base in node.bases}
            methods = {n.name for n in node.body
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            accepted_bases = {"AbstractRequestHandler", "AbstractExceptionHandler"}
            if not bases.intersection(accepted_bases):
                out.append(f"{path.relative_to(root)}:{node.lineno}: {node.name} "
                           "must inherit an Alexa request or exception handler base")
            for required in ("can_handle", "handle"):
                if required not in methods:
                    out.append(f"{path.relative_to(root)}:{node.lineno}: {node.name} "
                               f"is missing {required}()")

    if path == root / "main.py":
        forbidden = {"add_request_handler", "add_exception_handler",
                     "add_global_request_interceptor", "add_global_response_interceptor"}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in forbidden):
                out.append(f"main.py:{node.lineno}: register through project registries, "
                           f"not {node.func.attr}()")
    return out


def audit_registry(root: Path) -> list[str]:
    path = root / "src/registry.py"
    if not path.exists():
        return ["src/registry.py: missing"]
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not any(
            isinstance(t, ast.Name) and t.id == "REQUEST_HANDLERS" for t in node.targets
        ) or not isinstance(node.value, (ast.Tuple, ast.List)):
            continue
        names, seen, fallback_seen = [dotted(n) for n in node.value.elts], {}, False
        for position, name in enumerate(names, 1):
            short = name.split(".")[-1]
            if name in seen:
                out.append(f"{path.relative_to(root)}:{node.lineno}: duplicate {name} "
                           f"at positions {seen[name]} and {position}")
            seen[name] = position
            if fallback_seen and short not in FALLBACKS:
                out.append(f"{path.relative_to(root)}:{node.lineno}: {name} is after fallback")
            fallback_seen |= short in FALLBACKS
    return out


def audit_model(root: Path) -> list[str]:
    path = root / "en-GB.json"
    try:
        model = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"en-GB.json: invalid or missing: {exc}"]
    intents = model.get("interactionModel", {}).get("languageModel", {}).get("intents", [])
    names = [item.get("name") for item in intents]
    return [f"en-GB.json: duplicate intent {name!r}"
            for name in sorted({n for n in names if n and names.count(n) > 1})]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".", type=Path)
    root = parser.parse_args().root.resolve()
    findings = [item for path in files(root) for item in audit_module(path, root)]
    findings += audit_registry(root) + audit_model(root)
    if findings:
        print("Hear Alexa audit failed:")
        print("\n".join(f"- {item}" for item in findings))
        return 1
    print("Hear Alexa audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
