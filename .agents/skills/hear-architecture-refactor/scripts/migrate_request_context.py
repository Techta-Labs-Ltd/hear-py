from __future__ import annotations

import argparse
import ast
from pathlib import Path


class RequestContextTransformer(ast.NodeTransformer):
    READ_METHODS = {
        "get_request_attributes": "request",
        "get_session_attributes": "session",
    }
    WRITE_METHODS = {
        "set_request_attributes": "replace_request",
        "set_session_attributes": "replace_session",
    }

    def __init__(self) -> None:
        self.changed = False

    def visit_Call(self, node: ast.Call):
        node = self.generic_visit(node)
        if not isinstance(node.func, ast.Attribute):
            return node
        manager = node.func.value
        owner = self.manager_owner(manager)
        if owner is None:
            return node
        if node.func.attr in self.READ_METHODS:
            self.changed = True
            return ast.copy_location(
                self.context_call(self.READ_METHODS[node.func.attr], [owner]),
                node,
            )
        if node.func.attr in self.WRITE_METHODS:
            self.changed = True
            return ast.copy_location(
                self.context_call(
                    self.WRITE_METHODS[node.func.attr],
                    [owner, *node.args],
                ),
                node,
            )
        return node

    def visit_Attribute(self, node: ast.Attribute):
        node = self.generic_visit(node)
        if node.attr != "request_attributes":
            return node
        owner = self.manager_owner(node.value)
        if owner is None:
            return node
        self.changed = True
        return ast.copy_location(self.context_call("request", [owner]), node)

    @staticmethod
    def manager_owner(node: ast.AST):
        if isinstance(node, ast.Attribute) and node.attr == "attributes_manager":
            return node.value
        return None

    @staticmethod
    def context_call(method: str, arguments: list[ast.AST]) -> ast.Call:
        return ast.Call(
            func=ast.Attribute(
                value=ast.Name(id="RequestContext", ctx=ast.Load()),
                attr=method,
                ctx=ast.Load(),
            ),
            args=arguments,
            keywords=[],
        )


class RequestContextMigration:
    EXCLUDED = {
        "src/alexa/context.py",
        "src/alexa/runtime.py",
        "src/database/persistence.py",
        "src/models/user.py",
    }

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def run(self) -> None:
        for path in sorted((self.root / "src").rglob("*.py")):
            relative = path.relative_to(self.root).as_posix()
            if relative in self.EXCLUDED:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            transformer = RequestContextTransformer()
            tree = transformer.visit(tree)
            if not transformer.changed:
                continue
            self.add_import(tree)
            ast.fix_missing_locations(tree)
            path.write_text(ast.unparse(tree) + "\n", encoding="utf-8")

    @staticmethod
    def add_import(tree: ast.Module) -> None:
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "src.alexa.context":
                if any(alias.name == "RequestContext" for alias in node.names):
                    return
        insertion = 0
        while insertion < len(tree.body) and isinstance(
            tree.body[insertion],
            (ast.Import, ast.ImportFrom),
        ):
            insertion += 1
        tree.body.insert(
            insertion,
            ast.ImportFrom(
                module="src.alexa.context",
                names=[ast.alias(name="RequestContext")],
                level=0,
            ),
        )

    @classmethod
    def main(cls) -> int:
        parser = argparse.ArgumentParser()
        parser.add_argument("root", nargs="?", default=".")
        arguments = parser.parse_args()
        cls(Path(arguments.root)).run()
        return 0


raise SystemExit(RequestContextMigration.main())
