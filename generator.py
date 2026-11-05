"""The cultivator generator: turns Steam data into a deterministic, SteamID-seeded cultivator
(build_cultivator), plus the rules for fate, death,
lifespan, arsenal and treasures."""

import random
import time

import gamedata
import gametext
import logs
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
    if d.get('legacy'):
        cause = 'during a sect mission' if d['killer']=='sect_mission' else 'in their previous life'
        return cause, f"{c['name']} died {cause} before calendar synchronization, aged {d['age']:,}. Their original date is preserved in the historical save record."
    if d["killer"] == "sect_mission":
        return "a sect mission", f"{c['name']} was killed during a sect mission in Year {d['year']} of the Heavenly Calendar. Their soul must await rebirth."
    if d["killer"]=="sect_politics":
        return "sect intrigue",f"{c['name']} was assassinated during sect intrigue in Year {d['year']}. Their soul awaits rebirth."
    if d["killer"] in ("lethal_duel","travel_encounter"):
        cause="a lethal duel" if d["killer"]=="lethal_duel" else "a road encounter"
        return cause, f"{c['name']} was killed in {cause} in Year {d['year']}. Their soul awaits rebirth."
    if d["killer"] == "old_age":
        return "the end of their lifespan", f"{c['name']} reached the end of their lifespan in Year {d['year']} of the Heavenly Calendar."
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
                        incarnation=None, overrides=None, vitals=None, starting_treasure=None):
    overrides = overrides or {}
    rng = random.Random(int(steamid))  # same profile -> same cultivator
    # A reborn cultivator (incarnation, saved in their file) has a new random body: new talent,
    # name, gender, sect, affinity and title. The realm, path, personalities and arsenal stay.
    talent = gamedata.TALENT_BY_NAME[incarnation["talent"]] if incarnation else roll_talent(steamid)
    personalities = get_personalities(info, len(friend_ids or []))   # second: same reason
    path = roll_path(steamid)          # third: the Demonic Path adds power
    score = power_score(info, talent["power"] + sum(p["power"] for p in personalities)
                        + path["power"])
    if overrides:
        if not incarnation:
            talent = gamedata.TALENT_BY_NAME[overrides["talent"]]
        path = next(p for p in gamedata.PATHS if p["name"] == overrides["path"])
        personalities = [p for p in gamedata.PERSONALITIES if not p.get("steam_only") and p["name"] in overrides["personalities"]]
        score = local_power_score(overrides, talent_name=talent["name"])
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
    if overrides and not incarnation:
        gender, name, sect, element = (overrides[k] for k in ("gender", "name", "sect", "element"))
        title = overrides["title"] or gender_title(random.Random(f"title-{steamid}").choice(gamedata.TITLES_ALL[tier_no]), gender)
    treasure = random.Random(f"treasure-{steamid}").choice(gamedata.ALL_TREASURES[tier_no])  # starting treasure
    if starting_treasure is not None:
        treasure = starting_treasure
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
    # Successful ascension clears old losses in progress.py; later mission injuries
    # must still reduce an immortal's lifespan.
    if overrides and not incarnation:
        base_lifespan = overrides["lifespan"]
    if vitals:
        base_lifespan = vitals["base_lifespan"]
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
    if overrides and not incarnation:
        age = overrides["age"]
        fate = {"birth_year": overrides["birth_year"], "death": None}
    if vitals:
        age = vitals["age"]
        # These values were captured from a living cultivator at breakthrough.
        # Do not reroll its fate or derive a new age from its larger lifespan.
        fate = {"birth_year": vitals["birth_year"], "death": None}
    if age is not None and age >= lifespan:  # the years ran out (a failed breakthrough took them)
        death_age = age if vitals else lifespan
        fate["death"] = {"killer": "lifespan", "friend_id": None, "scene": 0, "age": death_age,
                         "year": fate["birth_year"] + death_age}
    age = fate["death"]["age"] if fate["death"] else age
    reputation = roll_reputation(steamid, info, personalities, path, duel_points)

    if overrides:
        death_chance = overrides["death_chance"] if not incarnation else death_chance
        technique = overrides["technique"] or technique

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


