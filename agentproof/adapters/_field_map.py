"""Cavab sahələrinin XƏRİTƏSİ — hədəfin adlandırması ilə müqavilə arasında.

`_dify_wire.py` bir hədəfin məftil formatını KODDA saxlayır: `agent_message`,
`retriever_resources`, `segment_id`. Bu yaxşıdır, çünki Dify formatı bizim
seçimimiz deyil. Amma müştərinin öz FastAPI/Express servisi üçün eyni yolu
getmək absurddur: hər müştəriyə bir `_acme_wire.py` yazmaq lazım gələrdi,
halbuki fərq YALNIZ sahə adlarındadır —

    {"answer": ...}   {"output": ...}   {"data": {"text": ...}}
    {"usage": ...}    {"meta": {"tokens": {...}}}
    {"sources": ...}  {"retrieved": ...}   {"context": [...]}

Ona görə bu modul sahə adlarını KODDAN KONFİQURASİYAYA çıxarır: yol verilir,
dəyər oxunur. Modul heç bir hədəfi, heç bir nəqliyyatı tanımır — nə httpx, nə
SSE. `json_http` da, `callable` adapteri də eyni xəritəni işlədir.

SƏSSİZ DEFAULT YOXDUR
---------------------
Ən böyük risk budur: müştəri `usage`-ı başqa adla verir, biz tapmırıq və
`Usage(0, 0)` yazırıq. Hesabatda bu "$0.00 — büdcədən aşağı, KEÇDİ" kimi
görünür: inandırıcı və yalan. Ona görə:

  * sahə TAPILMADIsa `usage = None` (sıfır DEYİL) -> `cost_under` `skipped`;
  * `retrieved` tapılmadısa boş siyahı, AMMA `fields_present["retrieved"]`
    `False` olur — "sahə yoxdur" ilə "axtardı, tapmadı" fərqlənir (LIM-E06);
  * mətn boşdursa `error = "empty_answer"` — səssiz keçmir;
  * `usage` obyekti TAPILDI, amma içindəki token adları tanınmadısa, bu da
    `None` qaytarır və `notes`-a `usage_fields_unmapped` yazılır: xəritə
    yarımçıqdır, ölçmə isə uydurulmur.

HANSI YOL İŞLƏDİ — HESABATDA GÖRÜNÜR
------------------------------------
Hər sahə üçün namizəd yolların siyahısı var (ilk uyğun gələn qazanır). Bu,
konfiqurasiya yükünü azaldır, amma təxmin gizli qalsaydı təhlükəli olardı:
`raw["mapped_paths"]` HƏMİŞƏ hansı yolun işlədiyini yazır. `preflight` məhz
bunu müştəriyə göstərir.

ÇOXNÖVBƏLİLİK TƏXMİN EDİLMİR
----------------------------
`conversation_id` üçün default namizəd YOXDUR (boş kortəj). Söhbətin
zəncirlənməsi QABİLİYYƏT iddiasıdır: səhv sahəni təxmin etsək, hər növbə yeni
söhbət açar və çoxnövbəli case-lər tək-növbəli kimi ölçülərdi — `COVERAGE.md
§7`-dəki səhvin eynisi. Konfiqurasiya verilməyibsə adapter "bu hədəf
çoxnövbəli dəstəkləmir" DEYİR.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Sequence

from agentproof.adapters._http_core import as_float, as_int, maybe_json
from agentproof.failure import classify_failure
from agentproof.types import AgentResponse, RetrievedChunk, ToolCall, Usage


class _Missing:
    """"Sahə YOXDUR" — `None`-dan fərqlidir (`None` hədəfin verdiyi dəyər ola bilər)."""

    def __repr__(self) -> str:  # pragma: no cover - yalnız debug
        return "<MISSING>"

    def __bool__(self) -> bool:
        return False


MISSING = _Missing()

#: Yol ayırıcısı. `a.b.0.c` — rəqəm seqmenti siyahı indeksidir.
SEP = "."


def resolve(payload: Any, path: str) -> Any:
    """Nöqtəli yol -> dəyər (tapılmasa `MISSING`).

    Boş yol KÖKün özüdür: hədəf sadəcə `"cavab mətni"` və ya `[...]` qaytara
    bilər, o zaman `text_path=""` yazılır.
    """
    if not path:
        return payload
    current = payload
    for segment in path.split(SEP):
        if isinstance(current, dict):
            if segment not in current:
                return MISSING
            current = current[segment]
        elif isinstance(current, (list, tuple)):
            if not segment.lstrip("-").isdigit():
                return MISSING
            index = int(segment)
            if not -len(current) <= index < len(current):
                return MISSING
            current = current[index]
        else:
            return MISSING
    return current


def first(payload: Any, paths: Sequence[str]) -> tuple[Any, str]:
    """Namizəd yollardan İLK tapılanı (dəyər, yol). Tapılmasa `(MISSING, "")`.

    `None` dəyər TAPILMIŞ sayılmır: hədəflər boş sahəni çox vaxt `null` ilə
    verir və bunu "sahə var, dəyəri yoxdur" kimi oxumaq növbəti namizədi
    kor edərdi.
    """
    for path in paths:
        value = resolve(payload, path)
        if value is not MISSING and value is not None:
            return value, path
    return MISSING, ""


def _paths(value: Any) -> tuple[str, ...]:
    """Konfiqurasiya dəyəri: bir yol (str) və ya namizədlər siyahısı."""
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(v) for v in value)


@dataclass(frozen=True)
class FieldMap:
    """Hansı sahə haradadır. Bütün dəyərlər NAMİZƏD yolların kortəjidir."""

    # --- yekun cavab ---------------------------------------------------
    text: tuple[str, ...] = (
        "answer", "output", "text", "response", "result",
        "data.answer", "data.output", "data.text",
        "choices.0.message.content",
    )
    # --- token istifadəsi ----------------------------------------------
    usage: tuple[str, ...] = ("usage", "metadata.usage", "meta.usage", "data.usage")
    usage_input: tuple[str, ...] = ("input_tokens", "prompt_tokens", "in", "input", "prompt")
    usage_output: tuple[str, ...] = ("output_tokens", "completion_tokens", "out", "output",
                                     "completion")
    usage_cached: tuple[str, ...] = ("cached_tokens", "cache_read_input_tokens", "cached")
    usage_model: tuple[str, ...] = ("model", "model_name")
    # --- tool çağırışları ----------------------------------------------
    tool_calls: tuple[str, ...] = ("tool_calls", "tools", "actions", "steps",
                                   "metadata.tool_calls", "data.tool_calls")
    tool_name: tuple[str, ...] = ("name", "tool", "tool_name", "function.name")
    tool_arguments: tuple[str, ...] = ("arguments", "args", "input", "tool_input",
                                       "parameters", "function.arguments")
    tool_result: tuple[str, ...] = ("result", "output", "observation", "response")
    tool_error: tuple[str, ...] = ("error",)
    # --- retrieval ------------------------------------------------------
    retrieved: tuple[str, ...] = ("retrieved", "sources", "documents", "context", "chunks",
                                  "metadata.retrieved", "metadata.retriever_resources",
                                  "data.retrieved")
    chunk_id: tuple[str, ...] = ("chunk_id", "id", "segment_id", "document_id", "source_id")
    chunk_text: tuple[str, ...] = ("text", "content", "snippet", "page_content")
    chunk_score: tuple[str, ...] = ("score", "relevance", "similarity", "distance")
    chunk_document: tuple[str, ...] = ("document", "document_name", "source", "doc", "title")
    # --- söhbət zənciri: DEFAULT YOXDUR (bax modul docstring-i) ----------
    conversation_id: tuple[str, ...] = ()
    # --- hədəfin öz xəta zərfi (200 statusla da gələ bilər) --------------
    error_code: tuple[str, ...] = ("error.code", "error.type", "error_code", "code")
    error_message: tuple[str, ...] = ("error.message", "error_message", "message", "detail")
    error_status: tuple[str, ...] = ("error.status", "error.status_code", "status", "status_code")

    #: `from_config` üçün icazəli açarlar (`<sahə>_path`).
    @staticmethod
    def config_keys() -> tuple[str, ...]:
        return tuple(f"{f.name}_path" for f in fields(FieldMap))

    @staticmethod
    def from_config(**config: Any) -> "FieldMap":
        """`text_path=...`, `usage_path=[...]` -> `FieldMap`.

        Tanınmayan açar SƏSSİZ ATILMIR: yazı səhvi (`retrieved_paths`) səssiz
        keçsəydi, adapter default namizədlərlə işləyib müştərinin verdiyi
        xəritəni gizlicə görməzdən gələrdi.
        """
        allowed = set(FieldMap.config_keys())
        unknown = sorted(set(config) - allowed)
        if unknown:
            raise TypeError(
                f"naməlum sahə xəritəsi açarı: {', '.join(unknown)}; "
                f"mövcud: {', '.join(sorted(allowed))}"
            )
        overrides = {
            key[: -len("_path")]: _paths(value)
            for key, value in config.items()
            if value is not None
        }
        return FieldMap(**overrides)  # type: ignore[arg-type]

    @property
    def supports_multi_turn(self) -> bool:
        """Söhbət zəncirlənə bilirmi — TƏXMİN deyil, konfiqurasiya faktı."""
        return bool(self.conversation_id)


# ============================================================== çıxarış qatı
@dataclass
class Mapped:
    """Xəritədən çıxan xam material + NƏYİN TAPILMADIĞI."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    retrieved: list[RetrievedChunk] = field(default_factory=list)
    usage: Usage | None = None
    conversation_id: str = ""
    error_code: str = ""
    error_message: str = ""
    error_status: int | None = None
    #: Sahə cavabda ÜMUMİYYƏTLƏ var idimi (boş olub-olmamasından asılı olmayaraq).
    present: dict[str, bool] = field(default_factory=dict)
    #: Hansı namizəd yol işlədi (hesabatda görünür, təxmin gizli qalmır).
    paths: dict[str, str] = field(default_factory=dict)
    #: Xəritənin yarımçıq qaldığı yerlər (`usage_fields_unmapped` və s.).
    notes: list[str] = field(default_factory=list)


