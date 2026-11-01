"""Terminal output: wrapping and the printing of cultivators, stories, the pavilion and
battles."""

import datetime

import combat
import gamedata
import generator
import pavilion_shop
import storage


def power_bar(idx):
    total = len(gamedata.REALMS)
    return "[" + "#" * (idx + 1) + "-" * (total - idx - 1) + f"] {idx + 1}/{total}"


def achievement_note(st):
    """One short line about where the achievement numbers came from."""
    if not st or st["hidden"] or st["games"] == 0:
        return None
    parts = []
    if st["refreshed"]:
        parts.append(f"full re-check of {st['queried']:,} games, cache updated")
    elif st["queried"] == 0:
        parts.append(f"all {st['reused']:,} games read from the cache, no Steam lookups needed")
    elif st["reused"] == 0:
        parts.append(f"{st['queried']:,} games checked with Steam and saved to the cache"
                     if not st["had_cache"] else f"{st['queried']:,} games checked with Steam")
    else:
        parts.append(f"{st['queried']:,} of {st['games']:,} games checked with Steam, "
                     f"{st['reused']:,} read from the cache")
    unknown = st["failed"] + st["blocked"]
    if unknown:
        parts.append(f"{unknown:,} could not be checked this time and will be retried next visit")
    return "; ".join(parts)


def personality_label(p):
    effects = []
    if p["power"]:
        effects.append(f"{p['power']:+d} power")
    if p["death"]:
        effects.append(f"{p['death'] * 100:+g}% death risk")
    return p["name"] + (f" ({', '.join(effects)})" if effects else "")


def print_cultivator(c, info):
    line = "=" * 64
    print("\n" + line)
    print(f"  {c['name']}  -  {c['title']} of the {c['sect']}")
    print(line)
    print(f"  Realm       : {c['realm']} ({c['realm_flavor']})")
    print(f"  Gender      : {c['gender'].capitalize()}")
    print(f"  Power       : {power_bar(c['realm_index'])}   (score {c['score']:,.0f})")
    t = c["talent"]
    print(f"  Talent      : {t['name']} (power {t['power']:+d})")
    if c["personalities"]:
        print("  Personality : " + ", ".join(personality_label(p) for p in c["personalities"]))
    else:
        print("  Personality : none (a quiet temperament)")
    print(f"  Path        : {generator.path_label(c['path'])}")
    rep = c["reputation"]
    print(f"  Reputation  : {rep['rank']} ({rep['points']:,} points)")
    if rep["bonuses"]:
        print("  Fame boosts : " + ", ".join(f"{n} {a:+d}" for n, a in rep["bonuses"]))
    print(f"  Death risk  : {c['death_chance'] * 100:g}%")
    print(f"  Affinity    : {c['element']}")
    print(f"  Matchups    : strong vs {', '.join(gamedata.ELEMENT_BEATS.get(c['element'], []))}; "
          f"weak vs {', '.join(combat.element_weak_to(c['element']))}")
    print(f"  Signature   : {c['technique']}")
    wrap_field("Arsenal", generator.arsenal_text(c))
    owned = generator.treasures_of(c)
    wrap_field("Treasures", generator.describe_treasures(owned) if owned else "none (robbed of everything)")
    events = [e for e in c.get("inventory_history", []) if e.get("type") != "start"]
    if events:
        wrap_words("  Recent      : ", storage.describe_event(events[-1]))
    if info["achievements_hidden"]:
        print("  Missions    : 0 (Steam is hiding your achievements)")
    else:
        n = c["missions"]
        print(f"  Missions    : {n:,} sect mission{'' if n == 1 else 's'} completed")
        new = info.get("achievements_new")
        if new and new > 0:
            print(f"  Since last  : +{new:,} new mission{'' if new == 1 else 's'} "
                  f"(+{new * gamedata.SECT_POINTS_PER_MISSION:,} sect points) since your last visit")
    print(f"  Sect points : {generator.sect_points_text(c)}")
    goods = generator.describe_goods(c.get("pavilion", {}).get("items", {}))
    if goods:
        wrap_field("Pavilion", goods)
    cut = " (cut short)" if c["death"] else ""
    lost = c.get("lifespan_lost", 0)
    print(f"  Lifespan    : {c['lifespan']:,} years{cut}"
          + (f" ({lost:,} lost to failed breakthroughs)" if lost else ""))
    print(f"  Born        : Year {c['birth_year']} of the Heavenly Calendar")
    if c.get("age") is not None:
        when = " at death" if c["death"] else ""
        yrs = c.get("account_years")
        src = f" ({yrs:.0f}-year-old account)" if yrs is not None else ""
        print(f"  Age         : {c['age']:,} years{when}{src}")
    if c["death"]:
        print(f"  Died        : Year {c['death']['year']} of the Heavenly Calendar "
              f"(aged {c['death']['age']:,})")
    else:
        print("  Status      : Alive and cultivating")
    if c["lightning"]:
        print(f"  Tribulations: survived {c['lightning']} heavenly lightning strikes")
    print(line)
    print("  Source stats from Steam:")
    if info.get("account_created") and c.get("account_years") is not None:
        year = datetime.datetime.fromtimestamp(info["account_created"], datetime.timezone.utc).year
        print(f"    Account age : {c['account_years']:.1f} years (created {year})")
    print(f"    Steam level : {info['level']}")
    print(f"    Paid games  : {info['game_count']:,}")
    print(f"    Achievements: {info['achievements']:,}")
    if info["badges_hidden"]:
        print("    Badges      : 0 (Steam is hiding your badges)")
    else:
        print(f"    Badges      : {info['badges']:,}")
    if info["top_game"]:
        print(f"    Most played : {info['top_game']} ({info['top_hours']:,.0f} h)")
    print(line)
    print()
    wrap_print(c["backstory"])
    print(line + "\n")


