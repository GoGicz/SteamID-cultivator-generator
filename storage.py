"""SQLite-backed persistent world and character records, legacy JSON migration,
Steam cache helpers, shared calendar, history, backups and developer editing."""

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
# Steam refresh never deletes permanent world data. Never delete the save folder.
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
        import copy
        return copy.deepcopy(_unsaved.get(path))
    return data if isinstance(data, dict) else None


def store_json(path, data):
    """Saves data; if the folder is not writable it is kept in memory for this run instead."""
    if write_json(path, data):
        _unsaved.pop(path, None)
        return True
    _unsaved[path] = data
    return False


def profile_cache_path(steamid):
    """Legacy file locator; current profile persistence is in world.db."""
    return os.path.join(CACHE_DIR, f"{steamid}.profile.json")


def _profile_read(steamid,cache,field,default):
    with world_transaction(cache) as db:
        # A world transaction/snapshot owns one stable SQLite view. Any DML,
        # including salary credits or direct profile edits, invalidates raw reads.
        token=(id(db),db.total_changes,db.in_transaction)
        raw_reads=getattr(_world_local,'raw_profile_reads',None)
        if raw_reads is None or raw_reads[0]!=token:
            raw_reads=(token,{});_world_local.raw_profile_reads=raw_reads
        rows=raw_reads[1];actor=str(steamid)
        if actor not in rows:
            if len(rows)>=64:rows.clear()
            rows[actor]=paid_profile_row(db,steamid)
        row=rows[actor]
        if not row:
            return default if field is not None else {"version": PROFILE_CACHE_VERSION, "steamid": str(steamid), "sections": {}}
        raw=row[0]
        cache_data=getattr(_world_local,'profile_reads',None)
        if cache_data is None:
            cache_data={};_world_local.profile_reads=cache_data
        previous=cache_data.get(str(steamid))
        try:
            if previous and previous[0]==raw:
                # Compare authoritative bytes refreshed after database writes.
                # Cached values never escape to mutable callers.
                if field is None:return json.loads(raw)
                data=previous[1]
                if data is None:
                    data=json.loads(raw);cache_data[str(steamid)]=(raw,data)
            else:
                data=decode_profile_json(raw)
                if not isinstance(data,dict) or data.get('steamid')!=str(steamid) or data.get('version')!=PROFILE_CACHE_VERSION or not isinstance(data.get('sections'),dict):
                    raise ValueError('Invalid profile identity or format.')
                if len(cache_data)>=64:cache_data.clear()
                cache_data[str(steamid)]=(raw,None if field is None else data)
                if field is None:return data
            return copy.deepcopy(data.get(field,default))
        except (ValueError,TypeError) as exc:
            raise logs.SteamError(f'Invalid saved profile {steamid}: {exc}. Restore a backup or repair it in Developer tools.') from exc


def load_profile_cache(steamid, cache=None):
    return _profile_read(steamid,cache,None,None)


def profile_field(steamid,field,default=None):
    return _profile_read(steamid,None,field,default)


def save_profile_cache(pc, *, durable=False):
    # All gameplay writes are durable now; retained keyword keeps callers compatible.
    with world_transaction() as db:
        # Copy only history lists containing a newly dated event. Other fields
        # are serialized synchronously without changing caller-owned objects.
        value=pc.copy()
        previous=None
        day=None
        def dated(container,key):
            nonlocal previous,day
            entries=container.get(key,[])
            result=entries
            for index,event in enumerate(entries):
                if not isinstance(event,dict) or 'world_day' in event:continue
                if previous is None:
                    old=load_profile_cache(pc['steamid'])
                    previous=list(old.get('activity',[]))
                    for section in ('inventory','pavilion','duel_reputation'):
                        previous.extend((old.get(section) or {}).get('history',[]))
                    for member in (old.get('sect_memberships') or {}).values():
                        previous.extend(member.get('history',[]))
                if event in previous:continue
                if day is None:day=world_state()['day']
                if result is entries:result=list(entries)
                result[index]=dict(event,world_day=day)
            return container if result is entries else dict(container,**{key:result})
        value=dated(value,'activity')
        for section in ('inventory','pavilion','duel_reputation'):
            if value.get(section):value[section]=dated(value[section],'history')
        if value.get('sect_memberships'):
            value['sect_memberships']={sect:dated(member,'history') for sect,member in value['sect_memberships'].items()}
        fold_salary_credit(db,steamid=value['steamid'])
        _write_profile(db, value)
        return True


def inventory_valid(inv):
    return (isinstance(inv, dict) and isinstance(inv.get("treasures"), list)
            and all(isinstance(t, str) for t in inv["treasures"])
            and isinstance(inv.get("history"), list))


