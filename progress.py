"""Progress of a cultivator: breakthroughs, adventures and rebirth."""

import json
import random
import time

import gamedata
import gametext
import generator
import offline_generator
import logs
import steam_api
import storage


# ---------------------------------------------------------------------------
# Sect missions: per-member persistent boards, atomic resolution and cooldowns.
# ---------------------------------------------------------------------------
def make_sect_offers(rng=random):
    import uuid
    offers = []
    kinds = ["herbs", "delivery", "bodyguard", "beast", rng.choice(["herbs", "delivery", "bodyguard", "beast"])]
    rng.shuffle(kinds)
    for kind in kinds:
        gender = rng.choice(["male", "female"])
        person = generator.make_name(rng, gender)
        title = generator.gender_title(rng.choice(gamedata.TITLES_ALL[0]), gender)
        if kind == "herbs":
            text = f"Gather {rng.choice(['moonlit lotus', 'jadeleaf', 'silverroot', 'sunfire blossom'])} for the sect alchemist {person}."
            points, stones = 5, 20
        elif kind == "delivery":
            destination = f"{rng.choice(gamedata.SECT_ADJ)} {rng.choice(gamedata.SECT_NOUN)}"
            text = f"Deliver {rng.choice(['a sealed letter', 'a medicine parcel', 'a jade scroll', 'a supply package'])} to the nearby {destination}."
            points, stones = 5, 30
        elif kind == "bodyguard":
            text = f"Protect {title} {person} on a journey through {rng.choice(['Bandit Pass', 'Mistwood Valley', 'the Silent Marsh', 'Fallen Star Road'])}."
            points, stones = 15, 100
        else:
            text = f"Slay the {rng.choice(['Crimson-Fang Tiger', 'Ironhide Boar', 'Moonshadow Wolf', 'Venomscale Serpent'])} threatening {rng.choice(['the herb gardens', 'the mountain road', 'a nearby village', 'the southern farms'])}."
            points, stones = 15, 120
        offers.append(dict(id=uuid.uuid4().hex, kind=kind, text=text, hard=points == 15,
                           sect_points=points, stones=stones, reputation=30 if points == 15 else 10))
    return offers


@storage.atomic
def sect_board(steamid, c, now=None):
    now = time.time() if now is None else now
    status = storage.ensure_sect(steamid, c)
    if c["sect"]=="Wanderer":
        return dict(status,offers=[])
    if not c["death"] and now >= status["ready_at"] and not status["offers"]:
        pc = storage.load_profile_cache(steamid)
        member = pc["sect_memberships"][status["identity"]["id"]]
        member["offers"] = make_sect_offers()
        if not storage.save_profile_cache(pc, durable=True):
            raise logs.SteamError("Could not persist the mission board. Check cache write permissions.")
        status = storage.ensure_sect(steamid, c)
    with storage.world_transaction() as db:
        if storage.region_ready(db) and status['offers']:
            here=storage.presence(steamid)
            if here['state']=='present' and any('location_id' not in o for o in status['offers']):
                pc=storage.load_profile_cache(steamid)
                for offer in pc['sect_memberships'][status['identity']['id']]['offers']:
                    if 'location_id' in offer:continue
                    offer['legacy_text']=offer['text'];offer['location_id']=here['location']
                    if offer['kind']=='herbs':offer['text']=offer['text'].rstrip('.')+' in the herb gardens of '+here['name']+'.'
                    elif offer['kind']=='delivery':offer['text']='Deliver a sealed sect parcel within '+here['name']+'.'
                    elif offer['kind']=='bodyguard':offer['text']=offer['text'].split(' on a journey')[0]+' within '+here['name']+'.'
                    else:offer['text']=offer['text'].split(' threatening')[0]+' on the outskirts of '+here['name']+'.'
                storage.save_profile_cache(pc,durable=True);status=storage.ensure_sect(steamid,c)
    return status


def mission_risks(c):
    protected = gamedata.TALENT_BY_NAME[c["talent"]["name"]]["power"] > gamedata.TALENT_BY_NAME["Regular Martial Body"]["power"]
    return {"failure": .15, "injury": max(.01, .04 - (.02 if protected else 0)),
            "death": max(.0002, .0008 - (.0003 if protected else 0))}


