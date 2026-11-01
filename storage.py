"""Everything saved to disk per profile (cache/<steamid>.profile.json): the TTL cache of Steam
data plus the permanent parts (inventory, pavilion, peaks,
realm state, life/rebirth flag, activity), the history log and the duel reputation."""

import json
import os

import gamedata
import logs


# The saved profiles live in a cache folder next to the program.
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")

# How long each kind of saved Steam data is trusted before Steam is asked again (hours).
# Data that rarely changes is checked rarely, data that changes often is checked often.
# Achievements have their own rule: RECHECK_AFTER_DAYS (30 days) per game, and a game is
# also re-checked whenever its playtime changes (which is seen when "games" refreshes).
REFRESH_HOURS = {
    "friends": 1,         # the friends list: new friends are added all the time
    "games": 12,          # games owned, playtime, most played game
    "level": 12,          # Steam level
    "badges": 12,         # badge count
    "summary": 6,         # display name and account age
    "friend_names": 24,   # the display name of a friend used in a story
    "vanity": 168,        # which SteamID a custom profile name belongs to (7 days)
}
INVENTORY_HISTORY_LIMIT = 25


# ---------------------------------------------------------------------------
# The profile cache. Everything Steam tells us about a profile is saved in
# cache/<SteamID>.profile.json, and each kind of data has its own refresh time
# (REFRESH_HOURS): things that rarely change are asked for rarely, things that change
# often (the friends list) more often. So a profile looked up again 20 minutes later
# needs almost no Steam calls. Only complete, successful answers are ever saved.
# The cultivator itself is rebuilt from this data each time (instantly, and always to the
# same result), and achievements have their own cache (see further down).
# "refresh <profile>" ignores every cache. Deleting the cache folder is always safe.
# ---------------------------------------------------------------------------
PROFILE_CACHE_VERSION = 1
_NUM = (int, float)
SECTION_SHAPES = {          # what a saved section must look like to be trusted
    "summary": {"name": str, "created": (int, type(None))},
    "level": {"level": int},
    "games": {"game_count": int, "top_game": (str, type(None)), "top_hours": _NUM,
              "total_hours": _NUM, "played": list},
    "badges": {"count": int},
    "friends": {"ids": list, "note": (str, type(None))},
}
_unsaved = {}               # path -> data that could not be written to disk (read-only folder)


def ago(seconds):
    """'45s', '20m', '3h' or '2d': a short, rounded age for the log."""
    seconds = max(0, int(seconds))
    for limit, unit, size in ((90, "s", 1), (5400, "m", 60), (129600, "h", 3600)):
        if seconds < limit:
            return f"{round(seconds / size)}{unit}"
    return f"{round(seconds / 86400)}d"


def entry_fresh(entry, name, now):
    """True if a saved entry (a dict with an 'at' time) is younger than REFRESH_HOURS[name]."""
    if not isinstance(entry, dict):
        return False
    at = entry.get("at")
    if isinstance(at, bool) or not isinstance(at, _NUM):
        return False
    return 0 <= now - at < REFRESH_HOURS[name] * 3600      # a clock set backwards counts as stale


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return _unsaved.get(path)
    return data if isinstance(data, dict) else None


def store_json(path, data):
    """Saves data; if the folder is not writable it is kept in memory for this run instead."""
    if write_json(path, data):
        _unsaved.pop(path, None)
        return True
    _unsaved[path] = data
    return False


def profile_cache_path(steamid):
    return os.path.join(CACHE_DIR, f"{steamid}.profile.json")


def load_profile_cache(steamid):
    data = read_json(profile_cache_path(steamid))
    if (not data or data.get("version") != PROFILE_CACHE_VERSION
            or data.get("steamid") != str(steamid) or not isinstance(data.get("sections"), dict)):
        data = {"version": PROFILE_CACHE_VERSION, "steamid": str(steamid), "sections": {}}
    return data


def save_profile_cache(pc):
    return store_json(profile_cache_path(pc["steamid"]), pc)


def inventory_valid(inv):
    return (isinstance(inv, dict) and isinstance(inv.get("treasures"), list)
            and all(isinstance(t, str) for t in inv["treasures"])
            and isinstance(inv.get("history"), list))


