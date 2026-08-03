// AFK-tehtäväpankki — lähde: https://oldschool.runescape.wiki/w/Guide:AFK_Skilling_Methods
// reqs: { skillKey: minLevel } — kaikkien pitää täyttyä että tehtävä on tarjolla.
// f2p: true = onnistuu myös free-to-play-worldeissa.
// afk: kuinka pitkään yksi klikkaus/toiminto kestää ilman uutta inputtia.

const SKILL_META = {
  attack:       { fi: 'Attack',       emoji: '🗡️' },
  strength:     { fi: 'Strength',     emoji: '💪' },
  defence:      { fi: 'Defence',      emoji: '🛡️' },
  hitpoints:    { fi: 'Hitpoints',    emoji: '❤️' },
  ranged:       { fi: 'Ranged',       emoji: '🏹' },
  prayer:       { fi: 'Prayer',       emoji: '✨' },
  magic:        { fi: 'Magic',        emoji: '🔮' },
  cooking:      { fi: 'Cooking',      emoji: '🍳' },
  woodcutting:  { fi: 'Woodcutting',  emoji: '🪓' },
  fletching:    { fi: 'Fletching',    emoji: '🎯' },
  fishing:      { fi: 'Fishing',      emoji: '🎣' },
  firemaking:   { fi: 'Firemaking',   emoji: '🔥' },
  crafting:     { fi: 'Crafting',     emoji: '🧵' },
  smithing:     { fi: 'Smithing',     emoji: '⚒️' },
  mining:       { fi: 'Mining',       emoji: '⛏️' },
  herblore:     { fi: 'Herblore',     emoji: '🌿' },
  agility:      { fi: 'Agility',      emoji: '🏃' },
  thieving:     { fi: 'Thieving',     emoji: '🥷' },
  slayer:       { fi: 'Slayer',       emoji: '💀' },
  farming:      { fi: 'Farming',      emoji: '🌾' },
  runecraft:    { fi: 'Runecraft',    emoji: '🌀' },
  hunter:       { fi: 'Hunter',       emoji: '🪤' },
  construction: { fi: 'Construction', emoji: '🏠' },
  sailing:      { fi: 'Sailing',      emoji: '⛵' },
};

