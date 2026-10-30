#!/usr/bin/env python3
"""
Steam Cultivator Generator
--------------------------
Enter a Steam profile and get a cultivation-novel style character whose
power depends on your Steam level, number of paid games and hours in your top game.
It also picks one of your Steam friends at random and tells a short story about
the two of your cultivators meeting.
Every cultivator rolls a random talent (from Poor Martial Body up to Reincarnation
of the Dao). Talent ignores your Steam stats completely, adds power, and sets the
chance of dying in battle (8% for a regular body, 15% for a poor one, and lower the
better the talent). Every cultivator also has a birth year. Talent and fate are
fixed by your SteamID, so the same profile always gets the same result. Rarely, the
killer is one of your own Steam friends.
Every unlocked Steam achievement counts as one completed sect mission, and every
mission pays 5 sect points. Steam can only be asked about achievements one game at
a time, so the first lookup of a big library takes a little while. The results are
saved in a "cache" folder next to this file, so later runs only ask Steam about games
whose playtime changed (or new ones) and report how many achievements you gained since
your last visit. Type "refresh <profile>" (or run with --refresh) to re-check everything.
Every cultivator walks the Righteous Path (70% by default, +5 reputation) or the Demonic
Path (+20 power), by luck from the SteamID. Type "mocb" (or "mocb <profile1> <profile2>")
to make two cultivators duel: the program works out who is most likely to win and tells a
short story of the battle. Affinity matters in duels: an element that is strong against
the other's gets +3% win chance (every element beats two and loses to two), and when one
fighter's power towers over the other's, the story shows the stronger one's arrogance.
The age of your Steam account sets the age of your cultivator: a brand-new account gives
a youth, and an account of 20 years or more a cultivator close to the end of their
lifespan (a doomed cultivator dies at that age). Every command is written to a log file
in the "Logs" folder next to this file (one file per day), with what was run and how
many Steam API calls it used. The API key is never written to the log.
Your Steam badges build your reputation, from "Unknown Nobody" up to "Universal
Legend". Personalities, earned from your friends, badges, achievements and games,
add reputation (some only by chance) and a few also change power and death risk,
for example "Fearless" (more than 100 badges): +50 power but +0.8% death risk.

Setup:
    pip install requests
    Get a free API key: https://steamcommunity.com/dev/apikey
    Set it as an environment variable (recommended):
        Windows (cmd):   set STEAM_API_KEY=yourkey
        Linux / macOS:   export STEAM_API_KEY=yourkey
    ...or just paste it when the program asks.

Run:
    python steam_cultivator.py

Your Steam profile's "Game details" must be set to Public,
otherwise Steam will not give out the data.
The friend story needs a public "Friends List" too; if it is private (or you
have no friends) the story is simply skipped.
"""

import datetime
import json
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

API = "https://api.steampowered.com"
TIMEOUT = 15

BETRAYAL_CHANCE = 0.05   # of those who die, chance the killer is one of their friends
SECT_POINTS_PER_MISSION = 5   # 1 unlocked achievement = 1 sect mission = 5 sect points

