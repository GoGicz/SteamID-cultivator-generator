"""Static game content: realms, talents, paths, personalities, reputation ranks, names, titles,
elements, treasures and pavilion goods, signature moves."""


SECT_POINTS_PER_MISSION = 5   # 1 unlocked achievement = 1 sect mission = 5 sect points

# ---------------------------------------------------------------------------
# Reputation: every Steam badge is worth REP_PER_BADGE reputation points, and the
# personalities below add more. Ranks are (minimum points, name), lowest to highest.
# The steps between ranks grow gradually: the first ranks come quickly but still take some
# work, the last ones need a great deal. A duel won against a stronger realm pays 25 points
# per realm of difference (see REP_GAIN_PER_REALM), so with one realm of difference it takes
# about 2, 3, 4, 6, 9, 12, 16, 22 and 32 such wins to climb from each rank to the next; no
# single ordinary duel can skip a rank.
# ---------------------------------------------------------------------------
REP_PER_BADGE = 2
REPUTATION_RANKS = [
    (0,    "Unknown Nobody"),
    (40,   "Barely Noticed"),
    (100,  "Familiar Face"),
    (200,  "Sect Favorite"),
    (350,  "Regional Celebrity"),
    (560,  "Famed Across the Provinces"),
    (850,  "Renowned Master"),
    (1250, "Continental Legend"),
    (1800, "Name Spoken by the Heavens"),
    (2600, "Universal Legend"),
]

# ---------------------------------------------------------------------------
# Personalities. Anyone can hold several. Each one has:
#   test        : who gets it, from (info, friend_count)
#   power       : added to the power score
#   death       : added to the death chance (0.008 = +0.8 percentage points)
#   rep         : reputation points it can give
#   rep_chance  : chance of actually getting them (1.0 = always, 0.5 = a coin flip);
#                 the roll is fixed by the SteamID, so a profile never changes its mind
#   roll_group  : (optional) personalities with the same group share one dice roll;
#                 Brave and Fearless do, so Fearless is never worse off than Brave
#   trait       : how the backstory describes it (a past-tense phrase)
# ---------------------------------------------------------------------------
PERSONALITIES = [
    {"name": "Social", "rule": "more than 40 Steam friends",
     "test": lambda info, friends: friends > 40,
     "power": 0, "death": 0.0, "rep": 30, "rep_chance": 1.0,
     "trait": "made friends wherever they went"},
    {"name": "Brave", "rule": "51 to 100 badges",
     "test": lambda info, friends: 50 < info["badges"] <= 100,
     "power": 0, "death": 0.0, "rep": 25, "rep_chance": 0.30, "roll_group": "courage",
     "trait": "never flinched when danger came knocking"},
    {"name": "Fearless", "rule": "more than 100 badges",
     "test": lambda info, friends: info["badges"] > 100,
     "power": 50, "death": 0.008, "rep": 60, "rep_chance": 0.50, "roll_group": "courage",
     "trait": "laughed in the face of heavenly tribulations"},
    {"name": "Diligent", "rule": "1,000 or more achievements",
     "test": lambda info, friends: info["achievements"] >= 1000,
     "power": 0, "death": 0.0, "rep": 20, "rep_chance": 1.0,
     "trait": "trained until the candles burned out"},
    {"name": "Collector", "rule": "300 or more paid games",
     "test": lambda info, friends: info["game_count"] >= 300,
     "power": 0, "death": 0.0, "rep": 15, "rep_chance": 1.0,
     "trait": "could never walk past a treasure stall without stopping"},
]
NO_PERSONALITY_TRAIT = "kept a quiet temperament that set off no gossip"

# ---------------------------------------------------------------------------
# Paths. Every cultivator walks one of two, picked by luck from the SteamID (never from
# Steam stats). RIGHTEOUS_CHANCE is the chance of the Righteous Path; the Demonic Path
# gets the rest, so 0.70 means 70% / 30%.
#   power : added to the power score        rep : added to the reputation points
# ---------------------------------------------------------------------------
RIGHTEOUS_CHANCE = 0.70
PATHS = [
    {"name": "Righteous", "power": 0, "rep": 5},
    {"name": "Demonic", "power": 20, "rep": 0},
]
                              # (set to 0 to trust the cache until playtime changes)

