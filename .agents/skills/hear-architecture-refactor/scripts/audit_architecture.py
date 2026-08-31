from __future__ import annotations

import argparse
import ast
import hashlib
import io
import re
import sys
import tokenize
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, order=True)
class Finding:
    severity: str
    rule: str
    path: str
    line: int
    message: str


class AuditPolicy:
    FORBIDDEN_DIRECTORIES = frozenset(
        {
            "actions",
            "adapters",
            "handlers",
            "presenters",
            "repositories",
            "resolver",
            "runtime",
            "webhooks",
        }
    )
    ROOT_FILES = frozenset(
        {"__init__.py", "application.py", "container.py", "registry.py"}
    )
    REQUIRED_CLASSES = {
        "src/application.py": "Application",
        "src/container.py": "ApplicationContainer",
        "src/registry.py": "RouteRegistry",
        "src/models/user.py": "User",
        "src/models/listener.py": "Listener",
        "src/alexa/context.py": "RequestContext",
    }
    STATE_GATEWAYS = frozenset(
        {
            "src/alexa/context.py",
            "src/alexa/runtime.py",
            "src/database/persistence.py",
            "src/models/user.py",
        }
    )
    STATE_METHODS = frozenset(
        {
            "get_request_attributes",
            "set_request_attributes",
            "get_session_attributes",
            "set_session_attributes",
        }
    )
    FORBIDDEN_IMPORTS = {
        "alexa": frozenset(
            {
                "clients",
                "container",
                "controllers",
                "database",
                "dependencies",
                "middleware",
                "models",
                "services",
            }
        ),
        "clients": frozenset(
            {
                "container",
                "controllers",
                "database",
                "dependencies",
                "middleware",
                "models",
            }
        ),
        "constants": frozenset(
            {
                "alexa",
                "clients",
                "container",
                "controllers",
                "database",
                "dependencies",
                "middleware",
                "models",
                "services",
                "utils",
            }
        ),
        "controllers": frozenset(
            {
                "clients",
                "container",
                "database",
                "dependencies",
                "middleware",
                "services",
            }
        ),
        "database": frozenset(
            {
                "alexa",
                "clients",
                "container",
                "controllers",
                "dependencies",
                "middleware",
                "services",
            }
        ),
        "middleware": frozenset(
            {"clients", "container", "controllers", "database", "dependencies"}
        ),
        "models": frozenset(
            {"container", "controllers", "database", "dependencies", "middleware"}
        ),
        "services": frozenset(
            {"container", "controllers", "database", "dependencies", "middleware"}
        ),
        "utils": frozenset(
            {
                "alexa",
                "clients",
                "container",
                "controllers",
                "database",
                "dependencies",
                "middleware",
                "models",
                "services",
            }
        ),
    }
    MAX_FILE_LINES = {
        "alexa": 500,
        "clients": 350,
        "constants": 300,
        "controllers": 220,
        "database": 400,
        "middleware": 350,
        "models": 650,
        "services": 300,
        "utils": 400,
    }
    MAX_METHOD_LINES = {
        "alexa": 80,
        "clients": 80,
        "constants": 60,
        "controllers": 50,
        "database": 100,
        "middleware": 120,
        "models": 120,
        "services": 80,
        "utils": 60,
    }
    DUPLICATE_METHOD_EXCLUSIONS = frozenset(
        {
            "__init__",
            "can_handle",
            "handle",
            "execute",
            "process",
            "get",
            "set",
            "read",
            "update",
            "clear",
            "to_dict",
            "from_dict",
        }
    )


