"""Machine-checkable completion rules for rolled tasks.

The RuneLite plugin reads a task's "verify" spec and completes the task by
itself when the game shows it was done. Tasks without a spec (verify=None) are
completed by hand with the Done button, exactly as before.

Spec types the plugin understands:
  level       {"skill", "target"}           real level reaches target
  xp_actions  {"skill", "count"}            count separate xp gains in skill (one per action)
  xp_gain     {"skills", "amount"}          total xp gained across skills
  item_gain   {"skill", "items", "count"}   quantity of items gained together with xp in skill
  kc          {"names", "count"}            "Your <name> ... count is: N" chat messages
  npc_kill    {"names", "count"}            NPCs the player was fighting dying
  quest       {"quest"}                     quest log shows the quest finished
  clog        {"itemIds", "count"}          new collection log items (chat notification)
  diary       {"region", "tier"}            whole diary tier completed (chat message)
"""
import re

MELEE = ["attack", "strength", "defence"]

# Templates the plugin can't observe reliably (rewards, contracts, sailing...).
# These stay manual (Done button).
_MANUAL = re.compile(
    r"Forestry|Brimhaven|Hallowed Sepulchre|Pyramid Plunder|Mixology|Volcanic Mine|"
    r"Giants' Foundry|Mahogany Homes|farming contract|Tithe Farm|herb runs|^Plant|"
    r"Hunter Guild|Nightmare Zone|Konar|^Attach|blessed bone shards|courier|port tasks|"
    r"^Chart|^Salvage|tickets|Fortis Colosseum|"
    # xp arrives in batches, so neither xp drops nor same-tick item gains count them
    r"Blast Furnace|jugs of wine",
    re.IGNORECASE,
)

# KC-style chat counters for skill tasks: template fragment -> counter names
_SKILL_KC = [
    (re.compile(r"Wintertodt", re.I), ["Wintertodt"]),
    (re.compile(r"Tempoross", re.I), ["Tempoross"]),
    (re.compile(r"Guardians of the Rift", re.I), ["Guardians of the Rift"]),
    (re.compile(r"slayer tasks? from", re.I), ["Slayer task"]),
]

# Items produced in batches, where one xp gain != one item
_ITEM_GAIN = [
    (re.compile(r"^Craft \{n\} (\w+) runes$"), lambda m: [m.group(1).capitalize() + " rune"]),
    (re.compile(r"^Fletch \{n\} arrow shafts$"), lambda m: ["Arrow shaft"]),
    (re.compile(r"^Fletch \{n\} broad bolts$"), lambda m: ["Broad bolts"]),
    (re.compile(r"^Smith \{n\} cannonballs$"), lambda m: ["Cannonball"]),
    # Cutting and stringing both give fletching xp; count only the cut (u) bows.
    (re.compile(r"^Fletch \{n\} (\w+) longbows$"), lambda m: [m.group(1).capitalize() + " longbow (u)"]),
]

# Boss templates that don't follow "Kill (the) X {n} times"
_BOSS_SPECIAL = {
    "Kill each Dagannoth King {n} times": (["Dagannoth Rex", "Dagannoth Prime", "Dagannoth Supreme"], 3),
    "Complete {n} Barrows runs": (["Barrows"], 1),
    "Complete the Fight Caves {n} times (TzTok-Jad)": (["TzTok-Jad"], 1),
    "Complete {n} Gauntlet runs": (["Gauntlet"], 1),
    "Complete {n} Moons of Peril runs": (["Lunar Chest"], 1),
    "Complete {n} Chambers of Xeric raids": (["Chambers of Xeric"], 1),
    "Complete {n} Theatre of Blood raids": (["Theatre of Blood"], 1),
    "Complete {n} Tombs of Amascut raids": (["Tombs of Amascut"], 1),
    "Kill the Royal Titans {n} times": (["Royal Titan"], 1),
}


def _singular(word):
    word = word.strip()
    return word[:-1] if word.endswith("s") else word


def for_skill_task(skill, template, count, level):
    """Spec for a Task-category roll, or None when it can only be done by hand."""
    if skill == "quests":
        return {"type": "quest", "quest": template.split(": ", 1)[1]}
    if template.startswith("Gain {n}"):
        # "from" lets the plugin re-base on the real in-game level: the server's
        # level can be stale (hiscores cache) or 1 for unranked skills.
        return {"type": "level", "skill": skill, "from": level, "target": min(99, level + count)}
    if _MANUAL.search(template):
        return None
    m = re.search(r"laps of the (.+?) (?:rooftop )?course", template)
    if m:
        return {"type": "kc", "names": [m.group(1)], "count": count}
    for rx, names in _SKILL_KC:
        if rx.search(template):
            return {"type": "kc", "names": names, "count": count}
    for rx, items in _ITEM_GAIN:
        m = rx.match(template)
        if m:
            return {"type": "item_gain", "skill": skill, "items": items(m), "count": count}
    m = re.match(r"^Kill \{n\} (.+)$", template)
    if m:
        names = [_singular(n) for n in m.group(1).split(" or ")]
        return {"type": "npc_kill", "names": names, "count": count}
    if skill == "combat":
        return None
    return {"type": "xp_actions", "skill": skill, "count": count}


def for_boss(template, count):
    """Spec for a Bosses-category roll ("Kill X {n} times" style templates)."""
    if template in _BOSS_SPECIAL:
        names, per = _BOSS_SPECIAL[template]
        return {"type": "kc", "names": names, "count": count * per}
    m = re.match(r"^Kill \{n\} (.+)$", template)
    if m:  # non-boss NPCs without a kill counter, e.g. Tormented Demons
        return {"type": "npc_kill", "names": [_singular(m.group(1))], "count": count}
    m = re.match(r"^Kill (?:the )?(.+?) \{n\} times$", template)
    if m:
        return {"type": "kc", "names": [n.strip() for n in m.group(1).split(" or ")], "count": count}
    return None


def for_afk(task):
    """Daily AFK task: done after about half an hour of the method's xp."""
    skill = task.get("skill")
    if not skill:
        return None
    skills = MELEE if skill in MELEE else [skill]
    xp = task.get("xp") or 0
    amount = max(1000, round(xp / 2)) if xp else 5000
    return {"type": "xp_gain", "skills": skills, "amount": amount}
