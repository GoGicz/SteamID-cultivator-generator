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


def steam_get(endpoint, params):
    """Makes one Steam request and counts it. Every request in the program goes through here."""
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
        raise logs.SteamError(f"Could not reach Steam: {e}")
    if r.status_code in (401, 403):
        raise logs.SteamError("Steam rejected the API key (check it is correct).")
    if r.status_code != 200:
        raise logs.SteamError(f"Steam returned HTTP {r.status_code}.")
    try:
        return r.json().get("response", {})
    except ValueError:
        raise logs.SteamError("Steam sent a response I could not read.")


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
        friends = r.json().get("friendslist", {}).get("friends", [])
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
    if not players:
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
