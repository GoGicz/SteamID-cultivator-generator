"""Duels (the 'mocb' command): odds, affinity, power gap, loot and theft, reputation changes,
and the telling of the battle."""

import random
import time

import gamedata
import gametext
import generator
import logs
import storage


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

# ---------------------------------------------------------------------------
# Treasures and the inventory. Everyone starts with the one treasure their SteamID gives
# them. From then on the inventory saved in the profile's JSON file (cache/<SteamID>.profile.json)
# is what counts: a Demonic winner steals the prized treasure of the loser, and every winner
# has a DROP_CHANCE of finding a random new treasure. FALLBACK_TREASURE is only what the
# stories call the belongings of someone who owns nothing; it is not in the inventory.
# ---------------------------------------------------------------------------
DROP_CHANCE = 0.05
STEAL_CHANCE = 0.25      # a Demonic winner steals the loser's prized treasure in 1 duel out of 4


def resolve_loot(w, l, rng=random):
    """What the winner w takes or finds after beating l. Returns {'stolen': treasure or None,
    'nothing': True if a Demonic winner had nothing to steal, 'missed': True if the winner
    had something to steal but the STEAL_CHANCE roll failed, 'blocked': True if the loser's
    Spatial Escape Talisman stopped the theft, 'found': treasure or None}.
    A Demonic winner has a STEAL_CHANCE (25%) of stealing the loser's prized treasure in a duel
    (a talisman is only used up when that roll succeeds); any winner has a DROP_CHANCE of
    finding a random treasure that suits their realm and that they do not own yet."""
    loot = {"stolen": None, "nothing": False, "found": None, "blocked": False, "missed": False}
    if w["path"]["name"] == "Demonic":
        prize = generator.prized_treasure(generator.treasures_of(l))
        if not prize:
            loot["nothing"] = True
        elif rng.random() >= STEAL_CHANCE:           # this time the winner does not get the chance
            loot["missed"] = True
        elif generator.talisman_count(l) > 0:                  # a Spatial Escape Talisman saves it
            loot["blocked"] = True
        else:
            loot["stolen"] = prize
    if rng.random() < DROP_CHANCE:
        owned = generator.treasures_of(w) + ([loot["stolen"]] if loot["stolen"] else [])
        tier = 0 if w["realm_index"] <= 2 else 1 if w["realm_index"] <= 6 else 2
        pool = [t for t in gamedata.ALL_TREASURES[tier] if t not in owned] or \
               [t for pool_ in gamedata.ALL_TREASURES for t in pool_ if t not in owned]
        if pool:
            loot["found"] = rng.choice(pool)
    return loot


# ---------------------------------------------------------------------------
# Reputation from duels. Only the realm decides. If the winner is in a LOWER realm than the
# loser, the winner gains REP_GAIN_PER_REALM for every realm of difference and the loser
# loses REP_LOSS_PER_REALM for every realm. If both are on the same realm, or the stronger
# realm won as expected, nothing changes. When both cultivators are Righteous the loser loses
# only REP_LOSS_RIGHTEOUS_FACTOR of that (the righteous forgive more easily); Righteous vs
# Demonic and Demonic vs Demonic cost the full amount. Reputation never goes below 0.
# ---------------------------------------------------------------------------
REP_GAIN_PER_REALM = 25
REP_LOSS_PER_REALM = 20
REP_LOSS_RIGHTEOUS_FACTOR = 0.5


def reputation_change(w, l):
    """What a duel does to the two reputations: {'kind': 'upset' | 'same' | 'expected',
    'gap': realms of difference, 'gain': for the winner, 'loss': for the loser, 'light':
    True if the loss is the lighter Righteous-vs-Righteous one}."""
    gap = l["realm_index"] - w["realm_index"]
    if gap == 0:
        return {"kind": "same", "gap": 0, "gain": 0, "loss": 0, "light": False}
    if gap < 0:
        return {"kind": "expected", "gap": gap, "gain": 0, "loss": 0, "light": False}
    light = w["path"]["name"] == "Righteous" and l["path"]["name"] == "Righteous"
    loss = round(gap * REP_LOSS_PER_REALM * (REP_LOSS_RIGHTEOUS_FACTOR if light else 1))
    return {"kind": "upset", "gap": gap, "gain": gap * REP_GAIN_PER_REALM, "loss": loss,
            "light": light}