# ---------------------------------------------------------------------------
# Talents, weakest to strongest. Rolled by pure luck (never by Steam stats).
#   weight : relative chance of rolling it (Regular Martial Body is the most common)
#   power  : added to the power score, so it can push you into a higher realm
#   death  : chance of dying in battle (8% for a regular body, 15% for a poor one)
# ---------------------------------------------------------------------------
TALENTS = [
    {"name": "Poor Martial Body", "weight": 20, "power": -30, "death": 0.15,
     "blurb": "blocked meridians that make every step of cultivation twice as hard"},
    {"name": "Regular Martial Body", "weight": 45, "power": 0, "death": 0.08,
     "blurb": "an unremarkable body, just like ten thousand other disciples"},
    {"name": "Gifted Spirit Root", "weight": 20, "power": 75, "death": 0.06,
     "blurb": "spirit roots that glow faintly whenever Qi touches them"},
    {"name": "Heaven-Favored Genius", "weight": 9, "power": 200, "death": 0.04,
     "blurb": "a genius whose Qi circulates as if guided by the heavens themselves"},
    {"name": "Divine Physique", "weight": 4, "power": 450, "death": 0.025,
     "blurb": "a rare divine physique that made the sect elders drop their teacups"},
    {"name": "Primordial Chaos Body", "weight": 1.5, "power": 900, "death": 0.01,
     "blurb": "a Chaos Body that appears only once in a hundred thousand years"},
    {"name": "Reincarnation of the Dao", "weight": 0.5, "power": 1600, "death": 0.0025,
     "blurb": "the Dao itself reborn in mortal flesh, and the heavens trembled"},
]

TALENT_BY_NAME = {t["name"]: t for t in TALENTS}

# ---------------------------------------------------------------------------
# Cultivation realms: (minimum power score, name, flavor)
# ---------------------------------------------------------------------------
REALMS = [
    (0,    "Mortal Body Tempering",       "barely able to sense Qi"),
    (50,   "Qi Condensation",             "a fledgling who has just opened the first meridians"),
    (150,  "Foundation Establishment",    "a solid Dao foundation is laid"),
    (300,  "Core Formation",              "a golden core spins in the dantian"),
    (500,  "Nascent Soul",                "a nascent soul now roams beyond the body"),
    (800,  "Soul Transformation",         "heaven and earth answer the soul's call"),
    (1200, "Void Refinement",             "stepping through the void is as easy as breathing"),
    (1800, "Mahayana",                    "an overlord whose name shakes the nine provinces"),
    (2600, "Tribulation Transcendence",   "heavenly lightning bows to this existence"),
    (3500, "Immortal Ascension",          "a true immortal who looks down on mortals and sects alike"),
]

SURNAMES = ["Li", "Wang", "Zhang", "Liu", "Chen", "Yang", "Huang", "Zhao", "Wu", "Zhou",
            "Xu", "Sun", "Ma", "Zhu", "Hu", "Guo", "Lin", "He", "Gao", "Luo",
            "Ouyang", "Murong", "Shangguan", "Duanmu", "Xiahou"]
GIVEN = ["Tian", "Feng", "Yun", "Hao", "Ming", "Xuan", "Yu", "Jian", "Long", "Chen",
         "Wei", "Lei", "Qing", "Han", "Yan", "Zhi", "Ruo", "Shuo", "Jun", "Xiao",
         "Bai", "Mo", "Ling", "Heng", "Wuji"]
# Female cultivators draw their given names from their own list. Male ones keep the list above,
# so every male cultivator keeps the name they always had.
FEMALE_GIVEN = ["Yue", "Lian", "Xue", "Mei", "Hua", "Rou", "Shan", "Ning", "Xia", "Lan",
                "Fang", "Zhu", "Ying", "Ru", "Shu", "Wan", "Jing", "Bing", "Meng", "Xiu",
                "Zi", "Qiu", "Die", "Fei", "Luo"]
# Titles that have a female form (everything else is the same for both).
FEMALE_TITLES = {"Sect Master": "Sect Mistress", "Array Master": "Array Mistress",
                 "Talisman Master": "Talisman Mistress", "Dao Lord": "Dao Lady",
                 "Patriarch": "Matriarch", "Immortal Emperor": "Immortal Empress",
                 "Mountain-Splitting Swordsman": "Mountain-Splitting Swordswoman",
                 "Lord of Ten Thousand Peaks": "Lady of Ten Thousand Peaks",
                 "Overlord of the Nine Provinces": "Empress of the Nine Provinces",
                 "Lord of the Endless Sea": "Lady of the Endless Sea"}
SECT_ADJ = ["Azure", "Crimson", "Nine-Heaven", "Void", "Thousand-Peak", "Jade", "Black Tortoise",
            "Eternal", "Ninefold", "Starfall", "Hidden Moon", "Celestial", "Boundless"]