const TASKS = [
  // Woodcutting
  { name: 'Infected Roots', skill: 'woodcutting', reqs: { woodcutting: 80 }, afk: '30:00', notes: 'Log basket suositeltu', f2p: false },
  { name: 'Rosewood Trees', skill: 'woodcutting', reqs: { woodcutting: 92 }, afk: '4:35', f2p: false },
  { name: 'Redwood Trees', skill: 'woodcutting', reqs: { woodcutting: 90 }, afk: '4:24', f2p: false },
  { name: 'Ironwood Trees', skill: 'woodcutting', reqs: { woodcutting: 80 }, afk: '4:00', f2p: false },
  { name: 'Magic Trees', skill: 'woodcutting', reqs: { woodcutting: 75 }, afk: '3:54', f2p: false },
  { name: 'Camphor Trees', skill: 'woodcutting', reqs: { woodcutting: 66 }, afk: '2:00', f2p: false },
  { name: 'Yew Trees', skill: 'woodcutting', reqs: { woodcutting: 60 }, afk: '1:54', f2p: true },
  { name: 'Mahogany Trees', skill: 'woodcutting', reqs: { woodcutting: 50 }, afk: '1:00', f2p: false },
  { name: 'Maple Trees', skill: 'woodcutting', reqs: { woodcutting: 45 }, afk: '1:00', f2p: true },

  // Mining
  { name: 'Guardian Fragments (GOTR)', skill: 'mining', reqs: { mining: 1, runecraft: 27 }, afk: '10:00', notes: 'XP-katto 1250/kierros', f2p: false },
  { name: 'Shooting Stars', skill: 'mining', reqs: { mining: 10 }, afk: '7:00', f2p: true },
  { name: 'Duke Sucellus -kaivuu', skill: 'mining', reqs: { mining: 72 }, afk: '5:00', f2p: false },
  { name: 'Amethyst Crystals', skill: 'mining', reqs: { mining: 92 }, afk: '1:57', notes: 'Expert mining gloves', f2p: false },
  { name: 'Daeyalt Essence', skill: 'mining', reqs: { mining: 60 }, afk: '1:00', f2p: false },
  { name: 'Calcified Rocks', skill: 'mining', reqs: { mining: 41 }, afk: '0:35', notes: 'Blessed bone shardeja Prayeriin', f2p: false },
  { name: 'Barronite Rocks', skill: 'mining', reqs: { mining: 14 }, afk: '0:20', f2p: true },

  // Cooking
  { name: 'Juuston kirnuaminen', skill: 'cooking', reqs: { cooking: 21 }, afk: '7:17', f2p: false },
  { name: 'Kalojen/lihan kokkaus', skill: 'cooking', reqs: { cooking: 1 }, afk: '1:07', f2p: true },
  { name: "Forester's Rations", skill: 'cooking', reqs: { cooking: 35 }, afk: '0:49', f2p: false },

  // Thieving
  { name: 'Wealthy Citizen -taskuvarkaus', skill: 'thieving', reqs: { thieving: 50 }, afk: '1:32', f2p: false },
  { name: 'Talomurrot (Varlamore)', skill: 'thieving', reqs: { thieving: 50 }, afk: '0:55', notes: 'Tarvitsee house keyt', f2p: false },
  { name: 'Summer Garden (one-click)', skill: 'thieving', reqs: { thieving: 65 }, afk: '0:36', f2p: false },

  // Smithing
  { name: 'Yhden barin esineet (paja)', skill: 'smithing', reqs: { smithing: 1 }, afk: '1:07', f2p: true },
  { name: 'Cannonballit', skill: 'smithing', reqs: { smithing: 35 }, afk: '1:02', notes: 'Double ammo mould', f2p: false },

  // Fletching
  { name: 'Bolt tipit', skill: 'fletching', reqs: { fletching: 11 }, afk: '1:21', f2p: false },
  { name: 'Battlestaffit', skill: 'fletching', reqs: { fletching: 40 }, afk: '0:49', f2p: false },
  { name: 'Redwood Shieldit', skill: 'fletching', reqs: { fletching: 92 }, afk: '0:47', f2p: false },
  { name: 'Jousien vuoleminen', skill: 'fletching', reqs: { fletching: 5 }, afk: '0:32', f2p: false },

  // Firemaking
  { name: "Forester's Campfire", skill: 'firemaking', reqs: { firemaking: 1 }, afk: '2:31', f2p: true },

  // Fishing
  { name: 'Stranglewood-kalastus', skill: 'fishing', reqs: { fishing: 63 }, afk: '30:00', f2p: false },
  { name: 'Karambwanji', skill: 'fishing', reqs: { fishing: 5 }, afk: '20:00', f2p: false },
  { name: 'Dark Crab', skill: 'fishing', reqs: { fishing: 85 }, afk: '7:32', notes: 'Fish barrel + elite wildy diary — wildissä!', f2p: false },
  { name: 'Civitas illa Fortis -kalastus', skill: 'fishing', reqs: { fishing: 1 }, afk: '7:00', f2p: false },
  { name: 'Cave Eel', skill: 'fishing', reqs: { fishing: 38 }, afk: '4:58', f2p: false },
  { name: 'Karambwan', skill: 'fishing', reqs: { fishing: 65 }, afk: '4:13', f2p: false },
  { name: 'Anglerfish', skill: 'fishing', reqs: { fishing: 82 }, afk: '2:37', f2p: false },
  { name: 'Tavallinen kalastuspaikka', skill: 'fishing', reqs: { fishing: 1 }, afk: '1:57', f2p: true },
  { name: 'Barbarian Fishing (Quidamortem)', skill: 'fishing', reqs: { fishing: 48 }, afk: '1:57', f2p: false },
  { name: 'Sacred Eel', skill: 'fishing', reqs: { fishing: 87 }, afk: '1:00', notes: "Rada's blessing 4", f2p: false },
  { name: 'Infernal Eel', skill: 'fishing', reqs: { fishing: 80 }, afk: '1:00', notes: "Rada's blessing 4", f2p: false },

  // Agility
  { name: 'POH Agility', skill: 'agility', reqs: { agility: 1, construction: 88 }, afk: '10:00', f2p: false },
  { name: 'Vampyrium Rocks', skill: 'agility', reqs: { agility: 61 }, afk: '7:30', notes: 'Liian aikainen klikki resetoi cooldownin', f2p: false },
  { name: 'Pedals', skill: 'agility', reqs: { agility: 30 }, afk: '5:19', f2p: false },

  // Herblore
  { name: 'Tarin teko (herb tar)', skill: 'herblore', reqs: { herblore: 11 }, afk: '0:47', f2p: false },
  { name: 'Yrttien putsaus (auto)', skill: 'herblore', reqs: { herblore: 3 }, afk: '0:34', f2p: false },
  { name: 'Stackable secondary -potionit', skill: 'herblore', reqs: { herblore: 77 }, afk: '0:31', f2p: false },

  // Runecraft
  { name: 'Blood Runes (Zeah)', skill: 'runecraft', reqs: { runecraft: 77 }, afk: '0:55', f2p: false },
  { name: 'Soul Runes (Zeah)', skill: 'runecraft', reqs: { runecraft: 90 }, afk: '0:55', f2p: false },
  { name: 'ZMI-altari', skill: 'runecraft', reqs: { runecraft: 1 }, afk: '0:25', f2p: false },

  // Magic
  { name: 'Korujen lumous (auto-cast)', skill: 'magic', reqs: { magic: 7 }, afk: '1:53', f2p: true },
  { name: 'Plank Make', skill: 'magic', reqs: { magic: 86 }, afk: '1:30', f2p: false },
  { name: 'String Jewellery', skill: 'magic', reqs: { magic: 80 }, afk: '0:49', f2p: false },
  { name: 'Splashing', skill: 'magic', reqs: { magic: 1 }, afk: '20:00', f2p: true },

  // Crafting
  { name: 'Saven poltto', skill: 'crafting', reqs: { crafting: 1 }, afk: '1:58', f2p: true },
  { name: 'Lasinpuhallus', skill: 'crafting', reqs: { crafting: 1 }, afk: '0:50', f2p: false },
  { name: 'Kehrääminen (spinning)', skill: 'crafting', reqs: { crafting: 1 }, afk: '0:50', f2p: true },

  // Strength
  { name: 'Blast Furnace -pumppu', skill: 'strength', reqs: { strength: 30 }, afk: '30:00', f2p: false },

  // Sailing
  { name: 'Crewmate-salvaging', skill: 'sailing', reqs: { sailing: 40 }, afk: '30:00', f2p: false },
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
  { name: 'Maniacal Monkey -metsästys', skill: 'hunter', reqs: { hunter: 60 }, afk: '0:25', f2p: false },

  // Prayer
  { name: 'Gilded Altar (auto-offer)', skill: 'prayer', reqs: { prayer: 1 }, afk: '1:02', notes: 'Luut alttarille POH:ssa', f2p: false },

  // Combat
  { name: 'Gemstone Crabit', skill: 'hitpoints', reqs: { hitpoints: 10 }, afk: '10:00', notes: 'Children of the Sun -questi', f2p: false },
  { name: 'Sand Crabit', skill: 'hitpoints', reqs: { hitpoints: 10 }, afk: '10:00', f2p: false },
  { name: 'Ammonite Crabit', skill: 'hitpoints', reqs: { hitpoints: 10 }, afk: '10:00', notes: 'Bone Voyage -questi', f2p: false },
  { name: 'NMZ Melee', skill: 'strength', reqs: { attack: 60, strength: 60 }, afk: '20:00', notes: 'Nightmare Zone -questit', f2p: false },
  { name: 'NMZ Ranged', skill: 'ranged', reqs: { ranged: 70 }, afk: '20:00', notes: 'Nightmare Zone -questit', f2p: false },
  { name: 'Vyrewatch Sentinelit', skill: 'slayer', reqs: { attack: 70, strength: 70, defence: 70 }, afk: '17:00', notes: 'Sins of the Father -questi', f2p: false },
  { name: 'Maniacal Monkeys (Ice Barrage)', skill: 'magic', reqs: { magic: 94 }, afk: '10:00', notes: 'Monkey Madness II', f2p: false },
  { name: 'Maniacal Monkeys (chinning)', skill: 'ranged', reqs: { ranged: 80 }, afk: '10:00', notes: 'MM II + red chinchompat', f2p: false },
];
