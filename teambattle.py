"""Team battles: 2 vs 2 or 3 vs 3. Odds, the fixed winner, loot, reputation and the story."""

import random
import time

import combat
import gamedata
import gametext
import generator
import logs
import storage


TEAM_SIZES = (2, 3)
TEAM_REP_FACTOR = 0.5          # a team battle changes reputation by half of what a duel would
PATH_ORDER = ["Righteous", "Mixed", "Demonic"]


def team_type(team):
    """'Righteous' or 'Demonic' if every member walks that path, else 'Mixed'."""
    paths = {c["path"]["name"] for c in team}
    return paths.pop() if len(paths) == 1 else "Mixed"


def team_strength(team):
    return sum(c["score"] + combat.BATTLE_SCORE_FLOOR for c in team)


def team_odds(a_team, b_team):
    """Chance (0 to 1) that team a beats team b: the teams' combined power, and the average
    element matchup over every pair of fighters. Never fully certain (0.1% to 99.9%)."""
    sa = team_strength(a_team) ** combat.BATTLE_EXPONENT
    sb = team_strength(b_team) ** combat.BATTLE_EXPONENT
    power = sa / (sa + sb)
    edges = [combat.element_edge(x["element"], y["element"]) for x in a_team for y in b_team]
    shift = combat.AFFINITY_BONUS * sum(edges) / len(edges)
    return min(0.999, max(0.001, power + shift)), power, shift


def check_teams(ids_a, ids_b):
    """Raises SteamError unless the teams are 2 vs 2 or 3 vs 3 with nobody listed twice."""
    if len(ids_a) != len(ids_b) or len(ids_a) not in TEAM_SIZES:
        raise logs.SteamError("A team battle is 2 vs 2 or 3 vs 3: both teams need the same "
                              "number of fighters, two or three.")
    everyone = list(ids_a) + list(ids_b)
    if len(set(everyone)) != len(everyone):
        raise logs.SteamError("Every fighter can only be in the battle once: the same cultivator "
                              "is listed twice.")


def fight_teams(team_a, team_b, rng=random):
    """Decides the battle with a dice roll: team a wins with the chance team_odds() says. With
    BATTLE_UPSETS off the favorite always wins."""
    p_a, p_power, shift = team_odds(team_a, team_b)
    favorite_a = p_a >= 0.5
    a_wins = rng.random() < p_a if combat.BATTLE_UPSETS else favorite_a
    p_winner = p_a if a_wins else 1 - p_a
    return {"p_a": p_a, "p_b": 1 - p_a, "p_power_a": p_power, "element_shift_a": shift,
            "even": abs(p_a - 0.5) < 1e-9, "winner_side": "a" if a_wins else "b",
            "favorite_side": "a" if favorite_a else "b", "p_winner": p_winner,
            "upset": p_winner < 0.5}


def average_realm(team):
    return sum(c["realm_index"] for c in team) / len(team)


def team_reputation_change(winners, losers):
    """{'kind': 'upset' | 'same' | 'expected', 'gap': realms (average, rounded), 'gain': per
    winner, 'loss': per loser, 'light': True if both teams are entirely Righteous}."""
    gap = round(average_realm(losers) - average_realm(winners))
    if gap == 0:
        return {"kind": "same", "gap": 0, "gain": 0, "loss": 0, "light": False}
    if gap < 0:
        return {"kind": "expected", "gap": gap, "gain": 0, "loss": 0, "light": False}
    light = team_type(winners) == "Righteous" and team_type(losers) == "Righteous"
    factor = TEAM_REP_FACTOR * (combat.REP_LOSS_RIGHTEOUS_FACTOR if light else 1)
    return {"kind": "upset", "gap": gap,
            "gain": round(gap * combat.REP_GAIN_PER_REALM * TEAM_REP_FACTOR),
            "loss": round(gap * combat.REP_LOSS_PER_REALM * factor), "light": light}


def apply_team_reputation(members, winners_side, change):
    """Saves the reputation each fighter won or lost. members: {'a': [(id, c)...], 'b': [...]}.
    Fills change['gain'] / change['loss'] with the smallest real amounts (the loss stops at 0)
    and change['ranks'] with {name: (before, after)}."""
    change["ranks"] = {}
    if change["kind"] != "upset":
        return
    now = time.time()
    real_gain, real_loss = [], []
    for side in ("a", "b"):
        won = side == winners_side
        others = [c for _, c in members["b" if side == "a" else "a"]]
        for cid, c in members[side]:
            rep = c["reputation"]
            delta = change["gain"] if won else -change["loss"]
            old = storage.read_duel_rep(cid)[0]
            base = rep.get("base_points", rep["points"] - rep.get("duel_points", 0))
            new = max(-base, old + delta)
            storage.write_duel_rep(cid, new, {"at": now, "points": new - old, "won": won,
                                              "other": ", ".join(o["name"] for o in others),
                                              "realm": c["realm"], "other_realm": others[0]["realm"]})
            before = rep["rank"]
            c["reputation"] = combat.with_duel_points(rep, new)
            change["ranks"][c["name"]] = (before, c["reputation"]["rank"])
            (real_gain if won else real_loss).append(abs(new - old))
            logs.RUN_LOG.note(f"reputation: {c['name']} ({cid}) {new - old:+d} for the team battle, "
                              f"now {c['reputation']['points']}")
    change["gain"], change["loss"] = min(real_gain), min(real_loss)


