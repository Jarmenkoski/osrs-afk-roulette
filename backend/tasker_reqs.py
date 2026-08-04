"""Requirement rules for the Taskman-style task generator.

Maps task names (from tasker_tiers.json) to effective minimum skill levels,
INCLUDING the skill requirements of prerequisite quests — hiscores can't tell
us quest completion, so a quest gate is approximated by its skill gates.

"combat" is a pseudo-skill checked against the computed combat level.
Diary requirements were pulled from the OSRS Wiki (per region & tier).
Sailing-era tasks (2025-26 content) are best-effort estimates marked EST.

This file is DESIGNED TO BE TUNED — adjust numbers freely and redeploy.
"""
import re

# ---- Achievement diaries: region -> tier -> reqs (source: OSRS Wiki) ----
DIARY = {
    "ardougne": {
        "easy": {"thieving": 5, "combat": 36},
        "medium": {"agility": 39, "strength": 38, "ranged": 25, "thieving": 38, "crafting": 49,
                   "firemaking": 50, "magic": 51, "woodcutting": 36, "farming": 31, "construction": 10},
        "hard": {"mining": 52, "strength": 50, "agility": 56, "smithing": 68, "herblore": 45,
                 "fishing": 53, "ranged": 60, "thieving": 72, "cooking": 53, "prayer": 42,
                 "crafting": 50, "firemaking": 50, "magic": 66, "woodcutting": 50, "runecraft": 65,
                 "farming": 70, "construction": 50, "hunter": 59},
        "elite": {"mining": 52, "strength": 50, "agility": 90, "smithing": 91, "herblore": 45,
                  "fishing": 81, "ranged": 60, "thieving": 82, "cooking": 91, "prayer": 42,
                  "crafting": 50, "firemaking": 50, "magic": 94, "fletching": 69, "woodcutting": 50,
                  "runecraft": 65, "farming": 85, "construction": 50, "hunter": 59},
    },
    "desert": {
        "easy": {"hunter": 5, "thieving": 21},
        "medium": {"agility": 30, "slayer": 22, "hunter": 47, "thieving": 25, "herblore": 36,
                   "construction": 20, "woodcutting": 35},
        "hard": {"attack": 50, "mining": 45, "agility": 70, "thieving": 65, "firemaking": 60,
                 "smithing": 68, "magic": 68, "slayer": 65, "combat": 85},
        "elite": {"cooking": 85, "magic": 94, "fletching": 95, "construction": 78, "thieving": 91,
                  "prayer": 85, "combat": 85},
    },
    "falador": {
        "easy": {"agility": 5, "smithing": 13, "mining": 10, "construction": 16},
        "medium": {"agility": 42, "firemaking": 49, "magic": 37, "mining": 40, "strength": 37,
                   "thieving": 40, "cooking": 20, "prayer": 10, "defence": 20, "crafting": 40,
                   "farming": 23, "ranged": 19, "woodcutting": 30},
        "hard": {"agility": 59, "herblore": 52, "mining": 60, "runecraft": 56, "slayer": 72,
                 "woodcutting": 71, "fishing": 53, "cooking": 53, "thieving": 58, "defence": 50,
                 "crafting": 40, "firemaking": 49, "prayer": 70},
        "elite": {"agility": 80, "farming": 91, "herblore": 81, "mining": 60, "runecraft": 88,
                  "woodcutting": 75, "fishing": 53, "cooking": 53, "thieving": 58, "defence": 50,
                  "crafting": 40, "firemaking": 49, "prayer": 70},
    },
    "fremennik": {
        "easy": {"attack": 20, "strength": 20, "defence": 20, "ranged": 5, "firemaking": 15,
                 "crafting": 23, "smithing": 20, "mining": 20, "thieving": 5, "hunter": 11,
                 "woodcutting": 15},
        "medium": {"mining": 40, "defence": 30, "agility": 35, "smithing": 50, "crafting": 31,
                   "firemaking": 40, "thieving": 42, "slayer": 47, "hunter": 35, "construction": 37},
        "hard": {"mining": 70, "herblore": 66, "fishing": 53, "cooking": 53, "thieving": 75,
                 "crafting": 61, "firemaking": 49, "magic": 72, "woodcutting": 56, "slayer": 47,
                 "hunter": 55, "agility": 35},
        "elite": {"hitpoints": 70, "strength": 70, "mining": 70, "agility": 80, "smithing": 60,
                  "defence": 40, "herblore": 66, "fishing": 53, "ranged": 70, "thieving": 75,
                  "cooking": 53, "crafting": 80, "magic": 72, "woodcutting": 56, "runecraft": 82,
                  "slayer": 83, "hunter": 55, "combat": 100},
    },
    "kandarin": {
        "easy": {"fishing": 16, "farming": 13, "agility": 20},
        "medium": {"agility": 36, "herblore": 48, "fishing": 46, "cooking": 43, "magic": 45,
                   "fletching": 50, "farming": 26, "woodcutting": 36, "ranged": 40, "mining": 30,
                   "smithing": 30, "strength": 22},
        "hard": {"fishing": 70, "agility": 60, "fletching": 70, "woodcutting": 60, "firemaking": 65,
                 "smithing": 75, "magic": 56, "herblore": 48, "thieving": 53, "cooking": 43,
                 "ranged": 40, "prayer": 70, "defence": 70, "construction": 50, "combat": 100},
        "elite": {"fishing": 76, "cooking": 80, "herblore": 86, "crafting": 85, "firemaking": 85,
                  "magic": 87, "smithing": 90, "farming": 79, "agility": 60},
    },
    "karamja": {
        "easy": {"agility": 10, "mining": 40},
        "medium": {"agility": 32, "herblore": 3, "fishing": 65, "cooking": 16, "crafting": 20,
                   "woodcutting": 50, "farming": 27, "hunter": 41},
        "hard": {"mining": 52, "strength": 50, "agility": 53, "smithing": 40, "herblore": 25,
                 "fishing": 65, "ranged": 42, "thieving": 50, "cooking": 53, "crafting": 50,
                 "magic": 59, "woodcutting": 50, "runecraft": 44, "slayer": 50, "farming": 27,
                 "hunter": 41, "combat": 100},
        "elite": {"mining": 52, "strength": 50, "agility": 53, "smithing": 40, "herblore": 87,
                  "fishing": 65, "ranged": 42, "thieving": 50, "cooking": 53, "crafting": 50,
                  "magic": 59, "woodcutting": 50, "runecraft": 91, "slayer": 50, "farming": 72,
                  "hunter": 41, "combat": 100},
    },
    "kourend & kebos": {
        "easy": {"mining": 15, "thieving": 25, "construction": 25, "fishing": 20, "herblore": 12},
        "medium": {"mining": 42, "agility": 49, "fishing": 43, "crafting": 31, "firemaking": 50,
                   "farming": 45, "construction": 30, "hunter": 53, "woodcutting": 50, "thieving": 25},
        "hard": {"mining": 65, "smithing": 70, "defence": 40, "herblore": 31, "fishing": 43,
                 "thieving": 49, "firemaking": 50, "magic": 66, "agility": 49, "woodcutting": 60,
                 "slayer": 62, "farming": 74, "hunter": 53, "construction": 30, "combat": 85},
        "elite": {"runecraft": 77, "mining": 65, "crafting": 38, "woodcutting": 90, "fishing": 82,
                  "cooking": 84, "slayer": 95, "magic": 90, "fletching": 40, "farming": 85,
                  "combat": 85},
    },
    "lumbridge & draynor": {
        "easy": {"runecraft": 5, "slayer": 7, "woodcutting": 15, "firemaking": 15, "fishing": 15},
        "medium": {"agility": 20, "strength": 19, "ranged": 50, "magic": 31, "fishing": 30,
                   "crafting": 38, "woodcutting": 30, "thieving": 38, "hunter": 42, "runecraft": 23,
                   "combat": 70},
        "hard": {"mining": 50, "agility": 46, "smithing": 40, "herblore": 25, "fishing": 53,
                 "ranged": 50, "thieving": 53, "cooking": 70, "prayer": 52, "crafting": 70,
                 "firemaking": 65, "magic": 60, "woodcutting": 57, "runecraft": 59, "farming": 63,
                 "hunter": 42, "combat": 70},
        "elite": {"attack": 50, "hitpoints": 50, "mining": 72, "strength": 70, "agility": 70,
                  "smithing": 88, "defence": 65, "herblore": 70, "fishing": 62, "ranged": 70,
                  "thieving": 78, "cooking": 72, "prayer": 52, "crafting": 70, "firemaking": 75,
                  "magic": 75, "fletching": 70, "woodcutting": 75, "runecraft": 76, "slayer": 74,
                  "farming": 70, "construction": 70, "hunter": 70, "sailing": 52, "combat": 85},
    },
    "morytania": {
        "easy": {"crafting": 15, "cooking": 12, "slayer": 15, "farming": 23, "combat": 20},
        "medium": {"hunter": 29, "agility": 40, "woodcutting": 45, "cooking": 40, "herblore": 22,
                   "slayer": 42, "smithing": 35},
        "hard": {"magic": 66, "construction": 50, "agility": 71, "firemaking": 50, "woodcutting": 50,
                 "farming": 47, "slayer": 58, "mining": 55, "thieving": 53, "prayer": 70,
                 "defence": 70, "crafting": 45},
        "elite": {"fishing": 96, "strength": 76, "firemaking": 80, "magic": 83, "crafting": 84,
                  "slayer": 85, "defence": 70},
    },
    "varrock": {
        "easy": {"mining": 15, "agility": 13, "crafting": 8, "runecraft": 9, "fishing": 20,
                 "thieving": 5},
        "medium": {"agility": 30, "herblore": 10, "fishing": 20, "thieving": 25, "crafting": 36,
                   "firemaking": 40, "magic": 25, "farming": 30, "combat": 40},
        "hard": {"smithing": 20, "thieving": 53, "firemaking": 60, "magic": 54, "woodcutting": 60,
                 "agility": 51, "prayer": 52, "farming": 68, "construction": 50, "hunter": 66,
                 "ranged": 40, "combat": 40},
        "elite": {"smithing": 89, "herblore": 90, "cooking": 95, "fletching": 81, "runecraft": 78,
                  "magic": 86, "mining": 60, "thieving": 53, "agility": 51, "farming": 68,
                  "construction": 50, "hunter": 66, "combat": 40},
    },
    "western provinces": {
        "easy": {"mining": 15, "fletching": 20, "hunter": 9, "combat": 40},
        "medium": {"agility": 37, "mining": 40, "smithing": 30, "herblore": 18, "fishing": 46,
                   "cooking": 42, "crafting": 25, "firemaking": 35, "magic": 46, "woodcutting": 35,
                   "hunter": 31, "combat": 70},
        "hard": {"mining": 70, "agility": 56, "smithing": 45, "fishing": 62, "ranged": 70,
                 "thieving": 75, "cooking": 70, "crafting": 40, "firemaking": 50, "magic": 66,
                 "woodcutting": 50, "farming": 68, "construction": 65, "hunter": 69, "combat": 100},
        "elite": {"agility": 85, "fletching": 85, "thieving": 85, "farming": 75, "slayer": 93,
                  "ranged": 70, "magic": 66, "mining": 70, "fishing": 62, "cooking": 70,
                  "firemaking": 50, "construction": 65, "hunter": 69, "combat": 100},
    },
    "wilderness": {
        "easy": {"magic": 21, "agility": 15, "mining": 15},
        "medium": {"mining": 55, "woodcutting": 61, "agility": 52, "magic": 60, "slayer": 50,
                   "smithing": 50},
        "hard": {"mining": 55, "agility": 64, "smithing": 75, "fishing": 53, "magic": 66,
                 "hunter": 67, "slayer": 68},
        "elite": {"mining": 85, "smithing": 90, "fishing": 85, "cooking": 90, "magic": 96,
                  "woodcutting": 75, "firemaking": 75, "thieving": 84, "slayer": 83, "agility": 64},
    },
}

