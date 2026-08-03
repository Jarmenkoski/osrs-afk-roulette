"""OSRS AFK Roulette — shared leaderboard API.

Tiny Flask + SQLite backend. The static frontend on GitHub Pages posts
done/skip events here and reads the shared leaderboard.
"""
import datetime
import json
import os
import re
import sqlite3
import time
import urllib.request
from zoneinfo import ZoneInfo

from flask import Flask, g, jsonify, request

DB_PATH = os.environ.get("DB_PATH", "/data/afk.db")
# Channel webhook lives only on the server (.env) so the whole group can post
# without configuring anything in their browser.
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
SITE_BASE = "https://afk.rosu.fi"
ANNOUNCE_COOLDOWN_S = 30
ALLOWED_ORIGINS = {
    "https://afk.rosu.fi",
    "https://jarmenkoski.github.io",
}
TZ = ZoneInfo("Europe/Helsinki")

NICK_RE = re.compile(r"^[A-Za-z0-9 _-]{1,12}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SKILLS = {
    "attack", "strength", "defence", "hitpoints", "ranged", "prayer", "magic",
    "cooking", "woodcutting", "fletching", "fishing", "firemaking", "crafting",
    "smithing", "mining", "herblore", "agility", "thieving", "slayer",
    "farming", "runecraft", "hunter", "construction", "sailing",
}