def _usage(payload: Any, fmap: FieldMap, model: str, mapped: Mapped) -> Usage | None:
    raw, path = first(payload, fmap.usage)
    mapped.present["usage"] = raw is not MISSING
    if raw is MISSING:
        return None
    mapped.paths["usage"] = path
    if not isinstance(raw, dict):
        mapped.notes.append("usage_not_an_object")
        return None
    input_value, _ = first(raw, fmap.usage_input)
    output_value, _ = first(raw, fmap.usage_output)
    if input_value is MISSING and output_value is MISSING:
        # Obyekt var, token adları tanınmadı: ölçmə UYDURULMUR.
        mapped.notes.append("usage_fields_unmapped")
        return None
    cached_value, _ = first(raw, fmap.usage_cached)
    model_value, _ = first(raw, fmap.usage_model)
    return Usage(
        input_tokens=as_int(input_value) if input_value is not MISSING else 0,
        output_tokens=as_int(output_value) if output_value is not MISSING else 0,
        cached_tokens=as_int(cached_value) if cached_value is not MISSING else 0,
        model=model or (str(model_value) if model_value is not MISSING else ""),
    )


def _tool_calls(payload: Any, fmap: FieldMap, mapped: Mapped) -> list[ToolCall]:
    raw, path = first(payload, fmap.tool_calls)
    mapped.present["tool_calls"] = raw is not MISSING
    if raw is MISSING:
        return []
    mapped.paths["tool_calls"] = path
    if not isinstance(raw, list):
        mapped.notes.append("tool_calls_not_a_list")
        return []
    calls: list[ToolCall] = []
    for item in raw:
        if isinstance(item, str):
            calls.append(ToolCall(name=item))
            continue
        name, _ = first(item, fmap.tool_name)
        if name is MISSING:
            mapped.notes.append("tool_call_without_name")
            continue
        arguments = maybe_json(first(item, fmap.tool_arguments)[0])
        result = maybe_json(first(item, fmap.tool_result)[0])
        error = first(item, fmap.tool_error)[0]
        calls.append(
            ToolCall(
                name=str(name),
                arguments=arguments if isinstance(arguments, dict) else {},
                result=None if result is MISSING else result,
                error=None if error is MISSING else str(error),
            )
        )
    return calls


