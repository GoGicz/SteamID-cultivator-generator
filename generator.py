"""The cultivator generator: turns Steam data into a deterministic, SteamID-seeded cultivator
(build_cultivator), plus the rules for fate, death,
lifespan, arsenal and treasures."""

import random
import time

import gamedata
import gametext
import logs
import steam_api
import steam_profile
import storage


BETRAYAL_CHANCE = 0.05   # of those who die, chance the killer is one of their friends

# A Steam account of ACCOUNT_YEARS_FOR_MAX_AGE years or more gives the oldest possible
# cultivator; a brand-new account gives the youngest. In between it scales evenly.
ACCOUNT_YEARS_FOR_MAX_AGE = 20
SECONDS_PER_YEAR = 365.25 * 24 * 3600


def treasure_rank(item):
    """0 for a low treasure, 1 for a middle one, 2 for a high one."""
    if item in gamedata.PAVILION_TREASURE_RANKS:
        return gamedata.PAVILION_TREASURE_RANKS[item]
    for rank in (2, 1, 0):
        if item in gamedata.ALL_TREASURES[rank]:
            return rank
    return 0


def prized_treasure(items):
    """The best treasure in a list (the earliest one among equals), or None if it is empty.
    It is the treasure the stories talk about, and the one a Demonic winner steals."""
    best = None
    for item in items:
        if best is None or treasure_rank(item) > treasure_rank(best):
            best = item
    return best


def treasures_of(c):
    """What a cultivator owns, as a list (older cultivator dicts only have one 'treasure')."""
    return list(c["treasures"]) if "treasures" in c else [c["treasure"]]


def describe_treasures(items):
    """'a jade slip, a tripod furnace (x2)': duplicates are counted instead of repeated."""
    counts = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return ", ".join(f"{k} (x{v})" if v > 1 else k for k, v in counts.items())


def talisman_count(c):
    """How many Spatial Escape Talismans a cultivator holds."""
    return c.get("pavilion", {}).get("items", {}).get(gamedata.TALISMAN_ID, 0)


def describe_goods(items):
    """'Qi Gathering Pill (x2), Iron Spirit Sword' for the pavilion goods a cultivator owns."""
    parts = []
    for item in gamedata.PAVILION_ITEMS:
        n = items.get(item["id"], 0)
        if n and item["kind"] != "Treasure":
            parts.append(f"{item['name']} (x{n})" if n > 1 else item["name"])
    return ", ".join(parts)


def build_arsenal(seed, element, path_name):
    """Two attacks of the element, one of the path, one defense: the same seed always gives
    the same four moves. Uses its own random generator, so nothing else shifts."""
    rng = random.Random(f"arsenal-{seed}")
    return {"attacks": rng.sample(gamedata.ELEMENT_MOVES[element], 2),
            "path_attack": rng.choice(gamedata.PATH_MOVES.get(path_name, gamedata.PATH_MOVES["Righteous"])),
            "defense": rng.choice(gamedata.DEFENSE_MOVES)}


def arsenal_of(c):
    """A cultivator's arsenal (built on the fly for a cultivator that has none yet)."""
    return c.get("arsenal") or build_arsenal(c["name"], c["element"], c["path"]["name"])


def arsenal_text(c):
    a = arsenal_of(c)
    return ", ".join(a["attacks"] + [a["path_attack"], a["defense"]])


def pick_variant(value, tiers, rng, **fmt):
    for limit, variants in tiers:
        if value < limit:
            return rng.choice(variants).format(**fmt)


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
    return rng.choices(gamedata.TALENTS, weights=[t["weight"] for t in gamedata.TALENTS], k=1)[0]


def roll_path(steamid):
    """Righteous or Demonic, by luck only. The same SteamID always walks the same path."""
    rng = random.Random(f"path-{steamid}")
    return gamedata.PATHS[0] if rng.random() < gamedata.RIGHTEOUS_CHANCE else gamedata.PATHS[1]


def path_label(path):
    effects = []
    if path["power"]:
        effects.append(f"+{path['power']} power")
    if path["rep"]:
        effects.append(f"+{path['rep']} reputation")
    return path["name"] + (f" ({', '.join(effects)})" if effects else "")


def get_personalities(info, friend_count):
    """Every personality this profile qualifies for, in table order."""
    return [p for p in gamedata.PERSONALITIES if p["test"](info, friend_count)]