class ArchitectureAudit:
    def __init__(self, root: Path, strict: bool = False, limit: int = 250) -> None:
        self.root = root.resolve()
        self.src = self.root / "src"
        self.strict = strict
        self.limit = limit
        self.findings: list[Finding] = []
        self.trees: dict[Path, ast.Module] = {}
        self.sources: dict[Path, str] = {}
        self.class_locations: list[tuple[str, Path, int]] = []
        self.method_bodies: dict[str, list[tuple[str, Path, int]]] = defaultdict(list)

    def run(self) -> int:
        if not self.src.is_dir():
            self.add("ERROR", "layout", self.src, 1, "src directory is missing")
            return self.report()
        self.check_layout()
        for path in sorted(self.src.rglob("*.py")):
            self.inspect_file(path)
        self.check_required_classes()
        self.check_dead_classes()
        self.check_duplicate_methods()
        return self.report()

    def inspect_file(self, path: Path) -> None:
        source = path.read_text(encoding="utf-8")
        relative = self.relative(path)
        self.sources[path] = source
        try:
            tree = ast.parse(source)
        except SyntaxError as error:
            self.add("ERROR", "syntax", path, error.lineno or 1, error.msg)
            return
        self.trees[path] = tree
        self.check_module_shape(path, tree)
        self.check_comments(path, source)
        self.check_imports(path, tree)
        self.check_environment_boundaries(path, tree)
        self.check_state_boundaries(path, tree)
        self.check_service_locator(path, tree)
        self.check_sizes(path, tree, source)
        self.collect_classes_and_methods(path, tree)
        if relative == "src/constants/__init__.py" and source.strip():
            self.add(
                "ERROR",
                "constants-owner",
                path,
                1,
                "constants package initializer must not re-export a mixed catalog",
            )

    def check_layout(self) -> None:
        for directory in sorted(self.src.iterdir()):
            if not directory.is_dir() or directory.name not in AuditPolicy.FORBIDDEN_DIRECTORIES:
                continue
            if any(directory.rglob("*.py")):
                self.add(
                    "ERROR",
                    "forbidden-directory",
                    directory,
                    1,
                    f"remove legacy source directory {directory.name}",
                )
        for path in sorted(self.src.glob("*.py")):
            if path.name not in AuditPolicy.ROOT_FILES:
                self.add(
                    "ERROR",
                    "root-module",
                    path,
                    1,
                    "move loose root code to its class owner",
                )
        dependencies = self.src / "dependencies.py"
        if dependencies.exists():
            self.add(
                "ERROR",
                "single-container",
                dependencies,
                1,
                "merge Dependencies into ApplicationContainer and remove this module",
            )

    def check_module_shape(self, path: Path, tree: ast.Module) -> None:
        allowed = (ast.Import, ast.ImportFrom, ast.ClassDef)
        for node in tree.body:
            if not isinstance(node, allowed):
                self.add(
                    "ERROR",
                    "class-only-module",
                    path,
                    getattr(node, "lineno", 1),
                    f"top-level {type(node).__name__} is forbidden; keep imports and classes only",
                )
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)) and not isinstance(
                parents.get(node), ast.Module
            ):
                self.add(
                    "ERROR",
                    "top-imports",
                    path,
                    node.lineno,
                    "nested or conditional import is forbidden",
                )

    def check_comments(self, path: Path, source: str) -> None:
        try:
            tokens = tokenize.generate_tokens(io.StringIO(source).readline)
            for token in tokens:
                if token.type == tokenize.COMMENT:
                    self.add(
                        "ERROR",
                        "no-code-comments",
                        path,
                        token.start[0],
                        "replace the code comment with expressive classes, methods, and tests",
                    )
        except tokenize.TokenError as error:
            self.add("ERROR", "tokenize", path, 1, str(error))

    def check_imports(self, path: Path, tree: ast.Module) -> None:
        layer = self.layer(path)
        forbidden = AuditPolicy.FORBIDDEN_IMPORTS.get(layer, frozenset())
        for node in tree.body:
            modules: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            elif isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            for module in modules:
                if layer == "clients" and module == "src.models.resolver":
                    continue
                if module == "src.constants":
                    self.add(
                        "ERROR",
                        "focused-constant-import",
                        path,
                        node.lineno,
                        "import the owning constants class from its focused module",
                    )
                imported_layer = self.imported_layer(module)
                if imported_layer in forbidden:
                    self.add(
                        "ERROR",
                        "dependency-direction",
                        path,
                        node.lineno,
                        f"{layer} must not import {module}",
                    )
                if layer == "database" and module.startswith("src.models.") and module != "src.models.user":
                    self.add(
                        "ERROR",
                        "database-model-boundary",
                        path,
                        node.lineno,
                        "database code may import only the User model contract",
                    )

    def check_state_boundaries(self, path: Path, tree: ast.Module) -> None:
        relative = self.relative(path)
        if relative in AuditPolicy.STATE_GATEWAYS:
            return
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {
                "request_attributes",
                "persistent_attributes",
            }:
                self.add(
                    "ERROR",
                    "state-gateway",
                    path,
                    node.lineno,
                    f"access {node.attr} through User or RequestContext",
                )
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in AuditPolicy.STATE_METHODS:
                    self.add(
                        "ERROR",
                        "state-gateway",
                        path,
                        node.lineno,
                        f"call {node.func.attr} through the owning state class",
                    )
            if isinstance(node, ast.Constant) and node.value in {"_store", "_dirty"}:
                self.add(
                    "ERROR",
                    "state-gateway",
                    path,
                    node.lineno,
                    f"raw state key {node.value} belongs to User",
                )

    def check_environment_boundaries(self, path: Path, tree: ast.Module) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                owner = node.func.value
                if isinstance(owner, ast.Name) and owner.id == "os" and node.func.attr == "getenv":
                    self.add(
                        "ERROR",
                        "settings-gateway",
                        path,
                        node.lineno,
                        "read environment configuration through config.Settings",
                    )
                if isinstance(owner, ast.Attribute) and isinstance(owner.value, ast.Name) and owner.value.id == "os" and owner.attr == "environ":
                    self.add(
                        "ERROR",
                        "settings-gateway",
                        path,
                        node.lineno,
                        "read environment configuration through config.Settings",
                    )
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute):
                owner = node.value
                if isinstance(owner.value, ast.Name) and owner.value.id == "os" and owner.attr == "environ":
                    self.add(
                        "ERROR",
                        "settings-gateway",
                        path,
                        node.lineno,
                        "read environment configuration through config.Settings",
                    )

    def check_service_locator(self, path: Path, tree: ast.Module) -> None:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr == "resolve" and isinstance(node.func.value, ast.Name):
                if node.func.value.id == "Container":
                    self.add(
                        "ERROR",
                        "service-locator",
                        path,
                        node.lineno,
                        "inject the exact dependency through the constructor",
                    )

    def check_sizes(self, path: Path, tree: ast.Module, source: str) -> None:
        layer = self.layer(path)
        line_limit = AuditPolicy.MAX_FILE_LINES.get(layer, 250)
        line_count = len(source.splitlines())
        if line_count > line_limit:
            self.add(
                "WARN",
                "large-module",
                path,
                1,
                f"{line_count} lines exceeds the {line_limit}-line review threshold",
            )
        method_limit = AuditPolicy.MAX_METHOD_LINES.get(layer, 80)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            length = (node.end_lineno or node.lineno) - node.lineno + 1
            if length > method_limit:
                self.add(
                    "WARN",
                    "large-method",
                    path,
                    node.lineno,
                    f"{node.name} is {length} lines; extract cohesive class-owned behavior",
                )

    def collect_classes_and_methods(self, path: Path, tree: ast.Module) -> None:
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                self.class_locations.append((node.name, path, node.lineno))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = ast.dump(ast.Module(body=node.body, type_ignores=[]), include_attributes=False)
            if len(body) < 300 or node.name in AuditPolicy.DUPLICATE_METHOD_EXCLUSIONS:
                continue
            digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
            self.method_bodies[digest].append((node.name, path, node.lineno))

    def check_required_classes(self) -> None:
        for relative, class_name in AuditPolicy.REQUIRED_CLASSES.items():
            path = self.root / relative
            tree = self.trees.get(path)
            if tree is None:
                self.add("ERROR", "required-owner", path, 1, f"define class {class_name}")
                continue
            if not any(
                isinstance(node, ast.ClassDef) and node.name == class_name
                for node in tree.body
            ):
                self.add("ERROR", "required-owner", path, 1, f"define class {class_name}")

    def check_dead_classes(self) -> None:
        combined = "\n".join(self.sources.values())
        for name, path, line in self.class_locations:
            references = len(re.findall(rf"\b{re.escape(name)}\b", combined))
            if references == 1 and not name.endswith(("Error", "Exception")):
                self.add(
                    "WARN",
                    "dead-class",
                    path,
                    line,
                    f"{name} has no production caller",
                )

    def check_duplicate_methods(self) -> None:
        for entries in self.method_bodies.values():
            modules = {path for _, path, _ in entries}
            if len(modules) < 2:
                continue
            locations = ", ".join(
                f"{self.relative(path)}:{line}:{name}" for name, path, line in entries
            )
            name, path, line = entries[0]
            self.add(
                "WARN",
                "duplicate-method",
                path,
                line,
                f"consolidate exact duplicate behavior: {locations}",
            )

    def add(
        self,
        severity: str,
        rule: str,
        path: Path,
        line: int,
        message: str,
    ) -> None:
        self.findings.append(
            Finding(severity, rule, self.relative(path), int(line or 1), message)
        )

    def report(self) -> int:
        ordered = sorted(
            set(self.findings),
            key=lambda item: (
                0 if item.severity == "ERROR" else 1,
                item.path,
                item.line,
                item.rule,
            ),
        )
        for finding in ordered[: self.limit]:
            print(
                f"{finding.severity} {finding.rule} "
                f"{finding.path}:{finding.line} {finding.message}"
            )
        if len(ordered) > self.limit:
            print(f"... {len(ordered) - self.limit} additional findings omitted")
        counts = Counter(finding.severity for finding in ordered)
        print(
            f"Architecture audit: {counts['ERROR']} errors, "
            f"{counts['WARN']} warnings"
        )
        failed = counts["ERROR"] > 0 or (self.strict and counts["WARN"] > 0)
        return 1 if failed else 0

    def layer(self, path: Path) -> str:
        relative = path.relative_to(self.src)
        return relative.parts[0] if len(relative.parts) > 1 else "root"

    @staticmethod
    def imported_layer(module: str) -> str:
        parts = module.split(".")
        return parts[1] if len(parts) > 1 and parts[0] == "src" else ""

    def relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()

    @classmethod
    def main(cls) -> int:
        parser = argparse.ArgumentParser()
        parser.add_argument("root", nargs="?", default=".")
        parser.add_argument("--strict", action="store_true")
        parser.add_argument("--limit", type=int, default=250)
        arguments = parser.parse_args()
        return cls(Path(arguments.root), strict=arguments.strict, limit=arguments.limit).run()


raise SystemExit(ArchitectureAudit.main())
