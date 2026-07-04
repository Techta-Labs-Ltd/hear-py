from __future__ import annotations

import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def modpath(name: str) -> str | None:
    p = os.path.join(ROOT, *name.split(".")) + ".py"
    if os.path.exists(p):
        return p
    p2 = os.path.join(ROOT, *name.split("."), "__init__.py")
    return p2 if os.path.exists(p2) else None


def exported_names(path: str) -> set[str]:
    tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    names: set[str] = set()
    for s in tree.body:
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(s.name)
        elif isinstance(s, ast.Assign):
            for t in s.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name):
            names.add(s.target.id)
        elif isinstance(s, ast.ImportFrom):
            for a in s.names:
                names.add(a.asname or a.name)
        elif isinstance(s, ast.Import):
            for a in s.names:
                names.add((a.asname or a.name).split(".")[0])
    return names


def main():
    problems = []
    for base in ("src", "config"):
        for dp, _d, fs in os.walk(os.path.join(ROOT, base)):
            if "__pycache__" in dp:
                continue
            for f in fs:
                if not f.endswith(".py"):
                    continue
                path = os.path.join(dp, f)
                rel = os.path.relpath(path, ROOT)
                tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and not node.level and node.module \
                            and node.module.split(".")[0] in ("src", "config"):
                        tgt = modpath(node.module)
                        if not tgt:
                            problems.append((rel, node.lineno, node.module, "<module missing>"))
                            continue
                        exp = exported_names(tgt)
                        for a in node.names:
                            if a.name != "*" and a.name not in exp:
                                problems.append((rel, node.lineno, node.module, a.name))
    for rel, ln, mod, name in sorted(problems):
        print(f"{rel}:{ln}  {mod} -> {name}")
    print(f"\nTOTAL unresolved imports: {len(problems)}")


if __name__ == "__main__":
    main()
