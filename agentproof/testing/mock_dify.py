"""Dify Service API stub — API açarı olmadan ucdan-uca sınaq üçün.

Təqlid edilən səth `target/SETUP.md §7`-dən götürülüb:

  GET  /v1/info                      -> Bearer yoxdursa 401 (Dify xəta zərfi)
  POST /v1/chat-messages             -> ChatCompletionResponse (blocking)
  GET  /v1/messages                  -> agent_thoughts (tool call izləri)

Bu **hədəfin özü deyil**, hədəfin MƏFTİLİ (wire format). Real Dify qalxanda
`http_agent` adapteri dəyişmir — yalnız base_url və açar dəyişir.

Cavab məzmunu `scripted` lüğəti ilə idarə olunur: {query_substring: response_spec}.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

DEFAULT_API_KEY = "app-mock-000000000000000000000000"


def _dify_error(code: str, message: str, status: int) -> tuple[int, dict[str, Any]]:
    return status, {"code": code, "message": message, "status": status}


class _Handler(BaseHTTPRequestHandler):
    server_version = "MockDify/1.17.0"
    protocol_version = "HTTP/1.1"

    # susdurulur: test çıxışını doldurmasın
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        pass

    # ---- köməkçilər -------------------------------------------------
    @property
    def script(self) -> "MockDifyServer":
        return self.server.script  # type: ignore[attr-defined]

    def _auth_ok(self) -> bool:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return False
        return header[len("Bearer ") :] == self.script.api_key

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _unauthorized(self) -> None:
        status, payload = _dify_error(
            "unauthorized",
            "Authorization header must be provided and start with 'Bearer'",
            401,
        )
        self._send(status, payload)

    # ---- marşrutlar -------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if not self._auth_ok():
            self._unauthorized()
            return
        if path == "/v1/info":
            self._send(200, {"name": "Aurora Goods Support (mock)", "tags": []})
        elif path == "/v1/messages":
            qs = parse_qs(urlparse(self.path).query)
            conv = (qs.get("conversation_id") or [""])[0]
            self._send(200, {"data": self.script.messages_for(conv), "has_more": False})
        else:
            status, payload = _dify_error("not_found", "Not Found", 404)
            self._send(status, payload)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if not self._auth_ok():
            self._unauthorized()
            return
        if path != "/v1/chat-messages":
            status, payload = _dify_error("not_found", "Not Found", 404)
            self._send(status, payload)
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        status, payload = self.script.chat(body)
        self._send(status, payload)


class MockDifyServer:
    """Skriptləşdirilmiş Dify stub-u.

    `scripted` formatı — açar sorğunun içində axtarılan alt sətir, dəyər:
        {
          "answer": str,
          "retrieved": [{"chunk_id","document","content","score"}],
          "tool_calls": [{"name","arguments","result"}],
          "usage": {"prompt_tokens","completion_tokens"},
          "delay_ms": int,
          "error": ("code", "message", status)   # Dify xəta zərfi qaytarır
        }
    """

    def __init__(
        self,
        scripted: dict[str, dict[str, Any]] | None = None,
        default: dict[str, Any] | None = None,
        api_key: str = DEFAULT_API_KEY,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        self.scripted = scripted or {}
        self.default = default or {"answer": "Bu barədə məlumatım yoxdur."}
        self.api_key = api_key
        self._conversations: dict[str, list[dict[str, Any]]] = {}
        self.request_log: list[dict[str, Any]] = []
        self._httpd = ThreadingHTTPServer((host, port), _Handler)
        self._httpd.script = self  # type: ignore[attr-defined]
        self._thread: threading.Thread | None = None

    # ---- həyat dövrü ------------------------------------------------
    @property
    def base_url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}/v1"

    def start(self) -> "MockDifyServer":
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread:
            self._thread.join(timeout=5)

    def __enter__(self) -> "MockDifyServer":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    # ---- skript məntiqi ---------------------------------------------
    def _match(self, query: str) -> dict[str, Any]:
        q = query.lower()
        for needle, spec in self.scripted.items():
            if needle.lower() in q:
                return spec
        return self.default

    def messages_for(self, conversation_id: str) -> list[dict[str, Any]]:
        return self._conversations.get(conversation_id, [])

    def chat(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        self.request_log.append(body)
        query = body.get("query", "")
        if not body.get("user"):
            return _dify_error("invalid_param", "user is required", 400)

        spec = self._match(query)
        if "error" in spec:
            code, message, status = spec["error"]
            return _dify_error(code, message, status)

        if spec.get("delay_ms"):
            time.sleep(spec["delay_ms"] / 1000.0)

        conversation_id = body.get("conversation_id") or str(uuid.uuid4())
        message_id = str(uuid.uuid4())
        usage_spec = spec.get("usage", {"prompt_tokens": 1800, "completion_tokens": 250})
        retriever_resources = [
            {
                "position": i + 1,
                "dataset_id": "ds-mock",
                "dataset_name": "Aurora Goods KB",
                "document_id": r.get("chunk_id", ""),
                "document_name": r.get("document", ""),
                "segment_id": r.get("chunk_id", ""),
                "score": r.get("score", 0.0),
                "content": r.get("content", ""),
            }
            for i, r in enumerate(spec.get("retrieved", []))
        ]
        agent_thoughts = [
            {
                "id": str(uuid.uuid4()),
                "position": i + 1,
                "thought": "",
                "tool": tc["name"],
                "tool_input": json.dumps({tc["name"]: tc.get("arguments", {})}),
                "observation": json.dumps(tc.get("result")),
            }
            for i, tc in enumerate(spec.get("tool_calls", []))
        ]

        answer = spec.get("answer", "")
        self._conversations.setdefault(conversation_id, []).append(
            {
                "id": message_id,
                "conversation_id": conversation_id,
                "query": query,
                "answer": answer,
                "agent_thoughts": agent_thoughts,
                "retriever_resources": retriever_resources,
                "created_at": int(time.time()),
            }
        )

        return 200, {
            "event": "message",
            "task_id": str(uuid.uuid4()),
            "id": message_id,
            "message_id": message_id,
            "conversation_id": conversation_id,
            "mode": "chat",
            "answer": answer,
            "metadata": {
                "usage": {
                    "prompt_tokens": usage_spec.get("prompt_tokens", 0),
                    "completion_tokens": usage_spec.get("completion_tokens", 0),
                    "total_tokens": usage_spec.get("prompt_tokens", 0)
                    + usage_spec.get("completion_tokens", 0),
                    "currency": "USD",
                    "latency": 0.42,
                },
                "retriever_resources": retriever_resources,
            },
            "created_at": int(time.time()),
        }


def aurora_fixture() -> dict[str, dict[str, Any]]:
    """SETUP.md §8-dəki Aurora Goods ssenarisindən kiçik skript dəsti."""
    return {
        "restocking": {
            "answer": (
                "Aurora Goods qaytarma pəncərəsi 30 gündür. Açılmış məhsullarda "
                "15% restocking haqqı tutulur."
            ),
            "retrieved": [
                {
                    "chunk_id": "returns-and-refunds#restocking",
                    "document": "returns-and-refunds.md",
                    "content": "Opened items are subject to a 15% restocking fee.",
                    "score": 0.93,
                }
            ],
            "usage": {"prompt_tokens": 1820, "completion_tokens": 190},
        },
        "hədiyyə kartı": {
            "answer": (
                "Bu barədə sənədlərimizdə məlumat tapa bilmədim, ona görə sizi "
                "canlı dəstək əməkdaşına yönləndirirəm."
            ),
            "retrieved": [],
            "tool_calls": [
                {
                    "name": "escalate_to_human",
                    "arguments": {"reason": "gift card returns not covered in KB"},
                    "result": {"ticket": "T-1001"},
                }
            ],
            "usage": {"prompt_tokens": 1610, "completion_tokens": 120},
        },
        "ord-1042": {
            "answer": "ORD-1042 sifarişi 12.08.2026-da çatdırılıb, qaytarma pəncərəsi açıqdır.",
            "retrieved": [
                {
                    "chunk_id": "returns-and-refunds#window",
                    "document": "returns-and-refunds.md",
                    "content": "Returns accepted within 30 days of delivery.",
                    "score": 0.91,
                }
            ],
            "tool_calls": [
                {
                    "name": "lookup_order",
                    "arguments": {"order_id": "ORD-1042"},
                    "result": {"status": "delivered", "delivered_at": "2026-08-12"},
                }
            ],
            "usage": {"prompt_tokens": 2400, "completion_tokens": 310},
        },
    }


_WORD_RE = re.compile(r"\w+", re.UNICODE)