def read_inventory(steamid):
    """(treasures, history) saved for this profile, or None if it has no inventory yet."""
    inv = load_profile_cache(steamid).get("inventory")
    if not inventory_valid(inv):
        return None
    return list(inv["treasures"]), [e for e in inv["history"] if isinstance(e, dict)]


def write_inventory(steamid, treasures, events=()):
    """Saves the treasures and adds events ({'at','type','item','other'}) to the history.
    Lives next to the cached Steam data, but it is not part of it: 'refresh' and the refresh
    times never touch it."""
    pc = load_profile_cache(steamid)
    inv = pc.get("inventory")
    if not inventory_valid(inv):
        inv = {"treasures": [], "history": []}
    inv["treasures"] = list(treasures)
    inv["history"] = (inv["history"] + list(events))[-INVENTORY_HISTORY_LIMIT:]
    pc["inventory"] = inv
    return save_profile_cache(pc)


def read_pavilion(steamid):
    """{'items': {id: count}, 'spent': sect points spent, 'earned': the most sect points ever
    credited, 'history': [...]} saved for this profile; all empty if nothing was ever bought
    here (or the saved data is damaged)."""
    d = load_profile_cache(steamid).get("pavilion")
    empty = {"items": {}, "spent": 0, "earned": 0, "bonus": 0, "history": []}
    def whole(v, low):
        return isinstance(v, int) and not isinstance(v, bool) and v >= low
    if (isinstance(d, dict) and whole(d.get("spent"), 0) and isinstance(d.get("items"), dict)
            and all(isinstance(k, str) and whole(v, 1) for k, v in d["items"].items())
            and isinstance(d.get("history"), list)):
        return {"items": dict(d["items"]), "spent": d["spent"],
                "earned": d["earned"] if whole(d.get("earned"), 0) else 0,
                "bonus": d["bonus"] if isinstance(d.get("bonus"), int)
                and not isinstance(d.get("bonus"), bool) else 0,
                "history": [e for e in d["history"] if isinstance(e, dict)]}
    return empty


def write_pavilion(steamid, items, spent, event=None, earned=None, bonus=None):
    """Saves the goods bought in the pavilion and the sect points spent on them. 'earned' is
    the most sect points ever credited from achievements; left out, the saved one is kept."""
    pc = load_profile_cache(steamid)
    old = read_pavilion(steamid)
    history = old["history"] + ([event] if event else [])
    pc["pavilion"] = {"items": {k: v for k, v in items.items() if v > 0}, "spent": int(spent),
                      "earned": int(old["earned"] if earned is None else earned),
                      "bonus": int(old["bonus"] if bonus is None else bonus),
                      "history": history[-INVENTORY_HISTORY_LIMIT:]}
    return save_profile_cache(pc)


# Steam numbers that only ever go up. The level, paid games, hours in the top game and badges a
# profile has ever shown are remembered in its file (key "peaks"). Later lookups use the higher of
# the saved and the current number, so a dip in Steam's data (hidden badges, a refunded game, a
# glitchy answer) or a refresh can never take power or reputation away: only genuinely new
# levels, games, hours and badges add to it.
PEAK_FIELDS = ("level", "game_count", "top_hours", "badges")


def read_peaks(steamid):
    d = load_profile_cache(steamid).get("peaks")
    if not isinstance(d, dict):
        return {}
    good = {}
    for f in PEAK_FIELDS:
        v = d.get(f)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0:
            good[f] = v
    if isinstance(d.get("top_game"), str):
        good["top_game"] = d["top_game"]
    return good


def apply_peaks(steamid, info):
    """Returns a copy of info where every number in PEAK_FIELDS is at least the highest ever
    seen for this profile, and saves any new high. The Steam data cached in the profile file is
    left as Steam reported it."""
    saved = read_peaks(steamid)
    new, eff, raised = dict(saved), dict(info), []
    for f in PEAK_FIELDS:
        cur, old = info.get(f) or 0, saved.get(f)
        if old is not None and old > cur:
            eff[f] = old
            if f == "top_hours" and saved.get("top_game"):
                eff["top_game"] = saved["top_game"]      # the hours belong to that game
        elif old is None or cur > old:
            new[f] = cur
            if f == "top_hours":
                new["top_game"] = info.get("top_game") or ""
            if old is not None:
                raised.append(f)
    if eff["badges"] > 0:
        eff["badges_hidden"] = False
    if new != saved:
        pc = load_profile_cache(steamid)
        pc["peaks"] = new
        save_profile_cache(pc)
    if raised:
        logs.RUN_LOG.note(f"peaks: new highs saved for {', '.join(raised)}")
    kept = [f for f in PEAK_FIELDS if saved.get(f) is not None and saved[f] > (info.get(f) or 0)]
    if kept:
        logs.RUN_LOG.note(f"peaks: Steam now shows less {', '.join(kept)} than ever before; "
                          f"the highest known values are kept")
    return eff