# ---------------------------------------------------------------------------
# Reputation: every Steam badge is worth REP_PER_BADGE reputation points, and the
# personalities below add more. Ranks are (minimum points, name), lowest to highest.
# ---------------------------------------------------------------------------
REP_PER_BADGE = 2
REPUTATION_RANKS = [
    (0,    "Unknown Nobody"),
    (10,   "Barely Noticed"),
    (30,   "Familiar Face"),
    (70,   "Sect Favorite"),
    (130,  "Regional Celebrity"),
    (220,  "Famed Across the Provinces"),
    (350,  "Renowned Master"),
    (520,  "Continental Legend"),
    (750,  "Name Spoken by the Heavens"),
    (1000, "Universal Legend"),
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

# ---------------------------------------------------------------------------
# Duels ("mocb"). Win chance = power^BATTLE_EXPONENT, compared with the other fighter's
# (BATTLE_SCORE_FLOOR keeps two very weak fighters from dividing by nothing). A higher
# exponent makes the stronger fighter win more reliably.
# BATTLE_UPSETS = True: the dice decide the real winner using those chances (the
# favorite usually wins, sometimes not). False: the favorite always wins.
# The dice are fixed by the two SteamIDs, so the same pair always gives the same winner.
# ---------------------------------------------------------------------------
BATTLE_EXPONENT = 2.0
BATTLE_SCORE_FLOOR = 25
BATTLE_UPSETS = True
ACHIEVEMENT_WORKERS = 8       # how many games are asked about at the same time

# Achievement cache (see "Achievements and the achievement cache" below)
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Logs")

# A Steam account of ACCOUNT_YEARS_FOR_MAX_AGE years or more gives the oldest possible
# cultivator; a brand-new account gives the youngest. In between it scales evenly.
ACCOUNT_YEARS_FOR_MAX_AGE = 20
SECONDS_PER_YEAR = 365.25 * 24 * 3600
CACHE_VERSION = 1
RECHECK_AFTER_DAYS = 30       # re-check a saved game after this long even if nothing changed
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
SECT_ADJ = ["Azure", "Crimson", "Nine-Heaven", "Void", "Thousand-Peak", "Jade", "Black Tortoise",
            "Eternal", "Ninefold", "Starfall", "Hidden Moon", "Celestial", "Boundless"]
SECT_NOUN = ["Cloud Sect", "Sword Pavilion", "Lotus Temple", "Dao Palace", "Thunder Hall",
             "Mountain Gate", "Dragon Valley", "Phoenix Court", "Spirit Academy", "Heavenly Sect"]
TITLES_LOW = ["Outer Disciple", "Wandering Rogue", "Herb Gatherer", "Gate Sweeper", "Spirit Stone Beggar"]
TITLES_MID = ["Inner Disciple", "Elder", "Alchemist", "Sword Cultivator", "Array Master"]
TITLES_HIGH = ["Sect Master", "Ancestor", "Supreme Elder", "Sovereign", "Dao Lord"]
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

# ---------------------------------------------------------------------------
# Friend stories. Placeholders: {me} {friend} {friend_steam} {game} {sect}
# {realm} {treasure}. Add as many templates as you like.
# ---------------------------------------------------------------------------
STORIES_COMMON = [
    "While wandering the mountains, {me} met a fellow cultivator named {friend} "
    "(known in the mortal realm as '{friend_steam}'). They shared a pot of spirit tea and "
    "swore to become sworn siblings on the spot. By the next morning both had forgotten the oath.",

    "{me} and {friend} found a secret realm hidden behind a waterfall. Inside waited an ancient "
    "inheritance, and after three days of arguing about whose {game} technique was superior, "
    "they opened the final chamber. It contained one note: 'Go touch grass.' Both were "
    "enlightened at once.",

    "A rival sect challenged {me} to a duel, and {friend} showed up uninvited with a bag of "
    "snacks to watch from the sidelines. The whole mountain heard the cheering. {me} won, "
    "mostly out of embarrassment.",

    "{friend} once asked {me} for a pill recipe. {me} confidently provided one, and the furnace "
    "explosion was seen from three provinces away. The {sect} still sends {friend} the bill.",

    "{me} and {friend} bet a month of spirit stones on who could meditate longer. Three days "
    "in, both were still sitting perfectly still, glaring at each other. A passing sect elder "
    "declared it a draw and quietly took the whole pot.",

    "{friend} dragged {me} into a market haggling contest over {treasure}. After an hour of "
    "dramatic gasps and walking away twice, the merchant paid {me} to leave. Nobody can "
    "explain how that works.",

    "In a thunderstorm, {me} and {friend} sheltered inside a cave that turned out to be the "
    "den of a sleeping dragon. They tiptoed out together, whispering about {game}, and "
    "agreed never to mention the dragon's snoring to anyone.",

    "{friend} invited {me} to a banquet 'with only a few guests'. It was the entire "
    "{sect}, two rival sects, and a goose of unclear origin. {me} still insists the goose "
    "started the fight.",

    "On a lonely road, {me} and {friend} found a map to a legendary treasure. They followed "
    "it for a week, argued at every crossroads, and finally dug up a chest holding a single "
    "spirit stone and a note: 'Friendship was the real treasure.' They split the stone anyway.",

    "{me} taught {friend} the secret of a {game}-inspired sword form. {friend} practiced it "
    "so loudly that the neighbors filed a complaint with the {sect}. The form is now banned "
    "after sunset.",

    "{friend} once swore to {me} that a certain mushroom was perfectly safe. For three days "
    "both of them saw the future, though sadly only the part where they ate more mushrooms. "
    "They have not looked at a mushroom since.",

    "Lost in a mountain fog, {me} and {friend} walked in circles for a whole day before "
    "realizing they had been following each other. They laughed until the fog lifted, and the "
    "path home turned out to be right behind them.",
]

STORIES_WEAK = [
    "{me}, whose cultivation had only reached {realm}, was cornered by a demonic beast until "
    "{friend} burst in wielding nothing but a cooking pot. The beast fled in confusion. "
    "Neither of them speaks of it.",

    "Both {me} and {friend} were too poor to afford a single spirit stone, so they pooled their "
    "savings for one steamed bun and shared it under a tree, swearing that one day they would "
    "rule the heavens. The bun was delicious.",

    "Still only at {realm}, {me} could not make a flying sword rise higher than a stool. "
    "{friend} stood on the stool to cheer anyway, and the sword wobbled into the air for one "
    "glorious second before dropping them both into a pond.",

    "{me} and {friend} were hired as guards for a merchant caravan, and managed to lose the "
    "caravan, the merchant and one very patient donkey. They were paid in a sack of turnips, "
    "which they ate with great dignity.",
]

STORIES_STRONG = [
    "{me}, whose cultivation had reached {realm}, crossed nine provinces in a single breath "
    "just to rescue {friend} from a terrible blind date arranged by the {sect}.",

    "At the Great Ascension Banquet, every elder bowed to {me}. Only {friend} dared to say, "
    "'You still owe me a spirit stone.' {me} paid up immediately.",

    "When {me}, a master of {realm}, finally walked through the gates of the {sect}, ten "
    "thousand disciples knelt. {friend} waved from the back and shouted, 'Nice robe!' It was "
    "the only compliment {me} remembered.",

    "{me} once split a mountain in two to settle a dispute. {friend} asked politely whether "
    "{me} could put it back, since the mountain had a very good view. {me} spent the rest of "
    "the week gluing a mountain together.",

    "Heaven's tribulation lightning rained on {me} for nine hours. {friend} sat beside the "
    "crater with a parasol and a flask of tea, remarking that {me} looked 'a little "
    "crispy'. They shared the tea after.",
]

# ---------------------------------------------------------------------------
# Death scenes. Placeholders: {me} {sect} {technique} {treasure} {realm} {game}
# plus {rogue} / {bandits} (killer descriptions) or {friend} / {friend_steam}.
# ---------------------------------------------------------------------------
DEATH_ROGUE = [
    "{me} was ambushed at a mountain pass by {rogue} who coveted {treasure}. The duel lasted "
    "three breaths. {me}'s last words were reportedly: 'Tell the {sect} I was winning.'",

    "At the exact moment of a breakthrough attempt, {rogue} who had been stalking {me} for nine "
    "days finally struck. {technique} was unleashed too late, and the mountain fell silent.",

    "{me} accepted a duel with {rogue} and underestimated the stranger. The Heavens did not "
    "even bother to send thunder.",
]

DEATH_BANDITS = [
    "While travelling a lonely mountain road, {me} was surrounded by {bandits}. {technique} "
    "felled many of them, but in the end numbers won.",

    "{me} held the road against {bandits} so that a small village could escape. The villagers "
    "still burn incense at a roadside shrine, though nobody remembers the {sect}.",

    "{me} was poisoned with a cup of cheap wine at a roadside inn, then finished off by "
    "{bandits}. They sold {treasure} the next day for three copper coins.",
]

DEATH_FRIEND = [
    "{me} was betrayed by an old friend, {friend} (known in the mortal realm as '{friend_steam}'), "
    "who offered a cup of spirit tea laced with poison and then struck the final blow. "
    "{me}'s last words: 'I trusted you.'",

    "{friend} ('{friend_steam}'), a friend of many years, stabbed {me} in the back during a "
    "secret realm expedition and left with {treasure}. The {sect} still whispers about it.",

    "{me} and {friend} ('{friend_steam}') entered an ancient ruin together. Only {friend} came "
    "out, carrying {treasure} and a very unconvincing explanation.",
]

# ---------------------------------------------------------------------------
# Backstory building blocks. Every cultivator gets one template and one variant
# from each tier list, all picked from their SteamID, so it never changes.
#   Tier lists are (upper limit, [variants]); the first limit the value stays under wins.
#   meditation / treasury / missions are past-tense phrases ("spent 80 hours ...") and
#   work after any subject; dao is a complete sentence without the final period.
# ---------------------------------------------------------------------------
INF = float("inf")

MEDITATION_TIERS = [   # by hours in the most-played game: {hrs} {game}
    (5,    ["barely began to meditate in the cave of {game}",
            "dipped a toe into cultivation inside the cave of {game}, then wandered off for snacks"]),
    (200,  ["spent {hrs} hours in closed-door cultivation inside the cave of {game}",
            "sat cross-legged for {hrs} hours in the cave of {game}, slowly refining their Qi"]),
    (1500, ["endured {hrs} hours of seclusion in {game}, emerging with unshakable resolve",
            "vanished into {game} for {hrs} hours and returned with a sharper Dao heart"]),
    (INF,  ["sat in seclusion for an absurd {hrs} hours within {game}, long enough for mountains "
            "to turn to dust",
            "lost count of the seasons during {hrs} hours of seclusion in {game}, and the sect's "
            "cats grew old waiting"]),
]

TREASURY_TIERS = [     # by paid games owned: {gc}
    (1,    ["owned no treasures worth mentioning, a truly poor cultivator",
            "kept an empty storage ring and a head full of big dreams"]),
    (20,   ["kept {gc} humble treasures in their storage ring",
            "carried {gc} modest treasures wrapped in an old cloth"]),
    (200,  ["gathered {gc} treasures from across the realms",
            "collected {gc} treasures, each with its own story or curse"]),
    (INF,  ["amassed a vault of {gc} treasures that made whole sects weep with envy",
            "ruled over a treasure vault of {gc} items, guarded by three formations and one "
            "grumpy elder"]),
]

DAO_TIERS = [          # by Steam level: {lvl}
    (5,    ["A shallow Dao foundation had yet to be forged",
            "Their Dao foundation was only a tender sapling"]),
    (30,   ["Their Dao foundation stood at level {lvl}, steady but unspectacular",
            "At level {lvl}, their Dao foundation was solid if not dazzling"]),
    (100,  ["Their Dao foundation, tempered to level {lvl}, was respected throughout the region",
            "Tempered to level {lvl}, their Dao foundation earned quiet respect across the region"]),
    (INF,  ["Their Dao foundation reached level {lvl}, a height few have ever seen",
            "A Dao foundation at level {lvl} drew awe from rivals across nine provinces"]),
]

MISSION_TIERS = [      # by sect missions (= achievements): {n}
    (1,    ["never completed a single sect mission",
            "dodged every sect mission posted on the board"]),
    (2,    ["completed exactly one sect mission, and brought it up at every banquet",
            "finished one sect mission and took a three-year rest afterwards"]),
    (50,   ["completed {n} sect missions, just enough to avoid being thrown out",
            "took on {n} sect missions, mostly the ones nobody else wanted"]),
    (300,  ["completed {n} sect missions without complaint",
            "answered the mission board {n} times"]),
    (1000, ["completed {n} sect missions, and the mission hall elders learned their face by heart",
            "cleared {n} sect missions and earned a reserved seat at the mission hall"]),
    (INF,  ["completed an astonishing {n} sect missions, and the mission hall clerks ran out of ink",
            "cleared {n} sect missions, a record the {sect} carved onto a stone tablet"]),
]

REPUTATION_TIERS = [   # by reputation rank number (0 = lowest): {sect} {rank}
    (2,    ["Hardly anyone in the {sect} could have named them, and the world's verdict was "
            "simply '{rank}'",
            "Their name drew only shrugs, and the gossips filed them under '{rank}'"]),
    (4,    ["A few disciples of the {sect} knew their name, and rumor called them '{rank}'",
            "Their name had started to travel between the dining hall and the mission board, "
            "earning the title '{rank}'"]),
    (6,    ["Their name was spoken in tea houses across the region, where they were called "
            "'{rank}'",
            "Travelling merchants carried tales of them across the provinces, and the title "
            "'{rank}' followed"]),
    (8,    ["Whole sects bowed their heads at the mention of their name, and the world hailed "
            "them as '{rank}'",
            "Their name was carved into the tournament stones of three continents, and they "
            "became known as '{rank}'"]),
    (INF,  ["Every living cultivator knew their name, and even the heavens called them "
            "'{rank}'",
            "Their legend outlived kingdoms and sects alike, and the ages remembered them as "
            "'{rank}'"]),
]

# Placeholders: {steam} {name} {sect} {a_title} {talent} {dao} {meditation} {treasury}
# {missions} {personality} {reputation} {treasure} {element} {technique} {game} {realm}.
# {personality} is a past-tense phrase ("{name} made friends wherever they went");
# {reputation} is a full sentence without the final period. Add your own!
BACKSTORIES = [
    "Once known on Steam as '{steam}', {name} joined the {sect} as {a_title}. Their talent "
    "test revealed {talent}. {dao}. They {meditation}, and {treasury}. Within the sect, they "
    "{missions}. {name} {personality}. {reputation}. Their prized possession was {treasure}.",

    "The mortal world knew {name} only as '{steam}', a stubborn wanderer who {meditation}. "
    "Eventually the {sect} accepted them as {a_title}, and the talent stone revealed {talent}. "
    "{dao}. Over the years they {missions}, and {treasury}. {name} {personality}. "
    "{reputation}. At their belt always hung {treasure}.",

    "Elders of the {sect} still argue about {name}, {a_title} who once went by '{steam}' in "
    "the mortal realm. The talent test showed {talent}. {dao}. Mission hall records say {name} "
    "{missions}, and the vault ledger says they {treasury}. {name} {meditation}. "
    "{reputation}. Some say {name} {personality}. Their prized possession was {treasure}.",

    "Some say '{steam}' was just a name {name} borrowed in the mortal realm. Whatever the truth, "
    "the {sect} took them in as {a_title}, and the elders at the talent test uncovered {talent}. "
    "{dao}. {name} {meditation}, then {missions}. Along the way they {treasury}. Disciples "
    "agreed that {name} {personality}. {reputation}. Their most precious belonging was "
    "{treasure}.",

    "{name}, formerly '{steam}' in the mortal realm, served the {sect} as {a_title}. The talent "
    "test showed {talent}. {dao}. In their time, {name} {missions}, and {treasury}. They also "
    "{meditation}. {reputation}. Friends and rivals alike agreed that {name} {personality}. "
    "Of all their belongings, {treasure} was the dearest.",

    "Nobody in the {sect} could say where {name} came from, only that the mortal records listed "
    "them as '{steam}'. They joined as {a_title}, and the talent test revealed {talent}. {dao}. "
    "Legend says {name} {meditation}, and that they {missions}. They {treasury}. {reputation}. "
    "Whenever the tale was told, it added that {name} {personality}. Their prized possession "
    "was {treasure}.",

    "{name} came to the {sect} as {a_title}, carrying nothing but the mortal name '{steam}' and "
    "an affinity for {element}. The talent test revealed {talent}. {dao}. {name} {meditation}. "
    "The {technique} became their signature art. Over time they {missions}, and {treasury}. "
    "It was said {name} {personality}. {reputation}. Their prized possession was {treasure}.",
]


def pick_variant(value, tiers, rng, **fmt):
    for limit, variants in tiers:
        if value < limit:
            return rng.choice(variants).format(**fmt)


# ---------------------------------------------------------------------------
# Steam API helpers
# ---------------------------------------------------------------------------
class SteamError(Exception):
    pass


# ---------------------------------------------------------------------------
# Logging. Every Steam request goes through steam_get(), which counts it, so each
# command you run is written to Logs/steam_cultivator_<date>.log with what was run, what
# happened and how many Steam API calls it used (retries count too, because Steam counts
# every request). The API key is never written to the log.
# ---------------------------------------------------------------------------
def stamp(ts):
    """'2026-10-30 02:15:00' in local time."""
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


class RunLog:
    def __init__(self):
        self.lock = threading.Lock()
        self.secret = ""                 # the API key, hidden if it ever shows up in a message
        self.session_calls = 0
        self.session_commands = 0
        self.session_started = None
        self.session_written = False
        self.warned = False
        self.begin("")

    def begin(self, command):
        with self.lock:
            self.command = command
            self.started = time.time()
            self.calls = {}              # endpoint -> number of requests
            self.problems = {}           # (endpoint, outcome) -> number of requests
            self.notes = []

    def record(self, endpoint, outcome):
        with self.lock:
            self.calls[endpoint] = self.calls.get(endpoint, 0) + 1
            if outcome != "HTTP 200":
                k = (endpoint, outcome)
                self.problems[k] = self.problems.get(k, 0) + 1

    def note(self, text):
        with self.lock:
            self.notes.append(text)

    def total(self):
        with self.lock:
            return sum(self.calls.values())

    def scrub(self, text):
        text = re.sub(r"(key=)[0-9A-Za-z]+", r"\1<hidden>", str(text))
        if self.secret:
            text = text.replace(self.secret, "<hidden>")
        return text

    def _write(self, text):
        """Appends to today's log file. A log that can't be written never stops the program."""
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            path = os.path.join(LOG_DIR, "steam_cultivator_" + stamp(time.time())[:10] + ".log")
            with open(path, "a", encoding="utf-8") as f:
                f.write(text)
            return True
        except OSError as e:
            if not self.warned:
                self.warned = True
                print(f"\n  (Could not write the log in '{LOG_DIR}': {e}. Carrying on without it.)")
            return False

    def finish(self, status):
        """Writes the entry for the command that just ran."""
        now = time.time()
        with self.lock:
            calls, problems, notes = dict(self.calls), dict(self.problems), list(self.notes)
            command, took = self.command, now - self.started
        total = sum(calls.values())
        lines = []
        if not self.session_written:
            self.session_started = self.session_started or self.started
            lines.append(f"=== Session started {stamp(self.session_started)} ===\n")
        lines.append(f"[{stamp(self.started)}] "
                     f"{self.scrub(command)}\n")
        lines.append(f"  Result : {self.scrub(status)}\n")
        lines.append(f"  Steam API calls: {total} ({took:.1f}s)\n")
        for ep in sorted(calls):
            lines.append(f"    {ep:<34} {calls[ep]:>5}\n")
        for (ep, outcome), n in sorted(problems.items()):
            lines.append(f"  Problem: {ep}: {n} x {outcome}\n")
        for n in notes:
            lines.append(f"  Note   : {self.scrub(n)}\n")
        lines.append("\n")
        if self._write("".join(lines)):
            self.session_written = True
        self.session_calls += total
        self.session_commands += 1
        self.begin("")

    def end_session(self):
        if self.session_commands:
            self._write(f"=== Session ended {stamp(time.time())}: "
                        f"{self.session_commands} command(s), {self.session_calls} Steam API "
                        f"call(s) in total ===\n\n")


RUN_LOG = RunLog()


def steam_get(endpoint, params):
    """Makes one Steam request and counts it. Every request in the program goes through here."""
    name = re.sub(r"/v\d+/?$", "", endpoint.strip("/"))
    try:
        r = requests.get(f"{API}/{endpoint}", params=params, timeout=TIMEOUT)
    except requests.RequestException:
        RUN_LOG.record(name, "network error")
        raise
    # Steam answers 400 to "achievements of a game that has none", which is normal
    normal = r.status_code == 200 or (r.status_code == 400 and "GetPlayerAchievements" in name)
    RUN_LOG.record(name, "HTTP 200" if normal else f"HTTP {r.status_code}")
    return r


def api_get(path, key, **params):
    params["key"] = key
    try:
        r = steam_get(path, params)
    except requests.RequestException as e:
        raise SteamError(f"Could not reach Steam: {e}")
    if r.status_code in (401, 403):
        raise SteamError("Steam rejected the API key (check it is correct).")
    if r.status_code != 200:
        raise SteamError(f"Steam returned HTTP {r.status_code}.")
    try:
        return r.json().get("response", {})
    except ValueError:
        raise SteamError("Steam sent a response I could not read.")


def parse_profile_input(text):
    """Returns ('id', steamid64) or ('vanity', name)."""
    text = text.strip()
    if re.fullmatch(r"\d{17}", text):
        return "id", text
    m = re.search(r"steamcommunity\.com/profiles/(\d{17})", text)
    if m:
        return "id", m.group(1)
    m = re.search(r"steamcommunity\.com/id/([^/?#\s]+)", text)
    if m:
        return "vanity", m.group(1)
    return "vanity", text.strip("/ ")


def resolve_steamid(text, key):
    kind, value = parse_profile_input(text)
    if kind == "id":
        return value
    resp = api_get("ISteamUser/ResolveVanityURL/v1/", key, vanityurl=value)
    if resp.get("success") != 1:
        raise SteamError(f"Could not find a profile named '{value}'.")
    return resp["steamid"]


def fetch_profile(steamid, key, refresh=False):
    summary = api_get("ISteamUser/GetPlayerSummaries/v2/", key, steamids=steamid)
    players = summary.get("players", [])
    if not players:
        raise SteamError("No Steam profile exists with that ID.")
    player = players[0]
    if player.get("communityvisibilitystate") != 3:
        raise SteamError("This profile is private. Set the profile and 'Game details' to Public "
                         "in Steam > Edit Profile > Privacy Settings, then try again.")

    level_resp = api_get("IPlayerService/GetSteamLevel/v1/", key, steamid=steamid)

    # By default Steam leaves free-to-play games out of this list, so this is the
    # paid-games count (promo games that were claimed for free can still slip in).
    paid_resp = api_get("IPlayerService/GetOwnedGames/v1/", key, steamid=steamid,
                        include_appinfo=1)
    if "game_count" not in paid_resp:
        raise SteamError("Game details are hidden. Set 'Game details' to Public in your "
                         "Steam privacy settings (and untick 'Always keep my total playtime private').")

    # The most-played game is looked up among ALL games, free-to-play included,
    # so a cultivator can still be named after your Dota 2 / CS2 habit.
    all_resp = api_get("IPlayerService/GetOwnedGames/v1/", key, steamid=steamid,
                       include_appinfo=1, include_played_free_games=1)
    games = all_resp.get("games", [])
    top = max(games, key=lambda g: g.get("playtime_forever", 0), default=None)
    ach = count_achievements(steamid, key, games, refresh)
    RUN_LOG.note(f"achievements: {ach['total']} over {ach['games']} played games "
                 f"(asked Steam about {ach['queried']}, read {ach['reused']} from cache, "
                 f"{ach['failed']} failed, {ach['blocked']} blocked"
                 f"{', refresh forced' if ach['refreshed'] else ''})")

    # Badges (they feed the reputation system). Steam level is built purely from badge
    # XP, so a level above 0 with zero badges means Steam is not showing us the badges.
    try:
        badge_resp = api_get("IPlayerService/GetBadges/v1/", key, steamid=steamid)
    except SteamError:
        badge_resp = {}
    badges = len(badge_resp.get("badges", []))
    badges_hidden = badges == 0 and level_resp.get("player_level", 0) > 0
    created = player.get("timecreated")      # Unix time the account was made (public profiles)
    RUN_LOG.note(f"profile {steamid}: {player.get('personaname', 'Unknown')}, "
                 f"{len(games)} games owned incl. free, {badges} badges")
    return {
        "name": player.get("personaname", "Unknown"),
        "account_created": created if isinstance(created, int) and created > 0 else None,
        "level": level_resp.get("player_level", 0),
        "game_count": paid_resp.get("game_count", 0),
        "top_game": top.get("name", "Unknown Game") if top else None,
        "top_hours": (top.get("playtime_forever", 0) / 60) if top else 0.0,
        "total_hours": sum(g.get("playtime_forever", 0) for g in games) / 60,
        "achievements": ach["total"],
        "achievements_hidden": ach["hidden"],
        "achievements_new": ach["new"],      # gained since the last complete visit, or None
        "ach_stats": ach,
        "badges": badges,
        "badges_hidden": badges_hidden,
    }


# ---------------------------------------------------------------------------
# Achievements and the achievement cache
#
# Steam can only report achievements one game at a time, which is slow and eats API
# calls. So every game's result is saved in cache/<SteamID>.json next to this script.
# On the next visit Steam is asked about a game again only when something may have
# changed:
#   * the game is not in the cache yet (e.g. you started a new game),
#   * its playtime or its "last played" time changed (achievements are unlocked by
#     playing, so a game you did not touch cannot have new ones),
#   * or the saved entry is older than RECHECK_AFTER_DAYS, a safety net for the rare
#     unlock that does not show up in playtime (achievement tools, offline syncing).
# Typing "refresh <profile>" (or starting the program with --refresh) ignores the
# cache and checks every game again. Deleting the cache folder is always safe.
# ---------------------------------------------------------------------------
BLOCKED = "blocked"   # Steam refuses to show this profile's achievements
FAILED = "failed"     # the lookup did not work (network, Steam hiccup): result unknown

_cache_warned = False


def cache_path(steamid):
    return os.path.join(CACHE_DIR, f"{steamid}.json")


def load_cache(steamid):
    """Returns (cache, found). A missing, damaged or outdated file just counts as no cache."""
    empty = {"version": CACHE_VERSION, "steamid": str(steamid), "last_total": None, "games": {}}
    try:
        with open(cache_path(steamid), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return empty, False
    if (not isinstance(data, dict) or data.get("version") != CACHE_VERSION
            or data.get("steamid") != str(steamid) or not isinstance(data.get("games"), dict)):
        return empty, False
    if not isinstance(data.get("last_total"), int):
        data["last_total"] = None
    return data, True


def save_cache(cache):
    """Writes the cache file; returns False (after one warning) if the folder is not writable."""
    global _cache_warned
    path = cache_path(cache["steamid"])
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=1)
        os.replace(tmp, path)       # all or nothing: an interrupted save never leaves half a file
        return True
    except OSError as e:
        if not _cache_warned:
            _cache_warned = True
            print(f"\n  (Could not save the cache in '{CACHE_DIR}': {e}. Carrying on without it.)")
        return False


def entry_is_current(entry, game, now):
    """True if the saved result for this game can be trusted without asking Steam again."""
    if not isinstance(entry, dict) or not isinstance(entry.get("unlocked"), int):
        return False
    if entry.get("playtime") != game.get("playtime_forever", 0):
        return False
    if entry.get("last_played") != game.get("rtime_last_played", 0):
        return False
    checked = entry.get("checked_at")
    if not isinstance(checked, (int, float)):
        return False
    if RECHECK_AFTER_DAYS and now - checked > RECHECK_AFTER_DAYS * 86400:
        return False
    return True


def apply_results(cache, games, results, now):
    """Stores every real number from this round in the cache (never BLOCKED or FAILED).
    Returns True if anything was written."""
    changed = False
    for g in games:
        k = str(g["appid"])
        result = results.get(k)
        if isinstance(result, int):
            cache["games"][k] = {"unlocked": result, "playtime": g.get("playtime_forever", 0),
                                 "last_played": g.get("rtime_last_played", 0), "checked_at": now}
            changed = True
    return changed


def achievements_for_game(appid, steamid, key):
    """Unlocked achievements for one game: a number, BLOCKED (private) or FAILED (unknown).
    A game that has no achievements is simply 0."""
    for attempt in range(3):
        try:
            r = steam_get("ISteamUserStats/GetPlayerAchievements/v1/",
                          {"key": key, "steamid": steamid, "appid": appid})
        except requests.RequestException:
            time.sleep(1 + attempt)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(1 + attempt)          # Steam wants us to slow down; try again
            continue
        if r.status_code == 403:
            return BLOCKED                   # achievements are private
        if r.status_code == 400:
            return 0                         # Steam's answer for "this game has no achievements"
        if r.status_code != 200:
            return FAILED
        try:
            stats = r.json().get("playerstats", {})
        except (ValueError, AttributeError):
            return FAILED
        if "not public" in str(stats.get("error", "")).lower():
            return BLOCKED
        return sum(1 for a in stats.get("achievements", []) if a.get("achieved") == 1)
    return FAILED


class PrivacyWatch:
    """Spots a private profile early. Steam says 'not public' for every game, so after a few
    such answers and no good ones there is no point asking about the remaining games."""
    def __init__(self):
        self.lock = threading.Lock()
        self.blocked = 0
        self.good = 0

    def record(self, result):
        with self.lock:
            if result == BLOCKED:
                self.blocked += 1
            elif isinstance(result, int):
                self.good += 1

    def private(self):
        with self.lock:
            return self.blocked >= 3 and self.good == 0


def lookup_game(appid, steamid, key, watch):
    if watch.private():
        return BLOCKED
    result = achievements_for_game(appid, steamid, key)
    watch.record(result)
    return result


def count_achievements(steamid, key, games, refresh=False):
    """Total unlocked achievements over every game you have played (free ones too), using
    the cache wherever the saved result is still valid. Returns a dict:
      total, hidden (Steam hides them and nothing is known), reused (games read from the
      cache), queried (games asked about on Steam), failed / blocked (games that could not
      be checked this time), new (achievements gained since the last complete visit, or
      None on a first visit), had_cache, refreshed, games."""
    cache, had_cache = load_cache(steamid)
    old = cache["games"]
    now = time.time()
    played = [g for g in games if g.get("playtime_forever", 0) > 0]

    counts = {}                      # appid -> unlocked achievements
    todo = []
    for g in played:
        k = str(g["appid"])
        if not refresh and entry_is_current(old.get(k), g, now):
            counts[k] = old[k]["unlocked"]
        else:
            todo.append(g)
    stats = {"total": 0, "hidden": False, "reused": len(played) - len(todo), "queried": len(todo),
             "failed": 0, "blocked": 0, "new": None, "had_cache": had_cache,
             "refreshed": bool(refresh), "games": len(played)}

    results = {}                     # appid -> number, BLOCKED or FAILED
    if todo:
        watch = PrivacyWatch()
        pool = ThreadPoolExecutor(max_workers=ACHIEVEMENT_WORKERS)
        futures = {pool.submit(lookup_game, g["appid"], steamid, key, watch): g for g in todo}
        try:
            for f in as_completed(futures):
                results[str(futures[f]["appid"])] = f.result()
                print(f"\r  Counting achievements... {len(results)}/{len(todo)} games",
                      end="", flush=True)
        except BaseException:
            # Interrupted (Ctrl+C): keep every game that finished, so the next run only has
            # to do the rest. last_total stays as it was, because the scan is incomplete.
            for f, g in futures.items():
                if f.done() and not f.cancelled() and f.exception() is None:
                    results.setdefault(str(g["appid"]), f.result())
            try:
                pool.shutdown(wait=False, cancel_futures=True)
            except TypeError:                # Python older than 3.9
                pool.shutdown(wait=False)
            if apply_results(cache, todo, results, now):
                save_cache(cache)
            print()
            raise
        pool.shutdown()
        print("\r" + " " * 48 + "\r", end="", flush=True)

    for g in todo:
        k = str(g["appid"])
        result = results.get(k, FAILED)
        if isinstance(result, int):
            counts[k] = result
        else:                        # unknown right now: use the last known value, never a guess
            stats["blocked" if result == BLOCKED else "failed"] += 1
            prior = old.get(k)
            counts[k] = prior["unlocked"] if isinstance(prior, dict) and isinstance(
                prior.get("unlocked"), int) else 0

    total = sum(counts.values())
    stats["total"] = total
    stats["hidden"] = bool(todo) and stats["blocked"] == len(todo) and total == 0

    dirty = apply_results(cache, todo, results, now)
    if stats["failed"] == 0 and stats["blocked"] == 0:   # only a complete scan sets the baseline
        if cache["last_total"] is not None:
            stats["new"] = total - cache["last_total"]
        if cache["last_total"] != total:
            cache["last_total"] = total
            dirty = True
    if dirty:
        save_cache(cache)
    return stats


def get_friend_ids(steamid, key):
    """Returns (friend_ids, note). The list is empty when there are no friends or the
    friends list can't be read; note is a short explanation worth showing, or None."""
    try:
        r = steam_get("ISteamUser/GetFriendList/v1/",
                      {"key": key, "steamid": steamid, "relationship": "friend"})
    except requests.RequestException:
        return [], None
    if r.status_code in (401, 403):
        return [], "Your friends list is private, so no friend story this time."
    if r.status_code != 200:
        return [], None
    try:
        friends = r.json().get("friendslist", {}).get("friends", [])
    except ValueError:
        return [], None
    return [f["steamid"] for f in friends], None  # no friends -> empty list -> story skipped


def get_friend(friend_id, key):
    """Returns {'steamid', 'name'} or None if that friend's profile can't be read."""
    try:
        players = api_get("ISteamUser/GetPlayerSummaries/v2/", key, steamids=friend_id).get("players", [])
    except SteamError:
        return None
    if not players:
        return None
    return {"steamid": friend_id, "name": players[0].get("personaname", "a mysterious stranger")}


def resolve_friend(c, friend_ids, key):
    """The friend who appears in the story: the traitor if the cultivator was betrayed,
    otherwise a random friend. None when there is nobody to use."""
    death = c["death"]
    if death and death["friend_id"]:
        friend = get_friend(death["friend_id"], key)
        if friend:
            return friend
    if friend_ids:
        return get_friend(random.choice(friend_ids), key)
    return None


# ---------------------------------------------------------------------------
# Cultivator generation
# ---------------------------------------------------------------------------
def power_score(info, talent_bonus=0):
    base = info["level"] * 10 + info["game_count"] * 2 + info["top_hours"] / 10
    return max(0, base + talent_bonus)


def roll_talent(steamid):
    """Pure luck: only the SteamID is used, never level, games or hours. The same
    SteamID always rolls the same talent, which keeps the death roll stable too."""
    rng = random.Random(f"talent-{steamid}")
    return rng.choices(TALENTS, weights=[t["weight"] for t in TALENTS], k=1)[0]


def roll_path(steamid):
    """Righteous or Demonic, by luck only. The same SteamID always walks the same path."""
    rng = random.Random(f"path-{steamid}")
    return PATHS[0] if rng.random() < RIGHTEOUS_CHANCE else PATHS[1]


def path_label(path):
    effects = []
    if path["power"]:
        effects.append(f"+{path['power']} power")
    if path["rep"]:
        effects.append(f"+{path['rep']} reputation")
    return path["name"] + (f" ({', '.join(effects)})" if effects else "")


def get_personalities(info, friend_count):
    """Every personality this profile qualifies for, in table order."""
    return [p for p in PERSONALITIES if p["test"](info, friend_count)]


def personality_phrase(personalities):
    traits = [p["trait"] for p in personalities] or [NO_PERSONALITY_TRAIT]
    if len(traits) == 1:
        return traits[0]
    return ", ".join(traits[:-1]) + " and " + traits[-1]


def reputation_rank(points):
    idx = 0
    for i, (threshold, _) in enumerate(REPUTATION_RANKS):
        if points >= threshold:
            idx = i
    return idx


def roll_reputation(steamid, info, personalities, path=None):
    """Badges give the base reputation; personalities and the path add to it. A
    personality with a rep_chance below 1.0 rolls for its points; the roll comes from the
    SteamID, and every group in the table draws in a fixed order, so results never shift."""
    rng = random.Random(f"rep-{steamid}")
    groups = list(dict.fromkeys(p.get("roll_group", p["name"]) for p in PERSONALITIES))
    rolls = {g: rng.random() for g in groups}
    badge_points = info["badges"] * REP_PER_BADGE
    bonuses = [(p["name"], p["rep"]) for p in personalities
               if p["rep"] and rolls[p.get("roll_group", p["name"])] < p["rep_chance"]]
    if path and path["rep"]:
        bonuses.append((f"{path['name']} Path", path["rep"]))
    points = max(0, badge_points + sum(amount for _, amount in bonuses))
    idx = reputation_rank(points)
    return {"points": points, "badge_points": badge_points, "bonuses": bonuses,
            "rank_index": idx, "rank": REPUTATION_RANKS[idx][1]}


def get_realm(score):
    idx = 0
    for i, (threshold, _, _) in enumerate(REALMS):
        if score >= threshold:
            idx = i
    return idx, REALMS[idx]


def make_name(rng):
    return f"{rng.choice(SURNAMES)} {rng.choice(GIVEN)}{rng.choice(GIVEN).lower()}"


def generate_story(c, info, friend):
    # The friend's cultivator name is seeded from their SteamID, so it stays the same;
    # the story itself is picked at random, so every run can give a new one.
    friend_name = make_name(random.Random(int(friend["steamid"])))
    pool = list(STORIES_COMMON)
    if c["realm_index"] <= 3:
        pool += STORIES_WEAK
    elif c["realm_index"] >= 5:
        pool += STORIES_STRONG
    return random.choice(pool).format(
        me=c["name"], friend=friend_name, friend_steam=friend["name"],
        game=info["top_game"] or "the Void", sect=c["sect"],
        realm=c["realm"], treasure=c["treasure"])


def killer_phrases(realm_index):
    """(rogue cultivator, bandits) descriptions; stronger victims get stronger killers."""
    if realm_index <= 3:
        return "a nameless rogue cultivator", "a gang of mountain bandits"
    if realm_index <= 6:
        return "a feared rogue cultivator", "an army of five hundred bandits"
    return "a legendary rogue cultivator", "a bandit alliance of ten thousand blades"


def account_years(created, now=None):
    """How many years old the Steam account is, or None when Steam did not tell us."""
    if not isinstance(created, (int, float)) or created <= 0:
        return None
    return max(0.0, ((time.time() if now is None else now) - created) / SECONDS_PER_YEAR)


def cultivator_age(years, lifespan):
    """Age of the cultivator from the age of the Steam account: the older the account, the
    older the cultivator. A brand-new account is a youngster (16 at the very least), and an
    account of ACCOUNT_YEARS_FOR_MAX_AGE years or more is nearly at the end of the lifespan
    (95% of it). Returns None when the account age is unknown."""
    if years is None:
        return None
    share = 0.05 + 0.90 * min(years, ACCOUNT_YEARS_FOR_MAX_AGE) / ACCOUNT_YEARS_FOR_MAX_AGE
    return 16 + int((lifespan - 16) * share)


def roll_fate(steamid, realm_index, lifespan, friend_ids, death_chance, age=None):
    """Birth year and (maybe) death. The same SteamID always gives the same fate.
    Everything is drawn in a fixed order, so a result never shifts because
    something else (like the friends list) happened to change. If age is given (from
    the Steam account age), a doomed cultivator dies at that age instead of a random one."""
    fate = random.Random(f"fate-{steamid}")
    dies = fate.random() < death_chance      # death_chance comes from the talent
    betrayed = fate.random() < BETRAYAL_CHANCE
    killer = fate.choice(["rogue", "bandits"])
    scene = fate.randrange(1000)
    age_roll = fate.random()
    friend_roll = fate.random()
    birth_year = fate.randint(1000, 9000)

    result = {"birth_year": birth_year, "death": None}
    if dies:
        if age is None:                          # account age unknown: a random age at death
            min_age = 18 + realm_index * 60      # a strong cultivator is not a teenager
            age = min_age + int(age_roll * (lifespan - min_age))
        friend_id = None
        if betrayed and friend_ids:              # no friends -> no betrayal
            ids = sorted(friend_ids)
            friend_id = ids[int(friend_roll * len(ids))]
        result["death"] = {"killer": killer, "friend_id": friend_id, "scene": scene,
                           "age": age, "year": birth_year + age}
    return result


def describe_death(c, info, friend):
    """Returns (killer_label, text) for a cultivator that died."""
    d = c["death"]
    rogue, bandits = killer_phrases(c["realm_index"])
    fmt = dict(me=c["name"], sect=c["sect"], technique=c["technique"], treasure=c["treasure"],
               realm=c["realm"], game=info["top_game"] or "the Void", rogue=rogue, bandits=bandits)
    if d["friend_id"] and friend and friend["steamid"] == d["friend_id"]:
        friend_name = make_name(random.Random(int(friend["steamid"])))
        fmt.update(friend=friend_name, friend_steam=friend["name"])
        pool = DEATH_FRIEND
        label = f"{friend_name} (Steam: {friend['name']}), a trusted friend"
    elif d["killer"] == "rogue":
        pool, label = DEATH_ROGUE, rogue
    else:
        pool, label = DEATH_BANDITS, bandits
    return label, pool[d["scene"] % len(pool)].format(**fmt)


def generate_cultivator(info, steamid, friend_ids=None):
    rng = random.Random(int(steamid))  # same profile -> same cultivator
    talent = roll_talent(steamid)      # rolled first: it changes both power and death risk
    personalities = get_personalities(info, len(friend_ids or []))   # second: same reason
    path = roll_path(steamid)          # third: the Demonic Path adds power
    score = power_score(info, talent["power"] + sum(p["power"] for p in personalities)
                        + path["power"])
    idx, (_, realm, realm_flavor) = get_realm(score)

    if idx <= 2:
        titles, treasures = TITLES_LOW, TREASURES_LOW
    elif idx <= 6:
        titles, treasures = TITLES_MID, TREASURES_MID
    else:
        titles, treasures = TITLES_HIGH, TREASURES_HIGH

    name = make_name(rng)
    sect = f"{rng.choice(SECT_ADJ)} {rng.choice(SECT_NOUN)}"
    title = rng.choice(titles)
    element = rng.choice(ELEMENTS)
    treasure = rng.choice(treasures)

    game = info["top_game"] or "the Void"
    technique = f"{rng.choice(MOVE_ADJ)} {game} {rng.choice(MOVE_NOUN)}"

    lifespan = 80 + idx * rng.randint(150, 400)
    lightning = max(0, idx - 5) * 3 + (9 if idx == 9 else 0)
    death_chance = min(1.0, talent["death"] + sum(p["death"] for p in personalities))
    years = account_years(info.get("account_created"))
    age = cultivator_age(years, lifespan)    # None if Steam did not give the account's age
    fate = roll_fate(steamid, idx, lifespan, friend_ids or [], death_chance, age)
    age = fate["death"]["age"] if fate["death"] else age
    reputation = roll_reputation(steamid, info, personalities, path)

    # Sect missions: every unlocked achievement counts, and each one pays sect points
    missions = info["achievements"]
    sect_points = missions * SECT_POINTS_PER_MISSION

    # Backstory built from the real stats (variants and template picked from the SteamID)
    hrs, gc, lvl = info["top_hours"], info["game_count"], info["level"]
    nums = dict(hrs=f"{hrs:,.0f}", gc=f"{gc:,}", lvl=lvl, n=f"{missions:,}", game=game, sect=sect)
    meditation = pick_variant(hrs, MEDITATION_TIERS, rng, **nums)
    treasury = pick_variant(gc, TREASURY_TIERS, rng, **nums)
    dao = pick_variant(lvl, DAO_TIERS, rng, **nums)
    mission_text = pick_variant(missions, MISSION_TIERS, rng, **nums)

    # The reputation sentence uses its own generator so it never disturbs the picks above
    rep_text = pick_variant(reputation["rank_index"], REPUTATION_TIERS,
                            random.Random(f"repphrase-{steamid}"),
                            sect=sect, rank=reputation["rank"])

    article = "an" if title[0] in "AEIOU" else "a"
    backstory = rng.choice(BACKSTORIES).format(
        personality=personality_phrase(personalities), reputation=rep_text,
        steam=info["name"], name=name, sect=sect, a_title=f"{article} {title}",
        talent=talent["blurb"], dao=dao, meditation=meditation, treasury=treasury,
        missions=mission_text, treasure=treasure, element=element, technique=technique,
        game=game, realm=realm)

    return {
        "name": name, "sect": sect, "title": title, "realm": realm, "realm_flavor": realm_flavor,
        "realm_index": idx, "element": element, "technique": technique, "lifespan": lifespan,
        "lightning": lightning, "treasure": treasure, "backstory": backstory, "score": score,
        "birth_year": fate["birth_year"], "death": fate["death"], "talent": talent,
        "age": age, "account_years": years,
        "missions": missions, "sect_points": sect_points,
        "personalities": personalities, "reputation": reputation, "death_chance": death_chance,
        "path": path,
    }


def power_bar(idx):
    total = len(REALMS)
    return "[" + "#" * (idx + 1) + "-" * (total - idx - 1) + f"] {idx + 1}/{total}"


def achievement_note(st):
    """One short line about where the achievement numbers came from."""
    if not st or st["hidden"] or st["games"] == 0:
        return None
    parts = []
    if st["refreshed"]:
        parts.append(f"full re-check of {st['queried']:,} games, cache updated")
    elif st["queried"] == 0:
        parts.append(f"all {st['reused']:,} games read from the cache, no Steam lookups needed")
    elif st["reused"] == 0:
        parts.append(f"{st['queried']:,} games checked with Steam and saved to the cache"
                     if not st["had_cache"] else f"{st['queried']:,} games checked with Steam")
    else:
        parts.append(f"{st['queried']:,} of {st['games']:,} games checked with Steam, "
                     f"{st['reused']:,} read from the cache")
    unknown = st["failed"] + st["blocked"]
    if unknown:
        parts.append(f"{unknown:,} could not be checked this time and will be retried next visit")
    return "; ".join(parts)


def personality_label(p):
    effects = []
    if p["power"]:
        effects.append(f"{p['power']:+d} power")
    if p["death"]:
        effects.append(f"{p['death'] * 100:+g}% death risk")
    return p["name"] + (f" ({', '.join(effects)})" if effects else "")


def print_cultivator(c, info):
    line = "=" * 64
    print("\n" + line)
    print(f"  {c['name']}  -  {c['title']} of the {c['sect']}")
    print(line)
    print(f"  Realm       : {c['realm']} ({c['realm_flavor']})")
    print(f"  Power       : {power_bar(c['realm_index'])}   (score {c['score']:,.0f})")
    t = c["talent"]
    print(f"  Talent      : {t['name']} (power {t['power']:+d})")
    if c["personalities"]:
        print("  Personality : " + ", ".join(personality_label(p) for p in c["personalities"]))
    else:
        print("  Personality : none (a quiet temperament)")
    print(f"  Path        : {path_label(c['path'])}")
    rep = c["reputation"]
    print(f"  Reputation  : {rep['rank']} ({rep['points']:,} points)")
    if rep["bonuses"]:
        print("  Fame boosts : " + ", ".join(f"{n} +{a}" for n, a in rep["bonuses"]))
    print(f"  Death risk  : {c['death_chance'] * 100:g}%")
    print(f"  Affinity    : {c['element']}")
    print(f"  Matchups    : strong vs {', '.join(ELEMENT_BEATS.get(c['element'], []))}; "
          f"weak vs {', '.join(element_weak_to(c['element']))}")
    print(f"  Signature   : {c['technique']}")
    print(f"  Treasure    : {c['treasure']}")
    if info["achievements_hidden"]:
        print("  Missions    : 0 (Steam is hiding your achievements)")
    else:
        n = c["missions"]
        print(f"  Missions    : {n:,} sect mission{'' if n == 1 else 's'} completed")
        new = info.get("achievements_new")
        if new and new > 0:
            print(f"  Since last  : +{new:,} new mission{'' if new == 1 else 's'} "
                  f"(+{new * SECT_POINTS_PER_MISSION:,} sect points) since your last visit")
    print(f"  Sect points : {c['sect_points']:,}")
    cut = " (cut short)" if c["death"] else ""
    print(f"  Lifespan    : {c['lifespan']:,} years{cut}")
    print(f"  Born        : Year {c['birth_year']} of the Heavenly Calendar")
    if c.get("age") is not None:
        when = " at death" if c["death"] else ""
        print(f"  Age         : {c['age']:,} years{when} ({c['account_years']:.0f}-year-old "
              f"account)")
    if c["death"]:
        print(f"  Died        : Year {c['death']['year']} of the Heavenly Calendar "
              f"(aged {c['death']['age']:,})")
    else:
        print("  Status      : Alive and cultivating")
    if c["lightning"]:
        print(f"  Tribulations: survived {c['lightning']} heavenly lightning strikes")
    print(line)
    print("  Source stats from Steam:")
    if info.get("account_created") and c.get("account_years") is not None:
        year = datetime.datetime.fromtimestamp(info["account_created"], datetime.timezone.utc).year
        print(f"    Account age : {c['account_years']:.1f} years (created {year})")
    print(f"    Steam level : {info['level']}")
    print(f"    Paid games  : {info['game_count']:,}")
    print(f"    Achievements: {info['achievements']:,}")
    note = achievement_note(info.get("ach_stats"))
    if note:
        print(f"      ({note})")
    if info["badges_hidden"]:
        print("    Badges      : 0 (Steam is hiding your badges)")
    else:
        print(f"    Badges      : {info['badges']:,}")
    if info["top_game"]:
        print(f"    Most played : {info['top_game']} ({info['top_hours']:,.0f} h)")
    print(line)
    print()
    wrap_print(c["backstory"])
    print(line + "\n")


def wrap_print(text, width=62):
    words, line = text.split(), ""
    for w in words:
        if len(line) + len(w) + 1 > width:
            print("  " + line)
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        print("  " + line)


def print_story(story, friend):
    print(f"  A tale from their life (Steam friend: {friend['name']})")
    print("  " + "-" * 62)
    wrap_print(story)
    print("=" * 64 + "\n")


def print_death(c, info, friend):
    label, text = describe_death(c, info, friend)
    print("  The end of the road")
    print("  " + "-" * 62)
    print(f"  Slain by : {label}")
    print()
    wrap_print(text)
    print("=" * 64 + "\n")


# ---------------------------------------------------------------------------
# Duels: the "mocb" command
# ---------------------------------------------------------------------------
BATTLE_PLACES = [
    "a storm-lashed cliff above the Nine-Dragon Sea", "the ruins of an ancient sect gate",
    "a frozen mountain pass", "the arena of the Heavenly Tournament",
    "a moonlit bamboo forest", "a valley where the Qi hung thick as fog",
    "the courtyard of an abandoned temple", "a floating island high above the clouds",
]

# Openings by the two paths. In a mixed pair {x} is always the Righteous one and {y} the
# Demonic one. Placeholders: {x} {y} {x_sect} {y_sect} {place}
BATTLE_OPENINGS = {
    ("Righteous", "Righteous"): [
        "At {place}, {x} of the {x_sect} and {y} of the {y_sect}, both walkers of the "
        "Righteous Path, agreed to settle an old argument over who was the greater "
        "cultivator. Neither intended to hold back.",
        "Two upright cultivators, {x} and {y}, met at {place}. Bows were exchanged, then the "
        "Qi began to rise, because both were far too proud to yield.",
    ],
    ("Demonic", "Demonic"): [
        "At {place}, {x} and {y}, two walkers of the Demonic Path, reached for the same prize. "
        "Demonic cultivators do not share, and they certainly do not talk it over.",
        "{x} of the {x_sect} and {y} of the {y_sect} met at {place}, and the air turned bitter "
        "with killing intent. On the Demonic Path, only one of them was walking away.",
    ],
    ("Righteous", "Demonic"): [
        "At {place}, {x} of the {x_sect}, a champion of the Righteous Path, finally cornered "
        "{y} of the {y_sect}, whose Demonic arts had troubled the region for years.",
        "{y}, a Demonic cultivator, was trespassing near {place} when {x} of the Righteous Path "
        "appeared and demanded they leave. {y} laughed, and the sky darkened.",
    ],
}

# Placeholders: {x} {y} {x_tech} {y_tech} {x_elem} {y_elem}
BATTLE_CLASHES = [
    "{x} opened with {x_tech}, and {y} met it with {y_tech}, {x_elem} colliding with "
    "{y_elem} until the ground cracked.",
    "{x_tech} tore across the sky, answered by {y_tech}; {x_elem} Qi and {y_elem} Qi spiralled "
    "together in a roaring storm.",
    "The first exchange shook the mountain: {x_tech} against {y_tech}, {x_elem} against "
    "{y_elem}, and neither dared to blink.",
]

# The turning point depends on how likely the winner was to win.
# Placeholders: {w} {l} (winner, loser) {w_tech} {l_tech} {gap} (a sentence about the realms, or empty)
BATTLE_TURNS = {
    "close": [
        "For a hundred exchanges neither gave an inch, until {w} found a single opening in "
        "{l}'s defense and drove {w_tech} straight through it.",
        "The duel hung by a thread. In the end it was {w_tech} landing a heartbeat before "
        "{l_tech} that decided everything.",
        "Both were bleeding Qi, and both were smiling. Then {l} stumbled on a loose stone, and "
        "{w} did not waste the gift.",
    ],
    "clear": [
        "Little by little the difference in cultivation showed. {w}'s Qi flowed steady while "
        "{l}'s began to falter.{gap}",
        "{w} read every move of {l}'s {l_tech} and answered each one with calm precision.{gap}",
        "{l} fought bravely, but {w_tech} grew heavier with every exchange.{gap}",
    ],
    "crushing": [
        "It was hardly a contest. A single wave of {w}'s Qi sent {l} skidding across the "
        "stone.{gap}",
        "{l} barely finished {l_tech} before {w_tech} swept it aside like autumn leaves.{gap}",
        "The ground itself bowed under {w}'s Qi, and {l} could only watch as {w_tech} "
        "descended.{gap}",
    ],
    "upset": [
        "Everyone would have bet on {l}, but fortune had other plans. A forgotten trick, a lucky "
        "misstep, and suddenly {w_tech} was past {l}'s guard.{gap}",
        "Against every prediction, {w} refused to fall. When {l} grew careless, the heavens "
        "themselves seemed to tilt, and {w_tech} struck true.{gap}",
        "The odds said {l}. The Dao said otherwise. {w} caught {l_tech} on a borrowed breath and "
        "turned it back with ruthless timing.{gap}",
    ],
}

# Endings by (winner's path, loser's path).
# Placeholders: {w} {l} {w_sect} {l_sect} {w_treasure} {l_treasure}
BATTLE_ENDINGS = {
    ("Righteous", "Righteous"): [
        "{w} stepped back and offered {l} a healing pill. 'You fought well,' {w} said, and "
        "neither of them ever mentioned {l_treasure} again.",
        "{l} yielded with a bow, and {w} returned it. Word of the duel spread through the "
        "{w_sect}, and everyone agreed it had been an honorable one.",
        "Afterwards the two sat down to share a pot of spirit tea, arguing happily about who "
        "had really been the stronger.",
    ],
    ("Righteous", "Demonic"): [
        "{w} sealed {l}'s Qi with a talisman and carried {l} off to the {w_sect} for judgment, "
        "as the Righteous Path demanded.",
        "Ignoring {l}'s pleas, {w} shattered {l_treasure} and warned {l} never to return.",
        "{w} broke {l}'s demonic cultivation with a single palm. 'Walk a better road,' {w} "
        "said, and left.",
    ],
    ("Demonic", "Righteous"): [
        "{w} smiled coldly, plucked {l_treasure} from the dust, and left {l} to crawl home with "
        "a broken pride.",
        "Showing no mercy, {w} drained the last of {l}'s Qi and strolled away with "
        "{l_treasure}, humming a cheerful tune.",
        "{l} spoke of honor and mercy. {w} laughed, took {l_treasure} as the price of the "
        "lesson, and vanished into the night.",
    ],
    ("Demonic", "Demonic"): [
        "{w} finished the duel with a flick of the wrist. By morning the {l_sect} was missing "
        "one cultivator, and {w} was wearing {l_treasure}.",
        "{w} wiped a drop of blood from a thumb, claimed {l_treasure}, and left {l} as a "
        "warning to every other demonic cultivator in the region.",
        "{l} begged for mercy. {w} considered it, took {l_treasure} as the price, and let {l} "
        "live, for the moment.",
    ],
}


# ---------------------------------------------------------------------------
# Affinity matchups. ELEMENT_BEATS[x] lists the two elements x is strong against; each of
# those is weak against x. The table is balanced: every element beats exactly two others
# and loses to exactly two others, so no element is better than the rest overall.
# A matchup moves the duel odds by AFFINITY_BONUS for the stronger element and against the
# weaker one (0.03 = 3 percentage points). Elements not listed against each other, and two
# of the same element, are neutral.
# ---------------------------------------------------------------------------
AFFINITY_BONUS = 0.03
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

# ---------------------------------------------------------------------------
# Power gap. When one fighter's power towers over the other's (compared as a ratio, with
# the same BATTLE_SCORE_FLOOR as the odds), the story says so, and the stronger fighter
# acts arrogant and confident. Ratios at or above each limit pick the tier.
# ---------------------------------------------------------------------------
GAP_NOTICEABLE = 1.5
GAP_LARGE = 3.0
GAP_VAST = 8.0

# Placeholders: {strong} {weak} {strong_power} {weak_power}
BATTLE_GAP_SETUPS = {
    "noticeable": [
        "{strong} held the edge in power, {strong_power} against {weak_power}, and made sure "
        "{weak} could see the confident smile.",
        "'Show me what you have,' said {strong}, who commanded {strong_power} power to "
        "{weak}'s {weak_power}, with the easy confidence of someone who expects to win.",
        "{strong} rolled a shoulder and smiled. {strong_power} power against {weak_power} was a "
        "lead worth being smug about.",
    ],
    "large": [
        "{weak}, with only {weak_power} power, had challenged {strong}, who held "
        "{strong_power}. {strong} laughed out loud. 'Do you even understand the gap between "
        "us?'",
        "With {strong_power} power against {weak_power}, {strong} did not bother hiding the "
        "smirk. 'Kneel now, and I might forget this insolence,' {strong} said.",
        "{strong} looked down at {weak} the way a mountain looks at a pebble: {strong_power} "
        "power against a mere {weak_power}.",
    ],
    "vast": [
        "It was the strangest challenge the region had ever seen: {weak}, with a mere "
        "{weak_power} power, daring to face {strong}, who commanded {strong_power}. {strong} "
        "yawned. 'I will grant you the first move, and the second, and the third,' {strong} "
        "said.",
        "{strong}, arrogant to the bone with {strong_power} power, did not even take a stance. "
        "'Is this a duel or a joke?' {strong} sneered at {weak}'s {weak_power}.",
        "Nobody had expected {weak}, with {weak_power} power, to challenge {strong} and "
        "{strong_power}. {strong} stood with arms folded, wearing the bored face of someone "
        "watching an ant try to move a mountain.",
    ],
}

# After the duel, for large and vast gaps: key is (tier, did the stronger fighter win?)
BATTLE_GAP_AFTERMATH = {
    ("large", True): [
        "{strong} did not even look back. 'Come again when you are worth my time,' {strong} "
        "said.",
        "Without a scratch on them, {strong} dusted off a sleeve, already bored. 'Next,' "
        "{strong} called.",
    ],
    ("large", False): [
        "{strong}'s smile was gone. The tale of how pride cost {strong} the duel against "
        "{weak} would be told in tea houses for years.",
        "{strong} stared at the sky, stunned. Arrogance, it turned out, was the one opponent "
        "{strong} had never trained against.",
    ],
    ("vast", True): [
        "'Come back in a thousand years,' {strong} said over a shoulder, and did not wait for "
        "an answer.",
        "{strong} yawned again. The whole fight had taken less effort than a morning stretch, "
        "and everyone present knew it.",
    ],
    ("vast", False): [
        "The silence was enormous. {strong}, who had boasted of {strong_power} power, had been "
        "humbled by a cultivator with only {weak_power}, and the whole region would never let "
        "{strong} forget it.",
        "{weak} bowed politely. {strong} could not speak. By the next morning, 'pride before "
        "the fall' was a saying in every tea house.",
    ],
}

# When the elements favor one fighter. Placeholders: {adv} {dis} {adv_elem} {dis_elem}
BATTLE_ELEMENT_LINES = [
    "{adv_elem} is the natural bane of {dis_elem}, and {adv} felt the Qi tilt ever so slightly "
    "in their favor.",
    "The elements leaned toward {adv}: {adv_elem} holds the upper hand over {dis_elem}.",
    "{dis} could feel {dis_elem} Qi struggle against {adv}'s {adv_elem}, like swimming against "
    "a gentle current.",
]


def element_edge(x, y):
    """+1 if element x is strong against element y, -1 if it is weak against it, else 0."""
    if y in ELEMENT_BEATS.get(x, ()):
        return 1
    if x in ELEMENT_BEATS.get(y, ()):
        return -1
    return 0


def element_weak_to(x):
    """The elements that are strong against element x, in the usual element order."""
    return [e for e in ELEMENTS if x in ELEMENT_BEATS.get(e, ())]


def power_odds(a, b):
    """Chance (0 to 1) that cultivator a beats cultivator b, from both power scores alone."""
    sa = (a["score"] + BATTLE_SCORE_FLOOR) ** BATTLE_EXPONENT
    sb = (b["score"] + BATTLE_SCORE_FLOOR) ** BATTLE_EXPONENT
    return sa / (sa + sb)


def element_shift(a, b):
    """How far the elements move a's chance: +AFFINITY_BONUS, -AFFINITY_BONUS or 0."""
    return AFFINITY_BONUS * element_edge(a["element"], b["element"])


def battle_odds(a, b):
    """Chance (0 to 1) that cultivator a beats cultivator b: power plus the element matchup.
    Kept inside 0.1% to 99.9%, so no duel is ever certain."""
    return min(0.999, max(0.001, power_odds(a, b) + element_shift(a, b)))


def power_gap(a, b):
    """Returns (tier, stronger, weaker, ratio). tier is 'noticeable', 'large', 'vast' or None."""
    sa, sb = a["score"] + BATTLE_SCORE_FLOOR, b["score"] + BATTLE_SCORE_FLOOR
    strong, weak = (a, b) if sa >= sb else (b, a)
    ratio = max(sa, sb) / min(sa, sb)
    if ratio >= GAP_VAST:
        tier = "vast"
    elif ratio >= GAP_LARGE:
        tier = "large"
    elif ratio >= GAP_NOTICEABLE:
        tier = "noticeable"
    else:
        tier = None
    return tier, strong, weak, ratio


def fight(a, b, id_a, id_b):
    """Decides the duel. Same two SteamIDs, same winner, whichever order they are given in."""
    p_a = battle_odds(a, b)
    a_is_first = int(id_a) <= int(id_b)
    favorite_is_a = p_a > 0.5 or (p_a == 0.5 and a_is_first)
    if BATTLE_UPSETS:
        lo, hi = sorted((int(id_a), int(id_b)))
        roll = random.Random(f"battle-{lo}-{hi}").random()
        p_first = p_a if a_is_first else 1 - p_a
        a_wins = (roll < p_first) == a_is_first
    else:
        a_wins = favorite_is_a
    p_winner = p_a if a_wins else 1 - p_a
    return {"p_a": p_a, "p_b": 1 - p_a, "even": abs(p_a - 0.5) < 1e-9,
            "winner": a if a_wins else b, "loser": b if a_wins else a,
            "favorite": a if favorite_is_a else b, "p_winner": p_winner,
            "upset": p_winner < 0.5,
            "p_power_a": power_odds(a, b), "element_edge_a": element_edge(a["element"], b["element"])}


def battle_class(p_winner):
    if p_winner < 0.5:
        return "upset"
    if p_winner < 0.65:
        return "close"
    if p_winner < 0.85:
        return "clear"
    return "crushing"


def realm_gap_text(w, l):
    d = w["realm_index"] - l["realm_index"]
    if d > 0:
        return f" {w['name']}'s {w['realm']} cultivation towered over {l['name']}'s {l['realm']}."
    if d < 0:
        return (f" On paper, {l['name']}'s {l['realm']} cultivation should have crushed "
                f"{w['name']}'s {w['realm']}.")
    return ""


def battle_story(a, b, result):
    """A short story of the duel. The winner is fixed by fight(); the telling is random,
    so asking again gives the same result told in a different way."""
    x, y = a, b
    if a["path"]["name"] == "Demonic" and b["path"]["name"] == "Righteous":
        x, y = b, a                      # in a mixed pair, {x} is always the Righteous one
    w, l = result["winner"], result["loser"]
    tier, strong, weak, _ = power_gap(a, b)
    edge = element_edge(a["element"], b["element"])
    adv, dis = (a, b) if edge > 0 else (b, a)            # only used when edge != 0
    big_gap = tier in ("large", "vast")
    fmt = dict(
        x=x["name"], y=y["name"], x_sect=x["sect"], y_sect=y["sect"],
        x_tech=x["technique"], y_tech=y["technique"], x_elem=x["element"], y_elem=y["element"],
        w=w["name"], l=l["name"], w_tech=w["technique"], l_tech=l["technique"],
        w_sect=w["sect"], l_sect=l["sect"], w_treasure=w["treasure"], l_treasure=l["treasure"],
        place=random.choice(BATTLE_PLACES),
        # a big power gap already gets its own lines, so the realm comparison is skipped then
        gap="" if big_gap else realm_gap_text(w, l),
        strong=strong["name"], weak=weak["name"],
        strong_power=f"{strong['score']:,.0f}", weak_power=f"{weak['score']:,.0f}",
        adv=adv["name"], dis=dis["name"], adv_elem=adv["element"], dis_elem=dis["element"])
    parts = [random.choice(BATTLE_OPENINGS[(x["path"]["name"], y["path"]["name"])])]
    if tier:                                             # the stronger fighter shows off
        parts.append(random.choice(BATTLE_GAP_SETUPS[tier]))
    parts.append(random.choice(BATTLE_CLASHES))
    if edge:                                             # one element has the upper hand
        parts.append(random.choice(BATTLE_ELEMENT_LINES))
    parts.append(random.choice(BATTLE_TURNS[battle_class(result["p_winner"])]))
    parts.append(random.choice(BATTLE_ENDINGS[(w["path"]["name"], l["path"]["name"])]))
    if big_gap:                                          # arrogance paid off, or did not
        parts.append(random.choice(BATTLE_GAP_AFTERMATH[(tier, w is strong)]))
    text = " ".join(p.format(**fmt) for p in parts)
    if w["personalities"]:
        text += f" As ever, {w['name']} {random.choice(w['personalities'])['trait']}."
    return text


def print_battle(a, b, info_a, info_b, result, story):
    line = "=" * 64
    print("\n" + line)
    print("  MOCB  -  Clash of Cultivators")
    print(line)
    for tag, c, info, p in (("A", a, info_a, result["p_a"]), ("B", b, info_b, result["p_b"])):
        print(f"  [{tag}] {c['name']}  of the {c['sect']}")
        print(f"      Steam name : {info['name']}")
        print(f"      Realm      : {c['realm']}")
        print(f"      Power      : {c['score']:,.0f}")
        print(f"      Talent     : {c['talent']['name']}")
        print(f"      Path       : {c['path']['name']}")
        print(f"      Affinity   : {c['element']}")
        print(f"      Technique  : {c['technique']}")
        print(f"      Win chance : {p * 100:.1f}%")
        print()
    edge = element_edge(a["element"], b["element"])
    if edge:
        adv, dis = (a, b) if edge > 0 else (b, a)
        p_power_adv = result["p_power_a"] if adv is a else 1 - result["p_power_a"]
        wrap_print(f"Elements   : {adv['element']} is strong against {dis['element']}, so "
                   f"{adv['name']} gets +{AFFINITY_BONUS * 100:g}% win chance "
                   f"(power alone: {p_power_adv * 100:.1f}%)")
    elif a["element"] == b["element"]:
        wrap_print(f"Elements   : both are {a['element']}, so neither has the advantage")
    else:
        wrap_print(f"Elements   : {a['element']} and {b['element']} are neutral against each other")
    tier, strong, weak, ratio = power_gap(a, b)
    if tier:
        wrap_print(f"Power gap  : {tier} ({strong['score']:,.0f} vs {weak['score']:,.0f}), "
                   f"{strong['name']} is far ahead and knows it" if tier != "noticeable" else
                   f"Power gap  : noticeable ({strong['score']:,.0f} vs {weak['score']:,.0f}), "
                   f"{strong['name']} has the edge")
    if result["even"]:
        wrap_print("Prediction : a perfectly even match, too close to call")
    else:
        fav = result["favorite"]
        p_fav = result["p_a"] if fav is a else result["p_b"]
        wrap_print(f"Prediction : {fav['name']} is most likely to win ({p_fav * 100:.1f}%)")
    print(line)
    print()
    wrap_print(story)
    print()
    winner = result["winner"]
    if result["upset"]:
        wrap_print(f"Result : UPSET! {winner['name']} beat the odds "
                   f"({result['p_winner'] * 100:.1f}% chance) and wins the duel.")
    else:
        wrap_print(f"Result : {winner['name']} wins the duel.")
    print(line + "\n")


def get_info(steamid, key, profiles, refresh=False):
    """Steam data for a profile. A repeat lookup in the same run comes from memory."""
    if refresh or steamid not in profiles:
        profiles[steamid] = fetch_profile(steamid, key, refresh)
    return profiles[steamid]


def build_cultivator(steamid, key, profiles, refresh=False):
    """Returns (info, friend_ids, friends_note, cultivator) for one profile."""
    info = get_info(steamid, key, profiles, refresh)
    friend_ids, note = get_friend_ids(steamid, key)
    cultivator = generate_cultivator(info, steamid, friend_ids)
    RUN_LOG.note(f"friends: {len(friend_ids)}{' (' + note + ')' if note else ''}; cultivator "
                 f"{cultivator['name']}, {cultivator['realm']}, age {cultivator['age']}, "
                 f"{'died' if cultivator['death'] else 'alive'}")
    return info, friend_ids, note, cultivator


def run_battle(args, key, profiles):
    """The "mocb" command. Profiles come from the command line ('mocb <p1> <p2>') or are
    asked for one by one; a blank answer cancels."""
    ids = []
    for n, ordinal in enumerate(("First", "Second")):
        if n < len(args):
            text = args[n]
        else:
            text = input(f"  {ordinal} profile (URL, name or SteamID64, blank to cancel): ").strip()
        if not text:
            print("  Duel cancelled.\n")
            return
        ids.append(resolve_steamid(text, key))
    if ids[0] == ids[1]:
        raise SteamError("Pick two different profiles: a cultivator cannot duel themselves.")
    (info_a, _, _, a), (info_b, _, _, b) = [build_cultivator(i, key, profiles) for i in ids]
    result = fight(a, b, ids[0], ids[1])
    print_battle(a, b, info_a, info_b, result, battle_story(a, b, result))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    key = os.environ.get("STEAM_API_KEY") or input("Steam API key: ").strip()
    if not key:
        sys.exit("An API key is required (https://steamcommunity.com/dev/apikey).")

    print("Welcome, seeker of the Dao. Press Ctrl+C to leave.")
    print("Tip: type 'mocb' to make two profiles duel (or 'mocb <profile1> <profile2>').")
    print("Tip: type 'refresh <profile>' to ignore the saved achievement cache.\n")
    refresh_first = "--refresh" in sys.argv[1:]   # refresh each profile's first lookup this run
    profiles = {}
    RUN_LOG.secret = key
    while True:
        try:
            text = input("Steam profile URL, custom name, or SteamID64: ").strip()
            if not text:
                continue
            RUN_LOG.begin(describe_command(text))
            status = "ok"
            try:
                run_command(text, key, profiles, refresh_first)
            except SteamError as e:
                status = f"error: {e}"
                print(f"\n  ! {e}\n")
            except BaseException as e:           # Ctrl+C or end of input in the middle of a command
                RUN_LOG.finish("interrupted" if isinstance(e, (KeyboardInterrupt, EOFError))
                               else f"crashed: {type(e).__name__}: {e}")
                raise
            RUN_LOG.finish(status)
        except (KeyboardInterrupt, EOFError):
            print("\nMay your Dao be eternal. Farewell.")
            break
    RUN_LOG.end_session()


def describe_command(text):
    """What the log says was run, e.g. 'mocb a b', 'refresh lookup of x' or 'lookup of x'."""
    parts = text.split()
    if parts[0].lower() == "mocb":
        return "mocb " + " ".join(parts[1:])
    if text.lower().startswith("refresh "):
        return f"refresh lookup of {text[len('refresh '):].strip()}"
    return f"lookup of {text}"


def run_command(text, key, profiles, refresh_first):
    """One line typed by the user: a lookup, a 'refresh <profile>' lookup, or 'mocb'."""
    parts = text.split()
    if parts[0].lower() == "mocb":
        if len(parts) > 3:
            raise SteamError("mocb takes two profiles, for example: mocb <profile1> <profile2>")
        run_battle(parts[1:], key, profiles)
        return
    refresh = False
    if text.lower().startswith("refresh "):
        refresh, text = True, text[len("refresh "):].strip()
    if not text:
        return
    steamid = resolve_steamid(text, key)
    if refresh_first and steamid not in profiles:
        refresh = True
    info, friend_ids, note, cultivator = build_cultivator(steamid, key, profiles, refresh)
    friend = resolve_friend(cultivator, friend_ids, key)
    print_cultivator(cultivator, info)
    if friend:
        print_story(generate_story(cultivator, info, friend), friend)
    elif note:
        print(f"  ({note})\n")
    if cultivator["death"]:
        print_death(cultivator, info, friend)


if __name__ == "__main__":
    main()
