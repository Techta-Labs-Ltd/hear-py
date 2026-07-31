#!/usr/bin/env python3
"""Static structural guardrails for the Hear onboarding flow.

Report-only by design: hard violations (stage drift, missing registration,
broken resolver contract, missing sync) exit non-zero; known product gaps
(unwired geolocation, dead community prompt, dead location-choice state,
missing Connections.Response handler) are reported as GAPS and do not fail.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path

CANONICAL_STAGES = {"ask_permission", "ask_town", "await_location_confirm",
                    "confirm_town_for_community"}
GATE_ORDER = ["OnboardingGateHandler", "TownCaptureHandler", "IntentDispatchHandler"]
ONBOARDING_FILES = [
    "src/handlers/intents/onboarding.py",
    "src/handlers/intents/launch.py",
    "src/middleware/onboarding_gate.py",
]
ALLOWED_STORE_KEYS = {
    "onboardingTownAttempts", "deviceId", "userEmail",
    "userName", "fullName", "givenName", "familyName", "profileFetchDenied",
    "profileNameUnavailable", "listenerProfileSkipUntil", "listenerProfileResolvedAt",
    "listenerSyncedAt", "listenerId", "address", "state", "country",
    "postalCode", "followedCreators", "listeningPattern", "notificationsEnabled",
    "playbackSpeed", "playCount", "lastPlayedAt", "recentTrackListens",
    "history", "recentPlays", "lastToken", "awaitingNotificationOptIn",
    "pendingNotificationQueue", "awaitingNotificationChoice",
}


def dotted(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{dotted(node.value)}.{node.attr}".strip(".")
    return ""


def _ast(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def dict_keys_for(dict_node: ast.Dict) -> list[str]:
    keys = []
    for key in dict_node.keys:
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            keys.append(key.value)
    return keys


def update_store_keys(path: Path) -> list[str]:
    """Collect string keys passed to update_store / update dicts in a module."""
    tree = _ast(path)
    keys: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id not in ("update_store", "update"):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Dict):
                keys.extend(dict_keys_for(arg))
        for kw in node.keywords:
            if isinstance(kw.value, ast.Dict):
                keys.extend(dict_keys_for(kw.value))
    return keys


def default_store_keys(root: Path) -> set[str]:
    path = root / "src/services/storage/store.py"
    if not path.exists():
        return set()
    for node in ast.walk(_ast(path)):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            if isinstance(node, ast.Assign):
                targets = node.targets
                value = node.value
            else:
                targets = [node.target]
                value = node.value
            if not isinstance(value, ast.Dict):
                continue
            if any(isinstance(t, ast.Name) and t.id == "DEFAULT_STORE" for t in targets):
                return set(dict_keys_for(value))
    return set()


def stage_literals(path: Path) -> list[str]:
    """Collect onboardingStage string literals in comparisons and updates."""
    tree = _ast(path)
    stages: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (isinstance(key, ast.Constant) and key.value == "onboardingStage"
                        and isinstance(value, ast.Constant) and isinstance(value.value, str)):
                    stages.append(value.value)
        if isinstance(node, ast.Compare):
            for cmp in node.comparators:
                if (isinstance(cmp, ast.Constant) and isinstance(cmp.value, str)
                        and cmp.value in CANONICAL_STAGES):
                    pass
            for left in (node.left,):
                if (isinstance(left, ast.Call) and isinstance(left.func, ast.Attribute)
                        and left.func.attr == "get"):
                    args = [a for a in left.args if isinstance(a, ast.Constant)]
                    if any(a.value == "onboardingStage" for a in args):
                        for cmp in node.comparators:
                            if (isinstance(cmp, ast.Constant)
                                    and isinstance(cmp.value, str)):
                                stages.append(cmp.value)
    return stages


def audit(root: Path) -> tuple[list[str], list[str]]:
    hard: list[str] = []
    soft: list[str] = []
    decl = default_store_keys(root)

    for rel in ONBOARDING_FILES:
        path = root / rel
        if not path.exists():
            hard.append(f"{rel}: missing")
            continue
        stages = stage_literals(path)
        for stage in stages:
            if stage not in CANONICAL_STAGES:
                hard.append(f"{rel}: unrecognized onboarding stage {stage!r}")
        for key in update_store_keys(path):
            if key not in decl and key not in ALLOWED_STORE_KEYS:
                soft.append(f"{rel}: store key {key!r} used but not declared in DEFAULT_STORE")

    pipeline = root / "src/middleware/pipeline.py"
    if pipeline.exists():
        order = {}
        for node in ast.walk(_ast(pipeline)):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Tuple):
                if not any(isinstance(t, ast.Name) and t.id == "GATE_HANDLERS"
                           for t in node.targets):
                    continue
                for index, elt in enumerate(node.value.elts):
                    name = dotted(elt).split(".")[-1]
                    if name in GATE_ORDER:
                        order[name] = index
        for expected in GATE_ORDER:
            if expected not in order:
                hard.append(f"src/middleware/pipeline.py: GATE_HANDLERS missing {expected}")
        if order.get("OnboardingGateHandler", 0) >= order.get("TownCaptureHandler", 10 ** 6):
            hard.append("src/middleware/pipeline.py: OnboardingGateHandler must precede TownCaptureHandler")

    dispatch = root / "src/nlp/dispatch_handler.py"
    if dispatch.exists():
        dispatchable = []
        map_entries = {}
        for node in ast.walk(_ast(dispatch)):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                if isinstance(node, ast.Assign):
                    targets, value = node.targets, node.value
                else:
                    targets, value = [node.target], node.value
                if not isinstance(value, (ast.List, ast.Tuple, ast.Dict)):
                    continue
                if any(isinstance(t, ast.Name) and t.id == "DISPATCHABLE_INTENTS"
                       for t in targets) and isinstance(value, (ast.List, ast.Tuple)):
                    dispatchable = [e.value for e in value.elts
                                    if isinstance(e, ast.Constant)]
                elif any(isinstance(t, ast.Name) and t.id == "dispatch_map"
                         for t in targets) and isinstance(value, ast.Dict):
                    for key, val in zip(value.keys, value.values):
                        if isinstance(key, ast.Constant):
                            map_entries[key.value] = dotted(val)
        for intent, handler in (("town_capture", "TownCaptureHandler"),
                                ("location_set", "SetLocationHandler")):
            if intent not in dispatchable:
                hard.append(f"src/nlp/dispatch_handler.py: {intent} missing from DISPATCHABLE_INTENTS")
            if map_entries.get(intent) != handler:
                hard.append(f"src/nlp/dispatch_handler.py: {intent} must dispatch to {handler}")

    onboarding = root / "src/handlers/intents/onboarding.py"
    if onboarding.exists():
        tree = _ast(onboarding)
        saw_location_call = False
        scopes = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "resolve_utterance"):
                args = [a for a in node.args if isinstance(a, ast.Constant)]
                if args and args[0].value == "resolve_location":
                    intents = [kw.value.value for kw in node.keywords
                               if kw.arg == "alexa_intent"
                               and isinstance(kw.value, ast.Constant)]
                    if intents != ["TownCaptureIntent"]:
                        hard.append("src/handlers/intents/onboarding.py: resolve_location must pass alexa_intent=\"TownCaptureIntent\"")
                    saw_location_call = True
            if isinstance(node, ast.ImportFrom) and node.module == "config.permission_scopes":
                scopes.update(alias.name for alias in node.names)
        if not saw_location_call:
            hard.append("src/handlers/intents/onboarding.py: no resolve_location call found")
        for name in ("DEVICE_ADDRESS", "GEOLOCATION_READ"):
            if name not in scopes:
                hard.append(f"src/handlers/intents/onboarding.py: {name} must come from config.permission_scopes")

    for rel, expected in (("src/handlers/intents/onboarding.py", 3),
                          ("src/handlers/intents/launch.py", 3)):
        path = root / rel
        if not path.exists():
            continue
        for node in ast.walk(_ast(path)):
            if (isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "MAX_TOWN_ATTEMPTS"
                    for t in node.targets)
                    and isinstance(node.value, ast.Constant)
                    and node.value.value != expected):
                hard.append(f"{rel}: MAX_TOWN_ATTEMPTS must be {expected}")

    system = root / "src/handlers/intents/system.py"
    if system.exists():
        found = False
        for node in ast.walk(_ast(system)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls = {dotted(c.func) for c in ast.walk(node)
                     if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
            keys = {v.value for d in ast.walk(node) if isinstance(d, ast.Dict)
                    for v in d.keys if isinstance(v, ast.Constant)}
            if "sync_listener" in calls and "onboardingComplete" in keys:
                found = True
        if not found:
            hard.append("src/handlers/intents/system.py: confirmation must persist onboardingComplete and await sync_listener")

    return hard, soft


def report_gaps(root: Path) -> list[str]:
    gaps: list[str] = []
    handler_calls: set[str] = set()
    for path in sorted((root / "src").rglob("*.py")):
        for node in ast.walk(_ast(path)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                handler_calls.add(node.func.id)
    if "detect_device_location" not in handler_calls:
        gaps.append("G2: detect_device_location is never called - Amazon API city detection is unwired")
    body = "\n".join(p.read_text(encoding="utf-8") for p in
                     (root / "src").rglob("*.py"))
    if '"awaitingCommunityPlayback": True' not in body:
        gaps.append("G1: awaitingCommunityPlayback is never set to True - the local-community follow-up prompt never fires")
    if '"awaitingLocationChoice"' in body:
        gaps.append("G3: awaitingLocationChoice is still referenced - the dead Yes/No branches were not removed")
    if "Connections.Response" not in body:
        gaps.append("G4: no Connections.Response handling - the consent card has no in-session acceptance path")
    skip_path = root / "src/handlers/intents/onboarding.py"
    if skip_path.exists():
        sets_complete = False
        for node in ast.walk(_ast(skip_path)):
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == "finalize_town_skipped"):
                for dict_node in (d for d in ast.walk(node)
                                  if isinstance(d, ast.Dict)):
                    if ("onboardingComplete" in dict_keys_for(dict_node)
                            and any(isinstance(v, ast.Constant) and v.value is True
                                    for v in dict_node.values)):
                        sets_complete = True
        if not sets_complete:
            gaps.append("G5: finalize_town_skipped leaves onboardingComplete unset - the gate re-asks permission on the next intent")
    return gaps


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".", help="repository root")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    findings_hard, findings_soft = audit(root)
    gaps = report_gaps(root)

    if findings_hard:
        for line in findings_hard:
            print(f"  VIOLATION  {line}")
    if findings_soft:
        print("Soft findings (pre-existing hygiene, not blocking):")
        for line in findings_soft:
            print(f"  NOTE       {line}")
    if gaps:
        print("Known onboarding gaps (documented, not blocking):")
        for line in gaps:
            print(f"  GAP        {line}")

    if findings_hard:
        print(f"Hear onboarding audit failed: {len(findings_hard)} violation(s).")
        return 1
    print("Hear onboarding audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