_KEEP = object()
INCARNATION_FIELDS = {"gender": str, "name": str, "sect": str, "element": str, "talent": str,
                      "title_roll": int, "lifespan_roll": int, "immortal_lifespan": int,
                      "birth_year": int, "age": int, "count": int, "arsenal": dict}


def read_life(steamid):
    """{'dead': the death record saved when they died (None if alive), 'last_roll': time of the
    last rebirth roll, 'incarnation': the new body of a reborn cultivator, 'rebirths': how
    many times they were reborn}. Damaged data counts as 'nothing saved'."""
    d = load_profile_cache(steamid).get("life")
    out = {"dead": None, "last_roll": None, "incarnation": None, "rebirths": 0}
    if not isinstance(d, dict):
        return out
    dead = d.get("dead")
    if isinstance(dead, dict) and isinstance(dead.get("age"), int) and isinstance(dead.get("year"), int) \
            and "killer" in dead and "scene" in dead and "friend_id" in dead:
        out["dead"] = dead
    t = d.get("last_roll")
    if isinstance(t, (int, float)) and not isinstance(t, bool):
        out["last_roll"] = float(t)
    inc = d.get("incarnation")
    if (isinstance(inc, dict)
            and all(isinstance(inc.get(k), t_) and not isinstance(inc.get(k), bool) for k, t_ in INCARNATION_FIELDS.items())
            and inc["gender"] in ("male", "female") and inc["element"] in gamedata.ELEMENTS
            and inc["talent"] in gamedata.TALENT_BY_NAME):
        out["incarnation"] = inc
    n = d.get("rebirths")
    if isinstance(n, int) and not isinstance(n, bool) and n >= 0:
        out["rebirths"] = n
    return out


def write_life(steamid, dead=_KEEP, last_roll=_KEEP, incarnation=_KEEP, rebirths=_KEEP):
    """Saves the parts given (None clears dead/incarnation) and keeps the rest."""
    cur = read_life(steamid)
    for k, v in (("dead", dead), ("last_roll", last_roll), ("incarnation", incarnation),
                 ("rebirths", rebirths)):
        if v is not _KEEP:
            cur[k] = v
    pc = load_profile_cache(steamid)
    pc["life"] = cur
    return save_profile_cache(pc)


def read_realm_state(steamid):
    """{'realm_index': the realm they hold (None if never saved), 'last_failed': time of the
    last failed breakthrough or None}. The realm only changes through a breakthrough."""
    d = load_profile_cache(steamid).get("realm_state")
    out = {"realm_index": None, "last_failed": None, "lifespan_lost": 0, "born_realm": None}
    if isinstance(d, dict):
        b = d.get("born_realm")
        if isinstance(b, int) and not isinstance(b, bool) and 0 <= b < len(gamedata.REALMS):
            out["born_realm"] = b
        lost = d.get("lifespan_lost")
        if isinstance(lost, int) and not isinstance(lost, bool) and lost > 0:
            out["lifespan_lost"] = lost
        i = d.get("realm_index")
        if isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(gamedata.REALMS):
            out["realm_index"] = i
        t = d.get("last_failed")
        if isinstance(t, (int, float)) and not isinstance(t, bool):
            out["last_failed"] = float(t)
    return out


def write_realm_state(steamid, realm_index, last_failed=None, lifespan_lost=None):
    """Saves the realm held, the time of the last failed breakthrough and the years of lifespan
    lost to failed breakthroughs (left out: the saved number is kept)."""
    old = read_realm_state(steamid)
    lost = old["lifespan_lost"] if lifespan_lost is None else lifespan_lost
    # born_realm: the realm they were generated in (an immortal born as one has a different age
    # rule from one who ascended). Profiles saved before this existed count as born in the realm
    # they held until now.
    born = old["born_realm"]
    if born is None:
        born = old["realm_index"] if old["realm_index"] is not None else realm_index
    pc = load_profile_cache(steamid)
    pc["realm_state"] = {"realm_index": int(realm_index), "last_failed": last_failed,
                         "lifespan_lost": int(lost), "born_realm": int(born)}
    return save_profile_cache(pc)


