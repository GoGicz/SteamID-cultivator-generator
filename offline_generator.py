"""Seeded offline creation, developer templates and local save compatibility."""

import copy
import random
import time

import gamedata
import logs
import storage
from pathlib import Path
import secrets
import unicodedata

def normalize_local_name(text):
    return unicodedata.normalize("NFKC", text).strip().casefold()


def random_local_settings(*, player_start=False, rng=None, seed=None, native=False, sect_names=None):
    """Developer rolls span all realms; player starts use bounded beginner rolls."""
    from generator import make_name
    rng = rng or random.Random(secrets.randbits(128))
    sid = str(seed) if seed is not None else str(rng.randrange(10**19,10**20))
    native=player_start or native
    rng=random.Random(('local-v1:' if native else 'editor-v1:')+sid)
    realm = rng.randrange(2 if player_start else len(gamedata.REALMS))
    gender = rng.choice(("male", "female"))
    lifespan = rng.randint(*gamedata.REALM_LIFESPANS[realm])
    sects=sect_names or [row["name"] for row in storage.sect_names()]
    settings = {
        "name": make_name(rng, gender), "gender": gender,
        "sect": rng.choice(sects),
        "element": rng.choice(gamedata.ELEMENTS),
        "talent": rng.choices(gamedata.TALENTS, weights=[t["weight"] for t in gamedata.TALENTS], k=1)[0]["name"],
        "path": rng.choice(gamedata.PATHS)["name"],
        "score": rng.randint(*realm_power_range(realm)),
        "realm_index": realm, "born_realm": realm,
        "age": rng.randint(16, max(16, lifespan // 2)), "birth_year": rng.randint(1000, 9000),
        "lifespan": lifespan, "death_chance": 0.08,
        "title": "", "technique": "", "personalities": rng.sample([p["name"] for p in gamedata.PERSONALITIES if not p.get("steam_only")], rng.randrange(4)),
        "missions": 0 if player_start else rng.randint(0, 5000),
        "sect_points": rng.randint(0, 600 if player_start else 30000), "spirit_stones": 0,
        "reputation": rng.randint(0, 50 if player_start else 3000),
        "level": 0 if native else rng.randint(0, 200), "game_count": 0 if native else rng.randint(1, 1000),
        "top_game": "Dao Meditation", "top_hours": 0 if native else rng.randint(0, 10000),
        "badges": 0 if native else rng.randint(0, 300), "seed": sid,
    }
    if native:
        settings.update(generation='seed-v1',starting_reputation=settings['reputation'])
    return settings


def validate_local_settings(s):
    if not isinstance(s, dict):
        raise ValueError("Settings must be a JSON object.")
    if type(s.get("spirit_stones", 0)) is not int or s.get("spirit_stones", 0) < 0:
        raise ValueError("Spirit Stones must be a nonnegative whole number.")
    if "starting_reputation" in s and (type(s["starting_reputation"]) is not int or not 0<=s["starting_reputation"]<=10**9):
        raise ValueError("Starting reputation must be a nonnegative whole number.")
    if "power_offset" in s and (type(s["power_offset"]) is not int or abs(s["power_offset"]) > 10**9):
        raise ValueError("Power adjustment must be a whole number between -1,000,000,000 and 1,000,000,000.")
    required = {"name", "gender", "sect", "element", "talent", "path", "score", "realm_index", "born_realm", "age", "birth_year", "lifespan", "death_chance", "title", "technique", "personalities", "missions", "sect_points", "reputation", "level", "game_count", "top_game", "top_hours", "badges", "seed"}
    if required - s.keys():
        raise ValueError("Missing settings: " + ", ".join(sorted(required - s.keys())))
    for field in ("name", "sect", "top_game", "title", "technique"):
        value = s[field]
        if not isinstance(value, str) or len(value) > 300 or (field in ("name", "sect", "top_game") and not value.strip()):
            raise ValueError(f"{field} must be text (1–300 characters; title/technique can be blank).")
        if any(ord(c) < 32 for c in value):
            raise ValueError(f"{field} cannot contain control characters.")
    if not isinstance(s["seed"], str) or not s["seed"].isascii() or not s["seed"].isdigit() or len(s["seed"]) != 20:
        raise ValueError("Seed must be a 20-digit local identifier.")
    for field, options in (("gender", ("male", "female")), ("element", gamedata.ELEMENTS), ("talent", gamedata.TALENT_BY_NAME), ("path", [p["name"] for p in gamedata.PATHS])):
        if s[field] not in options:
            raise ValueError(f"Invalid {field}.")
    for field in ("score", "realm_index", "born_realm", "age", "birth_year", "lifespan", "missions", "sect_points", "reputation", "level", "game_count", "top_hours", "badges"):
        if type(s[field]) is not int or not (-10**9 if field == "birth_year" else 0) <= s[field] <= 10**9:
            raise ValueError(f"{field} must be a whole number between 0 and 1,000,000,000.")
    if not 0 <= s["realm_index"] < len(gamedata.REALMS) or not 0 <= s["born_realm"] < len(gamedata.REALMS):
        raise ValueError("Realm indexes are out of range.")
    if not 0 <= s["age"] < s["lifespan"]:
        raise ValueError("Age must be smaller than lifespan for a new living character.")
    if type(s["death_chance"]) not in (int, float) or not 0 <= s["death_chance"] <= 1:
        raise ValueError("Death risk must be between 0 and 1.")
    if not isinstance(s["personalities"], list) or any(p not in [v["name"] for v in gamedata.PERSONALITIES] for p in s["personalities"]) or len(set(s["personalities"])) != len(s["personalities"]):
        raise ValueError("Personalities must be a list of unique personality names from the game.")


def realm_power_range(realm_index):
    """Inclusive creation range; Immortal has no gameplay cap, so draws stop at 15,000."""
    low = gamedata.REALMS[realm_index][0]
    high = gamedata.REALMS[realm_index + 1][0] - 1 if realm_index + 1 < len(gamedata.REALMS) else 15000
    return low, high


def local_power_base(s, talent_name=None):
    """Same contributors as Steam power; local scores are rounded to whole points."""
    bonus = gamedata.TALENT_BY_NAME[talent_name or s["talent"]]["power"]
    bonus += next(p["power"] for p in gamedata.PATHS if p["name"] == s["path"])
    bonus += sum(p["power"] for p in gamedata.PERSONALITIES if not p.get("steam_only") and p["name"] in s["personalities"])
    return round(s["level"] * 10 + s["game_count"] * 2 + s["top_hours"] / 10 + bonus)


def local_power_score(s, talent_name=None):
    if s.get("generation")=="seed-v1":return s["score"]
    # Old saves keep their exact score until edited with the reactive controls.
    return max(0, local_power_base(s, talent_name) + s["power_offset"]) if "power_offset" in s else s["score"]


def local_profile_info(s):
    return {"name": s["name"], "account_created": None,
            "local_seed": s["seed"] if s.get("generation")=="seed-v1" else None,
            "level": s["level"], "game_count": s["game_count"],
            "top_game": s["top_game"], "top_hours": s["top_hours"], "total_hours": s["top_hours"],
            "achievements": s["missions"], "achievements_hidden": False, "achievements_new": None,
            "ach_stats": None, "badges": s["badges"], "badges_hidden": False, "offline": True}


def make_local_profile(settings):
    from generator import generate_cultivator
    s = copy.deepcopy(settings)
    for key in ("name", "sect", "title", "technique", "top_game"):
        if isinstance(s.get(key), str):
            s[key] = s[key].strip()
    validate_local_settings(s)
    s["starting_reputation"]=s["reputation"]
    sid = s["seed"]
    info = local_profile_info(s)
    c = generate_cultivator(info, sid, [], realm_index=s["realm_index"], born_realm=s["born_realm"], overrides=s)
    earned = s["missions"] * gamedata.SECT_POINTS_PER_MISSION
    return {"version": 1, "steamid": sid, "sections": {},
            "wallet": {"spirit_stones": s.get("spirit_stones", 0)},
            "offline": {"version": 1, "info": info, "character": s},
            "realm_state": {"realm_index": s["realm_index"], "born_realm": s["born_realm"], "lifespan_lost": 0, "last_failed": None},
            "life": {"dead": None, "last_roll": None, "incarnation": None, "rebirths": 0},
            "inventory": {"treasures": c["treasures"], "history": []},
            "pavilion": {"items": {}, "spent": 0, "earned": earned, "bonus": s["sect_points"] - earned, "history": []},
            "duel_reputation": {"points": 0, "history": []},
            "activity": [{"at": time.time(), "type": "adventure", "summary": "Created locally with the developer profile generator."}]}


def load_local_profile(steamid):
    local = storage.profile_field(steamid,"offline")
    if local is None:
        return None
    try:
        if not isinstance(local, dict) or local.get("version") != 1:
            raise ValueError("Unsupported local profile version.")
        validate_local_settings(local["character"])
        if local["character"]["seed"] != str(steamid):
            raise ValueError("Local seed does not match profile ID.")
        if not isinstance(local["info"], dict):
            raise ValueError("Local inputs must be an object.")
    except (ValueError, KeyError, TypeError) as exc:
        raise logs.SteamError(f"Invalid local profile {steamid}: {exc}")
    local["info"] = local_profile_info(local["character"])
    return local


def resolve_local_profile(text):
    """Exact normalized name, local:<name>, local:<ID>, or numeric ID. Never contacts Steam."""
    text = str(text).strip()
    explicit = text.lower().startswith("local:")
    if explicit:
        text = text[6:].strip()
    if text.isascii() and text.isdigit():
        # A picker already knows the ID; don't open every profile to resolve it.
        data = storage.load_profile_cache(text)
        if (data and data.get("steamid") == text and isinstance(data.get("offline"), dict)):
            return text
        if explicit:
            raise logs.SteamError("No local profile with that ID exists in this game's cache.")
        return None
    matches = []
    for data in storage.all_profiles():
        if not isinstance(data.get("offline"), dict):
            continue
        sid = data["steamid"]
        character = data["offline"].get("character")
        names = [character.get("name", "")] if isinstance(character, dict) else []
        life = data.get("life")
        incarnation = life.get("incarnation") if isinstance(life, dict) else None
        if isinstance(incarnation, dict):
            names.append(incarnation.get("name", ""))
        if text == sid or any(normalize_local_name(text) == normalize_local_name(n) for n in names if isinstance(n, str) and n):
            matches.append(sid)
    if len(matches) > 1:
        raise logs.SteamError("Several local profiles have that name. Use local:<ID> instead.")
    if matches:
        return matches[0]
    if explicit:
        raise logs.SteamError("No local profile with that name or ID exists in this game's cache.")
    return None


def create_local_profile(cache, data):
    """Create only; existing files and duplicate local names are never replaced."""
    sid = data.get("steamid", "")
    storage.validate_profile_data(data, sid)
    local = data.get("offline", {})
    validate_local_settings(local.get("character"))
    if sid != local["character"]["seed"]:
        raise ValueError("Profile ID must equal its local seed.")
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    name = normalize_local_name(local["character"]["name"])
    with storage.world_transaction(cache) as db:
        for saved in storage.all_profiles(cache):
            offline = saved.get("offline")
            character = offline.get("character") if isinstance(offline, dict) else None
            names = [character.get("name", "")] if isinstance(character, dict) else []
            life = saved.get("life")
            incarnation = life.get("incarnation") if isinstance(life, dict) else None
            if isinstance(incarnation, dict):
                names.append(incarnation.get("name", ""))
            if any(isinstance(n, str) and n and normalize_local_name(n) == name for n in names):
                raise ValueError("That local name is already in use. Choose a different name.")
        if db.execute('SELECT 1 FROM profiles WHERE id=?',(sid,)).fetchone():
            raise FileExistsError('This profile ID already exists.')
        data=copy.deepcopy(data)
        world=db.execute('SELECT day FROM world WHERE id=1').fetchone()
        day=world[0]
        char=data['offline']['character']
        data['calendar']={'birth_day':day-char['age']*storage.DAYS_PER_YEAR,'incarnation':0,
                          'synchronized_day':day,'base_lifespan':char['lifespan']}
        for event in data.get('activity',[]): event['world_day']=day
        storage._write_profile(db,data)
        choice=storage.chartered_sect(char['sect'],cache)
        if choice:
            db.execute('INSERT OR IGNORE INTO affiliations(actor,sect_id) VALUES(?,?)',(sid,choice['id']))
            home=storage.seat_location(db,choice['id'])
            if home:db.execute('INSERT OR IGNORE INTO positions VALUES(?,?)',(sid,home[0]))
        return cache / f"{sid}.profile.json"  # logical editor locator, no JSON is written