def read_inventory(steamid):
    """(treasures, history) saved for this profile, or None if it has no inventory yet."""
    inv = profile_field(steamid,"inventory")
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
    d = profile_field(steamid,"pavilion")
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
    d = profile_field(steamid,"peaks")
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
    d = profile_field(steamid,"life")
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
    if isinstance(dead,dict) and 'world_day' not in dead:
        clock=profile_field(steamid,'calendar')
        if clock:
            dead=dict(dead,world_day=world_state()['day'],year=int(world_state()['day'])//DAYS_PER_YEAR)
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
    d = profile_field(steamid,"realm_state")
    out = {"realm_index": None, "last_failed": None, "lifespan_lost": 0, "born_realm": None, "vitals": None}
    if isinstance(d, dict):
        v = d.get("vitals")
        if (isinstance(v, dict) and type(v.get("base_lifespan")) is int and v["base_lifespan"] > 0
                and (v.get("age") is None or type(v.get("age")) is int and v["age"] >= 0)
                and type(v.get("birth_year")) is int):
            out["vitals"] = dict(v)
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


def write_realm_state(steamid, realm_index, last_failed=None, lifespan_lost=None, vitals=_KEEP):
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
    saved_vitals = old["vitals"] if vitals is _KEEP else vitals
    if saved_vitals is not None:
        pc["realm_state"]["vitals"] = dict(saved_vitals)
    return save_profile_cache(pc)


ACTIVITY_LIMIT = 200


def read_activity(steamid):
    """What this cultivator did recently that nothing else records: duels and breakthroughs."""
    return _activity_entries(profile_field(steamid,"activity"))


def _activity_entries(d):
    return [e for e in d if isinstance(e, dict) and isinstance(e.get("at"), (int, float))] \
        if isinstance(d, list) else []


def add_activity(steamid, event):
    pc = load_profile_cache(steamid)
    if pc.get('world_npc'):
        event=dict(event,routine=not significant_activity(event))
    pc["activity"] = (_activity_entries(pc.get('activity')) + [event])[-ACTIVITY_LIMIT:]
    return save_profile_cache(pc)


def history_entries(steamid, limit=80):
    """Everything this cultivator did recently, newest first, as dicts {'at', 'kind', 'text'}.
    It merges the duel and breakthrough log with the inventory history (found, stolen, robbed,
    bought) and the pavilion history (purchases, talisman use). kind is one of: duel_win,
    duel_loss, bought, treasure, talisman, breakthrough_ok, breakthrough_fail, start, sold, adventure,
    reborn, team_win, team_loss."""
    pc = load_profile_cache(steamid)
    entries, seen = [], set()

    def add(at, kind, text, key=None):
        if key is not None:
            if key in seen:
                return
            seen.add(key)
        entries.append({"at": at, "kind": kind, "text": text})

    activity = read_activity(steamid)
    if pc.get('world_npc'):
        activity += npc_history_archive(steamid,limit)
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
        elif e.get("type") == "team":
            p, rep, allies = e.get("p"), e.get("rep", 0), e.get("allies") or []
            size = e.get("size", len(allies) + 1)
            text = (f"{'Won' if e.get('won') else 'Lost'} a {size} vs {size} team battle"
                    + (f" with {', '.join(allies)}" if allies else "")
                    + f" against {', '.join(e.get('enemies') or ['someone'])}"
                    + (f" (win chance {p * 100:.0f}%)" if isinstance(p, (int, float)) else "")
                    + (" - an upset!" if e.get("upset") else "")
                    + (f". Reputation {rep:+d}" if rep else ""))
            add(e["at"], "team_win" if e.get("won") else "team_loss", text)
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
    dated = {e.get('at'):e['world_day'] for e in activity if 'world_day' in e}
    for section in ('activity','pavilion','inventory','duel_reputation'):
        source = pc.get(section,[]) if section=='activity' else (pc.get(section) or {}).get('history',[])
        for event in source:
            if isinstance(event,dict) and 'world_day' in event:
                dated[event.get('at')] = event['world_day']
    for entry in entries:
        entry['when'] = calendar_text(dated[entry['at']]) if entry['at'] in dated else 'Before calendar synchronization'
    entries.sort(key=lambda x: x["at"], reverse=True)
    return entries[:limit]


def read_duel_rep(steamid):
    """(points, history) of the fame or shame this profile won in duels; (0, []) if none."""
    d = profile_field(steamid,"duel_reputation")
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


# ---------------------------------------------------------------------------
# The most recently looked-up cultivators (the window offers them when you build a team).
# ---------------------------------------------------------------------------
RECENT_LIMIT = 12


def recent_path():
    return os.path.join(CACHE_DIR, "recent_lookups.json")


def read_recent():
    """[{'steamid', 'name'}, ...], newest first. Damaged data counts as an empty list."""
    d = read_json(recent_path())
    items = d.get("recent") if isinstance(d, dict) else None
    return [{"steamid": e["steamid"], "name": e["name"]} for e in (items if isinstance(items, list) else [])
            if isinstance(e, dict) and isinstance(e.get("steamid"), str)
            and isinstance(e.get("name"), str)][:RECENT_LIMIT]


def add_recent(steamid, name):
    """Puts this cultivator first in the recent list (and updates the name saved for it)."""
    items = [e for e in read_recent() if e["steamid"] != steamid]
    items.insert(0, {"steamid": steamid, "name": name})
    store_json(recent_path(), {"recent": items[:RECENT_LIMIT]})


# ============================================================================
# Optional Steam API key persistence — explicit consent required
# ============================================================================

from pathlib import Path
import tempfile

API_KEY_SETTINGS_PATH = Path(__file__).resolve().parent / "steam_api_settings.json"


def load_saved_api_key():
    try:
        data = json.loads(API_KEY_SETTINGS_PATH.read_text(encoding="utf-8"))
        key = data.get("steam_api_key")
        if data.get("remember_api_key") is True and isinstance(key, str) and 0 < len(key) <= 256 and key == key.strip():
            return key
    except (OSError, ValueError, AttributeError):
        pass
    return ""


def save_api_key(key, *, consent=False):
    if consent is not True:
        raise ValueError("Explicit permission is required to remember an API key.")
    if not isinstance(key, str) or not key.strip() or len(key) > 256:
        raise ValueError("Cannot save an invalid API key.")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=API_KEY_SETTINGS_PATH.parent,
                                         prefix=".steam-key-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            json.dump({"remember_api_key": True, "steam_api_key": key.strip()}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, API_KEY_SETTINGS_PATH)
    except OSError:
        raise OSError("Could not save the API key settings file.") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def forget_api_key():
    try:
        API_KEY_SETTINGS_PATH.unlink(missing_ok=True)
    except OSError:
        raise OSError("Could not delete the saved API key settings file.") from None


# ============================================================================
# Developer save editing — validation, backups, and conflict protection
# ============================================================================

import copy
import datetime
import math

def decode_profile_json(raw):
    def reject(value):
        raise ValueError(f"Non-finite JSON number: {value}")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(raw, parse_constant=reject, object_pairs_hook=unique)


def validate_profile_data(data, steamid):
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Expected a version 1 profile object.")
    if data.get("steamid") != steamid or not isinstance(data.get("sections"), dict):
        raise ValueError("SteamID must match the filename; sections must be an object.")
    if 'sect_override' in data and (not isinstance(data['sect_override'],str) or not data['sect_override'].strip() or len(data['sect_override'])>300):raise ValueError('Invalid membership override.')
    if 'mentor_power' in data and (type(data['mentor_power']) is not int or not 0<=data['mentor_power']<=1000000000):raise ValueError('Invalid mentor training power.')
    partners=data.get('practice_partners',{})
    if not isinstance(partners,dict) or any(not isinstance(sid,str) or type(until) not in (int,float)
            or not 0<=until<=1e12+1 for sid,until in partners.items()):
        raise ValueError('Invalid duel practice cooldowns.')
    def whole(value, label, low=None, high=None):
        if type(value) is not int or (low is not None and value < low) or (high is not None and value > high):
            raise ValueError(f"{label}: expected integer" + (f" >= {low}" if low is not None else "") + (f" <= {high}" if high is not None else ""))
    whole(data.get("completed_sect_missions",0),"Completed sect missions",0)
    for section in ("realm_state", "pavilion", "inventory", "life", "duel_reputation", "peaks"):
        if section in data and not isinstance(data[section], dict):
            raise ValueError(f"{section} must be an object.")
    realm = data.get("realm_state", {})
    for key in ("realm_index", "born_realm"):
        if realm.get(key) is not None:
            whole(realm[key], key, 0, len(gamedata.REALMS) - 1)
    if "lifespan_lost" in realm:
        whole(realm["lifespan_lost"], "lifespan_lost", 0)
    for section, key in (("realm_state", "last_failed"), ("life", "last_roll")):
        value = data.get(section, {}).get(key)
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            raise ValueError(f"{key} must be a finite nonnegative timestamp or null.")
    pav = data.get("pavilion")
    if pav is not None:
        for key in ("spent", "earned", "bonus"):
            whole(pav.get(key, 0), key, None if key == "bonus" else 0)
        if not isinstance(pav.get("items"), dict) or not isinstance(pav.get("history"), list):
            raise ValueError("Pavilion requires items object and history list.")
        for key, value in pav["items"].items():
            if key not in gamedata.PAVILION_BY_ID:
                raise ValueError(f"Unknown pavilion item: {key}")
            whole(value, key, 1)
    inv = data.get("inventory")
    if inv is not None:
        if not isinstance(inv.get("treasures"), list) or not all(isinstance(t, str) for t in inv["treasures"]) or not isinstance(inv.get("history"), list):
            raise ValueError("Inventory requires a treasure string list and history list.")
        known = {t for tier in gamedata.ALL_TREASURES for t in tier} | set(gamedata.PAVILION_TREASURE_RANKS)
        if any(t not in known and not is_steam_item_treasure(t) for t in inv["treasures"]):
            raise ValueError("Inventory contains an unknown treasure name.")
    rep = data.get("duel_reputation")
    if rep is not None:
        whole(rep.get("points"), "Duel reputation")
        if not isinstance(rep.get("history"), list):
            raise ValueError("Duel reputation requires a history list.")
    if "rebirths" in data.get("life", {}):
        whole(data["life"]["rebirths"], "rebirths", 0)
    if "offline" in data:
        import generator
        local = data["offline"]
        if not isinstance(local, dict) or local.get("version") != 1:
            raise ValueError("Unsupported local profile version.")
        generator.validate_local_settings(local.get("character"))
        if local["character"]["seed"] != steamid:
            raise ValueError("Local seed must match profile ID.")
    if "wallet" in data:
        if not isinstance(data["wallet"], dict):
            raise ValueError("Wallet must be an object.")
        whole(data["wallet"].get("spirit_stones", 0), "Spirit Stones", 0)
    if "sect_memberships" in data:
        if not isinstance(data["sect_memberships"], dict):
            raise ValueError("Sect memberships must be an object.")
        for member in data["sect_memberships"].values():
            validate_sect_member(member)
    if 'calendar' in data:
        clock=data['calendar']
        if not isinstance(clock,dict): raise ValueError('Calendar must be an object.')
        for key in ('birth_day','synchronized_day','base_lifespan'):
            if type(clock.get(key)) not in (int,float) or not math.isfinite(clock[key]):
                raise ValueError('Invalid calendar '+key)
        whole(clock.get('incarnation'),'Calendar incarnation',0)
        whole(clock.get('base_lifespan'),'Calendar lifespan',1)
    vitals=realm.get('vitals')
    if vitals is not None:
        if not isinstance(vitals,dict): raise ValueError('Vitals must be an object.')
        whole(vitals.get('age'),'Age',0)
        whole(vitals.get('birth_year'),'Birth year')
        whole(vitals.get('base_lifespan'),'Base lifespan',1)
    life=data.get('life',{})
    dead=life.get('dead')
    if dead is not None:
        if not isinstance(dead,dict): raise ValueError('Death record must be an object or null.')
        whole(dead.get('age'),'Age at death',0)
        whole(dead.get('year'),'Death year')
        whole(dead.get('scene'),'Death scene',0)
        if not isinstance(dead.get('killer'),str) or not dead['killer'] or dead.get('friend_id') is not None and not isinstance(dead['friend_id'],str):
            raise ValueError('Invalid death cause or participant.')
    inc=life.get('incarnation')
    if inc is not None:
        if not isinstance(inc,dict) or any(type(inc.get(k)) is not t for k,t in INCARNATION_FIELDS.items()):
            raise ValueError('Invalid incarnation fields.')
        if inc['talent'] not in gamedata.TALENT_BY_NAME or inc['element'] not in gamedata.ELEMENTS or inc['gender'] not in ('male','female'):
            raise ValueError('Invalid incarnation traits.')
        if min(inc['age'],inc['count'],inc['lifespan_roll'],inc['immortal_lifespan'])<0:
            raise ValueError('Invalid incarnation age or lifespan.')
    histories=[data.get('activity',[])]
    for key in ('inventory','pavilion','duel_reputation'):
        histories.append(data.get(key,{}).get('history',[]))
    for entries in histories:
        if not isinstance(entries,list): raise ValueError('History must be a list.')
        for event in entries:
            if not isinstance(event,dict): raise ValueError('History entries must be objects.')
            if type(event.get('at')) not in (int,float) or not math.isfinite(event['at']) or event['at']<0:
                raise ValueError('History timestamps must be finite and nonnegative.')
            for key in ('summary','item','type'):
                if key in event and not isinstance(event[key],str): raise ValueError('Invalid history '+key)
            for key in ('rep','price','lost','points'):
                if key in event and type(event[key]) is not int: raise ValueError('Invalid history '+key)
            for key in ('allies','enemies'):
                if key in event and (not isinstance(event[key],list) or any(not isinstance(v,str) for v in event[key])):
                    raise ValueError('Invalid history participants.')
            for key in ('p','chance'):
                if key in event and (type(event[key]) not in (int,float) or not math.isfinite(event[key]) or not 0<=event[key]<=1):
                    raise ValueError('Invalid history probability.')
            if 'world_day' in event and (type(event['world_day']) not in (int,float) or not math.isfinite(event['world_day'])):
                raise ValueError('Invalid history calendar date.')
    if 'calendar' in data and (data['calendar']['base_lifespan']<=0 or data['calendar']['birth_day']>data['calendar']['synchronized_day']):
        raise ValueError('Invalid calendar lifespan or future birthday.')
    # Unknown fields are retained, allowing newer save fields to survive a round trip.


def is_steam_item_treasure(name):
    prefixes = ("Steam item · CS2 · ", "Steam item · Dota 2 · ", "Steam item · TF2 · ")
    return (isinstance(name, str) and any(name.startswith(p) and len(name) > len(p) for p in prefixes)
            and len(name) <= 190 and all(ord(c) >= 32 and ord(c) != 127 for c in name))


def validate_sect_member(member):
    """Reject damaged mission state without silently resetting earned reputation."""
    if not isinstance(member, dict):
        raise ValueError("Invalid sect membership.")
    if type(member.get("points")) is not int or member["points"] < 0:
        raise ValueError("Sect reputation must be a nonnegative integer.")
    ready = member.get("ready_at")
    if type(ready) not in (int, float) or not math.isfinite(ready) or ready < 0:
        raise ValueError("Invalid sect cooldown timestamp.")
    offers, history = member.get("offers"), member.get("history")
    if not isinstance(offers, list) or not isinstance(history, list):
        raise ValueError("Sect offers/history must be lists.")
    rewards = {"herbs": (False, 5, 20, 10), "delivery": (False, 5, 30, 10),
               "bodyguard": (True, 15, 100, 30), "beast": (True, 15, 120, 30)}
    ids = set()
    for offer in offers:
        if not isinstance(offer, dict) or not isinstance(offer.get("id"), str) or not offer["id"] or offer["id"] in ids:
            raise ValueError("Invalid or duplicate sect mission ID.")
        ids.add(offer["id"])
        if not isinstance(offer.get("text"), str) or not offer["text"].strip():
            raise ValueError("Invalid sect mission description.")
        kind = offer.get("kind")
        if not isinstance(kind, str) or kind not in rewards:
            raise ValueError("Invalid sect mission category.")
        if type(offer.get("hard")) is not bool or any(type(offer.get(k)) is not int for k in ("sect_points", "stones", "reputation")):
            raise ValueError("Invalid sect mission rewards.")
        if tuple(offer[k] for k in ("hard", "sect_points", "stones", "reputation")) != rewards[kind]:
            raise ValueError("Sect mission rewards do not match its category.")
    for event in history:
        if not isinstance(event, dict) or not isinstance(event.get("summary"), str):
            raise ValueError("Invalid sect mission history.")


def sect_identity(name):
    import hashlib, unicodedata
    canonical = ' '.join(unicodedata.normalize('NFKC',name).casefold().split())
    sid = hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:24]
    with world_transaction() as db:
        db.execute('INSERT OR IGNORE INTO sects(id,name) VALUES(?,?)',(sid,name))
        return dict(db.execute('SELECT * FROM sects WHERE id=?',(sid,)).fetchone())


def ensure_sect(steamid, c):
    identity = sect_identity(c["sect"])
    pc = load_profile_cache(steamid)
    memberships = pc.setdefault("sect_memberships", {})
    if not isinstance(memberships, dict):
        raise logs.SteamError("Invalid saved sect memberships. Restore the profile from a backup.")
    if identity["id"] not in memberships:
        memberships[identity["id"]] = {"points": gamedata.SECT_INITIAL_REPUTATION[c["realm_index"]],
                                      "ready_at": 0, "offers": [], "history": []}
        if not save_profile_cache(pc, durable=True):
            raise logs.SteamError("Could not save sect membership. Check cache write permissions.")
    member = memberships[identity["id"]]
    try:
        validate_sect_member(member)
    except ValueError as exc:
        raise logs.SteamError(f"Invalid saved sect state: {exc} Restore the profile from a backup.") from exc
    with world_transaction() as db:
        if db.execute('SELECT initialized FROM region_meta').fetchone()[0]:
            sect_id = None if c['sect']=='Wanderer' else identity['id']
            affiliation = db.execute('SELECT * FROM affiliations WHERE actor=?',(steamid,)).fetchone()
            if affiliation is None:
                db.execute('INSERT INTO affiliations(actor,sect_id) VALUES(?,?)',(steamid,sect_id))
            elif affiliation['sect_id'] != sect_id:
                db.execute("UPDATE affiliations SET sect_id=?,office='Member',mentor=NULL,support=0 WHERE actor=?",(sect_id,steamid))
                db.execute('UPDATE affiliations SET mentor=NULL WHERE mentor=?',(steamid,))
    points = member["points"]
    rank = max(i for i, (minimum, _) in enumerate(gamedata.SECT_RANKS) if points >= minimum)
    return dict(identity=identity, rank_index=rank, rank=gamedata.SECT_RANKS[rank][1], points=points, **{k: member[k] for k in ("ready_at", "offers", "history")})


def read_spirit_stones(steamid):
    """Unspent placeholder currency; legacy profiles start at zero."""
    wallet = profile_field(steamid,"wallet", {})
    value = wallet.get("spirit_stones", 0) if isinstance(wallet, dict) else 0
    return value if type(value) is int and value >= 0 else 0


import threading
_picker_lock = threading.Lock()
_picker_files = {}


def cached_profile_choices():
    with world_transaction() as db:
        rows = db.execute("SELECT id,name,kind FROM profiles WHERE kind!='npc' ORDER BY name COLLATE NOCASE,id").fetchall()
    result,counts = [],{}
    for row in rows:
        label = row['name'] + (' (local)' if row['kind']=='local' else ' (Steam)')
        counts[label] = counts.get(label,0)+1
        result.append((label if counts[label]==1 else f"{label} #{counts[label]}",row['id']))
    return result