def personality_phrase(personalities):
    traits = [p["trait"] for p in personalities] or [gamedata.NO_PERSONALITY_TRAIT]
    if len(traits) == 1:
        return traits[0]
    return ", ".join(traits[:-1]) + " and " + traits[-1]


def reputation_rank(points):
    idx = 0
    for i, (threshold, _) in enumerate(gamedata.REPUTATION_RANKS):
        if points >= threshold:
            idx = i
    return idx


def roll_reputation(steamid, info, personalities, path=None, duel_points=0):
    """Badges give the base reputation; personalities and the path add to it. A
    personality with a rep_chance below 1.0 rolls for its points; the roll comes from the
    SteamID, and every group in the table draws in a fixed order, so results never shift."""
    rng = random.Random(f"rep-{steamid}")
    groups = list(dict.fromkeys(p.get("roll_group", p["name"]) for p in gamedata.PERSONALITIES))
    rolls = {g: rng.random() for g in groups}
    badge_points = info["badges"] * gamedata.REP_PER_BADGE
    bonuses = [(p["name"], p["rep"]) for p in personalities
               if p["rep"] and rolls[p.get("roll_group", p["name"])] < p["rep_chance"]]
    if path and path["rep"]:
        bonuses.append((f"{path['name']} Path", path["rep"]))
    base_points = max(0, badge_points + sum(amount for _, amount in bonuses))
    if duel_points:                      # fame or shame won in duels (saved in the profile's file)
        bonuses.append(("Duels", duel_points))
    points = max(0, base_points + duel_points)
    idx = reputation_rank(points)
    return {"points": points, "badge_points": badge_points, "bonuses": bonuses,
            "base_points": base_points, "duel_points": duel_points,
            "rank_index": idx, "rank": gamedata.REPUTATION_RANKS[idx][1]}


def get_realm(score):
    idx = 0
    for i, (threshold, _, _) in enumerate(gamedata.REALMS):
        if score >= threshold:
            idx = i
    return idx, gamedata.REALMS[idx]


def roll_gender(steamid):
    """'male' or 'female', by luck from the SteamID only (own generator, so nothing else moves)."""
    return "male" if random.Random(f"gender-{steamid}").random() < 0.5 else "female"


def gender_title(title, gender):
    return gamedata.FEMALE_TITLES.get(title, title) if gender == "female" else title


def cultivator_name(steamid):
    """The name of the cultivator of this SteamID (a friend's name in a story is this too)."""
    if roll_gender(steamid) == "female":
        return make_name(random.Random(f"fname-{steamid}"), "female")
    return make_name(random.Random(int(steamid)))


def make_name(rng, gender="male"):
    given = gamedata.FEMALE_GIVEN if gender == "female" else gamedata.GIVEN
    return f"{rng.choice(gamedata.SURNAMES)} {rng.choice(given)}{rng.choice(given).lower()}"


def generate_story(c, info, friend):
    # The friend's cultivator name is seeded from their SteamID, so it stays the same;
    # the story itself is picked at random, so every run can give a new one.
    friend_name = cultivator_name(friend["steamid"])
    pool = list(gametext.STORIES_COMMON)
    if c["realm_index"] <= 3:
        pool += gametext.STORIES_WEAK
    elif c["realm_index"] >= 5:
        pool += gametext.STORIES_STRONG
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


IMMORTAL_INDEX = len(gamedata.REALMS) - 1
IMMORTAL_LIFESPAN = (60000, 90000)      # immortals are the pinnacle: ten times a Mahayana and more


def immortal_age(steamid, lifespan):
    """Age of an immortal: usually around half of the great lifespan (44-56%), but some are
    nearly at its end (85-97%) and some are young for an immortal (3-15%). By SteamID only."""
    r = random.Random(f"immortal-age-{steamid}")
    pick = r.random()
    if pick < 0.70:
        share = r.uniform(0.44, 0.56)
    elif pick < 0.85:
        share = r.uniform(0.85, 0.97)
    else:
        share = r.uniform(0.03, 0.15)
    return max(16, int(lifespan * share))


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
        friend_name = cultivator_name(friend["steamid"])
        fmt.update(friend=friend_name, friend_steam=friend["name"])
        pool = gametext.DEATH_FRIEND
        label = f"{friend_name} (Steam: {friend['name']}), a trusted friend"
    elif d["killer"] == "lifespan":
        pool, label = gametext.DEATH_LIFESPAN, "a failed breakthrough that used up their lifespan"
        return label, pool[sum(map(ord, c["name"])) % len(pool)].format(**fmt)
    elif d["killer"] == "rogue":
        pool, label = gametext.DEATH_ROGUE, rogue
    else:
        pool, label = gametext.DEATH_BANDITS, bandits
    return label, pool[d["scene"] % len(pool)].format(**fmt)