# Quest skill-gate shorthands (effective mins incl. sub-quests, approximated)
CABIN_FEVER = {"agility": 42, "crafting": 45, "smithing": 50, "ranged": 40}
DS2 = {"magic": 75, "smithing": 70, "mining": 68, "crafting": 62, "agility": 60, "thieving": 60}
MM2 = {"slayer": 69, "hunter": 60, "agility": 55, "thieving": 55, "firemaking": 60, "crafting": 70}
SOTE = {"agility": 70, "construction": 70, "farming": 70, "herblore": 70, "hunter": 70,
        "mining": 70, "smithing": 70, "woodcutting": 70, "combat": 100}
DT2Q = {"firemaking": 75, "magic": 75, "thieving": 70, "herblore": 62, "runecraft": 60,
        "construction": 60, "combat": 110}

# --- Boss tasks: own category, requirements follow the wiki's "recommended
# stats" style (combat stats, prayer, plus quest gates where relevant).
# Matching any of these patterns ALSO moves the task to the "boss" category.
BOSS_PATTERNS = [
    (r"raids \(cox|cox or tob|theatre|tombs of amascut|vial of blood",
     {"combat": 110, "attack": 75, "strength": 75, "defence": 75, "ranged": 75, "magic": 75, "prayer": 70}),
    (r"vorkath",
     {**DS2, "combat": 100, "ranged": 75, "defence": 70, "prayer": 70}),
    (r"zulrah",
     {"combat": 90, "ranged": 75, "magic": 75, "defence": 70, "prayer": 62, "agility": 56}),
    (r"cerberus|granite boots",
     {"slayer": 91, "combat": 100, "attack": 75, "strength": 75, "defence": 75, "prayer": 74}),
    (r"kraken|uncharged trident", {"slayer": 87, "magic": 75, "defence": 60}),
    (r"thermonuclear", {"slayer": 93, "magic": 75, "defence": 70}),
    (r"unsired|abyssal whip",
     {"slayer": 85, "combat": 100, "attack": 75, "strength": 75, "defence": 70, "magic": 70, "prayer": 70}),
    (r"kalphite queen",
     {"combat": 95, "attack": 75, "strength": 75, "defence": 75, "ranged": 70, "prayer": 70}),
    (r"kbd", {"combat": 85, "attack": 70, "strength": 70, "defence": 70, "prayer": 43}),
    (r"dagannoth king",
     {"combat": 90, "ranged": 75, "magic": 75, "defence": 75, "prayer": 70}),
    (r"god wars", {"combat": 90, "defence": 70, "prayer": 62}),  # boss doors have per-style 70 reqs
    (r"grotesque guardian|granite dust",
     {"slayer": 75, "combat": 90, "attack": 70, "strength": 70, "defence": 70, "prayer": 62}),
    (r"wildy bosses|broken dragon pickaxe",
     {"combat": 100, "attack": 75, "strength": 75, "defence": 75, "prayer": 70}),
    (r"chaos fanatic|scorpia|crazy arch", {"combat": 80, "defence": 70, "prayer": 43}),
    (r"sarachnis", {"combat": 85, "attack": 70, "strength": 70, "defence": 70}),
    (r"scurrius", {"combat": 30}),
    (r"hill giant club|bryophyta", {"combat": 50, "attack": 40, "strength": 40, "defence": 40}),
    (r"mole claw|mole skin", {"combat": 65, "attack": 60, "strength": 60, "defence": 60}),
    (r"barrows|bolt rack",
     {"combat": 70, "attack": 60, "strength": 60, "defence": 60, "magic": 50, "prayer": 43}),
    (r"fire cape", {"combat": 90, "ranged": 70, "defence": 60, "prayer": 43}),
    (r"spirit shield|holy elixir",  # Corporeal Beast
     {"combat": 100, "attack": 75, "strength": 75, "defence": 75, "prayer": 70}),
    (r"gauntlet|crystal grail",
     {**SOTE, "defence": 70, "ranged": 70, "magic": 70, "prayer": 70}),
    (r"dt2 bosses",
     {**DT2Q, "attack": 75, "strength": 75, "defence": 75, "prayer": 70}),
    (r"phantom muspah", {"combat": 100, "ranged": 75, "prayer": 70, "agility": 64}),
    (r"moons of peril", {"combat": 75, "attack": 70, "strength": 70, "defence": 70}),
    (r"hueycoatl", {"combat": 90, "attack": 70, "defence": 70}),  # EST
    (r"amoxliatl", {"combat": 70, "defence": 60}),  # EST
    (r"royal titans|steel ring", {"combat": 80, "magic": 70, "defence": 70}),  # EST
    (r"yama|doom of mokhaiotl", {"combat": 110, "defence": 75, "prayer": 70}),  # EST
    (r"maggot king", {"combat": 100, "defence": 70}),  # EST
    (r"araxxor|araxyte|aranea boot",
     {"slayer": 92, "combat": 100, "attack": 75, "strength": 75, "defence": 75, "prayer": 70}),
    (r"tormented demon",  # While Guthix Sleeps
     {"combat": 110, "attack": 75, "strength": 75, "defence": 75, "prayer": 70}),
    (r"fortis colosseum|sunfire splinter", {"combat": 110, "defence": 75, "prayer": 74}),
    (r"nihil shard|ceremonial robe", {"combat": 100, "defence": 70, "prayer": 70}),
    (r"boss pet", {"combat": 90, "defence": 70}),
]

