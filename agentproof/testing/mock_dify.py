"""Dify Service API stub — API açarı olmadan ucdan-uca sınaq üçün.

Təqlid edilən səth `target/SETUP.md §7` + canlı axından götürülmüş SSE formatı:

  GET  /v1/info                      -> Bearer yoxdursa 401 (Dify xəta zərfi)
  POST /v1/chat-messages             -> **SSE axını** (`response_mode=streaming`)
                                        `blocking` -> 400 `invalid_param`
                                        (Agent Chat App does not support blocking mode)
  GET  /v1/messages                  -> agent_thoughts (arxiv; adapter istifadə etmir)

Bu **hədəfin özü deyil**, hədəfin MƏFTİLİ (wire format). Real Dify qalxanda
`http_agent` adapteri dəyişmir — yalnız base_url və açar dəyişir.

Event formatı canlı `agent-chat` qaçışından bir-bir köçürülüb:
  - `agent_thought` eyni `id` ilə İKİ dəfə gəlir (əvvəl `tool`, sonra `observation`)
  - `tool` bir neçə tool-u `;` ilə birləşdirir, `tool_input`/`observation` isə
    tool adına görə açarlanır
  - `usage`-da model adı YOXDUR, qiymətlər STRING-dir
  - `retriever_resources[].score` STRING-dir

Cavab məzmunu `scripted` lüğəti ilə idarə olunur: {query_substring: response_spec}.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterator
from urllib.parse import parse_qs, urlparse

DEFAULT_API_KEY = "app-mock-000000000000000000000000"

# Canlı sistemdə təsdiqlənmiş rədd cavabı (PLAN.md "DÜZƏLİŞ").
BLOCKING_REJECTION = (
    "invalid_param",
    "Agent Chat App does not support blocking mode",
    400,
)


def _dify_error(code: str, message: str, status: int) -> tuple[int, dict[str, Any]]:
    return status, {"code": code, "message": message, "status": status}


#: Canlı `full-run-03`-dən BİR-BİR köçürülmüş kredit xətası. Dify upstream
#: cavabı MƏTN kimi sarır — ona görə səbəb yalnız mesajdan oxunur.
CREDIT_EXHAUSTED_MESSAGE = (
    "[models] Bad Request Error, Error code: 400 - {'type': 'error', 'error': "
    "{'type': 'invalid_request_error', 'message': 'Your credit balance is too low "
    "to access the Anthropic API. Please go to Plans & Billing to upgrade or "
    "purchase credits.'}, 'request_id': 'req_011CeTzFiqDQ7E5iMWnKGFD6'}"
)

#: Eyni zərf, 429 ilə — Dify loglarında rate limit belə görünür.
RATE_LIMIT_MESSAGE = (
    "[models] Rate Limit Error, Error code: 429 - {'type': 'error', 'error': "
    "{'type': 'rate_limit_error', 'message': 'Number of request tokens has "
    "exceeded your per-minute rate limit.'}}"
)

#: 529 — upstream overloaded. Gözləməklə keçir, kodu isə eynidir.
OVERLOADED_MESSAGE = (
    "[models] Api Server Overloaded Error, Error code: 529 - {'type': 'error', "
    "'error': {'type': 'overloaded_error', 'message': 'Overloaded'}}"
)


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

    def _send(
        self, status: int, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _unauthorized(self) -> None:
        status, payload = _dify_error(
            "unauthorized",
            "Authorization header must be provided and start with 'Bearer'",
            401,
        )
        self._send(status, payload)

    def _write_chunk(self, data: bytes) -> None:
        self.wfile.write(f"{len(data):X}\r\n".encode("ascii"))
        self.wfile.write(data)
        self.wfile.write(b"\r\n")
        self.wfile.flush()

    def _stream(self, lines: Iterator[str], truncate: bool) -> None:
        """`text/event-stream` chunked cavabı.

        `truncate=True` olanda yekun 0-chunk GÖNDƏRİLMİR və bağlantı kəsilir —
        adapterdə `stream_incomplete` yolunu sınamaq üçün.
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for line in lines:
            self._write_chunk(line.encode("utf-8"))
        if truncate:
            self.close_connection = True
            try:
                self.wfile.flush()
                self.connection.close()
            except OSError:
                pass
            return
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

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
        outcome = self.script.chat(body)
        if outcome.http_error is not None:
            status, payload = outcome.http_error
            self._send(status, payload, outcome.http_headers)
            return
        self._stream(outcome.lines(), outcome.truncate)