def print_items(head, items, width=64):
    """Prints 'head' + items separated by commas, wrapping between items (never inside a
    name) and lining the continuation up under the first item."""
    pad, line = " " * len(head), head
    for n, item in enumerate(items):
        piece = item + ("," if n < len(items) - 1 else "")
        if len(line) + len(piece) > width and line.strip() != head.strip():
            print(line.rstrip())
            line = pad
        line += piece + " "
    print(line.rstrip())


def wrap_words(head, text, width=64):
    """Word-wraps text after a label, lining the continuation lines up under the text."""
    pad, line = " " * len(head), head
    for word in text.split():
        if len(line) + len(word) > width and line.strip() != head.strip():
            print(line.rstrip())
            line = pad
        line += word + " "
    print(line.rstrip())


def wrap_field(label, text, width=64):
    print_items(f"  {label:<12}: ", text.split(", "), width)


def wrap_print(text, width=62):
    words, line = text.split(), ""
    for w in words:
        if len(line) + len(w) + 1 > width:
            print("  " + line)
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        print("  " + line)


def print_story(story, friend):
    print(f"  A tale from their life (Steam friend: {friend['name']})")
    print("  " + "-" * 62)
    wrap_print(story)
    print("=" * 64 + "\n")


def print_death(c, info, friend):
    label, text = generator.describe_death(c, info, friend)
    print("  The end of the road")
    print("  " + "-" * 62)
    print(f"  {'Cause   ' if c['death']['killer'] == 'lifespan' else 'Slain by'} : {label}")
    print()
    wrap_print(text)
    print("=" * 64 + "\n")


def print_pavilion(c):
    line = "=" * 64
    print("\n" + line)
    wrap_words("  ", f"SECT MARTIAL PAVILION  -  {c['name']} of the {c['sect']}")
    print(line)
    print(f"  Sect points available: {c['sect_points']:,}")
    kind_seen = None
    for n, item in enumerate(gamedata.PAVILION_ITEMS, 1):
        if item["kind"] != kind_seen:
            kind_seen = item["kind"]
            print(f"\n  {kind_seen.upper()}S")
        print(f"  {n:>2}. {item['name']}")
        wrap_words("      ", f"{item['price']:,} sect points - {pavilion_shop.pavilion_status(c, item)}")
        wrap_words("      ", item["blurb"])
    print(line)