# Ordered pattern rules: first regex (case-insensitive, searched) that matches wins.
# EST = estimate for 2025-26 content, tune after testing.
PATTERNS = [
    (r"demonic gorilla", {**MM2, "combat": 100, "attack": 75, "ranged": 75, "prayer": 70}),
    (r"monkey backpack", {"agility": 48, **MM2}),
    (r"elven signet|enhanced crystal teleport seed|blood shard", SOTE),
    (r"dust battlestaff|mist battlestaff", {"slayer": 93}),  # superior smoke devils EST
    (r"dragon limbs", {"combat": 90}),
    (r"venator", {"combat": 90}),
    (r"armoured zombies", {"combat": 60}),  # Defender of Varrock
    (r"revenant|rev cave|bracelet of ethereum", {"combat": 60}),
    (r"custodian stalker", {"slayer": 90, "combat": 90}),  # EST
    (r"dagon'hai", {"slayer": 60, "combat": 80}),  # Larran's chest EST

    # --- Slayer drops ---
    (r"crawling hand", {"slayer": 5}),
    (r"cockatrice", {"slayer": 25}),
    (r"mogres", {"slayer": 32}),
    (r"brine sabre", {"slayer": 47}),
    (r"turoth", {"slayer": 55}),
    (r"black mask", {"slayer": 58, **CABIN_FEVER}),
    (r"infernal mage", {"slayer": 45}),
    (r"mystic.*\(dark\)", {"slayer": 65}),
    (r"mystic.*\(light\)", {"combat": 70}),
    (r"basilisk jaw", {"slayer": 60, "crafting": 65}),  # Fremennik Exiles
    (r"basilisk head", {"slayer": 40}),
    (r"kurask head|kurasks", {"slayer": 70}),
    (r"gargoyle", {"slayer": 75}),
    (r"granite (helm|legs|longsword)", {"slayer": 70, "combat": 90}),
    (r"dragon boots", {"slayer": 83, "combat": 90}),
    (r"dark bow", {"slayer": 90}),
    (r"mount karuulm", {"slayer": 62}),
    (r"warped sceptre", {"slayer": 56}),
    (r"shaman mask|dragon warhammer", {"combat": 80}),  # lizardman shamans
    (r"elder chaos", {"combat": 70}),
    (r"long bone|curved bone|chewed bones", {"combat": 60}),

    # --- Minigames & activities ---
    (r"wintertodt", {"firemaking": 50}),
    (r"tempoross", {"fishing": 35}),
    (r"fish sack", {"fishing": 70}),  # EST
    (r"guardians of the rift", {"runecraft": 27}),
    (r"giants' foundry|colossal blade", {"smithing": 15}),
    (r"forestry", {"woodcutting": 15}),
    (r"camdozaal", {"mining": 14, "fishing": 7}),
    (r"fighter torso|fighter hat|healer hat|runner hat|ranger hat|runner boots|penance|granite body",
     {"combat": 60}),  # Barbarian Assault
    (r"halo|decorative|hood & cloak|banner", {}),  # Castle Wars
    (r"void|pest control", {"combat": 40}),
    (r"elite void", {**DIARY["western provinces"]["hard"]}),
    (r"angler piece", {"fishing": 15}),
    (r"gnome restaurant", {}),
    (r"master wand|mage's book|infinity|mta|bones to peaches", {"magic": 33}),
    (r"rogue equipment", {"thieving": 50, "agility": 50}),
    (r"shades of mort'ton", {"firemaking": 5}),
    (r"lumberjack", {"woodcutting": 30}),
    (r"gricoller|farmer's equipment|seed box|herb sack", {"farming": 34}),  # Tithe Farm
    (r"rum\b|the stuff|naval|flag", CABIN_FEVER | {"cooking": 40}),  # Trouble Brewing
    (r"barbarian rod", {"fishing": 48, "agility": 15, "strength": 15}),
    (r"pearl (fly )?fishing rod", {"fishing": 43, "hunter": 35}),  # aerial fishing
    (r"merfolk trident", {"fishing": 47, "hunter": 44}),
    (r"champion scroll", {"combat": 60}),
    (r"marksman|ogre (forester|expert)|dragon archer", {"ranged": 40}),  # Ranging Guild
    (r"creature creation", {"construction": 10}),
    (r"dragon defender", {"attack": 60, "strength": 60, "defence": 60}),
    (r"rune defender", {"attack": 60, "strength": 60}),
    (r"fossil island|ancient pages", {"agility": 35}),  # Horror from the Deep / Bone Voyage
    (r"prospector", {"mining": 30}),
    (r"graceful", {"agility": 30}),
    (r"mining gloves", {"mining": 60}),
    (r"superior mining", {"mining": 70}),
    (r"expert mining", {"mining": 85}),
    (r"tzhaar|obsidian|toktz", {"combat": 70}),
    (r"big swordfish", {"fishing": 50}),
    (r"big bass", {"fishing": 46}),
    (r"big shark", {"fishing": 76}),
    (r"ecumenical", {"combat": 60}),
    (r"dark totem|ancient shard", {"combat": 60}),
    (r"skull half|sceptre|mossy key|giant key", {"combat": 30}),
    (r"crab claw|crab shell", {}),
    (r"xeric's talisman", {"combat": 50}),
    (r"mahogany homes|supply crate|amy's saw|carpenter|plank sack", {"construction": 20}),
    (r"hallowed sepulchre", {"agility": 52, "combat": 70}),
    (r"pharaoh's sceptre", {"thieving": 44}),
    (r"dragon spear|shield left half|pirate's hook", {"combat": 70}),
    (r"grubby chest|egg sac", {"combat": 60}),
    (r"soul cape|ectoplasmator", {"combat": 40}),  # Soul Wars
    (r"celestial ring|star fragment", {"mining": 10}),
    (r"hunter guild", {"hunter": 46}),
    (r"alchemist|prescription goggles|chugging barrel|reagent pouch", {"herblore": 60}),  # Mixology EST
    (r"huasca seed", {"combat": 60}),  # EST
    (r"calcified acorn", {"mining": 41}),  # EST
    (r"colossal wyrm|sulphur blade", {"agility": 50}),  # EST Varlamore agility
    (r"vale totem", {"fletching": 35}),  # EST
    (r"tier 5 shayzien", {"combat": 60}),
    (r"coal bag|gem bag", {"mining": 30}),  # Motherlode EST
    (r"blood shard", {"combat": 80}),
    (r"ash covered tome", {"firemaking": 50}),  # EST
    (r"volcanic mine", {"mining": 50}),
    (r"heat-proof vessel", {"mining": 50, "sailing": 50}),  # EST
    (r"brutus", {"combat": 60}),  # EST

    # --- Sailing-era content (2025-26), all EST — tune after testing ---
    (r"tempor tantrum", {"sailing": 30}),
    (r"jubbly jive", {"sailing": 50}),
    (r"gwenith glide", {"sailing": 70}),
    (r"dragon (keel|helm schematic|salvaging|cannon|nails|metal sheet|cannonball)", {"sailing": 70}),
    (r"schematic", {"sailing": 45}),
    (r"paint", {"sailing": 40}),
    (r"sea treasure|medallion of the deep", {"sailing": 40}),
    (r"salvaging|shipwreck", {"sailing": 40}),
    (r"ray barbs|boat bottle|squid beak|blue krill|facility bottle|echo pearl|bottled storm",
     {"sailing": 40}),
    (r"narwhal horn|broken dragon hook|aquanite tendon|swift albatross", {"sailing": 65}),
    (r"golden haddock|orangefin|huge halibut|purplefin|swift marlin|gryphon feather",
     {"sailing": 60, "fishing": 70}),
    (r"mask of ranul", {"sailing": 30}),
    (r"horn of plenty|belle's folly|earthbound tecpatl|hosidius blueprint", {}),

    # --- Clues (obtaining + completing, rough gates) ---
    (r"beginner clue|easy clue", {}),
    (r"medium clue", {"combat": 40}),
    (r"hard clue", {"combat": 70}),
    (r"elite clue", {"combat": 90}),
    (r"master clue", {"combat": 100}),
]

