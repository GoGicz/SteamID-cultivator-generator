#!/usr/bin/env python3
"""
Steam Cultivator Generator
--------------------------
Enter a Steam profile and get a cultivation-novel style character whose
power depends on your Steam level, number of paid games and hours in your top game.
It also picks one of your Steam friends at random and tells a short story about
the two of your cultivators meeting.
Every cultivator rolls a random talent (from Poor Martial Body up to Reincarnation
of the Dao). Talent ignores your Steam stats completely, adds power, and sets the
chance of dying in battle (8% for a regular body, 15% for a poor one, and lower the
better the talent). Every cultivator also has a birth year. Talent and fate are
fixed by your SteamID, so the same profile always gets the same result. Rarely, the
killer is one of your own Steam friends.
Every unlocked Steam achievement counts as one completed sect mission, and every
mission pays 5 sect points. Steam can only be asked about achievements one game at
a time, so the first lookup of a big library takes a little while. The results are
saved in a "cache" folder next to this file, so later runs only ask Steam about games
whose playtime changed (or new ones) and report how many achievements you gained since
your last visit. Everything else Steam tells us about a profile is saved there too, each
kind with its own refresh time: the friends list every hour, the display name and account
age every 6 hours, games, level and badges every 12 hours, a friend's name every day, a
custom profile name every 7 days, and achievements (per game) every 30 days or as soon as
a game's playtime changes. A profile looked up again 20 minutes later needs no Steam calls
at all. The times are in REFRESH_HOURS near the top. Type "refresh <profile>" (or run
with --refresh) to ignore all saved data and ask Steam for everything again.
Every cultivator walks the Righteous Path (70% by default, +5 reputation) or the Demonic
Path (+20 power), by luck from the SteamID. Type "mocb" (or "mocb <profile1> <profile2>")
to make two cultivators duel: the program works out who is most likely to win and tells a
short story of the battle. Affinity matters in duels: an element that is strong against
the other's gets +3% win chance (every element beats two and loses to two), and when one
fighter's power towers over the other's, the story shows the stronger one's arrogance.
The age of your Steam account sets the age of your cultivator: a brand-new account gives
a youth, and an account of 20 years or more a cultivator close to the end of their
lifespan (a doomed cultivator dies at that age). Every command is written to a log file
in the "Logs" folder next to this file (one file per day), with what was run and how
many Steam API calls it used. The API key is never written to the log.
Besides the unique signature technique (named after your most played game), every
cultivator has an arsenal of four more moves, fixed by the SteamID: two attacks of their
element, one attack of their path and one defense. Duels use all of them.
If the achievement check keeps failing for the same game (3 visits in a row), that game
is not asked about any more, and the log says which games failed and which were given
up. "refresh <profile>" tries them again.
Treasures are an inventory saved in the profile's JSON file in the "cache" folder
(cache/<SteamID>.profile.json). A new profile starts with the one treasure its SteamID
gives it. In a duel, a Demonic winner has a 25% chance to steal the loser's prized (best) treasure, which is
removed from the loser's file and added to the winner's; if the loser owns nothing, the
story says so. Every winner also has a 5% chance of finding a random new treasure. The
changes show on the next profile load. "refresh" never touches the inventory, but deleting
the cache folder (or a profile's JSON file) resets it to the starting treasure.
Duels also change reputation, by realm only: when the winner is in a lower realm than the
loser, the winner gains 25 reputation per realm of difference and the loser loses 20 per
realm (only 10 per realm if both are Righteous). Same realm, or the stronger realm winning,
changes nothing. The points are saved in the profile's JSON file and shown as "Duels" in
the card's fame boosts; reputation never goes below 0. The dead cannot duel: a cultivator
who died in their fate cannot be used in "mocb".
Type "pavilion" to open the sect's Martial Pavilion for the cultivator you looked up
last (looking up another profile makes that one the latest; "mocb" does not). Pills,
weapons, treasures and the Spatial Escape Talisman cost sect points and are saved in that
cultivator's JSON file. A talisman stops one Demonic theft, then is used up. The dead cannot
shop, and "pavilion" is refused until a cultivator has been looked up. Reputation ranks
now rise gradually: the first ranks come quickly, the later ones need far more points.
Type "breakthrough" when the power score reaches the next realm: the chance depends on the
realm, the personality, the talent and an optional Heaven-Defying Breakthrough Pill (+30%,
5,000 sect points). Type "history" to see recent duels, purchases and breakthroughs. Type "sell" to sell treasures
for half their value in sect points, and "adventure" for a random event (a dead cultivator
gets a 1% rebirth roll instead, once every 24 hours, into a brand-new random body).
A failed breakthrough costs lifespan (5 years in the lowest realm, 250 in Void Refinement, up
to 480): if the lifespan falls to the cultivator's age, they die. Immortals live 60,000 to
90,000 years, and their age is a share of that. Every cultivator is male or female by SteamID.
Level, paid games, hours in the top game and badges are remembered at their highest ever in
the profile's JSON file: a dip in Steam's data or a refresh never takes power or reputation
away, and only genuinely new levels, games, hours or badges add to it.
Your Steam badges build your reputation, from "Unknown Nobody" up to "Universal
Legend". Personalities, earned from your friends, badges, achievements and games,
add reputation (some only by chance) and a few also change power and death risk,
for example "Fearless" (more than 100 badges): +50 power but +0.8% death risk.

Setup:
    pip install requests
    Get a free API key: https://steamcommunity.com/dev/apikey
    Set it as an environment variable (recommended):
        Windows (cmd):   set STEAM_API_KEY=yourkey
        Linux / macOS:   export STEAM_API_KEY=yourkey
    ...or just paste it when the program asks.

Run:
    python steam_cultivator.py

Your Steam profile's "Game details" must be set to Public,
otherwise Steam will not give out the data.
The friend story needs a public "Friends List" too; if it is private (or you
have no friends) the story is simply skipped.

Code layout (every .py file must sit in the same folder as this one):
    steam_cultivator.py      this file: the command line (command routing and prompts)
    steam_cultivator_gui.py  the window version (needs customtkinter)
    logs.py                  SteamError, the run log written to the Logs folder
    steam_api.py             Steam Web API requests, profile URL parsing, friends
    storage.py               the saved JSON per profile (cache), history, reputation
    achievements.py          achievement counting and its cache
    steam_profile.py         assembling a profile from Steam and the saved data
    gamedata.py              realms, talents, paths, treasures, pavilion goods...
    gametext.py              every story / battle / adventure text template
    generator.py             building the cultivator from the Steam data
    combat.py                duels (mocb), loot, theft, reputation from duels
    pavilion_shop.py         buying goods, selling treasures
    progress.py              breakthrough, adventure, rebirth
    display.py               printing to the terminal
"""