app = Flask(__name__)


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    con = g.pop("db", None)
    if con is not None:
        con.close()


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          nick TEXT NOT NULL,
          nick_key TEXT NOT NULL,
          d TEXT NOT NULL,
          task TEXT NOT NULL,
          skill TEXT NOT NULL,
          status TEXT NOT NULL CHECK (status IN ('done', 'skipped')),
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uniq_done_per_day
          ON events(nick_key, d) WHERE status = 'done';
        CREATE INDEX IF NOT EXISTS idx_nick ON events(nick_key);
        CREATE TABLE IF NOT EXISTS announce_times (
          nick_key TEXT PRIMARY KEY,
          ts REAL NOT NULL
        );
        """
    )
    con.commit()
    con.close()


@app.after_request
def cors(resp):
    origin = request.headers.get("Origin", "")
    if origin in ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Max-Age"] = "86400"
    return resp


@app.route("/api/<path:_sub>", methods=["OPTIONS"])
def preflight(_sub):
    return "", 204


def today():
    return datetime.datetime.now(TZ).date()


def parse_date(s):
    if not isinstance(s, str) or not DATE_RE.match(s):
        return None
    try:
        d = datetime.date.fromisoformat(s)
    except ValueError:
        return None
    # Reject dates far from server time (bad clocks / junk), allow client tz wiggle.
    if abs((d - today()).days) > 2:
        return None
    return d


def validate_event(e):
    if not isinstance(e, dict):
        return None
    nick = (e.get("nick") or "").strip()
    task = (e.get("task") or "").strip()
    skill = (e.get("skill") or "").strip().lower()
    status = (e.get("status") or "").strip().lower()
    d = parse_date(e.get("date") or "")
    if not NICK_RE.match(nick) or not task or len(task) > 80:
        return None
    if skill not in SKILLS or status not in ("done", "skipped") or d is None:
        return None
    return {
        "nick": nick,
        "nick_key": nick.lower().replace("_", " ").replace("-", " "),
        "d": d.isoformat(),
        "task": task,
        "skill": skill,
        "status": status,
    }


def insert_event(ev):
    """Returns True if the row was inserted (done-per-day dupes are ignored)."""
    con = db()
    cur = con.execute(
        """INSERT OR IGNORE INTO events (nick, nick_key, d, task, skill, status)
           VALUES (:nick, :nick_key, :d, :task, :skill, :status)""",
        ev,
    )
    con.commit()
    return cur.rowcount > 0


def streaks(done_days):
    """(current, best) from a sorted list of ISO date strings with a done task."""
    best = run = 0
    prev = None
    for s in done_days:
        d = datetime.date.fromisoformat(s)
        run = run + 1 if (prev is not None and (d - prev).days == 1) else 1
        best = max(best, run)
        prev = d
    current = 0
    if done_days:
        last = datetime.date.fromisoformat(done_days[-1])
        if (today() - last).days <= 1:
            current = 1
            for i in range(len(done_days) - 1, 0, -1):
                a = datetime.date.fromisoformat(done_days[i])
                b = datetime.date.fromisoformat(done_days[i - 1])
                if (a - b).days == 1:
                    current += 1
                else:
                    break
    return current, best


@app.get("/api/health")
def health():
    db().execute("SELECT 1")
    return jsonify({"ok": True})


@app.post("/api/events")
def add_event():
    ev = validate_event(request.get_json(silent=True))
    if ev is None:
        return jsonify({"ok": False, "error": "invalid event"}), 400
    inserted = insert_event(ev)
    return jsonify({"ok": True, "inserted": inserted})


@app.post("/api/events/bulk")
def add_events_bulk():
    body = request.get_json(silent=True)
    events = body.get("events") if isinstance(body, dict) else None
    if not isinstance(events, list) or len(events) > 1000:
        return jsonify({"ok": False, "error": "invalid bulk payload"}), 400
    inserted = 0
    for raw in events:
        e = dict(raw) if isinstance(raw, dict) else {}
        # Bulk sync may contain old dates from localStorage — accept any sane past date.
        d = e.get("date") or e.get("d") or ""
        try:
            parsed = datetime.date.fromisoformat(d) if isinstance(d, str) else None
        except ValueError:
            parsed = None
        if parsed is not None and (parsed - today()).days <= 2:
            ev = validate_event({**e, "date": today().isoformat()})
            if ev is not None:
                ev["d"] = parsed.isoformat()  # keep the original historical date
                if insert_event(ev):
                    inserted += 1
    return jsonify({"ok": True, "inserted": inserted})


@app.get("/api/leaderboard")
def leaderboard():
    rows = db().execute(
        """SELECT nick_key, MAX(nick) AS nick,
                  SUM(status = 'done') AS done,
                  SUM(status = 'skipped') AS skips,
                  MAX(d) AS last_date
           FROM events GROUP BY nick_key"""
    ).fetchall()
    players = []
    for r in rows:
        days = [
            x["d"]
            for x in db().execute(
                "SELECT DISTINCT d FROM events WHERE nick_key = ? AND status = 'done' ORDER BY d",
                (r["nick_key"],),
            )
        ]
        current, best = streaks(days)
        by_skill = {
            x["skill"]: x["n"]
            for x in db().execute(
                """SELECT skill, COUNT(*) AS n FROM events
                   WHERE nick_key = ? AND status = 'done' GROUP BY skill""",
                (r["nick_key"],),
            )
        }
        players.append(
            {
                "nick": r["nick"],
                "done": r["done"] or 0,
                "skips": r["skips"] or 0,
                "current": current,
                "best": best,
                "lastDate": r["last_date"],
                "bySkill": by_skill,
            }
        )
    players.sort(key=lambda p: (-p["current"], -p["done"], p["skips"]))
    return jsonify({"players": players})


@app.post("/api/announce")
def announce():
    """Build the daily-task embed server-side and post it to the channel webhook."""
    if not DISCORD_WEBHOOK_URL:
        return jsonify({"ok": False, "error": "webhook not configured"}), 503
    body = request.get_json(silent=True) or {}
    nick = (body.get("nick") or "").strip()
    t = body.get("task") if isinstance(body.get("task"), dict) else {}
    name = (t.get("name") or "").strip()
    skill = (t.get("skill") or "").strip().lower()
    afk = (t.get("afk") or "").strip()[:20]
    reqs = (t.get("reqs") or "").strip()[:200]
    notes = (t.get("notes") or "").strip()[:200]
    wiki = (t.get("url") or "").strip()
    if not NICK_RE.match(nick) or not name or len(name) > 80 or skill not in SKILLS:
        return jsonify({"ok": False, "error": "invalid payload"}), 400
    if not wiki.startswith("https://oldschool.runescape.wiki/"):
        wiki = ""

    # Cooldown lives in SQLite so it is shared across gunicorn workers.
    key = nick.lower().replace("_", " ").replace("-", " ")
    now = time.time()
    con = db()
    row = con.execute("SELECT ts FROM announce_times WHERE nick_key = ?", (key,)).fetchone()
    if row is not None and now - row["ts"] < ANNOUNCE_COOLDOWN_S:
        return jsonify({"ok": False, "error": "cooldown"}), 429
    con.execute(
        "INSERT INTO announce_times (nick_key, ts) VALUES (?, ?) "
        "ON CONFLICT(nick_key) DO UPDATE SET ts = excluded.ts",
        (key, now),
    )
    con.commit()

    row = db().execute(
        """SELECT SUM(status = 'done') AS done, SUM(status = 'skipped') AS skips
           FROM events WHERE nick_key = ?""",
        (key,),
    ).fetchone()
    days = [
        x["d"]
        for x in db().execute(
            "SELECT DISTINCT d FROM events WHERE nick_key = ? AND status = 'done' ORDER BY d",
            (key,),
        )
    ]
    current, _best = streaks(days)

    fields = [
        {"name": "Player", "value": nick, "inline": True},
        {"name": "Skill", "value": skill.capitalize(), "inline": True},
    ]
    if afk:
        fields.append({"name": "AFK time", "value": f"~{afk}", "inline": True})
    if reqs:
        fields.append({"name": "Requirements", "value": reqs, "inline": False})
    if notes:
        fields.append({"name": "Note", "value": notes, "inline": False})
    fields += [
        {"name": "🔥 Streak", "value": f"{current} days", "inline": True},
        {"name": "✅ Done", "value": str(row["done"] or 0), "inline": True},
        {"name": "⏭️ Skips", "value": str(row["skips"] or 0), "inline": True},
    ]
    payload = {
        "username": "AFK Roulette",
        "embeds": [{
            "title": f"🎡 Today's AFK task: {name}",
            **({"url": wiki} if wiki else {}),
            "color": 0xF5C542,
            "thumbnail": {"url": f"{SITE_BASE}/icons/{skill}.png"},
            "fields": fields,
            "footer": {"text": "OSRS AFK Roulette"},
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }],
    }
    req = urllib.request.Request(
        DISCORD_WEBHOOK_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "osrs-afk-roulette"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception:
        return jsonify({"ok": False, "error": "discord post failed"}), 502
    return jsonify({"ok": True})


@app.get("/api/history")
def history():
    nick = (request.args.get("nick") or "").strip()
    if not NICK_RE.match(nick):
        return jsonify({"ok": False, "error": "invalid nick"}), 400
    try:
        limit = min(max(int(request.args.get("limit", 15)), 1), 100)
    except ValueError:
        limit = 15
    key = nick.lower().replace("_", " ").replace("-", " ")
    rows = db().execute(
        """SELECT d, task, skill, status FROM events
           WHERE nick_key = ? ORDER BY d DESC, id DESC LIMIT ?""",
        (key, limit),
    ).fetchall()
    return jsonify({"entries": [dict(r) for r in rows]})


init_db()
