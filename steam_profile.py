"""Assembling a profile from Steam: which saved parts are still fresh (REFRESH_HOURS) and which
have to be fetched again."""

import time

import achievements
import logs
import steam_api
import storage


def fetch_profile(steamid, key, refresh=False):
    now = time.time()
    pc = storage.load_profile_cache(steamid)
    source = {}                              # section -> "cache (20m old)" or "Steam", for the log
    changed = False

    def saved(name):
        """The saved section if it can be used, else None."""
        if not refresh and storage.section_fresh(pc, name, now):
            source[name] = f"cache ({storage.ago(now - pc['sections'][name]['at'])} old)"
            return pc["sections"][name]["value"]
        return None

    def keep(name, value):
        nonlocal changed
        pc["sections"][name] = {"at": now, "value": value}
        source[name] = "Steam"
        changed = True

    summary = saved("summary")
    if summary is None:
        resp = steam_api.api_get("ISteamUser/GetPlayerSummaries/v2/", key, steamids=steamid)
        players = resp.get("players", [])
        if not players:
            raise logs.SteamError("No Steam profile exists with that ID.")
        player = players[0]
        if player.get("communityvisibilitystate") != 3:
            raise logs.SteamError("This profile is private. Set the profile and 'Game details' to "
                                  "Public in Steam > Edit Profile > Privacy Settings, then try again.")
        created = player.get("timecreated")  # Unix time the account was made (public profiles)
        summary = {"name": player.get("personaname", "Unknown"),
                   "created": created if isinstance(created, int) and created > 0 else None}
        keep("summary", summary)

    level = saved("level")
    if level is None:
        level_resp = steam_api.api_get("IPlayerService/GetSteamLevel/v1/", key, steamid=steamid)
        level = {"level": int(level_resp.get("player_level", 0))}
        keep("level", level)

    games = saved("games")
    if games is None:
        # By default Steam leaves free-to-play games out of this list, so this is the
        # paid-games count (promo games that were claimed for free can still slip in).
        paid_resp = steam_api.api_get("IPlayerService/GetOwnedGames/v1/", key, steamid=steamid,
                                      include_appinfo=1)
        if "game_count" not in paid_resp:
            raise logs.SteamError("Game details are hidden. Set 'Game details' to Public in your "
                                  "Steam privacy settings (and untick 'Always keep my total playtime private').")
        # The most-played game is looked up among ALL games, free-to-play included,
        # so a cultivator can still be named after your Dota 2 / CS2 habit.
        all_resp = steam_api.api_get("IPlayerService/GetOwnedGames/v1/", key, steamid=steamid,
                                     include_appinfo=1, include_played_free_games=1)
        owned = all_resp.get("games", [])
        top = max(owned, key=lambda g: g.get("playtime_forever", 0), default=None)
        games = {
            "game_count": int(paid_resp.get("game_count", 0)),
            "top_game": top.get("name", "Unknown Game") if top else None,
            "top_hours": (top.get("playtime_forever", 0) / 60) if top else 0.0,
            "total_hours": sum(g.get("playtime_forever", 0) for g in owned) / 60,
            # only the games that were played matter for achievements: [appid, minutes, last played]
            "played": [[g["appid"], g.get("playtime_forever", 0), g.get("rtime_last_played", 0)]
                       for g in owned if g.get("playtime_forever", 0) > 0],
            # names of those games, only used to say which game is meant in the log
            "names": {str(g["appid"]): g["name"] for g in owned
                      if g.get("playtime_forever", 0) > 0 and isinstance(g.get("name"), str)},
            "owned_total": len(owned),
        }
        keep("games", games)
    if changed:                              # saved now, so a Ctrl+C during the long
        storage.save_profile_cache(pc)               # achievement scan does not lose these answers
        changed = False

    played = []
    names = games.get("names") if isinstance(games.get("names"), dict) else {}
    for row in games["played"]:
        if (isinstance(row, list) and len(row) == 3 and all(isinstance(v, storage._NUM) for v in row)):
            game = {"appid": int(row[0]), "playtime_forever": row[1], "rtime_last_played": row[2]}
            name = names.get(str(int(row[0])))
            if isinstance(name, str):
                game["name"] = name
            played.append(game)
    ach = achievements.count_achievements(steamid, key, played, refresh)

    # Badges (they feed the reputation system). Steam level is built purely from badge
    # XP, so a level above 0 with zero badges means Steam is not showing us the badges.
    badges_saved = saved("badges")
    if badges_saved is None:
        try:
            badge_resp = steam_api.api_get("IPlayerService/GetBadges/v1/", key, steamid=steamid)
        except logs.SteamError:
            badge_resp = None                # not saved: a failed answer is never kept
        if badge_resp is not None:
            badges_saved = {"count": len(badge_resp.get("badges", []))}
            keep("badges", badges_saved)
            storage.save_profile_cache(pc)
    badges = badges_saved["count"] if badges_saved else 0
    badges_hidden = badges == 0 and level["level"] > 0

    logs.RUN_LOG.note(f"profile {steamid}: {summary['name']}, "
                      f"{games.get('owned_total', len(games['played']))} games owned incl. free, "
                      f"{badges} badges")
    logs.RUN_LOG.note("data from: " + ", ".join(f"{n} {source.get(n, 'Steam (no answer)')}"
                                                for n in ("summary", "level", "games", "badges")))
    logs.RUN_LOG.note(f"achievements: {ach['total']} over {ach['games']} played games "
                      f"(asked Steam about {ach['queried']}, read {ach['reused']} from cache, "
                      f"{ach['failed']} failed, {ach['blocked']} blocked, {ach['skipped']} skipped"
                      f"{', refresh forced' if ach['refreshed'] else ''})")
    achievements.log_achievement_failures(ach)
    return {
        "name": summary["name"],
        "account_created": summary["created"],
        "level": level["level"],
        "game_count": games["game_count"],
        "top_game": games["top_game"],
        "top_hours": games["top_hours"],
        "total_hours": games["total_hours"],
        "achievements": ach["total"],
        "achievements_hidden": ach["hidden"],
        "achievements_new": ach["new"],      # gained since the last complete visit, or None
        "ach_stats": ach,
        "badges": badges,
        "badges_hidden": badges_hidden,
    }


def get_info(steamid, key, profiles, refresh=False):
    """Steam data for a profile. What is still fresh in the profile cache is not asked again."""
    profiles[steamid] = fetch_profile(steamid, key, refresh)
    return profiles[steamid]
