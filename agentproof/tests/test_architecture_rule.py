"""STACK.md §6-nın POZULMAZ qaydasının maşınla yoxlanması.

`agentproof/graders/` və `agentproof/types.py` Inspect-i import ETMİR.
Bu qayda pozularsa, STACK qərarının yarısı (M3 lock-in arqumenti) itir —
ona görə sənəddə deyil, testdə saxlanır.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
GRADERS_ROOT = PACKAGE_ROOT / "graders"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _grader_sources() -> list[Path]:
    return [p for p in GRADERS_ROOT.rglob("*.py") if "tests" not in p.parts]


def test_graders_package_has_sources():
    assert len(_grader_sources()) >= 8, "grader qaynaqları tapılmadı — test mənasız yaşıl olardı"


def test_graders_do_not_import_inspect():
    offenders: list[str] = []
    for path in _grader_sources():
        for module in _imported_modules(path):
            if module == "inspect_ai" or module.startswith("inspect_ai."):
                offenders.append(f"{path.relative_to(PACKAGE_ROOT)} -> {module}")
    assert not offenders, (
        "graders/ paketi inspect_ai import etməməlidir (STACK.md §6):\n  " + "\n  ".join(offenders)
    )


def test_types_module_does_not_import_inspect():
    assert not any(
        m.startswith("inspect_ai") for m in _imported_modules(PACKAGE_ROOT / "types.py")
    )


def test_graders_importable_without_inspect_installed():
    """Alt-prosesdə `inspect_ai` bloklanır — grader-lər yenə də qalxmalıdır."""
    script = (
        "import sys\n"
        "class Blocker:\n"
        "    def find_module(self, name, path=None):\n"
        "        if name == 'inspect_ai' or name.startswith('inspect_ai.'):\n"
        "            raise ImportError('inspect_ai bloklandı (memarlıq testi)')\n"
        "        return None\n"
        "sys.meta_path.insert(0, Blocker())\n"
        "from agentproof.graders import registry\n"
        "assert 'inspect_ai' not in sys.modules, 'inspect_ai dolayı yolla yükləndi'\n"
        "print(len(registry.names()))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PACKAGE_ROOT.parent,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert int(result.stdout.strip()) >= 9


def test_only_runner_and_normalize_touch_inspect():
    """Inspect körpüsü NAZİK qalmalıdır — icazəli fayl siyahısı."""
    allowed = {
        "runner/agent.py",
        "runner/bridge.py",
        "runner/provider.py",
        "runner/scorer.py",
        "runner/task.py",
        "report/normalize.py",
    }
    touching = {
        str(p.relative_to(PACKAGE_ROOT))
        for p in PACKAGE_ROOT.rglob("*.py")
        if "tests" not in p.parts
        and any(m.startswith("inspect_ai") for m in _imported_modules(p))
    }
    assert touching <= allowed, f"Inspect-ə yeni toxunma nöqtəsi: {sorted(touching - allowed)}"