SECT_NOUN = ["Cloud Sect", "Sword Pavilion", "Lotus Temple", "Dao Palace", "Thunder Hall",
             "Mountain Gate", "Dragon Valley", "Phoenix Court", "Spirit Academy", "Heavenly Sect"]
TITLES_LOW = ["Outer Disciple", "Wandering Rogue", "Herb Gatherer", "Gate Sweeper", "Spirit Stone Beggar"]
TITLES_MID = ["Inner Disciple", "Elder", "Alchemist", "Sword Cultivator", "Array Master"]
TITLES_HIGH = ["Sect Master", "Ancestor", "Supreme Elder", "Sovereign", "Dao Lord"]
# More titles. The first lists above are what the main random generator always drew from;
# the pick from the complete lists (TITLES_*_ALL) uses its own generator seeded by the
# SteamID, so every other trait of a cultivator stays exactly as it was.
TITLES_LOW_MORE = ["Errand Runner", "Stable Keeper", "Spirit Beast Feeder", "Scripture Copier",
                   "Lantern Lighter", "Kitchen Hand of the Sect", "Mortal Turned Cultivator",
                   "Alley Pill Peddler", "Rain-Soaked Wanderer", "Tea House Apprentice",
                   "Pagoda Guard", "Broken Sword Collector", "Failed Alchemy Assistant",
                   "Mountain Path Sweeper"]
TITLES_MID_MORE = ["Core Disciple", "Formation Instructor", "Pill Refiner", "Talisman Master",
                   "Arena Champion", "Law Enforcement Elder", "Beast Tamer", "Blade Saint",
                   "Sect Treasurer", "Thunder Tribulation Survivor", "Spirit Vein Warden",
                   "Mountain-Splitting Swordsman", "Phoenix Flame Refiner", "Sect Envoy",
                   "Ghost Market Broker"]
TITLES_HIGH_MORE = ["Heavenly Sovereign", "Patriarch", "Grand Elder", "Immortal Emperor",
                    "Void Monarch", "Lord of Ten Thousand Peaks", "Great Dao Ancestor",
                    "Heaven-Piercing Sage", "Overlord of the Nine Provinces",
                    "Star-River Ancestor", "Keeper of the Heavenly Gate", "Lord of the Endless Sea",
                    "Eternal Sword Immortal", "Throne of the Ten Thousand Dao"]
TITLES_ALL = [TITLES_LOW + TITLES_LOW_MORE, TITLES_MID + TITLES_MID_MORE,
              TITLES_HIGH + TITLES_HIGH_MORE]
ELEMENTS = ["Fire", "Water", "Wood", "Metal", "Earth", "Lightning", "Wind", "Ice", "Shadow"]
MOVE_NOUN = ["Palm", "Fist", "Sword Art", "Finger", "Heavenly Scripture", "Divine Step",
             "Annihilation Technique", "Soul Seal", "Dao Formation", "Pill Formula"]
MOVE_ADJ = ["Eternal", "Nine-Layered", "Heaven-Defying", "Void-Shattering", "Primordial",
            "Boundless", "Blood-Soaked", "Dragon-Slaying", "Ascending", "Forbidden"]
TREASURES_LOW = ["a cracked spirit stone", "a rusty iron sword", "a half-torn cultivation manual",
                 "a grandfather's mysterious ring"]
TREASURES_MID = ["a flying sword of the sixth rank", "a purple-gold gourd", "a tripod furnace",
                 "a jade slip with an ancient inheritance"]
TREASURES_HIGH = ["a Heaven-Grade artifact", "a fragment of the Primordial Chaos Bell",
                  "a stolen divine artifact", "a Dao-seeking lantern older than the heavens"]
FALLBACK_TREASURE = "a plain wooden token"
TREASURES_LOW_MORE = ["a chipped jade bracelet", "a bamboo flute that hums by itself",
                      "a bag of slightly damp spirit grass", "a rooster-shaped copper talisman",
                      "a nameless beggar's bowl", "a bent ironwood hairpin",
                      "a cracked turtle-shell divination tool", "a lucky copper coin with a hole",
                      "a wooden sword carved by a childhood friend", "a map to a sect long forgotten",
                      "a spirit-grass pouch that never fully empties"]
TREASURES_MID_MORE = ["a thousand-year ginseng root", "a mirror that shows a person's past life",
                      "a seven-star formation flag", "a blood-jade prayer bead",
                      "a bronze mask of the Nine Hells", "a cauldron that never cools",
                      "a lantern that burns the soul-light of the dead", "a jade token of a fallen sect",
                      "a pair of boots that walk a thousand li a day", "a bottle of ten-year thunder dew",
                      "a puppet carved from lightning-struck wood"]