class _Server(ThreadingHTTPServer):
    """`truncate` ssenarisində bağlantı qəsdən qırılır — stack trace çap etmirik."""

    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        pass


class _ChatOutcome:
    def __init__(
        self,
        events: list[dict[str, Any]] | None = None,
        http_error: tuple[int, dict[str, Any]] | None = None,
        truncate: bool = False,
        malformed: bool = False,
        http_headers: dict[str, str] | None = None,
    ) -> None:
        self.events = events or []
        self.http_error = http_error
        self.truncate = truncate
        self.malformed = malformed
        # `Retry-After` — hədəf nə qədər gözləməyi özü deyir (AP-024).
        self.http_headers = http_headers or {}

    def lines(self) -> Iterator[str]:
        events = self.events
        if self.truncate:
            # axın `message_end`-ə çatmadan kəsilir
            events = [e for e in events if e.get("event") != "message_end"]
        for event in events:
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        if self.malformed:
            yield "data: {bu JSON deyil\n\n"
        if self.truncate:
            yield 'data: {"event": "agent_mess'  # sətrin ortasında kəsilir


class MockDifyServer:
    """Skriptləşdirilmiş Dify stub-u.

    `scripted` formatı — açar sorğunun içində axtarılan alt sətir, dəyər:
        {
          "answer": str,                      # parçalara bölünüb axına verilir
          "retrieved": [{"chunk_id","document","content","score"}],
          "tool_calls": [{"name","arguments","result"}],
          "parallel_tools": bool,             # hamısı BİR thought-da (`;` ilə)
          "usage": {"prompt_tokens","completion_tokens"},
          "delay_ms": int,
          "side_effect": callable(body) -> dict | None,  # real yan təsir (tool servisi)
          "error": ("code","message",status),  # HTTP səviyyəsində Dify xəta zərfi
          "error_event": ("code","message",status),  # axın ORTASINDA `error` event-i
          "times": int,                        # xəta yalnız İLK N sorğuda verilir,
                                               # sonra normal cavab gəlir (backoff testi)
          "retry_after": str,                  # `Retry-After` başlığı (HTTP xətası ilə)
          "usage_before_error": bool,          # `error_event`-dən ƏVVƏL `message_end`
                                               # (tokenlər yandı, cavab sındı)
          "no_message_end": bool,              # `message_end` göndərilmir
          "no_conversation_id": bool,          # event-lərdə `conversation_id` boş gəlir
                                               # (çoxnövbəli zəncirin qırılması)
          "truncate": bool,                    # axın yarımçıq kəsilir
          "malformed": bool,                   # parse olunmayan `data:` sətri
          "ping": bool,                        # `ping` event-ləri qarışdırılır
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
        #: `times: N` sayğacı (skript açarı -> neçə dəfə xəta verildi).
        self._error_counts: dict[str, int] = {}
        self.request_log: list[dict[str, Any]] = []
        self._httpd = _Server((host, port), _Handler)
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
    def _match(self, query: str) -> tuple[str, dict[str, Any]]:
        q = query.lower()
        for needle, spec in self.scripted.items():
            if needle.lower() in q:
                return needle, spec
        return "", self.default

    def _error_expired(self, needle: str, spec: dict[str, Any]) -> bool:
        """`times: N` — xəta yalnız ilk N sorğuda verilir.

        Backoff testinin şərti budur: hədəf bir müddət 429 qaytarır, sonra
        özünə gəlir. Sayğac skript açarına görə aparılır.
        """
        limit = spec.get("times")
        if limit is None:
            return False
        seen = self._error_counts.get(needle, 0)
        if seen >= int(limit):
            return True
        self._error_counts[needle] = seen + 1
        return False

    def messages_for(self, conversation_id: str) -> list[dict[str, Any]]:
        return self._conversations.get(conversation_id, [])

    def chat(self, body: dict[str, Any]) -> _ChatOutcome:
        self.request_log.append(body)
        query = body.get("query", "")
        if not body.get("user"):
            return _ChatOutcome(http_error=_dify_error("invalid_param", "user is required", 400))
        if body.get("response_mode") != "streaming":
            return _ChatOutcome(http_error=_dify_error(*BLOCKING_REJECTION))

        needle, matched = self._match(query)
        spec = dict(matched)
        expired = self._error_expired(needle, spec)
        if expired:
            # Hədəf özünə gəldi: xəta təlimatları düşür, normal cavab qalır.
            spec.pop("error", None)
            spec.pop("error_event", None)
        if "error" in spec:
            headers = (
                {"Retry-After": str(spec["retry_after"])} if spec.get("retry_after") else {}
            )
            return _ChatOutcome(http_error=_dify_error(*spec["error"]), http_headers=headers)

        # Söhbət id-si BURADA həll olunur, `side_effect`-dən ƏVVƏL: real Dify-da
        # da yeni söhbətin id-si cavab hazırlanarkən mövcuddur. Beləcə skript
        # tarixçəni id üzrə saxlaya bilir (çoxnövbəli testlər üçün şərtdir).
        # `request_log` isə GÖNDƏRİLƏN xam dəyəri saxlayır (ilk növbədə "").
        resolved = {**body, "conversation_id": body.get("conversation_id") or str(uuid.uuid4())}

        side_effect = spec.get("side_effect")
        if callable(side_effect):
            override = side_effect(resolved)
            if isinstance(override, dict):
                spec.update(override)

        if spec.get("delay_ms"):
            time.sleep(spec["delay_ms"] / 1000.0)

        return _ChatOutcome(
            events=self._events(query, resolved, spec),
            truncate=bool(spec.get("truncate")),
            malformed=bool(spec.get("malformed")),
        )

    # ---- event qurucusu ---------------------------------------------
    def _events(
        self, query: str, body: dict[str, Any], spec: dict[str, Any]
    ) -> list[dict[str, Any]]:
        conversation_id = body.get("conversation_id") or str(uuid.uuid4())
        message_id = str(uuid.uuid4())
        task_id = str(uuid.uuid4())
        base = {
            # `no_conversation_id`: hədəf id qaytarmır -> adapter çoxnövbəli
            # zənciri qura bilmir və bunu ADLA bildirməlidir, susmamalıdır.
            "conversation_id": "" if spec.get("no_conversation_id") else conversation_id,
            "message_id": message_id,
            "task_id": task_id,
            "created_at": int(time.time()),
        }
        events: list[dict[str, Any]] = []

        tool_calls = list(spec.get("tool_calls", []))
        groups = (
            [tool_calls] if spec.get("parallel_tools") and tool_calls else [[t] for t in tool_calls]
        )
        for position, group in enumerate(groups, start=1):
            thought_id = str(uuid.uuid4())
            names = ";".join(t["name"] for t in group)
            tool_input = json.dumps({t["name"]: t.get("arguments", {}) for t in group})
            observation = json.dumps(
                {t["name"]: json.dumps(t.get("result")) for t in group}
            )
            common = {
                **base,
                "event": "agent_thought",
                "id": thought_id,
                "position": position,
                "thought": "",
                "message_files": [],
                "tool_labels": {t["name"]: {"en_US": t["name"]} for t in group},
            }
            # canlı davranış: əvvəl observation-suz, sonra observation ilə
            events.append({**common, "tool": names, "tool_input": tool_input, "observation": ""})
            events.append(
                {**common, "tool": names, "tool_input": tool_input, "observation": observation}
            )
            if spec.get("ping"):
                events.append({"event": "ping"})

        answer = spec.get("answer", "")
        for piece in _split(answer):
            events.append({**base, "event": "agent_message", "id": message_id, "answer": piece})

        if spec.get("error_event"):
            code, message, status = spec["error_event"]
            if spec.get("usage_before_error"):
                # `message_end` GƏLDİ (tokenlər yandı), sonra axın xəta ilə
                # bitdi. Bu tokenlərin xərci itməməlidir (AP-026).
                events.append(
                    {
                        **base,
                        "event": "message_end",
                        "id": message_id,
                        "files": [],
                        "metadata": {
                            "usage": _usage_payload(
                                spec.get("usage", {"prompt_tokens": 900, "completion_tokens": 40})
                            ),
                            "retriever_resources": [],
                        },
                    }
                )
            events.append(
                {
                    "event": "error",
                    "task_id": task_id,
                    "message_id": message_id,
                    "status": status,
                    "code": code,
                    "message": message,
                }
            )
            return events

        retriever_resources = _resources(spec.get("retrieved", []))
        self._conversations.setdefault(conversation_id, []).append(
            {
                "id": message_id,
                "conversation_id": conversation_id,
                "query": query,
                "answer": answer,
                "agent_thoughts": [e for e in events if e.get("event") == "agent_thought"],
                "retriever_resources": retriever_resources,
                "created_at": int(time.time()),
            }
        )

        if not spec.get("no_message_end"):
            usage_spec = spec.get("usage", {"prompt_tokens": 1800, "completion_tokens": 250})
            events.append(
                {
                    **base,
                    "event": "message_end",
                    "id": message_id,
                    "files": [],
                    "metadata": {
                        "usage": _usage_payload(usage_spec),
                        "retriever_resources": retriever_resources,
                    },
                }
            )
        return events


def _split(answer: str, n: int = 3) -> list[str]:
    """Cavabı bir neçə `agent_message` parçasına bölür (real axın parçalıdır)."""
    if not answer:
        return []
    size = max(1, len(answer) // n + 1)
    return [answer[i : i + size] for i in range(0, len(answer), size)]


def _resources(retrieved: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            # canlı formatda `position` və `score` STRING-dir
            "position": str(i + 1),
            "dataset_id": "ds-mock",
            "dataset_name": "Aurora Goods KB",
            "document_id": r.get("chunk_id", ""),
            "document_name": r.get("document", ""),
            "data_source_type": "upload_file",
            "segment_id": r.get("chunk_id", ""),
            "retriever_from": "api",
            "score": str(r.get("score", 0.0)),
            "content": r.get("content", ""),
        }
        for i, r in enumerate(retrieved)
    ]


def _usage_payload(usage_spec: dict[str, Any]) -> dict[str, Any]:
    prompt = int(usage_spec.get("prompt_tokens", 0))
    completion = int(usage_spec.get("completion_tokens", 0))
    prompt_price = prompt * 3 / 1_000_000
    completion_price = completion * 15 / 1_000_000
    # ⚠️ model adı QƏSDƏN yoxdur — canlı Dify də vermir (PLAN.md risk #2)
    return {
        "prompt_tokens": prompt,
        "prompt_unit_price": "3",
        "prompt_price_unit": "0.000001",
        "prompt_price": f"{prompt_price:.6f}",
        "completion_tokens": completion,
        "completion_unit_price": "15",
        "completion_price_unit": "0.000001",
        "completion_price": f"{completion_price:.6f}",
        "total_tokens": prompt + completion,
        "total_price": f"{prompt_price + completion_price:.6f}",
        "currency": "USD",
        "latency": 0.42,
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
