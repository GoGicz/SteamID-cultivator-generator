"""Progress of a cultivator: breakthroughs, adventures and rebirth."""

import json
import random
import time

import gamedata
import gametext
import generator
import logs
import steam_api
import storage


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


def perform_adventure(steamid, c, info, friend_ids, key, rng=random, now=None):
    """One adventure of cultivator c (a dead one gets the rebirth roll instead). Saves what
    happened and returns {'kind', 'title', 'text', 'rep', 'item', 'friend', 'reborn'}.
    Nothing is printed here."""
    now = time.time() if now is None else now
    if c["death"]:
        return attempt_rebirth(steamid, c, rng, now)
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
    if summary:
        storage.add_activity(steamid, {"at": now, "type": "adventure", "kind": kind, "summary": summary,
                                       "rep": out["rep"]})
    logs.RUN_LOG.note(f"adventure: {c['name']} ({steamid}) {kind}" + (f": {summary}" if summary else ""))
    return out


def new_incarnation(c, rng, now):
    """A new random body for the dead cultivator c. The realm, path, personalities and
    arsenal are not part of it: they stay."""
    gender = rng.choice(("male", "female"))
    return {"gender": gender, "name": generator.make_name(rng, gender),
            "sect": f"{rng.choice(gamedata.SECT_ADJ)} {rng.choice(gamedata.SECT_NOUN)}",
            "element": rng.choice(gamedata.ELEMENTS),
            "talent": rng.choices(gamedata.TALENTS, weights=[t["weight"] for t in gamedata.TALENTS], k=1)[0]["name"],
            "title_roll": rng.randrange(1_000_000), "lifespan_roll": rng.randint(150, 400),
            "immortal_lifespan": rng.randint(*generator.IMMORTAL_LIFESPAN),
            "birth_year": c["death"]["year"] + rng.randint(1, 300), "age": rng.randint(16, 40),
            "arsenal": json.loads(json.dumps(generator.arsenal_of(c))),
            "count": read_life_count(c) + 1, "at": now}


def read_life_count(c):
    return c.get("incarnation", 0)


def attempt_rebirth(steamid, c, rng=random, now=None):
    """The Heavens' roll for a dead cultivator: REBIRTH_CHANCE, at most once per
    REBIRTH_INTERVAL_HOURS. On success the new body is saved (see the section comment)."""
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
    rep_target = rng.randint(*REBIRTH_REP_RANGE)
    sect_target = rng.randint(*REBIRTH_SECT_POINTS_RANGE)
    storage.write_life(steamid, dead=None, last_roll=now, incarnation=inc, rebirths=inc["count"])
    storage.write_duel_rep(steamid, rep_target - c["reputation"]["base_points"])
    pav = storage.read_pavilion(steamid)
    storage.write_pavilion(steamid, pav["items"], pav["spent"], earned=max(pav["earned"], c["sect_points_earned"]),
                           bonus=sect_target - (max(pav["earned"], c["sect_points_earned"]) - pav["spent"]))
    storage.write_realm_state(steamid, c["realm_index"], None, 0)       # the old body's losses are gone
    summary = (f"{c['name']} died and was reborn as {inc['name']}, a {inc['gender']} of the "
               f"{inc['sect']}")
    storage.add_activity(steamid, {"at": now, "type": "reborn", "summary": summary})
    out.update(kind="reborn", reborn=True, title=gametext.ADVENTURE_TITLES["reborn"],
               old_name=c["name"], new_name=inc["name"], gender=inc["gender"], sect=inc["sect"],
               talent=inc["talent"], element=inc["element"], reputation=rep_target,
               sect_points=sect_target)
    out["text"] = (f"REBORN! After {c['death']['age']:,} years of wandering as a lost soul, "
                   f"{c['name']} awakens in a new body: {inc['name']}, a {inc['gender']} of the "
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
    elif top:
        st["reason"] = f"{c['name']} already stands in the highest realm, {c['realm']}."
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


def attempt_breakthrough(steamid, c, use_pill=False, rng=random, now=None):
    """Tries the breakthrough for cultivator c (loaded for steamid). Saves the new realm on
    success, the failure time on failure, uses up the pill if one was swallowed and records
    it all in the history. Raises SteamError if it is not allowed."""
    now = time.time() if now is None else now
    st = breakthrough_status(c, now)
    if not st["can"]:
        raise logs.SteamError(st["reason"])
    if use_pill and st["pills"] <= 0:
        raise logs.SteamError(f"{c['name']} owns no Heaven-Defying Breakthrough Pill. "
                              f"One can be bought at the Martial Pavilion.")
    bd = breakthrough_chance(c, use_pill)
    success = rng.random() < bd["total"]
    if use_pill:
        goods = dict(c["pavilion"]["items"])
        goods[BREAKTHROUGH_PILL_ID] -= 1
        storage.write_pavilion(steamid, goods, c["pavilion"]["spent"],
                               {"at": now, "type": "pill used", "item": gamedata.PAVILION_BY_ID[BREAKTHROUGH_PILL_ID]["name"],
                                "other": None})
    lost = 0 if success else st["penalty"]
    storage.write_realm_state(steamid, c["realm_index"] + (1 if success else 0),
                              None if success else now,
                              storage.read_realm_state(steamid)["lifespan_lost"] + lost)
    storage.add_activity(steamid, {"at": now, "type": "breakthrough", "success": success,
                                   "from": st["current"], "to": st["next"], "chance": bd["total"],
                                   "pill": bool(use_pill), "lost": lost,
                                   "fatal": bool(not success and st["fatal"])})
    logs.RUN_LOG.note(f"breakthrough: {c['name']} ({steamid}) {'broke through to ' + st['next'] if success else 'failed the breakthrough to ' + st['next']} "
                      f"({bd['total'] * 100:g}% chance{', pill used' if use_pill else ''})"
                      + (f", lost {lost} years of lifespan" if lost else "")
                      + (", and died of it" if not success and st["fatal"] else ""))
    return {"success": success, "chance": bd["total"], "from": st["current"], "to": st["next"],
            "pill_used": bool(use_pill), "lost": lost,
            "died": bool(not success and st["fatal"])}


def breakthrough_target(key, profiles, session):
    """(steamid, freshly loaded cultivator) of the latest looked-up profile."""
    steamid = session.get("latest")
    if not steamid:
        raise logs.SteamError("No cultivator has been selected yet. Look up a Steam profile first.")
    return steamid, generator.build_cultivator(steamid, key, profiles)[3]