TREASURES_HIGH_MORE = ["the Nine-Dragon Imperial Seal", "a pearl from the Eastern Sea Dragon King",
                       "a scroll written by the first Dao Ancestor",
                       "the last drop of the Primordial Spring", "a banner that commands ten "
                       "thousand ghosts", "a sliver of the Heaven-Splitting Sword",
                       "a seed of the World Tree", "the crown of a forgotten celestial emperor",
                       "a sealed demon-king's eye", "a star map that rewrites itself",
                       "the bell that tolled at the birth of the first Dao"]
ALL_TREASURES = [TREASURES_LOW + TREASURES_LOW_MORE, TREASURES_MID + TREASURES_MID_MORE,
                 TREASURES_HIGH + TREASURES_HIGH_MORE]


# ---------------------------------------------------------------------------
# The sect's Martial Pavilion ("pavilion" command). The last cultivator you looked up can
# spend sect points here. Pills, weapons and talismans are kept in the cultivator's JSON
# file (key "pavilion"); treasures go into the treasure inventory, so they can be stolen.
# A Spatial Escape Talisman stops a Demonic winner from stealing the owner's treasure. It is
# used up when it does (TALISMAN_SINGLE_USE; set it to False to keep the talisman).
# ---------------------------------------------------------------------------
TALISMAN_ID = "spatial_escape_talisman"
TALISMAN_SINGLE_USE = True
PAVILION_ITEMS = [
    {"id": "qi_gathering_pill", "name": "Qi Gathering Pill", "kind": "Pill", "price": 100,
     "blurb": "Gathers a little Qi. Nobody has ever complained about it."},
    {"id": "meridian_cleansing_pill", "name": "Meridian Cleansing Pill", "kind": "Pill",
     "price": 250, "blurb": "Clears blocked meridians. Tastes like swamp water."},
    {"id": "foundation_pill", "name": "Foundation Establishment Pill", "kind": "Pill",
     "price": 600, "blurb": "Steadies the Dao foundation before a breakthrough."},
    {"id": "soul_restoring_pill", "name": "Nine-Turn Soul Restoring Pill", "kind": "Pill",
     "price": 1200, "blurb": "Calls a wounded soul back from the edge."},
    {"id": "breakthrough_pill", "name": "Heaven-Defying Breakthrough Pill", "kind": "Pill",
     "price": 5000, "blurb": "Alchemists whisper it was stolen from the heavens. Adds +30% to "
                             "one breakthrough attempt."},
    {"id": "iron_spirit_sword", "name": "Iron Spirit Sword", "kind": "Weapon", "price": 200,
     "blurb": "A reliable blade for disciples who still count their spirit stones."},
    {"id": "azure_frost_spear", "name": "Azure Frost Spear", "kind": "Weapon", "price": 500,
     "blurb": "Leaves a trail of frost, and sometimes a cold."},
    {"id": "thousand_li_sword", "name": "Thousand-Li Flying Sword", "kind": "Weapon",
     "price": 1200, "blurb": "Crosses a thousand li in the time it takes to sneeze."},
    {"id": "dragon_halberd", "name": "Dragon-Slaying Halberd", "kind": "Weapon", "price": 2500,
     "blurb": "No dragon has been slain with it yet. The sect is hopeful."},
    {"id": "thunder_blade", "name": "Nine-Heavens Thunder Blade", "kind": "Weapon",
     "price": 5000, "blurb": "Calls down lightning on command, and occasionally by itself."},
    {"id": "storage_ring", "name": "a sect-forged storage ring", "kind": "Treasure", "rank": 0,
     "price": 250, "blurb": "A treasure. It can be stolen."},
    {"id": "jade_pendant", "name": "a spirit-nourishing jade pendant", "kind": "Treasure",
     "rank": 1, "price": 700, "blurb": "A treasure. It can be stolen."},
    {"id": "alchemy_cauldron", "name": "a nine-tier alchemy cauldron", "kind": "Treasure",
     "rank": 1, "price": 1500, "blurb": "A treasure. It can be stolen."},
    {"id": "lotus_throne", "name": "a Heaven-Grade lotus throne", "kind": "Treasure", "rank": 2,
     "price": 4000, "blurb": "A treasure. It can be stolen, unless you own a talisman."},
    {"id": TALISMAN_ID, "name": "Spatial Escape Talisman", "kind": "Talisman", "price": 2500,
     "blurb": "Single use: when a Demonic winner tries to steal your treasure, space folds "
              "and the treasure slips out of reach."},
]
PAVILION_BY_ID = {item["id"]: item for item in PAVILION_ITEMS}
PAVILION_TREASURE_RANKS = {item["name"]: item["rank"] for item in PAVILION_ITEMS
                           if item["kind"] == "Treasure"}