def with_duel_points(rep, duel_points):
    """A reputation dict with the duel points changed: new points, rank and Duels entry."""
    base = rep.get("base_points", rep["points"] - rep.get("duel_points", 0))
    bonuses = [(n, amount) for n, amount in rep["bonuses"] if n != "Duels"]
    if duel_points:
        bonuses.append(("Duels", duel_points))
    points = max(0, base + duel_points)
    idx = generator.reputation_rank(points)
    return dict(rep, points=points, base_points=base, duel_points=duel_points, bonuses=bonuses,
                rank_index=idx, rank=gamedata.REPUTATION_RANKS[idx][1])


def apply_reputation(ids, a, b, result, change):
    """Saves the reputation won and lost in the two profiles' files and updates the two
    cultivators. Fills change with what really happened (change['w_rank'], ['l_rank'] as
    (before, after), and the actual 'gain' and 'loss': the loss stops at 0 reputation)."""
    if change["kind"] != "upset":
        return
    w, l = result["winner"], result["loser"]
    w_id, l_id = (ids[0], ids[1]) if w is a else (ids[1], ids[0])
    now = time.time()
    for c, cid, delta, other, won in ((w, w_id, change["gain"], l, True),
                                      (l, l_id, -change["loss"], w, False)):
        rep = c["reputation"]
        old = storage.read_duel_rep(cid)[0]
        base = rep.get("base_points", rep["points"] - rep.get("duel_points", 0))
        new = max(-base, old + delta)                    # never below 0 reputation in total
        storage.write_duel_rep(cid, new, {"at": now, "points": new - old, "won": won, "other": other["name"],
                                          "realm": c["realm"], "other_realm": other["realm"]})
        before = rep["rank"]
        c["reputation"] = with_duel_points(rep, new)
        change["w_rank" if won else "l_rank"] = (before, c["reputation"]["rank"])
        change["gain" if won else "loss"] = abs(new - old)
        logs.RUN_LOG.note(f"reputation: {c['name']} ({cid}) {new - old:+d} for the duel against "
                          f"{other['name']} ({c['realm']} vs {other['realm']}), now {c['reputation']['points']}")


def apply_loot(ids, a, b, result, loot):
    """Saves what changed hands in the two profiles' inventory files and updates the two
    cultivators to match. ids are the SteamIDs of a and b."""
    if not (loot["stolen"] or loot["found"] or loot.get("blocked")):
        return
    w, l = result["winner"], result["loser"]
    w_id, l_id = (ids[0], ids[1]) if w is a else (ids[1], ids[0])
    now = time.time()
    if loot.get("blocked") and gamedata.TALISMAN_SINGLE_USE:      # the talisman is used up
        goods = dict(l["pavilion"]["items"])
        goods[gamedata.TALISMAN_ID] -= 1
        event = {"at": now, "type": "talisman used", "item": "Spatial Escape Talisman",
                 "other": w["name"]}
        storage.write_pavilion(l_id, goods, l["pavilion"]["spent"], event)
        l["pavilion"] = dict(l["pavilion"], items={k: v for k, v in goods.items() if v > 0})
        loot["talismans_left"] = goods[gamedata.TALISMAN_ID]
    if loot.get("blocked"):
        logs.RUN_LOG.note(f"loot: {l['name']} ({l_id})'s Spatial Escape Talisman saved the treasure "
                          f"from {w['name']} ({w_id})")
    if not (loot["stolen"] or loot["found"]):
        return
    w_items, l_items = generator.treasures_of(w), generator.treasures_of(l)
    w_events, l_events = [], []
    if loot["stolen"]:
        l_items.remove(loot["stolen"])
        w_items.append(loot["stolen"])
        w_events.append({"at": now, "type": "stole", "item": loot["stolen"], "other": l["name"]})
        l_events.append({"at": now, "type": "robbed", "item": loot["stolen"], "other": w["name"]})
        storage.write_inventory(l_id, l_items, l_events)
    if loot["found"]:
        w_items.append(loot["found"])
        w_events.append({"at": now, "type": "found", "item": loot["found"], "other": None})
    storage.write_inventory(w_id, w_items, w_events)
    for c, items, events in ((w, w_items, w_events), (l, l_items, l_events)):
        c["treasures"] = items
        c["treasure"] = generator.prized_treasure(items) or gamedata.FALLBACK_TREASURE
        c["inventory_history"] = c.get("inventory_history", []) + events
    if loot["stolen"]:
        logs.RUN_LOG.note(f"loot: {w['name']} ({w_id}) stole {loot['stolen']} from {l['name']} ({l_id})")
    if loot["found"]:
        logs.RUN_LOG.note(f"loot: {w['name']} ({w_id}) found {loot['found']} (the {DROP_CHANCE:.0%} drop)")