class EditableProfile:
    def __init__(self, path):
        self.path = Path(path)  # logical ID locator for the existing editor UI
        self.steamid = self.path.name.removesuffix('.profile.json')
        with world_transaction(self.path.parent) as db:
            row = paid_profile_row(db,self.steamid)
            if row is None:
                raise ValueError('No such profile in the world database.')
            self.data = json.loads(row['data'])
            self.revision = row['revision']
            self.credit = row['credit']
        self.original = json.dumps(self.data,ensure_ascii=False).encode('utf-8')
        validate_profile_data(self.data,self.steamid)

    def save(self,data):
        validate_profile_data(data,self.steamid)
        # Validate and serialize before creating a backup or touching live state.
        payload = json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8')
        with _world_lock:
            backup = backup_world(self.path.parent)
            with world_transaction(self.path.parent) as db:
                row = paid_profile_row(db,self.steamid)
                if row is None or row['revision'] != self.revision or row['credit'] != self.credit:
                    raise ValueError('The game or another editor changed this save. Reload before saving.')
                value = copy.deepcopy(data)
                # Explicit age edits reanchor this incarnation to the shared date.
                before = (self.data.get('offline') or {}).get('character',{})
                after = (value.get('offline') or {}).get('character',{})
                clock=value.get('calendar')
                day=db.execute('SELECT day FROM world WHERE id=1').fetchone()[0]
                current_age=max(0,int((day-clock['birth_day'])//DAYS_PER_YEAR)) if clock else None
                if after.get('age') != before.get('age') and after.get('age') != current_age and not (value.get('life') or {}).get('dead'):
                    inc=(value.get('life') or {}).get('incarnation') or {}
                    vitals=(value.get('realm_state') or {}).get('vitals') or {}
                    value['calendar']={'birth_day':day-after['age']*DAYS_PER_YEAR,
                                       'synchronized_day':day,'incarnation':inc.get('count',0),
                                       'base_lifespan':vitals.get('base_lifespan',after['lifespan'])}
                fold_salary_credit(db,self.steamid)
                _write_profile(db,value)
                self.credit=0
                self.revision += 1
        self.data = value
        self.original = payload
        return backup




# ============================================================================
# Persistent world — SQLite documents, indexed actors, calendar and chronicle.
# ============================================================================
import sqlite3
import contextlib
import functools
import threading
import time
import uuid

_world_lock = threading.RLock()
# Entries exist only while a session owns an open local WAL connection.
_checkpoint_worlds = set()
# Physical paths are pinned only for the lifetime of the owning world session.
# Other caches (including editor previews) retain independent identities.
_session_paths = {}
_session_path_lock = threading.Lock()


def _database_key(cache=None):
    return os.path.normcase(os.path.abspath(os.path.join(os.fspath(cache or CACHE_DIR), 'world.db')))


def _world_path(cache=None):
    with _session_path_lock:
        pinned = _session_paths.get(_database_key(cache))
    return pinned[1] if pinned else database_path(cache).resolve()


def _release_world_paths(owner):
    with _session_path_lock:
        for key in [key for key, value in _session_paths.items() if value[0] == owner]:
            del _session_paths[key]

_world_local = threading.local()
WORLD_YEAR = 3200
DAYS_PER_YEAR = 365
SECONDS_PER_DAY = 300


def database_path(cache=None):
    # Keep the historical save-folder selection working for developer tools.
    return Path(cache or CACHE_DIR) / "world.db"


def _profile_meta(data):
    import generator
    local = data.get("offline", {})
    inc = (data.get("life") or {}).get("incarnation") or {}
    name = inc.get("name") or local.get("character", {}).get("name") or generator.cultivator_name(data["steamid"])
    kind = "npc" if data.get("world_npc") else "local" if local else "steam"
    return name, kind


def _write_profile(db, data):
    if data.get('world_npc') and data.get('activity') and db.execute('PRAGMA user_version').fetchone()[0]>=6:
        data=retain_npc_activity(db,data)
    name, kind = _profile_meta(data)
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(',',':'))
    db.execute("""INSERT INTO profiles(id,name,kind,data,revision) VALUES(?,?,?,?,1)
        ON CONFLICT(id) DO UPDATE SET name=excluded.name,kind=excluded.kind,
        data=excluded.data,revision=profiles.revision+1""", (str(data['steamid']), name, kind, payload))


def _migrate_calendar_epoch(db, path):
    """Schema 2 renumbers structured dates, without changing ages or durations."""
    lease = db.execute('SELECT expires FROM simulation_lease WHERE id=1').fetchone()
    if lease and lease[0] > time.time():
        raise logs.SteamError('Close the other game before upgrading this world. After a crash, wait 30 seconds and retry.')
    folder = path.parent / 'migration_backups'
    folder.mkdir(exist_ok=True)
    backup = folder / ('before_calendar_3200_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.db')
    with contextlib.closing(sqlite3.connect(backup)) as dest:
        db.backup(dest)
    db.execute('BEGIN IMMEDIATE')
    if db.execute('PRAGMA user_version').fetchone()[0] != 1:
        db.commit()
        return
    world = dict(db.execute('SELECT * FROM world WHERE id=1').fetchone())
    delta = WORLD_YEAR * DAYS_PER_YEAR - world['start_day']
    years = int(delta / DAYS_PER_YEAR)
    date_keys = {'birth_day','synchronized_day','last_alive_day','awakened_day','world_day'}
    def shift(value):
        if isinstance(value,list):
            for item in value: shift(item)
        elif isinstance(value,dict):
            for key,item in list(value.items()):
                if key in date_keys and type(item) in (int,float):
                    value[key] = item + delta
                elif key in ('year','birth_year') and type(item) is int:
                    value[key] = item + years
                elif not key.startswith('original_'):
                    shift(item)
    for row in db.execute('SELECT id,data FROM profiles').fetchall():
        data = decode_profile_json(row['data'])
        shift(data)
        validate_profile_data(data,row['id'])
        _write_profile(db,data)
    for table,column in (('world','day'),('world','start_day'),('world_events','day'),('conversations','day')):
        db.execute(f'UPDATE {table} SET {column}={column}+?',(delta,))
    db.execute('UPDATE npcs SET next_day=next_day+? WHERE next_day<1e29',(delta,))
    db.execute('UPDATE relationships SET last_day=last_day+? WHERE last_day>=0',(int(delta),))
    db.execute("UPDATE conversations SET reply='[Recorded before calendar renumbering] ' || reply")
    db.execute('DELETE FROM simulation_lease')
    db.execute('PRAGMA user_version=2')
    db.commit()


def _open_world(cache=None):
    with _session_path_lock:
        pinned = _session_paths.get(_database_key(cache))
    path = pinned[1] if pinned else database_path(cache)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys=ON")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > 9:
            raise logs.SteamError("This world was saved by a newer game version. Please upgrade the game.")
        if version == 0:
            db.execute("BEGIN IMMEDIATE")
            # A second process may have initialized the database while we waited.
            if db.execute("PRAGMA user_version").fetchone()[0] == 0:
                for sql in (
                    "CREATE TABLE IF NOT EXISTS profiles(id TEXT PRIMARY KEY,name TEXT NOT NULL,kind TEXT NOT NULL,data TEXT NOT NULL,revision INTEGER NOT NULL)",
                    "CREATE INDEX IF NOT EXISTS profile_names ON profiles(kind,name COLLATE NOCASE)",
                    "CREATE TABLE IF NOT EXISTS sects(id TEXT PRIMARY KEY,name TEXT NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS world(id INTEGER PRIMARY KEY CHECK(id=1),day REAL NOT NULL,seconds_per_day REAL NOT NULL,seed TEXT NOT NULL,populated INTEGER NOT NULL DEFAULT 0,start_day REAL NOT NULL DEFAULT 0,pending_seconds REAL NOT NULL DEFAULT 0)",
                    "CREATE TABLE IF NOT EXISTS world_events(id INTEGER PRIMARY KEY,day REAL NOT NULL,kind TEXT NOT NULL,title TEXT NOT NULL,summary TEXT NOT NULL,location TEXT NOT NULL,importance INTEGER NOT NULL,visibility TEXT NOT NULL,actors TEXT NOT NULL,sects TEXT NOT NULL)",
                    "CREATE INDEX IF NOT EXISTS event_dates ON world_events(day DESC,id DESC)",
                    "CREATE TABLE IF NOT EXISTS npcs(id TEXT PRIMARY KEY REFERENCES profiles(id),next_day REAL NOT NULL,activity TEXT NOT NULL,location TEXT NOT NULL,steps INTEGER NOT NULL DEFAULT 0)",
                    "CREATE INDEX IF NOT EXISTS npc_schedule ON npcs(next_day)",
                    "CREATE TABLE IF NOT EXISTS simulation_lease(id INTEGER PRIMARY KEY CHECK(id=1),owner TEXT NOT NULL,expires REAL NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS relationships(player TEXT NOT NULL REFERENCES profiles(id),npc TEXT NOT NULL REFERENCES profiles(id),trust INTEGER NOT NULL DEFAULT 0,last_day INTEGER NOT NULL DEFAULT -1,PRIMARY KEY(player,npc))",
                    "CREATE TABLE IF NOT EXISTS conversations(id INTEGER PRIMARY KEY,player TEXT NOT NULL REFERENCES profiles(id),npc TEXT NOT NULL REFERENCES profiles(id),day REAL NOT NULL,topic TEXT NOT NULL,reply TEXT NOT NULL)",
                    "CREATE INDEX IF NOT EXISTS conversation_pair ON conversations(player,npc,id DESC)",
                ):
                    db.execute(sql)
                db.execute("INSERT OR IGNORE INTO world(id,day,seconds_per_day,seed) VALUES(1,?,?,?)",
                           (WORLD_YEAR * DAYS_PER_YEAR, SECONDS_PER_DAY, uuid.uuid4().hex))
                # Original files are the migration backup. Never write/delete them.
                imported = 0
                for file in sorted(path.parent.glob("*.profile.json")):
                    try:
                        data = decode_profile_json(file.read_bytes())
                        validate_profile_data(data, file.name.removesuffix('.profile.json'))
                    except (ValueError, TypeError, KeyError) as exc:
                        raise logs.SteamError(f"Migration stopped at {file.name}: {exc}. Original saves are unchanged.") from exc
                    data['legacy_calendar'] = True
                    _write_profile(db, data)
                    imported += 1
                epoch = WORLD_YEAR*DAYS_PER_YEAR
                db.execute('UPDATE world SET day=?,start_day=? WHERE id=1',(epoch,epoch))
                sect_file = path.parent / 'sects.json' 
                if sect_file.exists():
                    registry = decode_profile_json(sect_file.read_bytes())
                    for sid, record in registry.items():
                        if not isinstance(record, dict) or record.get('id') != sid or not isinstance(record.get('name'), str):
                            raise logs.SteamError("Migration stopped: invalid sect registry. Original saves are unchanged.")
                        db.execute('INSERT INTO sects VALUES(?,?)', (sid, record['name']))
                db.execute("INSERT INTO world_events(day,kind,title,summary,location,importance,visibility,actors,sects) VALUES(?,?,?,?,?,?,?,?,?)",
                           (epoch, 'calendar', 'The Heavenly Calendar synchronized',
                            f'A shared timeline begins. {imported} existing profiles were imported; older events retain their original records and are marked before synchronization.',
                            'The cultivation world', 3, 'public', '[]', '[]'))
                db.execute('PRAGMA user_version=2')
            db.commit()
        if db.execute('PRAGMA user_version').fetchone()[0] == 1:
            _migrate_calendar_epoch(db,path)
        if db.execute("PRAGMA user_version").fetchone()[0] == 2:
            _migrate_social_world(db, path)
        if db.execute("PRAGMA user_version").fetchone()[0] == 3:
            _migrate_living_actions(db,path)
        if db.execute("PRAGMA user_version").fetchone()[0] == 4:
            _migrate_sect_politics(db,path)
        if db.execute("PRAGMA user_version").fetchone()[0] == 5:
            _migrate_storage_retention(db,path)
        if db.execute("PRAGMA user_version").fetchone()[0] == 6:
            _migrate_territory(db,path)
        if db.execute('PRAGMA user_version').fetchone()[0]==7:
            import warfare
            warfare.migrate(db,path)
        if db.execute('PRAGMA user_version').fetchone()[0]==8:
            import warfare
            warfare.migrate_rituals(db,path)
        db.execute("""CREATE TABLE IF NOT EXISTS cultivation_clock(
            id INTEGER PRIMARY KEY CHECK(id=1), actor TEXT NOT NULL, cooldown REAL NOT NULL,
            skip_until REAL NOT NULL, first_tick INTEGER NOT NULL)""")
        _apply_retention_policy(db,path)
        return db
    except BaseException:
        db.rollback()
        db.close()
        raise


@contextlib.contextmanager
def world_transaction(cache=None, *, _connection=None):
    """One committed action, including all participants; nested actions share it."""
    # Nested calls already own the outer lock/connection. Compare the lexical key
    # first; only an explicit alternate spelling needs filesystem canonicalization.
    cache = cache or getattr(_world_local,'debug_cache',None)
    key = _database_key(cache)
    active = getattr(_world_local, 'active', None)
    if active:
        if active[2] != key and active[0] != str(_world_path(cache)):
            raise logs.SteamError('Cannot write two worlds in the same action.')
        yield active[1]
        return
    path = str(_world_path(cache))
    started=time.monotonic()
    with _world_lock:
        acquired=time.monotonic()
        db = _connection if _connection is not None else _open_world(cache)
        try:
            if path in _checkpoint_worlds:
                db.execute('PRAGMA wal_autocheckpoint=0')
            db.execute('BEGIN IMMEDIATE')
            _world_local.active = (path, db, key)
            opened=time.monotonic()
            yield db
            committing=time.monotonic()
            db.commit()
            committed=time.monotonic()
        except sqlite3.Error as exc:
            db.rollback()
            raise logs.SteamError(f'World save failed; the action was rolled back: {exc}') from exc
        except BaseException:
            db.rollback()
            raise
        finally:
            _world_local.active = None
            _world_local.last_profile = None
            _world_local.profile_reads = None
            _world_local.raw_profile_reads = None
            if _connection is None:db.close()
    finished=time.monotonic()
    if finished-started>=.25 and threading.current_thread() is not threading.main_thread():
        logs.performance_note(f'{threading.current_thread().name} transaction: lock {acquired-started:.2f}s, open/begin {opened-acquired:.2f}s, work {committing-opened:.2f}s, commit {committed-committing:.2f}s, close {finished-committed:.2f}s')


@contextlib.contextmanager
def world_snapshot():
    """Read one committed view; gameplay nested inside a writer sees that writer's state."""
    if getattr(_world_local,'active',None):
        with world_transaction() as db:
            yield db
        return
    cache=getattr(_world_local,'debug_cache',None)
    path=_world_path(cache)
    if path.is_file():
        started=time.monotonic()
        db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=15,isolation_level=None)
        try:
            db.row_factory=sqlite3.Row
            db.execute('BEGIN')
            if db.execute('PRAGMA user_version').fetchone()[0]==9:
                key=os.path.normcase(os.path.abspath(database_path(cache)))
                _world_local.active=(str(path),db,key)
                acquired=time.monotonic()
                try:yield db
                finally:
                    _world_local.active=None
                    _world_local.last_profile=None
                    _world_local.profile_reads=None
                    _world_local.raw_profile_reads=None
                return
        except sqlite3.Error as exc:
            raise logs.SteamError(f'Could not read the world: {exc}') from exc
        finally:
            db.close()
            finished=time.monotonic()
            if 'acquired' in locals() and finished-started>=.25 and threading.current_thread() is not threading.main_thread():
                logs.performance_note(f'{threading.current_thread().name} snapshot: open/lock {acquired-started:.2f}s, read {finished-acquired:.2f}s')
    # Creation and legacy migrations still use the normal exclusive writer path.
    with world_transaction(cache) as db:yield db


