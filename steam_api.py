"""Talking to the Steam Web API: the counted request helper, profile-URL parsing, SteamID
lookup and the friends list."""

import random
import re
import time

import requests

import logs
import storage


API = "https://api.steampowered.com"
TIMEOUT = 15


# Public Community inventories are separate from the publisher-only Inventory API.
# No API key, login cookies, trade actions, or market-price requests are sent here.
def inventory_treasure_candidates(steamid, appid, game):
    import html
    try:
        response = requests.get(f"https://steamcommunity.com/inventory/{steamid}/{appid}/2",
                                params={"l": "english", "count": 1000}, timeout=(2, 4))
        logs.RUN_LOG.record(f"CommunityInventory/{appid}", f"HTTP {response.status_code}")
        if response.status_code != 200:
            return []
        data = response.json()
    except requests.RequestException:
        logs.RUN_LOG.record(f"CommunityInventory/{appid}", "network error")
        logs.RUN_LOG.note(f"Community inventory {appid} unavailable; using game treasure fallback if needed")
        return []
    except ValueError:
        logs.RUN_LOG.note(f"Community inventory {appid} returned invalid JSON; using fallback if needed")
        return []
    if not isinstance(data, dict) or data.get("success") != 1:
        return []
    assets, descriptions = data.get("assets"), data.get("descriptions")
    if not isinstance(assets, list) or not isinstance(descriptions, list):
        return []
    owned = {(str(a.get("classid")), str(a.get("instanceid", "0"))) for a in assets
             if isinstance(a, dict) and str(a.get("classid", "")).isdigit()
             and str(a.get("instanceid", "0")).isdigit()
             and str(a.get("amount", "1")).isdigit() and int(str(a.get("amount", "1"))) > 0}
    result = []
    for item in descriptions:
        if not isinstance(item, dict) or (str(item.get("classid")), str(item.get("instanceid", "0"))) not in owned:
            continue
        name = item.get("market_hash_name") or item.get("name")
        if not isinstance(name, str):
            continue
        tags = item.get("tags", [])
        type_tags = " ".join(str(t.get("localized_tag_name", "")) + " " + str(t.get("internal_name", ""))
                             for t in tags if isinstance(t, dict) and t.get("category") == "Type") if isinstance(tags, list) else ""
        kind = (str(item.get("type", "")) + " " + type_tags).casefold()
        if appid == 730:
            if not any(word in kind for word in ("rifle", "pistol", "knife", "smg", "shotgun", "machinegun", "machine gun", "gloves")):
                continue
        elif any(word in kind for word in ("container", "supply crate", "treasure chest", "key", "tool")):
            continue
        clean = re.sub(r"[\x00-\x1f\x7f]", " ", html.unescape(re.sub(r"<[^>]*>", "", name))).strip()[:160]
        if clean:
            result.append(f"Steam item · {game} · {clean}")
    return sorted(set(result))


def choose_inventory_treasure(steamid):
    """Bounded parallel sampling: first 1,000 assets per supported game, no retries."""
    from concurrent.futures import ThreadPoolExecutor
    games = [(730, "CS2"), (570, "Dota 2"), (440, "TF2")]
    with ThreadPoolExecutor(max_workers=3) as pool:
        batches = list(pool.map(lambda g: inventory_treasure_candidates(steamid, *g), games))
    candidates = sorted(set(item for batch in batches for item in batch))
    return random.SystemRandom().choice(candidates) if candidates else None


def steam_get(endpoint, params):
    """Makes one Steam request and counts it. Every request in the program goes through here."""
    if not params.get("key"):
        raise logs.SteamError("This action needs a Steam API key. Local profiles work without one.")
    name = re.sub(r"/v\d+/?$", "", endpoint.strip("/"))
    try:
        r = requests.get(f"{API}/{endpoint}", params=params, timeout=TIMEOUT)
    except requests.RequestException:
        logs.RUN_LOG.record(name, "network error")
        raise
    # Steam answers 400 to "achievements of a game that has none", which is normal
    normal = r.status_code == 200 or (r.status_code == 400 and "GetPlayerAchievements" in name)
    logs.RUN_LOG.record(name, "HTTP 200" if normal else f"HTTP {r.status_code}")
    return r


def api_get(path, key, **params):
    params["key"] = key
    try:
        r = steam_get(path, params)
    except requests.RequestException as e:
        raise logs.SteamError("Could not reach Steam. Check your connection and try again.") from None
    if r.status_code in (401, 403):
        raise logs.SteamError("Steam rejected the API key (check it is correct).")
    if r.status_code != 200:
        raise logs.SteamError(f"Steam returned HTTP {r.status_code}.")
    try:
        data = r.json()
        if not isinstance(data,dict) or not isinstance(data.get('response'),dict):
            raise ValueError('Unexpected response structure')
        return data['response']
    except ValueError:
        raise logs.SteamError("Steam sent a response I could not read.")


def check_key(key):
    """Asks Steam one small question to find out whether the API key works. Raises SteamError
    (with a message fit to show) if Steam rejects the key or cannot be reached. The check is
    written to the run log like any other command."""
    logs.RUN_LOG.secret = key
    logs.RUN_LOG.begin("API key check")
    try:
        result = api_get("ISteamUser/GetPlayerSummaries/v0002/", key, steamids="76561197960435530")
        if not isinstance(result.get('players'),list) or any(not isinstance(p,dict) for p in result['players']):
            raise logs.SteamError('Steam returned an invalid key-validation response. Please try again.')
    except logs.SteamError as e:
        logs.RUN_LOG.finish(f"error: {e}")
        raise
    except BaseException as e:
        logs.RUN_LOG.finish(f"crashed: {type(e).__name__}: {e}")
        raise
    logs.RUN_LOG.finish("ok")


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


