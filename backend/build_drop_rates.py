"""Build drop_rates.json: how rare each NPC drop is, for the plugin's
"rarer than 1/x" Discord notification filter.

Source: the OSRS Wiki drop tables (bucket "dropsline", CC BY-NC-SA 3.0).
Output: {npc name (lower case): {item name (lower case): x}}, where a drop is
1/x per kill. Run again when new content is released:

    python build_drop_rates.py
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

API = "https://oldschool.runescape.wiki/api.php"
UA = {"User-Agent": "osrs-afk-roulette/1.0 (https://afk.rosu.fi)"}
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "drop_rates.json")
PAGE = 5000
FRACTION_RE = re.compile(r"^~?\s*([\d.,]+)\s*/\s*([\d.,]+)$")


def rarity(text, rolls):
    """1/x per kill as x, or None for "Varies", "Rare" etc."""
    text = (text or "").strip()
    if text.lower() == "always":
        return 1.0
    m = FRACTION_RE.match(text)
    if not m:
        return None
    num, den = (float(g.replace(",", "")) for g in m.groups())
    if num <= 0 or den <= 0:
        return None
    try:
        rolls = max(1, int(rolls or 1))
    except (TypeError, ValueError):
        rolls = 1
    return max(1.0, den / num / rolls)


def fetch(offset):
    query = (f"bucket('dropsline').select('page_name','item_name','drop_json')"
             f".limit({PAGE}).offset({offset}).run()")
    url = API + "?" + urllib.parse.urlencode({"action": "bucket", "format": "json", "query": query})
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return json.load(r).get("bucket", [])


def main():
    rates = {}
    offset = 0
    while True:
        rows = fetch(offset)
        for row in rows:
            try:
                drop = json.loads(row.get("drop_json") or "{}")
            except ValueError:
                continue
            x = rarity(drop.get("Rarity"), drop.get("Rolls"))
            item = (drop.get("Dropped item") or row.get("item_name") or "").strip().lower()
            if x is None or not item:
                continue
            for npc in {(row.get("page_name") or "").split("#")[0], drop.get("Dropped from") or ""}:
                npc = npc.strip().lower()
                if npc:
                    # The most common way to get an item counts (no false "rare" alerts).
                    table = rates.setdefault(npc, {})
                    table[item] = round(min(table.get(item, x), x), 2)
        print(f"{offset + len(rows)} rows, {len(rates)} npcs")
        if len(rows) < PAGE:
            break
        offset += PAGE
        time.sleep(1)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(rates, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
