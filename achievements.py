"""The achievement cache and the per-game achievement counting (slow, so it is cached for 30
days per game and failing games are tracked)."""

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

import logs
import steam_api
import storage


ACHIEVEMENT_WORKERS = 8       # how many games are asked about at the same time
CACHE_VERSION = 1
GIVE_UP_AFTER_FAILURES = 3    # a game whose achievement check failed this many visits in a row
                              # is no longer asked about ("refresh <profile>" tries it again)
OUTAGE_MIN_GAMES = 12         # if this many or more games are asked in one scan and ALL fail,
                              # it looks like a Steam outage, so those failures are not counted
RECHECK_AFTER_DAYS = 30       # re-check a saved game after this long even if nothing changed


# ---------------------------------------------------------------------------
# Achievements and the achievement cache
#
# Steam can only report achievements one game at a time, which is slow and eats API
# calls. So every game's result is saved in cache/<SteamID>.json next to this script.
# On the next visit Steam is asked about a game again only when something may have
# changed:
#   * the game is not in the cache yet (e.g. you started a new game),
#   * its playtime or its "last played" time changed (achievements are unlocked by
#     playing, so a game you did not touch cannot have new ones),
#   * or the saved entry is older than RECHECK_AFTER_DAYS, a safety net for the rare
#     unlock that does not show up in playtime (achievement tools, offline syncing).
# Typing "refresh <profile>" (or starting the program with --refresh) ignores the
# cache and checks every game again. Deleting the cache folder is always safe.
# ---------------------------------------------------------------------------
BLOCKED = "blocked"   # Steam refuses to show this profile's achievements
FAILED = "failed"     # the lookup did not work (network, Steam hiccup): result unknown


def cache_path(steamid):
    return os.path.join(storage.CACHE_DIR, f"{steamid}.json")