def generate_cultivator(info, steamid, friend_ids=None, inventory=None, duel_points=0,
                        pavilion=None, realm_index=None, lifespan_lost=0, born_realm=None,
                        incarnation=None):
    rng = random.Random(int(steamid))  # same profile -> same cultivator
    # A reborn cultivator (incarnation, saved in their file) has a new random body: new talent,
    # name, gender, sect, affinity and title. The realm, path, personalities and arsenal stay.
    talent = gamedata.TALENT_BY_NAME[incarnation["talent"]] if incarnation else roll_talent(steamid)
    personalities = get_personalities(info, len(friend_ids or []))   # second: same reason
    path = roll_path(steamid)          # third: the Demonic Path adds power
    score = power_score(info, talent["power"] + sum(p["power"] for p in personalities)
                        + path["power"])
    eligible, _ = get_realm(score)       # the highest realm the power score allows
    # The realm they actually hold is saved in their file and only rises through a breakthrough
    # (realm_index); with nothing saved yet they start in the realm their score gives.
    idx = eligible if realm_index is None else realm_index
    _, realm, realm_flavor = gamedata.REALMS[idx]

    tier_no = 0 if idx <= 2 else 1 if idx <= 6 else 2
    titles, treasures = (gamedata.TITLES_LOW, gamedata.TITLES_MID, gamedata.TITLES_HIGH)[tier_no], \
                        (gamedata.TREASURES_LOW, gamedata.TREASURES_MID, gamedata.TREASURES_HIGH)[tier_no]

    gender = roll_gender(steamid)
    name = make_name(rng)               # always drawn, so every later draw stays where it was...
    if gender == "female":              # ...and a woman's name then comes from her own generator
        name = cultivator_name(steamid)
    sect = f"{rng.choice(gamedata.SECT_ADJ)} {rng.choice(gamedata.SECT_NOUN)}"
    rng.choice(titles)                  # drawn exactly as before, so later draws do not move
    element = rng.choice(gamedata.ELEMENTS)
    rng.choice(treasures)               # (same here)
    title = gender_title(random.Random(f"title-{steamid}").choice(gamedata.TITLES_ALL[tier_no]), gender)
    if incarnation:
        gender, name, sect, element = (incarnation["gender"], incarnation["name"],
                                       incarnation["sect"], incarnation["element"])
        tier_titles = gamedata.TITLES_ALL[tier_no]
        title = gender_title(tier_titles[incarnation["title_roll"] % len(tier_titles)], gender)
    treasure = random.Random(f"treasure-{steamid}").choice(gamedata.ALL_TREASURES[tier_no])  # starting treasure
    owned = list(inventory) if inventory is not None else [treasure]   # what they own now
    main_treasure = prized_treasure(owned) or gamedata.FALLBACK_TREASURE

    game = info["top_game"] or "the Void"
    technique = f"{rng.choice(gamedata.MOVE_ADJ)} {game} {rng.choice(gamedata.MOVE_NOUN)}"

    lifespan_roll = rng.randint(150, 400)            # always drawn, as before
    if incarnation:
        lifespan_roll = incarnation["lifespan_roll"]
    if idx == IMMORTAL_INDEX:                         # immortals live far longer than anyone else
        base_lifespan = (incarnation["immortal_lifespan"] if incarnation else
                         random.Random(f"immortal-{steamid}").randint(*IMMORTAL_LIFESPAN))
    else:
        base_lifespan = 80 + idx * lifespan_roll
    if idx == IMMORTAL_INDEX:
        lifespan_lost = 0                             # ascending renews the body: the losses are gone
    lifespan = max(1, base_lifespan - lifespan_lost)  # years lost to failed breakthroughs
    lightning = max(0, idx - 5) * 3 + (9 if idx == 9 else 0)
    death_chance = min(1.0, talent["death"] + sum(p["death"] for p in personalities))
    years = account_years(info.get("account_created"))
    born_immortal = idx == IMMORTAL_INDEX and born_realm in (None, IMMORTAL_INDEX)
    if born_immortal:                        # generated as an immortal: a share of the great lifespan
        age = immortal_age(steamid, base_lifespan)
    elif idx == IMMORTAL_INDEX:              # ascended: keeps the age they had before (Steam account
        age = cultivator_age(years, 80 + (IMMORTAL_INDEX - 1) * lifespan_roll)   # age, as in the realm below)
    else:                                    # others: from the Steam account age (None if unknown)
        age = cultivator_age(years, base_lifespan)
    if incarnation:                          # a fresh young body, no fate written for it yet
        age = incarnation["age"]
        fate = {"birth_year": incarnation["birth_year"], "death": None}
    else:
        fate = roll_fate(steamid, idx, lifespan, friend_ids or [], death_chance, age)
    if age is not None and age >= lifespan:  # the years ran out (a failed breakthrough took them)
        fate["death"] = {"killer": "lifespan", "friend_id": None, "scene": 0, "age": lifespan,
                         "year": fate["birth_year"] + lifespan}
    age = fate["death"]["age"] if fate["death"] else age
    reputation = roll_reputation(steamid, info, personalities, path, duel_points)

    # Sect missions: every unlocked achievement counts, and each one pays sect points
    missions = info["achievements"]
    # Sect points are a ledger: what was ever credited minus what was spent. New achievements
    # add to the balance; a lower or missing count later (Steam hiding them, a failing game)
    # never takes credited points away, and spending is never "reset" by a new lookup.
    pavilion = pavilion or {"items": {}, "spent": 0, "earned": 0, "bonus": 0, "history": []}
    sect_points_earned = max(missions * gamedata.SECT_POINTS_PER_MISSION, pavilion.get("earned", 0))
    # "bonus" is sect points that came from somewhere else: treasures sold, a rebirth's new
    # fortune (it can be negative). What is left to spend = earned + bonus - spent.
    sect_points = max(0, sect_points_earned + pavilion.get("bonus", 0) - pavilion["spent"])

    # Backstory built from the real stats (variants and template picked from the SteamID)
    hrs, gc, lvl = info["top_hours"], info["game_count"], info["level"]
    nums = dict(hrs=f"{hrs:,.0f}", gc=f"{gc:,}", lvl=lvl, n=f"{missions:,}", game=game, sect=sect)
    meditation = pick_variant(hrs, gametext.MEDITATION_TIERS, rng, **nums)
    treasury = pick_variant(gc, gametext.TREASURY_TIERS, rng, **nums)
    dao = pick_variant(lvl, gametext.DAO_TIERS, rng, **nums)
    mission_text = pick_variant(missions, gametext.MISSION_TIERS, rng, **nums)

    # The reputation sentence uses its own generator so it never disturbs the picks above
    rep_text = pick_variant(reputation["rank_index"], gametext.REPUTATION_TIERS,
                            random.Random(f"repphrase-{steamid}"),
                            sect=sect, rank=reputation["rank"])

    article = "an" if title[0] in "AEIOU" else "a"
    backstory = rng.choice(gametext.BACKSTORIES).format(
        personality=personality_phrase(personalities), reputation=rep_text,
        steam=info["name"], name=name, sect=sect, a_title=f"{article} {title}",
        talent=talent["blurb"], dao=dao, meditation=meditation, treasury=treasury,
        missions=mission_text, treasure=main_treasure, element=element, technique=technique,
        game=game, realm=realm)

    if incarnation:
        backstory += (f" This is not {name}'s first life: after the old body died, the soul "
                      f"drifted through the Yellow Springs and woke in a new one "
                      f"(incarnation {incarnation['count']}), keeping only its Dao and its scars.")
    return {
        "incarnation": incarnation["count"] if incarnation else 0,
        "name": name, "gender": gender, "sect": sect, "title": title, "realm": realm, "realm_flavor": realm_flavor,
        "realm_index": idx, "eligible_realm_index": eligible, "element": element,
        "technique": technique, "lifespan": lifespan, "base_lifespan": base_lifespan,
        "lifespan_lost": lifespan_lost,
        "lightning": lightning, "treasure": main_treasure, "treasures": owned,
        "base_treasure": treasure, "inventory_history": [], "backstory": backstory, "score": score,
        "birth_year": fate["birth_year"], "death": fate["death"], "talent": talent,
        "age": age, "account_years": years,
        "arsenal": incarnation["arsenal"] if incarnation else build_arsenal(steamid, element, path["name"]),
        "missions": missions, "sect_points": sect_points,
        "sect_points_earned": sect_points_earned, "pavilion": pavilion,
        "personalities": personalities, "reputation": reputation, "death_chance": death_chance,
        "path": path,
    }


