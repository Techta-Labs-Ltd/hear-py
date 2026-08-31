from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path


class MigrationOwners:
    VALUES = {
        "src.alexa.context": "RequestContext",
        "src.alexa.entities": "AlexaEntities",
        "src.alexa.feedback": "AlexaFeedback",
        "src.alexa.playback": "AlexaPlayback",
        "src.alexa.playback_context": "PlaybackContext",
        "src.alexa.request": "AlexaRequest",
        "src.alexa.response": "AlexaResponse",
        "src.alexa.runtime": "AlexaRuntime",
        "src.alexa.speech": "Speech",
        "src.alexa.ssml": "Ssml",
        "src.application": "Application",
        "src.clients.alexa_settings": "AlexaSettingsSupport",
        "src.clients.hear": "HearApiSupport",
        "src.clients.progressive": "ProgressiveResponseSupport",
        "src.clients.resolver": "ResolverClientSupport",
        "src.constants.dialog": "DialogConstants",
        "src.constants.discovery": "DiscoveryConstants",
        "src.constants.listener": "ListenerConstants",
        "src.constants.onboarding": "OnboardingConstants",
        "src.constants.persistence": "PersistenceConstants",
        "src.constants.playback": "PlaybackConstants",
        "src.constants.search": "SearchConstants",
        "src.constants.state": "StateSchema",
        "src.controllers.can_fulfill": "CanFulfillPolicy",
        "src.controllers.intent_dispatch": "IntentDispatchPolicy",
        "src.controllers.launch": "LaunchControllerSupport",
        "src.controllers.playback_controls": "PlaybackControllerSupport",
        "src.controllers.playback_events": "PlaybackEventSupport",
        "src.controllers.system": "SystemControllerSupport",
        "src.database.dynamo_user": "DynamoUserSupport",
        "src.database.dynamodb": "DynamoExpressions",
        "src.database.persistence": "PersistenceSupport",
        "src.middleware.confirmation": "ConfirmationPolicy",
        "src.middleware.dialog_validation": "DialogValidationPolicy",
        "src.middleware.identity": "IdentityPolicy",
        "src.middleware.onboarding_gate": "OnboardingPolicy",
        "src.middleware.pipeline": "MiddlewareRegistry",
        "src.middleware.resolver": "ResolverPolicy",
        "src.registry": "RouteRegistry",
        "src.services.alexa_locality": "AlexaLocalitySupport",
        "src.services.listener_sync": "ListenerSyncSupport",
        "src.services.observability": "Observability",
        "src.utils.browse": "BrowseUtils",
        "src.utils.content": "ContentUtils",
        "src.utils.deadline": "DeadlineBudget",
        "src.utils.filters": "SearchFilterUtils",
        "src.utils.playback": "PlaybackUtils",
    }

    @classmethod
    def owner(cls, module: str) -> str:
        if module in cls.VALUES:
            return cls.VALUES[module]
        stem = module.rsplit(".", 1)[-1]
        return "".join(part.capitalize() for part in stem.split("_")) + "Module"


@dataclass(frozen=True)
class OwnedSymbol:
    module: str
    owner: str
    symbol: str


class SourceIndex:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.modules: dict[str, Path] = {}
        self.trees: dict[str, ast.Module] = {}
        self.owned: dict[tuple[str, str], OwnedSymbol] = {}
        self.reexports: dict[tuple[str, str], tuple[str, str]] = {}

    def build(self) -> None:
        for path in sorted((self.root / "src").rglob("*.py")):
            module = self.module_name(path)
            tree = ast.parse(path.read_text(encoding="utf-8"))
            self.modules[module] = path
            self.trees[module] = tree
            owner = MigrationOwners.owner(module)
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.owned[(module, node.name)] = OwnedSymbol(module, owner, node.name)
                elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                    for name in ClassModuleMigration.assigned_names(node):
                        if name != "__all__":
                            self.owned[(module, name)] = OwnedSymbol(module, owner, name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    for alias in node.names:
                        if alias.name != "*":
                            self.reexports[(module, alias.asname or alias.name)] = (
                                node.module,
                                alias.name,
                            )

    def resolve(self, module: str, symbol: str, seen=None) -> OwnedSymbol | None:
        key = (module, symbol)
        if key in self.owned:
            return self.owned[key]
        seen = seen or set()
        if key in seen or key not in self.reexports:
            return None
        seen.add(key)
        origin_module, origin_symbol = self.reexports[key]
        return self.resolve(origin_module, origin_symbol, seen)

    def module_name(self, path: Path) -> str:
        relative = path.relative_to(self.root).with_suffix("")
        parts = list(relative.parts)
        if parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)


class ExternalReferenceTransformer(ast.NodeTransformer):
    def __init__(self, index: SourceIndex, current_module: str) -> None:
        self.index = index
        self.current_module = current_module
        self.references: dict[str, OwnedSymbol] = {}

    def collect(self, tree: ast.AST) -> None:
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            for alias in node.names:
                resolved = self.index.resolve(node.module, alias.name)
                if resolved:
                    self.references[alias.asname or alias.name] = resolved

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if not node.module:
            return node
        retained: list[ast.alias] = []
        owner_imports: dict[tuple[str, str], ast.alias] = {}
        for alias in node.names:
            resolved = self.index.resolve(node.module, alias.name)
            if not resolved:
                retained.append(alias)
                continue
            owner_imports[(resolved.module, resolved.owner)] = ast.alias(
                name=resolved.owner,
                asname=None,
            )
        replacements: list[ast.stmt] = []
        if retained:
            replacements.append(
                ast.ImportFrom(module=node.module, names=retained, level=node.level)
            )
        for (module, _), alias in owner_imports.items():
            replacements.append(ast.ImportFrom(module=module, names=[alias], level=0))
        return replacements or None

    def visit_Name(self, node: ast.Name):
        if not isinstance(node.ctx, ast.Load) or node.id not in self.references:
            return node
        resolved = self.references[node.id]
        return ast.copy_location(
            ast.Attribute(
                value=ast.Name(id=resolved.owner, ctx=ast.Load()),
                attr=resolved.symbol,
                ctx=node.ctx,
            ),
            node,
        )


