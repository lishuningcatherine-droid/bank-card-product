"""Fails if any production-path module imports from ``legacy/``.

Production paths: ``src/bankrec`` (Python) and ``web/`` (TypeScript/JavaScript, excluding node_modules).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PY_ROOTS = [REPO_ROOT / "src"]
WEB_ROOT = REPO_ROOT / "web"
WEB_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
WEB_SKIP = {"node_modules", ".next", "out"}

_WEB_IMPORT = re.compile(r"""(?:from\s+|import\s*\(\s*|require\s*\(\s*|import\s+)['"]([^'"]+)['"]""")


def python_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name.split(".")[0] == "legacy"]
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0 and node.module.split(".")[0] == "legacy":
                found.append(node.module)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # Catches importlib.import_module("legacy...") and sys.path hacks pointing at legacy/.
            v = node.value
            if v == "legacy" or v.startswith("legacy.") or "legacy/src" in v or "legacy/data" in v:
                found.append(v)
    return found


def web_violations(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [m for m in _WEB_IMPORT.findall(text) if re.search(r"(^|/)legacy(/|$)", m)]


def _python_files() -> list[Path]:
    return [p for root in PY_ROOTS if root.exists() for p in root.rglob("*.py")]


def _web_files() -> list[Path]:
    if not WEB_ROOT.exists():
        return []
    return [
        p
        for p in WEB_ROOT.rglob("*")
        if p.suffix in WEB_EXTS and not WEB_SKIP.intersection(p.relative_to(WEB_ROOT).parts)
    ]


def test_production_code_does_not_import_legacy() -> None:
    violations = {str(p.relative_to(REPO_ROOT)): v for p in _python_files() if (v := python_violations(p))}
    violations |= {str(p.relative_to(REPO_ROOT)): v for p in _web_files() if (v := web_violations(p))}
    assert not violations, f"production code references legacy/: {violations}"


def test_guard_detects_python_imports(tmp_path: Path) -> None:
    cases = {
        "import legacy.src.scraper": True,
        "from legacy.data import x": True,
        "import importlib; importlib.import_module('legacy.src.parser')": True,
        "import sys; sys.path.insert(0, '../legacy/src')": True,
        "import legacyish": False,
        "from .legacy import x": False,  # relative import of a local module, not the archive
        "x = 'legacy_mode'": False,
    }
    for i, (src, expected) in enumerate(cases.items()):
        f = tmp_path / f"case{i}.py"
        f.write_text(src)
        assert bool(python_violations(f)) is expected, src


def test_guard_detects_web_imports(tmp_path: Path) -> None:
    cases = {
        "import x from '../../legacy/src/ui';": True,
        "const y = require('legacy/data/cards.csv');": True,
        "const z = await import('../legacy/src/a');": True,
        "import { legacyFlag } from './flags';": False,
    }
    for i, (src, expected) in enumerate(cases.items()):
        f = tmp_path / f"case{i}.ts"
        f.write_text(src)
        assert bool(web_violations(f)) is expected, src