import os
import sys

import combat
import display
import gamedata
import generator
import logs
import pavilion_shop
import progress
import steam_api
import storage


def run_sell(args, key, profiles, session):
    """The "sell" command: 'sell' lists the treasures and asks which, 'sell 2' sells number 2."""
    if len(args) > 1:
        raise logs.SteamError("sell takes one optional treasure number, for example: sell 2")
    steamid, c = pavilion_shop.pavilion_target(key, profiles, session, "sell")
    rows = pavilion_shop.sell_rows(c)
    if not args:
        line = "=" * 64
        print("\n" + line)
        display.wrap_words("  ", f"SELL TREASURES  -  {c['name']} ({c['sect_points']:,} sect points)")
        print(line)
        if not rows:
            print("  Nothing to sell: this cultivator owns no treasure.\n")
            return
        for r in rows:
            display.wrap_words(f"  {r['number']:>2}. ", f"{r['name']} - the pavilion pays {r['price']:,} "
                                                f"(worth {r['value']:,})")
        print(line)
        choice = input("  Sell which? (number, blank to leave): ").strip()
        if not choice:
            print("  Nothing sold.\n")
            return
    else:
        choice = args[0]
    row = pavilion_shop.sell_treasure(steamid, c, choice)
    display.wrap_words("  ", f"{c['name']} sold {row['name']} for {row['price']:,} sect points "
                     f"(half of its {row['value']:,} value).")
    print(f"  Sect points now: {c['sect_points']:,}\n")