class LocalReferenceTransformer(ast.NodeTransformer):
    def __init__(self, owner: str, symbols: set[str]) -> None:
        self.owner = owner
        self.symbols = symbols
        self.global_scopes: list[set[str]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef):
        return self.visit_callable(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        return self.visit_callable(node)

    def visit_callable(self, node):
        globals_for_function = {
            name
            for item in ast.walk(node)
            if isinstance(item, ast.Global)
            for name in item.names
        }
        self.global_scopes.append(globals_for_function)
        node.body = [item for child in node.body if (item := self.visit(child)) is not None]
        self.global_scopes.pop()
        return node

    def visit_Global(self, node: ast.Global):
        names = [name for name in node.names if name not in self.symbols]
        return ast.Global(names=names) if names else None

    def visit_Name(self, node: ast.Name):
        if node.id not in self.symbols:
            return node
        if isinstance(node.ctx, ast.Load):
            return ast.copy_location(
                ast.Attribute(
                    value=ast.Name(id=self.owner, ctx=ast.Load()),
                    attr=node.id,
                    ctx=node.ctx,
                ),
                node,
            )
        if self.global_scopes and node.id in self.global_scopes[-1]:
            return ast.copy_location(
                ast.Attribute(
                    value=ast.Name(id=self.owner, ctx=ast.Load()),
                    attr=node.id,
                    ctx=node.ctx,
                ),
                node,
            )
        return node


class ClassModuleMigration:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.index = SourceIndex(self.root)

    def run(self) -> None:
        self.index.build()
        targets = [
            *sorted((self.root / "src").rglob("*.py")),
            *sorted((self.root / "tests").rglob("*.py")),
            self.root / "main.py",
        ]
        for path in targets:
            self.migrate_file(path)

    def migrate_file(self, path: Path) -> None:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        module = self.index.module_name(path) if path.is_relative_to(self.root / "src") else ""
        external = ExternalReferenceTransformer(self.index, module)
        external.collect(tree)
        tree = external.visit(tree)
        if module:
            tree = self.class_only_tree(module, tree)
        ast.fix_missing_locations(tree)
        path.write_text(ast.unparse(tree) + "\n", encoding="utf-8")

    def class_only_tree(self, module: str, tree: ast.Module) -> ast.Module:
        imports: list[ast.stmt] = []
        classes: list[ast.ClassDef] = []
        assignments: list[ast.stmt] = []
        functions: list[ast.stmt] = []
        owner = MigrationOwners.owner(module)
        symbols = {
            symbol
            for candidate_module, symbol in self.index.owned
            if candidate_module == module
        }
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports.append(node)
            elif isinstance(node, ast.ClassDef):
                classes.append(node)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                if "__all__" not in self.assigned_names(node):
                    assignments.append(node)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(node)
        if module.endswith(".__init__") or self.index.modules.get(module, Path()).name == "__init__.py":
            return ast.Module(body=self.deduplicate_imports(imports), type_ignores=[])
        local = LocalReferenceTransformer(owner, symbols)
        transformed_classes = [local.visit(node) for node in classes]
        transformed_functions = []
        for node in functions:
            node.decorator_list.insert(0, ast.Name(id="staticmethod", ctx=ast.Load()))
            transformed_functions.append(local.visit(node))
        if not assignments and not transformed_functions:
            return ast.Module(
                body=[*self.deduplicate_imports(imports), *transformed_classes],
                type_ignores=[],
            )
        existing_owner = next(
            (candidate for candidate in transformed_classes if candidate.name == owner),
            None,
        )
        if existing_owner:
            existing_owner.body = [
                *assignments,
                *existing_owner.body,
                *transformed_functions,
            ]
            body_classes = transformed_classes
        else:
            owner_class = ast.ClassDef(
                name=owner,
                bases=[],
                keywords=[],
                body=[*assignments, *transformed_functions] or [ast.Pass()],
                decorator_list=[],
            )
            body_classes = [owner_class, *transformed_classes]
        return ast.Module(
            body=[*self.deduplicate_imports(imports), *body_classes],
            type_ignores=[],
        )

    @staticmethod
    def assigned_names(node: ast.Assign | ast.AnnAssign) -> set[str]:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return {
            target.id
            for target in targets
            if isinstance(target, ast.Name)
        }

    @staticmethod
    def deduplicate_imports(imports: list[ast.stmt]) -> list[ast.stmt]:
        seen: set[str] = set()
        result: list[ast.stmt] = []
        for node in imports:
            key = ast.dump(node, include_attributes=False)
            if key not in seen:
                seen.add(key)
                result.append(node)
        return result

    @classmethod
    def main(cls) -> int:
        parser = argparse.ArgumentParser()
        parser.add_argument("root", nargs="?", default=".")
        arguments = parser.parse_args()
        cls(Path(arguments.root)).run()
        return 0


raise SystemExit(ClassModuleMigration.main())