# ---------------------------------------------------------------------------
# Affinity matchups. ELEMENT_BEATS[x] lists the two elements x is strong against; each of
# those is weak against x. The table is balanced: every element beats exactly two others
# and loses to exactly two others, so no element is better than the rest overall.
# A matchup moves the duel odds by AFFINITY_BONUS for the stronger element and against the
# weaker one (0.03 = 3 percentage points). Elements not listed against each other, and two
# of the same element, are neutral.
# ---------------------------------------------------------------------------
AFFINITY_BONUS = 0.03

# ---------------------------------------------------------------------------
# Power gap. When one fighter's power towers over the other's (compared as a ratio, with
# the same BATTLE_SCORE_FLOOR as the odds), the story says so, and the stronger fighter
# acts arrogant and confident. Ratios at or above each limit pick the tier.
# ---------------------------------------------------------------------------
GAP_NOTICEABLE = 1.5
GAP_LARGE = 3.0
GAP_VAST = 8.0


def element_edge(x, y):
    """+1 if element x is strong against element y, -1 if it is weak against it, else 0."""
    if y in gamedata.ELEMENT_BEATS.get(x, ()):
        return 1
    if x in gamedata.ELEMENT_BEATS.get(y, ()):
        return -1
    return 0


def element_weak_to(x):
    """The elements that are strong against element x, in the usual element order."""
    return [e for e in gamedata.ELEMENTS if x in gamedata.ELEMENT_BEATS.get(e, ())]


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


def move_fields(tag, c):
    """Format fields for one fighter's arsenal: {tag_atk1} {tag_atk2} {tag_path} {tag_def}."""
    a = generator.arsenal_of(c)
    return {f"{tag}_atk1": a["attacks"][0], f"{tag}_atk2": a["attacks"][1],
            f"{tag}_path": a["path_attack"], f"{tag}_def": a["defense"]}