def pair_loot(winners, losers, ids_of, rng=random):
    """Every winner (strongest first) faces the loser of the same rank for loot, using the
    duel loot rules. Returns a list of {'winner', 'loser', 'loot'} and saves what changed."""
    out = []
    for w, l in zip(winners, losers):
        loot = combat.resolve_loot(w, l, rng)
        combat.apply_loot((ids_of[id(w)], ids_of[id(l)]), w, l, {"winner": w, "loser": l}, loot)
        out.append({"winner": w, "loser": l, "loot": loot})
    return out


def names_text(team):
    names = [c["name"] for c in team]
    return names[0] + " and " + names[1] if len(names) == 2 else ", ".join(names[:-1]) + " and " + names[-1]


def sect_text(team):
    sects = list(dict.fromkeys(c["sect"] for c in team))
    return " and ".join(f"the {s}" for s in sects)


def best_weapon(c):
    """The most expensive pavilion weapon the cultivator owns, or None."""
    owned = [gamedata.PAVILION_BY_ID[i] for i, n in c["pavilion"]["items"].items()
             if n and i in gamedata.PAVILION_BY_ID and gamedata.PAVILION_BY_ID[i]["kind"] == "Weapon"]
    return max(owned, key=lambda item: item["price"])["name"] if owned else None


def team_fields(tag, team):
    f = {f"{tag}_names": names_text(team), f"{tag}_sect_text": sect_text(team),
         f"{tag}_realm": team[0]["realm"]}
    for i in range(3):
        c = team[i] if i < len(team) else None
        n = i + 1
        f[f"{tag}{n}"] = c["name"] if c else ""
        f[f"{tag}{n}_tech"] = c["technique"] if c else ""
        f[f"{tag}{n}_elem"] = c["element"] if c else ""
        f[f"{tag}{n}_treasure"] = c["treasure"] if c else ""
        f[f"{tag}{n}_weapon"] = (best_weapon(c) or "") if c else ""
        f.update(combat.move_fields(f"{tag}{n}", c) if c else
                 {f"{tag}{n}_{k}": "" for k in ("atk1", "atk2", "path", "def")})
    return f


def team_story(team_a, team_b, result, pairs=None, change=None, rng=random):
    """The story of the battle. The winner is decided by fight_teams(); the telling is random.
    It depends on the paths of both teams, the realms, the arsenal, weapons, treasures and
    the personalities of the fighters."""
    pairs = pairs or []
    change = change or {"kind": "same"}
    won_a = result["winner_side"] == "a"
    winners, losers = (team_a, team_b) if won_a else (team_b, team_a)
    ta, tb = team_type(team_a), team_type(team_b)
    if PATH_ORDER.index(tb) < PATH_ORDER.index(ta):
        x_team, y_team = team_b, team_a
    else:
        x_team, y_team = team_a, team_b
    tx, ty = team_type(x_team), team_type(y_team)
    size = len(team_a)
    fmt = dict(place=rng.choice(gametext.BATTLE_PLACES))
    for tag, team in (("x", x_team), ("y", y_team), ("w", winners), ("l", losers)):
        fmt.update(team_fields(tag, team))
    kind = combat.battle_class(result["p_winner"])
    parts = [rng.choice(gametext.TEAM_OPENINGS[(tx, ty)]), rng.choice(gametext.TEAM_CLASHES)]
    # arsenal in action: a treasure and a weapon from the fighters who have them
    weapon_owners = [c for c in team_a + team_b if best_weapon(c)]
    if weapon_owners:
        who = rng.choice(weapon_owners)
        foe = rng.choice(team_b if who in team_a else team_a)
        parts.append(rng.choice(gametext.TEAM_WEAPON_LINES).format(
            who=who["name"], weapon=best_weapon(who), foe=foe["name"]))
    if kind in ("close", "upset"):
        parts.append(rng.choice(gametext.TEAM_COMBOS_LOSE[size]))
    parts.append(rng.choice(gametext.TEAM_COMBOS_WIN[size]))
    parts += rng.sample(gametext.TEAM_EXCHANGES[kind], 1 if kind in ("clear", "crushing") else 2)
    treasure_owner = rng.choice(team_a + team_b)
    parts.append(rng.choice(gametext.TEAM_TREASURE_LINES).format(
        who=treasure_owner["name"], treasure=treasure_owner["treasure"]))
    parts.append(rng.choice(gametext.TEAM_TURNS[kind]))
    wr, lr = average_realm(winners), average_realm(losers)
    realm_kind = "stronger" if round(wr - lr) > 0 else "weaker" if round(wr - lr) < 0 else "even"
    parts.append(rng.choice(gametext.TEAM_REALM_LINES[realm_kind]))
    parts.append(rng.choice(gametext.TEAM_ENDINGS[(team_type(winners), team_type(losers))]))
    for p in pairs:
        loot, w, l = p["loot"], p["winner"], p["loser"]
        if loot.get("stolen"):
            parts.append(rng.choice(gametext.TEAM_LOOT_STOLEN).format(
                thief=w["name"], victim=l["name"], stolen=loot["stolen"]))
        elif loot.get("blocked"):
            parts.append(rng.choice(gametext.TEAM_LOOT_BLOCKED).format(thief=w["name"], victim=l["name"]))
        if loot.get("found"):
            parts.append(rng.choice(gametext.TEAM_LOOT_FOUND).format(finder=w["name"], found=loot["found"]))
    if change["kind"] == "upset":
        parts.append(rng.choice(gametext.TEAM_REP_GAIN))
        parts.append(rng.choice(gametext.TEAM_REP_LOSS_LIGHT if change["light"]
                                else gametext.TEAM_REP_LOSS_HEAVY))
    text = " ".join(p.format(**fmt) for p in parts)
    quirky = [c for c in team_a + team_b if c["personalities"]]
    chosen = rng.sample(quirky, min(2, len(quirky)))
    for c, line in zip(chosen, rng.sample(gametext.TEAM_PERSONALITY_LINES, len(chosen))):
        text += " " + line.format(name=c["name"], trait=rng.choice(c["personalities"])["trait"])
    return text


