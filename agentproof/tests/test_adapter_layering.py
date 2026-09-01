"""AP-029 — qat sərhədi SƏNƏDDƏ deyil, TESTDƏ saxlanılır.

`http_agent.py` 786 sətir idi, çünki sərhəd yalnız docstring-də yazılmışdı:
"yeni müştəri = bir adapter faylı, < 150 sətir". Yazılmış qayda sürüşür.
Aşağıdakılar həmin qaydanı maşınla kilidləyir:

  adapters/_http_core.py   Dify sözünü BİLMİR (nə idxal, nə mətn)
  adapters/_dify_wire.py   yalnız wire formatı — httpx-ə TOXUNMUR
  adapters/http_agent.py   HTTP müştərisi, < 250 sətir
  adapters/conformance.py  heç bir KONKRET adapteri idxal ETMİR

AP-030/AP-031 ilə sərhəd İKİ yeni adapterə də şamil olunur:

  adapters/json_http.py      bloklayıcı JSON müştərisi, < 250 sətir
  adapters/callable_agent.py in-process çağırılan, < 250 sətir
  adapters/_field_map.py     sahə adları — nə HTTP, nə hədəf tanıyır

Qayda sadədir: **backoff, HALT və növbə birləşməsi YALNIZ nüvədədir**. Bu
kilid olmasa, hər yeni adapter onları öz üslubunda yenidən yazardı və
`full-run-03`-ün dərsləri üç fərqli cür sınardı.
"""

from __future__ import annotations

import ast
import io
import tokenize
from pathlib import Path

ADAPTERS = Path(__file__).resolve().parents[1] / "adapters"

#: `base.py` docstring-indəki vədin faktiki həddi (AP-029 DoD).
MAX_ADAPTER_LINES = 250

#: Hər biri BİR hədəf ailəsinin məftilini/çağırış üsulunu saxlayır.
ADAPTER_FILES = ("http_agent.py", "json_http.py", "callable_agent.py")

#: Nüvə qatı: konkret hədəfi tanımayan, hamı tərəfindən paylaşılan kod.
CORE_FILES = ("_http_core.py", "_field_map.py")


def _source(name: str) -> str:
    return (ADAPTERS / name).read_text(encoding="utf-8")


def _code(name: str) -> str:
    """Yalnız İCRA OLUNAN kod — docstring və şərhlər çıxarılır.

    Sərhəd qaydası KODA aiddir: nüvənin docstring-i "Dify-dən asılı deyil"
    cümləsini QURMALIDIR, amma kodunda Dify adı olmamalıdır.
    """
    kept: list[str] = []
    for tok in tokenize.generate_tokens(io.StringIO(_source(name)).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        kept.append(tok.string)
    return " ".join(kept)


def _imports(name: str) -> set[str]:
    tree = ast.parse(_source(name), filename=name)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
    return found


def test_core_does_not_know_about_dify():
    """Nüvə hədəfin protokolunu tanısaydı, ikinci adapter onu miras alardı."""
    for name in CORE_FILES:
        code = _code(name).lower()
        assert "dify" not in code, f"{name}: nüvənin KODUNDA Dify izi qaldı"
        assert "httpx" not in code, f"{name}: nüvə HTTP kitabxanasına bağlanmamalıdır"
    assert not any("adapters" in m for m in _imports("_http_core.py")), (
        "nüvə heç bir konkret adapteri idxal etməməlidir"
    )
    # `_field_map` yalnız nüvənin köməkçilərini götürür, adapter idxal ETMİR.
    foreign = {
        m for m in _imports("_field_map.py")
        if "adapters" in m and not m.startswith("agentproof.adapters._http_core")
    }
    assert not foreign, f"_field_map.py konkret adapter idxal edir: {sorted(foreign)}"


def test_field_map_has_no_target_specific_names():
    """Sahə adları KONFİQURASİYADADIR — biri kodda sabitlənsəydi, növbəti
    müştəri üçün yenə fayl redaktə etmək lazım gələrdi."""
    code = _code("_field_map.py").lower()
    for vendor in ("dify", "langgraph", "llamaindex", "openai", "anthropic", "vercel"):
        assert vendor not in code, f"_field_map.py kodunda `{vendor}` adı var"


def test_wire_layer_does_not_open_connections():
    """Wire faylı BAYTLARI oxuyur — sorğunu o göndərmir."""
    imports = _imports("_dify_wire.py")
    assert "httpx" not in imports
    assert "asyncio" not in imports


def test_adapter_file_stays_small():
    """786 sətir bir daha yığılmasın: hədd testdədir, docstring-də deyil."""
    for name in ADAPTER_FILES:
        lines = len(_source(name).splitlines())
        assert lines <= MAX_ADAPTER_LINES, f"{name} {lines} sətirdir"


def test_backoff_and_merge_live_only_in_the_core():
    """Təkrar maşını və növbə birləşməsi adapterdə TƏKRARLANMAMALIDIR."""
    for name in ADAPTER_FILES + ("_dify_wire.py", "_field_map.py"):
        code = _code(name)
        assert "asyncio . sleep" not in code, f"{name}: backoff gözləməsi nüvədə olmalıdır"
        assert "RETRYABLE" not in code, f"{name}: təkrar qərarı nüvədə olmalıdır"
        assert "HALT" not in code, f"{name}: qaçışın dayandırılması nüvədə olmalıdır"


def test_every_adapter_uses_the_shared_core():
    """Yeni adapter nüvəni ATLAYA bilməz.

    Atlasaydı, backoff/HALT/növbə birləşməsi orada sıfırdan yazılardı — və
    bu, AP-029-un aradan qaldırdığı vəziyyətin eynisidir.
    """
    for name in ADAPTER_FILES:
        imports = _imports(name)
        assert "agentproof.adapters._http_core" in imports, f"{name} nüvəni idxal etmir"
        assert f"agentproof.adapters._http_core.send_with_retry" in imports, (
            f"{name}: sorğu nüvənin təkrar maşınından KEÇMİR"
        )
        assert f"agentproof.adapters._http_core.merge_turns" in imports, (
            f"{name}: növbələr nüvə ilə birləşdirilmir"
        )


def test_conformance_suite_is_adapter_agnostic():
    """Müqavilə dəsti konkret adapteri tanısaydı, ona uyğunlaşdırıla bilərdi."""
    imports = _imports("conformance.py")
    for forbidden in ("agentproof.adapters.http_agent", "agentproof.adapters.mock_agent",
                      "agentproof.adapters._dify_wire", "agentproof.testing.mock_dify"):
        assert forbidden not in imports, f"conformance.py {forbidden}-i idxal edir"