@storage.atomic
def build_cultivator(steamid, key, profiles, refresh=False):
    """Returns (info, friend_ids, friends_note, cultivator) for one profile."""
    try:
        storage.validate_profile_data(storage.load_profile_cache(steamid),str(steamid))
    except (ValueError,TypeError,KeyError) as exc:
        raise logs.SteamError(f'Invalid saved profile {steamid}: {exc}. Restore a backup or repair it in Developer tools.') from exc
    local = load_local_profile(steamid)
    if local:
        info = dict(local["info"])
        friend_ids, note = [], "Locally generated cultivator. No Steam data or API calls."
        profiles[steamid] = info
    else:
        if not key:
            raise logs.SteamError("No local profile found. Steam profiles require an API key.")
        import steam_api
        import steam_profile
        info = storage.apply_peaks(steamid, steam_profile.get_info(steamid, key, profiles, refresh))
        friend_ids, note = steam_api.get_friends(steamid, key, refresh)
    saved = storage.read_inventory(steamid)          # None on the very first load of this profile
    starting_treasure = None
    if not local:
        pc = storage.load_profile_cache(steamid)
        origin = pc.get("steam_inventory_origin")
        if saved is None and isinstance(origin, dict) and storage.is_steam_item_treasure(origin.get("item")):
            starting_treasure = origin["item"]
        if "steam_inventory_origin" not in pc:
            pavilion = pc.get("pavilion")
            # Migrate only an untouched, recorded starting treasure. Never restore sold/
            # stolen treasures or replace earned, purchased, or manually edited inventory.
            pristine = (saved is not None and len(saved[0]) == 1 and len(saved[1]) == 1
                        and saved[1][0].get("type") == "start" and saved[1][0].get("item") == saved[0][0]
                        and not pc.get("activity") and not (pavilion.get("history") if isinstance(pavilion, dict) else None))
            if saved is None or pristine:
                starting_treasure = steam_api.choose_inventory_treasure(steamid)
                pc["steam_inventory_origin"] = {"checked_at": time.time(), "item": starting_treasure,
                                                "source": "community" if starting_treasure else "template"}
                storage.save_profile_cache(pc)
                if pristine and starting_treasure:
                    history = [dict(saved[1][0], item=starting_treasure, source="Steam Community inventory")]
                    storage.write_inventory(steamid, [starting_treasure])
                    # Replace the initial event rather than recording a second free treasure.
                    updated = storage.load_profile_cache(steamid)
                    updated["inventory"]["history"] = history
                    storage.save_profile_cache(updated)
                    saved = ([starting_treasure], history)
    duel_points, _ = storage.read_duel_rep(steamid)
    state = storage.read_realm_state(steamid)
    life = storage.read_life(steamid)
    calendar = storage.load_profile_cache(steamid).get("calendar")
    if calendar and not local and state["vitals"] is None and calendar.get('incarnation') == (life.get('incarnation') or {}).get('count',0):
        state["vitals"] = {"base_lifespan":calendar['base_lifespan'], "age":18,
                           "birth_year":max(0,int(calendar['birth_day'])//storage.DAYS_PER_YEAR)}
    cultivator = generate_cultivator(info, steamid, friend_ids,
                                     inventory=saved[0] if saved else None,
                                     duel_points=duel_points, pavilion=storage.read_pavilion(steamid),
                                     realm_index=state["realm_index"],
                                     lifespan_lost=state["lifespan_lost"],
                                     born_realm=state["born_realm"],
                                     incarnation=life["incarnation"],
                                     overrides=local["character"] if local else None,
                                     vitals=state["vitals"], starting_treasure=starting_treasure)
    override=storage.load_profile_cache(steamid).get('sect_override')
    if override is not None:
        old_sect=cultivator['sect'];cultivator['sect']=override
        cultivator['backstory']=cultivator['backstory'].replace(old_sect,override)
    synchronize_calendar(steamid, cultivator, life)
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
    cultivator["spirit_stones"] = storage.read_spirit_stones(steamid)
    cultivator["sect_status"] = storage.ensure_sect(steamid, cultivator)
    cultivator["sect_choice_needed"] = not storage.load_profile_cache(steamid).get("world_npc") and cultivator["sect"]!="Wanderer" and storage.chartered_sect(cultivator["sect"]) is None
    cultivator['traits'] = cultivator['personalities']
    cultivator['world_personalities'] = storage.actor_disposition(steamid)
    training=storage.load_profile_cache(steamid).get('mentor_power',0)
    cultivator['score']+=training
    cultivator['eligible_realm_index']=get_realm(cultivator['score'])[0]
    cultivator['injury'] = storage.injury_state(steamid)
    if cultivator['injury'] and not cultivator['death']:
        cultivator['healthy_score'] = cultivator['score']
        cultivator['score'] = round(cultivator['score']*cultivator['injury']['factor'])
    if cultivator['death']:storage.retire_dead(steamid)
    with storage.world_transaction() as db:
        affiliation=db.execute('SELECT sect_id,office,mentor FROM affiliations WHERE actor=?',(steamid,)).fetchone()
        cultivator['sect_role']=storage.member_role(affiliation)
        db.execute('INSERT OR REPLACE INTO actor_measures VALUES(?,?,?,?)',(steamid,cultivator.get('healthy_score',cultivator['score']),cultivator['realm_index'],storage.world_state()['day']))
    return info, friend_ids, note, cultivator


# ============================================================================
# Offline profiles — randomized templates, explicit stats, local lookup, creation
# ============================================================================

import copy
import json
from pathlib import Path
import secrets
import unicodedata

def normalize_local_name(text):
    return unicodedata.normalize("NFKC", text).strip().casefold()


def random_local_settings(*, player_start=False, rng=None):
    """Developer rolls span all realms; player starts use bounded beginner rolls."""
    rng = rng or random.Random(secrets.randbits(128))
    sid = str(rng.randrange(10**19, 10**20))
    realm = rng.randrange(2 if player_start else len(gamedata.REALMS))
    gender = rng.choice(("male", "female"))
    lifespan = rng.randint(*gamedata.REALM_LIFESPANS[realm])
    return {
        "name": make_name(rng, gender), "gender": gender,
        "sect": rng.choice(storage.sect_names())["name"],
        "element": rng.choice(gamedata.ELEMENTS),
        "talent": rng.choices(gamedata.TALENTS, weights=[t["weight"] for t in gamedata.TALENTS], k=1)[0]["name"],
        "path": rng.choice(gamedata.PATHS)["name"],
        "score": rng.randint(*realm_power_range(realm)),
        "realm_index": realm, "born_realm": realm,
        "age": rng.randint(16, max(16, lifespan // 2)), "birth_year": rng.randint(1000, 9000),
        "lifespan": lifespan, "death_chance": 0.08,
        "title": "", "technique": "", "personalities": rng.sample([p["name"] for p in gamedata.PERSONALITIES if not p.get("steam_only")], rng.randrange(4)),
        "missions": rng.randint(0, 120 if player_start else 5000),
        "sect_points": rng.randint(0, 600 if player_start else 30000), "spirit_stones": 0,
        "reputation": rng.randint(0, 50 if player_start else 3000),
        "level": rng.randint(0, 200), "game_count": rng.randint(1, 1000),
        "top_game": "Dao Meditation", "top_hours": rng.randint(0, 10000),
        "badges": rng.randint(0, 300), "seed": sid,
    }


def validate_local_settings(s):
    if not isinstance(s, dict):
        raise ValueError("Settings must be a JSON object.")
    if type(s.get("spirit_stones", 0)) is not int or s.get("spirit_stones", 0) < 0:
        raise ValueError("Spirit Stones must be a nonnegative whole number.")
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
    # Old saves keep their exact score until edited with the reactive controls.
    return max(0, local_power_base(s, talent_name) + s["power_offset"]) if "power_offset" in s else s["score"]


def local_profile_info(s):
    return {"name": s["name"], "account_created": None,
            "level": s["level"], "game_count": s["game_count"],
            "top_game": s["top_game"], "top_hours": s["top_hours"], "total_hours": s["top_hours"],
            "achievements": s["missions"], "achievements_hidden": False, "achievements_new": None,
            "ach_stats": None, "badges": s["badges"], "badges_hidden": False, "offline": True}


def make_local_profile(settings):
    s = copy.deepcopy(settings)
    for key in ("name", "sect", "title", "technique", "top_game"):
        if isinstance(s.get(key), str):
            s[key] = s[key].strip()
    validate_local_settings(s)
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
            "duel_reputation": {"points": s["reputation"] - c["reputation"]["base_points"], "history": []},
            "activity": [{"at": time.time(), "type": "adventure", "summary": "Created locally with the developer profile generator."}]}


def load_local_profile(steamid):
    data = storage.load_profile_cache(steamid)
    local = data.get("offline")
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
    local = copy.deepcopy(local)
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
            home=db.execute('SELECT id FROM locations WHERE sect_id=?',(choice['id'],)).fetchone()
            if home:db.execute('INSERT OR IGNORE INTO positions VALUES(?,?)',(sid,home[0]))
        return cache / f"{sid}.profile.json"  # logical editor locator, no JSON is written




# ============================================================================
# One Heavenly Calendar: stable birthdays, historical deaths, current incarnations.
# ============================================================================
def synchronize_calendar(steamid, c, life):
    pc = storage.load_profile_cache(steamid)
    now = storage.world_state()['day']
    incarnation = (life.get('incarnation') or {}).get('count', 0)
    clock = pc.get('calendar')
    if not clock or clock.get('incarnation') != incarnation:
        baseline = storage.world_state()['start_day'] if pc.get('legacy_calendar') and not clock else now
        age = c['age'] if c['age'] is not None else 18
        dead = life['dead'] or c['death']
        if dead:
            dead = copy.deepcopy(dead)
            age = dead['age']
            end = baseline - 1
            dead.update(original_year=dead.get('year'),year=int(end)//storage.DAYS_PER_YEAR, world_day=end, legacy=True)
            life['dead'] = dead
            pc['life'] = life
        else:
            end = baseline
        clock = {'birth_day': end-age*storage.DAYS_PER_YEAR, 'incarnation': incarnation,
                 'synchronized_day': baseline, 'original_birth_year': c['birth_year']}
        pc['calendar'] = clock
        # Keep a generated Steam lifespan stable as account data changes later.
        clock['base_lifespan'] = c['base_lifespan']
        storage.save_profile_cache(pc)
    c['birth_year'] = int(clock['birth_day']) // storage.DAYS_PER_YEAR
    c['birth_day'] = clock['birth_day']
    c['world_day'] = now
    dead = life['dead']
    c['death'] = dead
    if dead:
        c['age'] = dead['age']
    else:
        c['age'] = max(0, int((now-clock['birth_day']) // storage.DAYS_PER_YEAR))
        if c['age'] >= c['lifespan']:
            end = clock['birth_day'] + c['lifespan']*storage.DAYS_PER_YEAR
            # Injuries may exhaust a lifespan immediately, rather than in the past.
            end = max(end, clock.get('last_alive_day', clock['synchronized_day']))
            death_age = max(c['lifespan'],int((end-clock['birth_day'])//storage.DAYS_PER_YEAR))
            c['age'] = death_age
            dead = {'killer':'old_age','friend_id':None,'scene':0,'age':death_age,
                    'year':int(end)//storage.DAYS_PER_YEAR,'world_day':end}
            c['death'] = dead
            storage.write_life(steamid,dead=dead)
            import progress
            progress.record_world_action('death',c['name']+' has passed away',f"{c['name']} of {c['sect']} reached the end of their lifespan.",[(steamid,c)],outcome='death',importance=3 if c['realm_index']>=6 else 2)
    return c
