"""Build collection_tasks.json: the Collection log task pool.

Source: the OSRS Wiki "Collection log" page (CC BY-NC-SA 3.0), which lists
every collection log page (activity) and its items. From that we generate our
own tasks: "Get N new items from <activity>", plus one task per achievement
diary tier. Run again when new content is released:

    python build_collection_tasks.py

The plugin completes clog tasks from the in-game "New item added to your
collection log: <item>" chat message, so tasks carry item names, not ids.
"""
import json
import os
import re
import urllib.request

API = "https://oldschool.runescape.wiki/api.php?action=parse&page=Collection_log&format=json&prop=wikitext"
WIKI = "https://oldschool.runescape.wiki/w/"
UA = {"User-Agent": "osrs-afk-roulette/1.0 (https://afk.rosu.fi)"}
OUT = os.path.join(os.path.dirname(__file__), "collection_tasks.json")

DIARY_REGIONS = [
    ("Ardougne", "ardougne"), ("Desert", "desert"), ("Falador", "falador"),
    ("Fremennik", "fremennik"), ("Kandarin", "kandarin"), ("Karamja", "karamja"),
    ("Kourend & Kebos", "kourend-and-kebos"), ("Lumbridge & Draynor", "lumbridge-and-draynor"),
    ("Morytania", "morytania"), ("Varrock", "varrock"), ("Western Provinces", "western-provinces"),
    ("Wilderness", "wilderness"),
]
DIARY_TIERS = ["Easy", "Medium", "Hard", "Elite"]


def target_count(n_items):
    """Bigger pages ask for more new items per task."""
    if n_items < 15:
        return 1
    if n_items < 60:
        return 3
    return 5


def parse(wikitext):
    pages = []
    tab = activity = None
    items = []

    def flush():
        if activity and items:
            pages.append({"tab": tab, "activity": activity, "items": list(dict.fromkeys(items))})

    for line in wikitext.splitlines():
        m3 = re.match(r"^===\s*(.+?)\s*===\s*$", line)
        m2 = re.match(r"^==\s*([^=].*?)\s*==\s*$", line)
        if m3:
            flush()
            activity, items = m3.group(1), []
        elif m2:
            flush()
            tab, activity, items = m2.group(1), None, []
        elif activity:
            items += re.findall(r"\{\{plink\|([^|}]+)", line)
    flush()
    return pages


def main():
    req = urllib.request.Request(API, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        wikitext = json.load(r)["parse"]["wikitext"]["*"]

    tasks = []
    for page in parse(wikitext):
        n = target_count(len(page["items"]))
        what = "new item" if n == 1 else "new items"
        tasks.append({
            "name": f"Get {n} {what} from the {page['activity']} collection log",
            "short": page["activity"],
            "wiki": WIKI + page["activity"].replace(" ", "_"),
            "tip": f"Any {page['activity']} collection log item you don't have yet counts "
                   f"({len(page['items'])} items in total).",
            "weight": 1,
            "group": page["tab"],
            "verify": {"type": "clog", "items": page["items"], "count": n},
        })
    for region, key in DIARY_REGIONS:
        for tier in DIARY_TIERS:
            tasks.append({
                "name": f"Complete the {region} {tier} Diary",
                "short": f"{region} {tier}",
                "wiki": WIKI + region.replace(" & ", "_%26_").replace(" ", "_") + "_Diary",
                "tip": "Completes when the game announces the whole tier finished.",
                "weight": 1,
                "group": "Achievement Diaries",
                "verify": {"type": "diary", "region": key, "tier": tier.lower()},
            })

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=1)
    print(f"{len(tasks)} tasks -> {OUT}")


if __name__ == "__main__":
    main()