ACTIVITY_LIMIT = 200


def read_activity(steamid):
    """What this cultivator did recently that nothing else records: duels and breakthroughs."""
    d = load_profile_cache(steamid).get("activity")
    return [e for e in d if isinstance(e, dict) and isinstance(e.get("at"), (int, float))] \
        if isinstance(d, list) else []


def add_activity(steamid, event):
    pc = load_profile_cache(steamid)
    pc["activity"] = (read_activity(steamid) + [event])[-ACTIVITY_LIMIT:]
    return save_profile_cache(pc)


def history_entries(steamid, limit=80):
    """Everything this cultivator did recently, newest first, as dicts {'at', 'kind', 'text'}.
    It merges the duel and breakthrough log with the inventory history (found, stolen, robbed,
    bought) and the pavilion history (purchases, talisman use). kind is one of: duel_win,
    duel_loss, bought, treasure, talisman, breakthrough_ok, breakthrough_fail, start."""
    pc = load_profile_cache(steamid)
    entries, seen = [], set()

    def add(at, kind, text, key=None):
        if key is not None:
            if key in seen:
                return
            seen.add(key)
        entries.append({"at": at, "kind": kind, "text": text})

    activity = read_activity(steamid)
    first_duel = min([e["at"] for e in activity if e.get("type") == "duel"], default=None)
    for e in activity:
        if e.get("type") == "duel":
            p, rep = e.get("p"), e.get("rep", 0)
            text = (f"{'Defeated' if e.get('won') else 'Lost to'} {e.get('other', 'someone')} "
                    f"({e.get('other_realm', '?')}) in a duel"
                    + (f" (win chance {p * 100:.0f}%)" if isinstance(p, (int, float)) else "")
                    + (" - an upset!" if e.get("upset") else "")
                    + (f". Reputation {rep:+d}" if rep else ""))
            add(e["at"], "duel_win" if e.get("won") else "duel_loss", text)
        elif e.get("type") == "adventure" and e.get("summary"):
            add(e["at"], "adventure", e["summary"])
        elif e.get("type") == "reborn":
            add(e["at"], "reborn", e.get("summary", "Reborn into a new body"))
        elif e.get("type") == "breakthrough":
            how = f" ({e.get('chance', 0) * 100:.0f}% chance" \
                  + (", helped by a Heaven-Defying Breakthrough Pill)" if e.get("pill") else ")")
            if e.get("success"):
                add(e["at"], "breakthrough_ok",
                    f"Broke through from {e.get('from')} to {e.get('to')}{how}")
            else:
                lost = e.get("lost", 0)
                add(e["at"], "breakthrough_fail",
                    f"The breakthrough to {e.get('to')} failed{how}"
                    + (f" and cost {lost:,} years of lifespan" if lost else "")
                    + (". The lifespan ran out and they died" if e.get("fatal") else ""))
    pav = pc.get("pavilion")
    for e in (pav.get("history", []) if isinstance(pav, dict) else []):
        if not isinstance(e, dict) or not isinstance(e.get("at"), (int, float)):
            continue
        if e.get("type") == "bought":
            add(e["at"], "bought", f"Bought {e.get('item')} for {e.get('price', 0):,} sect points",
                ("bought", round(e["at"], 2), e.get("item")))
        elif e.get("type") == "talisman used":
            add(e["at"], "talisman", f"A Spatial Escape Talisman saved their treasure from "
                                      f"{e.get('other', 'a thief')}")
    inv = pc.get("inventory")
    for e in (inv.get("history", []) if isinstance(inv, dict) else []):
        if not isinstance(e, dict) or not isinstance(e.get("at"), (int, float)):
            continue
        who, item, kind = e.get("other") or "someone", e.get("item", "a treasure"), e.get("type")
        if kind == "robbed":
            add(e["at"], "treasure", f"Robbed of {item} by {who}")
        elif kind == "stole":
            add(e["at"], "treasure", f"Took {item} from {who}")
        elif kind == "found":
            add(e["at"], "treasure", f"Found {item} " + ("on an adventure" if e.get("other") == "adventure"
                                                         else "after a duel"))
        elif kind == "sold":
            add(e["at"], "sold", f"Sold {item} for {e.get('price', 0):,} sect points")
        elif kind == "bought":
            add(e["at"], "bought", f"Bought {item} at the Martial Pavilion",
                ("bought", round(e["at"], 2), item))
        elif kind == "start":
            add(e["at"], "start", f"Began the journey owning {item}")
    rep = pc.get("duel_reputation")             # duels from before the activity log existed
    for e in (rep.get("history", []) if isinstance(rep, dict) else []):
        if (isinstance(e, dict) and isinstance(e.get("at"), (int, float))
                and (first_duel is None or e["at"] < first_duel - 1)):
            won = e.get("won")
            add(e["at"], "duel_win" if won else "duel_loss",
                f"{'Defeated' if won else 'Lost to'} {e.get('other', 'someone')} "
                f"({e.get('other_realm', '?')}) in a duel. Reputation {e.get('points', 0):+d}")
    entries.sort(key=lambda x: x["at"], reverse=True)
    return entries[:limit]