_DIARY_RE = re.compile(r"complete the (.+) (easy|medium|hard|elite) diary", re.IGNORECASE)

# Recommended-stat prayer gates are capped here (user preference). Diary prayer
# requirements are real wiki requirements and are NOT capped.
PRAYER_CAP = 45


def _cap(reqs):
    if "prayer" in reqs and reqs["prayer"] > PRAYER_CAP:
        return {**reqs, "prayer": PRAYER_CAP}
    return reqs


_BOSS_COMPILED = [(re.compile(p, re.IGNORECASE), _cap(reqs)) for p, reqs in BOSS_PATTERNS]
_COMPILED = [(re.compile(p, re.IGNORECASE), _cap(reqs)) for p, reqs in PATTERNS]

# ---- Boss KILL tasks (the "Bosses" category): pure kill counts, slayer-style.
# (template with {n}, count_lo, count_hi, recommended-stat requirements)
_MELEE70 = {"attack": 70, "strength": 70, "defence": 70}
_MELEE75 = {"attack": 75, "strength": 75, "defence": 75}
_WILDY = {"combat": 100, **_MELEE75, "prayer": 45}
_GWD = {"combat": 90, "defence": 70, "prayer": 45}
_RAID = {"combat": 110, **_MELEE75, "ranged": 75, "magic": 75, "prayer": 45}
_DT2B = {**DT2Q, **_MELEE75, "prayer": 45}

