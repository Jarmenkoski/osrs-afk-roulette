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
        CREATE TABLE IF NOT EXISTS tasker_active (
          nick_key TEXT NOT NULL,
          category TEXT NOT NULL,
          task TEXT NOT NULL,
          PRIMARY KEY (nick_key, category)
        );
        CREATE TABLE IF NOT EXISTS quest_flags (
          nick_key TEXT NOT NULL,
          quest TEXT NOT NULL,
          PRIMARY KEY (nick_key, quest)
        );
        CREATE TABLE IF NOT EXISTS tasker_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          nick TEXT NOT NULL,
          nick_key TEXT NOT NULL,
          category TEXT NOT NULL,
          task TEXT NOT NULL,
          status TEXT NOT NULL CHECK (status IN ('done', 'skipped')),
          d TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_tasker_events_nick ON tasker_events(nick_key);
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
    except urllib.error.HTTPError as e:
        print(f"patch_original HTTP {e.code}: {e.read()[:500]}", flush=True)
    except Exception as e:
        print(f"patch_original failed: {e!r}", flush=True)


def ephemeral(msg):
    return jsonify({"type": 4, "data": {"content": msg, "flags": 64}})


def finish_roll(token, discord_id, nick):
    try:
        _finish_roll(token, discord_id, nick)
    except Exception as e:
        print(f"finish_roll crashed: {e!r}", flush=True)
        patch_original(token, {"content": "Something went wrong rolling your task — try again."})


def _finish_roll(token, discord_id, nick):
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
        gif = None
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
            try:
                labels, widx = spin_labels([t["name"] for t in elig], task["name"])
                if len(labels) >= 2:
                    gif = make_spin_gif(labels, widx)
            except Exception as e:
                print(f"spin gif failed: {e!r}", flush=True)
        embed = task_embed(con, nick, task, done)
        components = [] if done else task_buttons(discord_id)
        if gif:
            embed["image"] = {"url": "attachment://spin.gif"}
            patch_original_with_file(token, {
                "embeds": [embed], "components": components,
                "attachments": [{"id": 0, "filename": "spin.gif"}],
            }, "spin.gif", gif)
        else:
            patch_original(token, {"embeds": [embed], "components": components})
    finally:
        con.close()


# ---------- Spinning wheel GIF for Discord rolls ----------

WHEEL_COLORS_RGB = [(142, 68, 173), (192, 57, 43), (39, 174, 96), (41, 128, 185),
                    (211, 84, 0), (22, 160, 133), (127, 96, 0), (91, 44, 111),
                    (160, 64, 0), (30, 132, 73), (136, 78, 160), (176, 58, 46),
                    (31, 97, 141), (156, 100, 12)]
_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def build_wheel_base(labels, size):
    """Wheel with segments + labels drawn once; frames rotate this image."""
    import math
    from PIL import Image, ImageDraw, ImageFont

    cx = cy = size // 2
    R = size // 2 - 6
    img = Image.new("RGBA", (size, size), (26, 20, 16, 255))
    d = ImageDraw.Draw(img)
    n = len(labels)
    seg = 360 / n
    for i in range(n):
        d.pieslice([cx - R, cy - R, cx + R, cy + R], i * seg, (i + 1) * seg,
                   fill=WHEEL_COLORS_RGB[i % len(WHEEL_COLORS_RGB)], outline=(26, 20, 16), width=2)
    font = ImageFont.truetype(_FONT_PATH, 14)
    for i, lab in enumerate(labels):
        txt = lab if len(lab) <= 24 else lab[:22] + "…"
        mid = (i + 0.5) * seg
        bbox = font.getbbox(txt)
        timg = Image.new("RGBA", (bbox[2] - bbox[0] + 6, bbox[3] - bbox[1] + 10), (0, 0, 0, 0))
        ImageDraw.Draw(timg).text((3, 3), txt, font=font, fill=(255, 255, 255, 255))
        rimg = timg.rotate(-mid, expand=True, resample=Image.BICUBIC)
        rad = math.radians(mid)
        rtext = R * 0.58
        img.alpha_composite(rimg, (int(cx + math.cos(rad) * rtext - rimg.width / 2),
                                   int(cy + math.sin(rad) * rtext - rimg.height / 2)))
    d.ellipse([cx - R, cy - R, cx + R, cy + R], outline=(245, 197, 66), width=5)
    return img


def wheel_frame(base, rot):
    """Rotate the wheel clockwise by rot degrees, add hub + pointer on top."""
    from PIL import Image, ImageDraw

    fr = base.rotate(rot, resample=Image.BICUBIC, fillcolor=(26, 20, 16, 255))
    size = fr.width
    cx = cy = size // 2
    d = ImageDraw.Draw(fr)
    d.ellipse([cx - 26, cy - 26, cx + 26, cy + 26], fill=(245, 197, 66), outline=(122, 95, 30), width=3)
    d.polygon([(cx - 16, 2), (cx + 16, 2), (cx, 36)], fill=(192, 57, 43))
    return fr.convert("RGB")