def run_pavilion(args, key, profiles, session):
    """The "pavilion" command: 'pavilion' lists the goods and asks what to buy, 'pavilion 7'
    buys item 7 straight away."""
    if len(args) > 1:
        raise logs.SteamError("pavilion takes one optional item number, for example: pavilion 3")
    steamid, c = pavilion_shop.pavilion_target(key, profiles, session)
    if args:
        choice = args[0]
    else:
        display.print_pavilion(c)
        choice = input("  Buy which item? (number, blank to leave): ").strip()
        if not choice:
            print("  You leave the pavilion without buying anything.\n")
            return
    item = pavilion_shop.buy_pavilion_item(steamid, c, choice)
    line = "=" * 64
    print("\n" + line)
    display.wrap_words("  ", f"{c['name']} bought {item['name']} for {item['price']:,} sect points.")
    if item["kind"] == "Treasure":
        display.wrap_words("  ", "It was added to the treasure inventory (a treasure can be stolen by "
                         "a Demonic winner).")
    elif item["id"] == gamedata.TALISMAN_ID:
        display.wrap_words("  ", "It will save the owner's treasure from the next Demonic winner who "
                         "tries to steal it.")
    else:
        display.wrap_words("  ", "It was saved in the cultivator's JSON file.")
    print(f"  Sect points left: {c['sect_points']:,}")
    display.wrap_words("  Pavilion goods: ", pavilion_shop.pavilion_goods_text(c))
    display.wrap_words("  Treasures     : ", generator.describe_treasures(generator.treasures_of(c)) or "none")
    print(line + "\n")


def run_adventure(args, key, profiles, session):
    """The "adventure" command for the latest cultivator."""
    if args:
        raise logs.SteamError("adventure takes no arguments: look up a profile, then type it.")
    steamid = session.get("latest")
    if not steamid:
        raise logs.SteamError("No cultivator has been selected yet. Look up a Steam profile first, "
                              "then type 'adventure'.")
    info, friend_ids, _, c = generator.build_cultivator(steamid, key, profiles)
    r = progress.perform_adventure(steamid, c, info, friend_ids, key)
    line = "=" * 64
    print("\n" + line)
    display.wrap_words("  ", f"{r['title'].upper()}  -  {c['name']}")
    print(line)
    display.wrap_print(r["text"])
    print(line + "\n")


def run_breakthrough(args, key, profiles, session):
    """The "breakthrough" command for the latest cultivator: shows the chance and asks."""
    if args:
        raise logs.SteamError("breakthrough takes no arguments: look up a profile, then type it.")
    steamid, c = progress.breakthrough_target(key, profiles, session)
    st = progress.breakthrough_status(c)
    if not st["can"]:
        raise logs.SteamError(st["reason"])
    line = "=" * 64
    print("\n" + line)
    display.wrap_words("  ", f"BREAKTHROUGH  -  {c['name']}: {st['current']} to {st['next']}")
    print(line)
    use_pill = False
    for ln in progress.breakthrough_lines(st["chance"]):
        display.wrap_words("  ", ln)
    display.wrap_words("  ", progress.breakthrough_risk_text(st))
    if st["pills"]:
        pill = gamedata.PAVILION_BY_ID[progress.BREAKTHROUGH_PILL_ID]["name"]
        answer = input(f"  Swallow a {pill} (+{progress.BREAKTHROUGH_PILL_BONUS * 100:g}%, you own "
                       f"{st['pills']})? [y/N]: ").strip().lower()
        use_pill = answer in ("y", "yes")
        if use_pill:
            for ln in progress.breakthrough_lines(st["chance_pill"]):
                display.wrap_words("  ", ln)
    chance = (st["chance_pill"] if use_pill else st["chance"])["total"]
    if input(f"  Attempt the breakthrough at {chance * 100:g}%? [y/N]: ").strip().lower() \
            not in ("y", "yes"):
        print("  The cultivator decides to wait.\n")
        return
    r = progress.attempt_breakthrough(steamid, c, use_pill)
    display.wrap_words("  ", progress.breakthrough_result_text(c["name"], r))
    print(line + "\n")


def run_history(args, key, profiles, session):
    """The "history" command: what the latest cultivator did recently."""
    steamid, c = progress.breakthrough_target(key, profiles, session)
    entries = storage.history_entries(steamid, 20)
    print(f"\n  Recent history of {c['name']}")
    print("  " + "-" * 62)
    if not entries:
        print("  Nothing yet: no duels, purchases or breakthroughs.")
    for e in entries:
        display.wrap_words(f"  {logs.stamp(e['at'])[:16]}  ", e["text"])
    print()


