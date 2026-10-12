"""Adapters never import each other; they may use only shared modules (brief §6.6)."""

import ast
from pathlib import Path

ADAPTERS = Path(__file__).resolve().parents[1] / "src" / "bankrec" / "ingest" / "adapters"
ALLOWED = (
    "bankrec.ingest.common",
    "bankrec.parsers",
    "bankrec.normalize",
    "bankrec.model",
    "bankrec.candidate",
    "bankrec.ingest.adapters.base",
)


def test_adapters_only_import_shared_modules() -> None:
    bad: dict[str, list[str]] = {}
    for p in ADAPTERS.glob("*.py"):
        if p.name in {"__init__.py", "base.py"}:
            continue
        for node in ast.walk(ast.parse(p.read_text())):
            mods = []
            if isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            elif isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            for m in mods:
                if m.startswith("bankrec") and not m.startswith(ALLOWED):
                    bad.setdefault(p.name, []).append(m)
    assert not bad, bad


def test_every_bank_config_has_an_adapter_and_docs() -> None:
    import yaml

    root = ADAPTERS.parents[3]
    for cfg in (root / "config" / "banks").glob("*.yaml"):
        if cfg.name.startswith("_") or cfg.name.endswith(".rules.yaml"):
            continue
        data = yaml.safe_load(cfg.read_text())
        if data.get("role") == "regulator":
            continue
        assert (ADAPTERS / f"{data['adapter']}.py").exists(), cfg.name
        if not data.get("test_only"):
            assert (root / "docs" / "adapters" / f"{data['bank_id']}.md").exists(), cfg.name