def atomic(fn):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        with world_transaction():
            return fn(*args, **kwargs)
    return wrapped


def profile_ids(cache=None, include_npcs=True):
    with world_transaction(cache) as db:
        sql = 'SELECT id FROM profiles' + ('' if include_npcs else " WHERE kind != 'npc'") + ' ORDER BY name COLLATE NOCASE,id'
        return [r[0] for r in db.execute(sql)]


def all_profiles(cache=None, include_npcs=True):
    with world_transaction(cache) as db:
        table='paid_profiles' if db.execute('PRAGMA user_version').fetchone()[0]>=7 else 'profiles'
        query='SELECT data FROM '+table
        if not include_npcs:
            query+=" WHERE kind != 'npc'"
        return [json.loads(r[0]) for r in db.execute(query)]


def world_state(cache=None):
    with world_transaction(cache) as db:
        row=db.execute('SELECT * FROM world WHERE id=1').fetchone()
        if row is None: raise logs.SteamError('Invalid saved world: clock record is missing.')
        state=dict(row)
        for key in ('day','start_day','seconds_per_day','pending_seconds'):
            value=state.get(key)
            if type(value) not in (int,float) or not math.isfinite(value):
                raise logs.SteamError('Invalid saved world: '+key+' must be finite.')
        if not 0<=state['start_day']<=state['day']<=1e12 or not 1<=state['seconds_per_day']<=86400 or not 0<=state['pending_seconds']<=1e12:
            raise logs.SteamError('Invalid saved world: calendar, pace or pending time is out of range.')
        return state


def calendar_text(day=None):
    day = world_state()['day'] if day is None else day
    whole = int(day)
    year = whole // DAYS_PER_YEAR
    era = f'Year {abs(year):,} before the Heavenly Calendar' if year < 0 else f'Year {year:,}'
    return f'{era}  |  Day {whole % DAYS_PER_YEAR + 1}'


def world_event(kind, title, summary, *, actors=(), sects=(), location='The cultivation world',
                importance=2, visibility='public', day=None):
    if visibility not in ('public', 'rumor', 'hidden', 'local'):
        raise ValueError('Invalid event visibility.')
    with world_transaction() as db:
        day = world_state()['day'] if day is None else day
        cur = db.execute('INSERT INTO world_events(day,kind,title,summary,location,importance,visibility,actors,sects) VALUES(?,?,?,?,?,?,?,?,?)',
                         (day,kind,title,summary,location,importance,visibility,json.dumps(list(actors)),json.dumps(list(sects))))
        return cur.lastrowid


def world_history(query='', kind='All', page=0, limit=30):
    validate_page(query,page,limit)
    if not isinstance(kind,str): raise logs.SteamError('Choose an event category.')
    with world_snapshot() as db:
        where = "visibility IN ('public','rumor') AND importance>=2"
        args = []
        sect_names=dict(db.execute('SELECT id,name FROM sects'))
        if query:
            where += ''' AND (instr(lower(title || ' ' || summary || ' ' || location),lower(?))>0 OR EXISTS (SELECT 1 FROM json_each(world_events.sects) j JOIN sects s ON s.id=j.value WHERE instr(lower(s.name),lower(?))>0))'''
            args.extend([query,query])
        if kind != 'All':
            where += ' AND kind=?'; args.append(kind)
        total = db.execute('SELECT count(*) FROM world_events WHERE '+where,args).fetchone()[0]
        rows = []
        for row in db.execute('SELECT * FROM world_events WHERE '+where+' ORDER BY day DESC,id DESC LIMIT ? OFFSET ?',args+[limit,max(0,page)*limit]):
            e = dict(row)
            try:
                for key in ('actors','sects'):
                    e[key]=decode_profile_json(e[key])
                    if not isinstance(e[key],list) or any(not isinstance(value,str) for value in e[key]):
                        raise ValueError('Invalid participants')
                if type(e['day']) not in (int,float) or not math.isfinite(e['day']):raise ValueError('Invalid event date')
            except (ValueError,TypeError) as exc:
                raise logs.SteamError(f"Invalid saved World History event {e['id']}. Restore a database backup.") from exc
            e['sect_names']=[sect_names.get(s,s) for s in e['sects']]
            e['actor_names']=[]
            for actor in e['actors']:
                profile=db.execute('SELECT name FROM profiles WHERE id=?',(actor,)).fetchone()
                e['actor_names'].append(profile[0] if profile else actor)
            e['when'] = calendar_text(e['day']); rows.append(e)
        return rows,total


def backup_world(cache=None):
    """SQLite backup API includes committed state; never copy a live DB file."""
    with _world_lock:
        source = _open_world(cache)
        folder = database_path(cache).parent / 'devtools_backups'
        folder.mkdir(exist_ok=True)
        target = folder / ('world_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.db')
        dest = sqlite3.connect(target)
        try:
            source.backup(dest)
        finally:
            dest.close(); source.close()
        return target


def validate_page(query,page,limit):
    if not isinstance(query,str) or type(page) is not int or not 0<=page<=1000000 or type(limit) is not int or not 1<=limit<=200:
        raise logs.SteamError('Invalid search or page size (allowed: 1–200).')


def member_role(affiliation):
    if not affiliation or not affiliation['sect_id']:
        return 'Unaffiliated'
    if affiliation['office']=='Member' and affiliation['mentor']:
        return 'Direct Disciple'
    return affiliation['office']


def npc_card_fields(row,data):
    from generator import local_power_score
    c=data['offline']['character']
    dead=bool((data.get('life') or {}).get('dead'))
    realm=data.get('realm_state',{}).get('realm_index',c['realm_index'])
    incarnation=data.get('life',{}).get('incarnation') or {}
    power=local_power_score(c,talent_name=incarnation.get('talent',c['talent']))+data.get('mentor_power',0)
    if row['factor'] and not dead:
        power=round(power*row['factor'])
    standing=data.get('sect_memberships',{}).get(row['sect_id'],{}).get('points',gamedata.SECT_INITIAL_REPUTATION[realm])
    rank=next(name for threshold,name in reversed(gamedata.SECT_RANKS) if standing>=threshold)
    return dict(power=power,realm=gamedata.REALMS[realm][1],rank=rank if row['sect_id'] else None)


def world_population(query='', page=0, limit=50):
    validate_page(query,page,limit)
    with world_snapshot() as db:
        where = "p.kind='npc' AND (instr(lower(p.name),lower(?))>0 OR instr(p.id,?)>0)"
        args = [query,query]
        count = db.execute('SELECT count(*) FROM profiles p WHERE '+where,args).fetchone()[0]
        rows = []
        for row in db.execute('''SELECT p.id,p.name,p.data,n.activity,a.sect_id,a.office,a.mentor,s.name AS sect,
                i.factor,l.name place,d.name destination FROM profiles p JOIN npcs n ON n.id=p.id
                LEFT JOIN affiliations a ON a.actor=p.id LEFT JOIN sects s ON s.id=a.sect_id
                LEFT JOIN positions pos ON pos.actor=p.id LEFT JOIN locations l ON l.id=pos.location
                LEFT JOIN journeys j ON j.actor=p.id LEFT JOIN locations d ON d.id=json_extract(j.path,'$[#-1]')
                LEFT JOIN injuries i ON i.actor=p.id AND i.until_day>(SELECT day FROM world)
                WHERE '''+where+' ORDER BY p.name COLLATE NOCASE,p.id LIMIT ? OFFSET ?',args+[limit,max(0,page)*limit]):
            try:
                data=decode_profile_json(row['data'])
                validate_profile_data(data,row['id'])
                c=data['offline']['character']
                if type(data['realm_state']['realm_index']) is not int:raise ValueError('Missing NPC realm')
            except (ValueError,TypeError,KeyError) as exc:
                raise logs.SteamError(f"Invalid saved world cultivator {row['id']}: {exc}. Restore a database backup.") from exc
            dead = (data.get('life') or {}).get('dead')
            card=npc_card_fields(row,data)
            card.update(id=row['id'],name=row['name'],sect=row['sect'] or 'Wanderer',role=member_role(row),
                        location=row['place'] or 'Unmapped',destination=row['destination'],
                        activity='Deceased' if dead else 'Travelling' if row['destination'] else row['activity'])
            rows.append(card)
        return rows,count


# Windows monotonic time includes sleep; unbiased interrupt time excludes it.
# Cache the API binding, not the time. Other supported platforms use monotonic time.
_unbiased_time = None
if os.name == 'nt':
    import ctypes
    _unbiased_time = ctypes.WinDLL('kernel32', use_last_error=True).QueryUnbiasedInterruptTime
    _unbiased_time.argtypes = [ctypes.POINTER(ctypes.c_ulonglong)]
    _unbiased_time.restype = ctypes.c_int


def active_play_time():
    if _unbiased_time is not None:
        value = ctypes.c_ulonglong()
        if not _unbiased_time(ctypes.byref(value)):
            raise logs.SteamError('Windows could not read the active-play clock.')
        return value.value / 10_000_000
    return time.monotonic()


WAL_RECLAIM_BYTES = 64 * 1024 * 1024


def _reclaim_wal(keeper, path, frames, copied):
    """Try reclaiming a large, checkpointed WAL; never wait for reader/writer locks.

    This runs only in the checkpoint worker, outside the world lock. TRUNCATE
    still performs SQLite's durability checks and may flush a concurrent tail;
    a busy reader/writer makes it defer, never delete or invalidate that WAL.
    """
    try:
        allocated = Path(str(path)+'-wal').stat().st_size
    except FileNotFoundError:
        return False
    if allocated < WAL_RECLAIM_BYTES:
        return False
    if frames < 0 or copied < frames:
        return True
    timeout = keeper.execute('PRAGMA busy_timeout').fetchone()[0]
    try:
        keeper.execute('PRAGMA busy_timeout=0')
        started = time.monotonic()
        busy, remaining, done = keeper.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
        if not busy:
            logs.performance_note(f'Background WAL reclaimed {allocated} bytes in {time.monotonic()-started:.2f}s')
        return bool(busy)
    finally:
        keeper.execute(f'PRAGMA busy_timeout={int(timeout)}')


def _checkpoint_loop(keeper,path,stop):
    """PASSIVE copies committed pages without waiting for readers or taking the game lock."""
    # data_version changes on commits from other connections. WAL allocation can
    # stay large after a successful checkpoint and is not evidence of new work.
    version = None
    incomplete = False
    reclaim_pending = False
    last_reclaim_notice = 0
    delay = 2
    while not stop.wait(delay):
        try:
            current = keeper.execute('PRAGMA data_version').fetchone()[0]
            if current == version and not incomplete and not reclaim_pending:
                continue
            started=time.monotonic()
            busy,frames,copied=keeper.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchone()
            took=time.monotonic()-started
            incomplete = bool(busy or (frames >= 0 and copied < frames))
            reclaim_pending = _reclaim_wal(keeper,path,frames,copied)
            if reclaim_pending and time.monotonic()-last_reclaim_notice >= 30:
                last_reclaim_notice = time.monotonic()
                logs.performance_note(f'Background WAL reclaim deferred: {copied}/{frames} frames copied; waiting for a safe reset window')
            # A long-lived reader may pin old pages. Retry without spinning;
            # new writes restore the normal cadence. Never block readers.
            delay = min(10, delay * 2) if incomplete and current == version else 2
            version = current  # Sampled before checkpoint: concurrent commits remain visible.
            if took>=1.5:
                logs.performance_note(f'Background WAL checkpoint {took:.2f}s, {copied}/{frames} frames, busy={busy}')
        except (OSError,sqlite3.Error) as exc:
            logs.performance_note(f'Background WAL checkpoint deferred: {exc}')
            delay = 5



def _stop_checkpoint(path,keeper,stop,thread):
    with _world_lock:_checkpoint_worlds.discard(str(path))
    stop.set()
    thread.join()
    keeper.close()


