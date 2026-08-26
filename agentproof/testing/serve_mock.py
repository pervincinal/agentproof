"""Mock Dify serverini ayrıca prosesdə qaldırır — CLI-ı açarsız sınamaq üçün.

    python -m agentproof.testing.serve_mock --port 8099
    DIFY_BASE_URL=http://127.0.0.1:8099/v1 DIFY_API_KEY=app-mock-000000000000000000000000 \
      python evals/run.py --target dify_http --dataset evals/datasets/spike.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agentproof.testing.mock_dify import DEFAULT_API_KEY, MockDifyServer, aurora_fixture


def main() -> int:
    p = argparse.ArgumentParser(description="Mock Dify Service API")
    p.add_argument("--port", type=int, default=8099)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--script", default=None, help="JSON fayl: {sual_parçası: cavab_spesifikasiyası}")
    p.add_argument("--break-restocking", action="store_true",
                   help="qəsdən yanlış siyasət rəqəmi qaytar (reqressiya nümayişi)")
    args = p.parse_args()

    scripted = json.loads(Path(args.script).read_text()) if args.script else aurora_fixture()
    if args.break_restocking:
        scripted["restocking"]["answer"] = "Qaytarma pəncərəsi 45 gündür, haqq 20%-dir."

    server = MockDifyServer(scripted=scripted, host=args.host, port=args.port).start()
    print(f"mock Dify: {server.base_url}")
    print(f"api key  : {DEFAULT_API_KEY}", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