@storage.atomic
def perform_team_battle(ids_a, ids_b, key, profiles, rng=random):
    """Runs one team battle: loads the fighters, refuses the dead, fights, saves loot,
    reputation and activity. Returns everything a front end needs (teams sorted strongest
    first, infos, result, story, pairs, change). Nothing is printed here."""
    ids_a, ids_b = list(ids_a), list(ids_b)
    check_teams(ids_a, ids_b)
    loaded = {}
    for cid in ids_a + ids_b:
        info, _, _, c = generator.build_cultivator(cid, key, profiles)
        loaded[cid] = (info, c)
    dead = [(c, info) for info, c in loaded.values() if c["death"]]
    if dead:
        who = "; ".join(f"{c['name']} (Steam: {info['name']}) died in Year {c['death']['year']} "
                        f"of the Heavenly Calendar, aged {c['death']['age']:,}" for c, info in dead)
        raise logs.SteamError(f"{who}. The dead cannot fight, so there is no team battle.")

    def ordered(ids):                       # strongest first, ties by SteamID
        return sorted(ids, key=lambda i: (-loaded[i][1]["score"], int(i)))
    storage.require_physical(ids_a[0],dangerous=True,others=tuple((ids_a+ids_b)[1:]))
    ids_a, ids_b = ordered(ids_a), ordered(ids_b)
    team_a, team_b = [loaded[i][1] for i in ids_a], [loaded[i][1] for i in ids_b]
    result = fight_teams(team_a, team_b, rng)
    won_a = result["winner_side"] == "a"
    winners, losers = (team_a, team_b) if won_a else (team_b, team_a)
    ids_of = {id(c): i for i, (_, c) in loaded.items()}
    pairs = pair_loot(winners, losers, ids_of, rng)
    change = team_reputation_change(winners, losers)
    story = team_story(team_a, team_b, result, pairs, change, rng)
    apply_team_reputation({"a": list(zip(ids_a, team_a)), "b": list(zip(ids_b, team_b))},
                          result["winner_side"], change)
    now = time.time()
    for side, ids, team, mates_of in (("a", ids_a, team_a, team_b), ("b", ids_b, team_b, team_a)):
        won = result["winner_side"] == side
        p = result["p_" + side]
        for cid, c in zip(ids, team):
            storage.add_activity(cid, {
                "at": now, "type": "team", "won": won, "size": len(team), "p": p,
                "allies": [m["name"] for m in team if m is not c],
                "enemies": [m["name"] for m in mates_of],
                "rep": (change["gain"] if won else -change["loss"]) if change["kind"] == "upset" else 0,
                "upset": bool(result["upset"]) and won})
    logs.RUN_LOG.note(f"team battle {len(team_a)}v{len(team_b)}: "
                      f"{names_text(team_a)} vs {names_text(team_b)}, "
                      f"{'team one' if won_a else 'team two'} wins ({result['p_winner']:.0%} chance)")
    return {"ids_a": ids_a, "ids_b": ids_b, "team_a": team_a, "team_b": team_b,
            "infos_a": [loaded[i][0] for i in ids_a], "infos_b": [loaded[i][0] for i in ids_b],
            "result": result, "story": story, "pairs": pairs, "change": change}