class WorldClock:
    """Session-only monotonic clock; wall-clock gaps on restart never advance time."""
    def __init__(self, now=None):
        self.last = active_play_time() if now is None else now
        self.owner = uuid.uuid4().hex
        cache=getattr(_world_local,'debug_cache',None)
        path=_world_path(cache)
        self._cache=path.parent
        with world_transaction(self._cache) as db:
            row=db.execute('SELECT owner,expires FROM simulation_lease WHERE id=1').fetchone()
            if row and row['expires'] > time.time():
                raise logs.SteamError('This world is already running in another game session. Close that session first.')
            db.execute('INSERT OR REPLACE INTO simulation_lease VALUES(1,?,?)',(self.owner,time.time()+30))

        import weakref
        with _session_path_lock:
            for key in (_database_key(cache), _database_key(path.parent)):
                _session_paths[key] = (self.owner, path)
        self._close_paths=weakref.finalize(self,_release_world_paths,self.owner)

        # Keep WAL open between short-lived transactions. Reads can then finish
        # against a committed snapshot even while the simulator flushes pages.
        self._tick_db=None
        self._journal_keeper=None
        if os.name=='nt' and ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor)) in (3,6):
            with _world_lock:
                keeper=sqlite3.connect(path,isolation_level=None,timeout=.2,check_same_thread=False)
                try:
                    if keeper.execute('PRAGMA journal_mode=WAL').fetchone()[0]=='wal':
                        import weakref
                        writer=sqlite3.connect(path,isolation_level=None,timeout=15,check_same_thread=False)
                        writer.row_factory=sqlite3.Row
                        writer.execute('PRAGMA foreign_keys=ON')
                        writer.execute('PRAGMA cache_size=-16384')
                        self._tick_db=writer
                        self._close_writer=weakref.finalize(self,writer.close)
                        self._journal_keeper=keeper
                        stop=threading.Event()
                        thread=threading.Thread(target=_checkpoint_loop,args=(keeper,path,stop),name='World WAL checkpoint',daemon=True)
                        thread.start()
                        _checkpoint_worlds.add(str(path))
                        self._close_journal=weakref.finalize(self,_stop_checkpoint,path,keeper,stop,thread)
                except sqlite3.OperationalError as exc:
                    if getattr(exc,'sqlite_errorcode',None) not in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):
                        self.close()
                        raise
                finally:
                    if self._journal_keeper is None:keeper.close()

    def tick(self, now=None, *, paused=False, bank_elapsed=False):
        import progress
        measured_start=time.monotonic()
        _world_local.batch_metrics={}
        now = active_play_time() if now is None else now
        elapsed = max(0, now-self.last)
        with world_transaction(self._cache,_connection=self._tick_db) as db:
            row=db.execute('SELECT owner FROM simulation_lease WHERE id=1').fetchone()
            if not row or row['owner'] != self.owner:
                raise logs.SteamError('Another session owns this world clock. Close and reopen this game.')
            if paused and bank_elapsed and elapsed and not db.execute('SELECT 1 FROM encounters LIMIT 1').fetchone():
                db.execute('UPDATE world SET pending_seconds=pending_seconds+? WHERE id=1',(elapsed,))
            result = world_state() if paused else progress.advance_world(elapsed, max_work_seconds=.1)
            training=db.execute('SELECT cooldown,first_tick,skip_until FROM cultivation_clock WHERE id=1').fetchone()
            if training and training['cooldown']>0 and not paused and not result.get('encounter'):
                # The tick in flight when cultivation was requested can include time before training.
                remaining=max(0,training['cooldown']-(0 if training['first_tick'] else elapsed))
                db.execute('UPDATE cultivation_clock SET cooldown=?,first_tick=0 WHERE id=1',(remaining,))
            else:
                remaining=training['cooldown'] if training else 0
            result['cultivation_cooldown']=remaining
            result['skip_until']=training['skip_until'] if training else None
            db.execute('UPDATE simulation_lease SET expires=? WHERE id=1',(time.time()+30,))
        self.last = now
        duration=time.monotonic()-measured_start
        metrics=getattr(_world_local,'batch_metrics',{})
        samples=getattr(self,'_performance_samples',{'batches':0,'npc_decisions':0,'events':0,'elapsed':0,'maximum':0})
        samples['batches']+=1;samples['elapsed']+=duration;samples['maximum']=max(samples['maximum'],duration)
        for key in ('npc_decisions','events'):samples[key]+=metrics.get(key,0)
        for key in ('retention_jobs','retention_removed','retention_ms','news_delivered'):
            samples[key]=samples.get(key,0)+metrics.get(key,0)
        if time.monotonic()-getattr(self,'_last_performance_note',0)>=30:
            logs.metric('Simulation',batches=samples['batches'],npc_decisions=samples['npc_decisions'],events=samples['events'],work_ms=round(samples['elapsed']*1000,2),max_batch_ms=round(samples['maximum']*1000,2),pending_seconds=round(result['pending_seconds'],2))
            logs.metric('Retention',jobs=samples['retention_jobs'],reports_received=samples['news_delivered'],reports_removed=samples['retention_removed'],work_ms=round(samples['retention_ms'],2),oldest_due_days=round(metrics.get('retention_oldest_days',0),3))
            self._last_performance_note=time.monotonic()
            samples={'batches':0,'npc_decisions':0,'events':0,'elapsed':0,'maximum':0}
        self._performance_samples=samples
        return result

    def close(self):
        with world_transaction(self._cache) as db:
            db.execute('DELETE FROM simulation_lease WHERE id=1 AND owner=?',(self.owner,))
        if self._tick_db is not None:
            with _world_lock:
                self._close_writer()
                self._tick_db=None
        if self._journal_keeper is not None:
            self._close_journal()
            self._journal_keeper=None
        self._close_paths()

# ============================================================================
# Region and social framework (schema 3). Identity is always a profile/sect ID.
# ============================================================================
def _migrate_social_world(db, path):
    """Back up schema 2 before adding tables; never rewrite existing characters."""
    lease = db.execute('SELECT expires FROM simulation_lease WHERE id=1').fetchone()
    if lease and lease[0] > time.time():
        raise logs.SteamError('Close other game instances before upgrading this world (lease expires after 30 seconds).')
    folder = path.parent / 'migration_backups'
    folder.mkdir(exist_ok=True)
    target = sqlite3.connect(folder / ('before_social_world_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.db'))
    try:
        db.backup(target)
    finally:
        target.close()
    db.execute('BEGIN IMMEDIATE')
    if db.execute('PRAGMA user_version').fetchone()[0] == 2:
        for sql in (
            'CREATE TABLE region_meta(id INTEGER PRIMARY KEY CHECK(id=1),initialized INTEGER NOT NULL DEFAULT 0)',
            'INSERT INTO region_meta VALUES(1,0)',
            'CREATE TABLE locations(id TEXT PRIMARY KEY,name TEXT NOT NULL,district INTEGER NOT NULL,x REAL NOT NULL,y REAL NOT NULL,sect_id TEXT REFERENCES sects(id))',
            'CREATE UNIQUE INDEX headquarters ON locations(sect_id) WHERE sect_id IS NOT NULL',
            'CREATE TABLE routes(a TEXT REFERENCES locations(id),b TEXT REFERENCES locations(id),seconds INTEGER NOT NULL CHECK(seconds BETWEEN 15 AND 100),danger INTEGER NOT NULL CHECK(danger BETWEEN 0 AND 3),PRIMARY KEY(a,b),CHECK(a<>b))',
            'CREATE TABLE dispositions(actor TEXT PRIMARY KEY REFERENCES profiles(id),dominant TEXT NOT NULL,secondary TEXT NOT NULL)',
            "CREATE TABLE affiliations(actor TEXT PRIMARY KEY REFERENCES profiles(id),sect_id TEXT REFERENCES sects(id),office TEXT NOT NULL DEFAULT 'Member',mentor TEXT REFERENCES profiles(id),loyalty INTEGER NOT NULL DEFAULT 50,support INTEGER NOT NULL DEFAULT 0)",
            "CREATE UNIQUE INDEX one_sect_master ON affiliations(sect_id) WHERE office IN ('Sect Master','Acting Master')",
            'CREATE INDEX sect_roster ON affiliations(sect_id,office)',
            'CREATE TABLE positions(actor TEXT PRIMARY KEY REFERENCES profiles(id),location TEXT NOT NULL REFERENCES locations(id))',
            'CREATE TABLE journeys(actor TEXT PRIMARY KEY REFERENCES profiles(id),path TEXT NOT NULL,departure REAL NOT NULL,arrival REAL NOT NULL,CHECK(arrival>departure))',
            'CREATE TABLE event_knowledge(actor TEXT REFERENCES profiles(id),event INTEGER REFERENCES world_events(id),learned_day REAL NOT NULL,source TEXT NOT NULL,PRIMARY KEY(actor,event))',
            'CREATE TABLE event_effects(event INTEGER REFERENCES world_events(id),actor TEXT REFERENCES profiles(id),effect TEXT NOT NULL,PRIMARY KEY(event,actor,effect))',
            'ALTER TABLE relationships ADD COLUMN respect INTEGER NOT NULL DEFAULT 0',
            'ALTER TABLE relationships ADD COLUMN fear INTEGER NOT NULL DEFAULT 0',
            'ALTER TABLE relationships ADD COLUMN hostility INTEGER NOT NULL DEFAULT 0',
            'ALTER TABLE relationships ADD COLUMN known_location TEXT',
        ):
            db.execute(sql)
        db.execute('PRAGMA user_version=3')
    db.commit()


def actor_disposition(actor):
    """Independent, reproducible personality; existing trait stats are untouched."""
    import random
    with world_transaction() as db:
        row = db.execute('SELECT * FROM dispositions WHERE actor=?',(actor,)).fetchone()
        if not row:
            rng = random.Random('personality:' + str(actor))
            choices = list(gamedata.WORLD_PERSONALITIES)
            rng.shuffle(choices)
            selected = choices[:rng.randint(1,3)]
            # Cautious and Adventurous are opposing dominant motivations here.
            if 'Cautious' in selected and 'Adventurous' in selected:
                selected.remove('Adventurous' if selected[0]=='Cautious' else 'Cautious')
            db.execute('INSERT INTO dispositions VALUES(?,?,?)',(actor,selected[0],json.dumps(selected[1:])))
            return selected
        secondary = decode_profile_json('{"values":'+row['secondary']+'}')['values']
        values = [row['dominant']] + secondary if isinstance(secondary,list) else []
        if not 1 <= len(values) <= 3 or any(v not in gamedata.WORLD_PERSONALITIES for v in values) or len(set(values))!=len(values):
            raise logs.SteamError('Invalid saved world personality. Restore a backup.')
        return values


def relationship_list(player, page=0):
    validate_page('',page,50)
    with world_snapshot() as db:
        # The pair index lists only this player's conversations. Rumors can
        # change opinions before a first meeting and keep their own records.
        contacts=""" FROM (SELECT DISTINCT npc FROM conversations WHERE player=?) c
                      JOIN relationships r ON r.player=? AND r.npc=c.npc
                      JOIN profiles p ON p.id=c.npc"""
        rows=db.execute('SELECT r.*,p.name'+contacts+' ORDER BY last_day DESC,p.name,r.npc LIMIT 50 OFFSET ?',
                        (player,player,page*50)).fetchall()
        total=db.execute('SELECT count(*)'+contacts,(player,player)).fetchone()[0]
        result=[]
        for row in rows:
            item=dict(row)
            memory=db.execute("SELECT e.summary FROM event_knowledge k JOIN world_events e ON e.id=k.event JOIN event_facts f ON f.event=e.id WHERE k.actor=? AND json_extract(f.facts,'$.subject')=? ORDER BY e.day DESC,e.id DESC LIMIT 1",(row['npc'],player)).fetchone()
            item['memory']=memory[0] if memory else None
            result.append(item)
        return result,total


def sect_roster(sect_id, page=0, viewer=None):
    validate_page('',page,50)
    with world_snapshot() as db:
        sql = '''SELECT a.*,p.name,p.data,m.name mentor_name FROM affiliations a JOIN profiles p ON p.id=a.actor
                 LEFT JOIN profiles m ON m.id=a.mentor WHERE a.sect_id=?'''
        leaders = db.execute(sql+" AND a.office<>'Member' ORDER BY CASE a.office WHEN 'Sect Master' THEN 0 WHEN 'Acting Master' THEN 0 ELSE 1 END,p.name",(sect_id,)).fetchall()
        members = db.execute(sql+' ORDER BY CASE WHEN a.actor=? THEN 0 ELSE 1 END,p.name,p.id LIMIT 50 OFFSET ?',(sect_id,viewer,page*50)).fetchall()
        count = db.execute('SELECT count(*) FROM affiliations WHERE sect_id=?',(sect_id,)).fetchone()[0]
        disciples=db.execute(sql+' AND a.mentor IS NOT NULL ORDER BY p.name,p.id',(sect_id,)).fetchall()
        def present(row):
            result=dict(row);pc=decode_profile_json(result.pop('data'))
            life=pc.get('life',{})
            result['gender']=(life.get('incarnation') or {}).get('gender') or pc.get('offline',{}).get('character',{}).get('gender')

            realm=pc.get('realm_state',{}).get('realm_index') or 0
            points=pc.get('sect_memberships',{}).get(sect_id,{}).get('points',gamedata.SECT_INITIAL_REPUTATION[realm])
            result['rank']=next(label for threshold,label in reversed(gamedata.SECT_RANKS) if points>=threshold)
            result['dead']=bool(pc.get('life',{}).get('dead'))
            return result
        return dict(leaders=[present(r) for r in leaders],members=[present(r) for r in members],total=count,disciples=[present(r) for r in disciples])