def read_duel_rep(steamid):
    """(points, history) of the fame or shame this profile won in duels; (0, []) if none."""
    d = load_profile_cache(steamid).get("duel_reputation")
    if (isinstance(d, dict) and isinstance(d.get("points"), int) and not isinstance(d["points"], bool)
            and isinstance(d.get("history"), list)):
        return d["points"], [e for e in d["history"] if isinstance(e, dict)]
    return 0, []


def write_duel_rep(steamid, points, event=None):
    """Saves the duel reputation points and adds an event to the history."""
    pc = load_profile_cache(steamid)
    _, history = read_duel_rep(steamid)
    pc["duel_reputation"] = {"points": int(points),
                             "history": (history + ([event] if event else []))[-INVENTORY_HISTORY_LIMIT:]}
    return save_profile_cache(pc)


def describe_event(e):
    """One line about an inventory event, for the card."""
    when = logs.stamp(e["at"])[:10] if isinstance(e.get("at"), (int, float)) else "?"
    who, item = e.get("other") or "someone", e.get("item", "a treasure")
    kind = e.get("type")
    if kind == "robbed":
        return f"robbed of {item} by {who} ({when})"
    if kind == "stole":
        return f"took {item} from {who} ({when})"
    if kind == "found":
        return (f"found {item} on an adventure ({when})" if e.get("other") == "adventure"
                else f"found {item} after a duel ({when})")
    if kind == "sold":
        return f"sold {item} for {e.get('price', 0):,} sect points ({when})"
    if kind == "bought":
        return f"bought {item} at the Martial Pavilion ({when})"
    return f"{kind} ({when})"


def section_fresh(pc, name, now):
    """True if the saved section can be used without asking Steam: young enough and intact."""
    sec = pc["sections"].get(name)
    if not entry_fresh(sec, name, now) or not isinstance(sec.get("value"), dict):
        return False
    return all(isinstance(sec["value"].get(k), t) and not isinstance(sec["value"].get(k), bool)
               for k, t in SECTION_SHAPES[name].items())


def load_lookups():
    """Saved custom-name -> SteamID answers and friends' display names (shared by all profiles)."""
    data = read_json(os.path.join(CACHE_DIR, "lookups.json"))
    if not data or data.get("version") != PROFILE_CACHE_VERSION:
        data = {"version": PROFILE_CACHE_VERSION}
    for k in ("vanity", "names"):
        if not isinstance(data.get(k), dict):
            data[k] = {}
    return data


def save_lookups(lookups):
    return store_json(os.path.join(CACHE_DIR, "lookups.json"), lookups)

_cache_warned = False


def write_json(path, data):
    """Writes a cache file; returns False (after one warning) if the folder is not writable."""
    global _cache_warned
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, path)       # all or nothing: an interrupted save never leaves half a file
        return True
    except OSError as e:
        if not _cache_warned:
            _cache_warned = True
            print(f"\n  (Could not save the cache in '{CACHE_DIR}': {e}. Carrying on without it.)")
        return False