def resolve_steamid(text, key, refresh=False):
    import generator
    local_id = generator.resolve_local_profile(text)
    if local_id:
        return local_id
    if not key:
        raise logs.SteamError("No local profile found. Enter its name or local ID; Steam lookup needs an API key.")
    kind, value = parse_profile_input(text)
    if kind == "id":
        return value
    now = time.time()
    lookups = storage.load_lookups()
    saved = lookups["vanity"].get(value.lower())
    if (not refresh and storage.entry_fresh(saved, "vanity", now)
            and re.fullmatch(r"\d{17}", str(saved.get("steamid", "")))):
        logs.RUN_LOG.note(f"custom name '{value}': SteamID from cache ({storage.ago(now - saved['at'])} old)")
        return saved["steamid"]
    resp = api_get("ISteamUser/ResolveVanityURL/v1/", key, vanityurl=value)
    if resp.get("success") != 1:
        raise logs.SteamError(f"Could not find a profile named '{value}'.")
    lookups["vanity"][value.lower()] = {"at": now, "steamid": resp["steamid"]}
    storage.save_lookups(lookups)
    return resp["steamid"]


def fetch_friend_ids(steamid, key):
    """Asks Steam for the friends list. Returns (friend_ids, note, complete): complete is
    False when the answer is not trustworthy (network trouble, Steam error), so it is not saved."""
    try:
        r = steam_get("ISteamUser/GetFriendList/v1/",
                      {"key": key, "steamid": steamid, "relationship": "friend"})
    except requests.RequestException:
        return [], None, False
    if r.status_code in (401, 403):
        return [], "Your friends list is private, so no friend story this time.", True
    if r.status_code != 200:
        return [], None, False
    try:
        data=r.json()
        listing=data.get('friendslist') if isinstance(data,dict) else None
        friends=listing.get('friends') if isinstance(listing,dict) else None
        if not isinstance(friends,list) or any(not isinstance(f,dict) or not re.fullmatch(r'\d{17}',str(f.get('steamid',''))) for f in friends):
            return [],None,False
    except ValueError:
        return [], None, False
    return [f["steamid"] for f in friends], None, True  # no friends -> empty list -> story skipped


def get_friend_ids(steamid, key):
    """Returns (friend_ids, note). The list is empty when there are no friends or the
    friends list can't be read; note is a short explanation worth showing, or None."""
    ids, note, _ = fetch_friend_ids(steamid, key)
    return ids, note


def get_friends(steamid, key, refresh=False):
    """Like get_friend_ids, but a list that was saved less than REFRESH_HOURS['friends'] ago is
    used instead of asking Steam. If Steam cannot be reached, the last saved list is used even
    when it is older, so the story and a possible betrayal do not change because of a hiccup."""
    now = time.time()
    pc = storage.load_profile_cache(steamid)
    if not refresh and storage.section_fresh(pc, "friends", now):
        v = pc["sections"]["friends"]["value"]
        logs.RUN_LOG.note(f"friends: {len(v['ids'])} from cache "
                          f"({storage.ago(now - pc['sections']['friends']['at'])} old)")
        return list(v["ids"]), v["note"]
    ids, note, complete = fetch_friend_ids(steamid, key)
    if complete:
        pc["sections"]["friends"] = {"at": now, "value": {"ids": ids, "note": note}}
        storage.save_profile_cache(pc)
        logs.RUN_LOG.note(f"friends: {len(ids)} from Steam")
        return ids, note
    old = pc["sections"].get("friends")
    if isinstance(old, dict) and isinstance(old.get("value"), dict) and \
            isinstance(old["value"].get("ids"), list):
        logs.RUN_LOG.note(f"friends: Steam did not answer, using the saved list of "
                          f"{len(old['value']['ids'])} ({storage.ago(now - old.get('at', now))} old)")
        return list(old["value"]["ids"]), old["value"].get("note")
    logs.RUN_LOG.note("friends: Steam did not answer and nothing was saved")
    return ids, note


def get_friend(friend_id, key):
    """Returns {'steamid', 'name'} or None if that friend's profile can't be read.
    A display name that was saved less than REFRESH_HOURS['friend_names'] ago is reused."""
    now = time.time()
    lookups = storage.load_lookups()
    saved = lookups["names"].get(str(friend_id))
    if storage.entry_fresh(saved, "friend_names", now) and isinstance(saved.get("name"), str):
        logs.RUN_LOG.note(f"friend {friend_id}: name from cache")
        return {"steamid": friend_id, "name": saved["name"]}
    try:
        players = api_get("ISteamUser/GetPlayerSummaries/v2/", key, steamids=friend_id).get("players", [])
    except logs.SteamError:
        return None
    if not isinstance(players,list) or not players or not isinstance(players[0],dict):
        return None
    name = players[0].get("personaname")
    if isinstance(name, str) and name:
        lookups["names"][str(friend_id)] = {"at": now, "name": name}
        storage.save_lookups(lookups)
    return {"steamid": friend_id, "name": name or "a mysterious stranger"}


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