_BOSS_KILLS_RAW = [
    ("Kill Scurrius {n} times", 10, 30, {"combat": 30}),
    ("Kill Obor {n} times", 1, 3, {"combat": 50, "attack": 40, "strength": 40, "defence": 40}),
    ("Kill Bryophyta {n} times", 1, 3, {"combat": 50, "attack": 40, "strength": 40, "defence": 40}),
    ("Kill the Giant Mole {n} times", 10, 25, {"combat": 65, "attack": 60, "strength": 60, "defence": 60}),
    ("Complete {n} Barrows runs", 5, 15, {"combat": 70, "attack": 60, "strength": 60, "defence": 60, "magic": 50, "prayer": 43}),
    ("Kill Sarachnis {n} times", 10, 25, {"combat": 85, **_MELEE70}),
    ("Kill the King Black Dragon {n} times", 10, 25, {"combat": 85, **_MELEE70, "prayer": 43}),
    ("Kill Scorpia {n} times", 8, 20, {"combat": 80, "defence": 70, "prayer": 43}),
    ("Kill the Chaos Fanatic {n} times", 8, 20, {"combat": 80, "defence": 70, "prayer": 43}),
    ("Kill the Crazy Archaeologist {n} times", 8, 20, {"combat": 80, "defence": 70, "prayer": 43}),
    ("Kill the Chaos Elemental {n} times", 5, 15, _WILDY),
    ("Kill Callisto or Artio {n} times", 5, 15, _WILDY),
    ("Kill Vet'ion or Calvar'ion {n} times", 5, 15, _WILDY),
    ("Kill Venenatis or Spindel {n} times", 5, 15, _WILDY),
    ("Kill Hespori {n} times", 1, 3, {"farming": 65, "combat": 60}),
    ("Kill Skotizo {n} times", 1, 3, {"combat": 90, "defence": 70}),
    ("Kill Zalcano {n} times", 5, 15, SOTE),
    ("Kill the Kalphite Queen {n} times", 8, 20, {"combat": 95, **_MELEE75, "ranged": 70, "prayer": 45}),
    ("Kill each Dagannoth King {n} times", 8, 20, {"combat": 90, "ranged": 75, "magic": 75, "defence": 75, "prayer": 45}),
    ("Kill General Graardor {n} times", 10, 25, {**_GWD, "strength": 70}),
    ("Kill Kree'arra {n} times", 10, 25, {**_GWD, "ranged": 70}),
    ("Kill K'ril Tsutsaroth {n} times", 10, 25, {**_GWD, "hitpoints": 70}),
    ("Kill Commander Zilyana {n} times", 10, 25, {**_GWD, "agility": 70}),
    ("Kill Zulrah {n} times", 10, 25, {"combat": 90, "ranged": 75, "magic": 75, "defence": 70, "prayer": 45, "agility": 56}),
    ("Kill Vorkath {n} times", 10, 25, {**DS2, "combat": 100, "ranged": 75, "defence": 70, "prayer": 45}),
    ("Complete the Fight Caves {n} times (TzTok-Jad)", 1, 2, {"combat": 90, "ranged": 70, "defence": 60, "prayer": 43}),
    ("Kill the Kraken {n} times", 15, 40, {"slayer": 87, "magic": 75}),
    ("Kill Cerberus {n} times", 10, 25, {"slayer": 91, "combat": 100, **_MELEE75, "prayer": 45}),
    ("Kill the Thermonuclear Smoke Devil {n} times", 15, 40, {"slayer": 93, "magic": 75, "defence": 70}),
    ("Kill the Abyssal Sire {n} times", 8, 20, {"slayer": 85, "combat": 100, **_MELEE75, "magic": 70, "prayer": 45}),
    ("Kill the Grotesque Guardians {n} times", 10, 25, {"slayer": 75, "combat": 90, **_MELEE70, "prayer": 45}),
    ("Complete {n} Gauntlet runs", 3, 8, {**SOTE, "defence": 70, "ranged": 70, "magic": 70, "prayer": 45}),
    ("Kill the Corporeal Beast {n} times", 5, 15, {"combat": 100, **_MELEE75, "prayer": 45}),
    ("Kill the Phantom Muspah {n} times", 5, 15, {"combat": 100, "ranged": 75, "prayer": 45, "agility": 64}),
    ("Complete {n} Moons of Peril runs", 3, 8, {"combat": 75, **_MELEE70}),
    ("Kill Amoxliatl {n} times", 10, 20, {"combat": 70, "defence": 60}),
    ("Kill the Hueycoatl {n} times", 5, 10, {"combat": 90, "attack": 70, "defence": 70}),
    ("Kill the Royal Titans {n} times", 5, 15, {"combat": 80, "magic": 70, "defence": 70}),
    ("Kill Araxxor {n} times", 10, 20, {"slayer": 92, "combat": 100, **_MELEE75, "prayer": 45}),
    ("Kill {n} Tormented Demons", 10, 25, {"combat": 110, **_MELEE75, "prayer": 45}),
    ("Kill Vardorvis {n} times", 5, 12, _DT2B),
    ("Kill the Leviathan {n} times", 5, 12, _DT2B),
    ("Kill the Whisperer {n} times", 5, 12, _DT2B),
    ("Kill Duke Sucellus {n} times", 5, 12, _DT2B),
    ("Kill Nex {n} times", 5, 10, {"combat": 110, "ranged": 80, "defence": 75, "prayer": 45}),
    ("Kill the Nightmare {n} times", 3, 8, {"combat": 110, **_MELEE75, "magic": 75, "prayer": 45}),
    ("Complete {n} Chambers of Xeric raids", 2, 5, _RAID),
    ("Complete {n} Theatre of Blood raids", 2, 5, _RAID),
    ("Complete {n} Tombs of Amascut raids", 2, 5, _RAID),
    ("Complete {n} Fortis Colosseum waves", 4, 12, {"combat": 110, "defence": 75, "prayer": 45}),
    ("Kill Yama {n} times", 3, 8, {"combat": 110, "defence": 75, "prayer": 45}),  # EST
    ("Kill the Doom of Mokhaiotl {n} times", 3, 8, {"combat": 110, "defence": 75, "prayer": 45}),  # EST
]
BOSS_KILLS = [(t, lo, hi, _cap(r)) for t, lo, hi, r in _BOSS_KILLS_RAW]


def is_boss(task_name):
    """True if the task belongs to the boss category."""
    return any(rx.search(task_name) for rx, _ in _BOSS_COMPILED)


def reqs_for(task_name):
    """Return the requirement dict for a task name (empty dict = no gate)."""
    m = _DIARY_RE.search(task_name)
    if m:
        region, tier = m.group(1).strip().lower(), m.group(2).lower()
        return DIARY.get(region, {}).get(tier, {})
    for rx, reqs in _BOSS_COMPILED:
        if rx.search(task_name):
            return dict(reqs)
    for rx, reqs in _COMPILED:
        if rx.search(task_name):
            return dict(reqs)
    return {}
