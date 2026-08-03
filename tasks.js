// AFK task pool — source: https://oldschool.runescape.wiki/w/Guide:AFK_Skilling_Methods
// reqs: { skillKey: minLevel } — all must be met for the task to be offered.
// f2p: true = doable on free-to-play worlds.
// afk: how long one click/action lasts without further input.

const SKILL_META = {
  attack:       { name: 'Attack',       emoji: '🗡️' },
  strength:     { name: 'Strength',     emoji: '💪' },
  defence:      { name: 'Defence',      emoji: '🛡️' },
  hitpoints:    { name: 'Hitpoints',    emoji: '❤️' },
  ranged:       { name: 'Ranged',       emoji: '🏹' },
  prayer:       { name: 'Prayer',       emoji: '✨' },
  magic:        { name: 'Magic',        emoji: '🔮' },
  cooking:      { name: 'Cooking',      emoji: '🍳' },
  woodcutting:  { name: 'Woodcutting',  emoji: '🪓' },
  fletching:    { name: 'Fletching',    emoji: '🎯' },
  fishing:      { name: 'Fishing',      emoji: '🎣' },
  firemaking:   { name: 'Firemaking',   emoji: '🔥' },
  crafting:     { name: 'Crafting',     emoji: '🧵' },
  smithing:     { name: 'Smithing',     emoji: '⚒️' },
  mining:       { name: 'Mining',       emoji: '⛏️' },
  herblore:     { name: 'Herblore',     emoji: '🌿' },
  agility:      { name: 'Agility',      emoji: '🏃' },
  thieving:     { name: 'Thieving',     emoji: '🥷' },
  slayer:       { name: 'Slayer',       emoji: '💀' },
  farming:      { name: 'Farming',      emoji: '🌾' },
  runecraft:    { name: 'Runecraft',    emoji: '🌀' },
  hunter:       { name: 'Hunter',       emoji: '🪤' },
  construction: { name: 'Construction', emoji: '🏠' },
  sailing:      { name: 'Sailing',      emoji: '⛵' },
};