def battle_story(a, b, result, loot=None, change=None):
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
    loot = loot or {}
    change = change or {"kind": "same"}
    fmt = dict(
        x=x["name"], y=y["name"], x_sect=x["sect"], y_sect=y["sect"],
        x_tech=x["technique"], y_tech=y["technique"], x_elem=x["element"], y_elem=y["element"],
        w=w["name"], l=l["name"], w_tech=w["technique"], l_tech=l["technique"],
        w_sect=w["sect"], l_sect=l["sect"], w_treasure=w["treasure"], l_treasure=l["treasure"],
        place=random.choice(gametext.BATTLE_PLACES), **move_fields("w", w), **move_fields("l", l),
        **move_fields("x", x), **move_fields("y", y),
        # a big power gap already gets its own lines, so the realm comparison is skipped then
        gap="" if big_gap else realm_gap_text(w, l),
        strong=strong["name"], weak=weak["name"],
        strong_power=f"{strong['score']:,.0f}", weak_power=f"{weak['score']:,.0f}",
        adv=adv["name"], dis=dis["name"], adv_elem=adv["element"], dis_elem=dis["element"],
        stolen=loot.get("stolen") or "", found=loot.get("found") or "",
        w_realm=w["realm"], l_realm=l["realm"])
    parts = [random.choice(gametext.BATTLE_OPENINGS[(x["path"]["name"], y["path"]["name"])])]
    if tier:                                             # the stronger fighter shows off
        parts.append(random.choice(gametext.BATTLE_GAP_SETUPS[tier]))
    parts.append(random.choice(gametext.BATTLE_CLASHES))
    kind = battle_class(result["p_winner"])
    pool = gametext.BATTLE_EXCHANGES[kind]                        # the rest of the arsenal in action
    parts += random.sample(pool, 2 if kind in ("close", "upset") else 1)
    if edge:                                             # one element has the upper hand
        parts.append(random.choice(gametext.BATTLE_ELEMENT_LINES))
    parts.append(random.choice(gametext.BATTLE_TURNS[kind]))
    parts.append(random.choice(gametext.BATTLE_ENDINGS[(w["path"]["name"], l["path"]["name"])]))
    if loot.get("blocked"):                              # ...unless a talisman saves it...
        parts.append(random.choice(gametext.BATTLE_TALISMAN))
    elif loot.get("stolen"):                             # a Demonic winner takes the treasure...
        parts.append(random.choice(gametext.BATTLE_LOOT))
    elif loot.get("nothing"):                            # ...or finds there is none
        parts.append(random.choice(gametext.BATTLE_NO_LOOT))
    elif loot.get("missed"):                             # ...or does not get the chance this time
        parts.append(random.choice(gametext.BATTLE_STEAL_MISS))
    if big_gap:                                          # arrogance paid off, or did not
        parts.append(random.choice(gametext.BATTLE_GAP_AFTERMATH[(tier, w is strong)]))
    if loot.get("found"):                                # a lucky find after the fight
        parts.append(random.choice(gametext.BATTLE_FINDS))
    if change["kind"] == "upset":                        # a weaker realm won: fame and shame
        parts.append(random.choice(gametext.BATTLE_REP_GAIN))
        parts.append(random.choice(gametext.BATTLE_REP_LOSS_LIGHT if change["light"] else gametext.BATTLE_REP_LOSS_HEAVY))
    text = " ".join(p.format(**fmt) for p in parts)
    if w["personalities"]:
        text += f" As ever, {w['name']} {random.choice(w['personalities'])['trait']}."
    return text


def perform_battle(ids, key, profiles):
    """Runs one duel between the two SteamIDs in ids: loads both cultivators, refuses dead
    ones, fights, saves loot and reputation. Returns everything a front end needs to show it
    (a, b, info_a, info_b, result, story, loot, change). Nothing is printed here."""
    if ids[0] == ids[1]:
        raise logs.SteamError("Pick two different profiles: a cultivator cannot duel themselves.")
    (info_a, _, _, a), (info_b, _, _, b) = [generator.build_cultivator(i, key, profiles) for i in ids]
    dead = [(c, inf) for c, inf in ((a, info_a), (b, info_b)) if c["death"]]
    if dead:                                             # the dead cannot duel
        who = "; ".join(f"{c['name']} (Steam: {inf['name']}) died in Year {c['death']['year']} "
                        f"of the Heavenly Calendar, aged {c['death']['age']:,}" for c, inf in dead)
        raise logs.SteamError(f"{who}. The dead cannot duel, so there is no duel.")
    result = fight(a, b, ids[0], ids[1])
    loot = resolve_loot(result["winner"], result["loser"])
    change = reputation_change(result["winner"], result["loser"])
    story = battle_story(a, b, result, loot, change)
    apply_loot(ids, a, b, result, loot)                  # written to the inventory files
    apply_reputation(ids, a, b, result, change)          # ...and the reputation points
    now = time.time()
    for me, other, cid, p, won in ((a, b, ids[0], result["p_a"], result["winner"] is a),
                                   (b, a, ids[1], result["p_b"], result["winner"] is b)):
        rep = (change["gain"] if won else -change["loss"]) if change["kind"] == "upset" else 0
        storage.add_activity(cid, {"at": now, "type": "duel", "won": won, "other": other["name"],
                                   "other_realm": other["realm"], "p": p, "rep": rep,
                                   "upset": bool(result["upset"]) and won})
    return {"a": a, "b": b, "info_a": info_a, "info_b": info_b, "result": result,
            "story": story, "loot": loot, "change": change}
