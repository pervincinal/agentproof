#!/usr/bin/env python3
"""AgentProof board CLI — agentlər tapşırıqları buradan idarə edir.

  task.py list [--status S] [--assignee A]
  task.py show <id>
  task.py create --title T --desc D [--role R] [--prio P] [--status S] [--links a,b]
  task.py assign <id> <assignee>
  task.py move <id> <status> [--note N]
  task.py comment <id> <text>

Statuslar: backlog todo in_progress review testing blocked done
"""
import argparse, fcntl, json, os, sys, time
from pathlib import Path

STORE = Path(__file__).resolve().parent / "tasks.json"
STATUSES = ["backlog", "todo", "in_progress", "review", "testing", "blocked", "done"]
PRIOS = ["P0", "P1", "P2", "P3"]


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class Store:
    """tasks.json üzərində fayl kilidi ilə atomik əməliyyat."""

    def __enter__(self):
        STORE.parent.mkdir(parents=True, exist_ok=True)
        if not STORE.exists():
            STORE.write_text('{"seq": 0, "tasks": []}')
        self.fh = open(STORE, "r+")
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        self.data = json.load(self.fh)
        return self

    def __exit__(self, *a):
        if a[0] is None:
            self.fh.seek(0)
            self.fh.truncate()
            json.dump(self.data, self.fh, ensure_ascii=False, indent=1)
            self.fh.flush()
        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()

    def find(self, tid):
        for t in self.data["tasks"]:
            if t["id"] == tid:
                return t
        sys.exit(f"tapilmadi: {tid}")


def log(t, actor, action, detail=""):
    t.setdefault("history", []).append(
        {"at": _now(), "actor": actor, "action": action, "detail": detail})
    t["updated"] = _now()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    ap.add_argument("--actor", default=os.environ.get("AGENTPROOF_ACTOR", "unknown"))

    p = sub.add_parser("list"); p.add_argument("--status"); p.add_argument("--assignee")
    p = sub.add_parser("show"); p.add_argument("id")
    p = sub.add_parser("create")
    p.add_argument("--title", required=True); p.add_argument("--desc", default="")
    p.add_argument("--role", default=""); p.add_argument("--prio", default="P2", choices=PRIOS)
    p.add_argument("--status", default="backlog", choices=STATUSES)
    p.add_argument("--links", default=""); p.add_argument("--dod", default="")
    p = sub.add_parser("assign"); p.add_argument("id"); p.add_argument("assignee")
    p = sub.add_parser("move"); p.add_argument("id")
    p.add_argument("status", choices=STATUSES); p.add_argument("--note", default="")
    p = sub.add_parser("comment"); p.add_argument("id"); p.add_argument("text")

    a = ap.parse_args()
    with Store() as s:
        if a.cmd == "list":
            for t in s.data["tasks"]:
                if a.status and t["status"] != a.status: continue
                if a.assignee and t.get("assignee") != a.assignee: continue
                print(f'{t["id"]:8s} {t["prio"]:3s} {t["status"]:12s} '
                      f'{(t.get("assignee") or "-"):14s} {t["title"][:60]}')
        elif a.cmd == "show":
            print(json.dumps(s.find(a.id), ensure_ascii=False, indent=1))
        elif a.cmd == "create":
            s.data["seq"] += 1
            tid = f'AP-{s.data["seq"]:03d}'
            t = {"id": tid, "title": a.title, "desc": a.desc, "role": a.role,
                 "prio": a.prio, "status": a.status, "assignee": None,
                 "dod": a.dod, "links": [x for x in a.links.split(",") if x],
                 "created": _now(), "updated": _now(), "history": [], "comments": []}
            log(t, a.actor, "created")
            s.data["tasks"].append(t)
            print(tid)
        elif a.cmd == "assign":
            t = s.find(a.id); t["assignee"] = a.assignee
            log(t, a.actor, "assigned", a.assignee)
            print(f'{a.id} → {a.assignee}')
        elif a.cmd == "move":
            t = s.find(a.id); old = t["status"]
            if a.status == "blocked" and not a.note:
                sys.exit("blocked ucun --note MECBURIDIR (niye bloklandi)")
            t["status"] = a.status
            log(t, a.actor, f"{old}→{a.status}", a.note)
            print(f'{a.id} {old} → {a.status}')
        elif a.cmd == "comment":
            t = s.find(a.id)
            t.setdefault("comments", []).append(
                {"at": _now(), "actor": a.actor, "text": a.text})
            log(t, a.actor, "comment")
            print("ok")


if __name__ == "__main__":
    main()