def _retrieved(payload: Any, fmap: FieldMap, mapped: Mapped) -> list[RetrievedChunk]:
    raw, path = first(payload, fmap.retrieved)
    mapped.present["retrieved"] = raw is not MISSING
    if raw is MISSING:
        return []
    mapped.paths["retrieved"] = path
    if not isinstance(raw, list):
        mapped.notes.append("retrieved_not_a_list")
        return []
    chunks: list[RetrievedChunk] = []
    for position, item in enumerate(raw):
        if isinstance(item, str):
            # Yalnız mətn gəlirsə id UYDURULMUR — mövqe ilə adlandırılır və
            # bu, `retrieval_hit_at_k`-da açıq şəkildə uyğunsuzluq verir.
            chunks.append(RetrievedChunk(chunk_id=f"#{position}", text=item))
            continue
        chunk_id, _ = first(item, fmap.chunk_id)
        text_value, _ = first(item, fmap.chunk_text)
        score_value, _ = first(item, fmap.chunk_score)
        document, _ = first(item, fmap.chunk_document)
        if chunk_id is MISSING:
            mapped.notes.append("retrieved_chunk_without_id")
        chunks.append(
            RetrievedChunk(
                chunk_id=str(chunk_id) if chunk_id is not MISSING else f"#{position}",
                text=str(text_value) if text_value is not MISSING else "",
                score=as_float(score_value) if score_value is not MISSING else None,
                document=str(document) if document is not MISSING else "",
            )
        )
    return chunks