# ---------------------------------------------------------------------------
# Battle arsenal. Besides the unique signature technique (named after the most played game),
# every cultivator knows four more moves, picked from these tables by the SteamID: two
# attacks of their own element, one attack of their path, and one defensive or movement
# technique. The names are complete on their own and the duel story only ever uses them as
# "an attack" or "a defense", so any combination reads sensibly.
# ---------------------------------------------------------------------------
ELEMENT_MOVES = {
    "Fire": ["Crimson Lotus Flame Wave", "Phoenix Feather Barrage", "Scorching Sun Palm",
             "Ember Rain Sword Dance", "Inferno Dragon Roar", "Cinder Storm Fist"],
    "Water": ["Tidal Dragon Surge", "Moonlit Pool Reflection Strike", "Nine-Bend River Slash",
              "Rainfall Needle Barrage", "Abyssal Whirlpool Palm", "Thousand-Wave Fist"],
    "Wood": ["Ten Thousand Vine Bind", "Ancient Tree Crushing Palm", "Thorn Rain Barrage",
             "Verdant Sprout Sword", "Bamboo Forest Blade Dance", "Spirit Root Eruption"],
    "Metal": ["Heavenly Blade Rain", "Gold-Splitting Sword Light", "Iron Mountain Crushing Fist",
              "Ten Thousand Swords Return", "Steel Dragon Claw", "Piercing Needle Barrage"],
    "Earth": ["Mountain-Shaking Palm", "Yellow Earth Crushing Fist", "Boulder Rain Barrage",
              "Earth Dragon Rising Strike", "Ten-Thousand-Li Rockfall", "Quake Heart Stomp"],
    "Lightning": ["Nine Heavens Thunder Palm", "Purple Lightning Sword", "Thunder Tribulation Strike",
                  "Storm-Splitting Fist", "Chain Lightning Dance", "Heaven's Wrath Bolt"],
    "Wind": ["Hurricane Blade Dance", "Cloud-Cutting Palm", "Gale Feather Barrage",
             "Nine-Turn Whirlwind Kick", "Sky-Rending Wind Claw", "Tempest Sword Wave"],
    "Ice": ["Frost Lotus Spear Barrage", "Ice Phoenix Piercing Strike", "Glacier Crushing Palm",
            "Frozen Heart Sword", "Snowstorm Blade Dance", "Hundred-Li Frost Wave"],
    "Shadow": ["Shadow Clone Slash", "Nightfall Soul Claw", "Void Shade Palm",
               "Eclipse Dagger Rain", "Phantom Dance Strike", "Black Mist Devouring Fist"],
}
PATH_MOVES = {
    "Righteous": ["Heaven-Upholding Sword Light", "Righteous Qi Palm", "Orthodox Sword Formation",
                  "Vast Justice Strike", "Dao-Guarding Seal Fist"],
    "Demonic": ["Blood Moon Soul Reaping", "Demonic Qi Devouring Palm", "Ten-Thousand-Corpse Hand",
                "Bone-Chilling Demon Claw", "Soul-Shattering Devil Cry"],
}
DEFENSE_MOVES = ["Golden Bell Shield", "Cloud-Treading Shadowless Step", "Heavenly Turtle Barrier",
                 "Nine Palaces Void Step", "Jade Mirror Guard", "Spirit Veil Evasion",
                 "Diamond Body Technique", "Flowing Cloud Dodge"]
ELEMENT_BEATS = {
    "Fire":      ["Wood", "Metal"],         # fire burns wood and melts metal
    "Water":     ["Fire", "Metal"],         # water douses fire and rusts metal
    "Wood":      ["Earth", "Wind"],         # roots split earth, trees break the wind
    "Metal":     ["Wood", "Ice"],           # the axe fells wood, metal shatters ice
    "Earth":     ["Lightning", "Shadow"],   # earth grounds lightning and buries shadow
    "Lightning": ["Water", "Shadow"],       # lightning rides water and lights the dark
    "Wind":      ["Earth", "Lightning"],    # wind erodes earth and scatters the charge
    "Ice":       ["Water", "Wind"],         # ice freezes water and stills the air
    "Shadow":    ["Fire", "Ice"],           # darkness swallows flame and chills ice
}