def run_battle(args, key, profiles):
    """The "mocb" command. Profiles come from the command line ('mocb <p1> <p2>') or are
    asked for one by one; a blank answer cancels."""
    ids = []
    for n, ordinal in enumerate(("First", "Second")):
        if n < len(args):
            text = args[n]
        else:
            text = input(f"  {ordinal} profile (URL, name or SteamID64, blank to cancel): ").strip()
        if not text:
            print("  Duel cancelled.\n")
            return
        ids.append(steam_api.resolve_steamid(text, key))
    duel = combat.perform_battle(ids, key, profiles)
    display.print_battle(duel["a"], duel["b"], duel["info_a"], duel["info_b"], duel["result"],
                         duel["story"], duel["loot"], duel["change"])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    key = os.environ.get("STEAM_API_KEY") or input("Steam API key: ").strip()
    if not key:
        sys.exit("An API key is required (https://steamcommunity.com/dev/apikey).")

    print("Welcome, seeker of the Dao. Press Ctrl+C to leave.")
    print("Tip: type 'mocb' to make two profiles duel (or 'mocb <profile1> <profile2>').")
    print("Tip: type 'pavilion' to spend the sect points of the last cultivator you looked up.")
    print("Tip: type 'breakthrough' to try for the next realm, 'history' to see what they did.")
    print("Tip: type 'adventure' to send the last cultivator out, 'sell' to sell treasures.")
    print("Tip: type 'refresh <profile>' to ignore all saved Steam data.\n")
    refresh_first = "--refresh" in sys.argv[1:]   # refresh each profile's first lookup this run
    profiles = {}
    session = {}                                 # the latest cultivator looked up (for 'pavilion')
    logs.RUN_LOG.secret = key
    while True:
        try:
            text = input("Steam profile URL, custom name, or SteamID64: ").strip()
            if not text:
                continue
            logs.RUN_LOG.begin(describe_command(text))
            status = "ok"
            try:
                run_command(text, key, profiles, refresh_first, session)
            except logs.SteamError as e:
                status = f"error: {e}"
                print(f"\n  ! {e}\n")
            except BaseException as e:           # Ctrl+C or end of input in the middle of a command
                logs.RUN_LOG.finish("interrupted" if isinstance(e, (KeyboardInterrupt, EOFError))
                                    else f"crashed: {type(e).__name__}: {e}")
                raise
            logs.RUN_LOG.finish(status)
        except (KeyboardInterrupt, EOFError):
            print("\nMay your Dao be eternal. Farewell.")
            break
    logs.RUN_LOG.end_session()


def describe_command(text):
    """What the log says was run, e.g. 'mocb a b', 'refresh lookup of x' or 'lookup of x'."""
    parts = text.split()
    if parts[0].lower() in ("mocb", "pavilion", "breakthrough", "history", "adventure", "sell"):
        return parts[0].lower() + (" " + " ".join(parts[1:]) if parts[1:] else "")
    if text.lower().startswith("refresh "):
        return f"refresh lookup of {text[len('refresh '):].strip()}"
    return f"lookup of {text}"


def run_command(text, key, profiles, refresh_first, session=None):
    """One line typed by the user: a lookup, a 'refresh <profile>' lookup, 'mocb' or
    'pavilion'. session remembers the latest cultivator you looked up (for the pavilion)."""
    session = session if session is not None else {}
    parts = text.split()
    if parts[0].lower() == "pavilion":
        run_pavilion(parts[1:], key, profiles, session)
        return
    if parts[0].lower() == "breakthrough":
        run_breakthrough(parts[1:], key, profiles, session)
        return
    if parts[0].lower() == "adventure":
        run_adventure(parts[1:], key, profiles, session)
        return
    if parts[0].lower() == "sell":
        run_sell(parts[1:], key, profiles, session)
        return
    if parts[0].lower() == "history":
        run_history(parts[1:], key, profiles, session)
        return
    if parts[0].lower() == "mocb":
        if len(parts) > 3:
            raise logs.SteamError("mocb takes two profiles, for example: mocb <profile1> <profile2>")
        run_battle(parts[1:], key, profiles)
        return
    refresh = False
    if text.lower().startswith("refresh "):
        refresh, text = True, text[len("refresh "):].strip()
    if not text:
        return
    steamid = steam_api.resolve_steamid(text, key, refresh or (refresh_first and not profiles))
    if refresh_first and steamid not in profiles:
        refresh = True
    info, friend_ids, note, cultivator = generator.build_cultivator(steamid, key, profiles, refresh)
    session["latest"] = steamid              # the pavilion serves this cultivator from now on
    friend = steam_api.resolve_friend(cultivator, friend_ids, key)
    display.print_cultivator(cultivator, info)
    if friend:
        display.print_story(generator.generate_story(cultivator, info, friend), friend)
    elif note:
        print(f"  ({note})\n")
    if cultivator["death"]:
        display.print_death(cultivator, info, friend)


if __name__ == "__main__":
    main()
