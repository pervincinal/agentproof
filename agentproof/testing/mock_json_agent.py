"""Bloklayıcı JSON hədəf stub-u — `json_http` adapterini sınamaq üçün.

`mock_dify.py` bir KONKRET məhsulun məftilini təqlid edir (SSE, `agent_thought`,
`retriever_resources`). Bu stub isə "müştərinin öz servisi"ni təqlid edir:
sadə `POST -> JSON`, üstəlik sahə adları QƏSDƏN standart deyil —

    {"reply": ..., "cost": {"in_tokens": ...}, "trace": [...],
     "citations": [...], "thread": "...", "failure": {...}}

Bu adlar `FieldMap`-in default namizədlərinin HEÇ BİRİ ilə üst-üstə düşmür.
Səbəb: uyğunluq dəsti default-lar sayəsində keçsəydi, "sahə xəritəsi işləyir"
iddiası SINANMAMIŞ qalardı. Burada hər sahə konfiqurasiya ilə tapılır.

`shape="plain"` isə əksini sınayır: adları TİPİK olan hədəf (`answer`,
`usage`, `tool_calls`, `sources`) konfiqurasiyasız da oxunmalıdır.

`scripted` formatı (açar sorğuda axtarılan alt sətir):
    {
      "answer": str,
      "retrieved": [{"chunk_id","document","content","score"}],
      "tool_calls": [{"name","arguments","result"}],
      "usage": {"input_tokens","output_tokens"},
      "delay_ms": int,
      "side_effect": callable(body) -> dict | None,
      "error": ("code","message",status),      # HTTP statusu ilə xəta
      "error_body": ("code","message",status),  # 200 + gövdədə xəta zərfi
      "times": int,                             # xəta yalnız ilk N sorğuda
      "retry_after": str,                       # `Retry-After` başlığı
      "usage_before_error": bool,               # xəta zərfi + YANMIŞ tokenlər
      "no_conversation_id": bool,               # `thread` boş qayıdır
    }
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

DEFAULT_API_KEY = "svc-mock-000000000000000000000000"

#: Adları QƏSDƏN qeyri-standart olan hədəf (xəritələmə sınanır).
CUSTOM_MAP: dict[str, Any] = {
    "text_path": "reply",
    "usage_path": "cost",
    "usage_input_path": "in_tokens",
    "usage_output_path": "out_tokens",
    "tool_calls_path": "trace",
    "tool_name_path": "fn",
    "tool_arguments_path": "params",
    "tool_result_path": "returned",
    "retrieved_path": "citations",
    "chunk_id_path": "ref",
    "chunk_text_path": "body",
    "chunk_score_path": "rank",
    "chunk_document_path": "file",
    "error_code_path": "failure.kind",
    "error_message_path": "failure.detail",
    "error_status_path": "failure.http",
}

#: `conversation_id_path` AYRICA verilir: onu default-a qoymaq "bu hədəf
#: çoxnövbəli dəstəkləyir" iddiasını təxminə çevirərdi.
CUSTOM_CONVERSATION_PATH = "thread"


def _custom_body(spec: dict[str, Any], conversation_id: str) -> dict[str, Any]:
    body: dict[str, Any] = {"reply": spec.get("answer", "")}
    if "usage" in spec:
        body["cost"] = {
            "in_tokens": spec["usage"].get("input_tokens", 0),
            "out_tokens": spec["usage"].get("output_tokens", 0),
        }
    if "tool_calls" in spec:
        body["trace"] = [
            {"fn": t["name"], "params": t.get("arguments", {}), "returned": t.get("result")}
            for t in spec["tool_calls"]
        ]
    if "retrieved" in spec:
        body["citations"] = [
            {
                "ref": r.get("chunk_id", ""),
                "body": r.get("content", r.get("text", "")),
                # Bal STRING kimi gəlir — real hədəflərdə adi haldır.
                "rank": str(r.get("score")) if r.get("score") is not None else None,
                "file": r.get("document", ""),
            }
            for r in spec["retrieved"]
        ]
    body["thread"] = "" if spec.get("no_conversation_id") else conversation_id
    return body


def _plain_body(spec: dict[str, Any], conversation_id: str) -> dict[str, Any]:
    """Tipik adlandırma — `FieldMap` default namizədləri ilə oxunmalıdır."""
    body: dict[str, Any] = {"answer": spec.get("answer", "")}
    if "usage" in spec:
        body["usage"] = dict(spec["usage"])
    if "tool_calls" in spec:
        body["tool_calls"] = [dict(t) for t in spec["tool_calls"]]
    if "retrieved" in spec:
        body["sources"] = [
            {
                "chunk_id": r.get("chunk_id", ""),
                "text": r.get("content", r.get("text", "")),
                "score": r.get("score"),
                "document": r.get("document", ""),
            }
            for r in spec["retrieved"]
        ]
    body["conversation_id"] = "" if spec.get("no_conversation_id") else conversation_id
    return body


BODY_SHAPES = {"custom": _custom_body, "plain": _plain_body}


def _error_body(shape: str, code: str, message: str, status: int) -> dict[str, Any]:
    if shape == "custom":
        return {"failure": {"kind": code, "detail": message, "http": status}}
    return {"error": {"code": code, "message": message, "status": status}}


class _Handler(BaseHTTPRequestHandler):
    server_version = "MockJsonAgent/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        pass

    @property
    def script(self) -> "MockJsonAgentServer":
        return self.server.script  # type: ignore[attr-defined]

    def _auth_ok(self) -> bool:
        header = self.headers.get("Authorization", "")
        return header.startswith("Bearer ") and header[len("Bearer ") :] == self.script.api_key

    def _send(self, status: int, payload: dict[str, Any],
              headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/health":
            self._send(200, {"status": "ok"})
        elif path == self.script.path:
            # Çağırış ünvanı yalnız POST qəbul edir. `health()` default
            # rejimdə məhz bunu görür: server AYAQDADIR.
            self._send(405, _error_body(self.script.shape, "method_not_allowed", "use POST", 405))
        else:
            self._send(404, _error_body(self.script.shape, "not_found", "Not Found", 404))

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != self.script.path:
            self._send(404, _error_body(self.script.shape, "not_found", "Not Found", 404))
            return
        if not self._auth_ok():
            self._send(
                401,
                _error_body(self.script.shape, "unauthorized",
                            "Authorization header must be provided and start with 'Bearer'", 401),
            )
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        status, payload, headers = self.script.invoke(body)
        self._send(status, payload, headers)


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        pass


class MockJsonAgentServer:
    """Skriptləşdirilmiş bloklayıcı JSON hədəfi."""

    def __init__(
        self,
        scripted: dict[str, dict[str, Any]] | None = None,
        default: dict[str, Any] | None = None,
        api_key: str = DEFAULT_API_KEY,
        shape: str = "custom",
        path: str = "/invoke",
        query_field: str = "message",
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        self.scripted = scripted or {}
        self.default = default or {"answer": "Bu barədə məlumatım yoxdur."}
        self.api_key = api_key
        self.shape = shape
        self.path = path
        self.query_field = query_field
        self.request_log: list[dict[str, Any]] = []
        self._error_counts: dict[str, int] = {}
        self._httpd = _Server((host, port), _Handler)
        self._httpd.script = self  # type: ignore[attr-defined]
        self._thread: threading.Thread | None = None

    # ---- həyat dövrü ------------------------------------------------
    @property
    def base_url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def url(self) -> str:
        return f"{self.base_url}{self.path}"

    @property
    def health_url(self) -> str:
        return f"{self.base_url}/health"

    def start(self) -> "MockJsonAgentServer":
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread:
            self._thread.join(timeout=5)

    def __enter__(self) -> "MockJsonAgentServer":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    # ---- skript məntiqi ---------------------------------------------
    def _match(self, query: str) -> tuple[str, dict[str, Any]]:
        q = query.lower()
        for needle, spec in self.scripted.items():
            if needle.lower() in q:
                return needle, spec
        return "", self.default

    def _error_expired(self, needle: str, spec: dict[str, Any]) -> bool:
        """`times: N` — hədəf N sorğudan sonra özünə gəlir (backoff testi)."""
        limit = spec.get("times")
        if limit is None:
            return False
        seen = self._error_counts.get(needle, 0)
        if seen >= int(limit):
            return True
        self._error_counts[needle] = seen + 1
        return False

    def invoke(self, body: dict[str, Any]) -> tuple[int, dict[str, Any], dict[str, str]]:
        self.request_log.append(body)
        query = str(body.get(self.query_field, ""))
        needle, matched = self._match(query)
        spec = dict(matched)
        if self._error_expired(needle, spec):
            spec.pop("error", None)
            spec.pop("error_body", None)

        if "error" in spec:
            code, message, status = spec["error"]
            headers = {"Retry-After": str(spec["retry_after"])} if spec.get("retry_after") else {}
            return status, _error_body(self.shape, code, message, status), headers

        conversation_id = str(body.get("conversation_id") or "") or f"thr-{uuid.uuid4().hex[:12]}"
        side_effect = spec.get("side_effect")
        if callable(side_effect):
            override = side_effect({**body, "conversation_id": conversation_id})
            if isinstance(override, dict):
                spec.update(override)
        if spec.get("delay_ms"):
            time.sleep(spec["delay_ms"] / 1000.0)

        payload = BODY_SHAPES[self.shape](spec, conversation_id)
        if spec.get("error_body"):
            code, message, status = spec["error_body"]
            if not spec.get("usage_before_error"):
                # Tokenlər YANMADI: xərc sahəsi ümumiyyətlə gəlmir.
                payload.pop("cost", None)
                payload.pop("usage", None)
            payload.update(_error_body(self.shape, code, message, status))
            # Zərf 200 ilə gəlir: hədəf "uğur" statusu verib, içində xəta var.
            return 200, payload, {}
        return 200, payload, {}