def extract(payload: Any, fmap: FieldMap, model: str = "") -> Mapped:
    """Xam gövdə -> `Mapped`. Heç bir sahə uydurulmur, tapılmayan qeyd olunur."""
    mapped = Mapped()
    text_value, text_path = first(payload, fmap.text)
    mapped.present["text"] = text_value is not MISSING
    if text_value is not MISSING:
        mapped.paths["text"] = text_path
        mapped.text = text_value if isinstance(text_value, str) else str(text_value)

    mapped.tool_calls = _tool_calls(payload, fmap, mapped)
    mapped.retrieved = _retrieved(payload, fmap, mapped)
    mapped.usage = _usage(payload, fmap, model, mapped)

    conversation, conversation_path = first(payload, fmap.conversation_id)
    mapped.present["conversation_id"] = conversation is not MISSING
    if conversation is not MISSING:
        mapped.paths["conversation_id"] = conversation_path
        mapped.conversation_id = str(conversation)

    code, code_path = first(payload, fmap.error_code)
    message, _ = first(payload, fmap.error_message)
    status, _ = first(payload, fmap.error_status)
    if code is not MISSING:
        mapped.paths["error_code"] = code_path
        mapped.error_code = str(code)
    if message is not MISSING:
        mapped.error_message = str(message)
    if status is not MISSING:
        try:
            mapped.error_status = int(status)
        except (TypeError, ValueError):
            mapped.error_status = None
    return mapped


# ========================================================== cavab qurucusu
def build_response(
    payload: Any,
    fmap: FieldMap,
    *,
    latency_ms: int,
    model: str = "",
    transport: str = "json",
    http_status: int | None = None,
    retry_after: Any = None,
    extra_raw: dict[str, Any] | None = None,
) -> AgentResponse:
    """Xəritələnmiş gövdə -> `AgentResponse` (BİR növbə).

    Xəta iyerarxiyası: hədəfin öz zərfi > HTTP statusu > boş cavab. Üçü də
    ADLANDIRILIR — heç bir yolda səssiz boş mətn qayıtmır.
    """
    mapped = extract(payload, fmap, model)
    error, error_class = _error_of(mapped, http_status)
    return AgentResponse(
        text=mapped.text,
        tool_calls=mapped.tool_calls,
        retrieved=mapped.retrieved,
        usage=mapped.usage,
        latency_ms=latency_ms,
        raw={
            "transport": transport,
            "conversation_id": mapped.conversation_id,
            # Hansı sahə TAPILDI — `preflight` cədvəlinin xammalı budur.
            "fields_present": dict(mapped.present),
            # Hansı namizəd yol işlədi — təxmin gizli qalmır.
            "mapped_paths": dict(mapped.paths),
            "map_notes": list(mapped.notes),
            "http_status": http_status,
            "retry_after_s": _opt_float(retry_after),
            "target_error": (
                {
                    "code": mapped.error_code,
                    "message": mapped.error_message,
                    "status": mapped.error_status if mapped.error_status is not None
                    else http_status,
                }
                if error
                else None
            ),
            **(extra_raw or {}),
        },
        error=error,
        error_class=error_class,
    )


def _error_of(mapped: Mapped, http_status: int | None) -> tuple[str | None, str | None]:
    status = mapped.error_status if mapped.error_status is not None else http_status
    if mapped.error_code or mapped.error_message:
        code = mapped.error_code or f"http_{status or 'unknown'}"
        return code, classify_failure(
            code=mapped.error_code, message=mapped.error_message, status=status
        )
    if http_status is not None and http_status >= 400:
        code = f"http_{http_status}"
        return code, classify_failure(code="", message="", status=http_status)
    if not mapped.text.strip():
        # `empty_answer` -> təsnifat `unknown` verir: səbəb HƏQİQƏTƏN bilinmir,
        # amma cavab səssiz "boş mətn" kimi qiymətləndirilmir.
        return "empty_answer", classify_failure(code="empty_answer")
    return None, None


def error_detail(response: AgentResponse) -> str:
    """Hesabatda səbəbin yanında görünən insan-oxunaqlı izah.

    `send_with_retry` qaçışı dayandıranda bu mətn `HALT.detail`-ə düşür —
    yəni "niyə dayandıq" sualının cavabı budur.
    """
    target_error = (response.raw or {}).get("target_error") or {}
    code = str(target_error.get("code", "") or response.error or "")
    message = str(target_error.get("message", "")).strip()
    return f"{code}: {message}"[:500] if message else code


def _opt_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