def make_spin_gif(labels, winner_idx):
    """Animated GIF spinning to the winner (pointer at top). Returns bytes."""
    import io

    size = 380
    base = build_wheel_base(labels, size)
    n = len(labels)
    seg = 360 / n
    theta_w = (winner_idx + 0.5) * seg  # winner center, clockwise from 3 o'clock
    # verified visually: base.rotate(theta_w - 270) puts the winner under the pointer
    rot_total = 3 * 360 + (theta_w - 270) % 360
    frames, durations = [], []
    F = 32
    for i in range(F):
        t = (i + 1) / F
        eased = 1 - (1 - t) ** 4
        frames.append(wheel_frame(base, rot_total * eased))
        durations.append(45 if i < F - 1 else 2500)
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:],
                   duration=durations, optimize=True)
    return buf.getvalue()


def spin_labels(candidates, winner_name, max_segments=12):
    """Winner + a shuffled sample of other candidates; returns (labels, winner_idx)."""
    others = [c for c in candidates if c != winner_name]
    random.shuffle(others)
    labels = others[:max_segments - 1]
    labels.insert(random.randint(0, len(labels)), winner_name)
    return labels, labels.index(winner_name)


# ---------- /highscores podium image ----------

def fetch_discord_avatar(discord_id):
    """Returns PNG bytes of the user's Discord avatar (or their default one)."""
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    avatar_hash = None
    if token:
        try:
            req = urllib.request.Request(
                f"https://discord.com/api/v10/users/{discord_id}",
                headers={"Authorization": f"Bot {token}", "User-Agent": "osrs-afk-roulette"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                avatar_hash = json.load(r).get("avatar")
        except Exception:
            pass
    if avatar_hash:
        url = f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar_hash}.png?size=256"
    else:
        url = f"https://cdn.discordapp.com/embed/avatars/{(int(discord_id) >> 22) % 6}.png"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "osrs-afk-roulette"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read()
    except Exception:
        return None


def draw_podium(players, title="AFK HIGHSCORES"):
    """players: rank-ordered [{nick, done, avatar(bytes|None)}], 1-3 entries. Returns PNG bytes."""
    import io
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    W, H = 1200, 700
    img = Image.new("RGB", (W, H), "#1a1410")
    d = ImageDraw.Draw(img)
    for r in range(H, 0, -8):  # soft glow
        a = int(14 * (1 - r / H))
        d.ellipse([W / 2 - r * 1.4, H - r, W / 2 + r * 1.4, H + r], fill=(26 + a, 20 + a // 2, 16))

    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    f_title = ImageFont.truetype(font_path, 56)
    f_nick = ImageFont.truetype(font_path, 34)
    f_done = ImageFont.truetype(font_path, 28)
    f_rank = ImageFont.truetype(font_path, 72)

    def center_text(text, font, cx, y, fill):
        bb = d.textbbox((0, 0), text, font=font)
        d.text((cx - (bb[2] - bb[0]) / 2 - bb[0], y), text, font=font, fill=fill)

    center_text(title, f_title, W / 2, 28, "#f5c542")

    base = 660
    # layout per rank: (center_x, block_height, block_color, rank_label_color)
    slots = [
        (W / 2, 280, "#f5c542", "#241a08"),        # 1st, middle
        (W / 2 - 340, 200, "#c0c0c0", "#2b2119"),  # 2nd, left
        (W / 2 + 340, 150, "#cd7f32", "#2b2119"),  # 3rd, right
    ]
    bw = 280
    for i, p in enumerate(players[:3]):
        cx, bh, col, rankcol = slots[i]
        top = base - bh
        d.rounded_rectangle([cx - bw / 2, top, cx + bw / 2, base], radius=14, fill=col,
                            outline="#7a5f1e", width=4)
        center_text(str(i + 1), f_rank, cx, top + bh / 2 - 45, rankcol)

        # avatar circle above the block
        av_d = 150
        av_y = top - av_d - 78
        if p["avatar"]:
            try:
                av = Image.open(io.BytesIO(p["avatar"])).convert("RGB").resize((av_d, av_d))
                mask = Image.new("L", (av_d, av_d), 0)
                ImageDraw.Draw(mask).ellipse([0, 0, av_d, av_d], fill=255)
                img.paste(av, (int(cx - av_d / 2), av_y), mask)
            except Exception:
                p["avatar"] = None
        if not p["avatar"]:
            d.ellipse([cx - av_d / 2, av_y, cx + av_d / 2, av_y + av_d], fill="#4d3b28")
            center_text(p["nick"][:1].upper(), f_rank, cx, av_y + av_d / 2 - 45, "#f5c542")
        d.ellipse([cx - av_d / 2, av_y, cx + av_d / 2, av_y + av_d], outline="#f5c542", width=5)

        center_text(p["nick"], f_nick, cx, top - 72, "#e8dcc0")
        center_text(f"{p['done']} done", f_done, cx, top - 36, "#f5c542")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def patch_original_with_file(token, payload, filename, filebytes):
    boundary = f"----afkpodium{int(time.time() * 1000)}"
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
        f"Content-Type: application/json\r\n\r\n".encode() + json.dumps(payload).encode() + b"\r\n",
        f'--{boundary}\r\nContent-Disposition: form-data; name="files[0]"; filename="{filename}"\r\n'
        f"Content-Type: image/{'gif' if filename.endswith('.gif') else 'png'}\r\n\r\n".encode()
        + filebytes + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    req = urllib.request.Request(
        f"https://discord.com/api/v10/webhooks/{DISCORD_APP_ID}/{token}/messages/@original",
        data=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                 "User-Agent": "osrs-afk-roulette"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=15):
            pass
    except urllib.error.HTTPError as e:
        print(f"patch_with_file HTTP {e.code}: {e.read()[:500]}", flush=True)
    except Exception as e:
        print(f"patch_with_file failed: {e!r}", flush=True)


HS_CATEGORIES = {
    "afk": {"label": "AFK", "img_title": "AFK HIGHSCORES"},
    "task": {"label": "Task", "img_title": "TASK HIGHSCORES"},
    "boss": {"label": "Boss", "img_title": "BOSS HIGHSCORES"},
    "collection": {"label": "Collection", "img_title": "COLLECTION HIGHSCORES"},
}


def finish_highscores(token, category="afk"):
    try:
        _finish_highscores(token, category)
    except Exception as e:
        print(f"finish_highscores crashed: {e!r}", flush=True)
        patch_original(token, {"content": "Something went wrong building the highscores — try again."})


def _finish_highscores(token, category):
    meta = HS_CATEGORIES.get(category, HS_CATEGORIES["afk"])
    con = open_db()
    try:
        if category == "afk":
            rows = con.execute(
                """SELECT nick_key, MAX(nick) AS nick,
                          SUM(status = 'done') AS done, SUM(status = 'skipped') AS skips
                   FROM events GROUP BY nick_key
                   HAVING done > 0 ORDER BY done DESC, skips ASC LIMIT 3"""
            ).fetchall()
        else:
            rows = con.execute(
                """SELECT nick_key, MAX(nick) AS nick,
                          SUM(status = 'done') AS done, SUM(status = 'skipped') AS skips
                   FROM tasker_events WHERE category = ? GROUP BY nick_key
                   HAVING done > 0 ORDER BY done DESC, skips ASC LIMIT 3""",
                (category,),
            ).fetchall()
        if not rows:
            patch_original(token, {"content":
                f"No completed {meta['label']} tasks yet — the podium is empty!"})
            return
        links = {norm_key(r["nick"]): r["discord_id"]
                 for r in con.execute("SELECT discord_id, nick FROM discord_links")}
        players, medals = [], ["🥇", "🥈", "🥉"]
        desc_lines = []
        for i, r in enumerate(rows):
            avatar = None
            did = links.get(r["nick_key"])
            if did:
                avatar = fetch_discord_avatar(did)
            players.append({"nick": r["nick"], "done": r["done"], "avatar": avatar})
            line = f"{medals[i]} **{r['nick']}** — ✅ {r['done']} done · ⏭️ {r['skips']} skips"
            if category == "afk":
                days = [x["d"] for x in con.execute(
                    "SELECT DISTINCT d FROM events WHERE nick_key = ? AND status = 'done' ORDER BY d",
                    (r["nick_key"],))]
                current, _ = streaks(days)
                line = (f"{medals[i]} **{r['nick']}** — ✅ {r['done']} done · "
                        f"🔥 {current} streak · ⏭️ {r['skips']} skips")
            desc_lines.append(line)
        png = draw_podium(players, meta["img_title"])
        patch_original_with_file(token, {
            "embeds": [{
                "title": f"🏆 {meta['label']} Highscores — Top 3",
                "description": "\n".join(desc_lines),
                "color": 0xF5C542,
                "image": {"url": "attachment://podium.png"},
                "footer": {"text": "OSRS AFK Roulette · " + SITE_BASE.replace("https://", "")},
            }],
            "attachments": [{"id": 0, "filename": "podium.png"}],
        }, "podium.png", png)
    finally:
        con.close()


TASKER_CATEGORY_META = {
    "task": {"emoji": "📋", "title": "Task", "color": 0xF5C542},
    "boss": {"emoji": "⚔️", "title": "Boss task", "color": 0xC0392B},
    "collection": {"emoji": "📚", "title": "Collection task", "color": 0x2980B9},
}


def tasker_stats(con, key, category):
    row = con.execute(
        "SELECT SUM(status = 'done') AS d, SUM(status = 'skipped') AS s "
        "FROM tasker_events WHERE nick_key = ? AND category = ?", (key, category),
    ).fetchone()
    return {"done": row["d"] or 0, "skips": row["s"] or 0}


def tasker_discord_embed(con, nick, category, task, done=False):
    meta = TASKER_CATEGORY_META[category]
    s = tasker_stats(con, norm_key(nick), category)
    fields = [{"name": "Player", "value": nick, "inline": True}]
    if category == "task" and task.get("skill") == "quests":
        fields.append({"name": "Type", "value": f"Quest ({task.get('difficulty', '?')})", "inline": True})
    elif category == "task" and task.get("skill"):
        fields.append({"name": "Skill", "value": f"{task['skill']} (req {task.get('req', '?')})", "inline": True})
    if category == "boss" and task.get("reqs"):
        req_str = ", ".join(f"{k.capitalize()} {v}" for k, v in sorted(task["reqs"].items()))
        fields.append({"name": "Requirements", "value": req_str[:1000], "inline": False})
    if task.get("tip"):
        fields.append({"name": "Tip", "value": task["tip"][:1000], "inline": False})
    fields.append({"name": f"{meta['emoji']} {meta['title']} totals", "value":
                   f"✅ {s['done']} done · ⏭️ {s['skips']} skips",
                   "inline": False})
    title = (f"✅ Done: {task['name']}" if done
             else f"{meta['emoji']} {meta['title']}: {task['name']}")
    wiki = task.get("wiki") or ""
    return {
        "title": title,
        **({"url": wiki} if wiki.startswith("http") else {}),
        "color": 0x4CAF50 if done else meta["color"],
        "fields": fields,
        "footer": {"text": "OSRS AFK Roulette · " + SITE_BASE.replace("https://", "")},
    }


def tasker_buttons(category, discord_id, after_done=False, is_quest=False):
    if after_done:
        return [{"type": 1, "components": [
            {"type": 2, "style": 1, "label": "🎲 New task", "custom_id": f"tsk:new:{category}:{discord_id}"},
        ]}]
    buttons = [
        {"type": 2, "style": 3, "label": "✅ Done", "custom_id": f"tsk:done:{category}:{discord_id}"},
        {"type": 2, "style": 2, "label": "⏭️ Skip", "custom_id": f"tsk:skip:{category}:{discord_id}"},
    ]
    if is_quest:
        buttons.append({"type": 2, "style": 2, "label": "☑️ Already done",
                        "custom_id": f"tsk:already:{category}:{discord_id}"})
    return [{"type": 1, "components": buttons}]


def finish_tasker(token, discord_id, nick, category):
    try:
        con = open_db()
        try:
            key = norm_key(nick)
            levels = get_levels(con, nick)
            if levels is None:
                patch_original(token, {"content":
                    f"Couldn't fetch hiscores for **{nick}** — check the name with `/{category} nick:YourName`."})
                return
            task = get_active(con, key, category)
            gif = None
            if task is None:
                task = roll_category(levels, category, con, key)
                if task is None:
                    patch_original(token, {"content": f"No eligible {category} tasks for **{nick}**."})
                    return
                set_active(con, key, category, task)
                try:
                    labels, widx = spin_labels(tasker_candidates(levels, category, con, key),
                                               task["name"])
                    if len(labels) >= 2:
                        gif = make_spin_gif(labels, widx)
                except Exception as e:
                    print(f"spin gif failed: {e!r}", flush=True)
            embed = tasker_discord_embed(con, nick, category, task)
            components = tasker_buttons(category, discord_id,
                                        is_quest=task.get("name", "").startswith(QUEST_PREFIX))
            if gif:
                embed["image"] = {"url": "attachment://spin.gif"}
                patch_original_with_file(token, {
                    "embeds": [embed], "components": components,
                    "attachments": [{"id": 0, "filename": "spin.gif"}],
                }, "spin.gif", gif)
            else:
                patch_original(token, {"embeds": [embed], "components": components})
        finally:
            con.close()
    except Exception as e:
        print(f"finish_tasker crashed: {e!r}", flush=True)
        patch_original(token, {"content": "Something went wrong — try again."})


def tasker_candidates(levels, category, con, key):
    """Candidate labels for the spin GIF (same idea as the site's wheel)."""
    if category == "task":
        _cb, pool = skill_task_pool(levels, excluded_quests(con, key))
        return [m["template"].replace("{n}", str(m["lo"]) if m["lo"] == m["hi"] else f"{m['lo']}–{m['hi']}")
                for s in pool.values() for m in s["methods"]]
    _cb, eligible, _ = tasker_split(levels, category)
    return [t.get("display") or t["name"] for t in eligible]


def resolve_nick(cmd, discord_id, con):
    """Shared /afk-style nick resolution: optional nick option, else saved link."""
    nick_opt = next((o.get("value", "") for o in cmd.get("options", []) if o.get("name") == "nick"), "").strip()
    if nick_opt:
        if not NICK_RE.match(nick_opt):
            return None, ephemeral("That doesn't look like a valid OSRS name (max 12 chars).")
        con.execute(
            "INSERT INTO discord_links (discord_id, nick) VALUES (?, ?) "
            "ON CONFLICT(discord_id) DO UPDATE SET nick = excluded.nick",
            (discord_id, nick_opt),
        )
        con.commit()
        return nick_opt, None
    row = con.execute("SELECT nick FROM discord_links WHERE discord_id = ?", (discord_id,)).fetchone()
    if row is None:
        return None, ephemeral(
            f"Tell me your OSRS name first: `/{cmd.get('name', 'afk')} nick:YourName` (remembered after that).")
    return row["nick"], None


def handle_slash(data):
    cmd = data.get("data", {})
    name = cmd.get("name")
    if name == "highscores":
        hs_cat = next((o.get("value", "") for o in cmd.get("options", [])
                       if o.get("name") == "category"), "afk")
        if hs_cat not in HS_CATEGORIES:
            hs_cat = "afk"
        threading.Thread(target=finish_highscores, args=(data["token"], hs_cat), daemon=True).start()
        return jsonify({"type": 5})
    if name not in ("afk", "task", "boss", "collection"):
        return ephemeral("Unknown command.")
    user = (data.get("member") or {}).get("user") or data.get("user") or {}
    discord_id = user.get("id", "")
    nick, err = resolve_nick(cmd, discord_id, db())
    if err:
        return err
    if name == "afk":
        threading.Thread(target=finish_roll, args=(data["token"], discord_id, nick), daemon=True).start()
    else:
        threading.Thread(target=finish_tasker, args=(data["token"], discord_id, nick, name), daemon=True).start()
    return jsonify({"type": 5})  # deferred — the thread edits the message


def handle_tasker_button(data):
    parts = data.get("data", {}).get("custom_id", "").split(":")
    if len(parts) != 4:
        return ephemeral("Unknown button.")
    _, action, category, owner_id = parts
    if category not in TASKER_CATEGORY_META or action not in ("done", "skip", "new", "already"):
        return ephemeral("Unknown button.")
    user = (data.get("member") or {}).get("user") or data.get("user") or {}
    if user.get("id") != owner_id:
        return ephemeral("Only the player who rolled this task can use these buttons.")
    con = db()
    link = con.execute("SELECT nick FROM discord_links WHERE discord_id = ?", (owner_id,)).fetchone()
    if link is None:
        return ephemeral(f"Link your OSRS name first: `/{category} nick:YourName`.")
    nick = link["nick"]
    key = norm_key(nick)
    active = get_active(con, key, category)

    if action == "done":
        if active is None:
            return ephemeral(f"No active {category} task — roll one with `/{category}`.")
        con.execute(
            "INSERT INTO tasker_events (nick, nick_key, category, task, status, d) VALUES (?, ?, ?, ?, ?, ?)",
            (nick, key, category, active.get("name", "?"), "done", today().isoformat()),
        )
        con.execute("DELETE FROM tasker_active WHERE nick_key = ? AND category = ?", (key, category))
        con.commit()
        return jsonify({"type": 7, "data": {
            "embeds": [tasker_discord_embed(con, nick, category, active, done=True)],
            "components": tasker_buttons(category, owner_id, after_done=True),
        }})

    # skip / already / new all roll a fresh task from cached levels (no slow WOM fetch)
    lv = con.execute("SELECT levels FROM player_levels WHERE nick_key = ?", (key,)).fetchone()
    if lv is None:
        return ephemeral(f"Levels not cached — use `/{category}` first.")
    if action == "skip":
        if active is None:
            return ephemeral(f"No active {category} task — roll one with `/{category}`.")
        con.execute(
            "INSERT INTO tasker_events (nick, nick_key, category, task, status, d) VALUES (?, ?, ?, ?, ?, ?)",
            (nick, key, category, active.get("name", "?"), "skipped", today().isoformat()),
        )
        con.commit()
    elif action == "already":
        if active is None or not active.get("name", "").startswith(QUEST_PREFIX):
            return ephemeral("That button only works on an active quest task.")
        con.execute("INSERT OR IGNORE INTO quest_flags (nick_key, quest) VALUES (?, ?)",
                    (key, active["name"][len(QUEST_PREFIX):]))
        con.commit()
    elif active is not None:  # "new" pressed but a task is already active -> show it
        return jsonify({"type": 7, "data": {
            "embeds": [tasker_discord_embed(con, nick, category, active)],
            "components": tasker_buttons(category, owner_id,
                                         is_quest=active.get("name", "").startswith(QUEST_PREFIX)),
        }})
    levels = json.loads(lv["levels"])
    task = None
    if action == "already":
        # After flagging a pre-completed quest, hand out ANOTHER quest
        con.execute("DELETE FROM tasker_active WHERE nick_key = ? AND category = ?", (key, category))
        con.commit()
        task = roll_quest_task(levels, con, key)
    if task is None:
        task = roll_category(levels, category, con, key)
    if task is None:
        return ephemeral(f"No eligible {category} tasks.")
    set_active(con, key, category, task)
    return jsonify({"type": 7, "data": {
        "embeds": [tasker_discord_embed(con, nick, category, task)],
        "components": tasker_buttons(category, owner_id,
                                     is_quest=task.get("name", "").startswith(QUEST_PREFIX)),
    }})


def handle_button(data):
    custom_id = data.get("data", {}).get("custom_id", "")
    if custom_id.startswith("tsk:"):
        return handle_tasker_button(data)
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


# ---------- Taskman-style task generator (TEST MODE — not linked in UI yet) ----------

import tasker_reqs  # noqa: E402

with open(os.path.join(os.path.dirname(__file__), "tasker_tiers.json"), encoding="utf-8") as _f:
    TASKER_TIERS = json.load(_f)

# "collection" = ALL Taskman collection-log tasks (incl. boss uniques) behind
# one button; the same task in several tiers -> weights summed.
_coll = {}
for _tier in ("easy", "medium", "hard", "elite"):
    for _t in TASKER_TIERS[_tier]:
        if _t["name"] in _coll:
            _coll[_t["name"]]["weight"] += _t.get("weight", 1)
        else:
            _coll[_t["name"]] = {**_t, "origTier": _tier}
TASKER_TIERS["collection"] = list(_coll.values())

# "boss" = pure kill-count tasks with recommended stats (tasker_reqs.BOSS_KILLS)
TASKER_TIERS["boss"] = [
    {"name": t, "lo": lo, "hi": hi, "weight": 1, "reqs": reqs}
    for t, lo, hi, reqs in tasker_reqs.BOSS_KILLS
]
TIER_ALIASES = {"normal": "medium", "bosses": "boss", "log": "collection"}

import skill_tasks  # noqa: E402

with open(os.path.join(os.path.dirname(__file__), "quests.json"), encoding="utf-8") as _f:
    QUESTS = json.load(_f)
QUEST_PREFIX = "Complete the quest: "


def excluded_quests(con, key):
    """Quests never offered again: flagged 'already done' or completed via a task."""
    ex = {r["quest"] for r in con.execute(
        "SELECT quest FROM quest_flags WHERE nick_key = ?", (key,))}
    for r in con.execute(
        "SELECT task FROM tasker_events WHERE nick_key = ? AND status = 'done' AND task LIKE ?",
        (key, QUEST_PREFIX + "%"),
    ):
        ex.add(r["task"][len(QUEST_PREFIX):])
    return ex


def combat_level(lv):
    base = 0.25 * (lv.get("defence", 1) + lv.get("hitpoints", 10) + lv.get("prayer", 1) // 2)
    melee = 0.325 * (lv.get("attack", 1) + lv.get("strength", 1))
    ranged = 0.325 * (lv.get("ranged", 1) * 3 // 2)
    magic = 0.325 * (lv.get("magic", 1) * 3 // 2)
    return int(base + max(melee, ranged, magic))


def tasker_split(levels, tier):
    """Split a tier's tasks into eligible / blocked (with reasons) for the given levels."""
    cb = combat_level(levels)
    eligible, blocked = [], []
    for t in TASKER_TIERS[tier]:
        reqs = t["reqs"] if "reqs" in t else tasker_reqs.reqs_for(t["name"])
        missing = {}
        for skill, need in reqs.items():
            have = cb if skill == "combat" else levels.get(skill, 1)
            if have < need:
                missing[skill] = {"have": have, "need": need}
        entry = {**t, "reqs": reqs}
        if "{n}" in t["name"] and "lo" in t:
            entry["display"] = t["name"].replace("{n}", f"{t['lo']}–{t['hi']}")
        if missing:
            blocked.append({**entry, "missing": missing})
        else:
            eligible.append(entry)
    return cb, eligible, blocked


def tasker_prepare():
    nick = (request.args.get("nick") or "").strip()
    tier = (request.args.get("tier") or "easy").strip().lower()
    tier = TIER_ALIASES.get(tier, tier)
    if not NICK_RE.match(nick):
        return None, None, (jsonify({"ok": False, "error": "invalid nick"}), 400)
    if tier not in TASKER_TIERS:
        return None, None, (jsonify({"ok": False, "error": "tier must be easy/normal/hard/elite/boss"}), 400)
    levels = get_levels(db(), nick)
    if levels is None:
        return None, None, (jsonify({"ok": False, "error": "player not found on hiscores"}), 404)
    return tier, levels, None


@app.get("/api/tasker/eligible")
def tasker_eligible():
    tier, levels, err = tasker_prepare()
    if err:
        return err
    cb, eligible, blocked = tasker_split(levels, tier)
    return jsonify({
        "tier": tier, "combat": cb, "levels": levels,
        "eligibleCount": len(eligible), "blockedCount": len(blocked),
        "eligible": eligible, "blocked": blocked,
    })


def get_active(con, key, category):
    row = con.execute(
        "SELECT task FROM tasker_active WHERE nick_key = ? AND category = ?", (key, category)
    ).fetchone()
    return json.loads(row["task"]) if row else None


def set_active(con, key, category, task):
    con.execute(
        "INSERT INTO tasker_active (nick_key, category, task) VALUES (?, ?, ?) "
        "ON CONFLICT(nick_key, category) DO UPDATE SET task = excluded.task",
        (key, category, json.dumps(task)),
    )
    con.commit()


@app.get("/api/tasker/roll")
def tasker_roll():
    tier, levels, err = tasker_prepare()
    if err:
        return err
    nick = request.args.get("nick", "").strip()
    key = norm_key(nick)
    con = db()
    if tier in ("boss", "collection"):
        active = get_active(con, key, tier)
        if active:
            return jsonify({"tier": tier, "task": active, "active": True})
    cb, eligible, _ = tasker_split(levels, tier)
    if not eligible:
        return jsonify({"ok": False, "error": "no eligible tasks in this tier"}), 404
    weighted = [t for t in eligible for _ in range(max(1, t.get("weight", 1)))]
    task = dict(random.choice(weighted))
    if "{n}" in task["name"] and "lo" in task:
        count = random.randint(task["lo"], task["hi"])
        if task["hi"] >= 20:
            count = max(task["lo"], round(count / 5) * 5)
        task["name"] = task["name"].replace("{n}", str(count))
        task["count"] = count
    if tier in ("boss", "collection"):
        stored = {"name": task["name"], "wiki": task.get("wiki", ""), "tip": task.get("tip", "")}
        set_active(con, key, tier, stored)
    return jsonify({"tier": tier, "combat": cb, "task": task, "active": False})


def skill_task_pool(levels, quests_excluded=None):
    """Per-skill eligible methods with the near-level bucket marked."""
    cb = combat_level(levels)
    pool = {}
    # Quests as their own "skill": offer only quests whose skill requirements the
    # player meets and which they haven't done (tracked by us — hiscores can't
    # tell quest completion, so there's an "Already done" action to flag old ones).
    q_methods = []
    completed = quests_excluded or set()
    for q in QUESTS:
        if q["name"] in completed:
            continue
        # Quest chains: sequels are offered only once every prerequisite quest
        # has been marked done / already-done in our tracking.
        if any(pr not in completed for pr in q.get("quest_reqs", [])):
            continue
        if any((cb if s == "combat" else levels.get(s, 1)) < need for s, need in q["reqs"].items()):
            continue
        q_methods.append({"req": 1, "template": QUEST_PREFIX + q["name"], "lo": 1, "hi": 1,
                          "extra": {}, "near": True, "wiki": q["wiki"], "difficulty": q["difficulty"]})
    if q_methods:
        pool["quests"] = {"level": len(q_methods), "methods": q_methods}
    for skill in set(skill_tasks.SKILL_TASKS) | set(levels):
        lvl = cb if skill == "combat" else levels.get(skill, 1)
        elig = []
        for m in skill_tasks.SKILL_TASKS.get(skill, []):
            req, template, lo, hi = m[0], m[1], m[2], m[3]
            extra = m[4] if len(m) > 4 else {}
            if req > lvl:
                continue
            if any((cb if s == "combat" else levels.get(s, 1)) < need for s, need in extra.items()):
                continue
            elig.append({"req": req, "template": template, "lo": lo, "hi": hi, "extra": extra})
        if elig:
            top = max(e["req"] for e in elig)
            for e in elig:
                e["near"] = e["req"] >= lvl - skill_tasks.NEAR_WINDOW or e["req"] == top
        # Every trainable skill also offers a "gain levels" task, always near-level.
        # Amount scales down as levels get slower: 1-20 -> 5, 21-40 -> 4, 41-60 -> 3,
        # 61-80 -> 2, 81-98 -> 1 (capped so the target never exceeds 99).
        if skill != "combat" and lvl < 99:
            gain = 5 if lvl <= 20 else 4 if lvl <= 40 else 3 if lvl <= 60 else 2 if lvl <= 80 else 1
            gain = min(gain, 99 - lvl)
            elig.append({"req": 1, "template": f"Gain {{n}} {skill} level(s)",
                         "lo": gain, "hi": gain, "extra": {}, "near": True})
        if not elig:
            continue
        pool[skill] = {"level": lvl, "methods": elig}
    return cb, pool


@app.get("/api/tasker/task/eligible")
def skill_task_eligible():
    _tier, levels, err = tasker_prepare_nick_only()
    if err:
        return err
    key = norm_key(request.args.get("nick", "").strip())
    cb, pool = skill_task_pool(levels, excluded_quests(db(), key))
    return jsonify({"combat": cb, "skills": pool})


@app.get("/api/tasker/task/roll")
def skill_task_roll():
    _tier, levels, err = tasker_prepare_nick_only()
    if err:
        return err
    nick = request.args.get("nick", "").strip()
    key = norm_key(nick)
    con = db()
    active = get_active(con, key, "task")
    if active:
        return jsonify({**active, "active": True})
    result = roll_category(levels, "task", con, key)
    if result is None:
        return jsonify({"ok": False, "error": "no eligible tasks"}), 404
    set_active(con, key, "task", result)
    return jsonify({**result, "active": False})


def roll_quest_task(levels, con, key):
    """Roll a random eligible QUEST task (used after 'Already done')."""
    _cb, pool = skill_task_pool(levels, excluded_quests(con, key))
    q = pool.get("quests")
    if not q:
        return None
    m = random.choice(q["methods"])
    return {"name": m["template"], "task": m["template"], "skill": "quests",
            "level": q["level"], "req": 1, "near": True, "count": 1,
            "wiki": m.get("wiki"), "difficulty": m.get("difficulty")}


def roll_category(levels, category, con=None, key=None):
    """Roll a fresh task dict for a category, or None if nothing is eligible."""
    if category == "task":
        excluded = excluded_quests(con, key) if con is not None and key else None
        _cb, pool = skill_task_pool(levels, excluded)
        if not pool:
            return None
        skill = random.choice(list(pool.keys()))
        entry = pool[skill]
        near = [m for m in entry["methods"] if m["near"]]
        far = [m for m in entry["methods"] if not m["near"]]
        bucket = (near if random.random() < skill_tasks.NEAR_SHARE else far) if near and far else (near or far)
        m = random.choice(bucket)
        count = random.randint(m["lo"], m["hi"])
        if m["hi"] >= 20:
            count = max(m["lo"], round(count / 5) * 5)
        name = m["template"].replace("{n}", str(count))
        result = {"name": name, "task": name, "skill": skill, "level": entry["level"],
                  "req": m["req"], "near": m["near"], "count": count}
        if m.get("wiki"):
            result["wiki"] = m["wiki"]
        if m.get("difficulty"):
            result["difficulty"] = m["difficulty"]
        return result
    cb, eligible, _ = tasker_split(levels, category)
    if not eligible:
        return None
    weighted = [t for t in eligible for _ in range(max(1, t.get("weight", 1)))]
    task = dict(random.choice(weighted))
    if "{n}" in task["name"] and "lo" in task:
        count = random.randint(task["lo"], task["hi"])
        if task["hi"] >= 20:
            count = max(task["lo"], round(count / 5) * 5)
        task["name"] = task["name"].replace("{n}", str(count))
    return {"name": task["name"], "wiki": task.get("wiki", ""), "tip": task.get("tip", ""),
            "reqs": task.get("reqs", {})}


@app.get("/api/tasker/current")
def tasker_current():
    nick = (request.args.get("nick") or "").strip()
    category = (request.args.get("category") or "").strip().lower()
    if not NICK_RE.match(nick) or category not in ("task", "boss", "collection"):
        return jsonify({"ok": False, "error": "invalid params"}), 400
    active = get_active(db(), norm_key(nick), category)
    return jsonify({"active": active})


@app.post("/api/tasker/complete")
def tasker_complete():
    body = request.get_json(silent=True) or {}
    nick = (body.get("nick") or "").strip()
    category = (body.get("category") or "").strip().lower()
    status = (body.get("status") or "").strip().lower()
    if not NICK_RE.match(nick) or category not in ("task", "boss", "collection") \
            or status not in ("done", "skipped", "already"):
        return jsonify({"ok": False, "error": "invalid params"}), 400
    key = norm_key(nick)
    con = db()
    active = get_active(con, key, category)
    if active is None:
        return jsonify({"ok": False, "error": "no active task"}), 404
    name = active.get("name", "?")
    if status == "already":
        # "Already done" is only for quests: flag it so it's never offered again,
        # without counting as a done or a skip — and hand out ANOTHER quest.
        if not name.startswith(QUEST_PREFIX):
            return jsonify({"ok": False, "error": "only quest tasks can be flagged already done"}), 400
        con.execute("INSERT OR IGNORE INTO quest_flags (nick_key, quest) VALUES (?, ?)",
                    (key, name[len(QUEST_PREFIX):]))
        con.execute("DELETE FROM tasker_active WHERE nick_key = ? AND category = ?", (key, category))
        con.commit()
        lv = con.execute("SELECT levels FROM player_levels WHERE nick_key = ?", (key,)).fetchone()
        nxt = roll_quest_task(json.loads(lv["levels"]), con, key) if lv else None
        if nxt:
            set_active(con, key, category, nxt)
        return jsonify({"ok": True, "next": nxt})
    else:
        con.execute(
            "INSERT INTO tasker_events (nick, nick_key, category, task, status, d) VALUES (?, ?, ?, ?, ?, ?)",
            (nick, key, category, name, status, today().isoformat()),
        )
        if status == "done" and name.startswith(QUEST_PREFIX):
            con.execute("INSERT OR IGNORE INTO quest_flags (nick_key, quest) VALUES (?, ?)",
                        (key, name[len(QUEST_PREFIX):]))
    con.execute("DELETE FROM tasker_active WHERE nick_key = ? AND category = ?", (key, category))
    con.commit()
    return jsonify({"ok": True})


@app.get("/api/tasker/highscores")
def tasker_highscores():
    rows = db().execute(
        """SELECT nick_key, MAX(nick) AS nick, category,
                  SUM(status = 'done') AS done, SUM(status = 'skipped') AS skips
           FROM tasker_events GROUP BY nick_key, category"""
    ).fetchall()
    boards = {"task": [], "boss": [], "collection": []}
    for r in rows:
        if r["category"] in boards:
            boards[r["category"]].append(
                {"nick": r["nick"], "done": r["done"] or 0, "skips": r["skips"] or 0})
    for cat in boards:
        boards[cat].sort(key=lambda p: (-p["done"], p["skips"]))
    return jsonify(boards)


def tasker_prepare_nick_only():
    nick = (request.args.get("nick") or "").strip()
    if not NICK_RE.match(nick):
        return None, None, (jsonify({"ok": False, "error": "invalid nick"}), 400)
    levels = get_levels(db(), nick)
    if levels is None:
        return None, None, (jsonify({"ok": False, "error": "player not found on hiscores"}), 404)
    return None, levels, None


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