# ============================================================================
# Living actions (schema 4): authoritative presence, injuries, knowledge, encounters.
# ============================================================================
def _migrate_living_actions(db,path):
    lease=db.execute('SELECT expires FROM simulation_lease WHERE id=1').fetchone()
    if lease and lease[0]>time.time():
        raise logs.SteamError('Close other game instances before upgrading (wait 30 seconds after a crash).')
    folder=path.parent/'migration_backups';folder.mkdir(exist_ok=True)
    backup=sqlite3.connect(folder/('before_living_actions_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.db'))
    try:db.backup(backup)
    finally:backup.close()
    db.execute('BEGIN IMMEDIATE')
    if db.execute('PRAGMA user_version').fetchone()[0]==3:
        for sql in (
            'CREATE TABLE living_meta(id INTEGER PRIMARY KEY CHECK(id=1),initialized INTEGER NOT NULL DEFAULT 0,next_major REAL NOT NULL DEFAULT 0,last_cleanup REAL NOT NULL DEFAULT 0)',
            'INSERT INTO living_meta(id) VALUES(1)',
            'CREATE INDEX actors_at_location ON positions(location,actor)',
            'CREATE INDEX journeys_due ON journeys(arrival)',
            'ALTER TABLE journeys ADD COLUMN encounter_day REAL',
            'CREATE TABLE injuries(actor TEXT PRIMARY KEY REFERENCES profiles(id),until_day REAL NOT NULL,factor REAL NOT NULL CHECK(factor>0 AND factor<=1),cause TEXT NOT NULL)',
            "CREATE TABLE encounters(id TEXT PRIMARY KEY,actor TEXT NOT NULL UNIQUE REFERENCES profiles(id),day REAL NOT NULL,data TEXT NOT NULL)",
            'CREATE TABLE event_facts(event INTEGER PRIMARY KEY REFERENCES world_events(id),facts TEXT NOT NULL)',
            'CREATE TABLE news_queue(event INTEGER REFERENCES world_events(id),location TEXT REFERENCES locations(id),due REAL NOT NULL,PRIMARY KEY(event,location))',
            'CREATE INDEX news_due ON news_queue(due)',
            'CREATE TABLE duel_cooldowns(a TEXT REFERENCES profiles(id),b TEXT REFERENCES profiles(id),ready_day REAL NOT NULL,PRIMARY KEY(a,b))',
        ):db.execute(sql)
        db.execute('PRAGMA user_version=4')
    db.commit()


def region_ready(db):
    return bool(db.execute('SELECT initialized FROM region_meta').fetchone()[0])


def presence(actor, *, initialize=True):
    """A journey supersedes the saved departure location. No consumer may count both."""
    with world_transaction() as db:
        if not region_ready(db):return dict(state='unmapped',location=None,name='Region not initialized')
        if not db.execute('SELECT 1 FROM profiles WHERE id=?',(actor,)).fetchone():
            raise logs.SteamError('Unknown cultivator.')
        if initialize:db.execute('INSERT OR IGNORE INTO positions(actor,location) VALUES(?,?)',(actor,'r0_4'))
        pending=db.execute('SELECT id FROM encounters WHERE actor=?',(actor,)).fetchone()
        journey=db.execute('SELECT * FROM journeys WHERE actor=?',(actor,)).fetchone()
        if journey:
            return dict(state='encounter' if pending else 'travelling',location=None,name='On the road',journey=dict(journey))
        row=db.execute('SELECT l.* FROM positions p JOIN locations l ON l.id=p.location WHERE p.actor=?',(actor,)).fetchone()
        if not row and not initialize and not db.execute('SELECT 1 FROM positions WHERE actor=?',(actor,)).fetchone():
            row=db.execute("SELECT id,name FROM locations WHERE id='r0_4'").fetchone()
        if not row:raise logs.SteamError('Invalid saved location. Restore a database backup.')
        return dict(state='present',location=row['id'],name=row['name'])


def injury_state(actor):
    with world_transaction() as db:
        row=db.execute('SELECT * FROM injuries WHERE actor=?',(actor,)).fetchone()
        if not row:return None
        if any(type(row[k]) not in (int,float) or not math.isfinite(row[k]) for k in ('until_day','factor')) or not 0<row['factor']<=1:
            raise logs.SteamError('Invalid saved injury. Restore a backup.')
        return dict(row) if row['until_day']>world_state()['day'] else None


def require_physical(actor, *, dangerous=False, others=()):
    """Called inside action transactions, including CLI and NPC actions."""
    with world_transaction() as db:
        if db.execute('SELECT 1 FROM ascensions WHERE actor=?',(actor,)).fetchone():
            raise logs.SteamError('This cultivator is maintaining an ascension ritual.')
        if db.execute('SELECT 1 FROM encounters LIMIT 1').fetchone():
            raise logs.SteamError('The world is paused for a travel encounter. Resolve it before physical actions.')
        here=presence(actor)
        if here['state'] in ('travelling','encounter'):
            raise logs.SteamError('This cultivator is travelling. Wait until arrival before a physical action.')
        if dangerous and injury_state(actor):raise logs.SteamError('This cultivator is injured. Recover before dangerous activities.')
        for other in others:
            there=require_physical(other,dangerous=dangerous)
            if here['location']!=there['location']:raise logs.SteamError('Both cultivators must be at the same location.')
        return here


def people_here(actor,query='',page=0,detailed=False):
    validate_page(query,page,50)
    with world_snapshot() as db:
        if profile_field(actor,'life',{}).get('dead'):
            return dict(people=[],total=0,where='Deceased — seek rebirth through Adventure',state='deceased')
        here=presence(actor,initialize=False)
        if here['state']!='present':return dict(people=[],total=0,where=here['name'],state=here['state'])
        # Dead profiles remain browsable globally but never appear as available people.
        where="pos.location=? AND p.id<>? AND j.actor IS NULL AND json_extract(p.data,'$.life.dead') IS NULL AND instr(lower(p.name),lower(?))>0"
        args=(here['location'],actor,query)
        join=' FROM positions pos JOIN profiles p ON p.id=pos.actor JOIN npcs n ON n.id=p.id LEFT JOIN journeys j ON j.actor=p.id '
        count=db.execute('SELECT count(*)'+join+'WHERE '+where,args).fetchone()[0]
        fields=',p.data,i.factor' if detailed else ''
        injury=' LEFT JOIN injuries i ON i.actor=p.id AND i.until_day>(SELECT day FROM world)' if detailed else ''
        rows=db.execute('SELECT p.id,p.name,n.activity,a.office,a.mentor,a.sect_id,s.name sect'+fields+join+'LEFT JOIN affiliations a ON a.actor=p.id LEFT JOIN sects s ON s.id=a.sect_id'+injury+' WHERE '+where+' ORDER BY p.name,p.id LIMIT 50 OFFSET ?',args+(page*50,)).fetchall()
        people=[]
        for row in rows:
            person=dict(row,role=member_role(row))
            if detailed:
                person.update(npc_card_fields(row,decode_profile_json(person.pop('data'))))
                person['location']=here['name']
            people.append(person)
        return dict(people=people,total=count,where=here['name'],state='present')


def pending_encounter():
    with world_transaction() as db:
        row=db.execute('SELECT e.*,p.name FROM encounters e JOIN profiles p ON p.id=e.actor ORDER BY e.day LIMIT 1').fetchone()
        if not row:return None
        result=dict(row)
        try:
            result['data']=decode_profile_json(result['data'])
            if not isinstance(result['data'].get('enemy'),str):raise ValueError('Invalid encounter opponent')
            for key in ('escape','win','death_on_loss'):
                value=result['data'][key]
                if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1:raise ValueError('Invalid encounter odds')
        except (TypeError,ValueError,KeyError) as exc:
            raise logs.SteamError('Invalid saved encounter. Restore a backup.') from exc
        return result


def death_account(actor, circumstances):
    """Snapshot the place before retirement clears the last journey."""
    with world_transaction() as db:
        place = None
        if region_ready(db):
            road = db.execute("SELECT a.name,b.name FROM journeys j JOIN locations a ON a.id=json_extract(j.path,'$[0]') JOIN locations b ON b.id=json_extract(j.path,'$[#-1]') WHERE actor=?", (actor,)).fetchone()
            if road:
                place = f"on the road from {road[0]} to {road[1]}"
            else:
                site = db.execute('SELECT l.name FROM positions p JOIN locations l ON l.id=p.location WHERE p.actor=?', (actor,)).fetchone()
                if site:
                    place = 'at ' + site[0]
        return dict(circumstances=circumstances, place=place)