def points_left(c):
    """The sect points c can spend right now: earned + bonus - spent."""
    return max(0, c["sect_points_earned"] + c["pavilion"].get("bonus", 0) - c["pavilion"]["spent"])


def sect_points_text(c):
    """'1,200 (earned 1,000, spent 300, +500 from sales and rebirth)' for the card."""
    spent, bonus = c.get("pavilion", {}).get("spent", 0), c.get("pavilion", {}).get("bonus", 0)
    parts = []
    if spent or bonus:
        parts.append(f"earned {c['sect_points_earned']:,}")
    if spent:
        parts.append(f"spent {spent:,}")
    if bonus:
        parts.append(f"{bonus:+,} from sales and rebirth")
    return f"{c['sect_points']:,}" + (f" ({', '.join(parts)})" if parts else "")


def build_cultivator(steamid, key, profiles, refresh=False):
    """Returns (info, friend_ids, friends_note, cultivator) for one profile."""
    info = storage.apply_peaks(steamid, steam_profile.get_info(steamid, key, profiles, refresh))
    friend_ids, note = steam_api.get_friends(steamid, key, refresh)
    saved = storage.read_inventory(steamid)          # None on the very first load of this profile
    duel_points, _ = storage.read_duel_rep(steamid)
    state = storage.read_realm_state(steamid)
    life = storage.read_life(steamid)
    cultivator = generate_cultivator(info, steamid, friend_ids,
                                     inventory=saved[0] if saved else None,
                                     duel_points=duel_points, pavilion=storage.read_pavilion(steamid),
                                     realm_index=state["realm_index"],
                                     lifespan_lost=state["lifespan_lost"],
                                     born_realm=state["born_realm"],
                                     incarnation=life["incarnation"])
    if cultivator["death"]:                  # dead stays dead: the death is written into the file
        if life["dead"] is None:
            storage.write_life(steamid, dead=cultivator["death"])
        else:
            cultivator["death"] = life["dead"]
            cultivator["age"] = life["dead"]["age"]
    elif life["dead"] is not None:           # ...and a refresh or new Steam data never revives them
        cultivator["death"] = life["dead"]
        cultivator["age"] = life["dead"]["age"]
    if state["realm_index"] is None:         # first load: they start in the realm their stats give
        storage.write_realm_state(steamid, cultivator["realm_index"])
    cultivator["last_breakthrough_fail"] = state["last_failed"]
    if saved is None:                        # first load: the starting treasure becomes the inventory
        start = {"at": time.time(), "type": "start", "item": cultivator["base_treasure"],
                 "other": None}
        storage.write_inventory(steamid, cultivator["treasures"], [start])
        saved = (cultivator["treasures"], [start])
    cultivator["inventory_history"] = saved[1]
    stored = cultivator["pavilion"]
    if cultivator["sect_points_earned"] != stored.get("earned", 0):    # new achievements: credit them
        storage.write_pavilion(steamid, stored["items"], stored["spent"], earned=cultivator["sect_points_earned"])
        logs.RUN_LOG.note(f"sect points: credited up to {cultivator['sect_points_earned']} earned, "
                          f"{stored['spent']} spent, {cultivator['sect_points']} left")
        cultivator["pavilion"] = storage.read_pavilion(steamid)
    logs.RUN_LOG.note(f"{len(friend_ids)} friends{' (' + note + ')' if note else ''}; cultivator "
                      f"{cultivator['name']}, {cultivator['realm']}, age {cultivator['age']}, "
                      f"{'died' if cultivator['death'] else 'alive'}")
    return info, friend_ids, note, cultivator