def load_cache(steamid):
    """Returns (cache, found). A missing, damaged or outdated file just counts as no cache."""
    empty = {"version": CACHE_VERSION, "steamid": str(steamid), "last_total": None, "games": {},
             "failed": {}}
    try:
        with open(cache_path(steamid), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return empty, False
    if (not isinstance(data, dict) or data.get("version") != CACHE_VERSION
            or data.get("steamid") != str(steamid) or not isinstance(data.get("games"), dict)):
        return empty, False
    if not isinstance(data.get("last_total"), int):
        data["last_total"] = None
    failed = data.get("failed")
    data["failed"] = {k: v for k, v in failed.items() if isinstance(v, dict) and
                      isinstance(v.get("tries"), int) and not isinstance(v.get("tries"), bool)
                      } if isinstance(failed, dict) else {}
    return data, True


def save_cache(cache):
    return storage.write_json(cache_path(cache["steamid"]), cache)


def entry_is_current(entry, game, now):
    """True if the saved result for this game can be trusted without asking Steam again."""
    if not isinstance(entry, dict) or not isinstance(entry.get("unlocked"), int):
        return False
    if entry.get("playtime") != game.get("playtime_forever", 0):
        return False
    if entry.get("last_played") != game.get("rtime_last_played", 0):
        return False
    checked = entry.get("checked_at")
    if not isinstance(checked, (int, float)):
        return False
    if RECHECK_AFTER_DAYS and now - checked > RECHECK_AFTER_DAYS * 86400:
        return False
    return True


def apply_results(cache, games, results, now):
    """Stores every real number from this round in the cache (never BLOCKED or FAILED).
    Returns True if anything was written."""
    changed = False
    for g in games:
        k = str(g["appid"])
        result = results.get(k)
        if isinstance(result, int):
            cache["games"][k] = {"unlocked": result, "playtime": g.get("playtime_forever", 0),
                                 "last_played": g.get("rtime_last_played", 0), "checked_at": now}
            changed = True
    return changed


def game_label(g):
    """'Half-Life (app 70)' for the log, or just 'app 70' when the name is not known."""
    name = g.get("name")
    return f"{name} (app {g['appid']})" if name else f"app {g['appid']}"


def given_up(cache, appid):
    """True once a game's achievement check has failed GIVE_UP_AFTER_FAILURES visits."""
    entry = cache["failed"].get(str(appid))
    return bool(entry) and entry["tries"] >= GIVE_UP_AFTER_FAILURES


def track_failures(cache, todo, results, now):
    """Counts, per game, the visits in which its achievement check failed (a success wipes
    the count). Returns {'failed': [(game, tries)], 'gave_up': [game], 'outage': bool,
    'changed': bool}. Only FAILED counts: a private profile (BLOCKED) says nothing about the
    game. If every game asked in a big scan failed, it was Steam that was down, not the games,
    so nothing is counted against them."""
    asked = [g for g in todo if str(g["appid"]) in results]
    failed = [g for g in asked if results[str(g["appid"])] == FAILED]
    outage = len(asked) >= OUTAGE_MIN_GAMES and len(failed) == len(asked)
    out = {"failed": [], "gave_up": [], "outage": outage, "changed": False}
    for g in asked:
        k = str(g["appid"])
        result = results[k]
        if isinstance(result, int):
            if cache["failed"].pop(k, None) is not None:
                out["changed"] = True
        elif result == FAILED:
            tries = cache["failed"].get(k, {}).get("tries", 0)
            if not outage:
                tries += 1
                cache["failed"][k] = {"tries": tries, "last": now}
                out["changed"] = True
                if tries >= GIVE_UP_AFTER_FAILURES:
                    out["gave_up"].append(g)
            out["failed"].append((g, tries))
    return out


def achievements_for_game(appid, steamid, key):
    """Unlocked achievements for one game: a number, BLOCKED (private) or FAILED (unknown).
    A game that has no achievements is simply 0."""
    for attempt in range(3):
        try:
            r = steam_api.steam_get("ISteamUserStats/GetPlayerAchievements/v1/",
                                    {"key": key, "steamid": steamid, "appid": appid})
        except requests.RequestException:
            time.sleep(1 + attempt)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(1 + attempt)          # Steam wants us to slow down; try again
            continue
        if r.status_code == 403:
            return BLOCKED                   # achievements are private
        if r.status_code == 400:
            return 0                         # Steam's answer for "this game has no achievements"
        if r.status_code != 200:
            return FAILED
        try:
            stats = r.json().get("playerstats", {})
        except (ValueError, AttributeError):
            return FAILED
        if "not public" in str(stats.get("error", "")).lower():
            return BLOCKED
        return sum(1 for a in stats.get("achievements", []) if a.get("achieved") == 1)
    return FAILED


class PrivacyWatch:
    """Spots a private profile early. Steam says 'not public' for every game, so after a few
    such answers and no good ones there is no point asking about the remaining games."""
    def __init__(self):
        self.lock = threading.Lock()
        self.blocked = 0
        self.good = 0

    def record(self, result):
        with self.lock:
            if result == BLOCKED:
                self.blocked += 1
            elif isinstance(result, int):
                self.good += 1

    def private(self):
        with self.lock:
            return self.blocked >= 3 and self.good == 0


def lookup_game(appid, steamid, key, watch):
    if watch.private():
        return BLOCKED
    result = achievements_for_game(appid, steamid, key)
    watch.record(result)
    return result


# The window version of the program sets this to a function(done, total) so it can draw a
# progress bar; the terminal version leaves it None and prints "Counting achievements...".
PROGRESS_HOOK = None


def report_progress(done, total):
    if PROGRESS_HOOK is not None:
        PROGRESS_HOOK(done, total)
    else:
        print(f"\r  Counting achievements... {done}/{total} games", end="", flush=True)


def count_achievements(steamid, key, games, refresh=False):
    """Total unlocked achievements over every game you have played (free ones too), using
    the cache wherever the saved result is still valid. Returns a dict:
      total, hidden (Steam hides them and nothing is known), reused (games read from the
      cache), queried (games asked about on Steam), failed / blocked (games that could not
      be checked this time), new (achievements gained since the last complete visit, or
      None on a first visit), had_cache, refreshed, games."""
    cache, had_cache = load_cache(steamid)
    old = cache["games"]
    now = time.time()
    played = [g for g in games if g.get("playtime_forever", 0) > 0]
    dirty = False
    if refresh and cache["failed"]:
        cache["failed"] = {}         # a refresh gives every game a fresh start
        dirty = True

    counts = {}                      # appid -> unlocked achievements
    todo, skipped = [], []
    for g in played:
        k = str(g["appid"])
        if not refresh and entry_is_current(old.get(k), g, now):
            counts[k] = old[k]["unlocked"]
        elif given_up(cache, k):     # failed too many visits in a row: not asked any more
            skipped.append(g)
            prior = old.get(k)
            counts[k] = prior["unlocked"] if isinstance(prior, dict) and isinstance(
                prior.get("unlocked"), int) else 0
        else:
            todo.append(g)
    stats = {"total": 0, "hidden": False, "reused": len(played) - len(todo) - len(skipped),
             "queried": len(todo), "failed": 0, "blocked": 0, "new": None, "had_cache": had_cache,
             "refreshed": bool(refresh), "games": len(played), "skipped": len(skipped),
             "skipped_games": skipped, "failed_games": [], "gave_up": [], "outage": False}

    results = {}                     # appid -> number, BLOCKED or FAILED
    if todo:
        watch = PrivacyWatch()
        pool = ThreadPoolExecutor(max_workers=ACHIEVEMENT_WORKERS)
        futures = {pool.submit(lookup_game, g["appid"], steamid, key, watch): g for g in todo}
        try:
            for f in as_completed(futures):
                results[str(futures[f]["appid"])] = f.result()
                report_progress(len(results), len(todo))
        except BaseException:
            # Interrupted (Ctrl+C): keep every game that finished, so the next run only has
            # to do the rest. last_total stays as it was, because the scan is incomplete.
            for f, g in futures.items():
                if f.done() and not f.cancelled() and f.exception() is None:
                    results.setdefault(str(g["appid"]), f.result())
            try:
                pool.shutdown(wait=False, cancel_futures=True)
            except TypeError:                # Python older than 3.9
                pool.shutdown(wait=False)
            tracked = track_failures(cache, todo, results, now)
            if apply_results(cache, todo, results, now) or tracked["changed"] or dirty:
                save_cache(cache)
            if PROGRESS_HOOK is None:
                print()
            raise
        pool.shutdown()
        if PROGRESS_HOOK is None:
            print("\r" + " " * 48 + "\r", end="", flush=True)
        else:
            PROGRESS_HOOK(len(todo), len(todo))

    for g in todo:
        k = str(g["appid"])
        result = results.get(k, FAILED)
        if isinstance(result, int):
            counts[k] = result
        else:                        # unknown right now: use the last known value, never a guess
            stats["blocked" if result == BLOCKED else "failed"] += 1
            prior = old.get(k)
            counts[k] = prior["unlocked"] if isinstance(prior, dict) and isinstance(
                prior.get("unlocked"), int) else 0

    total = sum(counts.values())
    stats["total"] = total
    stats["hidden"] = bool(todo) and stats["blocked"] == len(todo) and total == 0

    tracked = track_failures(cache, todo, results, now)
    stats["failed_games"], stats["gave_up"] = tracked["failed"], tracked["gave_up"]
    stats["outage"] = tracked["outage"]
    dirty = apply_results(cache, todo, results, now) or tracked["changed"] or dirty
    if stats["failed"] == 0 and stats["blocked"] == 0:   # only a complete scan sets the baseline
        if cache["last_total"] is not None:
            stats["new"] = total - cache["last_total"]
        if cache["last_total"] != total:
            cache["last_total"] = total
            dirty = True
    if dirty:
        save_cache(cache)
    return stats


def game_list(games, limit=15):
    """'A (app 1), B (app 2) and 3 more' for the log."""
    labels = [game_label(g) for g in games]
    if len(labels) > limit:
        labels = labels[:limit] + [f"and {len(labels) - limit} more"]
    return ", ".join(labels)


def log_achievement_failures(ach):
    """Writes into the log which games failed their achievement check, and which were given up."""
    if ach["failed_games"]:
        what = ", ".join(f"{game_label(g)} [try {t} of {GIVE_UP_AFTER_FAILURES}]"
                         for g, t in ach["failed_games"][:15])
        more = len(ach["failed_games"]) - 15
        logs.RUN_LOG.note(f"achievement check FAILED for {len(ach['failed_games'])} game(s): {what}"
                          f"{f', and {more} more' if more > 0 else ''}")
        if ach["outage"]:
            logs.RUN_LOG.note("every game asked failed, so this looks like a Steam outage: "
                              "these failures were NOT counted against the games")
    if ach["gave_up"]:
        logs.RUN_LOG.note(f"achievement check GAVE UP on {len(ach['gave_up'])} game(s) after "
                          f"{GIVE_UP_AFTER_FAILURES} failed tries, they will not be asked again "
                          f"(use 'refresh <profile>' to retry): {game_list(ach['gave_up'])}")
    if ach["skipped_games"]:
        logs.RUN_LOG.note(f"achievement check SKIPPED {len(ach['skipped_games'])} game(s) that already "
                          f"failed {GIVE_UP_AFTER_FAILURES} times: {game_list(ach['skipped_games'])}")
