"""OSRS AFK Roulette — shared leaderboard API.

Tiny Flask + SQLite backend. The static frontend on GitHub Pages posts
done/skip events here and reads the shared leaderboard.
"""
import datetime
import json
import os
import random
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from flask import Flask, g, jsonify, request
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

DB_PATH = os.environ.get("DB_PATH", "/data/afk.db")
# Channel webhook lives only on the server (.env) so the whole group can post
# without configuring anything in their browser.
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
SITE_BASE = "https://afk.rosu.fi"
# Discord slash-command app (/afk) — HTTP interactions, no gateway bot needed.
DISCORD_APP_ID = os.environ.get("DISCORD_APP_ID", "")
DISCORD_PUBLIC_KEY = os.environ.get("DISCORD_PUBLIC_KEY", "")
LEVELS_CACHE_S = 12 * 3600

ANNOUNCE_COOLDOWN_S = 30
SUGGEST_COOLDOWN_S = 60
FOR_VOTES_TO_APPROVE = 2
AGAINST_VOTES_TO_REJECT = 2
WIKI_PREFIX = "https://oldschool.runescape.wiki/"
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

with open(os.path.join(os.path.dirname(__file__), "tasks.json"), encoding="utf-8") as _f:
    BUILTIN_TASKS = json.load(_f)

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
        CREATE TABLE IF NOT EXISTS suggestions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          skill TEXT NOT NULL,
          afk TEXT NOT NULL DEFAULT '',
          notes TEXT NOT NULL DEFAULT '',
          url TEXT NOT NULL DEFAULT '',
          f2p INTEGER NOT NULL DEFAULT 0,
          reqs TEXT NOT NULL,
          suggested_by TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'approved', 'rejected')),
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS suggestion_votes (
          suggestion_id INTEGER NOT NULL,
          nick_key TEXT NOT NULL,
          vote INTEGER NOT NULL CHECK (vote IN (1, -1)),
          PRIMARY KEY (suggestion_id, nick_key)
        );
        CREATE TABLE IF NOT EXISTS discord_links (
          discord_id TEXT PRIMARY KEY,
          nick TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS daily_rolls (
          nick_key TEXT NOT NULL,
          d TEXT NOT NULL,
          task TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done')),
          PRIMARY KEY (nick_key, d)
        );
        CREATE TABLE IF NOT EXISTS player_levels (
          nick_key TEXT PRIMARY KEY,
          nick TEXT NOT NULL,
          levels TEXT NOT NULL,
          updated_at REAL NOT NULL
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


def insert_event(con, ev):
    """Returns True if the row was inserted (done-per-day dupes are ignored)."""
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
    inserted = insert_event(db(), ev)
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
                if insert_event(db(), ev):
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


def discord_post(payload):
    """Post a payload to the channel webhook. Returns True on success."""
    if not DISCORD_WEBHOOK_URL:
        return False
    req = urllib.request.Request(
        DISCORD_WEBHOOK_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "osrs-afk-roulette"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True
    except Exception:
        return False


def check_cooldown(key, seconds):
    """Shared per-key cooldown in SQLite (gunicorn workers share no memory).
    Returns True if allowed (and stamps the key), False if still cooling down."""
    now = time.time()
    con = db()
    row = con.execute("SELECT ts FROM announce_times WHERE nick_key = ?", (key,)).fetchone()
    if row is not None and now - row["ts"] < seconds:
        return False
    con.execute(
        "INSERT INTO announce_times (nick_key, ts) VALUES (?, ?) "
        "ON CONFLICT(nick_key) DO UPDATE SET ts = excluded.ts",
        (key, now),
    )
    con.commit()
    return True


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

    key = nick.lower().replace("_", " ").replace("-", " ")
    if not check_cooldown(key, ANNOUNCE_COOLDOWN_S):
        return jsonify({"ok": False, "error": "cooldown"}), 429

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
    if not discord_post(payload):
        return jsonify({"ok": False, "error": "discord post failed"}), 502
    return jsonify({"ok": True})


def validate_suggestion(body):
    if not isinstance(body, dict):
        return None, "invalid payload"
    nick = (body.get("nick") or "").strip()
    name = (body.get("name") or "").strip()
    skill = (body.get("skill") or "").strip().lower()
    afk = (body.get("afk") or "").strip()[:20]
    notes = (body.get("notes") or "").strip()[:200]
    url = (body.get("url") or "").strip()[:200]
    f2p = 1 if body.get("f2p") else 0
    reqs_in = body.get("reqs")
    if not NICK_RE.match(nick):
        return None, "invalid nick"
    if not name or len(name) > 80:
        return None, "invalid name"
    if skill not in SKILLS:
        return None, "invalid skill"
    if url and not url.startswith(WIKI_PREFIX):
        return None, "wiki link must point to oldschool.runescape.wiki"
    reqs = {}
    if isinstance(reqs_in, dict):
        for k, v in reqs_in.items():
            k = str(k).strip().lower()
            if k not in SKILLS:
                continue
            try:
                lvl = int(v)
            except (TypeError, ValueError):
                continue
            if 1 <= lvl <= 99:
                reqs[k] = lvl
    if not reqs:
        return None, "at least one skill requirement is needed"
    if len(reqs) > 10:
        return None, "too many requirements"
    return {
        "nick": nick,
        "name": name,
        "skill": skill,
        "afk": afk,
        "notes": notes,
        "url": url,
        "f2p": f2p,
        "reqs": reqs,
    }, None


def suggestion_row_to_dict(r, my_key=None):
    con = db()
    up = con.execute(
        "SELECT COUNT(*) AS n FROM suggestion_votes WHERE suggestion_id = ? AND vote = 1",
        (r["id"],),
    ).fetchone()["n"]
    down = con.execute(
        "SELECT COUNT(*) AS n FROM suggestion_votes WHERE suggestion_id = ? AND vote = -1",
        (r["id"],),
    ).fetchone()["n"]
    my_vote = 0
    if my_key:
        v = con.execute(
            "SELECT vote FROM suggestion_votes WHERE suggestion_id = ? AND nick_key = ?",
            (r["id"], my_key),
        ).fetchone()
        my_vote = v["vote"] if v else 0
    return {
        "id": r["id"],
        "name": r["name"],
        "skill": r["skill"],
        "afk": r["afk"],
        "notes": r["notes"],
        "url": r["url"],
        "f2p": bool(r["f2p"]),
        "reqs": json.loads(r["reqs"]),
        "by": r["suggested_by"],
        "status": r["status"],
        "up": up,
        "down": down,
        "myVote": my_vote,
    }


@app.post("/api/suggestions")
def add_suggestion():
    data, err = validate_suggestion(request.get_json(silent=True))
    if err:
        return jsonify({"ok": False, "error": err}), 400
    key = data["nick"].lower().replace("_", " ").replace("-", " ")
    con = db()
    dup = con.execute(
        "SELECT id FROM suggestions WHERE lower(name) = ? AND status IN ('pending', 'approved')",
        (data["name"].lower(),),
    ).fetchone()
    if dup:
        return jsonify({"ok": False, "error": "a suggestion with this name already exists"}), 409
    if not check_cooldown("sug:" + key, SUGGEST_COOLDOWN_S):
        return jsonify({"ok": False, "error": "cooldown"}), 429
    cur = con.execute(
        """INSERT INTO suggestions (name, skill, afk, notes, url, f2p, reqs, suggested_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (data["name"], data["skill"], data["afk"], data["notes"], data["url"],
         data["f2p"], json.dumps(data["reqs"]), data["nick"]),
    )
    con.commit()
    sid = cur.lastrowid

    req_str = ", ".join(f"{k.capitalize()} {v}" for k, v in sorted(data["reqs"].items()))
    fields = [
        {"name": "Suggested by", "value": data["nick"], "inline": True},
        {"name": "Skill", "value": data["skill"].capitalize(), "inline": True},
    ]
    if data["afk"]:
        fields.append({"name": "AFK time", "value": f"~{data['afk']}", "inline": True})
    fields.append({"name": "Requirements", "value": req_str, "inline": False})
    if data["notes"]:
        fields.append({"name": "Notes", "value": data["notes"], "inline": False})
    if data["url"]:
        fields.append({"name": "Wiki", "value": data["url"], "inline": False})
    discord_post({
        "username": "AFK Roulette",
        "embeds": [{
            "title": f"🗳️ New task suggestion: {data['name']}",
            "url": f"{SITE_BASE}/#suggestions",
            "description": f"Vote for or against at {SITE_BASE}/#suggestions — "
                           f"{FOR_VOTES_TO_APPROVE} 👍 approves it, {AGAINST_VOTES_TO_REJECT} 👎 rejects it.",
            "color": 0x2980B9,
            "thumbnail": {"url": f"{SITE_BASE}/icons/{data['skill']}.png"},
            "fields": fields,
            "footer": {"text": "OSRS AFK Roulette"},
        }],
    })
    return jsonify({"ok": True, "id": sid})


@app.get("/api/suggestions")
def list_suggestions():
    nick = (request.args.get("nick") or "").strip()
    my_key = nick.lower().replace("_", " ").replace("-", " ") if NICK_RE.match(nick) else None
    rows = db().execute(
        "SELECT * FROM suggestions WHERE status = 'pending' ORDER BY id DESC LIMIT 50"
    ).fetchall()
    return jsonify({"suggestions": [suggestion_row_to_dict(r, my_key) for r in rows]})


@app.post("/api/suggestions/<int:sid>/vote")
def vote_suggestion(sid):
    body = request.get_json(silent=True) or {}
    nick = (body.get("nick") or "").strip()
    vote = body.get("vote")
    if not NICK_RE.match(nick) or vote not in (1, -1):
        return jsonify({"ok": False, "error": "invalid vote"}), 400
    key = nick.lower().replace("_", " ").replace("-", " ")
    con = db()
    row = con.execute("SELECT * FROM suggestions WHERE id = ?", (sid,)).fetchone()
    if row is None:
        return jsonify({"ok": False, "error": "not found"}), 404
    if row["status"] != "pending":
        return jsonify({"ok": False, "error": "voting is closed"}), 409
    con.execute(
        "INSERT INTO suggestion_votes (suggestion_id, nick_key, vote) VALUES (?, ?, ?) "
        "ON CONFLICT(suggestion_id, nick_key) DO UPDATE SET vote = excluded.vote",
        (sid, key, vote),
    )
    con.commit()
    result = suggestion_row_to_dict(row, key)
    new_status = None
    if result["up"] >= FOR_VOTES_TO_APPROVE:
        new_status = "approved"
    elif result["down"] >= AGAINST_VOTES_TO_REJECT:
        new_status = "rejected"
    if new_status:
        con.execute("UPDATE suggestions SET status = ? WHERE id = ?", (new_status, sid))
        con.commit()
        result["status"] = new_status
        emoji, verdict = ("✅", "approved — it's in the task pool!") if new_status == "approved" \
            else ("❌", "rejected by vote.")
        discord_post({
            "username": "AFK Roulette",
            "embeds": [{
                "title": f"{emoji} Suggestion {new_status}: {row['name']}",
                "description": f"The community has spoken: {row['name']} was {verdict}",
                "color": 0x4CAF50 if new_status == "approved" else 0xC0392B,
                "thumbnail": {"url": f"{SITE_BASE}/icons/{row['skill']}.png"},
                "footer": {"text": "OSRS AFK Roulette"},
            }],
        })
    return jsonify({"ok": True, **result})


@app.get("/api/tasks/approved")
def approved_tasks():
    rows = db().execute(
        "SELECT * FROM suggestions WHERE status = 'approved' ORDER BY id"
    ).fetchall()
    return jsonify({
        "tasks": [{
            "name": r["name"],
            "skill": r["skill"],
            "afk": r["afk"],
            "notes": r["notes"],
            "url": r["url"],
            "f2p": bool(r["f2p"]),
            "reqs": json.loads(r["reqs"]),
            "suggestedBy": r["suggested_by"],
        } for r in rows]
    })


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


# ---------- Discord /afk slash command (HTTP interactions) ----------

def open_db():
    """Standalone connection for background threads (flask.g is request-bound)."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def norm_key(nick):
    return nick.lower().replace("_", " ").replace("-", " ")


def fetch_levels_wom(nick):
    """Fetch skill levels from the Wise Old Man API. Returns dict or None."""
    enc = urllib.parse.quote(nick)
    for method in ("GET", "POST"):
        req = urllib.request.Request(
            f"https://api.wiseoldman.net/v2/players/{enc}",
            headers={"User-Agent": "osrs-afk-roulette"},
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.load(resp)
            skills = ((data.get("latestSnapshot") or {}).get("data") or {}).get("skills") or {}
            levels = {}
            for k, v in skills.items():
                k = "runecraft" if k == "runecrafting" else k
                if k in SKILLS and isinstance(v.get("level"), int):
                    levels[k] = max(1, v["level"])
            if levels:
                return levels
        except urllib.error.HTTPError as e:
            if e.code == 404 and method == "GET":
                continue  # not tracked yet -> POST asks WOM to import the player
            return None
        except Exception:
            return None
    return None


def get_levels(con, nick):
    key = norm_key(nick)
    row = con.execute("SELECT levels, updated_at FROM player_levels WHERE nick_key = ?", (key,)).fetchone()
    if row is not None and time.time() - row["updated_at"] < LEVELS_CACHE_S:
        return json.loads(row["levels"])
    levels = fetch_levels_wom(nick)
    if levels is None:
        return json.loads(row["levels"]) if row is not None else None  # stale beats nothing
    con.execute(
        "INSERT INTO player_levels (nick_key, nick, levels, updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(nick_key) DO UPDATE SET nick = excluded.nick, "
        "levels = excluded.levels, updated_at = excluded.updated_at",
        (key, nick, json.dumps(levels), time.time()),
    )
    con.commit()
    return levels


def eligible_for(con, levels):
    approved = [{
        "name": r["name"], "skill": r["skill"], "afk": r["afk"], "notes": r["notes"],
        "url": r["url"], "reqs": json.loads(r["reqs"]),
    } for r in con.execute("SELECT * FROM suggestions WHERE status = 'approved'")]
    pool = BUILTIN_TASKS + approved
    return [t for t in pool
            if all(levels.get(s, 1) >= lvl for s, lvl in t["reqs"].items())]


def player_stats(con, key):
    row = con.execute(
        "SELECT SUM(status = 'done') AS done, SUM(status = 'skipped') AS skips "
        "FROM events WHERE nick_key = ?", (key,),
    ).fetchone()
    days = [x["d"] for x in con.execute(
        "SELECT DISTINCT d FROM events WHERE nick_key = ? AND status = 'done' ORDER BY d", (key,))]
    current, _ = streaks(days)
    return {"done": row["done"] or 0, "skips": row["skips"] or 0, "current": current}


def task_embed(con, nick, task, done):
    key = norm_key(nick)
    s = player_stats(con, key)
    req_str = ", ".join(f"{k.capitalize()} {v}" for k, v in sorted(task["reqs"].items()))
    url = task.get("url") or ""
    if url and not url.startswith("http"):
        url = WIKI_PREFIX.rstrip("/") + url
    fields = [
        {"name": "Player", "value": nick, "inline": True},
        {"name": "Skill", "value": task["skill"].capitalize(), "inline": True},
    ]
    if task.get("afk"):
        fields.append({"name": "AFK time", "value": f"~{task['afk']}", "inline": True})
    fields.append({"name": "Requirements", "value": req_str, "inline": False})
    if task.get("notes"):
        fields.append({"name": "Note", "value": task["notes"], "inline": False})
    fields += [
        {"name": "🔥 Streak", "value": f"{s['current']} days", "inline": True},
        {"name": "✅ Done", "value": str(s["done"]), "inline": True},
        {"name": "⏭️ Skips", "value": str(s["skips"]), "inline": True},
    ]
    return {
        "title": (f"✅ Done: {task['name']}" if done else f"🎡 Today's AFK task: {task['name']}"),
        **({"url": url} if url else {}),
        "color": 0x4CAF50 if done else 0xF5C542,
        "thumbnail": {"url": f"{SITE_BASE}/icons/{task['skill']}.png"},
        "fields": fields,
        "footer": {"text": "OSRS AFK Roulette · " + SITE_BASE.replace("https://", "")},
    }


def task_buttons(discord_id):
    return [{"type": 1, "components": [
        {"type": 2, "style": 3, "label": "✅ Done", "custom_id": f"afk:done:{discord_id}"},
        {"type": 2, "style": 2, "label": "⏭️ Skip", "custom_id": f"afk:skip:{discord_id}"},
    ]}]


def patch_original(token, payload):
    req = urllib.request.Request(
        f"https://discord.com/api/v10/webhooks/{DISCORD_APP_ID}/{token}/messages/@original",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "osrs-afk-roulette"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception:
        pass


def ephemeral(msg):
    return jsonify({"type": 4, "data": {"content": msg, "flags": 64}})


def finish_roll(token, discord_id, nick):
    con = open_db()
    try:
        key = norm_key(nick)
        levels = get_levels(con, nick)
        if levels is None:
            patch_original(token, {"content":
                f"Couldn't fetch hiscores for **{nick}** — check the name with `/afk nick:YourName`."})
            return
        d = today().isoformat()
        row = con.execute("SELECT * FROM daily_rolls WHERE nick_key = ? AND d = ?", (key, d)).fetchone()
        if row is not None:
            task = json.loads(row["task"])
            done = row["status"] == "done"
        else:
            elig = eligible_for(con, levels)
            if not elig:
                patch_original(token, {"content": f"No eligible tasks found for **{nick}**."})
                return
            task = random.choice(elig)
            done = False
            con.execute(
                "INSERT INTO daily_rolls (nick_key, d, task, status) VALUES (?, ?, ?, 'pending')",
                (key, d, json.dumps(task)),
            )
            con.commit()
        patch_original(token, {
            "embeds": [task_embed(con, nick, task, done)],
            "components": [] if done else task_buttons(discord_id),
        })
    finally:
        con.close()


def handle_slash(data):
    cmd = data.get("data", {})
    if cmd.get("name") != "afk":
        return ephemeral("Unknown command.")
    user = (data.get("member") or {}).get("user") or data.get("user") or {}
    discord_id = user.get("id", "")
    con = db()
    nick_opt = next((o.get("value", "") for o in cmd.get("options", []) if o.get("name") == "nick"), "").strip()
    if nick_opt:
        if not NICK_RE.match(nick_opt):
            return ephemeral("That doesn't look like a valid OSRS name (max 12 chars).")
        con.execute(
            "INSERT INTO discord_links (discord_id, nick) VALUES (?, ?) "
            "ON CONFLICT(discord_id) DO UPDATE SET nick = excluded.nick",
            (discord_id, nick_opt),
        )
        con.commit()
        nick = nick_opt
    else:
        row = con.execute("SELECT nick FROM discord_links WHERE discord_id = ?", (discord_id,)).fetchone()
        if row is None:
            return ephemeral("Tell me your OSRS name first: `/afk nick:YourName` (remembered after that).")
        nick = row["nick"]
    threading.Thread(target=finish_roll, args=(data["token"], discord_id, nick), daemon=True).start()
    return jsonify({"type": 5})  # deferred — finish_roll edits the message


def handle_button(data):
    custom_id = data.get("data", {}).get("custom_id", "")
    parts = custom_id.split(":")
    if len(parts) != 3 or parts[0] != "afk":
        return ephemeral("Unknown button.")
    action, owner_id = parts[1], parts[2]
    user = (data.get("member") or {}).get("user") or data.get("user") or {}
    if user.get("id") != owner_id:
        return ephemeral("Only the player who rolled this task can use these buttons.")
    con = db()
    link = con.execute("SELECT nick FROM discord_links WHERE discord_id = ?", (owner_id,)).fetchone()
    if link is None:
        return ephemeral("Link your OSRS name first: `/afk nick:YourName`.")
    nick = link["nick"]
    key = norm_key(nick)
    d = today().isoformat()
    row = con.execute("SELECT * FROM daily_rolls WHERE nick_key = ? AND d = ?", (key, d)).fetchone()
    if row is None:
        return ephemeral("No task rolled today — use `/afk` first.")
    task = json.loads(row["task"])

    if action == "done":
        if row["status"] != "done":
            insert_event(con, {"nick": nick, "nick_key": key, "d": d,
                               "task": task["name"], "skill": task["skill"], "status": "done"})
            con.execute("UPDATE daily_rolls SET status = 'done' WHERE nick_key = ? AND d = ?", (key, d))
            con.commit()
        return jsonify({"type": 7, "data": {
            "embeds": [task_embed(con, nick, task, True)], "components": [],
        }})

    # skip
    if row["status"] == "done":
        return ephemeral("Already done today — no take-backs! 😄")
    lv = con.execute("SELECT levels FROM player_levels WHERE nick_key = ?", (key,)).fetchone()
    if lv is None:
        return ephemeral("Levels not cached — use `/afk` first.")
    insert_event(con, {"nick": nick, "nick_key": key, "d": d,
                       "task": task["name"], "skill": task["skill"], "status": "skipped"})
    elig = eligible_for(con, json.loads(lv["levels"]))
    pool = [t for t in elig if t["name"] != task["name"]] or elig
    if not pool:
        return ephemeral("No other eligible tasks to skip to!")
    new_task = random.choice(pool)
    con.execute("UPDATE daily_rolls SET task = ? WHERE nick_key = ? AND d = ?",
                (json.dumps(new_task), key, d))
    con.commit()
    return jsonify({"type": 7, "data": {
        "embeds": [task_embed(con, nick, new_task, False)],
        "components": task_buttons(owner_id),
    }})


@app.post("/api/discord/interactions")
def discord_interactions():
    if not DISCORD_PUBLIC_KEY:
        return "not configured", 503
    sig = request.headers.get("X-Signature-Ed25519", "")
    ts = request.headers.get("X-Signature-Timestamp", "")
    body = request.get_data()
    try:
        VerifyKey(bytes.fromhex(DISCORD_PUBLIC_KEY)).verify(ts.encode() + body, bytes.fromhex(sig))
    except (BadSignatureError, ValueError):
        return "invalid request signature", 401
    data = json.loads(body)
    itype = data.get("type")
    if itype == 1:
        return jsonify({"type": 1})  # PING -> PONG (endpoint validation)
    if itype == 2:
        return handle_slash(data)
    if itype == 3:
        return handle_button(data)
    return ephemeral("Unsupported interaction.")


init_db()