const TASKS = [
  // Woodcutting
  { name: 'Infected Roots', skill: 'woodcutting', reqs: { woodcutting: 80 }, afk: '30:00', notes: 'Log basket recommended', f2p: false },
  { name: 'Rosewood Trees', skill: 'woodcutting', reqs: { woodcutting: 92 }, afk: '4:35', f2p: false },
  { name: 'Redwood Trees', skill: 'woodcutting', reqs: { woodcutting: 90 }, afk: '4:24', f2p: false },
  { name: 'Ironwood Trees', skill: 'woodcutting', reqs: { woodcutting: 80 }, afk: '4:00', f2p: false },
  { name: 'Magic Trees', skill: 'woodcutting', reqs: { woodcutting: 75 }, afk: '3:54', f2p: false },
  { name: 'Camphor Trees', skill: 'woodcutting', reqs: { woodcutting: 66 }, afk: '2:00', f2p: false },
  { name: 'Yew Trees', skill: 'woodcutting', reqs: { woodcutting: 60 }, afk: '1:54', f2p: true },
  { name: 'Mahogany Trees', skill: 'woodcutting', reqs: { woodcutting: 50 }, afk: '1:00', f2p: false },
  { name: 'Maple Trees', skill: 'woodcutting', reqs: { woodcutting: 45 }, afk: '1:00', f2p: true },

  // Mining
  { name: 'Guardian Fragments (GOTR)', skill: 'mining', reqs: { mining: 1, runecraft: 27 }, afk: '10:00', notes: 'XP capped at 1,250 per round', f2p: false },
  { name: 'Shooting Stars', skill: 'mining', reqs: { mining: 10 }, afk: '7:00', f2p: true },
  { name: 'Duke Sucellus Mining', skill: 'mining', reqs: { mining: 72 }, afk: '5:00', f2p: false },
  { name: 'Amethyst Crystals', skill: 'mining', reqs: { mining: 92 }, afk: '1:57', notes: 'Expert mining gloves', f2p: false },
  { name: 'Daeyalt Essence', skill: 'mining', reqs: { mining: 60 }, afk: '1:00', f2p: false },
  { name: 'Calcified Rocks', skill: 'mining', reqs: { mining: 41 }, afk: '0:35', notes: 'Gives blessed bone shards for Prayer', f2p: false },
  { name: 'Barronite Rocks', skill: 'mining', reqs: { mining: 14 }, afk: '0:20', f2p: true },

  // Cooking
  { name: 'Churning (cheese)', skill: 'cooking', reqs: { cooking: 21 }, afk: '7:17', f2p: false },
  { name: 'Cooking Fish/Meat', skill: 'cooking', reqs: { cooking: 1 }, afk: '1:07', f2p: true },
  { name: "Forester's Rations", skill: 'cooking', reqs: { cooking: 35 }, afk: '0:49', f2p: false },

  // Thieving
  { name: 'Pickpocketing Wealthy Citizens', skill: 'thieving', reqs: { thieving: 50 }, afk: '1:32', f2p: false },
  { name: 'Burgling Houses (Varlamore)', skill: 'thieving', reqs: { thieving: 50 }, afk: '0:55', notes: 'Requires house keys', f2p: false },
  { name: 'One-click Summer Garden', skill: 'thieving', reqs: { thieving: 65 }, afk: '0:36', f2p: false },

  // Smithing
  { name: 'Smithing One-bar Items', skill: 'smithing', reqs: { smithing: 1 }, afk: '1:07', f2p: true },
  { name: 'Smithing Cannonballs', skill: 'smithing', reqs: { smithing: 35 }, afk: '1:02', notes: 'Double ammo mould', f2p: false },

  // Fletching
  { name: 'Bolt Tips', skill: 'fletching', reqs: { fletching: 11 }, afk: '1:21', f2p: false },
  { name: 'Battlestaves', skill: 'fletching', reqs: { fletching: 40 }, afk: '0:49', f2p: false },
  { name: 'Redwood Shields', skill: 'fletching', reqs: { fletching: 92 }, afk: '0:47', f2p: false },
  { name: 'Cutting Unstrung Bows', skill: 'fletching', reqs: { fletching: 5 }, afk: '0:32', f2p: false },

  // Firemaking
  { name: "Forester's Campfire", skill: 'firemaking', reqs: { firemaking: 1 }, afk: '2:31', f2p: true },

  // Fishing
  { name: 'The Stranglewood Fishing', skill: 'fishing', reqs: { fishing: 63 }, afk: '30:00', f2p: false },
  { name: 'Karambwanji', skill: 'fishing', reqs: { fishing: 5 }, afk: '20:00', f2p: false },
  { name: 'Dark Crab', skill: 'fishing', reqs: { fishing: 85 }, afk: '7:32', notes: 'Fish barrel + elite wilderness diary — in the Wilderness!', f2p: false },
  { name: 'Civitas illa Fortis Fishing', skill: 'fishing', reqs: { fishing: 1 }, afk: '7:00', f2p: false },
  { name: 'Cave Eel', skill: 'fishing', reqs: { fishing: 38 }, afk: '4:58', f2p: false },
  { name: 'Karambwan', skill: 'fishing', reqs: { fishing: 65 }, afk: '4:13', f2p: false },
  { name: 'Anglerfish', skill: 'fishing', reqs: { fishing: 82 }, afk: '2:37', f2p: false },
  { name: 'General Fishing Spot', skill: 'fishing', reqs: { fishing: 1 }, afk: '1:57', f2p: true },
  { name: 'Barbarian Fishing (Quidamortem)', skill: 'fishing', reqs: { fishing: 48 }, afk: '1:57', f2p: false },
  { name: 'Sacred Eel', skill: 'fishing', reqs: { fishing: 87 }, afk: '1:00', notes: "Rada's blessing 4", f2p: false },
  { name: 'Infernal Eel', skill: 'fishing', reqs: { fishing: 80 }, afk: '1:00', notes: "Rada's blessing 4", f2p: false },

  // Agility
  { name: 'POH Agility', skill: 'agility', reqs: { agility: 1, construction: 88 }, afk: '10:00', f2p: false },
  { name: 'Vampyrium Rocks', skill: 'agility', reqs: { agility: 61 }, afk: '7:30', notes: 'Clicking early resets the cooldown', f2p: false },
  { name: 'Pedals', skill: 'agility', reqs: { agility: 30 }, afk: '5:19', f2p: false },

  // Herblore
  { name: 'Making Herb Tar', skill: 'herblore', reqs: { herblore: 11 }, afk: '0:47', f2p: false },
  { name: 'Auto-cleaning Herbs', skill: 'herblore', reqs: { herblore: 3 }, afk: '0:34', f2p: false },
  { name: 'Stackable Secondary Potions', skill: 'herblore', reqs: { herblore: 77 }, afk: '0:31', f2p: false },

  // Runecraft
  { name: 'Blood Runes (Zeah)', skill: 'runecraft', reqs: { runecraft: 77 }, afk: '0:55', f2p: false },
  { name: 'Soul Runes (Zeah)', skill: 'runecraft', reqs: { runecraft: 90 }, afk: '0:55', f2p: false },
  { name: 'ZMI Runecrafting', skill: 'runecraft', reqs: { runecraft: 1 }, afk: '0:25', f2p: false },

  // Magic
  { name: 'Auto-cast Enchant Jewellery', skill: 'magic', reqs: { magic: 7 }, afk: '1:53', f2p: true },
  { name: 'Plank Make', skill: 'magic', reqs: { magic: 86 }, afk: '1:30', f2p: false },
  { name: 'String Jewellery', skill: 'magic', reqs: { magic: 80 }, afk: '0:49', f2p: false },
  { name: 'Splashing', skill: 'magic', reqs: { magic: 1 }, afk: '20:00', f2p: true },

  // Crafting
  { name: 'Firing Clay', skill: 'crafting', reqs: { crafting: 1 }, afk: '1:58', f2p: true },
  { name: 'Glassblowing', skill: 'crafting', reqs: { crafting: 1 }, afk: '0:50', f2p: false },
  { name: 'Spinning', skill: 'crafting', reqs: { crafting: 1 }, afk: '0:50', f2p: true },

  // Strength
  { name: 'Blast Furnace Pump', skill: 'strength', reqs: { strength: 30 }, afk: '30:00', f2p: false },

  // Sailing
  { name: 'Crewmate-only Salvaging', skill: 'sailing', reqs: { sailing: 40 }, afk: '30:00', f2p: false },
  { name: 'Merchant Shipwreck', skill: 'sailing', reqs: { sailing: 87 }, afk: '4:00', f2p: false },
  { name: 'Fremennik Shipwreck', skill: 'sailing', reqs: { sailing: 80 }, afk: '3:38', f2p: false },
  { name: 'Mercenary Shipwreck', skill: 'sailing', reqs: { sailing: 73 }, afk: '3:15', f2p: false },
  { name: 'Pirate Shipwreck', skill: 'sailing', reqs: { sailing: 64 }, afk: '2:38', f2p: false },
  { name: 'Large Shipwreck', skill: 'sailing', reqs: { sailing: 53 }, afk: '2:31', f2p: false },
  { name: 'Barracuda Shipwreck', skill: 'sailing', reqs: { sailing: 35 }, afk: '2:21', f2p: false },
  { name: "Fisherman's Shipwreck", skill: 'sailing', reqs: { sailing: 26 }, afk: '2:12', f2p: false },
  { name: 'Small Shipwreck', skill: 'sailing', reqs: { sailing: 15 }, afk: '1:00', f2p: false },
  { name: 'Crystal Extractor', skill: 'sailing', reqs: { sailing: 73 }, afk: '1:00', f2p: false },

  // Hunter
  { name: 'Stymphike', skill: 'hunter', reqs: { hunter: 82 }, afk: '0:39', f2p: false },
  { name: 'Maniacal Monkey Hunting', skill: 'hunter', reqs: { hunter: 60 }, afk: '0:25', f2p: false },

  // Prayer
  { name: 'Gilded Altar (auto-offer)', skill: 'prayer', reqs: { prayer: 1 }, afk: '1:02', notes: 'Bones on a gilded altar in a POH', f2p: false },

  // Combat
  { name: 'Gemstone Crabs', skill: 'hitpoints', reqs: { hitpoints: 10 }, afk: '10:00', notes: 'Requires Children of the Sun', f2p: false },
  { name: 'Sand Crabs', skill: 'hitpoints', reqs: { hitpoints: 10 }, afk: '10:00', f2p: false },
  { name: 'Ammonite Crabs', skill: 'hitpoints', reqs: { hitpoints: 10 }, afk: '10:00', notes: 'Requires Bone Voyage', f2p: false },
  { name: 'NMZ Melee', skill: 'strength', reqs: { attack: 60, strength: 60 }, afk: '20:00', notes: 'Requires Nightmare Zone quests', f2p: false },
  { name: 'NMZ Ranged', skill: 'ranged', reqs: { ranged: 70 }, afk: '20:00', notes: 'Requires Nightmare Zone quests', f2p: false },
  { name: 'Vyrewatch Sentinels', skill: 'slayer', reqs: { attack: 70, strength: 70, defence: 70 }, afk: '17:00', notes: 'Requires Sins of the Father', f2p: false },
  { name: 'Maniacal Monkeys (Ice Barrage)', skill: 'magic', reqs: { magic: 94 }, afk: '10:00', notes: 'Requires Monkey Madness II', f2p: false },
  { name: 'Maniacal Monkeys (chinning)', skill: 'ranged', reqs: { ranged: 80 }, afk: '10:00', notes: 'MM II + red chinchompas', f2p: false },
];