def mark_dead(actor,c,cause,*,circumstances=None):
    """A death removes travel and availability in the same gameplay transaction."""
    day=world_state()['day']
    write_life(actor,dead=dict(killer=cause,friend_id=None,scene=0,age=c['age'],year=int(day)//DAYS_PER_YEAR,world_day=day, account=death_account(actor,circumstances)))
    retire_dead(actor)


def retire_dead(actor):
    with world_transaction() as db:
        if db.execute('PRAGMA user_version').fetchone()[0]>=9:
            r=db.execute('SELECT site FROM ascensions WHERE actor=?',(actor,)).fetchone()
            if r:
                import warfare
                warfare.ritual_event(db,actor,r[0],'Ascension ended','The ascender died before completion.')
                db.execute('DELETE FROM ascensions WHERE actor=?',(actor,))
            db.execute('DELETE FROM ritual_party WHERE actor=? OR leader=?',(actor,actor))
        db.execute('DELETE FROM journeys WHERE actor=?',(actor,))
        db.execute('DELETE FROM encounters WHERE actor=?',(actor,))
        db.execute('DELETE FROM campaign_forces WHERE actor=?',(actor,))
        db.execute('DELETE FROM garrison_orders WHERE actor=?',(actor,))
        db.execute('DELETE FROM mine_wardens WHERE actor=?',(actor,))
        db.execute('DELETE FROM injuries WHERE actor=?',(actor,))
        db.execute("UPDATE npcs SET next_day=1e30,activity='Deceased' WHERE id=?",(actor,))


def injure(actor,cause,seconds=None):
    seconds=gamedata.INJURY_RECOVERY_SECONDS if seconds is None else seconds
    with world_transaction() as db:
        w=world_state();until=w['day']+seconds/w['seconds_per_day']
        db.execute('INSERT INTO injuries VALUES(?,?,?,?) ON CONFLICT(actor) DO UPDATE SET until_day=max(until_day,excluded.until_day),cause=excluded.cause',
                   (actor,until,gamedata.INJURY_POWER_FACTOR,cause))

# ============================================================================
# Sect governance schema 5. Stable IDs connect future diplomacy and territory.
# ============================================================================
def _migrate_sect_politics(db,path):
    lease=db.execute('SELECT expires FROM simulation_lease WHERE id=1').fetchone()
    if lease and lease[0]>time.time():raise logs.SteamError('Close other game instances before upgrading this world; a crashed session expires after 30 seconds.')
    folder=path.parent/'migration_backups';folder.mkdir(exist_ok=True)
    backup=sqlite3.connect(folder/('before_sect_politics_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.db'))
    try:db.backup(backup)
    finally:backup.close()
    db.execute('BEGIN IMMEDIATE')
    if db.execute('PRAGMA user_version').fetchone()[0]==4:
        for sql in (
            'CREATE TABLE sect_charters(sect_id TEXT PRIMARY KEY REFERENCES sects(id))',
            'CREATE TABLE actor_measures(actor TEXT PRIMARY KEY REFERENCES profiles(id),power REAL NOT NULL,realm INTEGER NOT NULL,day REAL NOT NULL)',
            'CREATE TABLE sect_governance(sect_id TEXT PRIMARY KEY REFERENCES sects(id),next_tick REAL NOT NULL,next_plot REAL NOT NULL,succession_at REAL,treasury INTEGER NOT NULL DEFAULT 0 CHECK(treasury>=0),revision INTEGER NOT NULL DEFAULT 0)',
            'CREATE TABLE membership_terms(actor TEXT PRIMARY KEY REFERENCES profiles(id),changed_day REAL NOT NULL DEFAULT -1,ready_day REAL NOT NULL DEFAULT 0,repair_used INTEGER NOT NULL DEFAULT 0,next_salary REAL NOT NULL,paid_role TEXT NOT NULL DEFAULT \'\',train_ready REAL NOT NULL DEFAULT 0,npc_review REAL NOT NULL)',
            'CREATE TABLE sect_ledger(id INTEGER PRIMARY KEY,sect_id TEXT REFERENCES sects(id),actor TEXT REFERENCES profiles(id),day REAL NOT NULL,kind TEXT NOT NULL,amount INTEGER NOT NULL,token TEXT UNIQUE NOT NULL)',
            'CREATE TABLE council_support(sect_id TEXT REFERENCES sects(id),candidate TEXT REFERENCES profiles(id),voter TEXT REFERENCES profiles(id),purpose TEXT NOT NULL,backing INTEGER NOT NULL DEFAULT 0,ready_day REAL NOT NULL DEFAULT 0,PRIMARY KEY(sect_id,candidate,voter,purpose))',
            'CREATE TABLE mentor_rewards(disciple TEXT REFERENCES profiles(id),event INTEGER,mentor TEXT REFERENCES profiles(id),amount INTEGER NOT NULL,PRIMARY KEY(disciple,event))',
            'CREATE TABLE sect_departures(id INTEGER PRIMARY KEY,actor TEXT REFERENCES profiles(id),sect_id TEXT REFERENCES sects(id),day REAL NOT NULL,office TEXT NOT NULL,penalty INTEGER NOT NULL)',
            'CREATE TABLE sect_plots(id TEXT PRIMARY KEY,sect_id TEXT REFERENCES sects(id),actor TEXT REFERENCES profiles(id),stage TEXT NOT NULL,due REAL NOT NULL,created REAL NOT NULL,round INTEGER NOT NULL DEFAULT 0,wins INTEGER NOT NULL DEFAULT 0,outcome TEXT,assassination_attempted INTEGER NOT NULL DEFAULT 0)',
            "CREATE UNIQUE INDEX one_active_plot ON sect_plots(sect_id) WHERE stage IN ('gathering','preparing','conflict')",
            'CREATE TABLE plot_evidence(plot TEXT REFERENCES sect_plots(id),observer TEXT REFERENCES profiles(id),points INTEGER NOT NULL DEFAULT 0,ready_day REAL NOT NULL DEFAULT 0,PRIMARY KEY(plot,observer))',
            'CREATE TABLE political_events(id INTEGER PRIMARY KEY,sect_id TEXT REFERENCES sects(id),plot TEXT REFERENCES sect_plots(id),event INTEGER REFERENCES world_events(id),day REAL NOT NULL,kind TEXT NOT NULL,data TEXT NOT NULL,public INTEGER NOT NULL DEFAULT 1)',
            'CREATE INDEX politics_by_sect ON political_events(sect_id,id DESC)',
        ):db.execute(sql)
        db.execute('PRAGMA user_version=5')
    db.commit()


def seat_location(db,sect):
    """Return the council's current seat, including a refuge after occupation."""
    original=db.execute('SELECT id FROM locations WHERE sect_id=?',(sect,)).fetchone()
    if not original:return None
    rule=db.execute('SELECT owner FROM campaign_sites WHERE site=?',(original[0],)).fetchone()
    if not rule or rule[0]==sect:return original
    refuge=db.execute('SELECT site FROM campaign_sites WHERE owner=? ORDER BY site LIMIT 1',(sect,)).fetchone()
    return refuge or ('r0_4',)


def sect_catalog(cache=None):
    """Exactly twenty chartered sects. No population generation or clock advancement."""
    import random,hashlib,unicodedata
    with world_transaction(cache) as db:
        if not db.execute('SELECT 1 FROM sect_charters LIMIT 1').fetchone():
            homes=db.execute('SELECT s.id,s.name FROM locations l JOIN sects s ON s.id=l.sect_id ORDER BY s.id').fetchall()
            chosen=[(r['id'],r['name']) for r in homes][:20]
            rng=random.Random(db.execute('SELECT seed FROM world').fetchone()[0]+'0')
            while len(chosen)<20:
                name=f'{rng.choice(gamedata.SECT_ADJ)} {rng.choice(gamedata.SECT_NOUN)}'
                canonical=' '.join(unicodedata.normalize('NFKC',name).casefold().split())
                sid=hashlib.sha256(canonical.encode()).hexdigest()[:24]
                if sid in {s[0] for s in chosen}:continue
                db.execute('INSERT OR IGNORE INTO sects(id,name) VALUES(?,?)',(sid,name));chosen.append((sid,name))
            db.executemany('INSERT INTO sect_charters VALUES(?)',[(sid,) for sid,name in chosen])
        rows=[]
        for sect in db.execute('SELECT s.* FROM sects s JOIN sect_charters c ON c.sect_id=s.id ORDER BY s.name').fetchall():
            members=db.execute("SELECT a.*,p.name,p.data FROM affiliations a JOIN profiles p ON p.id=a.actor WHERE a.sect_id=? AND json_extract(p.data,'$.life.dead') IS NULL",(sect['id'],)).fetchall()
            master=next((r for r in members if r['office'] in ('Sect Master','Acting Master')),None)
            home=seat_location(db,sect['id'])
            rows.append(dict(id=sect['id'],name=sect['name'],members=len(members),elders=sum(r['office']=='Elder' for r in members),master=master['name'] if master else 'Vacant',master_id=master['actor'] if master else None,acting=bool(master and master['office']=='Acting Master'),location=home[0] if home else None))
        return rows


def chartered_sect(name,cache=None):
    # Compare canonical identity, without creating an unlisted registry record.
    import unicodedata
    normalize=lambda x:' '.join(unicodedata.normalize('NFKC',x).casefold().split())
    return next((s for s in sect_names(cache) if normalize(s['name'])==normalize(name)),None)

def sect_names(cache=None):
    with world_transaction(cache) as db:
        if not db.execute('SELECT 1 FROM sect_charters LIMIT 1').fetchone():sect_catalog(cache)
        return [dict(r) for r in db.execute('SELECT s.id,s.name FROM sects s JOIN sect_charters c ON c.sect_id=s.id ORDER BY s.name')]

# ============================================================================
# Storage retention (schema 6). All gameplay cleanup is bounded and transactional.
# ============================================================================
NPC_RECENT_ACTIVITY = 25
NPC_HEARD_REPORTS = 170
NEWS_ARCHIVE_DAYS = 6


def _apply_retention_policy(db,path):
    """One-time policy backfill; no trimming or world advancement at startup."""
    if db.execute('PRAGMA user_version').fetchone()[0]<6:return
    if db.execute("SELECT 1 FROM sqlite_schema WHERE name='retention_policy'").fetchone():
        row=db.execute('SELECT routine,reports FROM retention_policy WHERE id=1').fetchone()
        if row and tuple(row)==(NPC_RECENT_ACTIVITY,NPC_HEARD_REPORTS):return
    if db.execute('SELECT 1 FROM npcs LIMIT 1').fetchone():
        lease=db.execute('SELECT expires FROM simulation_lease WHERE id=1').fetchone()
        if lease and lease[0]>time.time():
            raise logs.SteamError('Close the other game before updating retention; a crashed session expires after 30 seconds.')
        folder=path.parent/'migration_backups';folder.mkdir(exist_ok=True)
        with contextlib.closing(sqlite3.connect(folder/('before_retention_25_170_'+uuid.uuid4().hex+'.db'))) as backup:
            db.backup(backup)
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('CREATE TABLE IF NOT EXISTS retention_policy(id INTEGER PRIMARY KEY CHECK(id=1),routine INTEGER NOT NULL,reports INTEGER NOT NULL)')
        row=db.execute('SELECT routine,reports FROM retention_policy WHERE id=1').fetchone()
        if not row or tuple(row)!=(NPC_RECENT_ACTIVITY,NPC_HEARD_REPORTS):
            # The bounded profile pass also queues each NPC for the lower news cap.
            db.execute("UPDATE storage_maintenance SET profile_cursor='',profiles_done=NOT EXISTS(SELECT 1 FROM npcs)")
            db.execute('INSERT OR REPLACE INTO retention_policy VALUES(1,?,?)',(NPC_RECENT_ACTIVITY,NPC_HEARD_REPORTS))
        db.commit()
    except BaseException:
        db.rollback();raise


def _migrate_storage_retention(db,path):
    lease=db.execute('SELECT expires FROM simulation_lease WHERE id=1').fetchone()
    if lease and lease[0]>time.time():
        raise logs.SteamError('Close other game instances before upgrading storage; a crashed session expires after 30 seconds.')
    folder=path.parent/'migration_backups';folder.mkdir(exist_ok=True)
    backup=sqlite3.connect(folder/('before_storage_retention_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.db'))
    try:db.backup(backup)
    finally:backup.close()
    db.execute('BEGIN IMMEDIATE')
    if db.execute('PRAGMA user_version').fetchone()[0]==5:
        for sql in (
            'CREATE TABLE npc_milestones(actor TEXT REFERENCES profiles(id),token TEXT NOT NULL,at REAL NOT NULL,data TEXT NOT NULL,PRIMARY KEY(actor,token)) WITHOUT ROWID',
            'CREATE INDEX milestone_dates ON npc_milestones(actor,at DESC,token)',
            'CREATE TABLE npc_legacy_activity(actor TEXT PRIMARY KEY REFERENCES profiles(id),data TEXT NOT NULL)',
            'CREATE TABLE event_archives(event INTEGER PRIMARY KEY REFERENCES world_events(id))',
            'CREATE TABLE memory_queue(actor TEXT PRIMARY KEY REFERENCES profiles(id),due REAL NOT NULL)',
            'CREATE INDEX memory_due ON memory_queue(due,actor)',
            "CREATE INDEX heard_news_recent ON event_knowledge(actor,learned_day DESC,event DESC) WHERE source='Local report'",
            'CREATE INDEX cooldown_expiry ON duel_cooldowns(ready_day)',
            "CREATE TABLE storage_maintenance(id INTEGER PRIMARY KEY CHECK(id=1),profile_cursor TEXT NOT NULL DEFAULT '',profiles_done INTEGER NOT NULL DEFAULT 0,effect_cursor INTEGER NOT NULL DEFAULT 0,effect_actor TEXT NOT NULL DEFAULT '',effect_kind TEXT NOT NULL DEFAULT '',effects_done INTEGER NOT NULL DEFAULT 0,turn INTEGER NOT NULL DEFAULT 0)",
            "INSERT INTO storage_maintenance(id,profiles_done,effects_done) SELECT 1,NOT EXISTS(SELECT 1 FROM profiles WHERE kind='npc'),NOT EXISTS(SELECT 1 FROM event_effects)",
        ):db.execute(sql)
        db.execute('PRAGMA user_version=6')
    db.commit()


def significant_activity(event):
    """Only structured outcomes, never words in narrative summaries."""
    kind=event.get('type')
    return bool(kind in ('breakthrough','reborn')
                or event.get('milestone') in ('mentor_reward','major_discovery','leadership','major_injury')
                or event.get('outcome') in ('death','injury','injured','killed')
                or (kind in ('duel','team') and (event.get('upset') or event.get('mode')=='Lethal'))
                or (kind=='adventure' and event.get('kind') in ('treasure','gain','loss')))


def retain_npc_activity(db,data):
    import hashlib
    actor=str(data['steamid']);routine=[]
    for event in data.get('activity',[]):
        if not isinstance(event,dict):continue
        if significant_activity(event):
            payload=json.dumps(event,ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(',',':'))
            token=hashlib.sha256(payload.encode('utf-8')).hexdigest()
            db.execute('INSERT OR IGNORE INTO npc_milestones VALUES(?,?,?,?)',(actor,token,event.get('at',0),payload))
        else:routine.append(event)
    # Old untyped summaries may contain milestones. Preserve them once, outside
    # the frequently rewritten profile, instead of guessing from their wording.
    unknown=[e for e in routine[:-NPC_RECENT_ACTIVITY] if 'routine' not in e and e.get('type')=='adventure' and 'outcome' not in e and 'kind' not in e]
    if unknown:
        row=db.execute('SELECT data FROM npc_legacy_activity WHERE actor=?',(actor,)).fetchone()
        archive=json.loads(row[0]) if row else []
        keys={json.dumps(e,sort_keys=True,separators=(',',':')) for e in archive}
        for e in unknown:
            key=json.dumps(e,sort_keys=True,separators=(',',':'))
            if key not in keys:archive.append(e);keys.add(key)
        db.execute('INSERT INTO npc_legacy_activity VALUES(?,?) ON CONFLICT(actor) DO UPDATE SET data=excluded.data',
                   (actor,json.dumps(archive,ensure_ascii=False,allow_nan=False,separators=(',',':'))))
    return dict(data,activity=routine[-NPC_RECENT_ACTIVITY:])


def npc_history_archive(actor,limit=80):
    with world_transaction() as db:
        result=[json.loads(r[0]) for r in db.execute('SELECT data FROM npc_milestones WHERE actor=? ORDER BY at DESC,token LIMIT ?',(actor,limit))]
        row=db.execute('SELECT data FROM npc_legacy_activity WHERE actor=?',(actor,)).fetchone()
        if row:result.extend(json.loads(row[0]))
        return result


def queue_memory_cleanup(db,actor,day):
    if db.execute('SELECT 1 FROM npcs WHERE id=?',(actor,)).fetchone():
        db.execute('INSERT OR IGNORE INTO memory_queue VALUES(?,?)',(actor,day))


def trim_heard_reports(db,actor,day,*,limit=256):
    """Bounded indexed retention; archive guards commit before memory deletion."""
    boundary=db.execute("SELECT learned_day,event FROM event_knowledge WHERE actor=? AND source='Local report' ORDER BY learned_day DESC,event DESC LIMIT 1 OFFSET ?",(actor,NPC_HEARD_REPORTS-1)).fetchone()
    if not boundary:
        db.execute('DELETE FROM memory_queue WHERE actor=?',(actor,));return 0
    candidates=db.execute("""SELECT k.event,e.day,
        EXISTS(SELECT 1 FROM news_queue q WHERE q.event=k.event) propagating
        FROM event_knowledge k JOIN world_events e ON e.id=k.event
        WHERE k.actor=? AND k.source='Local report' AND (k.learned_day,k.event)<(?,?)
        ORDER BY k.learned_day,k.event LIMIT ?""",(actor,*boundary,limit)).fetchall()
    eligible=[row['event'] for row in candidates if row['day']<=day-NEWS_ARCHIVE_DAYS and not row['propagating']]
    if eligible:
        marks=','.join('?' for _ in eligible)
        # One set operation per table instead of three statements per report.
        db.execute('INSERT OR IGNORE INTO event_archives(event) VALUES '+','.join('(?)' for _ in eligible),eligible)
        db.execute('DELETE FROM event_effects WHERE actor=? AND event IN ('+marks+')',[actor,*eligible])
        db.execute('DELETE FROM event_knowledge WHERE actor=? AND event IN ('+marks+')',[actor,*eligible])
    if len(candidates)<limit and len(eligible)==len(candidates):
        db.execute('DELETE FROM memory_queue WHERE actor=?',(actor,))
    else:
        db.execute('UPDATE memory_queue SET due=? WHERE actor=?',(day if eligible else day+.2,actor))
    return len(eligible)


def maintain_storage(db,day,*,budget=.008,max_jobs=8):
    """Small round-robin jobs; cursors and deletions commit with the world tick."""
    began=time.perf_counter();deadline=began+budget;completed=0;removed=0
    initial=db.execute('SELECT * FROM storage_maintenance WHERE id=1').fetchone()
    if initial['profiles_done'] and initial['effects_done'] and not db.execute('SELECT 1 FROM memory_queue WHERE due<=? LIMIT 1',(day,)).fetchone() and not db.execute('SELECT 1 FROM duel_cooldowns WHERE ready_day<=? LIMIT 1',(day,)).fetchone():return 0
    while completed<max_jobs and (not completed or time.perf_counter()<deadline):
        state=db.execute('SELECT * FROM storage_maintenance WHERE id=1').fetchone();turn=(initial['turn']+completed)%4
        memory=db.execute('SELECT actor FROM memory_queue WHERE due<=? ORDER BY due,actor LIMIT 1',(day,)).fetchone()
        expired=db.execute('SELECT 1 FROM duel_cooldowns WHERE ready_day<=? LIMIT 1',(day,)).fetchone()
        available={0:not state['profiles_done'],1:not state['effects_done'],2:bool(memory),3:bool(expired)}
        # Preserve round-robin fairness for live jobs; completed backfills no
        # longer consume a scarce catch-up slot. Prefer news for spare slots.
        job=next((j for j in (turn,2,0,1,3) if available[j]),None)
        if job is None:break
        if job==0:
            rows=db.execute('SELECT p.id,p.data FROM npcs n JOIN profiles p ON p.id=n.id WHERE n.id>? ORDER BY n.id LIMIT 2',(state['profile_cursor'],)).fetchall()
            for row in rows:
                _write_profile(db,decode_profile_json(row['data']));queue_memory_cleanup(db,row['id'],day)
            db.execute('UPDATE storage_maintenance SET profile_cursor=?,profiles_done=? WHERE id=1',(rows[-1]['id'] if rows else state['profile_cursor'],int(len(rows)<2)))
        elif job==1:
            # Stable logical keys survive offline VACUUM and database copying.
            rows=db.execute('SELECT event,actor,effect FROM event_effects WHERE (event,actor,effect)>(?,?,?) ORDER BY event,actor,effect LIMIT 128',(state['effect_cursor'],state['effect_actor'],state['effect_kind'])).fetchall()
            for row in rows:
                if db.execute('SELECT 1 FROM event_knowledge WHERE actor=? AND event=?',(row['actor'],row['event'])).fetchone() or db.execute('SELECT 1 FROM event_archives WHERE event=?',(row['event'],)).fetchone():
                    db.execute('DELETE FROM event_effects WHERE event=? AND actor=? AND effect=?',(row['event'],row['actor'],row['effect']))
            if rows:
                last=rows[-1]
                db.execute('UPDATE storage_maintenance SET effect_cursor=?,effect_actor=?,effect_kind=?,effects_done=? WHERE id=1',(last['event'],last['actor'],last['effect'],int(len(rows)<128)))
            else:db.execute('UPDATE storage_maintenance SET effects_done=1 WHERE id=1')
        elif job==2:
            removed+=trim_heard_reports(db,memory['actor'],day)
        elif job==3:
            db.execute('DELETE FROM duel_cooldowns WHERE rowid IN (SELECT rowid FROM duel_cooldowns WHERE ready_day<=? ORDER BY ready_day LIMIT 64)',(day,))
        completed+=1
    if completed:db.execute('UPDATE storage_maintenance SET turn=? WHERE id=1',((initial['turn']+completed)%4,))
    metrics=getattr(_world_local,'batch_metrics',None)
    if metrics is not None:
        metrics['retention_jobs']=metrics.get('retention_jobs',0)+completed
        metrics['retention_removed']=metrics.get('retention_removed',0)+removed
        metrics['retention_ms']=metrics.get('retention_ms',0)+(time.perf_counter()-began)*1000
        oldest=db.execute('SELECT due FROM memory_queue ORDER BY due,actor LIMIT 1').fetchone()
        metrics['retention_oldest_days']=max(0,day-oldest[0]) if oldest else 0
    return completed


def compact_world_copy(destination,cache=None):
    """Explicit offline tool: validate a compact copy; never replace the input."""
    source=database_path(cache).resolve();destination=Path(destination).resolve()
    if destination.exists():raise logs.SteamError('Choose a new output filename; existing files are never overwritten.')
    if not source.is_file():raise logs.SteamError('No world.db was found in that cache.')
    stage=destination.with_name(destination.name+'.incomplete-'+uuid.uuid4().hex)
    try:
        with contextlib.closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as db:
            lease=db.execute('SELECT expires FROM simulation_lease WHERE id=1').fetchone()
            if lease and lease[0]>time.time():raise logs.SteamError('Close the game and editor before offline compaction.')
            db.execute('VACUUM INTO ?',(str(stage),))
        with contextlib.closing(sqlite3.connect(stage.as_uri()+'?mode=ro',uri=True)) as check:
            if check.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or check.execute('PRAGMA foreign_key_check').fetchone():
                raise logs.SteamError('The compact copy did not pass validation. The original remains unchanged.')
        # Publish without replacement, including if another process creates the
        # requested destination while validation is running.
        os.link(stage,destination)
        return dict(original_bytes=source.stat().st_size,compact_bytes=destination.stat().st_size,path=str(destination))
    finally:
        if stage.exists():stage.unlink()


def optimize_world_copy(destination,cache=None):
    """Finish retention on a private SQLite backup, then publish a compact copy."""
    source=database_path(cache).resolve();destination=Path(destination).resolve()
    if destination.exists():raise logs.SteamError('Choose a new output filename; existing files are never overwritten.')
    with tempfile.TemporaryDirectory(prefix='world-optimize-',dir=destination.parent) as folder:
        copied=Path(folder)/'world.db'
        with contextlib.closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src:
            lease=src.execute('SELECT expires FROM simulation_lease WHERE id=1').fetchone()
            if lease and lease[0]>time.time():raise logs.SteamError('Close the game and editor before offline optimization.')
            with contextlib.closing(sqlite3.connect(copied)) as dst:src.backup(dst)
        transactions=0
        with contextlib.closing(_open_world(folder)) as db:
            day=db.execute('SELECT day FROM world').fetchone()[0]
            while True:
                db.execute('BEGIN IMMEDIATE')
                try:
                    maintain_storage(db,day)
                    state=db.execute('SELECT profiles_done,effects_done FROM storage_maintenance').fetchone()
                    pending=(not all(state) or db.execute('SELECT 1 FROM memory_queue WHERE due<=? LIMIT 1',(day,)).fetchone()
                             or db.execute('SELECT 1 FROM duel_cooldowns WHERE ready_day<=? LIMIT 1',(day,)).fetchone())
                    db.commit();transactions+=1
                except BaseException:
                    db.rollback();raise
                if not pending:break
        result=compact_world_copy(destination,folder)
        result.update(original_bytes=source.stat().st_size,retention_transactions=transactions)
        return result


def _migrate_territory(db,path):
    lease=db.execute('SELECT expires FROM simulation_lease WHERE id=1').fetchone()
    if lease and lease[0]>time.time():
        raise logs.SteamError('Close the other game before upgrading the economy. A crashed session expires after 30 seconds.')
    folder=path.parent/'migration_backups'
    folder.mkdir(exist_ok=True)
    backup=sqlite3.connect(folder/('before_territory_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.db'))
    try:
        db.backup(backup)
    finally:
        backup.close()
    db.execute('BEGIN IMMEDIATE')
    if db.execute('PRAGMA user_version').fetchone()[0]==6:
        db.execute("""CREATE TABLE spirit_mines(location TEXT PRIMARY KEY REFERENCES locations(id),
                   kind TEXT NOT NULL CHECK(kind IN ('Small','Large')),owner TEXT REFERENCES sect_charters(sect_id),
                   yield_stones INTEGER NOT NULL CHECK(yield_stones>0))""")
        db.execute("""CREATE TABLE sect_payroll(sect_id TEXT PRIMARY KEY REFERENCES sect_charters(sect_id),
                   due REAL NOT NULL,cycles INTEGER NOT NULL DEFAULT 0,last_due INTEGER NOT NULL DEFAULT 0,
                   last_paid INTEGER NOT NULL DEFAULT 0,confidence INTEGER NOT NULL DEFAULT 100,
                   incumbent TEXT REFERENCES profiles(id))""")
        db.execute("""CREATE TABLE wage_debts(sect_id TEXT REFERENCES sect_charters(sect_id),actor TEXT REFERENCES profiles(id),
                   amount INTEGER NOT NULL CHECK(amount>0),misses INTEGER NOT NULL,PRIMARY KEY(sect_id,actor))""")
        db.execute("""CREATE TABLE salary_credits(actor TEXT PRIMARY KEY REFERENCES profiles(id),
            amount INTEGER NOT NULL CHECK(amount>0))""")
        db.execute("""CREATE VIEW paid_profiles AS SELECT p.id,p.kind,p.revision,coalesce(s.amount,0) AS credit,
            CASE WHEN s.actor IS NULL THEN p.data ELSE json_set(p.data,'$.wallet.spirit_stones',
            coalesce(json_extract(p.data,'$.wallet.spirit_stones'),0)+s.amount) END AS data
            FROM profiles p LEFT JOIN salary_credits s ON s.actor=p.id""")
        db.execute('CREATE TABLE mine_wardens(actor TEXT PRIMARY KEY REFERENCES profiles(id),location TEXT NOT NULL REFERENCES spirit_mines(location))')
        db.execute("""CREATE TRIGGER enroll_salary AFTER INSERT ON affiliations
            BEGIN INSERT OR IGNORE INTO membership_terms(actor,next_salary,npc_review)
            SELECT NEW.actor,day+1800.0/seconds_per_day,day+14400.0/seconds_per_day FROM world;
            END""")
        db.execute('CREATE INDEX sect_payroll_due ON sect_payroll(due,sect_id)')
        db.execute('PRAGMA user_version=7')
    db.commit()


def paid_profile_row(db,steamid):
    """Wallet snapshot for gameplay, editor and restore from pre-economy backups."""
    try:
        return db.execute('SELECT data,revision,credit FROM paid_profiles WHERE id=?',(str(steamid),)).fetchone()
    except sqlite3.OperationalError as exc:
        if str(exc)!='no such table: paid_profiles':
            raise
        return db.execute('SELECT data,revision,0 AS credit FROM profiles WHERE id=?',(str(steamid),)).fetchone()


def fold_salary_credit(db,steamid):
    """The caller is writing a wallet snapshot that already includes these wages."""
    if db.execute('PRAGMA user_version').fetchone()[0]>=7:
        db.execute('DELETE FROM salary_credits WHERE actor=?',(str(steamid),))


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Offline world storage tools; never overwrites a save.')
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--compact-copy',help='Compact the current data into a new output database. Close the game/editor first.')
    action.add_argument('--optimize-copy',help='Finish retention on a private backup and produce a validated compact database. Close the game/editor first.')
    parser.add_argument('--cache',default=CACHE_DIR,help='Folder containing world.db')
    args=parser.parse_args()
    print(json.dumps((optimize_world_copy(args.optimize_copy,args.cache) if args.optimize_copy else compact_world_copy(args.compact_copy,args.cache)),indent=2))