def print_battle(a, b, info_a, info_b, result, story, loot=None, change=None):
    line = "=" * 64
    print("\n" + line)
    print("  MOCB  -  Clash of Cultivators")
    print(line)
    for tag, c, info, p in (("A", a, info_a, result["p_a"]), ("B", b, info_b, result["p_b"])):
        print(f"  [{tag}] {c['name']}  of the {c['sect']}")
        print(f"      Steam name : {info['name']}")
        print(f"      Realm      : {c['realm']}")
        print(f"      Power      : {c['score']:,.0f}")
        print(f"      Talent     : {c['talent']['name']}")
        print(f"      Path       : {c['path']['name']}")
        print(f"      Affinity   : {c['element']}")
        print(f"      Technique  : {c['technique']}")
        print_moves(c)
        print(f"      Win chance : {p * 100:.1f}%")
        print()
    edge = combat.element_edge(a["element"], b["element"])
    if edge:
        adv, dis = (a, b) if edge > 0 else (b, a)
        p_power_adv = result["p_power_a"] if adv is a else 1 - result["p_power_a"]
        wrap_print(f"Elements   : {adv['element']} is strong against {dis['element']}, so "
                   f"{adv['name']} gets +{combat.AFFINITY_BONUS * 100:g}% win chance "
                   f"(power alone: {p_power_adv * 100:.1f}%)")
    elif a["element"] == b["element"]:
        wrap_print(f"Elements   : both are {a['element']}, so neither has the advantage")
    else:
        wrap_print(f"Elements   : {a['element']} and {b['element']} are neutral against each other")
    tier, strong, weak, ratio = combat.power_gap(a, b)
    if tier:
        wrap_print(f"Power gap  : {tier} ({strong['score']:,.0f} vs {weak['score']:,.0f}), "
                   f"{strong['name']} is far ahead and knows it" if tier != "noticeable" else
                   f"Power gap  : noticeable ({strong['score']:,.0f} vs {weak['score']:,.0f}), "
                   f"{strong['name']} has the edge")
    if result["even"]:
        wrap_print("Prediction : a perfectly even match, too close to call")
    else:
        fav = result["favorite"]
        p_fav = result["p_a"] if fav is a else result["p_b"]
        wrap_print(f"Prediction : {fav['name']} is most likely to win ({p_fav * 100:.1f}%)")
    print(line)
    print()
    wrap_print(story)
    print()
    winner = result["winner"]
    if result["upset"]:
        wrap_print(f"Result : UPSET! {winner['name']} beat the odds "
                   f"({result['p_winner'] * 100:.1f}% chance) and wins the duel.")
    else:
        wrap_print(f"Result : {winner['name']} wins the duel.")
    if loot:
        loser = result["loser"]
        if loot["stolen"]:
            wrap_print(f"Loot : {winner['name']} stole {loot['stolen']} from {loser['name']}.")
        elif loot.get("blocked"):
            left = loot.get("talismans_left")
            wrap_print(f"Loot : {winner['name']} tried to rob {loser['name']}, but a Spatial "
                       f"Escape Talisman saved the treasure"
                       + (f" ({left} left)." if left is not None else "."))
        elif loot["nothing"]:
            wrap_print(f"Loot : {winner['name']} tried to rob {loser['name']}, but there was "
                       f"no treasure to steal.")
        elif loot.get("missed"):
            wrap_print(f"Loot : {winner['name']} could not get at {loser['name']}'s treasure "
                       f"this time (a Demonic winner steals in {combat.STEAL_CHANCE:.0%} of duels).")
        if loot["found"]:
            wrap_print(f"Lucky find : {winner['name']} found {loot['found']}.")
        if loot["stolen"] or loot["found"]:
            wrap_print(f"Treasures : {a['name']} now owns {len(generator.treasures_of(a))}, "
                       f"{b['name']} now owns {len(generator.treasures_of(b))}.")
    if change:
        w, l = winner, result["loser"]
        if change["kind"] == "upset":
            def rank(side, who):          # 'Familiar Face -> Sect Favorite' (or just the rank)
                before, after = change.get(side, (who["reputation"]["rank"],) * 2)
                return before if before == after else f"{before} -> {after}"
            lost = (f"-{change['loss']} ({rank('l_rank', l)})" if change["loss"]
                    else "has no reputation left to lose")
            wrap_print(f"Reputation : {w['name']} ({w['realm']}) +{change['gain']} "
                       f"({rank('w_rank', w)}); {l['name']} ({l['realm']}) {lost}"
                       f"{', a lighter blow among the righteous' if change['light'] else ''}.")
        elif change["kind"] == "same":
            wrap_print("Reputation : same realm, so nobody gains or loses reputation.")
        else:
            wrap_print("Reputation : the stronger realm won as expected, so nothing changes.")
    print(line + "\n")


def print_moves(c):
    """The 'Moves' row of a duel fighter block, wrapped under its label."""
    print_items("      Moves      : ", generator.arsenal_text(c).split(", "))
