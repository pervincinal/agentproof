"""AgentProof canlı dashboard — qaçış vəziyyətini və repo sağlamlığını göstərir."""
import json, os, re, subprocess, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = Path("/tmp/fullrun3.log")
PORT = 8777


def sh(cmd, cwd=ROOT):
    try:
        return subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True,
                              text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def run_status():
    """Tam qaçışın gedişatını logdan oxuyur."""
    out = {"active": False, "done": 0, "total": 0, "accuracy": None,
           "retries": 0, "finished": False, "summary": None}
    if not LOG.exists():
        return out
    txt = LOG.read_text(errors="replace")
    steps = re.findall(r"Steps:\s+(\d+)/(\d+)\s+\d+%.*?accuracy:\s*([\d.]+|n/a).*?retries:\s*(\d+)", txt)
    if steps:
        d, t, acc, ret = steps[-1]
        out.update(done=int(d), total=int(t), retries=int(ret),
                   accuracy=None if acc == "n/a" else float(acc))
    out["active"] = bool(sh("pgrep -f 'evals/run.py' | head -1"))
    m = re.search(r"AgentProof · .*?RunRecord: \S+", txt, re.S)
    if m:
        out["finished"] = True
        out["summary"] = m.group(0)
    return out


def phases():
    """PLAN.md-dəki mərhələ cədvəlini oxuyur."""
    p = ROOT / "PLAN.md"
    rows = []
    if p.exists():
        for line in p.read_text(errors="replace").splitlines():
            if line.startswith("|") and line.count("|") >= 5:
                c = [x.strip() for x in line.strip("|").split("|")]
                if len(c) >= 5 and c[0].isdigit():
                    rows.append({"phase": c[0], "name": c[1], "role": c[2],
                                 "out": c[3], "status": c[4]})
    return rows


def counts():
    def n(path, pat):
        f = ROOT / path
        return len(re.findall(pat, f.read_text(errors="replace"), re.M)) if f.exists() else 0
    ds = ROOT / "evals/datasets/full.jsonl"
    cases = sum(1 for l in ds.read_text(errors="replace").splitlines()
                if l.lstrip().startswith("{")) if ds.exists() else 0
    tests = ""
    tf = Path("/tmp/pytest_full.txt")
    if tf.exists():
        m = re.search(r"(\d+) passed", tf.read_text(errors="replace"))
        tests = m.group(1) if m else ""
    return {"cases": cases, "tests": tests,
            "ops_findings": n("docs/OPS-FINDINGS.md", r"^## (OPS|VALID)-\d+"),
            "grader_audit": n("docs/GRADER-AUDIT.md", r"^## A-\d+")}


def board():
    """Board tapsiriqlari."""
    f = ROOT / "board" / "tasks.json"
    if not f.exists():
        return {"tasks": []}
    try:
        return json.loads(f.read_text(errors="replace"))
    except Exception:
        return {"tasks": []}


def move_task(tid, status, actor="board-ui"):
    """UI-dan status dəyişikliyi — CLI ilə eyni kilid yolundan keçir."""
    import subprocess
    r = subprocess.run(
        [str(ROOT / ".venv/bin/python"), str(ROOT / "board/task.py"),
         "--actor", actor, "move", tid, status],
        capture_output=True, text=True, cwd=ROOT, timeout=15)
    return {"ok": r.returncode == 0, "out": (r.stdout or r.stderr).strip()}


def commits():
    raw = sh("git log --pretty=format:'%h|%ar|%s' -12")
    out = []
    for l in raw.splitlines():
        p = l.split("|", 2)
        if len(p) == 3:
            out.append({"sha": p[0], "when": p[1], "msg": p[2]})
    return out


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        if not self.path.startswith("/api/move"):
            self.send_response(404); self.end_headers(); return
        n = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
            res = move_task(req.get("id", ""), req.get("status", ""))
        except Exception as e:
            res = {"ok": False, "out": str(e)}
        body = json.dumps(res).encode()
        self.send_response(200 if res["ok"] else 400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/board"):
            body = json.dumps(board()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
        elif self.path.startswith("/board"):
            body = (Path(__file__).parent / "board.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        elif self.path.startswith("/api/status"):
            body = json.dumps({"run": run_status(), "phases": phases(),
                               "counts": counts(), "commits": commits(),
                               "ts": time.time()}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
        else:
            body = (Path(__file__).parent / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print(f"AgentProof dashboard → http://localhost:{PORT}")
    HTTPServer(("127.0.0.1", PORT), H).serve_forever()
