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
a time, so the first lookup of a big library takes a little while.

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

import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

API = "https://api.steampowered.com"
TIMEOUT = 15

BETRAYAL_CHANCE = 0.05   # of those who die, chance the killer is one of their friends
SECT_POINTS_PER_MISSION = 5   # 1 unlocked achievement = 1 sect mission = 5 sect points
ACHIEVEMENT_WORKERS = 8       # how many games are asked about at the same time

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
]

STORIES_WEAK = [
    "{me}, whose cultivation had only reached {realm}, was cornered by a demonic beast until "
    "{friend} burst in wielding nothing but a cooking pot. The beast fled in confusion. "
    "Neither of them speaks of it.",

    "Both {me} and {friend} were too poor to afford a single spirit stone, so they pooled their "
    "savings for one steamed bun and shared it under a tree, swearing that one day they would "
    "rule the heavens. The bun was delicious.",
]

STORIES_STRONG = [
    "{me}, whose cultivation had reached {realm}, crossed nine provinces in a single breath "
    "just to rescue {friend} from a terrible blind date arranged by the {sect}.",

    "At the Great Ascension Banquet, every elder bowed to {me}. Only {friend} dared to say, "
    "'You still owe me a spirit stone.' {me} paid up immediately.",
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

# Placeholders: {steam} {name} {sect} {a_title} {talent} {dao} {meditation} {treasury}
# {missions} {treasure} {element} {technique} {game} {realm}. Add your own!
BACKSTORIES = [
    "Once known on Steam as '{steam}', {name} joined the {sect} as {a_title}. Their talent "
    "test revealed {talent}. {dao}. They {meditation}, and {treasury}. Within the sect, they "
    "{missions}. Their prized possession was {treasure}.",

    "The mortal world knew {name} only as '{steam}', a stubborn wanderer who {meditation}. "
    "Eventually the {sect} accepted them as {a_title}, and the talent stone revealed {talent}. "
    "{dao}. Over the years they {missions}, and {treasury}. At their belt always hung {treasure}.",

    "Elders of the {sect} still argue about {name}, {a_title} who once went by '{steam}' in "
    "the mortal realm. The talent test showed {talent}. {dao}. Mission hall records say {name} "
    "{missions}, and the vault ledger says they {treasury}. {name} {meditation}. Their prized "
    "possession was {treasure}.",

    "Some say '{steam}' was just a name {name} borrowed in the mortal realm. Whatever the truth, "
    "the {sect} took them in as {a_title}, and the elders at the talent test uncovered {talent}. "
    "{dao}. {name} {meditation}, then {missions}. Along the way they {treasury}. Their most "
    "precious belonging was {treasure}.",

    "{name}, formerly '{steam}' in the mortal realm, served the {sect} as {a_title}. The talent "
    "test showed {talent}. {dao}. In their time, {name} {missions}, and {treasury}. They also "
    "{meditation}. Of all their belongings, {treasure} was the dearest.",

    "Nobody in the {sect} could say where {name} came from, only that the mortal records listed "
    "them as '{steam}'. They joined as {a_title}, and the talent test revealed {talent}. {dao}. "
    "Legend says {name} {meditation}, and that they {missions}. They {treasury}. Their prized "
    "possession was {treasure}.",

    "{name} came to the {sect} as {a_title}, carrying nothing but the mortal name '{steam}' and "
    "an affinity for {element}. The talent test revealed {talent}. {dao}. {name} {meditation}. "
    "The {technique} became their signature art. Over time they {missions}, and {treasury}. "
    "Their prized possession was {treasure}.",
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


def api_get(path, key, **params):
    params["key"] = key
    try:
        r = requests.get(f"{API}/{path}", params=params, timeout=TIMEOUT)
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


def fetch_profile(steamid, key):
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
    achievements, achievements_hidden = count_achievements(steamid, key, games)
    return {
        "name": player.get("personaname", "Unknown"),
        "level": level_resp.get("player_level", 0),
        "game_count": paid_resp.get("game_count", 0),
        "top_game": top.get("name", "Unknown Game") if top else None,
        "top_hours": (top.get("playtime_forever", 0) / 60) if top else 0.0,
        "total_hours": sum(g.get("playtime_forever", 0) for g in games) / 60,
        "achievements": achievements,
        "achievements_hidden": achievements_hidden,
    }


def achievements_for_game(appid, steamid, key):
    """Unlocked achievements for one game, or None if Steam refuses to show them."""
    for attempt in range(3):
        try:
            r = requests.get(f"{API}/ISteamUserStats/GetPlayerAchievements/v1/",
                             params={"key": key, "steamid": steamid, "appid": appid},
                             timeout=TIMEOUT)
        except requests.RequestException:
            time.sleep(1 + attempt)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(1 + attempt)          # Steam wants us to slow down; try again
            continue
        if r.status_code == 403:
            return None                      # achievements are private
        if r.status_code != 200:
            return 0                         # 400: this game has no achievements
        try:
            stats = r.json().get("playerstats", {})
        except ValueError:
            return 0
        return sum(1 for a in stats.get("achievements", []) if a.get("achieved") == 1)
    return 0


def count_achievements(steamid, key, games):
    """Total unlocked achievements over every game you have played (free ones too).
    Steam has no single call for this, so it asks once per game, several at a time.
    Returns (count, hidden); hidden is True when Steam refused every single request."""
    appids = [g["appid"] for g in games if g.get("playtime_forever", 0) > 0]
    if not appids:
        return 0, False

    total = blocked = done = 0
    pool = ThreadPoolExecutor(max_workers=ACHIEVEMENT_WORKERS)
    try:
        futures = [pool.submit(achievements_for_game, a, steamid, key) for a in appids]
        for f in as_completed(futures):
            result = f.result()
            if result is None:
                blocked += 1
            else:
                total += result
            done += 1
            print(f"\r  Counting achievements... {done}/{len(appids)} games", end="", flush=True)
    except BaseException:
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:                    # Python older than 3.9
            pool.shutdown(wait=False)
        print()
        raise
    pool.shutdown()
    print("\r" + " " * 48 + "\r", end="", flush=True)
    return total, blocked == len(appids)


def get_friend_ids(steamid, key):
    """Returns (friend_ids, note). The list is empty when there are no friends or the
    friends list can't be read; note is a short explanation worth showing, or None."""
    try:
        r = requests.get(f"{API}/ISteamUser/GetFriendList/v1/",
                         params={"key": key, "steamid": steamid, "relationship": "friend"},
                         timeout=TIMEOUT)
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


def roll_fate(steamid, realm_index, lifespan, friend_ids, death_chance):
    """Birth year and (maybe) death. The same SteamID always gives the same fate.
    Everything is drawn in a fixed order, so a result never shifts because
    something else (like the friends list) happened to change."""
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
        min_age = 18 + realm_index * 60          # a strong cultivator is not a teenager
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
    score = power_score(info, talent["power"])
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
    fate = roll_fate(steamid, idx, lifespan, friend_ids or [], talent["death"])

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

    article = "an" if title[0] in "AEIOU" else "a"
    backstory = rng.choice(BACKSTORIES).format(
        steam=info["name"], name=name, sect=sect, a_title=f"{article} {title}",
        talent=talent["blurb"], dao=dao, meditation=meditation, treasury=treasury,
        missions=mission_text, treasure=treasure, element=element, technique=technique,
        game=game, realm=realm)

    return {
        "name": name, "sect": sect, "title": title, "realm": realm, "realm_flavor": realm_flavor,
        "realm_index": idx, "element": element, "technique": technique, "lifespan": lifespan,
        "lightning": lightning, "treasure": treasure, "backstory": backstory, "score": score,
        "birth_year": fate["birth_year"], "death": fate["death"], "talent": talent,
        "missions": missions, "sect_points": sect_points,
    }


def power_bar(idx):
    total = len(REALMS)
    return "[" + "#" * (idx + 1) + "-" * (total - idx - 1) + f"] {idx + 1}/{total}"


def print_cultivator(c, info):
    line = "=" * 64
    print("\n" + line)
    print(f"  {c['name']}  -  {c['title']} of the {c['sect']}")
    print(line)
    print(f"  Realm       : {c['realm']} ({c['realm_flavor']})")
    print(f"  Power       : {power_bar(c['realm_index'])}   (score {c['score']:,.0f})")
    t = c["talent"]
    print(f"  Talent      : {t['name']} (power {t['power']:+d}, death risk {t['death'] * 100:g}%)")
    print(f"  Affinity    : {c['element']}")
    print(f"  Signature   : {c['technique']}")
    print(f"  Treasure    : {c['treasure']}")
    if info["achievements_hidden"]:
        print("  Missions    : 0 (Steam is hiding your achievements)")
    else:
        n = c["missions"]
        print(f"  Missions    : {n:,} sect mission{'' if n == 1 else 's'} completed")
    print(f"  Sect points : {c['sect_points']:,}")
    cut = " (cut short)" if c["death"] else ""
    print(f"  Lifespan    : {c['lifespan']:,} years{cut}")
    print(f"  Born        : Year {c['birth_year']} of the Heavenly Calendar")
    if c["death"]:
        print(f"  Died        : Year {c['death']['year']} of the Heavenly Calendar "
              f"(aged {c['death']['age']:,})")
    else:
        print("  Status      : Alive and cultivating")
    if c["lightning"]:
        print(f"  Tribulations: survived {c['lightning']} heavenly lightning strikes")
    print(line)
    print("  Source stats from Steam:")
    print(f"    Steam level : {info['level']}")
    print(f"    Paid games  : {info['game_count']:,}")
    print(f"    Achievements: {info['achievements']:,}")
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
# Main
# ---------------------------------------------------------------------------
def main():
    key = os.environ.get("STEAM_API_KEY") or input("Steam API key: ").strip()
    if not key:
        sys.exit("An API key is required (https://steamcommunity.com/dev/apikey).")

    print("Welcome, seeker of the Dao. Press Ctrl+C to leave.\n")
    profiles = {}
    while True:
        try:
            text = input("Steam profile URL, custom name, or SteamID64: ").strip()
            if not text:
                continue
            steamid = resolve_steamid(text, key)
            if steamid not in profiles:          # looking up the same profile again is instant
                profiles[steamid] = fetch_profile(steamid, key)
            info = profiles[steamid]
            friend_ids, note = get_friend_ids(steamid, key)
            cultivator = generate_cultivator(info, steamid, friend_ids)
            friend = resolve_friend(cultivator, friend_ids, key)
            print_cultivator(cultivator, info)
            if friend:
                print_story(generate_story(cultivator, info, friend), friend)
            elif note:
                print(f"  ({note})\n")
            if cultivator["death"]:
                print_death(cultivator, info, friend)
        except SteamError as e:
            print(f"\n  ! {e}\n")
        except (KeyboardInterrupt, EOFError):
            print("\nMay your Dao be eternal. Farewell.")
            break


if __name__ == "__main__":
    main()
