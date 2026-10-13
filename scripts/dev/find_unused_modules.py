#!/usr/bin/env python3
"""Static import analysis for the cleanup: which modules are unused, and which are used only by legacy branches.

  python3 scripts/dev/find_unused_modules.py

Tier 1 = unreachable from every entry point (safe to delete now, together with the tests that import them).
Tier 2 = reachable only through the legacy `hook` branch / legacy plugin-prepare mode (delete after cutting those branches).
Lazy (in-function) imports count, so a module is only listed when nothing at all can import it.
"""
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
MODERN = ["mrh.application.advisory_runtime", "mrh.presentation.ctrl", "mrh.presentation.key_cli", "mrh.infrastructure.claude_hook",
          "mrh.presentation.dashboard", "mrh.infrastructure.secrets", "mrh.adapters.providers.registry"]
ENTRY = ["mrh.cli", "mrh.presentation.cli", "mrh.__main__", "mrh"]

mods = {}
for path in SRC.rglob("*.py"):
    name = ".".join(path.relative_to(SRC).with_suffix("").parts)
    mods[name[:-9] if name.endswith(".__init__") else name] = path


def imports(name):
    path, found = mods[name], set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = name.split(".")
                parts = parts[:len(parts) - node.level + (1 if path.name == "__init__.py" else 0)]
                base = ".".join(parts + ([node.module] if node.module else []))
            found.add(base)
            found.update(base + "." + a.name for a in node.names)
    return {m for m in found if m in mods}


def reach(entries):
    seen, stack = set(), [e for e in entries if e in mods]
    while stack:
        m = stack.pop()
        if m in seen:
            continue
        seen.add(m)
        stack += [i for i in imports(m) if i not in seen]
        stack += [".".join(m.split(".")[:k]) for k in range(1, len(m.split("."))) if ".".join(m.split(".")[:k]) in mods]
    return seen


def lines(m):
    return sum(1 for _ in open(mods[m]))


full, modern = reach(MODERN + ENTRY), reach(MODERN)
tier1 = sorted(m for m in mods if m not in full and not m.endswith("__init__"))
tier2 = sorted(m for m in full if m not in modern and not m.endswith("__init__") and m not in ENTRY + ["mrh.infrastructure.plugin"])
tests = list((ROOT / "tests").rglob("test_*.py"))
for title, group in (("Tier 1: nothing imports these (delete now)", tier1), ("Tier 2: only the legacy hook / legacy prepare branches use these", tier2)):
    print(f"\n{title}: {len(group)} modules, {sum(map(lines, group))} lines")
    for m in group:
        pkg, leaf = m.rsplit(".", 1)
        pattern = re.compile(r"(import|from)\s+" + re.escape(m) + r"\b|from\s+" + re.escape(pkg) + r"\s+import\s+[^\n]*\b" + re.escape(leaf) + r"\b")
        users = [t.relative_to(ROOT).as_posix() for t in tests if pattern.search(t.read_text())]
        print(f"  {lines(m):5d}  {mods[m].relative_to(ROOT)}" + (f"   tests: {', '.join(users)}" if users else ""))
