"""Build collection_tasks.json: the Collection log task pool.

Source: the OSRS Wiki "Collection log" page (CC BY-NC-SA 3.0), which lists
every collection log page (activity) and its items. From that we generate our
own tasks: "Get N new items from <activity>", plus one task per achievement
diary tier. Run again when new content is released:

    python build_collection_tasks.py

The plugin completes clog tasks from the in-game "New item added to your
collection log: <item>" chat message, so tasks carry item names. Item ids
(read from each item page's infobox) go to item_ids.json; the plugin draws
them as icons in its roll reel.
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

import tasker_reqs

API = "https://oldschool.runescape.wiki/api.php?action=parse&page=Collection_log&format=json&prop=wikitext"
QUERY = "https://oldschool.runescape.wiki/api.php"
WIKI = "https://oldschool.runescape.wiki/w/"
UA = {"User-Agent": "osrs-afk-roulette/1.0 (https://afk.rosu.fi)"}
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "collection_tasks.json")
IDS_OUT = os.path.join(HERE, "item_ids.json")


def _infobox_id(text):
    """First item id from an item page's infobox (the base version)."""
    for marker in ("{{Infobox Item", "{{Infobox Pet", "{{Infobox Bonuses"):
        i = text.find(marker)
        if i >= 0:
            m = re.search(r"^\|\s*id1?\s*=\s*(\d+)", text[i:], re.M)
            if m:
                return int(m.group(1))
    return None


def resolve_item_ids(names):
    """{item name: id} for the names the wiki has an item infobox for."""
    names = sorted(set(names))
    ids = {}
    for start in range(0, len(names), 50):
        batch = names[start:start + 50]
        params = {"action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main",
                  "titles": "|".join(batch), "redirects": 1, "format": "json", "formatversion": 2}
        req = urllib.request.Request(QUERY + "?" + urllib.parse.urlencode(params), headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            q = json.load(r)["query"]
        # Map the titles the wiki returns back to the names we asked for.
        back = {n: n for n in batch}
        for step in ("normalized", "redirects"):
            for e in q.get(step, []):
                for orig, cur in list(back.items()):
                    if cur == e["from"]:
                        back[orig] = e["to"]
        by_title = {}
        for p in q.get("pages", []):
            revs = p.get("revisions")
            if revs:
                found = _infobox_id(revs[0]["slots"]["main"]["content"])
                if found is not None:
                    by_title[p["title"]] = found
        for orig, title in back.items():
            if title in by_title:
                ids[orig] = by_title[title]
        time.sleep(0.5)
    return ids

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

    names = [i for t in tasks if t["verify"]["type"] == "clog" for i in t["verify"]["items"]]
    icons = [item for _kw, item in tasker_reqs.BOSS_ICONS] + tasker_reqs.EXTRA_ICONS
    ids = resolve_item_ids(names + icons)
    with open(IDS_OUT, "w", encoding="utf-8") as f:
        json.dump(ids, f, ensure_ascii=False, indent=0, sort_keys=True)
    missing = [n for n in icons if n not in ids]
    print(f"{len(ids)}/{len(set(names + icons))} item ids -> {IDS_OUT}; missing icons: {missing}")


if __name__ == "__main__":
    main()