@storage.atomic
def perform_sect_mission(steamid, c, offer_id, rng=random, now=None):
    now = time.time() if now is None else now
    if c["death"]:
        raise logs.SteamError("The dead cannot take sect missions. Seek rebirth through Adventure.")
    storage.require_physical(steamid)
    if c["sect"]=="Wanderer":raise logs.SteamError("Wanderers have no sect missions.")
    status = storage.ensure_sect(steamid, c)
    pc = storage.load_profile_cache(steamid)
    member = pc["sect_memberships"][status["identity"]["id"]]
    if now < member["ready_at"]:
        raise logs.SteamError(f"Sect mission cooldown: {int(member['ready_at'] - now) + 1} seconds remaining.")
    offer = next((o for o in member["offers"] if o["id"] == offer_id), None)
    if offer is None:
        raise logs.SteamError("That mission offer has expired. Refresh the sect board.")
    if offer.get("location_id") and storage.presence(steamid)["location"]!=offer["location_id"]:
        raise logs.SteamError("Travel to the mission location shown on this saved offer first.")
    if offer["hard"]:storage.require_physical(steamid,dangerous=True)
    outcome, cooldown, lost = "success", 300, 0
    if offer["hard"]:
        risk = mission_risks(c)
        roll = rng.random()
        cooldown = 600
        if roll < risk["death"]:
            outcome = "death"
        elif roll < risk["death"] + risk["injury"]:
            outcome, cooldown = "injury", 900
            lost = 10 * (c["realm_index"] + 1)
        elif roll < risk["death"] + risk["injury"] + risk["failure"]:
            outcome = "failure"
    if lost:
        state = storage.read_realm_state(steamid)
        state["lifespan_lost"] += lost
        state["vitals"] = {"age": c["age"], "birth_year": c["birth_year"], "base_lifespan": c["base_lifespan"]}
        pc["realm_state"] = state
        if c["lifespan"] - lost <= (c["age"] if c["age"] is not None else 0):
            outcome = "death"
    if outcome == "death":
        age = c["age"] if c["age"] is not None else 18
        life = storage.read_life(steamid)
        life["dead"] = {"killer": "sect_mission", "friend_id": None, "scene": 0,
                        "age": age, "year": int(storage.world_state()["day"])//storage.DAYS_PER_YEAR, "world_day": storage.world_state()["day"]}
        circumstance = "succumbed to injuries sustained during a sect mission" if lost else "was killed during a sect mission"
        life["dead"]["account"] = storage.death_account(steamid, circumstance)
        life["dead"]["account"]["assignment"] = offer["text"]
        pc["life"] = life
    if outcome == "success":
        pc["completed_sect_missions"]=pc.get("completed_sect_missions",0)+1
        member["points"] += offer["reputation"]
        pav = storage.read_pavilion(steamid)
        pav["bonus"] += offer["sect_points"]
        pc["pavilion"] = pav
        wallet = pc.setdefault("wallet", {})
        wallet["spirit_stones"] = storage.read_spirit_stones(steamid) + offer["stones"]
    result = dict(at=now, type="adventure", outcome=outcome, lost=lost,
                  summary=f"Sect mission {outcome}: {offer['text']}" +
                  (f" Earned {offer['sect_points']} sect points, {offer['stones']} Spirit Stones and {offer['reputation']} sect reputation." if outcome == "success" else f" Lifespan lost: {lost} years." if lost else " No rewards."))
    member["ready_at"] = now + cooldown
    member["offers"] = []
    member["history"] = (member["history"] + [result])[-50:]
    pc["activity"] = (storage.read_activity(steamid) + [result])[-storage.ACTIVITY_LIMIT:]
    if not storage.save_profile_cache(pc, durable=True):
        raise logs.SteamError("Mission could not be saved. Check cache write permissions before continuing.")
    if lost and outcome!='death':storage.injure(steamid,'Sect mission')
    if outcome=='death':storage.retire_dead(steamid)
    record_world_action('mission',c['name']+(' died on a sect mission' if outcome=='death' else ' completed a sect mission'),result['summary'],[(steamid,c)],outcome='mission_success' if outcome=='success' else outcome,importance=2 if outcome=='death' else 1)
    return result


# ---------------------------------------------------------------------------
# Adventure: the "adventure" command (and the Adventure button in the window). Every adventure
# rolls a NEW random event, not tied to the SteamID:
#   8%  they find a treasure one tier below their realm's
#  20%  they meet a friend (the friend story templates)
#   5%  reputation changes: 70% a gain, 30% a loss
#  67%  nothing happens
# A DEAD cultivator who presses the button does not adventure: the Heavens roll the dice for a
# rebirth instead, REBIRTH_CHANCE (1%), at most once every REBIRTH_INTERVAL_HOURS (24 hours).
# A reborn cultivator gets a new body (name, gender, sect, affinity, talent, title, lifespan,
# reputation and sect points are all rerolled at random, whatever the SteamID); realm, path,
# personalities and arsenal stay. The death is saved in their file, so a refresh never revives.
# ---------------------------------------------------------------------------
ADVENTURE_FIND_CHANCE = 0.08
ADVENTURE_FRIEND_CHANCE = 0.20
ADVENTURE_REP_CHANCE = 0.05
ADVENTURE_REP_GAIN_SHARE = 0.70
ADVENTURE_REP_GAIN = (10, 40)
ADVENTURE_REP_LOSS = (5, 25)
REBIRTH_CHANCE = 0.01
REBIRTH_INTERVAL_HOURS = 24
REBIRTH_REP_RANGE = (0, 500)
REBIRTH_SECT_POINTS_RANGE = (0, 3000)


def adventure_kind(roll):
    """'treasure', 'friend', 'reputation' or 'nothing' for a roll between 0 and 1."""
    if roll < ADVENTURE_FIND_CHANCE:
        return "treasure"
    if roll < ADVENTURE_FIND_CHANCE + ADVENTURE_FRIEND_CHANCE:
        return "friend"
    if roll < ADVENTURE_FIND_CHANCE + ADVENTURE_FRIEND_CHANCE + ADVENTURE_REP_CHANCE:
        return "reputation"
    return "nothing"


def lower_treasure_pool(c):
    """Treasures one tier below the cultivator's own (the lowest tier for the lowest), that they
    do not own yet; if they own them all, any lower-tier treasure not owned."""
    tier = 0 if c["realm_index"] <= 2 else 1 if c["realm_index"] <= 6 else 2
    owned = generator.treasures_of(c)
    pool = [t for t in gamedata.ALL_TREASURES[max(0, tier - 1)] if t not in owned]
    if not pool:
        pool = [t for lower in gamedata.ALL_TREASURES[:max(1, tier)] for t in lower if t not in owned]
    return pool


@storage.atomic
def perform_adventure(steamid, c, info, friend_ids, key, rng=random, now=None):
    """One adventure of cultivator c (a dead one gets the rebirth roll instead). Saves what
    happened and returns {'kind', 'title', 'text', 'rep', 'item', 'friend', 'reborn'}.
    Nothing is printed here."""
    now = time.time() if now is None else now
    if c["death"]:
        return attempt_rebirth(steamid, c, rng, now)
    storage.require_physical(steamid,dangerous=True)
    kind = adventure_kind(rng.random())
    fmt = dict(me=c["name"], sect=c["sect"])
    out = {"kind": kind, "text": "", "rep": 0, "item": None, "friend": None, "reborn": False}
    summary = None
    if kind == "treasure":
        pool = lower_treasure_pool(c)
        if pool:
            item = rng.choice(pool)
            items = generator.treasures_of(c) + [item]
            storage.write_inventory(steamid, items, [{"at": now, "type": "found", "item": item,
                                                      "other": "adventure"}])
            out["item"], summary = item, f"Found {item} on an adventure"
            out["text"] = rng.choice(gametext.ADVENTURE_FIND).format(item=item, **fmt)
        else:
            kind = "nothing"
    if kind == "friend":
        friend = steam_api.resolve_friend(c, friend_ids, key)
        if friend:
            out["friend"] = friend
            out["text"] = generator.generate_story(c, info, friend)
            summary = f"Spent time with their Steam friend {friend['name']} (cultivator " \
                      f"{generator.cultivator_name(friend['steamid'])})"
        else:
            kind = "nothing"                               # nobody to meet
    if kind == "reputation":
        gain = rng.random() < ADVENTURE_REP_GAIN_SHARE
        amount = rng.randint(*(ADVENTURE_REP_GAIN if gain else ADVENTURE_REP_LOSS))
        old, _ = storage.read_duel_rep(steamid)
        new = max(-c["reputation"]["base_points"], old + (amount if gain else -amount))
        actual = new - old
        storage.write_duel_rep(steamid, new)
        out["rep"] = actual
        out["text"] = rng.choice(gametext.ADVENTURE_REP_GAIN_TEXT if gain else gametext.ADVENTURE_REP_LOSS_TEXT
                                 ).format(amount=abs(actual) or amount, **fmt)
        if not gain and actual == 0:
            out["text"] += " (There was no reputation left to lose.)"
        summary = f"Reputation {actual:+d}: " + ("a deed that people talked about" if gain
                                                 else "a blunder that people talked about")
        out["kind"] = kind = "gain" if gain else "loss"
    if kind == "nothing":
        out["text"] = rng.choice(gametext.ADVENTURE_NOTHING).format(**fmt)
    out["kind"] = kind
    out["title"] = gametext.ADVENTURE_TITLES[kind]
    if rng.random()<.05:
        stones=rng.randint(10,20)
        pc=storage.load_profile_cache(steamid)
        pc.setdefault('wallet',{})['spirit_stones']=storage.read_spirit_stones(steamid)+stones
        storage.save_profile_cache(pc,durable=True)
        found=f'Found {stones} Spirit Stones.'
        out['stones']=stones
        out['text']+=' '+found
        summary=(summary+' · ' if summary else '')+found
    if summary:
        storage.add_activity(steamid, {"at": now, "type": "adventure", "kind": kind, "summary": summary,
                                       "rep": out["rep"]})
    logs.RUN_LOG.note(f"adventure: {c['name']} ({steamid}) {kind}" + (f": {summary}" if summary else ""))
    record_world_action('adventure',c['name']+' returned from an adventure',out['text'],[(steamid,c)],outcome='victory' if out['rep']>0 else kind,importance=1)
    return out


def new_incarnation(c, rng, now):
    """A new random body for the dead cultivator c. The realm, path, personalities and
    arsenal are not part of it: they stay."""
    gender = rng.choice(("male", "female"))
    return {"gender": gender, "name": generator.make_name(rng, gender),
            "sect": rng.choice(storage.sect_names())["name"],
            "element": rng.choice(gamedata.ELEMENTS),
            "talent": rng.choices(gamedata.TALENTS, weights=[t["weight"] for t in gamedata.TALENTS], k=1)[0]["name"],
            "title_roll": rng.randrange(1_000_000), "lifespan_roll": rng.randint(150, 400),
            "immortal_lifespan": rng.randint(*generator.IMMORTAL_LIFESPAN),
            "birth_year": 0, "age": rng.randint(16, 40),
            "arsenal": json.loads(json.dumps(generator.arsenal_of(c))),
            "count": read_life_count(c) + 1, "at": now}


def read_life_count(c):
    return c.get("incarnation", 0)


@storage.atomic
def attempt_rebirth(steamid, c, rng=random, now=None):
    """The Heavens' roll for a dead cultivator: REBIRTH_CHANCE, at most once per
    REBIRTH_INTERVAL_HOURS. On success the new body is saved (see the section comment)."""
    storage.require_physical(steamid)
    now = time.time() if now is None else now
    life = storage.read_life(steamid)
    wait = REBIRTH_INTERVAL_HOURS * 3600
    out = {"kind": "rebirth_wait", "text": "", "rep": 0, "item": None, "friend": None,
           "reborn": False, "wait": 0, "name": c["name"]}
    if life["last_roll"] is not None and now - life["last_roll"] < wait:
        left = int(life["last_roll"] + wait - now)
        out["wait"] = left
        out["text"] = (f"{c['name']}'s soul drifts through the Yellow Springs, but the Heavens "
                       f"have already looked today. The next chance comes in "
                       f"{left // 3600} h {left % 3600 // 60:02d} min.")
        out["title"] = gametext.ADVENTURE_TITLES["rebirth_wait"]
        return out
    storage.write_life(steamid, last_roll=now)
    if rng.random() >= REBIRTH_CHANCE:
        out["kind"] = "rebirth_fail"
        out["title"] = gametext.ADVENTURE_TITLES["rebirth_fail"]
        out["text"] = (f"{c['name']}'s soul wandered the Yellow Springs all day, searching for a "
                       f"body to call its own. The Heavens did not answer ({REBIRTH_CHANCE:.0%} "
                       f"chance, one roll every {REBIRTH_INTERVAL_HOURS} hours).")
        logs.RUN_LOG.note(f"rebirth: {c['name']} ({steamid}) rolled and stayed dead")
        return out
    inc = new_incarnation(c, rng, now)
    inc['awakened_day'] = storage.world_state()['day']
    inc['birth_year'] = int(storage.world_state()['day'])//storage.DAYS_PER_YEAR-inc['age']
    pc = storage.load_profile_cache(steamid)
    pc.pop('sect_override',None)
    pc.pop('sect_application',None)
    pc['past_incarnations'] = (pc.get('past_incarnations',[]) + [{'name':c['name'], 'birth_day':c.get('birth_day'), 'death':c['death']}])
    storage.save_profile_cache(pc)
    rep_target = rng.randint(*REBIRTH_REP_RANGE)
    sect_target = rng.randint(*REBIRTH_SECT_POINTS_RANGE)
    storage.write_life(steamid, dead=None, last_roll=now, incarnation=inc, rebirths=inc["count"])
    storage.write_duel_rep(steamid, rep_target - c["reputation"]["base_points"])
    pav = storage.read_pavilion(steamid)
    storage.write_pavilion(steamid, pav["items"], pav["spent"], earned=max(pav["earned"], c["sect_points_earned"]),
                           bonus=sect_target - (max(pav["earned"], c["sect_points_earned"]) - pav["spent"]))
    storage.write_realm_state(steamid, c["realm_index"], None, 0, vitals=None)  # new body, clear previous age/lifespan
    with storage.world_transaction() as db:
        db.execute("UPDATE npcs SET next_day=?,activity='Cultivating' WHERE id=?",(storage.world_state()['day']+1,steamid))
        db.execute("UPDATE affiliations SET office='Member',mentor=NULL,support=0 WHERE actor=?",(steamid,))
        db.execute('UPDATE affiliations SET mentor=NULL WHERE mentor=?',(steamid,))
        db.execute('DELETE FROM council_support WHERE candidate=? OR voter=?',(steamid,steamid))
        db.execute("UPDATE sect_plots SET stage='resolved',outcome='Previous incarnation ended' WHERE actor=? AND stage<>'resolved'",(steamid,))
        db.execute("UPDATE membership_terms SET paid_role='',next_salary=? WHERE actor=?",(storage.world_state()['day']+political_seconds(1800),steamid))
    summary = (f"{c['name']} died and was reborn as {inc['name']}, a {inc['gender']} of the "
               f"{inc['sect']}")
    storage.add_activity(steamid, {"at": now, "type": "reborn", "summary": summary})
    out.update(kind="reborn", reborn=True, title=gametext.ADVENTURE_TITLES["reborn"],
               old_name=c["name"], new_name=inc["name"], gender=inc["gender"], sect=inc["sect"],
               talent=inc["talent"], element=inc["element"], reputation=rep_target,
               sect_points=sect_target)
    out["text"] = (f"REBORN! In {storage.calendar_text()}, "
                   f"{c['name']} awakens in a new incarnation: {inc['name']}, a {inc['gender']} of the "
                   f"{inc['sect']}, born with {inc['talent']} and an affinity for {inc['element']}. "
                   f"Fame and fortune start anew ({rep_target:,} reputation, {sect_target:,} sect "
                   f"points). Realm, path, personality and arsenal remain.")
    logs.RUN_LOG.note(f"rebirth: {summary} (incarnation {inc['count']})")
    return out


# ---------------------------------------------------------------------------
# Breakthrough: the "breakthrough" command (and the Breakthrough button in the window). The realm
# a cultivator holds is saved in their file. When the power score reaches the next realm's
# threshold they may try to break through, one realm at a time. The chance is
#     base chance of the realm they are leaving (95% for the lowest ... 22% before the last)
#   + personality bonus (Fearless +5%, Brave +2%)
#   + talent bonus (Gifted Spirit Root +3% ... Reincarnation of the Dao +40%)
#   + 30% if a Heaven-Defying Breakthrough Pill is swallowed (it is used up either way),
# capped at 100%. A failed attempt means a rest of BREAKTHROUGH_COOLDOWN_MINUTES.
# ---------------------------------------------------------------------------
BREAKTHROUGH_BASE = [0.95, 0.86, 0.77, 0.68, 0.58, 0.49, 0.40, 0.31, 0.22]   # by current realm
TALENT_BREAKTHROUGH = {"Poor Martial Body": 0.0, "Regular Martial Body": 0.0,
                       "Gifted Spirit Root": 0.03, "Heaven-Favored Genius": 0.10,
                       "Divine Physique": 0.18, "Primordial Chaos Body": 0.28,
                       "Reincarnation of the Dao": 0.40}
PERSONALITY_BREAKTHROUGH = {"Fearless": 0.05, "Brave": 0.02}
BREAKTHROUGH_PILL_ID = "breakthrough_pill"
BREAKTHROUGH_PILL_BONUS = 0.30
BREAKTHROUGH_COOLDOWN_MINUTES = 60
# Years of lifespan a FAILED breakthrough costs, by the realm the cultivator is in (Void
# Refinement: 250). If the lifespan then falls to their age or below, they die of it.
LIFESPAN_PENALTY = [5, 12, 30, 60, 110, 170, 250, 350, 480]


def breakthrough_chance(c, use_pill=False):
    """The chance for cultivator c to break through to the next realm, with its parts."""
    base = BREAKTHROUGH_BASE[min(c["realm_index"], len(BREAKTHROUGH_BASE) - 1)]
    personalities = [(p["name"], PERSONALITY_BREAKTHROUGH[p["name"]]) for p in c["personalities"]
                     if PERSONALITY_BREAKTHROUGH.get(p["name"])]
    talent = (c["talent"]["name"], TALENT_BREAKTHROUGH.get(c["talent"]["name"], 0.0))
    pill = BREAKTHROUGH_PILL_BONUS if use_pill else 0.0
    raw = base + sum(b for _, b in personalities) + talent[1] + pill
    return {"base": base, "realm": c["realm"], "personalities": personalities,
            "talent": talent, "pill": pill, "total": round(min(1.0, raw), 4),
            "capped": raw > 1.0}


def breakthrough_lines(bd):
    """The parts of a chance, as plain lines for the terminal and the window."""
    pct = lambda x: f"{x * 100:g}%"
    lines = [f"Base chance in {bd['realm']}: {pct(bd['base'])}"]
    for name, bonus in bd["personalities"]:
        lines.append(f"Personality ({name}): +{pct(bonus)}")
    if bd["talent"][1]:
        lines.append(f"Talent ({bd['talent'][0]}): +{pct(bd['talent'][1])}")
    if bd["pill"]:
        lines.append(f"Heaven-Defying Breakthrough Pill: +{pct(bd['pill'])}")
    lines.append(f"Total: {pct(bd['total'])}" + (" (capped at 100%)" if bd["capped"] else ""))
    return lines


def breakthrough_risk_text(st):
    """What failing would cost, for the terminal and the window."""
    text = f"If it fails: {st['penalty']:,} years of lifespan are lost ({st['lifespan']:,} -> " \
           f"{max(0, st['lifespan'] - st['penalty']):,} years)."
    if st["fatal"]:
        text += (f" WARNING: the cultivator is {st['age']:,} years old, so a failure would use up "
                 f"the whole lifespan and END THEIR LIFE.")
    return text


def breakthrough_result_text(name, r):
    if r.get("ritual"):return r["ritual"]
    if r["success"]:
        return (f"SUCCESS! Heavenly lightning rolls across the sky. {name} breaks through to "
                f"{r['to']}!")
    text = (f"FAILED. The Qi turns on {name}, who loses {r['lost']:,} years of lifespan"
            + (" and dies of it." if r["died"] else
               f" and must rest for {BREAKTHROUGH_COOLDOWN_MINUTES} minutes before trying again."))
    return text + (" The pill is gone." if r["pill_used"] else "")


def breakthrough_status(c, now=None):
    """Can c try to break through right now? Returns a dict with 'can', 'reason' (why not),
    'current', 'next', the chance without and with a pill, the pills owned and the cooldown."""
    now = time.time() if now is None else now
    idx = c["realm_index"]
    top = idx >= len(gamedata.REALMS) - 1
    st = {"can": False, "reason": "", "current": c["realm"],
          "next": None if top else gamedata.REALMS[idx + 1][1], "pills": c["pavilion"]["items"].get(
              BREAKTHROUGH_PILL_ID, 0), "cooldown_left": 0,
          "chance": None if top else breakthrough_chance(c),
          "chance_pill": None if top else breakthrough_chance(c, True),
          "penalty": 0 if top else LIFESPAN_PENALTY[idx], "lifespan": c["lifespan"],
          "age": c.get("age"), "fatal": False}
    if not top and st["age"] is not None:
        st["fatal"] = st["age"] >= c["lifespan"] - st["penalty"]    # failing would end their life
    if c["death"]:
        st["reason"] = (f"{c['name']} died in Year {c['death']['year']} of the Heavenly "
                        f"Calendar. The dead cannot break through.")
    elif c.get('ascension'):
        st['reason']=f"Ascending at {c['ascension']['site']} until {storage.calendar_text(c['ascension']['ends'])}."
    elif top:
        st["reason"] = f"{c['name']} already stands in the highest realm, {c['realm']}."
    elif idx in (1,8) and not c['pavilion']['items'].get('foundation_pill' if idx==1 else gamedata.DAO_PILL):
        st['reason']='Requires one '+('Foundation Establishment Pill.' if idx==1 else 'Dao Integration Pill to begin a five-day ascension.')
    elif c["eligible_realm_index"] <= idx:
        need = gamedata.REALMS[idx + 1][0]
        st["reason"] = (f"Not ready yet: {gamedata.REALMS[idx + 1][1]} needs a power score of {need:,}, "
                        f"and {c['name']} has {c['score']:,.0f}.")
    else:
        failed = c.get("last_breakthrough_fail")
        left = int(failed + BREAKTHROUGH_COOLDOWN_MINUTES * 60 - now) if failed else 0
        if left > 0:
            st["cooldown_left"] = left
            st["reason"] = (f"{c['name']} is still recovering from the failed attempt and must "
                            f"rest for another {left // 60 + 1} minute(s).")
        else:
            st["can"] = True
    return st


@storage.atomic
def attempt_breakthrough(steamid, c, use_pill=False, rng=random, now=None):
    """Tries the breakthrough for cultivator c (loaded for steamid). Saves the new realm on
    success, the failure time on failure, uses up the pill if one was swallowed and records
    it all in the history. Raises SteamError if it is not allowed."""
    storage.require_physical(steamid,dangerous=True)
    now = time.time() if now is None else now
    st = breakthrough_status(c, now)
    if not st["can"]:
        raise logs.SteamError(st["reason"])
    if use_pill and st["pills"] <= 0:
        raise logs.SteamError(f"{c['name']} owns no Heaven-Defying Breakthrough Pill. "
                              f"One can be bought at the Martial Pavilion.")
    if c['realm_index']==8:
        import warfare
        return warfare.begin_ascension(steamid,c)
    if c['realm_index']==1:
        import pavilion_shop
        pavilion_shop.consume(steamid,'foundation_pill')
    bd = breakthrough_chance(c, use_pill)
    success = rng.random() < bd["total"]
    if use_pill:
        goods = storage.read_pavilion(steamid)["items"]
        goods[BREAKTHROUGH_PILL_ID] -= 1
        storage.write_pavilion(steamid, goods, c["pavilion"]["spent"],
                               {"at": now, "type": "pill used", "item": gamedata.PAVILION_BY_ID[BREAKTHROUGH_PILL_ID]["name"],
                                "other": None})
    lost = 0 if success else st["penalty"]
    vitals = storage.read_realm_state(steamid)["vitals"]
    if success:
        target = c["realm_index"] + 1
        low, high = gamedata.REALM_LIFESPANS[target]
        vitals = {"base_lifespan": rng.randint(low, high),
                  "age": c["age"], "birth_year": c["birth_year"]}
    storage.write_realm_state(steamid, c["realm_index"] + (1 if success else 0),
                              None if success else now,
                              0 if success else storage.read_realm_state(steamid)["lifespan_lost"] + lost,
                              vitals=vitals)
    if not success and st['fatal']:
        day=storage.world_state()['day']
        storage.write_life(steamid,dead={'killer':'lifespan','friend_id':None,'scene':0,
                                       'age':c['age'],'year':int(day)//storage.DAYS_PER_YEAR,'world_day':day,
                                       'account':storage.death_account(steamid,f"exhausted their remaining lifespan attempting to reach {st['next']}")})
    storage.add_activity(steamid, {"at": now, "type": "breakthrough", "success": success,
                                   "from": st["current"], "to": st["next"], "chance": bd["total"],
                                   "pill": bool(use_pill), "lost": lost,
                                   "fatal": bool(not success and st["fatal"])})
    logs.RUN_LOG.note(f"breakthrough: {c['name']} ({steamid}) {'broke through to ' + st['next'] if success else 'failed the breakthrough to ' + st['next']} "
                      f"({bd['total'] * 100:g}% chance{', pill used' if use_pill else ''})"
                      + (f", lost {lost} years of lifespan" if lost else "")
                      + (", and died of it" if not success and st["fatal"] else ""))
    record_world_action('breakthrough',c['name']+(' broke through' if success else ' failed a breakthrough'),breakthrough_result_text(c['name'],dict(success=success,to=st['next'],lost=lost,died=bool(not success and st['fatal']),pill_used=bool(use_pill))),[(steamid,c)],outcome='breakthrough' if success else 'failure',importance=3 if success and c['realm_index']>=5 else 1)
    if not success and st['fatal']:storage.retire_dead(steamid)
    return {"success": success, "chance": bd["total"], "from": st["current"], "to": st["next"],
            "pill_used": bool(use_pill), "lost": lost,
            "died": bool(not success and st["fatal"])}


def breakthrough_target(key, profiles, session):
    """(steamid, freshly loaded cultivator) of the latest looked-up profile."""
    steamid = session.get("latest")
    if not steamid:
        raise logs.SteamError("No cultivator has been selected yet. Look up a Steam profile first.")
    return steamid, generator.build_cultivator(steamid, key, profiles)[3]


# ============================================================================
# Living world: persisted population, scheduled activities, offline conversations.
# ============================================================================
@storage.atomic
def initialize_world(count=2500):
    if type(count) is not int or not 1 <= count <= 10000:
        raise ValueError('Population must be between 1 and 10,000.')
    world = storage.world_state()
    with storage.world_transaction() as db:
        existing = db.execute('SELECT count(*) FROM npcs').fetchone()[0]
    if world['populated'] and existing >= count:
        initialize_region()
        initialize_living_actions()
        initialize_politics()
        return world
    rng = random.Random(world['seed'] + str(existing))
    with storage.world_transaction() as db:
        sects = [r['name'] for r in storage.sect_names()]
    while len(sects) < 20:
        name = f'{rng.choice(gamedata.SECT_ADJ)} {rng.choice(gamedata.SECT_NOUN)}'
        if name not in sects:
            sects.append(name)
    for name in sects:
        storage.sect_identity(name)
    with storage.world_transaction() as db:
        weights = [rng.uniform(.7,1.3) for _ in sects]
        for index in range(existing,count):
            sid=str(rng.randrange(10**19,10**20))
            while db.execute('SELECT 1 FROM profiles WHERE id=?',(sid,)).fetchone():
                sid=str(rng.randrange(10**19,10**20))
            s=offline_generator.random_local_settings(native=True,seed=sid,sect_names=sects)
            birth_rng=random.Random('npc-birth-v1:'+sid)
            # Common cultivators outnumber the rare ancient masters.
            realm = birth_rng.choices(range(10),weights=[45,25,14,8,4,2,1,.6,.3,.1])[0]
            lifespan = birth_rng.randint(*gamedata.REALM_LIFESPANS[realm])
            age = birth_rng.randint(16,max(16,lifespan//2))
            s.update(realm_index=realm,born_realm=realm,lifespan=lifespan,age=age,
                     birth_year=int(world['day'])//storage.DAYS_PER_YEAR-age,
                     score=birth_rng.randint(*generator.realm_power_range(realm)),
                     sect='Wanderer' if index >= int(count*.9) else birth_rng.choices(sects,weights=weights)[0],
                     missions=birth_rng.randint(0,20*(realm+1)),sect_points=birth_rng.randint(0,100*(realm+1)))
            pc = offline_generator.make_local_profile(s)
            pc['world_npc'] = True
            pc['calendar'] = {'birth_day':world['day']-age*storage.DAYS_PER_YEAR,
                              'incarnation':0,'synchronized_day':world['day'],'base_lifespan':lifespan}
            pc['activity'] = []
            storage._write_profile(db,pc)
            db.execute('INSERT INTO npcs(id,next_day,activity,location) VALUES(?,?,?,?)',
                       (s['seed'],world['day']+rng.randint(1,30),'Cultivating',s['sect']))
        db.execute('UPDATE world SET populated=1 WHERE id=1')
    storage.world_event('world', 'New cultivators join the region' if existing else 'The living world opens',
                        f'{count-existing:,} cultivators have joined; the world now contains {count:,}, including wanderers.')
    initialize_region()
    initialize_living_actions()
    initialize_politics()
    return storage.world_state()


@storage.atomic
def talk_to_cultivator(player_id,npc_id,topic):
    topics = ('Greeting','Your life','Your sect','Your activity','World news')
    if topic not in topics:
        raise logs.SteamError('Choose one of the conversation topics.')
    if player_id == npc_id:
        raise logs.SteamError('Choose another cultivator to talk to.')
    player = generator.build_cultivator(player_id,'',{})[3]
    # Steam players are validated by the controller with their API key before entering here.
    pc = storage.load_profile_cache(player_id)
    if not pc.get('calendar') or (pc.get('life') or {}).get('dead') or (player and player['death']):
        raise logs.SteamError('Select a living player cultivator before talking.')
    if pc.get('world_npc'):
        raise logs.SteamError('Choose your own cultivator, rather than an autonomous NPC, to start a conversation.')
    c = generator.build_cultivator(npc_id,'',{})[3]
    if c['death']:
        raise logs.SteamError('This cultivator has died. Their profile remains in the historical record.')
    storage.require_physical(player_id,others=(npc_id,))
    with storage.world_transaction() as db:
        npc = db.execute('SELECT * FROM npcs WHERE id=?',(npc_id,)).fetchone()
        if npc is None:
            raise logs.SteamError('That cultivator is not a world NPC.')
        day = storage.world_state()['day']
        rel = db.execute('SELECT * FROM relationships WHERE player=? AND npc=?',(player_id,npc_id)).fetchone()
        trust = rel['trust'] if rel else 0
        last = rel['last_day'] if rel else -1
        familiar = ('It is good to see you again. ' if rel and rel['last_day']>=0 else '')+recognition(player_id,npc_id,player)
        personalities = ', '.join(storage.actor_disposition(npc_id))
        if topic == 'Greeting':
            traits={p['name'] for p in c['personalities']}
            tone = ('Come, share a tale of your travels!' if 'Social' in traits else
                    'The heavens have yet to frighten me.' if 'Fearless' in traits else
                    'A brave heart makes the road less lonely.' if 'Brave' in traits else
                    'Forgive the short visit; my training awaits.' if 'Diligent' in traits else
                    'Have you seen anything unusual at the treasure stalls?' if 'Collector' in traits else
                    'May your cultivation go well.')
            reply = f"{familiar} I am {c['name']} of {c['sect']}. {tone}"
        elif topic == 'Your life':
            reply = f"I am {c['age']:,} years old, born in Year {c['birth_year']:,}. I cultivate in {c['realm']}, with {c['talent']['name']}. Others call me {personalities}."
        elif topic == 'Your sect':
            reply = f"I belong to {c['sect']}. My standing is {c['sect_status']['rank']}, with {c['sect_status']['points']:,} sect reputation."
        elif topic == 'Your activity':
            reply = f"I am {npc['activity'].lower()} at {storage.presence(npc_id)['name']}. My next plans are due around {storage.calendar_text(npc['next_day'])}."
        else:
            with storage.world_transaction() as db:
                visible=db.execute("SELECT p.name,l.name FROM ascensions r JOIN profiles p ON p.id=r.actor JOIN locations l ON l.id=r.site ORDER BY r.tick LIMIT 1").fetchone()
            news=([{'source':'Witnessed','summary':f"The sky above {visible[1]} trembles as {visible[0]} attempts Immortal Ascension."}] if visible else known_news(npc_id,1))
            reply=((('I witnessed this: ' if news[0]['source']=='Witnessed' else 'A local report says: ')+news[0]['summary']) if news else 'I have heard no recent local news.')
        if topic == 'Greeting' and last != int(day):
            trust = min(100,trust+1); last = int(day)
        db.execute('INSERT INTO relationships(player,npc,trust,last_day) VALUES(?,?,?,?) ON CONFLICT(player,npc) DO UPDATE SET trust=excluded.trust,last_day=excluded.last_day',
                   (player_id,npc_id,trust,last))
        db.execute('UPDATE relationships SET known_location=? WHERE player=? AND npc=?',(storage.presence(npc_id)['name'],player_id,npc_id))
        db.execute('INSERT INTO conversations(player,npc,day,topic,reply) VALUES(?,?,?,?,?)',(player_id,npc_id,day,topic,reply))
        # Remember trust permanently; keep a bounded transcript for each relationship.
        db.execute('DELETE FROM conversations WHERE player=? AND npc=? AND id NOT IN (SELECT id FROM conversations WHERE player=? AND npc=? ORDER BY id DESC LIMIT 30)',
                   (player_id,npc_id,player_id,npc_id))
        return dict(reply=reply,trust=trust,name=c['name'],when=storage.calendar_text(day))


def conversation_history(player_id,npc_id):
    with storage.world_transaction() as db:
        return [dict(r) for r in db.execute('SELECT * FROM conversations WHERE player=? AND npc=? ORDER BY id DESC LIMIT 30',(player_id,npc_id))]

# ============================================================================
# Designed region, offices and active-play travel.
# ============================================================================
@storage.atomic
def initialize_region():
    import json
    with storage.world_transaction() as db:
        if db.execute('SELECT initialized FROM region_meta').fetchone()[0]:
            # Population expansions add affiliations without rerolling established offices.
            seed_region_actors(db)
            initialize_frontiers(db)
            return
        population_sects = {storage.decode_profile_json(r[0])['offline']['character']['sect'] for r in db.execute('SELECT p.data FROM profiles p JOIN npcs n ON n.id=p.id')}
        storage.sect_names()
        sects=db.execute('SELECT s.* FROM sects s JOIN sect_charters c ON c.sect_id=s.id ORDER BY s.id').fetchall()
        centers = [(500,350),(500,100),(820,350),(500,600),(180,350)]
        offsets = [(-100,-50),(0,-65),(100,-50),(110,40),(70,100),(-25,95),(-110,45),(-120,-5)]
        for district,((label,color,names),(cx,cy)) in enumerate(zip(gamedata.REGION_DISTRICTS,centers)):
            for slot,(dx,dy) in enumerate(offsets):
                sect = sects[district*4+slot] if slot<4 and district*4+slot<len(sects) else None
                name = sect['name'] if sect else names[slot-4] if slot>=4 else label+' Retreat '+str(slot+1)
                db.execute('INSERT INTO locations VALUES(?,?,?,?,?,?)',
                           (f'r{district}_{slot}',name,district,cx+dx,cy+dy,sect['id'] if sect else None))
            for slot in range(8):
                a,b=sorted((f'r{district}_{slot}',f'r{district}_{(slot+1)%8}'))
                db.execute('INSERT INTO routes VALUES(?,?,?,?)',(a,b,15+(slot%5)*5,0 if district==0 else 1))
            # A shorter, riskier cross-country connection.
            db.execute('INSERT INTO routes VALUES(?,?,?,?)',(f'r{district}_1',f'r{district}_5',25,2))
        for district,central,outer in ((1,1,5),(2,3,7),(3,5,1),(4,7,3)):
            db.execute('INSERT INTO routes VALUES(?,?,?,?)',(f'r0_{central}',f'r{district}_{outer}',75+district*5,1))
        seed_region_actors(db)
        # Seed actual offices once. Future appointments never derive from reputation title.
        for sect in sects:
            members = db.execute('SELECT a.actor,p.data FROM affiliations a JOIN profiles p ON p.id=a.actor JOIN npcs n ON n.id=a.actor WHERE a.sect_id=?',(sect['id'],)).fetchall()
            def strength(row):
                pc=storage.decode_profile_json(row['data']);s=pc['offline']['character']
                return (pc.get('realm_state',{}).get('realm_index',s['realm_index']),generator.local_power_score(s),row['actor'])
            members = sorted((r for r in members if not storage.decode_profile_json(r['data']).get('life',{}).get('dead')),key=strength,reverse=True)
            seats = min(len(members),1+max(3,min(6,len(members)//25)))
            for i,row in enumerate(members[:seats]):
                db.execute('UPDATE affiliations SET office=? WHERE actor=?',('Sect Master' if i==0 else 'Elder',row['actor']))
            # Talent, earned mission record, and shared personality each contribute.
            candidates = list(members[seats:])
            for i,mentor in enumerate(members[:seats]):
                mentor_traits=set(storage.actor_disposition(mentor['actor']))
                def aptitude(row):
                    pc=storage.decode_profile_json(row['data']);s=pc['offline']['character']
                    talent=next((j for j,t in enumerate(gamedata.TALENTS) if t['name']==s['talent']),0)
                    achievements=sum(e.get('success') is True for e in pc.get('activity',[])+storage.npc_history_archive(row['actor'],20))
                    compatibility=len(mentor_traits.intersection(storage.actor_disposition(row['actor'])))
                    return (talent*3+min(achievements,20)+compatibility*2,row['actor'])
                candidates.sort(key=aptitude,reverse=True)
                for disciple in candidates[:3 if i==0 else 2]:
                    db.execute('UPDATE affiliations SET mentor=? WHERE actor=?',(mentor['actor'],disciple['actor']))
                candidates=candidates[3 if i==0 else 2:]
        initialize_frontiers(db)
        db.execute('UPDATE region_meta SET initialized=1')


def seed_region_actors(db, actor=None):
    query='SELECT p.id,p.data FROM profiles p LEFT JOIN affiliations a ON a.actor=p.id WHERE a.actor IS NULL'
    if actor is not None:query+=' AND p.id=?'
    for row in db.execute(query, (actor,) if actor is not None else ()).fetchall():
        pc=storage.decode_profile_json(row['data'])
        settings=pc.get('offline',{}).get('character',{})
        if not settings: continue  # Steam profiles attach when selected on the map.
        name=settings['sect']
        sect=storage.sect_identity(name) if name!='Wanderer' else None
        db.execute('INSERT INTO affiliations(actor,sect_id) VALUES(?,?)',(row['id'],sect['id'] if sect else None))
        place=storage.seat_location(db,sect['id']) if sect else None
        location=place[0] if place else 'r0_4'
        db.execute('INSERT OR IGNORE INTO positions VALUES(?,?)',(row['id'],location))
        personality=storage.actor_disposition(row['id'])
        db.execute('UPDATE affiliations SET loyalty=? WHERE actor=?',(90 if 'Loyal' in personality else 50,row['id']))
        db.execute('UPDATE npcs SET location=(SELECT name FROM locations WHERE id=?) WHERE id=?',(location,row['id']))


def complete_journeys(db, day):
    import json
    due=db.execute('SELECT * FROM journeys WHERE arrival<=?',(day,)).fetchall()
    locations=[dict(r) for r in db.execute('SELECT * FROM locations')] if due else []
    routes=[dict(r) for r in db.execute('SELECT * FROM routes')] if due else []
    for journey in due:
        validate_region(locations,routes,journey,None)
        if storage.load_profile_cache(journey['actor']).get('life',{}).get('dead'):
            db.execute('DELETE FROM journeys WHERE actor=?',(journey['actor'],))
            continue
        path=json.loads(journey['path'])
        db.execute('UPDATE positions SET location=? WHERE actor=?',(path[-1],journey['actor']))
        db.execute('DELETE FROM journeys WHERE actor=?',(journey['actor'],))
        db.execute('UPDATE campaign_forces SET assembled=1 WHERE actor=? AND muster=?',(journey['actor'],path[-1]))
        db.execute("UPDATE npcs SET location=(SELECT name FROM locations WHERE id=?),activity='Arrived' WHERE id=?",(path[-1],journey['actor']))
        storage.add_activity(journey['actor'],{'at':time.time(),'type':'adventure','summary':'Arrived at '+db.execute('SELECT name FROM locations WHERE id=?',(path[-1],)).fetchone()[0]+'.'})


def region_view(actor=None):
    # UI navigation normally only reads. A first visit or an overdue arrival still
    # uses the gameplay path, with all prerequisites rechecked under the writer lock.
    with storage.world_snapshot() as db:
        if not storage.region_ready(db):raise logs.SteamError('The starting region is still being prepared.')
        ready=not actor or db.execute("SELECT 1 FROM affiliations a JOIN positions p ON p.actor=a.actor WHERE a.actor=?",(actor,)).fetchone()
        due=db.execute('SELECT 1 FROM journeys WHERE arrival<=(SELECT day FROM world) LIMIT 1').fetchone()
        if ready and not due:
            if not actor or not db.execute("SELECT 1 FROM journeys j JOIN profiles p ON j.actor=p.id WHERE j.actor=? AND json_extract(p.data,'$.life.dead') IS NOT NULL",(actor,)).fetchone():
                return _region_view(actor,False)
    return _region_view(actor,True)


def _region_view(actor,prepare):
    import json
    with storage.world_transaction() as db:
        if not db.execute('SELECT initialized FROM region_meta').fetchone()[0]:
            raise logs.SteamError('The starting region is still being prepared.')
        if actor:
            pc=storage.load_profile_cache(actor)
            if not pc.get('calendar'): raise logs.SteamError('Load a cultivator before entering the map.')
            if prepare:seed_region_actors(db, actor)
            if not db.execute('SELECT 1 FROM affiliations WHERE actor=?',(actor,)).fetchone():
                db.execute('INSERT INTO affiliations(actor) VALUES(?)',(actor,))
            if prepare:db.execute('INSERT OR IGNORE INTO positions VALUES(?,?)',(actor,'r0_4'))
        day=storage.world_state()['day']
        if prepare and actor and pc.get('life',{}).get('dead'):
            db.execute('DELETE FROM journeys WHERE actor=?',(actor,))
        if prepare:complete_journeys(db,day)
        journey=db.execute('SELECT * FROM journeys WHERE actor=?',(actor,)).fetchone()
        position=db.execute('SELECT location FROM positions WHERE actor=?',(actor,)).fetchone()
        locations=[dict(r) for r in db.execute(
            'SELECT l.*,m.kind AS mine,m.yield_stones,s.name AS owner,c.kind strategic,t.name controller FROM locations l '
            'LEFT JOIN campaign_sites c ON c.site=l.id LEFT JOIN sects t ON t.id=c.owner '
            'LEFT JOIN spirit_mines m ON m.location=l.id LEFT JOIN sects s ON s.id=m.owner')]
        routes=[dict(r) for r in db.execute('SELECT * FROM routes')]
        validate_region(locations,routes,journey,position)
        affiliation=db.execute('SELECT sect_id FROM affiliations WHERE actor=?',(actor,)).fetchone()
        return dict(viewer=actor,viewer_sect=affiliation[0] if affiliation else None,locations=locations,
                    routes=routes,
                    location=position[0] if position else None,
                    journey=dict(journey) if journey else None,day=day,
                    seconds_per_day=storage.world_state()['seconds_per_day'])


def route_plan(view, destination, safe=False):
    """Dijkstra over the same graph the map draws; total duration before departure."""
    import heapq
    start=view['location']
    if destination not in {r['id'] for r in view['locations']} or not start:
        raise logs.SteamError('Choose a valid starting point and destination.')
    graph={r['id']:[] for r in view['locations']}
    for edge in view['routes']:
        for a,b in ((edge['a'],edge['b']),(edge['b'],edge['a'])):
            graph[a].append((b,edge['seconds'],edge['danger']))
    queue=[(0,0,start,[start],0)];seen=set()
    while queue:
        priority,seconds,node,path,danger=heapq.heappop(queue)
        if node in seen: continue
        seen.add(node)
        if node==destination:
            # Long journeys are compressed into the agreed 75–100 second play budget.
            return dict(path=path,seconds=min(100,seconds),road_seconds=seconds,danger=danger)
        for neighbor,duration,risk in graph[node]:
            if neighbor not in seen:
                heapq.heappush(queue,(priority+duration+(risk*1000 if safe else 0),seconds+duration,neighbor,path+[neighbor],max(danger,risk)))
    raise logs.SteamError('No road connects these locations.')


@storage.atomic
def begin_journey(actor,destination,safe=False,rng=random):
    import json
    storage.require_physical(actor)
    view=region_view(actor)
    pc=storage.load_profile_cache(actor)
    c=generator.build_cultivator(actor,'',{})[3] if pc.get('offline') else None
    if pc.get('world_npc') or pc.get('life',{}).get('dead') or (c and c['death']):
        raise logs.SteamError('Only a living player cultivator can travel.')
    if view['journey']: raise logs.SteamError('Finish the current journey first.')
    plan=route_plan(view,destination,safe=safe)
    if not plan['seconds']: raise logs.SteamError('You are already there.')
    with storage.world_transaction() as db:
        start_journey(actor,plan,view,rng=rng)
        storage.add_activity(actor,{'at':time.time(),'type':'adventure','summary':'Departed for '+next(r['name'] for r in view['locations'] if r['id']==destination)+'.'})
    return region_view(actor)


def validate_region(locations,routes,journey,position):
    import json,math
    try:
        ids={r['id'] for r in locations}
        if len(ids)!=52: raise ValueError('Expected 52 landmarks')
        for row in locations:
            if type(row['district']) is not int or not 0<=row['district']<9 or not isinstance(row['name'],str): raise ValueError('Invalid landmark')
            if any(type(row[k]) not in (int,float) or not math.isfinite(row[k]) for k in ('x','y')): raise ValueError('Invalid map coordinates')
        edges={frozenset((r['a'],r['b'])) for r in routes}
        for row in routes:
            if row['a'] not in ids or row['b'] not in ids or type(row['seconds']) is not int or not 15<=row['seconds']<=100 or type(row['danger']) is not int or not 0<=row['danger']<=3: raise ValueError('Invalid road')
        if position and position[0] not in ids: raise ValueError('Invalid position')
        if journey:
            path=json.loads(journey['path'])
            if not isinstance(path,list) or not 2<=len(path)<=len(ids) or any(not isinstance(v,str) or v not in ids for v in path): raise ValueError('Invalid journey path')
            if any(frozenset((a,b)) not in edges for a,b in zip(path,path[1:])): raise ValueError('Invalid journey road')
            if any(type(journey[k]) not in (int,float) or not math.isfinite(journey[k]) for k in ('departure','arrival')) or not 0<=journey['departure']<journey['arrival']<=1e12: raise ValueError('Invalid journey dates')
    except (ValueError,TypeError,KeyError) as exc:
        raise logs.SteamError('Invalid saved region or journey. Restore a world backup: '+str(exc)) from exc

# ============================================================================
# Events and learned consequences. Facts are immutable; reactions are idempotent.
# ============================================================================
def record_world_action(kind,title,summary,actors,*,subject=None,outcome='',importance=1,location_override=None):
    """actors: (ID, freshly loaded pre-outcome character) pairs, captured atomically."""
    with storage.world_transaction() as db:
        day=storage.world_state()['day']
        first=actors[0][0];where=location_override or storage.presence(first)
        # Encounters occur on the route, never at its endpoint.
        location=where['location'];label=where['name']
        snapshots=[]
        for sid,c in actors:
            affiliation=db.execute('SELECT sect_id,office FROM affiliations WHERE actor=?',(sid,)).fetchone()
            snapshots.append(dict(id=sid,name=c['name'],realm=c['realm_index'],sect=affiliation['sect_id'] if affiliation else None,
                                  office=affiliation['office'] if affiliation else None,location=location,score=c['score']))
        if outcome in ('death','killed'):
            victim_ids={sid for sid,c in actors if outcome=='death' or sid!=(subject or first)}
            if any(r['id'] in victim_ids and (r['realm']>=6 or r['office'] in ('Sect Master','Acting Master','Elder')) for r in snapshots):importance=max(importance,3)
        event=storage.world_event(kind,title,summary,actors=[a[0] for a in actors],sects=[r['sect'] for r in snapshots if r['sect']],location=label,visibility='local',importance=importance)
        facts=dict(actors=snapshots,subject=subject or first,outcome=outcome,location=location)
        db.execute('INSERT INTO event_facts VALUES(?,?)',(event,json.dumps(facts)))
        witnesses={r[0] for r in db.execute('SELECT p.actor FROM positions p LEFT JOIN journeys j ON j.actor=p.actor JOIN profiles x ON x.id=p.actor WHERE p.location=? AND j.actor IS NULL AND json_extract(x.data,\'$.life.dead\') IS NULL',(location,))} if location else set()
        # Routine errands attract a few onlookers, not every resident of a town.
        if importance<2 and len(witnesses)>8:witnesses=set(random.Random('witness:'+str(event)).sample(sorted(witnesses),8))
        witnesses.update(a[0] for a in actors)
        for observer in witnesses:learn_event(db,event,observer,day,'Witnessed',facts)
        if importance>=2 and location:
            # Ordinary news stays regional or reaches the participants' sects.
            # Exceptional achievements and major events still travel worldwide.
            district=db.execute('SELECT district FROM locations WHERE id=?',(location,)).fetchone()[0]
            sects={r['sect'] for r in snapshots if r['sect']}
            for place in db.execute('SELECT id,district,sect_id FROM locations WHERE id<>?',(location,)):
                if importance<3 and outcome!='upset' and place['district']!=district and place['sect_id'] not in sects:continue
                delay=(.4 if place['district']==district else 2)+random.Random(str(event)+place['id']).random()
                db.execute('INSERT INTO news_queue VALUES(?,?,?)',(event,place['id'],day+delay))
        if importance>=3:
            gate=db.execute('SELECT next_major FROM living_meta').fetchone()[0]
            if day>=gate:
                # Only actual notable outcomes become major news; the timer creates nothing.
                db.execute("UPDATE world_events SET visibility='public' WHERE id=?",(event,))
                delay=random.Random('major:'+str(event)).uniform(6,18)
                db.execute('UPDATE living_meta SET next_major=?',(day+delay,))
        return event


def learn_event(db,event,observer,day,source,facts=None):
    inserted=db.execute('INSERT OR IGNORE INTO event_knowledge VALUES(?,?,?,?)',(observer,event,day,source)).rowcount
    if not inserted:return
    if source=='Local report':
        storage.queue_memory_cleanup(db,observer,day)
    if facts is None:
        row=db.execute('SELECT facts FROM event_facts WHERE event=?',(event,)).fetchone()
        if not row:return
        facts=json.loads(row[0])
    subject=facts['subject']
    if observer==subject:return
    # Knowledge insertion and its effects are atomic. Old markers remain a guard
    # until bounded cleanup removes them; no duplicate ledger is written now.
    if db.execute('SELECT 1 FROM event_archives WHERE event=?',(event,)).fetchone():return
    if db.execute("SELECT 1 FROM event_effects WHERE event=? AND actor=? AND effect='relationship'",(event,observer)).fetchone():return
    outcome=facts['outcome']
    respect=12 if outcome=='upset' else 3 if outcome in ('victory','mission_success','breakthrough') else 0
    fear=8 if outcome=='killed' else 0
    hostility=2 if outcome=='killed' else 0
    trust=-2 if outcome=='loss' else 0
    if outcome=='loss':hostility=2
    if outcome=='killed':
        observer_sect=db.execute('SELECT sect_id FROM affiliations WHERE actor=?',(observer,)).fetchone()
        observer_sect=observer_sect[0] if observer_sect else None
        victim=next((a for a in facts['actors'] if a['id']!=subject),None)
        victor=next((a for a in facts['actors'] if a['id']==subject),None)
        if victim and observer_sect and victim['sect']==observer_sect:hostility=20;trust=-8
        elif victor and observer_sect and victor['sect']==observer_sect:hostility=0;respect=4
    if not (respect or fear or hostility or trust):return
    # Respect/fear/hostility are separate from the general reputation ledger.
    db.execute('INSERT OR IGNORE INTO relationships(player,npc) VALUES(?,?)',(subject,observer))
    db.execute('UPDATE relationships SET respect=min(100,respect+?),fear=min(100,fear+?),hostility=min(100,hostility+?),trust=max(-100,min(100,trust+?)) WHERE player=? AND npc=?',(respect,fear,hostility,trust,subject,observer))


def spread_news(db,day):
    """Bound recipient work, retaining unfinished waves transactionally."""
    remaining=128
    for news in db.execute('SELECT * FROM news_queue WHERE due<=? ORDER BY due,event,location LIMIT 80',(day,)).fetchall():
        facts_row=db.execute('SELECT facts FROM event_facts WHERE event=?',(news['event'],)).fetchone()
        facts=json.loads(facts_row[0]) if facts_row else None
        rows=db.execute("""SELECT p.actor FROM positions p JOIN profiles x ON x.id=p.actor
            LEFT JOIN journeys j ON j.actor=p.actor
            WHERE p.location=? AND j.actor IS NULL AND json_extract(x.data,'$.life.dead') IS NULL
            AND NOT EXISTS(SELECT 1 FROM event_knowledge k WHERE k.actor=p.actor AND k.event=?)
            ORDER BY p.actor LIMIT ?""",(news['location'],news['event'],remaining)).fetchall()
        for row in rows:learn_event(db,news['event'],row[0],day,'Local report',facts)
        if len(rows)<remaining:
            db.execute('DELETE FROM news_queue WHERE event=? AND location=?',(news['event'],news['location']))
        remaining-=len(rows)
        if not remaining:break
    metrics=getattr(storage._world_local,'batch_metrics',None)
    if metrics is not None:metrics['news_delivered']=metrics.get('news_delivered',0)+128-remaining


def known_news(actor,limit=5):
    with storage.world_transaction() as db:
        return [dict(r) for r in db.execute('SELECT e.*,k.source FROM event_knowledge k JOIN world_events e ON e.id=k.event WHERE k.actor=? ORDER BY e.day DESC,e.id DESC LIMIT ?',(actor,limit))]


def recognition(player_id,npc_id,player):
    with storage.world_transaction() as db:
        me=db.execute('SELECT * FROM affiliations WHERE actor=?',(player_id,)).fetchone()
        them=db.execute('SELECT * FROM affiliations WHERE actor=?',(npc_id,)).fetchone()
        if me and them and me['sect_id'] and me['sect_id']==them['sect_id']:
            if me['office'] in ('Sect Master','Acting Master','Elder'):
                return f"I pay my respects, {me['office']}. Your service to our sect is known."
            if player and player['sect_status']['points']>=5000:
                return 'Honored guardian and protector, our sect owes you deep respect.'
            if player and player['sect_status']['points']>=1200:
                return 'Respected senior, your standing in our sect precedes you.'
        rel=db.execute('SELECT * FROM relationships WHERE player=? AND npc=?',(player_id,npc_id)).fetchone()
        if rel and rel['hostility']>=20:return 'Your recent deeds have made me wary. Keep your distance.'
        if rel and rel['fear']>=8:return 'I have heard what you are capable of. I will speak carefully.'
        if rel and rel['respect']>=12:return 'Your achievements have earned my respect.'
        if player and player['reputation']['points']>=500:return 'Your reputation has reached even these roads.'
        return 'We have spoken before.' if rel and rel['last_day']>=0 else 'I do not believe we have met.'


@storage.atomic
def initialize_living_actions():
    with storage.world_transaction() as db:
        # Additive, backward-compatible indexes, checked once at world startup.
        # The existing primary keys start with actor/disciple, not event.
        db.execute("""CREATE INDEX IF NOT EXISTS public_chronicle_dates ON world_events(day DESC,id DESC)
            WHERE visibility IN ('public','rumor') AND importance>=2""")
        db.execute('CREATE INDEX IF NOT EXISTS knowledge_event_lookup ON event_knowledge(event)')
        db.execute('CREATE INDEX IF NOT EXISTS political_event_lookup ON political_events(event)')
        db.execute('CREATE INDEX IF NOT EXISTS mentor_reward_event_lookup ON mentor_rewards(event)')
        if not storage.region_ready(db) or db.execute('SELECT initialized FROM living_meta').fetchone()[0]:return
        w=storage.world_state()
        for row in db.execute('SELECT id,next_day FROM npcs WHERE next_day<1e30').fetchall():
            delay=random.Random('schedule:'+row['id']).uniform(30,600)/w['seconds_per_day']
            db.execute('UPDATE npcs SET next_day=? WHERE id=?',(max(w['day'],min(row['next_day'],w['day']+delay)),row['id']))
        db.execute('UPDATE living_meta SET initialized=1,last_cleanup=?',(w['day'],))


def npc_weights(personalities,injured=False):
    weights=[0]*6
    for i,name in enumerate(personalities):
        for j,value in enumerate(gamedata.NPC_ACTIVITY_WEIGHTS[name]):weights[j]+=value*(2 if i==0 else 1)
    if injured:weights[2]=weights[4]=0;weights[0]*=2
    return weights


def _peer_feelings(db,actor,peers):
    # The (player,npc) primary key supports these bounded lookups. Scanning by
    # npc alone grows with the entire world's relationship history.
    ids=[p['id'] for p in peers]
    if not ids:return {}
    marks=','.join('?' for _ in ids)
    return {r['player']:dict(r) for r in db.execute(
        'SELECT * FROM relationships WHERE npc=? AND player IN ('+marks+')',(actor,*ids))}


def _npc_step(row,seed):
    import combat
    sid=row['id'];rng=random.Random(f"{seed}:{sid}:{row['steps']}")
    info,friends,_,c=generator.build_cultivator(sid,'',{})
    with storage.world_transaction() as db:
        day=storage.world_state()['day'];pace=storage.world_state()['seconds_per_day']
        if c['death']:
            storage.retire_dead(sid);return
        here=storage.presence(sid)
        if here['state']!='present':
            journey=db.execute('SELECT arrival FROM journeys WHERE actor=?',(sid,)).fetchone()
            db.execute('UPDATE npcs SET next_day=? WHERE id=?',(max(day+.01,journey[0] if journey else day+.1),sid));return
        import warfare
        if warfare.ritual_duty(db,sid,day) or warfare.duty(db,sid,day):
            return
        guard=db.execute('SELECT location FROM mine_wardens WHERE actor=?',(sid,)).fetchone()
        if guard and here['location']!=guard[0]:
            view=region_view(sid)
            plan=route_plan(view,guard[0],safe=True)
            start_journey(sid,plan,view,encounters=False)
            db.execute("UPDATE npcs SET next_day=?,activity='Travelling to guard post',steps=steps+1 WHERE id=?",
                       (day+plan['seconds']/pace,sid))
            return
        if political_duty(sid):return
        if not guard:
            npc_membership_choices(sid,rng)
        if storage.presence(sid)['state']!='present':
            db.execute('UPDATE npcs SET next_day=? WHERE id=?',(day+60/storage.world_state()['seconds_per_day'],sid));return
        if storage.profile_field(sid,'sect_override',c['sect'])!=c['sect']:
            c=generator.build_cultivator(sid,'',{})[3]
        personality=storage.actor_disposition(sid)
        import pavilion_shop
        if not guard and pavilion_shop.shop_duty(db,sid,c,personality,here,day,rng):
            return
        mission=storage.profile_field(sid,'npc_mission')
        if mission:
            if not isinstance(mission,dict):mission={}
            status=storage.ensure_sect(sid,c)
            offer=next((o for o in status.get('offers',[]) if o['id']==mission.get('offer')),None)
            valid=(c['sect']!='Wanderer' and status['identity']['id']==mission.get('sect') and offer is not None)
            if valid and offer.get('location_id')==here['location'] and status['ready_at']<=time.time():
                if not offer['hard'] or not storage.injury_state(sid):
                    perform_sect_mission(sid,c,offer['id'],rng=rng)
                    pc=storage.load_profile_cache(sid);pc.pop('npc_mission',None);storage.save_profile_cache(pc,durable=True)
                    if pc.get('life',{}).get('dead'):storage.retire_dead(sid)
                    else:db.execute("UPDATE npcs SET next_day=?,activity='Sect duties',steps=steps+1 WHERE id=?",(day+rng.uniform(120,480)/pace,sid))
                    return
            # Cancel stale, interrupted, or no longer feasible commitments. Existing
            # duties/healing above can supersede a mission; never teleport to finish.
            pc=storage.load_profile_cache(sid);pc.pop('npc_mission',None);storage.save_profile_cache(pc,durable=True)
        weights=npc_weights(personality,bool(storage.injury_state(sid)))
        if c['spirit_stones']<50 and c['sect']!='Wanderer':weights[1]*=1.5
        action=rng.choices(('Cultivating','Sect duties','Adventuring','Travelling','Duelling','Socializing'),weights=weights)[0]
        if guard and action in ('Travelling','Adventuring','Sect duties'):
            action='Guarding the mine'
        delay=rng.uniform(120,480)/pace
        if action=='Cultivating':
            pc=storage.load_profile_cache(sid);s=pc['offline']['character'];gain=rng.randint(1,3)
            if 'power_offset' in s:s['power_offset']+=gain
            else:s['score']+=gain
            storage.save_profile_cache(pc,durable=True)
            if political_actor(sid)['mentor']:
                try:mentor_training(sid)
                except logs.SteamError:pass
                try:claim_mentor_reward(sid)
                except logs.SteamError:pass
            c=generator.build_cultivator(sid,'',{})[3]
            if (c['realm_index']!=8 or warfare.available_escort(db,sid)) and not storage.injury_state(sid) and breakthrough_status(c)['can'] and rng.random()<(.65 if 'Ambitious' in personality else .25):attempt_breakthrough(sid,c,use_pill=c['realm_index']<8 and bool(c['pavilion']['items'].get(BREAKTHROUGH_PILL_ID)),rng=rng)
        elif action=='Sect duties':
            if c['sect']=='Wanderer':action='Resting'
            else:
                board=sect_board(sid,c)
                if board['offers'] and board['ready_at']<=time.time():
                    offers=[o for o in board['offers'] if not o['hard']] if 'Cautious' in personality or storage.injury_state(sid) else board['offers']
                    if offers:
                        offer=rng.choice(offers)
                        if offer.get('location_id') and offer['location_id']!=here['location']:
                            view=region_view(sid);plan=route_plan(view,offer['location_id'],safe='Cautious' in personality)
                            start_journey(sid,plan,view,encounters=True,rng=rng)
                            pc=storage.load_profile_cache(sid);pc['npc_mission']={'offer':offer['id'],'sect':board['identity']['id']};storage.save_profile_cache(pc,durable=True)
                            delay=plan['seconds']/pace+.01;action='Travelling to mission'
                        else:perform_sect_mission(sid,c,offer['id'],rng=rng)
        elif action=='Adventuring':perform_adventure(sid,c,info,friends,'',rng=rng)
        elif action=='Travelling':
            view=region_view(sid)
            choices=[r for r in view['locations'] if r['id']!=here['location']]
            if 'Loyal' in personality:
                home=storage.seat_location(db,storage.sect_identity(c['sect'])['id']) if c['sect']!='Wanderer' else None
                dest=home[0] if home and home[0]!=here['location'] and rng.random()<.6 else rng.choice(choices)['id']
            else:dest=rng.choice(choices)['id']
            plan=route_plan(view,dest,safe='Cautious' in personality)
            start_journey(sid,plan,view,encounters=True,rng=rng)
            delay=plan['seconds']/pace+.01
        elif action in ('Duelling','Socializing'):
            peers=storage.people_here(sid)['people']
            if action=='Duelling' and db.execute('SELECT 1 FROM ascensions LIMIT 1').fetchone():
                channeling={r[0] for r in db.execute('SELECT actor FROM ascensions')}
                peers=[p for p in peers if p['id'] not in channeling]
            if peers:
                feelings=_peer_feelings(db,sid,peers)
                peer_weights=[1+max(0,feelings.get(p['id'],{}).get('trust' if action=='Socializing' else 'hostility',0))/10 for p in peers]
                if action=='Duelling' and 'Cautious' in personality:
                    peer_weights=[0 if feelings.get(p['id'],{}).get('fear',0)>=50 else w for p,w in zip(peers,peer_weights)]
                if not any(peer_weights):peer_weights=[1]*len(peers);action='Socializing'
                other=rng.choices(peers,weights=peer_weights)[0]['id']
                if action=='Socializing':
                    db.execute('INSERT OR IGNORE INTO relationships(player,npc) VALUES(?,?)',(sid,other))
                    db.execute('UPDATE relationships SET trust=min(100,trust+1),last_day=? WHERE player=? AND npc=?',(int(day),sid,other))
                elif not storage.injury_state(other):
                    mode='Sparring' if 'Cautious' in personality else 'Competitive'
                    if 'Loyal' not in personality and any(x in personality for x in ('Ambitious','Schemer')) and rng.random()<.08:mode='Lethal'
                    # Do not create forced off-screen player duels; nearby list is NPC-only.
                    opponent=generator.build_cultivator(other,'',{})[3]
                    if not opponent['death'] and combat.duel_ready(sid,other):combat.perform_battle([sid,other],'',{},rng=rng,mode=mode)
            else:action='Resting'
        if storage.profile_field(sid,'life',{}).get('dead'):
            storage.retire_dead(sid);return
        db.execute('UPDATE npcs SET next_day=?,activity=?,steps=steps+1 WHERE id=?',(day+delay,action,sid))
        storage.add_activity(sid,{'at':time.time(),'type':'adventure','summary':action+' at '+here['name']+'.'})

# ============================================================================
# Journeys and choice-based encounters. World time stops while a choice is pending.
# ============================================================================
def start_journey(actor,plan,view,*,encounters=True,rng=random):
    import uuid
    with storage.world_transaction() as db:
        if db.execute('SELECT 1 FROM ascensions WHERE actor=?',(actor,)).fetchone():return
        seconds=plan['seconds'];depart=view['day'];arrival=depart+seconds/view['seconds_per_day']
        trigger=depart+(arrival-depart)*.5 if encounters and plan['danger'] and rng.random()<.08*plan['danger'] else None
        db.execute('INSERT INTO journeys(actor,path,departure,arrival,encounter_day) VALUES(?,?,?,?,?)',(actor,json.dumps(plan['path']),depart,arrival,trigger))
        db.execute("UPDATE npcs SET activity='Travelling' WHERE id=?",(actor,))


def open_due_encounter(db,day):
    import uuid
    journey=db.execute('SELECT * FROM journeys WHERE encounter_day IS NOT NULL AND encounter_day<=? ORDER BY encounter_day,actor LIMIT 1',(day,)).fetchone()
    if not journey:return False
    validate_region([dict(r) for r in db.execute('SELECT * FROM locations')],[dict(r) for r in db.execute('SELECT * FROM routes')],journey,None)
    actor=journey['actor'];pc=storage.load_profile_cache(actor)
    if pc.get('life',{}).get('dead'):
        storage.retire_dead(actor);return False
    # Probabilities are persisted once and displayed before any choice is made.
    rng=random.Random(f"encounter:{actor}:{journey['departure']}")
    names=('a territorial spirit beast','a bandit patrol','a venomous marsh beast')
    personality=storage.actor_disposition(actor)
    c=generator.build_cultivator(actor,'',{})[3]
    if c['death']:
        storage.retire_dead(actor);return False
    enemy_score=max(25,c.get('healthy_score',c['score']))*rng.uniform(.65,1.05)
    win=(c['score']+25)**2/((c['score']+25)**2+(enemy_score+25)**2)
    escape=(.85 if 'Cautious' in personality else .7)-(.1 if storage.injury_state(actor) else 0)
    data=dict(enemy=rng.choice(names),enemy_score=round(enemy_score),escape=escape,win=max(.05,min(.95,win)),death_on_loss=.05)
    if pc.get('world_npc'):
        where=storage.presence(actor)
        # NPCs make the same kinds of choices autonomously; only player choices pause time.
        cautious='Cautious' in personality or bool(storage.injury_state(actor))
        choice='Escape' if cautious or rng.random()<.5 else 'Fight'
        outcome='escaped';text=c['name']+' escaped a road threat.'
        if choice=='Escape' and rng.random()>=data['escape']:
            storage.injure(actor,'Road escape');outcome='injured';text=c['name']+' was injured escaping a road threat.'
        elif choice=='Fight':
            if rng.random()<data['win']:
                pc=storage.load_profile_cache(actor);pc.setdefault('wallet',{})['spirit_stones']=storage.read_spirit_stones(actor)+25
                storage.save_profile_cache(pc,durable=True);outcome='victory';text=c['name']+' overcame a road threat and earned 25 Spirit Stones.'
            elif rng.random()<data['death_on_loss']:
                storage.mark_dead(actor,c,'travel_encounter',circumstances=f"was killed fighting {data['enemy']}");outcome='death';text=c['name']+' died fighting a road threat.'
            else:
                storage.injure(actor,'Road encounter');outcome='injured';text=c['name']+' survived a road fight with injuries.'
        if outcome in ('death','injured'):db.execute('DELETE FROM journeys WHERE actor=?',(actor,))
        else:db.execute('UPDATE journeys SET encounter_day=NULL WHERE actor=?',(actor,))
        record_world_action('encounter',c['name']+' met danger on the road',text,[(actor,c)],outcome=outcome,importance=2 if outcome=='death' else 1,location_override=where)
        storage.add_activity(actor,{'at':time.time(),'type':'adventure','outcome':outcome,'summary':text})
        return False
    db.execute('INSERT INTO encounters VALUES(?,?,?,?)',(uuid.uuid4().hex,actor,day,json.dumps(data)))
    db.execute('UPDATE journeys SET encounter_day=NULL WHERE actor=?',(actor,))
    return True


@storage.atomic
def resolve_encounter(encounter_id,choice,key='',profiles=None,rng=random):
    if choice not in ('Retreat','Escape','Fight'):raise logs.SteamError('Choose retreat, escape or fight.')
    with storage.world_transaction() as db:
        row=db.execute('SELECT * FROM encounters WHERE id=?',(encounter_id,)).fetchone()
        if not row:raise logs.SteamError('That encounter has already been resolved.')
        actor=row['actor'];data=storage.pending_encounter()
        if not data or data['id']!=encounter_id:raise logs.SteamError('Resolve the first pending encounter.')
        odds=data['data'];c=generator.build_cultivator(actor,key,profiles or {})[3]
        if c['death']:
            storage.retire_dead(actor);return dict(text='The journey ends with this cultivator’s death.',actor=actor)
        encounter_place=storage.presence(actor)
        outcome='retreated';text='You turned back safely. The journey was cancelled.'
        continue_trip=False
        if choice=='Escape':
            continue_trip=rng.random()<odds['escape']
            if continue_trip:outcome='escaped';text='You slipped past the danger and continued your journey.'
            else:outcome='injured';storage.injure(actor,'Failed escape');text='Escape failed. You were injured and forced to return to your departure point.'
        elif choice=='Fight':
            if rng.random()<odds['win']:
                continue_trip=True;outcome='victory'
                pc=storage.load_profile_cache(actor);pc.setdefault('wallet',{})['spirit_stones']=storage.read_spirit_stones(actor)+25
                storage.save_profile_cache(pc,durable=True)
                text='You overcame the threat, found 25 Spirit Stones, and continued your journey.'
            elif rng.random()<odds['death_on_loss']:
                outcome='death';storage.mark_dead(actor,c,'travel_encounter',circumstances=f"was killed fighting {odds['enemy']}");text='The road encounter ended your life. Seek rebirth through Adventure.'
            else:outcome='injured';storage.injure(actor,'Road encounter');text='You survived the fight with an injury and returned to your departure point.'
        record_world_action('encounter',c['name']+' faced a road encounter',text,[(actor,c)],outcome=outcome,importance=1,location_override=encounter_place)
        if not continue_trip:db.execute('DELETE FROM journeys WHERE actor=?',(actor,))
        db.execute('DELETE FROM encounters WHERE id=?',(encounter_id,))
        storage.add_activity(actor,{'at':time.time(),'type':'adventure','summary':text})
        return dict(text=text,actor=actor,outcome=outcome)


@storage.atomic
def advance_world(elapsed_seconds, *, max_work_seconds=None):
    import math
    if type(elapsed_seconds) not in (int,float) or not math.isfinite(elapsed_seconds) or not 0<=elapsed_seconds<=1e12:raise ValueError('Elapsed play time must be finite and nonnegative.')
    if max_work_seconds is not None and (type(max_work_seconds) not in (int,float) or not math.isfinite(max_work_seconds) or max_work_seconds<=0):raise ValueError('Work budget must be positive and finite.')
    with storage.world_transaction() as db:
        deadline=None if max_work_seconds is None else time.perf_counter()+max_work_seconds
        world=storage.world_state()
        if db.execute('SELECT 1 FROM encounters LIMIT 1').fetchone():
            return dict(world,encounter=storage.pending_encounter())
        target=world['day']+(elapsed_seconds+world['pending_seconds'])/world['seconds_per_day']
        if target>1e12:raise logs.SteamError('Calendar advancement exceeds the supported range.')
        processed=0;yielded=False
        metrics={'npc_decisions':0,'events':0};storage._world_local.batch_metrics=metrics
        while processed<200:
            if processed and deadline is not None and time.perf_counter()>=deadline:
                yielded=True;break
            npc=db.execute('SELECT * FROM npcs WHERE next_day<=? ORDER BY next_day,id LIMIT 1',(target,)).fetchone()
            arrival=db.execute('SELECT min(arrival) FROM journeys WHERE arrival<=?',(target,)).fetchone()[0]
            encounter=db.execute('SELECT min(encounter_day) FROM journeys WHERE encounter_day<=?',(target,)).fetchone()[0]
            governance=db.execute('SELECT min(next_tick) FROM sect_governance WHERE next_tick<=?',(target,)).fetchone()[0]
            payroll=db.execute('SELECT due,sect_id FROM sect_payroll WHERE due<=? ORDER BY due,sect_id LIMIT 1',(target,)).fetchone()
            ritual=db.execute('SELECT actor,tick FROM ascensions WHERE tick<=? ORDER BY tick LIMIT 1',(target,)).fetchone()
            due=[v for v in (ritual['tick'] if ritual else None,payroll['due'] if payroll else None,npc['next_day'] if npc else None,arrival,encounter,governance) if v is not None]
            if not due:break
            next_day=max(storage.world_state()['day'],min(due))
            db.execute('UPDATE world SET day=? WHERE id=1',(next_day,))
            if encounter is not None and encounter<=next_day and open_due_encounter(db,next_day):
                # Choice encounters discard ordinary elapsed time, but an awarded cultivation
                # day must survive the interruption, including closing and reopening the game.
                db.execute("""UPDATE world SET pending_seconds=max(0,
                    (coalesce((SELECT skip_until FROM cultivation_clock WHERE id=1),0)-day)*seconds_per_day)""")
                metrics['events']=processed
                return dict(storage.world_state(),encounter=storage.pending_encounter())
            complete_journeys(db,next_day)
            if ritual and ritual['tick']<=next_day:
                import warfare
                warfare.ritual_tick(db,ritual['actor'],next_day)
            if governance is not None and governance<=next_day:
                politics_tick(next_day,limit=1 if deadline is not None else -1)
                if deadline is not None:
                    processed+=1
                    continue
            if payroll and payroll['due']<=next_day:
                pay_sect_salaries(payroll['sect_id'],next_day)
            if npc and npc['next_day']<=next_day:
                _npc_step(dict(npc),world['seed']);metrics['npc_decisions']+=1
            processed+=1
        metrics['events']=processed
        pending=0
        if processed==200 or yielded:
            reached=storage.world_state()['day'];pending=max(0,(target-reached)*world['seconds_per_day']);target=reached
        db.execute('UPDATE world SET day=?,pending_seconds=? WHERE id=1',(target,pending))
        complete_journeys(db,target)
        spread_news(db,target)
        prune_routine_events(db,target)
        # Backlog must never starve retention. One bounded round-robin job during
        # catch-up preserves simulation priority without abandoning cleanup.
        storage.maintain_storage(db,target,max_jobs=1 if pending>1e-6 else 8)
        db.execute('DELETE FROM injuries WHERE until_day<=?',(target,))
        ritual=db.execute('SELECT p.name,l.name,z.ends FROM ascensions z JOIN profiles p ON p.id=z.actor JOIN locations l ON l.id=z.site ORDER BY z.tick LIMIT 1').fetchone()
        return dict(storage.world_state(),encounter=None,ritual_notice=(f'{ritual[0]} is ascending at {ritual[1]} · {max(0,ritual[2]-target):.1f} days remaining' if ritual else ''))



def prune_routine_events(db,day):
    # Preserve significant history permanently; routine witnesses need a bounded memory.
    last=db.execute('SELECT last_cleanup FROM living_meta').fetchone()[0]
    if day<last+1:return
    # Rewarded achievements remain auditable; keeping the event also prevents SQLite
    # from reusing its integer ID after routine-history pruning.
    old=[r[0] for r in db.execute('SELECT id FROM world_events e WHERE importance<2 AND day<? AND NOT EXISTS (SELECT 1 FROM mentor_rewards r WHERE r.event=e.id) ORDER BY e.id LIMIT 100',(day-12,))]
    for event in old:
        for table in ('news_queue','event_knowledge','event_effects','event_facts','event_archives'):
            db.execute('DELETE FROM '+table+' WHERE event=?',(event,))
        db.execute('DELETE FROM world_events WHERE id=?',(event,))
    # Continue a large cleanup on the next tick, releasing the world lock between chunks.
    if len(old)<100:db.execute('UPDATE living_meta SET last_cleanup=?',(day,))

# ============================================================================
# Sect membership and governance. All changes use the same world transaction.
# ============================================================================
def political_seconds(seconds):
    return seconds/storage.world_state()['seconds_per_day']


def political_actor(actor):
    """Read an actor's current identity/strength without network calls or rerolling."""
    pc=storage.load_profile_cache(actor)
    s=pc.get('offline',{}).get('character',{})
    incarnation=pc.get('life',{}).get('incarnation') or {}
    with storage.world_transaction() as db:
        row=db.execute('SELECT a.*,p.name FROM profiles p LEFT JOIN affiliations a ON a.actor=p.id WHERE p.id=?',(actor,)).fetchone()
        if not row:raise logs.SteamError('Unknown cultivator.')
        result=dict(row);result['actor']=actor
        result['dead']=bool(pc.get('life',{}).get('dead'))
        realm=pc.get('realm_state',{}).get('realm_index',s.get('realm_index',0)) or 0
        result['realm']=realm
        # Steam-backed strength uses already saved training data, never a network refresh.
        if s:power=generator.local_power_score(s,talent_name=incarnation.get('talent',s['talent']))
        else:
            measured=db.execute('SELECT power FROM actor_measures WHERE actor=?',(actor,)).fetchone()
            power=measured[0] if measured else max(1,gamedata.REALMS[realm][0])
        injury=storage.injury_state(actor)
        result['power']=max(1,power*(injury['factor'] if injury else 1))
        result['standing']=pc.get('sect_memberships',{}).get(result['sect_id'],{}).get('points',gamedata.SECT_INITIAL_REPUTATION[realm])
        result['talent']=incarnation.get('talent',s.get('talent','Regular Martial Body'))
        result['personalities']=storage.actor_disposition(actor)
        result['npc']=bool(pc.get('world_npc'))
        return result


def initialize_politics():
    with storage.world_transaction() as db:
        if not storage.region_ready(db):return
        day=storage.world_state()['day'];pace=storage.world_state()['seconds_per_day']
        for sect in storage.sect_names():
            delay=random.Random('politics:'+sect['id']).uniform(1800,5400)/pace
            db.execute('INSERT OR IGNORE INTO sect_governance(sect_id,next_tick,next_plot) VALUES(?,?,?)',(sect['id'],day,day+delay))
            opened=db.execute('INSERT OR IGNORE INTO sect_payroll(sect_id,due) VALUES(?,?)',
                              (sect['id'],day+1800/pace)).rowcount
            if opened:
                db.execute('UPDATE sect_governance SET treasury=treasury+10000 WHERE sect_id=?',(sect['id'],))
        import warfare
        warfare.initialize(db,day,pace)
        db.execute('INSERT OR IGNORE INTO membership_terms(actor,next_salary,npc_review) SELECT actor,?,? FROM affiliations',(day+1800/pace,day+14400/pace))
        db.execute("INSERT OR IGNORE INTO positions(actor,location) SELECT a.actor,coalesce(l.id,'r0_4') FROM affiliations a LEFT JOIN locations l ON l.sect_id=a.sect_id")


def ensure_member_term(actor):
    with storage.world_transaction() as db:
        existing=db.execute('SELECT * FROM membership_terms WHERE actor=?',(actor,)).fetchone()
        if existing:return dict(existing)
        day=storage.world_state()['day']
        db.execute('INSERT OR IGNORE INTO membership_terms(actor,next_salary,npc_review) VALUES(?,?,?)',(actor,day+political_seconds(gamedata.SECT_SALARY_SECONDS),day+political_seconds(14400)))
        return dict(db.execute('SELECT * FROM membership_terms WHERE actor=?',(actor,)).fetchone())


def political_event(sect,kind,text,*,actor=None,plot=None,public=True,data=None):
    with storage.world_transaction() as db:
        # Routine sect reports remain in sect affairs; the world chronicle is reserved for major changes.
        major=kind in ('Council abdication','Appointment','Elder assassinated','Sect civil conflict','Takeover succeeded','Takeover failed','Conspiracy exposed')
        sect_row=db.execute('SELECT name FROM sects WHERE id=?',(sect,)).fetchone()
        sect_name=sect_row['name'] if sect_row else sect
        event=storage.world_event('politics',kind,f'{sect_name} — {text}',actors=[actor] if actor and public else [],sects=[sect],importance=2,visibility=('public' if major else 'local') if public else 'hidden')
        facts=dict(data or {},sect_id=sect,actor=actor,kind=kind)
        day=storage.world_state()['day']
        db.execute('INSERT INTO political_events(sect_id,plot,event,day,kind,data,public) VALUES(?,?,?,?,?,?,?)',(sect,plot,event,day,kind,json.dumps(facts),int(public)))
        if public:
            # Official sect reports can be discussed; private organizers are never inferred here.
            db.execute("INSERT OR IGNORE INTO event_knowledge(actor,event,learned_day,source) SELECT a.actor,?,?,'Sect report' FROM affiliations a JOIN profiles p ON p.id=a.actor WHERE a.sect_id=? AND json_extract(p.data,'$.life.dead') IS NULL",(event,day,sect))
        return event


def wallet_transfer(sender,recipient,amount):
    if type(amount) is not int or amount<=0:raise logs.SteamError('Spirit Stone amount must be a positive whole number.')
    if sender==recipient:raise logs.SteamError('Choose another cultivator.')
    if storage.read_spirit_stones(sender)<amount:raise logs.SteamError('Not enough Spirit Stones.')
    for actor,delta in ((sender,-amount),(recipient,amount)):
        pc=storage.load_profile_cache(actor);pc.setdefault('wallet',{})['spirit_stones']=storage.read_spirit_stones(actor)+delta
        storage.save_profile_cache(pc,durable=True)


def leave_penalty(actor,sect,office,mentor):
    penalty=15 if office!='Member' or mentor else 5
    with storage.world_transaction() as db:
        for row in db.execute("SELECT a.actor FROM affiliations a JOIN profiles p ON p.id=a.actor WHERE a.sect_id=? AND a.actor<>? AND json_extract(p.data,'$.life.dead') IS NULL",(sect,actor)).fetchall():
            db.execute('INSERT OR IGNORE INTO relationships(player,npc) VALUES(?,?)',(actor,row[0]))
            db.execute('UPDATE relationships SET respect=max(-100,respect-?),trust=max(-100,trust-?) WHERE player=? AND npc=?',(penalty,penalty,actor,row[0]))
        db.execute('INSERT INTO sect_departures(actor,sect_id,day,office,penalty) VALUES(?,?,?,?,?)',(actor,sect,storage.world_state()['day'],office,penalty))
    return penalty


@storage.atomic
def change_sect(actor,target_id=None,*,repair=False,npc=False):
    state=political_actor(actor);term=ensure_member_term(actor);day=storage.world_state()['day']
    if state['dead']:raise logs.SteamError('Seek rebirth before changing sects.')
    storage.require_physical(actor)
    target=next((s for s in storage.sect_catalog() if s['id']==target_id),None) if target_id else None
    if target_id and not target:raise logs.SteamError('Choose one of the twenty registered sects.')
    with storage.world_transaction() as db:
        registered=bool(db.execute('SELECT 1 FROM sect_charters WHERE sect_id=?',(state['sect_id'],)).fetchone())
        if repair and (registered or term['repair_used'] or not target):raise logs.SteamError('This membership does not qualify for the one-time correction.')
        if target_id==state['sect_id']:raise logs.SteamError('You already belong to that sect.')
        if not repair and day<term['ready_day']:raise logs.SteamError('Wait two hours of active play between voluntary sect changes.')
        if npc and state['sect_id'] and 'Loyal' in state['personalities']:raise logs.SteamError('Loyal NPCs do not voluntarily leave their sect.')
        if target and not repair and storage.presence(actor)['location']!=target['location']:raise logs.SteamError('Travel to the new sect headquarters before joining.')
        old=state['sect_id']
        if old and registered and not repair:
            leave_penalty(actor,old,state['office'],state['mentor'])
            political_event(old,'Member departed',state['name']+' relinquished their position and left the sect.',actor=actor,data={'actor':actor,'destination':target_id,'former_office':state['office']})
        pc=storage.load_profile_cache(actor)
        if target:
            memberships=pc.setdefault('sect_memberships',{})
            if target_id not in memberships:
                memberships[target_id]=dict(points=state['standing'] if repair else gamedata.SECT_INITIAL_REPUTATION[state['realm']],ready_at=0,offers=[],history=[])
            pc['sect_override']=target['name']
        else:pc['sect_override']='Wanderer'
        storage.save_profile_cache(pc,durable=True)
        db.execute("UPDATE affiliations SET sect_id=?,office='Member',mentor=NULL,support=0 WHERE actor=?",(target_id,actor))
        db.execute('UPDATE affiliations SET mentor=NULL WHERE mentor=?',(actor,))
        db.execute('DELETE FROM council_support WHERE candidate=? OR voter=?',(actor,actor))
        db.execute("UPDATE sect_plots SET stage='resolved',outcome='Plotter left the sect' WHERE actor=? AND stage<>'resolved'",(actor,))
        db.execute('UPDATE membership_terms SET changed_day=?,ready_day=?,repair_used=max(repair_used,?),next_salary=?,paid_role=\'\' WHERE actor=?',(day,day+political_seconds(gamedata.SECT_CHANGE_SECONDS),int(repair),day+political_seconds(gamedata.SECT_SALARY_SECONDS),actor))
        if target:
            if repair:db.execute('INSERT OR REPLACE INTO positions VALUES(?,?)',(actor,target['location']))
            political_event(target_id,'Member joined',state['name']+' joined '+target['name']+'.',actor=actor,data={'origin':old,'correction':repair})
        return 'Membership updated. Previous membership records and currencies were preserved.'


def council_members(sect):
    with storage.world_transaction() as db:
        return [political_actor(r[0]) for r in db.execute("SELECT a.actor FROM affiliations a JOIN profiles p ON p.id=a.actor WHERE a.sect_id=? AND a.office IN ('Elder','Sect Master','Acting Master') AND json_extract(p.data,'$.life.dead') IS NULL",(sect,)).fetchall()]


def achievement_count(actor):
    with storage.world_transaction() as db:
        return db.execute("SELECT count(*) FROM event_facts WHERE json_extract(facts,'$.subject')=? AND json_extract(facts,'$.outcome') IN ('upset','breakthrough','mission_success','victory')",(actor,)).fetchone()[0]


def office_role(state):
    if state['office'] in ('Sect Master','Acting Master','Elder'):
        return state['office']
    if state['mentor']:
        return 'Direct Disciple'
    return 'Member' if state['sect_id'] else ''


def appoint(actor,office,*,reason):
    with storage.world_transaction() as db:
        state=political_actor(actor);sect=state['sect_id'];day=storage.world_state()['day']
        if office in ('Sect Master','Acting Master'):
            for r in db.execute("SELECT actor FROM affiliations WHERE sect_id=? AND office IN ('Sect Master','Acting Master') AND actor<>?",(sect,actor)).fetchall():
                dead=political_actor(r[0])['dead']
                db.execute("UPDATE affiliations SET office=?,mentor=NULL WHERE actor=?",('Former Master' if dead else 'Elder',r[0]))
                students=db.execute('SELECT actor FROM affiliations WHERE mentor=? ORDER BY actor',(r[0],)).fetchall()
                for student in students[0 if dead else 2:]:
                    db.execute('UPDATE affiliations SET mentor=NULL WHERE actor=?',(student[0],))
                db.execute("UPDATE membership_terms SET paid_role=?,next_salary=? WHERE actor=?",('' if dead else 'Elder',day+political_seconds(1800),r[0]))
        db.execute('UPDATE affiliations SET office=?,mentor=NULL WHERE actor=?',(office,actor))
        ensure_member_term(actor)
        db.execute('UPDATE membership_terms SET next_salary=?,paid_role=? WHERE actor=?',(day+political_seconds(gamedata.SECT_SALARY_SECONDS),office,actor))
        db.execute('UPDATE sect_governance SET revision=revision+1 WHERE sect_id=?',(sect,))
        if office=='Sect Master':
            db.execute('UPDATE sect_payroll SET incumbent=?,confidence=100 WHERE sect_id=?',(actor,sect))
        prior_role=storage.member_role(state)
        political_event(sect,'Appointment',f"{prior_role} {state['name']} became {office}. {reason}",actor=actor,
                        data={'former_role':prior_role,'new_role':office})


@storage.atomic
def apply_direct_disciple(actor,mentor):
    a,m=political_actor(actor),political_actor(mentor)
    storage.require_physical(actor,others=(mentor,))
    if a['dead'] or m['dead'] or not a['sect_id'] or a['sect_id']!=m['sect_id']:raise logs.SteamError('The disciple and living mentor must belong to the same sect.')
    if a['office']!='Member' or a['mentor']:raise logs.SteamError('Only an unmentored ordinary member can apply.')
    if m['office'] not in ('Elder','Sect Master','Acting Master'):raise logs.SteamError('Choose a current elder or master.')
    with storage.world_transaction() as db:
        cap=2 if m['office']=='Elder' else 3
        count=db.execute("SELECT count(*) FROM affiliations a JOIN profiles p ON p.id=a.actor WHERE mentor=? AND json_extract(p.data,'$.life.dead') IS NULL",(mentor,)).fetchone()[0]
        if count>=cap:raise logs.SteamError('That mentor has no direct-disciple opening.')
        talent=next((i for i,t in enumerate(gamedata.TALENTS) if t['name']==a['talent']),0)
        achievements=achievement_count(actor)
        fit=len(set(a['personalities'])&set(m['personalities']))
        score=talent*6+min(achievements,10)*5+fit*8+min(a['standing']/100,10)
        if score<18 or talent==0 and achievements<2:raise logs.SteamError('The mentor wants stronger demonstrated achievements or greater talent and compatibility.')
        if a['power']>=m['power']:raise logs.SteamError('Choose a mentor stronger than you.')
        db.execute('UPDATE affiliations SET mentor=? WHERE actor=?',(mentor,actor));ensure_member_term(actor)
        db.execute("UPDATE membership_terms SET next_salary=?,paid_role='Direct Disciple' WHERE actor=?",(storage.world_state()['day']+political_seconds(gamedata.SECT_SALARY_SECONDS),actor))
        political_event(a['sect_id'],'Direct disciple accepted',a['name']+' became a direct disciple of '+m['name']+'.',actor=actor)
        return 'Your mentorship is established.'


def add_training_power(pc,gain):
    if pc.get('offline'):
        character=pc['offline']['character']
        if character.get('generation')=='seed-v1':
            character['score']+=gain
        else:
            character['power_offset']=character.get('power_offset',character['score']-generator.local_power_base(character))+gain
    else:
        pc['mentor_power']=pc.get('mentor_power',0)+gain


@storage.atomic
def solo_cultivation(actor,key='',profiles=None,rng=random):
    import math
    import warfare
    with storage.world_transaction() as db:
        clock=db.execute('SELECT cooldown,skip_until FROM cultivation_clock WHERE id=1').fetchone()
        world=storage.world_state()
        if clock and clock['cooldown']>0:
            raise logs.SteamError(f"Solo cultivation is ready in {math.ceil(clock['cooldown'])} seconds of active play.")
        if clock and clock['skip_until']>world['day']+1e-7:
            raise logs.SteamError('The previous cultivation day is still advancing.')
        if not actor or storage.profile_field(actor,'world_npc'):
            raise logs.SteamError('Select your own cultivator to train.')
        c=generator.build_cultivator(actor,key,profiles or {})[3]
        if c['death']:raise logs.SteamError('The dead cannot cultivate.')
        here=storage.require_physical(actor,dangerous=True)
        home=db.execute('SELECT 1 FROM affiliations a JOIN locations l ON l.sect_id=a.sect_id WHERE a.actor=? AND l.id=?',(actor,here['location'])).fetchone()
        if not home and here['location'] not in gamedata.PUBLIC_SITES:
            raise logs.SteamError('Train at your sect headquarters or a public pavilion site.')
        if not warfare.available_escort(db,actor):
            raise logs.SteamError('Finish your military or ritual assignment before training.')
        if ensure_member_term(actor)['train_ready']>world['day']:
            raise logs.SteamError('You are still recovering from mentor training.')
        realm=c['realm_index']
        gain=rng.randint(2,4)+max(0,realm-1)
        pc=storage.load_profile_cache(actor)
        add_training_power(pc,gain)
        storage.save_profile_cache(pc,durable=True)
        summary=f"Solo cultivation at {here['name']}: +{gain} power."
        storage.add_activity(actor,dict(at=time.time(),type='adventure',summary=summary))
        db.execute('INSERT OR REPLACE INTO cultivation_clock VALUES(1,?,300,?,1)',(actor,world['day']+1))
        db.execute('UPDATE world SET pending_seconds=pending_seconds+seconds_per_day WHERE id=1')
        return summary


@storage.atomic
def mentor_training(actor):
    a=political_actor(actor);mentor=a['mentor']
    if not mentor or a['dead']:raise logs.SteamError('A living direct disciple needs a current mentor.')
    m=political_actor(mentor);storage.require_physical(actor,others=(mentor,))
    if m['dead'] or m['sect_id']!=a['sect_id'] or m['office'] not in ('Elder','Sect Master','Acting Master'):raise logs.SteamError('This mentor can no longer provide training.')
    term=ensure_member_term(actor);day=storage.world_state()['day']
    if day<term['train_ready']:raise logs.SteamError('Mentor training is available every ten minutes of active play.')
    with storage.world_transaction() as db:
        pc=storage.load_profile_cache(actor);gain=3+min(4,max(0,m['realm']-a['realm']))
        if db.execute('SELECT 1 FROM cultivation_clock WHERE actor=? AND cooldown>0',(actor,)).fetchone():
            raise logs.SteamError('You are still recovering from solo cultivation.')
        add_training_power(pc,gain)
        storage.save_profile_cache(pc,durable=True)
        db.execute('UPDATE membership_terms SET train_ready=? WHERE actor=?',(day+political_seconds(gamedata.SECT_TRAIN_SECONDS),actor))
        db.execute('INSERT OR IGNORE INTO relationships(player,npc) VALUES(?,?)',(actor,mentor))
        db.execute('UPDATE relationships SET trust=min(100,trust+3),respect=min(100,respect+2) WHERE player=? AND npc=?',(actor,mentor))
        storage.add_activity(actor,dict(at=time.time(),type='adventure',summary=f'Mentor training with {m["name"]}: +{gain} power.'))
        return f'Training earned {gain} power. Complete missions or win notable battles for mentor gifts.'


@storage.atomic
def claim_mentor_reward(actor):
    a=political_actor(actor)
    if not a['mentor'] or a['dead']:raise logs.SteamError('You need a living mentorship.')
    m=political_actor(a['mentor']);storage.require_physical(actor,others=(m['actor'],))
    if m['dead'] or m['sect_id']!=a['sect_id'] or m['office'] not in ('Elder','Sect Master','Acting Master'):raise logs.SteamError('Your mentor is unavailable.')
    with storage.world_transaction() as db:
        rewards=[]
        for row in db.execute('SELECT f.event,f.facts FROM event_facts f WHERE json_extract(f.facts,\'$.subject\')=? AND NOT EXISTS(SELECT 1 FROM mentor_rewards r WHERE r.disciple=? AND r.event=f.event)',(actor,actor)).fetchall():
            facts=json.loads(row['facts']);outcome=facts['outcome'];amount=10 if outcome=='mission_success' else 30 if outcome=='breakthrough' else 0
            me=next((x for x in facts['actors'] if x['id']==actor),None)
            others=[x for x in facts['actors'] if x['id']!=actor]
            if me and others and outcome in ('upset','killed'):
                gap=max(x['realm']-me['realm'] for x in others)
                if gap>=2:amount=100+(gap-2)*25
            if amount:rewards.append((amount,row['event']))
        if not rewards:raise logs.SteamError('No unrewarded qualifying achievement. Complete a mission, break through, or defeat an opponent at least two realms higher.')
        amount,event=max(rewards)
        if storage.read_spirit_stones(m['actor'])<amount:raise logs.SteamError(f'Your mentor needs {amount} Spirit Stones for this reward. Try again after their salary.')
        wallet_transfer(m['actor'],actor,amount)
        db.execute('INSERT INTO mentor_rewards VALUES(?,?,?,?)',(actor,event,m['actor'],amount))
        storage.add_activity(actor,dict(at=time.time(),type='adventure',milestone='mentor_reward',summary=f'{m["name"]} awarded {amount} Spirit Stones for a verified achievement.'))
        return f'Your mentor awarded {amount} Spirit Stones from their own wallet.'

def support_chance(candidate,voter,amount=0,*,betrayal=False):
    with storage.world_transaction() as db:
        relation=db.execute('SELECT trust,respect FROM relationships WHERE player=? AND npc=?',(candidate['actor'],voter['actor'])).fetchone()
    trust=(relation['trust']+relation['respect'])/400 if relation else 0
    if betrayal and 'Loyal' in voter['personalities']:return 0
    fit=len(set(candidate['personalities'])&set(voter['personalities']))*.06
    base=.25+min(.2,candidate['standing']/10000)+trust+fit
    if amount:
        base+=min(.35,amount/1000)
        base+=.2 if 'Schemer' in voter['personalities'] else .1 if 'Ambitious' in voter['personalities'] else -.15 if 'Loyal' in voter['personalities'] else 0
    return max(.02,min(.95,base))


@storage.atomic
def seek_support(actor,voter,purpose='elder',amount=0,rng=random):
    if type(amount) is not int or not 0<=amount<=1000000:raise logs.SteamError('Choose a whole-number bribe from 0 to 1,000,000 Spirit Stones.')
    a,v=political_actor(actor),political_actor(voter)
    if a['dead'] or v['dead'] or actor==voter or not a['sect_id'] or a['sect_id']!=v['sect_id']:raise logs.SteamError('Choose another living council member in your sect.')
    if v['office'] not in ('Elder','Sect Master','Acting Master'):raise logs.SteamError('Only a council member can promise a vote.')
    storage.require_physical(actor,others=(voter,))
    with storage.world_transaction() as db:
        plot=db.execute("SELECT * FROM sect_plots WHERE id=? AND actor=? AND stage IN ('gathering','preparing')",(purpose,actor)).fetchone()
        if purpose not in ('elder','master') and not plot:raise logs.SteamError('This support campaign is no longer active.')
        if plot and 'Loyal' in a['personalities']:raise logs.SteamError('Loyal cultivators cannot plot betrayal.')
        prior=db.execute('SELECT * FROM council_support WHERE sect_id=? AND candidate=? AND voter=? AND purpose=?',(a['sect_id'],actor,voter,purpose)).fetchone()
        day=storage.world_state()['day']
        if prior and prior['backing']:raise logs.SteamError('This council member already supports that campaign.')
        if prior and day<prior['ready_day']:raise logs.SteamError('Wait ten minutes of active play before approaching this council member again.')
        if amount>storage.read_spirit_stones(actor):raise logs.SteamError('Not enough Spirit Stones for that offer.')
        chance=support_chance(a,v,amount,betrayal=bool(plot))
        accepted=chance>0 and rng.random()<chance
        if accepted and amount:wallet_transfer(actor,voter,amount)
        db.execute('INSERT OR REPLACE INTO council_support VALUES(?,?,?,?,?,?)',(a['sect_id'],actor,voter,purpose,int(accepted),day+political_seconds(600)))
        exposed=bool(amount and not accepted and rng.random()<.25)
        if exposed:
            pc=storage.load_profile_cache(actor);member=pc.get('sect_memberships',{}).get(a['sect_id'])
            if member:member['points']=max(0,member['points']-20);storage.save_profile_cache(pc,durable=True)
            if plot:
                for council in council_members(a['sect_id']):
                    if council['actor']!=actor:db.execute('INSERT INTO plot_evidence VALUES(?,?,2,0) ON CONFLICT(plot,observer) DO UPDATE SET points=max(points,2)',(purpose,council['actor']))
            political_event(a['sect_id'],'Bribe exposed',v['name']+' reported an improper offer from '+a['name']+'.',actor=actor,plot=purpose if plot else None)
        elif plot and accepted and amount:
            political_event(a['sect_id'],'Suspicious payment','A council member reportedly accepted an unexplained payment. The organizer remains unconfirmed.',plot=purpose,data={'evidence_hint':True})
        result=f"{v['name']} {'accepted' if accepted else 'refused'} your request."
        if accepted and amount:result+=f' {amount} Spirit Stones changed hands.'
        if exposed:result+=' The offer was exposed; sect standing fell by 20.'
        return result


def election_score(state,backing):
    # Multiple independent factors; office appointment is never a reputation title alone.
    return state['power']**.5+min(state['standing'],10000)/100+state['loyalty']/5+backing*30


def support_count(sect,candidate,purpose):
    with storage.world_transaction() as db:
        return db.execute("SELECT count(*) FROM council_support c JOIN affiliations a ON a.actor=c.voter JOIN profiles p ON p.id=a.actor WHERE c.sect_id=? AND c.candidate=? AND c.purpose=? AND c.backing=1 AND a.sect_id=c.sect_id AND a.office IN ('Elder','Sect Master','Acting Master') AND json_extract(p.data,'$.life.dead') IS NULL",(sect,candidate,purpose)).fetchone()[0]


@storage.atomic
def apply_office(actor,office='Elder'):
    a=political_actor(actor);storage.require_physical(actor)
    if a['dead'] or not a['sect_id']:raise logs.SteamError('Join a sect as a living member first.')
    if office not in ('Elder','Sect Master'):raise logs.SteamError('Choose Elder or Sect Master.')
    council=council_members(a['sect_id']);others=[v for v in council if v['actor']!=actor]
    if a['standing']<gamedata.SECT_ELDER_REPUTATION:raise logs.SteamError('At least 1,200 sect reputation is required.')
    elders=[v for v in council if v['office']=='Elder']
    if elders and a['power']<min(v['power'] for v in elders)*.8:raise logs.SteamError('Your strength must be at least 80% of the weakest current elder.')
    votes=support_count(a['sect_id'],actor,'elder' if office=='Elder' else 'master')
    if votes<max(1,(len(others)+1)//2):raise logs.SteamError('Secure support from at least half of the other council members first.')
    with storage.world_transaction() as db:
        home=storage.seat_location(db,a['sect_id'])
        if home and storage.presence(actor)['location']!=home[0]:raise logs.SteamError('Attend the sect headquarters for an appointment.')
        if office=='Elder':
            if a['office']!='Member':raise logs.SteamError('You already hold a council office.')
            count=db.execute('SELECT count(*) FROM affiliations WHERE sect_id=?',(a['sect_id'],)).fetchone()[0]
            cap=max(3,min(6,count//25))
            if len(elders)>=cap:raise logs.SteamError('The elder council is full. Keep your support while waiting for a vacancy.')
            appoint(actor,'Elder',reason='The council approved the appointment.')
            return 'You have been appointed Elder.'
        if a['office'] not in ('Elder','Acting Master') and a['standing']<5000:raise logs.SteamError('Master candidates must be elders or recognized guardians.')
        if any(v['office']=='Sect Master' for v in council):raise logs.SteamError('A legitimate sect master is still in office.')
        early=storage.world_state()['day']+political_seconds(gamedata.SECT_EARLY_ELECTION_SECONDS)
        db.execute('UPDATE sect_governance SET succession_at=min(coalesce(succession_at,?),?) WHERE sect_id=?',(early,early,a['sect_id']))
        return 'Your candidacy is registered. The council will weigh strength, standing, loyalty and support at succession.'


def pay_sect_salaries(sect,day):
    """Settle one shared pay period atomically. Never mint wages to cover a deficit."""
    with storage.world_transaction() as db:
        payroll=db.execute('SELECT * FROM sect_payroll WHERE sect_id=?',(sect,)).fetchone()
        if not payroll or day+1e-8<payroll['due']:
            return
        due=payroll['due']
        interval=political_seconds(gamedata.SECT_SALARY_SECONDS)
        cycle=payroll['cycles']
        yields=db.execute('SELECT yield_stones FROM spirit_mines WHERE owner=?',(sect,))
        income=sum(((cycle%4+1)*r[0])//4-((cycle%4)*r[0])//4 for r in yields)
        import warfare
        upkeep=warfare.occupation_cost(db,sect)
        balance=db.execute('SELECT treasury FROM sect_governance WHERE sect_id=?',(sect,)).fetchone()[0]+income
        balance=max(0,balance-upkeep)
        roster=db.execute("""SELECT a.*,p.kind,t.next_salary FROM affiliations a JOIN profiles p ON p.id=a.actor
            LEFT JOIN membership_terms t ON t.actor=a.actor WHERE a.sect_id=? AND json_extract(p.data,'$.life.dead') IS NULL""",(sect,)).fetchall()
        debts={r['actor']:r for r in db.execute('SELECT * FROM wage_debts WHERE sect_id=?',(sect,))}
        owed={actor:r['amount'] for actor,r in debts.items()}
        eligible=[]
        for member in roster:
            if member['next_salary'] is None:
                ensure_member_term(member['actor'])
                continue
            if member['next_salary']>due+1e-8:
                continue
            actor=member['actor']
            eligible.append(actor)
            owed[actor]=owed.get(actor,0)+gamedata.SECT_SALARIES[office_role(member)]
        total=sum(owed.values())
        spend=min(total,balance)
        payments={actor:amount*spend//total for actor,amount in owed.items()}
        # Largest remainders distribute the final whole stones without overspending.
        remainder=spend-sum(payments.values())
        if remainder:
            priority=sorted(owed,key=lambda actor:(-(owed[actor]*spend%total),actor))
            for actor in priority[:remainder]:
                payments[actor]+=1
        for actor,paid in payments.items():
            if paid:
                db.execute("""INSERT INTO salary_credits(actor,amount) VALUES(?,?) ON CONFLICT(actor)
                    DO UPDATE SET amount=amount+excluded.amount""",(actor,paid))
            arrears=owed[actor]-paid
            if arrears:
                db.execute("""INSERT INTO wage_debts VALUES(?,?,?,1) ON CONFLICT(sect_id,actor)
                    DO UPDATE SET amount=excluded.amount,misses=misses+1""",(sect,actor,arrears))
            elif actor in debts:
                db.execute('DELETE FROM wage_debts WHERE sect_id=? AND actor=?',(sect,actor))
        for member in roster:
            actor=member['actor']
            if member['kind']!='npc' and actor in payments:
                paid=payments[actor]
                arrears=owed[actor]-paid
                summary=f"{office_role(member)} salary: {paid} Spirit Stones."
                if arrears:
                    summary+=f" The treasury still owes you {arrears}."
                storage.add_activity(actor,dict(at=time.time(),type='adventure',summary=summary))
        db.executemany('UPDATE membership_terms SET next_salary=? WHERE actor=?',((due+interval,a) for a in eligible))
        db.execute('UPDATE sect_governance SET treasury=? WHERE sect_id=?',(balance-spend,sect))
        db.execute('UPDATE sect_payroll SET due=?,cycles=cycles+1,last_due=?,last_paid=? WHERE sect_id=?',
                   (due+interval,total,spend,sect))
        master=next((r for r in roster if r['office']=='Sect Master'),None)
        if master:
            confidence=payroll['confidence'] if master['actor']==payroll['incumbent'] else 100
            if spend<total:
                confidence=max(0,confidence-15)
                unpaid=[r for r in roster if owed.get(r['actor'],0)>payments.get(r['actor'],0) and r['actor']!=master['actor']]
                db.executemany("""INSERT INTO relationships(player,npc,respect) VALUES(?,?,-5)
                    ON CONFLICT(player,npc) DO UPDATE SET respect=max(-100,respect-5)""",
                    ((master['actor'],r['actor']) for r in unpaid))
                db.execute("UPDATE council_support SET backing=0 WHERE sect_id=? AND candidate=? AND purpose='master'",(sect,master['actor']))
            else:
                confidence=min(100,confidence+5)
            db.execute('UPDATE sect_payroll SET confidence=?,incumbent=? WHERE sect_id=?',(confidence,master['actor'],sect))
            if confidence<=25 and any(r['office']=='Elder' for r in roster):
                actor=master['actor']
                db.execute("UPDATE affiliations SET office='Member',mentor=NULL WHERE actor=?",(actor,))
                db.execute('UPDATE affiliations SET mentor=NULL WHERE mentor=?',(actor,))
                db.execute('DELETE FROM council_support WHERE candidate=?',(actor,))
                political_event(sect,'Council abdication',political_actor(actor)['name']+' was removed as Sect Master after repeated unpaid wages.',
                                actor=actor)
                reconcile_leadership(sect,day)


def treasury_summary(db,sect):
    row=db.execute("""SELECT g.treasury,p.last_due,p.last_paid,p.confidence,p.due,
        (SELECT coalesce(sum(amount),0) FROM wage_debts WHERE sect_id=p.sect_id) arrears,
        (SELECT coalesce(sum(yield_stones),0) FROM spirit_mines WHERE owner=p.sect_id) income
        FROM sect_payroll p JOIN sect_governance g USING(sect_id) WHERE p.sect_id=?""",(sect,)).fetchone()
    if not row:
        return None
    result=dict(row)
    result['wages']=sum(gamedata.SECT_SALARIES[office_role(member)] for member in db.execute(
        """SELECT a.* FROM affiliations a JOIN profiles p ON p.id=a.actor
           WHERE a.sect_id=? AND json_extract(p.data,'$.life.dead') IS NULL""",(sect,)))
    return result


def reconcile_leadership(sect,day):
    with storage.world_transaction() as db:
        dead=db.execute("SELECT a.actor,a.office,p.name FROM affiliations a JOIN profiles p ON p.id=a.actor WHERE a.sect_id=? AND json_extract(p.data,'$.life.dead') IS NOT NULL AND a.office IN ('Sect Master','Acting Master','Elder')",(sect,)).fetchall()
        for row in dead:
            db.execute("UPDATE affiliations SET office='Former '||office,mentor=NULL WHERE actor=?",(row['actor'],))
            db.execute('UPDATE affiliations SET mentor=NULL WHERE mentor=?',(row['actor'],))
        if db.execute("SELECT 1 FROM affiliations WHERE sect_id=? AND office='Sect Master' LIMIT 1",(sect,)).fetchone():
            return
        council=council_members(sect)
        master=next((a for a in council if a['office']=='Sect Master'),None)
        acting=next((a for a in council if a['office']=='Acting Master'),None)
        if not master and not acting:
            elders=[a for a in council if a['office']=='Elder']
            if elders:
                acting=max(elders,key=lambda a:(a['power'],a['realm'],a['actor']))
                previous=next((r for r in dead if r['office'] in ('Sect Master','Acting Master')),None)
                reason='The strongest eligible elder safeguards the vacant leadership.'
                if previous:
                    reason=f"Following the death of {previous['office']} {previous['name']}, the strongest eligible elder safeguards the sect."
                appoint(acting['actor'],'Acting Master',reason=reason)
                db.execute('UPDATE sect_governance SET succession_at=? WHERE sect_id=?',(day+political_seconds(gamedata.SECT_SUCCESSION_SECONDS),sect))
        due=db.execute('SELECT succession_at FROM sect_governance WHERE sect_id=?',(sect,)).fetchone()[0]
        if not master and due is not None and day>=due:
            candidates=council_members(sect)
            # Include eligible guardians with a registered, council-backed candidacy.
            extra=db.execute("SELECT DISTINCT candidate FROM council_support WHERE sect_id=? AND purpose='master' AND backing=1",(sect,)).fetchall()
            known={c['actor'] for c in candidates}
            for row in extra:
                c=political_actor(row[0])
                if c['actor'] not in known and not c['dead'] and c['sect_id']==sect and c['standing']>=5000:candidates.append(c)
            if candidates:
                winner=max(candidates,key=lambda a:(election_score(a,support_count(sect,a['actor'],'master')),a['actor']))
                appoint(winner['actor'],'Sect Master',reason='Council succession weighed strength, sect standing, loyalty and support.')
                db.execute('UPDATE sect_governance SET succession_at=NULL WHERE sect_id=?',(sect,))


def npc_membership_choices(actor,rng):
    term=ensure_member_term(actor);day=storage.world_state()['day']
    pending=storage.profile_field(actor,'sect_application')
    if not pending and day<term['npc_review']:return
    a=political_actor(actor)
    if not a['npc'] or a['dead']:return
    with storage.world_transaction() as db:
        if pending and not a['sect_id']:
            target=storage.seat_location(db,pending)
            here=storage.presence(actor)
            if target and here['state']=='present' and day>=term['ready_day']:
                if here['location']!=target[0]:
                    view=region_view(actor);start_journey(actor,route_plan(view,target[0],safe=True),view,encounters=False)
                else:
                    change_sect(actor,pending,npc=True)
                    pc=storage.load_profile_cache(actor);pc.pop('sect_application',None);storage.save_profile_cache(pc,durable=True)
            return
        if day<term['npc_review']:return
        db.execute('UPDATE membership_terms SET npc_review=? WHERE actor=?',(day+political_seconds(rng.uniform(14400,28800)),actor))
        if term['ready_day']>day:return
        if not a['sect_id']:
            if rng.random()<.15:
                pc=storage.load_profile_cache(actor)
                pc['sect_application']=rng.choice(storage.sect_names())['id'];storage.save_profile_cache(pc,durable=True)
            return
        if 'Loyal' in a['personalities'] or a['office'] in ('Acting Master','Sect Master'):return
        unpaid=db.execute('SELECT misses FROM wage_debts WHERE sect_id=? AND actor=?',(a['sect_id'],actor)).fetchone()
        # Reviewed on the existing membership schedule, with smaller risks for office holders.
        if unpaid:
            rate={'Member':.06,'Direct Disciple':.045,'Elder':.025}.get(office_role(a),0)
            if rng.random()<min(.65,rate*unpaid[0]) and storage.presence(actor)['state']=='present':
                change_sect(actor,None,npc=True)
                return
        # Concrete dissatisfaction, reviewed every 4–8 active hours, not every action.
        office=a['office']!='Member' or a['mentor']
        hostility=db.execute('SELECT avg(hostility) FROM relationships r JOIN affiliations x ON x.actor=r.player WHERE r.npc=? AND x.sect_id=?',(actor,a['sect_id'])).fetchone()[0] or 0
        chance=.005 if office else .04
        if office and 'Ambitious' in a['personalities']:chance=.001
        if hostility>=20 and rng.random()<chance:
            try:change_sect(actor,None,npc=True)
            except logs.SteamError:pass

# ============================================================================
# Staged internal plots. Private state is never a substitute for learned evidence.
# ============================================================================
def active_plot(sect):
    with storage.world_transaction() as db:
        row=db.execute("SELECT * FROM sect_plots WHERE sect_id=? AND stage IN ('gathering','preparing','conflict')",(sect,)).fetchone()
        return dict(row) if row else None


def start_plot(actor,rng=random,*,force=False):
    import uuid
    a=political_actor(actor)
    if a['dead'] or a['office'] not in ('Elder','Acting Master') or (not force and ('Loyal' in a['personalities'] or not any(p in a['personalities'] for p in ('Ambitious','Schemer')))):raise logs.SteamError('This cultivator will not instigate a takeover.')
    with storage.world_transaction() as db:
        if active_plot(a['sect_id']):raise logs.SteamError('A succession plot is already active in this sect.')
        pid=uuid.uuid4().hex;day=storage.world_state()['day']
        db.execute("INSERT INTO sect_plots(id,sect_id,actor,stage,due,created) VALUES(?,?,?,'gathering',?,?)",(pid,a['sect_id'],actor,day+political_seconds(rng.uniform(1800,3600)),day))
        db.execute('INSERT INTO plot_evidence VALUES(?,?,3,0)',(pid,actor))
        political_event(a['sect_id'],'Private ambition','An elder began gathering support.',actor=actor,plot=pid,public=False)
        return pid


def plot_factions(plot):
    council=council_members(plot['sect_id'])
    with storage.world_transaction() as db:
        allies={r[0] for r in db.execute('SELECT voter FROM council_support WHERE sect_id=? AND candidate=? AND purpose=? AND backing=1',(plot['sect_id'],plot['actor'],plot['id']))}
    allies.add(plot['actor'])
    attackers=[a for a in council if a['actor'] in allies and 'Loyal' not in a['personalities']]
    defenders=[a for a in council if a['actor'] not in {r['actor'] for r in attackers}]
    return attackers,defenders


def resolve_plot(plot,success,reason):
    with storage.world_transaction() as db:
        current=db.execute('SELECT stage FROM sect_plots WHERE id=?',(plot['id'],)).fetchone()
        if not current or current[0]=='resolved':return
        actor=political_actor(plot['actor'])
        if success and not actor['dead'] and actor['sect_id']==plot['sect_id'] and 'Loyal' not in actor['personalities']:
            appoint(actor['actor'],'Sect Master',reason=reason)
            db.execute('UPDATE sect_governance SET succession_at=NULL WHERE sect_id=?',(plot['sect_id'],))
            outcome='Takeover succeeded'
        else:
            success=False;outcome='Takeover failed'
            if not actor['dead']:
                db.execute("UPDATE affiliations SET office='Member',mentor=NULL,support=0 WHERE actor=?",(actor['actor'],))
                db.execute('UPDATE affiliations SET mentor=NULL WHERE mentor=?',(actor['actor'],))
                pc=storage.load_profile_cache(actor['actor']);member=pc.get('sect_memberships',{}).get(plot['sect_id'])
                if member:member['points']=max(0,member['points']-200);storage.save_profile_cache(pc,durable=True)
        db.execute("UPDATE sect_plots SET stage='resolved',outcome=? WHERE id=?",(outcome+': '+reason,plot['id']))
        prior_role=storage.member_role(actor)
        political_event(plot['sect_id'],outcome,f"{prior_role} {actor['name']} challenged for leadership. {reason}",
                        actor=actor['actor'],plot=plot['id'],data={'success':success,'challenger_role':prior_role})


def political_duty(actor):
    """Mobilize NPCs through normal journeys; no distant fights or teleporting."""
    with storage.world_transaction() as db:
        council=db.execute("""SELECT sect_id FROM affiliations WHERE actor=?
            AND office IN ('Elder','Sect Master','Acting Master')""",(actor,)).fetchone()
        if not council:return False
        plot=active_plot(council['sect_id'])
        if not plot or plot['stage']!='conflict':return False
        home=storage.seat_location(db,council['sect_id'])
        here=storage.presence(actor)
        if home and here['state']=='present' and here['location']!=home[0]:
            view=region_view(actor);start_journey(actor,route_plan(view,home[0],safe=True),view,encounters=False)
        db.execute('UPDATE npcs SET next_day=?,activity=? WHERE id=?',(storage.world_state()['day']+political_seconds(60),'Sect confrontation',actor))
    return True


def progress_plot(plot,day,rng):
    with storage.world_transaction() as db:
        a=political_actor(plot['actor'])
        if a['dead'] or a['sect_id']!=plot['sect_id'] or 'Loyal' in a['personalities']:
            resolve_plot(plot,False,'The organizer could no longer pursue the plot.');return
        if a['office']=='Sect Master' and plot['stage']!='conflict':
            db.execute("UPDATE sect_plots SET stage='resolved',outcome='Legitimate succession superseded the plot' WHERE id=?",(plot['id'],));return
        attackers,defenders=plot_factions(plot)
        if plot['stage']=='gathering':
            # Funds are limited by the actor's actual wallet and each voter has a cooldown.
            voters=[v for v in defenders if v['office']=='Elder' and v['actor']!=a['actor']]
            if voters and rng.random()<(.35 if 'Schemer' in a['personalities'] else .22):
                voter=rng.choice(voters)
                here=storage.presence(a['actor']);there=storage.presence(voter['actor'])
                if here['state']=='present' and there['state']=='present':
                    if here['location']!=there['location']:
                        view=region_view(a['actor']);start_journey(a['actor'],route_plan(view,there['location'],safe=True),view,encounters=False)
                    else:
                        amount=min(100,storage.read_spirit_stones(a['actor']))
                        try:seek_support(a['actor'],voter['actor'],plot['id'],amount if amount>=25 else 0,rng)
                        except logs.SteamError:pass
            if day>=plot['due']:
                db.execute("UPDATE sect_plots SET stage='preparing',due=? WHERE id=?",(day+political_seconds(rng.uniform(600,1200)),plot['id']))
                political_event(plot['sect_id'],'Council unrest','Unusual alliances and disputed council decisions suggest a possible leadership challenge. Investigate before naming a culprit.',plot=plot['id'])
            return
        if plot['stage']=='preparing':
            # A loyal elder can be attacked only when an actual conspirator is present.
            if not plot['assassination_attempted'] and 'Schemer' in a['personalities'] and rng.random()<.04:
                victims=[v for v in defenders if v['office']=='Elder' and 'Loyal' in v['personalities'] and v['npc']]
                here=storage.presence(a['actor'])
                victims=[v for v in victims if here['state']=='present' and storage.presence(v['actor'])['location']==here['location']]
                if victims:
                    victim=rng.choice(victims);db.execute('UPDATE sect_plots SET assassination_attempted=1 WHERE id=?',(plot['id'],))
                    if rng.random()<.3:
                        c=generator.build_cultivator(victim['actor'],'',{})[3];storage.mark_dead(victim['actor'],c,'sect_politics',circumstances=f"was assassinated during a struggle for control of {c['sect']}")
                        record_world_action('death','An elder was assassinated',victim['name']+' died during sect unrest.',[(victim['actor'],c)],subject=victim['actor'],outcome='death',importance=2)
                        political_event(plot['sect_id'],'Elder assassinated',victim['name']+' was found assassinated. The organizer has not been established publicly.',actor=victim['actor'],plot=plot['id'],data={'victim':victim['actor']})
                    else:political_event(plot['sect_id'],'Assassination thwarted','A loyal elder survived an assassination attempt; the organizer remains uncertain.',plot=plot['id'])
            # NPC resistance is independent of player intervention.
            informed=db.execute('SELECT count(*) FROM plot_evidence e JOIN affiliations a ON a.actor=e.observer WHERE plot=? AND points>=2 AND a.sect_id=? AND e.observer<>?',(plot['id'],plot['sect_id'],plot['actor'])).fetchone()[0]
            if informed and len(defenders)>=len(attackers) and rng.random()<.12:
                resolve_plot(plot,False,'Evidence and council opposition exposed the conspiracy.');return
            if day<plot['due']:return
            if len(attackers)<max(2,(len(attackers)+len(defenders)+1)//2):
                resolve_plot(plot,False,'The faction failed to secure sufficient council support.');return
            violent=rng.random()<(.25 if 'Schemer' in a['personalities'] else .55)
            if not violent:
                success=sum(election_score(x,1) for x in attackers)>sum(election_score(x,0) for x in defenders)
                resolve_plot(plot,success,'A council confrontation settled the leadership without civil fighting.');return
            db.execute("UPDATE sect_plots SET stage='conflict',due=?,round=0,wins=0 WHERE id=?",(day+political_seconds(120),plot['id']))
            political_event(plot['sect_id'],'Sect civil conflict',storage.member_role(a)+' '+a['name']+' openly challenged the leadership. Armed factions are assembling at headquarters.',actor=a['actor'],plot=plot['id'])
            for member in attackers+defenders:
                if member['npc']:political_duty(member['actor'])
            return
        if plot['stage']=='conflict' and day>=plot['due']:
            import combat
            home=storage.seat_location(db,plot['sect_id'])[0]
            left=[x for x in attackers if x['npc'] and storage.presence(x['actor'])['state']=='present' and storage.presence(x['actor'])['location']==home and not storage.injury_state(x['actor'])]
            right=[x for x in defenders if x['npc'] and storage.presence(x['actor'])['state']=='present' and storage.presence(x['actor'])['location']==home and not storage.injury_state(x['actor'])]
            won=False
            if left and right:
                l=max(left,key=lambda x:x['power']);r=max(right,key=lambda x:x['power'])
                if combat.duel_ready(l['actor'],r['actor']):
                    result=combat.perform_battle([l['actor'],r['actor']],'',{},rng=rng,mode='Lethal');won=result['result']['winner'] is result['a']
            else:
                # Factions that fail to muster lose ground; never force a player into combat.
                won=bool(left) and not right
            rounds=plot['round']+1;wins=plot['wins']+int(won)
            db.execute('UPDATE sect_plots SET round=?,wins=?,due=? WHERE id=?',(rounds,wins,day+political_seconds(120),plot['id']))
            political_event(plot['sect_id'],'Civil confrontation',f'Confrontation {rounds} favored '+('the challengers.' if won else 'the defenders.'),plot=plot['id'])
            if rounds>=3:resolve_plot(plot,wins>=2,'Three confrontations decided control of the sect.')


def politics_tick(day,*,limit=-1):
    with storage.world_transaction() as db:
        for gov in db.execute('SELECT * FROM sect_governance WHERE next_tick<=? ORDER BY next_tick,sect_id LIMIT ?',(day,limit)).fetchall():
            sect=gov['sect_id'];rng=random.Random(f"politics:{sect}:{gov['next_tick']:.8f}")
            db.execute('UPDATE sect_governance SET next_tick=? WHERE sect_id=?',(day+political_seconds(gamedata.SECT_POLITICS_SECONDS),sect))
            reconcile_leadership(sect,day)
            import warfare
            warfare.review(db,sect,day,rng)
            npc_candidate_progress(sect,rng)
            plot=active_plot(sect)
            if plot:progress_plot(plot,day,rng)
            elif day>=gov['next_plot']:
                db.execute('UPDATE sect_governance SET next_plot=? WHERE sect_id=?',(day+political_seconds(rng.uniform(3600,10800)),sect))
                candidates=[a for a in council_members(sect) if a['npc'] and a['office'] in ('Elder','Acting Master') and 'Loyal' not in a['personalities'] and any(p in a['personalities'] for p in ('Schemer','Ambitious'))]
                if candidates and rng.random()<.25:
                    weights=[2 if 'Schemer' in a['personalities'] else 1 for a in candidates]
                    start_plot(rng.choices(candidates,weights=weights)[0]['actor'],rng)


def intervention_chance(actor,action,evidence=0):
    a=political_actor(actor)
    chance={'Investigate':.55,'Warn council':.3+min(.6,evidence*.3),'Accuse':.15+min(.75,evidence*.3),'Negotiate':.35,'Back challenger':.6,'Defend leadership':.65}.get(action)
    if chance is None:raise logs.SteamError('Choose a political action.')
    return min(.95,max(.05,chance+min(.1,a['standing']/20000)+(.1 if a['office'] in ('Elder','Sect Master','Acting Master') else 0)))


@storage.atomic
def intervene(actor,action,rng=random):
    a=political_actor(actor);storage.require_physical(actor)
    if a['dead'] or not a['sect_id']:raise logs.SteamError('A living sect member must take this action.')
    plot=active_plot(a['sect_id'])
    if not plot:raise logs.SteamError('There are no public warning signs to investigate yet.')
    with storage.world_transaction() as db:
        home=storage.seat_location(db,a['sect_id'])
        if not home or storage.presence(actor)['location']!=home[0]:raise logs.SteamError('Attend sect headquarters to intervene.')
        row=db.execute('SELECT * FROM plot_evidence WHERE plot=? AND observer=?',(plot['id'],actor)).fetchone()
        evidence=row['points'] if row else 0;day=storage.world_state()['day']
        if not evidence and not db.execute('SELECT 1 FROM political_events WHERE plot=? AND public=1',(plot['id'],)).fetchone():raise logs.SteamError('There are no public warning signs to investigate yet.')
        if row and day<row['ready_day']:raise logs.SteamError('Wait two minutes of active play between interventions.')
        if action=='Back challenger' and 'Loyal' in a['personalities']:raise logs.SteamError('Loyal cultivators do not knowingly back betrayal.')
        chance=intervention_chance(actor,action,evidence);success=rng.random()<chance
        db.execute('INSERT INTO plot_evidence VALUES(?,?,?,?) ON CONFLICT(plot,observer) DO UPDATE SET ready_day=excluded.ready_day',(plot['id'],actor,evidence,day+political_seconds(120)))
        text=''
        if action=='Investigate':
            if success:
                db.execute('UPDATE plot_evidence SET points=min(3,points+1) WHERE plot=? AND observer=?',(plot['id'],actor));text='You obtained evidence of the conspiracy.'
            else:
                db.execute('INSERT OR IGNORE INTO relationships(player,npc) VALUES(?,?)',(actor,plot['actor']))
                db.execute('UPDATE relationships SET hostility=min(100,hostility+10) WHERE player=? AND npc=?',(actor,plot['actor']));text='Your investigation was noticed. The organizer now distrusts you.'
        elif action in ('Warn council','Accuse'):
            if success and evidence>=2:
                for voter in council_members(a['sect_id']):
                    if voter['actor']!=plot['actor']:db.execute('INSERT INTO plot_evidence VALUES(?,?,2,0) ON CONFLICT(plot,observer) DO UPDATE SET points=max(points,2)',(plot['id'],voter['actor']))
                political_event(a['sect_id'],'Conspiracy exposed',a['name']+' presented evidence implicating '+political_actor(plot['actor'])['name']+'.',actor=plot['actor'],plot=plot['id']);text='The council received your evidence and can act on it.'
            else:
                pc=storage.load_profile_cache(actor);member=pc.get('sect_memberships',{}).get(a['sect_id'])
                if member:member['points']=max(0,member['points']-(50 if action=='Accuse' else 10));storage.save_profile_cache(pc,durable=True)
                text='Your claim did not persuade the council; sect standing was damaged.'
        elif action=='Negotiate':
            if success:resolve_plot(plot,False,'Negotiation ended the leadership challenge.');text='Negotiation ended the conflict without further fighting.'
            else:text='Negotiations failed; the factions continue their plans.'
        elif action=='Back challenger':
            if a['office'] not in ('Elder','Sect Master','Acting Master'):raise logs.SteamError('Only council members can pledge a council vote.')
            if success:
                db.execute('INSERT OR REPLACE INTO council_support VALUES(?,?,?,?,1,0)',(a['sect_id'],plot['actor'],actor,plot['id']));text='You pledged support to the challenger.'
            else:text='The faction doubts your commitment.'
        elif action=='Defend leadership':
            if success:
                db.execute('DELETE FROM council_support WHERE sect_id=? AND candidate=? AND voter=? AND purpose=?',(a['sect_id'],plot['actor'],actor,plot['id']))
                db.execute('UPDATE sect_plots SET due=due+? WHERE id=?',(political_seconds(120),plot['id']));text='You rallied defenders and delayed the challenge by two active minutes.'
            else:text='You could not rally additional support.'
        storage.add_activity(actor,dict(at=time.time(),type='adventure',summary=action+': '+text))
        return f'{text} (Success chance: {chance:.0%}.)'


@storage.atomic
def fight_for_sect(actor,side,key='',profiles=None,rng=random):
    import combat
    a=political_actor(actor);plot=active_plot(a['sect_id']) if a['sect_id'] else None
    if not plot or plot['stage']!='conflict':raise logs.SteamError('No armed sect confrontation is active.')
    if side not in ('Defenders','Challengers'):raise logs.SteamError('Choose a side.')
    if side=='Challengers' and 'Loyal' in a['personalities']:raise logs.SteamError('Loyal cultivators cannot fight for a betrayal.')
    storage.require_physical(actor,dangerous=True)
    attackers,defenders=plot_factions(plot);opponents=attackers if side=='Defenders' else defenders
    here=storage.presence(actor)
    opponents=[v for v in opponents if v['actor']!=actor and v['npc'] and storage.presence(v['actor'])['state']=='present' and storage.presence(v['actor'])['location']==here['location'] and not storage.injury_state(v['actor'])]
    if not opponents:raise logs.SteamError('No opposing fighter is currently available at your location.')
    foe=max(opponents,key=lambda x:x['power'])
    result=combat.perform_battle([actor,foe['actor']],key,profiles or {},rng=rng,mode='Lethal')
    won=result['result']['winner'] is result['a']
    with storage.world_transaction() as db:
        rounds=plot['round']+1;wins=plot['wins']+int(won if side=='Challengers' else not won)
        db.execute('UPDATE sect_plots SET round=?,wins=? WHERE id=?',(rounds,wins,plot['id']))
        political_event(a['sect_id'],'Player confrontation',result['story'],actor=actor,plot=plot['id'])
        if rounds>=3:resolve_plot(plot,wins>=2,'Player and NPC confrontations settled the struggle.')
    return result['story']

def political_notice(actor):
    """Read only actionable, known plots for the selected living character."""
    with storage.world_snapshot() as db:
        row=db.execute("""SELECT p.id,p.stage,p.round,s.name FROM affiliations a
            JOIN sect_plots p ON p.sect_id=a.sect_id JOIN sects s ON s.id=a.sect_id
            JOIN profiles v ON v.id=a.actor
            WHERE a.actor=? AND p.stage IN ('gathering','preparing','conflict')
            AND json_extract(v.data,'$.life.dead') IS NULL AND
            (EXISTS(SELECT 1 FROM plot_evidence WHERE plot=p.id AND observer=a.actor AND points>0)
            OR EXISTS(SELECT 1 FROM political_events WHERE sect_id=a.sect_id AND plot=p.id AND public=1))""",(actor,)).fetchone()
        return tuple(row) if row else None


def sect_management(actor):
    with storage.world_transaction() as db:
        a=political_actor(actor);term=ensure_member_term(actor);day=storage.world_state()['day']
        catalog=storage.sect_catalog();registered=a['sect_id'] in {s['id'] for s in catalog}
        council=council_members(a['sect_id']) if registered else []
        for voter in council:
            voter['location']=storage.presence(voter['actor'])
            voter['disciples']=db.execute("SELECT count(*) FROM affiliations a JOIN profiles p ON p.id=a.actor WHERE mentor=? AND json_extract(p.data,'$.life.dead') IS NULL",(voter['actor'],)).fetchone()[0]
            voter['capacity']=2 if voter['office']=='Elder' else 3
            voter['support_chance']=support_chance(a,voter)
            voter['elder_backing']=bool(db.execute("SELECT 1 FROM council_support WHERE sect_id=? AND candidate=? AND voter=? AND purpose='elder' AND backing=1",(a['sect_id'],actor,voter['actor'])).fetchone())
        reports=[dict(r) for r in db.execute('SELECT e.title,e.summary,e.day,p.plot FROM political_events p JOIN world_events e ON e.id=p.event WHERE p.sect_id=? AND p.public=1 ORDER BY p.id DESC LIMIT 12',(a['sect_id'],))]
        plot=active_plot(a['sect_id']) if registered else None;known=None
        if plot:
            row=db.execute('SELECT points,ready_day FROM plot_evidence WHERE plot=? AND observer=?',(plot['id'],actor)).fetchone()
            evidence=row['points'] if row else 0
            public=bool(db.execute('SELECT 1 FROM political_events WHERE plot=? AND public=1',(plot['id'],)).fetchone())
            if public or evidence:
                known=dict(id=plot['id'],stage=plot['stage'],round=plot['round'],evidence=evidence,
                           organizer=political_actor(plot['actor'])['name'] if evidence>=2 or plot['stage']=='conflict' else 'Unconfirmed',
                           choices={action:intervention_chance(actor,action,evidence) for action in ('Investigate','Warn council','Accuse','Negotiate','Back challenger','Defend leadership')})
        role=office_role(a)
        economy=treasury_summary(db,a['sect_id'])
        payday=term['next_salary']
        if economy:
            import math
            interval=political_seconds(gamedata.SECT_SALARY_SECONDS)
            skipped=max(0,math.ceil((payday-economy['due']-1e-8)/interval))
            payday=economy['due']+skipped*interval
        # Read-only dashboard context; action functions remain authoritative.
        here=storage.presence(actor)
        home=storage.seat_location(db,a['sect_id']) if registered else None
        members=db.execute('SELECT count(*) FROM affiliations WHERE sect_id=?',(a['sect_id'],)).fetchone()[0] if registered else 0
        readiness=dict(presence=here,headquarters=home[0] if home else None,
                       elder_capacity=max(3,min(6,members//25)),
                       votes={role:support_count(a['sect_id'],actor,role) for role in ('elder','master')})
        return dict(readiness=readiness,economy=economy,actor=a,term=term,catalog=catalog,council=council,reports=reports,plot=known,spirit_stones=storage.read_spirit_stones(actor),
                    needs_choice=not registered and a['sect_id'] is not None and not term['repair_used'],
                    salary=gamedata.SECT_SALARIES.get(role,0) if registered else 0,role=role or 'Member',day=day,
                    salary_seconds=max(0,(payday-day)*storage.world_state()['seconds_per_day']),
                    change_seconds=max(0,(term['ready_day']-day)*storage.world_state()['seconds_per_day']))


def npc_candidate_progress(sect,rng):
    """Occasional legitimate applications; no extra free votes or automatic offices."""
    if rng.random()>.15:return
    with storage.world_transaction() as db:
        council=council_members(sect)
        # Apprentices compete for actual openings and must meet the same checks as players.
        mentors=[m for m in council if not m['dead'] and storage.presence(m['actor'])['state']=='present']
        if mentors and rng.random()<.2:
            mentor=rng.choice(mentors);here=storage.presence(mentor['actor'])['location']
            students=db.execute("SELECT a.actor FROM affiliations a JOIN profiles p ON p.id=a.actor JOIN positions x ON x.actor=a.actor LEFT JOIN journeys j ON j.actor=a.actor WHERE a.sect_id=? AND a.office='Member' AND a.mentor IS NULL AND p.kind='npc' AND x.location=? AND j.actor IS NULL AND json_extract(p.data,'$.life.dead') IS NULL ORDER BY a.actor LIMIT 12",(sect,here)).fetchall()
            if students:
                student=rng.choice(students)[0]
                try:apply_direct_disciple(student,mentor['actor'])
                except logs.SteamError:pass
        vacancy=not any(a['office']=='Sect Master' for a in council)
        if vacancy:candidates=[a for a in council if a['npc']]
        else:
            rows=db.execute("SELECT a.actor FROM affiliations a JOIN profiles p ON p.id=a.actor WHERE a.sect_id=? AND a.office='Member' AND p.kind='npc' AND json_extract(p.data,'$.life.dead') IS NULL AND coalesce(json_extract(p.data,'$.sect_memberships.'||a.sect_id||'.points'),0)>=1200 LIMIT 8",(sect,)).fetchall()
            candidates=[political_actor(r[0]) for r in rows]
        if not candidates:return
        a=max(candidates,key=lambda x:election_score(x,0));voters=[v for v in council if v['actor']!=a['actor']]
        if not voters:return
        purpose='master' if vacancy else 'elder'
        if support_count(sect,a['actor'],purpose)>=max(1,(len(voters)+1)//2):
            home=storage.seat_location(db,sect)[0]
            here=storage.presence(a['actor'])
            if here['state']=='present':
                if here['location']!=home:
                    view=region_view(a['actor']);start_journey(a['actor'],route_plan(view,home,safe=True),view,encounters=False)
                else:
                    try:apply_office(a['actor'],'Sect Master' if vacancy else 'Elder')
                    except logs.SteamError:pass
            return
        voter=rng.choice(voters)
        if storage.presence(a['actor'])['state']!='present' or storage.presence(voter['actor'])['state']!='present':return
        if storage.presence(a['actor'])['location']!=storage.presence(voter['actor'])['location']:return
        propensity=.05 if 'Loyal' in a['personalities'] else .6 if 'Schemer' in a['personalities'] else .35 if 'Ambitious' in a['personalities'] else .1
        bribe=50 if storage.read_spirit_stones(a['actor'])>=50 and rng.random()<propensity else 0
        try:seek_support(a['actor'],voter['actor'],purpose,bribe,rng)
        except logs.SteamError:pass



def initialize_frontiers(db):
    if db.execute('SELECT 1 FROM spirit_mines LIMIT 1').fetchone():
        # The legacy and new ranges do not overlap. Preserve each established mine's
        # relative richness and ownership, including worlds reopened after interruption.
        db.execute("UPDATE spirit_mines SET yield_stones=(3*yield_stones+1)/2 WHERE kind='Small' AND yield_stones BETWEEN 12000 AND 15000")
        return
    seed=storage.world_state()['seed']
    def mine(place,kind,owner,low,high):
        amount=random.Random(f'{seed}:ore:{place}').randint(low,high)
        db.execute('INSERT INTO spirit_mines VALUES(?,?,?,?)',(place,kind,owner,amount))
    for row in db.execute('SELECT id,sect_id FROM locations WHERE sect_id IS NOT NULL').fetchall():
        mine(row['id'],'Small',row['sect_id'],18000,22500)
    # Two approach roads per frontier allow through travel between neighboring old districts.
    borders=((180,100,'r1_7','r4_1'),(820,100,'r1_3','r2_1'),
             (820,600,'r2_5','r3_3'),(180,600,'r3_7','r4_5'))
    for district,((cx,cy,left,right),(_,_,names)) in enumerate(zip(borders,gamedata.FRONTIER_DISTRICTS),5):
        gate,hold,lode=sites=[f'r{district}_{i}' for i in range(3)]
        for site,name,(dx,dy) in zip(sites,names,((-80,0),(50,-35),(60,55))):
            db.execute('INSERT INTO locations VALUES(?,?,?,?,?,NULL)',(site,name,district,cx+dx,cy+dy))
        for src,dst,seconds,danger in ((left,gate,80,2),(right,hold,90,1),(gate,hold,25,1),(hold,lode,30,2)):
            db.execute('INSERT INTO routes VALUES(?,?,?,?)',(*sorted((src,dst)),seconds,danger))
        mine(lode,'Large',None,25000,35000)
    volunteers=db.execute('''SELECT n.id FROM npcs n JOIN affiliations a ON a.actor=n.id JOIN profiles p ON p.id=n.id
        WHERE a.sect_id IS NULL AND json_extract(p.data,'$.life.dead') IS NULL ORDER BY n.id LIMIT 12''').fetchall()
    for i,row in enumerate(volunteers):
        db.execute('INSERT INTO mine_wardens VALUES(?,?)',(row[0],f'r{5+i%4}_2'))
